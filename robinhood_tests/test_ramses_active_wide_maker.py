from __future__ import annotations

import unittest

from robinhood_research import BoundaryError
from robinhood_research.ramses_active_wide_maker import (
    CAPITAL_RATIO_MAX,
    CAPITAL_RATIO_MIN,
    HARD_D,
    MIN_WIDTH_BINS,
    PROACTIVE_D,
    REMINT_MAX_SECONDS,
    ReplacementCandidate,
    candidate_eligible,
    choose_executable_size,
    normalized_displacement,
    post_burn_remint_decision,
    rebalance_decision,
    select_replacement,
)


def candidate(
    *,
    width=90,
    sidedness="two_sided",
    active_inside=True,
    unwind=True,
    after=50,
    stress=10,
    ratio=1.0,
    size=25,
):
    return ReplacementCandidate(
        width_bins=width,
        sidedness=sidedness,
        active_inside=active_inside,
        full_unwind_executable=unwind,
        after_cost_return_bps=after,
        two_x_cost_return_bps=stress,
        capital_preservation_ratio=ratio,
        size_bps=size,
    )


class RamsesActiveWideMakerV1Tests(unittest.TestCase):
    def test_displacement_boundaries(self):
        self.assertEqual(normalized_displacement(0,100,50),0.0)
        self.assertEqual(normalized_displacement(0,100,75),0.5)
        self.assertEqual(normalized_displacement(0,100,100),1.0)
        self.assertEqual(PROACTIVE_D,0.5)
        self.assertEqual(HARD_D,1.0)

    def test_invalid_range_fails_closed(self):
        with self.assertRaisesRegex(BoundaryError,"wide_maker_invalid_range"):
            normalized_displacement(10,0,5)

    def test_inner_half_holds_even_with_valid_replacement(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=70,
            evidence_complete=True,current_unwind_executable=True,
            candidates=[candidate(width=90)],
        )
        self.assertEqual(result["action"],"hold")
        self.assertEqual(result["reason"],"inner_half_valid_range")

    def test_proactive_zone_rebalances_only_with_valid_replacement(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=80,
            evidence_complete=True,current_unwind_executable=True,
            candidates=[candidate(width=90,ratio=1.0)],
        )
        self.assertEqual(result["action"],"rebalance")
        self.assertEqual(result["reason"],"proactive_zone_valid_replacement")

    def test_proactive_zone_holds_when_replacement_not_ready(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=80,
            evidence_complete=True,current_unwind_executable=True,
            candidates=[candidate(width=42)],
        )
        self.assertEqual(result["action"],"hold")
        self.assertEqual(result["reason"],"proactive_zone_replacement_not_ready")

    def test_hard_zone_rebalances_or_exits(self):
        good=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=101,
            evidence_complete=True,current_unwind_executable=True,
            candidates=[candidate(width=120,ratio=1.0)],
        )
        self.assertEqual(good["action"],"rebalance")
        bad=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=101,
            evidence_complete=True,current_unwind_executable=True,
            candidates=[candidate(width=32)],
        )
        self.assertEqual(bad["action"],"exit")

    def test_narrow_current_range_is_hard_geometry_failure(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=40,active_bin=20,
            evidence_complete=True,current_unwind_executable=True,
            candidates=[candidate(width=90)],
        )
        self.assertEqual(result["action"],"rebalance")

    def test_unwind_failure_exits_without_replacement(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=50,
            evidence_complete=True,current_unwind_executable=False,
            candidates=[],
        )
        self.assertEqual(result["action"],"exit")

    def test_candidate_hard_gates_match_operator_contract(self):
        self.assertFalse(candidate_eligible(candidate(width=MIN_WIDTH_BINS-1)))
        self.assertFalse(candidate_eligible(candidate(unwind=False)))
        self.assertFalse(candidate_eligible(candidate(after=0)))
        self.assertFalse(candidate_eligible(candidate(stress=0)))
        self.assertFalse(candidate_eligible(candidate(ratio=CAPITAL_RATIO_MIN-.01)))
        self.assertFalse(candidate_eligible(candidate(ratio=CAPITAL_RATIO_MAX+.01)))
        self.assertFalse(candidate_eligible(candidate(sidedness="x_only")))
        self.assertTrue(candidate_eligible(candidate(width=65,ratio=.8)))
        self.assertTrue(candidate_eligible(candidate(width=200,ratio=1.2)))
        self.assertTrue(candidate_eligible(
            candidate(sidedness="x_only"),
            allow_directional_repair=True,
        ))

    def test_selection_prefers_stressed_economics_then_after_cost(self):
        choice=select_replacement([
            candidate(width=65,after=100,stress=20),
            candidate(width=90,after=80,stress=30),
            candidate(width=120,after=90,stress=30),
        ])
        self.assertEqual(choice.width_bins,120)

    def test_size_ladder_uses_largest_executable_not_above_target(self):
        self.assertEqual(
            choose_executable_size({50:False,25:True,12:True},governed_target_bps=50),25
        )
        self.assertEqual(
            choose_executable_size({50:True,25:True,12:True},governed_target_bps=25),25
        )
        self.assertIsNone(choose_executable_size({50:False,25:False,12:False,6:False,3:False,1:False}))

    def test_post_burn_remint_window_is_hard_180_seconds(self):
        good=post_burn_remint_decision(
            elapsed_seconds=REMINT_MAX_SECONDS,
            evidence_complete=True,
            candidates=[candidate()],
        )
        self.assertEqual(good["action"],"remint")
        late=post_burn_remint_decision(
            elapsed_seconds=REMINT_MAX_SECONDS+0.001,
            evidence_complete=True,
            candidates=[candidate()],
        )
        self.assertEqual(late["action"],"stay_cash")
        self.assertEqual(late["reason"],"remint_window_expired")

    def test_no_averaging_down_or_up_after_burn(self):
        too_small=post_burn_remint_decision(
            elapsed_seconds=30,evidence_complete=True,
            candidates=[candidate(ratio=.79)],
        )
        too_large=post_burn_remint_decision(
            elapsed_seconds=30,evidence_complete=True,
            candidates=[candidate(ratio=1.21)],
        )
        self.assertEqual(too_small["action"],"stay_cash")
        self.assertEqual(too_large["action"],"stay_cash")

    def test_evidence_failure_fails_closed(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=80,
            evidence_complete=False,current_unwind_executable=True,
            candidates=[candidate()],
        )
        self.assertEqual(result["action"],"fail_closed")


if __name__=="__main__":
    unittest.main()
