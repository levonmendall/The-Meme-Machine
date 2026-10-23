"""Matched synthetic SQLite work, never an authenticated market replay.

Copy this identical file into each exact source tree and call
``await run_owner_throughput_comparison(new_directory, measured=False)`` for
unprofiled arms, then use separate measured arms for quantized VM work. The
returned report contains no wall-time pass threshold or throughput claim.
Root owns execution/registration; this file does not open installed state.
"""
import asyncio
from contextlib import ExitStack
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_control import PriorityOwner, admit
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_selective_source import SelectiveSource, install, source_work
from tests.test_solana_closure import NOW, state_at
from tests.test_solana_prewarm_startup import seal
from tests.test_candidate_commit_batches import frame


VM_QUANTUM = 1000
MAX_TURNS = 512
TABLES = (
    'market_observations', 'candidate_lifecycle', 'evidence_bindings',
    'acquisition_jobs', 'acquisition_page_receipts', 'candidate_history_outbox',
    'rolling_boundary_waits', 'rolling_publication_waits',
    'rolling_preparation_jobs', 'candidate_pending_proofs', 'candidate_coverage',
    'candidate_gaps', 'candidate_checkpoints', 'canonical_evidence',
    'rolling_economic_events', 'rolling_economic_addresses',
    'candidate_content_receipts', 'rolling_event_lineage',
    'native_order_attestations', 'candidate_outbox',
)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
        separators=(',', ':'), default=lambda value: {'bytes': value.hex()}).encode()).hexdigest()


def emit_owner_throughput_report(report, arm):
    """One bounded stdout record; root records Git heads/run IDs externally.

    Byte hashes identify this identical harness and the affected loaded runtime
    modules, not a complete source census. No database rows or file paths leave
    this projection. Uninstrumented commit/VM values remain explicitly null.
    """
    modules = ('solana_selective_source', 'solana_selective_history',
        'solana_evidence_control', 'solana_evidence_plane', 'solana_rolling_history',
        'solana_history_work', 'solana_candidate_development', 'solana_acquisition_scheduler')
    sources = {}
    for name in modules:
        module = sys.modules.get('meme_machine.'+name)
        sources[name] = (None if module is None else
            hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest())
    final = report['final']
    summary = dict(schema='synthetic-owner-throughput-comparison-summary-v1',
        arm=arm, report_schema=report['schema'], scope=report['scope'],
        provenance=dict(harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            affected_runtime_module_sha256=sources, full_source_census=False),
        cohort=report['cohort'], runtime=report['runtime'], measured=report['measured'],
        vm_quantum=report['vm_quantum'], counters=report['counters'],
        turns=report['turns'], maximum_turns=report['maximum_turns'],
        fingerprints=dict(initial_functional=report['before']['functional_sha256'],
            final_functional=final['functional_sha256'],
            initial_canonical_order=report['before']['canonical_order_sha256'],
            final_canonical_order=final['canonical_order_sha256']),
        final=dict((key, final[key]) for key in ('complete', 'deadlines_preserved',
            'pending_jobs', 'pending_history', 'inflight', 'preparation_tickets',
            'transaction_open', 'synchronous')),
        cancellation_probe=report['cancellation_probe'], scheduling=report['scheduling'],
        provider_calls=report['provider_calls'], financial_authority=report['financial_authority'])
    print('OWNER_THROUGHPUT_COMPARISON '+json.dumps(summary,
        sort_keys=True, separators=(',', ':'), allow_nan=False), flush=True)
    return summary


class _OfflineDispatchRefused(RuntimeError):
    pass


class _QuietClock:
    """Evidence time is fixed; only the declared 101-ms poll clock advances."""
    def __init__(self):
        self.tick = 1.0

    def time(self):
        return NOW

    def monotonic(self):
        return self.tick

    def __getattr__(self, name):
        return getattr(time, name)


