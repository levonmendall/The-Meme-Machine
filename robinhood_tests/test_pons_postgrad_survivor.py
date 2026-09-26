import unittest

from robinhood_research.pons_postgrad_survivor import (
    POLICY, STRATEGY_VERSION, evaluate_entry, exit_action, select_entries,
    trend_efficiency_bps,
)


NOW=1_000_000


def winner_points():
    # A survivor trends higher, resets ~14% from an earlier peak, builds a two-hour
    # base, then breaks out without a one-candle 20% chase.
    return [
        (NOW-30*60*60,10_000),
        (NOW-24*60*60,10_200),
        (NOW-12*60*60,12_000),
        (NOW-8*60*60,13_000),
        (NOW-6*60*60,11_600),
        (NOW-4*60*60,11_800),
        (NOW-2*60*60,11_300),
        (NOW-90*60,11_500),
        (NOW-30*60,11_700),
        (NOW-16*60,11_800),
        (NOW-5*60,12_600),
        (NOW,12_900),
    ]


def facts(**changes):
    d=dict(
        now=NOW,graduation_at=NOW-30*60*60,lineage_proven=True,native_quote=True,
        price_points=winner_points(),capital_quote=10**18,
        flow_30m=dict(
            buy_quote=10**17,sell_quote=5*10**16,
            buyer_groups=["0x"+f"{i:040x}" for i in range(1,8)],
            new_buyer_groups=["0x"+f"{i:040x}" for i in range(5,8)],
            largest_buyer_flow_bps=2500,creator_sell_quote=0,
        ),
        flow_previous_30m=dict(buy_quote=6*10**16),
        execution=dict(roundtrip_loss_bps=180,double_size_roundtrip_loss_bps=260),
    )
    d.update(changes);return d


class PonsPostgradSurvivorTests(unittest.TestCase):
    def test_open_market_style_survivor_breakout_qualifies(self):
        out=evaluate_entry(facts())
        self.assertTrue(out["candidate"],out["all_rejections"])
        self.assertEqual(out["strategy"],STRATEGY_VERSION)
        self.assertGreater(out["proposed_quote_amount"],0)

    def test_volume_alone_cannot_rescue_downtrend(self):
        points=[
            (NOW-30*60*60,20_000),(NOW-24*60*60,18_000),
            (NOW-8*60*60,14_000),(NOW-6*60*60,12_000),
            (NOW-2*60*60,9_000),(NOW-30*60,9_300),(NOW,10_000),
        ]
        out=evaluate_entry(facts(price_points=points))
        self.assertFalse(out["candidate"])
        self.assertTrue(any(x in out["all_rejections"] for x in (
            "weak_since_graduation","weak_long_trend","weak_6h_trend"
        )))

    def test_dead_cat_bounce_is_rejected_even_with_strong_recent_flow(self):
        points=[
            (NOW-30*60*60,20_000),(NOW-24*60*60,17_000),
            (NOW-8*60*60,11_000),(NOW-6*60*60,9_000),
            (NOW-2*60*60,7_000),(NOW-30*60,7_200),
            (NOW-16*60,7_300),(NOW,8_500),
        ]
        out=evaluate_entry(facts(price_points=points))
        self.assertFalse(out["candidate"])
        self.assertIn("weak_since_graduation",out["all_rejections"])

    def test_thin_market_and_concentrated_buyer_fail_closed(self):
        f=facts(
            flow_30m=dict(
                buy_quote=10**15,sell_quote=2*10**14,
                buyer_groups=["0x"+f"{i:040x}" for i in range(1,8)],
                new_buyer_groups=["0x"+f"{i:040x}" for i in range(5,8)],
                largest_buyer_flow_bps=5000,creator_sell_quote=0,
            ),
            execution=dict(roundtrip_loss_bps=500,double_size_roundtrip_loss_bps=900),
        )
        out=evaluate_entry(f)
        self.assertFalse(out["candidate"])
        self.assertIn("buyer_concentration",out["all_rejections"])
        self.assertIn("roundtrip_friction",out["all_rejections"])
        self.assertIn("stress_friction",out["all_rejections"])
        self.assertIn("insufficient_executable_capacity",out["all_rejections"])

    def test_creator_distribution_is_hard_reject(self):
        flow=dict(facts()["flow_30m"]);flow["creator_sell_quote"]=1
        out=evaluate_entry(facts(flow_30m=flow))
        self.assertFalse(out["candidate"])
        self.assertIn("creator_distribution",out["all_rejections"])

    def test_one_buyer_pump_is_not_independent_demand(self):
        flow=dict(facts()["flow_30m"])
        flow["buyer_groups"]=["0x"+"11"*20]
        flow["new_buyer_groups"]=["0x"+"11"*20]
        out=evaluate_entry(facts(flow_30m=flow))
        self.assertFalse(out["candidate"])
        self.assertIn("insufficient_buyer_breadth",out["all_rejections"])

    def test_late_vertical_extension_is_not_chased(self):
        pts=winner_points()[:-2]+[(NOW-5*60,14_500),(NOW,15_000)]
        out=evaluate_entry(facts(price_points=pts))
        self.assertFalse(out["candidate"])
        self.assertIn("late_extension",out["all_rejections"])

    def test_cross_sectional_selection_prefers_persistent_strength(self):
        a=facts()
        b=facts(price_points=[
            (at,price*(101 if i==len(winner_points())-1 else 100)//100)
            for i,(at,price) in enumerate(winner_points())
        ])
        selected,decisions=select_entries([a,b],open_positions=0)
        self.assertEqual(len(selected),2)
        self.assertTrue(all(x["candidate"] for x in decisions))

    def test_exit_hard_stop(self):
        self.assertEqual(
            exit_action(
                after_cost_return_bps=-1000,high_water_return_bps=0,
                hold_seconds=100,seconds_since_high=100,
                buy_quote_30m=1,sell_quote_30m=1,new_buyers_30m=1,
            )["reason"],"hard_stop"
        )

    def test_exit_trails_large_winner(self):
        self.assertEqual(
            exit_action(
                after_cost_return_bps=2400,high_water_return_bps=4000,
                hold_seconds=10_000,seconds_since_high=600,
                buy_quote_30m=2,sell_quote_30m=1,new_buyers_30m=1,
            )["reason"],"high_water_trailing_stop"
        )

    def test_soft_demand_failure_requires_confirmation(self):
        first=exit_action(
            after_cost_return_bps=500,high_water_return_bps=1000,
            hold_seconds=1000,seconds_since_high=1000,
            buy_quote_30m=7,sell_quote_30m=10,new_buyers_30m=0,
            deterioration_streak=1,
        )
        second=exit_action(
            after_cost_return_bps=500,high_water_return_bps=1000,
            hold_seconds=1000,seconds_since_high=1000,
            buy_quote_30m=7,sell_quote_30m=10,new_buyers_30m=0,
            deterioration_streak=2,
        )
        self.assertEqual(first["action"],"hold")
        self.assertEqual(second["reason"],"persistent_demand_failure")

    def test_strategy_has_no_pregrad_import_dependency(self):
        import inspect
        import robinhood_research.pons_postgrad_survivor as module
        source=inspect.getsource(module)
        self.assertNotIn("pons_selective_continuation",source)
        self.assertNotIn("pons_opportunity_research",source)

    def test_efficiency_penalizes_chop(self):
        self.assertGreater(
            trend_efficiency_bps([100,110,120,130]),
            trend_efficiency_bps([100,130,90,130]),
        )


if __name__=="__main__":
    unittest.main()
