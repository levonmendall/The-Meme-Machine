import unittest
from types import SimpleNamespace

from robinhood_research.pons_selective_acquisition import strategy_prospect_preflight
from robinhood_research.pons_selective_continuation import ENTRY_THRESHOLDS


class PonsProspectAdmissionTests(unittest.TestCase):
    def candidate(self, *, progress=6000, graduated=False, snipe=0, creator_tax=100):
        threshold=10_000
        return dict(
            state=SimpleNamespace(
                real_quote=progress,
                graduated=graduated,
                creator_tax_bps=creator_tax,
            ),
            record={"graduationThreshold":threshold},
            current_snipe_bps=snipe,
        )

    def test_mid_late_curve_is_admitted(self):
        row=strategy_prospect_preflight(self.candidate(progress=6000))
        self.assertTrue(row["eligible"],row)

    def test_early_curve_is_screened_before_trajectory_window(self):
        row=strategy_prospect_preflight(self.candidate(progress=1000))
        self.assertFalse(row["eligible"])
        self.assertIn("curve_progress",row["reasons"])

    def test_static_safety_vetoes_are_strategy_prospect_filters(self):
        self.assertIn("snipe_tax_nonzero",
            strategy_prospect_preflight(self.candidate(snipe=1))["reasons"])
        self.assertIn("already_graduated",
            strategy_prospect_preflight(self.candidate(graduated=True))["reasons"])
        self.assertIn("creator_tax",
            strategy_prospect_preflight(self.candidate(
                creator_tax=ENTRY_THRESHOLDS["max_creator_tax_bps"]+1))["reasons"])


if __name__=="__main__":
    unittest.main()
