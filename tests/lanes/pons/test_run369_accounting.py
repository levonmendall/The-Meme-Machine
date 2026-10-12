import tempfile
from pathlib import Path
import unittest
from meme_machine.runtime.robinhood.pons import Broker
from meme_machine.lanes.pons.pipeline import Pipeline
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
from tests.lanes.pons.test_pons_candidate_plane import event

class CapacityAccountingTests(unittest.TestCase):
    def test_completed_decision_categories_project_without_changing_qualification(self):
        from meme_machine.lanes.pons.pons_attempts import decision_category
        from meme_machine.runtime.robinhood.accounting import classify
        cases=[
            (dict(complete=True,token_age_seconds=901,all_rejections=['token_age']),
                'EXPIRED_BY_STRATEGY_HORIZON','strategy_rejection'),
            (dict(complete=True,all_rejections=['execution_capacity'],proposed_size=dict(
                execution_capacity=dict(final_size=0,evaluated_sizes=[1],binding_reason='ordinary_execution'))),
                'EXECUTION_CAPACITY_UNAVAILABLE','execution_capacity_unavailable'),
            (dict(complete=False,all_rejections=['non_native_quote']),
                'STRUCTURAL_INELIGIBLE','structural_ineligible'),
            (dict(complete=False,all_rejections=['missing_history']),
                'INCOMPLETE_EVIDENCE','reconstruction_incomplete'),
            (dict(complete=False,all_rejections=['stale_quote']),
                'DEADLINE_MISSED','consumer_deadline'),
            (dict(complete=False,all_rejections=['provider_unavailable']),
                'PROVIDER_UNAVAILABLE','provider_failed')]
        for vector,category,classification in cases:
            with self.subTest(category=category),tempfile.TemporaryDirectory() as td:
                root=Path(td);broker=Broker(root/'plane',POLICY_HASH,clock=lambda:100.)
                pipeline=Pipeline(root/'opportunity-pipeline.sqlite','pons',POLICY_HASH)
                try:
                    broker.enqueue(event());work=broker.pop()
                    self.assertEqual(decision_category(dict(vector=vector)),category)
                    broker.plane.finish(work['work'],result=dict(vector=vector))
                    self.assertTrue(broker.plane.decision(work['key'],work['work']['generation'],category.lower(),'retained_rejection'))
                    broker.report_to(pipeline,drain=True)
                    snapshot=pipeline.snapshot()
                    self.assertEqual(snapshot['unique_classes'][classification],1)
                    self.assertEqual(snapshot['unique_classes'].get('qualified',0),0)
                    broker.report_to(pipeline,drain=True)
                    self.assertEqual(pipeline.snapshot()['raw_records'],snapshot['raw_records'])
                finally:pipeline.close();broker.close()
        with self.assertRaisesRegex(ValueError,'unclassified_candidate_plane_outcome'):
            classify('unknown_outcome_must_still_fail')

    def test_measured_service_deferral_reaches_opportunity_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            now=[100.]
            broker=Broker(Path(td)/'plane',POLICY_HASH,clock=lambda:now[0])
            pipeline=Pipeline(Path(td)/'opportunity-pipeline.sqlite','pons',POLICY_HASH)
            try:
                broker.enqueue(event());now[0]=104.8
                self.assertIsNone(broker.pop())
                # The runtime's coverage boundary must project durable plane outcomes.
                broker.report_to(pipeline)
                self.assertEqual(pipeline.snapshot()['unique_classes']['capacity_censored'],1)
            finally:pipeline.close();broker.close()

    def test_projection_restart_deduplicates_and_fences_obsolete_results(self):
        from meme_machine.runtime.robinhood.accounting import project
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/'opportunity-pipeline.sqlite'
            broker=Broker(root/'plane',POLICY_HASH,clock=lambda:100.)
            pipeline=Pipeline(path,'pons',POLICY_HASH)
            try:
                broker.enqueue(event());old=broker.pop()
                broker.enqueue(event(2));broker.failure(old,'provider_failure')
                fresh=broker.pop();broker.plane.finish(fresh['work'],result={})
                broker.report_to(pipeline,drain=True)
                snapshot=pipeline.snapshot()
                self.assertEqual(snapshot['unique_classes']['provider_failed'],0)
                self.assertEqual(snapshot['unique_classes']['canonical_completion'],1)
                self.assertEqual(snapshot['unique_classes']['superseded_generation'],1)
                pipeline.close();pipeline=Pipeline(path,'pons',POLICY_HASH)
                broker.close();broker=Broker(root/'plane',POLICY_HASH,clock=lambda:100.)
                broker.report_to(pipeline,drain=True)
                self.assertEqual(pipeline.snapshot()['raw_records'],snapshot['raw_records'])
                self.assertEqual(pipeline.snapshot()['unique_classes']['canonical_completion'],1)
                with self.assertRaisesRegex(ValueError,'bound'):project(broker.plane,pipeline,batch_size=257)
            finally:pipeline.close();broker.close()

    def test_bounded_projection_drains_backlog_without_losing_deferrals(self):
        from meme_machine.runtime.robinhood.accounting import project
        with tempfile.TemporaryDirectory() as td:
            broker=Broker(Path(td)/'plane',POLICY_HASH,clock=lambda:100.)
            pipeline=Pipeline(Path(td)/'opportunity-pipeline.sqlite','pons',POLICY_HASH)
            try:
                for n in range(1,91):broker.enqueue(event(n))
                broker.plane.claim(estimate_seconds=6)
                self.assertEqual(project(broker.plane,pipeline,batch_size=8),8)
                broker.report_to(pipeline,drain=True)
                self.assertEqual(pipeline.snapshot()['unique_classes']['capacity_censored'],1)
                self.assertEqual(pipeline.snapshot()['raw_records'],broker.plane.db.execute('SELECT COUNT(*) FROM transitions').fetchone()[0])
            finally:pipeline.close();broker.close()

    def test_projection_marker_and_history_commit_atomically(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as td:
            broker=Broker(Path(td)/'plane',POLICY_HASH,clock=lambda:100.)
            pipeline=Pipeline(Path(td)/'opportunity-pipeline.sqlite','pons',POLICY_HASH)
            try:
                broker.enqueue(event())
                pipeline.db.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON progress BEGIN SELECT RAISE(ABORT,'disk_failure'); END")
                with self.assertRaises(sqlite3.IntegrityError):broker.report_to(pipeline)
                self.assertEqual(pipeline.db.execute('SELECT COUNT(*) FROM progress_sources').fetchone()[0],0)
                pipeline.db.execute('DROP TRIGGER injected_failure')
                broker.report_to(pipeline)
                self.assertEqual(pipeline.snapshot()['raw_records'],1)
            finally:pipeline.close();broker.close()

    def test_authenticated_structural_boundary_is_not_provider_failure(self):
        import json
        from meme_machine.lanes.pons.pons_selective_acquisition import authenticated_early_rejection
        proof=json.loads((Path(__file__).resolve().parents[2]/'fixtures/robinhood/run369-pons-accounting.json').read_text())['deferrals'][1]['immutable_proof']
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'opportunity-pipeline.sqlite'
            broker=Broker(Path(td)/'plane',POLICY_HASH,clock=lambda:100.)
            pipeline=Pipeline(path,'pons',POLICY_HASH)
            try:
                e=event();e['address']=proof['curve'];broker.enqueue(e);work=broker.pop()
                screen=authenticated_early_rejection(proof['boundary'],proof)
                broker.failure(work,proof['boundary'],screen=screen)
                # Death after the plane commit must not lose the immutable proof.
                broker.close();broker=Broker(Path(td)/'plane',POLICY_HASH,clock=lambda:100.)
                broker.report_to(pipeline)
                newer=dict(event(2),address=e['address']);broker.enqueue(newer);broker.report_to(pipeline)
                self.assertEqual(pipeline.snapshot()['unique_classes']['provider_failed'],0)
                self.assertEqual(pipeline.snapshot()['unique_classes']['strategy_rejection'],0)
                self.assertEqual(pipeline.snapshot()['unique_classes']['structural_ineligible'],1)
            finally:pipeline.close();broker.close()