class _QuietAsyncio:
    async def sleep(self, delay, result=None):
        if delay < 0:
            raise AssertionError('negative fixture scheduling delay')
        return await asyncio.sleep(0, result)

    def __getattr__(self, name):
        return getattr(asyncio, name)


def _seed(state, *, retained, eligible, jobs, waits):
    """Real constructors/transactions; all inputs below are declared fixtures."""
    from meme_machine.solana_selective_source import commit_candidate_batch
    from meme_machine.solana_selective_history import PROGRAMS
    from meme_machine.solana_rolling_history import program_scope

    h = install(state)
    h.startup.begin()
    for family in ('pump', 'pumpswap'):
        h.startup.feed_ack(family, 100, 100)
    h.startup.native(('pump', 'pumpswap'))
    seal(h, 100, 100)
    if not h.startup.advance()['released']:
        raise AssertionError('quiet fixture failed actual startup release')
    # Boot the empty quiet interval through the existing synchronous fixture,
    # then install the production separated-history actor before any measured
    # acquisition work. Both sources receive this identical logical state.
    from meme_machine.solana_history_work import HistoricalTasks
    h.historical_tasks = HistoricalTasks(h)
    h.lifecycle.delivery_separated = True
    # Authentic captured decoder bytes carried by the existing synthetic native
    # frame fixture. They are not evidence of an original market opportunity.
    addresses = {PROGRAMS[f]: program_scope(f) for f in ('pump', 'pumpswap')}
    commit_candidate_batch(state, (frame(101), frame(102)), addresses,
        'owner-throughput-fixture', publish=False)
    initial = dict(eligible=[], expired_jobs=[], covered_jobs=[], local_plans=[], expired_reactivations=[],
                   expired_waits=[], deadlines={}, quiet=retained)
    with state.writer.transaction():
        for index in range(retained):
            address = 'retained-%04d' % index
            h.observe('pump', address, slot=100, signature='', seen=NOW-120,
                fields=dict(development_upper_bps=9000))
            h.bind('pump', address)
        for index in range(eligible):
            address = 'unbound-%04d' % index
            h.observe('pump', address, slot=100, signature='', seen=NOW-10+index/1000,
                fields=dict(development_upper_bps=9000))
            initial['eligible'].append(address)
        for index in range(16):
            family = 'pump' if index % 2 else 'pumpswap'
            address = 'reactivated-%04d' % index
            seen = NOW-200 if index < 8 else NOW-5
            h.observe(family, address, slot=100, signature='activity-'+str(index),
                seen=seen, fields=dict(activity=True, development_upper_bps=9000))
            h.bind(family, address)
            if index < 8:
                initial['expired_reactivations'].append((family, address))
        for table in ('rolling_boundary_waits', 'rolling_publication_waits'):
            for index in range(waits):
                family = 'pump' if index % 2 else 'pumpswap'
                address = table+'-%04d' % index
                h.observe(family, address, slot=101, signature='', seen=NOW-5, fields={})
                h.bind(family, address)
                deadline = NOW-1 if index < waits//2 else NOW+120
                h.db.execute('INSERT INTO '+table+' VALUES(?,?,?,?,?,?,?,?)',
                    (family, address, 101, 103, deadline, 4, NOW-5, 'pending'))
                if deadline < NOW:
                    initial['expired_waits'].append((table, family, address))
        for index in range(jobs):
            family = 'pump' if index % 2 else 'pumpswap'
            address = 'job-%04d' % index
            h.observe(family, address, slot=100, signature='', seen=NOW-5, fields={})
            h.bind(family, address)
            expired, covered = index % 4 == 0, index % 4 == 3
            deadline = NOW-1 if expired else NOW+100+index/1000
            identity = h.request(family, address, 100 if covered else 101,
                100 if covered else 103, priority=1 if covered else 3, deadline=deadline)
            initial['deadlines'][identity] = deadline
            if expired:
                initial['expired_jobs'].append(identity)
            if covered:
                initial['covered_jobs'].append(identity)
            if index % 4 == 2:
                initial['local_plans'].append((family, address, 101, 103))
            if index % 4 == 1:
                # A disclosed durable synthetic backoff; no failed provider
                # response is supplied and no cursor/coverage is advanced.
                h.db.execute('UPDATE acquisition_jobs SET error=? WHERE id=?',
                    (json.dumps(dict(kind='archive_provider_failure', retry_after=NOW+60)), identity))
    return initial


