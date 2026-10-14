"""Process-local bounded health; no execution or permission authority."""
import os,threading,time
from collections import deque
from contextlib import contextmanager
lock=threading.Lock()
state=dict(phase='RECONCILING',reconciled=False)
_operations=[]
_completed=deque(maxlen=8)
_signal=None

def cancellation_signal(signum):
    """Signal-handler facts only: no lock, filesystem or database operation."""
    global _signal
    try:
        _signal=dict(signal=int(signum),at=time.time(),monotonic=time.monotonic(),
                     pid=os.getpid(),native_thread_id=threading.get_native_id())
    except Exception:pass

@contextmanager
def operation(identity):
    """Fixed startup identifiers; descriptive facts never change readiness."""
    if not isinstance(identity,str) or not identity.startswith('pump.') or len(identity)>80:
        yield;return
    try:
        row=dict(operation=identity,at=time.time(),monotonic=time.monotonic(),
                 pid=os.getpid(),native_thread_id=threading.get_native_id(),state='ACTIVE')
        with lock:
            recorded=len(_operations)<8
            if recorded:_operations.append(row)
    except Exception:
        yield;return
    outcome='COMPLETE';error_type=None
    try:yield
    except BaseException as error:
        from .stop import Shutdown
        outcome='CANCELLED' if isinstance(error,Shutdown) else 'ERROR'
        error_type=type(error).__name__[:80]
        raise
    finally:
        try:
            done=dict(row,state=outcome,completed_at=time.time(),
                      elapsed_seconds=max(0,time.monotonic()-row['monotonic']))
            if error_type:done['error_type']=error_type
            with lock:
                if recorded:_operations.remove(row)
                _completed.append(done)
        except Exception:pass

def update(phase,**fields):
    with lock:
        state.update(phase=phase,progress_at=time.time(),**fields)
def snapshot():
    with lock:
        value=dict(state)
        if _operations:value['native_operation']=dict(_operations[-1])
        if _completed:value['native_recent_operations']=[dict(row) for row in _completed]
    if _signal is not None:value['cancellation_signal']=dict(_signal)
    return value
