"""Regression coverage for range-specific DLMM economic strategy research."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from meme_machine import dlmm
from meme_machine.dlmm_tape import reconstruct
from meme_machine.provider import Unavailable
from tests import dlmm_strategy_economics as economics
from tests.test_dlmm_tape import interval


class DlmmEconomicStrategy(unittest.TestCase):
    def _verified_interval(self):
        _snapshot, state, end, sigs, txs = interval()
        tape = reconstruct(
            state,
            end,
            sigs,
            txs,
            102,
            [100, 2**31 - 1, 2**31 - 1],
        )
        return state, tape

    def test_fixed_cost_hurdle_is_exactly_mechanical_35_bps(self):
        self.assertEqual(economics.FIXED_COST, 350_000)
        self.assertEqual(economics.FIXED_COST_BPS, 35.0)
        self.assertEqual(economics.HOLD_SECONDS, 60)

    def test_price_normalized_width_changes_with_bin_step(self):
        state, _ = self._verified_interval()
        fine = copy.deepcopy(state)
        coarse = copy.deepcopy(state)
        fine["step"] = 20
        coarse["step"] = 125
        fine_width = economics.normalized_width(fine, 200)
        coarse_width = economics.normalized_width(coarse, 200)
        self.assertGreater(fine_width, coarse_width)
        self.assertLessEqual(
            abs(economics.width_distance_bps(fine, fine_width) - 200),
            abs(economics.width_distance_bps(fine, 8) - 200),
        )
        self.assertLessEqual(
            abs(economics.width_distance_bps(coarse, coarse_width) - 200),
            abs(economics.width_distance_bps(coarse, 8) - 200),
        )

    def test_range_features_are_specific_to_proposed_range_and_cost_anchored(self):
        state, tape = self._verified_interval()
        features = economics.range_specific_features(
            state, tape, "foundation_spot", 2, placement_state=tape.terminal
        )
        self.assertEqual(features["width"], 2)
        self.assertEqual(features["placement_active_bin"], tape.terminal["active"])
        self.assertEqual(features["warmup_start_active_bin"], state["active"])
        self.assertGreater(features["range_liquidity_sol_lamports"], 0)
        self.assertIn("approach_50bps", features)
        self.assertIn("approach_100bps", features)
        self.assertIn("approach_200bps", features)
        self.assertIn("flow_into_range_volume_sol_lamports", features)
        self.assertIn("two_way_balance", features)
        self.assertIn("reversal_count", features)
        self.assertIn("touch_then_revert", features)
        self.assertEqual(features["fixed_cost_lamports"], 350_000)
        self.assertAlmostEqual(
            features["projected_60s_range_fee_surplus_lamports"],
            features["projected_60s_range_fee_capture_lamports"] - 350_000,
        )
        self.assertGreaterEqual(features["estimated_range_fee_capture_share"], 0)
        self.assertLessEqual(features["estimated_range_fee_capture_share"], 1)

    def test_development_gate_requires_cost_flow_and_reversion(self):
        base = dict(
            projected_60s_range_fee_surplus_lamports=1,
            flow_into_range_volume_sol_lamports=1,
            away_from_range_volume_sol_lamports=1,
            reversal_count=1,
            touch_then_revert=False,
            two_way_balance=0.5,
        )
        self.assertTrue(economics.development_economic_case(base)["passes"])
        for key, value in (
            ("projected_60s_range_fee_surplus_lamports", -1),
            ("flow_into_range_volume_sol_lamports", 0),
            ("away_from_range_volume_sol_lamports", 0),
        ):
            case = dict(base)
            case[key] = value
            if key == "away_from_range_volume_sol_lamports":
                case["reversal_count"] = 0
                case["touch_then_revert"] = False
                case["two_way_balance"] = 0
            self.assertFalse(
                economics.development_economic_case(case)["passes"],
                key,
            )

    def test_repository_rule_template_is_explicitly_unfrozen(self):
        body = json.loads(economics.RULE_PATH.read_text())
        self.assertEqual(body["status"], "development")
        with self.assertRaisesRegex(Unavailable, "holdout_rule_not_frozen"):
            economics.load_frozen_rule()

    def test_unfrozen_rule_cannot_be_used_for_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rule.json"
            path.write_text(json.dumps(dict(version=1, status="development")))
            with self.assertRaisesRegex(Unavailable, "holdout_rule_not_frozen"):
                economics.load_frozen_rule(path)

    def test_frozen_rule_schema_is_read_without_auto_tuning(self):
        rule = dict(
            version=1,
            status="frozen",
            frozen_at=200,
            development_cutoff_time=199,
            strategy="sdk_bidask",
            target_distance_bps=200,
            min_projected_60s_fee_surplus_lamports=0,
            require_flow_into_range=True,
            require_two_way_or_revert=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rule.json"
            path.write_text(json.dumps(rule))
            self.assertEqual(economics.load_frozen_rule(path), rule)
        protocol = economics.sample_protocol()
        self.assertFalse(protocol["automatic_rule_freeze"])
        self.assertFalse(protocol["development_profitability_claim_allowed"])
        self.assertTrue(protocol["holdout_requires_committed_frozen_rule"])


if __name__ == "__main__":
    unittest.main()
