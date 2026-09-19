import ast
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch,MagicMock

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
        self.assertFalse(p["support_layer"]["strategy_thresholds_changed"])
        self.assertEqual(
            p["support_layer"]["collect_fee_mode_1_only_y"],
            "fail_closed until exact fee-growth/swap accounting is implemented")
        self.assertEqual(
            p["range"]["warmup_alignment"]["qualifying_window_seconds"],12)
        self.assertEqual(
            p["range"]["warmup_alignment"]["max_fresh_windows"],5)
        self.assertEqual(
            p["discovery"]["execution_mode"],
            "streaming_first_sighting_immediate_handoff")
        self.assertTrue(
            p["discovery"]["no_full_universe_wait_before_handoff"])
        self.assertEqual(
            p["evidence_acquisition"]["interval_transaction_bound"],16)
        self.assertFalse(
            p["evidence_acquisition"]["strategy_thresholds_changed"])
        self.assertEqual(p["revision"],"1.6")

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
             patch.object(strategy.time,"time",return_value=2800):
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

    def test_streaming_discovery_yields_before_next_pool_history_read(self):
        p=strategy.load_policy()
        rows=[
            dict(
                address="first",name="first",tvl=1000,is_blacklisted=False,
                token_x=dict(address=dlmm.WSOL),token_y=dict(address="token1"),
                volume={"30m":1000},fees={"30m":10},
            ),
            dict(
                address="second",name="second",tvl=1000,is_blacklisted=False,
                token_x=dict(address=dlmm.WSOL),token_y=dict(address="token2"),
                volume={"30m":1000},fees={"30m":10},
            ),
        ]
        history_reads=[]
        def fake_api(path,params=None):
            if path=="/pools":
                return {"data":rows}
            if path.endswith("/volume/history"):
                address=path.split("/")[2]
                history_reads.append(address)
                return {"data":[
                    dict(timestamp=1000+i*300,
                         volume=(100 if i<5 else 500),
                         fees=(1 if i<5 else 5))
                    for i in range(6)
                ]}
            raise AssertionError(path)
        telemetry={}
        with patch.object(strategy,"_api",side_effect=fake_api), \
             patch.object(strategy.time,"time",return_value=2800):
            stream=strategy._iter_acceleration_candidates(p,telemetry)
            first=next(stream)
            self.assertEqual(first["address"],"first")
            self.assertEqual(history_reads,["first"])
            second=next(stream)
            self.assertEqual(second["address"],"second")
            self.assertEqual(history_reads,["first","second"])

    def test_history_acceleration_requires_six_consecutive_5m_buckets(self):
        candidate=dict(address="pool",tvl_usd=10000)
        rows=[
            dict(timestamp=1000+i*300,volume=(100 if i<5 else 500),
                 fees=(1 if i<5 else 5))
            for i in range(6)
        ]
        with patch.object(strategy,"_api",return_value={"data":rows}):
            out=strategy._history_acceleration(candidate,2800)
        self.assertEqual(out["acceleration_bucket_count"],6)
        self.assertEqual(out["volume_5m_usd"],500)
        self.assertEqual(out["volume_30m_usd"],1000)
        self.assertEqual(out["fee_5m_usd"],5)
        self.assertEqual(out["fee_30m_usd"],10)
        self.assertEqual(out["volume_acceleration"],3.0)
        self.assertEqual(out["fee_acceleration"],3.0)

    def test_partial_current_5m_bucket_is_excluded(self):
        candidate=dict(address="pool",tvl_usd=10000)
        # Six completed buckets end by t=2800. The t=2800 bucket ends at 3100
        # and must be ignored when observed_at=3000.
        rows=[
            dict(timestamp=1000+i*300,volume=(100 if i<5 else 500),
                 fees=(1 if i<5 else 5))
            for i in range(6)
        ]
        rows.append(dict(timestamp=2800,volume=99999,fees=999))
        with patch.object(strategy,"_api",return_value={"data":rows}):
            out=strategy._history_acceleration(candidate,3000)
        self.assertEqual(out["acceleration_bucket_count"],6)
        self.assertEqual(out["acceleration_window_end"],2500)
        self.assertEqual(out["acceleration_window_end_exclusive"],2800)
        self.assertEqual(out["latest_completed_bucket_age_seconds"],200)
        self.assertEqual(out["volume_5m_usd"],500)
        self.assertEqual(out["fee_5m_usd"],5)

    def test_signature_census_paginates_to_authenticated_start_boundary(self):
        page1=[
            dict(
                signature=f"new-{i}",slot=200-i,transactionIndex=i,
                confirmationStatus="finalized",err=None)
            for i in range(64)
        ]
        page2=[
            dict(signature="tx105",slot=105,transactionIndex=2,
                 confirmationStatus="finalized",err=None),
            dict(signature="tx104",slot=104,transactionIndex=1,
                 confirmationStatus="finalized",err=None),
            dict(signature="boundary",slot=100,transactionIndex=0,
                 confirmationStatus="finalized",err=None),
        ]
        rpc=MagicMock()
        rpc.call.side_effect=[page1,page2]
        rows,meta=strategy._complete_signature_census(
            rpc,"pool",100,105)
        self.assertEqual(meta["pages"],2)
        self.assertEqual(meta["relevant_successful"],2)
        self.assertEqual(meta["start_boundary_slot"],100)
        self.assertEqual(
            [row["signature"] for row in rows],
            ["tx105","tx104","boundary"])
        self.assertEqual(rpc.call.call_count,2)
        self.assertEqual(
            rpc.call.call_args_list[1].args[1][1]["before"],
            page1[-1]["signature"])

    def test_signature_census_keeps_16_transaction_bound(self):
        page=[
            dict(
                signature=f"tx-{i}",slot=117-i,transactionIndex=i,
                confirmationStatus="finalized",err=None)
            for i in range(17)
        ]
        page.append(dict(
            signature="boundary",slot=100,transactionIndex=0,
            confirmationStatus="finalized",err=None))
        rpc=MagicMock();rpc.call.return_value=page
        with self.assertRaisesRegex(
                Exception,"transaction_pressure_overflow"):
            strategy._complete_signature_census(
                rpc,"pool",100,117)

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

    def test_zero_flow_warmup_retries_fresh_12s_window_without_weakening_gates(self):
        p=strategy.load_policy()
        candidate=dict(
            address="pool",volume_acceleration=2.5,fee_acceleration=1.5)
        adapter=MagicMock();adapter.rpc.calls=0
        start={"slot":1}
        class Tape:
            def __init__(self,events): self.events=events
        refreshed=[
            dict(candidate,volume_acceleration=2.5,fee_acceleration=1.5),
            dict(candidate,volume_acceleration=2.2,fee_acceleration=1.4),
        ]
        observe=[
            ({"verified":True},Tape([]),{"slot":2},{"slot":1},adapter),
            ({"verified":True},Tape([{"event":"swap"}]),{"slot":3},{"slot":2},adapter),
        ]
        with patch.object(strategy,"_history_acceleration",side_effect=refreshed) as hist, \
             patch.object(strategy,"_fresh_supported_start",return_value=start) as fresh, \
             patch.object(strategy,"_observe_window",side_effect=observe) as obs:
            alignment,warm,entry,origin,_entry_start,_adapter,latest=(
                strategy._aligned_warmup(
                    adapter,candidate,p,MagicMock(),[]))
        self.assertTrue(alignment["aligned"])
        self.assertEqual(alignment["selected_window"],2)
        self.assertEqual(hist.call_count,2)
        self.assertEqual(fresh.call_count,2)
        self.assertEqual(obs.call_count,2)
        self.assertTrue(all(call.args[3]==12 for call in obs.call_args_list))
        self.assertEqual(len(warm.events),1)
        self.assertEqual(latest["volume_acceleration"],2.2)

    def test_zero_flow_retry_stops_if_acceleration_regime_expires(self):
        p=strategy.load_policy()
        candidate=dict(
            address="pool",volume_acceleration=2.5,fee_acceleration=1.5)
        adapter=MagicMock();adapter.rpc.calls=0
        class Tape:
            events=[]
        refreshed=[
            dict(candidate,volume_acceleration=2.5,fee_acceleration=1.5),
            dict(candidate,volume_acceleration=1.9,fee_acceleration=1.5),
        ]
        with patch.object(strategy,"_history_acceleration",side_effect=refreshed) as hist, \
             patch.object(strategy,"_fresh_supported_start",return_value={"slot":1}) as fresh, \
             patch.object(
                 strategy,"_observe_window",
                 return_value=(
                     {"verified":True},Tape(),{"slot":2},{"slot":1},adapter)) as obs:
            alignment,*_=strategy._aligned_warmup(
                adapter,candidate,p,MagicMock(),[])
        self.assertFalse(alignment["aligned"])
        self.assertEqual(alignment["reason"],"acceleration_regime_expired")
        self.assertEqual(hist.call_count,2)
        self.assertEqual(fresh.call_count,1)
        self.assertEqual(obs.call_count,1)

    def test_centered_range_is_two_sided_and_excludes_active(self):
        bins={str(i):{} for i in range(50,151)}
        state={"active":100,"bins":bins}
        lower,upper=strategy._centered_ids(state,4)
        self.assertEqual(lower,[96,97,98,99])
        self.assertEqual(upper,[101,102,103,104])
        self.assertNotIn(100,lower+upper)


if __name__=="__main__":
    unittest.main()
