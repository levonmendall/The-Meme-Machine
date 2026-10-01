"""M1 regression contract: committed native service must complete its decision.

Reference design: durable d3325376, finite native completion prerequisite. This
is a new qualification entrypoint, not imported branch-specific repair or proof.
The current production base must earn the assertions; failure stays a failure.
"""
from concurrent.futures import Future
from pathlib import Path
import threading
from unittest.mock import patch

from .clock import DeterministicClock
from .fixtures import b58
from .native import native_state, empty_frame, snapshot
from .restart import records


def qualify(output):
    from meme_machine import solana_evidence_service as service
    from meme_machine.solana_evidence_control import PriorityOwner
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_maintenance_runtime import ArchiveFlight, MaintenanceRuntime
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from .native import ENDPOINT
    clock=DeterministicClock();clock.begin();box={};events=[];accepted=[]
    path=Path(output)/'m1.sqlite'
    def seed():
        state=service.ServiceState(path,AlchemyEndpoint.parse(ENDPOINT));state.writer.clock=clock.time
        for i in range(1,129):
            state.writer.ingest(records(clock,'account:'+b58(i.to_bytes(32,'big')),1,'m1-ledger',account=True))
        assert state.writer.archive(clock.time()-180)==128
        rows=records(clock,'program:meteora',1800,'m1-recovery')
        state.writer.ingest(rows[:1000]);state.writer.ingest(rows[1000:])
        sub=next(s for s in service.program_subscriptions() if s.scope=='program:meteora')
        state.fence.block(sub,__import__('json').loads(empty_frame(10000,int(clock.time()))),clock.time())
        runtime=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
        plan,receipt=EvidenceWriter.prepare_and_write_archive(path,state.archive_plan())
        assert len(plan)==1000
        flight=ArchiveFlight(pending=(plan,receipt),submitted=clock.monotonic(),generation=runtime.generation)
        box.update(state=state,runtime=runtime,flight=flight)
        return state
    def error(future):
        try:future.result(20)
        except BaseException as exc:return type(exc).__name__+':'+str(exc)
        return None
    def submit(owner,fn,priority):
        future=owner.submit(fn,priority=priority);accepted.append(future);return future
    def observe(state):
        r=box['runtime'];f=box['flight']
        return dict(pending=r.arbiter.pending is not None,runtime_failure=r.failure,
            arbiter_failed=r.arbiter.failed,hot=state.writer.db.execute(
                "SELECT COUNT(*) FROM records WHERE scope='program:meteora' AND body IS NOT NULL").fetchone()[0],
            progress=state.writer.db.execute("SELECT units,records FROM maintenance_progress WHERE scope='program:meteora' AND side='archive'").fetchone(),
            episodes=state.writer.db.execute('SELECT * FROM maintenance_episodes ORDER BY scope,side').fetchall(),
            open_transaction=state.writer.db.in_transaction,receipt_remaining=len(f.pending[0]) if f.pending else 0,
            integrity=state.writer.db.execute('PRAGMA integrity_check').fetchone()[0])
    with patch.object(service,'time',clock):
        owner=PriorityOwner(seed,clock=clock.monotonic)
        try:
            owner.ready.result(20);r=box['runtime'];f=box['flight'];reads=[0]
            def trace(sql):
                if sql.startswith('SELECT scope,side,at,units,record_at,records FROM maintenance_progress ORDER BY scope,side LIMIT '):
                    reads[0]+=1
                    if reads[0]==2:
                        box['urgent']=submit(owner,lambda state:state.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
            def turn(state):
                state.writer.db.set_trace_callback(trace)
                try:return r.turn(f,clock.monotonic())
                finally:state.writer.db.set_trace_callback(None)
            first=submit(owner,turn,4);first_error=error(first)
            if 'urgent' in box:box['urgent'].result(10)
            before=submit(owner,observe,2).result(10)
            second=submit(owner,lambda state:r.turn(f,clock.monotonic()),4);second_error=error(second)
            after=submit(owner,observe,2).result(10)
            gates=dict(urgent_admitted='urgent' in box and box['urgent'].done(),
                accepted_future_completed=first.done(),completion_query_interrupted=reads[0]==2,
                cooperative_yield=first_error is not None and first_error.endswith(':evidence_background_yield'),
                native_slice_committed=before['hot']==1288 and before['progress']==(512,512),
                receipt_continuation_preserved=before['receipt_remaining']==488,
                transaction_closed=before['open_transaction'] is False,
                integrity=before['integrity']=='ok',cooperative_error_nonfatal=before['runtime_failure'] is None,
                episode_not_rebased=before['episodes']==after['episodes'],
                decision_completed=before['pending'] is False,next_admission_usable=second_error is None)
            return dict(passed=all(gates.values()),gates=gates,first_error=first_error,second_error=second_error,
                before=before,after=after,generation=r.generation,seed_records=1928,
                original_thresholds=True,repair_applied=False,material_executions=0)
        finally:
            owner.close()
            assert all(f.done() for f in accepted) and not owner.thread.is_alive()
