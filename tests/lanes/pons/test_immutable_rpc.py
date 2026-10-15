import os
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

    @unittest.skipUnless(os.environ.get('MM_PONS_REUSE_RETAINED_FIXTURE'),
        'opt-in retained audit discriminator; no production or provider access')
    def test_retained_reuse_ring_index_discriminator(self):
        """Actual cache accounting only; authentic audit rows are not market replay."""
        from collections import Counter
        from dataclasses import replace
        import hashlib
        import json
        import signal
        import socket
        import threading
        from meme_machine.operational.artifact_storage import Scratch,Policy,tree_bytes
        self.assertTrue(getattr(socket.socket.connect,'meme_machine_offline',False),
            'run through python -m operational.tests OPERATIONAL --cases')
        fixture=Path(os.environ['MM_PONS_REUSE_RETAINED_FIXTURE'])
        self.assertFalse(fixture.is_symlink());self.assertLessEqual(fixture.stat().st_size,1024**2)
        raw=fixture.read_bytes();checksum=hashlib.sha256(raw).hexdigest()
        self.assertEqual(checksum,'c397efb312c31522294d0ec50b326e2c0d8e6e78c86e3107fc0616099386b018')
        source=json.loads(raw);columns=('sequence','lane','domain','method','outcome','at','key_digest','source_at')
        self.assertEqual(source['columns'],list(columns));rows=source['rows']
        self.assertEqual(len(rows),4096);self.assertTrue(all(len(row)==8 for row in rows))
        self.assertEqual([row[0] for row in rows],list(range(277340,281436)))
        self.assertEqual(source['provider_requests'],0)
        first=min(row[5] for row in rows);last=max(row[5] for row in rows)
        event_rate=(len(rows)-1)/(last-first)
        def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
        def io_counts():
            path=Path('/proc/self/task')/str(threading.get_native_id())/'io'
            return {key:int(value) for key,value in
                (line.split(':',1) for line in path.read_text().splitlines())}
        def deadline(signum,frame):raise TimeoutError('reuse_discriminator_absolute_10s')
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL),(0.,0.),
            'discriminator must not replace an existing timer')
        old_handler=signal.signal(signal.SIGALRM,deadline)
        signal.setitimer(signal.ITIMER_REAL,10)
        begun=time.monotonic();variants=[]
        try:
            policy=replace(Policy.environment(),scratch_max_bytes=16*1024**2)
            with Scratch(policy=policy) as scratch:
                fixed_at=last+1;domain=rows[-1][2]
                for indexed in (False,True):
                    scratch.check();path=scratch.path/('indexed.sqlite' if indexed else 'original.sqlite')
                    store=EvidenceStore(path)
                    try:
                        with store.db:
                            store.db.executemany('INSERT INTO reuse_events VALUES(?,?,?,?,?,?,?,?)',rows)
                            if indexed:store.db.execute('CREATE INDEX probe_reuse_retention_sequence ON reuse_events(sequence)')
                        plans={name:store.db.execute('EXPLAIN QUERY PLAN '+sql).fetchall() for name,sql in (
                            ('count','SELECT COUNT(*) FROM reuse_events'),
                            ('boundary','SELECT sequence FROM reuse_events WHERE 1=1 ORDER BY sequence DESC LIMIT 1 OFFSET 4095'))}
                        reuse=Reuse('https://unit.invalid/retained-audit-probe',store,'pons')
                        # The retained digest is an identity, never a credential.
                        reuse.domain=domain
                        with patch('meme_machine.lanes.pons.immutable_rpc.time.time',return_value=fixed_at):
                            reuse.remember('eth_chainId',[],hex(CHAIN_ID),None)
                            totals=dict(wall_seconds=0.,cpu_seconds=0.);io=Counter();operations=Counter();vm=[0]
                            def trace(sql):
                                operations[sql.lstrip().split(None,1)[0].upper()]+=1
                                if sql.startswith('SELECT COUNT(*) FROM reuse_events'):operations['audit_count']+=1
                                if 'OFFSET 4095' in sql or ('ORDER BY sequence DESC LIMIT 1 OFFSET ' in sql):operations['audit_boundary']+=1
                            store.db.set_trace_callback(trace)
                            store.db.set_progress_handler(lambda:vm.__setitem__(0,vm[0]+1000) or 0,1000)
                            try:
                                for offset in range(0,32,8):
                                    # Guard scans and /proc probes are outside
                                    # the measured actual lookup calls.
                                    scratch.check();before=io_counts()
                                    wall=time.perf_counter();cpu=time.thread_time()
                                    answers=[reuse.lookup('eth_chainId',[]) for _ in range(8)]
                                    totals['cpu_seconds']+=time.thread_time()-cpu
                                    totals['wall_seconds']+=time.perf_counter()-wall
                                    after=io_counts();io.update({key:after[key]-before[key] for key in after})
                                    self.assertEqual(answers,[(True,hex(CHAIN_ID),None)]*8)
                            finally:
                                store.db.set_trace_callback(None);store.db.set_progress_handler(None,0)
                        retained=store.db.execute('SELECT * FROM reuse_events ORDER BY sequence').fetchall()
                        appended=[(281436+i,'pons',domain,'eth_chainId','session_hit',fixed_at,
                            hashlib.sha256(b'session').hexdigest(),fixed_at) for i in range(32)]
                        self.assertEqual(retained,[tuple(row) for row in rows[32:]]+appended)
                        self.assertEqual(reuse.telemetry(),{'eth_chainId:session_hit':32})
                        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM flights').fetchone(),(0,))
                        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM evidence').fetchone(),(0,))
                        self.assertTrue(store.db.execute("SELECT 1 FROM sqlite_master WHERE name='reuse_no_delete'").fetchone())
                        variants.append(dict(indexed=indexed,calls=32,**totals,thread_io=dict(io),
                            sql_operations=dict(operations),vm_steps_quantized=vm[0],vm_quantum=1000,
                            retained_sha256=hashlib.sha256(encoded(retained)).hexdigest(),query_plans=plans,
                            physical_transports=0,logical_session_hits=32))
                    finally:store.db.close()
                    scratch.check()
                self.assertEqual(variants[0]['retained_sha256'],variants[1]['retained_sha256'])
                observed=dict(scope='owner-reported rounded O11 process observations; not this fixture',
                    rchar_bytes=105.56*10**9,seconds=368.6,cpu_cores=.674)
                observed['rchar_bytes_per_second']=observed['rchar_bytes']/observed['seconds']
                normalization=[]
                for variant in variants:
                    cpu_rate=variant['cpu_seconds']/32*event_rate
                    read_rate=variant['thread_io']['rchar']/32*event_rate
                    normalization.append(dict(indexed=variant['indexed'],
                        projected_cpu_cores=cpu_rate,projected_rchar_bytes_per_second=read_rate,
                        fraction_of_reported_process_cpu=cpu_rate/observed['cpu_cores'],
                        fraction_of_reported_process_rchar=read_rate/observed['rchar_bytes_per_second']))
                result=dict(schema='retained-reuse-audit-index-discriminator-v1',
                    scope='authentic retained audit ring; synthetic32 session-hit calls; no market/capacity proof',
                    fixture_sha256=checksum,fixture_bytes=len(raw),retained_event_rate=event_rate,
                    retained_time_bounds=[first,last],variants=variants,normalization=normalization,
                    observation_reference=observed,provider_requests=0,authoritative_writes=False,
                    source_sha256={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in (
                        ('test',Path(__file__)),('immutable_rpc',Path(__import__(EvidenceStore.__module__,fromlist=['__file__']).__file__)),
                        ('storage',Path(__import__('meme_machine.runtime.storage',fromlist=['__file__']).__file__)))},
                    limitations=['sequential original then indexed; persistent connection warmed by identical seeding',
                        'trace/progress instrumentation identical in both variants; VM steps quantized',
                        'rchar/syscr include /proc probe overhead; no physical-disk or whole-machine inference',
                        'projection uses last retained278s event rate, not a complete O11 event census',
                        'no production index or accounting algorithm changed'],
                    fixture_peak_bytes=tree_bytes(scratch.path),elapsed_seconds=time.monotonic()-begun,
                    disposition='MEASURED_LOCAL_EFFECT_ONLY; reject as dominant cause if projected contribution is small')
                self.assertLessEqual(result['fixture_peak_bytes'],16*1024**2)
                self.assertLess(result['elapsed_seconds'],10)
                output=os.environ.get('MM_PONS_REUSE_DISCRIMINATOR_RESULT')
                if output:
                    target=Path(output).absolute()
                    self.assertEqual(target.parent,fixture.absolute().parent)
                    self.assertNotIn(scratch.path,target.parents)
                    payload=encoded(result)+b'\n';self.assertLess(len(payload),64*1024)
                    descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(descriptor,'wb') as stream:stream.write(payload)
                scratch.success=True
        finally:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old_handler)
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

    def test_capacity_evicts_only_excess_without_rebuilding_the_retained_set(self):
        db=self.store.db
        with db:db.executemany('INSERT INTO evidence VALUES(?,?,?,?)',
            [('domain',str(n),str(n),float(n)) for n in range(8192)])
        steps=[];db.set_progress_handler(lambda:steps.append(1) or 0,1000)
        try:
            with patch('meme_machine.lanes.pons.immutable_rpc.time.time',return_value=8192.):
                self.store.put('domain','new',8192)
            self.assertEqual(steps,[],'cache put rescanned every retained entry')
            steps.clear();self.store.put('domain','10',10)
            self.assertEqual(steps,[],'duplicate cache put rebuilt the eviction set')
        finally:db.set_progress_handler(None,0)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],8192)
        self.assertIsNone(self.store.get('domain','0'))
        self.assertEqual(self.store.get('domain','10'),(10,10.))
        self.assertEqual(self.store.get('domain','new'),(8192,8192.))
        with self.assertRaisesRegex(BoundaryError,'immutable_rpc_evidence_conflict'):
            self.store.put('domain','10',11)

    def test_overfull_restored_cache_keeps_the_same_original_retention_order(self):
        db=self.store.db
        with db:db.executemany('INSERT INTO evidence VALUES(?,?,?,?)',
            [('domain',str(n),str(n),float(n//2)) for n in range(8200)])
        expected={r[0] for r in db.execute('SELECT key FROM evidence ORDER BY created DESC,rowid LIMIT 8192')}
        self.store.put('domain','8199',8199)
        self.assertEqual({r[0] for r in db.execute('SELECT key FROM evidence')},expected)
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
