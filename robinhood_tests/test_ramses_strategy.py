import unittest

from robinhood_research.ramses import pack
from robinhood_research.ramses_strategy import (
    POLICY,
    POLICY_HASH,
    STRATEGY_VERSION,
    STRATEGY_DOMAIN,
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
        for bid in range(active - 4, active + 5):
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

    def _history(self, choppy=True):
        a = 1 << 23
        ids = [a, a + 1, a - 1, a + 2, a - 2, a + 3, a - 3, a] if choppy else list(range(a, a + 8))
        rows = []
        for i, bid in enumerate(ids):
            amount = (2 if i < len(ids) // 2 else 6) * 10**17
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

    def test_policy_is_frozen_and_research_only(self):
        self.assertEqual(STRATEGY_VERSION, "ramses-fee-pulse-v1")
        self.assertEqual(STRATEGY_DOMAIN, "robinhood-ramses-dlmm-independent")
        self.assertFalse(POLICY["independence"]["shared_allocator"])
        self.assertFalse(POLICY["independence"]["cross_strategy_signals"])
        self.assertEqual(len(POLICY_HASH), 64)
        self.assertFalse(POLICY["allocation_authority"])
        self.assertTrue(POLICY["paper_only"])
        self.assertEqual(POLICY["hurdle_bps"], -150000)
        self.assertEqual(POLICY["policy_revision"], "machinery-proof-v2")
        self.assertEqual(POLICY["reference_profitability_hurdle_bps"], 35)

    def test_chop_metric_distinguishes_two_way_from_directional_path(self):
        state = self._state()
        choppy = pool_features(state, self._history(True), "y")
        directional = pool_features(state, self._history(False), "y")
        self.assertGreater(choppy["chop_ratio_milli"], directional["chop_ratio_milli"])
        self.assertEqual(choppy["net_displacement_bins"], 0)
        self.assertGreater(choppy["gross_bin_crossings"], 0)

    def test_universe_percentiles_rank_fee_density_and_fee_rate(self):
        feature = pool_features(self._state(), self._history(True), "y")
        peers = [
            dict(turnover_bps=1, total_fee_rate=1),
            dict(turnover_bps=2, total_fee_rate=2),
            dict(turnover_bps=3, total_fee_rate=3),
        ]
        ranked = attach_universe_percentiles(feature, peers)
        self.assertEqual(ranked["turnover_percentile_bps"], 10000)
        self.assertEqual(ranked["fee_percentile_bps"], 10000)

    def test_fee_pulse_range_uses_70_30_core_buffer_when_history_requires_it(self):
        state = self._state()
        history = self._history(True)
        features = pool_features(state, history, "y")
        self.assertEqual((features["core_width"], features["outer_width"]), (2, 3))
        freeze = build_fee_pulse_freeze(
            state, 10**16, "y", entry_timestamp=1000,
            prehistory=history,
            gas_costs={"entry": 1, "add": 1, "remove": 1, "unwind": 1},
            features=features,
        )
        proposal = freeze["proposals"][0]
        self.assertEqual(proposal["core_allocation_bps"], 7000)
        self.assertEqual(proposal["buffer_allocation_bps"], 3000)
        self.assertEqual(proposal["bins"][0], state["active"] - 3)
        self.assertEqual(proposal["bins"][-1], state["active"] + 3)
        self.assertFalse(freeze["allocation_authority"])

    def test_fee_pulse_requires_universe_and_cost_evidence(self):
        state = self._state()
        history = self._history(True)
        features = pool_features(state, history, "y")
        freeze = build_fee_pulse_freeze(state, 10**16, "y", entry_timestamp=1000, prehistory=history)
        evaluation = evaluate_fee_pulse(features, freeze["proposals"][0])
        self.assertFalse(evaluation["qualified"])
        self.assertNotIn("universe_percentiles_unavailable", evaluation["reasons"])
        self.assertIn("cost_evidence_unavailable", evaluation["reasons"])

    def test_fee_pulse_can_qualify_on_frozen_high_density_inputs(self):
        state = self._state()
        history = self._history(True)
        features = pool_features(state, history, "y")
        features["turnover_percentile_bps"] = 10000
        features["fee_percentile_bps"] = 10000
        freeze = build_fee_pulse_freeze(
            state, 10**16, "y", entry_timestamp=1000, prehistory=history,
            gas_costs={"entry": 1, "add": 1, "remove": 1, "unwind": 1}, features=features,
        )
        evaluation = evaluate_fee_pulse(features, freeze["proposals"][0])
        self.assertTrue(evaluation["qualified"], evaluation)

    def test_execution_certification_percentiles_rank_but_do_not_veto(self):
        state = self._state()
        history = self._history(True)
        features = pool_features(state, history, "y")
        features["turnover_percentile_bps"] = 0
        features["fee_percentile_bps"] = 0
        freeze = build_fee_pulse_freeze(
            state, 10**16, "y", entry_timestamp=1000, prehistory=history,
            gas_costs={"entry": 1, "add": 1, "remove": 1, "unwind": 1}, features=features,
        )
        evaluation = evaluate_fee_pulse(features, freeze["proposals"][0])
        self.assertTrue(evaluation["qualified"], evaluation)
        self.assertFalse(evaluation["percentile_targets"]["turnover"])
        self.assertFalse(evaluation["percentile_targets"]["fee"])

    def test_machinery_proof_accepts_observed_one_way_negative_candidate(self):
        state = self._state()
        history = self._history(True)
        features = pool_features(state, history, "y")
        features["turnover_percentile_bps"] = 10000
        features["fee_percentile_bps"] = 10000
        features["volume_acceleration_milli"] = 0
        features["chop_ratio_milli"] = 0
        features["flow_imbalance_bps"] = 10000
        freeze = build_fee_pulse_freeze(
            state, 10**16, "y", entry_timestamp=1000, prehistory=history,
            gas_costs={"entry": 1, "add": 1, "remove": 1, "unwind": 1}, features=features,
        )
        proposal = freeze["proposals"][0]
        proposal["projected_return_bps"] = -134171
        evaluation = evaluate_fee_pulse(features, proposal)
        self.assertTrue(evaluation["qualified"], evaluation)

    def test_capital_is_capped_at_ten_percent_of_active_liquidity(self):
        f = pool_features(self._state(), self._history(True), "y")
        self.assertLessEqual(recommended_capital(f, 10**30), f["active_liquidity_quote"] // 10)

    def test_anchor_and_directional_ranges_are_one_sided(self):
        state = self._state()
        up = build_path_freeze(state, 10**16, "y", direction="up", mode="anchor_pulse", entry_timestamp=1000)
        down = build_path_freeze(state, 10**16, "y", direction="down", mode="directional_converter", entry_timestamp=1000)
        self.assertTrue(all(b > state["active"] for b in up["proposals"][0]["bins"]))
        self.assertTrue(all(b < state["active"] for b in down["proposals"][0]["bins"]))
        self.assertTrue(up["proposals"][0]["one_sided"])

    def test_external_signal_modes_fail_closed_when_stale_and_accept_explicit_fresh_signal(self):
        state = self._state()
        history = self._history(True)
        stale = dict(kind="anchor", source_class="external_reference", observed_at=900, confidence_bps=9000, expected_net_bps=100, direction="up")
        no_trade = classify_pool(
            state, history, "y", requested_capital=10**16, entry_timestamp=1000, now=1000,
            anchor_signal=stale,
        )
        self.assertNotEqual(no_trade["mode"], "anchor_pulse")
        fresh = dict(kind="anchor", source_class="external_reference", observed_at=995, confidence_bps=9000, expected_net_bps=100, direction="up")
        anchored = classify_pool(
            state, history, "y", requested_capital=10**16, entry_timestamp=1000, now=1000,
            anchor_signal=fresh,
        )
        self.assertEqual(anchored["mode"], "anchor_pulse")
        self.assertTrue(anchored["qualified"])
        directional = dict(kind="directional", source_class="ramses_independent_model", observed_at=995, confidence_bps=9000,
                           expected_net_bps=100, direction="down", conversion_side="x")
        converted = classify_pool(
            state, history, "y", requested_capital=10**16, entry_timestamp=1000, now=1000,
            directional_signal=directional,
        )
        self.assertEqual(converted["mode"], "directional_converter")

    def test_event_driven_controller_rebalances_then_exits_on_risk_or_limit(self):
        state = self._state()
        history = self._history(True)
        signal = dict(kind="anchor", source_class="external_reference", observed_at=995, confidence_bps=9000, expected_net_bps=100, direction="up", path_width=2)
        decision = classify_pool(
            state, history, "y", requested_capital=10**16, entry_timestamp=1000, now=1000,
            anchor_signal=signal,
        )
        action = controller_action(
            decision, current_active_bin=state["active"] + 2, elapsed_seconds=60, rebalances_used=0,
            opportunity_still_qualified=True, expected_remaining_fee_quote=1000,
            estimated_inventory_loss_quote=100, rebalance_cost_quote=100, unwind_cost_quote=100,
        )
        self.assertEqual(action["action"], "rebalance")
        risk = controller_action(
            decision, current_active_bin=state["active"] + 1, elapsed_seconds=60, rebalances_used=0,
            opportunity_still_qualified=True, expected_remaining_fee_quote=100,
            estimated_inventory_loss_quote=100, rebalance_cost_quote=10, unwind_cost_quote=10,
        )
        self.assertEqual((risk["action"], risk["reason"]), ("exit", "inventory_risk_dominates"))
        max_hold = controller_action(
            decision, current_active_bin=state["active"] + 1,
            elapsed_seconds=POLICY["controller"]["max_holding_seconds"], rebalances_used=0,
            opportunity_still_qualified=True, expected_remaining_fee_quote=1000,
            estimated_inventory_loss_quote=1, rebalance_cost_quote=1, unwind_cost_quote=1,
        )
        self.assertEqual((max_hold["action"], max_hold["reason"]), ("exit", "max_holding_period"))

    def test_cross_strategy_signal_provenance_fails_closed(self):
        state = self._state()
        history = self._history(True)
        contaminated = dict(
            kind="anchor",
            source_class="external_reference",
            source_strategy="continuation-v1-robinhood",
            observed_at=995,
            confidence_bps=9000,
            expected_net_bps=100,
            direction="up",
        )
        decision = classify_pool(
            state, history, "y", requested_capital=10**16,
            entry_timestamp=1000, now=1000, anchor_signal=contaminated,
        )
        self.assertNotEqual(decision["mode"], "anchor_pulse")
        self.assertIn(
            "cross_strategy_signal_forbidden",
            decision["signal_rejections"]["anchor"],
        )

    def test_wrong_signal_source_class_fails_closed(self):
        state = self._state()
        history = self._history(True)
        borrowed = dict(
            kind="directional",
            source_class="external_reference",
            observed_at=995,
            confidence_bps=9000,
            expected_net_bps=100,
            direction="down",
            conversion_side="x",
        )
        decision = classify_pool(
            state, history, "y", requested_capital=10**16,
            entry_timestamp=1000, now=1000, directional_signal=borrowed,
        )
        self.assertNotEqual(decision["mode"], "directional_converter")
        self.assertIn(
            "directional_signal_source",
            decision["signal_rejections"]["directional"],
        )


if __name__ == "__main__":
    unittest.main()
