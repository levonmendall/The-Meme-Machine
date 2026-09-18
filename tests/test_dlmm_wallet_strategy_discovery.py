import unittest

from meme_machine import dlmm,pump
from tests import dlmm_wallet_strategy_discovery as study


class WalletDerivedStudy(unittest.TestCase):
    def test_discovery_forbids_pnl_endpoints(self):
        with self.assertRaisesRegex(RuntimeError,"pnl_endpoint_forbidden"):
            study._json_get("/portfolio",{"user":"x"},allow_pnl=False)
        with self.assertRaisesRegex(RuntimeError,"pnl_endpoint_forbidden"):
            study._json_get("/positions/pool/pnl",{"user":"x"},allow_pnl=False)

    def test_actor_extraction_requires_pool_and_signer(self):
        pool=pump.b58(bytes([1])*32)
        wallet=pump.b58(bytes([2])*32)
        position=pump.b58(bytes([3])*32)
        keys=[position,pool]+[pump.b58(bytes([10+i])*32) for i in range(7)]+[
            wallet,pump.TOKEN_PROGRAM,pump.TOKEN_PROGRAM,
            pump.b58(bytes([30])*32),dlmm.PROGRAM]
        tx=dict(
            slot=123,
            transaction=dict(
                signatures=["sig"],
                message=dict(
                    header=dict(numRequiredSignatures=10),
                    accountKeys=keys,
                    instructions=[dict(
                        programIdIndex=13,
                        accounts=list(range(14)),
                        data=pump.b58(study.ADD_LIQUIDITY2_IX+b"fixture"),
                    )],
                ),
            ),
            meta=dict(err=None,innerInstructions=[]),
        )
        rows=study._actor_events(
            tx,pool,1,dict(signature="sig",slot=123))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["wallet"],wallet)
        self.assertEqual(rows[0]["position"],position)
        self.assertEqual(rows[0]["action"],"add_liquidity2")

        tx["transaction"]["message"]["header"]["numRequiredSignatures"]=9
        self.assertEqual(
            study._actor_events(tx,pool,1,dict(signature="sig",slot=123)),[])

    def test_unreadable_transaction_is_replaced_without_pnl_or_reordering(self):
        class FakeRPC:
            def __init__(self):
                self.failure_kinds={}
                self.calls=[]
            def call(self,method,params,priority):
                self.calls.append((method,params[0],priority))
                if params[0]=="bad":
                    self.failure_kinds["provider_error"]=self.failure_kinds.get("provider_error",0)+1
                    raise study.alchemy_provider.Unavailable("provider_request_failed")
                return dict(meta=dict(err=None),transaction=dict(message=dict()))

        rpc=FakeRPC()
        signatures=[
            dict(signature="bad",slot=3),
            dict(signature="good-1",slot=2),
            dict(signature="good-2",slot=1),
        ]
        readable,failures=study._read_recent_transactions(
            rpc,signatures,target=2,scan_limit=3)
        self.assertEqual([row[0]["signature"] for row in readable],["good-1","good-2"])
        self.assertEqual([row["signature"] for row in failures],["bad"])
        self.assertEqual(failures[0]["failure_kind_delta"],{"provider_error":1})
        self.assertEqual([call[1] for call in rpc.calls],["bad","good-1","good-2"])

    def test_repeatability_requires_cross_wallet_consensus(self):
        profiles=[
            dict(
                dominant_hold_bucket=dict(value="1-4h"),
                dominant_width_bucket=dict(value="11-25"),
                median_hold_seconds=7200,
                median_width_bins=17,
                rebalance_proxy_rate=0.8,
            ),
            dict(
                dominant_hold_bucket=dict(value="1-4h"),
                dominant_width_bucket=dict(value="11-25"),
                median_hold_seconds=7500,
                median_width_bins=19,
                rebalance_proxy_rate=0.6,
            ),
            dict(
                dominant_hold_bucket=dict(value="1-4h"),
                dominant_width_bucket=dict(value="11-25"),
                median_hold_seconds=6900,
                median_width_bins=18,
                rebalance_proxy_rate=0.7,
            ),
        ]
        r=study._repeatability(profiles)
        self.assertTrue(r["repeatable_behavior_identified"])
        self.assertEqual(r["derived_hold_seconds"],7200)
        self.assertEqual(r["derived_width_bins"],18)
        self.assertEqual(r["rebalance_preference"]["value"],"active")

        no_consensus=[dict(row) for row in profiles]
        no_consensus[1]=dict(
            dominant_hold_bucket=dict(value="<15m"),
            dominant_width_bucket=dict(value="<=10"),
            median_hold_seconds=600,
            median_width_bins=8,
            rebalance_proxy_rate=0.2,
        )
        no_consensus[2]=dict(
            dominant_hold_bucket=dict(value="4-24h"),
            dominant_width_bucket=dict(value=">50"),
            median_hold_seconds=20000,
            median_width_bins=80,
            rebalance_proxy_rate=0.2,
        )
        self.assertFalse(study._repeatability(no_consensus)["repeatable_behavior_identified"])

    def test_position_metrics_tracks_hold_width_and_fee_efficiency(self):
        row=dict(
            positionAddress="position",
            createdAt=100,closedAt=3700,
            lowerBinId=10,upperBinId=19,
            pnlUsd="12.5",pnlSol=0.05,pnlPctChange="2.5",pnlSolPctChange=1.0,
            allTimeFees=dict(total=dict(usd="5")),
            allTimeDeposits=dict(total=dict(usd="100")),
        )
        m=study._position_metrics(row)
        self.assertEqual(m["hold_seconds"],3600)
        self.assertEqual(m["width_bins"],10)
        self.assertEqual(m["pnl_usd"],12.5)
        self.assertEqual(m["pnl_sol"],0.05)
        self.assertEqual(m["fee_to_deposit"],0.05)

    def test_sol_pair_filter_is_explicit(self):
        self.assertTrue(study._sol_paired(dict(
            token_x=dict(address=dlmm.WSOL),token_y=dict(address="other"))))
        self.assertFalse(study._sol_paired(dict(
            token_x=dict(address="a"),token_y=dict(address="b"))))


if __name__=="__main__":
    unittest.main()
