import ast
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch,MagicMock

from meme_machine import dlmm
from tests import solana_dlmm_independent_v1 as strategy


class SolanaDlmmIndependentV1Tests(unittest.TestCase):
    def test_policy_is_independent_and_profitability_authoritative(self):
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
        self.assertEqual(
            p["discovery"]["union_sorts"][0],"fee_tvl_ratio_5m:desc")
        self.assertEqual(
            p["discovery"]["public_fee_density_role"],
            "ranking_context_only_not_entry_authority")
        self.assertEqual(
            p["range"]["warmup_alignment"]["qualifying_window_seconds"],12)
        self.assertEqual(p["range"]["intended_holding_seconds"],14400)
        self.assertEqual(p["range"]["max_holding_seconds"],86400)
        self.assertEqual(p["range"]["min_half_width_bins"],26)
        self.assertEqual(p["range"]["max_half_width_bins"],50)
        self.assertEqual(p["qualification"]["min_two_way_balance"],0.25)
        self.assertEqual(
            p["qualification"]["min_authenticated_fee_density_24h_pct"],5.0)
        self.assertEqual(p["qualification"]["min_expected_net_lamports"],1)
        self.assertEqual(
            p["fee_model"]["live_fee_density_threshold_pct"],5.0)
        self.assertIn(
            "range_fee_sol_lamports / range_liquidity_sol_lamports",
            p["fee_model"]["live_fee_density_metric"])
        self.assertFalse(p["fee_model"]["require_dynamic_fee_uplift"])
        self.assertEqual(p["revision"],"2.0-profitability-fee-density-v1")
        self.assertTrue(p["execution_certification"]["profitability_authority"])
        self.assertFalse(p["execution_certification"]["machinery_proof_only"])
        self.assertTrue(
            p["execution_certification"]["strategy2_continuity_required"])
        self.assertTrue(
            p["execution_certification"]["freshness_finality_unchanged"])

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

    def test_network_identity_retries_then_succeeds_once(self):
        bad=MagicMock()
        bad.call.side_effect=strategy.Unavailable("provider_request_failed")
        good=MagicMock()
        good.call.return_value=dlmm.pump.MAINNET
        for rpc in (bad,good):
            rpc.calls=rpc.http_requests=rpc.failures=rpc.retries=0
            rpc.failure_kinds={};rpc.failure_methods={}
            rpc.provider_telemetry.return_value={"provider":"alchemy"}
        rpcs=[]
        with patch.object(
                strategy.provider,"new_rpc",side_effect=[bad,good]) as make, \
             patch.object(strategy.time,"sleep") as sleep:
            proof=strategy._prove_network_identity(MagicMock(),rpcs)
        self.assertTrue(proof["verified"])
        self.assertEqual(proof["verified_attempt"],2)
        self.assertEqual(len(proof["attempts"]),2)
        self.assertEqual(len(rpcs),2)
        self.assertEqual(make.call_count,2)
        self.assertEqual(sleep.call_count,1)

    def test_rotated_adapter_reuses_proven_network_identity(self):
        rpc=MagicMock()
        rpc.calls=rpc.http_requests=rpc.failures=rpc.retries=0
        rpc.failure_kinds={};rpc.failure_methods={}
        rpcs=[]
        with patch.object(strategy.provider,"new_rpc",return_value=rpc), \
             patch.object(strategy.dlmm,"Adapter") as adapter_cls:
            strategy._new_adapter(MagicMock(),rpcs)
        adapter_cls.assert_called_once_with(rpc,network_verified=True)
        rpc.call.assert_not_called()
        self.assertEqual(rpcs,[rpc])

    def test_atomic_checkpoint_preserves_candidate_and_provider_telemetry(self):
        rpc=MagicMock()
        rpc.calls=7;rpc.http_requests=5;rpc.failures=2;rpc.retries=1
        rpc.failure_kinds={"network_or_timeout":2}
        rpc.failure_methods={"getTransaction:network_or_timeout":2}
        rpc.provider_telemetry.return_value={"topology":"test"}
        pacer=MagicMock();pacer.telemetry.return_value={"waits":3}
        report={"attempts":[{"pool":"p","terminal_classification":"exception"}]}
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"checkpoint.json"
            with patch.object(strategy,"OUT",out):
                strategy._atomic_checkpoint(
                    report,"candidate_exception",[rpc],pacer,
                    attempted_pool_count=1,complete_lifecycle_count=0)
            saved=json.loads(out.read_text())
        self.assertEqual(saved["checkpoint"]["stage"],"candidate_exception")
        self.assertEqual(saved["attempts"][0]["pool"],"p")
        self.assertEqual(saved["rpc"]["failure_kinds"]["network_or_timeout"],2)
        self.assertEqual(
            saved["rpc"]["failure_methods"][
                "getTransaction:network_or_timeout"],2)
        self.assertEqual(saved["alchemy_pacer"]["waits"],3)

    def test_adapter_network_verified_skips_genesis_probe(self):
        rpc=MagicMock()
        adapter=dlmm.Adapter(rpc,network_verified=True)
        self.assertIs(adapter.rpc,rpc)
        rpc.call.assert_not_called()

    def test_discovery_uses_fee_density_ranking_without_tvl_floor(self):
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
        # Public history is retained as ranking/context telemetry only.
        self.assertGreaterEqual(accepted[0]["volume_acceleration"],2)
        self.assertGreaterEqual(accepted[0]["fee_acceleration"],1.25)
        self.assertGreater(accepted[0]["fee_5m_usd"],0)
        self.assertEqual(strategy.DISCOVERY_SORTS[0],"fee_tvl_ratio_5m:desc")
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
                signature=f"new-{i}",slot=400-i,transactionIndex=i,
                confirmationStatus="finalized",err=None)
            for i in range(strategy.SIGNATURE_PAGE_LIMIT)
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

    def test_signature_census_reduces_requests_without_expanding_scan_capacity(self):
        self.assertEqual(strategy.SIGNATURE_PAGE_LIMIT,256)
        self.assertEqual(strategy.MAX_SIGNATURE_CENSUS_PAGES,4)
        self.assertEqual(strategy.SIGNATURE_CENSUS_MAX_ROWS,1024)

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

    def test_authenticated_fee_density_is_24h_normalized_local_liquidity(self):
        class Tape:
            terminal={"time":112}
            events=[{
                "observed":{"start":100,"end":101},
                "for_y":True,
            }]
        start={"time":100}
        with patch.object(strategy,"_range_liquidity_sol",return_value=1_000_000), \
             patch.object(strategy,"_event_volume_sol",return_value=100), \
             patch.object(strategy,"_event_fee_sol",return_value=10):
            row=strategy._range_flow_features(
                start,Tape(),[99],[101],liquidity_state={})
        self.assertAlmostEqual(row["fee_density"],0.00001)
        self.assertAlmostEqual(row["authenticated_fee_density_24h_pct"],7.2)
        self.assertGreater(
            row["authenticated_fee_density_24h_pct"],
            strategy.load_policy()["qualification"][
                "min_authenticated_fee_density_24h_pct"])

    def test_qualification_requires_authenticated_density_flow_capacity_and_unwind(self):
        p=strategy.load_policy()
        base=dict(
            volume_acceleration=0.1,
            fee_acceleration=0.1,
            authenticated_fee_density_24h_pct=5.0,
            dynamic_fee_uplift=1.0,
            competing_liquidity_to_capital_multiple=5.0,
            two_way_balance=0.25,
            drift_ratio=0.75,
            reversal_count=0,
            stress_inventory_roundtrip={"loss_bps":150.0},
            expected_net_lamports=1,
        )
        self.assertEqual(p["qualification"]["min_two_way_balance"],0.25)
        self.assertEqual(p["qualification"]["min_expected_net_lamports"],1)
        self.assertTrue(strategy.qualify(base,p)["passes"])
        mutations={
            "authenticated_fee_density":{
                "authenticated_fee_density_24h_pct":4.999},
            "capacity":{"competing_liquidity_to_capital_multiple":4.99},
            "two_way":{"two_way_balance":0.2499},
            "drift":{"drift_ratio":0.7501},
            "unwind":{"stress_inventory_roundtrip":{"loss_bps":150.01}},
            "expected_net":{"expected_net_lamports":0},
        }
        for expected,change in mutations.items():
            row=dict(base);row.update(change)
            decision=strategy.qualify(row,p)
            self.assertFalse(decision["passes"],expected)
            self.assertIn(expected,decision["failed"])
        # Acceleration and dynamic-fee uplift no longer authorize or veto entry.
        low_context=dict(base,volume_acceleration=0.0,fee_acceleration=0.0,
                         dynamic_fee_uplift=0.10)
        decision=strategy.qualify(low_context,p)
        self.assertTrue(decision["passes"])
        self.assertNotIn("volume_acceleration",decision["checks"])
        self.assertNotIn("fee_acceleration",decision["checks"])
        self.assertNotIn("dynamic_fee",decision["checks"])

    def test_fresh_authenticated_swap_trigger_starts_exact_12s_warmup(self):
        p=strategy.load_policy()
        candidate=dict(
            address="pool",volume_acceleration=2.5,fee_acceleration=1.5)
        adapter=MagicMock();adapter.rpc.calls=0
        post={"slot":20}
        trigger=dict(
            triggered=True,reason="authenticated_fresh_swap",
            signature="sig",slot=19,swap_count=1)
        class Tape:
            events=[{"event":"swap"}]
        with patch.object(
                strategy,"_await_fresh_swap_trigger",
                return_value=(trigger,post,adapter,candidate)) as watch, \
             patch.object(
                strategy,"_observe_window",
                return_value=(
                    {"verified":True},Tape(),{"slot":21},{"slot":20},adapter)
             ) as observe:
            result,warm,entry,origin,_adapter,latest=(
                strategy._triggered_warmup(
                    adapter,candidate,{"slot":10},p,MagicMock(),[]))
        self.assertTrue(result["aligned"])
        self.assertEqual(result["reason"],"verified_nonzero_warmup")
        self.assertEqual(result["qualifying_window_seconds"],12)
        self.assertEqual(observe.call_args.args[3],12)
        self.assertEqual(result["trigger"]["signature"],"sig")
        self.assertEqual(len(warm.events),1)
        self.assertEqual(latest["volume_acceleration"],2.5)
        self.assertEqual(watch.call_count,1)

    def test_zero_swap_after_fresh_trigger_is_rejected_not_retried(self):
        p=strategy.load_policy()
        candidate=dict(
            address="pool",volume_acceleration=2.5,fee_acceleration=1.5)
        adapter=MagicMock();adapter.rpc.calls=0
        trigger=dict(triggered=True,reason="authenticated_fresh_swap",slot=19)
        class Tape:
            events=[]
        with patch.object(
                strategy,"_await_fresh_swap_trigger",
                return_value=(trigger,{"slot":20},adapter,candidate)), \
             patch.object(
                strategy,"_observe_window",
                return_value=(
                    {"verified":True},Tape(),{"slot":21},{"slot":20},adapter)
             ) as observe:
            result,*_=strategy._triggered_warmup(
                adapter,candidate,{"slot":10},p,MagicMock(),[])
        self.assertFalse(result["aligned"])
        self.assertEqual(
            result["reason"],"verified_zero_warmup_after_fresh_swap")
        self.assertEqual(observe.call_count,1)
        self.assertEqual(observe.call_args.args[3],12)

    def test_new_finalized_swap_trigger_requires_authenticated_dlmm_swap(self):
        rpc=MagicMock()
        rpc.call.return_value=[
            dict(
                signature="sig",slot=11,confirmationStatus="finalized",
                err=None)
        ]
        tx=dict(meta=dict(err=None),blockTime=123,transaction={})
        rpc.call_many.return_value=[tx]
        with patch.object(
                strategy,"transaction_swaps",
                return_value=[dict(observed={"start":1,"end":2})]) as parse:
            out,meta=strategy._new_finalized_swaps(rpc,"pool",10)
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]["signature"],"sig")
        self.assertEqual(out[0]["slot"],11)
        self.assertEqual(out[0]["swap_count"],1)
        self.assertFalse(meta["rate_limited"])
        self.assertEqual(meta["head_slot"],11)
        self.assertEqual(parse.call_count,1)

    def test_signature_poll_supplies_head_without_second_rpc_read(self):
        rpc=MagicMock()
        rpc.failure_methods={}
        rpc.call.return_value=[
            dict(
                signature="head",slot=12,
                confirmationStatus="finalized",err=None)
        ]
        rpc.call_many.return_value=[dict(
            meta=dict(err=None),blockTime=123,transaction={})]
        with patch.object(strategy,"transaction_swaps",return_value=[]):
            swaps,meta=strategy._new_finalized_swaps(
                rpc,"pool",10)
        self.assertEqual(swaps,[])
        self.assertEqual(meta["head_slot"],12)
        self.assertEqual(rpc.call.call_count,1)
        self.assertEqual(rpc.call_many.call_count,1)

    def test_signature_429_is_transient_not_candidate_failure(self):
        rpc=MagicMock()
        rpc.failure_methods={}
        def limited(*_args,**_kwargs):
            rpc.failure_methods[
                "getSignaturesForAddress:http_429"]=2
            raise strategy.Unavailable("provider_request_failed")
        rpc.call.side_effect=limited
        swaps,meta=strategy._new_finalized_swaps(
            rpc,"pool",10)
        self.assertEqual(swaps,[])
        self.assertTrue(meta["rate_limited"])
        self.assertEqual(meta["stage"],"getSignaturesForAddress")
        self.assertEqual(meta["head_slot"],10)

    def test_transaction_429_does_not_advance_signature_cursor(self):
        rpc=MagicMock()
        rpc.failure_methods={}
        rpc.call.return_value=[
            dict(
                signature="sig",slot=11,
                confirmationStatus="finalized",err=None)
        ]
        def limited(*_args,**_kwargs):
            rpc.failure_methods["getTransaction:http_429"]=3
            raise strategy.Unavailable("provider_request_failed")
        rpc.call_many.side_effect=limited
        swaps,meta=strategy._new_finalized_swaps(
            rpc,"pool",10)
        self.assertEqual(swaps,[])
        self.assertTrue(meta["rate_limited"])
        self.assertEqual(meta["stage"],"getTransaction")
        self.assertEqual(meta["head_slot"],10)

    def test_stream_handoff_bootstrap_authenticates_first_unseen_swap_once(self):
        p=strategy.load_policy()
        candidate=dict(
            address="pool",volume_acceleration=2.5,fee_acceleration=1.5,
            fee_5m_usd=5.0,tvl_usd=1000.0,signal_observed_at=1000)
        adapter=MagicMock();adapter.rpc.calls=0
        broker=MagicMock()
        broker.cursor.return_value={"slot":0,"signature":None}
        broker.stream_status.return_value={"gaps":0}
        broker.recent_events.return_value=[]
        swap=dict(signature="sig",slot=11,swap_count=1)
        poll_meta=dict(
            rate_limited=False,head_slot=11,head_signature="sig")
        post={"slot":12}
        with patch.object(
                strategy,"_history_acceleration",return_value=candidate), \
             patch.object(
                strategy,"_new_finalized_swaps",
                return_value=([swap],poll_meta)) as auth, \
             patch.object(
                strategy,"_fresh_supported_start",return_value=post), \
             patch.object(strategy.time,"monotonic",return_value=0.0):
            trigger,observed,_adapter,_latest=strategy._await_fresh_swap_trigger(
                adapter,candidate,{"slot":10},p,MagicMock(),[],broker=broker)
        self.assertTrue(trigger["triggered"])
        self.assertEqual(trigger["wake_source"],"handoff_gap_auth")
        self.assertEqual(trigger["bootstrap_auth_reads"],1)
        self.assertEqual(trigger["polls"],1)
        self.assertEqual(auth.call_count,1)
        self.assertEqual(observed["slot"],12)

    def test_stream_trigger_does_not_poll_again_until_pool_wakes(self):
        p=strategy.load_policy()
        candidate=dict(
            address="pool",volume_acceleration=2.5,fee_acceleration=1.5,
            fee_5m_usd=5.0,tvl_usd=1000.0,signal_observed_at=1000)
        adapter=MagicMock();adapter.rpc.calls=0
        broker=MagicMock()
        broker.cursor.return_value={"slot":0,"signature":None}
        broker.stream_status.return_value={"gaps":0}
        broker.recent_events.side_effect=[
            [],
            [dict(signature=None,address="pool",slot=11,observed_at=1001)],
        ]
        swap=dict(signature="sig",slot=12,swap_count=1)
        polls=[
            ([],dict(rate_limited=False,head_slot=10,head_signature=None)),
            ([swap],dict(rate_limited=False,head_slot=12,head_signature="sig")),
        ]
        with patch.object(
                strategy,"_history_acceleration",return_value=candidate), \
             patch.object(
                strategy,"_new_finalized_swaps",side_effect=polls) as auth, \
             patch.object(
                strategy,"_fresh_supported_start",return_value={"slot":13}), \
             patch.object(strategy.time,"monotonic",return_value=0.0), \
             patch.object(strategy.time,"sleep"):
            trigger,_post,_adapter,_latest=strategy._await_fresh_swap_trigger(
                adapter,candidate,{"slot":10},p,MagicMock(),[],broker=broker)
        self.assertTrue(trigger["triggered"])
        self.assertEqual(trigger["wake_source"],"finalized_program_account_stream")
        self.assertEqual(trigger["bootstrap_auth_reads"],1)
        self.assertEqual(trigger["wakeups"],1)
        self.assertEqual(auth.call_count,2)

    def test_public_fee_context_expiry_stops_fresh_swap_wait(self):
        p=strategy.load_policy()
        candidate=dict(
            address="pool",volume_acceleration=0.1,fee_acceleration=0.1,
            fee_5m_usd=5.0,tvl_usd=1000.0)
        adapter=MagicMock();adapter.rpc.calls=0
        expired=dict(candidate,fee_5m_usd=0.0)
        with patch.object(
                strategy,"_history_acceleration",return_value=expired), \
             patch.object(strategy.time,"monotonic",return_value=0.0):
            trigger,post,_adapter,_latest=strategy._await_fresh_swap_trigger(
                adapter,candidate,{"slot":10},p,MagicMock(),[])
        self.assertFalse(trigger["triggered"])
        self.assertEqual(trigger["reason"],"public_fee_context_expired")
        self.assertIsNone(post)

    def test_public_acceleration_is_not_a_hard_regime_gate(self):
        p=strategy.load_policy()
        candidate=dict(
            fee_5m_usd=1.0,tvl_usd=1000.0,
            volume_acceleration=0.0,fee_acceleration=0.0)
        self.assertTrue(strategy._regime_pass(candidate,p))

    def test_centered_range_is_two_sided_and_excludes_active(self):
        bins={str(i):{} for i in range(0,201)}
        state={"active":100,"bins":bins}
        lower,upper=strategy._centered_ids(state,26)
        self.assertEqual(len(lower+upper),52)
        self.assertEqual(lower[0],74)
        self.assertEqual(upper[-1],126)
        self.assertNotIn(100,lower+upper)


if __name__=="__main__":
    unittest.main()
