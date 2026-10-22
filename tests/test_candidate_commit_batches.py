"""Original canonical economics, bounded FIFO batching and durable failure."""
import asyncio
import copy
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import closing
from unittest.mock import patch
import based58

from meme_machine.solana_candidate_join import YellowstoneTransactionFrame,CandidateTransactionJoin,scope_labels
from meme_machine.solana_evidence_plane import EvidenceUnavailable,digest,IntervalProof
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import (
    CandidateCommitQueue,SelectiveSource,commit_candidates,commit_candidate_batch,commit_control,
    CANDIDATE_COMMIT_BATCH,CANDIDATE_COMMIT_BYTES,
    native_commit_priority,subscription_disconnect_lower,
)
from meme_machine.yellowstone import geyser_pb2 as pb
from tests.test_solana_closure import NOW,state_at
from tests.test_solana_selective_evidence import FIXTURE


def frame(slot,*,logs=True):
    u=pb.SubscribeUpdate();b=u.block;b.slot=slot;b.parent_slot=slot-1
    b.blockhash=str(slot);b.parent_blockhash=str(slot-1);b.block_time.timestamp=int(NOW)
    if not logs:return YellowstoneTransactionFrame(u,100,NOW,replay_from_slot=100)
    tx=copy.deepcopy(FIXTURE['pump'][0]);sig=based58.b58encode(slot.to_bytes(64,'little')).decode()
    tx['transaction']['signatures']=[sig];tx['slot']=slot;tx['transactionIndex']=0;tx['blockTime']=int(NOW)
    return YellowstoneTransactionFrame(u,100,NOW,replay_from_slot=100,
        log_transactions=(tx,),candidate_statuses=((sig,0,(program_scope('pump'),),None,NOW),))


def oldest_transfer():
    """A captured authenticated supplement blocked by later-slot occupancy."""
    from tests.test_archive_full_log_content import StreamFullLogContentTests,NOW as LOG_NOW
    case=StreamFullLogContentTests()
    join,_,full,complete,_,bound=case.pressured()
    retained=copy.deepcopy(join);slot=full['slot'];sig=full['transaction']['signatures'][0]
    with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
        transferred=join.complete_deferred_log(slot,sig,complete,LOG_NOW+2)
    replay=retained.complete_deferred_log(slot,sig,complete,LOG_NOW+2)
    if transferred!=replay:raise AssertionError('oldest_transfer_changed_authenticated_frame')
    return transferred,replay,join


class CandidateCommitBatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state,self.h=state_at(Path(self.tmp.name)/'canonical.sqlite')
        self.addCleanup(self.state.writer.close)
        self.addresses={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}

    def snapshot(self,h):
        tables=('rolling_economic_events','rolling_economic_addresses','candidate_blocks',
            'candidate_pending_proofs','candidate_coverage','candidate_history_outbox')
        return {t:h.db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in tables}

    async def test_measured_owner_path_keeps_exact_economics_and_distinct_completion(self):
        baseline,h=state_at(Path(self.tmp.name)/'baseline.sqlite')
        self.addCleanup(baseline.writer.close)
        frames=[frame(100),frame(101)]
        commit_candidate_batch(baseline,frames,self.addresses,'same-session',publish=False)
        source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64),None)
        source.stop=asyncio.Event();source.batched=True;source.history_separated=True
        calls=[]
        async def work(fn,priority,**options):
            calls.append((priority,options));value=fn(self.state)
            source.stop.set();return value
        source.work=work;queue=CandidateCommitQueue()
        for value in frames:await queue.put(value)
        await asyncio.wait_for(source.candidate_commits(queue,self.addresses,'same-session'),2)
        self.assertEqual(self.snapshot(self.h),self.snapshot(h))
        self.assertEqual(calls,[(2,dict(label='source_commit',component='candidate'))])
        self.assertEqual(source.pipeline_metrics['economic_prepared:candidate']['latest_slot'],101)
        self.assertEqual(source.pipeline_metrics['evidence_timing:candidate']['latest_slot'],101)
        # A later joined frame is explicitly distinct from durable evidence;
        # reporting it cannot write evidence, consume a proof, or grant readiness.
        before=self.snapshot(self.h)
        source.observe('joined_frame',plane='candidate',slot=102,joined_wall=NOW+3)
        self.assertEqual(source.pipeline_metrics['joined_frame:candidate']['latest_slot'],102)
        self.assertEqual(source.pipeline_metrics['evidence_timing:candidate']['latest_slot'],101)
        self.assertEqual(self.snapshot(self.h),before)
        self.assertEqual(queue.count,0)

    async def test_transaction_timing_preserves_outer_commit_nested_rollback_and_failure(self):
        writer=self.state.writer;before=dict(writer.transaction_metrics)
        with writer.transaction():
            writer.db.execute("INSERT INTO meta VALUES('timing-test','committed')")
            with writer.transaction():
                writer.db.execute("UPDATE meta SET value='nested' WHERE key='timing-test'")
        self.assertEqual(writer.transaction_metrics['begin.calls'],before['begin.calls']+1)
        self.assertEqual(writer.transaction_metrics['commit.calls'],before['commit.calls']+1)
        committed=dict(writer.transaction_metrics)
        with self.assertRaisesRegex(RuntimeError,'original-failure'):
            with writer.transaction():
                with writer.transaction():
                    writer.db.execute("UPDATE meta SET value='rolled-back' WHERE key='timing-test'")
                    raise RuntimeError('original-failure')
        self.assertEqual(writer.transaction_metrics['begin.calls'],committed['begin.calls']+1)
        self.assertEqual(writer.transaction_metrics['commit.calls'],committed['commit.calls'])
        self.assertEqual(writer.db.execute("SELECT value FROM meta WHERE key='timing-test'").fetchone(),('nested',))
        self.assertFalse(writer.db.in_transaction)

    async def test_numeric_pipeline_diagnostics_are_bounded_and_do_not_write_on_each_event(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None)
        # The exclusive owner phase rows are fixed and allocated at startup;
        # decode telemetry must neither mutate them nor add per-stream rows.
        initial={key:dict(row) for key,row in source.pipeline_metrics.items()}
        self.assertEqual(set(initial),{'candidate_phase:'+name for name in (
            'validate','ingest_setup','rolling_adopt','economic_store',
            'delivery_outbox','coverage_receipt','batch_commit')}|
            {'development_phase:'+name for name in (
                'selection','reactivation','boundaries','publication','plan','commit')})
        self.assertTrue(all(value==0 for row in initial.values() for value in row.values()))
        for i in range(1000):
            source.observe('decode_timing',seconds=.001,stream_id=str(i),family='pump')
        expected=dict(initial)
        expected['decode_timing:shared']=dict(calls=1000,decode_total_microseconds=1_000_000,decode_peak_microseconds=1000)
        self.assertEqual(source.pipeline_metrics,expected)
        self.assertEqual(source.pending_diagnostics,[])
        self.assertEqual(source.native_streams,{})

    async def test_development_phase_namespace_and_transaction_exit_keep_exclusive_timing(self):
        from meme_machine.solana_candidate_phases import CandidatePhases,DEVELOPMENT_PHASES
        pipeline={};clock=dict(wall=0,cpu=0)
        timing=CandidatePhases(pipeline,phases=DEVELOPMENT_PHASES,prefix='development_phase:',
            wall=lambda:clock['wall'],cpu=lambda:clock['cpu'],runnable=lambda:None)
        self.assertEqual(set(timing.rows),{'selection','reactivation','boundaries','publication','plan','commit'})
        self.assertEqual(set(pipeline),{'development_phase:'+name for name in DEVELOPMENT_PHASES})
        self.assertTrue(all(set(row)==set(timing.rows['commit']) for row in timing.rows.values()))
        error=RuntimeError('original-development-failure');exits=[]
        class Transaction:
            def __enter__(self):clock['wall']+=8;clock['cpu']+=2;return 'original-enter'
            def __exit__(self,*failure):
                exits.append(failure);clock['wall']+=2;clock['cpu']+=.5;return False
        with self.assertRaises(RuntimeError) as caught:
            with timing.transaction_exit(Transaction(),phase_name='commit') as entered:
                self.assertEqual(entered,'original-enter')
                with timing.phase('selection'):
                    clock['wall']+=16;clock['cpu']+=4
                    raise error
        self.assertIs(caught.exception,error);self.assertIs(exits[0][1],error)
        selection=timing.rows['selection'];commit=timing.rows['commit']
        self.assertEqual((selection['calls'],selection['failed_calls'],selection['wall_seconds_total_microseconds'],selection['cpu_seconds_total_microseconds']),(1,1,16_000_000,4_000_000))
        self.assertEqual((commit['calls'],commit['failed_calls'],commit['wall_seconds_total_microseconds'],commit['cpu_seconds_total_microseconds']),(1,0,2_000_000,500_000))
        self.assertEqual(commit['runnable_unavailable_calls'],1)
        def broken_clock():raise RuntimeError('optional-recorder-failure')
        timing.wall=broken_clock
        with self.assertRaises(RuntimeError) as caught:
            with timing.phase('plan'):raise error
        self.assertIs(caught.exception,error)
        self.assertEqual((timing.rows['plan']['failed_calls'],timing.rows['plan']['unmeasured_calls']),(1,1))

    async def test_actual_development_callback_records_fixed_operations_and_original_rollback(self):
        from meme_machine.solana_candidate_phases import CandidatePhases,DEVELOPMENT_PHASES
        for fail in (False,True):
            source=SelectiveSource(SimpleNamespace(credential='offline'),None)
            source.batched=True;source.stop=asyncio.Event();events=[];clock=[0]
            source.development_phases=CandidatePhases(source.pipeline_metrics,
                phases=DEVELOPMENT_PHASES,prefix='development_phase:',
                wall=lambda:clock[0],cpu=lambda:clock[0]/2,runnable=lambda:None)
            error=RuntimeError('original-boundary-failure')
            def tick(name,value=None):events.append(name);clock[0]+=1;return value
            class DB:
                def execute(self,sql,args):
                    if sql.startswith('SELECT MAX(hi)'):return SimpleNamespace(fetchone=lambda:tick('frontier',(100,)))
                    if sql.startswith('SELECT first_seen'):return SimpleNamespace(fetchone=lambda:tick('first_seen',(NOW,)))
                    if "state='reactivated'" in sql:return SimpleNamespace(fetchall=lambda:tick('reactivation',[]))
                    raise AssertionError(sql)
            class Transaction:
                def __enter__(self):return tick('begin')
                def __exit__(self,*failure):tick('rollback' if failure[0] else 'commit');return False
            state=SimpleNamespace(writer=SimpleNamespace(db=DB(),transaction=Transaction))
            def boundaries(**options):
                self.assertEqual(options,dict(limit=16,after=0));tick('boundaries')
                if fail:raise error
                return 12
            def publication(**options):
                self.assertEqual(options,dict(limit=16,after=0));return tick('publication',13)
            history=SimpleNamespace(startup=SimpleNamespace(snapshot=lambda:tick('released',dict(released=True))),
                development_candidates=lambda *args:tick('selection',[('mint',)]),
                bind=lambda *args:tick('bind'),rolling=SimpleNamespace(
                    prepare=lambda *args,**options:tick('prepare'),resume_boundaries=boundaries,
                    resume_publication=publication),active_families={'pump','pumpswap'},
                plan=lambda **options:tick('plan'))
            async def work(fn,priority,**options):
                self.assertEqual((priority,options),(4,dict(label='candidate_development')))
                result=fn(state);source.stop.set();return result
            source.work=work
            with patch('meme_machine.solana_selective_source.install',return_value=history),patch(
                    'meme_machine.operational.position_continuation.position_only',return_value=False):
                if fail:
                    with self.assertRaises(RuntimeError) as caught:await source.acquire()
                    self.assertIs(caught.exception,error)
                else:await source.acquire()
            rows=source.development_phases.rows
            self.assertEqual(rows['selection']['calls'],2)
            self.assertEqual(rows['selection']['wall_seconds_total_microseconds'],6_000_000)
            self.assertEqual(rows['reactivation']['calls'],1)
            self.assertEqual(rows['boundaries']['calls'],1)
            self.assertEqual(rows['boundaries']['failed_calls'],int(fail))
            self.assertEqual(rows['publication']['calls'],int(not fail))
            self.assertEqual(rows['plan']['calls'],int(not fail))
            self.assertEqual(rows['commit']['calls'],1)
            self.assertEqual(rows['commit']['wall_seconds_total_microseconds'],1_000_000)
            expected=['released','frontier','begin','selection','bind','first_seen','prepare','reactivation','boundaries']
            self.assertEqual(events,expected+(['rollback'] if fail else ['publication','commit','plan']))
            if fail:
                self.assertFalse(hasattr(state,'development_cursors'))
                self.assertFalse(hasattr(state,'development_poll_at'))
            else:
                self.assertEqual(state.development_cursors,dict(reactivated=0,boundary=12,publication=13))
                self.assertTrue(hasattr(state,'development_poll_at'))

    async def test_native_input_progress_is_separate_and_missing_diagnostics_stay_unavailable(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None)
        source.native_streams['existing']=dict(messages={},samples=[])
        source.observe('native_frame',stream_id='existing',family='pump',message='slot',
            slot=104,bytes=50,seen=NOW,provider_created_at=NOW-1)
        metric=source.pipeline_metrics['native_frame:pump:slot']
        self.assertEqual((metric['latest_slot'],metric['bytes'],metric['latest_received_wall']),(104,50,NOW))
        self.assertNotIn('evidence_timing:candidate',source.pipeline_metrics)
        source.observe('native_frame',stream_id='existing',family='pump',message='transaction')
        unavailable=source.pipeline_metrics['native_frame:pump:transaction']
        self.assertNotIn('latest_slot',unavailable);self.assertNotIn('latest_received_wall',unavailable)
        self.assertEqual(unavailable['unmeasured_bytes_frames'],1)
        self.assertEqual(source.pending_diagnostics,[])

    async def test_no_owner_publication_timing_stays_unavailable_without_zero_latency(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None)
        source.observe('publication_timing',work_ready_monotonic=100,work_returned_monotonic=101)
        metric=source.pipeline_metrics['publication_timing:shared']
        self.assertEqual(metric['unmeasured_calls'],1)
        self.assertNotIn('owner_queue_total_microseconds',metric)
        self.assertNotIn('execution_total_microseconds',metric)
        self.assertEqual(source.pending_diagnostics,[])

    async def test_publication_serializes_once_with_original_receipt_and_checksum(self):
        import meme_machine.solana_candidate_lifecycle as module
        body=dict(record=dict(identity='economic',slot=100,logs=['escaped-\\-é']*100),available=NOW)
        expected=module.digest(['pump','mint','canonical',body]);checksum=module.digest(body)
        original=module.canonical;calls=[]
        def capture(value):
            if value is body:calls.append(value)
            return original(value)
        with patch.object(module,'canonical',capture):
            identity=self.h.lifecycle.emit('pump','mint','canonical',body)
        self.assertEqual(identity,expected);self.assertEqual(len(calls),1)
        row=self.h.db.execute('SELECT body,hash FROM candidate_history_outbox WHERE id=?',(identity,)).fetchone()
        self.assertEqual(row,(original(body),checksum))
        self.assertEqual(self.h.lifecycle.emit('pump','mint','canonical',body),identity)

    async def test_unfunded_intake_preserves_maintenance_fairness_and_position_priority(self):
        from meme_machine.solana_evidence_control import PriorityOwner
        entered=threading.Event();release=threading.Event();order=[]
        owner=PriorityOwner(lambda:SimpleNamespace(close=lambda:None))
        try:
            owner.ready.result(1)
            blocker=owner.submit(lambda s:(entered.set(),release.wait(2)),priority=0)
            self.assertTrue(entered.wait(1))
            archive=owner.submit(lambda s:order.append('archive'),priority=3)
            retirement=owner.submit(lambda s:order.append('retirement'),priority=4)
            priority=native_commit_priority([dict(family=f,priority=6) for f in ('pump','pumpswap')])
            native=owner.submit(lambda s:order.append('native'),priority=priority)
            protected=native_commit_priority([dict(family='pump',priority=1)])
            position=owner.submit(lambda s:order.append('position'),priority=protected)
            release.set()
            for future in (blocker,archive,retirement,native,position):future.result(1)
            self.assertEqual(order,['position','archive','retirement','native'])
            self.assertEqual(priority,2)
            self.assertEqual(native_commit_priority([dict(family='meteora',priority=6)]),2)
            self.assertEqual(owner.enqueued,{})
        finally:release.set();owner.close()

    async def test_linked_control_delivery_and_publication_share_intake_fifo(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None)
        source.stop=asyncio.Event();source.control_connected=True;calls=[];active=[]
        async def work(fn,priority,**kw):
            calls.append((priority,kw.get('label')))
            active.append((priority,kw.get('label'),kw.get('component')))
            try:result=fn(self.state)
            finally:active.pop()
            source.stop.set();return result
        source.work=work;queue=asyncio.Queue()
        for slot in (100,101):await queue.put(frame(slot,logs=False))
        await asyncio.wait_for(source.control_commits(queue),.5)
        self.assertEqual(calls,[(2,'source_commit')]);self.assertEqual(source.control_committed_slot,100)
        source.stop.clear();calls.clear()
        source.batched=True
        # Publication's delivery dependency shares the same intake/FIFO
        # owner turn. Both physical deliveries, including the duplicate, must
        # be durably charged exactly once BEFORE real proof publication.
        key=(int(NOW)//86400,'candidate_live','yellowstone')
        def meter():
            return self.h.db.execute('''SELECT raw_bytes,retained_bytes,canonical_bytes,
                ipc_bytes,rpc_cu,calls FROM provider_delivery
                WHERE day=? AND family=? AND transport=?''',key).fetchall()
        self.assertEqual(meter(),[])
        await source.delivered('candidate_live','yellowstone',100,NOW)
        await source.delivered('candidate_live','yellowstone',100,NOW)
        self.assertEqual(source.pending_delivery,{key:(200,NOW)})
        self.assertEqual(meter(),[]);self.assertEqual(calls,[])
        events=[];original_delivery=self.h.delivery;original_publish=self.h.lifecycle.publish
        def delivery(family,transport,**options):
            self.assertEqual(active,[(2,'source_commit','history_publication')])
            self.assertEqual((family,transport,options),
                ('candidate_live','yellowstone',dict(raw_bytes=200,seen=NOW)))
            self.assertEqual(meter(),[]);events.append('delivery')
            return original_delivery(family,transport,**options)
        def publish():
            self.assertEqual(active,[(2,'source_commit','history_publication')])
            self.assertEqual(events,['delivery'])
            self.assertEqual(meter(),[(200,0,0,0,0,0)])
            self.assertFalse(self.h.db.in_transaction,
                'delivery accounting must COMMIT before actual publication')
            events.append('publication')
            return original_publish()
        with patch.object(self.h,'delivery',side_effect=delivery),patch.object(
                self.h.lifecycle,'publish',side_effect=publish),patch.object(
                self.h.startup,'advance',return_value=None):
            await asyncio.wait_for(source.publish_history(),.5)
        self.assertEqual(events,['delivery','publication'])
        self.assertEqual(calls,[(2,'source_commit')])
        self.assertFalse(source.pending_delivery)
        self.assertEqual(meter(),[(200,0,0,0,0,0)])
        await source.flush_delivery();await source.flush_delivery()
        self.assertEqual(calls,[(2,'source_commit')])
        self.assertEqual(meter(),[(200,0,0,0,0,0)])

    async def test_selective_consumer_decodes_each_snapshot_body_once_and_keeps_all_history(self):
        from meme_machine import solana_selective_runtime as consumer
        from meme_machine.solana_evidence_plane import canonical
        rows=[]
        for n,kind in enumerate(('create','trade','migration')):
            event=dict(event_type=kind,mint='mint',market_time=int(NOW),index=0)
            body=dict(identity=str(n),scope='program:pump',slot=100,signature='sig'+str(n),
                transaction_index=n,event_index=0,market_time=int(NOW),payload=dict(event=event))
            rows.append((n+1,canonical(body),100,str(n),'sig'+str(n),n,0,int(NOW),NOW))
        reader=SimpleNamespace(db=self.h.db,discovery=lambda *a,**k:rows)
        tape=SimpleNamespace(plane=SimpleNamespace(_selective_reader=lambda:reader,clock=lambda:NOW))
        # This test supplies one already selected canonical snapshot. Startup
        # release and durable-history failure guards have independent coverage.
        with patch('meme_machine.solana_prewarm_startup.require_released'),patch(
                'meme_machine.runtime.candidate_history.open_candidate_history',return_value=None),patch.object(
                consumer,'decode_body',wraps=consumer.decode_body) as decode:
            events,cursor=consumer.consume_pump_discovery(tape,0)
        self.assertEqual(decode.call_count,3);self.assertEqual(cursor,3)
        self.assertEqual([e['event_type'] for e in events],['trade'])
        self.assertEqual([r['event']['event_type'] for r in tape.candidate_history_rows],['create','trade','migration'])
        self.assertEqual([r['event']['_economic_order'] for r in tape.candidate_history_rows],[0,1,2])
        self.assertTrue(all(r['event']['available_time']==int(NOW) for r in tape.candidate_history_rows))

    async def test_bounded_discovery_matches_original_order_time_and_legacy_hole_fallback(self):
        from meme_machine.solana_selective_history import ConsumerReader
        commit_candidate_batch(self.state,[frame(n) for n in range(100,108)],self.addresses,'session')
        reader=ConsumerReader(SimpleNamespace(db=self.h.db,path=self.state.writer.path,_healthy=lambda:None))
        original='''SELECT o.sequence,r.body,r.slot,r.identity,r.signature,r.transaction_index,
            r.event_index,r.market_time,r.first_seen FROM candidate_outbox o JOIN canonical_evidence r
            ON r.identity=o.identity WHERE o.scope='program:pump' AND o.sequence>? AND o.first_seen<=?
            ORDER BY o.sequence LIMIT ?'''
        for cursor,at,limit in ((0,NOW-1,2),(0,NOW,2),(0,NOW,5000)):
            self.assertEqual(reader.discovery(cursor,as_of=at,limit=limit),
                self.h.db.execute(original,(cursor,at,limit)).fetchall())
        first=reader.discovery(0,as_of=NOW,limit=2)
        later=reader.discovery(first[-1][0],as_of=NOW,limit=2)
        self.assertTrue(later);self.assertGreater(later[0][0],first[-1][0])
        # A retained legacy pointer without a canonical body must not cause
        # the bounded prefix to silently omit a later original opportunity.
        self.h.db.execute("INSERT INTO candidate_outbox(sequence,scope,identity,slot,first_seen) VALUES(0,'program:pump','legacy-hole',99,?)",(NOW,))
        self.assertEqual(reader.discovery(-1,as_of=NOW,limit=2),
            self.h.db.execute(original,(-1,NOW,2)).fetchall())

    async def test_latest_promotion_lookup_keeps_rowid_tie_order_without_economic_scan(self):
        body=dict(observed_at=NOW,first_seen=NOW,decision_deadline=NOW+120,ready_at=NOW,lower_slot=100)
        one=self.h.lifecycle.emit('pump','mint','promotion',dict(body,version=1),at=NOW)
        two=self.h.lifecycle.emit('pump','mint','promotion',dict(body,version=2),at=NOW)
        for n in range(100):self.h.lifecycle.emit('pump','mint','canonical',dict(record=dict(identity=str(n),slot=100),available=NOW))
        sql="SELECT id FROM candidate_history_outbox WHERE family=? AND address=? AND kind='promotion' ORDER BY created DESC,rowid DESC LIMIT 1"
        self.assertEqual(self.h.db.execute(sql,('pump','mint')).fetchone()[0],two)
        plan=' '.join(r[-1] for r in self.h.db.execute('EXPLAIN QUERY PLAN '+sql,('pump','mint')))
        self.assertIn('candidate_history_latest_promotion',plan);self.assertNotIn('TEMP B-TREE',plan)

    async def test_delayed_control_commit_does_not_regress_liveness_or_refresh_evidence(self):
        from meme_machine.solana_evidence_plane import EvidenceReader
        from meme_machine.solana_evidence_health import evidence_health
        from dataclasses import replace
        old=replace(frame(100,logs=False),seen=NOW-30);old.update.block.block_time.timestamp=int(NOW)-40
        self.state.fence.health('heartbeat',NOW-2)
        commit_control(self.state,old)
        health={k:json.loads(v) for k,v in self.h.db.execute('SELECT key,value FROM service_health')}
        self.assertEqual(health['heartbeat'],NOW)
        for scope in ('control:solana','program:pump','program:pumpswap'):
            self.assertEqual(health['finalized_frontier:'+scope],
                dict(slot=100,time=int(NOW)-40,seen=NOW-30))
        with closing(EvidenceReader(self.state.writer.path)) as reader:
            observed=evidence_health(reader,'control:solana',NOW)
            self.assertFalse(observed['usable'])
            self.assertEqual((observed['state'],observed['reason']),('DEGRADED','evidence_finalized_stale'))
            self.assertEqual(evidence_health(reader,'control:solana',NOW+16)['reason'],'evidence_heartbeat_stale')

    async def test_control_commit_failure_cannot_publish_a_liveness_heartbeat(self):
        before=dict(self.h.db.execute('SELECT key,value FROM service_health'))
        original=self.state.fence._health
        def fail(key,value):
            if key=='heartbeat':raise RuntimeError('offline_publication_failure')
            return original(key,value)
        with patch.object(self.state.fence,'_health',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'offline_publication_failure'):
                commit_control(self.state,frame(100,logs=False))
        self.assertEqual(dict(self.h.db.execute('SELECT key,value FROM service_health')),before)
        self.assertFalse(self.h.db.in_transaction)

    async def test_batch_retains_original_economics_order_proofs_and_restart(self):
        other,h=state_at(Path(self.tmp.name)/'original.sqlite')
        try:
            frames=[frame(n) for n in range(100,108)]
            for f in frames:commit_candidates(other,f,self.addresses,'session',publish=False)
            statements=[];self.h.db.set_trace_callback(statements.append)
            commit_candidate_batch(self.state,frames,self.addresses,'session',publish=False)
            self.assertEqual(self.snapshot(self.h),self.snapshot(h))
            self.assertEqual(sum(sql=='COMMIT' for sql in statements),1)
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
            before=self.snapshot(self.h);self.state.writer.close()
            self.state,self.h=state_at(self.state.writer.path)
            self.assertEqual(self.snapshot(self.h),before)
            self.h.lifecycle.publish();h.lifecycle.publish()
            self.assertEqual(self.snapshot(self.h),self.snapshot(h))
        finally:other.writer.close()

    async def test_failed_batch_rolls_back_economics_and_keeps_a_durable_gap(self):
        frames=[frame(n) for n in range(100,104)]
        frames[2].update.block.parent_slot=99
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_native_parent_gap'):
            commit_candidate_batch(self.state,frames,self.addresses,'session')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_blocks').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        self.assertFalse(self.h.db.in_transaction)
        self.state.writer.close();self.state,self.h=state_at(self.state.writer.path)
        self.assertEqual(self.h.db.execute("SELECT scope,lo,hi FROM candidate_gaps WHERE reason='candidate_native_batch_failed' ORDER BY scope").fetchall(),
            [(scope,100,103) for scope in sorted(self.addresses.values())])

    async def test_transferred_oldest_owner_failure_replays_after_restart_without_false_ack(self):
        transferred,replay,join=oldest_transfer();addresses=join.programs
        source=SelectiveSource(SimpleNamespace(credential='offline'),None)
        source.stop=asyncio.Event();source.batched=True
        queue=CandidateCommitQueue(lambda a,c:source.frame_census('rolling',a,c))
        await queue.put(transferred);before=self.snapshot(self.h)
        original=self.h.ingest;failure=RuntimeError('offline-transferred-owner-failure')
        def fail(records,**options):
            original(records,**options)
            raise failure
        async def owner(fn,priority,**options):return fn(self.state)
        source.work=owner
        with patch.object(self.h,'ingest',side_effect=fail):
            with self.assertRaises(RuntimeError) as caught:
                await source.candidate_commits(queue,addresses,'same-session')
        self.assertIs(caught.exception,failure)
        self.assertEqual(self.snapshot(self.h),before)
        self.assertEqual(queue.count,1)
        self.assertEqual(source.drain_snapshot()['queues']['rolling'],dict(accepted=1,committed=0,pending=1))
        # The failed owner-held frame has no ACK or fabricated coverage. Reopen
        # durable state and replay the same authenticated input into a new queue.
        path=self.state.writer.path;self.state.writer.close();self.state,self.h=state_at(path)
        self.addCleanup(self.state.writer.close)
        self.assertEqual(self.snapshot(self.h),before)
        other,h=state_at(Path(self.tmp.name)/'transfer-reference.sqlite')
        try:
            commit_candidate_batch(other,[replay],addresses,'same-session',publish=False)
            recovered=CandidateCommitQueue();await recovered.put(replay)
            done=asyncio.Event();done.set()
            await source.candidate_commits(recovered,addresses,'same-session',producer_done=done)
            self.assertEqual(self.snapshot(self.h),self.snapshot(h))
            self.assertEqual((recovered.count,recovered.bytes),(0,0))
            identities=self.h.db.execute('SELECT identity,hash,first_seen FROM rolling_economic_events ORDER BY identity').fetchall()
            self.assertTrue(identities)
            commit_candidate_batch(self.state,[replay],addresses,'same-session',publish=False)
            self.assertEqual(self.h.db.execute('SELECT identity,hash,first_seen FROM rolling_economic_events ORDER BY identity').fetchall(),identities)
        finally:other.writer.close()

    async def test_partial_head_journal_gap_and_completed_frame_survive_restart_cancel_and_owner_rollback(self):
        from tests.test_archive_full_log_content import StreamFullLogContentTests,ENDPOINT
        from meme_machine.solana_stream_log_repair import authenticate_supplement
        case=StreamFullLogContentTests();join,repairs,bound=case.multi_pressured()
        pristine=copy.deepcopy(join);first,second=repairs;slot,sig=first[0]
        addresses=join.programs;scope=next(iter(addresses.values()))
        # Match the real source ordering: the complete authenticated response
        # FULL-commits to the existing journal before transient admission.
        self.h._observation(None,'native_stream_log_supplement',first[2])
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
            self.assertIsNone(join.complete_deferred_log(slot,sig,first[1],first[3]))
        self.assertEqual(len(join.completed_log_fields),1)
        self.assertFalse(self.h.db.execute('SELECT identity FROM rolling_economic_events').fetchall())
        body=dict(plane='rolling',session='partial-head',**join.diagnostic(),
            accepted_pending=0,accepted_pending_bytes=0,drained=False,
            replay_from_slot=join.filtered_from_slot,complete_history_claim=False)
        lower=subscription_disconnect_lower(self.h,dict(scope=scope,family='pump',rolling=True),
            join.filtered_from_slot,'partial-head',fresh_rolling=True)
        lower=min(lower,body['oldest_slot'],body['early_log_min_slot'])
        body['recovery_obligations']=[dict(scope=scope,lower_slot=lower,upper_slot=None)]
        with self.state.writer.transaction():
            self.h.gap(scope,lower,None,'candidate_live_disconnect_or_filter_rebuild')
            self.h._observation(None,'source_session_drain',body)
        path=self.state.writer.path;self.state.writer.close();self.state,self.h=state_at(path)
        self.addCleanup(self.state.writer.close)
        receipt=json.loads(self.h.db.execute("SELECT body FROM acquisition_observations WHERE kind='native_stream_log_supplement'").fetchone()[0])
        retained=json.loads(self.h.db.execute("SELECT body FROM acquisition_observations WHERE kind='source_session_drain'").fetchone()[0])
        self.assertEqual(receipt,first[2]);self.assertEqual(retained,body)
        self.assertEqual(retained['oldest_missing_logs'],1)
        self.assertGreater(retained['pending_bytes'],pristine.pending_bytes)
        self.assertLessEqual(retained['recovery_obligations'][0]['lower_slot'],slot)
        self.assertIsNone(self.h.db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',(scope,)).fetchone())
        # Re-delivered native witnesses and the exact retained authenticated
        # provider input remain sufficient. This fixture does not claim that
        # production automatically restores a transient cache or its old clock.
        replay=pristine;witness=replay.deferred_log_witness(slot,sig)
        logs,_=authenticate_supplement(replay,witness,receipt['response'],ENDPOINT)
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
            self.assertIsNone(replay.complete_deferred_log(slot,sig,logs,first[3]))
            self.h._observation(None,'native_stream_log_supplement',second[2])
            repaired=replay.complete_deferred_log(*second[0],second[1],second[3])
        self.assertIsNotNone(repaired);self.assertFalse(replay.completed_log_fields)
        self.assertEqual(replay.pending_bytes,0)
        self.assertEqual(len(repaired.log_transactions),2)
        queue=CandidateCommitQueue()
        for current in range(100,100+CANDIDATE_COMMIT_BATCH):await queue.put(frame(current,logs=False))
        held=await queue.batch();before=(queue.count,queue.bytes)
        waiting=asyncio.create_task(queue.put(repaired));await asyncio.sleep(0)
        self.assertFalse(waiting.done());waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):await waiting
        self.assertEqual((queue.count,queue.bytes),before)
        self.assertLessEqual(lower,repaired.update.block.slot)
        queue.done(held);await queue.put(repaired)
        source=SelectiveSource(SimpleNamespace(credential='offline'),None)
        source.stop=asyncio.Event();source.batched=True
        async def owner(fn,priority,**options):return fn(self.state)
        source.work=owner;before=self.snapshot(self.h);original=self.h.ingest
        failure=RuntimeError('offline-multiple-head-owner-failure')
        def fail(records,**options):
            original(records,**options);raise failure
        with patch.object(self.h,'ingest',side_effect=fail):
            with self.assertRaises(RuntimeError) as caught:
                await source.candidate_commits(queue,addresses,'recovered-partial-head')
        self.assertIs(caught.exception,failure);self.assertEqual(self.snapshot(self.h),before)
        self.assertEqual(queue.count,1)
        self.state.writer.close();self.state,self.h=state_at(path)
        self.addCleanup(self.state.writer.close)
        self.assertEqual(self.snapshot(self.h),before)
        recovered=CandidateCommitQueue();await recovered.put(repaired)
        done=asyncio.Event();done.set()
        await source.candidate_commits(recovered,addresses,'recovered-partial-head',producer_done=done)
        identities=self.h.db.execute('SELECT identity,hash,first_seen FROM rolling_economic_events ORDER BY identity').fetchall()
        self.assertTrue(identities);self.assertEqual((recovered.count,recovered.bytes),(0,0))
        commit_candidate_batch(self.state,[repaired],addresses,'recovered-partial-head',publish=False)
        self.assertEqual(self.h.db.execute('SELECT identity,hash,first_seen FROM rolling_economic_events ORDER BY identity').fetchall(),identities)

    async def test_transferred_oldest_cancelled_queue_wait_reserves_no_extra_capacity(self):
        transferred,replay,join=oldest_transfer();changes=[]
        queue=CandidateCommitQueue(lambda a,c:changes.append((a,c)))
        for slot in range(100,100+CANDIDATE_COMMIT_BATCH):await queue.put(frame(slot,logs=False))
        held=await queue.batch();before=(queue.count,queue.bytes)
        waiting=asyncio.create_task(queue.put(transferred))
        await asyncio.sleep(0);self.assertFalse(waiting.done());waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):await waiting
        self.assertEqual((queue.count,queue.bytes),before)
        self.assertEqual(changes,[(1,0)]*CANDIDATE_COMMIT_BATCH)
        self.assertEqual(transferred,replay)
        # Retirement by the transient join is not durable completion. Apply
        # the production disconnect lower and gap/observation transaction used
        # by live.teardown, even though the queue never reserved this frame.
        # Its only remaining early log is later than the transferred slot.
        slot=transferred.update.block.slot;scope=next(iter(join.programs.values()))
        row=dict(scope=scope,family='pump',rolling=True)
        lower=subscription_disconnect_lower(self.h,row,transferred.replay_from_slot,
            'interrupted-transfer',fresh_rolling=True)
        body=dict(plane='rolling',session='interrupted-transfer',**join.diagnostic(),
            accepted_pending=queue.count,accepted_pending_bytes=queue.bytes,drained=False,
            replay_from_slot=transferred.replay_from_slot,complete_history_claim=False)
        pending=[n for n in (body['oldest_slot'],body['early_log_min_slot']) if n is not None and n>0]
        if pending:lower=min(lower,*pending)
        self.assertEqual(join.completed,slot);self.assertLessEqual(lower,slot)
        self.assertGreater(body['early_log_min_slot'],slot)
        body['recovery_obligations']=[dict(scope=scope,lower_slot=lower,upper_slot=None)]
        with self.state.writer.transaction():
            self.h.gap(scope,lower,None,'candidate_live_disconnect_or_filter_rebuild')
            self.h._observation(None,'source_session_drain',body)
        path=self.state.writer.path;self.state.writer.close();self.state,self.h=state_at(path)
        self.addCleanup(self.state.writer.close)
        self.assertEqual(self.h.db.execute('SELECT lo,hi FROM candidate_gaps WHERE scope=?',(scope,)).fetchall(),[(lower,None)])
        self.assertIsNone(self.h.db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',(scope,)).fetchone())
        observed=json.loads(self.h.db.execute("SELECT body FROM acquisition_observations WHERE kind='source_session_drain'").fetchone()[0])
        self.assertEqual(observed,body)
        self.assertLessEqual(observed['recovery_obligations'][0]['lower_slot'],slot)
        queue.done(held);await queue.put(replay)
        following=await queue.batch();self.assertEqual(following[0][0],replay)
        queue.done(following);await queue.join()
        self.assertEqual((queue.count,queue.bytes),(0,0))

    async def test_restart_replay_reconstructs_linkage_and_repairs_only_real_coverage(self):
        frames=[frame(n) for n in range(100,104)]
        commit_candidate_batch(self.state,frames,self.addresses,'old-session')
        before=self.h.db.execute('SELECT identity,first_seen,hash FROM rolling_economic_events ORDER BY identity').fetchall()
        for scope in self.addresses.values():self.h.gap(scope,100,102,'ordinary_disconnect')
        commit_candidate_batch(self.state,[frames[0]],self.addresses,'reconnected')
        self.assertEqual({r[0] for r in self.h.db.execute('SELECT slot FROM candidate_blocks')},{100})
        self.assertEqual(self.h.rolling.missing('pump',program_scope('pump'),100,102),[(100,102)])
        commit_candidate_batch(self.state,frames[1:],self.addresses,'reconnected')
        self.assertEqual(self.h.rolling.missing('pump',program_scope('pump'),100,102),[])
        self.assertEqual(self.h.db.execute('SELECT identity,first_seen,hash FROM rolling_economic_events ORDER BY identity').fetchall(),before)
        self.assertEqual({r[0] for r in self.h.db.execute('SELECT slot FROM candidate_blocks')},{103})
        # Cached block identity is not permission to accept a conflicting replay.
        changed=copy.deepcopy(frames[-1]);changed.update.block.blockhash='other-bank'
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_replay_receipt_conflict'):
            commit_candidate_batch(self.state,[changed],self.addresses,'third-session')

    async def test_ready_burst_commits_once_and_quiet_frame_is_immediate(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None)
        source.batched=True # The actual shared service owns its separate publisher.
        source.stop=asyncio.Event();q=CandidateCommitQueue();calls=[];statements=[]
        self.h.db.set_trace_callback(statements.append)
        async def work(fn,priority,**kw):
            calls.append(priority);result=fn(self.state);source.stop.set();return result
        source.work=work
        for slot in range(100,108):await q.put(frame(slot))
        await asyncio.wait_for(source.candidate_commits(q,self.addresses,'session',priority=0),.5)
        self.assertEqual(calls,[0]);self.assertEqual(q.count,0);self.assertEqual(q.bytes,0)
        self.assertEqual(sum(sql=='COMMIT' for sql in statements),1)
        self.assertEqual(self.h.db.execute('SELECT COUNT(DISTINCT signature) FROM rolling_economic_events').fetchone()[0],8)
        source.stop.clear();await q.put(frame(108))
        await asyncio.wait_for(source.candidate_commits(q,self.addresses,'session',priority=0),.1)
        self.assertEqual(calls,[0,0]);self.assertEqual(q.count,0)

    async def test_competing_join_producers_preserve_native_parent_order_after_backpressure(self):
        # The same join is synchronously fed by native, WS and HTTP repair
        # callbacks. A producer can emit another frame immediately after its
        # blocked put returns, before an older Event waiter resumes.
        join=CandidateTransactionJoin(self.addresses,set(),filtered_from_slot=100)
        label=scope_labels(self.addresses)[program_scope('pump')]
        emitted=[]
        def joined(slot):
            original=frame(slot);tx=original.log_transactions[0]
            sig=tx['transaction']['signatures'][0]
            self.assertIsNone(join.feed_log(slot,sig,tx['meta']['logMessages'],None,NOW))
            status=pb.SubscribeUpdate(filters=[label]);status.transaction_status.slot=slot
            status.transaction_status.index=0;status.transaction_status.signature=based58.b58decode(sig.encode())
            self.assertIsNone(join.feed(status,status.ByteSize(),NOW))
            meta=pb.SubscribeUpdate(filters=['b']);b=meta.block_meta
            b.slot=slot;b.parent_slot=slot-1;b.blockhash=str(slot);b.parent_blockhash=str(slot-1)
            b.block_time.timestamp=int(NOW);b.executed_transaction_count=1
            self.assertIsNone(join.feed(meta,meta.ByteSize(),NOW))
            final=pb.SubscribeUpdate(filters=['f']);final.slot.slot=slot
            final.slot.parent=slot-1;final.slot.status=pb.SLOT_FINALIZED
            result=join.feed(final,final.ByteSize(),NOW)
            self.assertIsNotNone(result);emitted.append(slot)
            return result
        accepted=[];queue=CandidateCommitQueue(lambda a,c:accepted.append((a,c)))
        for slot in range(100,108):await queue.put(joined(slot))
        first=await queue.batch()
        self.assertEqual(queue.count,CANDIDATE_COMMIT_BATCH)
        older_waiting=asyncio.Event()
        async def first_producer():
            await queue.put(joined(108))
            await older_waiting.wait()
            await queue.put(joined(110))
        async def second_producer():
            value=joined(109);older_waiting.set();await queue.put(value)
        producers=[asyncio.create_task(first_producer()),asyncio.create_task(second_producer())]
        try:
            await older_waiting.wait()
            self.assertFalse(any(task.done() for task in producers))
            self.assertEqual((queue.count,queue.bytes),(8,sum(row[1] for row in first)))
            commit_candidate_batch(self.state,[row[0] for row in first],self.addresses,'shared-join',publish=False)
            queue.done(first)
            await asyncio.wait_for(asyncio.gather(*producers),1)
            following=await queue.batch()
            slots=[row[0].update.block.slot for row in following]
            self.assertEqual(emitted,list(range(100,111)))
            # The original parent check and real economic writer must both
            # succeed, with every event and deferred proof retained in order.
            commit_candidate_batch(self.state,[row[0] for row in following],self.addresses,'shared-join',publish=False)
            self.assertEqual(slots,[108,109,110])
            queue.done(following);await queue.join()
            self.assertEqual((queue.count,queue.bytes),(0,0))
            self.assertEqual(accepted.count((1,0)),11)
            self.assertEqual(sum(count for _,count in accepted),11)
            self.assertEqual(self.h.db.execute('SELECT COUNT(DISTINCT signature) FROM rolling_economic_events').fetchone()[0],11)
            self.assertEqual({row[0] for row in self.h.db.execute('SELECT slot FROM candidate_blocks')},{110})
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0],20)
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_gaps').fetchone()[0],0)
            before=self.snapshot(self.h)
            self.state.writer.close();self.state,self.h=state_at(self.state.writer.path)
            self.addCleanup(self.state.writer.close)
            self.assertEqual(self.snapshot(self.h),before)
        finally:
            for task in producers:
                if not task.done():task.cancel()
            await asyncio.gather(*producers,return_exceptions=True)

    async def test_cancelled_capacity_waiters_keep_original_frame_reservations(self):
        # Cover both a producer owning the capacity wait and a subsequent
        # admission waiter. Cancellation neither ACKs nor frees owner-held work.
        for cancelled in (0,1):
            with self.subTest(cancelled=cancelled):
                changes=[];queue=CandidateCommitQueue(lambda a,c:changes.append((a,c)))
                for slot in range(100,108):await queue.put(frame(slot,logs=False))
                held=await queue.batch();before=(queue.count,queue.bytes)
                tasks=[asyncio.create_task(queue.put(frame(slot,logs=False))) for slot in (108,109)]
                await asyncio.sleep(0)
                tasks[cancelled].cancel()
                self.assertIsInstance((await asyncio.gather(tasks[cancelled],return_exceptions=True))[0],asyncio.CancelledError)
                self.assertFalse(tasks[1-cancelled].done())
                self.assertEqual((queue.count,queue.bytes),before)
                self.assertEqual(changes,[(1,0)]*8)
                queue.done(held);await asyncio.wait_for(tasks[1-cancelled],1)
                remaining=await queue.batch()
                self.assertEqual([row[0].update.block.slot for row in remaining],[109 if cancelled==0 else 108])
                queue.done(remaining);await queue.join()
                self.assertEqual((queue.count,queue.bytes),(0,0))
                self.assertEqual(sum(a for a,_ in changes),9)
                self.assertEqual(sum(c for _,c in changes),9)

    async def test_owner_held_frames_keep_count_and_byte_capacity_reserved(self):
        q=CandidateCommitQueue()
        for slot in range(100,100+CANDIDATE_COMMIT_BATCH):await q.put(frame(slot,logs=False))
        rows=await q.batch()
        waiting=asyncio.create_task(q.put(frame(200,logs=False)))
        await asyncio.sleep(0);self.assertFalse(waiting.done())
        self.assertEqual(q.count,CANDIDATE_COMMIT_BATCH)
        q.done(rows);await waiting;self.assertEqual(q.count,1)
        remaining=await q.batch();q.done(remaining);await q.join()
        self.assertEqual(q.bytes,0)
        f=frame(300,logs=False)
        f=YellowstoneTransactionFrame(f.update,CANDIDATE_COMMIT_BYTES,NOW)
        await q.put(f);rows=await q.batch()
        waiting=asyncio.create_task(q.put(frame(301,logs=False)))
        await asyncio.sleep(0);self.assertFalse(waiting.done())
        q.done(rows);await waiting;q.done(await q.batch())
        oversized=YellowstoneTransactionFrame(f.update,CANDIDATE_COMMIT_BYTES+1,NOW)
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_commit_batch_bound'):await q.put(oversized)

    async def test_busy_consumer_does_not_block_native_intake_or_advance_a_proof(self):
        from meme_machine.runtime.candidate_history import CandidateHistory
        with closing(CandidateHistory(self.h.lifecycle.path)) as consumer:
            with consumer.transaction():
                started=time.perf_counter()
                commit_candidate_batch(self.state,[frame(n) for n in range(100,104)],self.addresses,'session')
                self.assertLess(time.perf_counter()-started,.5,
                    'canonical owner waited behind the native consumer writer')
                self.assertGreater(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
                self.assertGreater(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],0)
                self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
                self.assertTrue(self.h.rolling.missing('pump',program_scope('pump'),100,102))
                self.assertFalse(self.h.db.in_transaction)
                # More valid source frames remain durable while publication waits.
                commit_candidate_batch(self.state,[frame(n) for n in range(104,108)],self.addresses,'session')
                retained=self.h.db.execute('SELECT identity,hash,first_seen FROM rolling_economic_events ORDER BY identity').fetchall()
            # A restart retains deferred obligations, not a claimed consumer ACK.
            self.state.writer.close();self.state,self.h=state_at(self.state.writer.path)
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
            self.h.lifecycle.publish()
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],0)
            self.assertEqual(self.h.rolling.missing('pump',program_scope('pump'),100,106),[])
            self.assertEqual(self.h.db.execute('SELECT identity,hash,first_seen FROM rolling_economic_events ORDER BY identity').fetchall(),retained)
            refs=consumer.db.execute('SELECT identity,hash FROM canonical_event_refs ORDER BY identity').fetchall()
            self.assertTrue(refs)
            self.h.lifecycle.publish()
            self.assertEqual(consumer.db.execute('SELECT identity,hash FROM canonical_event_refs ORDER BY identity').fetchall(),refs)

    async def test_publication_does_not_hide_a_storage_error_as_consumer_contention(self):
        commit_candidate_batch(self.state,[frame(n) for n in range(100,104)],self.addresses,'session',publish=False)
        before=self.snapshot(self.h)
        failure=sqlite3.OperationalError('offline-io-failure');failure.sqlite_errorcode=sqlite3.SQLITE_IOERR
        with patch('meme_machine.solana_candidate_lifecycle.CandidateHistory',side_effect=failure):
            with self.assertRaisesRegex(sqlite3.OperationalError,'offline-io-failure'):
                self.h.lifecycle.publish()
        self.assertEqual(self.snapshot(self.h),before)
        self.assertFalse(self.h.db.in_transaction)


    async def test_deferred_fanout_preserves_exact_outbox_full_ack_and_restart(self):
        from meme_machine.solana_derived_fanout import prepare,apply
        from meme_machine.solana_history_delivery import capture_context,capture,deliver,acknowledge
        from meme_machine.runtime.candidate_history import CandidateHistory
        other,h=state_at(Path(self.tmp.name)/'inline-fanout.sqlite')
        self.addCleanup(other.writer.close)
        frames=[frame(slot) for slot in range(100,104)]
        self.h.lifecycle.delivery_separated=True;h.lifecycle.delivery_separated=True
        commit_candidate_batch(other,frames,self.addresses,'fanout-session',publish=False)
        commit_candidate_batch(self.state,frames,self.addresses,'fanout-session',publish=False,defer_fanout=True)
        expected=self.snapshot(h);actual=self.snapshot(self.h)
        self.assertTrue(expected['candidate_history_outbox'])
        self.assertEqual(actual['candidate_history_outbox'],[])
        self.assertEqual({k:v for k,v in actual.items() if k!='candidate_history_outbox'},
            {k:v for k,v in expected.items() if k!='candidate_history_outbox'})
        pending=self.h.db.execute('SELECT * FROM candidate_derived_fanout ORDER BY rowid').fetchall()
        self.assertTrue(pending)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        # Restart after the canonical FULL commit, before any derived output.
        # Neither replay of the same input nor restart may invent an ACK.
        path=self.state.writer.path;self.state.writer.close();self.state,self.h=state_at(path)
        self.addCleanup(self.state.writer.close);self.h.lifecycle.delivery_separated=True
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_derived_fanout ORDER BY rowid').fetchall(),pending)
        commit_candidate_batch(self.state,frames,self.addresses,'fanout-session',publish=False,defer_fanout=True)
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_derived_fanout ORDER BY rowid').fetchall(),pending)
        context=capture_context(self.h.lifecycle)
        while (product:=prepare(context.canonical_path,context.endpoint_identity,context.source_identity)) is not None:
            self.assertTrue(apply(self.h.lifecycle,product))
        self.assertEqual(self.snapshot(self.h),expected)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_derived_fanout').fetchone()[0],0)
        # Exercise the same separated consumer FULL and fresh canonical ACK on
        # both paths. Compare decoded authenticated economics, not DB paths.
        observations=[]
        for history in (h,self.h):
            life=history.lifecycle;snapshot=capture(life)
            self.assertTrue(snapshot['rows']);result=deliver(snapshot)
            self.assertEqual(history.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],len(snapshot['rows']))
            self.assertTrue(acknowledge(life,snapshot,result))
            self.assertEqual(history.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],0)
            with closing(CandidateHistory(life.path,clock=lambda:NOW)) as shared:
                keys=shared.db.execute('SELECT DISTINCT lane,candidate FROM canonical_event_refs ORDER BY lane,candidate').fetchall()
                observations.append([(key,list(shared.events(*key))) for key in keys])
        self.assertTrue(observations[0]);self.assertEqual(*observations)
        self.assertEqual(self.snapshot(self.h),self.snapshot(h))

    async def test_deferred_intake_releases_eight_frame_reservation_before_slow_preparation(self):
        from concurrent.futures import ThreadPoolExecutor
        from meme_machine.solana_derived_fanout import prepare
        from meme_machine.solana_history_delivery import capture_context
        from meme_machine.solana_history_notifications import install as notifications
        source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64),None)
        source.stop=asyncio.Event();source.batched=True;source.history_separated=True
        source.delivery_capture_context=capture_context(self.h.lifecycle)
        self.h.lifecycle.delivery_separated=True
        async def work(fn,priority,**options):return fn(self.state)
        work.candidate_delivery_fanout=True;source.work=work
        notifications(self.h,asyncio.get_running_loop(),source.history_changed)
        entered=threading.Event();release=threading.Event();pool=ThreadPoolExecutor(max_workers=1)
        source.preparation_executor=pool
        def slow(*args):
            product=prepare(*args)
            if product is not None:
                entered.set()
                if not release.wait(3):raise AssertionError('offline-fanout-test-release-missing')
            return product
        queue=CandidateCommitQueue();done=asyncio.Event();done.set()
        for slot in range(100,108):await queue.put(frame(slot))
        consumer=None
        try:
            with patch('meme_machine.solana_derived_fanout.prepare',side_effect=slow):
                consumer=source.fanout_task=asyncio.create_task(source.derived_fanout())
                await asyncio.wait_for(source.candidate_commits(queue,self.addresses,'slow-fanout',producer_done=done),2)
                self.assertTrue(await asyncio.to_thread(entered.wait,2))
                self.assertEqual((queue.count,queue.bytes),(0,0))
                self.assertGreater(self.h.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0],0)
                self.assertGreater(self.h.db.execute('SELECT COUNT(*) FROM candidate_derived_fanout').fetchone()[0],0)
                self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],0)
                self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
                # New native frame admission and an unrelated owner transaction
                # can progress while derived CPU preparation holds no owner or
                # canonical read transaction. This is not claimed as throughput.
                for slot in range(108,116):await asyncio.wait_for(queue.put(frame(slot)),1)
                self.assertEqual(queue.count,CANDIDATE_COMMIT_BATCH)
                with self.state.writer.transaction():
                    self.h.db.execute("INSERT INTO service_health VALUES('fanout-owner-progress','1')")
                self.assertEqual(self.h.db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0],0)
                release.set();source.fanout_done.set();source.fanout_wakeup.notify()
                await asyncio.wait_for(consumer,2)
        finally:
            release.set();source.fanout_done.set();source.fanout_wakeup.notify()
            if consumer is not None and not consumer.done():consumer.cancel()
            if consumer is not None:await asyncio.gather(consumer,return_exceptions=True)
            pool.shutdown(wait=True)

    async def test_deferred_capacity_rolls_back_whole_frame_batch_without_false_gap(self):
        from meme_machine.solana_derived_fanout import FanoutBackpressure
        before=self.snapshot(self.h)
        with patch('meme_machine.solana_derived_fanout.MAX_RECORDS',1):
            with self.assertRaises(FanoutBackpressure):
                commit_candidate_batch(self.state,[frame(100),frame(101)],self.addresses,'bounded-fanout',publish=False,defer_fanout=True)
        self.assertEqual(self.snapshot(self.h),before)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_derived_fanout').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_gaps').fetchone()[0],0)
        self.assertFalse(self.h.db.in_transaction)
        commit_candidate_batch(self.state,[frame(100)],self.addresses,'bounded-fanout',publish=False,defer_fanout=True)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_derived_fanout').fetchone()[0],1)

    async def test_deferred_preparation_rejects_fresh_binding_change_without_losing_intent(self):
        from meme_machine.solana_derived_fanout import prepare,apply
        from meme_machine.solana_history_delivery import capture_context
        from meme_machine.solana_selective_history import economic_records
        rows=economic_records('pump',PROGRAMS['pump'],copy.deepcopy(FIXTURE['pump'][0]),
            endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream')
        mint=next(row.payload['event']['mint'] for row in rows if row.kind=='event')
        self.h.bind('pump','retained-alias',market_address=mint)
        commit_candidate_batch(self.state,[frame(100)],self.addresses,'binding-fanout',publish=False,defer_fanout=True)
        before=self.h.db.execute('SELECT * FROM candidate_derived_fanout ORDER BY rowid').fetchall()
        context=capture_context(self.h.lifecycle)
        product=prepare(context.canonical_path,context.endpoint_identity,context.source_identity)
        self.assertIsNotNone(product)
        with self.state.writer.transaction():
            self.h.db.execute("UPDATE evidence_bindings SET market_address='changed' WHERE family='pump' AND address='retained-alias'")
        self.assertFalse(apply(self.h.lifecycle,product))
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_derived_fanout ORDER BY rowid').fetchall(),before)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],0)
        with self.state.writer.transaction():
            self.h.db.execute("UPDATE evidence_bindings SET market_address=? WHERE family='pump' AND address='retained-alias'",(mint,))
        self.assertTrue(apply(self.h.lifecycle,product))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_derived_fanout').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT DISTINCT address FROM candidate_history_outbox').fetchall(),[('retained-alias',)])


