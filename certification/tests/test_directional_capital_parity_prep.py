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
            "pump_current": 50,
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
        # These appear only as unchanged context; the patch must not remove/add them.
        changed = [
            line for line in self.patch.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        forbidden = (
            "hard_stop_bps",
            "ordinary_limit",
            "stress_limit",
            "retention_bps",
            "turnover_divisor",
            "minimum_fill_breadth_bps",
            "max_immediate_roundtrip_loss_bps",
            "max_double_size_roundtrip_loss_bps",
        )
        for line in changed:
            self.assertFalse(
                any(token in line for token in forbidden),
                f"risk/execution safeguard changed: {line}",
            )

    def test_patch_has_no_workflow_or_meteora_ramses_delta(self):
        self.assertNotIn(".github/workflows", self.patch)
        self.assertNotIn("meteora", self.patch.lower())
        self.assertNotIn("ramses", self.patch.lower())


if __name__ == "__main__":
    unittest.main()
