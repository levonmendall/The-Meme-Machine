import unittest
from meme_machine.lanes.ramses.ramses_strategy import USDG_ADDRESS
from meme_machine.lanes.ramses.ramses_universe import _quiet_activity_cohort,_quote_side

class RamsesMarketScopeEfficiencyTests(unittest.TestCase):
    def test_only_one_or_two_swap_pools_enter_state_cohort(self):
        rows=[{"pool":"zero","swaps":0,"latest_swap_block":0},
              {"pool":"one","swaps":1,"latest_swap_block":10},
              {"pool":"two","swaps":2,"latest_swap_block":11},
              {"pool":"busy","swaps":3,"latest_swap_block":12}]
        selected=_quiet_activity_cohort(rows,32)
        self.assertEqual({r["pool"] for r in selected},{"one","two"})

    def test_usdg_identity_is_known_before_full_state_hydration(self):
        self.assertEqual(_quote_side({"token_x":"0x1","token_y":USDG_ADDRESS}),"y")
        self.assertEqual(_quote_side({"token_x":USDG_ADDRESS,"token_y":"0x2"}),"x")
        self.assertIsNone(_quote_side({"token_x":"0x1","token_y":"0x2"}))

if __name__=="__main__":
    unittest.main()
