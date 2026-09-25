import unittest

from certification.guard import active_market_job


class GuardOfflineWrapperTests(unittest.TestCase):
    def test_reviewed_v9_nonmarket_wrapper_does_not_block_smoke(self):
        job={'status':'in_progress','name':'certify / offline-prerequisites'}
        self.assertFalse(active_market_job(
            'v9-handoff-continuation-nonmarket-certification',job))

    def test_current_reviewed_nonmarket_wrappers_do_not_block(self):
        job={'status':'in_progress','name':'certify / offline-prerequisites'}
        for workflow in (
            'v10-provider-pressure-nonmarket-certification',
            'Ramses v4 offline certification',
            'Ramses v4 launchable non-market certification',
            'v12-active-strategy-certification',
        ):
            with self.subTest(workflow=workflow):
                self.assertFalse(active_market_job(workflow,job))

    def test_unknown_wrapper_with_offline_named_job_still_fails_closed(self):
        job={'status':'in_progress','name':'certify / offline-prerequisites'}
        self.assertTrue(active_market_job('unknown-wrapper',job))

    def test_market_workflow_still_blocks(self):
        self.assertTrue(active_market_job(
            'four-lane-certification',
            {'status':'in_progress','name':'offline-prerequisites'}))

    def test_completed_job_never_blocks(self):
        self.assertFalse(active_market_job(
            'unknown-wrapper',{'status':'completed','name':'anything'}))


if __name__=='__main__':
    unittest.main()
