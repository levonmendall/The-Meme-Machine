import unittest

from robinhood_research.ramses import pack
from robinhood_research.ramses_strategy import (
    POLICY,
    POLICY_HASH,
    STRATEGY_VERSION,
    STRATEGY_DOMAIN,
    USDG_ADDRESS,
    attach_universe_percentiles,
    build_fee_pulse_freeze,
    build_path_freeze,
    classify_pool,
    controller_action,
    evaluate_fee_pulse,
    pool_features,
    recommended_capital,
)


class RamsesStrategyTests(unittest.TestCase):
    def _state(self):
        active = 1 << 23
        bins = {}
        for bid in range(active - 110, active + 111):
            if bid < active:
                reserves = [0, 10**18]
            elif bid > active:
                reserves = [10**18, 0]
            else:
                reserves = [10**18, 10**18]
            bins[bid] = dict(reserves=reserves, supply=10**18)
        return dict(
            active=active,
            step=10,
            reserves=[5 * 10**18, 5 * 10**18],
            protocol=[0, 0],
            static=[40000, 30, 600, 5000, 40000, 500, 350000],
            variable=[10000, 0, active, 1000],
            bins=bins,
        )

    def _history(self, count=8, choppy=True):
        a = 1 << 23
        if choppy:
            ids = [a, a + 1, a - 1, a + 2, a - 2, a + 3, a - 3, a]
        else:
            ids = list(range(a, a + 8))
        ids=ids[:count]
        rows = []
        for i, bid in enumerate(ids):
            amount = (2 if i < max(1,len(ids) // 2) else 6) * 10**17
            side = 0 if i % 2 == 0 else 1
            pair = [amount, 0] if side == 0 else [0, amount]
            fee = [10**16, 0] if side == 0 else [0, 10**16]
            rows.append(dict(args=dict(
                id=bid,
                amountsIn=hex(pack(pair)),
                protocolFees=hex(pack([0, 0])),
                totalFees=hex(pack(fee)),
            )))
        return rows

    @staticmethod
    def _costs(value=1):
        return {"entry":value,"add":value,"remove":value,"unwind":value}

    def _decision(
        self, *, history=None, rebalance_reference_capital=None,
        rebalance_reference_bins=None, rebalance_mode=None,
        quote_token=USDG_ADDRESS
    ):
        return classify_pool(
            self._state(),
            self._history(2) if history is None else history,
            "y",
            requested_capital=10**16,
            entry_timestamp=1000,
            now=1000,
            gas_costs=self._costs(),
            quote_token=quote_token,
            rebalance_reference_capital=rebalance_reference_capital,
            rebalance_reference_bins=rebalance_reference_bins,
            rebalance_mode=rebalance_mode,
        )

    def test_policy_is_active_wide_maker_v3_and_paper_only(self):
        self.assertEqual(
            STRATEGY_VERSION,
            "ramses-active-wide-maker-v1/rebalance-v3",
        )
        self.assertEqual(STRATEGY_DOMAIN, "robinhood-ramses-dlmm-independent")
        self.assertEqual(POLICY["policy_revision"], "profitability-v1-active-wide-maker-v3")
        self.assertTrue(POLICY["profitability_authority"])
        self.assertFalse(POLICY["machinery_proof_only"])
        self.assertFalse(POLICY["independence"]["shared_allocator"])
        self.assertEqual(POLICY["active_wide_maker"]["quote_token"], USDG_ADDRESS)
        self.assertEqual(POLICY["active_wide_maker"]["prior_30m_swaps_max"], 2)
        self.assertEqual(POLICY["active_wide_maker"]["min_width_bins"], 65)
        self.assertEqual(POLICY["active_wide_maker"]["max_position_local_liquidity_bps"], 50)
        self.assertEqual(POLICY["validation"]["minimum_eligible_rebalances"], 20)
        self.assertEqual(POLICY["validation"]["minimum_distinct_pools"], 5)
        self.assertEqual(len(POLICY_HASH), 64)
        self.assertFalse(POLICY["allocation_authority"])
        self.assertTrue(POLICY["paper_only"])

    def test_chop_metric_and_percentiles_remain_available_for_telemetry(self):
        state=self._state()
        choppy=pool_features(state,self._history(8,True),"y")
        directional=pool_features(state,self._history(8,False),"y")
        self.assertGreater(choppy["chop_ratio_milli"],directional["chop_ratio_milli"])
        ranked=attach_universe_percentiles(choppy,[
            dict(turnover_bps=1,total_fee_rate=1),
            dict(turnover_bps=2,total_fee_rate=2),
        ])
        self.assertEqual(ranked["turnover_percentile_bps"],10000)
        self.assertEqual(ranked["fee_percentile_bps"],10000)

    def test_legacy_fee_pulse_helpers_remain_replayable_but_not_authoritative(self):
        state=self._state()
        history=self._history(8,True)
        features=pool_features(state,history,"y")
        freeze=build_fee_pulse_freeze(
            state,10**16,"y",entry_timestamp=1000,prehistory=history,
            gas_costs=self._costs(),features=features,
        )
        self.assertTrue(evaluate_fee_pulse(features,freeze["proposals"][0])["qualified"])
        path=build_path_freeze(
            state,10**16,"y",direction="up",mode="anchor_pulse",
            entry_timestamp=1000,
        )
        self.assertTrue(path["proposals"][0]["one_sided"])
        active=self._decision()
        self.assertEqual(active["mode"],"active_wide_maker")
        self.assertNotIn(active["mode"],("fee_pulse","anchor_pulse","directional_converter"))

    def test_capital_is_capped_at_half_percent_of_active_liquidity(self):
        f=pool_features(self._state(),self._history(2),"y")
        expected=f["active_liquidity_quote"]*50//10000
        self.assertEqual(recommended_capital(f,10**30),expected)

    def test_quiet_usdg_entry_builds_wide_two_sided_freeze(self):
        decision=self._decision()
        self.assertTrue(decision["qualified"],decision)
        self.assertEqual(decision["mode"],"active_wide_maker")
        proposal=decision["freeze"]["proposals"][0]
        self.assertGreaterEqual(len(proposal["bins"]),65)
        self.assertIn(len(proposal["bins"]),POLICY["active_wide_maker"]["width_candidates"])
        self.assertTrue(proposal["two_sided"])
        self.assertGreaterEqual(proposal["capital_preservation_bps"],8000)
        self.assertLessEqual(proposal["capital_preservation_bps"],12000)

    def test_non_usdg_and_nonquiet_initial_entries_fail_closed(self):
        wrong=self._decision(quote_token="0x"+"11"*20)
        self.assertFalse(wrong["qualified"])
        self.assertIn("quote_asset_not_usdg",wrong["reasons"])
        busy=self._decision(history=self._history(3))
        self.assertFalse(busy["qualified"])
        self.assertIn("prior_30m_not_quiet",busy["reasons"])

    def test_rebalance_bypasses_initial_quiet_gate_but_requires_economics(self):
        initial=self._decision()
        old_bins=initial["freeze"]["proposals"][0]["bins"]
        decision=self._decision(
            history=self._history(8),
            rebalance_reference_capital=10**16,
            rebalance_reference_bins=old_bins,
            rebalance_mode="compound_resize",
        )
        self.assertTrue(decision["qualified"],decision)
        self.assertTrue(decision["rebalance_candidate"])
        self.assertEqual(decision["rebalance_mode"],"compound_resize")
        proposal=decision["freeze"]["proposals"][0]
        self.assertGreater(proposal["projected_after_cost_result"],0)
        self.assertGreater(proposal["two_x_cost_stress_result"],0)
        self.assertGreaterEqual(
            proposal["overlap_fraction"],
            POLICY["active_wide_maker"]["compound_overlap_min"],
        )

    def test_recenter_requires_low_overlap(self):
        state=self._state()
        initial=self._decision()
        old_proposal=initial["freeze"]["proposals"][0]
        old_bins=old_proposal["bins"]
        burn_capital=int(old_proposal["capital_employed"])
        # Move the whole synthetic market state far enough that a centered
        # replacement has low overlap while preserving realistic local flow.
        old_active=state["active"]
        state["active"]+=100
        for bid,row in state["bins"].items():
            if bid < state["active"]:
                row["reserves"]=[0,10**18]
            elif bid > state["active"]:
                row["reserves"]=[10**18,0]
            else:
                row["reserves"]=[10**18,10**18]
        history=self._history(8)
        for row in history:
            row["args"]["id"]+=state["active"]-old_active
        decision=classify_pool(
            state,history,"y",requested_capital=burn_capital,
            entry_timestamp=1000,now=1000,gas_costs=self._costs(),
            quote_token=USDG_ADDRESS,
            rebalance_reference_capital=burn_capital,
            rebalance_reference_bins=old_bins,
            rebalance_mode="recenter",
        )
        self.assertTrue(decision["qualified"],decision)
        proposal=decision["freeze"]["proposals"][0]
        self.assertLessEqual(
            proposal["overlap_fraction"],
            POLICY["active_wide_maker"]["recenter_overlap_max"],
        )

    def test_legacy_external_signal_cannot_grant_strategy_authority(self):
        signal=dict(
            kind="anchor",source_class="external_reference",observed_at=995,
            confidence_bps=9000,expected_net_bps=100,direction="up",
        )
        decision=classify_pool(
            self._state(),self._history(2),"y",requested_capital=10**16,
            entry_timestamp=1000,now=1000,gas_costs=self._costs(),
            quote_token=USDG_ADDRESS,anchor_signal=signal,
        )
        self.assertTrue(decision["qualified"])
        self.assertEqual(decision["mode"],"active_wide_maker")
        self.assertTrue(decision["legacy_signals_ignored"])

    def test_controller_holds_inside_and_watch_zone(self):
        decision=self._decision()
        proposal=decision["freeze"]["proposals"][0]
        lo,hi=min(proposal["bins"]),max(proposal["bins"])
        center=(lo+hi)//2
        inside=controller_action(
            decision,current_active_bin=center,elapsed_seconds=60,rebalances_used=0,
            opportunity_still_qualified=False,expected_remaining_fee_quote=19,
            estimated_inventory_loss_quote=10,rebalance_cost_quote=10,unwind_cost_quote=10,
        )
        self.assertEqual(inside["action"],"hold")
        half=(hi-lo)/2
        watch_bin=int((lo+hi)/2+1.2*half)
        watch=controller_action(
            decision,current_active_bin=watch_bin,elapsed_seconds=60,rebalances_used=0,
            opportunity_still_qualified=False,expected_remaining_fee_quote=1000,
            estimated_inventory_loss_quote=10,rebalance_cost_quote=10,unwind_cost_quote=10,
        )
        self.assertEqual((watch["action"],watch["reason"]),("hold","hysteresis_no_partial_shift"))

    def test_controller_compounds_inside_when_fee_reserve_pays_cycle(self):
        decision=self._decision()
        proposal=decision["freeze"]["proposals"][0]
        center=(min(proposal["bins"])+max(proposal["bins"]))//2
        action=controller_action(
            decision,current_active_bin=center,elapsed_seconds=60,rebalances_used=0,
            opportunity_still_qualified=True,expected_remaining_fee_quote=20,
            estimated_inventory_loss_quote=0,rebalance_cost_quote=10,unwind_cost_quote=10,
        )
        self.assertEqual(action["action"],"rebalance")
        self.assertEqual(action["mode"],"compound_resize")
        self.assertEqual(action["reason"],"fee_reserve_pays_compound")

    def test_controller_recenters_only_with_known_positive_remaining_edge(self):
        decision=self._decision()
        proposal=decision["freeze"]["proposals"][0]
        lo,hi=min(proposal["bins"]),max(proposal["bins"])
        half=(hi-lo)/2
        recenter_bin=int((lo+hi)/2+2.0*half)
        unknown=controller_action(
            decision,current_active_bin=recenter_bin,elapsed_seconds=60,rebalances_used=0,
            opportunity_still_qualified=True,expected_remaining_fee_quote=None,
            estimated_inventory_loss_quote=10,rebalance_cost_quote=10,unwind_cost_quote=10,
        )
        self.assertEqual((unknown["action"],unknown["reason"]),("exit","recenter_fee_reserve_unavailable"))
        recenter=controller_action(
            decision,current_active_bin=recenter_bin,elapsed_seconds=60,rebalances_used=0,
            opportunity_still_qualified=True,expected_remaining_fee_quote=1000,
            estimated_inventory_loss_quote=10,rebalance_cost_quote=10,unwind_cost_quote=10,
        )
        self.assertEqual(recenter["action"],"rebalance")

    def test_controller_never_chases_overrun_and_exits_on_inventory_risk(self):
        decision=self._decision()
        proposal=decision["freeze"]["proposals"][0]
        lo,hi=min(proposal["bins"]),max(proposal["bins"])
        half=(hi-lo)/2
        overrun=int((lo+hi)/2+3.2*half)
        out=controller_action(
            decision,current_active_bin=overrun,elapsed_seconds=60,rebalances_used=0,
            opportunity_still_qualified=True,expected_remaining_fee_quote=10000,
            estimated_inventory_loss_quote=0,rebalance_cost_quote=10,unwind_cost_quote=10,
        )
        self.assertEqual((out["action"],out["reason"]),("exit","normalized_displacement_overrun_no_chase"))
        risk=controller_action(
            decision,current_active_bin=(lo+hi)//2,elapsed_seconds=60,rebalances_used=0,
            opportunity_still_qualified=True,expected_remaining_fee_quote=100,
            estimated_inventory_loss_quote=101,rebalance_cost_quote=10,unwind_cost_quote=10,
        )
        self.assertEqual((risk["action"],risk["reason"]),("exit","inventory_risk_dominates"))


if __name__=="__main__":
    unittest.main()
