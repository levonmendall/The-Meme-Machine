"""Bounded cold recovery on the existing evidence owner and archive executor.

No market admission occurs here. Old evidence keeps its original timestamps,
pins, gaps and deadlines; actual committed cleanup resolves overdue storage
work before the steady-state service contract begins.
"""
import asyncio
import time
from .solana_evidence_plane import EvidenceUnavailable,EvidenceWriter
from .solana_maintenance_state import DebtAgeAdapter,RESIDENCE_SECONDS


async def recover(work,pool,path,stop,*,wall=None,monotonic=None):
    wall=wall or time.time;monotonic=monotonic or time.monotonic
    started=monotonic();deadline=started+60
    def overdue(state):
        observation=DebtAgeAdapter(state.writer,wall=wall,monotonic=monotonic).observe(state.fence.session)
        return any(at is not None and at+RESIDENCE_SECONDS<=observation.wall
                   for scope in observation.scopes for at in (scope.hot_oldest,scope.retirement_oldest))
    initial=await work(overdue,4,label='maintenance_decision')
    if not initial:return
    while not stop.is_set():
        if monotonic()>=deadline:raise EvidenceUnavailable('maintenance_startup_recovery_incomplete')
        snapshot=await work(lambda state:state.archive_plan(),4,label='archive_plan')
        if snapshot:
            future=pool.submit(EvidenceWriter.prepare_and_write_archive,path,snapshot,max_bytes=16*1024*1024)
            plan,receipt=await asyncio.wait_for(asyncio.wrap_future(future),15)
            while plan:
                plan=await work(lambda state:state.archive_commit_slice(plan,receipt),4,label='archive_commit_plan')
                if monotonic()>=deadline:raise EvidenceUnavailable('maintenance_startup_recovery_incomplete')
        await work(lambda state:state.retention(),4,label='retention')
        if not await work(overdue,4,label='maintenance_decision'):
            return
        await asyncio.sleep(0)
