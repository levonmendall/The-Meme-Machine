"""Provider-free retention read-cost regression, with unchanged evidence semantics.

The tested writer is byte-identical to canonical Phase E #21 before the additive
index change. These are focused SQLite tests, not a full Phase-E certificate.
"""
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from meme_machine.solana_evidence_plane import EvidenceWriter, EvidenceReader
from tests.test_retention_progress import record, proof

INDEX = 'records_hot_scope_slot'
FLOOR = 'SELECT MIN(slot) FROM records WHERE scope=? AND body IS NOT NULL'

class RetentionAccessPathTests(unittest.TestCase):
    def writer(self, td):
        return EvidenceWriter(Path(td)/'db', clock=lambda:10000)

    def seed(self, writer):
        for start in range(0,4096,1024):
            writer.ingest([replace(record(),identity=f'archived:{i:06}',signature=f'archived:{i:06}',
                                  slot=10+i//128) for i in range(start,start+1024)])
        while writer.archive(500):
            pass
        writer.ingest([replace(record(),identity='hot',signature='hot',slot=1000,
                               market_time=1000,observed_at=1000)])

    def test_first_hot_lookup_does_not_scan_archived_backlog(self):
        with tempfile.TemporaryDirectory() as td:
            writer=self.writer(td)
            try:
                self.seed(writer)
                steps=[0]
                def count():steps[0]+=1;return 0
                writer.db.set_progress_handler(count,1)
                try:floor=writer.db.execute(FLOOR,('pump',)).fetchone()[0]
                finally:writer.db.set_progress_handler(None,0)
                self.assertEqual(floor,1000)
                self.assertLess(steps[0],200,'first-hot lookup walks archived records instead of seeking hot index')
            finally:writer.close()

    def test_index_migration_and_restart_preserve_every_record(self):
        with tempfile.TemporaryDirectory() as td:
            writer=self.writer(td)
            self.seed(writer)
            before=writer.db.execute('SELECT identity,scope,slot,body,hash,archive FROM records ORDER BY identity').fetchall()
            writer.db.execute('DROP INDEX IF EXISTS '+INDEX)
            writer.close()
            for _ in range(2):
                writer=self.writer(td)
                try:
                    self.assertIsNotNone(writer.db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?",(INDEX,)).fetchone())
                    self.assertEqual(before,writer.db.execute('SELECT identity,scope,slot,body,hash,archive FROM records ORDER BY identity').fetchall())
                    self.assertEqual(writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
                finally:writer.close()

    def test_archive_transition_updates_index_without_changing_floor(self):
        with tempfile.TemporaryDirectory() as td:
            writer=self.writer(td)
            try:
                writer.ingest([replace(record(),identity='first',slot=20,market_time=20),
                               replace(record(),identity='next',slot=30,market_time=30)])
                self.assertEqual(writer.db.execute(FLOOR,('pump',)).fetchone()[0],20)
                self.assertEqual(writer.archive(25),1)
                self.assertEqual(writer.db.execute(FLOOR,('pump',)).fetchone()[0],30)
                self.assertEqual(writer.archive(40),1)
                self.assertIsNone(writer.db.execute(FLOOR,('pump',)).fetchone()[0])
                self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],2)
            finally:writer.close()

    def test_retirement_slice_is_identical_with_and_without_index(self):
        results=[]
        for with_index in (False,True):
            with tempfile.TemporaryDirectory() as td:
                writer=self.writer(td)
                try:
                    self.seed(writer)
                    if not with_index:writer.db.execute('DROP INDEX IF EXISTS '+INDEX)
                    # Existing archive semantics, 256-row durable deletion bound.
                    writer.retain(500,max_records=256,archive_first=False,checkpoint=False)
                    self.assertEqual(writer.db.execute("SELECT value FROM counters WHERE key='compacted_records'").fetchone()[0],256)
                    results.append(writer.db.execute('SELECT identity,scope,slot,body,hash FROM records ORDER BY identity').fetchall())
                    self.assertEqual(writer.db.execute('PRAGMA foreign_key_check').fetchall(),[])
                    self.assertEqual(writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
                finally:writer.close()
        self.assertEqual(results[0],results[1])

if __name__=='__main__':unittest.main()
