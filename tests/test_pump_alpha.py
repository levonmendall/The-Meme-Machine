import unittest
from fractions import Fraction

from meme_machine.pump_alpha import (
    POLICY_HASH,
    PumpAlphaLifecycle,
    creator_confirmation,
    evaluate_exit,
    evaluate_late_curve,
    evaluate_postgrad_continuation,
    evaluate_second_leg,
    policy_snapshot,
    skilled_wallet_convergence,
)


def trade(t, wallet, quote, token=1_000_000, buy=True, **extra):
    row = dict(market_time=t, wallet=wallet, quote_amount=quote, token_amount=token,
               buy=buy, slot=t, index=0)
    row.update(extra)
    return row


def fast_curve(now=100):
    return [
        dict(market_time=70, progress_bps=5200),
        dict(market_time=80, progress_bps=6000),
        dict(market_time=90, progress_bps=7000),
        dict(market_time=94, progress_bps=7600),
        dict(market_time=97, progress_bps=8100),
        dict(market_time=100, progress_bps=8600),
    ]


def slow_curve(now=100):
    return [
        dict(market_time=70, progress_bps=8000),
        dict(market_time=80, progress_bps=8200),
        dict(market_time=90, progress_bps=8400),
        dict(market_time=94, progress_bps=8460),
        dict(market_time=97, progress_bps=8530),
        dict(market_time=100, progress_bps=8600),
    ]


def curve_demand(now=100):
    rows = [
        trade(73, "old1", 25_000_000, 250_000),
        trade(78, "old2", 25_000_000, 240_000),
    ]
    for i, (t, q) in enumerate([
        (91, 60_000_000), (93, 70_000_000), (95, 80_000_000),
        (97, 90_000_000), (99, 100_000_000), (100, 110_000_000),
    ]):
        rows.append(trade(t, f"b{i}", q, 500_000 + i * 40_000, True, cluster=f"c{i}"))
    return rows


