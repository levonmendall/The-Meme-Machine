import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import based58
from meme_machine.solana_activity_routes import ActivityRoutes,shards
from meme_machine.solana_candidate_join import CandidateTransactionJoin,candidate_subscription,scope_labels
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,EvidenceUnavailable,EvidenceConflict,IntervalProof,digest
from meme_machine.solana_evidence_queries import PumpEvidenceView,MeteoraEvidenceView
from meme_machine.solana_program_decoders import pump_events,pumpswap_trade_events
from meme_machine.solana_selective_history import SelectiveHistory,CandidateReader,economic_records,coverage_scope,rpc_economic_transaction
from meme_machine.yellowstone import geyser_pb2 as pb

FIXTURE=json.loads((Path(__file__).parent/'fixtures/solana_selective_cohort.json').read_text())
METEORA=json.loads((Path(__file__).parent/'fixtures/meteora_account_coalescence.json').read_text())

class SelectiveEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'evidence.sqlite'
        self.now=[1791400000.];self.writer=EvidenceWriter(self.path,clock=lambda:self.now[0])
        self.history=SelectiveHistory(self.writer,'a'*64,clock=lambda:self.now[0])
        self.reader=EvidenceReader(self.path)
    def tearDown(self):self.reader.close();self.writer.close();self.tmp.cleanup()
    def proof(self,scope,lo,hi,seen=None):
        return IntervalProof(scope,lo,hi,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=hi,
                 lineage_hash=digest([scope,lo,hi])),self.now[0] if seen is None else seen)
    def bind_pump(self):
        tx=FIXTURE['pump'][0];creation=next(e for e in pump_events(tx) if e['event_type']=='create')
        self.history.bind('pump',creation['bonding_curve'],market_address=creation['mint'],aliases=(creation['mint'],))
        return creation['bonding_curve'],creation['mint']
    def request(self,family,address,lo,hi):
        self.history.request(family,address,lo,hi,priority=3,deadline=self.now[0]+100)
        return self.history.plan()[0]

    def test_candidate_coverage_cannot_be_mistaken_for_program_coverage(self):
        curve,mint=self.bind_pump();txs=FIXTURE['pump'];lo=min(t['slot'] for t in txs);hi=max(t['slot'] for t in txs)
        job=self.request('pump',curve,lo,hi)
        self.history.commit_page(job,dict(data=txs,paginationToken='next-even-though-short'),finalized_through=hi)
        candidate=CandidateReader(self.reader,'pump',mint)
        self.assertFalse(candidate.covered(candidate.scope,lo,hi,as_of=self.now[0]))
        job=self.history.plan()[0];self.history.commit_page(job,dict(data=[],paginationToken=None),finalized_through=hi)
        self.assertTrue(candidate.covered(candidate.scope,lo,hi,as_of=self.now[0]))
        self.assertFalse(self.reader.covered('program:pump',lo,hi,as_of=self.now[0]))
        rows=PumpEvidenceView(candidate,candidate.scope).events(mint,lower_slot=lo,upper_slot=hi,
            lower_time=0,upper_time=int(self.now[0]),as_of=self.now[0])
        oracle=[e for t in txs for e in sorted(pump_events(t),key=lambda e:e['index']) if e['mint']==mint]
        self.assertEqual([{k:v for k,v in r.items() if k!='_economic_order'} for r in rows],oracle)

    def test_native_order_and_duplicate_content_survive_restart(self):
        curve,mint=self.bind_pump();txs=FIXTURE['pump'];lo=txs[0]['slot'];hi=txs[-1]['slot']
        job=self.request('pump',curve,lo,hi);self.history.commit_page(job,dict(data=txs),finalized_through=hi)
        candidate=CandidateReader(self.reader,'pump',mint);before=candidate.window(candidate.scope,lo,hi,as_of=self.now[0],address=mint)
        count=self.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]
        self.now[0]+=1
        rows=[r for tx in txs for r in economic_records('pump',curve,tx,endpoint_identity='a'*64,seen=self.now[0],source='alchemy_finalized_stream')]
        self.history.ingest(rows)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],count)
        self.reader.close();self.writer.close();self.writer=EvidenceWriter(self.path,clock=lambda:self.now[0]);self.history=SelectiveHistory(self.writer,'a'*64,clock=lambda:self.now[0]);self.reader=EvidenceReader(self.path)
        candidate=CandidateReader(self.reader,'pump',mint)
        self.assertEqual(candidate.window(candidate.scope,lo,hi,as_of=self.now[0],address=mint),before)

    def test_archive_pagination_has_no_historical_sixteen_page_discard(self):
        curve,mint=self.bind_pump();template=FIXTURE['pump'][1];slot=template['slot'];job=self.request('pump',curve,slot,slot+16)
        for page in range(17):
            tx=copy.deepcopy(template);tx['slot']=slot+page;tx['transactionIndex']=0
            tx['transaction']['signatures']=[based58.b58encode(hashlib.sha512(str(page).encode()).digest()).decode()]
            result=self.history.commit_page(job,dict(data=[tx],paginationToken=None if page==16 else str(page)),finalized_through=slot+16)
            if page<16:job=self.history.plan()[0]
        self.assertTrue(result['complete']);self.assertEqual(result['pages'],17)
        self.assertTrue(self.history.telemetry()['capacity_pressure'])

    def test_late_history_uses_shared_cache_without_regressing_global_floor(self):
        curve,mint=self.bind_pump();tx=FIXTURE['pump'][0];floor=tx['slot']+100
        self.writer.db.execute("INSERT INTO meta VALUES('retention_floor:program:pump',?)",(str(floor),))
        job=self.request('pump',curve,tx['slot'],tx['slot']);self.history.commit_page(job,dict(data=[tx]),finalized_through=tx['slot'])
        candidate=CandidateReader(self.reader,'pump',mint)
        self.assertEqual(candidate.window(candidate.scope,tx['slot'],tx['slot'],as_of=self.now[0],address=mint)[0]['payload']['event']['event_type'],'create')
        self.assertEqual(int(self.writer.db.execute("SELECT value FROM meta WHERE key='retention_floor:program:pump'").fetchone()[0]),floor)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM shared_history_cache').fetchone()[0],len(pump_events(tx)))

    def test_more_than_128_candidate_proofs_do_not_create_maintenance_scopes(self):
        for n in range(1024):
            address='pool-'+str(n);self.history.observe('meteora',address,slot=10,signature='scout',fields={'recoverable':True})
            self.history.bind('meteora',address);self.history.prove(self.proof(coverage_scope('meteora',address),10,12))
        self.assertEqual(self.history.telemetry()['candidates'],1024)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM cursors').fetchone()[0],0)

    def test_compressed_coverage_keeps_original_prospective_availability(self):
        self.history.bind('pumpswap','pool');scope=coverage_scope('pumpswap','pool')
        for n in range(600):self.history.prove(self.proof(scope,10+n,10+n,seen=self.now[0]+n))
        candidate=CandidateReader(self.reader,'pumpswap','pool')
        self.assertTrue(candidate.covered(scope,10,20,as_of=self.now[0]+10))
        self.assertFalse(candidate.covered(scope,10,21,as_of=self.now[0]+10))
        self.assertLessEqual(self.writer.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],3)

    def test_real_coalesced_meteora_swap_is_preserved_in_scoped_history(self):
        tx=METEORA['transaction'];pool=METEORA['counterexample']['pools'][0]['pool'];slot=tx['slot']
        self.history.bind('meteora',pool)
        job=self.request('meteora',pool,slot,slot);self.history.commit_page(job,dict(data=[tx]),finalized_through=slot)
        candidate=CandidateReader(self.reader,'meteora',pool)
        signatures,transactions,_=MeteoraEvidenceView(candidate,candidate.scope).interval(pool,start_slot=slot,end_slot=slot,as_of=self.now[0])
        self.assertEqual(signatures[0]['transactionIndex'],537)
        row=candidate.window(candidate.scope,slot,slot,as_of=self.now[0],address=pool,kind='transaction')[0]
        self.assertEqual(row['payload'],rpc_economic_transaction(tx,rich=True))
        self.assertTrue(row['payload']['meta']['innerInstructions'])

    def test_provider_delivery_is_measured_before_local_projection_or_dedup(self):
        self.history.delivery('pumpswap','yellowstone',raw_bytes=100000,retained_bytes=5000,canonical_bytes=2000,ipc_bytes=1000)
        self.history.delivery('pumpswap','yellowstone',raw_bytes=100000,retained_bytes=5000,canonical_bytes=0,ipc_bytes=1000)
        row=self.writer.db.execute('SELECT raw_bytes,retained_bytes,canonical_bytes,ipc_bytes FROM provider_delivery').fetchone()
        self.assertEqual(row,(200000,10000,2000,2000))

    def test_expired_jobs_are_durable_but_unelapsed_jobs_remain_feasible(self):
        self.history.request('meteora','old',1,2,priority=3,deadline=self.now[0]+1)
        self.history.request('pump','position',1,2,priority=1,deadline=self.now[0]+20)
        self.assertEqual(self.history.plan()[0]['address'],'position')
        self.now[0]+=2;self.history.plan()
        self.assertEqual(self.history.telemetry()['deadline_misses'],1)

