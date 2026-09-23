import copy
import json
from pathlib import Path
import tempfile
import unittest

from certification.chain_binding import evaluate as chain_binding
from certification.prospective_acceptance import (
    evaluate, make_record, protocol as load_protocol
)

class ChainBindingTests(unittest.TestCase):
    def test_correct_distinct_chain_keys_pass(self):
        env={
            "MM_SOLANA_READ_RPC_URL":"https://solana-mainnet.g.alchemy.com/v2/sol-key",
            "MM_ROBINHOOD_READ_RPC_URL":"https://robinhood-mainnet.g.alchemy.com/v2/rh-key",
            "MM_ROBINHOOD_DLMM_RPC_URL":"https://robinhood-mainnet.g.alchemy.com/v2/rh-key",
        }
        def transport(url,method,params):
            if "solana" in url:
                return {"ok":True,"http_status":200,"result":"genesis-mainnet"}
            if "api.mainnet-beta.solana.com" in url:
                return {"ok":True,"http_status":200,"result":"genesis-mainnet"}
            return {"ok":True,"http_status":200,"result":"0x1237"}
        result=chain_binding(env,transport)
        self.assertTrue(result["passed"])
        self.assertTrue(result["key_binding"]["solana_and_robinhood_read_are_distinct"])

    def test_swapped_hosts_fail_closed(self):
        env={
            "MM_SOLANA_READ_RPC_URL":"https://robinhood-mainnet.g.alchemy.com/v2/a",
            "MM_ROBINHOOD_READ_RPC_URL":"https://solana-mainnet.g.alchemy.com/v2/b",
            "MM_ROBINHOOD_DLMM_RPC_URL":"https://solana-mainnet.g.alchemy.com/v2/b",
        }
        result=chain_binding(env,lambda u,m,p:{"ok":True,"http_status":200,"result":"0x1237"})
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["solana_correct_host"])
        self.assertFalse(result["checks"]["robinhood_read_correct_host"])

class ProtocolFreezeTests(unittest.TestCase):
    def test_frozen_protocol_matches_runtime_authority(self):
        from certification.protocol_freeze import verify
        result=verify()
        self.assertTrue(result["passed"],result["failures"])

class ProspectiveAcceptanceTests(unittest.TestCase):
    def _protocol(self):
        p,_=load_protocol()
        p=copy.deepcopy(p)
        p["evidence_quality"].update(
            minimum_completed_market_blocks_per_lane=2,
            minimum_observation_hours_per_lane=2,
            minimum_calendar_span_hours=1,
            minimum_natural_settlements_per_lane=2,
            minimum_active_blocks_per_lane=2,
        )
        p["portfolio_acceptance"].update(
            minimum_complete_portfolio_blocks=2,
            minimum_calendar_span_hours=1,
        )
        p["portfolio_acceptance"]["pairwise_correlation"]["minimum_joint_nonzero_blocks"]=2
        return p

    def _record(self,proto,run_id,started,ret):
        lane={}
        for name in ("pump","meteora","pons","ramses"):
            lane[name]={
                "identity_match":True,
                "natural_settled":1,
                "forced_settled":0,
                "process_restarts":0,
                "unexpected_exit":False,
                "accounting_reconciled":True,
                "telemetry_complete":True,
                "freshness_finality_unchanged":True,
                "durable_replay":True,
                "infrastructure_censoring_fraction":0.0,
                "economics":{
                    "flat":True,
                    "block_return":ret[name],
                    "return_per_observed_hour":ret[name],
                    "deployed_return_per_capital_hour":max(ret[name],0.001),
                    "capital_time_complete":True,
                },
            }
        return {
            "schema":"meme-machine-prospective-block-v1",
            "cohort_id":proto["cohort_id"],"protocol_sha256":"p",
            "run_id":run_id,"phase":"hourly","status":"FINISHED",
            "started_at":started,"ended_at":started+3600,"observation_hours":1,
            "engineering_pass":True,"integration_sha":"same",
            "source_manifest_hash":"manifest","implementation_hash":"impl",
            "runtime_control_freeze_passed":True,"chain_binding_passed":True,
            "lanes":lane,
        }

    def test_zero_trade_completed_block_is_retained(self):
        proto,_=load_protocol()
        frozen=proto["frozen_lanes"]
        result={
            "run_id":"r","phase":"hourly","status":"FINISHED",
            "continuous_overlap_seconds":3600,"started_at":1,"ended_at":3601,
            "integration_sha":"i","source_manifest_hash":"m","implementation_hash":"x",
            "source_diff_hashes":{k:v["source_diff_sha256"] for k,v in frozen.items()},
            "hourly_engineering":{"status":"PASS"},"lanes":{},
        }
        for lane,row in frozen.items():
            base={
                "strategy_version":row["strategy_version"],"policy_hash":row["policy_hash"],
                "natural_settled":0,"forced_settled":0,"process_restarts":0,
                "unexpected_exit":False,"open_positions":0,"accounting_reconciled":True,
                "gates":{"telemetry_complete":True,"freshness_finality_unchanged":True,
                         "durable_replay":True},"funnel":{"unique_admitted":1},
            }
            if lane=="pump":
                base["native_accounting"]={"initial":100,"realized":0,"basis":0,"pending":0,
                    "reserved":0,"capital_unit_seconds":0}
            elif lane=="pons":
                base["cohort_accounting"]={"genesis":100,"realized":0,"remaining_cost_basis":0,
                    "reserved":0,"unsettled":0,"capital_integral_complete":True}
            elif lane=="meteora":
                base["native_accounting"]={"genesis":{"capital":100},"realized_pnl_lamports":0,
                    "pending":0,"reserved":0,"unsettled":0,"open_positions":0}
            else:
                base["native_accounting"]={"by_quote_asset":{"q":{"paper_capital":100,
                    "realized":0,"committed":0,"open_positions":0}}}
            result["lanes"][lane]=base
        rec=make_record(result,proto,"p")
        self.assertEqual(rec["lanes"]["pump"]["economics"]["block_return"],0)
        self.assertEqual(rec["lanes"]["pons"]["economics"]["block_return"],0)
        self.assertEqual(rec["lanes"]["meteora"]["economics"]["block_return"],0)
        self.assertEqual(rec["lanes"]["ramses"]["economics"]["block_return"],0)

    def test_identity_drift_blocks_promotion(self):
        proto=self._protocol()
        a=self._record(proto,"a",0,{x:.01 for x in ("pump","meteora","pons","ramses")})
        b=self._record(proto,"b",7200,{x:.02 for x in ("pump","meteora","pons","ramses")})
        b["integration_sha"]="different"
        result=evaluate([a,b],proto,"p")
        self.assertFalse(result["identity_frozen"])
        self.assertFalse(result["promotion_eligible"])

    def test_small_synthetic_profitable_cohort_can_pass_reduced_test_thresholds(self):
        proto=self._protocol()
        # Different lane paths avoid undefined perfect-correlation denominators.
        a=self._record(proto,"a",0,{"pump":.01,"meteora":.02,"pons":.03,"ramses":.04})
        b=self._record(proto,"b",7200,{"pump":.02,"meteora":.03,"pons":.01,"ramses":.05})
        # Relax only correlation for this deterministic unit fixture.
        proto["portfolio_acceptance"]["pairwise_correlation"]["maximum_absolute_correlation"]=1.0
        result=evaluate([a,b],proto,"p",expected_integration_sha="same")
        self.assertTrue(all(row["status"]=="PASS" for row in result["lanes"].values()))
        self.assertNotEqual(result["portfolio"]["status"],"FAIL")

if __name__=="__main__":
    unittest.main()
