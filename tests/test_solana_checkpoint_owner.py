"""Source commits stay durable without also performing retention's checkpoint."""
from dataclasses import replace
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest

from meme_machine.solana_evidence_plane import EvidenceWriter
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_provider_config import AlchemyEndpoint
from tests.test_run381_retention_progress import record


class CheckpointOwnerTests(unittest.TestCase):
    def test_source_commit_publishes_durable_wal_and_retention_copies_database(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'db'
            state = ServiceState(path, AlchemyEndpoint.parse(
                'https://solana-mainnet.g.alchemy.com/v2/offline-test'))
            try:
                state.writer.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                before = path.stat().st_size
                payload = {'public_fixture': random.Random(23).randbytes(16000).hex()}
                rows = [replace(record(), identity='checkpoint:'+str(i),
                    signature='signature:'+str(i), payload=payload, market_time=1000, observed_at=2000)
                    for i in range(400)]
                state.writer.ingest(rows)
                wal = Path(str(path)+'-wal')
                self.assertGreater(wal.stat().st_size, 4*1024*1024,
                    'fixture did not cross the former automatic checkpoint threshold')
                self.assertEqual(path.stat().st_size, before,
                    'source commit performed a redundant database checkpoint')
                # An independent connection observes the committed records from
                # WAL while the main database has not yet copied their pages.
                with sqlite3.connect(path) as reader:
                    self.assertEqual(reader.execute('SELECT COUNT(*) FROM records').fetchone()[0], 400)
                    self.assertEqual(reader.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(state.writer.db.execute('PRAGMA synchronous').fetchone()[0], 2)
                state.writer.retain(0, archive_first=False)
                self.assertGreater(path.stat().st_size, before)
                self.assertLess(path.stat().st_size+wal.stat().st_size, state.writer.max_hot_bytes)
            finally:
                state.close()

    def test_standalone_writer_keeps_automatic_checkpoint_and_service_keeps_capacity_guard(self):
        with tempfile.TemporaryDirectory() as td:
            writer = EvidenceWriter(Path(td)/'standalone')
            try:
                self.assertGreater(writer.db.execute('PRAGMA wal_autocheckpoint').fetchone()[0], 0)
            finally:
                writer.close()
            state = ServiceState(Path(td)/'service', AlchemyEndpoint.parse(
                'https://solana-mainnet.g.alchemy.com/v2/offline-test'))
            try:
                self.assertEqual(state.writer.max_hot_bytes, 2*1024**3)
            finally:
                state.close()


if __name__ == '__main__':
    unittest.main()
