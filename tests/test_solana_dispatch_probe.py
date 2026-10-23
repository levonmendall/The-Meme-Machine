"""Real SQLite dispatch scheduling; synthetic plans never grant entry authority."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
import zlib

from meme_machine.solana_candidate_lifecycle import CandidateLifecycle
from meme_machine.solana_dispatch_probe import (
    CHUNK, PAGE, GUARD, JOB_FIELDS, DispatchProbe, READY, COMPLETE, DEFERRED)
from meme_machine.solana_evidence_plane import (
    EvidenceWriter, EvidenceUnavailable, IntervalProof, canonical, digest)
from meme_machine.solana_history_work import HistoricalTasks, dependency_stamp
from meme_machine.solana_prewarm_startup import SCHEMA as STARTUP_SCHEMA
from meme_machine.solana_rolling_history import RollingHistory, program_scope
from meme_machine.solana_selective_history import SelectiveHistory


NOW = 1791400000.0


class DispatchProbeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)/'canonical.sqlite'
        self.wall = NOW
        self.writer = EvidenceWriter(self.path, clock=lambda: self.wall)
        self.addCleanup(self.close_writer)
        self.h = SelectiveHistory(self.writer, 'a'*64, clock=lambda: self.wall)
        self.h.active_families = ('pump', 'pumpswap')
        self.db = self.writer.db
        self.h.lifecycle = CandidateLifecycle(self.h,
            candidate_path=Path(temporary.name)/'candidates.sqlite')
        self.h.rolling = RollingHistory(self.h)
        self.db.executescript(STARTUP_SCHEMA)
        self.db.execute('INSERT INTO prewarm_startup VALUES(1,?,?,?,?,?,?,?)',
            ('fixture-session', 'STEADY_STATE', NOW, NOW, 1, canonical({}), digest({})))
        self.h.historical_tasks = HistoricalTasks(self.h)
        self.h.bind('pump', 'fixture-mint')
        self.db.execute('INSERT INTO candidate_lifecycle VALUES(?,?,?,?,?,?,?,?,?,?)',
            ('pump', 'fixture-mint', 'scout', 0, 10, 100, NOW, NOW, None, 10))
        identity = self.h.request('pump', 'fixture-mint', 10, 100,
            priority=3, deadline=NOW+150)
        self.job = dict(zip(JOB_FIELDS, self.db.execute(
            'SELECT '+','.join(JOB_FIELDS)+' FROM acquisition_jobs WHERE id=?',
            (identity,)).fetchone()))
        self.probe = DispatchProbe(self.h)
        self.h.dispatch_probe = self.probe

    def test_fanout_tightens_overlapping_flight_before_first_child_enqueue(self):
        self.cache(self.metric([[10,20],[30,40]]))
        flight=self.h.request('pump',self.job['address'],15,25,priority=4,deadline=NOW+200)
        tightened=[]
        self.h._archive_preparation_tickets={flight:SimpleNamespace(
            tighten=lambda priority,deadline:tightened.append((priority,deadline)))}
        self.h.install_planner()
        for _ in range(100):
            result=self.h.plan_step(excluding=(flight,))
            self.assertIsNone(result.plan)
            cursor=self.db.execute('SELECT after_slot FROM acquisition_schedule_fanout_v1 WHERE job_id=?',
                (self.job['id'],)).fetchone()
            if cursor==(20,):
                break
        else:
            self.fail('first independently bounded child was not materialized')
        self.assertEqual(self.db.execute('SELECT priority,deadline,token,pages,status FROM acquisition_jobs WHERE id=?',
            (flight,)).fetchone(),(3,NOW+150,None,0,'pending'))
        self.assertIn((3,NOW+150),tightened)
        self.assertEqual(self.db.execute('SELECT lo,hi,deadline,token,pages,status FROM acquisition_jobs WHERE id=?',
            (self.job['id'],)).fetchone(),(10,100,NOW+150,None,0,'pending'))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM acquisition_jobs WHERE lo=10 AND hi=20 AND status='pending'").fetchone(),(1,))
        self.assertFalse(self.db.in_transaction)

    def close_writer(self):
        if self.writer is not None:
            self.writer.close()
            self.writer = None

    def metric(self, gaps=None, *, padding=0, **fields):
        value = dict(lower_slot=10, upper_slot=100,
            missing_intervals=[[10, 100]] if gaps is None else gaps)
        if padding:
            value['note'] = 'x'*padding
        value.update(fields)
        return value

    def cache(self, value, *, checksum=None, raw=None):
        """Authenticate a synthetic local plan using the real dependency stamp.

        This creates no coverage, publication, native proof or financial record.
        Tests with corrupt bytes retain the expected hash as an explicit input.
        """
        pending = self.h.historical_tasks.enqueue('pump', self.job['address'],
            self.job['lo'], self.job['hi'], deadline=self.job['deadline'],
            priority=self.job['priority'])
        identity = pending['historical_job']
        spec = json.loads(self.db.execute(
            'SELECT body FROM rolling_preparation_jobs WHERE id=?', (identity,)).fetchone()[0])
        raw = canonical(value) if raw is None else raw
        checksum = hashlib.sha256(raw.encode()).hexdigest() if checksum is None else checksum
        stamp = dependency_stamp(self.h.rolling, spec)
        with self.writer.transaction():
            self.db.execute("""UPDATE rolling_preparation_jobs SET status='complete',
                dependency=?,metric=?,metric_hash=? WHERE id=?""",
                (stamp, raw, checksum, identity))
        return identity, raw

    def turn(self, *, job=None, after_slot=None):
        with self.writer.transaction():
            result = self.probe.step(self.job if job is None else job, after_slot=after_slot)
        self.assertFalse(self.db.in_transaction)
        return result

    def finish(self, *, job=None, after_slot=None, maximum=200):
        for _ in range(maximum):
            result = self.turn(job=job, after_slot=after_slot)
            if result.state in (READY, COMPLETE) or not result.continuation:
                return result
        self.fail('dispatch probe did not finish its bounded continuation')

    def pending(self, scope, lo, hi):
        proof = IntervalProof(scope, lo, hi, 'alchemy_finalized_stream', 'a'*64,
            dict(finalized=True, complete=True, scope=scope, lower_slot=lo,
                upper_slot=hi, lineage_hash=digest([scope, lo, hi])), NOW)
        with self.writer.transaction():
            self.h.lifecycle.defer_proof(proof)

    def fragment(self, points, *, scope=None):
        scope = self.h.scope_for('pump', self.job['address']) if scope is None else scope
        packed = zlib.compress(canonical(points).encode(), 1)
        checksum = hashlib.sha256(packed).hexdigest()
        self.db.execute('INSERT INTO candidate_coverage VALUES(?,?,?,?,?,?,?,?,?,?)',
            (scope, points[0][0], points[-1][1], len(points),
             min(point[2] for point in points), max(point[2] for point in points),
             packed, checksum, digest(points), 'alchemy_finalized_stream'))
        return scope

    def append_fragment(self, scope, points):
        packed = zlib.compress(canonical(points).encode(), 1)
        self.db.execute('''UPDATE candidate_coverage SET hi=?,count=?,last_available=?,
            points=?,hash=?,lineage=? WHERE scope=? AND lo=?''',
            (points[-1][1], len(points), max(point[2] for point in points), packed,
             hashlib.sha256(packed).hexdigest(), digest(points), scope, points[0][0]))

    def test_large_metric_reads_one_chunk_per_turn_and_authenticates_entire_tail(self):
        _, raw = self.cache(self.metric(padding=CHUNK*3+123))
        reads = []
        previous = 0
        for _ in range(100):
            result = self.turn()
            context = self.probe.context
            self.assertIsNotNone(context)
            read = context.get('read', 0)
            self.assertGreaterEqual(read, previous)
            self.assertLessEqual(read-previous, CHUNK)
            parser = context.get('parser')
            if parser is not None:
                self.assertLessEqual(len(parser.buffer), CHUNK)
            if read != previous:
                reads.append(read-previous)
            if result.state == READY:
                self.assertEqual(read, len(raw.encode()))
                self.assertTrue(context['verified'])
                break
            self.assertEqual(result.state, DEFERRED)
            self.assertTrue(result.continuation)
            previous = read
        else:
            self.fail('large authenticated metric did not become ready')
        self.assertGreaterEqual(len(reads), 4)
        self.assertEqual(result.interval, (10, 100))
        self.assertTrue(self.probe.current(self.job, result))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0], 0)

    def test_corrupt_full_hash_never_releases_early_gap(self):
        self.cache(self.metric(padding=CHUNK*2), checksum='0'*64)
        results = []
        with self.assertRaisesRegex(EvidenceUnavailable, 'historical_metric_corrupt'):
            for _ in range(100):
                result = self.turn()
                results.append(result.state)
                self.assertNotIn(result.state, (READY, COMPLETE))
        self.assertGreater(len(results), 3)
        self.assertIsNone(self.probe.context)

    def test_authenticated_malformed_json_tail_never_releases_gap(self):
        raw = canonical(self.metric(padding=CHUNK*2))[:-1]+',"upper_slot":100}'
        self.cache(None, raw=raw)
        with self.assertRaisesRegex(EvidenceUnavailable, 'dispatch_metric_json'):
            for _ in range(100):
                self.assertNotIn(self.turn().state, (READY, COMPLETE))

    def test_pending_publications_subtract_union_across_candidate_and_program(self):
        scope = self.h.scope_for('pump', self.job['address'])
        self.pending(scope, 10, 24)
        self.pending(scope, 40, 49)
        self.pending(program_scope('pump'), 30, 39)
        self.cache(self.metric())
        first = self.finish()
        self.assertEqual((first.state, first.interval, first.scanned_through, first.missing_any),
            (READY, (25, 29), 29, True))
        second = self.finish(after_slot=29)
        self.assertEqual((second.state, second.interval, second.scanned_through, second.missing_any),
            (READY, (50, 100), 100, True))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0], 0)

    def test_fully_pending_interval_waits_without_false_complete_or_job_retirement(self):
        self.pending(self.h.scope_for('pump', self.job['address']), 10, 100)
        self.cache(self.metric())
        result = self.finish()
        self.assertEqual((result.state, result.reason, result.scanned_through, result.missing_any),
            (DEFERRED, 'PENDING_PUBLICATION', 100, True))
        self.assertEqual(self.db.execute('SELECT status,deadline,lo,hi FROM acquisition_jobs WHERE id=?',
            (self.job['id'],)).fetchone(), ('pending', self.job['deadline'], 10, 100))

    def test_pending_proof_work_is_paged_and_preserves_uncovered_tail(self):
        scope = self.h.scope_for('pump', self.job['address'])
        for slot in range(10, 10+PAGE+5):
            self.pending(scope, slot, slot)
        self.cache(self.metric())
        proof_turns = 0
        for _ in range(150):
            result = self.turn()
            context = self.probe.context
            proof = None if context is None else context.get('proof')
            if proof is not None:
                proof_turns += 1
                for branch in proof['branches']:
                    self.assertLessEqual(len(branch['rows']), PAGE)
            if result.state == READY:
                break
        else:
            self.fail('paged proof subtraction made no progress')
        self.assertGreaterEqual(proof_turns, 4)
        self.assertEqual(result.interval, (10+PAGE+5, 100))

    def test_verified_fanout_reuses_parser_checkpoint_without_rereading_metric_tail(self):
        self.cache(self.metric([[10, 20], [30, 40]], padding=CHUNK*3))
        first = self.finish()
        self.assertEqual(first.interval, (10, 20))
        original = self.probe.db

        class NoMetricRead:
            def __getattr__(self, name):
                return getattr(original, name)

            def blobopen(self, *args, **kwargs):
                raise AssertionError('verified next fanout reread the full metric')

        self.probe.db = NoMetricRead()
        try:
            second = self.finish(after_slot=20)
        finally:
            self.probe.db = original
        self.assertEqual((second.state, second.interval, second.scanned_through, second.missing_any),
            (READY, (30, 40), 40, True))
        exhausted = self.finish(after_slot=40)
        self.assertEqual((exhausted.state, exhausted.reason,
                          exhausted.scanned_through, exhausted.missing_any),
            (DEFERRED, 'FANOUT_COMPLETE', 40, True))
        self.assertEqual(self.db.execute('SELECT status FROM acquisition_jobs WHERE id=?',
            (self.job['id'],)).fetchone()[0], 'pending')

    def test_only_authenticated_empty_missing_verdict_is_complete(self):
        self.cache(self.metric([]))
        result = self.finish()
        self.assertEqual((result.state, result.interval, result.scanned_through, result.missing_any),
            (COMPLETE, None, 100, False))
        self.assertTrue(self.probe.current(self.job, result))

    def test_boundary_wait_is_authenticated_but_not_complete(self):
        self.cache(dict(missing_intervals=None, boundary_state='LOWER_BOUND_PENDING_ROLLING_PUBLICATION'))
        result = self.finish()
        self.assertEqual((result.state, result.reason, result.scanned_through),
            (DEFERRED, 'PREPARATION_UNUSABLE', None))
        self.assertFalse(self.probe.current(self.job, result))

    def test_resolved_floor_excluding_original_request_cannot_expand_dispatch_scope(self):
        self.cache(self.metric([[20, 100]], lower_slot=20))
        result = self.finish()
        self.assertEqual((result.state, result.reason, result.scanned_through),
            (DEFERRED, 'PREPARATION_UNUSABLE', None))
        self.assertEqual(self.db.execute('SELECT lo,hi,deadline FROM acquisition_jobs WHERE id=?',
            (self.job['id'],)).fetchone(), (10, 100, self.job['deadline']))

    def test_source_job_tightening_revokes_old_claim_without_retiming_obligation(self):
        self.cache(self.metric())
        ready = self.finish()
        self.assertTrue(self.probe.current(self.job, ready))
        with self.writer.transaction():
            self.db.execute('UPDATE acquisition_jobs SET deadline=deadline-10 WHERE id=?',
                (self.job['id'],))
        self.assertFalse(self.probe.current(self.job, ready))
        changed = self.turn()
        self.assertEqual((changed.state, changed.reason), (DEFERRED, 'JOB_CHANGED'))
        self.assertEqual(self.db.execute('SELECT deadline,lo,hi FROM acquisition_jobs WHERE id=?',
            (self.job['id'],)).fetchone(), (self.job['deadline']-10, 10, 100))

    def test_binding_mutation_revokes_ready_claim(self):
        self.cache(self.metric())
        ready = self.finish()
        with self.writer.transaction():
            self.db.execute("UPDATE evidence_bindings SET market_address='different-market' "
                "WHERE family='pump' AND address=?", (self.job['address'],))
        self.assertFalse(self.probe.current(self.job, ready))

    def test_session_generation_change_and_original_deadline_revoke_claim(self):
        self.cache(self.metric())
        ready = self.finish()
        self.wall = self.job['deadline']
        self.assertFalse(self.probe.current(self.job, ready))
        self.wall = NOW
        self.assertTrue(self.probe.current(self.job, ready))
        with self.writer.transaction():
            self.db.execute("UPDATE prewarm_startup SET session='another-generation' WHERE id=1")
        self.assertFalse(self.probe.current(self.job, ready))

    def test_rollback_turn_discards_volatile_metric_progress_before_resume(self):
        self.cache(self.metric(padding=CHUNK*3))
        self.turn()  # Fresh metadata anchors the plan, before the first blob read.
        committed_turn = self.db.execute('SELECT turn FROM '+GUARD+' WHERE id=1').fetchone()[0]
        self.assertEqual(self.probe.context['read'], 0)
        with self.assertRaisesRegex(RuntimeError, 'rollback owner quantum'):
            with self.writer.transaction():
                result = self.probe.step(self.job)
                self.assertEqual(result.state, DEFERRED)
                self.assertGreater(self.probe.context['read'], 0)
                raise RuntimeError('rollback owner quantum')
        self.assertEqual(self.db.execute('SELECT turn FROM '+GUARD+' WHERE id=1').fetchone()[0],
            committed_turn)
        self.assertNotEqual(self.probe.context['turn'], committed_turn)
        result = self.turn()
        self.assertEqual(result.state, DEFERRED)
        self.assertEqual(self.probe.context['read'], 0)
        self.assertEqual(self.finish().state, READY)

    def test_strictly_above_hi_insert_keeps_fresh_authenticated_claim(self):
        self.cache(self.metric())
        ready = self.finish()
        with self.writer.transaction():
            self.fragment([[101, 101, NOW]], scope=program_scope('pump'))
        self.assertTrue(self.probe.current(self.job, ready))
        with self.writer.transaction():
            self.db.execute('INSERT INTO candidate_gaps(scope,lo,hi,created,repaired,reason) '
                'VALUES(?,?,?,?,NULL,?)', (program_scope('pump'), 100, 100, NOW, 'test-gap'))
        self.assertFalse(self.probe.current(self.job, ready))

    def test_authenticated_same_fragment_head_appends_do_not_starve_older_metric(self):
        points = [[10, 100, NOW]]
        with self.writer.transaction():
            scope = self.fragment(points, scope=program_scope('pump'))
        self.cache(self.metric(padding=CHUNK*3))
        self.turn()
        self.assertEqual(self.probe.context['phase'], 'metric')
        original_anchor = self.probe.context['anchor']
        for number in range(1, 100):
            points.append([100+number, 100+number, NOW])
            with self.writer.transaction():
                self.append_fragment(scope, points)
            result = self.turn()
            self.assertEqual(self.probe.context['anchor'], original_anchor)
            if result.state == READY:
                break
        else:
            self.fail('authenticated appends above job upper bound starved original work')
        self.assertTrue(self.probe.current(self.job, result))
        self.assertEqual(result.interval, (10, 100))
        rewritten = [list(point) for point in points]
        rewritten[0][2] = NOW-1
        with self.writer.transaction():
            self.append_fragment(scope, rewritten+[[points[-1][1]+1, points[-1][1]+1, NOW]])
        self.assertFalse(self.probe.current(self.job, result))

    def test_pending_preparation_anchor_is_transactional_and_not_published_on_rollback(self):
        waiting = self.finish()
        self.assertEqual((waiting.state, waiting.reason), (DEFERRED, 'PREPARATION_PENDING'))
        prep_id = self.probe.context['job']['id']
        row = self.db.execute('SELECT body FROM rolling_preparation_jobs WHERE id=?', (prep_id,)).fetchone()
        self.assertIsNotNone(row)
        spec = json.loads(row[0])
        raw = canonical(self.metric())
        checksum = hashlib.sha256(raw.encode()).hexdigest()
        stamp = dependency_stamp(self.h.rolling, spec)
        with self.assertRaisesRegex(RuntimeError, 'rollback applied preparation'):
            with self.writer.transaction():
                self.db.execute("UPDATE rolling_preparation_jobs SET status='complete',"
                    'dependency=?,metric=?,metric_hash=? WHERE id=?', (stamp, raw, checksum, prep_id))
                self.assertTrue(self.probe.preparation_applied(prep_id, checksum))
                self.assertEqual(self.db.execute('SELECT anchored FROM '+GUARD+' WHERE id=1').fetchone()[0], 1)
                raise RuntimeError('rollback applied preparation')
        self.assertEqual(self.db.execute('SELECT status FROM rolling_preparation_jobs WHERE id=?',
            (prep_id,)).fetchone()[0], 'pending')
        self.assertEqual(self.db.execute('SELECT anchored FROM '+GUARD+' WHERE id=1').fetchone()[0], 0)
        self.assertEqual(self.turn().reason, 'PREPARATION_PENDING')
        with self.assertRaisesRegex(EvidenceUnavailable, 'dispatch_probe_anchor_transaction'):
            self.probe.preparation_applied(prep_id, checksum)
        with self.writer.transaction():
            self.db.execute("UPDATE rolling_preparation_jobs SET status='complete',"
                'dependency=?,metric=?,metric_hash=? WHERE id=?', (stamp, raw, checksum, prep_id))
            self.assertTrue(self.probe.preparation_applied(prep_id, checksum))
        self.assertEqual(self.finish().state, READY)

    def test_temp_invalidation_does_not_require_udf_after_older_source_reopens_database(self):
        self.fragment([[10, 100, NOW]])
        persistent = [sql for sql, in self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger'")]
        temporary = [sql for sql, in self.db.execute(
            "SELECT sql FROM sqlite_temp_master WHERE type='trigger'")]
        self.assertFalse(any('dispatch_probe_prefix_append_v1' in sql for sql in persistent))
        self.assertTrue(any('dispatch_probe_prefix_append_v1' in sql for sql in temporary))
        self.close_writer()
        with sqlite3.connect(self.path, isolation_level=None) as previous_source:
            previous_source.execute('UPDATE candidate_coverage SET count=count WHERE lo=10')
            self.assertEqual(previous_source.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
