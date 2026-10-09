"""Worker pressure retains native Current requalification after restart."""
from pathlib import Path
import tempfile
import unittest
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
from meme_machine.runtime.robinhood.pons import Broker
from tests.lanes.pons.test_pons_candidate_plane import event


class CurrentWorkerAdmissionTests(unittest.TestCase):
    def test_actual_cohort_worker_pressure_keeps_independent_qualification_and_native_watch(self):
        from tests.lanes.pons import test_pons_continuous_campaign as native
        fixture=native.ContinuousCampaignTests()
        fixture._campaign_probe(worker_pressure=True)

    def broker(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.now=100.;path=Path(tmp.name)/'plane'
        b=Broker(path,POLICY_HASH,clock=lambda:self.now);return path,b

    def test_worker_deferral_survives_restart_without_terminal_lifecycle_or_old_vector_authority(self):
        path,b=self.broker();ev=event();b.enqueue(ev)
        work=b.pop();self.assertTrue(b.finish(work,dict(vector=dict(current_threshold_pass=True)),.01))
        self.assertTrue(b.plane.decision(work['key'],work['work']['generation'],'qualified'))
        before=b.plane.get(work['key'])
        self.assertTrue(b.defer_execution_worker(work['key'],work['work']['generation'],worker_limit=8))
        after=b.plane.get(work['key'])
        self.assertEqual(after['state'],'worker_deferred')
        self.assertEqual((after['observed'],after['deadline'],after['generation']),
            (before['observed'],before['deadline'],before['generation']))
        b.acknowledge(work);b.close();self.now=106
        b=Broker(path,POLICY_HASH,clock=lambda:self.now);self.addCleanup(b.close)
        self.assertEqual(b.reactivate_one(),work['key'])
        next_work=b.pop()
        self.assertTrue(next_work['canonical_refresh'])
        self.assertGreater(next_work['work']['generation'],work['work']['generation'])
        self.assertEqual(next_work['queued_at'],106)
        self.assertEqual(next_work['deadline'],111)
        self.assertIsNone(b.plane.get(work['key'])['result'])
        self.assertFalse(b.plane.decision(work['key'],work['work']['generation'],'entry_confirmation'))

    def test_new_market_generation_cannot_be_overwritten_by_old_worker_deferral(self):
        _,b=self.broker();self.addCleanup(b.close)
        b.enqueue(event());old=b.pop();self.assertTrue(b.finish(old,{},.01))
        b.enqueue(event(2));before=b.plane.get(old['key'])
        self.assertFalse(b.defer_execution_worker(old['key'],old['work']['generation'],worker_limit=8))
        self.assertEqual(b.plane.get(old['key']),before)
