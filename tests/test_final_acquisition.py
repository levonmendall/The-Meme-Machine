"""Dispatch, publication and immutable-batch regressions; no market I/O."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tests.test_solana_closure import state_at, NOW
from meme_machine.solana_evidence_plane import IntervalProof, digest, EvidenceReader
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import coverage_scope, CandidateReader
from meme_machine.lanes.pump.solana_immutable_rpc import ImmutableReads
from meme_machine.lanes.pump.solana_read_rpc import ReadOnlyFailoverRPC
from meme_machine.lanes.pump.provider import Unavailable
from meme_machine.lanes.pons.immutable_rpc import EvidenceStore, Reuse
from meme_machine.lanes.pons.provider_topology import PacedRpc
from meme_machine.lanes.pons import BoundaryError


class OperationalWiringTests(unittest.TestCase):
    def test_lane_and_worker_reuse_existing_pump_broker_without_state_migration(self):
        from meme_machine.operational.supervisor import Supervisor
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);service=Supervisor(root);service.epoch='preserved-paper-epoch'
            with patch.dict(os.environ,MM_SOLANA_EVIDENCE_BROKER_DB='/unrelated/old.sqlite'):
                lane=service.environment('pump');worker=service.environment('solana')
            expected=str(root/'pump/solana-evidence-broker.sqlite3')
            self.assertEqual(lane['MM_SOLANA_EVIDENCE_BROKER_DB'],expected)
            self.assertEqual(worker['MM_SOLANA_EVIDENCE_BROKER_DB'],expected)
            self.assertNotIn('MM_SOLANA_EVIDENCE_BROKER_DB',service.environment('pons'))
            self.assertEqual(list(root.iterdir()),[])
            (root/'shared').mkdir();(root/'shared/solana-evidence.sqlite.sock').touch()
            def spawn(*args,**kwargs):
                self.assertTrue((root/'pump').is_dir())
                self.assertEqual(kwargs['env']['MM_SOLANA_EVIDENCE_BROKER_DB'],expected)
                self.assertFalse(Path(expected).exists())
                return SimpleNamespace(poll=lambda:None)
            with patch('meme_machine.operational.supervisor.subprocess.Popen',side_effect=spawn):
                service.start_services()
            self.assertFalse((root/'portfolio.sqlite').exists())
            self.assertEqual(service.epoch,'preserved-paper-epoch')


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'canonical.sqlite';self.now=[NOW]
        self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.addCleanup(lambda:self.state.writer.close())
        self.h.bind('pumpswap','pool');self.scope=coverage_scope('pumpswap','pool')

    def request(self,lo=100,hi=120,priority=3,deadline=None,address='pool'):
        return self.h.request('pumpswap',address,lo,hi,priority=priority,deadline=deadline or NOW+150)

    def seal(self,lo,hi,scope=None,pending=False):
        scope=scope or program_scope('pumpswap')
        proof=IntervalProof(scope,lo,hi,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=hi,lineage_hash=digest([scope,lo,hi])),self.now[0])
        if pending:self.h.lifecycle.defer_proof(proof)
        else:self.h.prove(proof)

    def test_rolling_publication_after_enqueue_eliminates_the_entire_request(self):
        identity=self.request();self.seal(100,120)
        before=list(self.h.db.execute('SELECT scope,points,hash FROM candidate_coverage'))
        self.assertIsNone(self.h.plan())
        self.assertEqual(self.h.db.execute('SELECT status,pages,deadline,lo,hi FROM acquisition_jobs WHERE id=?',(identity,)).fetchone(),
            ('complete',0,NOW+150,100,120))
        self.assertEqual(list(self.h.db.execute('SELECT scope,points,hash FROM candidate_coverage')),before)
        with closing(EvidenceReader(self.path)) as reader:
            self.assertTrue(CandidateReader(reader,'pumpswap','pool').covered(self.scope,100,120,as_of=NOW))

    def test_pending_publication_waits_without_fabricating_coverage(self):
        identity=self.request();self.seal(100,120,pending=True)
        self.assertIsNone(self.h.plan())
        self.assertEqual(self.h.rolling.missing('pumpswap',self.scope,100,120),[(100,120)])
        self.assertEqual(self.h.db.execute('SELECT status,deadline FROM acquisition_jobs WHERE id=?',(identity,)).fetchone(),('pending',NOW+150))
        self.h.lifecycle.publish();self.assertIsNone(self.h.plan())
        self.assertEqual(self.h.rolling.missing('pumpswap',self.scope,100,120),[])

    def test_partial_overlap_shares_flight_then_buys_only_the_missing_tail(self):
        leader=self.request();job=self.h.plan()[0]
        follower=self.request(110,130,priority=0,deadline=NOW+75)
        self.assertIsNone(self.h.plan(excluding=(leader,)))
        self.assertEqual(self.h.db.execute('SELECT priority,deadline FROM acquisition_jobs WHERE id=?',(leader,)).fetchone(),(0,NOW+75))
        self.h.commit_page(job,dict(data=[]),finalized_through=130);self.h.lifecycle.publish()
        remaining,config=self.h.plan()
        self.assertEqual((remaining['lo'],remaining['hi'],remaining['deadline'],remaining['priority']),(121,130,NOW+75,0))
        self.assertEqual(config['filters']['slot'],dict(gte=121,lte=130))
        self.h.commit_page(remaining,dict(data=[]),finalized_through=130);self.h.lifecycle.publish()
        self.assertIsNone(self.h.plan())
        self.assertEqual(self.h.db.execute('SELECT status,lo,hi,deadline FROM acquisition_jobs WHERE id=?',(follower,)).fetchone(),('complete',110,130,NOW+75))
        self.assertEqual(self.h.rolling.missing('pumpswap',self.scope,100,130),[])

    def test_authenticated_aliases_share_work_but_unrelated_pools_keep_priority(self):
        self.h.bind('pumpswap','pool',aliases=('alias',))
        leader=self.request();self.request(address='alias')
        safety=self.request(address='another-pool',priority=0)
        selected,_=self.h.plan(excluding=(leader,))
        self.assertEqual(selected['id'],safety)
        self.assertEqual(self.h.scope_for('pumpswap','alias'),self.scope)

    def test_restart_retains_missing_children_and_original_deadline(self):
        original=self.request();self.seal(100,109);self.seal(116,120)
        first=self.h.plan()[0];self.assertEqual((first['lo'],first['hi']),(110,115))
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        again=self.h.plan()[0];self.assertEqual(again,first)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],2)
        self.h.commit_page(again,dict(data=[]),finalized_through=120);self.h.lifecycle.publish()
        self.assertIsNone(self.h.plan())
        self.assertEqual(self.h.db.execute('SELECT status,deadline FROM acquisition_jobs WHERE id=?',(original,)).fetchone(),('complete',NOW+150))

    def test_publication_wait_does_not_renew_or_bypass_expired_deadline(self):
        identity=self.request(deadline=NOW+1);self.seal(100,120,pending=True)
        self.assertIsNone(self.h.plan());self.now[0]=NOW+2
        self.h.lifecycle.publish();self.assertIsNone(self.h.plan())
        self.assertEqual(self.h.db.execute('SELECT status,deadline FROM acquisition_jobs WHERE id=?',(identity,)).fetchone(),('deadline_missed',NOW+1))

    def test_partial_paid_page_retains_its_cursor_and_original_bounds(self):
        self.request();job=self.h.plan()[0]
        self.h.commit_page(job,dict(data=[],paginationToken='next-page'),finalized_through=120)
        self.seal(100,109)
        again,config=self.h.plan()
        self.assertEqual((again['lo'],again['hi'],again['pages'],config['paginationToken']),(100,120,1,'next-page'))
        self.assertEqual(again['deadline'],NOW+150)

    def test_unsealed_gap_is_repaired_and_other_candidates_are_never_excluded(self):
        self.seal(100,120,scope=self.scope);self.h.gap(self.scope,105,106,'disconnect')
        self.request();repair,_=self.h.plan()
        self.assertEqual((repair['lo'],repair['hi']),(105,106))
        other=self.request(address='quiet-late-winner')
        self.assertEqual(self.h.plan(excluding=(repair['id'],))[0]['id'],other)


class ImmutableBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'existing-broker.sqlite')
        self.url='https://solana-mainnet.g.alchemy.com/v2/'+('x'*32)
        self.env=patch.dict(os.environ,MM_SOLANA_EVIDENCE_BROKER_DB=self.path)
        self.env.start();self.addCleanup(self.env.stop)
        self.shared=ImmutableReads(self.path,self.url);self.shared.finalized(120)

    def test_saved_batch_workload_uses_one_read_per_unique_finalized_time(self):
        seen=[]
        def fetch(params):seen.extend(params);return [1000+p[0] for p in params]
        values=self.shared.call_many('getBlockTime',[[100],[100],[101]],fetch)
        self.assertEqual(values,[1100,1100,1101]);self.assertEqual(seen,[[100],[101]])
        other=ImmutableReads(self.path,self.url)
        self.assertEqual(other.call_many('getBlockTime',[[101],[100]],fetch),[1101,1100])
        self.assertEqual(seen,[[100],[101]])
        self.assertEqual(other.call('getBlockTime',[100],lambda: self.fail('duplicate physical read')),1100)

    def test_batch_keeps_unfinalized_reads_fresh_and_nulls_uncached(self):
        seen=[]
        def fetch(params):seen.extend(params);return [None for _ in params]
        for _ in range(2):self.shared.call_many('getBlockTime',[[100],[121],[121]],fetch)
        self.assertEqual(seen,[[100],[121],[121],[100],[121],[121]])
        other=ImmutableReads(self.path,'https://solana-mainnet.g.alchemy.com/v2/other')
        self.assertFalse(other.eligible('getBlockTime',[100]))

    def test_batch_and_single_consumer_share_one_live_lease(self):
        started=threading.Event();release=threading.Event();calls=[]
        def fetch(params):calls.append(params);started.set();release.wait(2);return [1100]
        with ThreadPoolExecutor(2) as pool:
            first=pool.submit(self.shared.call_many,'getBlockTime',[[100]],fetch)
            self.assertTrue(started.wait(1))
            second=pool.submit(self.shared.call,'getBlockTime',[100],lambda:self.fail('second purchase'))
            release.set();self.assertEqual(first.result(),[1100]);self.assertEqual(second.result(),1100)
        self.assertEqual(calls,[[[100]]])
        with self.shared.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM solana_read_leases').fetchone()[0],0)

    def test_rpc_batch_does_not_reenter_its_own_lease_or_reuse_fresh_accounts(self):
        seen=[]
        def transport(request):
            seen.append(request['method'])
            result=1100 if request['method']=='getBlockTime' else dict(context=dict(slot=120),value=[])
            return dict(id=request['id'],result=result)
        for _ in range(2):
            rpc=ReadOnlyFailoverRPC(self.url,transport=transport,sleeper=lambda _:None)
            self.assertEqual(rpc.call_many('getBlockTime',[[100],[100]]),[1100,1100])
            rpc.call('getMultipleAccounts',[['a'],dict(commitment='finalized')],True)
        self.assertEqual(seen,['getBlockTime','getMultipleAccounts','getMultipleAccounts'])
        with self.assertRaisesRegex(Unavailable,'consumer_deadline'):
            self.shared.call_many('getBlockTime',[[100]],lambda _:[],deadline=time.time()-1)

    def test_source_reuses_lane_genesis_with_zero_additional_delivery_or_cu(self):
        from meme_machine.runtime.evidence_worker import RepairRPC
        from meme_machine.solana_provider_config import GENESIS
        self.shared.call('getGenesisHash',[],lambda:GENESIS)
        rpc=RepairRPC(self.url,None)
        with patch.object(rpc,'_call_delivered',side_effect=AssertionError('genesis bought twice')):
            rpc.validate_network()
            self.assertEqual(rpc.call_delivered('getGenesisHash',[]),(GENESIS,dict(bytes=0,cu=0,calls=0)))

    def test_one_client_concurrent_batch_guard_does_not_bypass_shared_single_read(self):
        from meme_machine.lanes.pump.solana_immutable_rpc import ImmutableRPCMixin
        entered=threading.Event();release=threading.Event();waiting=threading.Event();seen=[]
        class Parent:
            def call(self,method,params,priority=False,**kwargs):seen.append(method);return 1100
            def call_many(self,method,params,priority=False,batch_size=8):
                entered.set();release.wait(2)
                return [self.call(method,p,priority) for p in params]
        class Client(ImmutableRPCMixin,Parent):pass
        rpc=Client();rpc.url=self.url
        def wait(seconds):waiting.set();time.sleep(seconds)
        with patch('meme_machine.lanes.pump.solana_immutable_rpc._stop_sleep',side_effect=wait),ThreadPoolExecutor(2) as pool:
            batch=pool.submit(rpc.call_many,'getBlockTime',[[100]])
            self.assertTrue(entered.wait(1))
            single=pool.submit(rpc.call,'getBlockTime',[100])
            self.assertTrue(waiting.wait(1));release.set()
            self.assertEqual(batch.result(),[1100]);self.assertEqual(single.result(),1100)
        self.assertEqual(seen,['getBlockTime'])

    def test_live_expired_lease_is_not_stolen_and_dead_owner_is_recovered(self):
        owner=self.shared.lease_owner()
        with self.shared.connect() as db:
            db.execute('INSERT INTO solana_read_leases VALUES(?,?,?,?,?)',
                (self.shared.endpoint,'getBlockTime','[100]',owner,time.time()-1))
        with self.assertRaisesRegex(Unavailable,'consumer_deadline'):
            self.shared.call_many('getBlockTime',[[100]],lambda _:self.fail('live flight bought again'),deadline=time.time()+.03)
        with self.shared.connect() as db:
            self.assertEqual(db.execute('SELECT owner FROM solana_read_leases').fetchone()[0],owner)
            db.execute('UPDATE solana_read_leases SET owner=?',('dead:999999999:0|old',))
        self.assertEqual(self.shared.call_many('getBlockTime',[[100]],lambda _:[1100]),[1100])
        with self.shared.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM solana_read_leases').fetchone()[0],0)


class PonsSenderTests(unittest.TestCase):
    def test_historical_fallback_supplies_authenticated_canonical_block_pins(self):
        from engineering.pons_history.fixtures import Tape
        from engineering.robinhood_scout.replay import markets
        from meme_machine.lanes.pons.pons_history import PonsHistory
        from meme_machine.lanes.pons.pons_historical import Preparation,MANAGER,SWAP
        from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
        with tempfile.TemporaryDirectory() as folder:
            history=PonsHistory(Path(folder)/'history.sqlite',policy=POLICY_HASH)
            try:
                tape=Tape(candidates=1);first,last=tape.grad+1,tape.grad+4
                pool=markets(tape)[0]['key'].pool_id();query=dict(address=MANAGER,topics=[[SWAP],[pool]])
                logs=tape._read('eth_getLogs',[dict(query,fromBlock=hex(first),toBlock=hex(last))])
                preparation=Preparation(history,tape.provider);original=preparation.calls;pins=[]
                def acquire(calls,**kwargs):
                    if calls and calls[0][0]=='eth_getTransactionByHash':pins.append(kwargs.get('receipt_pins'))
                    return original(calls,**kwargs)
                with patch.object(preparation,'calls',side_effect=acquire):
                    result=preparation._witness(logs,query,first,last)
                self.assertEqual(pins,[{e['transactionHash']:e['blockHash'] for e in logs}])
                self.assertEqual(result['raw'],logs)
            finally:history.close()

    def test_pinned_fallback_sender_shared_across_current_and_survivor(self):
        store=EvidenceStore();self.addCleanup(store.db.close);seen=[]
        tx=dict(hash='tx',blockHash='block',**{'from':'0x'+'01'*20})
        def rpc(lane):
            r=PacedRpc('https://unit.invalid/key',role='test',requests_per_second=2,transport=lambda m,p:seen.append(m) or copy.deepcopy(tx))
            r.evidence_reuse=Reuse('https://unit.invalid/key',store,lane);r.evidence_receipts={'tx':'block'}
            return r
        self.assertEqual(rpc('current').call('eth_getTransactionByHash',['tx']),tx)
        self.assertEqual(rpc('survivor').batch([('eth_getTransactionByHash',['tx'])]),[tx])
        self.assertEqual(seen,['eth_getTransactionByHash'])
        reuse=Reuse('https://unit.invalid/key',store,'current')
        self.assertFalse(reuse.lookup('eth_getTransactionByHash',['tx'],receipts={'tx':'fork'})[0])
        self.assertIsNone(reuse.key('eth_getTransactionByHash',['tx']))
        key=reuse.key('eth_getTransactionByHash',['tx'],receipts={'tx':'fork'})
        with self.assertRaisesRegex(BoundaryError,'transaction_block_disagreement'):
            reuse.remember('eth_getTransactionByHash',['tx'],tx,key)


class SourceFlightTests(unittest.TestCase):
    def test_concurrent_finalized_repair_buys_once_and_counts_only_physical_delivery(self):
        from meme_machine.runtime.evidence_worker import RepairRPC
        rpc=RepairRPC('https://solana-mainnet.g.alchemy.com/v2/'+('x'*32),None)
        started=threading.Event();release=threading.Event();joined=threading.Event();calls=[]
        params=['pool',dict(commitment='finalized',filters=dict(slot=dict(gte=100,lte=120)))]
        def physical(method,params,priority):
            calls.append(method);started.set();release.wait(2)
            return dict(data=[]),dict(bytes=123,cu=100)
        from concurrent.futures import Future
        original=Future.result
        def wait(future,*args,**kwargs):joined.set();return original(future,*args,**kwargs)
        with patch.object(rpc,'_call_delivered',side_effect=physical),patch.object(Future,'result',wait),ThreadPoolExecutor(2) as pool:
            first=pool.submit(rpc.call_delivered,'getTransactionsForAddress',params,1)
            self.assertTrue(started.wait(1))
            second=pool.submit(rpc.call_delivered,'getTransactionsForAddress',params,1)
            self.assertTrue(joined.wait(1));release.set()
            a,b=first.result(),second.result()
        self.assertEqual(calls,['getTransactionsForAddress']);self.assertEqual(a[0],b[0])
        self.assertEqual(a[1],dict(bytes=123,cu=100));self.assertEqual(b[1],dict(bytes=0,cu=0,calls=0))
        self.assertIsNot(a[0],b[0]);self.assertEqual(rpc.flights,{})


class RecoveryReplayTests(unittest.TestCase):
    def test_published_program_prefix_is_not_purchased_again_on_position_rebuild(self):
        from meme_machine.solana_selective_source import SelectiveSource
        from meme_machine.solana_program_decoders import pump_events
        from tests.test_solana_selective_evidence import FIXTURE
        from meme_machine.solana_selective_history import economic_records, PROGRAMS
        tx=FIXTURE['pump'][1];mint=pump_events(tx)[0]['mint'];slot=tx['slot']
        with tempfile.TemporaryDirectory() as tmp:
            state,h=state_at(Path(tmp)/'canonical.sqlite')
            try:
                h.bind('pump',mint)
                rows=economic_records('pump',PROGRAMS['pump'],tx,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream')
                h.ingest(rows)
                while h.lifecycle.flush():pass
                scope=program_scope('pump');lo=max(1,slot-100)
                h.prove(IntervalProof(scope,lo,slot,'alchemy_finalized_stream','a'*64,
                    dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=slot,lineage_hash=digest([lo,slot])),NOW))
                before=list(h.db.execute('SELECT identity,hash,first_seen FROM canonical_evidence'))
                trace=[]
                async def run():
                    source=SelectiveSource(SimpleNamespace(credential='offline',stream_url='offline'),None)
                    source.stop=asyncio.Event()
                    async def work(fn,priority=1,**kwargs):return fn(state)
                    async def rpc(method,params,family,priority=4):
                        trace.append(method);self.assertEqual(method,'getSlot');return slot
                    class Socket:
                        def __init__(self):self.queue=asyncio.Queue()
                        async def send(self,raw):
                            request=json.loads(raw);self.queue.put_nowait(json.dumps(dict(id=request['id'],result=17)))
                        async def recv(self):return await self.queue.get()
                    class Connection:
                        async def __aenter__(self):return Socket()
                        async def __aexit__(self,*args):pass
                    async def native(channel,request,handler,family,local_stop):
                        self.assertEqual(request.from_slot,slot+1);source.stop.set()
                    source.work=work;source.measured_rpc=rpc;source.stream=native
                    desired=[dict(family='pump',address=mint,scope=coverage_scope('pump',mint),priority=1,lower_slot=lo,deadline=NOW+150)]
                    with patch('meme_machine.solana_selective_source.connect',return_value=Connection()):
                        await source.live(None,desired,asyncio.Event())
                asyncio.run(run())
                self.assertEqual(trace,['getSlot','getSlot'])
                self.assertEqual(list(h.db.execute('SELECT identity,hash,first_seen FROM canonical_evidence')),before)
            finally:state.writer.close()
