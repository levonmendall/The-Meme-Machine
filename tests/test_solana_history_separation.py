"""Retained economic fixtures; no provider traffic or installed epoch access."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from concurrent.futures.process import BrokenProcessPool
from tests.test_solana_closure import NOW,state_at
from tests.test_solana_selective_evidence import FIXTURE
from meme_machine.solana_history_work import HistoricalTasks,HistoryExecutor,prepare_history,CPUBudget
from meme_machine.solana_evidence_plane import EvidenceUnavailable,IntervalProof,digest
from meme_machine.solana_selective_history import PROGRAMS,economic_records,coverage_scope
from meme_machine.solana_rolling_history import RollingHistory,program_scope


def delayed(seconds):time.sleep(seconds);return True


class HistorySeparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'canonical.sqlite'
        self.now=[NOW];self.state,self.h=state_at(self.path,lambda:self.now[0])
    def tearDown(self):self.state.writer.close();self.tmp.cleanup()
    def enable(self):
        self.tasks=HistoricalTasks(self.h);self.h.historical_tasks=self.tasks
    def seal(self,scope,lo,hi):
        self.h.prove(IntervalProof(scope,lo,hi,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=hi,
                 lineage_hash=digest([scope,lo,hi])),self.now[0]))

    def test_reactivation_time_index_preserves_exact_epoch_minimum_and_all_outbox_rows(self):
        life=self.h.lifecycle
        for i in range(64):
            life.emit('pump','candidate','canonical',dict(record=dict(identity=str(i),slot=i)),at=NOW+i)
        for family,address,epoch,seen in (
            ('pump','candidate',1,12.125),('pump','candidate',1,10.125),
            ('pump','candidate',2,8.5),('pump','candidate','1',4),
            ('pump','other',1,3),('pumpswap','candidate',1,2),
            ('pump','candidate',1,None)):
            life.emit(family,address,'reactivated',dict(epoch=epoch,seen=seen),at=NOW)
        life.emit('pump','candidate','promotion',dict(epoch=1,seen=1),at=NOW)
        rows=self.h.db.execute('SELECT * FROM candidate_history_outbox ORDER BY rowid').fetchall()
        query="SELECT MIN(json_extract(body,'$.seen')) FROM candidate_history_outbox {index} WHERE family=? AND address=? AND kind='reactivated' AND json_extract(body,'$.epoch')=?"
        for params,expected in ((('pump','candidate',1),10.125),(('pump','candidate',2),8.5),
                                (('pump','candidate','1'),4),(('pump','candidate',99),None)):
            old=self.h.db.execute(query.format(index='INDEXED BY candidate_history_identity_pending'),params).fetchone()
            new=self.h.db.execute(query.format(index=''),params).fetchone()
            self.assertEqual(new,old);self.assertEqual(new,(expected,))
            plan=self.h.db.execute('EXPLAIN QUERY PLAN '+query.format(index=''),params).fetchall()
            self.assertTrue(any('candidate_history_reactivation_time' in r[3] for r in plan))
        self.assertEqual(rows,self.h.db.execute('SELECT * FROM candidate_history_outbox ORDER BY rowid').fetchall())
        # Reinstalling the existing owner schema does not duplicate or consume
        # a pending row; restart still sees every original obligation.
        from meme_machine.solana_candidate_lifecycle import CandidateLifecycle
        CandidateLifecycle(self.h)
        self.assertEqual(rows,self.h.db.execute('SELECT * FROM candidate_history_outbox ORDER BY rowid').fetchall())

    def pump(self):
        rows=[]
        for tx in FIXTURE['pump']:
            rows.extend(economic_records('pump',PROGRAMS['pump'],copy.deepcopy(tx),
                endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream'))
        self.h.ingest(rows)
        self.seal(program_scope('pump'),min(r.slot for r in rows),max(r.slot for r in rows))
        mint=next(r.payload['event']['mint'] for r in rows if r.payload['event']['event_type']=='create')
        return mint,rows
    def request(self,address='pool',lo=100,hi=110,family='pumpswap',deadline=NOW+150,priority=3):
        self.h.bind(family,address)
        return self.h.rolling.prepare(family,address,lo,hi,deadline=deadline,priority=priority)
    def work(self):
        job=self.tasks.claim();self.assertIsNotNone(job)
        return job,prepare_history(self.path,job)
    def test_complete_retained_pump_history_matches_original_metrics_and_events(self):
        mint,rows=self.pump();hi=max(r.slot for r in rows)
        original=self.h.rolling.prepare('pump',mint,0,hi,deadline=NOW+150,priority=3)
        before=self.h.db.execute('SELECT identity,slot,signature,event_index,body,hash FROM rolling_economic_events ORDER BY slot,transaction_index,event_index').fetchall()
        population=self.h.db.execute('SELECT family,address,state,epoch FROM candidate_lifecycle ORDER BY family,address').fetchall()
        self.enable();pending=self.request(mint,0,hi,'pump')
        self.assertIsNone(pending['missing_intervals']);self.assertFalse(pending['entry_authority'])
        job,result=self.work()
        self.assertEqual(self.tasks.apply(job,result),original)
        self.assertEqual(before,self.h.db.execute('SELECT identity,slot,signature,event_index,body,hash FROM rolling_economic_events ORDER BY slot,transaction_index,event_index').fetchall())
        self.assertEqual(population,self.h.db.execute('SELECT family,address,state,epoch FROM candidate_lifecycle ORDER BY family,address').fetchall())
        self.assertEqual(len(before),len(rows))
    def test_missing_history_has_identical_jobs_and_original_deadlines(self):
        self.seal(program_scope('pumpswap'),100,104)
        self.h.bind('pumpswap','pool')
        original=self.h.rolling.prepare('pumpswap','pool',98,110,deadline=NOW+150,priority=3)
        jobs=self.h.db.execute('SELECT id,family,address,lo,hi,deadline,status FROM acquisition_jobs ORDER BY id').fetchall()
        self.enable();self.request(lo=98)
        job,result=self.work();self.assertEqual(self.tasks.apply(job,result),original)
        self.assertEqual(jobs,self.h.db.execute('SELECT id,family,address,lo,hi,deadline,status FROM acquisition_jobs ORDER BY id').fetchall())
        self.assertFalse(original['entry_authority']);self.assertTrue(original['missing_intervals'])
    def test_slow_worker_never_holds_sql_snapshot_or_blocks_live_commit(self):
        mint,rows=self.pump();self.enable();self.request(mint,0,max(r.slot for r in rows),'pump')
        job=self.tasks.claim();gate=threading.Event();entered=threading.Event();errors=[]
        original=RollingHistory.missing_from_inputs
        def slow(rolling,inputs):
            self.assertIsNone(rolling.db);self.assertIsNone(rolling.history.db)
            entered.set();gate.wait(3);return original(rolling,inputs)
        def worker():
            try:
                with patch.object(RollingHistory,'missing_from_inputs',slow):prepare_history(self.path,job)
            except BaseException as exc:errors.append(exc)
        thread=threading.Thread(target=worker);thread.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.state.writer.transaction():
                self.h.ingest(rows) # exact duplicate retains identities/order
                self.h.db.execute("INSERT INTO service_health VALUES('offline-live-progress','1')")
            self.assertEqual(len(rows),self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0])
            self.assertEqual(self.h.db.execute("SELECT status FROM rolling_preparation_jobs WHERE id=?",(job['id'],)).fetchone()[0],'active')
            self.assertEqual(self.h.db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0],0)
        finally:gate.set();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
    def test_restart_reclaims_job_without_changing_economic_cursor_or_deadline(self):
        mint,rows=self.pump();self.enable();pending=self.request(mint,0,max(r.slot for r in rows),'pump')
        old=self.tasks.claim();cursors=self.h.db.execute('SELECT * FROM cursors ORDER BY scope').fetchall()
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0]);self.enable()
        new,result=self.work();self.assertEqual(old['id'],new['id']);self.assertNotEqual(old['token'],new['token'])
        self.assertFalse(self.tasks.apply(old,dict(result,id=old['id'],token=old['token'])))
        self.assertEqual(new['deadline'],NOW+150);self.tasks.apply(new,result)
        self.assertEqual(cursors,self.h.db.execute('SELECT * FROM cursors ORDER BY scope').fetchall())
    def test_new_reorganization_gap_invalidates_prepared_result(self):
        self.seal(program_scope('pumpswap'),100,110);self.enable();self.request()
        job,result=self.work();self.h.gap(program_scope('pumpswap'),105,107,'offline_reorg')
        self.assertFalse(self.tasks.apply(job,result))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM promotion_history_metrics').fetchone()[0],0)
        self.assertEqual(self.h.rolling.missing('pumpswap',coverage_scope('pumpswap','pool'),100,110),[(105,107)])
        self.now[0]+=.2;job,result=self.work();metric=self.tasks.apply(job,result)
        self.assertEqual(metric['missing_intervals'],[(105,107)]);self.assertFalse(metric['entry_authority'])
    def test_monotone_live_append_accepts_exact_old_proof_prefix(self):
        self.seal(program_scope('pumpswap'),100,110);self.enable();self.request()
        job,result=self.work();self.seal(program_scope('pumpswap'),111,112)
        self.assertEqual(self.tasks.apply(job,result)['missing_intervals'],[])
    def invalidated(self,change):
        self.seal(program_scope('pumpswap'),100,110);self.enable()
        self.request();job,result=self.work()
        if change=='binding':
            # Canonical upgrades explicitly replace a binding; ordinary bind()
            # correctly refuses a conflicting rewrite.
            with self.state.writer.transaction():
                self.h.db.execute("DELETE FROM evidence_bindings WHERE family='pumpswap' AND address='pool'")
                self.h.bind('pumpswap','pool',market_address='different')
        elif change=='generation':self.h.startup.begin()
        else:
            with self.state.writer.transaction():self.h.db.execute('DELETE FROM candidate_coverage')
        self.assertFalse(self.tasks.apply(job,result))
    def test_rebinding_invalidates_result(self):self.invalidated('binding')
    def test_source_generation_invalidates_result(self):self.invalidated('generation')
    def test_deleted_proof_invalidates_result(self):self.invalidated('proof')
    def test_unavailable_worker_backs_off_and_preserves_all_candidates(self):
        self.enable()
        for i in range(80):
            address='quiet-'+str(i)
            self.h.observe('pumpswap',address,slot=100,signature='',seen=NOW,fields={})
            self.request(address)
        job=self.tasks.claim();self.tasks.defer(job,'BrokenProcessPool')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_preparation_jobs').fetchone()[0],80)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_lifecycle').fetchone()[0],80)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        row=self.h.db.execute('SELECT status,retry_at,deadline FROM rolling_preparation_jobs WHERE id=?',(job['id'],)).fetchone()
        self.assertEqual(row[0],'pending');self.assertGreater(row[1],NOW);self.assertEqual(row[2],NOW+150)
    def test_worker_crash_replaces_only_history_process(self):
        self.seal(program_scope('pumpswap'),100,110);self.enable();self.request();job=self.tasks.claim()
        executor=HistoryExecutor()
        try:
            with self.assertRaises(BrokenProcessPool):executor.submit(os._exit,19).result(timeout=10)
            result=executor.submit(prepare_history,self.path,job).result(timeout=10)
            self.assertEqual(self.tasks.apply(job,result)['missing_intervals'],[])
        finally:executor.close()
    def test_deadline_miss_does_not_grant_coverage_or_erase_survivor(self):
        self.enable();self.request('current',family='pump',deadline=NOW+1)
        self.request('survivor',family='pumpswap',deadline=NOW+100)
        self.now[0]+=2;job=self.tasks.claim()
        self.assertEqual(job['spec']['family'],'pumpswap')
        self.assertEqual(self.h.db.execute("SELECT status FROM rolling_preparation_jobs WHERE json_extract(body,'$.family')='pump'").fetchone()[0],'deadline_missed')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
    def test_original_boundary_and_publication_waits_remain_durable(self):
        self.h.observe('pump','curve',slot=100,signature='',seen=NOW,fields={});self.h.bind('pump','curve')
        original=self.h.rolling.prepare('pump','curve',0,110,deadline=NOW+150,priority=3)
        self.assertTrue(original['boundary_state'])
        self.enable();self.h.rolling.resume_boundaries(limit=16)
        job,result=self.work();self.assertEqual(self.tasks.apply(job,result),original)
        self.assertEqual(self.h.db.execute("SELECT status FROM rolling_boundary_waits").fetchone()[0],'pending')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
    def test_protection_keeps_original_synchronous_required_checks(self):
        self.seal(program_scope('pumpswap'),100,110);self.enable()
        result=self.request(priority=0)
        self.assertEqual(result['missing_intervals'],[])
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_preparation_jobs').fetchone()[0],0)
    def test_duplicate_jobs_and_tampered_output_cannot_duplicate_economics(self):
        self.seal(program_scope('pumpswap'),100,110);self.enable()
        for _ in range(12):self.request()
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_preparation_jobs').fetchone()[0],1)
        job,result=self.work();wrong=dict(result,result_hash='0'*64)
        with self.assertRaisesRegex(EvidenceUnavailable,'historical_result_identity'):self.tasks.apply(job,wrong)
        self.tasks.apply(job,result);self.assertFalse(self.tasks.apply(job,result))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
    def test_cpu_budget_is_worker_local_and_bounded_per_job(self):
        budget=CPUBudget(.25)
        with patch('meme_machine.solana_history_work.time.process_time',return_value=budget.cpu+.004),patch('meme_machine.solana_history_work.time.monotonic',side_effect=[budget.started+.001,budget.started+.001,budget.started+.02,budget.started+.02]),patch('meme_machine.solana_history_work.time.sleep') as sleep:
            budget();sleep.assert_called_once()

    def test_flag_rollback_drains_durable_jobs_through_original_checks(self):
        self.seal(program_scope('pumpswap'),100,110);self.enable();self.request()
        del self.h.historical_tasks
        self.tasks.resume_sync(limit=16)
        self.assertEqual(self.h.db.execute('SELECT status FROM rolling_preparation_jobs').fetchone()[0],'complete')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM promotion_history_metrics').fetchone()[0],1)

    def test_unchanged_completed_history_is_reused_without_worker_or_writes(self):
        self.seal(program_scope('pumpswap'),100,110);self.enable();self.request()
        job,result=self.work();metric=self.tasks.apply(job,result)
        changes=self.h.db.total_changes
        for _ in range(30):self.assertEqual(self.request(),metric)
        self.assertEqual(changes,self.h.db.total_changes);self.assertIsNone(self.tasks.claim())
        self.h.gap(program_scope('pumpswap'),105,105,'new_authenticated_gap')
        self.request();job,result=self.work()
        self.assertEqual(self.tasks.apply(job,result)['missing_intervals'],[(105,105)])

    def test_pending_upper_bounds_coalesce_without_losing_deadline_or_slots(self):
        self.enable()
        identities=set(self.request(hi=hi)['historical_job'] for hi in range(110,151))
        self.assertEqual(len(identities),1)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_preparation_jobs').fetchone()[0],1)
        job,result=self.work();self.assertEqual(job['spec']['hi'],150)
        self.assertEqual(job['deadline'],NOW+150)
        self.assertEqual(self.tasks.apply(job,result)['missing_intervals'],[(100,150)])

    def test_unchanged_hash_rewrite_invalidates_cached_history_and_fails_closed(self):
        self.seal(program_scope('pumpswap'),100,110);self.enable();self.request()
        job,result=self.work();self.tasks.apply(job,result)
        self.h.db.execute("UPDATE candidate_coverage SET points=?",(b'corrupt',))
        self.request();job=self.tasks.claim();self.assertIsNotNone(job)
        with self.assertRaisesRegex(Exception,'corrupt'):prepare_history(self.path,job)

    def test_monotone_repair_recomputes_old_conservative_result_before_reuse(self):
        self.seal(program_scope('pumpswap'),100,104);self.enable();self.request()
        job,result=self.work();self.seal(program_scope('pumpswap'),105,110)
        self.assertEqual(self.tasks.apply(job,result)['missing_intervals'],[(105,110)])
        self.request();job,result=self.work()
        self.assertEqual(self.tasks.apply(job,result)['missing_intervals'],[])

    def test_optional_acquisition_waits_for_verified_local_plan_and_reuses_repair(self):
        self.seal(program_scope('pumpswap'),100,104);self.enable();self.h.bind('pumpswap','pool')
        identity=self.h.request('pumpswap','pool',105,110,deadline=NOW+150,priority=3)
        self.assertIsNone(self.h.plan())
        job,result=self.work();self.tasks.apply(job,result)
        self.assertEqual(self.h.plan()[0]['id'],identity)
        self.seal(program_scope('pumpswap'),105,110)
        self.assertIsNone(self.h.plan())
        job,result=self.work();self.tasks.apply(job,result)
        self.assertIsNone(self.h.plan())
        self.assertEqual(self.h.db.execute('SELECT status FROM acquisition_jobs WHERE id=?',(identity,)).fetchone()[0],'complete')

    def test_optional_history_does_not_delay_urgent_provider_dispatch(self):
        self.enable();self.h.bind('pumpswap','optional');self.h.bind('pumpswap','protected')
        self.h.request('pumpswap','optional',100,110,priority=4,deadline=NOW+150)
        self.assertIsNone(self.h.plan())
        urgent=self.h.request('pumpswap','protected',100,110,priority=0,deadline=NOW+3)
        self.assertEqual(self.h.plan()[0]['id'],urgent)


class DeliverySeparationTests(unittest.TestCase):
    setUp=HistorySeparationTests.setUp
    tearDown=HistorySeparationTests.tearDown
    pump=HistorySeparationTests.pump
    seal=HistorySeparationTests.seal
    def test_raw_reuse_preserves_exact_outbox_ids_bytes_and_order(self):
        _,rows=self.pump()
        before=self.h.db.execute('SELECT id,family,address,kind,body,hash,created FROM candidate_history_outbox ORDER BY priority,created,rowid').fetchall()
        other=Path(self.tmp.name)/'other.sqlite';state,h=state_at(other,lambda:NOW)
        try:
            h.lifecycle.delivery_separated=True;h.ingest(rows)
            after=h.db.execute('SELECT id,family,address,kind,body,hash,created FROM candidate_history_outbox ORDER BY priority,created,rowid').fetchall()
            self.assertEqual(before,after)
        finally:state.writer.close()
    def test_consumer_and_proof_full_commit_precede_owner_ack_and_checkpoint(self):
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge
        self.h.lifecycle.delivery_separated=True
        mint,rows=self.pump()
        # Remove the fixture helper's direct coverage; publish only through the
        # production outbox/proof protocol under test.
        with self.state.writer.transaction():self.h.db.execute('DELETE FROM candidate_coverage')
        lo,hi=min(r.slot for r in rows),max(r.slot for r in rows)
        scope=program_scope('pump')
        self.h.lifecycle.defer_proof(IntervalProof(scope,lo,hi,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=hi,lineage_hash=digest([lo,hi])),NOW))
        life=self.h.lifecycle;snapshot=capture(life)
        life.publish();self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        result=deliver(snapshot)
        life.publish();self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertTrue(acknowledge(life,snapshot,result))
        proof_snapshot=capture(life);self.assertTrue(proof_snapshot['proofs'])
        deliver(proof_snapshot);life.publish()
        self.assertEqual(self.h.db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',(scope,)).fetchone()[0],hi)
        self.assertEqual(self.h.rolling.missing('pump',self.h.scope_for('pump',mint),lo,hi),[])
    def test_crash_after_consumer_commit_replays_without_duplicate_events(self):
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge
        from meme_machine.runtime.candidate_history import CandidateHistory
        self.h.lifecycle.delivery_separated=True;mint,rows=self.pump()
        snapshot=capture(self.h.lifecycle);deliver(snapshot)
        with __import__('contextlib').closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as shared:
            before=shared.events('pump',mint)
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.h.lifecycle.delivery_separated=True
        repeated=capture(self.h.lifecycle);result=deliver(repeated)
        self.assertTrue(acknowledge(self.h.lifecycle,repeated,result))
        with __import__('contextlib').closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as shared:
            self.assertEqual(shared.events('pump',mint),before)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],0)

    def test_retained_epoch_fraction_survives_delivery_ack_and_crash_replay(self):
        from contextlib import closing
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge
        from meme_machine.runtime.candidate_history import CandidateHistory
        # Actual scalar from the retained 2026-10-14 failing outbox batch.
        # SQLite 3.45.1 json_extract rounds this by one binary floating step.
        available=1791933736.556373
        self.now[0]=available;self.h.lifecycle.delivery_separated=True
        rows=[r for tx in FIXTURE['pump'] for r in economic_records('pump',PROGRAMS['pump'],
            copy.deepcopy(tx),endpoint_identity='a'*64,seen=available,source='alchemy_finalized_stream')]
        self.h.ingest(rows)
        mint=next(r.payload['event']['mint'] for r in rows if r.payload['event']['event_type']=='create')
        original=self.h.db.execute('SELECT id,body,hash,created FROM candidate_history_outbox ORDER BY rowid').fetchall()
        snapshot=capture(self.h.lifecycle);result=deliver(snapshot)
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:available)) as shared:
            before=shared.events('pump',mint)
        # Simulate consumer commit followed by process loss before canonical ACK.
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0]+10)
        self.h.lifecycle.delivery_separated=True
        repeated=capture(self.h.lifecycle)
        self.assertTrue(acknowledge(self.h.lifecycle,repeated,deliver(repeated)))
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:available+10)) as shared:
            self.assertEqual(shared.events('pump',mint),before)
        for identity,raw,checksum,created in original:
            record=json.loads(raw).get('record')
            if record:
                self.assertEqual(repeated['references'][identity],
                    (record['identity'],record['slot'],available))
                compact=next(r for r in result['acknowledgements'] if r[0]==identity)
                self.assertEqual(json.loads(compact[1])['available'],available)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],0)

    def test_capture_preserves_integer_and_real_scalar_types_and_large_native_slots(self):
        from meme_machine.solana_history_delivery import capture
        self.h.lifecycle.delivery_separated=True
        for index,(available,slot) in enumerate(((1791933736.556373,100),(0,101),
                (0.0,102),(1e-10,103),(1791933736.5563732,2**63+1))):
            with self.subTest(available=available,slot=slot):
                identity=self.h.lifecycle.emit('pump','candidate','canonical',
                    dict(record=dict(identity='event-'+str(index),slot=slot),available=available))
                snapshot=capture(self.h.lifecycle);reference=snapshot['references'][identity]
                self.assertEqual(reference,('event-'+str(index),slot,available))
                self.assertIs(type(reference[1]),int)
                self.assertIs(type(reference[2]),type(available))
    def test_missing_tampered_receipt_and_changed_generation_cannot_ack(self):
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge
        self.h.lifecycle.delivery_separated=True;self.pump()
        snapshot=capture(self.h.lifecycle);result=deliver(snapshot)
        changed=dict(result,acknowledgements=[(r[0],r[1],r[2]) for r in result['acknowledgements']])
        index=next(i for i,r in enumerate(changed['acknowledgements']) if r[1] is not None)
        ident,raw,checksum=changed['acknowledgements'][index]
        changed['acknowledgements'][index]=(ident,raw,'0'*64)
        with self.assertRaisesRegex(EvidenceUnavailable,'ack_content'):acknowledge(self.h.lifecycle,snapshot,changed)
        self.h.startup.begin()
        self.assertFalse(acknowledge(self.h.lifecycle,snapshot,result))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],len(snapshot['rows']))
    def test_delayed_delivery_does_not_hold_canonical_owner_or_wal_reader(self):
        from meme_machine.solana_history_delivery import capture,deliver
        from meme_machine.solana_candidate_lifecycle import CandidateLifecycle
        self.h.lifecycle.delivery_separated=True;self.pump();snapshot=capture(self.h.lifecycle)
        gate=threading.Event();entered=threading.Event();errors=[]
        original=CandidateLifecycle.deliver_rows
        def slow(life,*args):
            self.assertFalse(hasattr(life,'db'));entered.set();gate.wait(3);return original(life,*args)
        def run():
            try:
                with patch.object(CandidateLifecycle,'deliver_rows',slow):deliver(snapshot)
            except BaseException as exc:errors.append(exc)
        thread=threading.Thread(target=run);thread.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.state.writer.transaction():self.h.db.execute("INSERT INTO service_health VALUES('offline-progress','1')")
            self.assertEqual(self.h.db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0],0)
        finally:gate.set();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])

    def test_observation_refresh_runs_off_owner_and_preserves_future_requalification(self):
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge
        life=self.h.lifecycle;life.delivery_separated=True
        self.h.observe('pumpswap','quiet',slot=100,signature='',seen=NOW,fields={})
        self.h.bind('pumpswap','quiet');life.promote('pumpswap','quiet',deadline=NOW+1,lower_slot=100)
        snapshot=capture(life);acknowledge(life,snapshot,deliver(snapshot))
        self.now[0]+=2;life.refresh();snapshot=capture(life)
        self.assertEqual(self.h.db.execute("SELECT state FROM candidate_lifecycle WHERE address='quiet'").fetchone()[0],'queued')
        self.assertTrue(acknowledge(life,snapshot,deliver(snapshot)))
        self.assertEqual(self.h.db.execute("SELECT state FROM candidate_lifecycle WHERE address='quiet'").fetchone()[0],'demoted')
        self.assertTrue(self.h.db.execute("SELECT 1 FROM candidate_history_outbox WHERE kind='demoted'").fetchone())

    def test_pending_proof_with_empty_consumer_database_defers_safely(self):
        self.h.lifecycle.delivery_separated=True
        self.h.lifecycle.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.h.lifecycle.path):pass
        scope=program_scope('pumpswap')
        self.h.lifecycle.defer_proof(IntervalProof(scope,100,110,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=100,upper_slot=110,lineage_hash=digest([100,110])),NOW))
        self.h.lifecycle.publish()
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0],1)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)

    def test_new_reorganization_gap_invalidates_delivered_proof_receipt(self):
        from meme_machine.solana_history_delivery import capture,deliver
        life=self.h.lifecycle;life.delivery_separated=True;scope=program_scope('pumpswap')
        life.defer_proof(IntervalProof(scope,100,110,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=100,upper_slot=110,lineage_hash=digest([100,110])),NOW))
        deliver(capture(life));self.h.gap(scope,105,107,'canonical_reorganization')
        life.publish()
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0],1)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)

    def test_enabled_configuration_reaches_only_existing_canonical_worker(self):
        from meme_machine.operational.supervisor import Supervisor
        service=Supervisor(Path(self.tmp.name)/'offline-service',offline=True)
        service.initialize()
        try:
            with patch.dict(os.environ,MM_SOLANA_HISTORY_SEPARATED='1',MM_PAPER_EPOCH=service.epoch):
                self.assertEqual(service.environment('solana')['MM_SOLANA_HISTORY_SEPARATED'],'1')
                for lane in ('pump','pons'):self.assertNotIn('MM_SOLANA_HISTORY_SEPARATED',service.environment(lane))
            with patch.dict(os.environ,MM_SOLANA_HISTORY_SEPARATED='invalid',MM_PAPER_EPOCH=service.epoch):
                with self.assertRaisesRegex(ValueError,'configuration'):service.environment('solana')
        finally:
            if service.lock:service.lock.close()


class ColdRestoreTests(unittest.TestCase):
    setUp=HistorySeparationTests.setUp
    tearDown=HistorySeparationTests.tearDown
    pump=HistorySeparationTests.pump
    seal=HistorySeparationTests.seal
    def cold(self):
        import zlib
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        from meme_machine.solana_evidence_plane import canonical,decode_body
        mint,events=self.pump();ScopedRetirement(self.h)
        rows=self.h.db.execute('SELECT * FROM rolling_economic_events ORDER BY slot,transaction_index,event_index').fetchall()
        items=[dict(record=decode_body(r[9],self.h.db),available=r[11]) for r in rows]
        raw=canonical(items).encode();packed=zlib.compress(raw,1);archive=digest(items)
        file=Path(self.tmp.name)/'original-cold.json.zlib';file.write_bytes(packed)
        with self.state.writer.transaction():
            self.h.db.execute('INSERT INTO scoped_cold_manifests VALUES(?,?,?,?,?,?,?)',
                (archive,str(file),hashlib.sha256(packed).hexdigest(),len(rows),len(raw),len(packed),NOW))
            for row,item in zip(rows,items,strict=True):
                self.h.db.execute('INSERT INTO scoped_cold_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(*row[:9],None,row[10],row[11],archive))
                self.h.db.executemany('INSERT INTO scoped_cold_addresses VALUES(?,?)',[(row[0],a) for a in item['record']['addresses']])
                self.h.db.execute('UPDATE rolling_economic_events SET body=NULL,archive=? WHERE identity=?',(archive,row[0]))
        self.tasks=HistoricalTasks(self.h);self.h.historical_tasks=self.tasks
        return mint,rows
    def test_exact_cold_economics_restored_in_bounded_off_owner_batch(self):
        mint,original=self.cold()
        self.assertFalse(self.tasks.cold_ready('pump',mint,epoch=1,deadline=NOW+150))
        job=self.tasks.claim();result=prepare_history(self.path,job)
        self.assertTrue(self.h.db.execute('SELECT 1 FROM rolling_economic_events WHERE body IS NULL').fetchone())
        self.assertFalse(result['spec'].get('entry_authority',False))
        self.assertTrue(self.tasks.apply(job,result)['complete'])
        after=self.h.db.execute('SELECT * FROM rolling_economic_events ORDER BY slot,transaction_index,event_index').fetchall()
        self.assertEqual(after,original)
        self.assertTrue(self.tasks.cold_ready('pump',mint,epoch=1,deadline=NOW+150))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM scoped_cold_records').fetchone()[0],0)
    def test_source_restart_invalidates_cold_result_without_losing_records(self):
        mint,original=self.cold();self.tasks.cold_ready('pump',mint,epoch=1,deadline=NOW+150)
        job=self.tasks.claim();result=prepare_history(self.path,job);self.h.startup.begin()
        self.assertFalse(self.tasks.apply(job,result))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM scoped_cold_records').fetchone()[0],len(original))
        self.assertFalse(self.h.db.execute('SELECT 1 FROM rolling_economic_events WHERE body IS NOT NULL').fetchone())

    def test_archive_preparation_is_independent_and_new_position_pin_refuses_commit(self):
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        from meme_machine.solana_history_archive import prepare,apply
        mint,events=self.pump();self.h.lifecycle.flush();retirement=ScopedRetirement(self.h)
        plan=retirement.retire(limit=64,measure_hot_bytes=False,plan_only=True)
        self.assertTrue(plan['selected'])
        result=prepare(plan)
        before=self.h.db.execute('SELECT identity,body,hash FROM rolling_economic_events ORDER BY identity').fetchall()
        self.h.lifecycle.pin(coverage_scope('pump',mint),'held-test-owner','position',0)
        self.assertFalse(apply(self.h,plan,result))
        self.assertEqual(self.h.db.execute('SELECT identity,body,hash FROM rolling_economic_events ORDER BY identity').fetchall(),before)
        self.h.lifecycle.unpin(coverage_scope('pump',mint),'held-test-owner','position')
        self.assertEqual(apply(self.h,plan,result)['retired_records'],len(result['selected']))
        for identity,body,checksum in before:
            self.assertEqual(retirement.body(identity),json.loads(body))


class HistoryCalculationTests(unittest.TestCase):
    def setUp(self):
        from meme_machine.runtime.survivor_history import History
        from meme_machine.lanes.pump.pumpswap_survivor import POLICY_HASH,reduce_reset_history
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'history.sqlite';self.policy=POLICY_HASH;self.reducer=reduce_reset_history
        self.history=History(self.path,policy=self.policy);self.addCleanup(lambda:self.history.close())
        self.history.graduate('late',dict(at=0,pool='canonical-pool'))
        self.points=[(t,dict(price=str(100+t//60%37),low=str(95+t//60%37),high=str(105+t//60%37))) for t in range(0,7*86400+1,60)]
        self.history.append('late',through=self.points[-1][0],events=[],points=self.points,complete=True)
    def calculation(self,at=None):
        return self.history.calculation_facts('late',self.points[-1][0] if at is None else at,reducer=self.reducer,policy=self.policy)
    def test_exact_reset_and_required_windows_with_no_retention_loss(self):
        before=self.history.facts('late',self.points[-1][0])[0]
        points,events,prefix=self.calculation()
        for start in (self.points[-1][0]-3600,self.points[-1][0]-7200,self.points[-1][0]-21600):
            self.assertEqual([p for p in points if p['at']>=start],[p for p in before if p['at']>=start])
        self.assertEqual(self.reducer(before),self.reducer([p for p in points if p['at']>prefix['through']],prefix))
        self.assertEqual(points[0],before[0]);self.assertLess(len(points),len(before))
        self.assertEqual(self.history.facts('late',self.points[-1][0])[0],before)
    def test_unchanged_summary_and_restart_decode_no_old_prefix(self):
        self.calculation();changes=self.history.db.total_changes
        self.calculation();self.assertEqual(self.history.calculation_metrics['prefix_records_decoded'],0)
        self.assertEqual(changes,self.history.db.total_changes)
        self.history.close()
        from meme_machine.runtime.survivor_history import History
        self.history=History(self.path,policy=self.policy)
        self.calculation();self.assertEqual(self.history.calculation_metrics['prefix_records_decoded'],0)
    def test_new_old_evidence_and_corruption_invalidate_summary(self):
        self.calculation();self.history.append('late',through=self.points[-1][0],events=[],points=[(30,'110')],complete=True)
        points,_,prefix=self.calculation()
        full=self.history.facts('late',self.points[-1][0])[0]
        self.assertEqual(self.reducer(full),self.reducer([p for p in points if p['at']>prefix['through']],prefix))
        self.history.db.execute("UPDATE points SET price='corrupt' WHERE candidate='late' AND at=60")
        with self.assertRaisesRegex(ValueError,'corruption'):self.calculation()
    def test_incomplete_history_never_uses_complete_summary(self):
        self.calculation();row=self.history.get('late');row['complete']=False;self.history.save(row)
        full=self.history.facts('late',self.points[-1][0]);points,events,prefix=self.calculation()
        self.assertEqual((points,events),full);self.assertIsNone(prefix)

    def test_late_eligible_survivor_has_identical_full_qualification(self):
        from tests.lanes.pump.test_pumpswap_survivor import facts
        from meme_machine.lanes.pump.pumpswap_survivor import evaluate_entry
        f=facts();shift=5*86400
        prices=[(0,'100'),(shift-3600,'100')]+[(p['at']+shift,p['price']) for p in f['price_points']]
        self.history.graduate('new-regime',dict(at=0,pool='canonical-independent-pool'))
        events=[dict(e,at=e['at']+shift) for e in f['demand_events']]
        self.history.append('new-regime',through=f['now']+shift,events=events,points=prices,complete=True)
        full_points,full_events=self.history.facts('new-regime',f['now']+shift)
        original=dict(f,now=f['now']+shift,base_end=f['base_end']+shift,price_points=full_points,demand_events=full_events)
        expected=evaluate_entry(original);self.assertTrue(expected['candidate'],expected)
        points,events,prefix=self.history.calculation_facts('new-regime',original['now'],reducer=self.reducer,policy=self.policy)
        self.assertEqual(evaluate_entry(dict(original,price_points=points,demand_events=events,reset_history_prefix=prefix)),expected)
    def test_only_acquisition_nodes_changed_in_runtime_and_original_economics_pin(self):
        import ast,subprocess
        from tests.test_robinhood_usd_valuation import opportunity_predecessor
        relative='meme_machine/lanes/pump/pumpswap_survivor_runtime.py'
        root=Path(__file__).resolve().parents[1]
        previous=ast.parse(subprocess.check_output(['git','show','ea4f4f1bfb12ef0d3ce01d4df70a93f6d37e7605:'+relative],cwd=root))
        source=(root/relative).read_bytes()
        # First verify the exact approved opportunity-access layer against the
        # combined manifest, then retain this original acquisition/economics
        # comparison on its operational predecessor. No runtime node is exempt.
        current=ast.parse(opportunity_predecessor(self,relative,source))
        changed=source.replace(b'qualification_evidence_complete=not maintenance',
                               b'qualification_evidence_complete=True',1)
        self.assertNotEqual(changed,source)
        with self.assertRaises(AssertionError):
            opportunity_predecessor(self,relative,changed)
        def method(tree):return next(n for c in tree.body if isinstance(c,ast.ClassDef) and c.name=='Runtime' for n in c.body if isinstance(n,ast.FunctionDef) and n.name=='reconstruct')
        old=method(previous);new=method(current)
        branch=next(n for n in new.body if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and n.test.id=='maintenance' and any(isinstance(x,ast.ImportFrom) and x.module=='pumpswap_survivor' for x in n.orelse))
        old_read=next(n for n in old.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='facts')
        new.body[new.body.index(branch)]=copy.deepcopy(old_read)
        for node in ast.walk(new):
            if isinstance(node,ast.keyword) and node.arg=='reset_history_prefix':node.value=ast.parse("self.history.prefix(row['id'])",mode='eval').body
        self.assertEqual(ast.dump(new),ast.dump(old))
