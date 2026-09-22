from __future__ import annotations

import unittest

from robinhood_research import BoundaryError
from robinhood_research.ramses_active_wide_maker import (
    CAPITAL_RATIO_MAX,
    CAPITAL_RATIO_MIN,
    HARD_REMINT_DEADLINE_SECONDS,
    ReplacementCandidate,
    candidate_eligible,
    choose_executable_size,
    normalized_displacement,
    rebalance_decision,
    remint_deadline_action,
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
    overlap=0.0,
    ratio=1.0,
    size=25,
):
    return ReplacementCandidate(
        width_bins=width,
        sidedness=sidedness,
        active_inside=active_inside,
        full_unwind_executable=unwind,
        after_cost_fee_return_bps=after,
        two_x_cost_return_bps=stress,
        overlap_fraction=overlap,
        capital_preservation_ratio=ratio,
        size_bps=size,
    )


class RamsesActiveWideMakerV3Tests(unittest.TestCase):
    def test_normalized_displacement_boundaries(self):
        self.assertEqual(normalized_displacement(0,100,50),0.0)
        self.assertEqual(normalized_displacement(0,100,100),1.0)
        self.assertEqual(normalized_displacement(0,100,125),1.5)
        self.assertEqual(normalized_displacement(0,100,200),3.0)
        self.assertGreater(normalized_displacement(0,100,201),3.0)

    def test_invalid_range_fails_closed(self):
        with self.assertRaisesRegex(BoundaryError,"wide_maker_invalid_range"):
            normalized_displacement(10,0,5)

    def test_inside_holds_without_fee_reserve(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=90,
            evidence_complete=True,current_unwind_executable=True,
            fee_reserve_quote=199,rebalance_cycle_cost_quote=100,
            inventory_risk_quote=0,remaining_fee_reserve_quote=1000,
            unwind_deteriorated=False,
            candidates=[candidate(overlap=.75,ratio=1.0)],
        )
        self.assertEqual(result["action"],"hold")

    def test_inside_compounds_only_with_economic_broad_overlap_and_preserved_capital(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=50,
            evidence_complete=True,current_unwind_executable=True,
            fee_reserve_quote=200,rebalance_cycle_cost_quote=100,
            inventory_risk_quote=0,remaining_fee_reserve_quote=1000,
            unwind_deteriorated=False,
            candidates=[
                candidate(width=65,after=60,overlap=.75,ratio=.79),
                candidate(width=90,after=80,overlap=.60,ratio=1.0),
                candidate(width=120,after=80,overlap=.80,ratio=1.21),
            ],
        )
        self.assertEqual(result["action"],"compound_resize")
        self.assertEqual(result["replacement"]["width_bins"],90)

    def test_inside_risk_exit_overrides_compound(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=50,
            evidence_complete=True,current_unwind_executable=True,
            fee_reserve_quote=1000,rebalance_cycle_cost_quote=100,
            inventory_risk_quote=501,remaining_fee_reserve_quote=500,
            unwind_deteriorated=False,
            candidates=[candidate(overlap=.75,ratio=1.0)],
        )
        self.assertEqual(result["action"],"exit")

    def test_watch_band_prohibits_partial_shift(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=110,
            evidence_complete=True,current_unwind_executable=True,
            fee_reserve_quote=1000,rebalance_cycle_cost_quote=100,
            inventory_risk_quote=0,remaining_fee_reserve_quote=500,
            unwind_deteriorated=False,
            candidates=[candidate(overlap=.3,ratio=1.0)],
        )
        self.assertEqual(result["action"],"watch")
        self.assertEqual(result["reason"],"hysteresis_no_partial_shift")

    def test_recenter_band_requires_fresh_broad_full_reset_and_preserved_capital(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=150,
            evidence_complete=True,current_unwind_executable=True,
            fee_reserve_quote=0,rebalance_cycle_cost_quote=100,
            inventory_risk_quote=0,remaining_fee_reserve_quote=500,
            unwind_deteriorated=False,
            candidates=[
                candidate(width=42,after=100,overlap=0.0,ratio=1.0),
                candidate(width=90,after=20,overlap=.25,ratio=1.0),
                candidate(width=120,after=30,overlap=.05,ratio=.79),
                candidate(width=150,after=30,overlap=.05,ratio=1.0),
            ],
        )
        self.assertEqual(result["action"],"recenter")
        self.assertEqual(result["replacement"]["width_bins"],150)

    def test_recenter_exits_when_no_valid_replacement(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=150,
            evidence_complete=True,current_unwind_executable=True,
            fee_reserve_quote=0,rebalance_cycle_cost_quote=100,
            inventory_risk_quote=0,remaining_fee_reserve_quote=500,
            unwind_deteriorated=False,
            candidates=[
                candidate(width=42,overlap=0.0,ratio=1.0),
                candidate(width=90,overlap=.3,ratio=1.0),
                candidate(width=120,stress=0,overlap=.05,ratio=1.0),
                candidate(width=150,overlap=.05,ratio=1.21),
            ],
        )
        self.assertEqual(result["action"],"exit")
        self.assertEqual(result["reason"],"no_valid_recenter_replacement")

    def test_overrun_never_chases(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=201,
            evidence_complete=True,current_unwind_executable=True,
            fee_reserve_quote=1000,rebalance_cycle_cost_quote=100,
            inventory_risk_quote=0,remaining_fee_reserve_quote=500,
            unwind_deteriorated=False,
            candidates=[candidate(width=200,after=100,stress=100,overlap=0,ratio=1.0)],
        )
        self.assertEqual(result["action"],"exit_no_chase")

    def test_evidence_failure_is_fail_closed(self):
        result=rebalance_decision(
            lower_bin=0,upper_bin=100,active_bin=50,
            evidence_complete=False,current_unwind_executable=True,
            fee_reserve_quote=1000,rebalance_cycle_cost_quote=100,
            inventory_risk_quote=0,remaining_fee_reserve_quote=500,
            unwind_deteriorated=False,candidates=[],
        )
        self.assertEqual(result["action"],"fail_closed")

    def test_candidate_hard_gates_include_capital_preservation(self):
        self.assertFalse(candidate_eligible(candidate(width=42),mode="recenter"))
        self.assertFalse(candidate_eligible(candidate(sidedness="x_only"),mode="recenter"))
        self.assertFalse(candidate_eligible(candidate(unwind=False),mode="recenter"))
        self.assertFalse(candidate_eligible(candidate(after=0),mode="recenter"))
        self.assertFalse(candidate_eligible(candidate(stress=0),mode="recenter"))
        self.assertFalse(candidate_eligible(candidate(overlap=.11),mode="recenter"))
        self.assertFalse(candidate_eligible(candidate(overlap=.49),mode="compound_resize"))
        self.assertFalse(candidate_eligible(candidate(overlap=.05,ratio=CAPITAL_RATIO_MIN-.01),mode="recenter"))
        self.assertFalse(candidate_eligible(candidate(overlap=.05,ratio=CAPITAL_RATIO_MAX+.01),mode="recenter"))
        self.assertTrue(candidate_eligible(candidate(overlap=.10,ratio=.8),mode="recenter"))
        self.assertTrue(candidate_eligible(candidate(overlap=.50,ratio=1.2),mode="compound_resize"))

    def test_selection_prefers_after_cost_then_narrower_tie(self):
        choice=select_replacement([
            candidate(width=90,after=50,overlap=0,ratio=1.0),
            candidate(width=120,after=60,overlap=0,ratio=1.0),
            candidate(width=150,after=60,overlap=0,ratio=1.0),
        ],mode="recenter")
        self.assertEqual(choice.width_bins,120)

    def test_size_ladder_uses_largest_executable_not_above_target(self):
        self.assertEqual(
            choose_executable_size({50:False,25:True,12:True},governed_target_bps=50),25
        )
        self.assertEqual(
            choose_executable_size({50:True,25:True,12:True},governed_target_bps=25),25
        )
        self.assertIsNone(choose_executable_size({50:False,25:False,12:False,6:False,3:False,1:False}))

    def test_deadline_is_exact_and_stale_geometry_recomputes(self):
        self.assertEqual(remint_deadline_action(HARD_REMINT_DEADLINE_SECONDS)["action"],"continue_same_decision")
        self.assertEqual(remint_deadline_action(HARD_REMINT_DEADLINE_SECONDS+0.001)["action"],"discard_and_recompute")


if __name__=="__main__":
    unittest.main()
