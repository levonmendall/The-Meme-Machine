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
        self._lock=threading.Lock()
        self.sequence=0
        self.warm_since=None
        self.loss_until=0
        self.connected=False
        self.notifications=0
        self.trade_events=0
        self.gaps=0
        self.capacity_losses=0
        self.parse_failures=0
        self.last_slot=None

    def begin(self, now=None):
        now=int(self.clock() if now is None else now)
        with self._lock:
            self._events.clear()
            self.warm_since=now
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
        accepted=0
        with self._lock:
            self.notifications += 1
            self.last_slot=max(self.last_slot or 0,int(context['slot']))
            self._prune_locked(now)
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
                trade_events=self.trade_events,gaps=self.gaps,capacity_losses=self.capacity_losses,
                parse_failures=self.parse_failures,last_slot=self.last_slot,
                loss_until=self.loss_until,max_events=self.max_events,
                retention_seconds=self.retention,event_id_version=EVENT_ID_VERSION)


class PumpLogStream:
    """One finalized logsSubscribe connection; any disconnect resets continuity."""
    def __init__(self, rpc_url, tape, clock=time.time):
        self.url=websocket_url(rpc_url)
        self.tape=tape
        self.clock=clock
        self.subscription=None
        self.error_kind=None

    def run(self, stop_event, ready_event=None):
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
                self.tape.begin(int(self.clock()))
                if ready_event is not None:
                    ready_event.set()
                while not stop_event.is_set():
                    try:
                        message=websocket.recv(timeout=1)
                    except TimeoutError:
                        continue
                    payload=json.loads(message)
                    try:
                        self.tape.ingest_notification(payload,int(self.clock()))
                    except (ValueError,KeyError,TypeError):
                        self.error_kind='parse_failure'
                        self.tape.gap(int(self.clock()),parse=True)
                        return
        except Exception as exc:
            # Never emit URLs or provider response bodies into diagnostics.
            self.error_kind=type(exc).__name__
            self.tape.gap(int(self.clock()))
            if ready_event is not None:
                ready_event.set()
        finally:
            if stop_event.is_set():
                self.tape.stop()
