"""Bounded finalized Pump.fun log stream for prospective point-in-time evidence."""
from collections import deque
import json
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from websockets.sync.client import connect

from . import pump

WINDOW_SECONDS = 60
RETENTION_SECONDS = 75
MAX_EVENTS = 50_000
MAX_CREATIONS = 5_000
EVENT_ID_VERSION = 'sig-slot-log-mint-v2'


def event_identity(signature, slot, event):
    """Stable live economic-event identity; resists provider signature reuse."""
    signature=str(signature or '').strip()
    mint=str((event or {}).get('mint') or '').strip()
    index=int((event or {})['index'])
    slot=int(slot)
    if not signature or not mint or slot < 0 or index < 0:
        raise ValueError('invalid_live_event_identity')
    return f'{signature}:{slot}:{index}:{mint}'


def websocket_url(http_url):
    parts=urlsplit(http_url)
    if parts.scheme != 'https' or not parts.netloc:
        raise ValueError('HTTPS RPC required')
    return urlunsplit(('wss',parts.netloc,parts.path,parts.query,parts.fragment))


class PumpTape:
    """In-memory finalized trade tape with explicit continuity/capacity truth."""
    def __init__(self, retention=RETENTION_SECONDS, max_events=MAX_EVENTS, clock=time.time):
        if retention < WINDOW_SECONDS or max_events < 1:
            raise ValueError('invalid tape bounds')
        self.retention,self.max_events,self.clock=retention,max_events,clock
        self._events=deque()
        self._creates={}
        self._lock=threading.Lock()
        self.sequence=0
        self.warm_since=None
        self.loss_until=0
        self.connected=False
        self.notifications=0
        self.trade_events=0
        self.creation_events=0
        self.creation_capacity_losses=0
        self.gaps=0
        self.capacity_losses=0
        self.parse_failures=0
        self.last_slot=None

    def begin(self, now=None, preserve_loss=False):
        now=int(self.clock() if now is None else now)
        with self._lock:
            self._events.clear()
            self._creates.clear()
            self.warm_since=now
            if not preserve_loss:
                self.loss_until=0
            self.connected=True
            self.last_slot=None

    def gap(self, now=None, parse=False):
        now=int(self.clock() if now is None else now)
        with self._lock:
            self.gaps += 1
            if parse:
                self.parse_failures += 1
            self._events.clear()
            self._creates.clear()
            self.warm_since=None
            self.loss_until=max(self.loss_until,now+WINDOW_SECONDS)
            self.connected=False
            self.last_slot=None

    def stop(self):
        with self._lock:
            self.connected=False

    def _prune_locked(self, now):
        cutoff=now-self.retention
        while self._events and self._events[0][1]['market_time'] < cutoff:
            self._events.popleft()

    def ingest_notification(self, payload, available_time=None):
        now=int(self.clock() if available_time is None else available_time)
        if payload.get('method') != 'logsNotification':
            return 0
        result=payload['params']['result']
        context=result['context']
        value=result['value']
        signature=value['signature']
        tx={'slot':int(context['slot']),
            'meta':{'err':value.get('err'),'logMessages':value.get('logs') or []}}
        decoded=pump.trade_events(tx)
        creations=pump.create_events(tx)
        accepted=0
        with self._lock:
            self.notifications += 1
            self.last_slot=max(self.last_slot or 0,int(context['slot']))
            self._prune_locked(now)
            for event in creations:
                if int(event['market_time']) > now:
                    self.loss_until=max(self.loss_until,now+WINDOW_SECONDS)
                    continue
                event=dict(event)
                event.update(
                    id=f"{signature}:{int(context['slot'])}:{int(event['index'])}:{event['mint']}:create",
                    available_time=now,
                )
                if event['mint'] not in self._creates and len(self._creates)>=MAX_CREATIONS:
                    self._creates.pop(next(iter(self._creates)))
                    self.creation_capacity_losses += 1
                self._creates[event['mint']]=event
                self.creation_events += 1
            for event in decoded:
                # A future-dated chain timestamp cannot become point-in-time evidence.
                # Treat it as a missing observation window instead of rewriting time.
                if int(event['market_time']) > now:
                    self.loss_until=max(self.loss_until,now+WINDOW_SECONDS)
                    continue
                event=dict(event)
                event.update(id=event_identity(signature,context['slot'],event),available_time=now)
                self.sequence += 1
                if len(self._events) >= self.max_events:
                    self._events.popleft()
                    self.capacity_losses += 1
                    self.loss_until=max(self.loss_until,now+WINDOW_SECONDS)
                self._events.append((self.sequence,event))
                self.trade_events += 1
                accepted += 1
        return accepted

    def covered(self, now=None):
        now=int(self.clock() if now is None else now)
        with self._lock:
            return bool(self.connected and self.warm_since is not None and
                        now-self.warm_since >= WINDOW_SECONDS and now >= self.loss_until)

    def latest_sequence(self):
        with self._lock:
            return self.sequence

    def events_since(self, sequence):
        with self._lock:
            rows=[dict(event) for seq,event in self._events if seq>sequence]
            return rows,self.sequence

    def creation(self, mint):
        with self._lock:
            value=self._creates.get(mint)
            return None if value is None else dict(value)

    def window(self, mint, now=None, max_slot=None):
        now=int(self.clock() if now is None else now)
        cutoff=now-WINDOW_SECONDS
        with self._lock:
            return [dict(event) for _,event in self._events
                    if event['mint']==mint and cutoff <= event['market_time'] <= now
                    and (max_slot is None or event['slot'] <= max_slot)]

    def status(self, now=None):
        now=int(self.clock() if now is None else now)
        with self._lock:
            return dict(connected=self.connected,covered=bool(
                self.connected and self.warm_since is not None and
                now-self.warm_since >= WINDOW_SECONDS and now >= self.loss_until),
                warm_seconds=0 if self.warm_since is None else max(0,now-self.warm_since),
                retained_events=len(self._events),notifications=self.notifications,
                trade_events=self.trade_events,creation_events=self.creation_events,
                creation_records=len(self._creates),creation_capacity_losses=self.creation_capacity_losses,
                gaps=self.gaps,capacity_losses=self.capacity_losses,
                parse_failures=self.parse_failures,last_slot=self.last_slot,
                loss_until=self.loss_until,max_events=self.max_events,
                retention_seconds=self.retention,event_id_version=EVENT_ID_VERSION)


