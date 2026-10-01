"""M1 regression: a native commit must survive interruption of its completion read.

Real SQLite, owner admission, immutable archiver and ledger; no pressure profile.
"""
from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import traceback
import unittest
import websockets
from unittest.mock import patch

from meme_machine import solana_evidence_service as service
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceWriter
from meme_machine.solana_maintenance_runtime import ArchiveFlight, MaintenanceRuntime
from meme_machine.solana_provider_config import AlchemyEndpoint
from tests.maintenance_production_harness import Clock, ENDPOINT, SCOPES, ingest, rows
from tests.test_production_maintenance_arbiter import finalized_frontier

EVIDENCE = {}
PROGRESS_SELECT = (
    'SELECT scope,side,at,units,record_at,records '
    'FROM maintenance_progress ORDER BY scope,side LIMIT '
)

def public_key(index):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    raw = index.to_bytes(32, 'big')
    leading = len(raw) - len(raw.lstrip(b'\0'))
    value = int.from_bytes(raw, 'big')
    encoded = ''
    while value:
        value, digit = divmod(value, 58)
        encoded = alphabet[digit] + encoded
    return '1' * leading + encoded

def failure(exc):
    return dict(type=type(exc).__name__, message=str(exc),
                traceback=''.join(traceback.format_exception(exc)))

