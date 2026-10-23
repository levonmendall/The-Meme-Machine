"""Real SQLite scheduling fixtures; no market, provider or financial authority."""
from contextlib import contextmanager
import hashlib
import sqlite3
from types import SimpleNamespace
import unittest

from meme_machine.solana_acquisition_scheduler import (
    AcquisitionScheduler, DEFERRED, FANOUT, IDLE, JOB_FIELDS, QUEUE, SIGNALS,
    STATE, URGENT_STATE)
from meme_machine.solana_evidence_plane import EvidenceUnavailable


JOBS = '''CREATE TABLE acquisition_jobs(
    id TEXT PRIMARY KEY,family TEXT NOT NULL,address TEXT NOT NULL,
    lo INTEGER NOT NULL,hi INTEGER NOT NULL,priority INTEGER NOT NULL,deadline REAL NOT NULL,
    status TEXT NOT NULL,token TEXT,pages INTEGER NOT NULL,last_slot INTEGER,last_index INTEGER,
    lineage TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,error TEXT)'''


class SQLiteOwner:
    """An actual transaction/savepoint boundary without unrelated runtime setup."""
    def __init__(self, db):
        self.db = db
        self.sequence = 0
        self.after_commit = None

    @contextmanager
    def transaction(self):
        nested = self.db.in_transaction
        self.sequence += 1
        savepoint = 'test_owner_'+str(self.sequence)
        self.db.execute('SAVEPOINT '+savepoint if nested else 'BEGIN IMMEDIATE')
        try:
            yield
        except BaseException:
            if nested:
                self.db.execute('ROLLBACK TO '+savepoint)
                self.db.execute('RELEASE '+savepoint)
            else:
                self.db.execute('ROLLBACK')
            raise
        else:
            self.db.execute('RELEASE '+savepoint if nested else 'COMMIT')
            if not nested and self.after_commit is not None:
                self.after_commit()


class AcquisitionSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.execute(JOBS)
        self.writer = SQLiteOwner(self.db)
        self.now = 100.0
        self.serial = 0
        self.history = SimpleNamespace(db=self.db, writer=self.writer,
            clock=lambda: self.now, active_families=('pump', 'pumpswap', 'meteora'))

    def install(self):
        self.scheduler = AcquisitionScheduler(self.history)
        return self.scheduler

    def add_job(self, *, priority=3, deadline=1000.0, family='pump',
                created=10.0, status='pending', identity=None, address=None,
                lo=0, hi=10):
        self.serial += 1
        identity = identity or hashlib.sha256(('job-'+str(self.serial)).encode()).hexdigest()
        self.db.execute('INSERT INTO acquisition_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity, family, address or 'address-'+str(self.serial), lo, hi, priority, deadline,
             status, None, 0, None, None, '0'*64, created, created, None))
        return identity

    def source(self, identity):
        row = self.db.execute('SELECT '+','.join(JOB_FIELDS)+
                              ' FROM acquisition_jobs WHERE id=?', (identity,)).fetchone()
        return dict(zip(JOB_FIELDS, row))

    def take(self, *, urgent=False, excluding=(), maximum=100):
        for _ in range(maximum):
            result = self.scheduler.next(urgent=urgent, excluding=excluding)
            if result != DEFERRED:
                return result
        self.fail('bounded scheduler made no progress')

    def finish(self, job):
        self.db.execute("UPDATE acquisition_jobs SET status='complete' WHERE id=?", (job['id'],))

    def count_is_exact(self):
        expected = self.db.execute(
            "SELECT COUNT(*) FROM acquisition_jobs WHERE status='pending'").fetchone()[0]
        self.assertEqual(self.scheduler.pending_count(), expected)
        return expected

    def defer_rank_two_population(self, count=40):
        identities = [self.add_job(priority=2, deadline=1000+i) for i in range(count)]
        for _ in identities:
            job = self.take(urgent=True)
            self.assertIsInstance(job, dict)
            self.assertTrue(self.scheduler.defer(job, 200.0))
        self.assertEqual(self.scheduler.next(urgent=True), IDLE)
        return identities

    def test_clock_replacement_after_install_controls_fresh_eligibility(self):
        self.install()
        self.add_job(priority=0, deadline=150.0)
        self.history.clock = lambda: 200.0
        self.assertEqual(self.scheduler.next(), IDLE)
        self.assertEqual(self.scheduler.pending_count(), 1)

    def test_expiry_during_scheduling_commit_never_returns_expired_job(self):
        self.add_job(priority=0, deadline=150.0)
        self.install()
        self.writer.after_commit = lambda: setattr(self, 'now', 200.0)
        result = self.scheduler.next(urgent=True)
        self.assertIn(result, (IDLE, DEFERRED))
        self.assertEqual(self.scheduler.pending_count(), 1)

    def test_global_sort_matches_original_rank_deadline_priority_created_and_id(self):
        self.install()
        identities = []
        for number in range(42):
            identities.append(self.add_job(priority=number % 7,
                deadline=500+(number % 4), created=10+(number % 3),
                family=('pump', 'pumpswap', 'meteora')[number % 3]))
        original = [self.source(identity) for identity in identities]
        expected = sorted(original, key=lambda job: (
            min(job['priority'], 3), job['deadline'], job['priority'], job['created'], job['id']))
        received = []
        for expected_job in expected:
            job = self.take()
            self.assertIsInstance(job, dict)
            self.assertEqual({key: job[key] for key in JOB_FIELDS}, expected_job)
            received.append(job['id'])
            self.finish(job)
        self.assertEqual(received, [job['id'] for job in expected])
        self.assertEqual(self.take(), IDLE)
        self.assertEqual(self.count_is_exact(), 0)

    def test_urgent_order_is_proved_before_optional_backfill_finishes(self):
        for number in range(80):
            self.add_job(priority=3, deadline=700+number)
        urgent = [self.add_job(priority=2, deadline=200+number,
            family=('pump', 'pumpswap')[number % 2]) for number in range(40)]
        self.install()
        first = self.scheduler.next(urgent=True)
        self.assertEqual(first['id'], urgent[0])
        self.assertEqual(self.db.execute(
            f'SELECT after_id,complete FROM {STATE}').fetchone(), ('', 0))
        self.assertTrue(self.scheduler.defer(first, 150.0))
        second = self.scheduler.next(urgent=True)
        self.assertEqual(second['id'], urgent[1])
        self.assertNotEqual(second['id'], first['id'])

        newly_urgent = self.add_job(priority=0, deadline=160.0)
        fresh = self.scheduler.next(urgent=True)
        self.assertEqual(fresh['id'], newly_urgent)
        self.finish(fresh)
        self.db.execute('UPDATE acquisition_jobs SET priority=1,deadline=140 WHERE id=?',
                        (first['id'],))
        tightened = self.scheduler.next(urgent=True)
        self.assertEqual(tightened['id'], first['id'])
        self.assertGreater(tightened['_scheduler_version'], first['_scheduler_version'])
        self.assertFalse(self.scheduler.defer(first, 130.0))
        self.assertEqual(self.source(first['id'])['deadline'], 140.0)

    def test_more_than_sixteen_rank_two_due_retries_do_not_block_new_rank_zero(self):
        self.install()
        self.defer_rank_two_population(40)
        self.now = 200.0
        urgent = self.add_job(priority=0, deadline=900.0)
        selected = self.scheduler.next(urgent=True)
        self.assertEqual(selected['id'], urgent)
        # Rank-two bookkeeping was not needed to prove the rank-zero head.
        blocked = self.db.execute(f'SELECT COUNT(*) FROM {QUEUE} WHERE rank=2 AND ready=0').fetchone()[0]
        self.assertEqual(blocked, 40)

    def test_same_rank_proved_earlier_head_can_precede_remaining_due_retry_prefix(self):
        self.install()
        identities = self.defer_rank_two_population(40)
        self.now = 200.0
        earlier = self.add_job(priority=2, deadline=500.0)
        selected = self.scheduler.next(urgent=True)
        self.assertEqual(selected['id'], earlier)
        blocked = self.db.execute(f'SELECT COUNT(*) FROM {QUEUE} WHERE rank=2 AND ready=0').fetchone()[0]
        self.assertEqual(blocked, 24)
        self.finish(selected)
        selected = self.take(urgent=True)
        self.assertEqual(selected['id'], identities[0])

    def test_counter_covers_inactive_families_and_rollback_and_status_aba(self):
        self.history.active_families = ('pump',)
        self.install()
        active = self.add_job(priority=1)
        inactive = self.add_job(priority=0, family='meteora')
        self.add_job(status='failed')
        original = self.scheduler.next(urgent=True)
        self.assertEqual(original['id'], active)
        self.assertEqual(self.count_is_exact(), 2)
        with self.assertRaisesRegex(RuntimeError, 'rollback fixture'):
            with self.writer.transaction():
                self.add_job(priority=0)
                self.db.execute("UPDATE acquisition_jobs SET status='complete' WHERE id=?", (active,))
                self.db.execute('DELETE FROM acquisition_jobs WHERE id=?', (inactive,))
                self.assertEqual(self.count_is_exact(), 1)
                raise RuntimeError('rollback fixture')
        self.assertEqual(self.count_is_exact(), 2)
        self.db.execute('UPDATE acquisition_jobs SET priority=1 WHERE id=?', (active,))
        self.assertEqual(self.count_is_exact(), 2)
        self.db.execute("UPDATE acquisition_jobs SET status='complete' WHERE id=?", (active,))
        self.assertEqual(self.count_is_exact(), 1)
        self.assertIsNone(self.db.execute(f'SELECT version FROM {QUEUE} WHERE id=?', (active,)).fetchone())
        self.db.execute("UPDATE acquisition_jobs SET status='pending' WHERE id=?", (active,))
        self.assertEqual(self.count_is_exact(), 2)
        refreshed = self.scheduler.next(urgent=True)
        self.assertEqual(refreshed['id'], active)
        self.assertGreater(refreshed['_scheduler_version'], original['_scheduler_version'])
        self.assertFalse(self.scheduler.defer(original, 200.0))
        self.db.execute('DELETE FROM acquisition_jobs WHERE id=?', (inactive,))
        self.assertEqual(self.count_is_exact(), 1)

    def test_backfill_cursor_and_retry_survive_restart_without_recount_or_global_reset(self):
        for number in range(40):
            self.add_job(priority=3, deadline=700+number)
        urgent = [self.add_job(priority=2, deadline=200+number) for number in range(40)]
        self.install()
        progress = self.scheduler.backfill()
        self.assertEqual(progress, dict(complete=False, processed=16))
        first = self.scheduler.next(urgent=True)
        self.assertEqual(first['id'], urgent[0])
        self.assertTrue(self.scheduler.defer(first, 150.0))
        state = self.db.execute(f'SELECT * FROM {STATE}').fetchall()
        cursor = self.db.execute(f'SELECT * FROM {URGENT_STATE} ORDER BY family,priority').fetchall()
        queue = self.db.execute(f'SELECT ready,retry_at,version FROM {QUEUE} WHERE id=?',
                                (first['id'],)).fetchone()
        statements = []
        self.db.set_trace_callback(statements.append)
        try:
            self.scheduler = AcquisitionScheduler(self.history)
        finally:
            self.db.set_trace_callback(None)
        self.assertFalse(any('SELECT COUNT(*) FROM ACQUISITION_JOBS' in statement.upper()
                             for statement in statements))
        self.assertEqual(self.db.execute(f'SELECT * FROM {STATE}').fetchall(), state)
        self.assertEqual(self.db.execute(f'SELECT * FROM {URGENT_STATE} ORDER BY family,priority').fetchall(), cursor)
        self.assertEqual(self.db.execute(f'SELECT ready,retry_at,version FROM {QUEUE} WHERE id=?',
                                        (first['id'],)).fetchone(), queue)
        self.assertEqual(self.scheduler.next(urgent=True)['id'], urgent[1])
        self.now = 151.0
        self.assertEqual(self.scheduler.next(urgent=True)['id'], urgent[0])

    def test_outer_rollback_does_not_advance_backfill_or_urgent_seed_cursors(self):
        for number in range(40):
            self.add_job(priority=2, deadline=200+number)
        self.install()
        before = self.db.execute(f'SELECT * FROM {STATE}').fetchall()
        urgent_before = self.db.execute(f'SELECT * FROM {URGENT_STATE} ORDER BY family,priority').fetchall()
        with self.assertRaisesRegex(RuntimeError, 'rollback fixture'):
            with self.writer.transaction():
                self.scheduler.backfill()
                self.assertIsInstance(self.scheduler.next(urgent=True), dict)
                raise RuntimeError('rollback fixture')
        self.assertEqual(self.db.execute(f'SELECT * FROM {STATE}').fetchall(), before)
        self.assertEqual(self.db.execute(f'SELECT * FROM {URGENT_STATE} ORDER BY family,priority').fetchall(), urgent_before)
        self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {QUEUE}').fetchone()[0], 0)
        self.assertEqual(self.count_is_exact(), 40)

    def test_replaced_trigger_is_refused_on_restart(self):
        self.install()
        identity = self.add_job()
        source = self.source(identity)
        self.db.execute('DROP TRIGGER acquisition_schedule_update_v1')
        self.db.execute('''CREATE TRIGGER acquisition_schedule_update_v1
            AFTER UPDATE ON acquisition_jobs BEGIN SELECT 1; END''')
        with self.assertRaisesRegex(EvidenceUnavailable, 'acquisition_schedule_schema_mismatch'):
            AcquisitionScheduler(self.history)
        self.assertEqual(self.source(identity), source)
        self.assertEqual(self.count_is_exact(), 1)

    def test_replaced_dispatch_index_is_refused_on_restart(self):
        self.install()
        self.add_job()
        self.db.execute('DROP INDEX acquisition_schedule_head_v1')
        self.db.execute(f'CREATE INDEX acquisition_schedule_head_v1 ON {QUEUE}(id)')
        with self.assertRaisesRegex(EvidenceUnavailable, 'acquisition_schedule_schema_mismatch'):
            AcquisitionScheduler(self.history)
        self.assertEqual(self.count_is_exact(), 1)

    def test_stale_queue_head_fails_closed_instead_of_filtering_an_unbounded_prefix(self):
        self.install()
        identity = self.add_job(priority=3, deadline=500.0)
        self.add_job(priority=3, deadline=600.0)
        self.db.execute(f'UPDATE {QUEUE} SET deadline=400 WHERE id=?', (identity,))
        with self.assertRaisesRegex(EvidenceUnavailable, 'acquisition_schedule_projection_mismatch'):
            self.scheduler.next()
        self.assertEqual(self.source(identity)['deadline'], 500.0)
        self.assertEqual(self.count_is_exact(), 2)

    def test_exclusions_are_bounded_and_do_not_change_durable_readiness(self):
        self.install()
        identities = [self.add_job(priority=0, deadline=500.0, created=10.0) for _ in range(10)]
        ordered = sorted(identities)
        selected = self.scheduler.next(urgent=True, excluding=tuple(ordered[:8]))
        self.assertEqual(selected['id'], ordered[8])
        before = self.db.execute(f'SELECT * FROM {STATE}').fetchall()
        with self.assertRaisesRegex(EvidenceUnavailable, 'acquisition_schedule_exclusions'):
            self.scheduler.next(excluding=tuple(ordered[:9]))
        self.assertEqual(self.db.execute(f'SELECT * FROM {STATE}').fetchall(), before)
        self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {QUEUE} WHERE ready=0').fetchone()[0], 0)

    def test_fanout_child_cursor_and_wait_roll_back_atomically_and_survive_restart(self):
        self.install()
        identity = self.add_job(address='fanout-parent')
        parent = self.take()
        self.assertEqual(parent['id'], identity)
        original = self.source(identity)
        queue_before = self.db.execute(f'SELECT * FROM {QUEUE} WHERE id=?',
                                       (identity,)).fetchone()
        child = None
        with self.assertRaisesRegex(RuntimeError, 'rollback fanout'):
            with self.writer.transaction():
                child = self.add_job(address=parent['address'], lo=0, hi=4)
                self.scheduler.fanout_advance(parent, 4)
                self.assertEqual(self.scheduler.fanout_after(parent), 4)
                self.scheduler.fanout_wait(parent)
                self.assertEqual(self.db.execute(
                    f'SELECT after_slot,waiting FROM {FANOUT} WHERE job_id=?',
                    (identity,)).fetchone(), (None, 1))
                self.assertEqual(self.db.execute(
                    f'SELECT ready,retry_at FROM {QUEUE} WHERE id=?',
                    (identity,)).fetchone(), (0, parent['deadline']))
                raise RuntimeError('rollback fanout')
        self.assertIsNone(self.db.execute('SELECT id FROM acquisition_jobs WHERE id=?',
                                         (child,)).fetchone())
        self.assertIsNone(self.db.execute(f'SELECT job_id FROM {FANOUT} WHERE job_id=?',
                                         (identity,)).fetchone())
        self.assertEqual(self.db.execute(f'SELECT * FROM {QUEUE} WHERE id=?',
                                        (identity,)).fetchone(), queue_before)
        self.assertEqual(self.source(identity), original)

        with self.writer.transaction():
            child = self.add_job(address=parent['address'], lo=0, hi=4)
            self.scheduler.fanout_advance(parent, 4)
        self.scheduler = AcquisitionScheduler(self.history)
        self.assertEqual(self.scheduler.fanout_after(parent), 4)
        self.assertIsNotNone(self.db.execute('SELECT id FROM acquisition_jobs WHERE id=?',
                                            (child,)).fetchone())
        with self.writer.transaction():
            self.scheduler.fanout_wait(parent)
        wait_before = self.db.execute(f'SELECT * FROM {FANOUT} WHERE job_id=?',
                                      (identity,)).fetchone()
        queue_before = self.db.execute(f'SELECT * FROM {QUEUE} WHERE id=?',
                                       (identity,)).fetchone()
        self.scheduler = AcquisitionScheduler(self.history)
        self.assertEqual(self.db.execute(f'SELECT * FROM {FANOUT} WHERE job_id=?',
                                        (identity,)).fetchone(), wait_before)
        self.assertEqual(self.db.execute(f'SELECT * FROM {QUEUE} WHERE id=?',
                                        (identity,)).fetchone(), queue_before)
        self.assertEqual(self.source(identity), original)

    def test_fanout_wait_does_not_self_wake_after_many_point_one_second_turns(self):
        self.install()
        identity = self.add_job(address='fanout-clock')
        parent = self.take()
        self.scheduler.fanout_wait(parent)
        for _ in range(40):
            self.now += .11
            self.assertEqual(self.scheduler.next(), IDLE)
        self.assertEqual(self.db.execute(
            f'SELECT ready,retry_at FROM {QUEUE} WHERE id=?',
            (identity,)).fetchone(), (0, parent['deadline']))
        self.assertEqual(self.db.execute(
            f'SELECT waiting,after_slot FROM {FANOUT} WHERE job_id=?',
            (identity,)).fetchone(), (1, None))
        self.assertEqual(self.db.execute('SELECT status FROM acquisition_jobs WHERE id=?',
                                         (identity,)).fetchone()[0], 'pending')

    def test_only_committed_child_state_change_wakes_waiting_parent(self):
        self.install()
        identity = self.add_job(address='fanout-child', deadline=900.0)
        child = self.add_job(address='fanout-child', lo=0, hi=4)
        parent = self.take()
        self.assertEqual(parent['id'], identity)
        original = self.source(identity)
        self.scheduler.fanout_wait(parent)
        self.assertEqual(self.take(excluding=(child,)), IDLE)
        with self.assertRaisesRegex(RuntimeError, 'rollback child'):
            with self.writer.transaction():
                self.db.execute("UPDATE acquisition_jobs SET status='complete' WHERE id=?", (child,))
                self.scheduler.wake_fanout()
                self.assertEqual(self.db.execute(
                    f'SELECT ready FROM {QUEUE} WHERE id=?', (identity,)).fetchone(), (1,))
                raise RuntimeError('rollback child')
        self.assertEqual(self.db.execute(
            f'SELECT ready FROM {QUEUE} WHERE id=?', (identity,)).fetchone(), (0,))
        self.assertEqual(self.db.execute(
            f'SELECT waiting FROM {FANOUT} WHERE job_id=?', (identity,)).fetchone(), (1,))
        self.db.execute("UPDATE acquisition_jobs SET status='complete' WHERE id=?", (child,))
        self.assertEqual(self.take()['id'], identity)
        self.assertEqual(self.db.execute(
            f'SELECT waiting,after_slot FROM {FANOUT} WHERE job_id=?',
            (identity,)).fetchone(), (0, None))
        self.assertEqual(self.source(identity), original)

    def test_hot_child_signals_do_not_reset_more_than_sixteen_waiting_parents(self):
        self.install()
        address = 'fanout-many'
        identities = [self.add_job(address=address, deadline=800.0+number)
                      for number in range(40)]
        child = self.add_job(address=address, deadline=1500.0, lo=0, hi=4)
        for identity in identities:
            parent = self.take()
            self.assertEqual(parent['id'], identity)
            self.scheduler.fanout_wait(parent)
        for _ in range(4):
            self.scheduler.wake_fanout()
        self.assertEqual(self.db.execute(
            f'SELECT COUNT(*) FROM {FANOUT} WHERE waiting=1').fetchone()[0], 40)
        self.db.execute("UPDATE acquisition_jobs SET status='complete' WHERE id=?", (child,))
        self.scheduler.wake_fanout()
        self.assertEqual(self.db.execute(
            f'SELECT COUNT(*) FROM {FANOUT} WHERE waiting=1').fetchone()[0], 24)
        scan = self.db.execute(
            f'SELECT scan_revision,after_parent FROM {SIGNALS} WHERE family=? AND scope=?',
            ('pump', 'candidate:pump:'+address)).fetchone()
        self.assertGreaterEqual(scan[0], 0)
        self.assertEqual(scan[1], sorted(identities)[15])

        # Ongoing changes to this child's durable progress increase revision,
        # but must not restart the current bounded parent-keyset pass.
        self.db.execute('UPDATE acquisition_jobs SET last_slot=1 WHERE id=?', (child,))
        self.assertEqual(self.db.execute(
            f'SELECT scan_revision,after_parent FROM {SIGNALS} WHERE family=? AND scope=?',
            ('pump', 'candidate:pump:'+address)).fetchone(), scan)
        self.scheduler.wake_fanout()
        self.assertEqual(self.db.execute(
            f'SELECT COUNT(*) FROM {FANOUT} WHERE waiting=1').fetchone()[0], 8)
        next_scan = self.db.execute(
            f'SELECT scan_revision,after_parent FROM {SIGNALS} WHERE family=? AND scope=?',
            ('pump', 'candidate:pump:'+address)).fetchone()
        self.assertEqual(next_scan, (scan[0], sorted(identities)[31]))
        self.db.execute('UPDATE acquisition_jobs SET last_slot=2 WHERE id=?', (child,))
        self.scheduler.wake_fanout()
        self.assertEqual(self.db.execute(
            f'SELECT COUNT(*) FROM {FANOUT} WHERE waiting=1').fetchone()[0], 0)
        self.assertEqual(self.db.execute(
            f'SELECT COUNT(*) FROM {QUEUE} WHERE ready=1').fetchone()[0], 40)
        self.assertEqual(self.count_is_exact(), 40)

    def test_unrelated_candidate_change_does_not_wake_fanout_parent(self):
        self.install()
        identity = self.add_job(address='fanout-unchanged', deadline=900.0)
        other = self.add_job(address='fanout-unrelated')
        parent = self.take()
        self.assertEqual(parent['id'], identity)
        self.scheduler.fanout_wait(parent)
        self.db.execute("UPDATE acquisition_jobs SET status='complete' WHERE id=?", (other,))
        for _ in range(8):
            self.now += .11
            self.assertEqual(self.scheduler.next(), IDLE)
        self.assertEqual(self.db.execute(
            f'SELECT ready FROM {QUEUE} WHERE id=?', (identity,)).fetchone(), (0,))
        self.assertEqual(self.db.execute(
            f'SELECT waiting FROM {FANOUT} WHERE job_id=?', (identity,)).fetchone(), (1,))

    def test_changed_parent_version_discards_previous_fanout_cursor(self):
        self.install()
        identity = self.add_job(address='fanout-new-version')
        original = self.take()
        self.scheduler.fanout_advance(original, 4)
        self.assertEqual(self.scheduler.fanout_after(original), 4)
        self.db.execute('UPDATE acquisition_jobs SET deadline=800 WHERE id=?', (identity,))
        current = self.take()
        self.assertEqual(current['id'], identity)
        self.assertGreater(current['_scheduler_version'], original['_scheduler_version'])
        self.assertIsNone(self.scheduler.fanout_after(current))
        self.assertEqual(self.db.execute(
            f'SELECT job_version,after_slot,waiting FROM {FANOUT} WHERE job_id=?',
            (identity,)).fetchone(), (current['_scheduler_version'], None, 0))
        self.assertFalse(self.scheduler.defer(original, 300.0))
        self.assertEqual(self.source(identity)['deadline'], 800.0)
        self.scheduler.fanout_advance(current, 6)
        before = self.db.execute(f'SELECT * FROM {FANOUT} WHERE job_id=?',
                                 (identity,)).fetchone()
        for operation in (lambda: self.scheduler.fanout_after(original),
                          lambda: self.scheduler.fanout_advance(original, 7),
                          lambda: self.scheduler.fanout_wait(original)):
            with self.assertRaisesRegex(EvidenceUnavailable, 'acquisition_schedule_fanout_stale'):
                operation()
            self.assertEqual(self.db.execute(f'SELECT * FROM {FANOUT} WHERE job_id=?',
                                            (identity,)).fetchone(), before)

    def binding_table(self, bindings):
        self.db.execute('''CREATE TABLE evidence_bindings(
            family TEXT NOT NULL,address TEXT NOT NULL,coverage_scope TEXT NOT NULL,
            PRIMARY KEY(family,address))''')
        self.db.executemany('INSERT INTO evidence_bindings VALUES(?,?,?)', bindings)

    def test_alias_child_durable_change_wakes_same_authenticated_scope_parent(self):
        scope = 'candidate:pump:shared-market'
        self.binding_table([('pump', 'parent-alias', scope),
                            ('pump', 'child-alias', scope)])
        self.install()
        identity = self.add_job(address='parent-alias', deadline=900.0)
        child = self.add_job(address='child-alias', lo=0, hi=4)
        parent = self.take()
        self.assertEqual(parent['id'], identity)
        original = self.source(identity)
        self.scheduler.fanout_wait(parent)
        self.assertEqual(self.db.execute(
            f'SELECT scope,waiting FROM {FANOUT} WHERE job_id=?',
            (identity,)).fetchone(), (scope, 1))
        self.assertEqual(self.take(excluding=(child,)), IDLE)
        self.db.execute("UPDATE acquisition_jobs SET status='complete' WHERE id=?", (child,))
        self.assertEqual(self.take()['id'], identity)
        self.assertEqual(self.source(identity), original)

    def test_rebinding_signals_both_old_and_new_scope_waiting_parents(self):
        old_scope = 'candidate:pump:old-market'
        new_scope = 'candidate:pump:new-market'
        self.binding_table([('pump', 'old-parent', old_scope),
                            ('pump', 'new-parent', new_scope),
                            ('pump', 'moving-child', old_scope)])
        self.install()
        old_parent = self.add_job(address='old-parent', deadline=800.0)
        new_parent = self.add_job(address='new-parent', deadline=801.0)
        child = self.add_job(address='moving-child')
        for identity in (old_parent, new_parent):
            parent = self.take()
            self.assertEqual(parent['id'], identity)
            self.scheduler.fanout_wait(parent)
        original = {identity: self.source(identity) for identity in (old_parent, new_parent, child)}
        for _ in range(4):
            self.scheduler.wake_fanout()
        self.assertEqual(self.db.execute(
            f'SELECT COUNT(*) FROM {FANOUT} WHERE waiting=1').fetchone()[0], 2)
        self.db.execute('UPDATE evidence_bindings SET coverage_scope=? WHERE family=? AND address=?',
                        (new_scope, 'pump', 'moving-child'))
        for _ in range(8):
            self.scheduler.wake_fanout()
        self.assertEqual(self.db.execute(
            f'SELECT job_id,waiting FROM {FANOUT} ORDER BY job_id').fetchall(),
            [(identity, 0) for identity in sorted((old_parent, new_parent))])
        self.assertEqual({identity: self.source(identity) for identity in original}, original)

    def test_new_binding_wakes_parent_waiting_on_original_unbound_fallback(self):
        scope = 'candidate:pump:bound-market'
        self.binding_table([])
        self.install()
        identity = self.add_job(address='initially-unbound')
        parent = self.take()
        self.scheduler.fanout_wait(parent)
        original = self.source(identity)
        self.assertEqual(self.db.execute(
            f'SELECT scope,waiting FROM {FANOUT} WHERE job_id=?',
            (identity,)).fetchone(), ('candidate:pump:initially-unbound', 1))
        for _ in range(4):
            self.scheduler.wake_fanout()
        self.db.execute('INSERT INTO evidence_bindings VALUES(?,?,?)',
                        ('pump', 'initially-unbound', scope))
        for _ in range(8):
            self.scheduler.wake_fanout()
        self.assertEqual(self.db.execute(
            f'SELECT ready FROM {QUEUE} WHERE id=?', (identity,)).fetchone(), (1,))
        self.assertEqual(self.scheduler.next()['id'], identity)
        self.assertIsNone(self.scheduler.fanout_after(parent))
        self.assertEqual(self.db.execute(
            f'SELECT scope,waiting,after_slot FROM {FANOUT} WHERE job_id=?',
            (identity,)).fetchone(), (scope, 0, None))
        self.assertEqual(self.source(identity), original)


if __name__ == '__main__':
    unittest.main()
