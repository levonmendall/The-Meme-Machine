"""Reserve one existing process worker for native preparation.

Maintenance and opportunistic archive decoding share the other worker. Physical
occupancy follows the executor future, including when an async waiter cancels.
No database, provider, deadline or evidence authority lives in this facade.
"""
from concurrent.futures import Future,wait as wait_futures
import threading


class ArchivePreparationTicket:
    """Advisory cancellation only, bounded by existing in-flight RPC jobs.

    The owner sets a thread-safe flag immediately on urgency tightening. Only
    its queued event-loop callback touches async wakeups. False invalidation,
    including rolled-back work, merely restores the original owner decoder.
    """
    def __init__(self,priority,deadline,loop,wakeup):
        import asyncio
        self.claim=(priority,deadline);self.loop=loop;self.wakeup=wakeup
        self.invalid=threading.Event();self.changed=asyncio.Event()
    def tighten(self,priority,deadline):
        if (priority>=self.claim[0] and deadline>=self.claim[1]) or self.invalid.is_set():return
        self.invalid.set()
        try:self.loop.call_soon_threadsafe(self._notify)
        except Exception:pass # Advisory failure cannot replace the owner result.
    def _notify(self):
        self.changed.set();self.wakeup.notify()


class _NativePreparation:
    def __init__(self,pool):self.pool=pool
    def submit(self,fn,*args,**kwargs):
        return self.pool._submit('native',fn,args,kwargs)


class PreparationPool:
    """Two physical slots, bounded waiting, and no optional-work queue."""
    def __init__(self,executor,*,notify=None):
        self.notify=notify
        self.executor=executor;self.lock=threading.RLock();self.closed=False;self.cancel_pending=False
        self.active={'native':None,'maintenance':None}
        self.waiting={'native':[],'maintenance':[]}
        self.native=_NativePreparation(self)

    def _notify(self):
        # The service callback only queues WorkPulse.notify on its event loop.
        # Notification is advisory and cannot hide physical release/results.
        try:
            if self.notify is not None:self.notify()
        except Exception:pass

    def submit(self,fn,*args,**kwargs):
        """Existing archive/recovery callers retain their mandatory FIFO."""
        return self._submit('maintenance',fn,args,kwargs)

    def try_submit_optional(self,fn,*args,**kwargs):
        with self.lock:
            if (self.closed or self.active['maintenance'] is not None
                    or self.waiting['maintenance'] or self.waiting['native']):return None
            return self._submit('optional',fn,args,kwargs)

    def _submit(self,role,fn,args,kwargs):
        with self.lock:
            if self.closed:raise RuntimeError('preparation_pool_closed')
            slot='native' if role=='native' else 'maintenance'
            future=Future();job=(future,fn,args,kwargs)
            if self.active[slot] is not None:
                if role=='optional':return None
                if len(self.waiting[slot])>=1:
                    future.set_exception(RuntimeError('preparation_waiting_bound'))
                    return future
                self.waiting[slot].append(job)
                future.add_done_callback(lambda _:self._cancel_waiting(slot,job))
            else:self._start(slot,job)
            return future

    def _start(self,slot,job):
        future,fn,args,kwargs=job
        if not future.set_running_or_notify_cancel():return
        self.active[slot]=job
        try:physical=self.executor.submit(fn,*args,**kwargs)
        except BaseException as error:
            self.active[slot]=None;future.set_exception(error)
            self._dispatch();self._notify()
            return
        physical.add_done_callback(lambda completed:self._completed(slot,job,completed))

    def _completed(self,slot,job,physical):
        with self.lock:
            if self.active[slot] is not job:raise RuntimeError('preparation_slot_identity')
            self.active[slot]=None
            future=job[0]
            try:value=physical.result();error=None
            except BaseException as failure:error=failure
            self._dispatch()
            if error is not None:future.set_exception(error)
            else:future.set_result(value)
            self._notify()

    def _cancel_waiting(self,slot,job):
        with self.lock:
            if job[0].cancelled() and job in self.waiting[slot]:
                self.waiting[slot].remove(job)
                job[0].set_running_or_notify_cancel()
            self._dispatch();self._notify()

    def _dispatch(self):
        if self.closed and self.cancel_pending:return
        # Native continuations always enter the real executor before waiting
        # maintenance. Each class still has at most one physical operation.
        for slot in ('native','maintenance'):
            while self.active[slot] is None and self.waiting[slot]:
                self._start(slot,self.waiting[slot].pop(0))

    def shutdown(self,wait=True,*,cancel_futures=False):
        with self.lock:
            self.closed=True;self.cancel_pending=cancel_futures
            futures=[job[0] for job in self.active.values() if job is not None]
            futures.extend(job[0] for pending in self.waiting.values() for job in pending)
            if cancel_futures:
                for pending in self.waiting.values():
                    for job in tuple(pending):job[0].cancel()
                    pending.clear()
            self._notify()
        if cancel_futures:
            # No queued facade work may now dispatch. Let the real executor
            # cancel its still-pending physical futures before waiting on their
            # proxies; those futures may become terminal only during shutdown.
            self.executor.shutdown(wait=wait,cancel_futures=True)
            if wait:wait_futures(futures)
            return
        def finish():
            # Without cancellation, accepted queued mandatory work must reach
            # the real executor and finish before its submission boundary closes.
            wait_futures(futures)
            self.executor.shutdown(wait=wait,cancel_futures=False)
        if wait:finish()
        else:threading.Thread(target=finish,name='preparation-close',daemon=True).start()
