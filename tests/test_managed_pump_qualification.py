"""Native nonfinancial read-side regressions; every input/provider is offline."""
import base64
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import unittest
import zlib
from unittest.mock import Mock, patch

from meme_machine.operational import managed_native_pump as managed
from meme_machine.operational import managed_pump_qualification as qualification
from meme_machine.runtime.candidate_history import CandidateHistory
from tests import test_managed_native_pump as fixtures


class _BaselineQualificationReader(qualification.QualificationReader):
    """Exactly the predecessor read pairs, with the same strategy/cursor code."""
    def _history_event(self, mint, identity, *, prepared=None):
        self._reference_scope(mint, identity)
        return self.history.event('pump', mint, identity)

    def _creation_events(self, mint):
        self._reference_scope(mint, kind='pump_create')
        return self.history.events('pump', mint, kind='pump_create',
                                   cancelled=self.cancelled.is_set)


class ReaderSQLTests(unittest.TestCase):
    def setUp(self):
        from tests.test_managed_pump_discovery_publication import GlobalPumpPublicationTests
        self.fixture = GlobalPumpPublicationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.config
        self.row = self.fixture.trade()
        self.mint = self.row.payload['event']['mint']
        self.identity = 'pump-source:' + self.row.identity
        self.fixture.history.ingest([self.row])

    def worker(self, baseline=False, name=None):
        parent = _BaselineQualificationReader if baseline else qualification.QualificationReader
        config = self.config
        name = name or ('baseline' if baseline else 'optimized')
        class Reader(parent):
            @property
            def path(self):
                return Path(config.root) / (name + '-qualification.sqlite')
        worker = Reader(config, clock=lambda: self.row.observed_at + 1)
        self.addCleanup(worker.close)
        self.assertTrue(worker._open())
        return worker

    def publish(self):
        from meme_machine.solana_history_delivery import capture, deliver, acknowledge
        snapshot = capture(self.fixture.life)
        self.assertTrue(acknowledge(self.fixture.life, snapshot, deliver(snapshot)))

    def publish_creation(self):
        from meme_machine.solana_selective_history import PROGRAMS, economic_records
        from tests.test_solana_selective_evidence import FIXTURE
        creation = next(row for tx in FIXTURE['pump'] for row in economic_records(
            'pump', PROGRAMS['pump'], deepcopy(tx),
            endpoint_identity=self.fixture.history.endpoint_identity,
            seen=self.row.observed_at, source='alchemy_finalized_stream')
            if row.payload['event']['event_type'] == 'create'
            and row.payload['event']['mint'] == self.mint)
        self.fixture.history.ingest([creation])
        self.publish()
        return creation

    def traced(self, worker, fn):
        statements = []
        connections = [worker.history.db, worker.plane.reader.db,
                       *getattr(worker.history, '_source_readers', {}).values()]
        for db in connections:
            db.set_trace_callback(statements.append)
        try:
            value = fn()
        finally:
            for db in connections:
                db.set_trace_callback(None)
        selects = [sql for sql in statements if sql.lstrip().upper().startswith('SELECT')]
        return value, selects

    def observations(self, worker):
        return worker.db.execute('SELECT * FROM observations ORDER BY sequence').fetchall()

    def test_real_compact_reference_reuses_selection_and_keeps_fresh_source_authentication(self):
        self.publish()
        old, new = self.worker(True), self.worker()
        for worker in (old, new):
            worker._history_event(self.mint, self.identity)  # Open each native reference reader.
        before, old_sql = self.traced(old, lambda:old._history_event(self.mint, self.identity))
        after, new_sql = self.traced(new, lambda:new._history_event(self.mint, self.identity))
        self.assertEqual(before, after)
        self.assertEqual((len(old_sql), len(new_sql)), (5, 4))
        for statements in (old_sql, new_sql):
            self.assertEqual(sum('SELECT archive FROM canonical_evidence' in sql for sql in statements), 1)
            self.assertEqual(sum('SELECT body,hash,archive FROM canonical_evidence' in sql for sql in statements), 1)
        self.assertEqual(sum('FROM canonical_event_refs' in sql for sql in new_sql), 1)

    def test_actual_native_text_decodes_once_and_keeps_identical_decisions(self):
        from meme_machine.solana_evidence_plane import decode_body
        self.publish()
        old, new = self.worker(True), self.worker()
        raw = self.fixture.history.db.execute(
            'SELECT body FROM canonical_evidence WHERE identity=?',
            (self.row.identity,)).fetchone()[0]
        self.assertIs(type(raw), str)  # Actual normalized rolling native representation.
        with patch('meme_machine.solana_evidence_plane.decode_body', wraps=decode_body) as decode:
            before = old.step()
            self.assertEqual(decode.call_count, 2)
            decode.reset_mock()
            after = new.step()
            self.assertEqual(decode.call_count, 1)
        self.assertEqual(before, after)
        self.assertEqual(self.observations(old), self.observations(new))

    def test_prepared_reference_retains_decode_fallback_for_compressed_and_changed_bytes(self):
        from meme_machine.solana_evidence_plane import decode_body
        self.publish()
        old, new = self.worker(True), self.worker()
        raw = self.fixture.history.db.execute(
            'SELECT body FROM canonical_evidence WHERE identity=?',
            (self.row.identity,)).fetchone()[0]
        record = decode_body(raw, self.fixture.history.db)
        prepared = (record, qualification._canonical(record))
        expected = old._history_event(self.mint, self.identity)
        variants = (b'SEP1' + zlib.compress(raw.encode(), 1),
                    json.dumps(record, sort_keys=True, indent=2))
        for representation in variants:
            with self.subTest(representation=type(representation).__name__):
                with sqlite3.connect(self.config.evidence) as db:
                    db.execute('UPDATE rolling_economic_events SET body=? WHERE identity=?',
                               (representation, self.row.identity))
                for worker in (old, new):
                    with patch('meme_machine.solana_evidence_plane.decode_body', wraps=decode_body) as decode:
                        self.assertEqual(worker._history_event(self.mint, self.identity,
                            prepared=prepared), expected)
                        self.assertEqual(decode.call_count, 1)
        changed = deepcopy(record)
        changed['payload']['event']['mint'] = 'different-mint'
        with sqlite3.connect(self.config.evidence) as db:
            db.execute('UPDATE rolling_economic_events SET body=?,hash=? WHERE identity=?',
                (qualification._canonical(changed), hashlib.sha256(
                    qualification._canonical(changed).encode()).hexdigest(), self.row.identity))
        for worker in (old, new):
            with self.assertRaisesRegex(ValueError, 'candidate_history_corruption'):
                worker._history_event(self.mint, self.identity, prepared=prepared)

    def test_unserializable_discovery_outer_does_not_preempt_original_foreign_reference_guard(self):
        from meme_machine.solana_evidence_plane import decode_body
        self.publish()
        old, new = self.worker(True), self.worker()
        raw = self.fixture.history.db.execute(
            'SELECT body FROM canonical_evidence WHERE identity=?',
            (self.row.identity,)).fetchone()[0]
        malformed = decode_body(raw, self.fixture.history.db)
        malformed['payload']['event']['nonfinite_corruption'] = float('nan')
        with sqlite3.connect(self.config.evidence) as db:
            db.execute('UPDATE rolling_economic_events SET body=? WHERE identity=?',
                       (json.dumps(malformed), self.row.identity))
        with sqlite3.connect(self.config.history) as db:
            ref = json.loads(db.execute('SELECT body FROM canonical_event_refs WHERE identity=?',
                                        (self.identity,)).fetchone()[0])
            ref['path'] = '/original/financial/source.sqlite'
            db.execute('UPDATE canonical_event_refs SET body=? WHERE identity=?',
                       (qualification._canonical(ref), self.identity))
        for worker in (old, new):
            with self.assertRaisesRegex(ValueError, 'foreign_qualification_reference'):
                worker.step()
            self.assertEqual(self.observations(worker), [])

    def test_missing_creation_reuses_selection_without_caching_absence(self):
        self.publish()
        old, new = self.worker(True), self.worker()
        before, old_sql = self.traced(old, lambda:old._creation_events(self.mint))
        after, new_sql = self.traced(new, lambda:new._creation_events(self.mint))
        self.assertEqual(before, after)
        self.assertEqual(after, [])
        self.assertEqual((len(old_sql), len(new_sql)), (3, 2))
        # A later history commit must be visible to both existing readers.
        history = CandidateHistory(self.config.history)
        try:
            history.append_event('pump', self.mint, identity='legacy-creation',
                slot=1, transaction_index=0, event_index=0, market_time=1,
                kind='pump_create', payload=dict(event_type='create', mint=self.mint))
        finally:
            history.close()
        self.assertEqual(old._creation_events(self.mint), new._creation_events(self.mint))
        self.assertEqual(len(new._creation_events(self.mint)), 1)

    def test_native_creation_keeps_authentication_order_and_both_legacy_reference_populations(self):
        self.publish_creation()
        history = CandidateHistory(self.config.history)
        try:
            history.append_event('pump', self.mint, identity='legacy-creation',
                slot=1, transaction_index=None, event_index=1, market_time=1,
                kind='pump_create', payload=dict(event_type='create', mint=self.mint))
        finally:
            history.close()
        old, new = self.worker(True), self.worker()
        for worker in (old, new):
            worker._creation_events(self.mint)
        before, old_sql = self.traced(old, lambda:old._creation_events(self.mint))
        after, new_sql = self.traced(new, lambda:new._creation_events(self.mint))
        self.assertEqual(before, after)
        self.assertEqual(len(after), 2)
        self.assertEqual(after[0]['identity'], 'legacy-creation')
        self.assertEqual((len(old_sql), len(new_sql)), (5, 4))
        for worker in (old, new):
            worker.cancelled.set()
            from meme_machine.runtime.stop import Shutdown
            with self.assertRaises(Shutdown):
                worker._creation_events(self.mint)
            worker.cancelled.clear()
            self.assertEqual(worker._creation_events(self.mint), before)

    def test_legacy_point_precedence_does_not_start_authenticating_an_unused_reference(self):
        self.publish()
        old, new = self.worker(True), self.worker()
        legacy = old._history_event(self.mint, self.identity)
        legacy['payload']['legacy_precedence'] = True
        raw = qualification._canonical(legacy)
        with sqlite3.connect(self.config.history) as db:
            db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)',
                ('pump', self.mint, self.identity, legacy['slot'], legacy['transaction_index'],
                 legacy['event_index'], legacy['market_time'], legacy['kind'], raw,
                 hashlib.sha256(raw.encode()).hexdigest()))
            db.execute('UPDATE canonical_event_refs SET hash=? WHERE identity=?',
                       ('f'*64, self.identity))
        self.assertEqual(old._history_event(self.mint, self.identity), legacy)
        self.assertEqual(new._history_event(self.mint, self.identity), legacy)
        # Locator safety still precedes legacy selection as in the predecessor.
        with sqlite3.connect(self.config.history) as db:
            ref = json.loads(db.execute('SELECT body FROM canonical_event_refs WHERE identity=?',
                                        (self.identity,)).fetchone()[0])
            ref['path'] = '/original/financial/source.sqlite'
            db.execute('UPDATE canonical_event_refs SET body=? WHERE identity=?',
                       (qualification._canonical(ref), self.identity))
        for worker in (old, new):
            with self.assertRaisesRegex(ValueError, 'foreign_qualification_reference'):
                worker._history_event(self.mint, self.identity)

    def test_real_native_decision_cursor_and_resume_match_predecessor_with_less_sql(self):
        self.publish()
        old, new = self.worker(True), self.worker()
        for worker in (old, new):
            worker._history_event(self.mint, self.identity)
        before, old_sql = self.traced(old, old.step)
        after, new_sql = self.traced(new, new.step)
        self.assertEqual(before, after)
        self.assertEqual(self.observations(old), self.observations(new))
        self.assertEqual(before['stages'], {'creation_unavailable':1})
        self.assertEqual(len(old_sql)-len(new_sql), 2)
        self.assertEqual(old.step(), new.step())
        expected = self.observations(new)
        old.close();new.close()
        # Existing handles are closed explicitly; suppress their second cleanup.
        old.history = old.plane = old.db = None
        new.history = new.plane = new.db = None
        resumed_old, resumed_new = self.worker(True), self.worker()
        self.assertEqual(resumed_old.step(), resumed_new.step())
        self.assertEqual(expected, self.observations(resumed_new))

    def test_unpublished_native_input_keeps_both_cursors_pending_until_real_publication(self):
        old, new = self.worker(True), self.worker()
        self.assertEqual(old.step(), new.step())
        self.assertEqual(self.observations(new), [])
        self.publish()
        self.assertEqual(old.step(), new.step())
        self.assertEqual(self.observations(old), self.observations(new))

    def test_compact_reference_corruption_foreign_locator_and_source_hash_fail_identically(self):
        self.publish()
        old, new = self.worker(True), self.worker()
        with sqlite3.connect(self.config.history) as db:
            original = db.execute('SELECT body,hash FROM canonical_event_refs WHERE identity=?',
                                  (self.identity,)).fetchone()
        with sqlite3.connect(self.config.evidence) as db:
            source_hash = db.execute('SELECT hash FROM rolling_economic_events WHERE identity=?',
                                     (self.row.identity,)).fetchone()[0]
        for case in ('reference_hash', 'foreign_locator', 'source_hash'):
            with self.subTest(case=case):
                with sqlite3.connect(self.config.history) as db:
                    ref = json.loads(original[0])
                    if case == 'foreign_locator':
                        ref['path'] = '/original/financial/source.sqlite'
                    raw = qualification._canonical(ref)
                    checksum = 'f'*64 if case == 'reference_hash' else hashlib.sha256(raw.encode()).hexdigest()
                    db.execute('UPDATE canonical_event_refs SET body=?,hash=? WHERE identity=?',
                               (raw, checksum, self.identity))
                with sqlite3.connect(self.config.evidence) as db:
                    db.execute('UPDATE rolling_economic_events SET hash=? WHERE identity=?',
                               ('e'*64 if case == 'source_hash' else source_hash, self.row.identity))
                outcomes = []
                for worker in (old, new):
                    try:
                        worker.step()
                    except Exception as error:
                        outcomes.append((type(error), str(error)))
                    else:
                        self.fail('native identity corruption must not advance the cursor')
                    self.assertEqual(self.observations(worker), [])
                self.assertEqual(outcomes[0], outcomes[1])

    def test_cold_reference_uses_the_same_locator_manifest_payload_and_hash_guards(self):
        from meme_machine.solana_evidence_plane import decode_body
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        self.publish()
        old, new = self.worker(True), self.worker()
        expected = old._history_event(self.mint, self.identity)
        ScopedRetirement(self.fixture.history)
        raw = self.fixture.history.db.execute(
            'SELECT body FROM canonical_evidence WHERE identity=?',
            (self.row.identity,)).fetchone()[0]
        record = decode_body(raw, self.fixture.history.db)
        directory = self.config.evidence.with_suffix('.scoped-cold')
        directory.mkdir(mode=0o700)
        path = directory / ('a'*64 + '.zlib')
        packed = zlib.compress(qualification._canonical([dict(record=record,
            available=self.row.observed_at)]).encode())
        path.write_bytes(packed);path.chmod(0o600)
        checksum = hashlib.sha256(packed).hexdigest()
        with sqlite3.connect(self.config.evidence) as db:
            db.execute('INSERT INTO scoped_cold_manifests VALUES(?,?,?,?,?,?,?)',
                ('cold', str(path), checksum, 1, len(raw), len(packed), self.row.observed_at))
            db.execute('UPDATE rolling_economic_events SET body=NULL,archive=? WHERE identity=?',
                       ('cold', self.row.identity))
        prepared = (record, qualification._canonical(record))
        self.assertEqual(old._history_event(self.mint, self.identity, prepared=prepared), expected)
        self.assertEqual(new._history_event(self.mint, self.identity, prepared=prepared), expected)
        for case in ('payload_hash', 'foreign_archive', 'missing_manifest'):
            with self.subTest(case=case):
                with sqlite3.connect(self.config.evidence) as db:
                    if case == 'missing_manifest':
                        db.execute('DELETE FROM scoped_cold_manifests WHERE id=?', ('cold',))
                    else:
                        db.execute('UPDATE scoped_cold_manifests SET path=?,hash=? WHERE id=?',
                            ('/original/financial/archive.zlib' if case == 'foreign_archive' else str(path),
                             'f'*64 if case == 'payload_hash' else checksum, 'cold'))
                outcomes = []
                for worker in (old, new):
                    try:
                        worker._history_event(self.mint, self.identity)
                    except Exception as error:
                        outcomes.append((type(error), str(error)))
                    else:
                        self.fail('cold reference guard must fail closed')
                self.assertEqual(outcomes[0], outcomes[1])


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ManagedPumpTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.stores()
        self.config = self.fixture.config
        environment = managed.production_environment(self.config)
        environment.__enter__()
        self.addCleanup(environment.__exit__, None, None, None)
        self.worker = qualification.QualificationReader(self.config, clock=lambda: 1000)
        self.addCleanup(self.worker.close)

    def source(self, event, *, publish=True, identity='native-event'):
        canonical = dict(identity=identity, kind='event', slot=10,
            transaction_index=0, event_index=0, market_time=1000,
            payload=dict(event=event))
        with sqlite3.connect(self.config.evidence) as db:
            db.execute('INSERT INTO candidate_outbox VALUES(?,?,?,?,?)',
                (1, identity, 'program:pump', 10, 1000))
        if publish:
            self.publish(event, identity=identity)
        return canonical

    def publish(self, event, *, identity='native-event'):
        history = CandidateHistory(self.config.history)
        try:
            history.observe('pump', event['mint'], surface='pump.fun', observed_at=1000)
            history.append_event('pump', event['mint'], identity='pump-source:' + identity,
                slot=10, transaction_index=0, event_index=0, market_time=1000,
                kind='pump_' + event['event_type'], payload=event)
        finally:
            history.close()

    def discovery(self, canonical):
        reader = self.worker.plane._selective_reader()
        return patch.object(reader, 'discovery', side_effect=lambda sequence, **kwargs:
            [] if sequence >= 1 else [(1, json.dumps(canonical), 10, 'native-event',
                                       'signature', 0, 0, 1000, 1000)])

    def test_native_publication_is_required_before_durable_consumer_progress(self):
        event = dict(mint='mint', creator='creator', event_type='create', market_time=1000)
        canonical = self.source(event, publish=False)
        self.assertTrue(self.worker._open())
        with self.discovery(canonical):
            first = self.worker.step()
            self.assertEqual(first['native_event_backlog'], 1)
            self.assertEqual(first['durably_observed_native_events'], 0)
            self.publish(event)
            with patch.object(CandidateHistory, '__init__', side_effect=AssertionError('second_writer')):
                result = self.worker.step()
                repeated = self.worker.step()
        self.assertEqual(result['native_event_backlog'], 0)
        self.assertEqual(repeated['durably_observed_native_events'], 1)
        self.assertEqual(result['stages'], {'creation_observed': 1})
        self.assertFalse(result['full_qualification_proven'])
        with self.assertRaises(sqlite3.OperationalError):
            self.worker.history.db.execute('DELETE FROM candidates')
        self.assertEqual(managed.pump_snapshot(self.config)['history']['funding'], 0)

    def test_payload_disagreement_cannot_advance_the_native_cursor(self):
        event = dict(mint='mint', creator='creator', event_type='create', market_time=1000)
        canonical = self.source(event, publish=False)
        self.publish(dict(event, creator='different'))
        self.assertTrue(self.worker._open())
        with self.discovery(canonical), self.assertRaisesRegex(ValueError, 'source_identity'):
            self.worker.step()
        self.assertEqual(self.worker.snapshot()['durably_observed_native_events'], 0)

    def test_foreign_reference_fails_before_the_native_reader_opens_it(self):
        self.assertTrue(self.worker._open())
        raw = json.dumps(dict(path='/original/economic/evidence.sqlite'))
        with sqlite3.connect(self.config.history) as db:
            db.execute('INSERT INTO canonical_event_refs VALUES(?,?,?,?,?,?,?,?,?,?)',
                ('pump', 'mint', 'pump-source:native-event', 10, 0, 0, 1000,
                 'pump_create', raw, hashlib.sha256(raw.encode()).hexdigest()))
        with patch.object(self.worker.history, 'event', side_effect=AssertionError('foreign_open')):
            with self.assertRaisesRegex(ValueError, 'foreign_qualification_reference'):
                self.worker._reference_scope('mint', 'pump-source:native-event')

    def test_reference_target_is_explicit_and_pinned_on_restart(self):
        self.assertTrue(self.worker._open())
        self.worker.close()
        self.worker.history = self.worker.plane = self.worker.db = None
        changed = qualification.QualificationReader(self.config, decision_target=100)
        self.addCleanup(changed.close)
        with self.assertRaisesRegex(ValueError, 'qualification_identity_changed'):
            changed._open()
        for target in (True, 0, -1, '100'):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'decision_target_required'):
                qualification.QualificationReader(self.config, decision_target=target)

    def test_missing_target_does_not_buy_rpc_or_record_false_full_completion(self):
        from meme_machine.lanes.pump import runner
        from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
        from tests.lanes.pump.test_pump_acceleration_strategy import PumpAccelerationStrategyTests
        event = dict(mint='mint', market_time=1000, event_type='trade', slot=10,
            index=0, _economic_order=0, real_token_reserves=200)
        self.publish(dict(mint='mint', creator='creator', market_time=900,
                          event_type='create', initial_real_token_reserves=1000))
        self.assertTrue(self.worker._open())
        self.worker.provider = Mock(side_effect=AssertionError('no_quote_authority'))
        self.worker.confirmations = ConfirmationBook({}, 0)
        record = dict(payload=event, candidate='mint', identity='trade', kind='pump_trade')
        signal = PumpAccelerationStrategyTests().strong_late()
        with patch.object(self.worker.plane, 'pump_events', return_value=[]), \
                patch.object(runner, '_late_stream_signal', return_value=(signal, {}, {})), \
                patch.object(runner, '_late_stream_prospect', return_value=(runner.qualify(signal), ())):
            result, _ = self.worker._evaluate(None, record)
        self.assertEqual(result['stage'], 'decision_target_unavailable')
        self.assertFalse(result['full_qualification_complete'])
        self.worker.provider.snapshot.assert_not_called()

    def test_explicit_native_vector_matches_production_without_opening_a_sleeve(self):
        from meme_machine.lanes.pump import pump, runner
        from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
        fixture = json.loads((Path(__file__).parent /
            'lanes/pump/fixtures/mainnet_candidate_accounts.json').read_text())
        accounts = deepcopy(fixture['response']['value'])
        curve = pump.curve(accounts[0])
        initial = min(curve.supply, curve.token) * 3 // 4
        raw = bytearray(base64.b64decode(accounts[0]['data'][0]))
        struct.pack_into('<Q', raw, 24, initial // 5)
        accounts[0]['data'][0] = base64.b64encode(raw).decode()
        curve = pump.curve(accounts[0])
        creation = dict(mint='MINT', creator=curve.creator,
                        initial_real_token_reserves=5 * curve.real_token)
        events = [dict(mint='MINT', wallet='wallet' + str(i), market_time=980+i,
            real_token_reserves=curve.real_token, virtual_quote_reserves=curve.sol,
            virtual_token_reserves=curve.token, slot=i+1, index=0, buy=True,
            amount=20_000_000) for i in range(20)]
        snapshot = dict(mint='MINT', accounts=accounts, slot=100,
                        market_time=1000, available_time=1000)
        confirmations = ConfirmationBook({}, 0)
        target = 10_000_000
        with patch.object(runner, '_current_pump_sizing', return_value=dict(target=target)):
            native, _, _ = runner._late_signal(creation, events, snapshot, 1500, confirmations)
        with patch('meme_machine.runtime.directional_sleeve.open_sleeve',
                   side_effect=AssertionError('financial_open')):
            isolated = qualification.full_late_signal(creation, events, snapshot, 1500,
                                                     confirmations, target)
        self.assertEqual(isolated, native)
        self.assertEqual(runner.qualify(isolated), runner.qualify(native))

    def admitted(self, *, expires=1010, fail=None):
        from meme_machine.runtime.usd_valuation import USDValue
        from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
        self.now = [1000]
        self.worker.clock = lambda: self.now[0]
        value = USDValue('SOL', 9, Decimal('100'), 990, expires, 'offline-native-oracle', 'a'*64)
        reader = Mock(side_effect=fail) if fail else Mock(return_value=value)
        self.worker.target = qualification.FreshReferenceSizing(self.config.generation,
            clock=lambda: self.now[0], value_reader=reader)
        self.publish(dict(mint='mint', creator='creator', market_time=900,
            event_type='create', initial_real_token_reserves=1000), identity='creation')
        event = dict(mint='mint', market_time=1000, event_type='trade', slot=10,
            index=0, _economic_order=0, real_token_reserves=200)
        canonical = self.source(event)
        self.assertTrue(self.worker._open())
        self.worker.confirmations = ConfirmationBook({}, 0)
        self.worker.provider = Mock()
        self.worker.provider.snapshot.return_value = dict(mint='mint', market_time=1000, slot=10)
        self.worker.provider.concentration.return_value = 1500
        return canonical, reader

    def evaluate_admitted(self, canonical):
        from meme_machine.lanes.pump import runner
        from tests.lanes.pump.test_pump_acceleration_strategy import PumpAccelerationStrategyTests
        signal = PumpAccelerationStrategyTests().strong_late()
        with self.discovery(canonical), \
                patch.object(self.worker.plane, 'pump_events', return_value=[]), \
                patch.object(runner, '_late_stream_signal', return_value=(signal, {}, {})), \
                patch.object(runner, '_late_stream_prospect', return_value=(runner.qualify(signal), ())), \
                patch.object(qualification, 'full_late_signal', return_value=signal) as full, \
                patch('meme_machine.runtime.directional_sleeve.open_sleeve',
                      side_effect=AssertionError('financial_sleeve_forbidden')):
            result = self.worker.step()
        row = self.worker.db.execute('SELECT body,hash,full_complete FROM observations').fetchone()
        self.assertEqual(hashlib.sha256(row[0].encode()).hexdigest(), row[1])
        self.assertEqual(managed.pump_snapshot(self.config)['history']['funding'], 0)
        with sqlite3.connect(self.config.history) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM decisions').fetchone()[0], 0)
        return result, json.loads(row[0]), full

    def test_fresh_reference_reaches_full_native_qualification_and_durable_provenance(self):
        canonical, reader = self.admitted()
        result, observed, full = self.evaluate_admitted(canonical)
        self.assertEqual(result['stages'], {'native_full_qualification': 1})
        self.assertEqual(result['native_event_backlog'], 0)
        self.assertEqual(result['full_qualifications'], 1)
        self.assertFalse(result['full_qualification_proven'] or result['financial_authority'])
        reader.assert_called_once_with(1000)
        self.assertEqual([call.args[-1] for call in full.call_args_list], [500_000_000]*2)
        self.worker.provider.snapshot.assert_called_once_with('mint', 1000)
        self.worker.provider.concentration.assert_called_once()
        sizing = observed['decision_sizing']
        self.assertEqual(sizing['reference_equity_usd'], '1000.00')
        self.assertFalse(sizing['actual_shared_ledger'] or sizing['financial_authority'])
        self.assertEqual(sizing['generation'], self.config.generation)
        self.assertEqual(sizing['valuation']['evidence_hash'], 'a'*64)

    def test_identical_sizing_snapshot_and_native_inputs_keep_full_decision_and_evidence(self):
        canonical, value_reader = self.admitted()
        optimized = self.worker
        target = qualification.FreshReferenceSizing(self.config.generation,
            clock=lambda: self.now[0], value_reader=value_reader)
        config = self.config
        class Reference(_BaselineQualificationReader):
            @property
            def path(self):
                return Path(config.root) / 'full-decision-reference.sqlite'
        reference = Reference(config, decision_target=target,
                              clock=lambda: self.now[0])
        self.addCleanup(reference.close)
        self.assertTrue(reference._open())
        reference.confirmations = deepcopy(optimized.confirmations)
        reference.provider = Mock()
        reference.provider.snapshot.return_value = deepcopy(optimized.provider.snapshot.return_value)
        reference.provider.concentration.return_value = optimized.provider.concentration.return_value
        outputs = []
        try:
            for worker in (reference, optimized):
                self.worker = worker
                result, observed, _ = self.evaluate_admitted(canonical)
                outputs.append((result, observed, worker.db.execute(
                    'SELECT * FROM observations ORDER BY sequence').fetchall()))
        finally:
            self.worker = optimized
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0][0]['full_qualifications'], 1)
        self.assertTrue(outputs[0][1]['full_qualification_complete'])

    def test_missing_or_expired_valuation_is_incomplete_and_does_not_invent_a_target(self):
        from meme_machine.runtime.usd_valuation import ValuationUnavailable
        canonical, reader = self.admitted(fail=ValuationUnavailable('secret-provider-unavailable'))
        result, observed, full = self.evaluate_admitted(canonical)
        self.assertEqual(result['stages'], {'native_evidence_incomplete': 1})
        self.assertFalse(observed['full_qualification_complete'])
        self.assertEqual(observed['failure_type'], 'ValuationUnavailable')
        self.assertNotIn('secret-provider', json.dumps(observed))
        self.worker.provider.snapshot.assert_not_called(); full.assert_not_called()

    def test_original_oracle_expiry_after_concentration_prevents_full_completion(self):
        canonical, reader = self.admitted(expires=1000)
        def concentration(*_):
            self.now[0] = 1001
            return 1500
        self.worker.provider.concentration.side_effect = concentration
        result, observed, full = self.evaluate_admitted(canonical)
        self.assertEqual(result['stages'], {'native_evidence_incomplete': 1})
        self.assertFalse(observed['full_qualification_complete'])
        self.assertEqual(full.call_count, 1)
        self.assertEqual(observed['decision_sizing']['valuation']['valid_until'], 1000)

    def test_original_oracle_expiry_during_snapshot_stops_before_capacity_or_concentration(self):
        canonical, reader = self.admitted(expires=1000)
        snapshot = self.worker.provider.snapshot.return_value
        def delayed(*_):
            self.now[0] = 1001
            return snapshot
        self.worker.provider.snapshot.side_effect = delayed
        result, observed, full = self.evaluate_admitted(canonical)
        self.assertEqual(result['stages'], {'native_evidence_incomplete': 1})
        self.assertFalse(observed['full_qualification_complete'])
        full.assert_not_called();self.worker.provider.concentration.assert_not_called()

    def test_reference_identity_survives_price_change_but_not_scope_or_generation_change(self):
        from meme_machine.runtime.usd_valuation import USDValue
        first = qualification.FreshReferenceSizing(self.config.generation, clock=lambda: 1000,
            value_reader=lambda _: USDValue('SOL', 9, Decimal('100'), 990, 1010, 'one', 'a'*64))
        self.worker.target = first
        self.assertTrue(self.worker._open());self.worker.close()
        second = qualification.FreshReferenceSizing(self.config.generation, clock=lambda: 1000,
            value_reader=lambda _: USDValue('SOL', 9, Decimal('200'), 990, 1010, 'two', 'b'*64))
        resumed = qualification.QualificationReader(self.config, decision_target=second, clock=lambda: 1000)
        self.addCleanup(resumed.close)
        self.assertTrue(resumed._open())
        self.assertEqual(first(1000).lamports, 2*second(1000).lamports)
        with self.assertRaisesRegex(ValueError, 'decision_target_generation'):
            qualification.QualificationReader(self.config,
                decision_target=qualification.FreshReferenceSizing('f'*32, value_reader=Mock()))
        resumed.close()
        with patch('meme_machine.portfolio_accounting.PLANNED_SHARED_CAPITAL', '2000.00'), \
                self.assertRaisesRegex(ValueError, 'qualification_identity_changed'):
            changed = qualification.QualificationReader(self.config, decision_target=second)
            self.addCleanup(changed.close);changed._open()


