"""Bounded physical workers for the existing durable Current controllers.

Only the native five-second idle wait yields. Connections, journal authority,
provider sessions and controller generators remain on their original thread.
There is no position-count admission rule or additional durable state here.
"""
from concurrent.futures import Future,ThreadPoolExecutor
from contextvars import copy_context
import heapq
import threading
import time

from . import BoundaryError


class LifecyclePool:
    def __init__(self,*,max_workers=8,clock=None,wait_for_due=None):
        if not 1<=max_workers<=8:raise ValueError('current_physical_worker_limit')
        self.max_workers=max_workers;self.clock=clock or time.monotonic;self.lock=threading.Condition()
        self.wait_for_due=wait_for_due or (lambda seconds:self.lock.wait(min(.05,seconds)))
        self.workers=[dict(queue=[],owners=0,running=False) for _ in range(max_workers)]
        self.executor=ThreadPoolExecutor(max_workers=max_workers,thread_name_prefix='pons-current')
        self.started=set();self.sequence=0;self.entries=0;self.closing=False
        self.counts=dict(owners=0,peak_owners=0,active_physical_workers=0,peak_physical_workers=0,
            protection_turns=0,late_protection_turns=0,max_queue_age_seconds=0.)

    def entry_capacity_available(self):
        with self.lock:
            # Sleeping held owners do not consume entry-processing tickets.
            # Due protective work is always dispatched before a queued entry.
            return not self.closing and self.entries<self.max_workers

    def submit(self,function,*args,**kwargs):
        from .pons_selective_paper import run_lifecycle,run_lifecycle_steps
        from .pons_selective_recovery import _resume_receipt,_resume_receipt_steps
        entry=function is run_lifecycle
        if entry:factory=run_lifecycle_steps
        elif function is _resume_receipt:factory=_resume_receipt_steps
        else:raise ValueError('current_native_controller_required')
        with self.lock:
            if self.closing:raise RuntimeError('current_workers_closed')
            if entry and self.entries>=self.max_workers:
                raise BoundaryError('current_entry_workers_temporarily_busy')
            index=min(range(self.max_workers),key=lambda i:(self.workers[i]['owners'],i))
            future=Future();self.sequence+=1
            owner=dict(future=future,factory=factory,args=args,kwargs=kwargs,iterator=None,
                context=None,entry=entry,sequence=self.sequence,due=self.clock(),pending_exit=False)
            self.workers[index]['owners']+=1;self.entries+=int(entry)
            self.counts['owners']+=1
            self.counts['peak_owners']=max(self.counts['peak_owners'],self.counts['owners'])
            self._enqueue(index,owner)
            if index not in self.started:
                self.started.add(index);self.executor.submit(self._worker,index)
            self.lock.notify_all()
            return future

    def _enqueue(self,index,owner):
        heapq.heappush(self.workers[index]['queue'],
            (owner['due'],0 if owner['pending_exit'] else 1,owner['sequence'],owner))

    def _worker(self,index):
        worker=self.workers[index]
        while True:
            with self.lock:
                while not worker['queue']:
                    if self.closing:return
                    self.lock.wait(.05)
                due,_,_,owner=worker['queue'][0];now=self.clock()
                if not self.closing and due>now:
                    self.wait_for_due(due-now);continue
                # Among ready work, protection precedes entry; original release
                # times remain unchanged. Sequence breaks equal-deadline ties.
                ready=[]
                while worker['queue'] and (self.closing or worker['queue'][0][0]<=now):
                    ready.append(heapq.heappop(worker['queue']))
                chosen=min(range(len(ready)),key=lambda j:(ready[j][3]['entry'],
                    ready[j][0],ready[j][1],ready[j][2]))
                _,_,_,owner=ready.pop(chosen)
                for row in ready:heapq.heappush(worker['queue'],row)
                age=max(0.,now-owner['due'])
                self.counts['max_queue_age_seconds']=max(self.counts['max_queue_age_seconds'],age)
                if owner['iterator'] is not None:
                    self.counts['protection_turns']+=int(not self.closing)
                    self.counts['late_protection_turns']+=int(not self.closing and age>1e-6)
                worker['running']=True;self.counts['active_physical_workers']+=1
                self.counts['peak_physical_workers']=max(self.counts['peak_physical_workers'],
                    self.counts['active_physical_workers'])
            done=False;value=None;error=None
            try:
                if owner['iterator'] is None:
                    if not owner['future'].set_running_or_notify_cancel():done=True
                    else:
                        # ContextVar history/provider attribution is isolated
                        # between controllers sharing this physical thread.
                        owner['context']=copy_context()
                        owner['iterator']=owner['context'].run(owner['factory'],*owner['args'],**owner['kwargs'])
                        value=owner['context'].run(next,owner['iterator'])
                else:
                    value=owner['context'].run(owner['iterator'].send,'handoff' if self.closing else None)
                if not done and (not isinstance(value,dict) or value.get('kind')!='monitor_wait'
                        or value.get('seconds')!=5):
                    raise BoundaryError('current_native_monitor_schedule_changed')
            except StopIteration as result:done=True;value=result.value
            except BaseException as exc:done=True;error=exc
            finally:
                if done and owner['iterator'] is not None:
                    try:owner['context'].run(owner['iterator'].close)
                    except BaseException as exc:
                        if error is None:error=exc
                with self.lock:
                    worker['running']=False;self.counts['active_physical_workers']-=1
                    if owner['entry']:
                        owner['entry']=False;self.entries-=1
                    if done:
                        worker['owners']-=1;self.counts['owners']-=1
                        if not owner['future'].cancelled():
                            if error is not None:owner['future'].set_exception(error)
                            else:owner['future'].set_result(value)
                    else:
                        # The native controller's original wait begins after
                        # its previous turn, exactly as in the synchronous path.
                        owner['due']=self.clock()+value['seconds']
                        owner['pending_exit']=bool(value.get('pending_exit'))
                        self._enqueue(index,owner)
                    self.lock.notify_all()

    def telemetry(self):
        with self.lock:return dict(self.counts,physical_worker_limit=self.max_workers,
            entry_tasks=self.entries,position_count_limit=None)

    def request_handoff(self):
        with self.lock:self.closing=True;self.lock.notify_all()

    def shutdown(self,wait=True,*,cancel_futures=False):
        self.request_handoff()
        self.executor.shutdown(wait=wait,cancel_futures=False)

    def __enter__(self):return self
    def __exit__(self,*exc):self.shutdown()
