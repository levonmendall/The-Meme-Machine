"""Bounded control protocol and one priority-scheduled SQLite owner.

Socket disconnect never cancels accepted work. A durable command receipt and the
mutation share one commit. Expired requests cannot be replayed after receipt GC.
"""
import concurrent.futures
from collections import deque
import heapq
import math
import os
import re
import threading
import time
from time import thread_time as owner_thread_time
import sqlite3

from .solana_evidence_plane import EvidenceUnavailable

COMMAND_SECONDS=3.0
ATTEMPT_SECONDS=.5
MAX_COMMAND_BYTES=32768
MAX_RECEIPTS=8192
OWNER_SLOW_SECONDS=1.0
OWNER_OPERATION_LIMIT=8
MAINTENANCE_PERMIT_SECONDS=.100


class _MaintenanceBoundary:
    """One FIFO scheduling ticket; it contains no native callback or Needs."""
    def __init__(self,owner,sequence,requested,deadline):
        self.owner=owner;self.requested_sequence=sequence;self.requested_at=requested
        self.deadline=deadline;self.ready=concurrent.futures.Future()
        self.state='PENDING';self.permit_deadline=None;self.command_future=None



def owner_operation(fn):
    """Fixed source identity only; never callback arguments, SQL or locals."""
    identity=getattr(fn,'owner_operation',{})
    identity=identity if isinstance(identity,dict) else {}
    code=getattr(fn,'__code__',None)
    module=identity.get('origin_module',getattr(fn,'__module__',None))
    line=identity.get('origin_line',getattr(code,'co_firstlineno',None))
    stage=identity.get('stage');component=identity.get('component')
    return dict(stage=stage if stage in ('source_commit','candidate_development','archive_plan',
        'archive_commit_plan','retention','maintenance_health','health_ipc','health_scheduler',
        'checkpoint_prepare','checkpoint_finish','maintenance_decision','history_dispatch',
        'history_apply','candidate_delivery_capture','candidate_delivery_ack') else 'UNLABELLED',
        component=component if component in ('control','candidate','scout','history_publication',
            'delivery_accounting') else 'NONE',
        origin_module=module if isinstance(module,str) and re.fullmatch(r'meme_machine\.[A-Za-z0-9_.]{1,128}',module) else 'UNAVAILABLE',
        origin_line=line if type(line)is int and 0<line<1000000 else None)


