"""Real owner SQLite scheduling regressions; synthetic scouts grant no entry."""
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.lanes.pump.pump_acceleration_strategy import POLICY
from meme_machine.solana_candidate_development import (
    CandidateDevelopment, DevelopmentCandidates, PlanningStep, DISPATCH, DEFERRED, IDLE)
from meme_machine.solana_candidate_lifecycle import SCHEMA as LIFECYCLE_SCHEMA
from meme_machine.solana_candidate_phases import CandidatePhases, DEVELOPMENT_PHASES
from meme_machine.solana_evidence_plane import EvidenceWriter, EvidenceUnavailable, canonical, digest
from meme_machine.solana_selective_history import SelectiveHistory, coverage_scope


NOW = 1791400000.0


class BoundedDevelopmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)/'canonical.sqlite'
        self.wall = NOW
        self.monotonic = 0.0
        self.plan_calls = []
        self.urgent_result = PlanningStep(IDLE)
        self.optional_result = PlanningStep(IDLE)
        self.prepare_failure = False
        self.actor = None
        self.open_history()
        self.addCleanup(lambda: self.writer.close())
        self.pipeline = {}
        self.timing = CandidatePhases(self.pipeline, phases=DEVELOPMENT_PHASES,
            prefix='development_phase:', runnable=lambda: None)

    def open_history(self):
        self.writer = EvidenceWriter(self.path, clock=lambda: self.wall)
        self.h = SelectiveHistory(self.writer, 'a'*64, clock=lambda: self.wall)
        self.db = self.h.db
        self.db.executescript(LIFECYCLE_SCHEMA)
        self.db.execute('''CREATE TABLE IF NOT EXISTS fixture_preparations(
            family TEXT,address TEXT,lo INTEGER,hi INTEGER,priority INTEGER,deadline REAL,
            PRIMARY KEY(family,address))''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS fixture_phase_effects(
            phase TEXT,after_cursor INTEGER,limit_value INTEGER,result_cursor INTEGER)''')
        self.h.active_families = ('pump',)
        # These tests exercise actor/queue ownership, not DispatchProbe or an
        # independently tested history/provider implementation.
        self.h.install_planner = lambda: None
        self.h.plan_step = self.plan_step
        self.h.lifecycle = SimpleNamespace(publish=lambda: None,
            demote=lambda *args, **kwargs: None, promote=lambda *args, **kwargs: None)
        self.h.rolling = SimpleNamespace(prepare=self.prepare,
            resume_boundaries=lambda **options: self.phase_effect('boundaries', 17, **options),
            resume_publication=lambda **options: self.phase_effect('publication', 23, **options),
            repair_required_checkpoint_prefixes=lambda: None)

    def plan_step(self, *, excluding=(), urgent_only=False, quantum=None):
        self.plan_calls.append((urgent_only, tuple(excluding), self.db.in_transaction))
        return self.urgent_result if urgent_only else self.optional_result

    def prepare(self, family, address, lo, hi, *, priority, deadline):
        self.assertTrue(self.db.in_transaction)
        self.assertIsNotNone(self.db.execute(
            'SELECT 1 FROM evidence_bindings WHERE family=? AND address=?',
            (family, address)).fetchone())
        self.db.execute('INSERT INTO fixture_preparations VALUES(?,?,?,?,?,?)',
                        (family, address, lo, hi, priority, deadline))
        if self.prepare_failure:
            raise RuntimeError('original preparation failure')
        return dict(missing_intervals=None, entry_authority=False)

    def phase_effect(self, phase, result, *, limit, after):
        self.assertTrue(self.db.in_transaction)
        self.db.execute('INSERT INTO fixture_phase_effects VALUES(?,?,?,?)',
                        (phase, after, limit, result))
        return result

    def market(self, address, *, fields=None, first=None, family='pump', lifecycle=True):
        first = self.wall if first is None else first
        fields = {} if fields is None else fields
        self.db.execute('INSERT INTO market_observations VALUES(?,?,?,?,?,?,?,?,?)',
            (family, address, 1, 1, first, first, 'offline-scout', canonical(fields), digest(fields)))
        if lifecycle:
            self.db.execute('INSERT INTO candidate_lifecycle VALUES(?,?,?,?,?,?,?,?,?,?)',
                (family, address, 'scout', 0, 1, 1, first, first, None, 0))

    def build_actor(self):
        self.actor = CandidateDevelopment(self.h, clock=lambda: self.monotonic)
        return self.actor

    def phase_step(self, actor, frontier=123, **options):
        # Urgent IDLE consumes one transition; retain a single housekeeping
        # phase for the isolated phase/commit witnesses below. The full bounded
        # microbatch and its independent real-time cutoff have separate tests.
        with patch('meme_machine.solana_candidate_development.MICROBATCH_TRANSITIONS', 2), \
                patch('meme_machine.solana_candidate_development.time.perf_counter', return_value=0):
            return actor.step(self.timing, frontier, **options)

    def seed(self, candidates):
        for _ in range(2000):
            if candidates.backfill(self.timing):
                return
        self.fail('bounded candidate backfill made no progress')

    def original(self):
        return self.h.development_candidates(POLICY.min_curve_progress_bps, 16)

    def test_queue_selection_matches_original_complete_unknown_and_progress_branches(self):
        fields = ({}, {'complete': True, 'development_upper_bps': 0},
            {'complete': False, 'development_upper_bps': POLICY.min_curve_progress_bps-1},
            {'complete': False, 'development_upper_bps': POLICY.min_curve_progress_bps},
            {'complete': False, 'development_upper_bps': None},
            {'complete': False, 'development_upper_bps': 'retained-original-sqlite-type'})
        with self.writer.transaction():
            for number in range(48):
                self.market('candidate-'+str(number).zfill(3), fields=fields[number % len(fields)],
                            first=NOW+(number % 4), lifecycle=False)
            self.market('other-family', family='pumpswap', lifecycle=False)
            self.h.bind('pump', 'candidate-000')
        candidates = DevelopmentCandidates(self.h, POLICY.min_curve_progress_bps)
        self.seed(candidates)
        selected = []
        while True:
            expected = self.original()
            actual = candidates.next()
            self.assertEqual(actual, expected)
            if not actual:
                break
            with self.writer.transaction():
                for address, in actual:
                    self.h.bind('pump', address)
                    selected.append(address)
        self.assertGreater(len(selected), 16)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0], 49)
        self.assertEqual(candidates.next(), [])

    def test_ten_thousand_bound_and_low_progress_scouts_do_not_expand_head_vm_work(self):
        minimum = POLICY.min_curve_progress_bps
        retained = []
        bindings = []
        for number in range(10000):
            address = 'retained-'+str(number).zfill(5)
            fields = {'complete': True} if number % 2 == 0 else dict(
                complete=False, development_upper_bps=minimum-1)
            retained.append(('pump', address, 1, 1, NOW, NOW, 'offline-scout',
                             canonical(fields), digest(fields)))
            if number % 2 == 0:
                bindings.append(('pump', address, address, 'program:pump',
                                 coverage_scope('pump', address), '{}'))
        with self.writer.transaction():
            self.db.executemany('INSERT INTO market_observations VALUES(?,?,?,?,?,?,?,?,?)', retained)
            self.db.executemany('INSERT INTO evidence_bindings VALUES(?,?,?,?,?,?)', bindings)
            for number in range(20):
                self.market('eligible-'+str(number).zfill(2), first=NOW-1, lifecycle=False)
        candidates = DevelopmentCandidates(self.h, minimum)
        self.seed(candidates)
        expected = self.original()
        self.assertEqual(len(expected), 16)
        steps = [0]

        def bounded():
            steps[0] += 100
            return int(steps[0] > 5000)

        self.db.set_progress_handler(bounded, 100)
        try:
            self.assertEqual(candidates.next(), expected)
        finally:
            self.db.set_progress_handler(None, 0)
        self.assertLessEqual(steps[0], 5000)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0], 10020)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM evidence_bindings').fetchone()[0], 5000)

    def test_live_market_binding_unbind_and_retirement_keep_original_selection(self):
        candidates = DevelopmentCandidates(self.h, POLICY.min_curve_progress_bps)
        self.seed(candidates)
        self.market('live', fields={'complete': True})
        self.assertEqual(candidates.next(), self.original())
        self.h.bind('pump', 'live')
        self.assertEqual(candidates.next(), [])
        self.db.execute("DELETE FROM evidence_bindings WHERE family='pump' AND address='live'")
        self.assertEqual(candidates.next(), [('live',)])
        fields = dict(complete=False, development_upper_bps=POLICY.min_curve_progress_bps-1)
        self.db.execute("UPDATE market_observations SET fields=? WHERE family='pump' AND address='live'",
                        (canonical(fields),))
        self.assertEqual(candidates.next(), self.original())
        self.assertEqual(candidates.next(), [])
        self.db.execute("UPDATE market_observations SET fields=?,first_seen=? WHERE address='live'",
                        (canonical(dict(complete=True)), NOW-2))
        self.assertEqual(candidates.next(), [('live',)])
        self.db.execute("DELETE FROM market_observations WHERE family='pump' AND address='live'")
        self.assertEqual(candidates.next(), self.original())
        self.assertEqual(candidates.next(), [])

    def test_binding_address_and_family_moves_restore_old_now_unbound_candidate(self):
        self.market('original', lifecycle=False)
        self.market('replacement', lifecycle=False)
        self.h.bind('pump', 'original')
        candidates = DevelopmentCandidates(self.h, POLICY.min_curve_progress_bps)
        self.seed(candidates)
        self.db.execute("UPDATE evidence_bindings SET address='replacement' WHERE family='pump' AND address='original'")
        self.assertEqual(candidates.next(), self.original())
        self.assertEqual(candidates.next(), [('original',)])
        self.db.execute("UPDATE evidence_bindings SET family='pumpswap' WHERE family='pump' AND address='replacement'")
        self.assertEqual(candidates.next(), self.original())
        self.assertEqual(candidates.next(), [('original',), ('replacement',)])

    def test_backfill_and_trigger_changes_are_rollback_safe_and_resume_after_restart(self):
        for number in range(40):
            self.market('retained-'+str(number).zfill(3), lifecycle=False)
        candidates = DevelopmentCandidates(self.h, POLICY.min_curve_progress_bps)
        self.assertFalse(candidates.backfill(self.timing))
        before = self.db.execute(f'SELECT * FROM {candidates.STATE}').fetchall()
        with self.assertRaisesRegex(RuntimeError, 'rollback fixture'):
            with self.writer.transaction():
                candidates.backfill(self.timing)
                self.market('new-rolled-back', lifecycle=False)
                self.h.bind('pump', 'retained-000')
                raise RuntimeError('rollback fixture')
        self.assertEqual(self.db.execute(f'SELECT * FROM {candidates.STATE}').fetchall(), before)
        self.assertIsNone(self.db.execute("SELECT 1 FROM market_observations WHERE address='new-rolled-back'").fetchone())
        self.assertIsNone(self.db.execute("SELECT 1 FROM evidence_bindings WHERE address='retained-000'").fetchone())
        self.writer.close()
        self.open_history()
        candidates = DevelopmentCandidates(self.h, POLICY.min_curve_progress_bps)
        self.assertEqual(self.db.execute(f'SELECT * FROM {candidates.STATE}').fetchall(), before)
        self.seed(candidates)
        self.assertEqual(candidates.next(), self.original())

    def test_different_minimum_requires_explicit_policy_migration(self):
        DevelopmentCandidates(self.h, POLICY.min_curve_progress_bps)
        with self.assertRaisesRegex(EvidenceUnavailable, 'candidate_development_policy_migration_required'):
            DevelopmentCandidates(self.h, POLICY.min_curve_progress_bps+1)

    def test_binding_and_first_preparation_commit_in_same_selection_quantum(self):
        self.market('atomic-entry', first=NOW-10)
        actor = self.build_actor()
        self.seed(actor.candidates)
        self.prepare_failure = True
        with self.assertRaisesRegex(RuntimeError, 'original preparation failure'):
            self.phase_step(actor)
        self.assertEqual(actor.phase, 0)
        self.assertIsNone(self.db.execute("SELECT 1 FROM evidence_bindings WHERE address='atomic-entry'").fetchone())
        self.assertEqual(self.db.execute('SELECT * FROM fixture_preparations').fetchall(), [])
        self.assertEqual(actor.candidates.next(), [('atomic-entry',)])
        self.prepare_failure = False
        self.assertEqual(self.phase_step(actor).state, DEFERRED)
        self.assertEqual(actor.phase, 1)
        self.assertEqual(self.db.execute('SELECT * FROM fixture_preparations').fetchall(),
                         [('pump', 'atomic-entry', 0, 123, 3, NOW+140)])
        self.assertEqual(actor.candidates.next(), [])

    def test_failed_commit_does_not_advance_phase_or_published_cursor(self):
        actor = self.build_actor()
        actor.phase = 2
        actor.cursors['boundary'] = 5
        original = self.writer.db

        class FailingCommit:
            def __getattr__(self, key):
                return getattr(original, key)

            def execute(self, statement, *args, **kwargs):
                if statement == 'COMMIT':
                    raise sqlite3.OperationalError('original commit failure')
                return original.execute(statement, *args, **kwargs)

        with patch.object(self.writer, 'db', FailingCommit()):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'original commit failure'):
                self.phase_step(actor)
        self.assertEqual(actor.phase, 2)
        self.assertEqual(actor.cursors['boundary'], 5)
        self.assertEqual(self.db.execute('SELECT * FROM fixture_phase_effects').fetchall(), [])
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.phase_step(actor).state, DEFERRED)
        self.assertEqual(actor.phase, 3)
        self.assertEqual(actor.cursors['boundary'], 17)
        self.assertEqual(self.db.execute('SELECT * FROM fixture_phase_effects').fetchall(),
                         [('boundaries', 5, 16, 17)])

    def test_fifth_quantum_plans_even_when_every_callback_exceeds_poll_interval(self):
        actor = self.build_actor()
        plan = ({'id': 'offline-job'}, {'unchanged': True})
        self.optional_result = PlanningStep(DISPATCH, plan)
        results = []
        for _ in range(5):
            self.monotonic += .2
            results.append(self.phase_step(actor, excluding=('inflight',), batched=True))
        self.assertEqual([result.state for result in results], [DEFERRED]*4+[DISPATCH])
        self.assertEqual(results[-1].plan, plan)
        self.assertEqual(actor.phase, 0)
        self.assertEqual([urgent for urgent, _, _ in self.plan_calls], [True]*5+[False])
        self.assertTrue(all(excluding == ('inflight',) for _, excluding, _ in self.plan_calls))
        self.assertTrue(all(in_transaction for _, _, in_transaction in self.plan_calls))
        self.assertEqual(self.timing.rows['plan']['calls'], 6)

    def test_incomplete_scout_backfill_still_reaches_planning_quantum(self):
        for number in range(64):
            self.market('retained-scout-'+str(number).zfill(3), lifecycle=False,
                fields=dict(complete=False, development_upper_bps=POLICY.min_curve_progress_bps-1))
        actor = self.build_actor()
        self.optional_result = PlanningStep(DISPATCH, ({'id': 'offline-job'}, {}))
        results = []
        for _ in range(5):
            self.monotonic += .2
            results.append(self.phase_step(actor))
        self.assertEqual([result.state for result in results], [DEFERRED]*4+[DISPATCH])
        self.assertEqual(self.db.execute(f'SELECT complete FROM {actor.candidates.STATE}').fetchone(), (0,))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0], 64)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM evidence_bindings').fetchone()[0], 0)

    def test_external_hooks_run_after_commit_once_before_fresh_planning_despite_urgent_dispatch(self):
        actor=self.build_actor()
        actor.phase=4
        self.h.active_families=('pump','meteora')
        hooks=[]
        def external(name):
            self.assertFalse(self.db.in_transaction)
            hooks.append(name)
            with self.writer.transaction():
                self.db.execute('INSERT INTO fixture_phase_effects VALUES(?,?,?,?)',(name,0,0,0))
        self.h.lifecycle.publish=lambda:external('legacy_publish')
        self.h.rolling.repair_required_checkpoint_prefixes=lambda:external('legacy_edf')
        self.urgent_result=PlanningStep(DISPATCH,({'id':'held-original'},{}))
        with patch('meme_machine.solana_candidate_development.time.perf_counter',return_value=0):
            for _ in range(2):
                result=actor.step(self.timing,123,batched=False)
                self.assertEqual(result.plan[0]['id'],'held-original')
                self.assertEqual(actor.phase,4)
            self.assertEqual(hooks,['legacy_publish','legacy_edf'])
            self.urgent_result=PlanningStep(IDLE)
            self.optional_result=PlanningStep(DISPATCH,({'id':'fresh-after-hooks'},{}))
            result=actor.step(self.timing,123,batched=False)
        self.assertEqual(result.plan[0]['id'],'fresh-after-hooks')
        self.assertEqual(hooks,['legacy_publish','legacy_edf'])
        self.assertEqual(actor.phase,0)
        self.assertFalse(actor.external_boundary_done)
        self.assertTrue(all(in_transaction for _,_,in_transaction in self.plan_calls))
        self.assertEqual(self.db.execute('SELECT phase FROM fixture_phase_effects ORDER BY rowid').fetchall(),
            [('legacy_publish',),('legacy_edf',)])

    def test_urgent_dispatch_precedes_projection_backfill_and_all_housekeeping(self):
        self.market('unprocessed-scout')
        actor = self.build_actor()
        self.urgent_result = PlanningStep(DISPATCH, ({'id': 'urgent-original'}, {}))
        before = self.db.execute(f'SELECT * FROM {actor.candidates.STATE}').fetchall()
        with patch.object(actor.candidates, 'backfill', side_effect=AssertionError('urgent work delayed by backfill')):
            result = actor.step(self.timing, 123)
        self.assertIs(result, self.urgent_result)
        self.assertEqual(actor.phase, 0)
        self.assertEqual(self.db.execute(f'SELECT * FROM {actor.candidates.STATE}').fetchall(), before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM evidence_bindings').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT * FROM fixture_preparations').fetchall(), [])
        self.assertEqual(self.db.execute('SELECT * FROM fixture_phase_effects').fetchall(), [])

    def test_empty_install_is_complete_and_live_inserts_need_no_retained_rebuild(self):
        actor = self.build_actor()
        self.assertEqual(self.db.execute(
            f'SELECT after_address,complete FROM {actor.candidates.STATE}').fetchone(), ('', 1))
        self.market('new-live-scout')
        self.assertEqual(actor.candidates.next(), [('new-live-scout',)])
        with patch.object(actor.candidates, 'backfill', wraps=actor.candidates.backfill) as backfill:
            self.phase_step(actor)
        backfill.assert_called_once_with(self.timing)
        self.assertEqual(self.db.execute(
            f'SELECT after_address,complete FROM {actor.candidates.STATE}').fetchone(), ('', 1))
        self.assertEqual(self.db.execute('SELECT address FROM fixture_preparations').fetchall(),
            [('new-live-scout',)])

    def test_microbatch_several_bounded_units_publish_with_one_full_commit(self):
        actor = self.build_actor()
        actor.phase = 2
        actor.cursors.update(boundary=5, publication=7)
        plan = ({'id': 'original-optional-plan'}, {'unchanged': True})
        self.optional_result = PlanningStep(DISPATCH, plan)
        statements = []
        self.assertEqual(self.db.execute('PRAGMA synchronous').fetchone()[0], 2)
        self.db.set_trace_callback(statements.append)
        try:
            with patch('meme_machine.solana_candidate_development.time.perf_counter', return_value=0):
                result = actor.step(self.timing, 123, excluding=('already-inflight',))
        finally:
            self.db.set_trace_callback(None)
        controls = [statement.strip().upper() for statement in statements]
        self.assertEqual(sum(statement == 'BEGIN IMMEDIATE' for statement in controls), 1)
        self.assertEqual(sum(statement == 'COMMIT' for statement in controls), 1)
        self.assertEqual(sum(statement == 'ROLLBACK' for statement in controls), 0)
        self.assertEqual(self.db.execute('SELECT * FROM fixture_phase_effects').fetchall(),
            [('boundaries', 5, 16, 17), ('publication', 7, 16, 23)])
        self.assertEqual((result.state, result.plan), (DISPATCH, plan))
        self.assertEqual(actor.phase, 0)
        self.assertEqual(actor.cursors, dict(reactivated=0, boundary=17, publication=23))
        self.assertEqual(self.timing.rows['commit']['calls'], 1)
        self.assertEqual([urgent for urgent, _, _ in self.plan_calls], [True, False])
        self.assertTrue(all(in_transaction for _, _, in_transaction in self.plan_calls))

    def test_later_unit_failure_rolls_back_all_phase_writes_and_original_actor_state(self):
        self.market('atomic-all-phases', first=NOW-10)
        actor = self.build_actor()
        actor.cursors.update(reactivated=7, boundary=5, publication=6)
        original_cursors = dict(actor.cursors)
        original_state = self.db.execute(f'SELECT * FROM {actor.candidates.STATE}').fetchall()
        original_queue = self.db.execute(f'SELECT * FROM {actor.candidates.QUEUE}').fetchall()

        def fail_later(**options):
            self.phase_effect('publication', 23, **options)
            # These preceding writes are visible in this same canonical unit.
            self.assertIsNotNone(self.db.execute(
                "SELECT 1 FROM evidence_bindings WHERE address='atomic-all-phases'").fetchone())
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM fixture_preparations').fetchone()[0], 1)
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM fixture_phase_effects').fetchone()[0], 2)
            raise RuntimeError('later atomic unit failed')

        with patch.object(self.h.rolling, 'resume_publication', side_effect=fail_later), \
                patch('meme_machine.solana_candidate_development.time.perf_counter', return_value=0):
            with self.assertRaisesRegex(RuntimeError, 'later atomic unit failed'):
                actor.step(self.timing, 123)
        self.assertEqual(actor.phase, 0)
        self.assertEqual(actor.poll_at, 0)
        self.assertEqual(actor.cursors, original_cursors)
        self.assertEqual(self.db.execute(f'SELECT * FROM {actor.candidates.STATE}').fetchall(), original_state)
        self.assertEqual(self.db.execute(f'SELECT * FROM {actor.candidates.QUEUE}').fetchall(), original_queue)
        self.assertEqual(self.db.execute('SELECT * FROM fixture_preparations').fetchall(), [])
        self.assertEqual(self.db.execute('SELECT * FROM fixture_phase_effects').fetchall(), [])
        self.assertIsNone(self.db.execute(
            "SELECT 1 FROM evidence_bindings WHERE address='atomic-all-phases'").fetchone())
        self.assertFalse(self.db.in_transaction)

    def test_real_budget_stops_before_next_atomic_unit_independent_of_poll_clock(self):
        actor = self.build_actor()
        actor.phase = 2
        actor.cursors.update(boundary=5, publication=7)
        self.monotonic = -1000.0
        ticks = []

        def real_budget_counter():
            value = (0.0, 0.001, 0.006)[len(ticks)]
            ticks.append(value)
            return value

        with patch('meme_machine.solana_candidate_development.time.perf_counter',
                side_effect=real_budget_counter):
            result = actor.step(self.timing, 123)
        self.assertEqual(result.state, DEFERRED)
        self.assertEqual(ticks, [0.0, 0.001, 0.006])
        self.assertEqual(actor.phase, 3)
        self.assertEqual(actor.cursors, dict(reactivated=0, boundary=17, publication=7))
        self.assertEqual(self.db.execute('SELECT * FROM fixture_phase_effects').fetchall(),
            [('boundaries', 5, 16, 17)])
        self.assertEqual(self.monotonic, -1000.0)
        self.assertEqual([urgent for urgent, _, _ in self.plan_calls], [True])

    def test_cold_retained_rebuild_yields_to_new_urgent_job_then_converges_in_order(self):
        # All retained rows precede actor/trigger installation. Lexical rebuild
        # order differs from the original first_seen selection order.
        population = 65
        for number in range(population):
            self.market('cold-'+str(number).zfill(3), first=NOW-number,
                fields={'complete': True})
        expected = ['cold-'+str(number).zfill(3) for number in reversed(range(population))]
        actor = self.build_actor()
        self.assertEqual(self.db.execute(
            f'SELECT after_address,complete FROM {actor.candidates.STATE}').fetchone(), ('', 0))
        self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {actor.candidates.QUEUE}').fetchone(), (0,))
        self.phase_step(actor)
        self.assertEqual(self.db.execute(
            f'SELECT after_address,complete FROM {actor.candidates.STATE}').fetchone(), ('cold-015', 0))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM evidence_bindings').fetchone(), (0,))
        urgent_id = self.h.request('pump', 'new-held-obligation', 10, 20,
            priority=0, deadline=NOW+30)

        def durable_plan(*, excluding=(), urgent_only=False, quantum=None):
            self.plan_calls.append((urgent_only, tuple(excluding), self.db.in_transaction))
            row = self.db.execute("SELECT id,lo,hi,priority,deadline FROM acquisition_jobs "
                "WHERE status='pending' AND priority<=2 ORDER BY priority,deadline,id LIMIT 1").fetchone()
            if row is not None:
                job = dict(zip(('id', 'lo', 'hi', 'priority', 'deadline'), row))
                return PlanningStep(DISPATCH, (job, {'unchanged': True}))
            return PlanningStep(IDLE)

        self.h.plan_step = durable_plan
        before = self.db.execute(f'SELECT * FROM {actor.candidates.STATE}').fetchall()
        with patch.object(actor.candidates, 'backfill', side_effect=AssertionError('urgent blocked by retained rebuild')):
            dispatched = actor.step(self.timing, 123)
        self.assertEqual((dispatched.state, dispatched.plan[0]['id']), (DISPATCH, urgent_id))
        self.assertEqual(dispatched.plan[0], dict(id=urgent_id, lo=10, hi=20, priority=0, deadline=NOW+30))
        self.assertEqual(self.db.execute(f'SELECT * FROM {actor.candidates.STATE}').fetchall(), before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM fixture_preparations').fetchone(), (0,))
        with self.writer.transaction():
            self.db.execute("UPDATE acquisition_jobs SET status='complete' WHERE id=?", (urgent_id,))
        for _ in range(300):
            self.monotonic += .2
            self.phase_step(actor)
            complete = self.db.execute(
                f'SELECT complete FROM {actor.candidates.STATE}').fetchone()[0]
            if complete:
                self.assertEqual(actor.candidates.next(), self.original())
            else:
                self.assertEqual(self.db.execute('SELECT COUNT(*) FROM evidence_bindings').fetchone(), (0,))
                self.assertEqual(self.db.execute('SELECT COUNT(*) FROM fixture_preparations').fetchone(), (0,))
            if self.db.execute('SELECT COUNT(*) FROM fixture_preparations').fetchone()[0] == population:
                break
        else:
            self.fail('bounded retained projection did not converge after urgent dispatch')
        self.assertEqual(self.db.execute(
            f'SELECT complete FROM {actor.candidates.STATE}').fetchone(), (1,))
        actual = [address for address, in self.db.execute(
            'SELECT address FROM fixture_preparations ORDER BY rowid')]
        self.assertEqual(actual, expected)
        self.assertEqual(actor.candidates.next(), [])
        self.assertEqual(self.original(), [])


if __name__ == '__main__':
    unittest.main()
