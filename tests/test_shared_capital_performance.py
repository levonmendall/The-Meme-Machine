"""Sparse samples, confidence, time efficiency and slow bounded budget changes."""
from copy import deepcopy
import tempfile
import unittest

from meme_machine.shared_capital import RiskPolicy
from meme_machine.shared_capital.performance import evidence_score, update_budgets
from meme_machine.shared_capital.model import money
from tests.shared_capital_support import Harness


def samples(n, pnl="5", capital="25", days=2, at=1000000):
    return [dict(at=at - i * 60, pnl=pnl, capital_deployed=capital,
        capital_seconds=str(money(capital) * days * 86400), costs="0.1") for i in reversed(range(n))]


class PerformanceTests(unittest.TestCase):
    def test_single_outlier_shrinks_toward_neutral(self):
        policy = RiskPolicy(adaptive=True).value()
        single = evidence_score(samples(1, pnl="1000"), policy, 1000000)
        demonstrated = evidence_score(samples(60), policy, 1000000)
        self.assertLess(single["multiplier_bps"], 10250)
        self.assertGreater(demonstrated["multiplier_bps"], single["multiplier_bps"])
        self.assertEqual(evidence_score([], policy, 1000000)["multiplier_bps"], 10000)

    def test_recent_winning_streak_cannot_erase_longer_losses(self):
        policy = RiskPolicy(adaptive=True).value(); at = 3000000
        long = samples(80, pnl="-5", at=at - 10 * 86400)
        streak = samples(3, pnl="10", at=at)
        score = evidence_score(long + streak, policy, at)
        self.assertTrue(score["inconsistent_windows"])
        self.assertLess(score["multiplier_bps"], 10000)

    def test_profit_factor_drawdown_downside_tail_costs_and_capital_time_are_reported(self):
        policy = RiskPolicy(adaptive=True).value()
        score = evidence_score(samples(30) + samples(5, pnl="-3") + samples(1, pnl="100"), policy, 1000000)
        ref = score["reference"]
        self.assertGreater(ref["profit_factor_bps"], 10000)
        self.assertGreater(ref["drawdown_bps"], 0)
        self.assertGreater(ref["downside_bps"], 0)
        self.assertGreater(ref["tail_capture_bps"], 0)
        self.assertGreater(money(ref["capital_seconds"]), 0)
        self.assertGreater(money(ref["costs"]), 0)

    def test_return_per_capital_time_does_not_reward_gross_pnl_or_holding_period_alone(self):
        policy = RiskPolicy(adaptive=True).value()
        fast = evidence_score(samples(60, pnl="25", days=1), policy, 1000000)
        slow = evidence_score(samples(60, pnl="250", days=10), policy, 1000000)
        self.assertEqual(fast["reference"]["efficiency_bps_per_day"], slow["reference"]["efficiency_bps_per_day"])
        self.assertEqual(fast["multiplier_bps"], slow["multiplier_bps"])

    def test_bounded_hysteresis_cooldown_and_no_sale_of_existing_positions(self):
        with tempfile.TemporaryDirectory() as td:
            h = Harness(td, RiskPolicy(adaptive=True))
            try:
                requests, _ = h.allocate([("pump_current", {})]); h.fill(requests[0])
                before = h.authority.snapshot()["ledger"]
                state = deepcopy(before)
                state["samples"]["pons_current"] = samples(100)
                update_budgets(state, 1000000)
                first = state["allocation"]["multipliers"]["pons_current"]
                self.assertGreater(first, 10000)
                self.assertLessEqual(first, 10500)
                state["samples"]["pons_current"] = samples(100, pnl="-20", at=1000001)
                update_budgets(state, 1000001)
                self.assertEqual(state["allocation"]["multipliers"]["pons_current"], first)
                update_budgets(state, 1000001 + 3600)
                self.assertLess(state["allocation"]["multipliers"]["pons_current"], first)
                self.assertEqual(state["positions"], before["positions"])
                self.assertEqual(state["cash"], before["cash"])
                self.assertTrue(all(8000 <= v <= 12000 for v in state["allocation"]["multipliers"].values()))
            finally: h.close()
