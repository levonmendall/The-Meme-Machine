import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[2]
PREP = ROOT / "certification" / "strategy-prep"
MANIFEST = PREP / "exit-optimization-v1.json"
PATCH = PREP / "exit-optimization-v1.patch"


class ExitOptimizationPrepTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(MANIFEST.read_text())
        self.patch = PATCH.read_text()

    def test_stage_e_isolation_is_fail_closed(self):
        guard = self.policy["stage_e_isolation"]
        self.assertFalse(guard["stage_e_candidate_modified"])
        self.assertFalse(guard["stage_e_branch_modified"])
        self.assertFalse(guard["workflow_dispatch_authorized"])
        self.assertFalse(guard["market_run_authorized"])
        self.assertFalse(guard["activation_allowed"])
        self.assertTrue(guard["requires_explicit_post_stage_e_promotion"])
        self.assertTrue(guard["requires_exact_sha_non_market_recertification_after_composition"])

    def test_pump_current_only_widens_runner_giveback(self):
        p = self.policy["changes"]["pump_current"]
        self.assertEqual(p["hard_stop_bps"], -800)
        self.assertEqual(p["first_profit_bps"], 1500)
        self.assertEqual(p["first_profit_sell_bps"], 2500)
        self.assertEqual(p["runner_giveback_bps_before"], 1200)
        self.assertEqual(p["runner_giveback_bps_after"], 1400)
        self.assertFalse(p["other_exit_logic_changed"])
        self.assertIn("-    trailing_drawdown_bps: int = 1200", self.patch)
        self.assertIn("+    trailing_drawdown_bps: int = 1400", self.patch)

    def test_pons_current_profit_protection_changes_are_exact(self):
        p = self.policy["changes"]["pons_current"]
        self.assertEqual(p["hard_stop_bps"], -800)
        self.assertEqual(p["first_profit_bps"], 1800)
        self.assertEqual(p["first_profit_sell_bps_before"], 3333)
        self.assertEqual(p["first_profit_sell_bps_after"], 2500)
        self.assertEqual(p["runner_trailing_drawdown_bps_before"], 1000)
        self.assertEqual(p["runner_trailing_drawdown_bps_after"], 1200)
        self.assertEqual(p["immediate_adverse_sell_buy_ratio_bps_after"], 12000)
        self.assertIn("+    min_adverse_sell_buy_ratio_bps=12_000,", self.patch)
        self.assertIn("buy_quote=10,sell_quote=11", self.patch)
        self.assertIn('self.assertEqual(mild_reversal["action"],"hold")', self.patch)
        self.assertIn("buy_quote=10,sell_quote=12", self.patch)

    def test_meteora_exit_hysteresis_sits_outside_entry_envelope(self):
        m = self.policy["changes"]["meteora"]
        self.assertEqual(m["entry_min_two_way_balance"], 0.20)
        self.assertEqual(m["entry_max_drift_ratio"], 0.80)
        self.assertEqual(m["exit_one_way_two_way_balance_after"], 0.18)
        self.assertEqual(m["exit_one_way_drift_ratio_after"], 0.82)
        self.assertLess(m["exit_one_way_two_way_balance_after"], m["entry_min_two_way_balance"])
        self.assertGreater(m["exit_one_way_drift_ratio_after"], m["entry_max_drift_ratio"])
        self.assertEqual(m["economic_collapse_confirmation_segments_after"], 3)
        self.assertIn('recent["two_way_balance"]<0.18', self.patch)
        self.assertIn('recent["drift_ratio"]>0.82', self.patch)

    def test_meteora_static_hash_forces_regeneration_before_promotion(self):
        self.assertIn(
            '"policy_hash": "REGENERATE_AFTER_FINAL_COMPOSITION"',
            self.patch,
        )
        self.assertIn(
            "Regenerate every affected Pump, Pons, and Meteora policy hash",
            "\n".join(self.policy["promotion_requirements"]),
        )

    def test_no_survivor_ramses_sizing_or_workflow_delta(self):
        forbidden_paths = (
            "pumpswap_survivor.py",
            "pumpswap_survivor_runtime.py",
            "pons_postgrad_survivor.py",
            "pons_survivor_runtime.py",
            "ramses_strategy.py",
            ".github/workflows/",
        )
        for path in forbidden_paths:
            self.assertNotIn("diff --git a/" + path, self.patch)
        self.assertNotIn("target_sleeve_bps", self.patch)
        self.assertNotIn("target_capital_bps", self.patch)
        self.assertNotIn("capital_size_bps", self.patch)

    def test_expected_source_scope_only(self):
        headers = [
            line for line in self.patch.splitlines()
            if line.startswith("diff --git a/")
        ]
        self.assertEqual(
            headers,
            [
                "diff --git a/meme_machine/pump_acceleration_strategy.py b/meme_machine/pump_acceleration_strategy.py",
                "diff --git a/robinhood_research/pons_selective_continuation.py b/robinhood_research/pons_selective_continuation.py",
                "diff --git a/robinhood_tests/test_pons_selective_continuation.py b/robinhood_tests/test_pons_selective_continuation.py",
                "diff --git a/SOLANA_DLMM_INDEPENDENT_V1.json b/SOLANA_DLMM_INDEPENDENT_V1.json",
                "diff --git a/tests/solana_dlmm_independent_v1.py b/tests/solana_dlmm_independent_v1.py",
                "diff --git a/tests/test_solana_dlmm_independent_v1.py b/tests/test_solana_dlmm_independent_v1.py",
            ],
        )


if __name__ == "__main__":
    unittest.main()
