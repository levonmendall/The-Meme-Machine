"""Offline parity, cache fencing, exact expiry and operation-count regressions."""
import base64
import copy
import gzip
import json
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime.robinhood.plane import Plane, canonical
from meme_machine.runtime.robinhood.ramses_window import Window, KEY
from meme_machine import solana_program_decoders as codecs
from meme_machine.solana_evidence_service import decode_source_message, program_subscriptions, prepare_block_scope, program_decoders


class ImmutableEfficiency(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'plane.sqlite'
        self.now=100.;self.p=Plane(self.path,clock=lambda:self.now)
    def tearDown(self):self.p.close();self.tmp.cleanup()

    def test_warm_reads_no_evidence_select_or_duplicate_commit(self):
        self.p.put('pons:receipt','tx',{'value':[1]},{'authority':'authenticated'})
        sql=[];self.p.db.set_trace_callback(sql.append)
        for _ in range(200):
            value,proof=self.p.evidence('pons:receipt','tx');value['value'].append(9)
            self.p.put('pons:receipt','tx',{'value':[1]},proof)
        self.assertFalse(any('FROM evidence' in s for s in sql))
        self.assertFalse(any(s=='COMMIT' for s in sql))
        self.assertEqual(self.p.evidence('pons:receipt','tx')[0],{'value':[1]})

    def test_immutable_conflict_and_external_eviction(self):
        self.p.put('pons:receipt','tx',{},{});self.p.evidence('pons:receipt','tx')
        with self.assertRaisesRegex(ValueError,'canonical_evidence_conflict'):self.p.put('pons:receipt','tx',{'changed':1},{})
        other=Plane(self.path)
        try:other.db.execute("DELETE FROM evidence WHERE key='tx'")
        finally:other.close()
        self.assertIsNone(self.p.evidence('pons:receipt','tx'))
        self.p.put('pons:receipt','tx',{},{});self.p.close();self.p=Plane(self.path)
        self.assertEqual(self.p.evidence('pons:receipt','tx'),({},{}))

    def test_immutable_warm_facts_survive_unrelated_candidate_maintenance(self):
        self.p.put('pons:receipt','tx',{'body':1},{'authority':'authenticated'})
        self.p.maintain();self.observe(1)
        self.p.maintain();sql=[];self.p.db.set_trace_callback(sql.append)
        for _ in range(200):self.p.evidence('pons:receipt','tx')
        self.assertFalse(any('FROM evidence' in s for s in sql))

    def test_bounded_positive_cache_no_negative_cache(self):
        for n in range(1100):self.p.put('receipt',str(n),{'n':n},{})
        self.assertLessEqual(len(self.p._immutable),1024)
        self.assertLessEqual(self.p._immutable_bytes,16*1024*1024)
        self.assertIsNone(self.p.evidence('receipt','missing'))
        other=Plane(self.path)
        try:other.put('receipt','missing',{'new':1},{})
        finally:other.close()
        self.assertEqual(self.p.evidence('receipt','missing')[0],{'new':1})

    def test_unchanged_checkpoint_no_commit_mutable_checkpoint_fresh(self):
        self.p.checkpoint('mutable',{'n':1});sql=[];self.p.db.set_trace_callback(sql.append)
        for _ in range(200):self.p.checkpoint('mutable',{'n':1})
        self.assertFalse(any(s=='COMMIT' for s in sql))
        other=Plane(self.path)
        try:other.checkpoint('mutable',{'n':2})
        finally:other.close()
        self.assertEqual(self.p.checkpoint_read('mutable'),{'n':2})

    def observe(self,n,**kwargs):
        return self.p.observe(str(n),'pons',str(n),{},ordering=(n,),watermark={},interpretation={},
                              observed=self.now,deadline=self.now+10,priority=2,**kwargs)

    def test_idle_maintenance_bounded_and_age_boundary_exact(self):
        for n in range(1000):self.observe(n,needs_work=False)
        self.p.maintain();steps=[0]
        def progress():steps[0]+=1;return 0
        self.p.db.set_progress_handler(progress,1)
        for _ in range(20):self.p.maintain()
        self.p.db.set_progress_handler(None,0)
        self.assertLess(steps[0],500)
        self.now+=86400;self.p.maintain();self.assertIsNotNone(self.p.get('0'))
        self.now+=.01;self.p.maintain();self.assertIsNone(self.p.get('0'))
        self.assertEqual(self.p.history_archive()['retired_ordering']['pons'],[999])

    def test_other_connection_and_active_pins_force_maintenance(self):
        self.observe(1,needs_work=False)
        self.p.checkpoint('native_position:x',{'candidate':'1','position':{'status':'open'}})
        self.p.maintain();self.now+=86401;self.p.maintain()
        self.assertIsNotNone(self.p.get('1'))
        other=Plane(self.path)
        try:other.checkpoint('native_position:x',{'candidate':'1','position':{'status':'settled'}})
        finally:other.close()
        self.p.maintain();self.assertIsNone(self.p.get('1'))

    def test_rolling_duplicate_enforces_new_retention_without_noop_commit(self):
        proof={'authority':'authenticated_receipt_header'}
        self.p.rolling_put('c','a',10,1,{},proof)
        self.p.rolling_put('c','b',20,2,{},proof)
        sql=[];self.p.db.set_trace_callback(sql.append)
        self.p.rolling_put('c','b',20,2,{},proof)
        self.assertNotIn('COMMIT',sql)
        self.p.rolling_put('c','b',20,2,{},proof,retention_seconds=5)
        self.assertIsNone(self.p.rolling_get('c','a',proof))


class LocalSolanaEfficiency(unittest.TestCase):
    def test_pump_program_data_once_without_changing_event_order(self):
        raw=base64.b64encode(b'not an event'+b'x'*250).decode()
        tx={'slot':7,'meta':{'err':None,'logMessages':[
            'Program '+codecs.pump.PROGRAM+' invoke [1]',
            'Program data: '+raw,'Program '+codecs.pump.PROGRAM+' success']}}
        with patch.object(codecs.base64,'b64decode',wraps=base64.b64decode) as calls:
            self.assertEqual(codecs.pump_events(tx),[]);self.assertEqual(calls.call_count,1)
        tx['meta']['logMessages'][1]='Program data: !invalid!'
        with self.assertRaises(ValueError):codecs.pump_events(tx)

    def test_prepared_scope_bytes_match_standalone_and_pickle(self):
        fixture=Path(__file__).parent/'fixtures/solana_evidence_plane/run380-production-templates.json.gz'
        templates=json.loads(gzip.decompress(fixture.read_bytes()))['templates']
        txs=[]
        for family in templates.values():
            for tx in family[:4]:txs.append(copy.deepcopy(tx))
        # Loaded addresses must remain part of relevance and canonical addresses.
        tx=copy.deepcopy(txs[0]);tx['transaction']['signatures']=['loaded']
        keys=tx['transaction']['message']['accountKeys'];tx['meta']['loadedAddresses']={'readonly':keys,'writable':[]}
        tx['transaction']['message']['accountKeys']=[];txs.append(tx)
        msg={'method':'blockNotification','params':{'result':{'value':{'slot':9,'block':{
            'parentSlot':8,'blockhash':'h9','previousBlockhash':'h8','blockTime':10,'transactions':txs}}}}}
        subs=[s for s in program_subscriptions() if s.evidence_class!='logs']
        prepared,total,retained=decode_source_message(json.dumps(msg),'',[s.address for s in subs],'0'*64,2000000000.)
        self.assertEqual(total,len(txs));self.assertEqual(retained,len(txs))
        for sub in subs:
            standalone=prepare_block_scope(sub,msg,2000000000.,'0'*64,program_decoders(),include_logs=True,budget=[16*1024*1024])
            self.assertEqual(prepared.scopes[sub.scope],standalone)
        transferred=pickle.loads(pickle.dumps(prepared))
        for scope,value in prepared.scopes.items():
            for batch,original in zip(transferred.scopes[scope]['batches'],value['batches']):
                for row,old in zip(batch,original):
                    self.assertEqual((row.encoded,row.chunks,row.checksum),(old.encoded,old.chunks,old.checksum))
                    self.assertEqual(row.record.payload,{})


class IncrementalRamses(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'p.sqlite';self.p=Plane(self.path)
        self.logs=[self.event(n) for n in range(1,101)];self.fetched=[];self.decoded_count=0;self.changed=False
        self.window=Window(self.p,'same-source',self.fetch,self.decode)
    def tearDown(self):self.p.close();self.tmp.cleanup()
    def event(self,n,address='a'):
        return dict(address=address,blockNumber=hex(n),blockHash='h'+str(n),transactionHash='t'+str(n),transactionIndex='0x0',logIndex='0x0',removed=False)
    def call(self,method,params,scope):
        n=int(params[0],16);return dict(number=hex(n),hash=('changed' if self.changed else 'h')+str(n))
    def fetch(self,rpc,start,end,addresses,progress=None):
        if start>end or not addresses:return []
        self.fetched.append((start,end,tuple(addresses)))
        return copy.deepcopy([e for e in self.logs if start<=int(e['blockNumber'],16)<=end and e['address'] in addresses])
    def decode(self,logs,addresses):
        self.decoded_count+=len(logs);by={};costs=[]
        for e in sorted(logs,key=lambda e:tuple(int(e[k],16) for k in ('blockNumber','transactionIndex','logIndex'))):
            if e['address'] not in addresses or e['removed']:raise ValueError('log_identity')
            by.setdefault(e['address'],[]).append({'block':int(e['blockNumber'],16),'value':e['transactionHash']})
            costs.append({'block':int(e['blockNumber'],16),'pool':e['address']})
        return by,costs
    def run_window(self,start,end,addresses=('a',)):
        logs=self.window.collect(self,start,end,addresses)
        result=self.window.decoded(logs,addresses)
        expected=self.decode(self.fetch(self,start,end,addresses),addresses)
        self.assertEqual(result,expected)
        return result
    def test_tail_only_exact_expiry_restart_and_single_new_decode(self):
        self.run_window(1,100);self.fetched.clear();self.decoded_count=0
        self.logs.append(self.event(101));logs=self.window.collect(self,2,101,('a',));self.window.decoded(logs,('a',))
        self.assertEqual(self.fetched,[(101,101,('a',))]);self.assertEqual(self.decoded_count,1)
        self.assertEqual(min(int(e['blockNumber'],16) for e in logs),2)
        self.p.close();self.p=Plane(self.path);self.window=Window(self.p,'same-source',self.fetch,self.decode)
        self.fetched.clear();self.decoded_count=0;self.run_window(2,101)
        # Only the explicit comparison used full fetch/decode after restart.
        self.assertEqual(self.fetched,[(2,101,('a',))]);self.assertEqual(self.decoded_count,100)
    def test_new_pool_full_current_window_catchup(self):
        self.run_window(1,100);self.logs.extend([self.event(50,'b'),self.event(101)]);self.fetched.clear()
        self.run_window(2,101,('a','b'))
        self.assertEqual(self.fetched[:2],[(101,101,('a',)),(2,101,('b',))])
    def test_changed_anchor_and_regressed_frontier_refresh_all(self):
        self.run_window(1,100);self.changed=True;self.fetched.clear()
        self.run_window(2,101);self.assertEqual(self.fetched[0],(2,101,('a',)))
        self.fetched.clear();self.run_window(1,50);self.assertEqual(self.fetched[0],(1,50,('a',)))
    def test_failed_fetch_preserves_checkpoint(self):
        self.run_window(1,100);old=self.p.checkpoint_read(KEY)
        self.window.fetch=lambda *args:(_ for _ in ()).throw(ValueError('missing_page'))
        with self.assertRaises(ValueError):self.window.collect(self,2,101,('a',))
        self.assertEqual(self.p.checkpoint_read(KEY),old)
    def test_bounded_cache_and_projection_corruption(self):
        self.run_window(1,100);row=self.p.checkpoint_read(KEY);row['decoded'].clear();self.p.checkpoint(KEY,row)
        self.fetched.clear();self.run_window(2,101);self.assertEqual(self.fetched[0],(2,101,('a',)))
        self.window.max_rows=1;self.run_window(2,101);self.assertIsNone(self.p.checkpoint_read(KEY))
    def test_empty_window_and_duplicate_outputs_preserved(self):
        self.logs=[];self.run_window(1,10);self.run_window(2,11)
        self.logs=[self.event(12),self.event(12)];self.run_window(3,12)


if __name__=='__main__':unittest.main()
