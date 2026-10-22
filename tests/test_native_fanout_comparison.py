"""Actual native intake with inline versus pre-intake envelopes, in disposable offline stores.

The False arm is the retained 806 inline queue_records behavior; True selects
the pre-intake envelope preparation capability. This is an instrumented subsystem comparison,
not live capacity, RPC/WS acquisition, process-transfer or strategy acceptance.
No normalized original-window parcel, invented quote or financial command is
used. Receipt availability uses a fixed test clock; stage costs use real clocks.
"""
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import wraps
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import based58

from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.solana_candidate_join import CandidateTransactionJoin, scope_labels
from meme_machine.solana_economic_preparation import prepare_candidate_frames
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_history_delivery import capture_context, generation
from meme_machine.solana_history_notifications import install as notifications, delivery_hint
from meme_machine.solana_preparation_pool import PreparationPool
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import CandidateCommitQueue, SelectiveSource, source_work
from meme_machine.yellowstone import geyser_pb2 as pb
from tests.test_publication_accounting_turn import OwnedWork
from tests.test_solana_closure import NOW, state_at
from tests.test_solana_selective_evidence import FIXTURE


BASELINE = '806e5087e17426a15a1f4ecbe5f69964a7215af9'
ADDRESSES = {PROGRAMS[f]: program_scope(f) for f in ('pump', 'pumpswap')}


def native_frames(count=8):
    """Real join: captured complete logs + matching native statuses/finality.

    Slot/signature/index coordinates are deterministic fixture transformations;
    the captured event/log bodies remain unchanged. This exercises body-free
    native validation and real decoding, not the HTTP repair or provider path.
    """
    join = CandidateTransactionJoin(ADDRESSES, (), filtered_from_slot=100,
                                    clock=lambda: 0.)
    frames = []
    labels = scope_labels(ADDRESSES)
    for slot in range(100, 100 + count):
        transactions = [(family, tx) for family in ('pump', 'pumpswap') for tx in FIXTURE[family]]
        for index, (family, original) in enumerate(transactions):
            signature = based58.b58encode((slot * 100 + index).to_bytes(64, 'little')).decode()
            result = join.feed_log(slot, signature, copy.deepcopy(original['meta']['logMessages']), None, NOW)
            if result is not None:frames.append(result)
            update = pb.SubscribeUpdate(filters=[labels[program_scope(family)]])
            status = update.transaction_status
            status.slot = slot; status.index = index
            status.signature = based58.b58decode(signature.encode())
            result = join.feed(update, update.ByteSize(), NOW)
            if result is not None:frames.append(result)
        update = pb.SubscribeUpdate(filters=['b']); meta = update.block_meta
        meta.slot = slot; meta.parent_slot = slot - 1
        meta.blockhash = str(slot); meta.parent_blockhash = str(slot - 1)
        meta.block_time.timestamp = int(NOW)
        meta.executed_transaction_count = len(transactions)
        result = join.feed(update, update.ByteSize(), NOW)
        if result is not None:frames.append(result)
        update = pb.SubscribeUpdate(filters=['f'])
        update.slot.slot = slot; update.slot.parent = slot - 1; update.slot.status = pb.SLOT_FINALIZED
        result = join.feed(update, update.ByteSize(), NOW)
        if result is not None:frames.append(result)
    if [f.update.block.slot for f in frames] != list(range(100, 100 + count)):
        raise AssertionError('native_fixture_not_exactly_joined')
    return tuple(frames)


class MeasuredExecutor:
    """Only observes calls to the actual worker functions, without replacing them."""
    def __init__(self, workers, name):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)
        self.costs = {}; self.lock = threading.Lock()

    def submit(self, function, *args, **kwargs):
        submitted = time.perf_counter_ns()
        name = function.__module__ + '.' + getattr(function, '__name__', type(function).__name__)
        def measured():
            started = time.perf_counter_ns(); cpu = time.thread_time_ns()
            try:return function(*args, **kwargs)
            finally:
                with self.lock:
                    row = self.costs.setdefault(name, Counter())
                    row.update(calls=1, queue_nanoseconds=started-submitted,
                               service_wall_nanoseconds=time.perf_counter_ns()-started,
                               service_cpu_nanoseconds=time.thread_time_ns()-cpu)
        return self.pool.submit(measured)

    def shutdown(self, wait=True, *, cancel_futures=False):
        self.pool.shutdown(wait=wait, cancel_futures=cancel_futures)


