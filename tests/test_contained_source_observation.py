"""Contained current observation keeps the historical failed drain unchanged.

All canonical/provider/authority files are disposable offline fixtures. The
production historical hash is asserted and only patched for synthetic old bytes.
These checks never establish a historical callback disposition or live readiness.
"""
import asyncio
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from meme_machine import solana_source_drain as drain
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_selective_source import SelectiveSource
from meme_machine.operational.supervisor import Supervisor
from tests.test_solana_closure import NOW, state_at


PRODUCTION_HISTORICAL_SHA256 = '5431d349aa8539ba935861cccb93c1f4c164bce9b0173bf4c77be7b562ffa8c9'
OLD_RUN = '85ce1aa8c9c54be0addd87a37e81784b'


class ObservationFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state, self.history = state_at(self.root / 'canonical.sqlite')
        self.addCleanup(self.state.writer.close)
        self.db = self.state.writer.db
        self.db.execute("INSERT INTO candidate_checkpoints VALUES('candidate:pump:old',17,'old-receipt',1)")
        self.db.execute("""INSERT INTO candidate_history_outbox
            (id,family,address,kind,body,hash,created,consumed,priority)
            VALUES('old-history','pump','mint','canonical','{}','old-hash',1,NULL,4)""")
        self.db.execute("""INSERT INTO candidate_pending_proofs VALUES
            ('old-proof','candidate:pump:old',1,2,'alchemy_finalized_stream',?,'{}',1)""",
            ('a' * 64,))
        self.history.gap('candidate:pump:old', 1, None, 'historical_gap_retained')
        self.old = dict(state='RECOVERY_REQUIRED', terminal=True,
            source_pid=3046583, run_identity=OLD_RUN,
            accepted_handlers=564488, settled_handlers=564486, pending_handlers=2,
            unpreserved_sessions=0, preserved_partial_sessions=2, closed_sessions=2,
            all_accepted_committed=True,
            queues={name: dict(accepted=count, committed=count, pending=0)
                for name, count in (('control', 3483), ('rolling', 1311),
                    ('scout', 29065), ('candidate', 0))},
            pending_history=1480899, pending_proofs=13819,
            started_at_monotonic=10.0, terminal_at_monotonic=20.0)
        self.old_raw = json.dumps(self.old, indent=2) + '\n'
        self.old_hash = hashlib.sha256(self.old_raw.encode()).hexdigest()
        self.production_hash = drain.HISTORICAL_OBSERVATION_SHA256
        self.enterContext(patch.object(drain, 'HISTORICAL_OBSERVATION_SHA256', self.old_hash))
        self.put('source_drain', self.old_raw)
        self.enterContext(patch.dict(os.environ, dict(MM_MODE='PAPER',
            MM_OPERATIONAL_PHASE='OBSERVATION'), clear=True))
        self.runtime_guard = self.enterContext(patch.object(drain,
            '_require_observation_funding_closed', return_value=None))

    def put(self, key, raw):
        self.db.execute('INSERT OR REPLACE INTO service_health VALUES(?,?)', (key, raw))

    def value(self, key):
        row = self.db.execute('SELECT value FROM service_health WHERE key=?', (key,)).fetchone()
        return None if row is None else row[0]

    def facts(self):
        names = [row[0] for row in self.db.execute("""SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name""")]
        return {name: self.db.execute('SELECT * FROM "' + name + '"').fetchall()
            for name in names}

    def current(self, *, state='DRAINED', pending=0):
        source = SelectiveSource(SimpleNamespace(credential='offline', identity='a' * 64), None)
        body = source.drain_snapshot()
        accepted = 2 if pending else 0
        body.update(state=state, terminal=state in ('DRAINED', 'RECOVERY_REQUIRED'),
            accepted_handlers=accepted, settled_handlers=accepted - pending, pending_handlers=pending,
            terminal_at_monotonic=30.0 if state in ('DRAINED', 'RECOVERY_REQUIRED') else None)
        return body

    def marker(self, **changes):
        body = self.current()
        body.update(historical_unknown_handlers=2,
            historical_source_drain_sha256=self.old_hash, historical_recovery_verified=False)
        body.update(changes)
        return body

    def begin(self):
        body = self.current(state='RUNNING')
        body.update(historical_unknown_handlers=2,
            historical_source_drain_sha256=self.old_hash, historical_recovery_verified=False)
        raw = drain.begin_source_observation(self.state, self.old_raw, body)
        return body, raw

    def publish(self, body, observation_boundary):
        return drain.publish_source_drain(self.state, self.old_raw, body,
            contained_observation=True, observation_boundary=observation_boundary)


