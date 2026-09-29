"""E24: stale interruption flags and durable, fixed-cardinality lifecycle counts."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_plane import lifecycle_scope
from meme_machine.solana_evidence_service import ServiceState
from tests.test_retention_outcomes import CONFIG, seed
from tests.test_run381_retention_progress import record


class MaintenanceIntegrityTests(unittest.TestCase):
    @contextmanager
    def state(self):
        with tempfile.TemporaryDirectory() as folder:
            state=ServiceState(Path(folder)/'db',CONFIG)
            try:yield state
            finally:state.close()

    def counts(self,state):
        return dict(state.writer.db.execute('SELECT key,value FROM counters WHERE key LIKE \'lifecycle.%\''))

    def test_stale_interruption_flag_never_swallows_storage_error(self):
        for message in ('disk I/O error','database is locked','database or disk is full'):
            with self.subTest(message=message),self.state() as state:
                state.writer._background_sql_interrupted=True
                with patch.object(state.writer,'retain',side_effect=sqlite3.OperationalError(message)):
                    with self.assertRaisesRegex(sqlite3.OperationalError,message):state.retention()
                self.assertNotIn('retention_outcome.unknown',state.storage_metrics)
                self.assertEqual(state.storage_metrics['retention.failed'],1)

    def test_actual_interrupt_without_owner_evidence_is_not_swallowed(self):
        with self.state() as state:
            with patch.object(state.writer,'retain',side_effect=sqlite3.OperationalError('interrupted')):
                with self.assertRaises(sqlite3.OperationalError):state.retention()

    def test_new_rows_archive_retry_and_retirement_counts_are_exact(self):
        with self.state() as state:
            seed(state,256)
            initial=self.counts(state)
            self.assertEqual(initial['lifecycle.ingested.program:meteora'],256)
            self.assertEqual(initial['lifecycle.archived.program:meteora'],256)
            # Archive publication already succeeded in seed(); replaying retention
            # after drain must not book the same work twice.
            state.retention();state.retention()
            counts=self.counts(state)
            self.assertEqual(counts['lifecycle.retired.program:meteora'],256)
            self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)

    def test_rollback_and_duplicate_ingestion_cannot_count_useful_work(self):
        with self.state() as state:
            row=replace(record(),scope='program:meteora')
            state.writer.ingest([row]);state.writer.ingest([row])
            self.assertEqual(self.counts(state)['lifecycle.ingested.program:meteora'],1)
            with self.assertRaisesRegex(RuntimeError,'rollback'):
                with state.writer.transaction():
                    state.writer.ingest([replace(row,identity='other-identity',signature='new-signature')])
                    raise RuntimeError('rollback')
            self.assertEqual(self.counts(state)['lifecycle.ingested.program:meteora'],1)
            self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)

    def test_failed_archive_and_retirement_do_not_count_rolled_back_rows(self):
        with self.state() as state:
            state.writer.ingest([replace(record(),scope='program:meteora')])
            plan=state.writer.archive_plan(1000)
            receipt=state.writer.write_archive(state.writer.path,plan)
            db=state.writer.db
            db.execute("CREATE TRIGGER reject_archive BEFORE UPDATE OF body ON records BEGIN SELECT RAISE(ABORT,'archive_test'); END")
            with self.assertRaisesRegex(sqlite3.IntegrityError,'archive_test'):state.writer.commit_archive(plan,receipt)
            self.assertNotIn('lifecycle.archived.program:meteora',self.counts(state))
            db.execute('DROP TRIGGER reject_archive')
            state.writer.commit_archive(plan,receipt);state.writer.commit_archive(plan,receipt)
            self.assertEqual(self.counts(state)['lifecycle.archived.program:meteora'],1)
            db.execute("CREATE TRIGGER reject_retire BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT,'retire_test'); END")
            with self.assertRaisesRegex(sqlite3.IntegrityError,'retire_test'):state.retention()
            self.assertNotIn('lifecycle.retired.program:meteora',self.counts(state))
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_scope_telemetry_cardinality_never_contains_an_address(self):
        scopes=['account:secret-'+str(i) for i in range(1000)]+['custom-'+str(i) for i in range(1000)]
        self.assertEqual({lifecycle_scope(s) for s in scopes},{'account','other'})
        for name in ('program:meteora','program:pump','program:pumpswap'):
            self.assertEqual(lifecycle_scope(name),name)


if __name__=='__main__':unittest.main()
