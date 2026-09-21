import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import tests.prospective_stream_qualification as q


class ProspectiveStreamQualificationControlsTests(unittest.TestCase):
    def test_adaptive_budget_covers_long_observation_without_unbounded_growth(self):
        self.assertEqual(q.evidence_candidate_budget(105), 20)
        self.assertGreaterEqual(q.evidence_candidate_budget(3300), 60)
        self.assertLessEqual(q.evidence_candidate_budget(3300), q.MAX_EVIDENCE_CANDIDATE_LIMIT)
        self.assertEqual(q.evidence_candidate_budget(3300, "7"), 7)
        self.assertEqual(q.evidence_candidate_budget(3300, "999"), q.MAX_EVIDENCE_CANDIDATE_LIMIT)

    def test_dlmm_certification_branch_cannot_spawn_default_live_diagnostic(self):
        text=(Path(__file__).parents[1]/".github/workflows/ci.yml").read_text()
        self.assertIn("!startsWith(github.ref_name, 'cert/dlmm-machinery-proof')", text)
        self.assertNotIn("MM_STREAM_MAX_EVIDENCE_CANDIDATES: '20'", text)

    def test_shadow_reporting_never_grants_order_authority(self):
        text=(Path(__file__).parents[0]/"prospective_stream_qualification.py").read_text()
        self.assertIn("research_policy_passes", text)
        self.assertIn("authorized_qualifications", text)
        self.assertIn("order_authority=False", text)
        self.assertIn("research_authority_only=True", text)


if __name__ == "__main__":
    unittest.main()