class ContainedSourceBoundaryTests(ObservationFixture, unittest.TestCase):
    def test_current_accounting_must_match_its_actual_source_run_pid_and_version(self):
        for change in (dict(version=2),dict(run='e'*32),dict(pid=999999)):
            body=self.marker()
            body['handler_accounting'].update(change)
            self.put(drain.OBSERVATION_DRAIN_KEY,json.dumps(body))
            before=self.facts()
            with self.subTest(change=change),self.assertRaises(EvidenceUnavailable):
                drain.historical_observation_boundary(self.state)
            self.assertEqual(self.facts(),before)

    def test_production_hash_and_separate_key_are_fixed_source_contracts(self):
        self.assertEqual(self.production_hash, PRODUCTION_HISTORICAL_SHA256)
        self.assertEqual(drain.OBSERVATION_DRAIN_KEY, 'source_drain_observation')

    def test_historical_boundary_accepts_state_and_query_only_db_without_any_writes(self):
        original = self.facts()
        changes = self.db.total_changes
        self.db.execute('PRAGMA query_only=ON')
        try:
            state_result = drain.historical_observation_boundary(self.state)
            db_result = drain.historical_observation_boundary(self.db)
        finally:
            self.db.execute('PRAGMA query_only=OFF')
        self.assertIsInstance(state_result, dict)
        self.assertEqual(state_result, db_result)
        self.assertLess(len(json.dumps(state_result).encode()), 8192)
        self.assertEqual(self.facts(), original)
        self.assertEqual(self.db.total_changes, changes)
        self.runtime_guard.assert_not_called()

    def test_contained_retention_requires_guard_but_normal_retention_still_refuses(self):
        original = self.facts()
        with self.assertRaisesRegex(EvidenceUnavailable, 'source_drain_historical_handlers_unlocated'):
            drain.retained_source_drain(self.state)
        self.runtime_guard.assert_not_called()
        self.assertEqual(drain.retained_source_drain(self.state, contained_observation=True), self.old_raw)
        self.runtime_guard.assert_called_once_with()
        self.assertEqual(self.facts(), original)
        self.runtime_guard.side_effect = EvidenceUnavailable('funding is not closed')
        with self.assertRaises(EvidenceUnavailable):
            drain.retained_source_drain(self.state, contained_observation=True)
        self.assertEqual(self.facts(), original)

    def test_reformatted_or_different_historical_bytes_never_match_the_pin(self):
        for raw in (self.old_raw + ' ', json.dumps(self.old, sort_keys=True)):
            with self.subTest(format=raw[-4:]):
                self.put('source_drain', raw)
                before = self.facts()
                with self.assertRaises(EvidenceUnavailable):
                    drain.historical_observation_boundary(self.state)
                self.assertEqual(self.facts(), before)

    def test_exact_hash_does_not_replace_the_historical_census_and_queue_checks(self):
        cases = [dict(accepted_handlers=564489), dict(settled_handlers=564487),
            dict(pending_handlers=1), dict(pending_handlers=True), dict(terminal=False),
            dict(state='DRAINED'), dict(all_accepted_committed=False),
            dict(unpreserved_sessions=1)]
        queue_changed = deepcopy(self.old)
        queue_changed['queues']['control'].update(committed=3482, pending=1)
        missing_queue = deepcopy(self.old)
        del missing_queue['queues']['rolling']
        for body in [*(dict(self.old, **change) for change in cases),
                queue_changed, missing_queue]:
            raw = json.dumps(body)
            self.put('source_drain', raw)
            before = self.facts()
            with self.subTest(body=body), patch.object(drain,
                    'HISTORICAL_OBSERVATION_SHA256', hashlib.sha256(raw.encode()).hexdigest()):
                with self.assertRaises(EvidenceUnavailable):
                    drain.historical_observation_boundary(self.state)
            self.assertEqual(self.facts(), before)

    def test_control_obligation_or_any_current_handler_row_blocks_new_observation(self):
        drain.preserve_control_recovery(self.state, 457279885, 457279885)
        before = self.facts()
        with self.assertRaises(EvidenceUnavailable):
            drain.historical_observation_boundary(self.state)
        self.assertEqual(self.facts(), before)
        self.db.execute('DELETE FROM service_health WHERE key=?', (drain.CONTROL_RECOVERY_KEY,))
        self.put(drain.HANDLER_RECOVERY_KEY, json.dumps(dict(version=1, records=[dict(
            run='c' * 32, id=1, source_pid=42, state='INTERRUPTED')])) )
        before = self.facts()
        with self.assertRaises(EvidenceUnavailable):
            drain.historical_observation_boundary(self.state)
        self.assertEqual(self.facts(), before)

    def test_explicit_clear_control_and_empty_handler_ledger_remain_readable(self):
        self.put(drain.CONTROL_RECOVERY_KEY, 'null')
        self.put(drain.HANDLER_RECOVERY_KEY, json.dumps(dict(version=1, records=[])))
        original = self.facts()
        drain.historical_observation_boundary(self.state)
        self.assertEqual(self.facts(), original)

    def test_begin_records_running_before_work_and_crash_cannot_reuse_old_clean_marker(self):
        self.put(drain.OBSERVATION_DRAIN_KEY, json.dumps(self.marker()))
        _, boundary = self.begin()
        self.assertEqual(self.value('source_drain'), self.old_raw)
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY), boundary)
        marker = json.loads(boundary)
        self.assertEqual((marker['state'], marker['terminal']), ('RUNNING', False))
        self.assertEqual(marker['historical_unknown_handlers'], 2)
        self.assertEqual(marker['historical_source_drain_sha256'], self.old_hash)
        before = self.facts()
        with self.assertRaises(EvidenceUnavailable):
            drain.historical_observation_boundary(self.state)
        self.assertEqual(self.facts(), before)

    def test_successful_current_terminal_is_separate_and_restart_visible_without_recovery_claim(self):
        started, boundary = self.begin()
        terminal = dict(started, state='DRAINED', terminal=True, terminal_at_monotonic=30.0)
        original = self.facts()
        self.assertIsNone(self.publish(terminal, boundary))
        marker = json.loads(self.value(drain.OBSERVATION_DRAIN_KEY))
        self.assertEqual(marker['state'], 'DRAINED')
        self.assertEqual(marker['historical_unknown_handlers'], 2)
        self.assertEqual(marker['historical_source_drain_sha256'], self.old_hash)
        self.assertEqual(self.value('source_drain'), self.old_raw)
        after = self.facts()
        self.assertEqual({k: v for k, v in after.items() if k != 'service_health'},
            {k: v for k, v in original.items() if k != 'service_health'})
        # A separately reopened query-only reader sees this exact restart gate.
        with closing(sqlite3.connect(self.state.writer.path.as_uri() + '?mode=ro', uri=True)) as reader:
            reader.execute('PRAGMA query_only=ON')
            drain.historical_observation_boundary(reader)
        with self.assertRaisesRegex(EvidenceUnavailable, 'source_drain_historical_handlers_unlocated'):
            drain.retained_source_drain(self.state)
        self.assertEqual(drain.retained_source_drain(self.state, contained_observation=True), self.old_raw)

    def test_failed_current_terminal_and_handler_are_preserved_and_block_next_start(self):
        started, boundary = self.begin()
        terminal = dict(started, state='RECOVERY_REQUIRED', terminal=True,
            accepted_handlers=2, settled_handlers=1, pending_handlers=1,
            terminal_at_monotonic=30.0)
        self.put(drain.HANDLER_RECOVERY_KEY, json.dumps(dict(version=1, records=[dict(
            run=started['run_identity'], id=2, source_pid=started['source_pid'],
            state='INTERRUPTED', recovery=None)])))
        handlers = self.value(drain.HANDLER_RECOVERY_KEY)
        self.publish(terminal, boundary)
        marker = json.loads(self.value(drain.OBSERVATION_DRAIN_KEY))
        self.assertEqual((marker['state'], marker['pending_handlers']), ('RECOVERY_REQUIRED', 1))
        self.assertEqual(self.value('source_drain'), self.old_raw)
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY), handlers)
        before = self.facts()
        with self.assertRaises(EvidenceUnavailable):
            drain.historical_observation_boundary(self.state)
        self.assertEqual(self.facts(), before)

    def test_prior_observation_must_be_terminal_clean_and_bound_to_exact_historical_record(self):
        bad_markers = [dict(state='RUNNING', terminal=False), dict(state='DRAINING', terminal=False),
            dict(state='RECOVERY_REQUIRED'), dict(terminal=False),
            dict(historical_unknown_handlers=0), dict(historical_unknown_handlers=True),
            dict(historical_source_drain_sha256='b' * 64),
            dict(accepted_handlers=3, settled_handlers=2, pending_handlers=1),
            dict(all_accepted_committed=False), dict(unpreserved_sessions=1)]
        for changes in bad_markers:
            self.put(drain.OBSERVATION_DRAIN_KEY, json.dumps(self.marker(**changes)))
            before = self.facts()
            with self.subTest(changes=changes), self.assertRaises(EvidenceUnavailable):
                drain.historical_observation_boundary(self.state)
            self.assertEqual(self.facts(), before)

    def test_publication_requires_unchanged_running_marker_and_same_current_owner(self):
        started, boundary = self.begin()
        terminal = dict(started, state='DRAINED', terminal=True, terminal_at_monotonic=30.0)
        for changed in (boundary + '\n', json.dumps(self.marker())):
            self.put(drain.OBSERVATION_DRAIN_KEY, changed)
            before = self.facts()
            with self.assertRaises(EvidenceUnavailable):
                self.publish(terminal, boundary)
            self.assertEqual(self.facts(), before)
        self.put(drain.OBSERVATION_DRAIN_KEY, boundary)
        for changes in (dict(run_identity='f' * 32), dict(source_pid=started['source_pid'] + 1)):
            before = self.facts()
            with self.subTest(changes=changes), self.assertRaises(EvidenceUnavailable):
                self.publish(dict(terminal, **changes), boundary)
            self.assertEqual(self.facts(), before)

    def test_original_owner_transaction_rolls_back_current_publication(self):
        started, boundary = self.begin()
        terminal = dict(started, state='DRAINED', terminal=True, terminal_at_monotonic=30.0)
        before = self.facts()
        with self.assertRaisesRegex(RuntimeError, 'injected current terminal rollback'):
            with self.state.writer.transaction():
                self.publish(terminal, boundary)
                raise RuntimeError('injected current terminal rollback')
        self.assertEqual(self.facts(), before)
        self.assertEqual(self.value('source_drain'), self.old_raw)


