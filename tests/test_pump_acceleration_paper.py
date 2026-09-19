import unittest

from meme_machine.pump_acceleration_paper import PumpAccelerationPaperLifecycle
from meme_machine.pump_acceleration_strategy import (
    MODE_LATE_CURVE,
    Qualification,
    STRATEGY_ID,
    policy_hash,
)


def qualification(strategy_id=STRATEGY_ID, qualified=True):
    return Qualification(
        strategy_id=strategy_id,
        mode=MODE_LATE_CURVE,
        mint="MINT",
        observed_at=100,
        qualified=qualified,
        score=90,
        reasons=(),
        confirmations=(),
        entry_fraction_bps=500,
        policy_hash=policy_hash(),
    )


class PumpAccelerationPaperLifecycleTests(unittest.TestCase):
    def test_rejects_other_strategy_authority(self):
        life=PumpAccelerationPaperLifecycle()
        with self.assertRaises(ValueError):
            life.reserve(qualification("continuation-v1"),1000,100)

    def test_rejects_unqualified_signal(self):
        life=PumpAccelerationPaperLifecycle()
        with self.assertRaises(ValueError):
            life.reserve(qualification(qualified=False),1000,100)

    def test_late_curve_can_carry_only_through_authenticated_graduation(self):
        life=PumpAccelerationPaperLifecycle()
        life.reserve(qualification(),1000,100)
        life.fill(tokens=100,cost_quote_units=900,now=102,surface="pump.fun")
        with self.assertRaises(ValueError):
            life.authenticate_graduation(now=120,authenticated=False)
        state=life.authenticate_graduation(now=120,authenticated=True)
        self.assertEqual(state["surface"],"pumpswap")
        self.assertTrue(state["graduation_authenticated"])

    def test_trailing_exit_and_settlement_are_strategy_local(self):
        life=PumpAccelerationPaperLifecycle()
        life.reserve(qualification(),1000,100)
        life.fill(tokens=100,cost_quote_units=1000,now=102,surface="pump.fun")
        first=life.mark(1300,now=110,demand_score=80)
        self.assertIsNone(first["exit_reason"])
        second=life.mark(1150,now=120,demand_score=80)
        self.assertEqual(second["exit_reason"],"trailing_momentum_exit")
        closed=life.settle(1140,now=122)
        self.assertEqual(closed["realized_quote_units"],140)
        self.assertIsNone(life.snapshot()["position"])

    def test_low_demand_exits_without_touching_other_strategy_state(self):
        life=PumpAccelerationPaperLifecycle()
        life.reserve(qualification(),1000,100)
        life.fill(tokens=100,cost_quote_units=1000,now=102,surface="pump.fun")
        mark=life.mark(1010,now=110,demand_score=30)
        self.assertEqual(mark["exit_reason"],"demand_deceleration")
        snap=life.snapshot()
        self.assertEqual(snap["strategy_id"],STRATEGY_ID)
        self.assertFalse(snap["capital_authority"])


if __name__ == "__main__":
    unittest.main()
