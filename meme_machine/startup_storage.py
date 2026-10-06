"""Bounded cold recovery on the existing evidence owner and archive executor.

No market admission occurs here. Old evidence keeps its original timestamps,
pins, gaps and deadlines; actual committed cleanup resolves overdue storage
work before the steady-state service contract begins.
"""
import asyncio
import time
from .solana_evidence_plane import EvidenceUnavailable,EvidenceWriter
from .solana_maintenance_state import DebtAgeAdapter,RESIDENCE_SECONDS


def needs_recovery(observation,clock=None,*,housekeeping=False):
    return (housekeeping and bool(observation.housekeeping) or any(
        at is not None and (at+RESIDENCE_SECONDS<=observation.wall if clock is None else
            clock.project(at+RESIDENCE_SECONDS)<=observation.monotonic)
        for scope in observation.scopes for at in
        (scope.hot_oldest,scope.retirement_oldest,scope.blocked_retirement_oldest)))


async def recover(work,pool,path,stop,*,wall=None,monotonic=None,
                  force=False,flight=None,on_complete=None,clock=None,record_required=None):
    wall=wall or time.time;monotonic=monotonic or time.monotonic
    started=monotonic();deadline=started+60
    async def owned(fn,label):
        while True:
            if stop.is_set():raise asyncio.CancelledError
            if monotonic()>=deadline:
                raise EvidenceUnavailable('maintenance_startup_recovery_incomplete')
            try:
                result=await work(fn,4,label=label)
                if monotonic()>=deadline:
                    raise EvidenceUnavailable('maintenance_startup_recovery_incomplete')
                return result
            except EvidenceUnavailable as exc:
                if str(exc)!='evidence_background_yield':raise
                # Keep this carrier and the original deadline across an urgent
                # SQL yield. Returning to normal arbitration would strand a
                # partially acknowledged archive and overdue recovery work.
                await asyncio.sleep(0)
    def overdue(state):
        observation=DebtAgeAdapter(state.writer,wall=wall,monotonic=monotonic).observe(state.fence.session)
        # A live source need not become entirely idle. Clean the newly overdue
        # evidence, then let the unchanged arbiter service ordinary young debt.
        records=needs_recovery(observation,clock)
        if record_required is not None:records=records or record_required(observation)
        pending=records or force and bool(observation.housekeeping)
        if not pending and on_complete is not None:on_complete(state,observation)
        return pending,records
    async def commit(plan,receipt):
        while plan:
            plan=await owned(lambda state:state.archive_commit_slice(plan,receipt),'archive_commit_plan')
            if monotonic()>=deadline:raise EvidenceUnavailable('maintenance_startup_recovery_incomplete')
    # Finish the existing carrier first; never start a second archive worker or
    # discard a durable receipt while an older operation is still in flight.
    if flight is not None:
        if flight.future is not None:
            plan,receipt=await asyncio.wait_for(asyncio.wrap_future(flight.future),15)
            await commit(plan,receipt)
        elif flight.pending is not None:await commit(*flight.pending)
        elif flight.prepared is not None:
            future=pool.submit(EvidenceWriter.prepare_and_write_archive,path,flight.prepared,max_bytes=16*1024*1024)
            plan,receipt=await asyncio.wait_for(asyncio.wrap_future(future),15)
            await commit(plan,receipt)
        flight.future=flight.pending=flight.prepared=flight.submitted=flight.generation=None
    def select(state):
        pending,records=overdue(state)
        # Garbage alone needs its bounded cleanup slice, not a new archive of
        # otherwise healthy young records. Expired source debt is record work.
        return pending,state.archive_plan() if records else None
    def retire(state):
        # Preserve the same zero-argument hooks used by normal arbitration.
        with state.housekeeping_retention():state.retention()
    pending,snapshot=await owned(select,'maintenance_decision')
    if not pending:return
    while not stop.is_set():
        if monotonic()>=deadline:raise EvidenceUnavailable('maintenance_startup_recovery_incomplete')
        if snapshot:
            future=pool.submit(EvidenceWriter.prepare_and_write_archive,path,snapshot,max_bytes=16*1024*1024)
            plan,receipt=await asyncio.wait_for(asyncio.wrap_future(future),15)
            while plan:
                def advance(state):
                    remaining=state.archive_commit_slice(plan,receipt)
                    if remaining:return remaining,None,None
                    # Source still interleaves between the unchanged 512-row
                    # commits. Dependent cleanup, observation and successor
                    # selection use their final slice's existing owner turn,
                    # rather than queuing three additional round trips.
                    # Cold recovery must finish garbage witnesses even when
                    # urgent source work preempts ordinary scope retirement.
                    retire(state)
                    pending,snapshot=select(state)
                    return remaining,pending,snapshot
                plan,pending,snapshot=await owned(advance,'archive_commit_plan')
        else:
            def cleanup(state):
                retire(state)
                return select(state)
            pending,snapshot=await owned(cleanup,'retention')
        if not pending:return
        await asyncio.sleep(0)
