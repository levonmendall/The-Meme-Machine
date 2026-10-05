"""Read-only provider census keeps transactional caching and releases SQLite."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from meme_machine.lanes.ramses import BoundaryError, ramses_lifecycle_log_census as census


class RamsesCensusConnectionTests(unittest.TestCase):
    def check_case(self, *, failure=False):
        original = sqlite3.connect
        opened, closed = [], []

        class Tracked(sqlite3.Connection):
            def close(self):
                closed.append(self)
                return super().close()

        def connect(*args, **kwargs):
            db = original(*args, **kwargs, factory=Tracked)
            opened.append(db)
            return db

        provider = Mock()
        provider.batch.return_value = [None if failure else []]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old-census.sqlite'
            db = original(path)
            db.execute('CREATE TABLE log_pages(identity TEXT PRIMARY KEY, body TEXT NOT NULL)')
            db.commit()
            db.close()
            try:
                with patch.object(census.sqlite3, 'connect', side_effect=connect):
                    if failure:
                        with self.assertRaisesRegex(BoundaryError, 'connected_lifecycle_log_page_shape'):
                            census.collect(1, 2, '0x' + '1' * 40, cache_path=path,
                                           reader_factory=lambda *a, **kw: provider)
                    else:
                        self.assertEqual(census.collect(1, 2, '0x' + '1' * 40, cache_path=path,
                                         reader_factory=lambda *a, **kw: provider), [])
                self.assertEqual(opened, closed)
                with self.assertRaises(sqlite3.ProgrammingError):
                    opened[0].execute('SELECT 1')
                db = original(path)
                try:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM log_pages').fetchone()[0],
                                     0 if failure else 1)
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                finally:
                    db.close()
                if not failure:
                    # An authenticated empty page remains durable and reusable.
                    self.assertEqual(census.collect(1, 2, '0x' + '1' * 40, cache_path=path,
                                     reader_factory=Mock(side_effect=AssertionError('cache missed'))), [])
            finally:
                for db in opened:
                    db.close()

    def test_completed_page_commits_and_closes(self):
        self.check_case()

    def test_invalid_page_is_not_cached_and_reader_closes(self):
        self.check_case(failure=True)
