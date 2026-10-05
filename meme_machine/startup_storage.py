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
                  force=False,flight=None,on_complete=None,clock=None):
    wall=wall or time.time;monotonic=monotonic or time.monotonic
    started=monotonic();deadline=started+60
    def overdue(state):
        observation=DebtAgeAdapter(state.writer,wall=wall,monotonic=monotonic).observe(state.fence.session)
        # A live source need not become entirely idle. Clean the newly overdue
        # evidence, then let the unchanged arbiter service ordinary young debt.
        pending=needs_recovery(observation,clock,housekeeping=force)
        if not pending and on_complete is not None:on_complete(state,observation)
        return pending
    async def commit(plan,receipt):
        while plan:
            plan=await work(lambda state:state.archive_commit_slice(plan,receipt),4,label='archive_commit_plan')
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
    initial=await work(overdue,4,label='maintenance_decision')
    if not initial:return
    while not stop.is_set():
        if monotonic()>=deadline:raise EvidenceUnavailable('maintenance_startup_recovery_incomplete')
        snapshot=await work(lambda state:state.archive_plan(),4,label='archive_plan')
        if snapshot:
            future=pool.submit(EvidenceWriter.prepare_and_write_archive,path,snapshot,max_bytes=16*1024*1024)
            plan,receipt=await asyncio.wait_for(asyncio.wrap_future(future),15)
            await commit(plan,receipt)
        await work(lambda state:state.retention(),4,label='retention')
        if not await work(overdue,4,label='maintenance_decision'):
            return
        await asyncio.sleep(0)
