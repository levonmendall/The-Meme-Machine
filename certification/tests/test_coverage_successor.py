import copy
import json
from pathlib import Path
import unittest
from certification import coverage_successor as gate
from certification.prospective_program import initial_state,protocol

class SuccessorPreservationTests(unittest.TestCase):
    def state(self):
        record=json.loads((Path(__file__).parents[1]/'evidence/coverage-predecessor-record.json').read_text())
        return dict(phase='HALTED',integration_sha=gate.PREDECESSOR_SHA,cohort_id=gate.PREDECESSOR_COHORT,
            protocol_sha256=gate.PREDECESSOR_PROTOCOL,current_workflow_run_id=gate.PREDECESSOR_RUN,records=[record])

    def test_exact_censored_flat_record_is_preserved_and_never_imported(self):
        result=gate.verify_state(self.state())
        self.assertTrue(result['preserved_censored']);self.assertTrue(result['verified_flat'])
        self.assertEqual(result['records_imported_into_successor'],0)
        proto,ph=protocol();state=initial_state('repair-sha',123,proto,ph,100)
        self.assertEqual(state['records'],[])
        if proto['cohort_id']==gate.SUCCESSOR_COHORT:
            lineage=state['historical_references']['coverage_repair']
            self.assertEqual(lineage['repair_sha'],'repair-sha')
            self.assertEqual(lineage['certification_run_id'],123)

    def test_running_predecessor_or_rewritten_result_cannot_launch(self):
        for mutate in (lambda s:s.update(phase='RUNNING'),
                       lambda s:s['records'][0].update(block_admission_passed=True),
                       lambda s:s['records'][0]['lanes']['pump'].update(natural_settled=0)):
            state=self.state();mutate(state)
            with self.assertRaisesRegex(ValueError,'coverage_predecessor'):gate.verify_state(state)

    def test_only_cohort_source_diff_bindings_can_change_acceptance_identity(self):
        proto,_=protocol();new=copy.deepcopy(proto)
        new['cohort_id']='new';new['frozen_parent_integration_sha']='new'
        for row in new['frozen_lanes'].values():row['source_diff_sha256']='new'
        self.assertEqual(gate.acceptance_terms(proto),gate.acceptance_terms(new))
        new['evidence_quality']['maximum_infrastructure_censoring_fraction']=.2
        self.assertNotEqual(gate.acceptance_terms(proto),gate.acceptance_terms(new))

if __name__=='__main__':unittest.main()
