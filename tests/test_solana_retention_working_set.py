"""Mature-store retention I/O and atomicity, using the production owner/writer."""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_provider_config import AlchemyEndpoint


def io_bytes():
    return {key: int(value.split()[0]) for line in Path('/proc/self/io').read_text().splitlines()
            for key, value in [line.split(':', 1)]}


def owner(path):
    return ServiceState(path, AlchemyEndpoint.parse(
        'https://solana-mainnet.g.alchemy.com/v2/offline-test'))


def mature_store(writer, count=24000):
    """Dense public index fixture; no fabricated evidence is queried as authority."""
    db = writer.db
    with writer.transaction():
        db.executemany('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (
            (f'record-{i:08d}', 'scope-'+str(i % 3), i, 'signature-'+str(i),
             'program', float(i), 0, None, 'event', 'x'*2500, 'h'*64, float(i), None)
            for i in range(count)))
        db.executemany('INSERT INTO lineage VALUES(?,?,?,?)', (
            (f'record-{i:08d}', 'alchemy_finalized_stream', 'a'*64, 1) for i in range(count)))
        db.executemany('INSERT INTO address_keys VALUES(?,?)', (
            (i, 'address-'+str(i)) for i in range(4000)))
        db.executemany('INSERT INTO address_refs VALUES(?,?,?)', (
            ((i*19+j) % 4000, i+1, i) for i in range(count) for j in range(16)))
        db.executemany('INSERT INTO cursors VALUES(?,?,?)', (
            ('scope-'+str(i), count, 1) for i in range(3)))
        db.execute("UPDATE records SET body=NULL,archive='archived-fixture' WHERE slot<1000")
    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    db.execute('PRAGMA shrink_memory')


class RetentionWorkingSetTests(unittest.TestCase):
    @unittest.skipUnless(Path('/proc/self/io').exists(), 'Linux process I/O counters required')
    def test_bounded_slice_avoids_statement_journal_and_page_cache_churn(self):
        with tempfile.TemporaryDirectory() as td:
            state = owner(Path(td)/'db')
            try:
                mature_store(state.writer)
                before = io_bytes()
                state.writer.retain(1e9, archive_first=False)
                after = io_bytes()
                # Counts bytes requested, independent of filesystem/cache speed.
                # Old 2 MiB/disk-temp owner requires ~126 MB writes and 73 MB
                # reads for these same 1,000 archived identities. Current bounded
                # working set needs ~34 MB writes / 20 MB reads, including WAL
                # commit and the real maintenance checkpoint.
                self.assertLess(after['wchar']-before['wchar'], 50*1024**2)
                self.assertLess(after['rchar']-before['rchar'], 40*1024**2)
                db = state.writer.db
                self.assertEqual(db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 23000)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM address_refs').fetchone()[0], 23000*16)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM lineage').fetchone()[0], 23000)
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0], 2)
                self.assertGreater(db.execute('PRAGMA cache_spill').fetchone()[0], 0)
                self.assertEqual(db.execute('PRAGMA cache_size').fetchone()[0], -16384)
                self.assertEqual(state.writer.max_hot_bytes, 2*1024**3)
            finally:
                state.close()

    def test_failed_delete_restores_trigger_changes_and_survives_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'db'
            state = owner(path)
            try:
                mature_store(state.writer, count=1200)
                db = state.writer.db
                # Fail after BEFORE DELETE has removed address_refs. Statement
                # and outer-transaction rollback must restore all prior rows.
                db.execute("""CREATE TRIGGER injected_abort AFTER DELETE ON records
                    WHEN OLD.identity='record-00000030' BEGIN
                    SELECT RAISE(ABORT,'injected retention interruption'); END""")
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'injected retention interruption'):
                    state.writer.retain(1e9, archive_first=False)
                self.assertFalse(db.in_transaction)
            finally:
                state.close()
            state = owner(path)
            try:
                db = state.writer.db
                for table, expected in (('records', 1200), ('lineage', 1200), ('address_refs', 19200)):
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0], expected)
                self.assertIsNone(db.execute("SELECT value FROM meta WHERE key='retention_floor:scope-0'").fetchone())
                db.execute('DROP TRIGGER injected_abort')
                state.writer.retain(1e9, archive_first=False)
                with sqlite3.connect(path) as reader:
                    self.assertEqual(reader.execute('SELECT COUNT(*) FROM records').fetchone()[0], 200)
                    self.assertEqual(reader.execute('SELECT COUNT(*) FROM address_refs').fetchone()[0], 3200)
                    self.assertEqual(reader.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            finally:
                state.close()


if __name__ == '__main__':
    unittest.main()