def _snapshot(state, initial, *, full=True):
    h = install(state)
    tables = {}
    for table in (TABLES if full else ()):
        rows = h.db.execute('SELECT * FROM '+table).fetchall()
        rows.sort(key=lambda row: json.dumps(row, sort_keys=True, default=lambda value: value.hex()))
        tables[table] = dict(rows=len(rows), sha256=_digest(rows))
    job_rows = {row[0]: row[1:] for row in h.db.execute(
        'SELECT id,status,deadline,priority,token,pages FROM acquisition_jobs')}
    bound = {row[0] for row in h.db.execute("SELECT address FROM evidence_bindings WHERE family='pump'")}
    states = {(row[0], row[1]): row[2] for row in h.db.execute(
        'SELECT family,address,state FROM candidate_lifecycle')}
    plans = {tuple(row) for row in h.db.execute('''SELECT json_extract(body,'$.family'),
        json_extract(body,'$.address'),json_extract(body,'$.lo'),json_extract(body,'$.hi')
        FROM rolling_preparation_jobs WHERE json_extract(body,'$.kind') IS NULL''')}
    missing = []
    for table, family, address in initial['expired_waits']:
        row = h.db.execute('SELECT status FROM '+table+' WHERE family=? AND address=?',
            (family, address)).fetchone()
        if row != ('deadline_missed',):
            missing.append((table, family, address))
    complete = (all(address in bound for address in initial['eligible'])
        and all(job_rows[key][0] == 'deadline_missed' for key in initial['expired_jobs'])
        and all(job_rows[key][0] == 'complete' for key in initial['covered_jobs'])
        and all(tuple(key) in plans for key in initial['local_plans'])
        and all(states[key] == 'demoted' for key in initial['expired_reactivations'])
        and not missing)
    from meme_machine.lanes.pump.pump_acceleration_strategy import POLICY
    complete = complete and not h.development_candidates(POLICY.min_curve_progress_bps, 1)
    deadlines_preserved = all(job_rows[key][1] == value for key, value in initial['deadlines'].items())
    order = (h.db.execute('''SELECT scope,slot,transaction_index,event_index,identity,hash,first_seen
        FROM canonical_evidence ORDER BY scope,slot,transaction_index,event_index,identity''').fetchall()
        if full else None)
    return dict(tables=tables, functional_sha256=_digest(tables),
        canonical_order=order, canonical_order_sha256=_digest(order),
        complete=complete, deadlines_preserved=deadlines_preserved,
        seeded_job_statuses=job_rows,
        pending_jobs=h.db.execute("SELECT COUNT(*) FROM acquisition_jobs WHERE status='pending'").fetchone()[0],
        pending_history=h.db.execute("SELECT COUNT(*) FROM rolling_preparation_jobs WHERE status IN ('pending','active')").fetchone()[0],
        inflight=len(getattr(state, 'acquisition_inflight', ())),
        preparation_tickets=len(getattr(h, '_archive_preparation_tickets', {})),
        transaction_open=state.writer.db.in_transaction,
        synchronous=state.writer.db.execute('PRAGMA synchronous').fetchone()[0])