class M1NativeCompletionTests(unittest.TestCase):
    def test_urgent_completion_clears_decision_before_next_ordinary_admission(self):
        clock = Clock()
        box = {}
        events = []
        accepted_futures = []
        EVIDENCE.clear()
        EVIDENCE.update(kind='m1_native_completion_regression',
                        production_base='dc08f9064cf5e37b63f383f52aa709d0afc1723f',
                        material_executions=0, completion_assertion_weakened=False)

        def event(name, **extra):
            events.append(dict(event=name, monotonic=clock.monotonic(), **extra))

        with tempfile.TemporaryDirectory() as td, \
             patch.object(service, 'time', clock), \
             patch.object(websockets, 'connect',
                          side_effect=AssertionError('provider_access_forbidden')) as transport:
            def factory():
                state = service.ServiceState(Path(td) / 'db',
                                             AlchemyEndpoint.parse(ENDPOINT))
                state.writer.clock = clock.time
                # Ledger rows are earned by a real native archive, never inserted
                # or credited directly. Valid account scopes fit the 260 bound.
                ledger_records = []
                for index in range(1, 129):
                    scope = 'account:' + public_key(index)
                    ledger_records.extend(replace(row, kind='account')
                                          for row in rows(clock, scope, 1, tag='ledger'))
                ingest(state.writer, ledger_records)
                archived = state.writer.archive(clock.time() - 180)
                if archived != 128:
                    raise AssertionError(('native_seed_archive_count', archived))
                # A genuine recovery excess survives the 512-record slice.
                ingest(state.writer, rows(clock, SCOPES[0], 1800, tag='recovery'))
                finalized_frontier(state, clock, SCOPES[0])
                runtime = MaintenanceRuntime(state, monotonic=clock.monotonic,
                                             wall=clock.time)
                snapshot = state.archive_plan()
                plan, receipt = EvidenceWriter.prepare_and_write_archive(
                    state.writer.path, snapshot)
                if len(plan) != 1000:
                    raise AssertionError(('native_receipt_records', len(plan)))
                flight = ArchiveFlight(pending=(plan, receipt), submitted=clock.monotonic(),
                                       generation=runtime.generation)
                box.update(state=state, runtime=runtime, flight=flight)
                EVIDENCE.update(seed_records=1928, seed_archived=archived,
                                native_progress_rows_before=state.writer.db.execute(
                                    'SELECT COUNT(*) FROM maintenance_progress').fetchone()[0],
                                receipt_records=len(plan), initial_hot_debt=1800,
                                generation=runtime.generation,
                                completion_recovery_available=hasattr(runtime, '_complete_decision'))
                return state

            owner = PriorityOwner(factory, clock=clock.monotonic)
            def accept(fn, priority, label):
                event(label + '_submit_called')
                future = owner.submit(fn, priority=priority)
                accepted_futures.append(future)
                event(label + '_accepted', sequence=owner.sequence)
                return future

            try:
                owner.ready.result(timeout=20)
                runtime, flight = box['runtime'], box['flight']
                progress_reads = [0]

                def urgent(state):
                    event('urgent_owner_entry')
                    value = state.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]
                    event('urgent_completed', records=value)
                    return value

                def trace(sql):
                    if not sql.startswith(PROGRESS_SELECT):
                        return
                    progress_reads[0] += 1
                    event('native_progress_select', ordinal=progress_reads[0], sql=sql)
                    # First SELECT is observation; second is completion finally,
                    # after the actual bounded native archive commit.
                    if progress_reads[0] == 2:
                        box['urgent_future'] = accept(urgent, 0, 'urgent')

                def first_turn(state):
                    event('maintenance_owner_entry')
                    state.writer.db.set_trace_callback(trace)
                    try:
                        return runtime.turn(flight, clock.monotonic())
                    finally:
                        state.writer.db.set_trace_callback(None)
                        event('maintenance_owner_exit',
                              interrupted=state.writer._background_sql_interrupted)

                accepted = accept(first_turn, 4, 'maintenance')
                EVIDENCE['first_request_accepted'] = True
                first_error = None
                try:
                    accepted.result(timeout=20)
                except BaseException as exc:
                    first_error = failure(exc)
                EVIDENCE.update(first_future_done=accepted.done(), first_error=first_error)

                urgent_future = box.get('urgent_future')
                if urgent_future is not None:
                    EVIDENCE['urgent_result'] = urgent_future.result(timeout=10)

                def snapshot_state(state):
                    return dict(
                        pending=None if runtime.arbiter.pending is None else asdict(runtime.arbiter.pending),
                        runtime_failure=runtime.failure, arbiter_failed=runtime.arbiter.failed,
                        hot=state.writer.db.execute(
                            'SELECT COUNT(*) FROM records WHERE scope=? AND body IS NOT NULL',
                            (SCOPES[0],)).fetchone()[0],
                        archive_progress=state.writer.db.execute(
                            "SELECT units,records FROM maintenance_progress WHERE scope=? AND side='archive'",
                            (SCOPES[0],)).fetchone(),
                        episodes=state.writer.db.execute(
                            'SELECT scope,side,source_deadline,wall_started,envelope '
                            'FROM maintenance_episodes ORDER BY scope,side').fetchall(),
                        integrity=state.writer.db.execute('PRAGMA integrity_check').fetchone()[0],
                        transaction_open=state.writer.db.in_transaction,
                        events=list(runtime.ring),
                        receipt_remaining=len(flight.pending[0]) if flight.pending else 0)

                first_state = accept(snapshot_state, 2, 'snapshot').result(timeout=10)
                EVIDENCE['after_interruption'] = first_state
                # Capture actual subsequent native error before the completion
                # assertion. This is not an expected-failure test.
                second_error = None
                second = accept(lambda state: runtime.turn(flight, clock.monotonic()),
                                4, 'next_maintenance')
                try:
                    second.result(timeout=20)
                except BaseException as exc:
                    second_error = failure(exc)
                EVIDENCE.update(next_future_done=second.done(), next_error=second_error,
                                after_next_turn=accept(snapshot_state, 2, 'final_snapshot').result(timeout=10),
                                owner_metrics=owner.telemetry(), trace_events=events,
                                provider_calls=transport.call_count)

                self.assertIsNotNone(urgent_future, 'urgent work must actually enter owner.submit()')
                self.assertTrue(urgent_future.done(), 'accepted urgent work must complete')
                self.assertTrue(accepted.done(), 'accepted maintenance future must complete')
                self.assertEqual(next(e['ordinal'] for e in events if e['event'] == 'native_progress_select' and e['ordinal'] == 2), 2,
                                 'urgent admission must target the completion read')
                self.assertIsNotNone(first_error)
                self.assertEqual(first_error['message'], 'evidence_background_yield')
                self.assertEqual(first_state['hot'], 1288, 'a real bounded native slice must commit')
                self.assertEqual(first_state['archive_progress'], (512, 512))
                self.assertEqual(first_state['receipt_remaining'], 488)
                self.assertEqual(first_state['integrity'], 'ok')
                self.assertFalse(first_state['transaction_open'])
                self.assertIsNone(first_state['runtime_failure'], 'cooperative interruption must remain nonfatal')
                self.assertEqual(first_state['episodes'], EVIDENCE['after_next_turn']['episodes'],
                                 'the original durable recovery episode must not reset')
                self.assertEqual(transport.call_count, 0)
                # Required assertion: no skip/expectedFailure, manual pending reset,
                # replacement complete() or fabricated native progress.
                self.assertIsNone(first_state['pending'],
                                  'M1: interrupted native completion left an accepted decision in flight')
                self.assertIsNone(second_error,
                                  'the next ordinary native maintenance admission must remain usable')
            finally:
                owner.close()
                EVIDENCE.update(owner_thread_joined=not owner.thread.is_alive(),
                                accepted_future_count=len(accepted_futures),
                                all_accepted_futures_done=all(f.done() for f in accepted_futures))


from concurrent.futures import Future
from contextlib import contextmanager
import sqlite3

from meme_machine.solana_evidence_plane import EvidenceUnavailable
from tests.test_production_maintenance_arbiter import native_runtime, orphan_chunk


