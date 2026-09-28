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


def command_envelope(request,now):
    consumer=request.get('consumer');identity=request.get('request_id');expiry=request.get('expires_at')
    if (not isinstance(consumer,str) or not consumer or len(consumer)>128
            or not isinstance(identity,str) or not 1<=len(identity)<=64
            or type(expiry) not in (int,float) or not now-COMMAND_SECONDS*2<=expiry<=now+COMMAND_SECONDS):
        raise EvidenceUnavailable('evidence_command_envelope')
    return consumer,identity,expiry


class PriorityOwner:
    def __init__(self, factory, *, capacity=64, reserved=8, clock=time.monotonic):
        self.capacity=capacity; self.reserved=reserved
        self.clock=clock;self.enqueued={}
        self.metrics={}
        self.cv=threading.Condition(); self.queue=[]; self.sequence=0
        self.closed=False; self.ready=concurrent.futures.Future()
        self._checkpoint_epoch=0; self._checkpoint_busy=False
        self._checkpoint_handoff=None
        self.thread=threading.Thread(target=self._run,args=(factory,),name='solana-evidence-owner',daemon=True)
        self.thread.start()

    def submit(self, fn, *, priority=1, expires=None):
        future=concurrent.futures.Future()
        with self.cv:
            if self.closed: raise EvidenceUnavailable('evidence_owner_unavailable')
            limit=self.capacity if priority==0 else self.capacity-self.reserved
            if len(self.queue)>=limit:
                self.metrics['rejected']=self.metrics.get('rejected',0)+1
                raise EvidenceUnavailable('evidence_control_overloaded')
            self.sequence+=1
            self.enqueued[self.sequence]=self.clock()
            heapq.heappush(self.queue,(priority,self.sequence,expires,fn,future)); self.cv.notify()
            self.metrics['queue_peak']=max(self.metrics.get('queue_peak',0),len(self.queue))
        return future

    def _run(self,factory):
        try:
            self.state=factory(); self.ready.set_result(True)
        except BaseException as exc:
            self.ready.set_exception(exc); self.closed=True; return
        try:
            while True:
                with self.cv:
                    self.cv.wait_for(lambda:(self.queue or self.closed) and self._checkpoint_handoff is None)
                    if not self.queue and self.closed: break
                    # Exit/reservation and foreground work retain strict priority.
                    # Source commits and bounded background slices share FIFO
                    # admission order. A one-second aging rescue still made each
                    # completed archive wait behind newer source commits, idling
                    # its worker and accumulating hot history (Run 381). Neither
                    # source nor maintenance may repeatedly overtake the other.
                    eligible=[]
                    if self.queue[0][0]>=2:
                        eligible=[(row[1],i) for i,row in enumerate(self.queue)]
                    if eligible:
                        _,index=min(eligible);item=self.queue[index]
                        self.metrics['nonurgent_fifo_selections']=self.metrics.get('nonurgent_fifo_selections',0)+1
                        if self.clock()-self.enqueued[item[1]]>=1.0:
                            self.metrics['aged_selections']=self.metrics.get('aged_selections',0)+1
                        self.queue[index]=self.queue[-1];self.queue.pop();heapq.heapify(self.queue)
                    else:item=heapq.heappop(self.queue)
                    priority,sequence,expires,fn,future=item
                    queued=self.clock()-self.enqueued.pop(sequence)
                    prefix='priority'+str(priority)
                    wait=int(max(0,queued)*1_000_000)
                    self.metrics[prefix+'.queue_peak_us']=max(self.metrics.get(prefix+'.queue_peak_us',0),wait)
                    self.metrics[prefix+'.queue_total_us']=self.metrics.get(prefix+'.queue_total_us',0)+wait
                    self._checkpoint_busy=True
                started=self.clock()
                interrupted=False
                try:
                    if expires is not None and time.time()>expires:
                        raise EvidenceUnavailable('evidence_command_expired')
                    writer=getattr(self.state,'writer',None)
                    def queued_priority():
                        with self.cv:return self.queue[0][0] if self.queue else None
                    def queued_before(priority_limit):
                        queued=queued_priority()
                        return queued is not None and queued<priority_limit
                    def interrupt_background():
                        nonlocal interrupted
                        if interrupted:return 0 # allow rollback to finish
                        # Long/background SQL may still be interrupted only by
                        # urgent foreground/control work. Restarting archive
                        # scans for every normal source frame can starve cleanup.
                        if getattr(writer,'_retention_atomic',False):return 0
                        if queued_before(2):
                            interrupted=True;return 1
                        return 0
                    def yield_retention_boundary():
                        # Retention has already committed its bounded slice here.
                        # Urgent control work rotates scopes to preserve cross-scope
                        # fairness; normal source/counter work may let a still-full
                        # dense scope resume after that queued work runs.
                        queued=queued_priority()
                        if queued is None or queued>=4:return None
                        return 'urgent' if queued<2 else 'source'
                    if priority==4 and writer:
                        writer._retention_yield_requested=yield_retention_boundary
                        writer.db.set_progress_handler(interrupt_background,1000)
                    try:result=fn(self.state)
                    except sqlite3.OperationalError as exc:
                        if interrupted:raise EvidenceUnavailable('evidence_background_yield') from exc
                        raise
                    finally:
                        if priority==4 and writer:
                            writer.db.set_progress_handler(None,0)
                            writer._retention_yield_requested=None
                except BaseException as exc: future.set_exception(exc)
                else: future.set_result(result)
                finally:
                    elapsed=int(max(0,self.clock()-started)*1_000_000)
                    with self.cv:
                        self._checkpoint_epoch+=1; self._checkpoint_busy=False
                        if interrupted:self.metrics['background_yields']=self.metrics.get('background_yields',0)+1
                        self.metrics[prefix+'.execution_peak_us']=max(self.metrics.get(prefix+'.execution_peak_us',0),elapsed)
                        self.metrics[prefix+'.execution_total_us']=self.metrics.get(prefix+'.execution_total_us',0)+elapsed
                        self.metrics[prefix+'.completed']=self.metrics.get(prefix+'.completed',0)+1
        finally: self.state.close()

    def checkpoint_ticket(self):
        """Conservative owner-generation fence, never database authority."""
        with self.cv:
            if self.closed or self.queue or self._checkpoint_busy:return None
            return self._checkpoint_epoch

    def checkpoint_ticket_after_current(self):
        """Issue a marker in FIFO after all older admitted owner work."""
        if threading.get_ident()!=self.thread.ident:
            raise EvidenceUnavailable('checkpoint_ticket_owner_thread')
        with self.cv:
            if self.closed or not self._checkpoint_busy:return None
            return self._checkpoint_epoch+1

    def checkpoint_current(self,ticket):
        # Called inside the admitted owner callback. Any intervening
        # operation, including a command outside serve.work(), invalidates
        # the old PASSIVE completion. Reads conservatively invalidate too.
        with self.cv:
            return (type(ticket) is int and not self.closed
                    and self._checkpoint_busy and ticket==self._checkpoint_epoch)

    def checkpoint_handoff_after_current(self):
        """Lease the next mutation boundary to the one checkpoint worker.

        The lease is an owner-queue operation, so already admitted urgent work
        retains priority and older nonurgent work retains FIFO order. Reception
        and decoding continue; subsequent database operations stay bounded in the
        existing queue. Only an explicit matching release resumes mutation.
        """
        if threading.get_ident()!=self.thread.ident:
            raise EvidenceUnavailable('checkpoint_handoff_owner_thread')
        with self.cv:
            if self.closed or not self._checkpoint_busy or self._checkpoint_handoff is not None:
                raise EvidenceUnavailable('checkpoint_handoff_unavailable')
            token=object();self._checkpoint_handoff=token
            self._checkpoint_handoff_started=self.clock()
            self.metrics['checkpoint_handoffs']=self.metrics.get('checkpoint_handoffs',0)+1
            return token

    def release_checkpoint_handoff(self,token):
        """Release only after off-owner I/O has completed, including on failure."""
        with self.cv:
            if token is None or token is not self._checkpoint_handoff:
                raise EvidenceUnavailable('checkpoint_handoff_token')
            elapsed=int(max(0,self.clock()-self._checkpoint_handoff_started)*1_000_000)
            self.metrics['checkpoint_handoff_total_us']=self.metrics.get('checkpoint_handoff_total_us',0)+elapsed
            self.metrics['checkpoint_handoff_peak_us']=max(self.metrics.get('checkpoint_handoff_peak_us',0),elapsed)
            self._checkpoint_handoff=None;self.cv.notify_all()

    def telemetry(self):
        with self.cv:return dict(self.metrics,queued=len(self.queue))

    def close(self):
        with self.cv: self.closed=True; self.cv.notify_all()
        self.thread.join(timeout=5)
        if self.thread.is_alive(): raise EvidenceUnavailable('evidence_owner_shutdown_timeout')


