import unittest

from meme_machine import dlmm
from tests import dlmm_wallet_cluster_prospective as prospective


class WalletClusterProspective(unittest.TestCase):
    def test_frozen_candidate_preserves_failed_confirmatory_gate(self):
        body=prospective.load_candidate()
        gate=body["source"]["confirmatory_repeatability_gate"]
        self.assertFalse(gate["passed"])
        self.assertEqual(body["exploratory_cluster"]["wallet_count"],14)
        self.assertEqual(body["exploratory_cluster"]["exact_hold_seconds"],491)
        self.assertEqual(body["exploratory_cluster"]["exact_width_bins"],70)
        self.assertFalse(body["allocation_authority"])

    def _effect(self,width=70,sol_side="x"):
        deposits=[]
        for bid in range(10,10+width):
            deposits.append(dict(
                bin_id=bid,
                x=100 if sol_side=="x" else 0,
                y=100 if sol_side=="y" else 0,
            ))
        return dict(
            amount_x=100*width if sol_side=="x" else 0,
            amount_y=100*width if sol_side=="y" else 0,
            bin_deposits=deposits,
        )

    def test_signal_requires_exact_70_bin_one_sided_sol_add(self):
        event={"effect":self._effect(70,"x")}
        info={"x":dlmm.WSOL,"y":"token"}
        qualified,reason=prospective._qualify_signal(event,info)
        self.assertIsNone(reason)
        self.assertEqual(qualified["width_bins"],70)
        self.assertEqual(len(qualified["source_sol_weights"]),70)

        rejected,reason=prospective._qualify_signal(
            {"effect":self._effect(69,"x")},info)
        self.assertIsNone(rejected)
        self.assertEqual(reason,"source_width_not_70")

        rejected,reason=prospective._qualify_signal(
            {"effect":self._effect(70,"y")},info)
        self.assertIsNone(rejected)
        self.assertEqual(reason,"source_not_one_sided_sol")

    def test_paper_deposit_mirrors_weights_at_fixed_capital(self):
        bins={}
        for bid in range(10,80):
            bins[str(bid)]=dict(
                x=1_000_000,y=0,price=dlmm.Q,supply=dlmm.Q,
                fee_x=0,fee_y=0,
            )
        state=dict(
            x=dlmm.WSOL,y="token",active=9,slot=100,time=1000,bins=bins,
        )
        signal={"source_sol_weights":{bid:1 for bid in range(10,80)}}
        p=prospective._paper_deposit(state,signal)
        self.assertEqual(p["lower"],10)
        self.assertEqual(p["upper"],79)
        self.assertEqual(len(p["shares"]),70)
        self.assertEqual(sum(
            p["virtual"]["bins"][str(bid)]["x"]-1_000_000
            for bid in range(10,80)
        )+p["idle_sol"],prospective.CAPITAL)


if __name__=="__main__":
    unittest.main()
