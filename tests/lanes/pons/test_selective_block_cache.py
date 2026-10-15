import time
import unittest
from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext

class BlockCacheTests(unittest.TestCase):
    def test_block_hash_scopes_cache_and_gas_price_always_refreshes(self):
        class Rpc:
            def __init__(self):self.calls=[]
            def batch(self,calls,scope):self.calls.extend(calls);return ['0x1']*len(calls)
        rpc=Rpc();ctx=SelectiveEvidenceContext('https://robinhood-mainnet.g.alchemy.com/v2/offline');ctx.acquire=lambda *a:rpc
        ctx.pin=(10,'hash-a');calls=[('eth_getCode',['curve','0xa']),('eth_gasPrice',[])]
        ctx.batch(calls,'pons_natural');ctx.batch(calls,'pons_natural')
        self.assertEqual([x[0] for x in rpc.calls],['eth_getCode','eth_gasPrice','eth_gasPrice'])
        ctx.pin=(10,'hash-b');ctx.batch(calls,'pons_natural')
        self.assertEqual(rpc.calls[-2:],calls)
    def test_adjacent_header_batch_is_bounded_deduplicated_and_expiry_aware(self):
        ctx=SelectiveEvidenceContext('https://robinhood-mainnet.g.alchemy.com/v2/offline')
        ctx.adjacent=[dict(deadline=time.time()+5,event=dict(blockNumber=hex(i),blockHash=str(i))) for i in range(10)]
        ctx.adjacent.append(dict(deadline=0,event=dict(blockNumber='0xff',blockHash='late')))
        extra=ctx.prefetch_adjacent_headers([('eth_gasPrice',[])]*48)
        self.assertEqual(len(extra),2)
        self.assertNotIn('late',[x[1] for x in extra])
        self.assertEqual(ctx.prefetch_adjacent_headers([('eth_gasPrice',[])]*50),[])
