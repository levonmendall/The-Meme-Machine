"""Native nonfinancial read-side regressions; every input/provider is offline."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import unittest
from unittest.mock import Mock, patch

from meme_machine.operational import managed_native_pump as managed
from meme_machine.operational import managed_pump_qualification as qualification
from meme_machine.runtime.candidate_history import CandidateHistory
from tests import test_managed_native_pump as fixtures


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

    def source(self, event, *, publish=True):
        identity = 'native-event'
        canonical = dict(identity=identity, kind='event', slot=10,
            transaction_index=0, event_index=0, market_time=1000,
            payload=dict(event=event))
        with sqlite3.connect(self.config.evidence) as db:
            db.execute('INSERT INTO candidate_outbox VALUES(?,?,?,?,?)',
                (1, identity, 'program:pump', 10, 1000))
        if publish:
            self.publish(event)
        return canonical

    def publish(self, event):
        history = CandidateHistory(self.config.history)
        try:
            history.observe('pump', event['mint'], surface='pump.fun', observed_at=1000)
            history.append_event('pump', event['mint'], identity='pump-source:native-event',
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


if __name__ == '__main__':
    unittest.main()