class ContainedSourceBootTests(ObservationFixture, unittest.IsolatedAsyncioTestCase):
    async def invoke_boot(self, *, mode='PAPER', phase='OBSERVATION', admitted=True):
        source = SelectiveSource(SimpleNamespace(credential='offline', identity='a' * 64), None)
        stop = asyncio.Event()
        probe = RuntimeError('offline stop before original install')

        async def work(function, priority=2, **options):
            return function(self.state)

        def stop_at_install(state):
            marker = json.loads(self.value(drain.OBSERVATION_DRAIN_KEY))
            self.assertEqual((marker['state'], marker['terminal']), ('RUNNING', False))
            self.assertEqual(self.value('source_drain'), self.old_raw)
            raise probe

        with patch.dict(os.environ, MM_MODE=mode, MM_OPERATIONAL_PHASE=phase), \
                patch('meme_machine.solana_selective_source.install', side_effect=stop_at_install) as install, \
                patch.object(source, 'measured_rpc', new_callable=AsyncMock) as rpc, \
                patch('meme_machine.solana_selective_source.grpc.aio.secure_channel') as channel:
            if admitted:
                with self.assertRaises(RuntimeError) as caught:
                    await asyncio.wait_for(source.run(work, stop), .5)
                self.assertIs(caught.exception, probe)
                install.assert_called_once_with(self.state)
                snapshot = source.drain_snapshot()
                self.assertEqual(snapshot['historical_unknown_handlers'], 2)
                self.assertEqual(snapshot['historical_source_drain_sha256'], self.old_hash)
            else:
                with self.assertRaises(EvidenceUnavailable):
                    await asyncio.wait_for(source.run(work, stop), .5)
                install.assert_not_called()
                snapshot = source.drain_snapshot()
                self.assertNotIn('historical_unknown_handlers', snapshot)
                self.assertNotIn('historical_source_drain_sha256', snapshot)
            rpc.assert_not_awaited()
            channel.assert_not_called()

    async def test_exact_observation_context_marks_running_before_original_install(self):
        await self.invoke_boot()
        self.runtime_guard.assert_called()
        self.assertEqual(self.value('source_drain'), self.old_raw)

    async def test_normal_or_nonpaper_context_never_enables_historical_containment(self):
        original = self.facts()
        for mode, phase in (('PAPER', 'continuous'), ('PAPER', 'observation'), ('LIVE', 'OBSERVATION')):
            with self.subTest(mode=mode, phase=phase):
                await self.invoke_boot(mode=mode, phase=phase, admitted=False)
                self.assertEqual(self.facts(), original)
        self.runtime_guard.assert_not_called()

    async def test_failed_runtime_guard_never_stamps_an_admitted_snapshot_or_running_marker(self):
        original = self.facts()
        self.runtime_guard.side_effect = EvidenceUnavailable('unverified funding closure')
        await self.invoke_boot(admitted=False)
        self.assertEqual(self.facts(), original)


class SourceObservationEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.enterContext(patch('meme_machine.operational.supervisor.pons_capability_path', return_value=None))
        self.enterContext(patch('meme_machine.lanes.pons.log_windows.protected_capability_path', return_value=None))

    def service(self, admission):
        service = Supervisor(self.root, offline=False, admission=admission)
        service.epoch = 'paper-observation-fixture'
        return service

    def test_only_observation_source_receives_observation_phase(self):
        service = self.service('OBSERVATION')
        for lane in ('solana', 'pump', 'pons'):
            child = service.environment(lane)
            self.assertEqual(child['MM_MODE'], 'PAPER')
            self.assertEqual(child['MM_PAPER_EPOCH'], service.epoch)
            self.assertEqual(child['MM_STATE_ROOT'], str(self.root))
            self.assertEqual(child['MM_OPERATIONAL_PHASE'],
                'OBSERVATION' if lane == 'solana' else 'continuous')

    def test_parent_phase_cannot_promote_normal_source_or_override_observation_source(self):
        for admission, inherited, expected in (('NORMAL', 'OBSERVATION', 'continuous'),
                ('OBSERVATION', 'continuous', 'OBSERVATION')):
            with self.subTest(admission=admission), patch.dict(os.environ, MM_OPERATIONAL_PHASE=inherited):
                self.assertEqual(self.service(admission).environment('solana')['MM_OPERATIONAL_PHASE'], expected)


