"""Real canonical SQLite quanta; no provider, market or financial authority."""
from collections import Counter
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.solana_acquisition_scheduler import (
    FANOUT, QUEUE, SIGNALS, STATE, URGENT_COUNT, URGENT_STATE)
from meme_machine.solana_candidate_development import CandidateDevelopment, DISPATCH, DEFERRED
from meme_machine.solana_candidate_lifecycle import SCHEMA as LIFECYCLE_SCHEMA
from meme_machine.solana_evidence_plane import EvidenceUnavailable, EvidenceWriter
from meme_machine.solana_planning_quantum import PlanningQuantum
from meme_machine.solana_rolling_history import RollingHistory
from meme_machine.solana_selective_history import SelectiveHistory


NOW = 1791400000.0


class OwnerPlanningQuantumTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)/'canonical.sqlite'
        self.wall = NOW
        self.writer = EvidenceWriter(self.path, clock=lambda: self.wall)
        self.addCleanup(self.writer.close)
        self.h = SelectiveHistory(self.writer, 'a'*64, clock=lambda: self.wall)
        self.h.active_families = ('pump', 'pumpswap')
        self.db = self.writer.db
        self.db.executescript(LIFECYCLE_SCHEMA)
        self.h.rolling = RollingHistory(self.h)
        self.serial = 0

    def install(self):
        self.h.install_planner()
        self.scheduler = self.h.acquisition_scheduler

    def add_job(self, *, priority=3, deadline=None, address=None, family='pump'):
        self.serial += 1
        return self.h.request(family, address or 'quantum-job-'+str(self.serial), 10, 20,
            priority=priority, deadline=NOW+1000 if deadline is None else deadline)

    def quantum(self):
        return PlanningQuantum(self.h, deadline=time.perf_counter()+60)

    def scheduling_snapshot(self):
        tables = ('acquisition_jobs', 'acquisition_observations', QUEUE, STATE,
            URGENT_STATE, URGENT_COUNT, FANOUT, SIGNALS,
            'acquisition_schedule_signal_cursor_v1')
        return {table: self.db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
                for table in tables}

    def complete(self, identity):
        self.db.execute("UPDATE acquisition_jobs SET status='complete' WHERE id=?", (identity,))

    def test_real_preludes_run_once_but_each_head_is_selected_fresh_inside_quantum(self):
        self.install()
        expected = [self.add_job(priority=2, deadline=NOW+100),
            self.add_job(priority=2, deadline=NOW+110),
            self.add_job(priority=3, deadline=NOW+120),
            self.add_job(priority=3, deadline=NOW+130)]
        statements = []
        self.db.set_trace_callback(statements.append)
        try:
            with patch.object(self.scheduler, '_seed_urgent', wraps=self.scheduler._seed_urgent) as seed, \
                    patch.object(self.scheduler, '_wake_rank', wraps=self.scheduler._wake_rank) as ranks, \
                    patch.object(self.scheduler, 'backfill', wraps=self.scheduler.backfill) as backfill, \
                    patch.object(self.scheduler, 'wake_fanout', wraps=self.scheduler.wake_fanout) as signals:
                with self.writer.transaction():
                    quantum = self.quantum()
                    try:
                        for identity in expected:
                            result = self.h.plan_step(quantum=quantum)
                            self.assertEqual((result.state, result.plan[0]['id']), (DISPATCH, identity))
                            self.complete(identity)
                    finally:
                        quantum.close()
                self.assertEqual(seed.call_count, 1)
                self.assertEqual(backfill.call_count, 1)
                self.assertEqual(signals.call_count, 1)
                rank_counts = Counter(call.args[0] for call in ranks.call_args_list)
                self.assertEqual(rank_counts, Counter({0: 1, 1: 1, 2: 1, 3: 1}))
        finally:
            self.db.set_trace_callback(None)
        expiry_reads = [statement for statement in statements
            if statement.lstrip().upper().startswith('SELECT')
            and 'INDEXED BY acquisition_expiry_quantum_v1' in statement]
        self.assertEqual(len(expiry_reads), len(self.h.active_families))
        self.assertEqual(self.scheduler.pending_count(), 0)
        self.assertFalse(self.db.in_transaction)

    def test_new_urgent_arrival_and_tightening_outrank_cached_optional_prelude(self):
        self.install()
        optional = self.add_job(priority=3, deadline=NOW+300)
        later = self.add_job(priority=3, deadline=NOW+400)
        with self.writer.transaction():
            quantum = self.quantum()
            try:
                first = self.h.plan_step(quantum=quantum)
                self.assertEqual(first.plan[0]['id'], optional)
                urgent = self.add_job(priority=1, deadline=NOW+200)
                second = self.h.plan_step(quantum=quantum)
                self.assertEqual((second.state, second.plan[0]['id']), (DISPATCH, urgent))
                self.db.execute('UPDATE acquisition_jobs SET priority=0,deadline=? WHERE id=?',
                                (NOW+100, later))
                third = self.h.plan_step(quantum=quantum)
                self.assertEqual((third.state, third.plan[0]['id'], third.plan[0]['deadline']),
                                 (DISPATCH, later, NOW+100))
            finally:
                quantum.close()
        self.assertEqual(self.db.execute('SELECT lo,hi,deadline,status FROM acquisition_jobs WHERE id=?',
            (optional,)).fetchone(), (10, 20, NOW+300, 'pending'))
        self.assertEqual(self.db.execute('SELECT lo,hi,deadline,status FROM acquisition_jobs WHERE id=?',
            (urgent,)).fetchone(), (10, 20, NOW+200, 'pending'))

    def test_new_earlier_retry_frontier_yields_then_fresh_quantum_wakes_original_head(self):
        self.install()
        earlier = self.add_job(priority=3, deadline=NOW+100)
        later = self.add_job(priority=3, deadline=NOW+200)
        with self.writer.transaction():
            quantum = self.quantum()
            try:
                first = self.h.plan_step(quantum=quantum)
                self.assertEqual(first.plan[0]['id'], earlier)
                with quantum.decision(self.h):
                    self.assertTrue(self.scheduler.defer(first.plan[0], NOW+.5, quantum=quantum))
                self.wall = NOW+.5
                result = self.h.plan_step(quantum=quantum)
                self.assertEqual((result.state, result.plan, result.yield_quantum),
                                 (DEFERRED, None, True))
                self.assertEqual(self.db.execute(f'SELECT ready,retry_at FROM {QUEUE} WHERE id=?',
                    (earlier,)).fetchone(), (0, NOW+.5))
                self.assertEqual(self.db.execute('SELECT status FROM acquisition_jobs WHERE id=?',
                    (later,)).fetchone(), ('pending',))
            finally:
                quantum.close()
        with self.writer.transaction():
            fresh = self.quantum()
            try:
                result = self.h.plan_step(quantum=fresh)
                self.assertEqual((result.state, result.plan[0]['id'], result.plan[0]['deadline']),
                                 (DISPATCH, earlier, NOW+100))
            finally:
                fresh.close()

    def test_expired_debt_is_bounded_and_honest_while_fresh_urgent_work_dispatches(self):
        self.install()
        expired = [self.add_job(priority=3, deadline=NOW-1-number) for number in range(40)]
        urgent = self.add_job(priority=0, deadline=NOW+100)
        with self.writer.transaction():
            quantum = self.quantum()
            try:
                result = self.h.plan_step(quantum=quantum)
                self.assertEqual((result.state, result.plan[0]['id'], result.plan[0]['deadline']),
                                 (DISPATCH, urgent, NOW+100))
                self.complete(urgent)
                result = self.h.plan_step(quantum=quantum)
                self.assertEqual((result.state, result.plan), (DEFERRED, None))
            finally:
                quantum.close()
        statuses = Counter(status for status, in self.db.execute(
            'SELECT status FROM acquisition_jobs WHERE id IN ('+','.join('?' for _ in expired)+')', expired))
        self.assertEqual(statuses, Counter({'deadline_missed': 16, 'pending': 24}))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM acquisition_observations '
            "WHERE kind='deadline_missed'").fetchone(), (16,))
        self.assertEqual(self.scheduler.pending_count(), 24)

    def test_quantum_scope_rejects_creation_without_outer_transaction_and_closed_reuse(self):
        self.install()
        with self.assertRaises(EvidenceUnavailable):
            self.quantum()
        with self.writer.transaction():
            quantum = self.quantum()
            with quantum.decision(self.h):
                pass
            quantum.close()
            with self.assertRaises(EvidenceUnavailable):
                with quantum.decision(self.h):
                    self.fail('closed quantum entered a decision')

    def test_foreign_writer_and_foreign_thread_cannot_use_active_quantum(self):
        self.install()
        other = EvidenceWriter(self.path.parent/'other.sqlite', clock=lambda: self.wall)
        self.addCleanup(other.close)
        foreign = SimpleNamespace(writer=other, db=other.db, clock=self.h.clock)
        with self.writer.transaction():
            quantum = self.quantum()
            try:
                with self.assertRaises(EvidenceUnavailable):
                    with quantum.decision(foreign):
                        self.fail('foreign writer entered a decision')
                quantum.close()
                quantum = self.quantum()
                quantum.validate(self.h)
                errors = []

                def cross_thread():
                    try:
                        with quantum.decision(self.h):
                            errors.append(AssertionError('foreign thread entered a decision'))
                    except BaseException as error:
                        errors.append(error)

                thread = threading.Thread(target=cross_thread)
                thread.start()
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], EvidenceUnavailable)
            finally:
                quantum.close()

    def test_constructor_rejects_writer_database_mismatch_before_creating_guard(self):
        self.install()
        other = EvidenceWriter(self.path.parent/'foreign-constructor.sqlite', clock=lambda: self.wall)
        self.addCleanup(other.close)
        foreign = SimpleNamespace(writer=self.writer, db=other.db, clock=self.h.clock)
        with self.writer.transaction(), other.transaction():
            before = other.db.execute("SELECT name FROM sqlite_temp_master WHERE type='table'").fetchall()
            with self.assertRaises(EvidenceUnavailable):
                PlanningQuantum(foreign, deadline=time.perf_counter()+60)
            self.assertEqual(other.db.execute("SELECT name FROM sqlite_temp_master WHERE type='table'").fetchall(), before)

    def test_constructor_uses_real_writer_owner_check_and_refuses_foreign_thread(self):
        self.install()
        with self.writer.transaction():
            with patch.object(self.writer, '_check', wraps=self.writer._check) as owner_check:
                quantum = self.quantum()
                try:
                    owner_check.assert_called()
                finally:
                    quantum.close()
            errors = []

            def foreign_constructor():
                try:
                    foreign_quantum = self.quantum()
                    foreign_quantum.close()
                    errors.append(AssertionError('foreign thread constructed an owner quantum'))
                except BaseException as error:
                    errors.append(error)

            thread = threading.Thread(target=foreign_constructor)
            thread.start()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], EvidenceUnavailable)

    def test_escaping_plan_exception_keeps_savepoint_rollback_and_poisons_caught_quantum(self):
        self.install()
        identity = self.add_job(priority=1, deadline=NOW+100)
        original = self.db.execute('SELECT * FROM acquisition_jobs WHERE id=?', (identity,)).fetchone()
        observations = self.db.execute('SELECT * FROM acquisition_observations').fetchall()

        def failed_completeness(*args, **options):
            self.db.execute('UPDATE acquisition_jobs SET deadline=? WHERE id=?', (NOW+50, identity))
            self.h._observation(identity, 'fixture_planning_error', dict(complete=False))
            raise RuntimeError('original quantum planning failure')

        with self.writer.transaction():
            quantum = self.quantum()
            try:
                with patch.object(self.h.rolling, 'missing', side_effect=failed_completeness):
                    with self.assertRaisesRegex(RuntimeError, 'original quantum planning failure'):
                        self.h.plan_step(quantum=quantum)
                self.assertEqual(self.db.execute('SELECT * FROM acquisition_jobs WHERE id=?',
                    (identity,)).fetchone(), original)
                self.assertEqual(self.db.execute('SELECT * FROM acquisition_observations').fetchall(), observations)
                with self.assertRaises(EvidenceUnavailable):
                    self.h.plan_step(quantum=quantum)
            finally:
                quantum.close()

    def test_budget_crossed_between_previous_phase_and_decision_entry_yields_without_consuming_phase(self):
        from meme_machine.solana_candidate_phases import CandidatePhases, DEVELOPMENT_PHASES
        self.install()
        identity=self.add_job(priority=3)
        actor=CandidateDevelopment(self.h,clock=lambda:0)
        actor.phase=4
        actor.poll_at=1
        timing=CandidatePhases({},phases=DEVELOPMENT_PHASES,
            prefix='development_phase:',runnable=lambda:None)
        clock=[.004]
        validations=[]
        original_validate=PlanningQuantum.validate
        def advancing_validate(quantum,history):
            original_validate(quantum,history)
            validations.append(quantum.decisions)
            # Urgent-empty admission completes first. The later phase4 plan
            # enters just after its caller saw budget remaining. This is the
            # original public-check/context-entry race, not a forged result.
            if len(validations)==5:clock[0]=.010
        with patch('meme_machine.solana_candidate_development.time.perf_counter',side_effect=lambda:clock[0]), \
                patch.object(PlanningQuantum,'validate',new=advancing_validate), \
                patch.object(self.h,'_plan_step',wraps=self.h._plan_step) as actual_plan:
            result=actor.step(timing,30)
        self.assertEqual((result.state,result.plan,result.yield_quantum),(DEFERRED,None,True))
        self.assertEqual(actor.phase,4)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(actual_plan.call_count,1)
        self.assertTrue(actual_plan.call_args.kwargs['urgent_only'])
        self.assertEqual(self.db.execute('SELECT status,deadline,lo,hi FROM acquisition_jobs WHERE id=?',
            (identity,)).fetchone(),('pending',NOW+1000,10,20))
        # A subsequent fresh turn still performs the unconsumed phase4 plan.
        with patch('meme_machine.solana_candidate_development.time.perf_counter',return_value=0):
            result=actor.step(timing,30)
        self.assertEqual((result.state,result.plan[0]['id']),(DISPATCH,identity))
        self.assertEqual(actor.phase,0)

    def test_sixteen_decision_budget_yields_without_another_plan_or_claim(self):
        self.install()
        identity = self.add_job(priority=1)
        with self.writer.transaction():
            quantum = self.quantum()
            try:
                for _ in range(16):
                    with quantum.decision(self.h):
                        pass
                with patch.object(self.h.rolling, 'missing', side_effect=AssertionError('exhausted quantum planned')):
                    result = self.h.plan_step(quantum=quantum)
                self.assertEqual((result.state, result.plan, result.yield_quantum), (DEFERRED, None, True))
                with self.assertRaises(EvidenceUnavailable):
                    with quantum.decision(self.h):
                        self.fail('seventeenth decision entered')
            finally:
                quantum.close()
        self.assertEqual(self.db.execute('SELECT status,deadline,lo,hi FROM acquisition_jobs WHERE id=?',
            (identity,)).fetchone(), ('pending', NOW+1000, 10, 20))

    def test_outer_rollback_rewinds_sql_cursors_and_refuses_old_quantum_in_new_transaction(self):
        for _ in range(24):
            self.add_job(priority=3)
        self.install()
        before = self.scheduling_snapshot()
        quantum = None
        with self.assertRaisesRegex(RuntimeError, 'rollback original outer quantum'):
            with self.writer.transaction():
                quantum = self.quantum()
                result = self.h.plan_step(quantum=quantum)
                self.assertEqual(result.state, DEFERRED)
                self.assertNotEqual(self.db.execute(f'SELECT after_id,complete FROM {STATE}').fetchone(), ('', 0))
                raise RuntimeError('rollback original outer quantum')
        self.assertEqual(self.scheduling_snapshot(), before)
        try:
            with self.writer.transaction():
                with self.assertRaises(EvidenceUnavailable):
                    with quantum.decision(self.h):
                        self.fail('rolled-back quantum crossed into a new owner transaction')
        finally:
            quantum.close()
        with self.writer.transaction():
            fresh = self.quantum()
            try:
                self.assertEqual(self.h.plan_step(quantum=fresh).state, DEFERRED)
                self.assertNotEqual(self.db.execute(f'SELECT after_id,complete FROM {STATE}').fetchone(), ('', 0))
            finally:
                fresh.close()

    def test_fresh_quantum_repeats_preludes_instead_of_reusing_previous_transaction_cache(self):
        self.install()
        identity = self.add_job(priority=2)
        with patch.object(self.scheduler, '_seed_urgent', wraps=self.scheduler._seed_urgent) as seed, \
                patch.object(self.scheduler, 'wake_fanout', wraps=self.scheduler.wake_fanout) as signals:
            for _ in range(2):
                with self.writer.transaction():
                    quantum = self.quantum()
                    try:
                        result = self.h.plan_step(quantum=quantum)
                        self.assertEqual((result.state, result.plan[0]['id']), (DISPATCH, identity))
                    finally:
                        quantum.close()
            self.assertEqual(seed.call_count, 2)
            self.assertEqual(signals.call_count, 2)


if __name__ == '__main__':
    unittest.main()
