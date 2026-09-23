import inspect
import unittest
from pathlib import Path

from tests import prospective_stream_qualification as observer


class ObservationCoverageContract(unittest.TestCase):
    def test_long_observer_is_bounded_but_not_cut_short_by_candidate_count(self):
        self.assertEqual(observer.MIN_OBSERVE_SECONDS,30)
        self.assertEqual(observer.DEFAULT_OBSERVE_SECONDS,105)
        self.assertEqual(observer.MAX_OBSERVE_SECONDS,3300)
        self.assertEqual(observer.MAX_EVIDENCE_CANDIDATE_LIMIT,80)
        self.assertEqual(observer.evidence_candidate_budget(3300),69)
        source=inspect.getsource(observer.main)
        self.assertIn('while time.monotonic()<deadline:',source)
        self.assertNotIn('while time.monotonic()<deadline and len(attempted)',source)
        self.assertIn("'evidence_candidate_budget_exhausted'",source)
        self.assertIn('qualification_observation_seconds=max',source)
        self.assertIn('stream_observation_seconds=max',source)
        self.assertIn("report.setdefault('qualification_observation_ended_at',now)",source)

    def test_workflow_requests_55_minutes_of_post_warmup_observation(self):
        workflow=Path('.github/workflows/ci.yml').read_text()
        self.assertIn("MM_STREAM_OBSERVE_SECONDS: '3300'",workflow)
        self.assertNotIn("MM_STREAM_MAX_EVIDENCE_CANDIDATES: '20'",workflow)
        self.assertIn("contains(github.event.head_commit.message, '[legacy-shadow-connectivity]')",workflow)
        self.assertIn('timeout-minutes: 60',workflow)


if __name__=='__main__':
    unittest.main()
