"""Production-owner fences and bounded archive queries; no provider access."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import threading
import time
import unittest
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceWriter, EvidenceReader
from tests.test_run381_retention_progress import record, proof


class CoordinatedDatabaseTests(unittest.TestCase):
    def test_snapshot_set_queries_preserve_records_and_pins(self):
        with tempfile.TemporaryDirectory() as td:
            writer=EvidenceWriter(Path(td)/'db',clock=lambda:1000)
            try:
                rows=[replace(record(),identity='row:%04d'%i,signature='s:%04d'%i,
                              slot=10+i//100) for i in range(1000)]
                writer.ingest(rows,proof=proof(10,20))
                writer.ingest([replace(record(),identity='pinned',signature='pinned',slot=100)])
                writer.interest('position','pump',lower_slot=100,priority=0,lifecycle='open')
                statements=[]
                writer.db.set_trace_callback(lambda sql:statements.append(1) if sql.startswith(('SELECT','WITH')) else None)
                try:snapshot=writer.archive_snapshot(1000)
                finally:writer.db.set_trace_callback(None)
                self.assertEqual(len(snapshot['rows']),1000)
                self.assertLessEqual(len(statements),50)
                self.assertNotIn('pinned',{r['identity'] for r in snapshot['rows']})
                plan,receipt=writer.prepare_and_write_archive(writer.path,snapshot,max_bytes=16*1024*1024)
                self.assertEqual(writer.commit_archive(plan,receipt),1000)
                self.assertIsNotNone(writer.db.execute("SELECT body FROM records WHERE identity='pinned'").fetchone()[0])
                self.assertEqual(writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            finally:writer.close()

    def owner(self,path):
        def factory():
            writer=EvidenceWriter(path,clock=lambda:1000)
            writer.db.execute('PRAGMA wal_autocheckpoint=0')
            writer.ingest([record()],proof=proof(10,10))
            return SimpleNamespace(writer=writer,close=writer.close)
        owner=PriorityOwner(factory);owner.ready.result(5)
        return owner

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
                    ticket=self.idle_ticket(owner)
                    passive=EvidenceWriter.checkpoint(path)
                    self.assertEqual(passive[1],passive[2])
                    owner.submit(lambda s,p=priority:s.writer.ingest([
                        replace(record(),identity='tail:'+str(p),signature='tail:'+str(p))]),
                        priority=priority).result(5)
                    called=[]
                    def guarded(state):
                        if owner.checkpoint_current(ticket):
                            called.append(True);return state.writer.finish_checkpoint()
                        return None
                    self.assertIsNone(owner.submit(guarded,priority=2).result(5))
                    self.assertEqual(called,[],'stale completion performed owner-side catch-up')
                ticket=self.idle_ticket(owner);passive=EvidenceWriter.checkpoint(path)
                self.assertEqual(passive[1],passive[2])
                def clean(state):
                    self.assertTrue(owner.checkpoint_current(ticket))
                    return state.writer.finish_checkpoint()
                self.assertEqual(owner.submit(clean,priority=2).result(5),(0,0,0))
                self.assertEqual(Path(str(path)+'-wal').stat().st_size,0)
            finally:owner.close()
            reader=EvidenceReader(path)
            try:self.assertEqual(len(reader.window('pump',10,10,as_of=1000)),4)
            finally:reader.close()

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
