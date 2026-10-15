import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from meme_machine.lanes.pons import pons_selective_acquisition as acquisition

from meme_machine.lanes.pons.pons_selective_acquisition import strategy_prospect_preflight
from meme_machine.lanes.pons.pons_selective_continuation import ENTRY_THRESHOLDS


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

    def test_outside_domain_never_requests_trajectory_or_window_and_can_reenter(self):
        ctx=MagicMock();ctx.telemetry.return_value={}
        candidate=self.candidate(progress=1000)
        candidate.update(token='token',curve='curve',block=1,stamp=SimpleNamespace(event_at=100),
                         decoded_event={'decoded':{'name':'CurveBuy'}})
        event=dict(blockNumber='0x1',blockHash='hash',transactionHash='tx',logIndex='0x0')
        with patch.object(acquisition,'_authenticate_candidate',return_value=candidate),patch.object(
                acquisition,'_trajectory') as trajectory,patch.object(acquisition,'_authenticate_window') as window:
            row=acquisition.evaluate_candidate('unused',event,[],strategy_capital_quote=100,
                                               evidence_context=ctx)
            self.assertTrue(row['screened_out'])
            self.assertFalse(row['vector']['complete'])
            trajectory.assert_not_called();window.assert_not_called()
        candidate['state'].real_quote=6000
        self.assertTrue(strategy_prospect_preflight(candidate)['eligible'])


if __name__=="__main__":
    unittest.main()
