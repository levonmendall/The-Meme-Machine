"""Concurrent cold startup, bounded local lock recovery, and evidence preservation."""
import multiprocessing
import os
import queue
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.lanes.meteora import solana_evidence_broker as module


def start_broker(path, barrier, output, identity):
    try:
        barrier.wait(timeout=20)
        broker = module.EvidenceBroker(path)
        broker.record_event("startup", slot=identity+1, signature=str(identity))
        broker.close()
        output.put(("ok", identity))
    except BaseException as error:
        output.put(("error", type(error).__name__, str(error)))


class StartupWALTests(unittest.TestCase):
    def test_real_journal_transition_waits_for_existing_reader_then_preserves_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "broker.sqlite")
            owner = sqlite3.connect(path)
            self.addCleanup(owner.close)
            owner.execute("CREATE TABLE retained(value TEXT)")
            owner.execute("INSERT INTO retained VALUES('original')")
            owner.commit()
            owner.execute("BEGIN")
            owner.execute("SELECT * FROM retained").fetchall()
            db = sqlite3.connect(path)
            self.addCleanup(db.close)
            waits = []
            def release(delay):
                waits.append(delay)
                owner.rollback()
            self.assertEqual(module._enable_wal(db, sleeper=release), "wal")
            self.assertEqual(len(waits), 1)
            self.assertEqual(db.execute("SELECT * FROM retained").fetchall(), [("original",)])
            self.assertEqual(db.execute("PRAGMA busy_timeout").fetchone()[0], 30000)

    def test_simultaneous_fresh_processes_share_one_intact_broker(self):
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "broker.sqlite")
            barrier = context.Barrier(6)
            output = context.Queue()
            processes = [context.Process(target=start_broker,args=(path,barrier,output,i)) for i in range(6)]
            try:
                for process in processes:process.start()
                rows = [output.get(timeout=40) for _ in processes]
                for process in processes:process.join(timeout=10)
                self.assertEqual(sorted(rows), [("ok", i) for i in range(6)])
                self.assertEqual([p.exitcode for p in processes], [0]*6)
                broker = module.EvidenceBroker(path)
                try:
                    self.assertEqual(len(broker.recent_events("startup")), 6)
                    self.assertEqual(broker.db.execute("SELECT count(*) FROM stream_signature_archive").fetchone()[0], 6)
                    self.assertEqual(broker.db.execute("PRAGMA quick_check").fetchall(), [("ok",)])
                    self.assertEqual(broker.db.execute("SELECT count(*) FROM pressure").fetchone()[0], 1)
                    with self.assertRaisesRegex(sqlite3.IntegrityError,"append_only"):
                        broker.db.execute("DELETE FROM stream_signature_archive")
                finally:broker.close()
            finally:
                for process in processes:
                    if process.is_alive():process.terminate()
                    if process.pid is not None:process.join(timeout=5)
                output.close()
                output.join_thread()

    def fake_db(self, code):
        error = sqlite3.OperationalError("test local startup failure")
        if code is not None:error.sqlite_errorcode=code
        class DB:
            def __init__(self):self.calls=[]
            def execute(self, sql):
                self.calls.append(sql)
                if sql == "PRAGMA journal_mode=WAL":raise error
        return DB(), error

    def test_persistent_busy_exhausts_single_deadline_and_restores_busy_timeout(self):
        for code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_BUSY | (2<<8)):
            with self.subTest(code=code):
                db, error = self.fake_db(code)
                now=[0.0]
                waits=[]
                def sleep(delay):
                    waits.append(delay);now[0]+=delay
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    module._enable_wal(db, timeout=0.12, monotonic=lambda:now[0], sleeper=sleep)
                self.assertIs(caught.exception,error)
                self.assertAlmostEqual(sum(waits),0.12)
                self.assertEqual(db.calls.count("PRAGMA journal_mode=WAL"),4)
                self.assertEqual(db.calls[-1],"PRAGMA busy_timeout=30000")

    def test_non_lock_operational_errors_fail_without_retry(self):
        for code in (None,sqlite3.SQLITE_CORRUPT,sqlite3.SQLITE_READONLY,sqlite3.SQLITE_IOERR):
            with self.subTest(code=code):
                db,error=self.fake_db(code)
                with patch.object(module.time,"sleep") as sleep:
                    with self.assertRaises(sqlite3.OperationalError) as caught:
                        module._enable_wal(db,sleeper=sleep)
                self.assertIs(caught.exception,error)
                sleep.assert_not_called()
                self.assertEqual(db.calls.count("PRAGMA journal_mode=WAL"),1)

    def test_failed_constructor_closes_connection_without_initializing_consumers(self):
        with patch.object(module.sqlite3,"connect") as connect, patch.object(module,"_enable_wal",side_effect=sqlite3.OperationalError("locked")), patch.object(module,"EvidenceConsumers") as consumers:
            with self.assertRaises(sqlite3.OperationalError):module.EvidenceBroker(":memory:")
            connect.return_value.close.assert_called_once()
            consumers.assert_not_called()

    def test_memory_broker_remains_supported(self):
        broker=module.EvidenceBroker(":memory:")
        try:self.assertEqual(broker.db.execute("PRAGMA journal_mode").fetchone()[0],"memory")
        finally:broker.close()
