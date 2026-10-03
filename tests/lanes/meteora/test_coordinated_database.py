"""Production-owner fences and bounded archive queries; no provider access."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import threading
import time
import unittest
from meme_machine.lanes.meteora.solana_evidence_control import PriorityOwner
from meme_machine.lanes.meteora.solana_evidence_plane import EvidenceWriter,EvidenceReader,EvidenceUnavailable
from tests.lanes.meteora.test_run381_retention_progress import record,proof


class CoordinatedDatabaseTests(unittest.TestCase):
    def test_snapshot_set_queries_preserve_records_and_pins(self):
        with tempfile.TemporaryDirectory() as td:
            writer=EvidenceWriter(Path(td)/'db',clock=lambda:1000)
            try:
                rows=[replace(record(),identity='row:%04d'%i,signature='s:%04d'%i,slot=10+i//100) for i in range(1000)]
                writer.ingest(rows,proof=proof(10,20))
                writer.ingest([replace(record(),identity='pinned',signature='pinned',slot=100)])
                writer.interest('position','pump',lower_slot=100,priority=0,lifecycle='open')
                statements=[]
                writer.db.set_trace_callback(lambda sql:statements.append(1) if sql.startswith(('SELECT','WITH')) else None)
                try:snapshot=writer.archive_snapshot(1000)
                finally:writer.db.set_trace_callback(None)
                self.assertEqual(len(snapshot['rows']),1000);self.assertLessEqual(len(statements),50)
                self.assertNotIn('pinned',{r['identity'] for r in snapshot['rows']})
                plan,receipt=writer.prepare_and_write_archive(writer.path,snapshot,max_bytes=16*1024*1024)
                self.assertEqual(writer.commit_archive(plan,receipt),1000)
                self.assertIsNotNone(writer.db.execute("SELECT body FROM records WHERE identity='pinned'").fetchone()[0])
                self.assertEqual(writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            finally:writer.close()

    def test_every_snapshot_cursor_closes_after_injected_iteration_failure(self):
        prefixes=('WITH account_pins','SELECT r.identity,c.hash','SELECT identity,source',
                  'WITH wanted','SELECT identity,body','SELECT hash,body')
        for prefix in prefixes:
            with self.subTest(prefix=prefix),tempfile.TemporaryDirectory() as td:
                writer=EvidenceWriter(Path(td)/'db',clock=lambda:1000)
                writer.ingest([replace(record(),identity='cursor:'+str(i),signature='cursor:'+str(i),
                    payload={'raw_lineage':{'logs':['large-line'*2000],'err':None}})
                    for i in range(16)],proof=proof(10,10))
                held=[];cursors=[]
                class Cursor:
                    def __init__(self,cursor):self.cursor=cursor;self.closed=False
                    def __iter__(self):return self
                    def __next__(self):
                        self.cursor.fetchone();raise sqlite3.OperationalError('injected_snapshot_read')
                    def fetchall(self):
                        self.cursor.fetchone();raise sqlite3.OperationalError('injected_snapshot_read')
                    def close(self):self.closed=True;self.cursor.close()
                class DB:
                    def __init__(self,db):self.db=db;self.armed=True
                    def __getattr__(self,key):return getattr(self.db,key)
                    def execute(self,sql,*args):
                        cursor=self.db.execute(sql,*args)
                        if self.armed and sql.startswith(prefix):
                            wrapped=Cursor(cursor);cursors.append(wrapped);return wrapped
                        return cursor
                db=DB(writer.db);writer.db=db
                try:
                    try:writer.archive_snapshot(1000)
                    except sqlite3.OperationalError as exc:held.append(exc)
                    self.assertEqual(len(held),1);self.assertTrue(cursors)
                    self.assertTrue(all(c.closed for c in cursors))
                    db.armed=False
                    writer.retain(1000,archive_first=False)
                    self.assertEqual(db.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()[0],0)
                finally:writer.close()

    def owner(self,path):
        def factory():
            writer=EvidenceWriter(path,clock=lambda:1000)
            writer.db.execute('PRAGMA wal_autocheckpoint=0')
            writer.ingest([record()],proof=proof(10,10))
            return SimpleNamespace(writer=writer,close=writer.close)
        owner=PriorityOwner(factory);owner.ready.result(5);return owner

    def idle_ticket(self,owner):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            ticket=owner.checkpoint_ticket()
            if ticket is not None:return ticket
            time.sleep(.001)
        self.fail('owner_never_became_idle')

    def test_intervening_source_or_urgent_command_invalidates_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db';owner=self.owner(path)
            try:
                for priority in (0,2,4):
                    ticket=self.idle_ticket(owner);passive=EvidenceWriter.checkpoint(path)
                    self.assertEqual(passive[1],passive[2])
                    owner.submit(lambda s,p=priority:s.writer.ingest([
                        replace(record(),identity='tail:'+str(p),signature='tail:'+str(p))]),priority=priority).result(5)
                    called=[]
                    def guarded(state):
                        if owner.checkpoint_current(ticket):called.append(True);return state.writer.finish_checkpoint()
                        return None
                    self.assertIsNone(owner.submit(guarded,priority=2).result(5))
                    self.assertEqual(called,[],'stale completion performed owner-side catch-up')
                ticket=self.idle_ticket(owner);passive=EvidenceWriter.checkpoint(path)
                self.assertEqual(passive[1],passive[2])
                def clean(state):
                    self.assertTrue(owner.checkpoint_current(ticket));return state.writer.finish_checkpoint()
                self.assertEqual(owner.submit(clean,priority=2).result(5),(0,0,0))
                self.assertEqual(Path(str(path)+'-wal').stat().st_size,0)
            finally:owner.close()
            reader=EvidenceReader(path)
            try:self.assertEqual(len(reader.window('pump',10,10,as_of=1000)),4)
            finally:reader.close()

    def test_fifo_checkpoint_marker_progresses_without_idle_queue_polling(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db';owner=self.owner(path)
            try:
                with self.assertRaisesRegex(EvidenceUnavailable,'checkpoint_ticket_owner_thread'):
                    owner.checkpoint_ticket_after_current()
                for _ in range(8):
                    owner.submit(lambda s:s.writer.acknowledge('probe','pump',10),priority=0).result(5)
                    ticket=owner.submit(lambda s:owner.checkpoint_ticket_after_current(),priority=2).result(5)
                    passive=EvidenceWriter.checkpoint(path);self.assertEqual(passive[1],passive[2])
                    def finish(state):
                        self.assertTrue(owner.checkpoint_current(ticket));return state.writer.finish_checkpoint()
                    self.assertEqual(owner.submit(finish,priority=2).result(5),(0,0,0))
            finally:owner.close()

    def test_ticket_is_unavailable_during_inflight_owner_operation(self):
        with tempfile.TemporaryDirectory() as td:
            owner=self.owner(Path(td)/'db');entered=threading.Event();release=threading.Event()
            try:
                def active(state):
                    entered.set()
                    if not release.wait(5):raise TimeoutError('test_owner_release')
                future=owner.submit(active,priority=2)
                self.assertTrue(entered.wait(5));self.assertIsNone(owner.checkpoint_ticket())
                release.set();future.result(5)
            finally:release.set();owner.close()


if __name__=='__main__':unittest.main()
