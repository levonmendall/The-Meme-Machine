import unittest

from tests.market_native_fast_smoke import _classify_stage


class FastSmokeClassification(unittest.TestCase):
    def test_provider_failure_after_full_attempt_is_terminal(self):
        stage, oid = _classify_stage(
            {"orders": {}},
            {"full_evidence_attempted": 1, "provider_failures": 1,
             "full_reason_distribution": {}, "qualified": 0},
            0, 0,
        )
        self.assertEqual(stage, "provider_or_evidence_failure_after_full_attempt")
        self.assertIsNone(oid)

    def test_complete_full_evidence_rejection_is_useful_terminal_boundary(self):
        stage, oid = _classify_stage(
            {"orders": {}},
            {"full_evidence_attempted": 1, "provider_failures": 0,
             "full_reason_distribution": {"concentration": 1}, "qualified": 0},
            0, 0,
        )
        self.assertEqual(stage, "full_evidence_completed_no_qualification")
        self.assertIsNone(oid)

    def test_reservation_and_fill_are_distinguished(self):
        stage, oid = _classify_stage(
            {"orders": {"o1": {"status": "reserved"}}},
            {"full_evidence_attempted": 1, "provider_failures": 0,
             "full_reason_distribution": {"qualified": 1}, "qualified": 1},
            1, 0,
        )
        self.assertEqual((stage, oid), ("reserved_order", "o1"))

        stage, oid = _classify_stage(
            {"orders": {"o1": {"status": "settled", "fill": {"tokens": 1}}}},
            {"full_evidence_attempted": 1, "provider_failures": 0,
             "full_reason_distribution": {"qualified": 1}, "qualified": 1},
            1, 0,
        )
        self.assertEqual((stage, oid), ("filled_entry", "o1"))


if __name__ == "__main__":
    unittest.main()
