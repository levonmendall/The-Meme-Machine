"""Process-local bounded health; no execution or permission authority."""
import os,re,sys,threading,time
from collections import deque
from contextlib import contextmanager
lock=threading.Lock()
state=dict(phase='RECONCILING',reconciled=False)
_operations=[]
_completed=deque(maxlen=8)
_signal=None

_FAILURE_CLASSES=frozenset(('Exception','RuntimeError','FileNotFoundError','PermissionError',
    'KeyError','ValueError','TypeError','AssertionError','ImportError','ModuleNotFoundError',
    'OSError','TimeoutError','OperationalError','IntegrityError','DatabaseError',
    'EvidenceUnavailable','EvidenceConflict','StorageGuardError','ValuationUnavailable',
    'NameError','AttributeError','IndexError','ProgrammingError','InterfaceError','DataError',
    'ZeroDivisionError','OverflowError'))


def native_failure(error,lane):
    """Retain bounded source identities before a native exception exits.

    The diagnostic unit deliberately has no stderr channel. Never retain an
    exception message, SQL, frame locals, provider payload or arbitrary path.
    SQLite's existing separately bounded annotation contains owned metadata;
    the public collector independently selects its typed fields.
    """
    from .sqlite_failure import payload
    def detail(exc):
        kind=type(exc).__name__
        row=dict(exception_class=kind if kind in _FAILURE_CLASSES else 'UNRECOGNIZED_EXCEPTION_TYPE',
                 frames=[],traceback_truncated=False)
        trace=exc.__traceback__;scanned=0
        while trace is not None and scanned<32:
            module=trace.tb_frame.f_globals.get('__name__','');function=trace.tb_frame.f_code.co_name
            if (isinstance(module,str) and len(module)<=160
                    and re.fullmatch(r'meme_machine(?:\.[A-Za-z_][A-Za-z0-9_]*)+',module)
                    and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}',function)):
                row['frames'].append(dict(module=module,function=function,line=trace.tb_lineno))
            trace=trace.tb_next;scanned+=1
        row['traceback_truncated']=trace is not None or len(row['frames'])>8
        row['frames']=row['frames'][-8:]
        return row
    value=dict(detail(error),version=1,lane=lane,pid=os.getpid(),
        process_instance=os.environ.get('MM_LANE_PROCESS_INSTANCE'),
        native_thread_id=threading.get_native_id(),at=time.time(),monotonic=time.monotonic(),
        traceback_scope='ALLOWLISTED_SOURCE_FRAMES_ONLY',causes=[])
    current=error;seen=set()
    for index in range(4):
        if id(current) in seen:break
        seen.add(id(current))
        if index:value['causes'].append(detail(current))
        diagnostic=payload(current)
        if diagnostic is not None and 'sqlite_failure' not in value:
            value.update(sqlite_failure=diagnostic,sqlite_failure_cause_index=index)
        current=current.__cause__ or (None if current.__suppress_context__ else current.__context__)
        if current is None:break
    return value

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
            not (identity.startswith('pump.') or identity in ('pons.shared_capital_restore','pons.cohort_recovery','pons.candidate_restore'))):
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

def thread_inventory():
    """Bounded descriptive thread identities; no frames or native-work authority."""
    row=dict(state='UNAVAILABLE',pid='UNAVAILABLE',collected_at='UNAVAILABLE',
             collected_at_monotonic='UNAVAILABLE',limit=16,total='UNAVAILABLE',
             truncated='UNAVAILABLE',missing_native_thread_ids='UNAVAILABLE',threads=[])
    try:
        row.update(pid=os.getpid(),collected_at=time.time(),collected_at_monotonic=time.monotonic())
        main=threading.main_thread();threads=threading.enumerate()
        def identity(thread):
            tid=thread.native_id
            return tid if type(tid) is int and tid>0 else None
        threads.sort(key=lambda thread:(thread is not main,identity(thread) or float('inf')))
        retained=[]
        for thread in threads[:16]:
            name=thread.name
            role=('main' if thread is main else 'health' if name=='health' else
                  'survivor' if name=='survivor_0' else
                  'pons-hydration' if name=='pons-hydration_0' else
                  'pons-discovery' if name in ('pons-discovery_0','pons-discovery_1') else
                  'pons-current' if re.fullmatch(r'pons-current_[0-7]',name) else
                  'pons-current-entry' if re.fullmatch(r'pons-current-entry_[0-7]',name) else
                  'pons-usd' if name=='pons-usd_0' else
                  'pons-scale-history' if name=='pons-scale-history_0' else 'UNAVAILABLE')
            retained.append(dict(native_thread_id=identity(thread) or 'UNAVAILABLE',role=role))
        row.update(state='SAMPLED',total=len(threads),truncated=len(threads)>16,
                   missing_native_thread_ids=sum(identity(thread) is None for thread in threads),
                   threads=retained)
    except Exception:
        row.update(state='UNAVAILABLE',threads=[])
    return row

def snapshot():
    with lock:
        value=dict(state)
        if _operations:value['native_operation']=dict(_operations[-1])
        if _completed:value['native_recent_operations']=[dict(row) for row in _completed]
    if _signal is not None:value['cancellation_signal']=dict(_signal)
    value['native_threads']=thread_inventory()
    from . import operation_costs
    if operation_costs.enabled():value['operation_costs']=operation_costs.snapshot()
    return value
