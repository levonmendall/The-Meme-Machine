"""Native ring deletion stays bounded, private and independent of evidence.

Synthetic SQLite state proves guard/transaction mechanics only. No provider,
financial book, strategy decision or market-capacity claim is involved.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, contextmanager
import os
from pathlib import Path
import select
import signal
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime.operating_families import active_sql
from meme_machine.runtime.robinhood.plane import Plane, _EVIDENCE_RETENTION_SCHEMA
from meme_machine.runtime.robinhood.pons import Broker
from meme_machine.runtime.stop import Shutdown
from meme_machine.runtime.storage import audit_ring
from tests.lanes.pons.test_pons_candidate_plane import event


RINGS = {
    'transitions': ('history_no_delete', 'seq'),
    'observations': ('observations_no_delete', 'rowid'),
}
FUNCTION = 'mm_native_audit_delete'


def legacy_guard(table):
    trigger, _ = RINGS[table]
    return ('CREATE TRIGGER ' + trigger + ' BEFORE DELETE ON ' + table +
            " BEGIN SELECT RAISE(ABORT,'append_only'); END")


class NativeAuditGuardTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            'MM_MODE': 'PAPER', 'MM_OPERATIONAL_PHASE': 'OFFLINE_TEST'}, clear=True))
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.now = 100.
        self.plane = self.open_plane('plane.sqlite')

    def open_plane(self, name):
        plane = Plane(self.root / name, clock=lambda: self.now)
        self.addCleanup(lambda: None if plane._closed else plane.close())
        return plane

    def guard(self, table, plane=None):
        plane = plane or self.plane
        return plane.db.execute('SELECT sql FROM sqlite_master WHERE name=?',
                                (RINGS[table][0],)).fetchone()[0]

    def schema(self, plane=None):
        return (plane or self.plane).db.execute('PRAGMA schema_version').fetchone()[0]

    @contextmanager
    def schema_transaction(self, plane):
        # The original Plane transaction intentionally rolls back DDL-only work
        # when total_changes is unchanged. These setup migrations must commit.
        with plane.lock:
            plane.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                plane.db.execute('COMMIT')
            except BaseException:
                if plane.db.in_transaction:
                    plane.db.execute('ROLLBACK')
                raise

    def population(self, table, plane=None):
        return (plane or self.plane).db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]

    def participation(self):
        return 'candidate NOT IN (SELECT id FROM candidates WHERE NOT (' + active_sql('lane') + '))'

    def seed_ring(self, table, *, plane=None, candidate='active', count=4097):
        """Small bodies, original schema and original 4096-row boundary."""
        plane = plane or self.plane
        if plane.get(candidate) is None:
            plane.observe(candidate, 'pons', 'first', {'synthetic': True}, ordering=(1,),
                watermark={}, interpretation={}, observed=self.now, deadline=self.now + 5,
                priority=4, needs_work=False)
        existing = self.population(table, plane)
        with plane.transaction():
            if table == 'transitions':
                last = plane.db.execute('SELECT COALESCE(MAX(seq),0) FROM transitions').fetchone()[0]
                plane.db.executemany('INSERT INTO transitions VALUES(?,?,?,?,?,?,?,?,?)',
                    ((last + n + 1, candidate, 1, self.now, 'watching', None, '{}', '{}', '{}')
                     for n in range(count - existing)))
            else:
                plane.db.executemany('INSERT INTO observations VALUES(?,?,?,?)',
                    ((candidate, 'synthetic-' + str(n), '{}', self.now)
                     for n in range(existing, count)))
        self.assertEqual(self.population(table, plane), count)

    def seed_evidence(self, plane=None):
        plane = plane or self.plane
        with plane.transaction():
            plane.db.executemany('INSERT INTO evidence VALUES(?,?,?,?,?)',
                (('pons:guard-fixture', str(n), '{}', '{}', n) for n in range(4)))

    def evidence_state(self, plane=None):
        plane = plane or self.plane
        return tuple(tuple(tuple(row) for row in plane.db.execute(sql)) for sql in (
            'SELECT * FROM evidence ORDER BY namespace,key',
            'SELECT * FROM receipt_obligations ORDER BY namespace,key,consumer,owner,generation',
            'SELECT * FROM evidence_retention_revision ORDER BY namespace'))

    def counted_maintain(self, plane=None):
        plane = plane or self.plane
        statements = []
        plane.db.set_trace_callback(statements.append)
        try:
            plane.maintain()
        finally:
            plane.db.set_trace_callback(None)
        return [sql for sql in statements
                if sql.startswith('SELECT COUNT(*) FROM evidence WHERE namespace=')]

    def prune(self, table, *, plane=None, native=True, **options):
        plane = plane or self.plane
        trigger, key = RINGS[table]
        kwargs = dict(key=key, where=self.participation(), **options)
        if native:
            kwargs['_retention'] = plane._native_audit_retention
        return audit_ring(plane.db, table, trigger, **kwargs)

    def delete_arguments(self, table='transitions', plane=None):
        plane = plane or self.plane
        trigger, key = RINGS[table]
        return dict(key=key, where=self.participation(), cutoff=2, rowid=True,
                    guard=self.guard(table, plane), limit=4096)

    def assert_closed(self, plane=None):
        plane = plane or self.plane
        cap = plane._native_audit_retention
        self.assertIsNone(cap._permit)
        self.assertIsNone(cap._transaction)
        self.assertEqual(plane.db.execute('SELECT ' + FUNCTION + '(NULL,NULL)').fetchone()[0], 0)
        first = plane.db.execute('SELECT seq FROM transitions ORDER BY seq LIMIT 1').fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            plane.db.execute('DELETE FROM transitions WHERE seq=?', (first,))

    def test_direct_delete_never_gains_a_permit_from_an_owned_transaction(self):
        for table in RINGS:
            self.seed_ring(table, count=3)
            self.assertIn('IS NOT 1', self.guard(table))
            for inside in (False, True):
                with self.subTest(table=table, transaction=inside):
                    if inside:
                        with self.plane.transaction():
                            with self.assertRaises(sqlite3.IntegrityError):
                                self.plane.db.execute('DELETE FROM ' + table)
                    else:
                        with self.assertRaises(sqlite3.IntegrityError):
                            self.plane.db.execute('DELETE FROM ' + table)
                    assignment = 'kind=kind' if table == 'transitions' else 'body=body'
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.plane.db.execute('UPDATE ' + table + ' SET ' + assignment)
                    self.assertEqual(self.population(table), 3)
        self.assert_closed()

    def test_missing_function_and_non_one_or_null_returns_reject_direct_delete(self):
        self.seed_ring('transitions', count=3)
        with closing(sqlite3.connect(self.plane.path)) as foreign:
            with self.assertRaises(sqlite3.OperationalError):
                foreign.execute('DELETE FROM transitions')
        cap = self.plane._native_audit_retention
        try:
            for value in (None, 0, 2, -1, '1'):
                with self.subTest(result=value):
                    self.plane.db.create_function(FUNCTION, 2, lambda table, key, value=value: value)
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.plane.db.execute('DELETE FROM transitions')
                    self.assertEqual(self.population('transitions'), 3)
            self.plane.db.create_function(FUNCTION, 2, None)
            with self.assertRaises(sqlite3.OperationalError):
                self.plane.db.execute('DELETE FROM transitions')
        finally:
            self.plane.db.create_function(FUNCTION, 2, cap._predicate)
        self.assert_closed()

    def test_native_pruning_preserves_original_paused_and_null_participation(self):
        self.seed_ring('transitions')
        with self.plane.transaction():
            self.plane.db.execute('''INSERT INTO candidates(
                id,lane,generation,interpretation,latest_id,observed,ordering,desired,
                payload,state,pending,priority,rank,deadline,queued)
                VALUES('paused','ramses',1,'{}','old',100,'[0]','{}','{}','watching',0,4,0,105,100)''')
            self.plane.db.executemany('INSERT INTO transitions VALUES(?,?,?,?,?,?,?,?,?)', (
                (-2, 'paused', 1, self.now, 'watching', None, '{}', '{}', '{}'),
                (-1, None, 1, self.now, 'watching', None, '{}', '{}', '{}')))
        before = self.schema()
        with self.plane.transaction():
            self.prune('transitions')
        self.assertEqual(self.schema(), before)
        self.assertEqual(self.plane.db.execute("SELECT COUNT(*) FROM transitions WHERE candidate='active'").fetchone()[0], 4096)
        self.assertIsNotNone(self.plane.db.execute("SELECT 1 FROM transitions WHERE candidate='paused'").fetchone())
        self.assertIsNotNone(self.plane.db.execute('SELECT 1 FROM transitions WHERE candidate IS NULL').fetchone())
        self.seed_ring('observations')
        before = self.schema()
        with self.plane.transaction():
            self.prune('observations')
        self.assertEqual(self.schema(), before)
        self.assertEqual(self.population('observations'), 4096)
        self.assert_closed()

    def test_real_peer_enqueue_and_cross_thread_audit_keep_clean_evidence_tokens(self):
        path = self.root / 'native-broker.sqlite'
        broker = Broker(path, 'offline-guard-policy', clock=lambda: self.now)
        peer = Broker(path, 'offline-guard-policy', clock=lambda: self.now)
        self.addCleanup(broker.close)
        self.addCleanup(peer.close)
        broker.enqueue(event(1), needs_work=False)
        candidate = broker.identity(event(1))
        self.seed_ring('transitions', plane=broker.plane, candidate=candidate, count=4096)
        self.seed_ring('observations', plane=broker.plane, candidate=candidate, count=4096)
        self.seed_evidence(broker.plane)
        self.assertEqual(len(self.counted_maintain(broker.plane)), 1)
        before = self.evidence_state(broker.plane)
        schema = self.schema(broker.plane)
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertTrue(pool.submit(peer.enqueue, event(4097), needs_work=False).result(3))
        self.assertEqual(self.schema(broker.plane), schema)
        self.assertEqual(self.counted_maintain(broker.plane), [])
        self.assertEqual(self.schema(broker.plane), schema)
        self.assertEqual(self.evidence_state(broker.plane), before)
        self.assertEqual(self.population('transitions', broker.plane), 4096)
        self.assertEqual(self.population('observations', broker.plane), 4096)
        self.assert_closed(peer.plane)

    def test_original_default_storage_fallback_changes_schema_and_forces_recount(self):
        self.seed_ring('transitions')
        self.seed_evidence()
        self.assertEqual(len(self.counted_maintain()), 1)
        before = self.evidence_state()
        schema = self.schema()
        with self.plane.transaction():
            self.prune('transitions', native=False)
        self.assertGreater(self.schema(), schema)
        self.assertEqual(self.population('transitions'), 4096)
        self.assertEqual(len(self.counted_maintain()), 1)
        self.assertEqual(self.evidence_state(), before)
        self.assert_closed()

    def test_native_audit_and_foreign_evidence_trigger_cycle_cannot_share_credit(self):
        self.seed_ring('transitions', count=4096)
        self.seed_evidence()
        self.assertEqual(len(self.counted_maintain()), 1)

        def foreign():
            self.plane.db.execute('DROP TRIGGER evidence_retention_evidence_update')
            self.plane.db.execute("UPDATE evidence SET created=created+1 WHERE namespace='pons:guard-fixture'")
            self.plane.db.execute(_EVIDENCE_RETENTION_SCHEMA['evidence_retention_evidence_update'])

        for foreign_first in (False, True):
            with self.subTest(foreign_first=foreign_first):
                with self.plane.transaction():
                    if foreign_first:
                        foreign()
                    self.plane._audit(self.plane._row('active'), 'watching')
                    if not foreign_first:
                        foreign()
                self.assertEqual(len(self.counted_maintain()), 1)
                self.assertEqual(self.population('transitions'), 4096)

    def test_unobserved_schema_reset_cannot_replay_an_old_native_edge(self):
        self.seed_ring('transitions', count=4096)
        self.seed_evidence()
        with self.plane.transaction():
            self.plane.db.executemany('INSERT INTO evidence VALUES(?,?,?,?,?)',
                (('pons:guard-fixture', str(n), '{}', '{}', n) for n in range(4, 4096)))
        self.assertEqual(len(self.counted_maintain()), 1)
        before = self.schema()
        peer = self.open_plane('plane.sqlite')
        with peer.transaction():
            peer._audit(peer._row('active'), 'watching')
        # The rejected schema-edge design credited the +2 native edge here.
        # Stable native guards create no reusable global schema-version edge.
        with closing(sqlite3.connect(self.plane.path, isolation_level=None)) as raw:
            raw.execute('PRAGMA schema_version=' + str(before))
            raw.execute('DROP TRIGGER evidence_retention_evidence_insert')
            raw.execute("INSERT INTO evidence VALUES('pons:guard-fixture','overflow','{}','{}',99999)")
            raw.execute(_EVIDENCE_RETENTION_SCHEMA['evidence_retention_evidence_insert'])
        self.assertEqual(self.schema(), before + 2)
        self.assertEqual(len(self.counted_maintain()), 1)
        self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0], 4096)

    def test_known_legacy_and_mixed_guards_migrate_once_and_reopen_without_ddl(self):
        for index, tables in enumerate(((), ('transitions',), ('observations',), tuple(RINGS))):
            with self.subTest(legacy=tables):
                name = 'mixed-' + str(index) + '.sqlite'
                owner = self.open_plane(name)
                with self.schema_transaction(owner):
                    for table in tables:
                        owner.db.execute('DROP TRIGGER ' + RINGS[table][0])
                        owner.db.execute(legacy_guard(table))
                owner.close()
                migrated = self.open_plane(name)
                self.assertTrue(migrated._native_audit_retention._enabled)
                for table in RINGS:
                    self.assertIn(FUNCTION, self.guard(table, migrated))
                schema = self.schema(migrated)
                migrated.close()
                reopened = self.open_plane(name)
                self.assertEqual(self.schema(reopened), schema)
                self.assertTrue(reopened._native_audit_retention._enabled)

    def test_unknown_or_missing_guard_never_authorizes_partial_pair_migration(self):
        for index, unknown in enumerate((False, True)):
            with self.subTest(unknown=unknown):
                name = 'foreign-' + str(index) + '.sqlite'
                owner = self.open_plane(name)
                with self.schema_transaction(owner):
                    owner.db.execute('DROP TRIGGER history_no_delete')
                    owner.db.execute(legacy_guard('transitions'))
                    owner.db.execute('DROP TRIGGER observations_no_delete')
                    if unknown:
                        owner.db.execute("CREATE TRIGGER observations_no_delete BEFORE DELETE ON observations BEGIN SELECT RAISE(ABORT,'foreign_guard'); END")
                owner.close()
                reopened = self.open_plane(name)
                self.assertFalse(reopened._native_audit_retention._enabled)
                self.assertNotIn(FUNCTION, self.guard('transitions', reopened))
                if unknown:
                    self.assertIn('foreign_guard', self.guard('observations', reopened))

    def test_mid_migration_failure_rolls_back_both_guards_and_closes_failed_owner(self):
        name = 'migration-failure.sqlite'
        owner = self.open_plane(name)
        with self.schema_transaction(owner):
            for table in RINGS:
                owner.db.execute('DROP TRIGGER ' + RINGS[table][0])
                owner.db.execute(legacy_guard(table))
        expected = {table: self.guard(table, owner) for table in RINGS}
        owner.close()
        raw = sqlite3.connect(self.root / name, isolation_level=None, check_same_thread=False)

        class FailSecondGuard:
            def __init__(self):
                object.__setattr__(self, 'closed', False)
            def __getattr__(self, key):
                return getattr(raw, key)
            def __setattr__(self, key, value):
                setattr(raw, key, value)
            def execute(self, sql, *args):
                if sql.startswith('CREATE TRIGGER observations_no_delete') and FUNCTION in sql:
                    raise sqlite3.OperationalError('injected_second_guard_creation')
                return raw.execute(sql, *args)
            def close(self):
                object.__setattr__(self, 'closed', True)
                raw.close()

        failing = FailSecondGuard()
        try:
            with patch('meme_machine.runtime.operation_costs.connect', return_value=failing):
                with self.assertRaisesRegex(sqlite3.OperationalError, 'injected_second_guard_creation'):
                    Plane(self.root / name, clock=lambda: self.now)
            self.assertTrue(failing.closed)
        finally:
            if not failing.closed:
                raw.close()
        with closing(sqlite3.connect(self.root / name)) as reader:
            for table, sql in expected.items():
                self.assertEqual(reader.execute('SELECT sql FROM sqlite_master WHERE name=?',
                    (RINGS[table][0],)).fetchone()[0], sql)
        reopened = self.open_plane(name)
        self.assertTrue(reopened._native_audit_retention._enabled)
        for table in RINGS:
            self.assertIn(FUNCTION, self.guard(table, reopened))

    def test_baseexception_and_original_cancellation_reset_private_state(self):
        self.seed_ring('transitions')

        class Cancelled(BaseException):
            pass

        with self.assertRaises(Cancelled):
            with self.plane.transaction():
                self.prune('transitions')
                raise Cancelled()
        self.assertEqual(self.population('transitions'), 4097)
        self.assert_closed()
        with self.assertRaises(Shutdown):
            with self.plane.transaction():
                self.prune('transitions', startup_cancel=lambda: True)
        self.assertEqual(self.population('transitions'), 4097)
        self.assert_closed()

    def test_migration_commit_failure_never_publishes_half_a_guard_pair(self):
        name = 'migration-commit.sqlite'
        owner = self.open_plane(name)
        with self.schema_transaction(owner):
            for table in RINGS:
                owner.db.execute('DROP TRIGGER ' + RINGS[table][0])
                owner.db.execute(legacy_guard(table))
        expected = {table: self.guard(table, owner) for table in RINGS}
        owner.close()
        raw = sqlite3.connect(self.root / name, isolation_level=None)
        raw.set_authorizer(lambda action, a, b, c, d: sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_TRANSACTION and a == 'COMMIT' else sqlite3.SQLITE_OK)
        with patch('meme_machine.runtime.operation_costs.connect', return_value=raw):
            with self.assertRaises(sqlite3.DatabaseError):
                Plane(self.root / name, clock=lambda: self.now)
        with self.assertRaises(sqlite3.ProgrammingError):
            raw.execute('SELECT 1')
        with closing(sqlite3.connect(self.root / name)) as reader:
            self.assertEqual(expected, {table: reader.execute('SELECT sql FROM sqlite_master WHERE name=?',
                (RINGS[table][0],)).fetchone()[0] for table in RINGS})
        reopened = self.open_plane(name)
        self.assertTrue(reopened._native_audit_retention._enabled)

    def test_abrupt_child_exit_during_native_prune_cannot_persist_a_permit_or_delete(self):
        self.seed_ring('transitions')
        read_fd, write_fd = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(read_fd)
            try:
                own = Plane(self.plane.path, clock=lambda: self.now)
                with own.transaction():
                    self.prune('transitions', plane=own)
                    os.write(write_fd, b'pruned_before_commit')
                    os._exit(0)  # Deliberately skip every Python finally/close.
            except BaseException:
                os._exit(2)
        os.close(write_fd)
        reaped = False
        try:
            self.assertTrue(select.select([read_fd], [], [], 3)[0])
            self.assertEqual(os.read(read_fd, 128), b'pruned_before_commit')
            _, status = os.waitpid(child, 0)
            reaped = True
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        finally:
            os.close(read_fd)
            if not reaped:
                os.kill(child, signal.SIGKILL)
                os.waitpid(child, 0)
        self.assertEqual(self.population('transitions'), 4097)
        reopened = self.open_plane('plane.sqlite')
        self.assertEqual(self.population('transitions', reopened), 4097)
        self.assert_closed(reopened)
        with reopened.transaction():
            self.prune('transitions', plane=reopened)
        self.assertEqual(self.population('transitions', reopened), 4096)
        self.assert_closed(reopened)

    def test_actual_sqlite_commit_failure_resets_permit_and_rolls_back_deletion(self):
        self.seed_ring('transitions')
        calls = []

        def authorizer(action, first, second, database, source):
            if action == sqlite3.SQLITE_TRANSACTION:
                calls.append(first)
                if first == 'COMMIT':
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.plane.db.set_authorizer(authorizer)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                with self.plane.transaction():
                    self.prune('transitions')
        finally:
            self.plane.db.set_authorizer(None)
        self.assertIn('COMMIT', calls)
        self.assertIn('ROLLBACK', calls)
        self.assertEqual(self.population('transitions'), 4097)
        self.assert_closed()

    def test_actual_delete_failure_resets_permit_before_native_rollback_and_retry(self):
        self.seed_ring('transitions')
        cap = self.plane._native_audit_retention
        permitted = []
        def deny_delete(action, first, second, database, source):
            if action == sqlite3.SQLITE_DELETE and first == 'transitions':
                permitted.append(cap._permit is not None)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.plane.db.set_authorizer(deny_delete)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                with self.plane.transaction():
                    self.prune('transitions')
        finally:
            self.plane.db.set_authorizer(None)
        self.assertEqual(permitted, [True])
        self.assertEqual(self.population('transitions'), 4097)
        self.assert_closed()
        with self.plane.transaction():
            self.prune('transitions')
        self.assertEqual(self.population('transitions'), 4096)
        self.assert_closed()

    def test_reentrant_delete_cannot_reuse_the_original_prune_permit(self):
        self.seed_ring('transitions')
        cap = self.plane._native_audit_retention
        arguments = self.delete_arguments()
        outcomes = []

        def authorizer(action, first, second, database, source):
            if action == sqlite3.SQLITE_DELETE and first == 'transitions':
                try:
                    cap.delete(self.plane.db, 'transitions', 'history_no_delete', **arguments)
                except ValueError as error:
                    outcomes.append(str(error))
                else:
                    outcomes.append('REENTRANT_DELETE_NOT_REFUSED')
            return sqlite3.SQLITE_OK

        self.plane.db.set_authorizer(authorizer)
        try:
            with self.plane.transaction():
                self.prune('transitions')
        finally:
            self.plane.db.set_authorizer(None)
        self.assertEqual(outcomes, ['native_audit_reentrant_delete'])
        self.assertEqual(self.population('transitions'), 4096)
        self.assert_closed()

        with self.plane.transaction():
            self.plane._audit(self.plane._row('active'), 'watching')
        self.assertEqual(self.population('transitions'), 4096)
        self.assert_closed()

    def test_foreign_transaction_has_no_capability_and_default_fallback_still_works(self):
        self.seed_ring('transitions')
        cap = self.plane._native_audit_retention
        with self.plane.lock:
            self.plane.db.execute('BEGIN IMMEDIATE')
            try:
                self.assertFalse(cap.delete(self.plane.db, 'transitions', 'history_no_delete',
                    **self.delete_arguments()))
                self.assertEqual(self.population('transitions'), 4097)
            finally:
                self.plane.db.execute('ROLLBACK')
        schema = self.schema()
        self.prune('transitions')
        self.assertEqual(self.population('transitions'), 4096)
        self.assertGreater(self.schema(), schema)
        self.assert_closed()

    def test_wrong_connection_shape_and_unowned_thread_never_acquire_permit(self):
        self.seed_ring('transitions')
        cap = self.plane._native_audit_retention
        with closing(sqlite3.connect(':memory:', isolation_level=None)) as other:
            other.execute('BEGIN')
            with self.plane.transaction():
                with self.assertRaises(ValueError):
                    cap.delete(other, 'transitions', 'history_no_delete', **self.delete_arguments())
                for key, value in (('key', 'rowid'), ('where', '1=1'), ('rowid', False),
                        ('limit', 4095), ('cutoff', True)):
                    args = dict(self.delete_arguments(), **{key: value})
                    with self.subTest(field=key), self.assertRaises(ValueError):
                        cap.delete(self.plane.db, 'transitions', 'history_no_delete', **args)
            other.execute('ROLLBACK')
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaises(ValueError):
                pool.submit(cap.delete, self.plane.db, 'transitions', 'history_no_delete',
                            **self.delete_arguments()).result(2)
        self.assertEqual(self.population('transitions'), 4097)
        self.assert_closed()

    def test_forked_process_rejects_capability_before_inherited_sqlite_access(self):
        self.seed_ring('transitions')
        cap = self.plane._native_audit_retention
        arguments = self.delete_arguments()
        read_fd, write_fd = os.pipe()
        child = None
        reaped = False
        try:
            with self.plane.transaction():
                child = os.fork()
                if child == 0:
                    os.close(read_fd)
                    try:
                        cap.delete(self.plane.db, 'transitions', 'history_no_delete', **arguments)
                    except ValueError as error:
                        os.write(write_fd, str(error).encode())
                        os._exit(0)
                    except BaseException:
                        os._exit(2)
                    os._exit(3)
                os.close(write_fd)
                write_fd = None
                self.assertTrue(select.select([read_fd], [], [], 2)[0], 'child capability check timed out')
                self.assertEqual(os.read(read_fd, 128), b'native_audit_delete_owner')
                _, status = os.waitpid(child, 0)
                reaped = True
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        finally:
            if child and not reaped:
                os.kill(child, signal.SIGKILL)
                os.waitpid(child, 0)
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
        self.assertEqual(self.population('transitions'), 4097)
        self.assert_closed()

    def test_replaced_or_removed_udf_disables_cap_and_preserves_native_fallback(self):
        for index, missing in enumerate((False, True)):
            with self.subTest(missing=missing):
                owner = self.open_plane('replacement-' + str(index) + '.sqlite')
                self.seed_ring('transitions', plane=owner)
                schema = self.schema(owner)
                owner.db.create_function(FUNCTION, 2, None if missing else lambda table, key: None)
                with owner.transaction():
                    self.prune('transitions', plane=owner)
                self.assertFalse(owner._native_audit_retention._enabled)
                self.assertEqual(self.population('transitions', owner), 4096)
                self.assertGreater(self.schema(owner), schema)
                self.assertIsNone(owner._native_audit_retention._permit)

    def test_closed_owner_and_unknown_extra_trigger_cannot_use_native_permit(self):
        self.seed_ring('transitions')
        schema = self.schema()
        self.plane.db.execute("CREATE TRIGGER foreign_audit_guard BEFORE DELETE ON transitions WHEN 0 BEGIN SELECT RAISE(ABORT,'foreign'); END")
        with self.plane.transaction():
            self.prune('transitions')
        self.assertEqual(self.population('transitions'), 4096)
        self.assertGreater(self.schema(), schema + 1)
        self.assertIsNotNone(self.plane.db.execute("SELECT 1 FROM sqlite_master WHERE name='foreign_audit_guard'").fetchone())
        cap = self.plane._native_audit_retention
        arguments = self.delete_arguments()
        self.plane.close()
        with self.assertRaises(ValueError):
            cap.delete(self.plane.db, 'transitions', 'history_no_delete', **arguments)
        self.assertIsNone(cap._permit)
        self.assertIsNone(cap._transaction)

    def test_preopened_connection_without_udf_keeps_original_serialized_pruning(self):
        path = self.root / 'old-connection.sqlite'
        with closing(sqlite3.connect(path, isolation_level=None)) as old:
            owner = self.open_plane(path.name)
            self.seed_ring('transitions', plane=owner)
            self.seed_evidence(owner)
            self.counted_maintain(owner)
            before = self.schema(owner)
            with self.assertRaises(sqlite3.OperationalError):
                old.execute('DELETE FROM transitions')
            audit_ring(old, 'transitions', 'history_no_delete', where=self.participation())
            self.assertGreater(self.schema(owner), before)
            self.assertEqual(self.population('transitions', owner), 4096)
            self.assertEqual(len(self.counted_maintain(owner)), 1)
            self.assertIn(FUNCTION, self.guard('transitions', owner))
            self.assert_closed(owner)

    def test_oversized_guard_or_extra_trigger_metadata_stays_closed(self):
        name = 'large-guard.sqlite'
        owner = self.open_plane(name)
        with self.schema_transaction(owner):
            owner.db.execute('DROP TRIGGER observations_no_delete')
            owner.db.execute('CREATE TRIGGER observations_no_delete BEFORE DELETE ON observations '
                '/*' + 'x' * 4096 + "*/ BEGIN SELECT RAISE(ABORT,'append_only'); END")
        owner.close()
        reopened = self.open_plane(name)
        self.assertFalse(reopened._native_audit_retention._enabled)
        self.assertEqual(reopened.db.execute("SELECT octet_length(sql) FROM sqlite_master WHERE name='observations_no_delete'").fetchone()[0],
                         len(self.guard('observations', reopened).encode()))
        self.seed_ring('transitions')
        self.plane.db.execute('CREATE TRIGGER huge_extra_guard BEFORE DELETE ON transitions '
            '/*' + 'y' * 4096 + "*/ WHEN 0 BEGIN SELECT RAISE(ABORT,'foreign'); END")
        before = self.schema()
        with self.plane.transaction():
            self.prune('transitions')
        self.assertGreater(self.schema(), before)
        self.assertEqual(self.population('transitions'), 4096)
        self.assert_closed()


if __name__ == '__main__':
    unittest.main()
