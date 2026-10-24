"""Offline raw-observation projection: separate populations and immutable clocks."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('pons_simulator_publish_test',
    Path(__file__).resolve().parents[1] / 'scripts/pons_simulator_publish.py')
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)
NOW = 1792803600


class AuxiliaryObservationTests(unittest.TestCase):
    def test_retired_financial_mirror_cannot_publish_as_current_authority(self):
        with patch.object(publisher.simulator, 'export_state', return_value={'authority_retired': True}), \
                patch.object(publisher, 'observation') as capture:
            with self.assertRaises(ValueError):
                publisher.build(1, 'c' * 40)
            capture.assert_not_called()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.folder.chmod(0o700)
        self.path = self.folder / 'operational-observation.json'
        self.enterContext(patch.object(publisher, 'PUBLICATION', self.folder))
        self.enterContext(patch.object(publisher.time, 'time', return_value=NOW))

    def record(self, **changes):
        value = dict(schema='pons-simulator-auxiliary-observation-v1', captured_at=publisher.utc(NOW - 10),
            source_sha256='a' * 64, provider_requests=119, raw_curve_topic_events=41,
            provider_connected=True, execution_state='STOPPED', lineage_verified=False,
            native_evaluations=None, model_decision='WAIT', boundary='PROVIDER_CLOCK_IDENTITY_UNAVAILABLE')
        value.update(changes)
        self.path.write_text(json.dumps(value))
        self.path.chmod(0o600)
        return value

    def build(self):
        at = publisher.utc(NOW - 20)
        book = dict(epoch_id='paper-pons-simulator-1000-20261024', inception_sha256='b' * 64,
            obligations=dict(positions_open=0), portfolio=dict(as_of=at,
                balances=dict(available_cash='1000.00', reserved_cash='0', deployed_capital='0',
                    realized_pnl='0', unrealized_pnl='0', equity='1000.00', fees='0'),
                shared_capital=dict(inception_equity='1000.00'), positions=[],
                retired_regime_totals={}, history=[], history_complete=False))
        capture = dict(provider_requests=1, failure=dict(code='native_provider_response_unavailable'),
            completed_ranges=[dict(completion_epoch_seconds=NOW - 20, native_consume_seconds=2)],
            processing=dict(samples=[dict(wall_epoch_seconds=NOW - 20, sampled_backlog_chain_units=3)]),
            native_projection=dict(pending_native_candidates=7, durable_economic_events=5,
                scout=dict(events=dict(curve=8, launch=1))), rpc_latency=[])
        events = [dict(at=publisher.utc(NOW - 40), event_id=str(n) * 64,
            kind='REJECTED', lifecycle_id=None, reason_code='PROTECTION_UNAVAILABLE') for n in range(1, 4)]
        with patch.object(publisher.simulator, 'export_state', return_value=book), \
                patch.object(publisher, 'observation', return_value=(capture, at, 'FAILED')), \
                patch.object(publisher, 'manager_journal', return_value=(events, events[-1]['at'])):
            return publisher.build(1, 'c' * 40)

    def test_newer_raw_record_replaces_old_native_population_without_claiming_qualification(self):
        record = self.record()
        value = self.build()
        self.assertEqual(value['execution_state'], 'STOPPED')
        operations, activity, strategy = (value['metrics'][group] for group in ('operational', 'activity', 'strategy'))
        self.assertEqual(operations['provider_requests']['value'], '119')
        self.assertEqual(operations['connected']['value'], '1')
        self.assertEqual(activity['events_seen']['value'], '41')
        self.assertEqual(activity['events_seen']['as_of'], record['captured_at'])
        self.assertNotEqual(activity['events_seen']['as_of'], value['captured_at'])
        for key in ('events_processed', 'queue_depth', 'sampled_block_debt', 'launch_events'):
            self.assertNotIn(key, activity)
        for key in ('range_processing_ms', 'processing_latency_ms', 'provider_failures'):
            self.assertNotIn(key, operations)
        self.assertNotIn('evaluated', strategy)
        self.assertEqual(strategy['manager_decisions']['value'], '3')
        self.assertEqual(strategy['manager_rejections']['value'], '3')
        self.assertEqual(len(value['history']['events']['rows']), 3)
        self.assertIn('AUTHENTICATED_RAW_OBSERVATION_ONLY', value['reason_codes'])
        self.assertIn('WAIT_FOR_VERIFIED_PROTECTION', value['reason_codes'])
        self.assertNotIn('PROVIDER_UNAVAILABLE', value['reason_codes'])
        self.assertEqual(value['metrics']['financial']['cash']['value'], '1000.00')

    def test_older_raw_record_never_overwrites_newer_native_sample(self):
        self.record(captured_at=publisher.utc(NOW - 30))
        value = self.build()
        self.assertEqual(value['execution_state'], 'FAILED')
        self.assertEqual(value['metrics']['activity']['events_processed']['value'], '5')
        self.assertEqual(value['metrics']['operational']['provider_requests']['value'], '1')
        self.assertNotIn('AUTHENTICATED_RAW_OBSERVATION_ONLY', value['reason_codes'])

    def test_unknown_authority_claims_bounds_future_clock_and_public_mode_refuse(self):
        for changes in (dict(lineage_verified=True), dict(native_evaluations=3),
                dict(raw_curve_topic_events=True), dict(provider_requests=0), dict(provider_requests=151),
                dict(model_decision='ENTER'), dict(execution_state='RUNNING'),
                dict(captured_at=publisher.utc(NOW + 1)), dict(private_url='SECRET')):
            with self.subTest(fields=tuple(changes)):
                self.record(**changes)
                with self.assertRaises(ValueError):
                    publisher.auxiliary_observation()
        self.record()
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            publisher.auxiliary_observation()


if __name__ == '__main__':
    unittest.main()
