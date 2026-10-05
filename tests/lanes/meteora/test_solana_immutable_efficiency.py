import json,os,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.lanes.meteora.solana_read_rpc import ReadOnlyFailoverRPC
from meme_machine.lanes.meteora.solana_evidence_broker import EvidenceBroker,DynamicAddressLogStream
from meme_machine.lanes.meteora.solana_immutable_rpc import ImmutableReads
from meme_machine.lanes.meteora.provider import Unavailable

class SolanaEfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=str(Path(self.temp.name)/'shared.db')
        self.env=patch.dict(os.environ,MM_SOLANA_EVIDENCE_BROKER_DB=self.db,MM_CERTIFICATION_LANE='pump');self.env.start();self.addCleanup(self.env.stop)
        self.wire=[]
    def rpc(self,url='https://solana-mainnet.g.alchemy.com/v2/test'):
        def transport(q):
            rows=q if isinstance(q,list) else [q];out=[]
            for x in rows:
                self.wire.append(x)
                result={'getGenesisHash':'mainnet','getBlockTime':123,'getTransaction':{'slot':7,'blockTime':123,'meta':{}},'getMultipleAccounts':{'context':{'slot':7},'value':[]}}[x['method']]
                out.append(dict(id=x['id'],jsonrpc='2.0',result=result))
            return out if isinstance(q,list) else out[0]
        return ReadOnlyFailoverRPC(url,transport=transport,sleeper=lambda s:None)
    def params(self):return ['sig',dict(encoding='json',commitment='finalized',maxSupportedTransactionVersion=1)]
    def test_pump_meteora_and_rotated_candidates_fetch_one_body(self):
        a=self.rpc();first=a.call('getTransaction',self.params(),True)
        for lane in ('pump','meteora','pump'):
            with patch.dict(os.environ,MM_CERTIFICATION_LANE=lane):self.assertEqual(self.rpc().call('getTransaction',self.params(),True),first)
        self.assertEqual(len(self.wire),1)
    def test_genesis_proof_survives_rotation_but_not_endpoint_change(self):
        self.rpc().call('getGenesisHash');self.rpc().call('getGenesisHash')
        self.assertEqual(len(self.wire),1)
        self.rpc('https://solana-mainnet.g.alchemy.com/v2/different').call('getGenesisHash')
        self.assertEqual(len(self.wire),2)
    def test_shared_block_time_requires_finality_proof(self):
        a=self.rpc();a.call('getMultipleAccounts',[[],{'commitment':'finalized'}]);a.call('getBlockTime',[7])
        self.rpc().call('getBlockTime',[7]);self.assertEqual(sum(q['method']=='getBlockTime' for q in self.wire),1)
        self.rpc().call('getBlockTime',[8]);self.rpc().call('getBlockTime',[8])
        self.assertEqual(sum(q['method']=='getBlockTime' for q in self.wire),3)
    def test_dynamic_accounts_are_not_shared_across_rotations(self):
        for _ in range(2):self.rpc().call('getMultipleAccounts',[['a'],{'commitment':'finalized'}])
        self.assertEqual(len(self.wire),2)
    def test_confirmed_transaction_does_not_populate_finalized_cache(self):
        p=self.params();p[1]['commitment']='confirmed';self.rpc().call('getTransaction',p,True)
        self.rpc().call('getTransaction',self.params(),True);self.assertEqual(len(self.wire),2)
    def test_endpoint_change_cannot_reuse_transaction_authority(self):
        self.rpc().call('getTransaction',self.params(),True)
        with self.assertRaisesRegex(Unavailable,'authority_changed'):self.rpc('https://other.invalid/').call('getTransaction',self.params(),True)
    def test_archive_conflict_fails_closed_and_hot_eviction_preserves_body(self):
        b=EvidenceBroker(self.db);self.addCleanup(b.close);b.put_transaction('a',{'slot':1})
        with b.db:b.db.execute('DELETE FROM tx_cache')
        self.assertEqual(b.get_transaction('a'),{'slot':1})
        with self.assertRaisesRegex(ValueError,'immutable_transaction_conflict'):b.put_transaction('a',{'slot':2})
        with self.assertRaises(sqlite3.IntegrityError):
            with b.db:b.db.execute('DELETE FROM immutable_transactions')
    def test_speculative_budget_never_deletes_stream_evidence(self):
        b=EvidenceBroker(self.db,clock=lambda:100);self.addCleanup(b.close)
        s=DynamicAddressLogStream('wss://hint.invalid',b,'pool',prefetch=True,prefetch_filter=lambda *a:True,clock=lambda:100)
        admitted=[]
        for i in range(20):
            b.record_event('pool:a',signature=str(i),slot=i,observed_at=100)
            admitted.append(s.should_prefetch('a',{},i))
        self.assertEqual(sum(admitted),8);self.assertEqual(len(b.recent_events('pool:a')),20)
        self.assertTrue(s.should_prefetch('b',{},1)) # one hot pool cannot consume every permit
    def test_null_or_error_network_proof_is_not_cached(self):
        store=ImmutableReads(self.db,'https://same.invalid');calls=[]
        for _ in range(2):store.call('getGenesisHash',[],lambda:calls.append(1))
        self.assertEqual(len(calls),2)
    def test_no_consumer_count_inflation_for_cached_provider_job(self):
        self.rpc().call('getTransaction',self.params(),True)
        self.rpc().call('getTransaction',self.params(),True)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM immutable_transactions').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM evidence_consumers').fetchone()[0],1)

    def test_concurrent_consumers_share_one_inflight_fetch(self):
        import concurrent.futures
        from threading import Lock
        count=[0];lock=Lock()
        def fetch(q):
            with lock:count[0]+=len(q) if isinstance(q,list) else 1
            time.sleep(.08)
            out=[dict(id=x['id'],result={'slot':7,'blockTime':123}) for x in (q if isinstance(q,list) else [q])]
            return out if isinstance(q,list) else out[0]
        def consumer():
            rpc=ReadOnlyFailoverRPC('https://solana-mainnet.g.alchemy.com/v2/test',transport=fetch)
            return rpc.call('getTransaction',self.params(),True)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            a,b=list(pool.map(lambda _:consumer(),range(2)))
        self.assertEqual(a,b);self.assertEqual(count[0],1)
        broker=EvidenceBroker(self.db);self.addCleanup(broker.close)
        self.assertEqual(broker._pressure()['transport_reservations'],1)
    def test_cached_body_between_queue_and_claim_cannot_resurrect_provider_job(self):
        a=EvidenceBroker(self.db);b=EvidenceBroker(self.db)
        self.addCleanup(a.close);self.addCleanup(b.close)
        a.queue_transaction('sig',kind='pump_window',deadline=time.time()+5)
        b.put_transaction('sig',{'slot':7})
        self.assertEqual(a._claim_jobs(8),[])
        self.assertFalse(a.queue_transaction('sig',kind='dlmm_fresh',deadline=time.time()+5))
        self.assertEqual(a._pressure()['transport_reservations'],0)
        self.assertEqual(a.db.execute("SELECT status FROM jobs WHERE job_key='tx:sig'").fetchone()[0],'complete')

    def test_transient_gettransaction_timeout_retries_once_with_lower_batch_pressure(self):
        now=[100.]
        b=EvidenceBroker(self.db,clock=lambda:now[0],
            sleeper=lambda n:now.__setitem__(0,now[0]+n));self.addCleanup(b.close)
        class Rpc:
            failure_methods={}
            attempts=0
            def call_many(self,_method,params,*_args,**_kwargs):
                self.attempts+=1
                if self.attempts==1:
                    self.failure_methods={'getTransaction:TimeoutError':1}
                    raise Unavailable('provider_request_failed')
                return [dict(slot=1,blockTime=1) for _ in params]
        rpc=Rpc();before=b._pressure()
        values,meta=b.hydrate_transactions(
            rpc,['a','b','c','d'],kind='pump_window',deadline=105.,batch_size=8)
        self.assertEqual(meta['pending'],0);self.assertEqual(rpc.attempts,2)
        after=b._pressure()
        self.assertLess(after['batch_size'],before['batch_size'])
        self.assertEqual(after['rate_events'],before['rate_events'])
        phases=b.consumers.telemetry()['acquisition_phase_attempts']
        self.assertEqual(phases['provider_transient_retry'],1)

    def test_repeated_transient_gettransaction_failure_stays_fail_closed(self):
        now=[100.]
        b=EvidenceBroker(self.db,clock=lambda:now[0],
            sleeper=lambda n:now.__setitem__(0,now[0]+n));self.addCleanup(b.close)
        class Rpc:
            failure_methods={}
            attempts=0
            def call_many(self,*_args,**_kwargs):
                self.attempts+=1
                self.failure_methods={'getTransaction:TimeoutError':self.attempts}
                raise Unavailable('provider_request_failed')
        rpc=Rpc();values,meta=b.hydrate_transactions(
            rpc,['a'],kind='pump_window',deadline=105.,batch_size=8)
        self.assertEqual(rpc.attempts,2);self.assertEqual(meta['pending'],1)
        self.assertIsNone(values['a'])
        self.assertEqual(
            b.consumers.telemetry()['acquisition_failures'],
            {'provider_unavailable':1})

    def test_recovered_internal_429_still_updates_shared_batch_pressure(self):
        class Rpc:
            gettransaction_429_events=0
            def call_many(self,m,p,*a,**kw):
                self.gettransaction_429_events+=1
                return [{'slot':1} for _ in p]
        a=EvidenceBroker(self.db);b=EvidenceBroker(self.db);self.addCleanup(a.close);self.addCleanup(b.close)
        before=b._pressure()['batch_size']
        result,meta=a.hydrate_transactions(Rpc(),['sig'],kind='pump_window',deadline=time.time()+5)
        self.assertEqual(meta['pending'],0)
        self.assertLess(b._pressure()['batch_size'],before)
        for _ in range(8):b._note_pressure_success()
        self.assertGreater(a._pressure()['batch_size'],before//2)

    def test_stream_hint_archive_survives_hot_window_eviction_without_authority(self):
        b=EvidenceBroker(self.db);self.addCleanup(b.close)
        b.record_event('s',signature='old',slot=1,observed_at=1,payload={'hint':True})
        b.record_event('s',signature='new',slot=2,observed_at=10000)
        self.assertEqual(len(b.recent_events('s')),1)
        self.assertEqual(b.db.execute('SELECT count(*) FROM stream_signature_archive').fetchone()[0],2)
        self.assertIsNone(b.get_transaction('old'))

    def test_unserviceable_reservation_releases_unique_job_lease(self):
        b=EvidenceBroker(self.db);self.addCleanup(b.close)
        with b.db:b.db.execute("UPDATE pressure SET cooldown_until=?",(time.time()+60,))
        result,meta=b.hydrate_transactions(self.rpc(),['a'],kind='pump_window',deadline=time.time()+.1)
        self.assertEqual(meta['pending'],1);self.assertEqual(self.wire,[])
        self.assertEqual(b.db.execute("SELECT count(*) FROM jobs WHERE status='inflight'").fetchone()[0],0)

    def test_late_body_is_archived_but_does_not_complete_expired_consumer(self):
        now=[100.]
        b=EvidenceBroker(self.db,clock=lambda:now[0],sleeper=lambda n:now.__setitem__(0,now[0]+n));self.addCleanup(b.close)
        class Slow:
            def call_many(self,*a,**kw):now[0]=102.;return [{'slot':1}]
        values,meta=b.hydrate_transactions(Slow(),['a'],kind='pump_window',deadline=101.)
        self.assertIsNone(values['a']);self.assertEqual(meta['pending'],1)
        self.assertEqual(b.get_transaction('a'),{'slot':1})
        values,meta=b.hydrate_transactions(Slow(),['a'],kind='pump_window',deadline=103.)
        self.assertEqual(meta['pending'],0) # later independent consumer can reuse history

    def test_local_governor_expiry_is_not_recorded_as_provider_failure(self):
        b=EvidenceBroker(self.db);self.addCleanup(b.close)
        class LocalFailure:
            def call_many(self,*a,**kw):
                self.evidence_local_failure='certification_provider_queue_deadline'
                raise Unavailable('provider_unavailable')
        _,meta=b.hydrate_transactions(LocalFailure(),['sig'],kind='pump_window',deadline=time.time()+1)
        self.assertEqual(meta['pending'],1)
        telemetry=b.consumers.telemetry()
        self.assertEqual(telemetry['acquisition_failures'],{'physical_governor_wait':1})
        self.assertEqual(telemetry['acquisition_phase_attempts']['physical_governor_wait'],1)

    def test_expired_before_enqueue_is_separate_and_never_transports(self):
        b=EvidenceBroker(self.db);self.addCleanup(b.close)
        _,meta=b.hydrate_transactions(self.rpc(),['sig'],kind='pump_window',deadline=time.time()-1)
        self.assertEqual(self.wire,[])
        telemetry=b.consumers.telemetry()
        self.assertEqual(telemetry['acquisition_phase_attempts']['already_expired_before_enqueue'],1)
        self.assertEqual(telemetry['deadline_decomposition'][0]['stage'],'already_expired_before_enqueue')
