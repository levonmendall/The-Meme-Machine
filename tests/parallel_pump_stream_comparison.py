"""Synchronized read-only Pump program stream comparison.

Compares the authenticated OnFinality WebSocket against the historically productive
Solana public WebSocket over one identical wall-clock observation interval.
No RPC writes, signing, order authority, or strategy decisions occur here.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from pathlib import Path

from websockets.sync.client import connect

from meme_machine import pump
from meme_machine.solana_read_rpc import primary_ws_url


PUBLIC_WS_URL='wss://api.mainnet-beta.solana.com'
DURATION_SECONDS=max(60,min(int(os.environ.get('MM_STREAM_COMPARE_SECONDS','300')),900))
REPORT=Path(os.environ.get('MM_STREAM_COMPARE_REPORT','pump-stream-parallel-comparison.json'))


class Collector:
    def __init__(self,name,url,start_event,deadline_box,ready_event,stop_event):
        self.name=name
        self.url=url
        self.start_event=start_event
        self.deadline_box=deadline_box
        self.ready_event=ready_event
        self.stop_event=stop_event
        self.notifications=0
        self.decoded_trades=0
        self.notification_signatures=set()
        self.trade_signatures=set()
        self.mints=set()
        self.trade_ids=set()
        self.connections=0
        self.reconnects=0
        self.subscription_errors=0
        self.parse_errors=0
        self.disconnect_kinds=Counter()
        self.first_observed_monotonic=None
        self.last_observed_monotonic=None

    def _subscribe(self,ws):
        req={'jsonrpc':'2.0','id':1,'method':'logsSubscribe','params':[
            {'mentions':[pump.PROGRAM]},{'commitment':'finalized'}]}
        ws.send(json.dumps(req))
        ack=json.loads(ws.recv(timeout=10))
        if ack.get('error') or not isinstance(ack.get('result'),int):
            self.subscription_errors+=1
            raise RuntimeError('subscription_rejected')
        return int(ack['result'])

    def run(self):
        ever_connected=False
        while not self.stop_event.is_set():
            deadline=self.deadline_box.get('deadline')
            if deadline is not None and time.monotonic()>=deadline:
                return
            try:
                with connect(
                    self.url,open_timeout=10,ping_interval=20,ping_timeout=20,
                    close_timeout=5,max_size=2_000_000,max_queue=512,
                ) as ws:
                    self._subscribe(ws)
                    if ever_connected:
                        self.reconnects+=1
                    ever_connected=True
                    self.connections+=1
                    self.ready_event.set()

                    # Both collectors subscribe first. Messages received before the
                    # common start are intentionally discarded.
                    while not self.start_event.is_set() and not self.stop_event.is_set():
                        try:
                            ws.recv(timeout=0.25)
                        except TimeoutError:
                            pass
                    if self.stop_event.is_set():
                        return

                    while not self.stop_event.is_set():
                        deadline=self.deadline_box.get('deadline')
                        if deadline is not None and time.monotonic()>=deadline:
                            return
                        try:
                            raw=ws.recv(timeout=0.5)
                        except TimeoutError:
                            continue
                        observed=time.monotonic()
                        if deadline is None or observed>=deadline:
                            return
                        try:
                            payload=json.loads(raw)
                            if payload.get('method')!='logsNotification':
                                continue
                            result=payload['params']['result']
                            context=result['context']
                            value=result['value']
                            signature=str(value['signature'])
                            slot=int(context['slot'])
                            tx={'slot':slot,'meta':{
                                'err':value.get('err'),
                                'logMessages':value.get('logs') or [],
                            }}
                            trades=pump.trade_events(tx)
                        except (ValueError,KeyError,TypeError,json.JSONDecodeError):
                            self.parse_errors+=1
                            continue

                        self.notifications+=1
                        self.notification_signatures.add(signature)
                        if self.first_observed_monotonic is None:
                            self.first_observed_monotonic=observed
                        self.last_observed_monotonic=observed
                        for trade in trades:
                            self.decoded_trades+=1
                            self.trade_signatures.add(signature)
                            mint=str(trade['mint'])
                            self.mints.add(mint)
                            self.trade_ids.add(
                                f"{signature}:{slot}:{int(trade['index'])}:{mint}")
            except Exception as exc:
                self.disconnect_kinds[type(exc).__name__]+=1
                if self.deadline_box.get('deadline') is None:
                    # Before the synchronized start, allow the peer to keep waiting
                    # while this collector retries.
                    time.sleep(1)
                else:
                    self.stop_event.wait(1)

    def public_summary(self):
        return dict(
            notifications=self.notifications,
            decoded_pump_trades=self.decoded_trades,
            unique_notification_signatures=len(self.notification_signatures),
            unique_trade_signatures=len(self.trade_signatures),
            unique_mints=len(self.mints),
            unique_trade_events=len(self.trade_ids),
            connections=self.connections,
            reconnects=self.reconnects,
            subscription_errors=self.subscription_errors,
            parse_errors=self.parse_errors,
            disconnect_kinds=dict(self.disconnect_kinds),
        )


def _overlap(a,b):
    intersection=a & b
    union=a | b
    return dict(
        intersection=len(intersection),
        union=len(union),
        jaccard=(None if not union else len(intersection)/len(union)),
        onfinality_coverage_of_public=(None if not b else len(intersection)/len(b)),
        public_coverage_of_onfinality=(None if not a else len(intersection)/len(a)),
    )


def main():
    auth_url=primary_ws_url()
    if auth_url=='wss://solana.api.onfinality.io/public-ws':
        raise SystemExit('authenticated_onfinality_ws_required')

    start_event=threading.Event()
    stop_event=threading.Event()
    deadline_box={}
    auth_ready=threading.Event()
    public_ready=threading.Event()

    auth=Collector('onfinality_authenticated',auth_url,start_event,deadline_box,auth_ready,stop_event)
    public=Collector('solana_public',PUBLIC_WS_URL,start_event,deadline_box,public_ready,stop_event)
    threads=[
        threading.Thread(target=auth.run,daemon=True),
        threading.Thread(target=public.run,daemon=True),
    ]
    for thread in threads:
        thread.start()

    start_wait=time.monotonic()
    if not auth_ready.wait(20):
        stop_event.set()
        raise SystemExit('onfinality_subscription_not_ready')
    remaining=max(0.1,20-(time.monotonic()-start_wait))
    if not public_ready.wait(remaining):
        stop_event.set()
        raise SystemExit('public_subscription_not_ready')

    started_monotonic=time.monotonic()
    started_epoch=int(time.time())
    deadline_box['deadline']=started_monotonic+DURATION_SECONDS
    start_event.set()

    while time.monotonic()<deadline_box['deadline']:
        time.sleep(min(1,max(0,deadline_box['deadline']-time.monotonic())))
    stop_event.set()
    for thread in threads:
        thread.join(timeout=8)
    ended_epoch=int(time.time())

    # Here "a" means OnFinality and "b" means historical/public.
    overlap=dict(
        notification_signatures=_overlap(
            auth.notification_signatures,public.notification_signatures),
        trade_signatures=_overlap(auth.trade_signatures,public.trade_signatures),
        mints=_overlap(auth.mints,public.mints),
        trade_events=_overlap(auth.trade_ids,public.trade_ids),
    )
    public_only_mints=sorted(public.mints-auth.mints)[:25]
    onfinality_only_mints=sorted(auth.mints-public.mints)[:25]
    public_only_trade_signatures=sorted(public.trade_signatures-auth.trade_signatures)[:25]
    onfinality_only_trade_signatures=sorted(auth.trade_signatures-public.trade_signatures)[:25]

    report=dict(
        kind='pump_parallel_stream_comparison_v1',
        success=True,
        read_only=True,
        qualification_authority=False,
        order_authority=False,
        duration_seconds=DURATION_SECONDS,
        started=started_epoch,
        ended=ended_epoch,
        endpoints=dict(
            onfinality='authenticated_secret_redacted',
            public=PUBLIC_WS_URL,
        ),
        onfinality=auth.public_summary(),
        public=public.public_summary(),
        overlap=overlap,
        samples=dict(
            public_only_mints=public_only_mints,
            onfinality_only_mints=onfinality_only_mints,
            public_only_trade_signatures=public_only_trade_signatures,
            onfinality_only_trade_signatures=onfinality_only_trade_signatures,
        ),
    )

    # Fail closed only on comparison validity, not because one provider is worse.
    if auth.connections<1 or public.connections<1:
        report['success']=False
        report['limitation']='one_or_more_streams_never_subscribed'
    elif auth.notifications==0 and public.notifications==0:
        report['success']=False
        report['limitation']='no_notifications_from_either_stream'
    else:
        report['limitation']=None

    REPORT.write_text(json.dumps(report,sort_keys=True,indent=2))
    print(json.dumps(report,sort_keys=True))
    if not report['success']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
