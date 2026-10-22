"""Bounded, provider-free concurrent native intake/publication/qualification.

This sibling of the unchanged original-window replay reuses its authenticated
cohort and semantic comparison. Actual serve.work, PriorityOwner, the managed
capture actor and QualificationReader run on their actual separate threads.
The fixed decision clock and unavailable quotes are explicit fixture limits;
this is engineering Track A, never live acceptance or a capacity certificate.
"""
import argparse
import ast
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from engineering.diagnostics import replay_original_pump_window as original

SCHEMA = 'concurrent-pump-window-engineering-v1'
MAX_BATCH_BYTES = 16 * 1024**2
ARRIVAL_BATCHES = 2
STORE_FIELDS = ('canonical_native', 'canonical_discovery', 'canonical_delivery',
                'candidate_history', 'qualification_observations', 'qualification_candidates')
CANDIDATE_COLUMNS = ('lane', 'candidate', 'surface', 'first_observed', 'last_observed',
                     'decision_deadline', 'body', 'hash')
CANDIDATE_METADATA = ('source', 'creator', 'pool', 'structural_scout', 'recoverable',
                      'provider_promotion', 'evidence_state', 'volume_quality')
MAX_CANDIDATE_DETAILS = 16
MAX_CANDIDATE_DIFFERENCE_BYTES = 64 * 1024


def candidate_difference_report(directory, names=('serial-control', 'concurrent')):
    """Bounded diagnosis of quiescent stores; every original comparison stays strict.

    Candidate identities and metadata values leave this function only as hashes.
    Values are shown only for fixed public surface names and integer timestamps.
    """
    import sqlite3
    from meme_machine.runtime.journal import digest
    def load(name):
        path = directory/name/'history.sqlite'
        db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=0, isolation_level=None)
        try:
            db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
            rows = {}
            for row in db.execute('SELECT '+','.join(CANDIDATE_COLUMNS)+' FROM candidates ORDER BY lane,candidate'):
                body = json.loads(row[6])
                original.need(digest(body) == row[7] and original.sha(row[6].encode()) == row[7],
                              'concurrent_candidate_body_hash')
                original.need(set(body) == set(CANDIDATE_COLUMNS[:6]) | {'metadata'} and
                    all(body[key] == row[index] for index, key in enumerate(CANDIDATE_COLUMNS[:6])) and
                    type(body['metadata']) is dict, 'concurrent_candidate_body_columns')
                rows[row[:2]] = (row, body)
            return rows
        finally:
            try:db.rollback()
            finally:db.close()
    before, after = (load(name) for name in names)
    columns = Counter(); body_fields = Counter(); metadata_fields = Counter()
    differing = unknown_metadata = 0; details = []
    for key in sorted(before.keys() | after.keys()):
        left, right = before.get(key), after.get(key)
        if left == right:continue
        differing += 1
        changed = [name for index, name in enumerate(CANDIDATE_COLUMNS)
                   if left is None or right is None or left[0][index] != right[0][index]]
        fields = [name for name in (*CANDIDATE_COLUMNS[:6], 'metadata')
                  if left is None or right is None or left[1][name] != right[1][name]]
        lm = {} if left is None else left[1]['metadata']; rm = {} if right is None else right[1]['metadata']
        metadata = [name for name in lm.keys() | rm.keys()
                    if (name in lm, lm.get(name)) != (name in rm, rm.get(name))]
        known = sorted(name for name in metadata if name in CANDIDATE_METADATA)
        unknown = len(metadata) - len(known)
        columns.update(changed); body_fields.update(fields); metadata_fields.update(known); unknown_metadata += unknown
        if len(details) == MAX_CANDIDATE_DETAILS:continue
        def value_hash(value, name):
            return None if value is None else original.sha(original.canonical(value[0][CANDIDATE_COLUMNS.index(name)]))
        safe = {}
        for name in ('surface', 'first_observed', 'last_observed', 'decision_deadline'):
            if name not in changed:continue
            values = []
            for value in (left, right):
                item = None if value is None else value[0][CANDIDATE_COLUMNS.index(name)]
                if name == 'surface':
                    item = item if item in ('pump', 'pump.fun', 'pumpswap', 'meteora', 'meteora-dlmm', None) else 'other'
                else:original.need(item is None or type(item) is int, 'concurrent_candidate_timestamp')
                values.append(item)
            safe[name] = values
        details.append(dict(candidate_key_sha256=original.sha(original.canonical(key)),
            present=[left is not None, right is not None], different_columns=changed,
            column_value_sha256={name:[value_hash(left, name), value_hash(right, name)] for name in changed},
            safe_values=safe, different_body_fields=fields, different_metadata_fields=known,
            unknown_metadata_fields_differing=unknown,
            metadata_value_sha256={name:[original.sha(original.canonical([name in values, values.get(name)]))
                for values in (lm, rm)] for name in known}))
    report = dict(schema='bounded-candidate-state-difference-v1', rows=[len(before), len(after)],
        differing_candidate_keys=differing, column_difference_counts={name:columns[name] for name in CANDIDATE_COLUMNS},
        body_field_difference_counts={name:body_fields[name] for name in (*CANDIDATE_COLUMNS[:6], 'metadata')},
        metadata_field_difference_counts={name:metadata_fields[name] for name in CANDIDATE_METADATA},
        unknown_metadata_fields_differing=unknown_metadata, details=details,
        detail_limit=MAX_CANDIDATE_DETAILS, byte_limit=MAX_CANDIDATE_DIFFERENCE_BYTES,
        truncated=len(details) < differing, candidate_bodies_authenticated=True,
        scope='closed_quiescent_private_stores_read_only_outside_timed_arms_not_comparison_normalization')
    while len(original.canonical(report)) > MAX_CANDIDATE_DIFFERENCE_BYTES and details:
        details.pop(); report['truncated'] = True
    original.need(len(original.canonical(report)) <= MAX_CANDIDATE_DIFFERENCE_BYTES,
                  'concurrent_candidate_difference_bound')
    return report


