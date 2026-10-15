"""Process-local bounded health; no execution or permission authority."""
import os,re,sys,threading,time
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

def cancellation_stack():
    """One optional health-thread probe; never call from the signal handler.

    Retain only owned Python call identities, not source, filenames, frame
    locals, SQL, or a claim about the C call/lock beneath a Python frame.
    """
    row=dict(state='UNAVAILABLE',reason='probe_failed',at=time.time(),
             monotonic=time.monotonic(),pid=os.getpid(),
             reporter_native_thread_id=threading.get_native_id(),
             target_native_thread_id=None,target_python_thread_id=None,
             frames=[],frames_truncated=False)
    frame=None
    try:
        main=threading.main_thread()
        row.update(target_native_thread_id=main.native_id,target_python_thread_id=main.ident)
        if main.ident is None:
            row['reason']='main_thread_unavailable';return row
        frame=sys._current_frames().get(main.ident)
        if frame is None:
            row['reason']='main_thread_frame_missing';return row
        scanned=0
        while frame is not None and scanned<128 and len(row['frames'])<8:
            module=frame.f_globals.get('__name__');function=frame.f_code.co_name
            if (isinstance(module,str) and len(module)<=160 and
                    re.fullmatch(r'meme_machine(?:\.[A-Za-z_][A-Za-z0-9_]*)+',module) and
                    isinstance(function,str) and
                    re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}',function)):
                row['frames'].append(dict(module=module,function=function,line=frame.f_lineno))
            scanned+=1;frame=frame.f_back
        row['frames_truncated']=frame is not None
        row.update(state='CAPTURED' if row['frames'] else 'UNAVAILABLE',
                   reason='owned_python_frames' if row['frames'] else 'no_owned_frames')
    except Exception:
        row.update(state='UNAVAILABLE',reason='probe_failed',frames=[])
    finally:
        # Do not retain live frame objects (and their application locals).
        del frame
    return row

@contextmanager
def operation(identity):
    """Fixed startup identifiers; descriptive facts never change readiness."""
    if (not isinstance(identity,str) or len(identity)>80 or
            not (identity.startswith('pump.') or identity=='pons.shared_capital_restore')):
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
