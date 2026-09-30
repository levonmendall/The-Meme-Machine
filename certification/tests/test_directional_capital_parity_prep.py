import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[2]
PREP = ROOT / "certification" / "strategy-prep"
MANIFEST = PREP / "directional-capital-parity-v1.json"
PATCH = PREP / "directional-capital-parity-v1.patch"


class DirectionalCapitalParityPrepTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(MANIFEST.read_text())
        self.patch = PATCH.read_text()

    def test_all_directional_regimes_have_equal_five_percent_target(self):
        targets = self.policy["directional_targets"]
        self.assertEqual(
            {name: row["prepared_target_bps"] for name, row in targets.items()},
            {
                "pump_current": 500,
                "pons_current": 500,
                "pump_survivor": 500,
                "pons_survivor": 500,
            },
        )

    def test_only_previously_throttled_regimes_are_increased(self):
        targets = self.policy["directional_targets"]
        self.assertEqual(targets["pump_current"]["previous_target_bps"], 500)
        for name in ("pons_current", "pump_survivor", "pons_survivor"):
            self.assertEqual(targets[name]["previous_target_bps"], 25)
            self.assertEqual(targets[name]["prepared_target_bps"], 500)

    def test_existing_stops_bound_five_percent_target_risk(self):
        targets = self.policy["directional_targets"]
        expected = {
            "pump_current": 40,
            "pons_current": 40,
            "pump_survivor": 60,
            "pons_survivor": 50,
        }
        self.assertEqual(
            {name: row["planned_stop_risk_bps_of_sleeve"] for name, row in targets.items()},
            expected,
        )
        self.assertLessEqual(max(expected.values()), 60)

    def test_preparation_is_explicitly_non_activating_and_stage_e_isolated(self):
        guard = self.policy["stage_e_isolation"]
        self.assertFalse(guard["stage_e_candidate_modified"])
        self.assertFalse(guard["stage_e_branch_modified"])
        self.assertFalse(guard["workflow_dispatch_authorized"])
        self.assertFalse(guard["market_run_authorized"])
        self.assertFalse(guard["activation_allowed"])
        self.assertTrue(guard["requires_explicit_post_stage_e_promotion"])
        self.assertTrue(guard["requires_exact_sha_non_market_recertification_after_composition"])

    def test_patch_changes_capital_authority_or_policy_identity_only(self):
        allowed = (
            "capital_revision",
            "target_sleeve_bps",
            "target=self.capital*",
            "POLICY_REVISION",
            "capital_size_bps",
            "target_capital_bps",
            "cap=min(self.capital*",
            "fresh_quotes(state,self.capital*",
        )
        for line in self.patch.splitlines():
            if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
                continue
            self.assertTrue(
                any(token in line for token in allowed),
                f"unexpected non-capital change in prepared patch: {line}",
            )

    def test_patch_preserves_execution_and_risk_limits(self):
        changed = [
            line for line in self.patch.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        # Hard risk values are not part of the delta at all.
        for line in changed:
            self.assertNotIn("hard_stop_bps", line)
            self.assertNotIn("max_immediate_roundtrip_loss_bps", line)
            self.assertNotIn("max_double_size_roundtrip_loss_bps", line)

        # Where capital and safeguards share one source line, both sides of the
        # diff must preserve the safeguard text exactly.
        self.assertIn(
            "-    minimum_fill_breadth_bps=5000, target_sleeve_bps=25, turnover_divisor=40,",
            self.patch,
        )
        self.assertIn(
            "+    minimum_fill_breadth_bps=5000, target_sleeve_bps=500, turnover_divisor=40,",
            self.patch,
        )
        self.assertIn(
            "-            target=self.capital*25//10000,minimum=GAS*2+1,retention_bps=5000,",
            self.patch,
        )
        self.assertIn(
            "+            target=self.capital*500//10000,minimum=GAS*2+1,retention_bps=5000,",
            self.patch,
        )
        self.assertIn("ordinary_limit=600,stress_limit=600", self.patch)
        self.assertIn(
            "-            target=self.capital*25//10000,minimum=self.capital*5//10000,retention_bps=5000,",
            self.patch,
        )
        self.assertIn(
            "+            target=self.capital*500//10000,minimum=self.capital*5//10000,retention_bps=5000,",
            self.patch,
        )
        self.assertIn("ordinary_limit=450,stress_limit=650", self.patch)

    def test_patch_has_no_workflow_or_meteora_ramses_delta(self):
        self.assertNotIn(".github/workflows", self.patch)
        self.assertNotIn("meteora", self.patch.lower())
        self.assertNotIn("ramses", self.patch.lower())


if __name__ == "__main__":
    unittest.main()
