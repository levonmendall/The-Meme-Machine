"""Fixed prerequisite wiring must not bypass exact source or weaken acceptance."""
import json
from pathlib import Path
import re
import unittest
from certification import build_consistency as build
from certification.maintenance_qualification import PLAN_PATH, frozen_inputs

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/stagee-fixed-cohort.yml'


class FixedCohortWiringTests(unittest.TestCase):
    def test_matrix_is_exactly_the_existing_frozen_cohort(self):
        text = WORKFLOW.read_text()
        matrix = re.search(r'^        trial: \[([^\]]+)\]$', text, re.M)
        self.assertIsNotNone(matrix)
        self.assertEqual([x.strip() for x in matrix[1].split(',')], json.loads(PLAN_PATH.read_text())['trials'])
        self.assertTrue(frozen_inputs())
        self.assertIn('fail-fast: false', text)
        self.assertNotIn('continue-on-error', text)

    def test_trial_execution_requires_build_preflight_and_immutable_checkout(self):
        text = WORKFLOW.read_text()
        self.assertIn('  trial:\n    needs: preflight\n', text)
        self.assertEqual(text.count('ref: ${{ github.sha }}'), 3)
        self.assertEqual(text.count('test "$GITHUB_RUN_ATTEMPT" = 1'), 3)
        self.assertIn('python -m certification.build_consistency verify', text)
        self.assertIn('python -m certification.maintenance_qualification --trial "$TRIAL"', text)
        self.assertNotIn('workflow_run:', text)

    def test_every_trial_raw_artifact_is_retained_and_recomputed(self):
        text = WORKFLOW.read_text()
        self.assertIn('if: always() && needs.preflight.result', text)
        self.assertIn("for part in ['preflight',*plan['trials']]", text)
        self.assertIn('_artifact_metadata(api,run_id,name)', text)
        self.assertIn('extract_artifact(api,reference,root/part)', text)
        self.assertIn('with qualification():result=cleanup_recovery.aggregate(root,sha)', text)
        self.assertIn("os.environ['TRIAL_JOB_RESULT']=='success'", text)
        self.assertIn('contents: read', text)
        self.assertNotIn('contents: write', text)
        self.assertNotIn('actions: write', text)

    def test_ready_archive_regression_is_discovered_as_a_test_method(self):
        from tests.test_run381_archive_scheduling import ArchiveReceiptRetryTests
        names = unittest.defaultTestLoader.getTestCaseNames(ArchiveReceiptRetryTests)
        target = 'test_ready_archive_receipt_finishes_slices_before_fresh_retention_grant'
        self.assertEqual(names.count(target), 1)

    def test_reviewed_test_refresh_does_not_authorize_strategy_changes(self):
        test = 'tests/test_run381_archive_scheduling.py'
        strategy = 'meme_machine/pump_acceleration_strategy.py'
        self.assertIn(test, build.ALLOWED_RUNTIME)
        before = {test: ('100644', 'old'), strategy: ('100644', 'frozen')}
        after = dict(before); after[test] = ('100644', 'reviewed')
        self.assertEqual(build.reviewed_delta(before, after, build.ALLOWED_RUNTIME), [test])
        after[strategy] = ('100644', 'changed')
        with self.assertRaisesRegex(ValueError, 'build_unreviewed_native_delta'):
            build.reviewed_delta(before, after, build.ALLOWED_RUNTIME)


if __name__ == '__main__':
    unittest.main()
