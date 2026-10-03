import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.lanes.pons import BoundaryError, CHAIN_ID
from meme_machine.lanes.pons.immutable_rpc import EvidenceStore, Reuse, choose_block_receipts
from meme_machine.lanes.pons.provider_topology import PacedRpc

class ImmutableRpcTest(unittest.TestCase):
    def setUp(self):
        self.store=EvidenceStore();self.reuse=Reuse('https://unit.invalid/key',self.store,'pons')
    def test_session_chain_verified_once_not_across_new_session(self):
        r=self.reuse;r.remember('eth_chainId',[],hex(CHAIN_ID),None)
        self.assertTrue(r.lookup('eth_chainId',[])[0])
        self.assertFalse(Reuse('https://unit.invalid/key',self.store,'pons').lookup('eth_chainId',[])[0])
        with self.assertRaises(BoundaryError):r.remember('eth_chainId',[],'0x1',None)
    def test_hash_pinned_call_and_code_across_candidates(self):
        for m,p in [('eth_call',[{'to':'0xa','data':'0x12'},'0x1']),('eth_getCode',['0xa','0x1'])]:
            key=self.reuse.key(m,p,{'0x1':'0xh1'})
            self.reuse.remember(m,p,'0x123',key)
            other=Reuse('https://unit.invalid/key',self.store,'ramses')
            self.assertEqual(other.lookup(m,p,{'0x1':'0xh1'})[:2],(True,'0x123'))
            self.assertFalse(other.lookup(m,p,{'0x1':'0xreorg'})[0])
            self.assertFalse(other.lookup(m,p,{})[0])
    def test_overrides_and_other_block_are_distinct(self):
        a=self.reuse.key('eth_call',[{'to':'a','data':'b'},'0x1'],{'0x1':'h1'})
        b=self.reuse.key('eth_call',[{'to':'a','data':'b'},'0x2'],{'0x2':'h2'})
        c=self.reuse.key('eth_call',[{'to':'a','data':'b'},'0x1',{'a':{'balance':'0x1'}}],{'0x1':'h1'})
        self.assertEqual(len({a,b,c}),3)
        self.assertIsNone(self.reuse.key('eth_call',[{},'latest']))
    def test_header_number_and_hash_share_identity(self):
        h={'number':'0x1','hash':'h1','timestamp':'0x2','parentHash':'h0'}
        self.reuse.remember('eth_getBlockByNumber',['0x1',False],h,None)
        self.assertEqual(self.reuse.lookup('eth_getBlockByHash',['h1',False])[1],h)
        self.assertEqual(self.reuse.lookup('eth_getBlockByNumber',['0x1',False],{'0x1':'h1'})[1],h)
        self.assertFalse(self.reuse.lookup('eth_getBlockByNumber',['latest',False])[0])
    def test_receipt_requires_expected_block(self):
        p=['tx'];k=self.reuse.key('eth_getTransactionReceipt',p,receipts={'tx':'h1'})
        self.reuse.remember('eth_getTransactionReceipt',p,{'transactionHash':'tx','blockHash':'h1'},k)
        self.assertTrue(self.reuse.lookup('eth_getTransactionReceipt',p,receipts={'tx':'h1'})[0])
        self.assertFalse(self.reuse.lookup('eth_getTransactionReceipt',p,receipts={'tx':'h2'})[0])
        with self.assertRaises(BoundaryError):self.reuse.remember('eth_getTransactionReceipt',p,{'transactionHash':'tx','blockHash':'h2'},k)
    def test_exact_log_filter_and_immutable_bounds(self):
        p=[{'fromBlock':'0x1','toBlock':'0x1','topics':['topic']}];pins={'0x1':'h1','0x2':'h2'}
        k=self.reuse.key('eth_getLogs',p,pins);self.reuse.remember('eth_getLogs',p,[],k)
        self.assertEqual(self.reuse.lookup('eth_getLogs',p,pins)[:2],(True,[]))
        self.assertFalse(self.reuse.lookup('eth_getLogs',[dict(p[0],topics=['other'])],pins)[0])
        self.assertIsNone(self.reuse.key('eth_getLogs',[{'fromBlock':'0x1','toBlock':'latest'}],pins))
    def test_endpoint_domain_and_conflict_fail_closed(self):
        self.store.put(self.reuse.domain,'k',1)
        self.assertIsNone(self.store.get(Reuse('https://other.invalid',self.store).domain,'k'))
        with self.assertRaises(BoundaryError):self.store.put(self.reuse.domain,'k',2)
    def test_block_receipts_rule_throughput_and_size_guard(self):
        self.assertTrue(choose_block_receipts(25,40,supported=True,remaining_seconds=2))
        for n,total,supported,remaining in [(2,2,True,2),(25,100,True,2),(100,200,True,2),(25,40,False,2),(25,40,True,.1)]:
            self.assertFalse(choose_block_receipts(n,total,supported=supported,remaining_seconds=remaining))
    def test_batch_deduplicates_and_expired_miss_does_not_transport(self):
        seen=[]
        rpc=PacedRpc('https://unit.invalid',role='test',requests_per_second=2,
            transport=lambda m,p: seen.append((m,p)) or '0x123')
        rpc.evidence_reuse=self.reuse;rpc.hash_state_supported={'eth_getCode','eth_call'};rpc.evidence_pins={'0x1':'h1'}
        call=('eth_getCode',['a','0x1'])
        self.assertEqual(rpc.batch([call,call]),['0x123','0x123']);self.assertEqual(len(seen),1)
        rpc.evidence_deadline=time.monotonic()-1
        with self.assertRaises(BoundaryError):rpc.batch([('eth_getCode',['b','0x1'])])
        self.assertEqual(len(seen),1)
    def test_raw_reuse_history_is_append_only(self):
        self.reuse.lookup('eth_chainId',[])
        with self.assertRaises(Exception):self.store.db.execute('DELETE FROM reuse_events')
    def test_concurrent_same_identity_executes_once(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        seen=[];started=threading.Event();release=threading.Event()
        def transport(m,p):
            seen.append(m);started.set();release.wait(2);return '0x123'
        def rpc(lane):
            r=PacedRpc('https://unit.invalid/key',role='test',requests_per_second=2,transport=transport)
            r.evidence_reuse=Reuse('https://unit.invalid/key',self.store,lane);r.hash_state_supported={'eth_getCode','eth_call'};r.evidence_pins={'0x1':'h1'}
            return r
        a,b=rpc('pons'),rpc('ramses')
        with ThreadPoolExecutor(2) as pool:
            x=pool.submit(a.call,'eth_getCode',['a','0x1']);self.assertTrue(started.wait(1))
            y=pool.submit(b.batch,[('eth_getCode',['a','0x1'])]);time.sleep(.02);release.set()
            self.assertEqual(x.result(),'0x123');self.assertEqual(y.result(),['0x123'])
        self.assertEqual(seen,['eth_getCode'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM flights').fetchone()[0],0)
    def test_waiter_keeps_own_deadline(self):
        with self.store.lease(self.reuse.domain,['k']):
            with self.assertRaisesRegex(BoundaryError,'immutable_evidence_wait_deadline'):
                with self.store.lease(self.reuse.domain,['k'],time.monotonic()):pass
    def test_gas_quote_same_epoch_after_original_observation_only(self):
        observed=time.monotonic()-1;deadline=observed+5
        hit,value,key=self.reuse.lookup('eth_gasPrice',[],cost_epoch=('h1',observed,deadline))
        self.assertFalse(hit);self.reuse.remember('eth_gasPrice',[],'0x123',key)
        self.assertTrue(self.reuse.lookup('eth_gasPrice',[],cost_epoch=('h1',observed,deadline))[0])
        self.assertFalse(self.reuse.lookup('eth_gasPrice',[],cost_epoch=('h2',observed,deadline))[0])
        self.assertFalse(self.reuse.lookup('eth_gasPrice',[],cost_epoch=('h1',time.monotonic(),deadline))[0])
        self.assertFalse(self.reuse.lookup('eth_gasPrice',[],cost_epoch=('h1',observed,time.monotonic()-1))[0])

    def test_numeric_pin_must_be_used_on_wire_not_only_cache_key(self):
        seen=[]
        rpc=PacedRpc('https://unit.invalid',role='test',requests_per_second=2,
            transport=lambda m,p: seen.append((m,p)) or '0x123')
        rpc.evidence_reuse=self.reuse;rpc.evidence_pins={'0x1':'h1'}
        rpc.call('eth_getCode',['a','0x1']);rpc.call('eth_getCode',['a','0x1'])
        self.assertEqual(len(seen),2)  # Unknown support: original safe path, no reuse.
        rpc.hash_state_supported={'eth_getCode','eth_call'}
        rpc.call('eth_getCode',['a','0x1']);rpc.call('eth_getCode',['a','0x1'])
        self.assertEqual(len(seen),3);self.assertEqual(seen[-1][1][1],{'blockHash':'h1'})
    def test_header_reorg_cannot_poison_pinned_alias(self):
        p=['0x1',False];k=self.reuse.key('eth_getBlockByNumber',p,{'0x1':'h1'})
        with self.assertRaisesRegex(BoundaryError,'immutable_header_pin_disagreement'):
            self.reuse.remember('eth_getBlockByNumber',p,{'number':'0x1','hash':'other'},k)
        self.assertIsNone(self.store.get(self.reuse.domain,k))
    def test_log_reorg_and_numeric_range_not_cached(self):
        self.assertIsNone(self.reuse.key('eth_getLogs',[{'fromBlock':'0x1','toBlock':'0x2'}],{'0x1':'h1','0x2':'h2'}))
        p=[{'blockHash':'h1'}];k=self.reuse.key('eth_getLogs',p)
        with self.assertRaisesRegex(BoundaryError,'immutable_log_block_disagreement'):
            self.reuse.remember('eth_getLogs',p,[{'blockHash':'other'}],k)