async def admit(owner,fn,**options):
    """Lossless pre-admission wait for one bounded producer command.

    Only a full queue retries. Expiry/owner failures remain fail-closed. Accepted
    work returns its original future exactly once and outlives its waiter.
    """
    import asyncio
    started=time.monotonic();refusals=0
    while True:
        try:future=owner.submit(fn,**options);break
        except EvidenceUnavailable as exc:
            if str(exc)!='evidence_control_overloaded':raise
            refusals+=1;await asyncio.sleep(min(.2,.01*2**min(refusals-1,5)))
    if refusals:
        micros=int((time.monotonic()-started)*1_000_000)
        with owner.cv:
            m=owner.metrics;m['admission_waited']=m.get('admission_waited',0)+1
            m['admission_refusals']=m.get('admission_refusals',0)+refusals
            m['admission_wait_total_us']=m.get('admission_wait_total_us',0)+micros
            m['admission_wait_peak_us']=max(m.get('admission_wait_peak_us',0),micros)
    return future


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
        self.active_operation=None;self.recent_slow_operations=deque(maxlen=OWNER_OPERATION_LIMIT)
        self.cv=threading.Condition(); self.queue=[]; self.sequence=0
        self._urgent_queued=0
        self._continuation_claimed=False
        self.closed=False; self.ready=concurrent.futures.Future()
        self.admission_notify=None
        self._checkpoint_epoch=0; self._checkpoint_busy=False
        self._checkpoint_handoff=None
        self._maintenance_ticket=None
        self.thread=threading.Thread(target=self._run,args=(factory,),name='solana-evidence-owner',daemon=True)
        self.thread.start()

    def submit(self, fn, *, priority=1, expires=None, admit_before=None,_maintenance_ticket=None):
        future=concurrent.futures.Future()
        with self.cv:
            if self.closed: raise EvidenceUnavailable('evidence_owner_unavailable')
            ticket=self._maintenance_ticket
            spending=_maintenance_ticket is not None
            if spending and (ticket is not _maintenance_ticket or ticket.state!='OPEN'
                    or priority!=4 or self._checkpoint_busy or self._checkpoint_handoff is not None
                    or self._urgent_queued):
                raise EvidenceUnavailable('maintenance_boundary_unavailable')
            if priority<2 and ticket is not None and ticket.state=='OPEN':
                self._release_maintenance_locked(ticket,'urgent_invalidated')
            limit=self.capacity if priority==0 else self.capacity-self.reserved
            reserved=int(ticket is not None and ticket.state=='OPEN' and not spending)
            if len(self.queue)+reserved>=limit:
                self.metrics['rejected']=self.metrics.get('rejected',0)+1
                raise EvidenceUnavailable('evidence_control_overloaded')
            accepted_at=self.clock()
            if spending and accepted_at>=ticket.permit_deadline:
                self._release_maintenance_locked(ticket,'expired')
                raise EvidenceUnavailable('maintenance_boundary_expired')
            if admit_before is not None:
                if accepted_at>=admit_before:
                    raise EvidenceUnavailable('evidence_admission_offer_expired')
                # Close the scheduling-snapshot race with a new urgent/older
                # admission. Ordinary submissions retain their existing path.
                if not spending and (self.queue or self._checkpoint_busy or self._checkpoint_handoff is not None):
                    raise EvidenceUnavailable('evidence_admission_offer_unavailable')
            self.sequence+=1
            future.owner_sequence=self.sequence
            future.owner_accepted_at=accepted_at
            self.enqueued[self.sequence]=accepted_at
            heapq.heappush(self.queue,(priority,self.sequence,expires,fn,future))
            if spending:
                ticket.state='ACCEPTED';ticket.command_future=future
                self.metrics['maintenance_boundary.accepted']=self.metrics.get('maintenance_boundary.accepted',0)+1
            if priority<2:self._urgent_queued+=1
            self.cv.notify()
            self.metrics['queue_peak']=max(self.metrics.get('queue_peak',0),len(self.queue))
        # A scheduling observer wakes the event loop outside the owner lock.
        # It has no power to reorder, cancel or choose admitted work.
        if self.admission_notify is not None:self.admission_notify()
        return future

    def request_maintenance_boundary(self,*,deadline):
        """Reserve one normal FIFO position, without accepting a native turn."""
        with self.cv:
            now=self.clock()
            if self.closed:raise EvidenceUnavailable('evidence_owner_unavailable')
            if (type(deadline) not in (int,float) or not math.isfinite(deadline)
                    or not now<deadline<2**63):raise EvidenceUnavailable('maintenance_boundary_deadline')
            if self._maintenance_ticket is not None:
                raise EvidenceUnavailable('maintenance_boundary_outstanding')
            if len(self.queue)>=self.capacity-self.reserved:
                self.metrics['rejected']=self.metrics.get('rejected',0)+1
                raise EvidenceUnavailable('evidence_control_overloaded')
            self.sequence+=1
            ticket=_MaintenanceBoundary(self,self.sequence,now,deadline)
            self._maintenance_ticket=ticket;self.enqueued[self.sequence]=now
            heapq.heappush(self.queue,(4,self.sequence,None,ticket,ticket.ready))
            self.metrics['maintenance_boundary.requested']=self.metrics.get('maintenance_boundary.requested',0)+1
            self.metrics['queue_peak']=max(self.metrics.get('queue_peak',0),len(self.queue))
            self.cv.notify_all()
            return ticket

    def _release_maintenance_locked(self,ticket,outcome):
        if ticket is not self._maintenance_ticket:return
        if ticket.state=='PENDING':
            self.queue=[row for row in self.queue if row[3] is not ticket]
            heapq.heapify(self.queue);self.enqueued.pop(ticket.requested_sequence,None)
        ticket.state='RELEASED';self._maintenance_ticket=None
        self.metrics['maintenance_boundary.'+outcome]=self.metrics.get('maintenance_boundary.'+outcome,0)+1
        if not ticket.ready.done():
            try:ticket.ready.set_exception(EvidenceUnavailable('maintenance_boundary_'+outcome))
            except concurrent.futures.InvalidStateError:
                # A notification waiter may cancel concurrently without taking
                # owner.cv. Only that terminal cancellation is harmless.
                if not ticket.ready.cancelled():raise
        self.cv.notify_all()

    def cancel_maintenance_boundary(self,ticket):
        """Abandon only an unspent scheduling ticket, never accepted native work."""
        with self.cv:
            if ticket is not self._maintenance_ticket:return False
            if ticket.state=='ACCEPTED':return False
            self._release_maintenance_locked(ticket,'cancelled');return True

    def submit_maintenance(self,fn,ticket):
        with self.cv:
            if (ticket is not self._maintenance_ticket or ticket.state!='OPEN'
                    or not callable(fn)):raise EvidenceUnavailable('maintenance_boundary_unavailable')
            return self.submit(fn,priority=4,admit_before=ticket.permit_deadline,
                _maintenance_ticket=ticket)

    def try_continuation(self,fn):
        """Claim one bounded stage after this ACK, without another admission.

        The claim is a scheduling boundary: already queued urgent work and any
        reserved maintenance boundary win. A later urgent admission may meet
        this bounded stage just as it may meet an already selected callback.
        The next consumer/ACK still reenters normal FIFO; this is not a loop.
        Active/slow-operation records keep the whole physical ACK unit; the
        service separately accounts its logical ACK and capture executions.
        """
        if threading.get_ident()!=self.thread.ident:
            raise EvidenceUnavailable('evidence_continuation_owner_thread')
        with self.cv:
            active=self.active_operation
            if (self.closed or not self._checkpoint_busy or self._continuation_claimed
                    or active is None or active['priority']!=2
                    or active['stage']!='candidate_delivery_ack' or self._urgent_queued
                    or self._maintenance_ticket is not None or self._checkpoint_handoff is not None):
                return False
            self._continuation_claimed=True
        fn(self.state)
        return True

    def _next_work(self):
        """Older FIFO work, one reserved boundary, and unchanged urgent priority."""
        with self.cv:
            while True:
                ticket=self._maintenance_ticket
                if ticket is not None and ticket.state=='OPEN':
                    if self.closed or self._urgent_queued or self.clock()>=ticket.permit_deadline:
                        self._release_maintenance_locked(ticket,
                            'closed' if self.closed else 'urgent_invalidated' if self._urgent_queued else 'expired')
                        continue
                    self.cv.wait(timeout=max(.001,ticket.permit_deadline-self.clock()))
                    continue
                self.cv.wait_for(lambda:(self.queue or self.closed) and self._checkpoint_handoff is None)
                if not self.queue and self.closed:return None
                ticket=self._maintenance_ticket
                # The real native command consumes the already reserved FIFO
                # slot. It keeps its genuine later acceptance/sequence clock.
                reserved=(ticket is not None and ticket.state=='ACCEPTED' and self.queue[0][0]>=2)
                if reserved:
                    index=next((i for i,row in enumerate(self.queue) if row[4] is ticket.command_future),None)
                    if index is None:raise EvidenceUnavailable('maintenance_boundary_command_missing')
                    item=self.queue[index];self.queue[index]=self.queue[-1];self.queue.pop();heapq.heapify(self.queue)
                elif self.queue[0][0]>=2:
                    _,index=min((row[1],i) for i,row in enumerate(self.queue))
                    item=self.queue[index];self.queue[index]=self.queue[-1];self.queue.pop();heapq.heapify(self.queue)
                    self.metrics['nonurgent_fifo_selections']=self.metrics.get('nonurgent_fifo_selections',0)+1
                    if self.clock()-self.enqueued[item[1]]>=1.0:
                        self.metrics['aged_selections']=self.metrics.get('aged_selections',0)+1
                else:item=heapq.heappop(self.queue)
                if ticket is not None and item[3] is ticket:
                    self.enqueued.pop(ticket.requested_sequence)
                    # A scheduling operation invalidates older checkpoint
                    # tickets just as every other serialized operation does.
                    self._checkpoint_epoch+=1
                    if (self.closed or self.clock()>=ticket.deadline):
                        self._release_maintenance_locked(ticket,'closed' if self.closed else 'expired')
                        continue
                    # Future.cancel() does not take owner.cv. Claim this
                    # notification atomically before exposing an OPEN permit.
                    if not ticket.ready.set_running_or_notify_cancel():
                        self._release_maintenance_locked(ticket,'cancelled')
                        continue
                    now=self.clock();ticket.permit_deadline=min(ticket.deadline,now+MAINTENANCE_PERMIT_SECONDS)
                    ticket.state='OPEN'
                    wait=int(max(0,now-ticket.requested_at)*1_000_000)
                    self.metrics['maintenance_boundary.granted']=self.metrics.get('maintenance_boundary.granted',0)+1
                    self.metrics['maintenance_boundary.wait_total_us']=self.metrics.get('maintenance_boundary.wait_total_us',0)+wait
                    self.metrics['maintenance_boundary.wait_peak_us']=max(self.metrics.get('maintenance_boundary.wait_peak_us',0),wait)
                    ticket.ready.set_result(ticket);self.cv.notify_all();continue
                self._checkpoint_busy=True
                return item

    def _run(self,factory):
        with self.cv:
            self.metrics.update(owner_pid=os.getpid(),native_thread_id=threading.get_native_id())
        try:
            self.state=factory(); self.ready.set_result(True)
        except BaseException as exc:
            self.ready.set_exception(exc); self.closed=True; return
        try:
            while True:
                item=self._next_work()
                if item is None:break
                with self.cv:
                    # Exit/reservation and foreground work retain strict priority.
                    # Source commits and bounded background slices share FIFO
                    # admission order. A one-second aging rescue still made each
                    # completed archive wait behind newer source commits, idling
                    # its worker and accumulating hot history (Run 381). Neither
                    # source nor maintenance may repeatedly overtake the other.
                    priority,sequence,expires,fn,future=item
                    self._continuation_claimed=False
                    if priority<2:self._urgent_queued-=1
                    queued=self.clock()-self.enqueued.pop(sequence)
                    prefix='priority'+str(priority)
                    wait=int(max(0,queued)*1_000_000)
                    self.metrics[prefix+'.queue_peak_us']=max(self.metrics.get(prefix+'.queue_peak_us',0),wait)
                    self.metrics[prefix+'.queue_total_us']=self.metrics.get(prefix+'.queue_total_us',0)+wait
                    self._checkpoint_busy=True
                started=self.clock()
                cpu_started=owner_thread_time();outcome='FAILED'
                with self.cv:
                    self.active_operation=dict(owner_operation(fn),priority=priority,
                        sequence=sequence,pid=os.getpid(),native_thread_id=threading.get_native_id(),
                        started_monotonic=started,queue_microseconds=wait)
                interrupted=False
                try:
                    if expires is not None and time.time()>expires:
                        raise EvidenceUnavailable('evidence_command_expired')
                    writer=getattr(self.state,'writer',None)
                    if writer is not None:writer._background_sql_interrupted=False
                    def queued_priority():
                        with self.cv:return self.queue[0][0] if self.queue else None
                    def interrupt_background():
                        nonlocal interrupted
                        if interrupted:return 0 # allow rollback to finish
                        # Long/background SQL may still be interrupted only by
                        # urgent foreground/control work. Restarting archive
                        # scans for every normal source frame can starve cleanup.
                        if getattr(writer,'_retention_atomic',False):return 0
                        # Admission/removal maintains this count under cv. Read
                        # the atomic integer at the same 1,000-op SQL cadence;
                        # repeatedly locking the scheduler here consumed CPU
                        # needed by the native join. Queue order is unchanged.
                        if self._urgent_queued:
                            interrupted=True
                            writer._background_sql_interrupted=True
                            return 1
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
                        writer._owner_progress_handler=interrupt_background
                        writer._retention_yield_requested=yield_retention_boundary
                        writer.db.set_progress_handler(interrupt_background,1000)
                    try:result=fn(self.state)
                    except sqlite3.OperationalError as exc:
                        if interrupted:raise EvidenceUnavailable('evidence_background_yield') from exc
                        raise
                    finally:
                        if priority==4 and writer:
                            writer.db.set_progress_handler(None,0)
                            writer._owner_progress_handler=None
                            writer._retention_yield_requested=None
                except BaseException as exc: future.set_exception(exc)
                else: outcome='COMPLETED';future.set_result(result)
                finally:
                    elapsed=int(max(0,self.clock()-started)*1_000_000)
                    with self.cv:
                        if elapsed>=OWNER_SLOW_SECONDS*1_000_000:
                            self.recent_slow_operations.append(dict(self.active_operation,
                                completed_monotonic=self.clock(),execution_microseconds=elapsed,
                                execution_cpu_microseconds=int(max(0,owner_thread_time()-cpu_started)*1_000_000),
                                outcome=outcome))
                        self.active_operation=None
                        self._continuation_claimed=False
                        self._checkpoint_epoch+=1; self._checkpoint_busy=False
                        ticket=self._maintenance_ticket
                        if ticket is not None and ticket.command_future is future:
                            self._release_maintenance_locked(ticket,'completed')
                        if interrupted:self.metrics['background_yields']=self.metrics.get('background_yields',0)+1
                        self.metrics[prefix+'.execution_peak_us']=max(self.metrics.get(prefix+'.execution_peak_us',0),elapsed)
                        self.metrics[prefix+'.execution_total_us']=self.metrics.get(prefix+'.execution_total_us',0)+elapsed
                        self.metrics[prefix+'.completed']=self.metrics.get(prefix+'.completed',0)+1
        finally: self.state.close()

    def checkpoint_ticket(self):
        """Conservative owner-generation fence, never database authority."""
        with self.cv:
            if self.closed or self.queue or self._checkpoint_busy or self._maintenance_ticket is not None:return None
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
        existing queue. The already-ready checkpoint worker receives this token
        directly and releases it after I/O, before notifying its asyncio waiter.
        Only an explicit matching release resumes mutation.
        """
        if threading.get_ident()!=self.thread.ident:
            raise EvidenceUnavailable('checkpoint_handoff_owner_thread')
        with self.cv:
            if (self.closed or not self._checkpoint_busy or self._checkpoint_handoff is not None
                    or self._maintenance_ticket is not None and self._maintenance_ticket.state in ('OPEN','ACCEPTED')):
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
        with self.cv:
            active=None if self.active_operation is None else dict(self.active_operation,
                observed_monotonic=self.clock(),elapsed_microseconds=int(max(0,
                    self.clock()-self.active_operation['started_monotonic'])*1_000_000))
            return dict(self.metrics,queued=len(self.queue),active_operation=active,
                recent_slow_operations=[dict(row) for row in self.recent_slow_operations])

    def close(self):
        with self.cv:
            self.closed=True
            ticket=self._maintenance_ticket
            if ticket is not None and ticket.state!='ACCEPTED':self._release_maintenance_locked(ticket,'closed')
            self.cv.notify_all()
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
