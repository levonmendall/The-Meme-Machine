"""Real native discovery/publication regressions; disposable, offline stores."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import json
import time
import unittest
from unittest.mock import patch

from meme_machine.operational import managed_native_pump as managed
from meme_machine.operational.managed_pump_qualification import QualificationReader
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_history_delivery import capture, deliver, acknowledge
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS, economic_records
from meme_machine.solana_selective_source import install
from tests import test_managed_native_pump as managed_fixtures
from tests.test_solana_selective_evidence import FIXTURE


class GlobalPumpPublicationTests(unittest.TestCase):
    def setUp(self):
        fixture = managed_fixtures.ManagedPumpTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.stores()
        self.config = fixture.config
        environment = managed.production_environment(self.config)
        environment.__enter__()
        self.addCleanup(environment.__exit__, None, None, None)
        self.state = ServiceState(self.config.evidence,
            managed.AlchemyEndpoint.parse(self.config.endpoint))
        self.addCleanup(self.state.writer.close)
        self.history = install(self.state)
        self.life = self.history.lifecycle
        self.assertTrue(self.life.delivery_separated)
        self.worker = QualificationReader(self.config)
        self.addCleanup(self.worker.close)

    def trade(self):
        for tx in FIXTURE['pump']:
            for row in economic_records('pump', PROGRAMS['pump'], deepcopy(tx),
                    endpoint_identity=self.history.endpoint_identity,
                    seen=self.history.clock(), source='alchemy_finalized_stream'):
                if row.payload['event']['event_type'] == 'trade':
                    return row
        self.fail('captured Pump fixture must include a trade')

    def pending(self, identity):
        return self.history.db.execute("""SELECT id,address,body,hash,consumed
            FROM candidate_history_outbox WHERE family='pump' AND kind='canonical'
            AND json_extract(body,'$.record.identity')=? ORDER BY rowid""",
            (identity,)).fetchall()

    def test_first_unbound_trade_is_delivered_without_creation_or_coverage_authority(self):
        row = self.trade()
        mint = row.payload['event']['mint']
        self.assertFalse(self.history.db.execute(
            'SELECT 1 FROM evidence_bindings').fetchone())
        self.history.ingest([row])
        pending = self.pending(row.identity)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0][1], mint)
        before = self.worker.step()
        self.assertEqual(before['incoming_native_events'], 1)
        self.assertEqual(before['durably_observed_native_events'], 0)
        self.assertEqual(before['native_event_backlog'], 1)
        self.assertIsNotNone(self.life.unconsumed(program_scope('pump'), through=row.slot))
        snapshot = capture(self.life)
        result = deliver(snapshot)
        # A durable consumer record is still not a canonical ACK or coverage.
        self.assertIsNotNone(self.life.unconsumed(program_scope('pump'), through=row.slot))
        self.assertEqual(self.pending(row.identity), pending)
        self.assertTrue(acknowledge(self.life, snapshot, result))
        observed = self.worker.step()
        self.assertEqual(observed['durably_observed_native_events'], 1)
        self.assertEqual(observed['native_event_backlog'], 0)
        self.assertEqual(observed['stages'], {'creation_unavailable': 1})
        self.assertFalse(observed['full_qualification_proven'])
        self.assertEqual(observed['full_qualifications'], 0)
        for table in ('evidence_bindings', 'rolling_origins', 'candidate_checkpoints',
                      'candidate_coverage'):
            self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM ' + table).fetchone(), (0,))
        self.assertIsNone(self.life.unconsumed(program_scope('pump'), through=row.slot))
        counts = managed.pump_snapshot(self.config)['history']
        self.assertEqual(counts['canonical_event_refs'], 1)
        self.assertEqual(counts['funding'], 0)
        self.assertEqual(counts['decisions'], 0)

    def test_crash_before_ack_reuses_the_same_event_and_authentic_availability(self):
        row = self.trade()
        self.history.ingest([row])
        first = capture(self.life)
        deliver(first)
        before = self.pending(row.identity)
        with closing(CandidateHistory(self.config.history)) as shared:
            original = shared.events('pump', row.payload['event']['mint'])
        # Exact native redelivery does not refresh availability or create an
        # additional economic obligation, even after the external FULL commit.
        self.history.ingest([replace(row, observed_at=row.observed_at + 10)])
        repeated = capture(self.life)
        self.assertEqual(repeated['rows'], first['rows'])
        self.assertTrue(acknowledge(self.life, repeated, deliver(repeated)))
        self.assertEqual(len(self.pending(row.identity)), 1)
        with closing(CandidateHistory(self.config.history)) as shared:
            self.assertEqual(shared.events('pump', row.payload['event']['mint']), original)
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM canonical_event_refs').fetchone(), (1,))
        compact = json.loads(self.pending(row.identity)[0][2])
        self.assertEqual(compact['source_hash'], before[0][3])
        self.assertEqual(compact['available'], row.observed_at)

    def test_existing_curve_recipient_keeps_its_identity_and_receipt_fence(self):
        row = self.trade()
        mint = row.payload['event']['mint']
        scope = self.history.bind('pump', 'retained-curve', market_address=mint,
                                  aliases=(mint,))
        self.history.ingest([row])
        pending = self.pending(row.identity)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0][1], 'retained-curve')
        self.assertIsNotNone(self.life.unconsumed(scope, through=row.slot))
        snapshot = capture(self.life)
        self.assertTrue(acknowledge(self.life, snapshot, deliver(snapshot)))
        self.assertIsNone(self.life.unconsumed(scope, through=row.slot))
        self.assertEqual(self.worker.step()['durably_observed_native_events'], 1)

    def test_trade_before_later_binding_keeps_publication_and_retries_changed_ack(self):
        row = self.trade()
        mint = row.payload['event']['mint']
        self.history.ingest([row])
        original = self.pending(row.identity)
        self.assertEqual(len(original), 1)
        first = capture(self.life)
        result = deliver(first)
        # A final-state binding census cannot establish that these recipients
        # existed when an earlier native trade entered the discovery cursor.
        # A binding arriving during external delivery must also retain the
        # existing exact-snapshot ACK fence and its original pending obligation.
        self.history.bind('pump', mint, market_address=mint,
                          aliases=('later-curve',))
        self.assertEqual(self.history.db.execute(
            "SELECT COUNT(*) FROM evidence_bindings WHERE family='pump' AND market_address=?",
            (mint,)).fetchone(), (2,))
        self.assertFalse(acknowledge(self.life, first, result))
        self.assertEqual(self.pending(row.identity), original)
        retry = capture(self.life)
        self.assertEqual(retry['rows'], first['rows'])
        self.assertTrue(acknowledge(self.life, retry, deliver(retry)))
        self.assertEqual(len(self.pending(row.identity)), 1)
        self.assertIsNotNone(self.pending(row.identity)[0][4])
        with closing(CandidateHistory(self.config.history)) as shared:
            self.assertEqual(shared.db.execute(
                'SELECT COUNT(*) FROM canonical_event_refs').fetchone(), (1,))
        observed = self.worker.step()
        self.assertEqual(observed['durably_observed_native_events'], 1)
        self.assertEqual(observed['native_event_backlog'], 0)
        self.assertEqual(observed['stages'], {'creation_unavailable': 1})
        self.assertFalse(observed['full_qualification_proven'])
        counts = managed.pump_snapshot(self.config)['history']
        self.assertEqual(counts['funding'], 0)
        self.assertEqual(counts['decisions'], 0)

    def test_unbound_pumpswap_keeps_its_existing_scoped_publication_contract(self):
        rows = [row for tx in FIXTURE['pumpswap'] for row in economic_records(
            'pumpswap', PROGRAMS['pumpswap'], deepcopy(tx),
            endpoint_identity=self.history.endpoint_identity,
            seen=self.history.clock(), source='alchemy_finalized_stream')]
        self.assertTrue(rows)
        self.history.ingest(rows)
        self.assertEqual(self.history.db.execute(
            "SELECT COUNT(*) FROM candidate_history_outbox WHERE kind='canonical'").fetchone(), (0,))
        self.assertEqual(self.worker.step()['durably_observed_native_events'], 0)

    def test_same_captured_native_stream_has_identical_reader_outputs_and_resume(self):
        from meme_machine.operational.managed_qualification_replay import compare_readers
        row = self.trade()
        self.history.ingest([row])
        snapshot = capture(self.life)
        self.assertTrue(acknowledge(self.life, snapshot, deliver(snapshot)))
        before = self.pending(row.identity)
        with patch('meme_machine.operational.managed_pump_qualification.MarketSnapshotProvider',
                   side_effect=AssertionError('comparison_must_not_construct_network_provider')):
            result = compare_readers(self.config, until=time.monotonic()+20,
                                     as_of=row.observed_at + 1)
            repeated = compare_readers(self.config, until=time.monotonic()+20,
                                       as_of=result['as_of'])
        self.assertTrue(result['coherent'])
        self.assertTrue(result['reader_restart_verified'])
        self.assertEqual(result['input_rows'], 1)
        self.assertEqual(result['output_rows'], 1)
        self.assertEqual(result['provider_requests'], 0)
        self.assertEqual(result['reference']['output_sha256'], repeated['optimized']['output_sha256'])
        self.assertEqual(self.pending(row.identity), before)
        # Missing creation is honestly equal unavailable evidence; equality
        # does not establish complete qualification or actionable decisions.
        self.assertFalse(result['verified'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['optimized']['snapshot']['stages'], {'creation_unavailable': 1})
        print('QUALIFICATION_READER_REPLAY ' + json.dumps(result, sort_keys=True), flush=True)

    def test_comparison_keeps_unpublished_cursor_barrier_and_denies_live_sizing(self):
        from meme_machine.operational.managed_qualification_replay import compare_readers
        row = self.trade()
        self.history.ingest([row])
        result = compare_readers(self.config, until=time.monotonic()+20,
                                 as_of=row.observed_at + 1)
        self.assertTrue(result['coherent'])
        self.assertEqual(result['input_rows'], 0)
        self.assertEqual(result['output_rows'], 0)
        self.assertFalse(result['complete'])
        self.assertEqual(result['reference']['snapshot']['native_event_backlog'], 1)
        with self.assertRaisesRegex(ValueError, 'retained_integer_target_required'):
            compare_readers(self.config, until=time.monotonic()+20,
                            as_of=row.observed_at + 1, decision_target=lambda now: 1)


if __name__ == '__main__':
    unittest.main()