def production_capabilities(work):
    """Copy only literal capabilities declared beside the actual serve.work.

    The existing OwnedWork adapter compiles that real function. Read its
    adjacent flags too, so a combined successor exercises its real publication
    handoff automatically while an older baseline keeps its actual contract.
    """
    from meme_machine import solana_evidence_service as service
    tree = ast.parse(Path(service.__file__).read_bytes())
    serve = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'serve')
    capabilities = {name:False for name in ('candidate_delivery_continuation',
        'candidate_delivery_capture_actor', 'candidate_delivery_publication_handoff')}
    for node in serve.body:
        if not isinstance(node, ast.Assign):continue
        for target in node.targets:
            if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and
                    target.value.id == 'work' and target.attr in capabilities):
                original.need(isinstance(node.value, ast.Constant) and type(node.value.value) is bool,
                              'concurrent_production_capability_literal')
                capabilities[target.attr] = node.value.value
    for name, enabled in capabilities.items():setattr(work, name, enabled)
    original.need(capabilities['candidate_delivery_capture_actor'], 'concurrent_actual_actor_capability_required')
    return capabilities


def limits(batch, rate, seconds):
    original.need(type(batch) is int and 1 <= batch <= original.BATCH, 'concurrent_batch_bound')
    original.need(type(rate) in (int, float) and math.isfinite(rate) and 0 < rate <= 10000,
                  'concurrent_arrival_rate')
    original.need(type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= 1800,
                  'concurrent_deadline')


def freeze(parcel, batch):
    """Authenticate immutable normalized inputs before either timed arm."""
    from meme_machine.solana_economic_preparation import prepare_economic_record
    records, encodings, identities, sequences = {}, Counter(), set(), set()
    original.need(parcel.inputs == parcel.warmup + parcel.measured and parcel.warmup and parcel.measured,
                  'concurrent_cohort_partition')
    last_sequence = -1
    for item in parcel.inputs:
        sequence, identity = item['sequence'], item['identity']
        original.need(type(sequence) is int and sequence > last_sequence and sequence not in sequences
                      and identity not in identities, 'concurrent_cohort_order')
        last_sequence = sequence; sequences.add(sequence); identities.add(identity)
        record, checksum, encoding = parcel.record(item)
        original.need(record.identity == identity and record.scope == item['scope'] and
                      record.slot == item['slot'] and record.observed_at == item['first_seen'] and
                      original.sha(original.canonical(record.body())) == checksum,
                      'concurrent_normalized_identity')
        prepared = prepare_economic_record(record)
        records[identity] = prepared, checksum, encoding
        encodings[encoding] += 1
    batches = [parcel.measured[start:start+batch] for start in range(0, len(parcel.measured), batch)]
    for group in [parcel.warmup, *batches]:
        original.need(sum(len(original.canonical(records[item['identity']][0].record.body()))
                          for item in group) <= MAX_BATCH_BYTES, 'concurrent_batch_bytes')
    parcel.unchanged()
    return records, batches, dict(encodings)


def compare_arms(before, after):
    """Every original semantic field is mandatory; differences remain failures."""
    fields = [key for key in original.SEMANTIC_FIELDS
              if key not in before or key not in after or before[key] != after[key]]
    stores = [key for key in STORE_FIELDS if key not in before['store_fingerprints'] or
              key not in after['store_fingerprints'] or
              before['store_fingerprints'][key] != after['store_fingerprints'][key]]
    stores.extend(sorted((set(before['store_fingerprints']) | set(after['store_fingerprints'])) - set(STORE_FIELDS)))
    return dict(coherent=not fields and not stores, semantic_fields=list(original.SEMANTIC_FIELDS),
                different_semantic_fields=fields, different_stores=stores)


@dataclass(frozen=True)
class NormalizedOutboxBatch:
    """Economic-record carrier only; no native frame, census or finality fields."""
    rows: tuple
    outbox: tuple = ()


