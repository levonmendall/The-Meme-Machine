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