async def run_owner_throughput_comparison(directory, *, retained=256, eligible=32,
        jobs=128, waits=32, measured=True, urgent=False, cancel_dispatch=False):
    """One bounded arm; compare returned fingerprints before timing arms.

    The real owner interrupt handler is chained by the optional VM probe. No
    SQL, evidence predicate, plan result, RPC response or acquire finally block
    is replaced. Fixture clocks/idle yields are explicit scheduling controls.
    """
    if (any(type(value) is not int or value < 1 for value in (retained, eligible, jobs, waits))
            or retained+eligible+jobs+2*waits+16 > 1000 or jobs % 4 or waits % 2):
        raise ValueError('bounded fixture population required')
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    clock = _QuietClock()
    counters = dict(callbacks=0, commits=0, rollbacks=0, vm_steps_quantized_lower_bound=0,
        callback_wall_seconds=0., callback_thread_cpu_seconds=0., max_owner_callback_seconds=0.,
        owner_queue_seconds=0., urgent_queue_seconds=0., urgent_commands=0,
        dispatch_refusals=0, dispatch_cancellations=0, background_yields=0)
    callback_rows = []
    source = SelectiveSource(SimpleNamespace(credential='offline', identity='a'*64), None)
    source.stop = asyncio.Event()
    source.batched = True
    source.history_separated = True
    dispatch = asyncio.Event()
    owner = None
    urgent_futures = []
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ,
            {'MM_SOLANA_HISTORY_SEPARATED': '1', 'TMPDIR': str(directory.parent)}, clear=True))
        module = sys.modules[SelectiveSource.__module__]
        stack.enter_context(patch.object(module, 'time', clock))
        stack.enter_context(patch.object(module, 'asyncio', _QuietAsyncio()))
        # The candidate's constructor supports an injected scheduling clock.
        # Absence of this new module is normal on the unchanged baseline.
        try:
            development = importlib.import_module('meme_machine.solana_candidate_development')
        except ModuleNotFoundError as error:
            if error.name != 'meme_machine.solana_candidate_development':
                raise
        else:
            constructor = development.CandidateDevelopment
            stack.enter_context(patch.object(development, 'CandidateDevelopment',
                lambda history: constructor(history, clock=clock.monotonic)))
            stack.enter_context(patch.object(development, 'time', clock))

        def factory():
            with patch.dict(os.environ, MM_SOLANA_HISTORY_SEPARATED='0'):
                state, _ = state_at(directory/'canonical.sqlite', clock.time)
            state.close = state.writer.close
            return state

        owner = PriorityOwner(factory)
        await asyncio.wrap_future(owner.ready)
        async def plain(fn, priority=2):
            return await asyncio.shield(asyncio.wrap_future(await admit(owner, fn, priority=priority)))

        async def work(fn, priority=1, *, accepted=None, **options):
            submitted = time.perf_counter()
            candidate = options.get('label') == 'candidate_development'
            def timed(state):
                previous = getattr(state.writer, '_owner_progress_handler', None)
                before = dict(counters)
                def progress():
                    counters['vm_steps_quantized_lower_bound'] += VM_QUANTUM
                    return previous() if previous is not None else 0
                def trace(sql):
                    verb = sql.lstrip().split(None, 1)[0].upper()
                    if verb == 'COMMIT':counters['commits'] += 1
                    elif verb == 'ROLLBACK':counters['rollbacks'] += 1
                if measured:
                    state.writer.db.set_progress_handler(progress, VM_QUANTUM)
                    state.writer.db.set_trace_callback(trace)
                started, cpu = time.perf_counter(), time.thread_time()
                if candidate and urgent and counters['callbacks'] == 2:
                    queued = time.perf_counter()
                    def probe(_):
                        counters['urgent_commands'] += 1
                        counters['urgent_queue_seconds'] += time.perf_counter()-queued
                    urgent_futures.append(owner.submit(probe, priority=0))
                try:
                    return fn(state)
                finally:
                    elapsed, used = time.perf_counter()-started, time.thread_time()-cpu
                    if measured:
                        state.writer.db.set_trace_callback(None)
                        state.writer.db.set_progress_handler(previous, VM_QUANTUM if previous else 0)
                    if candidate:
                        counters['callbacks'] += 1
                        counters['callback_wall_seconds'] += elapsed
                        counters['callback_thread_cpu_seconds'] += used
                        counters['max_owner_callback_seconds'] = max(counters['max_owner_callback_seconds'], elapsed)
                        counters['owner_queue_seconds'] += started-submitted
                        callback_rows.append(dict(wall_seconds=elapsed, thread_cpu_seconds=used,
                            commits=counters['commits']-before['commits'] if measured else None,
                            vm_steps_quantized_lower_bound=(counters['vm_steps_quantized_lower_bound']-before['vm_steps_quantized_lower_bound']) if measured else None))
            future = await admit(owner, timed, priority=priority)
            if accepted is not None:
                accepted(future)
            wrapped = asyncio.wrap_future(future)
            try:
                value = await asyncio.shield(wrapped)
            except asyncio.CancelledError:
                wrapped.add_done_callback(lambda result: result.exception() if not result.cancelled() else None)
                raise
            except EvidenceUnavailable as error:
                if str(error) == 'evidence_background_yield':
                    counters['background_yields'] += 1
                raise
            if candidate:
                source.stop.set()
            return value

        async def refuse(*args, **kwargs):
            if cancel_dispatch and not counters['dispatch_cancellations']:
                dispatch.set()
                await asyncio.Future()  # Cancellation uses acquire's real finally.
            counters['dispatch_refusals'] += 1
            raise _OfflineDispatchRefused('no provider operation in synthetic owner benchmark')

        source.work = source_work(work, source.stop)
        source.measured_rpc = refuse
        started = time.perf_counter()
        try:
            initial = await plain(lambda state: _seed(state, retained=retained,
                eligible=eligible, jobs=jobs, waits=waits))
            before = await plain(lambda state: _snapshot(state, initial))
            current = before
            cancellation_probe = None
            for turn in range(MAX_TURNS):
                clock.tick = 1.0+(turn+1)*.101
                source.stop.clear()
                source.acquisition_idle_until = 0
                task = asyncio.create_task(source.acquire())
                watching = asyncio.create_task(dispatch.wait())
                try:
                    done, _ = await asyncio.wait((task, watching), return_when=asyncio.FIRST_COMPLETED)
                    if watching in done and dispatch.is_set() and not task.done():
                        counters['dispatch_cancellations'] += 1
                        task.cancel()
                    try:
                        await task
                    except _OfflineDispatchRefused:
                        pass
                    except asyncio.CancelledError:
                        if not dispatch.is_set():raise
                    dispatch.clear()
                finally:
                    if not watching.done():watching.cancel()
                    if not task.done():task.cancel()
                    await asyncio.gather(task, watching, return_exceptions=True)
                for future in urgent_futures:
                    await asyncio.wrap_future(future)
                current = await plain(lambda state: _snapshot(state, initial, full=False))
                if current['complete']:
                    if cancel_dispatch and cancellation_probe is None:
                        # Optional work above remains legitimately blocked on
                        # absent local-history workers. Only after its own
                        # convergence, add one explicit missing urgent request
                        # to exercise dispatch cancellation. It cannot mask the
                        # primary optional scan or supply any provider response.
                        def arm(state):
                            h = install(state)
                            h.observe('pump', 'cancellation-probe', slot=101,
                                signature='', seen=NOW, fields={})
                            h.bind('pump', 'cancellation-probe')
                            return h.request('pump', 'cancellation-probe', 101, 103,
                                priority=1, deadline=NOW+50)
                        cancellation_probe = await plain(arm, 0)
                        initial['deadlines'][cancellation_probe] = NOW+50
                    elif not cancel_dispatch or counters['dispatch_cancellations']:
                        break
            else:
                raise AssertionError('actual acquisition callbacks exceeded fixed fixture turn bound')
            current = await plain(lambda state: _snapshot(state, initial))
            reported_counters = dict(counters)
            if not measured:
                for key in ('commits', 'rollbacks', 'vm_steps_quantized_lower_bound'):
                    reported_counters[key] = None
            return dict(schema='synthetic-owner-throughput-comparison-v1',
                scope='ACTUAL_SQLITE_ACQUIRE_CALLBACKS_SYNTHETIC_POPULATION_NOT_AUTHENTIC_MARKET_REPLAY',
                cohort=dict(retained=retained, eligible=eligible, jobs=jobs, waits_per_kind=waits,
                    reactivated=16, sha256=_digest(initial)),
                runtime=dict(python=sys.version.split()[0], sqlite=sqlite3.sqlite_version),
                measured=measured, vm_quantum=VM_QUANTUM if measured else None,
                commit_counts_measured=measured, counters=reported_counters, callbacks=callback_rows,
                turns=turn+1, maximum_turns=MAX_TURNS,
                cancellation_probe=dict(id=cancellation_probe,
                    injected_after_primary_convergence=cancellation_probe is not None),
                driver_wall_seconds=time.perf_counter()-started,
                before=before, final=current, provider_calls=0, financial_authority=False,
                scheduling=dict(wall_time=NOW, poll_tick_seconds=.101,
                    idle_sleep='one_event_loop_yield', owner_clock='real_monotonic'),
                limitations=['Fresh deterministic fixtures, not live population, Btree layout or original availability.',
                    'Archive requests are refused before provider work; incomplete history remains pending.',
                    'Owner timings include optional VM/trace instrumentation only when measured=true.',
                    'Driver wall includes setup, fingerprints and fixture scheduling; it is not a market service rate.'])
        finally:
            source.stop.set()
            await asyncio.to_thread(owner.close)


