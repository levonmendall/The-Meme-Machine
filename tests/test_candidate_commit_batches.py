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

from meme_machine.solana_candidate_join import YellowstoneTransactionFrame
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import (
    CandidateCommitQueue,SelectiveSource,commit_candidates,commit_candidate_batch,commit_control,
    CANDIDATE_COMMIT_BATCH,CANDIDATE_COMMIT_BYTES,
    native_commit_priority,
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
        for i in range(1000):
            source.observe('decode_timing',seconds=.001,stream_id=str(i),family='pump')
        self.assertEqual(source.pipeline_metrics,{'decode_timing:shared':dict(
            calls=1000,decode_total_microseconds=1_000_000,decode_peak_microseconds=1000)})
        self.assertEqual(source.pending_diagnostics,[])
        self.assertEqual(source.native_streams,{})

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
        source.stop=asyncio.Event();source.control_connected=True;calls=[]
        async def work(fn,priority,**kw):
            calls.append((priority,kw.get('label')));result=fn(self.state)
            source.stop.set();return result
        source.work=work;queue=asyncio.Queue()
        for slot in (100,101):await queue.put(frame(slot,logs=False))
        await asyncio.wait_for(source.control_commits(queue),.5)
        self.assertEqual(calls,[(2,'source_commit')]);self.assertEqual(source.control_committed_slot,100)
        source.stop.clear();calls.clear()
        source.batched=True
        # Publication's delivery dependency must share its intake/FIFO class.
        # Every byte, including duplicate deliveries, remains accounted.
        await source.delivered('candidate_live','yellowstone',100,NOW)
        await source.delivered('candidate_live','yellowstone',100,NOW)
        with patch.object(self.h.startup,'advance',return_value=None):
            await asyncio.wait_for(source.publish_history(),.5)
        self.assertEqual(calls,[(2,'source_commit'),(2,'source_commit')])
        self.assertFalse(source.pending_delivery)

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


if __name__=='__main__':unittest.main()
