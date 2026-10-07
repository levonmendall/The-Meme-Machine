"""Model B reuses canonical truth; fixtures prove parity, never live rates."""
from contextlib import closing
import copy,json,os,tempfile,time,unittest,zlib
from pathlib import Path
from unittest.mock import patch
from tests.test_solana_closure import state_at,NOW
from tests.test_solana_selective_evidence import FIXTURE
from meme_machine.solana_evidence_plane import EvidenceReader,EvidenceUnavailable,IntervalProof,digest
from meme_machine.solana_selective_history import CandidateReader,PROGRAMS,economic_records,coverage_scope
from meme_machine.solana_rolling_history import program_scope
from meme_machine.runtime.candidate_history import CandidateHistory

class RollingPrewarmTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'canonical.sqlite'
        self.now=[NOW];self.state,self.h=state_at(self.path,lambda:self.now[0])
    def tearDown(self):self.state.writer.close();self.tmp.cleanup()
    def seal(self,scope,lo,hi):
        self.h.lifecycle.defer_proof(IntervalProof(scope,lo,hi,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=hi,lineage_hash=digest([scope,lo,hi])),self.now[0]))
        while self.h.lifecycle.flush():pass
        self.h.lifecycle.publish()
    def pump(self):
        txs=FIXTURE['pump'];rows=[]
        for tx in txs:
            # Real captured logs, authentic native index, NO transaction body.
            minimal={k:copy.deepcopy(tx[k]) for k in ('slot','blockTime','transactionIndex')}
            minimal.update(transaction=dict(signatures=tx['transaction']['signatures']),
                meta=dict(err=tx['meta']['err'],logMessages=tx['meta']['logMessages']))
            rows.extend(economic_records('pump',PROGRAMS['pump'],minimal,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream'))
        self.h.ingest(rows);self.seal(program_scope('pump'),txs[0]['slot'],txs[-1]['slot'])
        mint=next(r.payload['event']['mint'] for r in rows if r.payload['event']['event_type']=='create')
        return mint,rows
    def test_first_sight_meteora_installs_history_before_promotion_without_rpc_or_entry(self):
        from meme_machine.solana_selective_source import plan_live
        self.h.observe('meteora','pool',slot=100,signature='',seen=NOW,fields=dict(wsol_pair_locator=True,activity=False))
        desired=plan_live(self.state)
        self.assertEqual([(r['address'],r['priority']) for r in desired],[('pool',5)])
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        self.assertEqual(self.h.db.execute("SELECT state FROM candidate_lifecycle").fetchone()[0],'cheap_retained')
        self.assertFalse(self.h.db.execute('SELECT 1 FROM promotion_history_metrics').fetchone())
    def test_non_wsol_bin_locator_has_no_rich_prewarm_interest(self):
        from meme_machine.solana_selective_source import plan_live
        self.h.observe('meteora','other',slot=100,signature='',seen=NOW,fields=dict(bin_array_locator='bin',activity=False))
        self.assertEqual(plan_live(self.state),[])
    def test_body_free_shared_reservoir_and_creation_boundary_are_complete_at_promotion(self):
        mint,rows=self.pump();lo=rows[0].slot;hi=FIXTURE['pump'][-1]['slot']
        metric=self.h.rolling.prepare('pump',mint,0,hi,deadline=NOW+150)
        self.assertTrue(metric['history_already_complete_at_promotion']);self.assertEqual(metric['backfill_jobs'],[])
        with closing(EvidenceReader(self.path)) as reader:
            candidate=CandidateReader(reader,'pump',mint)
            self.assertTrue(candidate.covered(candidate.scope,0,hi,as_of=NOW))
            self.assertEqual(len(candidate.window(candidate.scope,lo,hi,as_of=NOW,address=mint)),len(rows))
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
            self.assertEqual(shared.event_order_status('pump',mint)['events'],len(rows))
            self.assertEqual(len(shared.events('pump',mint)),len(rows))
        self.h.ingest(rows)
        while self.h.lifecycle.flush():pass
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0],len(rows))

    def test_scout_before_creation_publication_waits_durably_instead_of_cold_backfill(self):
        from meme_machine.solana_program_decoders import pump_events
        creation=next(e for e in pump_events(FIXTURE['pump'][0]) if e['event_type']=='create')
        curve=creation['bonding_curve'];slot=FIXTURE['pump'][0]['slot']
        self.h.observe('pump',curve,slot=slot,signature='',seen=NOW,fields={'activity':True})
        self.h.bind('pump',curve)
        self.h.rolling.prepare('pump',curve,0,FIXTURE['pump'][-1]['slot'],deadline=NOW+150)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        mint,rows=self.pump();self.now[0]+=2;self.h.rolling.resume_boundaries()
        self.assertEqual(self.h.db.execute('SELECT status,deadline FROM rolling_boundary_waits').fetchone(),('resolved',NOW+150))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
    def test_only_small_missing_gap_is_requested_and_original_deadline_survives_restart(self):
        self.h.bind('pumpswap','pool');scope=coverage_scope('pumpswap','pool')
        self.seal(scope,100,103);self.seal(scope,106,110)
        metric=self.h.rolling.prepare('pumpswap','pool',100,110,deadline=NOW+150)
        self.assertEqual(metric['missing_intervals'],[(104,105)])
        self.assertEqual(self.h.db.execute('SELECT lo,hi,deadline FROM acquisition_jobs').fetchall(),[(104,105,NOW+150)])
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.now[0]+=10;self.h.rolling.prepare('pumpswap','pool',100,110,deadline=NOW+300)
        self.assertEqual(self.h.db.execute('SELECT lo,hi,deadline FROM acquisition_jobs').fetchall(),[(104,105,NOW+150)])

    def test_authenticated_creation_still_waits_for_unpublished_tail_across_restart(self):
        mint,rows=self.pump();hi=FIXTURE['pump'][-1]['slot'];deadline=NOW+150
        metric=self.h.rolling.prepare('pump',mint,0,hi+2,deadline=deadline)
        self.assertEqual(metric['publication_pending_intervals'],[(hi+1,hi+2)])
        self.assertEqual(metric['backfill_jobs'],[])
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.now[0]+=5;self.h.rolling.resume_publication()
        self.assertEqual(self.h.db.execute('SELECT status,deadline FROM rolling_publication_waits').fetchone(),('pending',deadline))
        self.seal(program_scope('pump'),hi+1,hi+2);self.h.rolling.resume_publication()
        self.assertEqual(self.h.db.execute('SELECT status,deadline FROM rolling_publication_waits').fetchone(),('resolved',deadline))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)

    def test_proven_closed_gap_is_repaired_while_live_tail_waits(self):
        self.h.bind('pumpswap','pool');scope=coverage_scope('pumpswap','pool')
        self.seal(scope,100,103);self.seal(scope,106,110)
        metric=self.h.rolling.prepare('pumpswap','pool',100,112,deadline=NOW+150)
        self.assertEqual(self.h.db.execute('SELECT lo,hi FROM acquisition_jobs').fetchall(),[(104,105)])
        self.assertEqual(metric['publication_pending_intervals'],[(111,112)])
        self.assertFalse(metric['history_already_complete_at_promotion'])

    def test_first_native_membership_waits_without_coverage_and_keeps_deadline(self):
        self.h.bind('meteora','pool')
        self.h.rolling.prepare('meteora','pool',100,110,deadline=NOW+10)
        self.h.rolling.prepare('meteora','pool',100,110,deadline=NOW+150)
        self.assertEqual(self.h.db.execute('SELECT deadline FROM rolling_publication_waits').fetchone()[0],NOW+10)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        self.now[0]+=11;self.h.rolling.resume_publication()
        self.assertEqual(self.h.db.execute('SELECT status FROM rolling_publication_waits').fetchone()[0],'deadline_missed')
        self.seal(coverage_scope('meteora','pool'),100,110);self.h.rolling.resume_publication()
        self.assertEqual(self.h.db.execute('SELECT status FROM rolling_publication_waits').fetchone()[0],'deadline_missed')
    def test_open_upper_boundary_and_unresolved_gap_never_fabricate_completeness(self):
        self.h.bind('pumpswap','pool');scope=coverage_scope('pumpswap','pool')
        self.seal(scope,100,109);self.h.gap(scope,105,None,'disconnect')
        self.assertEqual(self.h.lifecycle.missing(scope,100,110),[(105,110)])
        with closing(EvidenceReader(self.path)) as reader:
            candidate=CandidateReader(reader,'pumpswap','pool')
            self.assertFalse(candidate.covered(scope,100,110,as_of=NOW))
    def test_independent_overlap_really_repairs_candidate_gap_without_global_inference(self):
        self.h.bind('pumpswap','pool');scope=coverage_scope('pumpswap','pool')
        self.seal(scope,100,110);self.h.gap(scope,105,106,'rebuild')
        self.assertEqual(self.h.lifecycle.missing(scope,100,110),[(105,106)])
        self.seal(program_scope('pumpswap'),105,106)
        self.assertEqual(self.h.lifecycle.missing(scope,100,110),[])
        self.assertEqual(self.h.lifecycle.missing(scope,100,111),[(111,111)])
    def test_seal_makes_both_independent_jobs_runnable_without_resetting_deadline(self):
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as shared:
            for name in ('one','two'):
                shared.enqueue('meteora',name,kind='warmup',ready_at=NOW,deadline=NOW+150,estimate_seconds=12,priority=30,identity=name,payload={})
                shared.wait_for_history(name,'candidate:meteora:'+name,100,110,retry_at=NOW+120)
            self.assertIsNone(shared.claim('first'))
        for name in ('one','two'):
            self.h.bind('meteora',name);self.seal(coverage_scope('meteora',name),100,110)
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as shared:
            a=shared.claim('first');b=shared.claim('second')
            self.assertEqual({a['id'],b['id']},{'one','two'})
            self.assertEqual([a['deadline'],b['deadline']],[NOW+150,NOW+150])
            self.assertIsNone(shared.claim('third'))
    def test_authoritative_checkpoint_does_not_seal_missing_deltas_and_survives_restart(self):
        from engineering.solana_closure.replay_positive import ReplayRPC
        from meme_machine.lanes.meteora import dlmm
        folder=Path('tests/fixtures/solana_positive_meteora');summary=json.loads((folder/'result.json').read_text())
        positive=next(x for x in summary['warmups'] if x.get('qualification',{}).get('passes'))
        rows=[json.loads(x) for x in zlib.decompress((folder/'rpc.ndjson.zlib').read_bytes()).decode().splitlines()]
        rpc=ReplayRPC(rows[positive['rpc_start_index']:]);snap=dlmm.Adapter(rpc,network_verified=True).snapshot(positive['pool'],int(positive['first_scout_time']),True,True)
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:
            shared.checkpoint('program:meteora',positive['pool'],snap,proof=digest(snap),frontier=snap['slot'])
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:
            cp=shared.latest_checkpoint('program:meteora',positive['pool'],as_of=snap['available_time'])
            self.assertEqual(cp['snapshot'],snap)
            self.assertIsNone(shared.latest_checkpoint('program:meteora',positive['pool'],as_of=snap['available_time']-1))
        scope=self.h.bind('meteora',positive['pool'])
        self.assertNotEqual(self.h.lifecycle.missing(scope,snap['slot'],snap['slot']+1),[])
    def test_pinned_position_history_cannot_retire_under_storage_pressure(self):
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        mint,rows=self.pump();scope=self.h.scope_for('pump',mint)
        self.h.lifecycle.pin(scope,'position','right_tail',rows[0].slot)
        retired=ScopedRetirement(self.h).retire()
        self.assertEqual(retired['retired_records'],0);self.assertGreater(retired['pinned_bytes'],0)

    def test_quiet_views_do_not_scan_whole_program_during_retirement(self):
        from dataclasses import replace
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        mint,rows=self.pump()
        # Deterministic storage pressure, not strategy or market evidence.
        self.h.ingest([replace(rows[-1],identity='storage-pressure:'+str(i)) for i in range(500)])
        while self.h.lifecycle.flush():pass
        self.h.lifecycle.pin(coverage_scope('pump',mint),'position','open_position',0)
        for i in range(200):self.h.bind('pump','quiet-view:'+str(i))
        steps=[0]
        def budget():
            steps[0]+=1000
            return int(steps[0]>350000)
        self.h.db.set_progress_handler(budget,1000)
        try:retired=ScopedRetirement(self.h).retire()
        finally:self.h.db.set_progress_handler(None,0)
        self.assertEqual(retired['retired_records'],0)
        self.assertGreater(retired['pinned_bytes'],0)
        self.assertLess(steps[0],350000)
    def test_normalized_history_remains_readable_after_hot_retirement(self):
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        mint,rows=self.pump()
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:before=shared.events('pump',mint)
        retired=ScopedRetirement(self.h).retire()
        self.assertGreater(retired['retired_records'],0)
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:self.assertEqual(shared.events('pump',mint),before)
        with closing(EvidenceReader(self.path)) as reader:
            c=CandidateReader(reader,'pump',mint)
            self.assertEqual(len(c.window(c.scope,rows[0].slot,FIXTURE['pump'][-1]['slot'],as_of=NOW)),len(rows))
            from meme_machine.solana_selective_history import ConsumerReader
            self.assertEqual(len(ConsumerReader(reader).discovery(0,as_of=NOW)),len(rows))
        ScopedRetirement(self.h).restore('pump',mint)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM shared_history_cache').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events WHERE body IS NOT NULL').fetchone()[0],len(rows))

    def test_global_raw_retirement_cannot_delete_normalized_reservoir_or_candidate_view(self):
        mint,rows=self.pump()
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:before=shared.events('pump',mint)
        # Global raw maintenance owns records/chunks, never rolling economics.
        self.h.db.execute('DELETE FROM records')
        self.h.db.execute('DELETE FROM shared_history_cache')
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:
            self.assertEqual(shared.events('pump',mint),before)
        self.h.ingest(rows)
        while self.h.lifecycle.flush():pass
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],len(rows))

    def test_model_a_migration_preserves_hash_and_original_availability(self):
        from meme_machine.solana_selective_history import SelectiveHistory
        from dataclasses import replace
        tx=FIXTURE['pump'][0]
        e=__import__('meme_machine.solana_program_decoders',fromlist=['pump_events']).pump_events(tx)[0]
        legacy=SelectiveHistory(self.state.writer,'a'*64,clock=lambda:NOW)
        rows=economic_records('pump',e['mint'],tx,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_repair')
        legacy.ingest(rows)
        before=self.h.db.execute('SELECT identity,hash,first_seen FROM canonical_evidence ORDER BY identity').fetchall()
        self.now[0]+=100
        self.h.ingest([replace(r,observed_at=self.now[0]) for r in rows])
        self.h.ingest([replace(r,observed_at=self.now[0]+1) for r in rows])
        self.assertEqual(self.h.db.execute('SELECT identity,hash,first_seen FROM canonical_evidence ORDER BY identity').fetchall(),before)

    def test_meteora_normalized_packet_is_shared_once_across_candidate_and_cold_views(self):
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        capture=json.loads(Path('tests/fixtures/meteora_account_coalescence.json').read_text())
        tx=capture['transaction'];pool=capture['counterexample']['pools'][0]['pool']
        self.h.bind('meteora',pool)
        rows=economic_records('meteora',pool,tx,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream')
        self.h.ingest(rows)
        while self.h.lifecycle.flush():pass
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:
            before=shared.events('meteora',pool)
            self.assertEqual(len(before),len(rows))
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
        self.h.db.execute('DELETE FROM records');self.h.db.execute('DELETE FROM shared_history_cache')
        self.h.ingest(rows)
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:self.assertEqual(shared.events('meteora',pool),before)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],len(rows))
        self.now[0]+=1000
        retired=ScopedRetirement(self.h).retire();self.assertEqual(retired['retired_records'],len(rows))
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:self.assertEqual(shared.events('meteora',pool),before)
    def test_two_worker_limit_and_provider_filter_limit_are_unchanged_in_authority(self):
        from meme_machine.solana_selective_source import MAX_LIVE_CANDIDATES
        from meme_machine.solana_candidate_join import candidate_subscription
        addresses={PROGRAMS['meteora']:coverage_scope('meteora',PROGRAMS['meteora'])}
        request=candidate_subscription(addresses,100,full_addresses=set(addresses))
        self.assertLessEqual((MAX_LIVE_CANDIDATES-1)+3,50)
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:self.assertEqual(shared.worker_capacity,2)
        self.assertFalse(request.blocks)

    def test_quiet_group_shares_proof_but_cannot_cover_a_nonmember_or_earlier_time(self):
        from meme_machine.solana_selective_source import commit_rolling_group
        from meme_machine.solana_candidate_join import YellowstoneTransactionFrame
        from meme_machine.yellowstone import geyser_pb2 as pb
        addresses={a:coverage_scope('meteora',a) for a in ('one','two')}
        for a in addresses:self.h.bind('meteora',a)
        self.h.bind('meteora','other')
        for slot in (100,101):
            u=pb.SubscribeUpdate();b=u.block;b.slot=slot;b.parent_slot=slot-1
            b.blockhash=str(slot);b.parent_blockhash=str(slot-1);b.block_time.timestamp=int(NOW)
            commit_rolling_group(self.state,YellowstoneTransactionFrame(u,10,NOW),addresses,'same')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],1)
        with closing(EvidenceReader(self.path)) as reader:
            for a in addresses:
                c=CandidateReader(reader,'meteora',a);self.assertTrue(c.covered(c.scope,100,100,as_of=NOW))
                self.assertFalse(c.covered(c.scope,99,100,as_of=NOW))
            c=CandidateReader(reader,'meteora','other');self.assertFalse(c.covered(c.scope,100,100,as_of=NOW))

    def test_new_program_history_starts_at_delivered_frontier_without_archive_census(self):
        import asyncio
        from types import SimpleNamespace
        from meme_machine.solana_selective_source import SelectiveSource
        from meme_machine.yellowstone import geyser_pb2 as pb
        calls=[];floors=[]
        async def run():
            source=SelectiveSource(SimpleNamespace(credential='offline',stream_url='offline'),None)
            source.stop=asyncio.Event();slot_calls=[0]
            async def work(fn,priority=1,**kwargs):return fn(self.state)
            async def rpc(method,params,family,priority=4):
                calls.append(method);self.assertEqual(method,'getSlot')
                slot_calls[0]+=1;return 100 if slot_calls[0]==1 else 104
            source.work=work;source.measured_rpc=rpc
            class Socket:
                def __init__(self):self.queue=asyncio.Queue();self.notifications=iter((11,12))
                async def send(self,raw):
                    request=json.loads(raw);self.queue.put_nowait(json.dumps(dict(id=request['id'],result=request['id']+10)))
                async def recv(self):
                    if not self.queue.empty():return await self.queue.get()
                    subscription=next(self.notifications,None)
                    if subscription is None:return await self.queue.get()
                    return json.dumps(dict(method='logsNotification',params=dict(subscription=subscription,
                        result=dict(context=dict(slot=105),value=dict(signature='failed',logs=[],err={'InstructionError':[0,0]})))))
            class Connection:
                async def __aenter__(self):return Socket()
                async def __aexit__(self,*args):pass
            async def native(channel,request,handler,family,local_stop):
                floors.append(request.from_slot)
                self.assertFalse(request.transactions)
                for slot in (106,107):
                    u=pb.SubscribeUpdate(filters=['b']);b=u.block_meta;b.slot=slot;b.parent_slot=slot-1
                    b.blockhash=str(slot);b.parent_blockhash=str(slot-1);b.block_time.timestamp=int(NOW)
                    await handler(u,u.ByteSize(),NOW)
                    u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=slot;u.slot.parent=slot-1;u.slot.status=pb.SLOT_FINALIZED
                    await handler(u,u.ByteSize(),NOW)
            source.stream=native
            desired=[dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,deadline=NOW+150,lower_slot=0,rolling=True) for f in ('pump','pumpswap')]
            with patch('meme_machine.solana_selective_source.connect',lambda *a,**kw:Connection()):await source.live(None,desired,asyncio.Event())
        asyncio.run(run())
        self.assertEqual(calls,['getSlot','getSlot']);self.assertEqual(floors,[106])
        self.assertEqual(self.h.lifecycle.missing(program_scope('pump'),106,106),[])
        self.assertEqual(self.h.lifecycle.missing(program_scope('pump'),105,106),[(105,105)])

    def test_group_readiness_publication_closes_read_cursor_before_concurrent_write(self):
        from meme_machine.solana_selective_source import commit_rolling_group
        from meme_machine.solana_candidate_join import YellowstoneTransactionFrame
        from meme_machine.yellowstone import geyser_pb2 as pb
        addresses={a:coverage_scope('meteora',a) for a in ('one','two')}
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as shared:
            for a in addresses:
                self.h.bind('meteora',a)
                shared.enqueue('meteora',a,kind='warmup',ready_at=NOW,deadline=NOW+150,
                    estimate_seconds=12,priority=30,identity=a,payload={})
                shared.wait_for_history(a,addresses[a],100,100,retry_at=NOW+120)
        original=CandidateHistory.commit_history_readiness
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as other:
            def competing_write(shared,scope,*args,**kwargs):
                if scope in addresses.values():
                    other.observe('pump','concurrent',surface='pump.fun',observed_at=int(NOW))
                return original(shared,scope,*args,**kwargs)
            with patch.object(CandidateHistory,'commit_history_readiness',competing_write):
                for slot in (100,101):
                    u=pb.SubscribeUpdate();b=u.block;b.slot=slot;b.parent_slot=slot-1
                    b.blockhash=str(slot);b.parent_blockhash=str(slot-1);b.block_time.timestamp=int(NOW)
                    commit_rolling_group(self.state,YellowstoneTransactionFrame(u,10,NOW),addresses,'same')
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as shared:
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM work_history_requirements').fetchone()[0],0)
            self.assertIsNotNone(shared.claim('first'));self.assertIsNotNone(shared.claim('second'))

    def test_owner_queue_rejection_retries_the_same_frame_without_silent_loss(self):
        import asyncio
        from meme_machine.solana_selective_source import source_work
        async def run():
            stop=asyncio.Event();calls=[]
            def frame(state):return 'committed'
            async def work(fn,priority,**options):
                calls.append((fn,priority,options))
                if len(calls)==1:raise EvidenceUnavailable('evidence_control_overloaded')
                return fn(None)
            wrapped=source_work(work,stop)
            self.assertEqual(await wrapped(frame,2,label='source_commit'),'committed')
            self.assertEqual(calls,[(frame,2,{'label':'source_commit'})]*2)
            async def unavailable(*args,**kwargs):raise EvidenceUnavailable('unresolved_evidence_gap')
            with self.assertRaisesRegex(EvidenceUnavailable,'unresolved_evidence_gap'):
                await source_work(unavailable,stop)(frame,2)
        asyncio.run(run())

if __name__=='__main__':unittest.main()
