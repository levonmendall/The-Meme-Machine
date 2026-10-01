"""Full shapes are implemented and disabled for Q2, even via the direct API."""
from pathlib import Path

from .clock import DeterministicClock
from .firewall import classification
from .fixtures import build_frame, spec
from .native import native_state, source, empty_frame, snapshot


def construct_full_fixture(run):
    """Construction is also classified before allocating full pressure bodies."""
    classification(run+'-full')  # MATERIAL_PRESSURE: always raises in this Q2 contract.
    s=spec(run);clock=DeterministicClock()
    frames=tuple(build_frame(run,n) for n in range(s['frames']))
    seeds=tuple(build_frame(run,n,historical_seed=True) for n in range(s.get('setup_debt_frames',0)))
    assert clock.elapsed_us==0 and not clock.executing
    return clock,frames,seeds


def execute_full_fixture(run, output):
    classification(run+'-full')
    # Retained code is intentionally unreachable under the Q2 firewall. This
    # synchronous deterministic replay can verify native shape/progress, but
    # does not replace the separately required throughput/capacity profiles.
    clock,frames,seeds=construct_full_fixture(run);s=spec(run)
    with native_state(Path(output)/'full.sqlite',clock) as state:
        # Historical seed availability is fixed historical evidence, never
        # refreshed to the execution epoch. Source state is then advanced by a
        # real linked empty finalized block at the declared epoch.
        from meme_machine import solana_evidence_service as service
        from meme_machine.solana_evidence_transport import Subscription
        import json
        for raw in seeds:
            seen=json.loads(raw)['params']['result']['value']['block']['blockTime']+1
            targets=tuple(sorted({sub.address for sub in service.program_subscriptions()}))
            decoded,_,_=service.decode_source_message(raw,'',targets,state.fence.endpoint_identity,seen)
            state.source(Subscription('service','all','all','blocks',4),decoded,seen,len(raw))
        if seeds:
            source(state,empty_frame(s['start_slot']-1,clock.wall_epoch),clock)
        clock.begin()
        samples=[]
        for n,raw in enumerate(frames):
            clock.advance_to(n*s['cadence_us']);source(state,raw,clock)
            if run=='run379':
                from meme_machine.solana_maintenance_runtime import MaintenanceRuntime,ArchiveFlight
                if n==0:r=MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time);flight=ArchiveFlight()
                result=r.turn(flight,clock.monotonic())
                if result['snapshot']:
                    from meme_machine.solana_evidence_plane import EvidenceWriter
                    plan,receipt=EvidenceWriter.prepare_and_write_archive(state.writer.path,result['snapshot'])
                    from concurrent.futures import Future
                    done=Future();done.set_result((plan,receipt));flight.attach(done,clock.monotonic(),r.generation)
            samples.append(snapshot(state.writer.path))
        return samples
