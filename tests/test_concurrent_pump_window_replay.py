"""Public normalized cohort, actual owner/actor/qualification, no providers."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engineering.diagnostics import replay_concurrent_pump_window as concurrent
from engineering.diagnostics import replay_original_pump_window as original
from tests.test_original_pump_window_replay import CapturedParcel


class ConcurrentWindowReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_real_owner_actor_and_qualifier_overlap_preserve_all_semantics_and_restart(self):
        parcel = CapturedParcel()
        # The public cohort has no oracle/quote/concentration input. No real
        # provider may be constructed to fill that missing evidence.
        with patch('meme_machine.operational.managed_pump_qualification.MarketSnapshotProvider',
                   side_effect=AssertionError('no_provider_construction')):
            result = concurrent.benchmark(parcel, self.root/'concurrent', batch=1, rate=5, seconds=30)
        self.assertTrue(result['engineering_validation_passed'])
        self.assertTrue(result['coherent']); self.assertTrue(result['concurrency_exercised'])
        self.assertEqual(result['semantic_fields'], list(original.SEMANTIC_FIELDS))
        self.assertEqual(len(result['semantic_fields']), 22)
        self.assertEqual(result['different_semantic_fields'], [])
        self.assertEqual(result['different_stores'], [])
        self.assertTrue(parcel.checked)
        self.assertTrue(result['production_admission_and_owner_policy'])
        self.assertEqual(result['input_provenance'], 'public_fixture')
        self.assertTrue(result['publication_thread_handoff_exercised'])
        self.assertFalse(result['actor_capture_service_cpu_separately_measured'])
        self.assertFalse(result['financial_authority'])
        self.assertFalse(result['throughput_readiness_proven'])
        self.assertFalse(result['full_qualification_proven'])
        self.assertEqual(result['quote_inputs'], 'unavailable_no_synthetic_quotes')
        self.assertEqual(result['context_rows_imported_as_state'], 0)
        left, right = result['runs']
        self.assertEqual(left['store_fingerprints'], right['store_fingerprints'])
        self.assertEqual(len(left['store_fingerprints']), 6)
        for row in result['runs']:
            self.assertTrue(row['distinct_pipeline_threads'])
            self.assertTrue(row['reader_restart_verified'])
            self.assertTrue(row['owner_actor_restart_verified'])
            self.assertEqual(row['initial']['native_event_backlog'], len(parcel.warmup))
            self.assertEqual(row['final']['native_event_backlog'], 0)
            self.assertEqual(row['completed'], {'warmup':len(parcel.warmup), 'measured':len(parcel.measured)})
            self.assertEqual(row['provider_requests'], 0)
            self.assertGreater(row['owner_counters']['owner.stage.candidate_delivery_ack.calls'], 0)
            self.assertNotIn('owner.stage.candidate_delivery_capture.calls', row['owner_counters'])
            self.assertEqual(row['counters']['offered_measured_events'], len(parcel.measured))
            self.assertEqual(row['counters']['admitted_measured_events'], len(parcel.measured))
            self.assertLessEqual(row['counters']['arrival_queue_peak_batches'], concurrent.ARRIVAL_BATCHES)
        self.assertGreater(right['counters']['delivery_before_intake_finished'], 0)
        self.assertGreater(right['counters']['observed_before_intake_finished'], 0)
        self.assertGreater(right['counters']['intake_turns_without_qualification_drain'], 0)
        self.assertEqual(left['counters'].get('intake_turns_without_qualification_drain', 0), 0)

    def test_every_original_semantic_field_is_required_and_mutation_fails(self):
        arm = {key: ['retained', key] for key in original.SEMANTIC_FIELDS}
        arm['store_fingerprints'] = {key:'original' for key in concurrent.STORE_FIELDS}
        self.assertTrue(concurrent.compare_arms(arm, deepcopy(arm))['coherent'])
        for key in original.SEMANTIC_FIELDS:
            with self.subTest(field=key):
                changed = deepcopy(arm); changed[key].append('mutated')
                result = concurrent.compare_arms(arm, changed)
                self.assertFalse(result['coherent']); self.assertEqual(result['different_semantic_fields'], [key])
                del changed[key]
                self.assertFalse(concurrent.compare_arms(arm, changed)['coherent'])
        changed = deepcopy(arm); changed['store_fingerprints']['canonical_native'] = 'mutated'
        self.assertEqual(concurrent.compare_arms(arm, changed)['different_stores'], ['canonical_native'])
        changed = deepcopy(arm); changed['store_fingerprints']['unknown'] = 'unreviewed'
        self.assertFalse(concurrent.compare_arms(arm, changed)['coherent'])

    def test_cohort_order_and_authentication_are_checked_before_private_stores(self):
        parcel = CapturedParcel()
        parcel.inputs[1]['sequence'] = parcel.inputs[0]['sequence']
        with self.assertRaisesRegex(ValueError, 'concurrent_cohort_order'):
            concurrent.benchmark(parcel, self.root/'rejected', seconds=1)
        self.assertFalse((self.root/'rejected').exists())
        parcel = CapturedParcel()
        record = parcel.records[parcel.inputs[1]['identity']]
        parcel.inputs[1]['first_seen'] = record.observed_at + 1
        with self.assertRaisesRegex(ValueError, 'concurrent_normalized_identity'):
            concurrent.benchmark(parcel, self.root/'rejected-auth', seconds=1)
        self.assertFalse((self.root/'rejected-auth').exists())

    def test_arrival_batch_and_deadline_limits_reject_unbounded_options(self):
        for batch, rate, seconds in ((0, 10, 1), (65, 10, 1), (1, 0, 1),
                                     (1, float('inf'), 1), (1, 1, 0), (1, 1, 1801)):
            with self.subTest(batch=batch, rate=rate, seconds=seconds), self.assertRaises(ValueError):
                concurrent.limits(batch, rate, seconds)


if __name__ == '__main__':
    unittest.main()
