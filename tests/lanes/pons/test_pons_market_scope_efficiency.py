import unittest
from types import SimpleNamespace
from unittest.mock import patch
from meme_machine.lanes.pons.pons_selective_acquisition import strategy_trajectory_preflight
from meme_machine.lanes.pons.pons_selective_continuation import ENTRY_THRESHOLDS

class PonsMarketScopeEfficiencyTests(unittest.TestCase):
    def candidate(self, asof=500):
        return {"stamp": SimpleNamespace(event_at=asof)}

    def test_token_age_and_trajectory_rules_screen_before_window(self):
        trajectory=dict(complete=True,progress_15s_bps=ENTRY_THRESHOLDS["min_progress_15s_bps"],
            accelerating=True,graduation_eta_seconds=ENTRY_THRESHOLDS["min_graduation_eta_seconds"])
        with patch("meme_machine.lanes.pons.pons_selective_acquisition.trajectory_metrics",return_value=trajectory):
            row=strategy_trajectory_preflight(self.candidate(),[],499)
        self.assertFalse(row["eligible"])
        self.assertIn("token_age",row["reasons"])

    def test_valid_existing_trajectory_rules_admit_receipt_window(self):
        trajectory=dict(complete=True,progress_15s_bps=ENTRY_THRESHOLDS["min_progress_15s_bps"],
            accelerating=True,graduation_eta_seconds=ENTRY_THRESHOLDS["min_graduation_eta_seconds"])
        launch=500-ENTRY_THRESHOLDS["min_token_age_seconds"]
        with patch("meme_machine.lanes.pons.pons_selective_acquisition.trajectory_metrics",return_value=trajectory):
            row=strategy_trajectory_preflight(self.candidate(),[],launch)
        self.assertTrue(row["eligible"],row)

    def test_existing_eta_and_acceleration_vetoes_are_preserved(self):
        trajectory=dict(complete=True,progress_15s_bps=ENTRY_THRESHOLDS["min_progress_15s_bps"],
            accelerating=False,graduation_eta_seconds=ENTRY_THRESHOLDS["max_graduation_eta_seconds"]+1)
        with patch("meme_machine.lanes.pons.pons_selective_acquisition.trajectory_metrics",return_value=trajectory):
            row=strategy_trajectory_preflight(self.candidate(),[],300)
        self.assertIn("curve_deceleration",row["reasons"])
        self.assertIn("graduation_eta",row["reasons"])

if __name__ == "__main__":
    unittest.main()