class ObservationFundingClosureTests(unittest.TestCase):
    """Real existing Budget and selected shared replay, never a funded trade."""
    def setUp(self):
        from meme_machine.operational.bounded_provider import Budget
        from meme_machine.shared_capital.runtime import process_identity
        from tests.test_pump_pons_capital_preparation import RuntimeIntegrationTests

        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.root, self.authority, self.now, self.plan = RuntimeIntegrationTests.fixture(
            self, owners=False, new_epoch=True)
        self.usage = self.root / 'shared/provider-usage.sqlite'
        profile_path = Path(__file__).resolve().parents[1] / (
            'operational/pump-first-release/deployment/paper-continuous.four-regime.json')
        self.profile = json.loads(profile_path.read_text())
        self.profile_file = self.root / 'selected-continuous-profile.json'
        self.profile_file.write_text(json.dumps(self.profile))
        self.budget = Budget.create(self.usage, continuous=self.profile)
        self.environment = dict(MM_MODE='PAPER', MM_OPERATIONAL_PHASE='OBSERVATION',
            MM_STATE_ROOT=str(self.root), MM_PAPER_EPOCH=self.plan['seed']['epoch_id'],
            MM_PROVIDER_OPERATION_MODE='CONTINUOUS', MM_PROVIDER_USAGE_DB=str(self.usage),
            MM_CONTINUOUS_PROVIDER_ENVELOPE=str(self.profile_file))
        self.enterContext(patch.dict(os.environ, self.environment, clear=True))
        self.sequence = 0
        self.scope = dict(mode='OBSERVATION', run_id='f' * 32, pid=os.getpid(),
            process_start=process_identity(os.getpid()), provider_db=str(self.usage),
            continuous_provider_db=str(self.usage))
        self.admit()

    def admit(self, **changes):
        self.sequence += 1
        self.authority.command('fixture-observation-scope-' + str(self.sequence),
            'runtime_admission', dict(self.scope, **changes), self.now)

    def facts(self):
        result = {}
        for path in (self.root / 'portfolio.sqlite', self.root / 'shared-capital.sqlite', self.usage):
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                db.execute('PRAGMA query_only=ON')
                names = [row[0] for row in db.execute("""SELECT name FROM sqlite_master
                    WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name""")]
                result[path.name] = {name: db.execute('SELECT * FROM "' + name + '"').fetchall()
                    for name in names}
        return result

    def test_real_selected_flat_authority_and_closed_budget_are_verified_without_constructors_or_writes(self):
        before = self.facts()
        with patch('meme_machine.operational.bounded_provider.Budget.__init__',
                side_effect=AssertionError('guard must not construct a writable Budget')), \
                patch('meme_machine.operational.bounded_provider.Budget.create',
                    side_effect=AssertionError('guard must never create a Budget')):
            drain._require_observation_funding_closed()
        self.assertEqual(self.facts(), before)
        self.assertEqual(self.budget.snapshot()['new_risk_ready'], 'false')
        self.assertEqual(self.authority.ledger()['runtime_admission']['mode'], 'OBSERVATION')

    def test_real_provider_readiness_failure_and_invalid_configuration_refuse_without_rewriting_usage(self):
        cases = [('new_risk_ready', 'true'), ('new_risk_ready', '0'),
            ('reason', 'fixture_retained_provider_failure'),
            ('continuous_envelope', '{"schema":"unselected-profile"}')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                with closing(sqlite3.connect(self.usage)) as db:
                    old = db.execute('SELECT value FROM run WHERE key=?', (key,)).fetchone()[0]
                    db.execute('UPDATE run SET value=? WHERE key=?', (value, key))
                    db.commit()
                before = self.facts()
                with self.assertRaises(EvidenceUnavailable):
                    drain._require_observation_funding_closed()
                self.assertEqual(self.facts(), before)
                with closing(sqlite3.connect(self.usage)) as db:
                    db.execute('UPDATE run SET value=? WHERE key=?', (old, key))
                    db.commit()

    def test_real_selected_admission_must_remain_observation_and_bind_both_usage_paths(self):
        for changes in (dict(mode='NORMAL'),
                dict(provider_db=str(self.root / 'shared/other.sqlite')),
                dict(continuous_provider_db=str(self.root / 'shared/other.sqlite'))):
            with self.subTest(changes=changes):
                self.admit(**changes)
                before = self.facts()
                with self.assertRaises(EvidenceUnavailable):
                    drain._require_observation_funding_closed()
                self.assertEqual(self.facts(), before)
                self.admit()

    def test_wrong_environment_or_missing_selected_budget_does_not_create_or_mutate_files(self):
        for key, value in (('MM_MODE', 'LIVE'), ('MM_OPERATIONAL_PHASE', 'continuous'),
                ('MM_PAPER_EPOCH', 'paper-other-epoch'),
                ('MM_PROVIDER_USAGE_DB', str(self.root / 'shared/missing-usage.sqlite'))):
            before = self.facts()
            with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                with self.assertRaises(EvidenceUnavailable):
                    drain._require_observation_funding_closed()
            self.assertEqual(self.facts(), before)
        self.assertFalse((self.root / 'shared/missing-usage.sqlite').exists())

    def test_original_flat_portfolio_check_is_not_replaced_by_observation_admission(self):
        # The real selected authority is flat. Inject one observed obligation
        # only at the readonly reader seam to exercise refusal without trading.
        ledger = self.authority.ledger()
        ledger['runtime_pending'] = dict(fixture_obligation=dict(state='UNRESOLVED'))
        before = self.facts()
        with patch('meme_machine.shared_capital.reporting.read_authority',
                return_value=SimpleNamespace(ledger=lambda: deepcopy(ledger))):
            with self.assertRaises(EvidenceUnavailable):
                drain._require_observation_funding_closed()
        self.assertEqual(self.facts(), before)


if __name__ == '__main__':
    unittest.main()
