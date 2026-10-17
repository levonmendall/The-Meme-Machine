"""The original pause guard can share an independently frozen read context."""
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational import pause
from meme_machine.runtime.stop import Shutdown


class FrozenPausedReader(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.shared = self.root / 'shared/robinhood-evidence.candidates.sqlite'
        self.shared.parent.mkdir()
        self.account = type('Account', (), {})()
        self.account.db = sqlite3.connect(':memory:')
        self.addCleanup(self.account.db.close)
        self.account.db.execute('CREATE TABLE portfolio_native_pending(lane,native,body)')
        self.state = dict(positions={}, reservations={})
        self.account.snapshot = lambda: self.state
        self.opened = []
        self.closed = []

    def shared_store(self, position=None, *, keep_writer=False):
        writer = sqlite3.connect(self.shared)
        self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
        writer.execute('CREATE TABLE runtime(key PRIMARY KEY,body)')
        writer.commit()
        if position is not None:
            writer.execute('INSERT INTO runtime VALUES(?,?)',
                ('native_position:ramses:retained', json.dumps(dict(position=position))))
            writer.commit()
        if keep_writer:
            self.addCleanup(writer.close)
            return writer
        writer.close()
        self.assertEqual(self.shared.read_bytes()[18:20], b'\x02\x02')
        self.assertFalse(Path(str(self.shared) + '-wal').exists())
        self.assertFalse(Path(str(self.shared) + '-shm').exists())

    @contextmanager
    def frozen_reader(self, path):
        # Offline stand-in for the already fenced inspector's read context.
        # A present WAL always uses SQLite's normal WAL-aware reader; the app
        # guard itself never selects immutable mode or grants a stopped fence.
        path = Path(path)
        self.assertTrue(path.is_relative_to(self.root))
        self.assertTrue(path.is_file())
        sidecar = any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-journal'))
        uri = path.as_uri() + '?mode=ro' + ('' if sidecar else '&immutable=1')
        db = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=.1)
        self.opened.append((path, uri, db))
        try:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('BEGIN')
            yield db
        finally:
            db.close()
            self.closed.append(path)

    def guarded(self):
        return pause.assert_clear(self.root, self.account, read_database=self.frozen_reader)

    def assert_refused(self, kind):
        with self.assertRaises(pause.PauseExposure) as caught:
            self.guarded()
        self.assertTrue(any(row['kind'] == kind for row in caught.exception.obligations),
                        caught.exception.obligations)
        return caught.exception.obligations

    def test_closed_wal_header_without_sidecars_uses_existing_frozen_transaction(self):
        self.shared_store()
        original = hashlib.sha256(self.shared.read_bytes()).hexdigest()
        result = self.guarded()
        self.assertEqual(set(result), {'meteora', 'ramses'})
        self.assertTrue(all(row == dict(economic_obligations=0, native_state_verified=True)
                            for row in result.values()))
        self.assertEqual([path for path, _, _ in self.opened], [self.shared])
        self.assertIn('&immutable=1', self.opened[0][1])
        self.assertEqual(self.closed, [self.shared])
        self.assertEqual(hashlib.sha256(self.shared.read_bytes()).hexdigest(), original)
        self.assertFalse(Path(str(self.shared) + '-wal').exists())
        self.assertFalse(Path(str(self.shared) + '-shm').exists())
        with self.assertRaises(sqlite3.ProgrammingError):
            self.opened[0][2].execute('SELECT 1')

    def test_active_shared_projection_still_refused(self):
        self.shared_store(dict(id='retained-position', status='open', held='1'))
        rows = self.assert_refused('shared_native_projection')
        self.assertEqual(rows[0]['identity'], 'retained-position')
        self.assertEqual(self.closed, [self.shared])

    def test_legacy_positions_and_reservations_still_refused(self):
        self.shared_store()
        for kind in ('positions', 'reservations'):
            for lane in ('meteora', 'ramses'):
                with self.subTest(kind=kind, lane=lane):
                    self.state[kind]['retained'] = dict(lane=lane)
                    rows = self.assert_refused(kind)
                    self.assertTrue(any(row['lane'] == lane and row['identity'] == 'retained'
                                        for row in rows))
                    self.state[kind].clear()

    def test_pending_native_delivery_still_refused(self):
        self.shared_store()
        for lane in ('meteora', 'ramses'):
            self.account.db.execute('INSERT INTO portfolio_native_pending VALUES(?,?,?)',
                (lane, 'pending-' + lane, json.dumps(dict(kind='enter', native_event_id='unacked'))))
        rows = self.assert_refused('native_delivery')
        self.assertEqual({row['identity'] for row in rows}, {'pending-meteora', 'pending-ramses'})
        self.assertTrue(all(row['event_id'] == 'unacked' for row in rows))

    def test_native_intent_and_unknown_economic_store_still_refused(self):
        self.shared_store()
        folder = self.root / 'ramses'
        folder.mkdir()
        (folder / 'continuation.json').write_text(json.dumps(dict(pending_intent='retained')))
        native = folder / 'retained.sqlite'
        with closing(sqlite3.connect(native)) as db:
            db.execute('CREATE TABLE unknown_positions(id)')
        rows = self.assert_refused('native_intent')
        self.assertTrue(any(row['kind'] == 'unverified_native_store' for row in rows))
        self.assertEqual([path for path, _, _ in self.opened], [self.shared, native])
        self.assertEqual(self.closed, [self.shared, native])

    def test_present_wal_committed_positive_position_is_not_hidden(self):
        # Keep a real committed positive row exclusively in the live WAL.
        writer = self.shared_store(keep_writer=True)
        self.assertEqual(writer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone(), (0, 0, 0))
        writer.execute('INSERT INTO runtime VALUES(?,?)',
            ('native_position:ramses:wal',
             json.dumps(dict(position=dict(id='wal-position', status='open', held=1)))))
        writer.commit()
        wal = Path(str(self.shared) + '-wal')
        self.assertGreater(wal.stat().st_size, 0)
        main_before = self.shared.read_bytes()
        wal_before = wal.read_bytes()
        with closing(sqlite3.connect(self.shared.as_uri() + '?mode=ro&immutable=1', uri=True)) as stale:
            self.assertEqual(stale.execute('SELECT count(*) FROM runtime').fetchone(), (0,))
        rows = self.assert_refused('shared_native_projection')
        self.assertEqual(rows[0]['identity'], 'wal-position')
        self.assertNotIn('immutable', self.opened[0][1])
        self.assertEqual(self.shared.read_bytes(), main_before)
        self.assertEqual(wal.read_bytes(), wal_before)

    def test_guard_enforces_query_only_even_with_supplied_context(self):
        self.shared_store()
        queried = []

        @contextmanager
        def reader(path):
            db = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
            try:
                yield db
            finally:
                queried.append(db.execute('PRAGMA query_only').fetchone())
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute('INSERT INTO runtime VALUES(?,?)', ('forbidden', '{}'))
                db.close()

        pause.assert_clear(self.root, self.account, read_database=reader)
        self.assertEqual(queried, [(1,)])

    def test_present_native_evidence_store_reuses_existing_transaction(self):
        self.shared_store()
        native = self.root / 'meteora/evidence.sqlite'
        native.parent.mkdir()
        with closing(sqlite3.connect(native)) as db:
            db.execute('CREATE TABLE observation(id)')
        result = self.guarded()
        self.assertEqual(set(result), {'meteora', 'ramses'})
        self.assertEqual([path for path, _, _ in self.opened], [self.shared, native])
        self.assertEqual(self.closed, [self.shared, native])

    def test_unreadable_or_unknown_shared_schema_remains_refusal(self):
        with closing(sqlite3.connect(self.shared)) as db:
            db.execute('CREATE TABLE unrelated(id)')
        rows = self.assert_refused('unverified_shared_store')
        self.assertEqual(rows[0]['identity'], 'shared/robinhood-evidence.candidates.sqlite')
        self.assertEqual(self.closed, [self.shared])

    def test_symlink_shared_store_does_not_reach_supplied_reader(self):
        target = self.root / 'elsewhere.sqlite'
        target.touch()
        self.shared.symlink_to(target)
        rows = self.assert_refused('unverified_shared_store')
        self.assertEqual(rows[0]['reason'], 'symlink')
        self.assertEqual(self.opened, [])

    def test_cancellation_propagates_and_closes_read_context(self):
        self.shared_store()
        closed = []

        class CancelledQuery:
            def __init__(self, db):
                self.db = db

            @property
            def in_transaction(self):
                return self.db.in_transaction

            def execute(self, sql, *args):
                if sql.startswith('SELECT key,body FROM runtime'):
                    raise Shutdown()
                return self.db.execute(sql, *args)

        @contextmanager
        def reader(path):
            with self.frozen_reader(path) as db:
                try:
                    yield CancelledQuery(db)
                finally:
                    closed.append(path)

        with self.assertRaises(Shutdown):
            pause.assert_clear(self.root, self.account, read_database=reader)
        self.assertEqual(closed, [self.shared])
        self.assertEqual(self.closed, [self.shared])
        with self.assertRaises(sqlite3.ProgrammingError):
            self.opened[0][2].execute('SELECT 1')

    def test_original_default_reader_keeps_original_wal_aware_open(self):
        self.shared_store()
        connect = sqlite3.connect
        calls = []

        def observe(*args, **kwargs):
            calls.append((args, kwargs))
            return connect(*args, **kwargs)

        with patch.object(pause.sqlite3, 'connect', side_effect=observe):
            result = pause.assert_clear(self.root, self.account)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ((self.shared.resolve().as_uri() + '?mode=ro',),
                                    dict(uri=True, timeout=1)))
        self.assertEqual(set(result), {'meteora', 'ramses'})


if __name__ == '__main__':
    unittest.main()
