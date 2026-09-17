"""Offline regressions for cache-bypassed DLMM interval endpoints."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine import dlmm, pump
from meme_machine.provider import RPC
from tests import dlmm_boundary_acquisition as boundary
from tests.dlmm_support import POOL, snapshot


class FreshProviderRead(unittest.TestCase):
    def test_fresh_call_bypasses_short_cache_and_refreshes_it(self):
        values=iter((111,222))
        def transport(request):
            return {'result':next(values)}
        rpc=RPC('https://example.invalid',limit=40,transport=transport,
                clock=lambda:100.0,sleeper=lambda _seconds:None)
        self.assertEqual(rpc.call('getBlockTime',[1],True),111)
        self.assertEqual(rpc.call('getBlockTime',[1],True),111)
        self.assertEqual(rpc.cache_hits,1)
        self.assertEqual(rpc.call('getBlockTime',[1],True,fresh=True),222)
        self.assertEqual(rpc.calls,2)
        # The fresh response becomes the new cache value.
        self.assertEqual(rpc.call('getBlockTime',[1],True),222)
        self.assertEqual(rpc.cache_hits,2)

    def test_dlmm_snapshot_fresh_flag_reaches_both_account_reads_only(self):
        fixture=snapshot()
        calls=[]
        class StubRPC:
            clock=staticmethod(lambda:100.0)
            def call(self,method,params=None,priority=False,fresh=False):
                params=params or []
                calls.append((method,params,priority,fresh))
                if method=='getGenesisHash':
                    return pump.MAINNET
                if method=='getMultipleAccounts':
                    keys=params[0]
                    return {'context':{'slot':100},
                            'value':[fixture['accounts'].get(key) for key in keys]}
                if method=='getBlockTime':
                    return 100
                raise AssertionError(method)
        adapter=dlmm.Adapter(StubRPC())
        result=adapter.snapshot(POOL,100,True,fresh=True)
        self.assertEqual(result['slot'],100)
        account_reads=[call for call in calls if call[0]=='getMultipleAccounts']
        self.assertEqual(len(account_reads),2)
        self.assertTrue(all(call[3] is True for call in account_reads))
        block_reads=[call for call in calls if call[0]=='getBlockTime']
        self.assertEqual(len(block_reads),1)
        self.assertFalse(block_reads[0][3])

    def test_interval_capture_requires_fresh_endpoint_snapshot(self):
        seen={}
        class Adapter:
            rpc=SimpleNamespace(call_many=lambda *args,**kwargs:[])
            def snapshot(self,pool,now,priority=False,fresh=False):
                seen.update(pool=pool,priority=priority,fresh=fresh)
                return {'slot':101}
        start={'pool':'pool','slot':100}
        anchor=dict(signature='anchor',slot=100,transactionIndex=0,err=None,
                    confirmationStatus='finalized')
        fake_tape=SimpleNamespace(events=[])
        with patch.object(boundary,'complete_signature_census',return_value=[anchor]), \
             patch.object(boundary,'reconstruct',return_value=fake_tape):
            _,cursor,count=boundary.capture_chunk(Adapter(),start,[100,0,0])
        self.assertEqual(seen,dict(pool='pool',priority=True,fresh=True))
        self.assertEqual(cursor,[100,0,0])
        self.assertEqual(count,0)


if __name__=='__main__':
    unittest.main()