class FreshSizingTests(unittest.TestCase):
    def test_actual_native_oracle_decoder_refreshes_conversion_and_keeps_original_expiry(self):
        from meme_machine.runtime.usd_valuation import NativeValueReader
        from tests.lanes.pump.test_pumpswap_survivor_evidence import EvidenceTests
        now = [100]
        oracle = EvidenceTests().oracle
        rpc = Mock()
        rpc.call.side_effect = [dict(context=dict(slot=100), value=[oracle()]),
            dict(context=dict(slot=200), value=[oracle(price=20_000_000_000, ema=20_000_000_000,
                published=221, previous=211, posted=190)])]
        reader = NativeValueReader('pump')
        target = qualification.FreshReferenceSizing('a'*32, clock=lambda: now[0], value_reader=reader)
        self.assertFalse(target.available(100))
        with patch('meme_machine.runtime.usd_valuation.time.time', side_effect=lambda: now[0]), \
                patch('meme_machine.solana_read_rpc.new_rpc', return_value=rpc), \
                patch('meme_machine.portfolio_accounting.PortfolioAccounting.__init__',
                      side_effect=AssertionError('no_financial_inception')):
            first = target(now[0]);first.validate(220)
            self.assertTrue(target.available(220))
            self.assertFalse(target.available(221))
            with self.assertRaises(ValueError):first.validate(221)
            now[0] = 221
            second = target(now[0])
        self.assertEqual(rpc.call.call_count, 2)
        self.assertEqual(first.lamports, 500_500_500)
        self.assertEqual(second.lamports, 250_125_062)
        self.assertEqual(first.provenance['valuation']['valid_until'], 220)
        self.assertEqual(second.provenance['valuation']['valid_until'], 341)

    def test_pure_sizing_preserves_predecessor_integer_floors_and_legacy_behavior(self):
        import ast
        import subprocess
        from meme_machine.shared_capital import adapter
        old = subprocess.check_output(['git', '--no-optional-locks', 'show',
            '2c6a2da067d985b97423882eac49b1123d553d02:meme_machine/shared_capital/adapter.py'],
            cwd=Path(__file__).resolve().parents[1])
        node = next(n for n in ast.parse(old).body if isinstance(n, ast.FunctionDef)
                    and n.name == 'directional_target')
        namespace = dict(vars(adapter))
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<immutable-sizing-predecessor>', 'exec'), namespace)
        previous = namespace['directional_target']
        for equity in ('-1', '0', '0.019999999', '0.02', '1.0000000001', '1000', '100000000'):
            for rate in ('0.1', '1000', '10010010.01001001001001001001'):
                ledger = dict(policy=dict(sizing_basis='shared_realized_equity'),
                    initial_capital=equity, realized={}, shared_costs='0')
                expected = previous(ledger, 'pump_current', native_units_per_usd=rate)
                current = adapter.directional_target(ledger, 'pump_current', native_units_per_usd=rate)
                self.assertEqual(current, expected)
                pure = adapter.directional_native_target(expected['native_equity'])
                self.assertEqual(pure, {k: expected[k] for k in ('native_equity', 'requested_native_units')})
        self.assertEqual(adapter.directional_native_target(19)['requested_native_units'], 0)
        self.assertEqual(adapter.directional_native_target(20)['requested_native_units'], 1)
        for invalid in (True, -1, '20', Decimal('20')):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                    adapter.CapitalError, '^verified_native_sizing_base_required$'):
                adapter.directional_native_target(invalid)
        for rate in ('500', '2000'):
            ledger = dict(policy=dict(sizing_basis='effective_family_equivalence'))
            args = dict(native_units_per_usd=rate, legacy_native_realized_equity=100003)
            self.assertEqual(adapter.directional_target(ledger, 'pump_current', **args),
                             previous(ledger, 'pump_current', **args))


if __name__ == '__main__':
    unittest.main()
