"""Disposable integrated startup contracts, never a faithful market replay.

The real supervisor, lane entrypoints, native constructors and durable history
protocol are exercised. Controlled provider boundaries and the offline process
fixture deliberately provide no market-capacity or held-protection proof.
"""
from collections import deque
from contextlib import ExitStack, closing
import copy
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engineering.diagnostics.current_combined_observation_20261014 import SingleAttemptSupervisor
from meme_machine.operational import lane
from meme_machine.operational.supervisor import Supervisor
from meme_machine.paper_policy_revision import ACTIVE_REVISION, previous_hash
from meme_machine.runtime import status, stop
from meme_machine.solana_evidence_plane import EvidenceUnavailable, IntervalProof, digest
from meme_machine.solana_history_delivery import capture, deliver, acknowledge
from meme_machine.solana_history_work import HistoricalTasks, prepare_history
from meme_machine.solana_selective_history import PROGRAMS, economic_records
from meme_machine.solana_rolling_history import program_scope
from tests.test_solana_closure import NOW, state_at
from tests.test_solana_selective_evidence import FIXTURE


class IntegratedStartupRehearsal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {'PATH': os.environ.get('PATH', ''), 'MM_MODE': 'PAPER',
                    'MM_PAPER_POLICY_REVISION': ACTIVE_REVISION,
                    'MM_PAPER_EPOCH': 'offline-fixture-integrated-startup'}
        self.environment = patch.dict(os.environ, self.env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.saved_status = (status.state, status._operations, status._completed,
                             status._signal, stop.requested.is_set())
        status.state = dict(phase='RECONCILING', reconciled=False)
        status._operations = []
        status._completed = deque(maxlen=8)
        status._signal = None
        stop.requested.clear()
        self.addCleanup(self.restore_status)
        self.signals = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        self.addCleanup(lambda: [signal.signal(s, h) for s, h in self.signals.items()])
        self.health_threads_before = {thread for thread in threading.enumerate()
                                      if thread.name == 'health'}
        # Runs before process-global status/event restoration. The production
        # heartbeat remains unchanged; only this in-process fixture joins its
        # newly constructed threads to prevent a late sample in the next test.
        self.addCleanup(self.join_fixture_health)

    def join_fixture_health(self):
        stop.requested.set()
        owned = [thread for thread in threading.enumerate()
                 if thread.name == 'health' and thread not in self.health_threads_before]
        for thread in owned:thread.join(2)
        self.assertFalse(any(thread.is_alive() for thread in owned),
                         'disposable_native_health_thread_not_stopped')

    def restore_status(self):
        status.state, status._operations, status._completed, status._signal, requested = self.saved_status
        if requested:
            stop.requested.set()
        else:
            stop.requested.clear()

    def service(self):
        output = self.root / 'diagnostic'
        output.mkdir(exist_ok=True)
        service = SingleAttemptSupervisor(self.root, output=output, offline=True)
        self.addCleanup(lambda: service.lock.close() if service.lock else None)
        return service

    def test_real_supervisor_and_offline_children_start_recover_and_stop(self):
        """Real process ownership/native journals; fills are synthetic mechanics."""
        service = self.service()
        started = []; reached = []; failures = []
        watcher_stop = threading.Event()
        popen = subprocess.Popen
        def spawn(*args, **kwargs):
            started.append((list(args[0]), dict(kwargs['env'])))
            return popen(*args, **kwargs)
        def observe():
            end = time.monotonic() + 12
            while not watcher_stop.is_set() and time.monotonic() < end:
                rows = []
                for family in ('pump', 'pons'):
                    try:
                        rows.append(json.loads((self.root / family / 'health.json').read_text()))
                    except (OSError, ValueError):
                        break
                if (len(rows) == 2 and all(row.get('reconciled') is True and
                        row.get('phase') in ('MANAGING', 'DISCOVERING') for row in rows)):
                    reached.extend(rows);service.stop_requested = True;return
                time.sleep(.02)
            if not watcher_stop.is_set():
                failures.append('offline_children_never_reached_native_fixture_reconciliation')
                service.stop_requested = True
        watcher = threading.Thread(target=observe, name='fixture-readiness', daemon=True)
        watcher.start()
        try:
            with patch('meme_machine.operational.supervisor.subprocess.Popen', side_effect=spawn):
                service.run(seconds=12)
        finally:
            service.stop_requested = True
            watcher_stop.set()
            watcher.join(2)
        self.assertFalse(watcher.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(reached), 2)
        self.assertEqual(len(started), 2)
        for command, env in started:
            self.assertIn('meme_machine.operational.lane', command)
            self.assertIn('--offline', command)
            self.assertEqual(env['MM_PAPER_POLICY_REVISION'], ACTIVE_REVISION)
            self.assertEqual(env['MM_PAPER_EPOCH'], service.epoch)
            self.assertFalse(any('RPC_URL' in key for key in env))
        for family, process in service.processes.items():
            self.assertEqual(process.poll(), 0, family)
            row = json.loads((self.root / family / 'health.json').read_text())
            self.assertEqual(row['phase'], 'STOPPED')
            self.assertTrue(row['reconciled'])
            self.assertEqual(row['market_calls'], 0)
        with service.account() as account:
            self.assertTrue(account._reconcile(account.snapshot())['checks']['cash_basis_conservation'])
        self.assertEqual(service.attempted_lanes, {'pump', 'pons'})

    def test_actual_child_launcher_keeps_managed_route_and_native_state_distinct(self):
        service = self.service();service.initialize();service.offline = False
        endpoint = 'https://robinhood-mainnet.g.alchemy.com/v2/disposable-fixture'
        with patch.dict(os.environ, MM_PONS_OBSERVATION_ROUTE='canonical_primary',
                        MM_ROBINHOOD_READ_RPC_URL=endpoint), \
                patch('meme_machine.operational.supervisor.subprocess.Popen') as spawn:
            spawn.return_value.pid = 123
            service.start_lane('pons')
        command = spawn.call_args.args[0];child = spawn.call_args.kwargs['env']
        self.assertNotIn('--offline', command)
        self.assertEqual(child['MM_PAPER_POLICY_REVISION'], ACTIVE_REVISION)
        self.assertEqual(child['MM_PONS_OBSERVATION_ROUTE'], 'canonical_primary')
        self.assertEqual(child['MM_RPC_CACHE_DB'], str(self.root / 'shared/robinhood-evidence.sqlite'))
        self.assertEqual(child['MM_DIRECTIONAL_SLEEVE_DB'], str(self.root / 'pons/directional-sleeve.sqlite'))
        from meme_machine.lanes.pons.provider_topology import discovery_endpoint
        self.assertEqual(discovery_endpoint(environ=child), (endpoint, True))

    def canonical(self):
        (self.root / 'shared').mkdir(exist_ok=True)
        state, history = state_at(self.root / 'shared/canonical.sqlite')
        self.addCleanup(lambda: state.writer.close())
        history.lifecycle.delivery_separated = True
        tasks = HistoricalTasks(history)
        history.historical_tasks = tasks
        records = [record for tx in FIXTURE['pump'] for record in economic_records(
            'pump', PROGRAMS['pump'], copy.deepcopy(tx), endpoint_identity='a' * 64,
            seen=NOW, source='alchemy_finalized_stream')]
        history.ingest(records)
        return state, history, tasks, records

    def test_canonical_historian_consumer_restart_preserves_pending_then_exact_ack(self):
        state, history, tasks, records = self.canonical()
        pending = state.writer.db.execute('SELECT id,hash FROM candidate_history_outbox '
                                         'WHERE consumed IS NULL ORDER BY id').fetchall()
        self.assertTrue(pending)
        snapshot = capture(history.lifecycle);result = deliver(snapshot)
        # Consumer success without the exact authoritative ACK is not completion.
        self.assertEqual(state.writer.db.execute('SELECT id,hash FROM candidate_history_outbox '
                         'WHERE consumed IS NULL ORDER BY id').fetchall(), pending)
        path = state.writer.path
        state.writer.close()
        state, history = state_at(path)
        self.addCleanup(state.writer.close)
        history.lifecycle.delivery_separated = True
        tasks = HistoricalTasks(history);history.historical_tasks = tasks
        replay = capture(history.lifecycle)
        self.assertTrue(acknowledge(history.lifecycle, replay, deliver(replay)))
        self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM candidate_history_outbox '
                         'WHERE consumed IS NULL').fetchone()[0], 0)
        mint = next(r.payload['event']['mint'] for r in records if r.payload['event']['event_type'] == 'create')
        self.assertEqual(len({r.identity for r in records}), len(records))
        from meme_machine.runtime.candidate_history import CandidateHistory
        with closing(CandidateHistory(history.lifecycle.path, clock=lambda: NOW)) as consumer:
            self.assertEqual(len(consumer.events('pump', mint)), len(records))
        # Missing canonical coverage must remain unavailable, including after
        # a durable historian obligation and restart-style reclaim.
        history.bind('pumpswap', 'pending-pool')
        request = history.rolling.prepare('pumpswap', 'pending-pool', 100, 110,
                                         priority=3, deadline=NOW + 150)
        self.assertFalse(request['entry_authority'])
        job = tasks.claim();self.assertIsNotNone(job)
        completed = prepare_history(state.writer.path, job)
        metric = tasks.apply(job, completed)
        self.assertFalse(metric['entry_authority'])
        self.assertTrue(metric['missing_intervals'])
        required = history.request('pumpswap', 'pending-pool', 100, 110,
                                   priority=3, deadline=NOW + 150)
        self.assertTrue(required)
        self.assertTrue(state.writer.db.execute('SELECT 1 FROM acquisition_jobs '
                        "WHERE status<>'complete' LIMIT 1").fetchone())

    def test_busy_history_consumer_records_actual_failure_without_acknowledging_pending(self):
        from meme_machine.runtime.candidate_history import CandidateHistory
        state, history, _, _ = self.canonical()
        snapshot = capture(history.lifecycle)
        before = state.writer.db.execute('SELECT id,hash FROM candidate_history_outbox '
                 'WHERE consumed IS NULL ORDER BY id').fetchall()
        with closing(CandidateHistory(history.lifecycle.path, clock=lambda: NOW)) as blocker:
            blocker.db.execute('BEGIN IMMEDIATE')
            try:
                with self.assertRaises(sqlite3.OperationalError) as caught:deliver(snapshot)
                self.assertEqual(caught.exception.sqlite_errorcode & 255, sqlite3.SQLITE_BUSY)
                facts = caught.exception.sqlite_failure
                self.assertEqual(facts['database'], str(history.lifecycle.path.resolve()))
                self.assertEqual(facts['pid'], os.getpid())
                self.assertEqual(facts['native_thread_id'], threading.get_native_id())
                self.assertTrue(facts['connection_identity'])
                self.assertEqual(facts['scope'], 'candidate_delivery.deliver')
                self.assertEqual(state.writer.db.execute('SELECT id,hash FROM candidate_history_outbox '
                                 'WHERE consumed IS NULL ORDER BY id').fetchall(), before)
            finally:blocker.db.execute('ROLLBACK')
        repeated = capture(history.lifecycle)
        self.assertTrue(acknowledge(history.lifecycle, repeated, deliver(repeated)))

    def pump_setup(self, stack):
        from meme_machine.lanes.pump import runner
        state, history, tasks, records = self.canonical()
        folder = self.root / 'pump';folder.mkdir(exist_ok=True)
        (folder / 'native-genesis.json').write_text(json.dumps(dict(capital=1_000_000_000)))
        child = dict(MM_SOLANA_EVIDENCE_PLANE_DB=str(state.writer.path),
            MM_SOLANA_CANDIDATE_HISTORY_DB=str(history.lifecycle.path),
            MM_SOLANA_EVIDENCE_BROKER_DB=str(folder / 'broker.sqlite'),
            MM_DIRECTIONAL_SLEEVE_DB=str(folder / 'sleeve.sqlite'),
            MM_DIRECTIONAL_COHORT_ID=self.env['MM_PAPER_EPOCH'],
            MM_DIRECTIONAL_COMPOSITE_REQUIRED='1')
        stack.enter_context(patch.dict(os.environ, child))
        for name in ('ACCOUNTING', 'PIPELINE', 'CANDIDATE_HISTORY', 'FILL_PERSISTENCE_CONTEXT',
                     'INITIAL_LAMPORTS', 'ENTRY_BUDGET'):
            stack.enter_context(patch.object(runner, name, getattr(runner, name)))
        stack.enter_context(patch.object(runner, 'REPORT', folder / 'report.json'))
        resources = []
        startup = runner._startup_work
        def opened(identity, call, *args, **kwargs):
            value = startup(identity, call, *args, **kwargs)
            if callable(getattr(value, 'close', None)):resources.append(value)
            return value
        def close_fixture_resources():
            # Startup faults can precede the runner's own loop finally. Close
            # only newly constructed disposable fixture resources, Survivor
            # first so its connections stay on their owning executor.
            for resource in reversed(resources):
                try:resource.close()
                except (sqlite3.ProgrammingError, RuntimeError):
                    pass  # Already closed by the actual native drain.
        stack.callback(close_fixture_resources)
        stack.enter_context(patch.object(runner, '_startup_work', side_effect=opened))
        # Native RPC-session construction is a controlled boundary. Local books,
        # evidence readers, broker, history and Survivor constructors remain real.
        sessions = SimpleNamespace(history=[], rpc=SimpleNamespace(http_requests=0),
            postgrad=SimpleNamespace(held_pumpswap_probe_reuses=0, held_finalized_time_reuses=0),
            pump=SimpleNamespace(local_finalized_time_reuses=0),
            finish=lambda: None, holder_probe_status=lambda: {})
        stack.enter_context(patch.object(runner, 'Sessions', return_value=sessions))
        stack.enter_context(patch.object(runner, '_restore_observed_pump_candidates', return_value=0))
        # Use the normal publication implementation synchronously in this
        # mechanics fixture, avoiding an unrelated background reporting actor.
        from meme_machine.lanes.pump import durable_publication
        publication = durable_publication.publish_report
        stack.enter_context(patch.object(durable_publication, 'publish_report',
            side_effect=lambda path, report, **kwargs: publication(path, report, asynchronous=False)))
        stack.enter_context(patch('meme_machine.operational.bounded_provider.install'))
        stack.enter_context(patch('sys.argv', ['lane', '--lane', 'pump', '--state-root', str(self.root)]))
        return runner, state, history

    def test_actual_pump_lane_startup_initializes_owned_survivor_and_cancels_without_ack_loss(self):
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime
        owned = [];pending_before = None
        with ExitStack() as stack:
            runner, state, history = self.pump_setup(stack)
            pending_before = state.writer.db.execute('SELECT id,hash FROM candidate_history_outbox '
                            'WHERE consumed IS NULL ORDER BY id').fetchall()
            def controlled_history_step(runtime, *, admit):
                owned.append((runtime, threading.get_native_id(), admit))
                self.assertIsNotNone(runtime.history.db)
                self.assertIsNotNone(runtime.book.db)
                self.assertIsNotNone(runtime.candidate_history)
                return dict(last_boundary='fixture_missing_current_coverage',
                    accounting=dict(open_positions=0, reserved=0),
                    accounting_replay=dict(verified=True), durable_handoff=False)
            stack.enter_context(patch.object(Runtime, 'step', controlled_history_step))
            def cancel_after_native_restore(*args, **kwargs):
                status.cancellation_signal(signal.SIGTERM);stop.requested.set()
                raise stop.Shutdown()
            stack.enter_context(patch.object(runner, '_monitor_positions', side_effect=cancel_after_native_restore))
            lane.main()
            final = json.loads((self.root / 'pump/health.json').read_text())
            self.assertEqual(state.writer.db.execute('SELECT id,hash FROM candidate_history_outbox '
                             'WHERE consumed IS NULL ORDER BY id').fetchall(), pending_before)
            self.assertIsNone(runner.CANDIDATE_HISTORY)
            self.assertIsNone(runner.ACCOUNTING)
        self.assertEqual(final['phase'], 'STOPPED')
        self.assertTrue(final['reconciled'])  # Current native empty-book restore only.
        self.assertEqual(len(owned), 1)
        self.assertNotEqual(owned[0][1], threading.get_native_id())
        self.assertIs(owned[0][2], False)
        self.assertFalse(final.get('native_continuation', {}).get('survivor_handoff_ready', False))

    def test_actual_pump_startup_failure_preserves_operation_pending_and_unfinished_status(self):
        # This deliberately stops before runner's loop-level finally. Its
        # process-exit cleanup is not claimed to be a graceful native drain.
        with ExitStack() as stack:
            runner, state, history = self.pump_setup(stack)
            before = state.writer.db.execute('SELECT id,hash FROM candidate_history_outbox '
                     'WHERE consumed IS NULL ORDER BY id').fetchall()
            error = EvidenceUnavailable('fixture_required_canonical_dependency_missing')
            stack.enter_context(patch.object(runner, 'RuntimeEvidence', side_effect=error))
            try:
                with self.assertRaises(EvidenceUnavailable) as caught:lane.main()
                self.assertIs(caught.exception, error)
                observed = status.snapshot()
                self.assertIs(observed['reconciled'], False)
                self.assertEqual(observed['native_recent_operations'][-1]['operation'],
                                 'pump.runtime_evidence_open')
                self.assertEqual(observed['native_recent_operations'][-1]['state'], 'ERROR')
                self.assertEqual(state.writer.db.execute('SELECT id,hash FROM candidate_history_outbox '
                                 'WHERE consumed IS NULL ORDER BY id').fetchall(), before)
            finally:
                # Test-owned in-process resources only. A killed real worker's
                # SQLite descriptors close on process exit; this test neither
                # repairs production startup cleanup nor declares reconciliation.
                for name in ('CANDIDATE_HISTORY', 'ACCOUNTING', 'PIPELINE'):
                    resource = getattr(runner, name)
                    if resource is not None:resource.close()
                    setattr(runner, name, None)
                stop.requested.set()

    def cohort_paths(self, stack):
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        folder = self.root / 'pons';folder.mkdir(exist_ok=True)
        values = dict(ROOT=folder, REPORT=folder / 'report.json', SKILL_DB=folder / 'skill.sqlite',
            PROGRESS=folder / 'progress.json', ROWS_LOG=folder / 'rows.jsonl',
            QUALIFIERS_LOG=folder / 'qualifiers.jsonl', PROVIDER_LOG=folder / 'provider.jsonl',
            RECOVERY_LOG=folder / 'recovery.jsonl')
        for name, path in values.items():stack.enter_context(patch.object(cohort, name, path))
        stack.enter_context(patch.object(cohort, 'STRATEGY_CAPITAL_QUOTE', 1000))
        from meme_machine.lanes.pons import pons_selective_paper
        stack.enter_context(patch.object(pons_selective_paper, 'STRATEGY_CAPITAL_QUOTE', 1000))
        stack.enter_context(patch.dict(os.environ, MM_RPC_CACHE_DB=str(self.root / 'shared/canonical.sqlite')))
        (self.root / 'shared').mkdir(exist_ok=True)
        (folder / 'native-genesis.json').write_text(json.dumps(dict(capital=1000)))
        stack.enter_context(patch.dict(os.environ,
            MM_ROBINHOOD_READ_RPC_URL='https://robinhood-mainnet.g.alchemy.com/v2/disposable-fixture',
            MM_DIRECTIONAL_COMPOSITE_REQUIRED='1',
            MM_DIRECTIONAL_SLEEVE_DB=str(folder / 'sleeve.sqlite'),
            MM_DIRECTIONAL_COHORT_ID=self.env['MM_PAPER_EPOCH']))
        stack.enter_context(patch('meme_machine.operational.bounded_provider.install'))
        stack.enter_context(patch('sys.argv', ['lane', '--lane', 'pons', '--state-root', str(self.root)]))
        return cohort, folder, self.root / 'shared/canonical.candidates.sqlite'

    def seed_cohort(self, folder, plane, *, unresolved=False):
        from meme_machine.lanes.pons import pons_selective_capital as capital
        from meme_machine.runtime.robinhood.pons import Broker
        from tests.lanes.pons.test_pons_candidate_plane import event
        old = previous_hash('pons_current')
        with patch.object(capital, 'POLICY_HASH', old):
            book = capital.CohortCapital(folder / 'pons-selective-cohort-capital.sqlite', 1000)
        if unresolved:
            book.reserve('retained-open', 100, at=100, decision_hash='fixture', trial_path='retained-trial')
        # This nomination is retained across the policy restart, but remains
        # within its unchanged nomination/retention deadlines during rehearsal.
        # An epoch-100 fixture would legitimately retire under the real clock.
        observed = time.time()
        broker = Broker(plane, old, clock=lambda: observed)
        broker.enqueue(event())
        saved = dict(result=dict(policy_hash=old, rows=[], qualifiers=[], lifecycles=[],
            discovery_sessions=[], sequencer_recoveries=[], started_at=100,
            operational_configuration=dict(campaign=True), candidate_plane_path=str(plane)),
            cursor=123, phase='paused', owner='not-a-live-owner', checkpoint_at=100)
        broker.plane.checkpoint('pons_cohort', saved);broker.close()
        return saved

    def test_actual_pons_cohort_recovery_reaches_provider_boundary_with_shared_cache(self):
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
        with ExitStack() as stack:
            cohort, folder, plane = self.cohort_paths(stack)
            saved = self.seed_cohort(folder, plane)
            observed = [];owned = []
            def controlled_history_step(runtime, *, admit):
                owned.append((runtime, threading.get_native_id(), admit))
                self.assertIsNotNone(runtime.history.db)
                self.assertIsNotNone(runtime.book.db)
                return dict(last_boundary='fixture_missing_provider_evidence',
                    accounting=dict(open_positions=0, reserved=0),
                    accounting_replay=dict(verified=True), durable_handoff=False)
            stack.enter_context(patch.object(Runtime, 'step', controlled_history_step))
            def provider_boundary(*args, **kwargs):
                observed.append(status.snapshot())
                stop.requested.set();raise stop.Shutdown()
            stack.enter_context(patch.object(cohort, '_start_observation', side_effect=provider_boundary))
            try:lane.main()
            finally:stop.requested.set()
            final = json.loads((folder / 'health.json').read_text())
        self.assertEqual(len(observed), 1)
        self.assertTrue(observed[0]['reconciled'])
        self.assertEqual(final['phase'], 'STOPPED')
        self.assertTrue(final['reconciled'])
        self.assertEqual(len(owned), 1)
        self.assertNotEqual(owned[0][1], threading.get_native_id())
        self.assertIs(owned[0][2], False)
        self.assertFalse(final.get('native_continuation', {}).get('survivor_handoff_ready', False))
        self.assertFalse((plane.parent / 'pons-selective-cohort-capital.sqlite').exists())
        from meme_machine.runtime.robinhood.plane import Plane
        with closing(Plane(plane)) as recovered:
            self.assertEqual(recovered.checkpoint_read('pons_cohort'), saved)
            self.assertEqual(recovered.db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0], 1)

    def test_actual_pons_cohort_unresolved_native_capital_stops_before_provider(self):
        with ExitStack() as stack:
            cohort, folder, plane = self.cohort_paths(stack)
            saved = self.seed_cohort(folder, plane, unresolved=True)
            with patch.object(cohort, '_start_observation') as transport:
                try:
                    with self.assertRaisesRegex(ValueError, 'transition_unresolved_capital'):lane.main()
                finally:stop.requested.set()
            transport.assert_not_called()
        self.assertIs(status.snapshot()['reconciled'], False)
        from meme_machine.runtime.robinhood.plane import Plane
        with closing(Plane(plane)) as recovered:
            self.assertEqual(recovered.checkpoint_read('pons_cohort'), saved)

    def test_real_provider_admission_rejection_keeps_pending_and_original_deadline(self):
        from meme_machine.lanes.pons import BoundaryError
        from meme_machine.lanes.pons.provider_admission import Admission
        now = [100.];physical = []
        admission = Admission(self.root / 'admission.sqlite', 'https://provider.invalid',
            lane='pons', clock=lambda: now[0], sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds))
        error = BoundaryError('provider_http_429')
        error.provider_http_context = dict(http_status=429, truncated=False,
            response_headers={'retry-after': '8'})
        def rejected():physical.append(now[0]);raise error
        with self.assertRaises(BoundaryError) as caught:
            admission.invoke(rejected, ['eth_getLogs'] * 4, 'discovery', deadline=105.)
        self.assertEqual(str(caught.exception), 'provider_http_429')
        self.assertIs(caught.exception.provider_http_context, error.provider_http_context)
        with self.assertRaisesRegex(BoundaryError, 'deadline'):
            admission.invoke(lambda: physical.append(now[0]), ['eth_getLogs'], 'discovery', deadline=105.)
        self.assertEqual(physical, [100.])
        with closing(admission.connect()) as reader:
            records = [json.loads(row[0]) for row in reader.execute('SELECT body FROM admissions')]
        self.assertTrue(any(row.get('deadline') == 105. and row.get('granted') is False for row in records))
        # A protection endpoint has its own shared identity, unaffected by the
        # rejected public endpoint. This is scheduling proof, not live latency.
        canonical = Admission(admission.path, 'https://canonical.invalid', lane='pons',
            clock=lambda: now[0], sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds))
        self.assertEqual(canonical.invoke(lambda: 'controlled-quote', ['eth_call'],
            'paper_unwind', deadline=now[0] + 3), 'controlled-quote')


if __name__ == '__main__':
    unittest.main()
