import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from meme_machine import dlmm,pump
from meme_machine.dlmm_acquisition import (
    AdaptiveReconstructionQueue,
    ReconstructionTask,
    UnionSignatureLedger,
    PUBLIC_DISCOVERY_PROVIDER,
    classify_dlmm_lp_logs,
    discovery_streams,
    valid_solana_signature,
)
from tests import dlmm_adaptive_operator_discovery as v2


def _sig(byte):
    return pump.b58(bytes([byte])*64)


class DLMMAdaptiveAcquisitionTests(unittest.TestCase):
    def test_queue_is_deadline_ordered_not_fixed_count_ordered(self):
        q=AdaptiveReconstructionQueue(limit=10)
        q.enqueue(ReconstructionTask(
            identity="later",kind="tx",deadline=200,priority=(0,),
            payload={"signature":"later"}))
        q.enqueue(ReconstructionTask(
            identity="earlier",kind="tx",deadline=150,priority=(99,),
            payload={"signature":"earlier"}))
        task=q.pop_ready(
            100,provider_calls=1,rotation_threshold=200,
            request_interval_seconds=0.2)
        self.assertEqual(task.identity,"earlier")
        self.assertEqual(q.status(100)["processed"],1)
        self.assertEqual(len(q),1)

    def test_queue_defers_before_provider_headroom_breach(self):
        q=AdaptiveReconstructionQueue(limit=10)
        q.enqueue(ReconstructionTask(
            identity="x",kind="tx",deadline=200,priority=(0,),
            payload={},estimated_calls=1))
        self.assertIsNone(q.pop_ready(
            100,provider_calls=200,rotation_threshold=200,
            request_interval_seconds=0.2))
        self.assertEqual(q.status(100)["provider_headroom_deferrals"],1)
        self.assertEqual(len(q),1)

    def test_union_ledger_deduplicates_and_reports_directional_coverage(self):
        ledger=UnionSignatureLedger()
        neutral=[
            f"Program {dlmm.PROGRAM} invoke [1]",
            "Program log: Instruction: Swap2",
            f"Program {dlmm.PROGRAM} success",
        ]
        lp=[
            f"Program {dlmm.PROGRAM} invoke [1]",
            "Program log: Instruction: AddLiquidity2",
            f"Program {dlmm.PROGRAM} success",
        ]
        a,b,c=_sig(1),_sig(2),_sig(3)
        ledger.observe(PUBLIC_DISCOVERY_PROVIDER,a,1,1.0,neutral)
        ledger.observe(PUBLIC_DISCOVERY_PROVIDER,b,2,2.0,lp)
        ledger.observe(PUBLIC_DISCOVERY_PROVIDER,c,3,3.0,neutral)
        s=ledger.status()
        self.assertEqual(s["unique_signatures"],3)
        self.assertEqual(s["overlap_signatures"],0)
        self.assertAlmostEqual(s["jaccard"],0.0)
        self.assertAlmostEqual(s["public_coverage_of_union"],1.0)
        self.assertAlmostEqual(s["onfinality_coverage_of_union"],0.0)
        self.assertEqual(s["reconstruction_candidates"],1)
        self.assertEqual(s["filtered_without_http"],2)
        self.assertEqual([r["signature"] for r in ledger.candidate_rows()],[b])

    def test_stream_rejects_zero_signature_before_candidate_reconstruction(self):
        zero="1"*64
        self.assertFalse(valid_solana_signature(zero))
        self.assertTrue(valid_solana_signature(_sig(5)))
        ledger=UnionSignatureLedger()
        logs=[
            f"Program {dlmm.PROGRAM} invoke [1]",
            "Program log: Instruction: AddLiquidity2",
            f"Program {dlmm.PROGRAM} success",
        ]
        ledger.observe(PUBLIC_DISCOVERY_PROVIDER,zero,1,1.0,logs)
        self.assertEqual(ledger.status()["unique_signatures"],0)
        self.assertEqual(ledger.status()["invalid_signature_notifications"],1)
        self.assertEqual(ledger.candidate_rows(),[])

    def test_discovery_streams_use_public_solana_only(self):
        rows=discovery_streams({})
        self.assertEqual(rows,[(PUBLIC_DISCOVERY_PROVIDER,
                                "wss://api.mainnet-beta.solana.com")])
        rows=discovery_streams({
            "MM_ONFINALITY_SOLANA_WS_URL":
                "wss://solana.api.onfinality.io/ws?apikey=ignored"
        })
        self.assertEqual(rows,[(PUBLIC_DISCOVERY_PROVIDER,
                                "wss://api.mainnet-beta.solana.com")])

    def test_log_filter_selects_supported_lp_instruction_without_http(self):
        logs=[
            f"Program {dlmm.PROGRAM} invoke [1]",
            "Program log: Instruction: AddLiquidity2",
            f"Program {dlmm.PROGRAM} success",
        ]
        row=classify_dlmm_lp_logs(logs)
        self.assertTrue(row["likely_lp"])
        self.assertFalse(row["uncertain"])
        self.assertEqual(row["actions"],["add_liquidity2"])

    def test_log_filter_rejects_swap_only_transaction(self):
        logs=[
            f"Program {dlmm.PROGRAM} invoke [1]",
            "Program log: Instruction: Swap2",
            f"Program {dlmm.PROGRAM} success",
        ]
        row=classify_dlmm_lp_logs(logs)
        self.assertFalse(row["likely_lp"])
        self.assertFalse(row["uncertain"])
        self.assertEqual(row["actions"],[])

    def test_log_filter_queues_truncated_logs_conservatively(self):
        row=classify_dlmm_lp_logs([
            f"Program {dlmm.PROGRAM} invoke [1]",
            "Log truncated",
        ])
        self.assertFalse(row["likely_lp"])
        self.assertTrue(row["uncertain"])

    def test_pool_rejection_diagnostic_classifies_without_changing_rules(self):
        rows=[
            dict(address="eligible",name="ok",is_blacklisted=False,tvl=60000,
                 volume={"24h":30000},
                 token_x={"address":dlmm.WSOL,"symbol":"SOL"},
                 token_y={"address":"mint-a","symbol":"A"}),
            dict(address="nosol",name="x",is_blacklisted=False,tvl=60000,
                 volume={"24h":30000},
                 token_x={"address":"mint-b","symbol":"B"},
                 token_y={"address":"mint-c","symbol":"C"}),
            dict(address="lowtvl",name="y",is_blacklisted=False,tvl=40000,
                 volume={"24h":30000},
                 token_x={"address":dlmm.WSOL,"symbol":"SOL"},
                 token_y={"address":"mint-d","symbol":"D"}),
            dict(address="lowvol",name="z",is_blacklisted=False,tvl=60000,
                 volume={"24h":20000},
                 token_x={"address":dlmm.WSOL,"symbol":"SOL"},
                 token_y={"address":"mint-e","symbol":"E"}),
            dict(address="black",name="b",is_blacklisted=True,tvl=60000,
                 volume={"24h":30000},
                 token_x={"address":dlmm.WSOL,"symbol":"SOL"},
                 token_y={"address":"mint-f","symbol":"F"}),
        ]
        def fake(path,params=None,allow_pnl=False):
            self.assertEqual(path,"/pools")
            return {"data":rows if params["page"]==1 else []}
        with patch.object(v2.study,"_json_get",side_effect=fake):
            d=v2.diagnose_pool_universe()
        self.assertEqual(d["observable_unique_pools"],5)
        self.assertEqual(d["eligible_under_current_rules"],1)
        self.assertEqual(d["primary_classification"]["eligible"],1)
        self.assertEqual(d["primary_classification"]["not_exactly_one_sol_leg"],1)
        self.assertEqual(d["primary_classification"]["tvl_below_50000"],1)
        self.assertEqual(d["primary_classification"]["volume_24h_below_25000"],1)
        self.assertEqual(d["primary_classification"]["blacklisted"],1)

    def test_pool_census_pages_until_inventory_end_without_sample_cap(self):
        eligible=lambda i:dict(
            address=f"pool-{i}",name=f"p{i}",tvl=100000,
            volume={"24h":50000},fee_tvl_ratio={"24h":1},
            created_at=1,
            token_x={"address":dlmm.WSOL,"symbol":"SOL"},
            token_y={"address":f"token-{i}","symbol":"T"},
        )
        pages={1:[eligible(i) for i in range(v2.POOL_PAGE_SIZE)],
               2:[eligible(v2.POOL_PAGE_SIZE)]}
        def fake(path,params=None,allow_pnl=False):
            self.assertEqual(path,"/pools")
            self.assertFalse(allow_pnl)
            return {"data":pages.get(params["page"],[])}
        with patch.object(v2.study,"_json_get",side_effect=fake):
            rows,status=v2.census_eligible_pools()
        self.assertTrue(status["complete"])
        self.assertEqual(status["pages"],2)
        self.assertEqual(len(rows),v2.POOL_PAGE_SIZE+1)
        self.assertNotIn("pool_sample",status)

    def test_actor_extraction_filters_to_censused_pool_and_signer(self):
        pool=pump.b58(bytes([1])*32)
        wallet=pump.b58(bytes([2])*32)
        position=pump.b58(bytes([3])*32)
        keys=[position,pool]+[pump.b58(bytes([10+i])*32) for i in range(7)]+[
            wallet,pump.TOKEN_PROGRAM,pump.TOKEN_PROGRAM,
            pump.b58(bytes([30])*32),dlmm.PROGRAM]
        tx=dict(
            slot=123,
            transaction=dict(message=dict(
                header=dict(numRequiredSignatures=10),
                accountKeys=keys,
                instructions=[dict(
                    programIdIndex=13,accounts=list(range(14)),
                    data=pump.b58(v2.study.ADD_LIQUIDITY2_IX+b"fixture"),
                )],
            )),
            meta=dict(err=None,innerInstructions=[]),
        )
        rows=v2._actor_events_any_pool(
            tx,{pool:1},dict(signature="sig",slot=123,providers=["public"]))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["wallet"],wallet)
        self.assertEqual(rows[0]["pool"],pool)
        self.assertEqual(rows[0]["action"],"add_liquidity2")

    def test_adaptive_checkpoint_reuses_only_matching_pool_universe(self):
        pools=[{"address":"a"},{"address":"b"}]
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"checkpoint.json"
            with patch.object(v2,"CHECKPOINT_OUT",path):
                sig=_sig(4)
                v2._write_checkpoint(
                    pools,
                    {sig:{"signature":sig,"slot":1,"first_observed_at":1.0}},
                    {sig:{"status":"success","events":[]}},
                )
                candidates,processed=v2._load_checkpoint(pools)
                self.assertIn(sig,candidates)
                self.assertEqual(processed[sig]["status"],"success")
                self.assertEqual(v2._load_checkpoint([{"address":"different"}]),({},{}))

    def test_filtered_reconstruction_covers_current_lp_mutation_surface(self):
        actions={spec[0] for spec in v2.LP_MUTATIONS.values()}
        required={
            "add_liquidity","add_liquidity2","add_liquidity_by_strategy",
            "add_liquidity_by_strategy2","add_liquidity_by_strategy_one_side",
            "add_liquidity_by_weight","add_liquidity_by_weight2",
            "add_liquidity_one_side","add_liquidity_one_side_precise",
            "add_liquidity_one_side_precise2","rebalance_liquidity",
            "remove_all_liquidity","remove_liquidity","remove_liquidity2",
            "remove_liquidity_by_range","remove_liquidity_by_range2",
            "claim_fee","claim_fee2",
        }
        self.assertEqual(actions,required)

    def test_v2_has_no_fixed_pool_or_transaction_sample_constants(self):
        self.assertFalse(hasattr(v2,"POOL_SAMPLE"))
        self.assertFalse(hasattr(v2,"SIGNATURE_LIMIT"))
        self.assertFalse(hasattr(v2,"TX_BODY_TARGET"))
        self.assertFalse(hasattr(v2,"TX_BODY_SCAN_LIMIT"))
        self.assertEqual(v2.QUEUE_LIMIT,25000)
        self.assertEqual(v2.RPC_ROTATE_AT,200)


if __name__=="__main__":
    unittest.main()
