from copy import deepcopy
import unittest
from unittest.mock import patch

from certification.controls import smoke_engineering,sustained_readiness
from certification.smoke_continuation import register,complete,readiness
from certification.tests import test_controls as control_tests

class SmokeContinuationTests(unittest.TestCase):
    def sample(self):
        value=control_tests.ControlsTests().smoke()
        value.update(integration_sha='sha',implementation_hash='implementation',source_manifest_hash='manifest',run_id='native')
        value['lanes']['ramses'].update(open_positions=1,durable_handoff=True,terminal_reconciliation=dict(verified=True))
        state=dict(integration_sha='sha',current_workflow_run_id=1,phase='RUNNING',history=[])
        assurance=dict(runtime_sha='sha',run_id='native',operational_validity='valid')
        return value,state,assurance

    def test_measurement_end_preserves_position_and_blocks_fresh_capital_until_terminal_proof(self):
        row,state,audit=self.sample()
        self.assertEqual(smoke_engineering(row)['status'],'PASS')
        with patch('certification.smoke_continuation.implementation_hash',return_value='implementation'):
            state=register(state,row,audit,dict(id=2,digest='digest'),1)
            self.assertEqual(state['phase'],'WAITING_SMOKE_POSITIONS')
            self.assertEqual(row['lanes']['ramses']['open_positions'],1)
            with self.assertRaisesRegex(ValueError,'not_flat'):readiness(state,1)
            proof=dict(lane='ramses',handoff_required=False,terminal_replay_verified=True,
                assurance_passed=True,runtime_identity=dict(integration_sha='sha'),accounting=dict(open_positions=0,committed=0))
            missing=deepcopy(proof);missing['assurance_passed']=False
            with self.assertRaisesRegex(ValueError,'not_verified_flat'):complete(state,missing,1,'event')
            finished=complete(state,proof,1,'event')
            self.assertEqual(finished['phase'],'READY')
            self.assertEqual(complete(finished,proof,1,'event'),finished)
            restored=readiness(finished,1)
            self.assertEqual(restored['lanes']['ramses']['open_positions'],0)
            self.assertEqual(row['lanes']['ramses']['open_positions'],1)
            self.assertEqual(finished.get('records',[]),[])

    def test_open_smoke_without_native_replay_never_passes(self):
        row,_,_=self.sample();row['lanes']['ramses']['terminal_reconciliation']['verified']=False
        self.assertEqual(smoke_engineering(row)['status'],'FAIL')

if __name__=='__main__':unittest.main()
