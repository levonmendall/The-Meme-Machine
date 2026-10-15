"""Fixed exclusive candidate-commit costs in the existing source health view.

The canonical owner alone updates these preallocated numeric rows. The event
loop can copy them for health publication without a changing owner-side key set.
No evidence, SQL, authority or scheduling decision depends on these counters.
"""
from contextlib import contextmanager,nullcontext
import math
import os
import threading
from time import monotonic,thread_time

PHASES=('validate','ingest_setup','rolling_adopt','economic_store',
        'delivery_outbox','coverage_receipt','batch_commit')
_FIELDS=('calls','failed_calls','unmeasured_calls','runnable_measured_calls',
         'runnable_unavailable_calls',*(name+'_'+kind+'_microseconds'
         for name in ('wall_seconds','cpu_seconds','runnable_wait_seconds')
         for kind in ('total','peak')))


def runnable_snapshot():
    """The same kernel counter as owner health, for the actual calling TID.

    Two bounded reads per coarse phase, never per economic record or SQL call.
    Unsupported/missing kernel accounting remains unavailable, never zero.
    """
    try:
        with open('/proc/thread-self/schedstat','rb') as source:raw=source.read(128)
        values=raw.split()
        if len(values)!=3:return None
        runtime,waiting,slices=(int(value) for value in values)
        if min(runtime,waiting,slices)<0:return None
        return os.getpid(),threading.get_native_id(),waiting
    except (OSError,ValueError):return None


class CandidatePhases:
    def __init__(self,pipeline,*,wall=monotonic,cpu=thread_time,runnable=runnable_snapshot):
        self.wall=wall;self.cpu=cpu;self.runnable=runnable
        self.rows={name:pipeline.setdefault('candidate_phase:'+name,
            {field:0 for field in _FIELDS}) for name in PHASES}
        for name in ('bulk_calls','bulk_records','scalar_calls','scalar_records'):
            self.rows['economic_store'].setdefault(name,0)

    def storage(self,bulk,records):
        """Executed storage path, not a committed-event/coverage counter."""
        try:
            row=self.rows['economic_store'];prefix='bulk' if bulk else 'scalar'
            row[prefix+'_calls']+=1;row[prefix+'_records']+=records
        except BaseException:
            pass # Optional telemetry must not change the original operation.

    def _sample(self):
        wall=self.wall();cpu=self.cpu()
        if any(type(value) not in (int,float) or not math.isfinite(value) for value in (wall,cpu)):
            return None
        try:runnable=self.runnable()
        except BaseException:runnable=None
        return wall,cpu,runnable

    @contextmanager
    def phase(self,name):
        if name not in self.rows:raise ValueError('candidate_phase_identity')
        row=self.rows[name];started=None;failed=False
        try:started=self._sample()
        except BaseException:pass
        try:yield
        except BaseException:
            failed=True
            raise
        finally:
            # A recorder failure cannot replace the original application error
            # or alter transaction cleanup. Missing timing stays explicit.
            try:
                row['calls']+=1;row['failed_calls']+=int(failed)
                try:ended=self._sample()
                except BaseException:ended=None
                if started is None or ended is None or ended[0]<started[0] or ended[1]<started[1]:
                    row['unmeasured_calls']+=1
                else:
                    for metric,value in (('wall_seconds',ended[0]-started[0]),
                                         ('cpu_seconds',ended[1]-started[1])):
                        micros=int(value*1_000_000)
                        row[metric+'_total_microseconds']+=micros
                        row[metric+'_peak_microseconds']=max(row[metric+'_peak_microseconds'],micros)
                a=None if started is None else started[2];b=None if ended is None else ended[2]
                if (isinstance(a,tuple) and isinstance(b,tuple) and len(a)==len(b)==3
                        and a[:2]==b[:2] and type(a[2]) is int and type(b[2]) is int and b[2]>=a[2]):
                    micros=(b[2]-a[2])//1000
                    row['runnable_measured_calls']+=1
                    row['runnable_wait_seconds_total_microseconds']+=micros
                    row['runnable_wait_seconds_peak_microseconds']=max(row['runnable_wait_seconds_peak_microseconds'],micros)
                else:row['runnable_unavailable_calls']+=1
            except BaseException:
                try:row['unmeasured_calls']+=1
                except BaseException:pass

    def transaction_exit(self,manager):
        """Time only the original outer context exit, including rollback.

        The transaction body has exclusive subphases; it is never included in
        batch_commit. Delegate the original context's exception/suppression
        contract unchanged. Inner source SAVEPOINT boundaries are unmeasured.
        """
        owner=self
        class Exit:
            def __enter__(self):return manager.__enter__()
            def __exit__(self,*error):
                with owner.phase('batch_commit'):return manager.__exit__(*error)
        return Exit()


def phase(timing,name):
    return nullcontext() if timing is None else timing.phase(name)
