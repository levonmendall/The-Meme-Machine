import copy
import unittest
from certification.solana_lifecycle import pump_flat_completion,authoritative_activity
from certification.controls import smoke_engineering
from certification.report import LANES


class Run369LifecycleTests(unittest.TestCase):
    def row(self):
        from certification.tests.solana_fixture import pump_evidence
        return dict(pump_evidence(),exit_code=0,process_restarts=0,unexpected_exit=False,continuous_uptime_seconds=600,
            open_positions=0,accounting_reconciled=True,provider_requests=0,
            pump_discovery_terminal=dict(reason='flat_after_discovery',configured_seconds=600,deadline=1600,completed_at=1600),
            evidence_liveness=dict(usable_observations=500,failure=None,last=dict(usable=True)),
            gates={k:True for k in ('telemetry_complete','policy_unchanged','paper_only','responsive','state_isolated')})
    def test_only_exact_clean_discovery_completion_is_accepted(self):
        self.assertTrue(pump_flat_completion(self.row()))
        mutations=[dict(exit_code=1),dict(continuous_uptime_seconds=10),dict(open_positions=1),
                   dict(accounting_reconciled=False),dict(process_restarts=1),dict(infrastructure_failure='stale'),
                   dict(pump_discovery_terminal={}),dict(evidence_liveness=dict(usable_observations=0))]
        for mutation in mutations:
            with self.subTest(mutation=mutation):self.assertFalse(pump_flat_completion(dict(self.row(),**mutation)))
    def test_smoke_accepts_local_authoritative_activity_and_preserves_premature_failure(self):
        lanes={lane:dict(self.row(),provider_requests=1,funnel=dict(completed_scans=1,discovered=5)) for lane in LANES}
        lanes['pump']['provider_requests']=0
        result=dict(phase='smoke',status='FINISHED',continuous_overlap_seconds=599,lanes=lanes,
                    shared_provider={network:dict(queues=[]) for network in ('solana','robinhood')})
        self.assertEqual(smoke_engineering(result)['status'],'PASS')
        # Compact readiness must retain the exact same engineering proof.
        import json,tempfile
        from pathlib import Path
        from certification.controls import export_readiness
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'source';output=Path(temp)/'output'
            source.write_text(json.dumps(dict(result,run_id='fixture',source_manifest_hash='s',implementation_hash='i',integration_sha='sha')))
            export_readiness(source,output)
            receipt=json.loads(output.read_text().splitlines()[0].split('=',1)[1])
            self.assertEqual(smoke_engineering(receipt)['status'],'PASS')
        result=copy.deepcopy(result);result['lanes']['pump']['unexpected_exit']=True
        result['lanes']['pump']['continuous_uptime_seconds']=10
        failures=smoke_engineering(result)['failures']
        self.assertIn('pump:process_continuity',failures);self.assertIn('ten_minute_overlap_missing',failures)
    def test_unhealthy_zero_http_is_not_silently_accepted(self):
        row=self.row();row['evidence_liveness']['failure']='evidence_finalized_stale'
        self.assertFalse(authoritative_activity(row));self.assertFalse(pump_flat_completion(row))