class ActivityRoutingTests(unittest.TestCase):
    def test_multi_candidate_activity_never_misses_a_member_or_invents_an_event(self):
        router=ActivityRoutes('pool-'+str(n) for n in range(50))
        for members in (('pool-0',),('pool-27','pool-48'),('pool-1','pool-44','pool-7')):
            labels=[label for label,group in router.groups.items() if set(members)&set(group)]
            resolved=router.resolve(labels)
            self.assertTrue(set(members).issubset(resolved['addresses']))
            self.assertFalse(resolved['economic_event']);self.assertFalse(resolved['history_complete'])
        self.assertLessEqual(len(router.subscription().transactions_status),50)
        self.assertLessEqual(max(len(f.account_include) for f in router.subscription().transactions_status.values()),50)
        self.assertEqual(sum(len(r.addresses) for r in shards('p-'+str(n) for n in range(10000))),10000)

    def test_an_empty_include_filter_can_never_request_unrelated_transactions(self):
        request=ActivityRoutes(['one']).subscription()
        self.assertTrue(all(f.account_include for f in request.transactions_status.values()))
        self.assertFalse(request.transactions);self.assertFalse(request.blocks)

class NativeLogJoinTests(unittest.TestCase):
    def setup_join(self):
        tx=FIXTURE['pump'][1];mint=pump_events(tx)[0]['mint'];self.scope=coverage_scope('pump',mint)
        self.address=mint;self.tx=tx;self.join=CandidateTransactionJoin({mint:self.scope},set(),filtered_from_slot=tx['slot'])
        return tx
    def feed(self,update):return self.join.feed(update,update.ByteSize(),1791400000.)
    def test_logs_plus_independent_status_have_exact_order_with_no_body(self):
        tx=self.setup_join();slot=tx['slot'];sig=tx['transaction']['signatures'][0];index=tx['transactionIndex']
        request=candidate_subscription({self.address:self.scope},slot,full_addresses=set())
        self.assertFalse(request.transactions);self.assertTrue(request.transactions_status)
        u=pb.SubscribeUpdate(filters=[scope_labels({self.address:self.scope})[self.scope]])
        u.transaction_status.slot=slot;u.transaction_status.index=index;u.transaction_status.signature=based58.b58decode(sig.encode());self.feed(u)
        u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=slot;m.parent_slot=slot-1;m.blockhash='hash';m.parent_blockhash='parent';m.block_time.timestamp=tx['blockTime'];m.executed_transaction_count=index+1;self.feed(u)
        u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=slot;u.slot.parent=slot-1;u.slot.status=pb.SLOT_FINALIZED
        self.assertIsNone(self.feed(u))
        frame=self.join.feed_log(slot,sig,tx['meta']['logMessages'],None,1791400000.)
        self.assertEqual(len(frame.update.block.transactions),0)
        self.assertEqual(frame.log_transactions[0]['transactionIndex'],index)
        self.assertEqual(pump_events(frame.log_transactions[0]),pump_events(tx))
        # An overlapping WS delivery after commit must be idempotent and cannot
        # consume transient memory forever. A different late log fails closed.
        self.assertIsNone(self.join.feed_log(slot,sig,tx['meta']['logMessages'],None,1791400001.))
        self.assertEqual(self.join.early_log_bytes,0)
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_late_log_content'):
            self.join.feed_log(slot,sig,['different'],None,1791400001.)

    def status(self,slot,index,raw):
        u=pb.SubscribeUpdate(filters=[scope_labels({self.address:self.scope})[self.scope]])
        u.transaction_status.slot=slot;u.transaction_status.index=index;u.transaction_status.signature=raw
        return self.feed(u)

    def close_header(self,slot,count):
        u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=slot;m.parent_slot=slot-1
        m.blockhash='hash';m.parent_blockhash='parent';m.block_time.timestamp=self.tx['blockTime'];m.executed_transaction_count=count
        self.feed(u)
        u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=slot;u.slot.parent=slot-1;u.slot.status=pb.SLOT_FINALIZED
        return self.feed(u)

    def test_delayed_logs_do_not_rescan_or_reconvert_the_status_census(self):
        from unittest.mock import patch
        from meme_machine.solana_candidate_join import signature
        tx=self.setup_join();slot=tx['slot'];count=1000
        raw=[i.to_bytes(8,'big')+b'0'*56 for i in range(count)]
        texts=[signature(s) for s in raw]
        with patch('meme_machine.solana_candidate_join.signature',wraps=signature) as convert:
            for i,sig in enumerate(raw):self.assertIsNone(self.status(slot,i,sig))
            self.assertIsNone(self.close_header(slot,count))
            for _ in range(100):
                self.assertIsNone(self.join.drain())
                self.assertEqual(len(list(self.join.missing_log_keys(slot))),count)
            for i in reversed(range(count)):
                frame=self.join.feed_log(slot,texts[i],['authenticated log'],None,1791400000.+i/1000)
                if i:self.assertIsNone(frame)
            self.assertEqual(convert.call_count,count)
        self.assertEqual([r['transactionIndex'] for r in frame.log_transactions],list(range(count)))
        self.assertEqual(len(frame.candidate_statuses),count)
        self.assertEqual(frame.observed_at[texts[-1]],1791400000.+(count-1)/1000)
        self.assertFalse(list(self.join.missing_log_keys(slot)))

    def test_new_status_during_publication_wait_adds_its_missing_log(self):
        from meme_machine.solana_candidate_join import signature
        tx=self.setup_join();slot=tx['slot'];first=b'1'*64;second=b'2'*64
        self.status(slot,0,first);self.assertIsNone(self.close_header(slot,2))
        self.status(slot,1,second)
        self.assertIsNone(self.join.feed_log(slot,signature(first),['first'],None,1791400000.))
        self.assertEqual(list(self.join.missing_log_keys(slot)),[(slot,signature(second))])
        frame=self.join.feed_log(slot,signature(second),['second'],None,1791400001.)
        self.assertEqual(len(frame.log_transactions),2)

    def test_early_logs_need_no_recovery_and_conflicting_logs_still_fail_closed(self):
        from meme_machine.solana_candidate_join import signature
        tx=self.setup_join();slot=tx['slot'];raw=b'1'*64;text=signature(raw)
        self.join.feed_log(slot,text,['early'],None,1791400000.)
        self.status(slot,0,raw)
        self.assertFalse(list(self.join.missing_log_keys(slot)))
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_log_content_conflict'):
            self.join.feed_log(slot,text,['changed'],None,1791400000.)
        self.assertIsNotNone(self.close_header(slot,1))

