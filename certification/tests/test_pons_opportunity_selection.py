"""Evidence guards and unchanged Candidate Plane capabilities used by selection.

Research dispositions are checkpoints here, not enabled production strategy.
"""
from pathlib import Path
import tempfile
import unittest

from certification.robinhood.opportunity_replay import validate_point_in_time
from certification.robinhood.plane import Plane


class OpportunitySelectionTests(unittest.TestCase):
    def test_future_evidence_cannot_reconstruct_decision(self):
        validate_point_in_time(dict(market_events=[dict(event_at=10)],trajectory_snapshots=[dict(at=10)]),10)
        for field,record,error in [('market_events',dict(event_at=11),'future_event'),
                                   ('trajectory_snapshots',dict(at=11),'future_snapshot')]:
            row=dict(market_events=[],trajectory_snapshots=[]);row[field]=[record]
            with self.assertRaisesRegex(ValueError,error):validate_point_in_time(row,10)

    def test_research_disposition_checkpoint_restart_and_redelivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'plane.sqlite'
            for state in ('WATCHING','DEFERRED','PROMOTED','QUALIFIED'):
                with self.subTest(state=state):
                    p=Plane(path,clock=lambda:100)
                    args=dict(ordering=(1,),watermark={},interpretation={'policy':'frozen'},observed=100,deadline=105,priority=2)
                    p.observe(state,'pons','1',{},**args)
                    value=dict(state=state,generation=1,entry_authority=False)
                    p.checkpoint('research:'+state,value);p.close()
                    p=Plane(path,clock=lambda:101)
                    try:
                        self.assertEqual(p.checkpoint_read('research:'+state),value)
                        self.assertEqual(p.observe(state,'pons','1',{},**args),'duplicate')
                        self.assertEqual(p.get(state)['generation'],1)
                        self.assertEqual(p.get(state)['deadline'],105)
                    finally:p.close()

    def test_baseline_rejection_already_allows_new_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Plane(Path(tmp)/'plane.sqlite',clock=lambda:100)
            try:
                def observe(n):
                    return p.observe('curve','pons',str(n),{'n':n},ordering=(n,),watermark={},
                        interpretation={'policy':'frozen'},observed=100,deadline=105,priority=2)
                observe(1);old=p.claim();self.assertTrue(p.finish(old,result={'qualified':False}))
                self.assertTrue(p.decision('curve',1,'strategy_rejected','readiness'))
                observe(2);self.assertFalse(p.finish(old,result={'qualified':True}))
                new=p.claim();self.assertEqual(new['generation'],2)
                self.assertTrue(p.finish(new,result={'qualified':True}))
                self.assertTrue(p.decision('curve',2,'qualified'))
            finally:p.close()
