import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import dlmm_profitable_operator_discovery as op


class ProfitableOperatorDiscoveryTests(unittest.TestCase):
    def test_pool_census_exhausts_all_pages_and_keeps_all_eligible_sol_pairs(self):
        def fake(path,params=None,allow_pnl=False):
            self.assertEqual(path,"/pools")
            page=params["page"]
            if page==1:
                return {"pages":2,"data":[
                    {"address":"p2","name":"B","is_blacklisted":False,"tvl":60000,
                     "volume":{"24h":30000},"token_x":{"address":op.WSOL,"symbol":"SOL"},
                     "token_y":{"address":"m2","symbol":"B"},"fees":{},"fee_tvl_ratio":{}},
                    {"address":"skip","name":"X","is_blacklisted":False,"tvl":60000,
                     "volume":{"24h":30000},"token_x":{"address":"a","symbol":"A"},
                     "token_y":{"address":"b","symbol":"B"},"fees":{},"fee_tvl_ratio":{}},
                ]}
            if page==2:
                return {"pages":2,"data":[
                    {"address":"p1","name":"A","is_blacklisted":False,"tvl":70000,
                     "volume":{"24h":40000},"token_x":{"address":"m1","symbol":"A"},
                     "token_y":{"address":op.WSOL,"symbol":"SOL"},"fees":{},"fee_tvl_ratio":{}},
                ]}
            raise AssertionError(page)
        with patch.object(op.legacy,"_json_get",side_effect=fake):
            pools=op.census_pools()
        self.assertEqual([p["address"] for p in pools],["p1","p2"])

    def test_capital_timeline_does_not_double_count_recycled_capital(self):
        positions=[
            {"position":"a","closed_at":3600},
            {"position":"b","closed_at":7200},
        ]
        histories={
            "a":[{"event_type":"add","block_time":0,"slot":1,"ix_index":0,"total_usd":100},
                 {"event_type":"remove","block_time":3600,"slot":2,"ix_index":0,"total_usd":100}],
            "b":[{"event_type":"add","block_time":3600,"slot":3,"ix_index":0,"total_usd":100},
                 {"event_type":"remove","block_time":7200,"slot":4,"ix_index":0,"total_usd":100}],
        }
        # Use positive Unix timestamps because zero is intentionally rejected.
        for rows in histories.values():
            for row in rows:
                row["block_time"]+=100
        positions[0]["closed_at"]+=100;positions[1]["closed_at"]+=100
        out=op._capital_timeline(positions,histories)
        self.assertAlmostEqual(out["capital_hours_usd"],200.0)
        self.assertAlmostEqual(out["peak_concurrent_contributed_capital_usd"],100.0)
        self.assertAlmostEqual(out["residual_contributed_capital_usd"],0.0)

    def test_capital_timeline_sums_overlapping_exposure(self):
        positions=[{"position":"a","closed_at":3700},{"position":"b","closed_at":3700}]
        histories={
            "a":[{"event_type":"add","block_time":100,"slot":1,"ix_index":0,"total_usd":100},
                 {"event_type":"remove","block_time":3700,"slot":2,"ix_index":0,"total_usd":100}],
            "b":[{"event_type":"add","block_time":100,"slot":3,"ix_index":0,"total_usd":100},
                 {"event_type":"remove","block_time":3700,"slot":4,"ix_index":0,"total_usd":100}],
        }
        out=op._capital_timeline(positions,histories)
        self.assertAlmostEqual(out["capital_hours_usd"],200.0)
        self.assertAlmostEqual(out["peak_concurrent_contributed_capital_usd"],200.0)

    def test_realized_path_metrics_are_chronological(self):
        rows=[
            {"closed_at":200,"position":"b","pnl_usd":-4},
            {"closed_at":100,"position":"a","pnl_usd":10},
            {"closed_at":300,"position":"c","pnl_usd":2},
        ]
        out=op._realized_path_metrics(rows)
        self.assertAlmostEqual(out["profitable_position_rate"],2/3)
        self.assertAlmostEqual(out["max_realized_drawdown_usd"],4.0)
        self.assertEqual(out["active_weeks"],1)

    def test_current_liquidity_management_surface_is_in_operator_census(self):
        names={spec[0] for spec in op.LP_MUTATIONS.values()}
        for required in (
            "add_liquidity","add_liquidity2","add_liquidity_by_strategy",
            "add_liquidity_by_strategy2","add_liquidity_by_strategy_one_side",
            "add_liquidity_by_weight","add_liquidity_by_weight2",
            "add_liquidity_one_side","add_liquidity_one_side_precise",
            "add_liquidity_one_side_precise2","rebalance_liquidity",
            "remove_all_liquidity","remove_liquidity","remove_liquidity2",
            "remove_liquidity_by_range","remove_liquidity_by_range2",
            "claim_fee","claim_fee2",
        ):
            self.assertIn(required,names)

    def test_protocol_freezes_all_pool_census_and_no_wallet_cap(self):
        body=json.loads(op.PROTOCOL.read_text())
        self.assertIn("exhaust every observable",body["universe"]["pool_census"])
        self.assertIn("no per-pool wallet cap",body["lp_activity_census"]["wallet_selection"])
        self.assertEqual(body["execution"]["planned_meteora_request_cap_rps"],20)
        self.assertEqual(body["execution"]["solana_read_cap_rps"],5)
        self.assertFalse(body["authority"]["allocation_authority"])


if __name__=="__main__":
    unittest.main()
