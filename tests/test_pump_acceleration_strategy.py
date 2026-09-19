import unittest

from meme_machine.pump_acceleration_strategy import (
    CreatorQualityRecord,
    MODE_LATE_CURVE,
    MODE_POSTGRAD,
    MODE_SECOND_LEG,
    POLICY,
    SignalVector,
    WalletSkillRecord,
    creator_confirmation,
    flow_metrics,
    policy_hash,
    qualify,
    relative_return_bps,
    skilled_wallet_convergence,
    trajectory_metrics,
)


class PumpAccelerationStrategyTests(unittest.TestCase):
    def strong_late(self, **updates):
        row=dict(
            mint="MINT",
            observed_at=1_000,
            surface="pump.fun",
            phase=MODE_LATE_CURVE,
            curve_progress_bps=8200,
            curve_velocity_bps_per_s=80,
            curve_acceleration_bps_per_s2=5,
            independent_buyer_clusters=5,
            buyer_growth=3,
            net_buy_share_bps=8500,
            concentration_bps=1800,
            extension_bps=2500,
            skilled_wallet_clusters=2,
            creator_quality_bps=7000,
            creator_history_launches=10,
            quote_relative_return_bps=800,
        )
        row.update(updates)
        return SignalVector(**row)

    def test_fast_and_slow_same_curve_location_are_distinct(self):
        fast=trajectory_metrics([(0,3000),(10,4500),(20,6300),(30,8200)])
        slow=trajectory_metrics([(0,7500),(60,7700),(120,7900),(180,8200)])
        self.assertEqual(fast["curve_progress_bps"],slow["curve_progress_bps"])
        self.assertGreater(fast["curve_velocity_bps_per_s"],slow["curve_velocity_bps_per_s"])

    def test_curve_position_alone_is_not_enough(self):
        result=qualify(self.strong_late(
            curve_velocity_bps_per_s=0,
            buyer_growth=0,
            net_buy_share_bps=5000,
            independent_buyer_clusters=1,
        ))
        self.assertFalse(result.qualified)
        self.assertIn("curve_velocity",result.reasons)
        self.assertIn("independent_buyers",result.reasons)

    def test_strong_late_curve_can_qualify(self):
        result=qualify(self.strong_late())
        self.assertTrue(result.qualified,result.reasons)
        self.assertIn("skilled_wallet_convergence",result.confirmations)
        self.assertIn("creator_quality",result.confirmations)
        self.assertEqual(result.policy_hash,policy_hash())

    def test_creator_quality_cannot_override_weak_trajectory(self):
        result=qualify(self.strong_late(
            curve_velocity_bps_per_s=1,
            curve_acceleration_bps_per_s2=-5,
            buyer_growth=-1,
            creator_quality_bps=10_000,
        ))
        self.assertFalse(result.qualified)
        self.assertIn("curve_velocity",result.reasons)

    def test_skilled_wallet_convergence_is_point_in_time_and_funding_independent(self):
        rows=[
            WalletSkillRecord("a",900,10,8,2000,"fund-1"),
            WalletSkillRecord("b",900,20,14,3000,"fund-1"),
            WalletSkillRecord("c",900,10,7,1000,"fund-2"),
            WalletSkillRecord("future",1100,100,100,9999,"fund-3"),
            WalletSkillRecord("creator-linked",900,100,100,9999,"fund-4",True),
        ]
        self.assertEqual(skilled_wallet_convergence(rows,1000),2)

    def test_creator_history_after_observation_is_ignored(self):
        future=CreatorQualityRecord("creator",1001,20,20)
        self.assertIsNone(creator_confirmation(future,1000))
        current=CreatorQualityRecord("creator",999,10,7)
        self.assertEqual(creator_confirmation(current,1000),7000)

    def test_flow_metrics_excludes_related_clusters(self):
        events=[
            dict(wallet="w1",market_time=995,amount=100,buy=True),
            dict(wallet="w2",market_time=996,amount=100,buy=True),
            dict(wallet="creator",market_time=997,amount=900,buy=True),
            dict(wallet="s1",market_time=998,amount=50,buy=False),
        ]
        result=flow_metrics(events,1000,cluster_map={"creator":"related"},excluded_clusters={"related"})
        self.assertEqual(result["independent_buyer_clusters"],2)
        self.assertEqual(result["gross_buy"],200)
        self.assertEqual(result["gross_sell"],50)

    def test_postgrad_requires_graduation_and_new_demand(self):
        strong=SignalVector(
            mint="M",observed_at=1000,surface="pumpswap",phase=MODE_POSTGRAD,
            graduated=True,seconds_since_graduation=25,independent_buyer_clusters=6,
            buyer_growth=3,net_buy_share_bps=8500,concentration_bps=1600,
            price_vs_graduation_bps=1400,volume_acceleration_bps=3000,
            early_holder_sell_share_bps=1200,recovery_bps=1000,
            skilled_wallet_clusters=2,quote_relative_return_bps=500,
        )
        self.assertTrue(qualify(strong).qualified,qualify(strong).reasons)
        weak=SignalVector(**{**strong.__dict__,"graduated":False})
        self.assertFalse(qualify(weak).qualified)

    def test_second_leg_requires_pullback_consolidation_and_breakout(self):
        strong=SignalVector(
            mint="M",observed_at=1000,surface="pumpswap",phase=MODE_SECOND_LEG,
            graduated=True,seconds_since_graduation=120,independent_buyer_clusters=6,
            buyer_growth=3,net_buy_share_bps=8500,concentration_bps=1700,
            early_holder_sell_share_bps=1000,pullback_depth_bps=1200,
            recovery_bps=1600,consolidation_seconds=45,breakout_bps=1500,
            price_vs_graduation_bps=1800,skilled_wallet_clusters=2,
            quote_relative_return_bps=800,
        )
        self.assertTrue(qualify(strong).qualified,qualify(strong).reasons)
        weak=SignalVector(**{**strong.__dict__,"breakout_bps":100})
        self.assertFalse(qualify(weak).qualified)
        self.assertIn("breakout",qualify(weak).reasons)

    def test_relative_strength_removes_quote_asset_move(self):
        # token/USD +29.6%, quote/USD +8% => token/quote exactly +20%
        self.assertEqual(relative_return_bps(2960,800),2000)

    def test_non_sol_quote_is_strategy_supported(self):
        result=qualify(self.strong_late(quote_asset="NVDAX"))
        self.assertTrue(result.qualified)
        # Execution support is deliberately a separate adapter concern.

    def test_future_data_fails_closed(self):
        with self.assertRaises(ValueError):
            qualify(self.strong_late(future_data_used=True))


if __name__ == "__main__":
    unittest.main()
