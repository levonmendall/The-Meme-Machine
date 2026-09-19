import base64
import struct
import unittest

from meme_machine import pump
from meme_machine.postgrad import PUMPSWAP_PROGRAM
from meme_machine.pump_acceleration_evidence import (
    PUMPSWAP_BUY_EVENT,curve_progress_bps,early_holder_sell_share_bps,
    late_curve_trajectory,postgrad_volume_acceleration_bps,price_return_bps,
    pumpswap_trade_events,reserve_price_parts,second_leg_shape,
)


def pk(byte):
    return bytes([byte])*32


class CurveEvidenceTests(unittest.TestCase):
    def test_progress_is_exact_reserve_depletion(self):
        self.assertEqual(curve_progress_bps(1_000,300),7000)
        self.assertEqual(curve_progress_bps(1_000,0),10_000)
        with self.assertRaises(ValueError):
            curve_progress_bps(1_000,1_001)

    def test_price_return(self):
        self.assertEqual(price_return_bps(100,10,120,10),2000)

    def test_late_trajectory_uses_recent_states_but_absolute_creation_progress(self):
        creation={"initial_real_token_reserves":1_000}
        events=[
            dict(market_time=80,real_token_reserves=700,virtual_quote_reserves=100,
                 virtual_token_reserves=100,slot=1,index=0),
            dict(market_time=90,real_token_reserves=500,virtual_quote_reserves=120,
                 virtual_token_reserves=100,slot=2,index=0),
        ]
        curve=type("C",(),{"real_token":200,"sol":150,"token":100})()
        out=late_curve_trajectory(creation,events,curve,100)
        self.assertEqual(out["curve_progress_bps"],8000)
        self.assertGreater(out["curve_velocity_bps_per_s"],0)
        self.assertEqual(out["extension_bps"],2500)


class PumpSwapEvidenceTests(unittest.TestCase):
    def _event_raw(self):
        raw=bytearray(PUMPSWAP_BUY_EVENT)
        raw+=struct.pack("<q",100)
        for value in (50,60,10,20,1_000,500,55,30,2,40,3,57,58):
            raw+=struct.pack("<Q",value)
        raw+=pk(7)+pk(8)
        return bytes(raw)

    def test_decode_buy_event(self):
        raw=self._event_raw()
        log="Program data: "+base64.b64encode(raw).decode()
        tx={"slot":9,"meta":{"err":None,"logMessages":[
            f"Program {PUMPSWAP_PROGRAM} invoke [1]",log,
            f"Program {PUMPSWAP_PROGRAM} success",
        ]}}
        rows=pumpswap_trade_events(tx)
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]["buy"])
        self.assertEqual(rows[0]["pool_base_reserve"],1_000)
        self.assertEqual(rows[0]["pool_quote_reserve"],500)
        self.assertEqual(rows[0]["pool"],pump.b58(pk(7)))
        self.assertEqual(rows[0]["wallet"],pump.b58(pk(8)))

    def test_volume_and_early_sell_metrics(self):
        rows=[
            dict(market_time=75,amount=100,buy=True,wallet="a"),
            dict(market_time=95,amount=200,buy=True,wallet="b"),
            dict(market_time=96,amount=50,buy=False,wallet="early"),
            dict(market_time=97,amount=50,buy=False,wallet="late"),
        ]
        self.assertGreater(postgrad_volume_acceleration_bps(rows,100),0)
        self.assertEqual(early_holder_sell_share_bps(rows,{"early"}),5000)

    def test_second_leg_shape(self):
        rows=[
            dict(market_time=100,pool_base_reserve=100,pool_quote_reserve=100),
            dict(market_time=110,pool_base_reserve=100,pool_quote_reserve=150),
            dict(market_time=125,pool_base_reserve=100,pool_quote_reserve=120),
            dict(market_time=140,pool_base_reserve=100,pool_quote_reserve=122),
            dict(market_time=150,pool_base_reserve=100,pool_quote_reserve=123),
        ]
        shape=second_leg_shape(rows,100,160,reserve_price_parts(100,135))
        self.assertGreater(shape["pullback_depth_bps"],0)
        self.assertGreater(shape["recovery_bps"],0)
        self.assertGreater(shape["breakout_bps"],0)
        self.assertGreaterEqual(shape["consolidation_seconds"],20)


if __name__=="__main__":
    unittest.main()
