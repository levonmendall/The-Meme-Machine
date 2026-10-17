"""Same native FULL/ACK restoration plus fixed concurrent writer, offline only."""
from contextlib import closing
import hashlib
import gc
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from operational import pump_restore_benchmark as native
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational.offline import install_network_guard
from meme_machine.runtime import candidate_history, operation_costs


def io():
    return {key: int(value) for key, value in
        (row.split(': ', 1) for row in Path('/proc/thread-self/io').read_text().splitlines())}


def delta(before, after):
    return {k: delta(before.get(k, {}), v) if isinstance(v, dict) else v - before.get(k, 0)
        for k, v in after.items() if type(v) in (dict, int, float)}


def run(output):
    if sys.version_info[:3] != (3, 12, 14): raise ValueError('benchmark_pinned_python_required')
    install_network_guard(); os.environ['MM_OPERATION_COST_DIAGNOSTICS'] = '1'
    collections = dict(calls=0, wall_microseconds=0, cpu_microseconds=0)
    started = None
    def collected(phase, info):
        nonlocal started
        if phase == 'start': started = time.perf_counter_ns(), time.process_time_ns()
        elif started is not None:
            wall, cpu = started; started = None
            collections['calls'] += 1
            collections['wall_microseconds'] += (time.perf_counter_ns()-wall)//1000
            collections['cpu_microseconds'] += (time.process_time_ns()-cpu)//1000
    # Observe existing interpreter work; do not collect, disable, tune or defer
    # it. These counters discriminate total-CPU variability across fixed runs.
    gc.callbacks.append(collected)
    output = Path(output).resolve()
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_evidence_service import FinalizedFence
    from meme_machine.solana_selective_source import install, commit_control
    from meme_machine.solana_candidate_join import YellowstoneTransactionFrame
    from meme_machine.solana_scoped_retirement import ScopedRetirement
    from meme_machine.yellowstone import geyser_pb2 as pb
    try: paged = importlib.import_module('meme_machine.runtime.candidate_restore_reads')
    except ModuleNotFoundError: paged = None
    with Scratch() as scratch:
        counts = dict(archive_opens=0, archive_bytes_offered=0, network_calls=0)
        def audit(event, args):
            if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo'):
                counts['network_calls'] += 1; raise RuntimeError('benchmark_network_forbidden')
            if event == 'sqlite3.connect':
                value = os.fsdecode(args[0]).removeprefix('file:').split('?', 1)[0]
                if not Path(value).resolve().is_relative_to(scratch.path):
                    raise RuntimeError('benchmark_foreign_database_forbidden')
            if event == 'open' and not isinstance(args[0], int):
                path = Path(os.fsdecode(args[0])).resolve()
                if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
                    if path != output and not path.is_relative_to(scratch.path):
                        raise RuntimeError('benchmark_foreign_write_forbidden')
                elif path.suffix == '.zlib' and path.is_relative_to(scratch.path):
                    counts['archive_opens'] += 1; counts['archive_bytes_offered'] += path.stat().st_size
        sys.addaudithook(audit)
        legacy = scratch.path / 'legacy'; (legacy / 'shared').mkdir(parents=True)
        corpus = native.capture_fixture(Path.cwd(), 16, 32, 64, 0)
        built = native.build_history(corpus, legacy / 'shared'); built['restore_at'] = corpus['restore_at']
        with closing(EvidenceWriter(built['source'], clock=lambda: corpus['clock'])) as writer:
            h = install(SimpleNamespace(writer=writer, fence=FinalizedFence(writer, endpoint_identity=corpus['endpoint_identity'])))
            h.clock = h.lifecycle.clock = lambda: corpus['clock']
            with closing(candidate_history.CandidateHistory(built['consumer'])) as shared:
                candidates = shared.candidates(lane='pump', event_prefix='pump_')
            for row in candidates[:12]: ScopedRetirement(h).restore('pump', row['candidate'])
        relocated = scratch.path / 'aws'; legacy.rename(relocated)
        built.update(source=relocated / 'shared/solana-evidence.sqlite', consumer=relocated / 'shared/solana-candidate-history.sqlite')
        consumer_before = native.rows_digest(built['consumer'])
        stopped = threading.Event(); ready = threading.Event()
        requested = threading.Event(); completed = threading.Event(); errors = []
        writer_facts = dict(commits=0, checkpoints=0, checkpoint_busy=0, checkpoint_remaining_peak=0)
        def write():
            try:
                with closing(EvidenceWriter(built['source'], clock=lambda: corpus['clock'])) as writer:
                    state = SimpleNamespace(writer=writer, fence=FinalizedFence(writer, endpoint_identity=corpus['endpoint_identity']))
                    install(state); ready.set()
                    for n in range(1, 4001):
                        while not requested.wait(.05):
                            if stopped.is_set(): return
                        requested.clear()
                        if stopped.is_set(): return
                        slot = 100 + len(corpus['frames']) + n
                        update = pb.SubscribeUpdate(); block = update.block
                        block.slot = slot; block.parent_slot = slot - 1
                        block.blockhash = str(slot); block.parent_blockhash = str(slot - 1)
                        block.block_time.timestamp = corpus['clock'] + n
                        commit_control(state, YellowstoneTransactionFrame(update, update.ByteSize(), corpus['clock'] + n, replay_from_slot=100))
                        writer_facts['commits'] += 1
                        if n % 8 == 0:
                            busy, log, done = writer.db.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
                            writer_facts['checkpoints'] += 1; writer_facts['checkpoint_busy'] += busy
                            writer_facts['checkpoint_remaining_peak'] = max(writer_facts['checkpoint_remaining_peak'], log - done)
                        completed.set()
            except BaseException as error: errors.append(type(error).__name__); ready.set()
        result = dict(schema='pump-reference-page-cost-v1', scope=native.SCOPE,
            source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
            benchmark_generation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            python=sys.version, sqlite=sqlite3.sqlite_version, fixture_sha256=native.digest(corpus),
            runtime_source_sha256={p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (
                'meme_machine/runtime/candidate_history.py', 'meme_machine/lanes/pump/runner.py',
                'meme_machine/solana_evidence_storage.py', 'meme_machine/runtime/candidate_restore_reads.py') if Path(p).is_file()},
            reader='bounded_acquisition' if paged is not None else 'original_scalar',
            candidates=16, references=built['references'], financial_state_access=False,
            writer_schedule='One actual native FULL control commit before every16th reference; PASSIVE checkpoint every8th commit.',
            production_capacity_proven=False, cases=[])
        with patch.object(candidate_history, 'RETAINED_REFERENCE_LEGACY_ROOT', legacy), \
                patch.object(candidate_history, 'RETAINED_REFERENCE_AWS_ROOT', relocated), \
                patch.dict(os.environ, MM_MODE='PAPER', MM_PAPER_EPOCH=candidate_history.RETAINED_REFERENCE_EPOCH,
                    MM_STATE_ROOT=str(relocated), MM_SOLANA_EVIDENCE_PLANE_DB=str(built['source'])):
            thread = threading.Thread(target=write, name='fixture-native-full-writer'); thread.start()
            try:
                if not ready.wait(5): raise ValueError('benchmark_writer_start_timeout')
                if errors: raise ValueError('benchmark_native_writer_failed:'+errors[0])
                original_ref = candidate_history.CandidateHistory._reference_body
                original_connect = candidate_history.diagnostic_connect
                for run in range(6):
                    references = [0]; queries = dict(canonical=0, manifest=0, chunk=0, begin=0, rollback=0, fallback_references=0)
                    def trace(sql):
                        for key, text in (('canonical','FROM canonical_evidence'), ('manifest','FROM scoped_cold_manifests'),
                                          ('chunk','FROM hot_chunks'), ('begin','BEGIN'), ('rollback','ROLLBACK')):
                            if text in sql: queries[key] += 1
                    def connect(*args, **kwargs):
                        db = original_connect(*args, **kwargs)
                        if kwargs.get('diagnostic_role') in ('candidate_reference', 'candidate_restore_reference'):
                            db.set_trace_callback(trace)
                        return db
                    def reference(self, *args, **kwargs):
                        references[0] += 1
                        lookup = kwargs.get('_restore_lookup')
                        if lookup is not None and lookup.fallback: queries['fallback_references'] += 1
                        if references[0] % 16 == 0:
                            completed.clear(); requested.set()
                            if not completed.wait(2): raise ValueError('benchmark_native_writer_commit_timeout')
                        return original_ref(self, *args, **kwargs)
                    before_writer = dict(writer_facts); before_io = io(); before_costs = operation_costs.snapshot()['rows']
                    before_collections = dict(collections)
                    with patch.object(candidate_history, 'diagnostic_connect', connect), \
                            patch.object(candidate_history.CandidateHistory, '_reference_body', reference):
                        if paged is None: measured = native.restore_pass(built, counts)
                        else:
                            with patch.object(paged, 'connect', connect): measured = native.restore_pass(built, counts)
                    after_io = io(); after_costs = operation_costs.snapshot()['rows']
                    measured.update(source_queries=queries, actual_references=references[0],
                        native_writer_commits=writer_facts['commits']-before_writer['commits'],
                        native_writer_checkpoints=writer_facts['checkpoints']-before_writer['checkpoints'],
                        gc_delta=delta(before_collections,collections),
                        reader_thread_io_delta={k: after_io[k]-before_io[k] for k in before_io},
                        operation_delta=delta(before_costs.get('pump.observed_candidate_events', {}),
                            after_costs.get('pump.observed_candidate_events', {})))
                    result['cases'].append(measured)
                    output.write_text(json.dumps(result, sort_keys=True, indent=2)+'\n')
                    print(json.dumps(dict(case=run, wall=measured['wall_seconds'], queries=queries)), flush=True)
                    scratch.check()
            finally:
                stopped.set(); thread.join(5)
                if thread.is_alive(): raise ValueError('benchmark_writer_join_timeout')
        if errors: raise ValueError('benchmark_native_writer_failed:'+errors[0])
        if any(c['actual_references'] != 1024 or c['native_writer_commits'] != 64 or c['native_writer_checkpoints'] != 8 for c in result['cases']):
            raise ValueError('benchmark_same_workload_mismatch')
        if len({c['output_sha256'] for c in result['cases']}) != 1: raise ValueError('benchmark_economics_mismatch')
        result.update(writer=writer_facts, network_calls=counts['network_calls'], consumer_unchanged=native.rows_digest(built['consumer']) == consumer_before)
        if not result['consumer_unchanged']: raise ValueError('benchmark_consumer_history_mutated')
        output.write_text(json.dumps(result, sort_keys=True, indent=2)+'\n'); scratch.check(); scratch.success=True


if __name__ == '__main__': run(sys.argv[1])
