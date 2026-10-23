"""Off-owner physical WAL reclamation at an explicit SQLite mutation boundary.

A completed PASSIVE snapshot can already be obsolete when its callback runs.
The fast path may reject that stale generation, but the fallback must not wait
forever for idle time. This module obtains one FIFO owner handoff, checkpoints
its remaining tail off-owner, and releases the handoff on every terminal path.

No busy wait for readers, no durability change, no queue/storage-limit change.
The ready worker owns the handoff through actual I/O completion. Neither the
asyncio coordinator nor its shared executor is needed to release mutations.
"""
from __future__ import annotations
import asyncio
import concurrent.futures
from contextlib import closing
from pathlib import Path
import threading
from .solana_evidence_plane import EvidenceUnavailable
from .runtime.operation_costs import measured
from .runtime.sqlite_failure import connect as diagnostic_connect,checkpoint_result


@measured('owner.checkpoint')
def checkpoint_and_reclaim(path):
    """Caller holds the logical owner boundary; this connection owns no records."""
    with closing(diagnostic_connect(Path(path).resolve().as_uri()+'?mode=rw',
                                 diagnostic_role='canonical_checkpoint.handoff',uri=True,isolation_level=None,timeout=0)) as db:
        # The fresh PASSIVE includes every write preceding the handoff. It must
        # complete before TRUNCATE; a pinned old reader releases us immediately.
        result=checkpoint_result(db,db.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone())
        if result[0]!=0 or result[1]!=result[2]:return result
        # No new source, metadata, or retention transaction can append a tail
        # while the handoff is held. New readers remain valid; a reader that
        # prevents reset yields BUSY rather than being waited out or invalidated.
        return checkpoint_result(db,db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone())


class _CheckpointJob:
    def __init__(self):
        self.result=concurrent.futures.Future()
        self.cancelled=False
        self.token=None


class _CheckpointWait(asyncio.Future):
    """Cancellation signals the grant lock synchronously; never cancels work.

    This is the actual Future awaited by the Task. An ordinary shield outside
    it would postpone the signal until the coroutine receives CancelledError,
    allowing an owner callback to grant while that coroutine cannot run.
    """
    def __init__(self,future,worker,job):
        super().__init__()
        self.worker=worker;self.job=job
        future.add_done_callback(self._completed)

    def cancel(self,msg=None):
        if not self.done():self.worker.cancel(self.job)
        return super().cancel(msg)

    def _completed(self,future):
        if self.done():
            if not future.cancelled():future.exception()
        elif future.cancelled():self.cancel()
        else:
            error=future.exception()
            if error is None:self.set_result(future.result())
            else:self.set_exception(error)


class CheckpointWorker:
    """One ready thread and one bounded job, including its pre-admission slot.

    The owner grants directly under this condition. The worker releases the
    exact token before publishing a result; a delayed/cancelled asyncio waiter
    therefore cannot extend an otherwise completed SQLite mutation boundary.
    """
    def __init__(self,owner,path):
        self.owner=owner;self.path=Path(path).resolve()
        self.cv=threading.Condition()
        self.ready=concurrent.futures.Future()
        self.job=None;self.closed=False
        self.thread=threading.Thread(target=self._run,name='canonical-checkpoint',daemon=True)
        self.thread.start()

    def prepare(self):
        with self.cv:
            if self.closed or not self.ready.done() or not self.thread.is_alive():
                raise EvidenceUnavailable('checkpoint_worker_unavailable')
            if self.job is not None:raise EvidenceUnavailable('checkpoint_worker_inflight')
            self.job=_CheckpointJob()
            return self.job

    def cancel(self,job):
        # Only the owner callback consumes an admitted job. This flag and the
        # grant share a lock, so queued cancellation cannot start physical I/O.
        with self.cv:
            if self.job is job and job.token is None:job.cancelled=True

    def withdraw(self,job):
        """Release a slot only when owner admission failed or has been joined."""
        with self.cv:
            if self.job is job and job.token is None:
                self.job=None;job.result.set_result(None);self.cv.notify_all()

    def grant(self,job):
        """Called only by the admitted owner callback, never by asyncio."""
        with self.cv:
            if self.job is not job:raise EvidenceUnavailable('checkpoint_worker_job')
            if job.cancelled or self.closed:
                self.job=None;job.result.set_result(None);self.cv.notify_all()
                return False
            # READY precedes admission. This must be the owner's whole callback:
            # after publishing, it must perform no SQLite work or mutations.
            # The worker wakes directly, with no new task/executor submission.
            job.token=self.owner.checkpoint_handoff_after_current()
            self.cv.notify_all()
            return True

    def _run(self):
        with self.cv:self.ready.set_result(True)
        while True:
            with self.cv:
                self.cv.wait_for(lambda:self.closed or self.job is not None and self.job.token is not None)
                job=self.job
                if job is None or job.token is None:
                    if self.closed:return
                    continue
            result=None;error=None;release_failed=False
            try:result=checkpoint_and_reclaim(self.path)
            except BaseException as exc:error=exc
            finally:
                try:self.owner.release_checkpoint_handoff(job.token)
                except BaseException as exc:
                    release_failed=True
                    if error is None:error=exc
                    else:error.add_note('checkpoint handoff release also failed')
            # Token release precedes both availability of another job and all
            # future callbacks, including asyncio completion notification.
            with self.cv:
                self.job=None
                if release_failed:self.closed=True
                self.cv.notify_all()
            if error is None:job.result.set_result(result)
            else:job.result.set_exception(error)

    def close(self):
        """Join actual I/O before the caller may close the canonical writer."""
        with self.cv:
            self.closed=True
            if self.job is not None and self.job.token is None:self.job.cancelled=True
            self.cv.notify_all()
        self.thread.join(timeout=5)
        if self.thread.is_alive():raise EvidenceUnavailable('checkpoint_worker_shutdown_timeout')


async def reclaim_at_boundary(owner,path,*,worker=None):
    """Join accepted admission and worker-owned I/O, even under cancellation."""
    from .solana_evidence_control import admit
    owned=worker is None
    if owned:worker=CheckpointWorker(owner,path)
    if worker.owner is not owner or worker.path!=Path(path).resolve():
        raise EvidenceUnavailable('checkpoint_worker_identity')
    cancelled=False;job=None;accepted=None
    try:
        await asyncio.shield(asyncio.wrap_future(worker.ready))
        job=worker.prepare()
        accepted=asyncio.wrap_future(await admit(owner,lambda state:worker.grant(job),priority=2))
        while True:
            try:
                await _CheckpointWait(accepted,worker,job)
                break
            except asyncio.CancelledError:
                cancelled=True;worker.cancel(job)
        pending=asyncio.wrap_future(job.result)
        while True:
            try:
                result=await _CheckpointWait(pending,worker,job)
                break
            except asyncio.CancelledError:
                cancelled=True;worker.cancel(job)
        if cancelled:raise asyncio.CancelledError()
        return result
    finally:
        # An accepted grant was joined above, including repeated cancellation.
        # An admission failure owns no token and may withdraw its prepared slot.
        if job is not None:worker.withdraw(job)
        if owned:worker.close()
