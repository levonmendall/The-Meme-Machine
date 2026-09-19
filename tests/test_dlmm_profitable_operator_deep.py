import unittest
from unittest.mock import patch

from tests import dlmm_profitable_operator_deep as deep
from tests import dlmm_profitable_operator_reconstruction as rec


class ProfitableOperatorDeepTests(unittest.TestCase):
    def test_network_fee_is_counted_once_and_priced_from_direct_wsol_event(self):
        wallet={
            "histories":{
                "p":[{
                    "signature":"s","block_time":100,"pool":"pool",
                    "token_x":rec.dlmm.WSOL,"amount_x":"1000000000",
                    "amount_x_usd":150.0,"token_y":"other",
                    "amount_y":"0","amount_y_usd":0,
                }]
            }
        }
        out=deep._network_costs(wallet,{"s":{"fee_lamports":5000}})
        self.assertEqual(out["total_fee_lamports"],5000)
        self.assertTrue(out["fee_usd_complete"])
        self.assertAlmostEqual(out["total_fee_usd"],5000/1e9*150)
        self.assertAlmostEqual(out["position_cost_usd"]["p"],out["total_fee_usd"])

    def test_multi_position_transaction_keeps_wallet_cost_exact_but_twr_allocation_unavailable(self):
        event=lambda p:{
            "signature":"s","block_time":100,"pool":"pool",
            "token_x":rec.dlmm.WSOL,"amount_x":"1000000000",
            "amount_x_usd":150.0,"token_y":"other",
            "amount_y":"0","amount_y_usd":0,
        }
        wallet={"histories":{"a":[event("a")],"b":[event("b")]}}
        out=deep._network_costs(wallet,{"s":{"fee_lamports":5000}})
        self.assertTrue(out["fee_usd_complete"])
        self.assertIsNone(out["position_cost_usd"]["a"])
        self.assertIsNone(out["position_cost_usd"]["b"])
        self.assertEqual(out["position_cost_ambiguous_signatures"],["s"])

    def test_market_context_uses_historical_windows_and_never_current_fee_tvl(self):
        def api(path,params=None):
            if path=="/pools/p":
                return {"created_at":100}
            if path.endswith("/ohlcv"):
                return {"data":[
                    {"close":100.0},{"close":101.0},{"close":99.0}
                ]}
            if path.endswith("/volume/history"):
                return {"data":[
                    {"volume":10.0,"fees":1.0},{"volume":20.0,"fees":2.0}
                ]}
            raise AssertionError(path)
        with patch.object(deep.op,"_api",side_effect=api):
            out=deep._market_context("p",3700,{}, {})
        self.assertEqual(out["pool_age_seconds"],3600)
        self.assertEqual(out["pre_entry_60m_volume_usd"],30.0)
        self.assertEqual(out["pre_entry_60m_fees_usd"],3.0)
        self.assertIsNotNone(out["pre_entry_5m_log_return_volatility"])
        self.assertIsNone(out["fee_tvl_at_entry"])
        self.assertEqual(
            out["fee_tvl_at_entry_reason"],
            "historical_tvl_not_exposed_by_meteora_data_api")

    def test_final_rankings_are_metric_specific(self):
        rows=[
            {"wallet":"a","after_network_cost_pnl_usd":10.0,
             "after_cost_pnl_per_capital_hour":0.1,
             "exact_time_weighted_return":{"available":True,"twr":0.2},
             "profitable_position_rate":0.6,
             "max_after_cost_realized_drawdown_usd":5.0,
             "profitable_after_cost_active_week_rate":0.7},
            {"wallet":"b","after_network_cost_pnl_usd":9.0,
             "after_cost_pnl_per_capital_hour":0.2,
             "exact_time_weighted_return":{"available":True,"twr":0.1},
             "profitable_position_rate":0.8,
             "max_after_cost_realized_drawdown_usd":2.0,
             "profitable_after_cost_active_week_rate":0.5},
        ]
        ranks=deep._rank(rows)
        self.assertEqual(ranks["absolute_after_network_cost_pnl_usd"][0]["wallet"],"a")
        self.assertEqual(ranks["after_cost_pnl_per_capital_hour"][0]["wallet"],"b")
        self.assertEqual(ranks["exact_time_weighted_return"][0]["wallet"],"a")
        self.assertEqual(ranks["profitable_position_rate"][0]["wallet"],"b")
        self.assertEqual(ranks["max_after_cost_realized_drawdown_usd"][0]["wallet"],"b")


if __name__=="__main__":
    unittest.main()
