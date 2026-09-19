import struct
import unittest

from tests import dlmm_profitable_operator_reconstruction as rec


class ProfitableOperatorReconstructionTests(unittest.TestCase):
    def test_decode_strategy2_preserves_frozen_strategy_semantics(self):
        raw=bytearray(105)
        raw[:8]=rec.STRATEGY2
        struct.pack_into("<QQ",raw,8,1_000,2_000)
        struct.pack_into("<iiii",raw,24,100,3,90,120)
        raw[40]=4  # CurveBalanced
        out=rec.decode_strategy2(bytes(raw))
        self.assertEqual(out["amount_x"],1_000)
        self.assertEqual(out["amount_y"],2_000)
        self.assertEqual(out["observed_active_bin"],100)
        self.assertEqual(out["lower_bin_id"],90)
        self.assertEqual(out["upper_bin_id"],120)
        self.assertEqual(out["width_bins"],31)
        self.assertEqual(out["strategy_type"],"curve_balanced")
        self.assertEqual(out["strategy_family"],"curve")
        self.assertTrue(out["two_sided"])
        self.assertFalse(out["one_sided"])

    def test_decode_add2_and_distribution_shape(self):
        rows=[(98,1000,0),(99,3000,0),(100,6000,0)]
        raw=bytearray(28+8*len(rows)+4)
        raw[:8]=rec.ADD2
        struct.pack_into("<QQI",raw,8,10_000,0,len(rows))
        offset=28
        for row in rows:
            struct.pack_into("<iHH",raw,offset,*row);offset+=8
        struct.pack_into("<I",raw,offset,0)
        out=rec.decode_add2(bytes(raw))
        self.assertEqual(out["lower_bin_id"],98)
        self.assertEqual(out["upper_bin_id"],100)
        self.assertEqual(out["width_bins"],3)
        self.assertTrue(out["one_sided"])
        self.assertEqual(
            rec.classify_distribution(out["distributions"],100),"bid_ask_like"
        )

    def test_decode_remove_range2_and_rebalance(self):
        remove=bytearray(18);remove[:8]=rec.REMOVE_RANGE2
        struct.pack_into("<iiH",remove,8,80,120,10000)
        r=rec.decode_remove_range2(bytes(remove))
        self.assertEqual((r["lower_bin_id"],r["upper_bin_id"],r["bps"]),(80,120,10000))

        reb=bytearray(80);reb[:8]=rec.REBALANCE
        struct.pack_into("<iH??QQQQB",reb,8,101,2,True,False,1,2,3,4,1)
        x=rec.decode_rebalance(bytes(reb))
        self.assertEqual(x["observed_active_bin"],101)
        self.assertEqual(x["max_active_bin_slippage"],2)
        self.assertTrue(x["should_claim_fee"])
        self.assertFalse(x["should_claim_reward"])
        self.assertEqual(x["max_deposit_y_amount"],4)
        self.assertEqual(x["shrink_mode"],1)

    def test_exact_capital_rejects_partial_remove_instead_of_imputing(self):
        position={"lower_bin_id":90,"upper_bin_id":110}
        history=[
            {"event_type":"add","block_time":100,"signature":"a","total_usd":100},
            {"event_type":"remove","block_time":200,"signature":"b","total_usd":50},
        ]
        features={
            "a":{"actions":[{"action":"add_liquidity2"}]},
            "b":{"actions":[{
                "action":"remove_liquidity_by_range2",
                "instruction":"remove_liquidity_by_range2",
                "lower_bin_id":90,"upper_bin_id":100,"bps":5000,
            }]},
        }
        out=rec.exact_position_capital(position,history,features)
        self.assertFalse(out["exact"])
        self.assertEqual(out["reason"],"partial_remove_requires_bin_basis")

    def test_exact_capital_accepts_recycled_full_close_without_double_counting(self):
        position={"lower_bin_id":90,"upper_bin_id":110}
        history=[
            {"event_type":"add","block_time":100,"signature":"a","total_usd":100},
            {"event_type":"remove","block_time":3700,"signature":"b","total_usd":115},
        ]
        features={
            "a":{"actions":[{"action":"add_liquidity2"}]},
            "b":{"actions":[{
                "action":"remove_liquidity_by_range2",
                "instruction":"remove_liquidity_by_range2",
                "lower_bin_id":90,"upper_bin_id":110,"bps":10000,
            }]},
        }
        out=rec.exact_position_capital(position,history,features)
        self.assertTrue(out["exact"])
        self.assertAlmostEqual(out["capital_hours_usd"],100.0)

    def test_shared_external_fee_payer_merges_wallets_but_self_payer_does_not(self):
        rows=[
            {"wallet":"a","fee_payers":["fleet"]},
            {"wallet":"b","fee_payers":["fleet"]},
            {"wallet":"c","fee_payers":["c"]},
        ]
        clusters=rec.cluster_fleets(rows)
        members=sorted(sorted(x["wallets"]) for x in clusters)
        self.assertEqual(members,[["a","b"],["c"]])

    def test_sol_price_requires_direct_plausible_wsol_usd_pair(self):
        event=dict(
            token_x=rec.dlmm.WSOL,amount_x="1000000000",amount_x_usd=150.0,
            token_y="other",amount_y="1",amount_y_usd=1.0,
        )
        self.assertAlmostEqual(rec.infer_event_sol_price(event),150.0)
        self.assertIsNone(rec.infer_event_sol_price({
            "token_x":"other","amount_x":"1","amount_x_usd":1
        }))


if __name__=="__main__":
    unittest.main()
