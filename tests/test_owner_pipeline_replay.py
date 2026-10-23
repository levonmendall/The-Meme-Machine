"""Real disposable pipeline plus declared planner/control fixture, no providers."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engineering.diagnostics import replay_owner_pipeline as replay
from tests.test_original_pump_window_replay import CapturedParcel


class OwnerPipelineReplayTests(unittest.TestCase):
    def test_captured_pipeline_completes_actual_planning_checkpoint_and_restart(self):
        parcel = CapturedParcel()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve()/'component'
            with patch('meme_machine.operational.managed_pump_qualification.MarketSnapshotProvider',
                       side_effect=AssertionError('provider_construction_forbidden')):
                result = replay.benchmark(parcel,output,profile='component',batch=1,rate=10,seconds=15)
        self.assertTrue(parcel.checked)
        self.assertEqual(result['input_provenance'],'public_fixture')
        self.assertEqual(result['selected_events'],len(parcel.measured))
        self.assertEqual(result['context_rows_imported_as_state'],0)
        self.assertEqual(result['provider_requests'],0)
        self.assertFalse(result['financial_authority'])
        self.assertFalse(result['pons_wire_processing_exercised'])
        self.assertFalse(result['full_strategy_equivalence_proven'])
        self.assertFalse(result['throughput_readiness_proven'])
        run,metrics = result['run'],result['metrics']
        self.assertTrue(run['reader_restart_verified'])
        self.assertTrue(run['owner_actor_restart_verified'])
        self.assertEqual(metrics['classified_native_observations'],len(parcel.inputs))
        self.assertEqual(metrics['final_native_debt'],0)
        self.assertEqual(metrics['full_approved_strategy_evaluations'],0)
        self.assertEqual(metrics['full_approved_strategy_scope'],'UNEXERCISED')
        self.assertGreater(metrics['process_cpu_seconds_per_measured_input'],0)
        self.assertGreater(metrics['owner_execution_cpu_seconds'],0)
        workload = run['owner_workload']
        self.assertIn('SYNTHETIC',workload['fixture_scope'])
        self.assertEqual(workload['initial']['nonexpired_pending_jobs'],6)
        self.assertEqual(workload['initial']['complete_jobs'],0)
        self.assertEqual(workload['initial']['deadline_missed_jobs'],0)
        self.assertFalse(workload['initial']['complete'])
        self.assertTrue(workload['final']['complete'])
        self.assertTrue(workload['final']['deadlines_preserved'])
        self.assertEqual(workload['final']['complete_jobs'],2)
        self.assertEqual(workload['final']['deadline_missed_jobs'],2)
        self.assertEqual(workload['final']['local_plans'],2)
        self.assertEqual(workload['final']['inflight'],0)
        self.assertEqual(workload['final']['preparation_tickets'],0)
        self.assertFalse(workload['final']['transaction_open'])
        self.assertEqual(workload['final']['synchronous'],2)
        self.assertGreater(workload['counters']['planning_callbacks'],0)
        self.assertGreater(workload['counters']['checkpoint_calls'],0)
        self.assertGreater(workload['counters']['urgent_probes'],0)
        self.assertEqual(workload['counters'].get('refused_archive_dispatch',0),0)
        self.assertGreater(workload['checkpoint']['physical_calls'],0)
        self.assertEqual(sum(workload['urgent_latency']['histogram']),
                         workload['counters']['urgent_probes'])

    def test_metrics_separate_classifications_strategy_and_nonduplicated_owner_cost(self):
        run = dict(timing=dict(wall_nanoseconds=2_000_000_000,
                              process_cpu_nanoseconds=500_000_000),
            final=dict(durably_observed_native_events=10,full_qualifications=0,native_event_backlog=0),
            controlled_batch_progress=[dict(admitted=4,observed=1,elapsed_seconds=.2),
                                       dict(admitted=9,observed=7,elapsed_seconds=1.5)],
            owner_workload=dict(owner_thread_cpu_seconds=.2,timed_owner_counters={
                'owner.priority0.execution_total_microseconds':100_000,
                'owner.priority4.execution_total_microseconds':300_000,
                'owner.stage.candidate_development.execution_total_microseconds':300_000,
                'owner.stage.candidate_development.execution_cpu_total_microseconds':150_000}))
        result = replay.metrics(run,9)
        self.assertEqual(result['classified_native_observations_per_second'],5)
        self.assertEqual(result['full_approved_strategy_evaluations'],0)
        self.assertAlmostEqual(result['owner_execution_wall_seconds'],.4)
        self.assertAlmostEqual(result['owner_execution_cpu_seconds'],.2)
        self.assertEqual(result['sampled_native_debt_peak'],3)
        self.assertEqual(result['sampled_native_debt_at_intake_end'],2)
        self.assertTrue(result['warmup_processing_included_in_cpu_and_observation_rate'])


if __name__=='__main__':unittest.main()