def seed_retirement(state, clock, count=600):
    ingest(state.writer, rows(clock, SCOPES[0], count, tag='m1-retire'))
    while state.writer.archive(clock.time() - 180):
        pass


def ledger(state, side):
    return dict((scope, (units, records)) for scope, units, records in
                state.writer.db.execute(
                    'SELECT scope,units,records FROM maintenance_progress WHERE side=?',
                    (side,)))


class M1CompletionSemanticsTests(unittest.TestCase):
    @contextmanager
    def owner_runtime(self, seed=seed_retirement):
        clock, box = Clock(), {}
        with tempfile.TemporaryDirectory() as td, patch.object(service, 'time', clock):
            def factory():
                state = service.ServiceState(Path(td) / 'db',
                                             AlchemyEndpoint.parse(ENDPOINT))
                state.writer.clock = clock.time
                if seed is not None:
                    seed(state, clock)
                runtime = MaintenanceRuntime(state, monotonic=clock.monotonic,
                                             wall=clock.time)
                box.update(state=state, runtime=runtime)
                return state
            owner = PriorityOwner(factory, clock=clock.monotonic)
            try:
                owner.ready.result(20)
                yield owner, box, clock
            finally:
                owner.close()
                self.assertFalse(owner.thread.is_alive())

    def assert_completed_yield(self, runtime):
        self.assertIsNone(runtime.arbiter.pending)
        self.assertIsNone(runtime.failure)
        self.assertFalse(runtime.arbiter.failed)
        self.assertEqual(runtime.ring[-1]['reason'], 'cooperative_yield')
        self.assertEqual(runtime.ring[-1]['completion'], 'completed')

    def test_interruption_before_mutation_completes_without_progress(self):
        with native_runtime() as (state, runtime, clock):
            seed_retirement(state, clock)
            runtime._demands(runtime.adapter.observe(runtime.generation))
            origin = dict(runtime.arbiter.origin)
            with patch.object(state, 'retention',
                              side_effect=EvidenceUnavailable('evidence_background_yield')):
                with self.assertRaisesRegex(EvidenceUnavailable, '^evidence_background_yield$'):
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assert_completed_yield(runtime)
            self.assertEqual(runtime.arbiter.origin, origin)
            self.assertEqual(runtime.ring[-1]['durable_records'], {})
            self.assertEqual(ledger(state, 'retirement'), {})
            self.assertIsNone(runtime.arbiter.last_side)
            result = runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertGreater(result['retention_outcome'].retired_records, 0)
            self.assertIsNone(runtime.arbiter.pending)

    def test_preemptible_preparation_sql_interrupt_is_cooperative_and_zero_progress(self):
        with native_runtime() as (state, runtime, clock):
            seed_retirement(state, clock)
            interrupted = []
            def handler():
                if interrupted:
                    return 0
                interrupted.append(True)
                state.writer._background_sql_interrupted = True
                return 1
            def preparation():
                state.writer.db.execute("""WITH RECURSIVE n(x) AS
                    (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<10000)
                    SELECT sum(x) FROM n""").fetchone()
                self.fail('the real preparation SELECT must be interrupted')
            # Position the request after choose(), without replacing native SQL.
            def chosen(*args, **kwargs):
                value = native_choose(*args, **kwargs)
                state.writer._owner_progress_handler = handler
                state.writer.db.set_progress_handler(handler, 1000)
                return value
            native_choose = runtime.arbiter.choose
            with patch.object(runtime.arbiter, 'choose', side_effect=chosen), \
                 patch.object(state, 'retention', side_effect=preparation):
                with self.assertRaisesRegex(EvidenceUnavailable, '^evidence_background_yield$') as error:
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertEqual(error.exception.__cause__.sqlite_errorcode, sqlite3.SQLITE_INTERRUPT)
            self.assert_completed_yield(runtime)
            self.assertEqual(ledger(state, 'retirement'), {})
            self.assertFalse(state.writer.db.in_transaction)

    def test_urgent_request_during_atomic_retirement_defers_until_durable_slice(self):
        with self.owner_runtime() as (owner, box, clock):
            urgent = []
            def turn(state):
                def trace(sql):
                    if not urgent and sql.startswith('DELETE FROM records'):
                        self.assertTrue(state.writer._retention_atomic)
                        urgent.append(owner.submit(lambda s: 'urgent-ran', priority=0))
                state.writer.db.set_trace_callback(trace)
                try:
                    return box['runtime'].turn(ArchiveFlight(), clock.monotonic())
                finally:
                    state.writer.db.set_trace_callback(None)
            result = owner.submit(turn, priority=4).result(20)
            self.assertEqual(urgent[0].result(20), 'urgent-ran')
            outcome = result['retention_outcome']
            self.assertEqual(outcome.retired_records, 256)
            self.assertEqual(outcome.committed_slices, 1)
            self.assertTrue(outcome.interrupted)
            self.assertEqual(outcome.yield_reason, 'urgent')
            snapshot = owner.submit(lambda s: (
                ledger(s, 'retirement'), s.writer.db.in_transaction,
                s.writer._background_sql_interrupted), priority=2).result(20)
            self.assertEqual(snapshot[0][SCOPES[0]][1], 256)
            self.assertFalse(snapshot[1])
            self.assertFalse(snapshot[2])
            self.assertIsNone(box['runtime'].arbiter.pending)
            self.assertEqual(box['runtime'].ring[-1]['durable_records'], {SCOPES[0]: 256})

    def test_forced_sql_interrupt_rolls_back_atomic_retirement_without_credit(self):
        with native_runtime() as (state, runtime, clock):
            seed_retirement(state, clock)
            interrupted = []
            def trace(sql):
                if not interrupted and sql.startswith('DELETE FROM records'):
                    self.assertTrue(state.writer._retention_atomic)
                    interrupted.append(True)
                    state.writer._background_sql_interrupted = True
                    state.writer.db.interrupt()
            state.writer.db.set_trace_callback(trace)
            try:
                result = runtime.turn(ArchiveFlight(), clock.monotonic())
            finally:
                state.writer.db.set_trace_callback(None)
            outcome = result['retention_outcome']
            self.assertTrue(outcome.interrupted)
            self.assertFalse(outcome.made_progress)
            self.assertEqual(outcome.committed_slices, 0)
            self.assertEqual(ledger(state, 'retirement'), {})
            self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 600)
            self.assertFalse(state.writer.db.in_transaction)
            self.assertIsNone(runtime.arbiter.pending)
            self.assertIsNone(runtime.arbiter.last_side)
            self.assertEqual(runtime.ring[-1]['durable_records'], {})

    def test_committed_retirement_then_yield_keeps_durable_progress(self):
        with native_runtime() as (state, runtime, clock):
            seed_retirement(state, clock)
            native = state.retention
            def committed_then_yield():
                outcome = native()
                self.assertEqual(outcome.retired_records, 600)
                clock.advance(.1)
                raise EvidenceUnavailable('evidence_background_yield')
            with patch.object(state, 'retention', side_effect=committed_then_yield):
                with self.assertRaisesRegex(EvidenceUnavailable, '^evidence_background_yield$'):
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assert_completed_yield(runtime)
            self.assertEqual(ledger(state, 'retirement')[SCOPES[0]][1], 600)
            self.assertEqual(runtime.ring[-1]['durable_records'], {SCOPES[0]: 600})
            self.assertEqual(runtime.arbiter.origin['retirement', SCOPES[0]], .1)
            runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertIsNone(runtime.arbiter.pending)

    def test_committed_housekeeping_then_yield_renews_only_its_committed_owner(self):
        with native_runtime() as (state, runtime, clock):
            orphan_chunk(state.writer, 'm1-housekeeping')
            native = state.retention
            def committed_then_yield():
                self.assertEqual(native().housekeeping_rows, 1)
                clock.advance(.1)
                raise EvidenceUnavailable('evidence_background_yield')
            with patch.object(state, 'retention', side_effect=committed_then_yield):
                with self.assertRaisesRegex(EvidenceUnavailable, '^evidence_background_yield$'):
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assert_completed_yield(runtime)
            self.assertEqual(ledger(state, 'retirement'), {'__housekeeping__': (1, 0)})
            self.assertEqual(runtime.ring[-1]['durable_progress'], {'__housekeeping__': 1})
            self.assertEqual(runtime.ring[-1]['durable_records'], {})
            self.assertEqual(runtime.arbiter.origin['retirement', '__housekeeping__'], .1)

    def test_no_progress_archive_preparation_yield_does_not_renew_service(self):
        with native_runtime() as (state, runtime, clock):
            ingest(state.writer, rows(clock, SCOPES[0], 5, tag='m1-plan'))
            runtime._demands(runtime.adapter.observe(runtime.generation))
            before = runtime.arbiter.origin['archive', SCOPES[0]]
            flight = ArchiveFlight()
            with patch.object(state, 'archive_plan',
                              side_effect=EvidenceUnavailable('evidence_background_yield')):
                with self.assertRaisesRegex(EvidenceUnavailable, '^evidence_background_yield$'):
                    runtime.turn(flight, clock.monotonic())
            self.assert_completed_yield(runtime)
            self.assertEqual(ledger(state, 'archive'), {})
            self.assertEqual(runtime.arbiter.origin['archive', SCOPES[0]], before)
            self.assertIsNone(runtime.arbiter.last_side)
            self.assertTrue(flight.idle)

    def test_native_progress_failure_preserves_unknown_identity_and_committed_ledger(self):
        with native_runtime() as (state, runtime, clock):
            seed_retirement(state, clock)
            decisions = []
            native_choose = runtime.arbiter.choose
            def chosen(**kwargs):
                value = native_choose(**kwargs)
                decisions.append(value)
                return value
            with patch.object(runtime.arbiter, 'choose', side_effect=chosen), \
                 patch.object(runtime, '_native_progress',
                              side_effect=sqlite3.OperationalError('disk I/O error')):
                with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_storage_failure') as error:
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertIsInstance(error.exception.__cause__, sqlite3.OperationalError)
            self.assertIs(runtime.arbiter.pending, decisions[0])
            self.assertIsNotNone(runtime.failure)
            self.assertTrue(runtime.arbiter.failed)
            self.assertEqual(runtime.ring[-1]['completion'], 'failed_closed')
            self.assertTrue(runtime.ring[-1]['completion_pending'])
            self.assertNotIn('durable_progress', runtime.ring[-1])
            self.assertEqual(ledger(state, 'retirement')[SCOPES[0]][1], 600)
            self.assertIsNone(runtime.arbiter.last_side)
            with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_admission_revoked'):
                runtime.turn(ArchiveFlight(), clock.monotonic())
            # A fresh runtime reconstructs native committed progress, never the
            # abandoned exception's guessed return value.
            restarted = MaintenanceRuntime(state, monotonic=clock.monotonic, wall=clock.time)
            restarted.turn(ArchiveFlight(), clock.monotonic())
            self.assertIsNone(restarted.arbiter.pending)
            self.assertEqual(ledger(state, 'retirement')[SCOPES[0]][1], 600)

    def test_repeated_progress_read_yield_fails_closed_without_unbounded_retry(self):
        with native_runtime() as (state, runtime, clock):
            seed_retirement(state, clock)
            with patch.object(runtime, '_native_progress',
                              side_effect=EvidenceUnavailable('evidence_background_yield')) as read, \
                 patch.object(runtime.arbiter, 'complete', wraps=runtime.arbiter.complete) as complete:
                with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_completion_unavailable'):
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertEqual(read.call_count, 2)
            self.assertEqual(complete.call_count, 0)
            self.assertIsNotNone(runtime.arbiter.pending)
            self.assertTrue(runtime.arbiter.failed)
            self.assertIsNotNone(runtime.failure)
            self.assertEqual(runtime.ring[-1]['completion'], 'failed_closed')
            self.assertEqual(ledger(state, 'retirement')[SCOPES[0]][1], 600)
            self.assertIsNone(state.writer._owner_progress_handler)
            self.assertIsNone(runtime.arbiter.last_side)

    def test_fatal_native_error_is_not_masked_by_recovered_reporting_yield(self):
        with native_runtime() as (state, runtime, clock):
            seed_retirement(state, clock)
            native_read = runtime._native_progress
            reads = []
            def reporting(*args):
                reads.append(True)
                if len(reads) == 1:
                    raise EvidenceUnavailable('evidence_background_yield')
                return native_read(*args)
            with patch.object(state, 'retention', side_effect=sqlite3.OperationalError('disk I/O error')), \
                 patch.object(runtime, '_native_progress', side_effect=reporting):
                with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_storage_failure') as error:
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertEqual(str(error.exception.__cause__), 'disk I/O error')
            self.assertEqual(runtime.ring[-1]['reason'], 'fail_closed')
            self.assertTrue(runtime.ring[-1]['completion_read_interrupted'])
            self.assertIsNone(runtime.arbiter.pending)
            self.assertEqual(ledger(state, 'retirement'), {})
            self.assertIsNone(runtime.arbiter.last_side)
            self.assertTrue(runtime.arbiter.failed)

    def test_actual_sql_error_after_real_interrupt_is_not_misclassified_by_owner(self):
        with self.owner_runtime() as (owner, box, clock):
            urgent = []
            def turn(state):
                def failing_native():
                    urgent.append(owner.submit(lambda s: True, priority=0))
                    try:
                        state.writer.db.execute("""WITH RECURSIVE n(x) AS
                            (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<10000)
                            SELECT sum(x) FROM n""").fetchone()
                    except sqlite3.OperationalError as exc:
                        self.assertEqual(exc.sqlite_errorcode, sqlite3.SQLITE_INTERRUPT)
                    else:
                        self.fail('a real owner interrupt is required before the storage error')
                    # Actual SQLITE_ERROR, with the owner's earlier interrupt
                    # flag still set. It is not a cooperative interruption.
                    state.writer.db.execute('SELECT m1_missing_column FROM records').fetchone()
                with patch.object(state, 'retention', side_effect=failing_native):
                    return box['runtime'].turn(ArchiveFlight(), clock.monotonic())
            with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_storage_failure') as error:
                owner.submit(turn, priority=4).result(20)
            self.assertEqual(error.exception.__cause__.sqlite_errorcode, sqlite3.SQLITE_ERROR)
            self.assertIn('no such column', str(error.exception.__cause__))
            self.assertTrue(urgent[0].result(20))
            runtime = box['runtime']
            self.assertIsNotNone(runtime.failure)
            self.assertTrue(runtime.arbiter.failed)
            self.assertEqual(runtime.ring[-1]['reason'], 'fail_closed')
            self.assertIsNone(runtime.arbiter.pending)
            self.assertIsNone(runtime.arbiter.last_side)

    def test_arbitrary_exception_named_like_yield_is_still_fatal(self):
        with native_runtime() as (state, runtime, clock):
            orphan_chunk(state.writer, 'm1-fake-yield')
            with patch.object(state, 'retention', side_effect=RuntimeError('evidence_background_yield')):
                with self.assertRaisesRegex(RuntimeError, '^evidence_background_yield$'):
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertIsNotNone(runtime.failure)
            self.assertTrue(runtime.arbiter.failed)
            self.assertEqual(runtime.ring[-1]['reason'], 'fail_closed')
            self.assertIsNone(runtime.arbiter.last_side)

    def test_complete_failure_does_not_clear_identity_or_erase_known_durable_progress(self):
        with native_runtime() as (state, runtime, clock):
            seed_retirement(state, clock)
            with patch.object(runtime.arbiter, 'complete',
                              side_effect=EvidenceUnavailable('maintenance_completion_identity')) as complete:
                with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_completion_identity'):
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertEqual(complete.call_count, 1)
            self.assertIsNotNone(runtime.arbiter.pending)
            self.assertEqual(runtime.ring[-1]['durable_records'], {SCOPES[0]: 600})
            self.assertEqual(runtime.ring[-1]['completion'], 'failed_closed')
            self.assertTrue(runtime.arbiter.failed)
            self.assertIsNone(runtime.arbiter.last_side)

    def test_wrong_equal_decision_identity_and_duplicate_completion_are_rejected(self):
        with native_runtime() as (state, runtime, clock):
            orphan_chunk(state.writer, 'm1-identity')
            observation = runtime.adapter.observe(runtime.generation)
            needs = runtime._demands(observation)
            decision = runtime.arbiter.choose(generation=runtime.generation,
                as_of=observation.monotonic, now=clock.monotonic(), needs=needs,
                ready=dict(archive=True, retirement=True))
            state.retention()
            progress, records = runtime._native_progress(runtime.last_progress, needs, decision.side)
            with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_completion_identity'):
                runtime.arbiter.complete(replace(decision), clock.monotonic(), progress,
                                         record_progress=records)
            self.assertIs(runtime.arbiter.pending, decision)
            self.assertIsNone(runtime.arbiter.last_side)
            runtime.arbiter.complete(decision, clock.monotonic(), progress, record_progress=records)
            origins = dict(runtime.arbiter.origin)
            with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_completion_identity'):
                runtime.arbiter.complete(decision, clock.monotonic(), progress, record_progress=records)
            self.assertIsNone(runtime.arbiter.pending)
            self.assertEqual(runtime.arbiter.origin, origins)
            self.assertEqual(ledger(state, 'retirement'), {'__housekeeping__': (1, 0)})

    def test_completion_callback_raising_after_completion_never_completes_twice(self):
        with native_runtime() as (state, runtime, clock):
            orphan_chunk(state.writer, 'm1-post-complete')
            native = runtime.arbiter.complete
            def completed_then_error(*args, **kwargs):
                native(*args, **kwargs)
                raise RuntimeError('m1_reporting_failure')
            with patch.object(runtime.arbiter, 'complete', side_effect=completed_then_error) as complete:
                with self.assertRaisesRegex(RuntimeError, 'm1_reporting_failure'):
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertEqual(complete.call_count, 1)
            self.assertIsNone(runtime.arbiter.pending)
            self.assertIsNotNone(runtime.failure)
            self.assertEqual(ledger(state, 'retirement'), {'__housekeeping__': (1, 0)})
            with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_admission_revoked'):
                runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertEqual(complete.call_count, 1)

    def test_repeated_archive_receipt_retry_after_commit_is_idempotent(self):
        with native_runtime() as (state, runtime, clock):
            ingest(state.writer, rows(clock, SCOPES[0], 5, tag='m1-receipt'))
            plan, receipt = EvidenceWriter.prepare_and_write_archive(state.writer.path, state.archive_plan())
            flight = ArchiveFlight(pending=(plan, receipt), submitted=clock.monotonic(),
                                   generation=runtime.generation)
            native = state.archive_commit_slice_and_plan
            def committed_then_yield(*args):
                native(*args)
                clock.advance(.1)
                raise EvidenceUnavailable('evidence_background_yield')
            with patch.object(state, 'archive_commit_slice_and_plan', side_effect=committed_then_yield):
                with self.assertRaisesRegex(EvidenceUnavailable, '^evidence_background_yield$'):
                    runtime.turn(flight, clock.monotonic())
                first_gap = runtime.arbiter.max_scope_gap['archive', SCOPES[0]]
                self.assertIs(flight.pending[1], receipt)
                self.assertEqual(runtime.ring[-1]['durable_records'], {SCOPES[0]: 5})
                # Let unchanged selection service native retirement first, if it
                # is due. The original receipt must eventually be retried.
                for _ in range(6):
                    try:
                        runtime.turn(flight, clock.monotonic())
                    except EvidenceUnavailable as exc:
                        self.assertEqual(str(exc), 'evidence_background_yield')
                        break
                else:
                    self.fail('original durable receipt was not retried')
                self.assertEqual(runtime.ring[-1]['durable_records'], {})
                self.assertEqual(runtime.arbiter.max_scope_gap['archive', SCOPES[0]], first_gap)
                self.assertIsNone(runtime.arbiter.pending)
            # Reconstruct accounting from the durable ledger before the same
            # receipt's final idempotent acknowledgement.
            restarted = MaintenanceRuntime(state, monotonic=clock.monotonic, wall=clock.time)
            restarted.turn(flight, clock.monotonic())
            self.assertIsNone(flight.pending)
            self.assertIsNone(restarted.arbiter.pending)
            self.assertEqual(ledger(state, 'archive')[SCOPES[0]], (5, 5))
            self.assertEqual(restarted.ring[-1]['durable_records'], {})
            self.assertEqual(len(list((state.writer.path.parent / (state.writer.path.name + '.archive')).glob('*.gz'))), 1)

    def test_native_archive_worker_remains_pending_without_duplicate_preparation(self):
        with native_runtime() as (state, runtime, clock):
            ingest(state.writer, rows(clock, SCOPES[0], 5, tag='m1-worker'))
            flight = ArchiveFlight()
            runtime.turn(flight, clock.monotonic())
            self.assertIsNotNone(flight.prepared)
            future = Future()
            flight.attach(future, clock.monotonic(), runtime.generation)
            with patch.object(state, 'archive_plan', wraps=state.archive_plan) as plan:
                runtime.turn(flight, clock.monotonic())
            self.assertIs(flight.future, future)
            self.assertFalse(future.done())
            self.assertIsNone(runtime.arbiter.pending)
            self.assertEqual(plan.call_count, 0)
            self.assertEqual(ledger(state, 'archive'), {})
            clock.advance(runtime.leases.worker)
            with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_archive_worker_lease_exceeded'):
                runtime.turn(flight, clock.monotonic())
            self.assertIs(flight.future, future)

    def test_generation_change_before_selection_fails_closed(self):
        with native_runtime() as (state, runtime, clock):
            orphan_chunk(state.writer, 'm1-generation')
            state.fence.session = 'changed-generation'
            with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_generation_changed'):
                runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertEqual(runtime.arbiter.sequence, 0)
            self.assertIsNone(runtime.arbiter.pending)
            self.assertEqual(ledger(state, 'retirement'), {})

    def test_generation_change_after_commit_cannot_credit_old_decision(self):
        with native_runtime() as (state, runtime, clock):
            seed_retirement(state, clock)
            native = runtime._native_progress
            def report_then_change(*args):
                result = native(*args)
                state.fence.session = 'changed-after-commit'
                return result
            with patch.object(runtime, '_native_progress', side_effect=report_then_change):
                with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_generation_changed'):
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertTrue(runtime.arbiter.failed)
            self.assertIsNotNone(runtime.arbiter.pending)
            self.assertIsNone(runtime.arbiter.last_side)
            self.assertEqual(ledger(state, 'retirement')[SCOPES[0]][1], 600)
            self.assertEqual(runtime.ring[-1]['durable_records'], {SCOPES[0]: 600})

    def test_execution_lease_expiration_preserves_commit_but_revokes_service_success(self):
        with native_runtime() as (state, runtime, clock):
            seed_retirement(state, clock)
            native = state.retention
            def late_commit():
                result = native()
                clock.advance(runtime.leases.execution + .1)
                return result
            with patch.object(state, 'retention', side_effect=late_commit):
                with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_execution_lease_exceeded'):
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertTrue(runtime.arbiter.failed)
            self.assertIsNotNone(runtime.failure)
            self.assertIsNone(runtime.arbiter.last_side)
            self.assertEqual(runtime.ring[-1]['completion'], 'failed_closed')
            self.assertEqual(runtime.ring[-1]['durable_records'], {SCOPES[0]: 600})
            self.assertEqual(ledger(state, 'retirement')[SCOPES[0]][1], 600)
            self.assertEqual(list(runtime.arbiter.rates['retirement']), [])

    def test_late_reporting_retry_still_enforces_execution_lease(self):
        with native_runtime() as (state, runtime, clock):
            seed_retirement(state, clock)
            native = runtime._native_progress
            reads = []
            def interrupted_then_late(*args):
                reads.append(True)
                if len(reads) == 1:
                    raise EvidenceUnavailable('evidence_background_yield')
                clock.advance(runtime.leases.execution + .1)
                return native(*args)
            with patch.object(runtime, '_native_progress', side_effect=interrupted_then_late):
                with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_execution_lease_exceeded'):
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertEqual(len(reads), 2)
            self.assertTrue(runtime.arbiter.failed)
            self.assertIsNone(runtime.arbiter.last_side)
            self.assertEqual(ledger(state, 'retirement')[SCOPES[0]][1], 600)
            self.assertEqual(runtime.ring[-1]['durable_records'], {SCOPES[0]: 600})

    def test_uncommitted_outer_archive_transaction_cannot_earn_progress(self):
        with native_runtime() as (state, runtime, clock):
            ingest(state.writer, rows(clock, SCOPES[0], 5, tag='m1-outer'))
            plan, receipt = EvidenceWriter.prepare_and_write_archive(state.writer.path, state.archive_plan())
            flight = ArchiveFlight(pending=(plan, receipt), submitted=clock.monotonic(),
                                   generation=runtime.generation)
            def uncommitted(*args):
                state.writer.db.execute('BEGIN IMMEDIATE')
                state.writer.commit_archive(plan, receipt)
                raise EvidenceUnavailable('evidence_background_yield')
            try:
                with patch.object(state, 'archive_commit_slice_and_plan', side_effect=uncommitted):
                    with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_completion_transaction_open'):
                        runtime.turn(flight, clock.monotonic())
                self.assertIsNotNone(runtime.arbiter.pending)
                self.assertIsNone(runtime.arbiter.last_side)
                self.assertNotIn('durable_progress', runtime.ring[-1])
                self.assertTrue(runtime.arbiter.failed)
            finally:
                if state.writer.db.in_transaction:
                    state.writer.db.execute('ROLLBACK')
            self.assertEqual(ledger(state, 'archive'), {})
            self.assertEqual(state.writer.db.execute(
                'SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0], 5)


    def test_completion_failure_named_like_yield_still_revokes_admission(self):
        with native_runtime() as (state, runtime, clock):
            orphan_chunk(state.writer, 'm1-complete-yield')
            with patch.object(runtime.arbiter, 'complete',
                              side_effect=EvidenceUnavailable('evidence_background_yield')) as complete:
                with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_completion_unavailable'):
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertEqual(complete.call_count, 1)
            self.assertIsNotNone(runtime.arbiter.pending)
            self.assertIsNotNone(runtime.failure)
            self.assertTrue(runtime.arbiter.failed)
            self.assertIsNone(runtime.arbiter.last_side)
            self.assertEqual(runtime.ring[-1]['reason'], 'fail_closed')
            self.assertEqual(runtime.ring[-1]['durable_progress'], {'__housekeeping__': 1})

    def test_observation_time_counts_against_the_existing_execution_lease(self):
        with native_runtime() as (state, runtime, clock):
            seed_retirement(state, clock)
            observe, retain = runtime.adapter.observe, state.retention
            def slow_observation(*args):
                value = observe(*args)
                clock.advance(2)
                return value
            def slow_retirement():
                value = retain()
                clock.advance(2)
                return value
            with patch.object(runtime.adapter, 'observe', side_effect=slow_observation), \
                 patch.object(state, 'retention', side_effect=slow_retirement):
                with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_execution_lease_exceeded'):
                    runtime.turn(ArchiveFlight(), clock.monotonic())
            self.assertEqual(clock.monotonic(), 4)
            self.assertIsNotNone(runtime.failure)
            self.assertTrue(runtime.arbiter.failed)
            self.assertIsNone(runtime.arbiter.last_side)
            self.assertEqual(runtime.ring[-1]['durable_records'], {SCOPES[0]: 600})
            self.assertEqual(ledger(state, 'retirement')[SCOPES[0]][1], 600)
            self.assertEqual(list(runtime.arbiter.rates['retirement']), [])


if __name__ == '__main__':
    unittest.main()