def coherent_counts(path):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, isolation_level=None, timeout=0)) as db:
        db.execute('PRAGMA query_only=ON')
        return db.execute('SELECT (SELECT count(*) FROM canonical_evidence),'

            '(SELECT count(*) FROM candidate_history_outbox WHERE consumed IS NULL),'
            '(SELECT count(*) FROM candidate_pending_proofs)').fetchone()


def semantic_cut(state):
    """Authenticate real native/ref bodies before rebinding only their file locator."""
    db = state.writer.db; life = state.selective.lifecycle
    tables = {
        'canonical': 'SELECT identity,hash,first_seen,slot,transaction_index,event_index FROM canonical_evidence ORDER BY identity',
        'economic': 'SELECT * FROM rolling_economic_events ORDER BY identity',
        'order': 'SELECT * FROM native_order_attestations ORDER BY scope,slot,signature',
        'discovery': 'SELECT * FROM candidate_outbox ORDER BY sequence',
        'blocks': 'SELECT * FROM candidate_blocks ORDER BY scope',
        'delivery': 'SELECT id,family,address,kind,body,hash,created,consumed,priority FROM candidate_history_outbox ORDER BY id',
        'proofs': 'SELECT * FROM candidate_pending_proofs ORDER BY id',
        'coverage': 'SELECT * FROM candidate_coverage ORDER BY scope,lo',
        'checkpoints': 'SELECT * FROM candidate_checkpoints ORDER BY scope',
        'gaps': 'SELECT * FROM candidate_gaps ORDER BY id',
    }
    result = {name:list(db.execute(sql)) for name, sql in tables.items()}
    if db.execute('SELECT count(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone() != (0,):
        raise AssertionError('native_comparison_unacked_outbox')
    with closing(CandidateHistory(life.path, clock=lambda: NOW)) as history:
        references = []
        for lane, candidate, identity, kind, raw, checksum in history.db.execute(
                'SELECT lane,candidate,identity,kind,body,hash FROM canonical_event_refs ORDER BY lane,candidate,identity'):
            if hashlib.sha256(raw.encode()).hexdigest() != checksum:
                raise AssertionError('native_comparison_reference_hash')
            body = json.loads(raw)
            if body['path'] != str(state.writer.path.resolve()):
                raise AssertionError('native_comparison_reference_path')
            # Exercise the real canonical source reader before normalizing the
            # fresh private path. No native hash, event or receipt is changed.
            history.event(lane, candidate, identity)
            body['path'] = '@private-canonical'
            references.append((lane, candidate, identity, kind, body))
        result['references'] = references
        result['candidates'] = list(history.db.execute('SELECT * FROM candidates ORDER BY lane,candidate'))
        receipts = []
        for identity, family, address, kind, at, raw, checksum in history.db.execute(
                'SELECT * FROM source_receipts ORDER BY id'):
            if hashlib.sha256(raw.encode()).hexdigest() != checksum:
                raise AssertionError('native_comparison_receipt_hash')
            body = json.loads(raw)
            if kind == 'coverage':
                if body['generation'] != json.loads(json.dumps(generation(life))):
                    raise AssertionError('native_comparison_receipt_source_identity')
                # Each private file necessarily has a different inode. Verify
                # that real identity first; normalize only these two locator
                # coordinates, never proof, recipient, timestamp or hash input.
                body['generation'] = [*body['generation'][:2], '@device', '@inode']
            receipts.append((identity, family, address, kind, at, body))
        result['receipts'] = receipts
        for table in ('funding', 'decisions'):
            if history.db.execute('SELECT count(*) FROM '+table).fetchone() != (0,):
                raise AssertionError('native_comparison_financial_state')
    return result


async def run_native_arm(path, frames, *, prepared, restart_before_ack=False):
    """Same bounded arrival schedule, actual owner/queues, and strict terminal cut."""
    from meme_machine import solana_history_delivery as delivery
    from meme_machine.solana_candidate_lifecycle import CandidateLifecycle
    from meme_machine import solana_economic_preparation as economic
    products, _ = prepare_candidate_frames(frames, ADDRESSES, 'matched-native-session', 'a'*64)
    expected = {row.record.identity:row for product in products for row in product.rows}
    source = owner = work = None; tasks = []; samples = []; stage_counts = []; pipelines = []
    gate = asyncio.Event(); ready = asyncio.Event(); done = asyncio.Event()
    offered = committed = 0; intake_peak = 0; restart_pending = None; restart_reserved = None
    sample_count = 0; peaks = Counter(); probe_count = Counter(); outbox_paths = Counter()
    preparation_results = Counter(); preparation_result_lock = threading.Lock()
    loop = asyncio.get_running_loop()
    preparation = MeasuredExecutor(2, 'native-comparison-preparation')
    delivery_executor = MeasuredExecutor(1, 'native-comparison-delivery')
    pool = PreparationPool(preparation)
    receipt_clock = SimpleNamespace(monotonic=lambda: 0., thread_time=time.thread_time)

    def factory():
        state, history = state_at(path)
        history.lifecycle.delivery_separated = True
        # The actual binding API freezes several alias recipients per economic
        # input, so 64-row publication pages differ from native event counts.
        for prepared in expected.values():
            row = prepared.record
            family = row.scope.split(':')[1]
            market = row.payload['event'].get('mint' if family == 'pump' else 'pool')
            for number in range(2):
                alias = based58.b58encode(hashlib.sha256((family+market+str(number)).encode()).digest()).decode()
                history.bind(family, alias, market_address=market)
        state.close = state.writer.close
        return state

    async def open_source():
        nonlocal owner, source, work
        owner = PriorityOwner(factory)
        await asyncio.shield(asyncio.wrap_future(owner.ready))
        source = SelectiveSource(SimpleNamespace(identity='a'*64, credential='offline'), None)
        source.stop = asyncio.Event(); source.batched = True; source.history_separated = True
        source.canonical_path = str(path); source.preparation_executor = pool.native
        source.delivery_executor = delivery_executor
        work = OwnedWork(owner)
        work.candidate_delivery_capture_actor = True
        work.candidate_delivery_publication_handoff = True
        work.candidate_outbox_preparation = prepared
        source.work = source_work(work, source.stop)
        def seed(state):
            history = state.selective
            notifications(history, loop, source.history_changed, capture_hints=True)
            return capture_context(history.lifecycle), delivery_hint(history)
        context, hint = await source.work(seed, 0)
        source.delivery_capture_context = context; source._history_delivery_hint(hint)
        def sample():
            nonlocal sample_count
            counts = coherent_counts(path)
            sample_count += 1
            point = dict(elapsed_ns=time.perf_counter_ns()-started, offered_frames=offered,
                committed_frames=committed, canonical_records=counts[0], delivery_obligations=counts[1], pending_proofs=counts[2])
            for key in ('delivery_obligations', 'pending_proofs'):
                peaks[key] = max(peaks[key], point[key])
            if len(samples) < 128:samples.append(point)
            else:samples[-1] = point
        def returned(label, component):
            if label in ('source_commit', 'candidate_delivery_ack'):sample()
        work.returned = returned
        if restart_before_ack and restart_pending is None:
            async def before(number, label, component):
                if label == 'candidate_delivery_ack':
                    # Gate only AFTER real canonical consumer FULL, before its
                    # owner ACK admission; scout-only metadata cannot satisfy it.
                    target = Path(source.delivery_capture_context.candidate_path)
                    with closing(sqlite3.connect(target.as_uri()+'?mode=ro',uri=True,timeout=0)) as db:
                        schema = db.execute("SELECT 1 FROM sqlite_master WHERE name='canonical_event_refs'").fetchone()
                        delivered = bool(schema and db.execute('SELECT count(*) FROM canonical_event_refs').fetchone()[0])
                    if delivered:ready.set(); await gate.wait()
            work.before = before
        tasks.extend((asyncio.create_task(source.candidate_history_delivery()),
                      asyncio.create_task(source.publish_history())))

    def check_workers():
        for task in tasks:
            if task.done():
                task.result(); raise AssertionError('native_comparison_worker_stopped')

    async def settled():
        while True:
            check_workers()
            counts = coherent_counts(path)
            if counts[1:] == (0, 0):return
            await asyncio.sleep(.005)

    async def owner_probes():
        # Real owner admissions competing with intake/fanout. These are fixed
        # nonfinancial fixture operations, not a claim to exercise live held
        # quotes or the production maintenance ticket/archival protocol.
        probe_started = loop.time()
        for number in range(len(frames)):
            await asyncio.sleep(max(0, probe_started+number*.002-loop.time()))
            await source.work(lambda state:state.writer.db.execute(
                'SELECT count(*) FROM canonical_evidence').fetchone(), 0, label=None)
            probe_count['priority_zero_calls'] += 1
            def maintenance(state):
                with state.writer.transaction():
                    state.writer.db.execute("INSERT OR REPLACE INTO service_health VALUES('fixture_maintenance','1')")
            await source.work(maintenance, 4, label=None)
            probe_count['priority_four_calls'] += 1

    async def late_scout_and_promotion():
        # Use the actual lifecycle producers after canonical FULL/ACK. The
        # existing promotion precedence must survive on the very same mint.
        mint = next(row.record.payload['event']['mint'] for row in expected.values()
                    if row.record.scope == 'program:pump')
        def scout(state):
            state.selective.observe('pump', mint, slot=frames[-1].update.block.slot,
                seen=NOW, signature='captured-native-late-locator',
                fields=dict(economic_event=False, history_complete=False, complete=False))
        await source.work(scout, 2, label='source_commit', component='scout')
        await settled()
        promoted = await source.work(lambda state:state.selective.lifecycle.promote(
            'pump', mint, deadline=NOW+45), 2, label='source_commit', component='scout')
        if promoted is None:raise AssertionError('native_comparison_promotion_not_exercised')
        await settled()

    async def close_source():
        nonlocal owner
        if owner is None and not tasks:return
        if source is not None:
            source.stop.set()
            for pulse in (source.history_wakeup, source.delivery_wakeup):pulse.notify()
        for task in tasks:task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True); tasks.clear()
        stage_counts.append(dict(work.counts) if work is not None else {})
        if source is not None:pipelines.append(copy.deepcopy(source.pipeline_metrics))
        if owner is not None:
            await asyncio.to_thread(owner.close); owner = None
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):raise result

    original_prepare = economic.prepare_candidate_frames
    @wraps(original_prepare)
    def observed_prepare(*args, **kwargs):
        answer = original_prepare(*args, **kwargs)
        with preparation_result_lock:
            preparation_results['native_preparation_calls'] += 1
            preparation_results['prepared_outbox_records'] += sum(len(frame.outbox) for frame in answer[0])
            mode = 'inline_calls' if threading.current_thread() is threading.main_thread() else 'worker_calls'
            preparation_results[mode] += 1
        return answer

    original_emit = CandidateLifecycle.emit_raw
    def observed_emit(life, *args, **kwargs):
        answer = original_emit(life, *args, **kwargs)
        if kwargs.get('_prepared') is not None:outbox_paths['fresh_owner_validated_prepared_hits'] += 1
        return answer

    started = time.perf_counter_ns(); cpu = time.process_time_ns()
    try:
        # Replace this module's time BINDING, never time.monotonic globally.
        # Only delivery receipt availability is fixed. Timers in PriorityOwner,
        # source scheduling and MeasuredExecutor remain their actual clocks.
        with (patch.object(delivery, 'time', receipt_clock),
              patch.object(CandidateLifecycle, 'emit_raw', observed_emit),
              patch.object(economic, 'prepare_candidate_frames', observed_prepare)):
            async with asyncio.timeout(30):
                await open_source()
                queue = CandidateCommitQueue()
                def census(accepted, completed):
                    nonlocal committed, intake_peak
                    committed += completed
                    intake_peak = max(intake_peak, offered-committed)
                queue.changed = census
                consumer = asyncio.create_task(source.candidate_commits(queue, ADDRESSES,
                    'matched-native-session', producer_done=done))
                probing = asyncio.create_task(owner_probes())
                try:
                    arrival_started = loop.time()
                    for number, frame in enumerate(frames):
                        await asyncio.sleep(max(0, arrival_started+number*.002-loop.time()))
                        offered += 1; intake_peak = max(intake_peak, offered-committed)
                        await queue.put(frame)
                    done.set()
                    await consumer
                    await probing
                    if queue.count or committed != len(frames):raise AssertionError('native_comparison_intake_unsettled')
                    if restart_before_ack:
                        await ready.wait()
                        def reserved(state):
                            db = state.writer.db
                            return db.execute('SELECT (SELECT count(*) FROM canonical_evidence),'
                                '(SELECT count(*) FROM candidate_history_outbox WHERE consumed IS NULL),'
                                '(SELECT count(*) FROM candidate_pending_proofs)').fetchone()
                        restart_pending = await source.work(reserved, 0, label=None)
                        if restart_pending[0] != len(expected) or restart_pending[1] == 0:
                            raise AssertionError('native_comparison_restart_cut_not_exercised')
                        # Cancel before ACK admission: unlike a normal accepted
                        # owner callback there is no permission to manufacture an
                        # ACK. Durable outbox + consumer receipts drive restart.
                        await close_source()
                        await open_source()
                    await settled()
                    await late_scout_and_promotion()
                finally:
                    gate.set()
                    if not consumer.done():consumer.cancel()
                    if not probing.done():probing.cancel()
                    await asyncio.gather(consumer, probing, return_exceptions=True)
                # Freeze measured costs BEFORE semantic/reopen verification.
                # Background capture may finish between these short snapshots;
                # this is a checkpoint, not an atomic cross-thread census.
                with preparation.lock:measured_preparation = copy.deepcopy(preparation.costs)
                with delivery_executor.lock:measured_delivery = copy.deepcopy(delivery_executor.costs)
                measured_owner = copy.deepcopy(stage_counts+[dict(work.counts)])
                measured_pipelines = copy.deepcopy(pipelines+[source.pipeline_metrics])
                measured_backlog = copy.deepcopy(samples)
                measured_sample_count = sample_count
                measured_peaks = dict(peaks)
                wall_ns = time.perf_counter_ns()-started; cpu_ns = time.process_time_ns()-cpu
                before = await source.work(semantic_cut, 0)
                raw_native = await source.work(lambda state:dict(state.writer.db.execute(
                    'SELECT identity,hash FROM canonical_evidence')), 0)
                if raw_native != {identity:row.checksum for identity,row in expected.items()}:
                    raise AssertionError('native_comparison_economic_hashes_changed')
                await close_source()
                await open_source(); await settled()
                after = await source.work(semantic_cut, 0)
                if before != after:raise AssertionError('native_comparison_restart_changed_semantics')
                await close_source()
        return dict(semantics=before, timing=dict(wall_nanoseconds=wall_ns,
            parent_process_cpu_nanoseconds=cpu_ns, scope='instrumented_private_threads_setup_through_terminal_drain'),
            stages={**{key:dict(value) for key,value in measured_preparation.items()},
                    **{key:dict(value) for key,value in measured_delivery.items()}},
            preparation_results=dict(preparation_results), outbox_paths=dict(outbox_paths), owner_stages=measured_owner, backlog=measured_backlog, intake_peak_frames=intake_peak,
            source_pipeline=measured_pipelines,
            backlog_samples_total=measured_sample_count, backlog_sample_limit=128, backlog_peaks=measured_peaks,
            owner_probe_calls=dict(probe_count),
            restart_pending=restart_pending, restart_reserved=restart_reserved,
            expected_records=len(expected), frames=len(frames),
            event_types=dict(Counter(row.record.scope+':'+
                (('buy' if row.record.payload['event']['buy'] else 'sell')
                 if type(row.record.payload['event'].get('buy')) is bool else
                 row.record.payload['event'].get('event_type', 'trade')) for row in expected.values())),
            late_scout_and_true_promotion=True,
            receipt_availability_clock='fixed_NOW_all_stage_queue_service_clocks_real',
            measurement_limits=[
                'all_arms_instrumented_includes_private_setup_and_coarse_read_only_backlog_probes',
                'costs_frozen_before_semantic_reopen_checks_checkpoint_not_atomic_cross_thread_snapshot',
                'private_preparation_threads_exclude_production_spawn_transfer_and_child_cpu',
                'source_evidence_timing_repeats_batch_duration_per_frame_use_owner_stages_for_physical_callbacks',
                'owner_components_are_nested_in_source_commit_do_not_sum_parent_and_children',
                'native_receipt_identities_transformed_fixture_no_original_live_clock_quotes_or_full_qualification',
                'priority_probes_are_fixed_nonfinancial_owner_work_not_held_position_or_maintenance_protocol_proof',
                'delivery_returned_wall_metric_is_fixed_clock_zero_use_external_executor_stage_wall',
                'restart_reopens_actual_owner_and_consumer_same_generation_not_full_managed_startup',
                'gated_restart_cancels_before_ack_admission_not_a_physical_process_kill'],
            baseline=BASELINE, prepared=prepared, restart_equal=True)
    finally:
        gate.set()
        try:await close_source()
        finally:
            try:pool.shutdown(wait=True, cancel_futures=True)
            finally:delivery_executor.shutdown(wait=True, cancel_futures=True)


class NativeFanoutComparisonTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_inline_prepared_abba_preserves_economics_receipts_ack_and_restart(self):
        frames = native_frames()
        with tempfile.TemporaryDirectory() as directory:
            arms=[]
            for index,mode in enumerate((False,True,True,False)):
                arm=await run_native_arm(Path(directory)/str(index)/'canonical.sqlite',frames,prepared=mode)
                arms.append(arm)
                # Retain each completed arm even if a later arm or semantic
                # comparison fails. No equality verdict is implied here.
                print('NATIVE_FANOUT_ARM '+json.dumps(dict(index=index,
                    **{key:value for key,value in arm.items() if key != 'semantics'}),sort_keys=True),
                    file=sys.stderr,flush=True)
        for arm in arms:
            self.assertEqual(arm['semantics'], arms[0]['semantics'])
            self.assertTrue(arm['restart_equal']); self.assertEqual(arm['frames'], 8)
            self.assertGreater(arm['expected_records'], 64)
            self.assertGreater(len(arm['semantics']['delivery']), arm['expected_records'])
            self.assertGreater(len(arm['semantics']['receipts']), 0)
            self.assertLessEqual(arm['intake_peak_frames'], 8)
            self.assertEqual(arm['owner_probe_calls'], dict(priority_zero_calls=8, priority_four_calls=8))
            self.assertGreater(arm['event_types'].get('program:pump:buy', 0), 0)
            self.assertGreater(arm['event_types'].get('program:pump:sell', 0), 0)
            self.assertGreater(sum(value for key,value in arm['event_types'].items() if key.startswith('program:pumpswap:')), 0)
        for arm in (arms[1],arms[2]):
            self.assertGreater(arm['preparation_results'].get('prepared_outbox_records',0),0)
            self.assertGreater(arm['outbox_paths'].get('fresh_owner_validated_prepared_hits',0),0)
        for arm in (arms[0],arms[3]):
            self.assertEqual(arm['preparation_results'].get('prepared_outbox_records',0),0)
            self.assertEqual(arm['outbox_paths'].get('fresh_owner_validated_prepared_hits',0),0)
        # Publish the equality verdict only after every arm and invariant passes.
        print('NATIVE_FANOUT_COMPARISON '+json.dumps({
            'schema':'native-pre-intake-comparison-v1', 'order':['inline','prepared','prepared','inline'],
            'semantic_equal':True, 'native_provider_or_live_capacity_claim':False}, sort_keys=True),
            file=sys.stderr,flush=True)

    async def test_native_full_before_ack_restart_retains_all_obligations(self):
        frames = native_frames()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = await run_native_arm(root/'inline'/'canonical.sqlite', frames, prepared=False)
            restarted = await run_native_arm(root/'prepared'/'canonical.sqlite', frames,
                                              prepared=True, restart_before_ack=True)
        self.assertEqual(restarted['semantics'], baseline['semantics'])
        self.assertEqual(restarted['restart_pending'][0], restarted['expected_records'])
        self.assertGreater(restarted['restart_pending'][1], 0)
        self.assertTrue(restarted['restart_equal'])
