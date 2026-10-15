import json
from pathlib import Path
import unittest
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.abi import calldata
from meme_machine.lanes.pons.view_batch import batch,GETTERS,grouped

class Rpc:
    def __init__(self,unsupported=False,mismatch=False):self.calls=[];self.unsupported=unsupported;self.mismatch=mismatch
    def batch(self,calls,scope):
        self.calls.append(calls);out=[]
        for method,p in calls:
            if method=='eth_callMany':
                if self.unsupported:raise BoundaryError('provider_rpc_-32601')
                out.append([[dict(value='0xwrong' if self.mismatch else tx['input']) for tx in p[0][0]['transactions']]])
            else:out.append(p[0]['data'])
        return out

class ViewBatchTests(unittest.TestCase):
    def calls(self):return [('eth_call',[dict(to='a',data=calldata(g)),'0x1']) for g in ('token()','realQuoteReserve()')]
    def test_documented_getters_are_compiled_view_functions(self):
        from meme_machine.lanes.pons import pons
        path=Path(pons.__file__).with_name('pons_curve_template.json')
        abi=json.loads(path.read_text())['abi'];byname={a.get('name'):a for a in abi if a['type']=='function'}
        for g in GETTERS:self.assertEqual(byname[g.split('(')[0]]['stateMutability'],'view')
    def test_first_group_proves_parity_then_reduces_logical_work(self):
        r=Rpc();s={'supported':True};calls=self.calls()
        expected=[c[1][0]['data'] for c in calls]
        self.assertEqual(batch(r,calls,'test',s),expected);self.assertTrue(s['parity_verified'])
        self.assertEqual(len(r.calls[0]),3)
        self.assertEqual(batch(r,calls,'test',s),expected);self.assertEqual(len(r.calls[1]),1)
    def test_unsupported_falls_back_and_does_not_reprobe(self):
        r=Rpc(unsupported=True);s={'supported':True};calls=self.calls()
        self.assertEqual(batch(r,calls,'test',s),[c[1][0]['data'] for c in calls]);self.assertFalse(s['supported'])
        batch(r,calls,'test',s);self.assertEqual(len(r.calls),3)
    def test_disagreement_uses_independent_results_and_disables(self):
        s={'supported':True};calls=self.calls();r=Rpc(mismatch=True)
        self.assertEqual(batch(r,calls,'test',s),[c[1][0]['data'] for c in calls]);self.assertFalse(s['supported'])
    def test_no_cross_block_or_override_or_arbitrary_call_group(self):
        a,b=self.calls();b=('eth_call',[b[1][0],'0x2']);self.assertFalse(grouped([a,b]))
        b=('eth_call',[a[1][0],'0x1',{}]);self.assertFalse(grouped([a,b]))
        b=('eth_call',[dict(to='a',data='0xdeadbeef'),'0x1']);self.assertFalse(grouped([a,b]))
    def test_header_index_requires_adjacent_boundary_proof(self):
        from meme_machine.lanes.pons.pons_selective_acquisition import ImmutableEvidenceCache,_indexed_header_plan
        c=ImmutableEvidenceCache()
        def h(n):return dict(number=hex(n),hash=str(n),timestamp=hex(100+n//10))
        for n in (100,109,110,200,209,210,250):c.remember_header(h(n))
        plan,_=_indexed_header_plan(c,h(250),1)
        self.assertEqual(plan,[]) # exact 15s and 5s boundaries: 109/110 and 209/210
        c.headers_by_number.pop(110)
        plan,_=_indexed_header_plan(c,h(250),1)
        self.assertNotEqual(plan,[]) # a timestamp hint cannot replace successor proof
    def test_factory_hint_does_not_skip_current_reads(self):
        from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
        ctx=SelectiveEvidenceContext('https://robinhood-mainnet.g.alchemy.com/v2/offline')
        self.assertIsNone(ctx.factory_token_hint('curve'))
        # Cached identity merely shapes a pinned request; no factory result cache.
        ctx.factory_hints['curve']='token'
        self.assertEqual(ctx.factory_token_hint('CURVE'),'token')
        self.assertFalse(ctx.block_reads)
