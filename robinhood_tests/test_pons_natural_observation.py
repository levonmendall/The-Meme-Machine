import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from robinhood_research import BoundaryError
from robinhood_research.pons_natural_observation import (
    DISCOVERY_FALLBACK_COALESCE_SECONDS,
    DISCOVERY_MAX_BLOCKS,
    RESEARCH_BUY_WEI,
    ZERO,
    _authenticate_candidate, _authenticate_followup_events,
    _current_curve_events,
    _next_discovery_end,
    _one_word,
    _two_uints,
)


def word(value):
    return "0x"+f"{int(value):064x}"


class PonsNaturalObservationTests(unittest.TestCase):
    def test_word_decoders_are_strict(self):
        one=word(123)
        two="0x"+f"{123:064x}"+f"{456:064x}"
        self.assertEqual(_one_word(one),123)
        self.assertEqual(_two_uints(two),(123,456))
        with self.assertRaisesRegex(BoundaryError,"shape"):
            _one_word(two)
        with self.assertRaisesRegex(BoundaryError,"shape"):
            _two_uints(one)

    def test_observation_size_is_fixed_research_only_amount(self):
        self.assertEqual(RESEARCH_BUY_WEI,10**16)

    def test_ten_sequencer_blocks_use_one_log_query(self):
        class Rpc:
            def __init__(self): self.calls=[]
            def call(self,method,params,scope):
                self.calls.append((method,params,scope))
                return []
        rpc=Rpc()
        self.assertEqual(_current_curve_events(rpc,101,110),[])
        self.assertEqual(len(rpc.calls),1)
        method,params,scope=rpc.calls[0]
        self.assertEqual(method,"eth_getLogs")
        self.assertEqual(params[0]["fromBlock"],hex(101))
        self.assertEqual(params[0]["toBlock"],hex(110))
        self.assertEqual(scope,"pons_natural")

    def test_primary_fallback_discovery_coalesces_up_to_ten_blocks(self):
        class Feed:
            def __init__(self): self.kw=None
            def wait_for_range_after(self,cursor,**kwargs):
                self.kw=kwargs
                return cursor+7
        feed=Feed()
        discovery=SimpleNamespace(primary_fallback=True)
        self.assertEqual(_next_discovery_end(feed,100,discovery,timeout=1.0),107)
        self.assertEqual(feed.kw["max_blocks"],DISCOVERY_MAX_BLOCKS)
        self.assertEqual(
            feed.kw["coalesce_seconds"],DISCOVERY_FALLBACK_COALESCE_SECONDS
        )

    def test_candidate_authentication_is_exactly_two_batch_transports(self):
        now=int(time.time())
        curve="0x"+"22"*20
        token="0x"+"11"*20
        tx="0x"+"33"*32
        block_hash="0x"+"44"*32
        event=dict(
            blockNumber=hex(123),blockHash=block_hash,address=curve,
            transactionHash=tx,transactionIndex="0x0",logIndex="0x0",
            topics=[],data="0x",
        )
        header=dict(
            number=hex(123),hash=block_hash,parentHash="0x"+"55"*32,
            timestamp=hex(now),
        )
        receipt=dict(
            transactionHash=tx,blockHash=block_hash,gasUsed=hex(100_000),logs=[],
        )
        token_word=word(int(token,16))
        reserves="0x"+f"{2*10**18:064x}"+f"{800*10**24:064x}"
        first=[
            "0x1237",header,receipt,token_word,"0x6000",reserves,
            word(10**18),word(100*10**24),word(0),word(0),hex(10**9),
        ]
        batches=[]
        class Rpc:
            def batch(self,calls,scope):
                batches.append((calls,scope))
                return first if len(batches)==1 else ["0xdead"]
        record=dict(
            token=token,curve=curve,deployer="0x"+"66"*20,
            creatorFeeRecipient="0x"+"66"*20,pairToken=ZERO,exists=True,
        )
        auth=dict(immutables=dict(feeBps=100,creatorTaxBps=0))
        decoded=dict(decoded=dict(name="CurveBuy"),event_at=now)
        with patch(
            "robinhood_research.pons_natural_observation.factory_record",
            return_value=record,
        ), patch(
            "robinhood_research.pons_natural_observation.authenticate_curve",
            return_value=auth,
        ), patch(
            "robinhood_research.pons_natural_observation.raw_event",
            return_value=decoded,
        ):
            result=_authenticate_candidate(Rpc(),event,dict(reads=[]))
        self.assertEqual(len(batches),2)
        self.assertEqual(len(batches[0][0]),11)
        self.assertEqual(batches[0][0][0],("eth_chainId",[]))
        self.assertEqual(len(batches[1][0]),1)
        self.assertEqual(result["auth_transport_rounds"],2)
        self.assertLessEqual(result["freshness_seconds"],5)


    def test_followup_auth_batches_headers_and_receipts(self):
        curve="0x"+"22"*20
        block_hash="0x"+"44"*32
        header=dict(hash=block_hash,number="0x7b",timestamp="0x1")
        events=[
            dict(
                address=curve,blockHash=block_hash,blockNumber="0x7b",
                transactionHash="0x"+f"{i:064x}",
                transactionIndex=hex(i),logIndex=hex(i),topics=[],data="0x",
            )
            for i in (1,2)
        ]
        batches=[]
        class Rpc:
            def batch(self,calls,scope):
                batches.append(calls)
                if calls[0][0]=="eth_getBlockByHash":
                    return [header for _ in calls]
                return [
                    dict(
                        transactionHash=params[0],blockHash=block_hash,logs=[]
                    )
                    for _,params in calls
                ]
        candidate=dict(curve=curve)
        with patch(
            "robinhood_research.pons_natural_observation.raw_event",
            side_effect=lambda *args,**kwargs: dict(
                transaction_hash=kwargs["receipt"]["transactionHash"]
            ),
        ):
            rows=_authenticate_followup_events(Rpc(),candidate,events)
        self.assertEqual(len(rows),2)
        self.assertEqual(len(batches),2)
        self.assertEqual(batches[0][0][0],"eth_getBlockByHash")
        self.assertTrue(all(call[0]=="eth_getTransactionReceipt" for call in batches[1]))


if __name__=="__main__":
    unittest.main()