def prepare_normalized_outbox(rows, path, endpoint):
    """Use the operating optional preview on the authenticated normalized cohort.

    The existing owner independently checks fresh storage, recipients, source
    generation, bytes and first availability. This carrier grants no authority.
    """
    from meme_machine.solana_economic_preparation import MAX_BYTES, PreparedEconomicRecord, prepare_outbox
    original.need(0 < len(rows) <= original.BATCH and
                  all(type(row) is PreparedEconomicRecord for row in rows), 'concurrent_outbox_rows')
    original.need(sum(row.original_bytes for row in rows) <= MAX_BATCH_BYTES, 'concurrent_batch_bytes')
    retained = sum(row.original_bytes + row.byte_count for row in rows)
    original.need(retained <= MAX_BYTES, 'concurrent_outbox_product_bound')
    products, size = prepare_outbox((NormalizedOutboxBatch(tuple(rows)),), path, endpoint, MAX_BYTES-retained)
    return products[0].outbox, size


def compare_outbox_modes(runs):
    """All existing semantic/store checks plus actual ABBA preparation/reuse."""
    order = (False, True, True, False)
    original.need(len(runs) == len(order) and all(run['implementation'] == 'concurrent' and
        run['outbox_preparation']['enabled'] is mode for run, mode in zip(runs, order)),
        'concurrent_outbox_arm_order')
    compared = [compare_arms(runs[0], run) for run in runs[1:]]
    fields = [key for key in original.SEMANTIC_FIELDS
              if any(key in row['different_semantic_fields'] for row in compared)]
    stores = sorted({key for row in compared for key in row['different_stores']})
    exercised = all(run['outbox_preparation']['emit_probe_enabled'] and
        ((run['outbox_preparation']['products'] > 0 and
          run['outbox_preparation']['successful_prepared_emits'] > 0 and
          run['outbox_preparation']['measured_products'] > 0 and
          run['outbox_preparation']['measured_successful_prepared_emits'] > 0) if mode else
         (run['outbox_preparation']['products'] == 0 and
          run['outbox_preparation']['successful_prepared_emits'] == 0 and
          run['outbox_preparation']['measured_products'] == 0 and
          run['outbox_preparation']['measured_successful_prepared_emits'] == 0))
        for run, mode in zip(runs, order))
    return dict(coherent=not fields and not stores, semantic_fields=list(original.SEMANTIC_FIELDS),
        different_semantic_fields=fields, different_stores=stores,
        preparation_exercised=exercised, mode_order=['inline', 'prepared', 'prepared', 'inline'],
        same_concurrent_configuration=True, arm_comparisons=compared)


def stores(state, reader):
    """Six logical stores; source paths are authenticated before normalization."""
    def digest(db, sql):
        return original.sha(original.canonical(list(db.execute(sql))))
    history = reader.history
    references = []
    for lane, candidate, identity, kind, raw, checksum in history.db.execute(
            'SELECT lane,candidate,identity,kind,body,hash FROM canonical_event_refs ORDER BY lane,candidate,identity'):
        original.need(original.sha(raw.encode()) == checksum, 'concurrent_reference_hash')
        body = json.loads(raw)
        original.need(body['path'] == str(reader.config.evidence), 'concurrent_reference_path')
        body['path'] = '@fresh-canonical'
        references.append((lane, candidate, identity, kind, body))
    return dict(
        canonical_native=digest(state.writer.db,
            'SELECT identity,hash,first_seen,slot,transaction_index,event_index FROM canonical_evidence ORDER BY identity'),
        canonical_discovery=digest(state.writer.db, 'SELECT * FROM candidate_outbox ORDER BY sequence'),
        canonical_delivery=digest(state.writer.db,
            'SELECT id,family,address,kind,body,hash,created,consumed FROM candidate_history_outbox ORDER BY id'),
        candidate_history=original.sha(original.canonical(dict(references=references,
            candidates=list(history.db.execute('SELECT * FROM candidates ORDER BY lane,candidate')),
            receipts=list(history.db.execute('SELECT * FROM source_receipts ORDER BY id'))))),
        qualification_observations=digest(reader.db, 'SELECT * FROM observations ORDER BY sequence'),
        qualification_candidates=digest(reader.db, 'SELECT * FROM candidate_state ORDER BY mint'))