class _StreamParseFailure(RuntimeError):
    pass


class PumpLogStream:
    """Finalized logsSubscribe stream with fail-closed reconnect + full rewarm."""
    def __init__(self, rpc_url, tape, clock=time.time, ws_url=None, reconnect_delay=2.0):
        self.url=str(ws_url or websocket_url(rpc_url))
        parts=urlsplit(self.url)
        approved_hosts={'api.mainnet-beta.solana.com'}
        if parts.scheme != 'wss' or parts.hostname not in approved_hosts:
            raise ValueError('public Solana WSS endpoint required')
        self.tape=tape
        self.clock=clock
        self.reconnect_delay=max(0.0,float(reconnect_delay))
        self.subscription=None
        # error_kind is terminal/startup-facing only. Transient disconnects are
        # recorded separately so callers can remain fail-closed while the tape rewarms.
        self.error_kind=None
        self.last_error_kind=None
        self.connections=0
        self.reconnects=0

    def run(self, stop_event, ready_event=None):
        ever_ready=False
        while not stop_event.is_set():
            try:
                with connect(self.url,open_timeout=10,ping_interval=20,ping_timeout=20,
                             close_timeout=5,max_size=2_000_000,max_queue=128) as websocket:
                    request={'jsonrpc':'2.0','id':1,'method':'logsSubscribe','params':[
                        {'mentions':[pump.PROGRAM]},{'commitment':'finalized'}]}
                    websocket.send(json.dumps(request))
                    ack=json.loads(websocket.recv(timeout=10))
                    if ack.get('error') or not isinstance(ack.get('result'),int):
                        raise RuntimeError('subscription_rejected')
                    self.subscription=ack['result']
                    if ever_ready:
                        self.reconnects += 1
                    self.connections += 1
                    self.error_kind=None
                    self.tape.begin(int(self.clock()),preserve_loss=ever_ready)
                    ever_ready=True
                    if ready_event is not None and not ready_event.is_set():
                        ready_event.set()
                    while not stop_event.is_set():
                        try:
                            message=websocket.recv(timeout=1)
                        except TimeoutError:
                            continue
                        payload=json.loads(message)
                        try:
                            self.tape.ingest_notification(payload,int(self.clock()))
                        except (ValueError,KeyError,TypeError) as exc:
                            raise _StreamParseFailure() from exc
            except Exception as exc:
                if stop_event.is_set():
                    break
                kind='parse_failure' if isinstance(exc,_StreamParseFailure) else type(exc).__name__
                self.last_error_kind=kind
                # Every disconnect destroys evidence continuity. Reconnect is allowed,
                # but no candidate can qualify until a complete fresh 60s window exists.
                self.tape.gap(int(self.clock()),parse=(kind=='parse_failure'))
                self.subscription=None
                self.error_kind=None
                stop_event.wait(self.reconnect_delay)
        self.tape.stop()
