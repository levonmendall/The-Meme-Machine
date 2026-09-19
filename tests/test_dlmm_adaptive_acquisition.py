import time
import unittest
from unittest.mock import patch

from meme_machine import dlmm,pump
from meme_machine.dlmm_acquisition import (
    AdaptiveReconstructionQueue,
    ReconstructionTask,
    UnionSignatureLedger,
    PUBLIC_DISCOVERY_PROVIDER,
    ONFINALITY_DISCOVERY_PROVIDER,
    discovery_streams,
)
from tests import dlmm_adaptive_operator_discovery as v2


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
        ledger.observe(PUBLIC_DISCOVERY_PROVIDER,"a",1,1.0)
        ledger.observe(PUBLIC_DISCOVERY_PROVIDER,"b",2,2.0)
        ledger.observe(ONFINALITY_DISCOVERY_PROVIDER,"b",2,2.1)
        ledger.observe(ONFINALITY_DISCOVERY_PROVIDER,"c",3,3.0)
        s=ledger.status()
        self.assertEqual(s["unique_signatures"],3)
        self.assertEqual(s["overlap_signatures"],1)
        self.assertAlmostEqual(s["jaccard"],1/3)
        self.assertAlmostEqual(s["public_coverage_of_union"],2/3)
        self.assertAlmostEqual(s["onfinality_coverage_of_union"],2/3)

    def test_discovery_streams_always_include_public_and_optionally_authenticated(self):
        rows=discovery_streams({})
        self.assertEqual(rows[0][0],PUBLIC_DISCOVERY_PROVIDER)
        self.assertEqual(len(rows),1)
        rows=discovery_streams({
            "MM_ONFINALITY_SOLANA_WS_URL":
                "wss://solana.api.onfinality.io/ws?apikey=example"
        })
        self.assertEqual([row[0] for row in rows],
                         [PUBLIC_DISCOVERY_PROVIDER,ONFINALITY_DISCOVERY_PROVIDER])

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

    def test_v2_has_no_fixed_pool_or_transaction_sample_constants(self):
        self.assertFalse(hasattr(v2,"POOL_SAMPLE"))
        self.assertFalse(hasattr(v2,"SIGNATURE_LIMIT"))
        self.assertFalse(hasattr(v2,"TX_BODY_TARGET"))
        self.assertFalse(hasattr(v2,"TX_BODY_SCAN_LIMIT"))
        self.assertEqual(v2.QUEUE_LIMIT,25000)
        self.assertEqual(v2.RPC_ROTATE_AT,200)


if __name__=="__main__":
    unittest.main()
