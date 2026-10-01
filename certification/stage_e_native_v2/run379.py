"""Bounded native proof of non-aging setup; full dense pressure stays disabled."""
from pathlib import Path
import json
from .clock import DeterministicClock
from .contract import sha256
from .fixtures import build_frame,spec
from .native import native_state,empty_frame,source,snapshot


def bounded_setup_witness(output):
    from meme_machine import solana_evidence_service as service
    from meme_machine.solana_evidence_transport import Subscription
    from meme_machine.solana_maintenance_runtime import MaintenanceRuntime
    clock=DeterministicClock();s=spec('run379')
    # Exactly 200 seed transactions (2 instead of 160 per historical frame)
    # and 6 execution transactions; independent bounded construction identity.
    seeds=tuple(build_frame('run379',n,bounded=True,historical_seed=True) for n in range(100))
    live=tuple(build_frame('run379',n,bounded=True) for n in range(3))
    epoch=(clock.time(),clock.monotonic())
    assert clock.elapsed_us==0 and not clock.executing
    path=Path(output)/'run379-setup.sqlite'
    with native_state(path,clock) as state:
        targets=tuple(sorted({sub.address for sub in service.program_subscriptions()}))
        sub=Subscription('service','all','all','blocks',4)
        for raw in seeds:
            at=json.loads(raw)['params']['result']['value']['block']['blockTime']
            seen=at+1
            decoded,_,_=service.decode_source_message(raw,'',targets,state.fence.endpoint_identity,seen)
            state.source(sub,decoded,seen,len(raw))
            assert epoch==(clock.time(),clock.monotonic())
        source(state,empty_frame(1100,clock.wall_epoch),clock)
        seeded=snapshot(path);assert len(seeded['records'])==200 and seeded['gaps']==0
        runtime=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
        observation=runtime.adapter.observe(runtime.generation)
        hot=sum(scope.hot_eligible for scope in observation.scopes)
        assert hot==200
        original={r['identity']:(r['event_at'],r['first_seen']) for r in seeded['records']}
        assert all(at<clock.wall_epoch-180 and seen<clock.wall_epoch for at,seen in original.values())
        clock.begin()
        for n,raw in enumerate(live):
            clock.advance_to(n*s['cadence_us']);source(state,raw,clock)
        after=snapshot(path)
        assert after['gaps']==0
        for row in after['records']:
            if row['identity'] in original:
                assert original[row['identity']]==(row['event_at'],row['first_seen'])
        observation=runtime.adapter.observe(runtime.generation)
        runtime.clock.check(clock.time(),clock.monotonic(),{row.scope:row.source_time for row in observation.scopes})
        assert len(after['records'])==206
        return dict(generation=runtime.generation,setup_elapsed_us=0,setup_epoch=list(epoch),
            constructed_seed_frames=100,bounded_seed_transactions=200,bounded_execution_transactions=6,
            execution_elapsed_us=clock.elapsed_us,native_hot_debt=hot,source_continuity=True,
            original_availability_preserved=True,timestamps_refreshed=False,episodes_reenrolled=False,
            seed_input_hashes=[sha256(raw) for raw in seeds],execution_input_hashes=[sha256(raw) for raw in live],
            full_shape_executed=False,integrity=after['integrity'])
