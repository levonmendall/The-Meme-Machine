import tempfile
import unittest
from pathlib import Path

from meme_machine.engine import Engine
from meme_machine.research import analyze_reports, qualification_vector
from meme_machine.store import Store
from tests.support import SCOUT, evidence, event


class QualificationResearch(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(str(Path(self.tmp.name)/'research.db'),'synthetic',100_000_000,'test')
        self.engine=Engine(self.store,[SCOUT])

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_vector_preserves_frozen_qualified_decision(self):
        nomination=event()
        ev=evidence()
        self.assertEqual(self.engine.qualify(nomination,ev,100),'qualified')
        vector=qualification_vector(self.engine,nomination,ev,100)
        self.assertEqual(vector['actual_reason'],'qualified')
        self.assertTrue(vector['current_threshold_pass'])
        self.assertEqual(vector['all_rejections'],[])
        self.assertGreaterEqual(vector['independent_buyer_groups'],3)
        self.assertGreaterEqual(vector['independent_net_buy_lamports'],1_000_000_000)
        self.assertGreaterEqual(vector['margins']['concentration_bps'],0)
        self.assertGreaterEqual(vector['margins']['price_extension_bps'],0)
        self.assertGreaterEqual(vector['margins']['roundtrip_loss_bps'],0)

    def test_vector_attributes_rejection_without_changing_policy(self):
        nomination=event()
        ev=evidence();ev['concentration_bps']=4000
        self.assertEqual(self.engine.qualify(nomination,ev,100),'concentration')
        vector=qualification_vector(self.engine,nomination,ev,100)
        self.assertEqual(vector['actual_reason'],'concentration')
        self.assertIn('concentration',vector['all_rejections'])
        self.assertFalse(vector['current_threshold_pass'])
        # Analysis-only: changing just this counterfactual gate would have admitted
        # this synthetic candidate, while Engine.qualify remains unchanged.
        self.assertTrue(vector['sensitivity']['values']['max_concentration_bps']['4500'])
        self.assertEqual(self.engine.qualify(nomination,ev,100),'concentration')

    def test_vector_reports_multiple_rejections_after_first_failure(self):
        nomination=event()
        ev=evidence();ev['concentration_bps']=4000;ev['events']=[]
        vector=qualification_vector(self.engine,nomination,ev,100)
        self.assertEqual(vector['actual_reason'],'concentration')
        self.assertIn('concentration',vector['all_rejections'])
        self.assertIn('independent_demand',vector['all_rejections'])

    def test_aggregate_deduplicates_only_natural_nominations_and_requires_sample(self):
        vector=qualification_vector(self.engine,event(),evidence(),100)
        natural=dict(nomination_id='same',evidence_stage='complete',natural_nomination=True,
                     qualification_vector=vector)
        non_natural=dict(nomination_id='canary',evidence_stage='complete',natural_nomination=False,
                         qualification_vector=vector)
        analysis=analyze_reports([{'results':[natural,non_natural]},{'results':[natural]}],min_sample=2)
        self.assertEqual(analysis['unique_complete_nominations'],1)
        self.assertEqual(analysis['current_qualified'],1)
        self.assertFalse(analysis['sample_sufficient'])
        self.assertEqual(analysis['decision'],'insufficient_sample_for_threshold_revision')


    def test_aggregate_keeps_same_legacy_id_for_different_mints_separate(self):
        vector=qualification_vector(self.engine,event(),evidence(),100)
        rows=[
            dict(nomination_id='legacy:45',mint='MintA',evidence_stage='complete',
                 natural_nomination=True,qualification_vector=vector),
            dict(nomination_id='legacy:45',mint='MintB',evidence_stage='complete',
                 natural_nomination=True,qualification_vector=vector),
        ]
        analysis=analyze_reports([{'results':rows}],min_sample=2)
        self.assertEqual(analysis['unique_complete_nominations'],2)
        self.assertTrue(analysis['sample_sufficient'])



if __name__=='__main__':
    unittest.main()
