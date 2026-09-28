"""Real production SQLite outcomes: progress, pending work and interruption."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_plane import EvidenceUnavailable, EvidenceWriter
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_provider_config import AlchemyEndpoint
from meme_machine.solana_retention_outcome import RetentionOutcome
from tests.test_run381_retention_progress import record

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


if __name__=='__main__':
    unittest.main()