def command_priority(request):
    if request.get('op') in ('release','ack','advance_interest'): return 0
    if request.get('op')=='interest' and request.get('lifecycle') in ('reserved','open'): return 0
    return 3 if request.get('op')=='counter' else 1


class PendingCommands:
    """Coalesce socket retries before admission, retaining durable receipt checks.

    A pending response ends its socket waiter before work may commit. Keep the
    completed reply through the durable receipt's existing expiry window, so a
    retry needn't queue behind a second large commit just to read that receipt.
    Cache capacity/expiry match durable receipts; accepted work still has the
    original 64-entry owner bound. No market payloads are cached here.
    """
    def __init__(self,owner,*,capacity=MAX_RECEIPTS,clock=time.time):
        self.owner=owner;self.lock=threading.RLock();self.pending={}
        self.capacity=capacity;self.clock=clock

    def submit(self,request):
        from .solana_evidence_plane import digest
        now=self.clock();consumer,identity,expiry=command_envelope(request,now)
        key=(consumer,identity);checksum=digest(request)
        with self.lock:
            for identity,row in list(self.pending.items()):
                if row[1].done() and row[2]<now:self.pending.pop(identity)
            previous=self.pending.get(key)
            if previous:
                if previous[0]!=checksum:raise EvidenceUnavailable('evidence_command_identity_conflict')
                return previous[1]
            if len(self.pending)>=self.capacity:raise EvidenceUnavailable('evidence_receipt_capacity')
            future=self.owner.submit(lambda state:state.fence.command(request),
                                     priority=command_priority(request))
            self.pending[key]=(checksum,future,expiry+COMMAND_SECONDS*2)
            return future
