"""Preparation/committed-wakeup equivalence; no market or installed epoch IO."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import copy
import os
from dataclasses import replace
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tests.test_solana_closure import NOW,state_at
from tests.test_solana_selective_evidence import FIXTURE
from meme_machine.solana_candidate_join import YellowstoneTransactionFrame
from meme_machine.solana_candidate_phases import CandidatePhases,PHASES
from meme_machine.solana_economic_preparation import prepare_candidate_frames,prepare_economic_record
from meme_machine.solana_evidence_plane import EvidenceUnavailable,EvidenceConflict,IntervalProof,digest
from meme_machine.solana_history_delivery import capture,deliver,acknowledge
from meme_machine.solana_history_notifications import WorkPulse,install as notifications
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS,economic_records
from meme_machine.solana_selective_source import SelectiveSource,commit_candidates,commit_candidate_batch,CandidateCommitQueue
from meme_machine.yellowstone import geyser_pb2 as pb


def frame(tx,family):
    tx=copy.deepcopy(tx);u=pb.SubscribeUpdate();b=u.block
    b.slot=tx['slot'];b.parent_slot=b.slot-1;b.blockhash='fixture-'+str(b.slot)
    b.parent_blockhash='fixture-'+str(b.parent_slot);b.block_time.timestamp=tx['blockTime']
    return YellowstoneTransactionFrame(u,len(str(tx)),NOW,replay_from_slot=b.slot,
        log_transactions=(tx,),candidate_statuses=((tx['transaction']['signatures'][0],
            tx['transactionIndex'],(program_scope(family),),tx['meta']['err'],NOW),))


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state,self.h=state_at(Path(self.tmp.name)/'canonical.sqlite')
        self.addCleanup(self.state.writer.close)
    def addresses(self,family):return {PROGRAMS[family]:program_scope(family)}
    def test_fixed_phases_preserve_economic_bytes_and_transaction_statement_order(self):
        from itertools import count
        other,h=state_at(Path(self.tmp.name)/'phase-comparison.sqlite')
        original=[];measured=[];pipeline={}
        runnable=count(0,1000)
        timing=CandidatePhases(pipeline,wall=count(0,.1).__next__,cpu=count(0,.01).__next__,
            runnable=lambda:(1,2,next(runnable)))
        keys={name:set(row) for name,row in pipeline.items()}
        f=frame(FIXTURE['pump'][0],'pump');addresses=self.addresses('pump')
        products,_=prepare_candidate_frames((f,),addresses,'phase-session','a'*64)
        def trace(target):return lambda sql:target.append(sql.lstrip().split(None,1)[0])
        try:
            other.writer.db.set_trace_callback(trace(original))
            commit_candidate_batch(other,(f,),addresses,'phase-session',publish=False,prepared=products)
            self.state.writer.db.set_trace_callback(trace(measured))
            commit_candidate_batch(self.state,(f,),addresses,'phase-session',publish=False,
                prepared=products,timing=timing)
            self.assertEqual(measured,original)
            for table,order in (('rolling_economic_events','identity'),('rolling_economic_addresses','identity,address'),
                    ('candidate_content_receipts','identity'),('rolling_event_lineage','identity'),
                    ('candidate_lifecycle','family,address'),('candidate_history_outbox','id'),
                    ('candidate_outbox','sequence'),('native_order_attestations','scope,slot,signature'),
                    ('candidate_blocks','scope')):
                self.assertEqual(self.h.db.execute('SELECT * FROM '+table+' ORDER BY '+order).fetchall(),
                    h.db.execute('SELECT * FROM '+table+' ORDER BY '+order).fetchall(),table)
            self.assertEqual({name:set(row) for name,row in pipeline.items()},keys)
            self.assertEqual(set(timing.rows),set(PHASES))
            for name,row in timing.rows.items():
                self.assertEqual(row['calls'],2 if name=='ingest_setup' else 1,name)
                self.assertEqual(row['failed_calls'],0,name)
                self.assertEqual(row['unmeasured_calls'],0,name)
                self.assertEqual(row['runnable_measured_calls'],row['calls'],name)
                self.assertEqual(row['runnable_unavailable_calls'],0,name)
                self.assertGreater(row['wall_seconds_total_microseconds'],0,name)
                self.assertGreater(row['cpu_seconds_total_microseconds'],0,name)
                self.assertEqual(row['runnable_wait_seconds_total_microseconds'],row['calls'],name)
        finally:other.writer.close()

    def test_phase_failures_preserve_original_rollback_and_retry_obligations(self):
        pipeline={};timing=CandidatePhases(pipeline,runnable=lambda:None)
        f=frame(FIXTURE['pump'][0],'pump');addresses=self.addresses('pump')
        products,_=prepare_candidate_frames((f,),addresses,'phase-failure','a'*64)
        original=sqlite3.OperationalError('offline_original_store_failure')
        with patch.object(self.h.rolling,'store_many',side_effect=original):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                commit_candidate_batch(self.state,(f,),addresses,'phase-failure',publish=False,
                    prepared=products,timing=timing)
        self.assertIs(caught.exception,original)
        for table in ('rolling_economic_events','candidate_outbox','candidate_blocks'):
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT reason FROM candidate_gaps').fetchone()[0],
            'candidate_native_batch_failed')
        self.assertEqual(timing.rows['economic_store']['failed_calls'],1)
        self.assertEqual(timing.rows['batch_commit']['calls'],1) # Original transaction rollback exit.
        self.assertEqual(timing.rows['economic_store']['runnable_unavailable_calls'],1)
        commit_candidate_batch(self.state,(f,),addresses,'phase-failure',publish=False,
            prepared=products,timing=timing)
        self.assertGreater(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertGreater(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],0)
        self.assertEqual(timing.rows['economic_store']['calls'],2)
        self.assertEqual(timing.rows['economic_store']['failed_calls'],1)

    def test_phase_probe_loss_and_transaction_exit_preserve_original_exceptions(self):
        from itertools import count
        values=iter(((1,2,1000),(1,3,2000)))
        timing=CandidatePhases({},wall=count(0,.1).__next__,cpu=count(0,.01).__next__,
            runnable=lambda:next(values))
        with timing.phase('validate'):pass
        self.assertEqual(timing.rows['validate']['runnable_unavailable_calls'],1)
        self.assertEqual(timing.rows['validate']['runnable_measured_calls'],0)
        original=sqlite3.OperationalError('offline_original_commit_failure')
        class Transaction:
            def __enter__(self):return 'original-token'
            def __exit__(self,*error):raise original
        def failed_probe():raise OSError('offline_clock_probe')
        timing=CandidatePhases({},wall=failed_probe,runnable=failed_probe)
        with self.assertRaises(sqlite3.OperationalError) as caught:
            with timing.transaction_exit(Transaction()) as token:self.assertEqual(token,'original-token')
        self.assertIs(caught.exception,original)
        self.assertEqual(timing.rows['batch_commit']['calls'],1)
        self.assertEqual(timing.rows['batch_commit']['failed_calls'],1)
        self.assertEqual(timing.rows['batch_commit']['unmeasured_calls'],1)
        self.assertEqual(timing.rows['batch_commit']['runnable_unavailable_calls'],1)
        before=set(timing.rows)
        with self.assertRaisesRegex(ValueError,'candidate_phase_identity'):
            with timing.phase('arbitrary_record_identity'):pass
        self.assertEqual(set(timing.rows),before)

    def test_prepared_owner_path_preserves_all_economic_and_delivery_bytes(self):
        other,h=state_at(Path(self.tmp.name)/'comparison.sqlite')
        try:
            for family in ('pump','pumpswap'):
                slots={}
                for tx in FIXTURE[family]:slots.setdefault(tx['slot'],[]).append(frame(tx,family))
                for parts in slots.values():
                    f=replace(parts[0],log_transactions=tuple(t for p in parts for t in p.log_transactions),
                        candidate_statuses=tuple(s for p in parts for s in p.candidate_statuses))
                    addresses=self.addresses(family)
                    # This cohort contains sparse slots, each an independent
                    # replay session. It cannot establish missing slot coverage.
                    session='fixture-'+str(f.update.block.slot)
                    commit_candidates(other,f,addresses,session,publish=False)
                    products,_=prepare_candidate_frames((f,),addresses,session,'a'*64)
                    with patch('meme_machine.solana_selective_source.economic_records',side_effect=AssertionError('owner decoding')):
                        commit_candidates(self.state,f,addresses,session,publish=False,prepared=products[0])
            for table,order in (('rolling_economic_events','identity'),('rolling_economic_addresses','identity,address'),
                    ('candidate_content_receipts','identity'),('rolling_event_lineage','identity'),
                    ('candidate_lifecycle','family,address'),('candidate_history_outbox','id'),
                    ('native_order_attestations','scope,slot,signature'),('candidate_blocks','scope')):
                self.assertEqual(self.h.db.execute('SELECT * FROM '+table+' ORDER BY '+order).fetchall(),
                    h.db.execute('SELECT * FROM '+table+' ORDER BY '+order).fetchall(),table)
        finally:other.writer.close()
    def test_replay_restart_retains_original_availability_and_no_duplicates(self):
        f=frame(FIXTURE['pump'][0],'pump');a=self.addresses('pump')
        p,_=prepare_candidate_frames((f,),a,'session','a'*64)
        commit_candidates(self.state,f,a,'session',publish=False,prepared=p[0])
        before=self.h.db.execute('SELECT * FROM rolling_economic_events ORDER BY identity').fetchall()
        self.state.writer.close();self.state,self.h=state_at(Path(self.tmp.name)/'canonical.sqlite')
        f=replace(f,seen=NOW+10,candidate_statuses=tuple((*r[:4],NOW+10) for r in f.candidate_statuses))
        p,_=prepare_candidate_frames((f,),a,'restart','a'*64)
        commit_candidates(self.state,f,a,'restart',publish=False,prepared=p[0])
        self.assertEqual(before,self.h.db.execute('SELECT * FROM rolling_economic_events ORDER BY identity').fetchall())
    def test_stale_source_session_or_frame_is_refused_before_writes(self):
        f=frame(FIXTURE['pump'][0],'pump');a=self.addresses('pump')
        p,_=prepare_candidate_frames((f,),a,'session','a'*64)
        for changed,session in ((replace(f,seen=NOW+1),'session'),(f,'different')):
            with self.assertRaisesRegex(EvidenceUnavailable,'preparation_source_changed'):
                commit_candidates(self.state,changed,a,session,publish=False,prepared=p[0])
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)

    def test_partial_bulk_failure_preserves_frame_rollback_pending_delivery_and_exact_retry(self):
        f=frame(FIXTURE['pump'][0],'pump');addresses=self.addresses('pump')
        products,_=prepare_candidate_frames((f,),addresses,'bulk-frame','a'*64)
        db=self.h.db;original=sqlite3.OperationalError('offline_partial_bulk_lineage_failure')
        class Partial:
            def __getattr__(self,name):return getattr(db,name)
            def executemany(self,sql,values):
                if sql.startswith('INSERT OR IGNORE INTO rolling_event_lineage'):
                    db.executemany(sql,list(values)[:1]);raise original
                return db.executemany(sql,values)
        self.h.rolling.db=Partial()
        try:
            with self.assertRaises(sqlite3.OperationalError) as caught:
                commit_candidate_batch(self.state,(f,),addresses,'bulk-frame',publish=False,prepared=products)
            self.assertIs(caught.exception,original)
        finally:self.h.rolling.db=db
        for table in ('rolling_economic_events','rolling_economic_addresses','candidate_content_receipts',
                      'rolling_event_lineage','native_order_attestations','candidate_outbox',
                      'candidate_history_outbox','candidate_blocks'):
            self.assertEqual(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0,table)
        self.assertEqual(db.execute('SELECT reason FROM candidate_gaps').fetchone()[0],'candidate_native_batch_failed')
        self.assertFalse(db.in_transaction)
        commit_candidate_batch(self.state,(f,),addresses,'bulk-frame',publish=False,prepared=products)
        before=db.execute('SELECT * FROM rolling_economic_events ORDER BY identity').fetchall()
        self.assertTrue(before)
        self.assertGreater(db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],0)
        commit_candidate_batch(self.state,(f,),addresses,'bulk-frame',publish=False,prepared=products)
        self.assertEqual(db.execute('SELECT * FROM rolling_economic_events ORDER BY identity').fetchall(),before)
        self.assertEqual(db.execute('SELECT COUNT(DISTINCT identity),COUNT(*) FROM candidate_outbox').fetchone()[0],len(before))
    def test_mutable_parent_check_still_persists_failure_witness(self):
        f=frame(FIXTURE['pump'][0],'pump');a=self.addresses('pump');scope=program_scope('pump')
        p,_=prepare_candidate_frames((f,),a,'session','a'*64)
        b=f.update.block
        self.h.db.execute('INSERT INTO candidate_blocks VALUES(?,?,?,?,?,?,?,?,?)',
            (scope,b.slot-2,b.slot-3,'conflicting','previous',b.block_time.timestamp,NOW,'session','checksum'))
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_native_parent_gap'):
            commit_candidates(self.state,f,a,'session',publish=False,prepared=p[0])
        self.assertEqual(self.h.db.execute('SELECT reason FROM candidate_gaps').fetchone()[0],'candidate_native_parent_gap')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
    def test_changed_economics_conflicts_at_owner_and_unprepared_inputs_still_validate(self):
        r=economic_records('pump',PROGRAMS['pump'],FIXTURE['pump'][0],endpoint_identity='a'*64,
            seen=NOW,source='alchemy_finalized_stream')[0]
        self.h.ingest((prepare_economic_record(r),))
        changed=replace(r,payload=dict(r.payload,event=dict(r.payload['event'],unexpected_value=1)))
        with self.assertRaisesRegex(EvidenceConflict,'economic_content_conflict'):
            self.h.ingest((prepare_economic_record(changed),))
        with self.assertRaisesRegex(ValueError,'credential'):
            prepare_economic_record(replace(r,payload=dict(r.payload,secret='api_key=secret')))
    def test_configured_string_path_supports_capture_delivery_and_restart(self):
        from meme_machine.solana_candidate_lifecycle import CandidateLifecycle
        path=Path(self.tmp.name)/'configured-candidate.sqlite'
        with patch.dict(os.environ,{'MM_SOLANA_CANDIDATE_HISTORY_DB':str(path)}):
            life=CandidateLifecycle(self.h);life.delivery_separated=True
            self.assertEqual(life.path,path)
            life.emit('pump','candidate','scout',dict(slot=1,seen=NOW,fields={}))
            snapshot=capture(life);self.assertEqual(snapshot['candidate_path'],str(path))
            self.assertTrue(acknowledge(life,snapshot,deliver(snapshot)))
            self.assertIsNone(capture(CandidateLifecycle(self.h)))


class WakeupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.state,self.h=state_at(Path(self.tmp.name)/'canonical.sqlite')
        self.h.lifecycle.delivery_separated=True
        self.source=SelectiveSource(SimpleNamespace(identity='a'*64),None,token='offline')
        self.source.stop=asyncio.Event();self.calls=[]
        async def work(fn,priority=2,**kw):
            self.calls.append(kw.get('label'));return fn(self.state)
        self.source.work=work
        notifications(self.h,asyncio.get_running_loop(),self.source.history_changed)
    async def asyncTearDown(self):self.state.writer.close();self.tmp.cleanup()
    async def test_epochs_prevent_lost_wakeups_and_deadlines_do_not_need_market_event(self):
        pulse=WorkPulse();stop=asyncio.Event();pulse.notify()
        self.assertEqual(await pulse.wait(0,stop),1)
        task=asyncio.create_task(pulse.wait(1,stop));await asyncio.sleep(0);pulse.notify()
        self.assertEqual(await asyncio.wait_for(task,.5),2)
        start=time.monotonic();self.assertEqual(await pulse.wait(2,stop,delay=.02),2)
        self.assertGreaterEqual(time.monotonic()-start,.015)
        task=asyncio.create_task(pulse.wait(2,stop));stop.set();await asyncio.wait_for(task,.5)
    async def test_actual_source_prepares_before_owner_and_reserves_pool_for_protective_work(self):
        self.source.history_separated=True;self.source.batched=True;self.source.stop.set()
        f=frame(FIXTURE['pump'][0],'pump');addresses={PROGRAMS['pump']:program_scope('pump')}
        captured=[];self.source.observer=lambda kind,values:captured.append((kind,values))
        class NoUnnecessaryTransfer:
            def submit(self,*args):raise AssertionError('small packet process transfer')
        self.source.preparation_executor=NoUnnecessaryTransfer();q=CandidateCommitQueue();await q.put(f)
        with patch('meme_machine.solana_selective_source.economic_records',side_effect=AssertionError('owner decoding')):
            await self.source.candidate_commits(q,addresses,'small',priority=2)
        self.assertEqual(q.count,0)
        self.assertEqual(captured[-1][1]['preparation']['mode'],'off_owner_inline')
        self.assertGreaterEqual(self.source.pipeline_metrics['economic_prepared:candidate']['wall_seconds_total_microseconds'],0)
        self.assertEqual(self.source.pipeline_metrics['candidate_phase:economic_store']['calls'],1)
        pool=ThreadPoolExecutor(max_workers=1);self.source.preparation_executor=pool
        try:
            q=CandidateCommitQueue();await q.put(f)
            with patch('meme_machine.solana_selective_source.economic_records',side_effect=AssertionError('owner decoding')):
                await self.source.candidate_commits(q,addresses,'protective',priority=0)
            self.assertEqual(captured[-1][1]['preparation']['mode'],'existing_process_pool')
        finally:await asyncio.to_thread(pool.shutdown,wait=True)

    async def test_phase_completion_survives_canceled_actual_owner_waiter(self):
        from meme_machine.solana_evidence_control import PriorityOwner
        from meme_machine.solana_candidate_phases import runnable_snapshot
        entered=threading.Event();release=threading.Event();accepted=[];native={};sampled=[]
        def factory():
            state,h=state_at(Path(self.tmp.name)/'native-owner.sqlite')
            state.close=state.writer.close;native['history']=h
            return state
        owner=PriorityOwner(factory)
        await asyncio.wrap_future(owner.ready)
        async def work(fn,priority=2,**options):
            future=owner.submit(fn,priority=priority);accepted.append(future)
            return await asyncio.shield(asyncio.wrap_future(future))
        self.source.work=work;self.source.history_separated=True;self.source.batched=True
        self.source.stop.set()
        def sampled_scheduler():
            sampled.append(threading.get_native_id())
            return runnable_snapshot()
        self.source.candidate_phases.runnable=sampled_scheduler
        original=native['history'].rolling.store_many
        def held_store(*args,**kwargs):
            if not entered.is_set():
                entered.set()
                if not release.wait(2):raise RuntimeError('offline_owner_release_missing')
            return original(*args,**kwargs)
        f=frame(FIXTURE['pump'][0],'pump');q=CandidateCommitQueue();await q.put(f)
        addresses={PROGRAMS['pump']:program_scope('pump')}
        task=None
        try:
            with patch.object(native['history'].rolling,'store_many',held_store):
                task=asyncio.create_task(self.source.candidate_commits(q,addresses,'canceled-phase'))
                self.assertTrue(await asyncio.to_thread(entered.wait,1))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
                self.assertFalse(accepted[0].done())
                self.assertEqual(self.source.pipeline_metrics['candidate_phase:economic_store']['calls'],0)
                release.set();await asyncio.wrap_future(accepted[0])
            row=self.source.pipeline_metrics['candidate_phase:economic_store']
            self.assertEqual(row['calls'],1);self.assertEqual(row['failed_calls'],0)
            self.assertEqual(set(sampled),{owner.telemetry()['native_thread_id']})
            pending=await asyncio.wrap_future(owner.submit(lambda state:state.writer.db.execute(
                'SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0]))
            self.assertGreater(pending,0)
            self.assertEqual(q.count,1) # Canceled consumer never acknowledges its in-memory batch.
        finally:
            release.set()
            if task is not None and not task.done():
                task.cancel()
                try:await task
                except asyncio.CancelledError:pass
            await asyncio.to_thread(owner.close)
    async def test_preparation_failure_retains_witness_without_advancing_evidence(self):
        self.source.history_separated=True;self.source.batched=True;self.source.stop.set()
        f=frame(FIXTURE['pump'][0],'pump');q=CandidateCommitQueue();await q.put(f)
        a={PROGRAMS['pump']:program_scope('pump')}
        with patch('meme_machine.solana_economic_preparation.prepare_candidate_frames',
                side_effect=EvidenceUnavailable('candidate_preparation_result_bound')):
            with self.assertRaisesRegex(EvidenceUnavailable,'preparation_result_bound'):
                await self.source.candidate_commits(q,a,'failed',priority=2)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT reason FROM candidate_gaps').fetchone()[0],
            'candidate_economic_preparation_failed')
        from meme_machine.runtime.evidence_worker import failure_diagnostic
        self.assertIn('candidate_preparation_result_bound',failure_diagnostic(EvidenceUnavailable('candidate_preparation_result_bound')))
    async def test_idle_and_diagnostics_do_not_poll_or_trigger_publication_loop(self):
        task=asyncio.create_task(self.source.publish_history())
        try:
            await asyncio.sleep(.02);before=len(self.calls)
            self.source.diagnostic('offline_diagnostic',dict(no_evidence_authority=True))
            await self.source.flush_diagnostics()
            diagnostic=len(self.calls);await asyncio.sleep(.25)
            self.assertEqual(len(self.calls),diagnostic);self.assertEqual(before,1)
            self.h.lifecycle.emit('pump','candidate','scout',dict(slot=1,seen=NOW,fields={}))
            await asyncio.sleep(.02);self.assertEqual(len(self.calls),diagnostic)
            self.assertGreater(self.source.delivery_wakeup.epoch,0)
            self.source.history_changed();await asyncio.sleep(.02)
            self.assertEqual(len(self.calls),diagnostic+1)
        finally:self.source.stop.set();await asyncio.wait_for(task,1)
    async def test_rolled_back_outbox_does_not_notify_before_commit(self):
        epoch=self.source.history_wakeup.epoch
        with self.assertRaises(RuntimeError),self.state.writer.transaction():
            self.h.lifecycle.emit('pump','candidate','scout',dict(slot=1,seen=NOW,fields={}))
            await asyncio.sleep(0);self.assertEqual(self.source.history_wakeup.epoch,epoch)
            raise RuntimeError('rollback fixture')
        await asyncio.sleep(0);self.assertEqual(self.source.history_wakeup.epoch,epoch)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],0)
    async def test_shutdown_drains_single_accepted_consumer_commit_then_ack(self):
        self.h.lifecycle.delivery_separated=True
        self.h.lifecycle.emit('pump','candidate','scout',dict(slot=1,seen=NOW,fields={}))
        entered=threading.Event();release=threading.Event()
        def slow(snapshot):entered.set();release.wait(2);return deliver(snapshot)
        pool=ThreadPoolExecutor(max_workers=1);self.source.delivery_executor=pool
        try:
            with patch('meme_machine.solana_history_delivery.deliver',slow):
                task=asyncio.create_task(self.source.candidate_history_delivery())
                self.assertTrue(await asyncio.to_thread(entered.wait,1))
                task.cancel();release.set()
                with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],0)
        finally:release.set();await asyncio.to_thread(pool.shutdown,wait=True)
    async def test_completed_unchanged_proof_is_not_recommitted_and_gap_invalidates_it(self):
        self.h.lifecycle.delivery_separated=True;scope=program_scope('pumpswap')
        self.h.lifecycle.defer_proof(IntervalProof(scope,10,20,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=10,upper_slot=20,lineage_hash=digest([10,20])),NOW))
        snapshot=capture(self.h.lifecycle);deliver(snapshot)
        self.assertIsNone(capture(self.h.lifecycle))
        self.h.gap(scope,15,16,'retained-reorganization')
        self.assertTrue(capture(self.h.lifecycle)['proofs'])
    async def test_concurrent_consumer_writer_leaves_outbox_unacknowledged_then_recovers(self):
        self.h.lifecycle.delivery_separated=True
        self.h.lifecycle.emit('pump','candidate','scout',dict(slot=1,seen=NOW,fields={}))
        snapshot=capture(self.h.lifecycle);deliver(snapshot) # Establish the existing consumer schema.
        with closing(sqlite3.connect(self.h.lifecycle.path,timeout=0)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            with self.assertRaises(sqlite3.OperationalError):await asyncio.to_thread(deliver,snapshot)
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],1)
            writer.rollback()
        self.assertTrue(acknowledge(self.h.lifecycle,snapshot,await asyncio.to_thread(deliver,snapshot)))


if __name__=='__main__':unittest.main()