async def run_arm(parcel, records, batches, directory, *, concurrent, rate, seconds,
                  outbox_preparation=False, _outbox_probe=None):
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_evidence_service import FinalizedFence
    from meme_machine.solana_evidence_control import PriorityOwner
    from meme_machine.solana_selective_history import SelectiveHistory
    from meme_machine.solana_selective_source import SelectiveSource, STATE_SCHEMA, source_work
    from meme_machine.solana_candidate_lifecycle import CandidateLifecycle
    from meme_machine.solana_rolling_history import RollingHistory
    from meme_machine.solana_prewarm_startup import PrewarmStartup
    from meme_machine.solana_history_delivery import capture_context
    from meme_machine.solana_history_notifications import install as notifications, delivery_hint
    from meme_machine.operational.managed_native_pump import install_nonfinancial_history, _root
    from meme_machine.operational.managed_pump_qualification import QualificationReader
    from meme_machine.operational.managed_qualification_replay import NoNetworkProvider
    # Reuse the existing actual-production-work adapter; no alternate queue,
    # priority policy, admission, cancellation or continuation is implemented.
    from tests.test_publication_accounting_turn import OwnedWork

    directory.mkdir(mode=0o700); _root(directory)
    at = max(item['first_seen'] for item in parcel.inputs)
    config = SimpleNamespace(root=directory, evidence=directory/'canonical.sqlite',
        history=directory/'history.sqlite', generation='concurrent-engineering-v1',
        source_revision=original.RUNTIME_BASELINE)
    endpoint = records[parcel.inputs[0]['identity']][0].record.endpoint_identity
    counters = Counter(); owner = source = work = reader = None; capabilities = None
    delivery_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='track-a-history')
    qualification_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='track-a-qualification')
    tasks = []; acknowledgements = []; commands = []; progress = []; thread_ids = {}
    intake_finished = False; changed = asyncio.Event(); delivery_changed = asyncio.Event(); latest = None
    provider = NoNetworkProvider(); loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=ARRIVAL_BATCHES)
    original.need(type(outbox_preparation) is bool, 'concurrent_outbox_mode')

    def factory():
        writer = EvidenceWriter(config.evidence, clock=lambda: at)
        try:
            fence = FinalizedFence(writer, endpoint_identity=endpoint)
            history = SelectiveHistory(writer, endpoint, clock=lambda: at)
            history.db.executescript(STATE_SCHEMA)
            history.lifecycle = CandidateLifecycle(history, candidate_path=config.history)
            history.lifecycle.delivery_separated = True
            history.rolling = RollingHistory(history); history.startup = PrewarmStartup(history)
            fence.selective = history; fence.health('topology', 'candidate_hybrid_v1')
            thread_ids['owner'] = threading.get_ident()
            return SimpleNamespace(writer=writer, fence=fence, selective=history, close=writer.close)
        except BaseException:
            try:writer.close()
            except BaseException:pass
            raise

    def open_reader():
        value = QualificationReader(config, clock=lambda: at, provider=provider, decision_target=None)
        try:
            original.need(value._open(), 'concurrent_reader_open')
            value.plane.acknowledge = lambda *args: acknowledgements.append(args)
            def refused(**request):
                from meme_machine.solana_evidence_plane import EvidenceUnavailable
                commands.append(request)
                raise EvidenceUnavailable('concurrent_engineering_ipc_refused')
            value.plane.command = refused
            thread_ids['qualification'] = threading.get_ident()
            return value
        except BaseException:
            try:value.close()
            except BaseException:pass
            raise

    async def qualification(function, *args, cancel_result=None):
        future = asyncio.wrap_future(qualification_pool.submit(function, *args))
        try:return await asyncio.shield(future)
        except asyncio.CancelledError:
            # A physical qualification read/observation commit owns its SQLite
            # handles until terminal. Do not close them beneath a canceled
            # asyncio waiter or leave a failure unobserved.
            while not future.done():
                try:await asyncio.shield(future)
                except asyncio.CancelledError:continue
                except BaseException:break
            if not future.cancelled():
                result = future.result()
                if cancel_result is not None:
                    cleanup = asyncio.wrap_future(qualification_pool.submit(cancel_result, result))
                    while not cleanup.done():
                        try:await asyncio.shield(cleanup)
                        except asyncio.CancelledError:continue
                        except BaseException:break
                    cleanup.result()
            raise

    async def bootstrap():
        nonlocal owner, source, work, capabilities
        owner = PriorityOwner(factory)
        ready = asyncio.wrap_future(owner.ready)
        try:await asyncio.shield(ready)
        except asyncio.CancelledError:
            # ready is the native owner's own Future. Canceling its asyncio
            # waiter must not cancel initialization before its close finally.
            while not ready.done():
                try:await asyncio.shield(ready)
                except asyncio.CancelledError:continue
                except BaseException:break
            ready.result()
            raise
        source = SelectiveSource(SimpleNamespace(identity=endpoint), None, token='offline')
        source.stop = asyncio.Event(); source.delivery_executor = delivery_pool
        work = OwnedWork(owner); capabilities = production_capabilities(work)
        source.work = source_work(work, source.stop)
        source.canonical_path = str(config.evidence); source.history_separated = True
        def seed(state):
            history = state.selective
            notifications(history, loop, source.history_changed, capture_hints=True)
            return capture_context(history.lifecycle), delivery_hint(history)
        context, hint = await source.work(seed, 0)
        source.delivery_capture_context = context; source._history_delivery_hint(hint)
        def observe(kind, values):
            if kind == 'history_delivery_timing':
                counters['delivery_batches'] += 1
                counters['delivery_wall_nanoseconds'] += int(values['wall_seconds'] * 1e9)
                counters['delivery_cpu_nanoseconds'] += int(values['cpu_seconds'] * 1e9)
                if not intake_finished:counters['delivery_before_intake_finished'] += 1
                changed.set(); delivery_changed.set()
        source.observer = observe

    async def stop_tasks():
        if source is not None:
            source.stop.set(); source.delivery_wakeup.notify(); source.history_wakeup.notify()
        for task in tasks:task.cancel()
        if tasks:
            settled = await asyncio.gather(*tasks, return_exceptions=True)
            for result in settled:
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):raise result
        tasks.clear()

    async def admit_group(group):
        prepared = [records[item['identity']][0] for item in group]
        options = {}
        if outbox_preparation:
            begun, cpu = time.perf_counter_ns(), time.thread_time_ns()
            products, size = prepare_normalized_outbox(prepared, config.evidence, endpoint)
            counters['outbox_preparation_calls'] += 1
            counters['outbox_preparation_products'] += len(products)
            counters['outbox_preparation_bytes'] += size
            counters['outbox_preparation_wall_nanoseconds'] += time.perf_counter_ns()-begun
            counters['outbox_preparation_cpu_nanoseconds'] += time.thread_time_ns()-cpu
            options['prepared_outbox'] = products
        await source.work(lambda state: state.selective.ingest(prepared, **options), 2,
                          label='source_commit', component='candidate')

    def check_tasks():
        for task in tasks[:3]:
            if task.done():
                task.result()
                raise ValueError('original_window_concurrent_worker_stopped')

    async def qualified_until(target):
        while latest is None or latest.get('durably_observed_native_events', 0) < target:
            check_tasks(); changed.clear()
            if latest is not None and latest.get('durably_observed_native_events', 0) >= target:break
            await changed.wait()

    def pending_outbox(state):
        return state.writer.db.execute('SELECT 1 FROM candidate_history_outbox '
            'WHERE consumed IS NULL LIMIT 1').fetchone() is not None

    async def delivered_until_empty():
        # Native observations and outbox obligations are different populations:
        # several authenticated binding scopes can deliver one native identity.
        # Intake is finished here. Check once, then only after real delivery ACK
        # progress; qualification's empty turns must not poll the owner. Clear
        # before the coherent owner read so an ACK during it cannot be lost.
        while True:
            check_tasks(); delivery_changed.clear()
            counters['completion_outbox_checks'] += 1
            if not await source.work(pending_outbox, 2):return
            check_tasks(); counters['completion_outbox_waits'] += 1
            await delivery_changed.wait()

    async def qualify():
        nonlocal latest
        while not source.stop.is_set():
            latest = await qualification(reader.step)
            if latest.get('processed_this_turn', 0):
                counters['qualification_nonempty_turns'] += 1
                if not intake_finished:
                    counters['observed_before_intake_finished'] += latest['processed_this_turn']
            changed.set()
            await asyncio.sleep(0 if latest.get('processed_this_turn', 0) else .005)

    async def arrivals(started):
        offered = 0
        for group in batches:
            await asyncio.sleep(max(0, started + offered/rate - loop.time()))
            if queue.full():counters['arrival_backpressure_turns'] += 1
            await queue.put(group)
            counters['arrival_queue_peak_batches'] = max(counters['arrival_queue_peak_batches'], queue.qsize())
            counters['offered_measured_events'] += len(group); offered += len(group)
        await queue.put(None)

    async def intake():
        nonlocal intake_finished
        admitted = len(parcel.warmup)
        while True:
            group = await queue.get()
            if group is None:break
            await admit_group(group); admitted += len(group)
            counters['admitted_measured_events'] += len(group)
            if not concurrent:await qualified_until(admitted)
            if latest is None or latest.get('durably_observed_native_events', 0) < admitted:
                counters['intake_turns_without_qualification_drain'] += 1
            progress.append(dict(admitted=admitted, observed=None if latest is None else
                latest.get('durably_observed_native_events'), elapsed_seconds=loop.time()-started))
        intake_finished = True

    try:
        async with asyncio.timeout(seconds):
            await bootstrap()
            await qualification(install_nonfinancial_history, config)
            await admit_group(parcel.warmup)
            # Warmup commits have returned from the actual owner; no measured
            # arrivals or consumer tasks have started. Snapshot the operating
            # method spy too, so warmup-only reuse cannot certify the 5081 cut.
            warmup_products = counters['outbox_preparation_products']
            warmup_emits = None if _outbox_probe is None else _outbox_probe['successful_prepared_emits']
            reader = await qualification(open_reader, cancel_result=lambda value:value.close())
            initial = await qualification(reader.snapshot)
            original.need(initial['native_event_backlog'] == len(parcel.warmup) and
                          initial['durably_observed_native_events'] == 0, 'concurrent_initial_state')
            # Record the real consumer executor identity without replacing any
            # capture/delivery function or adding work to the owner pipeline.
            thread_ids['delivery'] = await asyncio.wrap_future(delivery_pool.submit(threading.get_ident))
            started = loop.time(); wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            tasks.extend((asyncio.create_task(source.candidate_history_delivery()),
                          asyncio.create_task(source.publish_history()), asyncio.create_task(qualify())))
            feeding = asyncio.create_task(arrivals(started)); producing = asyncio.create_task(intake())
            tasks.extend((feeding, producing))
            # A failure of any worker must interrupt a producer waiting for a
            # publication that can no longer occur, rather than wait out a run.
            async def finished():
                await asyncio.gather(feeding, producing)
                await qualified_until(len(parcel.inputs))
                await delivered_until_empty()
            completion = asyncio.create_task(finished())
            try:
                while not completion.done():
                    check_tasks()
                    watched = [task for task in tasks[:3] if not task.done()]
                    done, _ = await asyncio.wait([completion, *watched], return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        if task is not completion:
                            task.result(); raise ValueError('original_window_concurrent_worker_stopped')
                await completion
            finally:
                if not completion.done():completion.cancel()
                await asyncio.gather(completion, return_exceptions=True)
            timing = dict(wall_nanoseconds=time.perf_counter_ns()-wall,
                          process_cpu_nanoseconds=time.process_time_ns()-cpu,
                          scope='normalized_intake_actual_owner_actor_and_qualification_all_threads')
            total_products = counters['outbox_preparation_products']
            total_emits = None if _outbox_probe is None else _outbox_probe['successful_prepared_emits']
            # Stop the physical workers before taking a coherent terminal cut.
            # Their existing accepted-delivery cancellation cleanup must join
            # FULL then fresh owner ACK; no harness-side ACK is manufactured.
            await stop_tasks()
            final = await qualification(reader.snapshot)
            expected = {item['identity']: item for item in parcel.inputs}
            semantic = await qualification(original._semantic, reader, expected)
            history_events = await qualification(lambda: [reader.history.event(lane, candidate, identity)
                for lane, candidate, identity in reader.history.db.execute(
                    'SELECT lane,candidate,identity FROM canonical_event_refs ORDER BY lane,candidate,identity')])
            history_state = await qualification(lambda: {table: original.sha(original.canonical(list(
                reader.history.db.execute('SELECT * FROM '+table+' ORDER BY '+order))))
                for table, order in (('candidates', 'lane,candidate'), ('source_receipts', 'id'))})
            original_result = await qualification(original.original_comparison, reader, parcel)
            for table in ('funding', 'decisions'):
                original.need(await qualification(lambda: reader.history.db.execute(
                    'SELECT count(*) FROM '+table).fetchone()[0]) == 0, 'concurrent_financial_state')
            def canonical_cut(state):
                original.need(state.writer.db.execute('SELECT count(*) FROM candidate_history_outbox WHERE consumed IS NULL')
                              .fetchone() == (0,), 'concurrent_unacked_outbox')
                return list(state.writer.db.execute('SELECT identity,hash,first_seen,typeof(body) FROM canonical_evidence'))
            native = dict((row[0], row[1:]) for row in await source.work(canonical_cut, 2))
            fresh_encodings = Counter()
            for item in parcel.inputs:
                prepared, checksum, _ = records[item['identity']]
                value = native[item['identity']]
                original.need(value[:2] == (checksum, prepared.record.observed_at), 'concurrent_economics_changed')
                fresh_encodings['text' if value[2] == 'text' else 'SEP1' if value[2] == 'blob' else 'cold_canonical'] += 1
            # Read canonical data on its owning thread. Qualification/history
            # connections stay on their own thread even for the semantic cut.
            async def fingerprints():
                # Quiescent fresh stores have no writer. A short read-only
                # canonical connection belongs to the qualification worker.
                def read():
                    import sqlite3
                    db = sqlite3.connect(config.evidence.as_uri()+'?mode=ro', uri=True, isolation_level=None)
                    try:
                        db.execute('PRAGMA query_only=ON')
                        return stores(SimpleNamespace(writer=SimpleNamespace(db=db)), reader)
                    finally:db.close()
                return await qualification(read)
            before_restart = await fingerprints()
            owner_counts = dict(work.counts)
            original.need('owner.stage.candidate_delivery_capture.calls' not in owner_counts,
                          'concurrent_owner_capture_reintroduced')
            original.need(owner_counts.get('owner.stage.candidate_delivery_ack.calls', 0) > 0,
                          'concurrent_actual_owner_ack_missing')
            await qualification(reader.close); reader = None
            owner.close(); owner = None
            # Reopen the actual canonical owner, seed a new actor and reopen
            # the actual qualification reader, rather than copy prior cursors.
            await bootstrap(); reader = await qualification(open_reader, cancel_result=lambda value:value.close())
            tasks.append(asyncio.create_task(source.candidate_history_delivery()))
            await asyncio.sleep(0)
            await stop_tasks()
            restarted = await qualification(reader.step)
            original.need(restarted.get('processed_this_turn') == 0 and
                          {key:value for key,value in restarted.items() if key != 'processed_this_turn'} == final and
                          await qualification(original._semantic, reader, expected) == semantic and
                          await fingerprints() == before_restart, 'concurrent_restart_parity')
            original.need(final['native_event_backlog'] == 0 and len(native) == len(parcel.inputs),
                          'concurrent_incomplete_window')
            return dict(implementation='concurrent' if concurrent else 'serial_control', timing=timing,
                initial=initial, final=final, **semantic,
                history_semantic_sha256=original.sha(original.canonical(history_events)),
                history_state_sha256=history_state, original_comparison=original_result,
                ack_intents_sha256=original.sha(original.canonical(acknowledgements)),
                command_intents_sha256=original.sha(original.canonical(commands)),
                reader_restart_verified=True, owner_actor_restart_verified=True,
                store_fingerprints=before_restart, counters=dict(counters), owner_counters=owner_counts,
                outbox_preparation=dict(enabled=outbox_preparation,
                    products=total_products, total_products=total_products,
                    warmup_products=warmup_products, measured_products=total_products-warmup_products,
                    emit_probe_enabled=_outbox_probe is not None,
                    successful_prepared_emits=total_emits, total_successful_prepared_emits=total_emits,
                    warmup_successful_prepared_emits=warmup_emits,
                    measured_successful_prepared_emits=None if total_emits is None else total_emits-warmup_emits,
                    scope='normalized_records_actual_readonly_preview_on_source_event_loop_before_owner_admission_no_native_frame_or_process_IPC',
                    economic_products_frozen_before_timing_for_both_modes=True,
                    preparation_counters_include_untimed_warmup=True,
                    measured_counter_offsets='after_warmup_owner_return_before_existing_timed_start',
                    owner_callback_counts_are_not_SQL_statement_counts=True),
                thread_ids=thread_ids, distinct_pipeline_threads=len(set(thread_ids.values())) == 3,
                production_work_capabilities=capabilities,
                controlled_batch_progress=progress,
                decision_target='unavailable_no_original_oracle_retained', missing_provider_inputs=provider.missing,
                provider_requests=0, financial_authority=False, full_strategy_equivalence_proven=False,
                original_input_storage_encodings=dict(Counter(row[2] for row in records.values())),
                fresh_input_storage_encodings=dict(fresh_encodings))
    finally:
        try:
            await stop_tasks()
        finally:
            try:
                if reader is not None:await qualification(reader.close)
            finally:
                try:
                    if owner is not None:owner.close()
                finally:
                    # Existing physical consumer cancellation joins before
                    # owner close, including when a different cleanup fails.
                    delivery_pool.shutdown(wait=True, cancel_futures=True)
                    qualification_pool.shutdown(wait=True, cancel_futures=True)


def benchmark(parcel, directory, *, batch=1, rate=10, seconds=120, outbox_preparation=False):
    from meme_machine.runtime.evidence_worker import owner_thread_fairness
    limits(batch, rate, seconds)
    original.need(type(outbox_preparation) is bool, 'concurrent_outbox_mode')
    directory = Path(directory).absolute()
    original.need(directory.parent.resolve(strict=True) == directory.parent and not directory.exists(),
                  'new_output_required')
    records, batches, _ = freeze(parcel, batch)
    directory.mkdir(mode=0o700); old_umask = os.umask(0o077)
    def measured_arm(name, concurrent, prepared=False):
        from meme_machine.solana_candidate_lifecycle import CandidateLifecycle
        native_emit = CandidateLifecycle.emit_raw
        hits = Counter()
        def observed_emit(life, *args, **kwargs):
            answer = native_emit(life, *args, **kwargs)
            if kwargs.get('_prepared') is not None:hits['successful_prepared_emits'] += 1
            return answer
        # Only the explicitly selected comparison instruments the operating
        # method. The default route retains its existing measurement overhead.
        with patch.object(CandidateLifecycle, 'emit_raw', observed_emit) if outbox_preparation else nullcontext():
            run = asyncio.run(run_arm(parcel, records, batches, directory/name,
                concurrent=concurrent, rate=rate, seconds=seconds, outbox_preparation=prepared,
                _outbox_probe=hits if outbox_preparation else None))
        return run
    try:
        with original.no_network(), owner_thread_fairness():
            if outbox_preparation:
                names = ('outbox-control-0', 'outbox-prepared-1', 'outbox-prepared-2', 'outbox-control-3')
                runs = [measured_arm(name, True, prepared) for name, prepared in
                        zip(names, (False, True, True, False))]
                comparison = compare_outbox_modes(runs)
            else:
                names = ('serial-control', 'concurrent')
                runs = [measured_arm(name, concurrent) for name, concurrent in zip(names, (False, True))]
                comparison = compare_arms(*runs)
        for prepared, checksum, _ in records.values():
            original.need(original.sha(original.canonical(prepared.record.body())) == checksum,
                          'concurrent_normalized_input_mutated')
        parcel.unchanged()
        exercised = all(run['counters'].get(key, 0) > 0 for run in (runs if outbox_preparation else runs[1:])
                        for key in ('delivery_before_intake_finished', 'observed_before_intake_finished',
                                    'intake_turns_without_qualification_drain'))
        return dict(schema=SCHEMA, **comparison, concurrency_exercised=exercised,
            candidate_state_difference=candidate_difference_report(directory, names[:2]),
            engineering_validation_passed=comparison['coherent'] and exercised and
                (not outbox_preparation or comparison['preparation_exercised']) and
                all(run['distinct_pipeline_threads'] for run in runs),
            source=parcel.manifest['source'], source_manifest_sha256=parcel.manifest_fingerprint[1],
            input_provenance='public_fixture' if 'fixture' in parcel.manifest['source'] else 'authenticated_original_parcel',
            input_parcel_sha256=parcel.fingerprint[1], input_events=len(parcel.inputs),
            selected_events=len(parcel.measured), runtime_baseline_commit=original.RUNTIME_BASELINE,
            consumer_source_sha256=original.sha(Path(__file__).read_bytes()), runs=runs,
            outbox_preparation_comparison=outbox_preparation,
            schedule=dict(batch=batch, offered_events_per_second=rate, arrival_queue_batches=ARRIVAL_BATCHES,
                max_batch_bytes=MAX_BATCH_BYTES, clock=max(item['first_seen'] for item in parcel.inputs),
                clock_scope='fixed_availability_and_decision_clock_not_original_visibility_or_wall_clock',
                serial_control='wait_for_real_publication_and_qualification_after_each_admitted_batch',
                concurrent='independent_bounded_arrival_intake_actor_and_qualification_no_per_batch_drain'),
            context_rows_imported_as_state=0, original_inputs_unchanged=True,
            native_acquisition_join_repair_exercised=False, production_admission_and_owner_policy=True,
            owner_thread_fairness_seconds=.0005,
            publication_thread_handoff_exercised=True, actor_capture_service_cpu_separately_measured=False,
            concurrency_scope='independent_tasks_and_three_physical_threads_with_progress_before_intake_finishes_not_CPU_parallelism',
            classification_differences_are_failures=True, quote_inputs='unavailable_no_synthetic_quotes',
            full_qualification_proven=False, full_strategy_equivalence_proven=False,
            throughput_readiness_proven=False, financial_authority=False, provider_requests=0)
    finally:os.umask(old_umask)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--parcel', type=Path)
    inputs.add_argument('--public-fixture', action='store_true')
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--new-output-directory', required=True, type=Path)
    parser.add_argument('--batch', type=int)
    parser.add_argument('--rate', type=float)
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--outbox-preparation', action='store_true',
        help='Compare inline/prepared/prepared/inline with the same concurrent configuration.')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.batch is None:args.batch = 1 if args.public_fixture else 64
    if args.rate is None:args.rate = 10 if args.public_fixture else 2000
    limits(args.batch, args.rate, args.seconds)
    original.need(os.geteuid() != 0, 'unprivileged_consumer_required')
    original.need(bool(args.parcel) == bool(args.manifest_sha256), 'concurrent_manifest_pin')
    if not args.worker:
        from meme_machine.operational.artifact_storage import Scratch
        output = args.new_output_directory.absolute()
        original.need(output.parent.resolve(strict=True) == output.parent and not output.exists(), 'new_output_required')
        with Scratch() as scratch:
            target = scratch.path/'compute'
            command = [sys.executable, '-m', 'engineering.diagnostics.replay_concurrent_pump_window',
                '--worker', '--new-output-directory', str(target), '--batch', str(args.batch),
                '--rate', str(args.rate), '--seconds', str(args.seconds)]
            command += (['--parcel', str(args.parcel.absolute()), '--manifest-sha256', args.manifest_sha256]
                        if args.parcel else ['--public-fixture'])
            if args.outbox_preparation:command.append('--outbox-preparation')
            child = subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL)
            until = time.monotonic() + (4 if args.outbox_preparation else 2)*args.seconds
            try:
                while child.poll() is None:
                    scratch.check(); original.need(time.monotonic() < until, 'concurrent_worker_deadline')
                    time.sleep(.25)
                scratch.check(); original.need(child.returncode in (0, 2), 'concurrent_worker_failed_retained_scratch')
                path = target/'report.json'; raw = path.read_bytes()
                original.need(len(raw) <= 32*1024**2, 'report_bound')
                result = original.loads(raw)
                original.need(result['schema'] == SCHEMA and result['source_manifest_sha256'] ==
                    (args.manifest_sha256 or 'a'*64), 'concurrent_worker_report_binding')
                output.mkdir(mode=0o700); original._report(output/'report.json', raw)
                scratch.success = result['engineering_validation_passed']
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=5)
    else:
        if args.public_fixture:
            from tests.test_original_pump_window_replay import CapturedParcel
            parcel = CapturedParcel()
        else:parcel = original.Parcel(args.parcel, args.manifest_sha256)
        result = benchmark(parcel, args.new_output_directory, batch=args.batch, rate=args.rate, seconds=args.seconds,
                           outbox_preparation=args.outbox_preparation)
        original._report(args.new_output_directory/'report.json', original.canonical(result)+b'\n')
    print(json.dumps(dict(schema=SCHEMA, engineering_validation_passed=result['engineering_validation_passed'],
        coherent=result['coherent'], concurrency_exercised=result['concurrency_exercised'],
        financial_authority=False), sort_keys=True))
    return 0 if result['engineering_validation_passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
