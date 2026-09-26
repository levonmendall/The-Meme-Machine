"""Bounded control protocol and one priority-scheduled SQLite owner.

Socket disconnect never cancels accepted work. A durable command receipt and the
mutation share one commit. Expired requests cannot be replayed after receipt GC.
"""
import concurrent.futures
import heapq
import threading
import time
import sqlite3

from .solana_evidence_plane import EvidenceUnavailable

COMMAND_SECONDS=3.0
ATTEMPT_SECONDS=.5
MAX_COMMAND_BYTES=32768
MAX_RECEIPTS=8192


class PriorityOwner:
    def __init__(self, factory, *, capacity=64, reserved=8):
        self.capacity=capacity; self.reserved=reserved
        self.cv=threading.Condition(); self.queue=[]; self.sequence=0
        self.closed=False; self.ready=concurrent.futures.Future()
        self.thread=threading.Thread(target=self._run,args=(factory,),name='solana-evidence-owner',daemon=True)
        self.thread.start()

    def submit(self, fn, *, priority=1, expires=None):
        future=concurrent.futures.Future()
        with self.cv:
            if self.closed: raise EvidenceUnavailable('evidence_owner_unavailable')
            limit=self.capacity if priority==0 else self.capacity-self.reserved
            if len(self.queue)>=limit: raise EvidenceUnavailable('evidence_control_overloaded')
            self.sequence+=1
            heapq.heappush(self.queue,(priority,self.sequence,expires,fn,future)); self.cv.notify()
        return future

    def _run(self,factory):
        try:
            self.state=factory(); self.ready.set_result(True)
        except BaseException as exc:
            self.ready.set_exception(exc); self.closed=True; return
        try:
            while True:
                with self.cv:
                    self.cv.wait_for(lambda:self.queue or self.closed)
                    if not self.queue and self.closed: break
                    priority,_,expires,fn,future=heapq.heappop(self.queue)
                try:
                    if expires is not None and time.time()>expires:
                        raise EvidenceUnavailable('evidence_command_expired')
                    interrupted=False
                    writer=getattr(self.state,'writer',None)
                    def yield_background():
                        nonlocal interrupted
                        if interrupted:return 0 # allow rollback to finish
                        with self.cv:urgent=bool(self.queue and self.queue[0][0]<4)
                        if urgent:
                            interrupted=True;return 1
                        return 0
                    if priority==4 and writer:writer.db.set_progress_handler(yield_background,1000)
                    try:result=fn(self.state)
                    except sqlite3.OperationalError as exc:
                        if interrupted:raise EvidenceUnavailable('evidence_background_yield') from exc
                        raise
                    finally:
                        if priority==4 and writer:writer.db.set_progress_handler(None,0)
                except BaseException as exc: future.set_exception(exc)
                else: future.set_result(result)
        finally: self.state.close()

    def close(self):
        with self.cv: self.closed=True; self.cv.notify_all()
        self.thread.join(timeout=5)
        if self.thread.is_alive(): raise EvidenceUnavailable('evidence_owner_shutdown_timeout')


def command_priority(request):
    if request.get('op') in ('release','ack'): return 0
    if request.get('op')=='interest' and request.get('lifecycle') in ('reserved','open'): return 0
    return 3 if request.get('op')=='counter' else 1
