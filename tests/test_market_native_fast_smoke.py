import tempfile
import unittest
from pathlib import Path

from meme_machine.store import Store
from tests.market_native_fast_smoke import (
    GENESIS_SOL_USD_MICROS,
    GENESIS_SOURCE,
    _classify_stage,
    _outcome_exit_code,
    _target_order_stage,
    _verify_replayable_store,
)


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

    def test_provider_failure_during_preflight_is_terminal(self):
        stage, oid = _classify_stage(
            {"orders": {}},
            {"full_evidence_attempted": 0, "provider_failures": 1,
             "full_reason_distribution": {}, "qualified": 0},
            0, 0,
        )
        self.assertEqual(stage, "provider_or_evidence_failure_during_preflight")
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
        self.assertEqual(_outcome_exit_code(stage), 0)

    def test_target_specific_reservation_cancel_does_not_inherit_another_timer(self):
        state = {"orders": {
            "old": {"status": "cancelled"},
            "new": {"status": "reserved"},
        }}
        self.assertEqual(_target_order_stage(state, "old"), "reservation_cancelled")
        self.assertEqual(_target_order_stage(state, "new"), "reserved_order")
        stage, oid = _classify_stage(
            state,
            {"full_evidence_attempted": 2, "provider_failures": 0,
             "full_reason_distribution": {"qualified": 2}, "qualified": 2},
            2, 0, target_id="new",
        )
        self.assertEqual((stage, oid), ("reserved_order", "new"))

    def test_fill_and_cancel_are_distinguished_for_same_target(self):
        state = {"orders": {"o1": {"status": "settled", "fill": {"tokens": 1}}}}
        self.assertEqual(_target_order_stage(state, "o1"), "filled_entry")
        state["orders"]["o1"] = {"status": "cancelled", "reason": "entry_slippage"}
        self.assertEqual(_target_order_stage(state, "o1"), "reservation_cancelled")

    def test_inconclusive_and_stream_failures_are_non_green(self):
        self.assertEqual(_outcome_exit_code("no_full_evidence_candidate_in_smoke_window"), 2)
        self.assertEqual(_outcome_exit_code("hard_deadline_exhausted"), 2)
        self.assertEqual(_outcome_exit_code("stream_start_failure"), 1)
        self.assertEqual(_outcome_exit_code("stream_continuity_lost"), 1)

    def test_saved_store_reopens_reconciles_and_verifies_archive(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "smoke.db"
            store = Store(str(path), "prospective", GENESIS_SOL_USD_MICROS, GENESIS_SOURCE)
            store.close()
            self.assertTrue(_verify_replayable_store(path))


if __name__ == "__main__":
    unittest.main()
