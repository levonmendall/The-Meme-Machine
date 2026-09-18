import unittest
from unittest.mock import patch

from meme_machine import dlmm
from meme_machine.dlmm_economics import range_economic_case
from meme_machine.dlmm_tape import VerifiedTape
from meme_machine.provider import Unavailable


class DlmmRangeEconomicCaseTests(unittest.TestCase):
    def _state(self):
        bins = {}
        for bid in range(2, 11):
            bins[str(bid)] = dict(x=0, y=1_000_000_000, supply=1)
        return dict(
            x="TOKEN",
            y=dlmm.WSOL,
            active=10,
            step=25,
            bins=bins,
        )

    def test_range_metrics_and_60s_hurdle_are_point_in_time(self):
        state = self._state()
        event = dict(
            amount=1_000_000_000,
            for_y=False,
            time=100,
            observed={},
        )
        tape = VerifiedTape("a", "b", (event,), dict(), "lineage")
        quote = dict(
            start=9,
            traversed=(
                dict(bin=9, input=1_000_000_000, fee=100_000_000, protocol_fee=0),
                dict(bin=10, input=500_000_000, fee=50_000_000, protocol_fee=0),
            ),
        )
        with patch("meme_machine.dlmm_economics.dlmm.swap", return_value=(state, quote)):
            result = range_economic_case(
                state,
                state,
                tape,
                "sdk_bidask",
                8,
                12,
                capital_lamports=2_000_000_000,
                fixed_cost_lamports=0,
                hurdle_bps=35,
            )

        self.assertEqual(result["lower_bin"], 2)
        self.assertEqual(result["upper_bin"], 9)
        self.assertEqual(result["range_crossing_volume_sol_lamports"], 1_000_000_000)
        self.assertEqual(result["near_range_volume_sol_lamports"], 1_500_000_000)
        self.assertEqual(result["range_lp_fee_sol_lamports"], 100_000_000)
        self.assertEqual(result["near_range_lp_fee_sol_lamports"], 150_000_000)
        self.assertEqual(result["range_hit_swaps"], 1)
        self.assertEqual(result["near_range_hit_swaps"], 1)
        self.assertTrue(result["passes_pre_entry_hurdle"])
        self.assertFalse(result["allocation_authority"])
        self.assertFalse(result["outcome_data_used"])

    def test_host_fee_stays_out_of_lp_fee_proxy(self):
        state = self._state()
        event = dict(amount=100, for_y=False, time=100, observed={"host_fee": 10})
        tape = VerifiedTape("a", "b", (event,), dict(), "lineage")
        quote = dict(
            start=9,
            traversed=(
                dict(
                    bin=9,
                    input=100,
                    fee=30,
                    protocol_fee=10,
                    protocol_fee_pre_host=20,
                    host_fee=10,
                ),
            ),
        )
        with patch("meme_machine.dlmm_economics.dlmm.swap", return_value=(state, quote)):
            result = range_economic_case(
                state, state, tape, "sdk_bidask", 8, 60,
                capital_lamports=1_000, fixed_cost_lamports=0,
            )
        self.assertEqual(result["range_lp_fee_sol_lamports"], 10)

    def test_missing_proposed_range_fails_closed(self):
        state = self._state()
        del state["bins"]["2"]
        tape = VerifiedTape("a", "b", (), dict(), "lineage")
        with self.assertRaises(Unavailable):
            range_economic_case(state, state, tape, "sdk_bidask", 8, 60)


if __name__ == "__main__":
    unittest.main()