if __name__=='__main__':unittest.main()


class PublicationSQLCostTests(unittest.TestCase):
    """N-U binding SELECTs, 2N receipt statements and 31E empty-phase SQL saved.

    Counts describe delivery rows/batches, not measured market speed or fsyncs.
    Removing an empty writer can remove only its unnecessary SQLITE_BUSY;
    necessary write/authentication/outer FULL rollback guarantees remain.
    """
    from tests import test_solana_history_separation as _fixtures
    setUp=_fixtures.HistorySeparationTests.setUp
    tearDown=_fixtures.HistorySeparationTests.tearDown
    pump=_fixtures.HistorySeparationTests.pump
    seal=_fixtures.HistorySeparationTests.seal

    def test_capture_reuses_repeated_and_missing_bindings_only_for_its_owner_turn(self):
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge
        life=self.h.lifecycle;life.delivery_separated=True
        self.h.bind('pump','bound',market_address='original-mint')
        for index,address in enumerate(('bound','missing','bound','missing','bound')):
            life.emit('pump',address,'scout',dict(fields=dict(index=index)))
        lookups=[]
        query='SELECT market_address FROM evidence_bindings WHERE family='
        self.h.db.set_trace_callback(lambda sql:lookups.append(sql) if sql.startswith(query) else None)
        try:snapshot=capture(life)
        finally:self.h.db.set_trace_callback(None)
        self.assertEqual(len(snapshot['rows']),5)
        self.assertEqual(len(lookups),2)
        self.assertEqual(snapshot['bindings'],{('pump','bound'):('original-mint',),('pump','missing'):None})
        result=deliver(snapshot)
        # A later owner turn can change either a known or absent binding. The
        # original snapshot must never authorize ACK using the capture memo.
        with self.state.writer.transaction():
            self.h.db.execute("UPDATE evidence_bindings SET market_address='changed-mint' WHERE family='pump' AND address='bound'")
        self.assertFalse(acknowledge(life,snapshot,result))
        self.assertEqual(capture(life)['bindings'][('pump','bound')],('changed-mint',))
        with self.state.writer.transaction():
            self.h.db.execute("UPDATE evidence_bindings SET market_address='original-mint' WHERE family='pump' AND address='bound'")
        self.h.bind('pump','missing',market_address='late-mint')
        self.assertFalse(acknowledge(life,snapshot,result))
        self.assertEqual(capture(life)['bindings'][('pump','missing')],('late-mint',))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],5)
        with self.state.writer.transaction():
            self.h.db.execute("DELETE FROM evidence_bindings WHERE family='pump' AND address='missing'")
        self.assertTrue(acknowledge(life,snapshot,result))


    def test_row_only_delivery_uses_one_full_commit_without_receipt_savepoints(self):
        from contextlib import closing
        from meme_machine.runtime.candidate_history import CandidateHistory
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge
        life=self.h.lifecycle;life.delivery_separated=True
        for index in range(3):life.emit('pump','scout-'+str(index),'scout',dict(fields=dict(index=index)))
        snapshot=capture(life)
        self.assertEqual(snapshot['proofs'],[]);self.assertEqual(snapshot['refresh'],[])
        original=CandidateHistory.__init__;opened=[];statements=[]
        def initialize(shared,*args,**kwargs):
            original(shared,*args,**kwargs)
            opened.append(shared.path);shared.db.set_trace_callback(statements.append)
        with patch.object(CandidateHistory,'__init__',initialize):result=deliver(snapshot)
        self.assertEqual(opened,[life.path])
        verbs=[sql.lstrip().split(None,1)[0].upper() for sql in statements]
        self.assertEqual(verbs.count('BEGIN'),1);self.assertEqual(verbs.count('COMMIT'),1)
        # Each scout's observe keeps its existing savepoint. The receipt no
        # longer adds a second pair inside the same outer FULL transaction.
        self.assertEqual(verbs.count('SAVEPOINT'),3);self.assertEqual(verbs.count('RELEASE'),3)
        self.assertEqual(sum(sql.startswith('INSERT OR IGNORE INTO source_receipts') for sql in statements),3)
        self.assertTrue(acknowledge(life,snapshot,result))
        with closing(CandidateHistory(life.path)) as shared:
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM source_receipts').fetchone()[0],3)
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0],3)


    def test_intermediate_receipt_error_rolls_back_candidates_and_all_receipts(self):
        from contextlib import closing
        from meme_machine.runtime.candidate_history import CandidateHistory
        from meme_machine.runtime.sqlite_failure import Connection
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge
        life=self.h.lifecycle;life.delivery_separated=True
        for index in range(3):life.emit('pump','scout-'+str(index),'scout',dict(fields=dict(index=index)))
        snapshot=capture(life)
        pending=self.h.db.execute('SELECT * FROM candidate_history_outbox ORDER BY id').fetchall()
        original=Connection.execute;receipts=[]
        error=sqlite3.OperationalError('offline_intermediate_receipt_insert_failed')
        def insert(db,sql,parameters=()):
            if sql.startswith('INSERT OR IGNORE INTO source_receipts'):
                receipts.append(parameters[0])
                if len(receipts)==2:raise error
            return original(db,sql,parameters)
        with patch.object(Connection,'execute',insert):
            with self.assertRaises(sqlite3.OperationalError) as caught:deliver(snapshot)
        self.assertIs(caught.exception,error);self.assertEqual(len(receipts),2)
        with closing(CandidateHistory(life.path)) as shared:
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM source_receipts').fetchone()[0],0)
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_history_outbox ORDER BY id').fetchall(),pending)
        repeated=capture(life)
        self.assertEqual(repeated['rows'],snapshot['rows'])
        self.assertTrue(acknowledge(life,repeated,deliver(repeated)))


    def test_final_metadata_error_rolls_back_native_references_and_receipts(self):
        from contextlib import closing
        from meme_machine.runtime.candidate_history import CandidateHistory
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge
        life=self.h.lifecycle;life.delivery_separated=True;self.pump()
        snapshot=capture(life);self.assertTrue(snapshot['rows'])
        pending=self.h.db.execute('SELECT * FROM candidate_history_outbox ORDER BY id').fetchall()
        original=CandidateHistory.observe_pump_source_groups
        error=RuntimeError('offline_final_metadata_fold_failed');finished=[]
        def fold(shared,groups):
            receipts=shared.db.execute('SELECT COUNT(*) FROM source_receipts').fetchone()[0]
            if receipts==len(snapshot['rows']):
                finished.append(receipts);raise error
            return original(shared,groups)
        with patch.object(CandidateHistory,'observe_pump_source_groups',fold):
            with self.assertRaises(RuntimeError) as caught:deliver(snapshot)
        self.assertIs(caught.exception,error);self.assertEqual(finished,[len(snapshot['rows'])])
        with closing(CandidateHistory(life.path)) as shared:
            for table in ('candidates','events','canonical_event_refs','source_receipts'):
                self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0,table)
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_history_outbox ORDER BY id').fetchall(),pending)
        repeated=capture(life);self.assertEqual(repeated['rows'],snapshot['rows'])
        self.assertTrue(acknowledge(life,repeated,deliver(repeated)))


    def test_proof_only_delivery_retains_initial_receipt_schema_and_second_commit(self):
        from contextlib import closing
        from meme_machine.runtime.candidate_history import CandidateHistory
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge
        life=self.h.lifecycle;life.delivery_separated=True;scope=program_scope('pump')
        life.defer_proof(IntervalProof(scope,100,100,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=100,upper_slot=100,
                 lineage_hash=digest([scope,100])),NOW))
        snapshot=capture(life)
        self.assertEqual(snapshot['rows'],[]);self.assertTrue(snapshot['proofs'])
        original=CandidateHistory.__init__;opened=[]
        def initialize(shared,*args,**kwargs):
            original(shared,*args,**kwargs);opened.append(shared.path)
        with patch.object(CandidateHistory,'__init__',initialize):result=deliver(snapshot)
        self.assertEqual(opened,[life.path,life.path])
        with closing(CandidateHistory(life.path)) as shared:
            self.assertEqual(shared.db.execute("SELECT COUNT(*) FROM source_receipts WHERE kind='coverage'").fetchone()[0],1)
        self.assertTrue(acknowledge(life,snapshot,result))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
