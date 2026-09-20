import json
from pathlib import Path
import unittest

from certification.shadow import scores,freeze_observation,discrimination,candidate_vectors


class ShadowTests(unittest.TestCase):
    def registry(self):return json.loads((Path(__file__).parents[1]/'shadow_registry.json').read_text())

    def test_missing_fields_are_censored_and_directional_scores_are_exact(self):
        model=[dict(id='cost',path='x.cost',direction=-1),dict(id='missing',path='y',direction=1)]
        self.assertEqual(scores(dict(x=dict(cost=123456789012345678)),model),{'cost':'-123456789012345678','missing':None})

    def test_late_incomplete_forced_screening_and_post_outcome_never_become_prospective(self):
        registry=self.registry();lane='pons';event=dict(hash='source',at_ns=1800000000000000000,
            kind='candidate_observation',body=dict(policy_hash=registry['lanes'][lane]['policy_hash'],
                observation=dict(token='token',source_transaction='tx',vector=dict(complete=True,
                    decision_state_age_seconds=5.1,thresholds=dict(max_state_age_seconds=5)))))
        candidate=next(candidate_vectors(lane,event));self.assertFalse(freeze_observation(lane,candidate,event,registry)['prospective_feature_eligible'])
        candidate.update(complete=True,grade='authenticated_complete',pre_outcome=True)
        self.assertTrue(freeze_observation(lane,candidate,event,registry)['prospective_feature_eligible'])
        for key,value in (('pre_outcome',False),('grade','finalized_screening_only'),('complete',False)):
            changed=dict(candidate);changed[key]=value
            self.assertFalse(freeze_observation(lane,changed,event,registry)['prospective_feature_eligible'])
        event['at_ns']=1;self.assertFalse(freeze_observation(lane,candidate,event,registry)['prospective_feature_eligible'])
        event['body']['policy_hash']='other'
        with self.assertRaisesRegex(ValueError,'policy_mismatch'):freeze_observation(lane,candidate,event,registry)

    def test_tiny_or_unjoined_cohorts_cannot_support_discrimination(self):
        row=dict(asset='a',scores=dict(score='2'),prospective_feature_eligible=True,outcome_status='authenticated_settled',net_native=1)
        self.assertIsNone(discrimination([row],'score')['auc'])
        rows=[dict(row,asset=str(i),net_native=1 if i%2 else -1,scores=dict(score='1')) for i in range(30)]
        measured=discrimination(rows,'score');self.assertEqual(measured['auc'],dict(numerator=1,denominator=2))
        self.assertFalse(measured['promotion_eligible'])
        rows[0]['outcome_status']='forced_settled'
        self.assertEqual(discrimination(rows,'score')['outcomes'],29)
        self.assertIsNone(discrimination(rows,'score')['auc'])


if __name__=='__main__':unittest.main()