class SourceIntegrationTests(SelectiveEvidenceTests):
    # Reuse the real temporary canonical writer, never operational state.
    def setUp(self):
        super().setUp()
        from types import SimpleNamespace
        from meme_machine.solana_evidence_service import FinalizedFence
        self.state=SimpleNamespace(writer=self.writer,fence=FinalizedFence(self.writer,endpoint_identity='a'*64))
    def test_all_live_interests_survive_filter_pressure_and_shared_open_role(self):
        from meme_machine.solana_selective_source import plan_live
        for n in range(1024):
            owner='met-'+str(n);address='pool-'+str(n)
            self.writer.interest(owner,'program:meteora',lower_slot=1,priority=3,lifecycle='candidate')
            self.writer.db.execute('INSERT INTO service_interests VALUES(?,?,?,?)',(owner,'program:meteora',address,'account'))
        self.writer.interest('position','program:meteora',lower_slot=1,priority=0,lifecycle='open')
        self.writer.db.execute('INSERT INTO service_interests VALUES(?,?,?,?)',('position','program:meteora','pool-1','account'))
        first=plan_live(self.state);second=plan_live(self.state)
        self.assertEqual(len(first),1024);self.assertEqual(first,second)
        self.assertEqual(first[0]['address'],'pool-1');self.assertEqual(first[0]['priority'],1)
        self.assertTrue(self.history.telemetry()['capacity_pressure'])
    def test_read_only_startup_is_separate_from_funded_admission(self):
        import asyncio
        from unittest.mock import AsyncMock,MagicMock
        from meme_machine.solana_selective_source import SelectiveSource,PRODUCTION_BLOCKERS,require_certified
        self.assertTrue(PRODUCTION_BLOCKERS)
        source=SelectiveSource(MagicMock(),MagicMock(),token='offline')
        owner=AsyncMock()
        source.run=AsyncMock(return_value='observation')
        self.assertEqual(asyncio.run(source(owner,asyncio.Event())),'observation')
        with self.assertRaisesRegex(EvidenceUnavailable,PRODUCTION_BLOCKERS[0]):require_certified()
        owner.assert_not_called();source.rpc.call_delivered.assert_not_called()

    def test_current_rpc_receipt_counts_slot_cost_and_failed_physical_calls(self):
        from unittest.mock import MagicMock,patch
        from meme_machine.runtime.evidence_worker import RepairRPC,DeliveredRPCError
        rpc=RepairRPC('https://solana-mainnet.g.alchemy.com/v2/offline-fixture',MagicMock())
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{"id":1,"result":454000000}'
        with patch('urllib.request.urlopen',return_value=response):
            value,receipt=rpc.call_delivered('getSlot',[],1)
        self.assertEqual(value,454000000);self.assertEqual(receipt,dict(bytes=27,cu=20))
        response.__enter__.return_value.read.return_value=b'{"id":1,"error":{"code":-32005}}'
        with patch('urllib.request.urlopen',return_value=response):
            with self.assertRaises(DeliveredRPCError) as raised:rpc.call_delivered('getTransactionsForAddress',[],3)
        self.assertEqual(raised.exception.receipt,dict(bytes=32,cu=100))

    def test_native_resource_exhaustion_keeps_provider_detail_without_credentials(self):
        import asyncio
        import grpc
        from types import SimpleNamespace
        from unittest.mock import AsyncMock,MagicMock
        from meme_machine.solana_selective_source import SelectiveSource
        from engineering.solana_capacity.transport_meter import TransportMeter
        for phase in ('subscription_write','stream_read'):
            with self.subTest(phase=phase):
                source=SelectiveSource(SimpleNamespace(credential='fixture-key'),MagicMock(),token='fixture-token')
                source.stop=asyncio.Event()
                call=MagicMock();call.write=AsyncMock();call.read=AsyncMock()
                failure=grpc.aio.AioRpcError(grpc.StatusCode.RESOURCE_EXHAUSTED,None,None,
                    details='subscription limit exceeded; fixture-token https://solana-mainnet.g.alchemy.com/v2/fixture-key')
                (call.write if phase=='subscription_write' else call.read).side_effect=failure
                channel=MagicMock();channel.stream_stream.return_value.return_value=call
                meter=TransportMeter(Path(self.tmp.name)/('native-'+phase+'.zlib'));source.observer=meter
                request=pb.SubscribeRequest(from_slot=300)
                request.slots['finality'].filter_by_commitment=True
                with self.assertRaisesRegex(EvidenceUnavailable,'candidate_native_resource_exhausted'):
                    asyncio.run(source.stream(channel,request,AsyncMock(),'candidate_live'))
                meter.close();summary=meter.summary()
                self.assertEqual(summary['native_status_counts'],{'RESOURCE_EXHAUSTED':1})
                row=summary['native_errors'][0]
                self.assertEqual(row['phase'],phase);self.assertEqual(row['filters'],1)
                self.assertEqual(row['from_slot'],300);self.assertEqual(row['active_streams'],1)
                self.assertIn('subscription limit exceeded',row['details'])
                self.assertNotIn('fixture-token',row['details']);self.assertNotIn('fixture-key',row['details'])
                self.assertNotIn('alchemy.com/v2/',row['details'])
                self.assertEqual(summary['delivery'],[]);source.rpc.call_delivered.assert_not_called()
                call.cancel.assert_called_once()

if __name__=='__main__':unittest.main()
