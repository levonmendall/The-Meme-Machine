"""Fatal owned-child handoff; libraries never terminate their caller process."""
import json
import math
import threading
import time


class NativeOwnerDrainFailure(RuntimeError):
    """The original drain fence elapsed with source/thread owners still alive.

    The fixed child entry must hand this to process termination. Retained owners
    must not be closed concurrently or passed through asyncio.Runner.close().
    """
    def __init__(self,receipt):
        super().__init__('isolated_native_shutdown_incomplete')
        self.receipt=json.loads(json.dumps(receipt,allow_nan=False))
        self._retained=[]

    def retain(self,*owners):
        self._retained.extend(owners)


class NativeLifecycleObservation:
    """Bounded causal observations only; never a stop or ownership authority."""
    _EVENTS=frozenset(('BOOTSTRAP','SOURCE_READY','WORKER_STARTED','WORKER_FAILED',
        'WORKER_ENDED','SOURCE_ENDED','STOP_REQUESTED','CHANNEL_ABORT_REQUESTED','STREAM_CLOSED'))
    _ORIGINS=frozenset(('ENTRY_BOOTSTRAP','ENTRY_SIGNAL','ENTRY_FINALLY',
        'SOURCE_LIFECYCLE','SOURCE_WORKER','CHANNEL_ABORT','NATIVE_STREAM'))
    _REASONS=frozenset(('SIGNAL_TERM','SIGNAL_INT','LIFECYCLE_FAILURE',
        'LIFECYCLE_WINDOW','LIFECYCLE_EXTERNAL_STOP','ENTRY_CLEANUP',
        'TRANSPORT_ERROR','NORMAL_CLOSE','EOF','PARENT_FAILED','OWNER_CLOSE'))

    def __init__(self,*,clock=time.monotonic):
        self._clock=clock;self._lock=threading.RLock();self._events=[]
        self._seen=set();self._first_stop=None;self._first_close=None
        self._lost=False;self._last=None;self._dropped=0

    def record(self,event,origin,*,worker=None,reason=None,prior_local=None,prior_global=None,stream_kind=None):
        # Observation failure must never change the original stop/close/drain.
        try:
            if (event not in self._EVENTS or origin not in self._ORIGINS
                    or worker not in (None,'pump','pons','sizing')
                    or stream_kind not in (None,'yellowstone','solana_websocket','robinhood_sequencer')
                    or reason is not None and reason not in self._REASONS
                    or prior_local is not None and type(prior_local) is not bool
                    or prior_global is not None and type(prior_global) is not bool):
                raise ValueError('native_lifecycle_observation_shape')
            with self._lock:
                key=(event,origin,worker,stream_kind)
                if key in self._seen:return
                now=self._clock()
                if (type(now) not in (int,float) or not math.isfinite(now) or not 0<=now<2**53
                        or self._last is not None and now<self._last):
                    raise ValueError('native_lifecycle_observation_clock')
                row=dict(event=event,origin=origin,monotonic=now)
                for name,value in (('worker',worker),('stream_kind',stream_kind),('reason',reason),
                        ('prior_local',prior_local),('prior_global',prior_global)):
                    if value is not None:row[name]=value
                self._last=now;self._seen.add(key)
                if event=='STOP_REQUESTED' and self._first_stop is None:
                    self._first_stop=dict(row)
                if event=='CHANNEL_ABORT_REQUESTED' and self._first_close is None:
                    self._first_close=dict(row)
                if len(self._events)<16:self._events.append(row)
                else:self._dropped+=1
        except BaseException:self._lost=True

    def snapshot(self):
        with self._lock:
            value=dict(schema='native-lifecycle-observation-v1',events=[dict(row) for row in self._events],
                first_stop=None if self._first_stop is None else dict(self._first_stop),
                first_shared_abort=None if self._first_close is None else dict(self._first_close),
                lost=self._lost,dropped_events=self._dropped)
        if len(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())>4096:
            return dict(schema='native-lifecycle-observation-v1',events=[],first_stop=None,
                first_shared_abort=None,lost=True,dropped_events=self._dropped)
        return value


def observe_lifecycle(observer,*args,**fields):
    if observer is None:return
    try:observer.record(*args,**fields)
    except BaseException:
        try:observer._lost=True
        except BaseException:pass


def lifecycle_snapshot(observer):
    try:return observer.snapshot()
    except BaseException:
        return dict(schema='native-lifecycle-observation-v1',events=[],first_stop=None,
            first_shared_abort=None,lost=True,dropped_events=0)
