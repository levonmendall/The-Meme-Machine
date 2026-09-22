from __future__ import annotations

import unittest
from unittest.mock import patch

from robinhood_research.ramses_branch_b_cost_anchor import (
    _indexed_candidates,
    _verified_historical_cost_events,
)


POOL="0x"+"11"*20
TX_SWAP="0x"+"aa"*32
TX_MINT="0x"+"bb"*32
TX_BURN="0x"+"cc"*32
BH1="0x"+"01"*32
BH2="0x"+"02"*32
BH3="0x"+"03"*32


def fake_gql(query, variables):
    if "DLMMSwap(" in query:
        return {"DLMMSwap":[{"transaction":TX_SWAP,"pool":POOL,"timestamp":"100"}]}
    if "DLMMMint(" in query:
        return {"DLMMMint":[{"transaction":TX_MINT,"pool":POOL,"timestamp":"90"}]}
    if "DLMMBurn(" in query:
        return {"DLMMBurn":[{"transaction":TX_BURN,"pool":POOL,"timestamp":"80"}]}
    raise AssertionError(query)


class FakeRpc:
    def __init__(self, *,bad_header=False):
        self.bad_header=bad_header
        self.receipts={
            TX_SWAP:{
                "transactionHash":TX_SWAP,"status":"0x1","blockNumber":"0x64",
                "blockHash":BH1,"gasUsed":"0x186a0",
                "logs":[{"address":POOL,"removed":False,"blockHash":BH1,"transactionHash":TX_SWAP,"kind":"Swap"}],
            },
            TX_MINT:{
                "transactionHash":TX_MINT,"status":"0x1","blockNumber":"0x5a",
                "blockHash":BH2,"gasUsed":"0x30d40",
                "logs":[{"address":POOL,"removed":False,"blockHash":BH2,"transactionHash":TX_MINT,"kind":"DepositedToBins"}],
            },
            TX_BURN:{
                "transactionHash":TX_BURN,"status":"0x1","blockNumber":"0x50",
                "blockHash":BH3,"gasUsed":"0x493e0",
                "logs":[{"address":POOL,"removed":False,"blockHash":BH3,"transactionHash":TX_BURN,"kind":"WithdrawnFromBins"}],
            },
        }

    def batch(self,calls,*,scope):
        out=[]
        for method,params in calls:
            self.assertEqual if False else None
            if method!="eth_getTransactionReceipt":
                raise AssertionError((method,params,scope))
            out.append(self.receipts[params[0]])
        return out

    def blocks(self,block_numbers,*,scope):
        hashes={100:BH1,90:BH2,80:BH3}
        out=[]
        for n in block_numbers:
            h=hashes[n]
            if self.bad_header and n==90:
                h="0x"+"ff"*32
            out.append({"number":hex(n),"hash":h})
        return out


class BranchBCostAnchorTest(unittest.TestCase):
    def test_indexed_candidates_cover_all_cost_categories(self):
        rows=_indexed_candidates(gql_fn=fake_gql,limit=8)
        self.assertEqual(
            {r["category"] for r in rows},
            {"unwind","add_liquidity","remove_liquidity"},
        )
        self.assertEqual(len(rows),3)

    @patch(
        "robinhood_research.ramses_branch_b_cost_anchor.decode_ramses_event",
        side_effect=lambda _abi,event: {"name":event["kind"],"args":{}},
    )
    def test_historical_receipts_seed_all_cost_categories(self,_decode):
        events,state,meta=_verified_historical_cost_events(
            FakeRpc(),[POOL],200,gql_fn=fake_gql,
        )
        self.assertEqual(len(events),3)
        self.assertEqual(len(state["transactions"]),3)
        self.assertEqual(state["samples"]["unwind"],[100000])
        self.assertEqual(state["samples"]["add_liquidity"],[200000])
        self.assertEqual(state["samples"]["remove_liquidity"],[300000])
        self.assertEqual(meta["verified_transactions"],3)
        self.assertEqual(meta["rejected"],{})

    @patch(
        "robinhood_research.ramses_branch_b_cost_anchor.decode_ramses_event",
        side_effect=lambda _abi,event: {"name":event["kind"],"args":{}},
    )
    def test_noncanonical_header_is_rejected(self,_decode):
        events,state,meta=_verified_historical_cost_events(
            FakeRpc(bad_header=True),[POOL],200,gql_fn=fake_gql,
        )
        self.assertEqual(len(events),2)
        self.assertEqual(len(state["transactions"]),2)
        self.assertEqual(meta["rejected"].get("canonical_header_mismatch"),1)
        self.assertEqual(state["samples"]["add_liquidity"],[])


if __name__=="__main__":
    unittest.main()
