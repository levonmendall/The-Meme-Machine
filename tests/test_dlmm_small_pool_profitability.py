import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine import dlmm
from tests import dlmm_small_pool_profitability as study


class SmallPoolProfitabilityTests(unittest.TestCase):
    def test_tvl_bucket_boundaries_are_preregistered(self):
        self.assertEqual(study._bucket(0,study.TVL_BUCKETS),"<10k")
        self.assertEqual(study._bucket(9999.99,study.TVL_BUCKETS),"<10k")
        self.assertEqual(study._bucket(10000,study.TVL_BUCKETS),"10-25k")
        self.assertEqual(study._bucket(25000,study.TVL_BUCKETS),"25-50k")
        self.assertEqual(study._bucket(50000,study.TVL_BUCKETS),">=50k")

    def test_reserve_prebalances_require_both_exact_vaults(self):
        resolver=study.EntryContextResolver()
        identity=dict(x="x",y="y",vault_x="vx",vault_y="vy")
        tx=dict(
            slot=10,blockTime=100,
            transaction=dict(message=dict(accountKeys=["payer","vx","vy"])),
            meta=dict(
                loadedAddresses=dict(writable=[],readonly=[]),
                preTokenBalances=[
                    dict(accountIndex=1,mint="x",
                         uiTokenAmount=dict(amount="1230000",decimals=6)),
                    dict(accountIndex=2,mint="y",
                         uiTokenAmount=dict(amount="4000000000",decimals=9)),
                ],
            ),
        )
        out=resolver.reserve_balances(tx,identity)
        self.assertAlmostEqual(out["x_amount"],1.23)
        self.assertAlmostEqual(out["y_amount"],4.0)
        tx["meta"]["preTokenBalances"]=tx["meta"]["preTokenBalances"][:1]
        self.assertIsNone(resolver.reserve_balances(tx,identity))

    def test_price_inference_uses_sol_plausibility_and_ohlcv_ratio(self):
        resolver=study.EntryContextResolver()
        with patch.object(resolver,"_candles",return_value=[(900,2.0)]):
            prices,reason=resolver.prices(
                dict(
                    token_x=dlmm.WSOL,token_y="token",
                    amount_x="1000000000",amount_x_usd=200,
                    amount_y="0",amount_y_usd=0,
                ),
                dict(
                    token_x=dict(address=dlmm.WSOL,decimals=9),
                    token_y=dict(address="token",decimals=6),
                ),
                dict(x_decimals=9,y_decimals=6),
                "pool",1000,
            )
        self.assertIsNone(reason)
        self.assertAlmostEqual(prices["x_usd"],200.0)
        self.assertAlmostEqual(prices["y_usd"],100.0)
        self.assertEqual(prices["source"],"event_x_plus_ohlcv")

    def test_aggregate_keeps_small_pool_profit_separate(self):
        rows=[
            dict(wallet="a",positions=[
                dict(tvl_bucket="<10k",entry_tvl=dict(available=True),
                     pool_age_bucket="<1h",volatility_bucket=">=10pct",
                     deposit_usd=100,realized_pnl_usd=20,
                     after_network_cost_position_pnl_usd=19,
                     fee_income_usd=15,inventory_token_price_pnl_usd=5,pnl_pct=20),
                dict(tvl_bucket=">=50k",entry_tvl=dict(available=True),
                     pool_age_bucket=">=7d",volatility_bucket="<1pct",
                     deposit_usd=200,realized_pnl_usd=-5,
                     after_network_cost_position_pnl_usd=-6,
                     fee_income_usd=2,inventory_token_price_pnl_usd=-7,pnl_pct=-2.5),
            ]),
            dict(wallet="b",positions=[
                dict(tvl_bucket="<10k",entry_tvl=dict(available=True),
                     pool_age_bucket="1-6h",volatility_bucket="3-10pct",
                     deposit_usd=50,realized_pnl_usd=10,
                     after_network_cost_position_pnl_usd=None,
                     fee_income_usd=7,inventory_token_price_pnl_usd=3,pnl_pct=20),
            ]),
        ]
        by_tvl,cross,missing=study._aggregate(rows)
        self.assertEqual(by_tvl["<10k"]["position_count"],2)
        self.assertEqual(by_tvl["<10k"]["distinct_operator_count"],2)
        self.assertAlmostEqual(by_tvl["<10k"]["realized_pnl_usd"],30)
        self.assertAlmostEqual(by_tvl["<10k"]["pnl_per_deployed_dollar"],0.2)
        self.assertEqual(by_tvl[">=50k"]["position_count"],1)
        self.assertEqual(missing,{})
        self.assertEqual(len(cross),3)

    def test_protocol_keeps_50k_execution_gate_unchanged(self):
        body=json.loads(study.PROTOCOL.read_text())
        self.assertFalse(body["authority"]["current_50000_tvl_execution_gate_changed"])
        self.assertTrue(body["entry_context"]["no_current_tvl_substitution"])
        self.assertEqual(
            [x["label"] for x in body["tvl_strata"]],
            ["<10k","10-25k","25-50k",">=50k"],
        )
        self.assertEqual(body["revision"],"1.2")
        self.assertFalse(body["execution"]["depends_on_profitable_operator_deep_artifact"])


if __name__=="__main__":
    unittest.main()
