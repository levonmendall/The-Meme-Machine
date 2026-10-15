"""Real production SQLite outcomes: progress, pending work and interruption."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_plane import EvidenceUnavailable, EvidenceWriter
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_provider_config import AlchemyEndpoint
from meme_machine.solana_retention_outcome import RetentionOutcome, RetentionProgress
from tests.test_retention_progress import record

CONFIG=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')


def seed(state, count, scope='program:meteora', hot=False):
    rows=[replace(record(),identity=scope+':outcome:%05d'%i,
                  signature=scope+':outcome:%05d'%i,scope=scope,
                  slot=10,market_time=1000 if hot else 10,observed_at=1000)
          for i in range(count)]
    state.writer.ingest(rows)
    if not hot:
        while state.writer.archive(900):
            pass


class RetentionOutcomeTests(unittest.TestCase):
    @contextmanager
    def state(self):
        with tempfile.TemporaryDirectory() as td:
            state=ServiceState(Path(td)/'db',CONFIG)
            try:
                with patch('meme_machine.solana_evidence_service.time.time',return_value=1000):
                    yield state
            finally:
                state.close()

    def test_empty_scans_neither_commit_nor_invent_pending_work(self):
        with self.state() as state:
            for scope in ('program:meteora','program:pump','program:pumpswap'):
                seed(state,1,scope=scope,hot=True)
            state.retention()
            before=state.writer.db.total_changes; statements=[]
            state.writer._retention_yield_requested=lambda:'source'
            state.writer.db.set_trace_callback(statements.append)
            try:
                outcomes=[state.retention() for _ in range(10)]
            finally:
                state.writer.db.set_trace_callback(None)
            self.assertEqual(state.writer.db.total_changes,before)
            self.assertFalse(any(sql in ('BEGIN IMMEDIATE','COMMIT') for sql in statements))
            for outcome in outcomes:
                self.assertIs(outcome.pending,False)
                self.assertFalse(outcome.made_progress)
                self.assertFalse(outcome.retry)
                self.assertFalse(outcome.pressure)
                self.assertEqual(outcome.examined_scopes,3)

    def test_empty_promoted_housekeeping_does_not_starve_record_retirement(self):
        with self.state() as state:
            seed(state,2000)
            state.writer._retention_yield_requested=lambda:'source'
            with state.housekeeping_retention():outcome=state.retention()
            self.assertEqual(outcome.housekeeping_rows,0)
            self.assertEqual(outcome.retired_records,768)
            self.assertEqual(outcome.committed_slices,3)
            self.assertEqual(outcome.yield_reason,'source')

    def test_promoted_housekeeping_preserves_urgent_and_real_gc_priority(self):
        with self.state() as state:
            seed(state,2000)
            state.writer._retention_yield_requested=lambda:'urgent'
            with state.housekeeping_retention():urgent=state.retention()
            self.assertEqual(urgent.retired_records,0)
            self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],2000)
            with state.writer.transaction():
                state.writer.db.execute('INSERT INTO hot_chunks VALUES(?,?)',('real-orphan',b'orphan'))
            state.writer._retention_yield_requested=lambda:'source'
            with state.housekeeping_retention():gc=state.retention()
            self.assertGreater(gc.housekeeping_rows,0)
            self.assertEqual(gc.retired_records,0)
            self.assertFalse(state.writer.db.execute('SELECT 1 FROM hot_chunks').fetchone())
            with state.housekeeping_retention():records=state.retention()
            self.assertEqual(records.retired_records,768)

    def test_exactly_full_final_slice_is_not_a_backlog_signal(self):
        with self.state() as state:
            seed(state,256)
            state.writer.retain(900,max_records=256,archive_first=False,checkpoint=False)
            outcome=state.writer.last_retention_progress.snapshot()
            self.assertEqual(outcome.retired_records,256)
            self.assertEqual(outcome.committed_slices,1)
            self.assertTrue(outcome.made_progress)
            self.assertIs(outcome.pending,False)
            self.assertFalse(outcome.pressure)

    def test_unexamined_later_scope_cannot_be_reported_idle(self):
        with self.state() as state:
            seed(state,1,scope='a',hot=True);seed(state,512,scope='b')
            state.writer._retention_yield_requested=lambda:'urgent'
            outcome=state.retention()
            self.assertTrue(outcome.interrupted)
            self.assertIs(outcome.pending,None)
            self.assertFalse(outcome.pressure)
            self.assertTrue(outcome.retry)
            state.writer._retention_yield_requested=None
            finished=state.retention()
            self.assertEqual(finished.retired_records,512)

    def test_three_separate_slices_report_committed_work_before_source_yield(self):
        with self.state() as state:
            seed(state,2000)
            commits=[];writer=state.writer
            writer._retention_yield_requested=lambda:'source'
            def trace(sql):
                if sql=='COMMIT' and getattr(writer,'_retention_atomic',False):
                    row=writer.db.execute("SELECT value FROM counters WHERE key='compacted_records'").fetchone()
                    commits.append(row[0] if row else 0)
            writer.db.set_trace_callback(trace)
            try:outcome=state.retention()
            finally:writer.db.set_trace_callback(None)
            self.assertEqual(commits,[256,512,768])
            self.assertEqual(outcome.retired_records,768)
            self.assertEqual(outcome.committed_slices,3)
            self.assertIs(outcome.pending,True)
            self.assertTrue(outcome.pressure)
            self.assertEqual(outcome.yield_reason,'source')

    def test_urgent_boundary_keeps_one_commit_and_rotation(self):
        with self.state() as state:
            seed(state,1024,scope='a');seed(state,1024,scope='b')
            state.writer._retention_yield_requested=lambda:'urgent'
            outcome=state.retention()
            self.assertEqual(outcome.retired_records,256)
            self.assertEqual(outcome.committed_slices,1)
            self.assertEqual(state.writer._retention_next_scope,'b')
            second=state.retention()
            self.assertEqual(second.retired_records,256)
            self.assertEqual(state.writer._retention_next_scope,'a')

    def test_rolled_back_second_slice_never_counts_as_progress(self):
        with self.state() as state:
            seed(state,700)
            state.writer.db.execute("""CREATE TRIGGER fail_second BEFORE DELETE ON records
                WHEN OLD.identity='program:meteora:outcome:00260'
                BEGIN SELECT RAISE(ABORT,'test_rollback'); END""")
            with self.assertRaisesRegex(sqlite3.IntegrityError,'test_rollback'):
                state.retention()
            outcome=state.writer.last_retention_progress.snapshot()
            self.assertEqual(outcome.retired_records,256)
            self.assertEqual(outcome.committed_slices,1)
            self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],444)
            self.assertFalse(state.writer.db.in_transaction)
            self.assertEqual(state.writer.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_telemetry_writes_are_not_cleanup_progress(self):
        with self.state() as state:
            seed(state,1,hot=True);state.retention()
            native=state._storage_stage
            def telemetry_then_call(name,operation):
                with state.writer.transaction():
                    state.writer._count('test_unrelated_telemetry')
                return native(name,operation)
            with patch.object(state,'_storage_stage',side_effect=telemetry_then_call):
                outcome=state.retention()
            self.assertFalse(outcome.made_progress)
            self.assertIs(outcome.pending,False)

    def test_unrelated_sql_errors_are_not_swallowed(self):
        with self.state() as state:
            with patch.object(state.writer,'retain',side_effect=sqlite3.OperationalError('disk I/O error')):
                with self.assertRaisesRegex(sqlite3.OperationalError,'disk I/O error'):
                    state.retention()

    def test_interrupted_preparation_is_unknown_not_success(self):
        with tempfile.TemporaryDirectory() as td:
            owner=PriorityOwner(lambda:ServiceState(Path(td)/'db',CONFIG))
            owner.ready.result(5)
            requests=[]
            try:
                owner.submit(lambda s:seed(s,10,hot=True),priority=2).result(5)
                def exercise(state):
                    # Real progress-handler interruption during a read, before
                    # any mutation; urgent work must be served without rollback loss.
                    native=state.writer.retain
                    def interrupted_read(*args,**kwargs):
                        requests.append(owner.submit(lambda s:True,priority=0))
                        state.writer.db.execute("""WITH RECURSIVE n(x) AS
                            (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<10000)
                            SELECT sum(x) FROM n""").fetchone()
                        return native(*args,**kwargs)
                    with patch.object(state.writer,'retain',side_effect=interrupted_read):
                        return state.retention()
                outcome=owner.submit(exercise,priority=4).result(5)
                self.assertTrue(requests[0].result(5))
                self.assertTrue(outcome.interrupted)
                self.assertIs(outcome.pending,None)
                self.assertFalse(outcome.made_progress)
                self.assertFalse(outcome.pressure)
                self.assertTrue(outcome.retry)
            finally:
                owner.close()

    def test_service_outcomes_cannot_count_an_uncommitted_outer_transaction(self):
        with self.state() as state:
            with state.writer.transaction():
                with self.assertRaisesRegex(EvidenceUnavailable,'retention_inside_source_transaction'):
                    state.retention()

    def test_outcomes_require_explicit_semantics(self):
        with self.assertRaisesRegex(TypeError,'explicit'):
            bool(RetentionOutcome(pending=True))
        self.assertFalse(RetentionOutcome(retired_records=256,pending=False).retry)
        self.assertTrue(RetentionOutcome(pending=None,interrupted=True).retry)

    def test_continuity_only_cleanup_counts_without_record_deletions(self):
        with self.state() as state:
            # Real source schemas, no record bodies required for an old receipt.
            db=state.writer.db
            db.execute("INSERT INTO cursors VALUES('empty',100,1000)")
            db.execute("INSERT INTO stream_deliveries VALUES('empty',10,'sig','hash',10)")
            outcome=state.retention()
            self.assertEqual(outcome.retired_records,0)
            self.assertEqual(outcome.continuity_rows,1)
            self.assertTrue(outcome.made_progress)
            self.assertIs(outcome.pending,False)


class RetentionTimingTests(unittest.TestCase):
    state=RetentionOutcomeTests.state

    def test_timing_disabled_performs_no_clock_or_runnable_probes(self):
        progress=RetentionProgress()
        with patch('meme_machine.solana_retention_outcome.time.monotonic') as wall, \
                patch('meme_machine.solana_retention_outcome.time.thread_time') as cpu, \
                patch('meme_machine.solana_retention_outcome.runnable_snapshot') as runnable:
            with progress.phase('plan'):
                progress.scope('still-pending',True)
        wall.assert_not_called();cpu.assert_not_called();runnable.assert_not_called()
        self.assertEqual(progress.timing_metrics(),{})
        self.assertIs(progress.snapshot().pending,True)

    def test_timing_aggregates_exact_exclusive_samples_and_omits_unentered_phases(self):
        progress=RetentionProgress(timing_enabled=True)
        with patch('meme_machine.solana_retention_outcome.time.monotonic',
                   side_effect=[10,10.25,11,11.5,12,12.125]), \
                patch('meme_machine.solana_retention_outcome.time.thread_time',
                      side_effect=[3,3.125,4,4.25,5,5.0625]), \
                patch('meme_machine.solana_retention_outcome.runnable_snapshot',side_effect=[
                    (123,456,1000),(123,456,1001000),
                    (123,456,2001000),(123,456,5001000),
                    (123,456,6001000),(123,456,8001000)]):
            for name in ('plan','transaction','plan'):
                with progress.phase(name):pass
        self.assertEqual(progress.timing_metrics(),{
            'retention_phase.plan.wall_us':375000,
            'retention_phase.plan.cpu_us':187500,
            'retention_phase.plan.runnable_us':3000,
            'retention_phase.transaction.wall_us':500000,
            'retention_phase.transaction.cpu_us':250000,
            'retention_phase.transaction.runnable_us':3000,
            'retention_phase.unmeasured':0})
        self.assertEqual(progress.snapshot().committed_slices,0)
        self.assertFalse(progress.snapshot().made_progress)

    def test_timing_probe_failures_and_identity_changes_preserve_first_error(self):
        cases=[
            ('wall_failure',[OSError('optional clock'),11],[1,2],[(123,456,1000)]),
            ('nonfinite_wall',[float('nan'),11],[1,2],[(123,456,1000)]),
            ('nonfinite_cpu',[10,11],[1,float('inf')],[(123,456,1000)]),
            ('runnable_failure',[10,11],[1,2],[OSError('optional proc'),(123,456,2000)]),
            ('changed_tid',[10,11],[1,2],[(123,456,1000),(123,457,2000)]),
            ('changed_pid',[10,11],[1,2],[(123,456,1000),(124,456,2000)]),
        ]
        for name,walls,cpus,runnables in cases:
            with self.subTest(name=name):
                progress=RetentionProgress(timing_enabled=True)
                original=RuntimeError('original application failure')
                with patch('meme_machine.solana_retention_outcome.time.monotonic',side_effect=walls), \
                        patch('meme_machine.solana_retention_outcome.time.thread_time',side_effect=cpus), \
                        patch('meme_machine.solana_retention_outcome.runnable_snapshot',side_effect=runnables):
                    with self.assertRaises(RuntimeError) as caught:
                        with progress.phase('transaction'):raise original
                self.assertIs(caught.exception,original)
                self.assertEqual(progress.timing_metrics()['retention_phase.unmeasured'],1)
                self.assertNotIn('retention_phase.transaction.runnable_us',progress.timing_metrics())
                # A later valid measurement cannot erase the earlier loss.
                with patch.object(progress,'_timing_sample',side_effect=[
                        (20,5,(123,456,3000)),(20.25,5.125,(123,456,4000))]):
                    with progress.phase('post'):pass
                self.assertEqual(progress.timing_metrics()['retention_phase.unmeasured'],1)
                self.assertEqual(progress.snapshot().committed_slices,0)

    def test_timed_retention_keeps_committed_slice_after_later_rollback(self):
        with self.state() as state:
            seed(state,700)
            db=state.writer.db
            db.execute("""CREATE TRIGGER fail_timed_second BEFORE DELETE ON records
                WHEN OLD.identity='program:meteora:outcome:00260'
                BEGIN SELECT RAISE(ABORT,'timed_rollback'); END""")
            with patch.dict(os.environ,{'MM_SQLITE_DIAGNOSTIC_REQUIRED':'1'}):
                with self.assertRaisesRegex(sqlite3.IntegrityError,'timed_rollback'):
                    state.retention()
            outcome=state.writer.last_retention_progress.snapshot()
            self.assertEqual((outcome.retired_records,outcome.committed_slices),(256,1))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM records').fetchone()[0],444)
            self.assertFalse(db.in_transaction)
            self.assertIn('retention_phase.transaction.wall_us',state.storage_metrics)
            self.assertIn('retention_phase.transaction.cpu_us',state.storage_metrics)
            self.assertNotIn('retention_phase.post.wall_us',state.storage_metrics)
            db.execute('DROP TRIGGER fail_timed_second')
            with patch.dict(os.environ,{'MM_SQLITE_DIAGNOSTIC_REQUIRED':'1'}):
                finished=state.retention()
                repeated=state.retention()
            self.assertEqual(finished.retired_records,444)
            self.assertEqual(repeated.retired_records,0)
            self.assertEqual(db.execute("SELECT value FROM counters WHERE key='compacted_records'").fetchone()[0],700)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)

    def test_transaction_timing_includes_original_commit_context_exit(self):
        with self.state() as state:
            seed(state,1)
            writer=state.writer;native=writer._retention_transaction
            clock=[10.,5.,1000]
            @contextmanager
            def transaction(*args,**kwargs):
                with native(*args,**kwargs):yield
                # Controlled post-COMMIT exit work must remain inside the
                # transaction timer, without changing its production manager.
                self.assertFalse(writer.db.in_transaction)
                self.assertEqual(writer.last_retention_progress.committed_slices,1)
                clock[0]+=.25;clock[1]+=.125;clock[2]+=1000000
            def sample():return clock[0],clock[1],(123,456,clock[2])
            with patch.dict(os.environ,{'MM_SQLITE_DIAGNOSTIC_REQUIRED':'1'}), \
                    patch.object(writer,'_retention_transaction',side_effect=transaction), \
                    patch.object(RetentionProgress,'_timing_sample',side_effect=sample):
                outcome=state.retention()
            self.assertEqual(outcome.retired_records,1)
            self.assertEqual(state.storage_metrics['retention_phase.transaction.wall_us'],250000)
            self.assertEqual(state.storage_metrics['retention_phase.transaction.cpu_us'],125000)
            self.assertEqual(state.storage_metrics['retention_phase.transaction.runnable_us'],1000)
            self.assertEqual(state.storage_metrics['retention_phase.plan.wall_us'],0)
            self.assertEqual(state.storage_metrics['retention_phase.housekeeping.wall_us'],0)
            self.assertEqual(state.storage_metrics['retention_phase.post.wall_us'],0)
            self.assertEqual(state.storage_metrics['retention_phase.unmeasured'],0)

    def test_service_timing_export_accumulates_without_economic_writes(self):
        with self.state() as state:
            seed(state,1,hot=True)
            with patch.dict(os.environ,{'MM_SQLITE_DIAGNOSTIC_REQUIRED':'0'}):state.retention()
            before=state.writer.db.total_changes;clock=[0]
            def sample():
                clock[0]+=1
                return clock[0]/4,clock[0]/8,(123,456,clock[0]*1000)
            with patch.dict(os.environ,{'MM_SQLITE_DIAGNOSTIC_REQUIRED':'1'}), \
                    patch.object(RetentionProgress,'_timing_sample',side_effect=sample):
                first=state.retention()
                metrics=state.writer.last_retention_progress.timing_metrics()
                prior={key:state.storage_metrics[key] for key in metrics}
                second=state.retention()
            self.assertFalse(first.made_progress);self.assertFalse(second.made_progress)
            self.assertEqual(state.writer.db.total_changes,before)
            for key,value in metrics.items():
                self.assertEqual(state.storage_metrics[key],prior[key]+value)
            self.assertNotIn('retention_phase.transaction.wall_us',state.storage_metrics)
            self.assertEqual(state.storage_metrics['retention_phase.unmeasured'],0)

    def test_service_recorder_failure_preserves_original_sql_error(self):
        with self.state() as state:
            before=state.writer.db.total_changes
            original=sqlite3.OperationalError('disk I/O error')
            with patch.dict(os.environ,{'MM_SQLITE_DIAGNOSTIC_REQUIRED':'1'}), \
                    patch.object(state.writer,'retain',side_effect=original), \
                    patch.object(RetentionProgress,'timing_metrics',side_effect=OSError('optional recorder')):
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    state.retention()
            self.assertIs(caught.exception,original)
            self.assertEqual(state.storage_metrics['retention_phase.unmeasured'],1)
            self.assertEqual(state.writer.db.total_changes,before)
            self.assertFalse(state.writer.db.in_transaction)
            self.assertEqual(state.writer.last_retention_progress.snapshot().committed_slices,0)


if __name__=='__main__':
    unittest.main()
