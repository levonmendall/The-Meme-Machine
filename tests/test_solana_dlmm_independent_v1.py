import ast
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from meme_machine import dlmm
from tests import solana_dlmm_independent_v1 as strategy


class SolanaDlmmIndependentV1Tests(unittest.TestCase):
    def test_policy_is_independent_of_robinhood_and_prior_dlmm_strategies(self):
        p=strategy.load_policy()
        independence=p["independence"]
        for key in (
            "wallet_signals","profitable_wallet_labels","prior_dlmm_candidate_outputs",
            "small_pool_study_outputs","capital_efficiency_v1_outputs",
            "robinhood_strategies","pons_strategies","ramses_strategies",
            "robinhood_data","robinhood_provider_config",
        ):
            self.assertIs(independence[key],False,key)
        self.assertIsNone(p["discovery"]["minimum_pool_tvl_usd"])
        self.assertIsNone(p["discovery"]["minimum_absolute_volume_usd"])
        self.assertEqual(p["revision"],"1.1")

    def test_strategy_import_graph_contains_no_strategy_dependency(self):
        path=Path("tests/solana_dlmm_independent_v1.py")
        tree=ast.parse(path.read_text())
        imported=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node,ast.ImportFrom):
                base=node.module or ""
                for alias in node.names:
                    imported.append(base+"."+alias.name if base else alias.name)
        forbidden=(
            "robinhood","pons","ramses",
            "dlmm_profitability_pilot","dlmm_strategy_",
            "dlmm_wallet_","dlmm_capital_efficiency",
        )
        bad=[name for name in imported if any(token in name.lower() for token in forbidden)]
        self.assertEqual(bad,[])
        self.assertIn("tests.dlmm_alchemy_provider",imported)

    def test_robinhood_environment_fails_closed(self):
        with patch.dict(os.environ,{"MM_ROBINHOOD_READ_RPC_URL":"forbidden"},clear=False):
            with self.assertRaisesRegex(RuntimeError,"robinhood_config_forbidden"):
                strategy.assert_independence()

    def test_discovery_uses_acceleration_not_tvl_floor(self):
        p=strategy.load_policy()
        row=dict(
            address="pool",name="pool",tvl=2500,is_blacklisted=False,
            token_x=dict(address=dlmm.WSOL),token_y=dict(address="token"),
            volume={"5m":3000,"30m":6000},
            fees={"5m":30,"30m":120},
            fee_tvl_ratio={"5m":0.012},
            dynamic_fee_pct=0.5,
        )
        calls=[]
        buckets=[
            dict(timestamp=1000+i*300,volume=(100 if i<5 else 500),
                 fees=(1 if i<5 else 5))
            for i in range(6)
        ]
        def fake(path,params=None):
            calls.append((path,dict(params or {})))
            if path.endswith("/volume/history"):
                return {"data":buckets}
            return {"data":[row]}
        with patch.object(strategy,"_api",side_effect=fake), \
             patch.object(strategy.time,"time",return_value=2600):
            accepted,rejected,errors=strategy.discover(p,20)
        self.assertEqual(errors,[])
        self.assertEqual(len(accepted),1)
        self.assertEqual(rejected,[])
        self.assertEqual(accepted[0]["address"],"pool")
        self.assertGreaterEqual(accepted[0]["volume_acceleration"],2)
        self.assertGreaterEqual(accepted[0]["fee_acceleration"],1.25)
        pool_calls=[params for path,params in calls if path=="/pools"]
        self.assertTrue(all("tvl" not in str(c.get("filter_by","")).lower() for c in pool_calls))
        history_calls=[params for path,params in calls if path.endswith("/volume/history")]
        self.assertTrue(history_calls)
        self.assertTrue(all(c.get("timeframe")=="5m" for c in history_calls))

    def test_history_acceleration_requires_six_consecutive_5m_buckets(self):
        candidate=dict(address="pool",tvl_usd=10000)
        rows=[
            dict(timestamp=1000+i*300,volume=(100 if i<5 else 500),
                 fees=(1 if i<5 else 5))
            for i in range(6)
        ]
        with patch.object(strategy,"_api",return_value={"data":rows}):
            out=strategy._history_acceleration(candidate,2600)
        self.assertEqual(out["acceleration_bucket_count"],6)
        self.assertEqual(out["volume_5m_usd"],500)
        self.assertEqual(out["volume_30m_usd"],1000)
        self.assertEqual(out["fee_5m_usd"],5)
        self.assertEqual(out["fee_30m_usd"],10)
        self.assertEqual(out["volume_acceleration"],3.0)
        self.assertEqual(out["fee_acceleration"],3.0)

    def test_range_width_expands_with_observed_movement_but_remains_bounded(self):
        p=strategy.load_policy()
        class Tape:
            events=[
                {"observed":{"start":100,"end":103}},
                {"observed":{"start":103,"end":98}},
            ]
        entry={"active":100}
        half=strategy._movement_half_width(Tape(),entry,p)
        self.assertGreaterEqual(half,p["range"]["min_half_width_bins"])
        self.assertLessEqual(half,p["range"]["max_half_width_bins"])

    def test_qualification_requires_fee_event_flow_capacity_and_unwind(self):
        p=strategy.load_policy()
        base=dict(
            volume_acceleration=2.0,
            fee_acceleration=1.25,
            dynamic_fee_uplift=1.25,
            competing_liquidity_to_capital_multiple=10.0,
            two_way_balance=0.50,
            drift_ratio=0.50,
            reversal_count=1,
            stress_inventory_roundtrip={"loss_bps":70.0},
            expected_net_lamports=100000,
        )
        self.assertTrue(strategy.qualify(base,p)["passes"])
        mutations={
            "volume_acceleration":{"volume_acceleration":1.99},
            "fee_acceleration":{"fee_acceleration":1.24},
            "dynamic_fee":{"dynamic_fee_uplift":1.24},
            "capacity":{"competing_liquidity_to_capital_multiple":9.99},
            "two_way":{"two_way_balance":0.49},
            "drift":{"drift_ratio":0.5001},
            "reversal":{"reversal_count":0},
            "unwind":{"stress_inventory_roundtrip":{"loss_bps":70.01}},
            "expected_net":{"expected_net_lamports":99999},
        }
        for expected,change in mutations.items():
            row=dict(base);row.update(change)
            decision=strategy.qualify(row,p)
            self.assertFalse(decision["passes"],expected)
            self.assertIn(expected,decision["failed"])

    def test_centered_range_is_two_sided_and_excludes_active(self):
        bins={str(i):{} for i in range(50,151)}
        state={"active":100,"bins":bins}
        lower,upper=strategy._centered_ids(state,4)
        self.assertEqual(lower,[96,97,98,99])
        self.assertEqual(upper,[101,102,103,104])
        self.assertNotIn(100,lower+upper)


if __name__=="__main__":
    unittest.main()