class OwnerThroughputComparisonTests(unittest.IsolatedAsyncioTestCase):
    def assert_conserved(self, report):
        final = report['final']
        self.assertTrue(final['complete'])
        self.assertTrue(final['deadlines_preserved'])
        self.assertFalse(final['transaction_open'])
        self.assertEqual((final['inflight'], final['preparation_tickets']), (0, 0))
        self.assertEqual(final['synchronous'], 2)
        self.assertEqual(final['canonical_order'], report['before']['canonical_order'])
        for table in ('canonical_evidence', 'rolling_economic_events', 'candidate_content_receipts',
                      'rolling_event_lineage', 'native_order_attestations'):
            self.assertGreater(report['before']['tables'][table]['rows'], 0, table)
            self.assertEqual(final['tables'][table], report['before']['tables'][table], table)
        self.assertGreater(final['pending_jobs']+final['pending_history'], 0)
        self.assertEqual(report['provider_calls'], 0)
        self.assertFalse(report['financial_authority'])

    async def test_actual_population_is_conserved_and_vm_probe_preserves_semantics(self):
        with tempfile.TemporaryDirectory() as temporary:
            plain = await run_owner_throughput_comparison(Path(temporary)/'plain', measured=False)
            emit_owner_throughput_report(plain, 'optional_plain')
            measured = await run_owner_throughput_comparison(Path(temporary)/'measured', measured=True)
            emit_owner_throughput_report(measured, 'optional_measured')
        for report in (plain, measured):self.assert_conserved(report)
        self.assertEqual(plain['cohort'], measured['cohort'])
        self.assertEqual(plain['final'], measured['final'])
        self.assertGreater(measured['counters']['commits'], 0)
        self.assertGreater(measured['counters']['vm_steps_quantized_lower_bound'], 0)
        self.assertEqual(measured['counters']['dispatch_refusals'], 0)
        self.assertEqual(measured['counters']['dispatch_cancellations'], 0)

    async def test_actual_urgent_interruption_and_dispatch_cancel_preserve_obligations(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = await run_owner_throughput_comparison(Path(temporary)/'cancel',
                measured=True, urgent=True, cancel_dispatch=True)
            emit_owner_throughput_report(report, 'optional_then_postconvergence_cancellation')
        self.assert_conserved(report)
        self.assertEqual(report['counters']['urgent_commands'], 1)
        self.assertEqual(report['counters']['dispatch_cancellations'], 1)
        self.assertTrue(report['cancellation_probe']['injected_after_primary_convergence'])

