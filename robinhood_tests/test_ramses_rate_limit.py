import unittest
from unittest.mock import patch

from robinhood_research import BoundaryError
import robinhood_research.ramses_capture as capture


class _FakeSession:
    def __init__(self, *, max_batch=2):
        self.used=0
        self.limit=200
        self.max_batch=max_batch
        self.batch_transports=0
        self.call_transports=0
        self.failures={}
    def call(self,method,params,scope="connectivity"):
        self.used+=1
        self.call_transports+=1
        if method=="eth_chainId":
            return "0x1237"
        raise AssertionError((method,params,scope))
    def batch(self,calls,scope="connectivity"):
        self.used+=len(calls)
        self.batch_transports+=1
        if len(calls)>self.max_batch:
            self.failures["provider_http_429"]=self.failures.get("provider_http_429",0)+1
            raise BoundaryError("provider_http_429")
        out=[]
        for method,params in calls:
            if method=="echo":
                out.append(params[0])
            elif method=="eth_getTransactionReceipt":
                tx=params[0]
                out.append(dict(
                    transactionHash=tx,
                    blockHash="0x"+"ab"*32,
                    transactionIndex="0x0",
                    status="0x1",
                    logs=[],
                ))
            elif method=="eth_getBlockByNumber":
                block=int(params[0],16)
                out.append(dict(
                    number=hex(block),
                    hash="0x"+f"{block:064x}",
                    timestamp=hex(1000+block),
                    parentHash="0x"+"00"*32,
                ))
            else:
                raise AssertionError((method,params,scope))
        return out
    def telemetry(self):
        return dict(
            requests=self.used,
            transport_requests=self.batch_transports+self.call_transports,
            logical_requests=self.used,
            retries=0,
            methods={},
            logical_methods={},
            scopes={},
            failures=dict(self.failures),
            role="dlmm_reconstruction_primary",
            provider_kind="validation_cloud",
            endpoint_fingerprint="0123456789abcdef",
            pacing=dict(requests_per_second=5.0),
        )


class RamsesRateLimitTests(unittest.TestCase):
    def test_large_rate_limited_batch_adaptively_splits_without_losing_order(self):
        session=_FakeSession(max_batch=2)
        with patch.object(capture,"configured_dlmm_rpc",return_value=session), \
             patch.object(capture.time,"sleep",return_value=None):
            rpc=capture.BoundedMultiRpc(
                "https://example.invalid/rpc",
                max_sessions=2,
                batch_size=6,
                batch_pause=0,
                rate_retries=1,
                rate_cooldown=0,
                adaptive_batch_floor=2,
            )
            got=rpc.batch(
                [("echo",[i]) for i in range(6)],
                scope="forced",
            )
        self.assertEqual(got,list(range(6)))
        t=rpc.telemetry()
        self.assertGreaterEqual(t["adaptive_batch_splits"],2)
        self.assertGreaterEqual(t["rate_limit_events"],2)
        self.assertGreaterEqual(t["failures"].get("provider_http_429",0),2)
        self.assertEqual(
            t["endpoint_fingerprints"],
            {"0123456789abcdef":1},
        )

    def test_exact_receipts_and_numbered_blocks_are_cached_across_reuse(self):
        session=_FakeSession(max_batch=6)
        tx="0x"+"11"*32
        bh="0x"+"ab"*32
        with patch.object(capture,"configured_dlmm_rpc",return_value=session):
            rpc=capture.BoundedMultiRpc(
                "https://example.invalid/rpc",
                max_sessions=2,
                batch_size=6,
                batch_pause=0,
                rate_retries=0,
                rate_cooldown=0,
            )
            first=rpc.receipts([(tx,bh)],scope="auth")
            transports_after_receipt=session.batch_transports
            second=rpc.receipts([(tx,bh)],scope="auth")
            self.assertEqual(first,second)
            self.assertEqual(session.batch_transports,transports_after_receipt)

            blocks1=rpc.blocks([100,101],scope="headers")
            transports_after_blocks=session.batch_transports
            blocks2=rpc.blocks([101,100],scope="headers")
            self.assertEqual(
                [int(x["number"],16) for x in blocks1],
                [100,101],
            )
            self.assertEqual(
                [int(x["number"],16) for x in blocks2],
                [101,100],
            )
            self.assertEqual(session.batch_transports,transports_after_blocks)
        t=rpc.telemetry()
        self.assertEqual(t["receipt_cache_hits"],1)
        self.assertEqual(t["block_cache_hits"],2)


if __name__=="__main__":
    unittest.main()
