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
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                adapter.directional_native_target(invalid)
        for rate in ('500', '2000'):
            ledger = dict(policy=dict(sizing_basis='effective_family_equivalence'))
            args = dict(native_units_per_usd=rate, legacy_native_realized_equity=100003)
            self.assertEqual(adapter.directional_target(ledger, 'pump_current', **args),
                             previous(ledger, 'pump_current', **args))


if __name__ == '__main__':
    unittest.main()
