import unittest

from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
from meme_machine.lanes.pump.pump_acceleration_strategy import (
    MODE_LATE_CURVE, POLICY, Qualification, STRATEGY_ID, policy_hash,
)
from meme_machine.lanes.pump import runner as runner


class PumpCampaignTailDrainTests(unittest.TestCase):
    def test_final_second_entry_survives_900_seconds_and_only_a_real_stop_settles(self):
        discovery_end=10_000
        opened_at=discovery_end-1
        q=Qualification(
            strategy_id=STRATEGY_ID,
            mode=MODE_LATE_CURVE,
            mint='tail-entry',
            observed_at=opened_at-2,
            qualified=True,
            score=100,
            reasons=(),
            confirmations=(),
            entry_fraction_bps=POLICY.entry_fraction_bps,
            policy_hash=policy_hash(),
        )
        life=PumpAccelerationPaperLifecycle()
        life.reserve(q,2_000,opened_at-2)
        life.fill(tokens=100,cost_quote_units=1_000,now=opened_at,surface='pump.fun')

        timeout_at=opened_at+POLICY.late_curve_max_hold_s
        campaign_drain_end=discovery_end+runner.FOLLOWUP_SECONDS
        self.assertEqual(POLICY.late_curve_max_hold_s,900)
        self.assertGreaterEqual(runner.FOLLOWUP_SECONDS,1_000)
        self.assertLessEqual(timeout_at,campaign_drain_end)

        mark=life.mark(
            executable_proceeds_quote_units=1_000,
            now=timeout_at,
            demand_score=POLICY.demand_exit_score,
        )
        self.assertIsNone(mark['exit_reason'])
        with self.assertRaisesRegex(ValueError,'exit_not_intended'):life.settle(1_000,timeout_at)
        self.assertEqual(life.mark(800,timeout_at+5,demand_score=80)['exit_reason'],'risk_stop')
        closed=life.settle(800,timeout_at+5)
        self.assertEqual(closed['opened_at'],opened_at)
        self.assertEqual(closed['closed_at']-closed['opened_at'],905)
        self.assertIsNone(life.position)


if __name__=='__main__':
    unittest.main()
