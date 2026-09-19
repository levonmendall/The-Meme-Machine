from unittest import TestCase

from meme_machine.rejected_winner_trajectory import RULE, evaluate, summarize


def vector(**overrides):
    row=dict(
        concentration_bps=5000,
        real_sol_lamports=12_000_000_000,
        evidence_event_count=30,
        independent_buyer_groups=3,
        independent_net_buy_lamports=1_500_000_000,
        price_extension_bps=5000,
        roundtrip_loss_bps=300,
    )
    row.update(overrides)
    return row


class RejectedWinnerTrajectoryTests(TestCase):
    def test_frozen_directional_rule_passes_only_on_broadening_and_executability(self):
        initial=vector()
        confirm=vector(
            concentration_bps=4800,
            real_sol_lamports=12_500_000_000,
            evidence_event_count=35,
            independent_buyer_groups=4,
            independent_net_buy_lamports=1_800_000_000,
            price_extension_bps=5400,
            roundtrip_loss_bps=280,
        )
        result=evaluate(initial,confirm)
        self.assertTrue(result["complete"])
        self.assertTrue(result["passed"])
        self.assertTrue(all(result["checks"].values()))

    def test_thin_liquidity_fails_even_with_demand_acceleration(self):
        initial=vector(real_sol_lamports=9_000_000_000)
        confirm=vector(
            concentration_bps=4800,
            real_sol_lamports=9_500_000_000,
            evidence_event_count=35,
            independent_buyer_groups=4,
            independent_net_buy_lamports=1_800_000_000,
            price_extension_bps=5000,
            roundtrip_loss_bps=280,
        )
        result=evaluate(initial,confirm)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["executable_liquidity_floor"])

    def test_frozen_hard_gate_failure_is_valid_reject_without_downstream_fields(self):
        cases=(
            ("executable_liquidity_floor",dict(real_sol_lamports=9_000_000_000)),
            ("price_extension_within_frozen_cap",dict(price_extension_bps=12_001)),
            ("roundtrip_cost_within_frozen_cap",dict(roundtrip_loss_bps=501)),
        )
        for failed,confirm in cases:
            with self.subTest(failed=failed):
                result=evaluate({},confirm)
                self.assertTrue(result["complete"])
                self.assertFalse(result["passed"])
                self.assertEqual(result["reason"],"trajectory_reject")
                self.assertTrue(result["deterministic_reject"])
                self.assertTrue(result["hard_gate_reject"])
                self.assertEqual(result["hard_gate_failures"],[failed])
                self.assertFalse(result["checks"][failed])

    def test_passing_hard_gates_do_not_hide_missing_trajectory_fields(self):
        result=evaluate(
            vector(),
            dict(
                real_sol_lamports=12_000_000_000,
                price_extension_bps=5000,
                roundtrip_loss_bps=300,
            ),
        )
        self.assertFalse(result["complete"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["reason"],"incomplete_confirmation_vector")
        self.assertFalse(result["hard_gate_reject"])

    def test_rule_does_not_relax_continuation_economic_bounds(self):
        self.assertEqual(RULE["min_real_sol_lamports"],10_000_000_000)
        self.assertEqual(RULE["max_price_extension_bps"],12_000)
        self.assertEqual(RULE["max_roundtrip_loss_bps"],500)
        self.assertFalse(RULE["automatic_trading_admission"])

    def test_summary_never_grants_trading_authority(self):
        body=summarize([])
        self.assertFalse(body["trading_authority_granted"])
        self.assertFalse(body["validation_passed"])