class PumpAlphaTests(unittest.TestCase):
    def test_policy_hash_is_deterministic_and_has_no_allocator_authority(self):
        self.assertEqual(len(POLICY_HASH), 64)
        self.assertEqual(
            POLICY_HASH,
            __import__("meme_machine.pump_alpha", fromlist=["POLICY_HASH"]).POLICY_HASH,
        )
        self.assertFalse(policy_snapshot()["authority"]["shared_allocator_authority"])
        self.assertFalse(policy_snapshot()["authority"]["live_money_authority"])

    def test_fast_and_slow_curve_same_final_location_are_distinguished(self):
        common = dict(
            events=curve_demand(), now=100,
            graduation_quote_target=1_000_000_000,
            concentration_bps=1800, quote_asset="SOL", observed_at=100,
        )
        fast = evaluate_late_curve(curve_points=fast_curve(), **common)
        slow = evaluate_late_curve(curve_points=slow_curve(), **common)
        self.assertTrue(fast["eligible"], fast["reasons"])
        self.assertEqual(
            fast["features"]["curve"]["progress_bps"],
            slow["features"]["curve"]["progress_bps"],
        )
        self.assertFalse(slow["eligible"])
        self.assertIn("insufficient_curve_acceleration", slow["reasons"])
        self.assertGreater(fast["score_bps"], slow["score_bps"])

    def test_skilled_wallet_confirmation_requires_prior_skill_independence_and_followers(self):
        profiles = {
            "s1": dict(
                as_of=50, historical_trades=30, historical_roi_bps=1500,
                historical_net_pnl_quote=10, cluster="skill-a", funding_group="fund-a",
            ),
            "s2": dict(
                as_of=50, historical_trades=40, historical_roi_bps=900,
                historical_net_pnl_quote=11, cluster="skill-b", funding_group="fund-b",
            ),
            "samefund": dict(
                as_of=50, historical_trades=20, historical_roi_bps=500,
                historical_net_pnl_quote=5, cluster="skill-c", funding_group="fund-a",
            ),
            "future": dict(
                as_of=105, historical_trades=50, historical_roi_bps=5000,
                historical_net_pnl_quote=50, cluster="future",
            ),
            "creator": dict(
                as_of=50, historical_trades=50, historical_roi_bps=5000,
                historical_net_pnl_quote=50, cluster="creator", creator_related=True,
            ),
        }
        rows = [
            trade(80, "s1", 50), trade(82, "s2", 50), trade(83, "samefund", 50),
            trade(84, "future", 50), trade(85, "creator", 50),
            trade(90, "u1", 25, cluster="u1"), trade(92, "u2", 25, cluster="u2"),
        ]
        result = skilled_wallet_convergence(rows, 100, profiles)
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["skilled_clusters"], 2)
        self.assertGreaterEqual(result["unrelated_buyers_after_skilled_entry"], 2)

    def test_creator_quality_is_point_in_time_bonus_not_authority(self):
        good = creator_confirmation(
            dict(as_of=90, prior_launches=20, prior_graduations=4), 100
        )
        future = creator_confirmation(
            dict(as_of=101, prior_launches=100, prior_graduations=100), 100
        )
        self.assertTrue(good["confirmed"])
        self.assertFalse(future["history_valid"])
        result = evaluate_late_curve(
            curve_points=slow_curve(), events=curve_demand(), now=100,
            graduation_quote_target=1_000_000_000, concentration_bps=1800,
            creator_profile=dict(as_of=90, prior_launches=20, prior_graduations=10),
        )
        self.assertTrue(result["creator_confirmed"])
        self.assertFalse(result["eligible"])

    def test_quote_relative_strength_uses_actual_quote_ratio(self):
        rows = [
            trade(75, "a", 100, 100, cluster="a"),
            trade(82, "b", 105, 100, cluster="b"),
            trade(91, "c", 112, 100, cluster="c"),
            trade(94, "d", 116, 100, cluster="d"),
            trade(96, "e", 118, 100, cluster="e"),
            trade(98, "f", 120, 100, cluster="f"),
            trade(100, "g", 120, 100, cluster="g"),
        ]
        result = evaluate_late_curve(
            curve_points=fast_curve(), events=rows, now=100,
            graduation_quote_target=10_000, concentration_bps=1000,
            quote_asset="NVDAX",
        )
        self.assertEqual(result["quote_asset"], "NVDAX")
        self.assertEqual(
            result["features"]["demand"]["quote_relative_strength_bps"], 2000
        )

    def test_postgrad_continuation_requires_new_demand_and_low_distribution(self):
        rows = [
            trade(101, "old1", 20, 100), trade(102, "old2", 20, 100),
            trade(111, "a", 35, 100), trade(113, "b", 38, 100),
            trade(115, "c", 41, 100), trade(117, "d", 44, 100),
            trade(119, "e", 48, 100), trade(120, "f", 50, 100),
        ]
        result = evaluate_postgrad_continuation(
            events=rows, now=120, graduated_at=100,
            graduation_price=Fraction(30, 100),
            graduation_quote_target=1000, concentration_bps=1500,
        )
        self.assertTrue(result["eligible"], result["reasons"])
        self.assertGreaterEqual(
            result["features"]["price_vs_graduation_bps"], 0
        )

        dumped = rows + [
            trade(120, "early", 500, 100, buy=False, early_holder=True)
        ]
        bad = evaluate_postgrad_continuation(
            events=dumped, now=120, graduated_at=100,
            graduation_price=Fraction(30, 100),
            graduation_quote_target=1000, concentration_bps=1500,
        )
        self.assertFalse(bad["eligible"])
        self.assertIn("early_holder_distribution_too_high", bad["reasons"])

    def test_second_leg_rally_pullback_consolidation_breakout(self):
        rows = [
            trade(101, "r1", 120, 100), trade(105, "r2", 160, 100),
            trade(110, "r3", 200, 100), trade(116, "p1", 170, 100),
            trade(120, "p2", 150, 100), trade(126, "c1", 154, 100),
            trade(132, "c2", 156, 100), trade(138, "c3", 158, 100),
            trade(143, "c4", 160, 100),
            trade(146, "n1", 165, 100, cluster="n1"),
            trade(148, "n2", 168, 100, cluster="n2"),
            trade(149, "n3", 172, 100, cluster="n3"),
            trade(150, "n4", 175, 100, cluster="n4"),
        ]
        result = evaluate_second_leg(
            events=rows, now=150, graduated_at=100,
            graduation_quote_target=1000,
        )
        self.assertTrue(result["eligible"], result["reasons"])
        self.assertGreaterEqual(result["features"]["pullback_bps"], 1000)
        self.assertGreaterEqual(result["features"]["new_independent_buyers"], 3)

    def test_lifecycle_carries_only_after_postgrad_confirmation(self):
        curve = evaluate_late_curve(
            curve_points=fast_curve(), events=curve_demand(), now=100,
            graduation_quote_target=1_000_000_000, concentration_bps=1500,
        )
        life = PumpAlphaLifecycle()
        self.assertTrue(life.open_curve(curve, 100))
        self.assertTrue(life.graduate(105))
        hold = {
            "eligible": True,
            "entry_mode": "postgrad_continuation",
            "graduated_at": 105,
        }
        self.assertEqual(life.apply_postgrad(hold, 110), "hold")
        self.assertEqual(life.mode, "postgrad_carry")

        failed = PumpAlphaLifecycle()
        failed.open_curve(curve, 100)
        failed.graduate(105)
        self.assertEqual(
            failed.apply_postgrad({"eligible": False}, 121), "exit"
        )
        self.assertEqual(failed.mode, "exit_required")

    def test_aggressive_exit_on_stop_or_deceleration(self):
        rows = [
            trade(101, "a", 100, 100), trade(110, "b", 130, 100),
            trade(121, "s1", 100, 100, buy=False),
            trade(125, "s2", 90, 100, buy=False),
        ]
        decision = evaluate_exit(
            events=rows, now=125, entry_time=100,
            entry_price=Fraction(1, 1), graduation_quote_target=1000,
        )
        self.assertTrue(decision["exit"])
        self.assertTrue(
            set(decision["reasons"])
            & {"hard_stop", "trailing_drawdown", "net_demand_reversed"}
        )


if __name__ == "__main__":
    unittest.main()
