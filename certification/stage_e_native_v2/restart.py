"""Finite generation and restart qualification, without modifying runtime."""
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path

from .clock import DeterministicClock
from .contract import canonical
from .native import native_state, source, empty_frame, snapshot


def records(clock, scope, count, tag, *, account=False):
    from meme_machine.solana_evidence_plane import FinalizedRecord
    from .fixtures import signature
    return [FinalizedRecord(identity=f'v2:{tag}:{scope}:{i}',scope=scope,slot=10+i,
        signature='' if account else signature(f'{tag}:{scope}:{i}'),program='native-fixture',
        addresses=('native-fixture-address',),market_time=int(clock.time())-185,
        payload={'bounded_fixture':tag,'index':i},source='alchemy_finalized_stream',
        endpoint_identity='a'*64,observed_at=clock.time(),kind='account' if account else 'transaction',
        transaction_index=None if account else i) for i in range(count)]


def check_generations(output):
    from meme_machine.solana_evidence_plane import EvidenceWriter, EvidenceUnavailable
    from meme_machine.solana_maintenance_runtime import MaintenanceRuntime, ArchiveFlight
    path=Path(output)/'generation.sqlite'; clock=DeterministicClock(); clock.begin()
    rejected=[]
    with native_state(path,clock) as state:
        runtime=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
        state.writer.ingest(records(clock,'program:meteora',2,'generation'))
        plan,receipt=EvidenceWriter.prepare_and_write_archive(path,state.archive_plan())
        old=runtime.generation
        state.fence.disconnect('deterministic_generation_change')
        try:runtime.turn(ArchiveFlight(),clock.monotonic())
        except EvidenceUnavailable as exc:rejected.append(str(exc))
        else:raise AssertionError('stale_decision_accepted')
        fresh=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
        for kind in ('stale_receipt','stale_worker'):
            future=Future();future.set_result((plan,receipt))
            flight=ArchiveFlight(generation=old,submitted=clock.monotonic(),
                pending=(plan,receipt) if kind=='stale_receipt' else None,
                future=future if kind=='stale_worker' else None)
            fresh=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
            try:fresh.turn(flight,clock.monotonic())
            except EvidenceUnavailable as exc:rejected.append(str(exc))
            else:raise AssertionError(kind+'_accepted')
        assert snapshot(path)['counters'].get('archived_records',0)==0
        return dict(old_generation=old,new_generation=state.fence.session,rejected=rejected,
            stale_records_committed=0,integrity=snapshot(path)['integrity'])


def check_restart(output):
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_maintenance_runtime import MaintenanceRuntime
    path=Path(output)/'restart.sqlite';clock=DeterministicClock();clock.begin()
    scope='program:meteora'
    with native_state(path,clock) as state:
        # 1002 is the smallest native excess above the unchanged 1000 envelope.
        state.writer.ingest(records(clock,scope,1002,'restart'))
        sub=next(s for s in __import__('meme_machine.solana_evidence_service',fromlist=['program_subscriptions']).program_subscriptions() if s.scope==scope)
        state.fence.block(sub, __import__('json').loads(empty_frame(2000,int(clock.time()))),clock.time())
        r=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
        r._demands(r.adapter.observe(r.generation))
        episode_before=snapshot(path)['episodes'];assert episode_before
        plan,receipt=EvidenceWriter.prepare_and_write_archive(path,state.archive_plan())
        incomplete_before=snapshot(path)
        # Publication alone is not service; commit exactly one native 512 slice.
        assert incomplete_before['counters'].get('archived_records',0)==0
        remaining=state.archive_commit_slice(plan,receipt)
        committed=snapshot(path); old_generation=state.fence.session
        assert committed['counters']['archived_records']==512 and remaining
        # A rolled-back native attempt does not add durable service.
        try:
            with state.writer.transaction():
                state.writer.commit_archive(remaining,receipt)
                raise RuntimeError('qualification_injected_rollback')
        except RuntimeError:pass
        assert snapshot(path)['counters']['archived_records']==512
    clock.advance_to(1_000_000)
    with native_state(path,clock) as state:
        r=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
        after=snapshot(path)
        assert state.fence.session!=old_generation
        assert after['episodes']==episode_before and after['progress']==committed['progress']
        # Reconstruct from native records and durable ledger; old worker carriers
        # stay fenced. Existing receipt is continued by the current owner API.
        state.archive_commit_slice(remaining,receipt)
        resumed=snapshot(path)
        assert resumed['counters']['archived_records']==len(plan)
        state.archive_commit_slice(remaining,receipt)
        assert snapshot(path)['counters']['archived_records']==len(plan)
        archived=snapshot(path)
        # Program restart conservatively creates a gap. Native retention must
        # preserve that safety pin rather than fabricate completed continuity.
        state.retention();retired=snapshot(path)
        assert retired['integrity']=='ok' and retired['gaps']>0
        assert retired['counters'].get('compacted_records',0)>0
        before_again=retired['counters'].get('compacted_records',0)
        state.retention();assert snapshot(path)['counters'].get('compacted_records',0)==before_again
        return dict(committed_service_before=committed['progress'],reconstructed_ledger=after['progress'],
            episode_before=episode_before,episode_after=after['episodes'],
            incomplete_service_not_credited=True,no_duplicate_completion=True,no_lost_completion=True,
            archive_receipt_continued=True,retirement_continued=True,restart_gap_preserved=True,
            old_generation=old_generation,new_generation=state.fence.session,integrity='ok',
            record_count=1002,archived=archived['counters']['archived_records'],
            retired=retired['counters'].get('compacted_records',0))
