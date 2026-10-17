"""Fixed operation costs on disposable state; no service or provider activity."""
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import ExitStack, closing, nullcontext
from contextvars import copy_context
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from meme_machine.runtime import operation_costs as costs
from meme_machine.runtime import sqlite_failure


class OperationCostsTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {'MM_OPERATION_COST_DIAGNOSTICS': '1'}))
        for name, value in (('_rows', costs._new_rows()), ('_active', {}),
                            ('_sequence', 0), ('_recorder_valid', True),
                            ('_recording_lost_calls', 0), ('_active_overflow_calls', 0)):
            stack.enter_context(patch.object(costs, name, value))
        stack.enter_context(patch.object(costs, 'runnable_snapshot', return_value=None))
        self.temporary = stack.enter_context(tempfile.TemporaryDirectory())
        self.path = Path(self.temporary) / 'operation.sqlite'

    def row(self, name):
        return costs.snapshot()['rows'][name]

    def test_opt_out_keeps_native_factory_and_original_submit_without_probes(self):
        marker = object()
        function = Mock(return_value=marker)
        executor = Mock()
        executor.submit.return_value = marker
        with patch.dict(os.environ, {'MM_OPERATION_COST_DIAGNOSTICS': '0'}), \
                patch.object(costs, 'monotonic', side_effect=AssertionError('unexpected-clock')), \
                patch.object(costs, 'thread_time', side_effect=AssertionError('unexpected-cpu')), \
                patch.object(costs, 'runnable_snapshot', side_effect=AssertionError('unexpected-proc')):
            with costs.operation('pons.reporting'):
                self.assertIs(costs.measured('pons.reporting')(function)(7), marker)
            self.assertIs(costs.submit(executor, 'pons.reporting', function, 7, flag=True), marker)
            executor.submit.assert_called_once_with(function, 7, flag=True)
            with closing(costs.connect(':memory:', diagnostic_role='operation_test')) as db:
                self.assertIs(type(db), sqlite3.Connection)
                self.assertEqual(db.execute('SELECT 7').fetchone(), (7,))
            class Custom(sqlite3.Connection):
                pass
            with closing(costs.connect(':memory:', diagnostic_role='operation_test', factory=Custom)) as db:
                self.assertIs(type(db), Custom)
        sample = costs.snapshot()
        self.assertEqual(sample['rows'], {})
        self.assertEqual(sample['not_reached'], list(costs.NAMES))
        self.assertEqual(sample['not_reached_status'], 'UNEXERCISED')

    def test_names_are_fixed_and_private_arguments_are_never_retained(self):
        self.assertEqual(len(costs.NAMES), 32)
        for name in ('https://private.invalid/?apikey=secret', '', None, [], True):
            with self.assertRaisesRegex(ValueError, 'operation_cost_identity'):
                with costs.operation(name):
                    self.fail('invalid-operation-ran')
            with self.assertRaisesRegex(ValueError, 'operation_cost_identity'):
                costs.measured(name)
        @costs.measured('pons.reporting')
        def reporting(private):
            return private
        self.assertEqual(reporting('never-copy-this-argument'), 'never-copy-this-argument')
        sample = costs.snapshot()
        self.assertEqual(set(sample['rows']), {'pons.reporting'})
        self.assertNotIn('never-copy', json.dumps(sample))
        self.assertEqual(set(costs._rows), set(costs.NAMES))

    def test_coarse_cpu_wall_and_actual_thread_runnable_have_separate_counters(self):
        pid, tid = os.getpid(), threading.get_native_id()
        samples = ((10, 2, (pid, tid, 1000)), (12, 2.5, (pid, tid, 6000)))
        with patch.object(costs, '_sample', side_effect=samples):
            with costs.operation('owner.binding'):
                pass
        row = self.row('owner.binding')
        self.assertEqual(row['calls'], 1)
        self.assertEqual(row['wall_seconds_total_microseconds'], 2_000_000)
        self.assertEqual(row['cpu_seconds_total_microseconds'], 500_000)
        self.assertEqual(row['runnable_wait_seconds_total_microseconds'], 5)
        self.assertEqual(row['runnable_measured_calls'], 1)
        self.assertEqual(row['runnable_unavailable_calls'], 0)

    def test_order_attest_never_reads_per_record_scheduler_state(self):
        with patch.object(costs, 'runnable_snapshot') as runnable:
            with costs.operation('owner.order_attest'):
                pass
        runnable.assert_not_called()
        row = self.row('owner.order_attest')
        self.assertEqual(row['runnable_unavailable_calls'], 1)
        self.assertEqual(row['runnable_measured_calls'], 0)

    def test_direct_child_costs_are_invocation_local_and_include_grandchildren_once(self):
        samples = ((0, 0, None), (1, 1, None), (2, 2, None), (3, 3, None),
                   (4, 4, None), (5, 5, None), (7, 7, None), (10, 10, None),
                   (20, 20, None), (24, 24, None))
        with patch.object(costs, '_sample', side_effect=samples):
            with costs.operation('owner.economic_ingest'):
                with costs.operation('owner.rolling_store'):
                    with costs.operation('owner.order_attest'):
                        pass
                with costs.operation('owner.history_outbox'):
                    pass
            # Same child name under another caller must not change the parent's
            # direct-child totals or be subtracted from that parent's CPU.
            with costs.operation('owner.rolling_store'):
                pass
        parent = self.row('owner.economic_ingest')
        self.assertEqual(parent['child_calls'], 2)
        self.assertEqual(parent['child_unmeasured_calls'], 0)
        self.assertEqual(parent['child_wall_seconds_total_microseconds'], 5_000_000)
        self.assertEqual(parent['child_cpu_seconds_total_microseconds'], 5_000_000)
        self.assertEqual(parent['cpu_seconds_total_microseconds'] -
                         parent['child_cpu_seconds_total_microseconds'], 5_000_000)
        child = self.row('owner.rolling_store')
        self.assertEqual(child['cpu_seconds_total_microseconds'], 7_000_000)
        self.assertEqual(child['child_calls'], 1)
        self.assertEqual(child['child_cpu_seconds_total_microseconds'], 1_000_000)

    def test_same_name_failed_and_unmeasured_children_preserve_original_error(self):
        original = RuntimeError('original-child-error')
        with patch.object(costs, '_sample', side_effect=(
                (0, 0, None), (1, 1, None), (3, 3, None), (4, 4, None))):
            with costs.operation('owner.binding'):
                with self.assertRaises(RuntimeError) as caught:
                    with costs.operation('owner.binding'):
                        raise original
        self.assertIs(caught.exception, original)
        row = self.row('owner.binding')
        self.assertEqual(row['calls'], 2)
        self.assertEqual(row['child_calls'], 1)
        self.assertEqual(row['child_unmeasured_calls'], 0)
        self.assertEqual(row['child_cpu_seconds_total_microseconds'], 2_000_000)
        with patch.object(costs, '_sample', side_effect=(
                (0, 0, None), None, (2, 2, None), (3, 3, None))):
            with costs.operation('owner.binding'):
                with costs.operation('owner.history_enqueue'):
                    pass
        self.assertEqual(self.row('owner.binding')['child_unmeasured_calls'], 1)

    def test_stale_and_overlapping_copied_contexts_never_claim_exclusive_child_cost(self):
        with costs.operation('owner.binding'):
            stale = copy_context()
        def later():
            with costs.operation('owner.history_enqueue'):
                pass
        stale.run(later)
        self.assertEqual(self.row('owner.binding')['child_calls'], 0)
        with costs.operation('owner.binding'):
            a, b = copy_context(), copy_context()
            child_a = costs.operation('owner.history_enqueue')
            child_b = costs.operation('owner.rolling_store')
            a.run(child_a.__enter__)
            b.run(child_b.__enter__)
            a.run(child_a.__exit__, None, None, None)
            b.run(child_b.__exit__, None, None, None)
        parent = self.row('owner.binding')
        self.assertEqual(parent['child_calls'], 2)
        self.assertEqual(parent['child_unmeasured_calls'], 2)

    def test_child_totals_exceeding_parent_delta_are_explicitly_unavailable(self):
        with patch.object(costs, '_sample', side_effect=(
                (0, 0, None), (1, 1, None), (9, 9, None), (5, 5, None))):
            with costs.operation('owner.binding'):
                with costs.operation('owner.history_enqueue'):
                    pass
        parent = self.row('owner.binding')
        self.assertEqual(parent['child_calls'], 1)
        self.assertEqual(parent['child_unmeasured_calls'], 1)
        self.assertGreater(parent['child_cpu_seconds_total_microseconds'],
                           parent['cpu_seconds_total_microseconds'])

    def test_pending_child_after_parent_exit_is_unavailable_without_mutating_published_parent(self):
        parent = costs.operation('owner.binding')
        parent.__enter__()
        context = copy_context()
        child = costs.operation('owner.history_enqueue')
        context.run(child.__enter__)
        parent.__exit__(None, None, None)
        first = self.row('owner.binding')
        self.assertEqual(first['child_calls'], 1)
        self.assertEqual(first['child_unmeasured_calls'], 1)
        context.run(child.__exit__, None, None, None)
        self.assertEqual(self.row('owner.binding'), first)
        self.assertEqual(costs.snapshot()['active'], [])

    def test_probe_loss_regression_and_merge_failure_preserve_original_error(self):
        original = RuntimeError('original-private-operation-error')
        with patch.object(costs, '_sample', side_effect=OSError('optional-probe')):
            with self.assertRaises(RuntimeError) as caught:
                with costs.operation('pons.reporting'):
                    raise original
        self.assertIs(caught.exception, original)
        row = self.row('pons.reporting')
        self.assertEqual((row['calls'], row['failed_calls'], row['unmeasured_calls']), (1, 1, 1))
        with patch.object(costs, '_sample', side_effect=((9, 3, None), (8, 4, None))):
            with costs.operation('pons.reporting'):
                pass
        self.assertEqual(self.row('pons.reporting')['unmeasured_calls'], 2)
        with patch.object(costs, '_merge', side_effect=OSError('optional-merge')):
            with self.assertRaises(RuntimeError) as caught:
                with costs.operation('pons.reporting'):
                    raise original
        self.assertIs(caught.exception, original)
        sample = costs.snapshot()
        self.assertFalse(sample['recorder_valid'])
        self.assertGreater(sample['recording_lost_calls'], 0)
        self.assertEqual(sample['active'], [])
        self.assertIsNone(costs._current.get())

    def test_invalid_clocks_and_mismatched_runnable_never_become_measured_zero(self):
        pid, tid = os.getpid(), threading.get_native_id()
        with patch.object(costs, 'thread_time', return_value=float('nan')):
            with costs.operation('pons.usd_read'):
                pass
        self.assertEqual(self.row('pons.usd_read')['unmeasured_calls'], 1)
        with patch.object(costs, '_sample', side_effect=(
                (1, 1, (pid, tid, 0)), (2, 2, (pid, tid + 1, 3000)))):
            with costs.operation('pons.usd_read'):
                pass
        self.assertEqual(self.row('pons.usd_read')['runnable_measured_calls'], 0)
        with patch.object(costs, '_sample', side_effect=((-1e308, 1, None), (1e308, 2, None))):
            with costs.operation('pons.usd_read'):
                pass
        self.assertEqual(self.row('pons.usd_read')['unmeasured_calls'], 2)
        with patch.object(costs, 'monotonic', return_value=float('inf')):
            sample = costs.snapshot()
        self.assertFalse(sample['recorder_valid'])
        self.assertFalse(sample['available'])

    def test_snapshot_reports_actual_collection_clock_and_bounded_active_overflow(self):
        before = time.monotonic()
        with ExitStack() as stack:
            for _ in range(costs.ACTIVE_LIMIT + 1):
                stack.enter_context(costs.operation('owner.binding'))
            sample = costs.snapshot()
            self.assertEqual(len(sample['active']), costs.ACTIVE_LIMIT)
            self.assertEqual(sample['active_overflow_calls'], 1)
            self.assertGreaterEqual(sample['collected_monotonic'], before)
            for active in sample['active']:
                self.assertEqual(active['pid'], os.getpid())
                self.assertEqual(active['native_thread_id'], threading.get_native_id())
                self.assertLessEqual(active['started_monotonic'], sample['collected_monotonic'])
        self.assertEqual(costs.snapshot()['active'], [])
        self.assertEqual(self.row('owner.binding')['calls'], costs.ACTIVE_LIMIT + 1)
        self.assertEqual(self.row('owner.binding')['child_calls'], costs.ACTIVE_LIMIT)
        self.assertEqual(self.row('owner.binding')['child_unmeasured_calls'], 0)
        self.assertLess(len(json.dumps(sample).encode()), 32 * 1024)

    def test_two_blocked_worker_threads_keep_distinct_active_identity_and_finish(self):
        entered = [threading.Event(), threading.Event()]
        release = threading.Event()
        tids = []
        cpu_tids = []
        actual_cpu = time.thread_time
        def cpu():
            cpu_tids.append(threading.get_native_id())
            return actual_cpu()
        def work(index):
            tids.append(threading.get_native_id())
            entered[index].set()
            if not release.wait(2):
                raise RuntimeError('offline-release-missing')
            return index
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(costs, 'thread_time', side_effect=cpu):
            futures = [costs.submit(pool, 'pons.current_hydration', work, index) for index in range(2)]
            try:
                self.assertTrue(all(event.wait(1) for event in entered))
                sample = costs.snapshot()
                self.assertEqual(len(sample['active']), 2)
                self.assertEqual({row['native_thread_id'] for row in sample['active']}, set(tids))
                self.assertNotIn(threading.get_native_id(), tids)
                self.assertEqual(sample['rows']['pons.current_hydration']['calls'], 0)
            finally:
                release.set()
            self.assertEqual([future.result(2) for future in futures], [0, 1])
        row = self.row('pons.current_hydration')
        self.assertEqual((row['submitted_calls'], row['calls'], row['pending_calls']), (2, 2, 0))
        self.assertEqual(set(cpu_tids), set(tids))

    def test_submit_queue_and_cancel_before_execution_preserve_executor_semantics(self):
        entered, release = threading.Event(), threading.Event()
        def block():
            entered.set()
            release.wait(2)
        marker = object()
        callback = Mock(return_value=marker)
        with ThreadPoolExecutor(max_workers=1) as pool:
            blocker = pool.submit(block)
            try:
                self.assertTrue(entered.wait(1))
                cancelled = costs.submit(pool, 'pons.current_prime', callback)
                self.assertEqual(self.row('pons.current_prime')['pending_calls'], 1)
                self.assertTrue(cancelled.cancel())
                queued = costs.submit(pool, 'pons.current_prime', callback)
                self.assertEqual(self.row('pons.current_prime')['calls'], 0)
            finally:
                release.set()
            blocker.result(2)
            self.assertIs(queued.result(2), marker)
        callback.assert_called_once_with()
        row = self.row('pons.current_prime')
        self.assertEqual((row['submitted_calls'], row['calls'], row['pending_calls']), (2, 1, 0))
        self.assertEqual(row['cancelled_before_execution_calls'], 1)
        self.assertEqual(row['queue_calls'], 1)
        self.assertGreater(row['queue_total_microseconds'], 0)

    def test_cancellation_after_start_cannot_cancel_running_operation_or_replace_error(self):
        entered, release = threading.Event(), threading.Event()
        original = RuntimeError('original-worker-error')
        def work():
            entered.set()
            release.wait(2)
            raise original
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = costs.submit(pool, 'pons.survivor_step', work)
            try:
                self.assertTrue(entered.wait(1))
                self.assertFalse(future.cancel())
            finally:
                release.set()
            with self.assertRaises(RuntimeError) as caught:
                future.result(2)
        self.assertIs(caught.exception, original)
        self.assertEqual(self.row('pons.survivor_step')['failed_calls'], 1)
        self.assertEqual(costs.snapshot()['active'], [])

    def test_submit_rejection_preserves_original_exception_and_no_phantom_pending(self):
        original = RuntimeError('original-executor-rejection')
        executor = Mock()
        executor.submit.side_effect = original
        with self.assertRaises(RuntimeError) as caught:
            costs.submit(executor, 'pons.current_prime', lambda: None)
        self.assertIs(caught.exception, original)
        self.assertNotIn('pons.current_prime', costs.snapshot()['rows'])

    def test_process_executor_keeps_original_callable_and_marks_uninstrumented(self):
        # No process starts: exercise only dispatch selection with a typed mock.
        executor = Mock(spec=ProcessPoolExecutor)
        function = Mock()
        future = Mock()
        executor.submit.return_value = future
        self.assertIs(costs.submit(executor, 'pons.current_prime', function, 3), future)
        executor.submit.assert_called_once_with(function, 3)
        row = self.row('pons.current_prime')
        self.assertEqual(row['uninstrumented_executor_calls'], 1)
        self.assertEqual(row['pending_calls'], 0)
        self.assertEqual(row['queue_unmeasured_calls'], 1)

    def test_execute_fetch_iteration_transaction_and_checkpoint_are_distinct(self):
        with closing(costs.connect(self.path, diagnostic_role='operation_test', isolation_level=None)) as db:
            db.execute('CREATE TABLE retained(value INTEGER)')
            db.executemany('INSERT INTO retained VALUES(?)', ((1,), (2,)))
            with costs.operation('owner.binding'):
                self.assertEqual(db.execute('SELECT value FROM retained ORDER BY value').fetchone(), (1,))
                self.assertEqual(db.execute('SELECT value FROM retained ORDER BY value').fetchmany(1), [(1,)])
                self.assertEqual(db.execute('SELECT value FROM retained ORDER BY value').fetchall(), [(1,), (2,)])
                self.assertEqual(list(db.execute('SELECT value FROM retained ORDER BY value')), [(1,), (2,)])
                db.execute('BEGIN')
                db.execute('SAVEPOINT diagnostic')
                db.execute('RELEASE diagnostic')
                db.rollback()
                with db:
                    db.execute('BEGIN')
                result = db.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
                self.assertEqual(len(result), 3)
        sql = self.row('owner.binding')['sql']
        self.assertEqual(sql['statement']['calls'], 4)
        self.assertEqual(sql['fetch']['calls'], 6)  # Three fetch methods and 2 rows plus StopIteration.
        self.assertEqual(sql['transaction']['calls'], 6)
        self.assertEqual(sql['checkpoint']['calls'], 2)
        for row in sql.values():
            self.assertEqual(row['failed_calls'], 0)
            self.assertEqual(row['unmeasured_calls'], 0)
            self.assertGreaterEqual(row['wall_microseconds'], 0)
            self.assertGreaterEqual(row['cpu_microseconds'], 0)

    def test_nested_sql_belongs_only_innermost_operation_and_scope_restores(self):
        with closing(costs.connect(':memory:', diagnostic_role='operation_test')) as db:
            with costs.operation('owner.binding'):
                db.execute('SELECT 1').fetchone()
                original = RuntimeError('original-inner-error')
                with self.assertRaises(RuntimeError) as caught:
                    with costs.operation('owner.history_enqueue'):
                        db.execute('SELECT 2').fetchone()
                        raise original
                self.assertIs(caught.exception, original)
                db.execute('SELECT 3').fetchone()
        outer, inner = self.row('owner.binding'), self.row('owner.history_enqueue')
        self.assertEqual(outer['sql']['statement']['calls'], 2)
        self.assertEqual(outer['sql']['fetch']['calls'], 2)
        self.assertEqual(inner['sql']['statement']['calls'], 1)
        self.assertEqual(inner['sql']['fetch']['calls'], 1)
        self.assertEqual(inner['failed_calls'], 1)
        self.assertIsNone(costs._current.get())

    def test_native_executemany_has_one_separate_api_bucket_without_statement_double_count(self):
        with closing(costs.connect(':memory:', diagnostic_role='operation_test')) as db:
            db.execute('CREATE TABLE retained(value INTEGER)')
            with costs.operation('owner.rolling_store'):
                db.executemany('INSERT INTO retained VALUES(?)', ((1,), (2,)))
                self.assertEqual(db.execute('SELECT value FROM retained ORDER BY value').fetchall(),
                                 [(1,), (2,)])
        sql = self.row('owner.rolling_store')['sql']
        self.assertEqual(sql['statement_many']['calls'], 1)
        self.assertEqual(sql['statement_many']['failed_calls'], 0)
        self.assertEqual(sql['statement']['calls'], 1)
        self.assertEqual(sql['fetch']['calls'], 1)

    def test_copied_context_does_not_credit_sql_from_another_thread(self):
        def other_thread():
            with costs.operation('owner.history_enqueue'), \
                    closing(costs.connect(':memory:', diagnostic_role='operation_test')) as db:
                return db.execute('SELECT 7').fetchone()
        with costs.operation('owner.binding'):
            context = copy_context()
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(context.run, other_thread).result(2), (7,))
        row = self.row('owner.binding')
        self.assertEqual(row['selected_connection_calls'], 0)
        self.assertEqual(row['sql']['statement']['calls'], 0)
        self.assertEqual(row['child_calls'], 0)
        self.assertEqual(self.row('owner.history_enqueue')['sql']['statement']['calls'], 1)

    def test_actual_busy_readonly_and_context_rollback_preserve_native_first_errors(self):
        with sqlite3.connect(self.path) as setup:
            setup.execute('CREATE TABLE retained(value TEXT)')
        with closing(sqlite3.connect(self.path, isolation_level=None)) as holder, \
                closing(costs.connect(self.path, diagnostic_role='operation_test',
                                      timeout=0, isolation_level=None)) as db:
            holder.execute('BEGIN IMMEDIATE')
            try:
                with costs.operation('owner.binding'):
                    with self.assertRaises(sqlite3.OperationalError) as caught:
                        db.execute('BEGIN IMMEDIATE')
                self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)
                self.assertEqual(sqlite_failure.payload(caught.exception)['operation'], 'BEGIN')
                self.assertEqual(sqlite_failure.payload(caught.exception)['current_operation'], 'owner.binding')
            finally:
                holder.rollback()
            original = RuntimeError('original-body-error')
            with self.assertRaises(RuntimeError) as caught:
                with costs.operation('owner.history_enqueue'), db:
                    db.execute('BEGIN')
                    db.execute('INSERT INTO retained VALUES(?)', ('private-binding',))
                    raise original
            self.assertIs(caught.exception, original)
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM retained').fetchone(), (0,))
        with closing(costs.connect(self.path.as_uri() + '?mode=ro', uri=True,
                                    diagnostic_role='operation_test')) as db:
            with costs.operation('owner.binding'):
                with self.assertRaises(sqlite3.OperationalError) as readonly:
                    db.execute('INSERT INTO retained VALUES(?)', ('private-binding',))
            self.assertEqual(readonly.exception.sqlite_errorcode, sqlite3.SQLITE_READONLY)
            first = sqlite_failure.payload(readonly.exception)
            sqlite_failure.annotate(readonly.exception, {}, 'ROLLBACK', 0)
            self.assertEqual(sqlite_failure.payload(readonly.exception), first)
        row = self.row('owner.binding')
        self.assertEqual(row['sql']['transaction']['failed_calls'], 1)
        self.assertEqual(row['sql']['statement']['failed_calls'], 1)
        self.assertNotIn('private-binding', json.dumps(costs.snapshot()))

    def test_recorder_hooks_and_iteration_clock_loss_do_not_replace_native_behavior(self):
        with closing(costs.connect(':memory:', diagnostic_role='operation_test')) as db:
            with costs.operation('owner.binding'):
                with patch.object(costs, '_sql_started', side_effect=OSError('optional-start')):
                    self.assertEqual(db.execute('SELECT 1').fetchone(), (1,))
                with patch.object(costs, '_sql_finished', side_effect=OSError('optional-finish')):
                    self.assertEqual(db.execute('SELECT 2').fetchone(), (2,))
                    with self.assertRaises(sqlite3.OperationalError) as original:
                        db.execute('SELECT missing_private_column')
                self.assertEqual(original.exception.sqlite_errorcode, sqlite3.SQLITE_ERROR)
                cursor = db.execute('SELECT 3 UNION ALL SELECT 4')
                with patch.object(sqlite_failure.time, 'monotonic', side_effect=OSError('optional-clock')):
                    self.assertEqual(list(cursor), [(3,), (4,)])
        sample = costs.snapshot()
        self.assertFalse(sample['recorder_valid'])
        self.assertEqual(sample['active'], [])

    def test_optional_operation_lookup_failure_keeps_essential_original_sqlite_facts(self):
        with sqlite3.connect(self.path) as setup:
            setup.execute('CREATE TABLE retained(value INTEGER)')
        with closing(costs.connect(self.path.as_uri() + '?mode=ro', uri=True,
                                    diagnostic_role='operation_test', timeout=0)) as db:
            with costs.operation('owner.binding'), \
                    patch.object(costs, '_current_operation', side_effect=OSError('optional-private-lookup')):
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    db.execute('INSERT INTO retained VALUES(?)', (7,))
            facts = sqlite_failure.payload(caught.exception)
            self.assertEqual(facts['sqlite_errorcode'], sqlite3.SQLITE_READONLY)
            self.assertEqual(facts['operation'], 'INSERT')
            self.assertEqual(facts['database'], str(self.path))
            self.assertEqual(facts['opening_mode'], 'ro')
            self.assertEqual(facts['connection_role'], 'operation_test')
            self.assertEqual(facts['connection_identity'], db._failure_metadata['connection_identity'])
            self.assertIsNone(facts['current_operation'])
            self.assertFalse(facts['operation_costs_valid'])
            self.assertNotIn('optional-private-lookup', json.dumps(facts))

    def test_custom_connection_and_callable_cursor_factories_remain_authoritative(self):
        class Custom(sqlite3.Connection):
            pass
        with costs.operation('owner.binding'):
            with closing(costs.connect(':memory:', diagnostic_role='operation_test', factory=Custom)) as db:
                self.assertIs(type(db), Custom)
            with closing(costs.connect(':memory:', 5, 0, '', True, Custom,
                                       diagnostic_role='operation_test')) as db:
                self.assertIs(type(db), Custom)
            with closing(costs.connect(':memory:', diagnostic_role='operation_test')) as db:
                factory = lambda connection: sqlite3.Cursor(connection)
                self.assertEqual(db.cursor(factory=factory).execute('SELECT 7').fetchone(), (7,))
                with patch.dict(os.environ, {'MM_OPERATION_COST_DIAGNOSTICS': '0'}):
                    self.assertEqual(db.cursor(factory=factory).execute('SELECT 8').fetchone(), (8,))
        row = self.row('owner.binding')
        self.assertEqual(row['uninstrumented_connection_calls'], 2)
        self.assertEqual(row['uninstrumented_cursor_calls'], 2)
        self.assertEqual(row['selected_connection_calls'], 1)

    def test_reentrant_sql_callback_marks_nested_timing_incomplete_without_double_count(self):
        with closing(costs.connect(':memory:', diagnostic_role='operation_test')) as db:
            db.create_function('nested', 0, lambda: db.execute('SELECT 7').fetchone()[0])
            with costs.operation('owner.binding'):
                self.assertEqual(db.execute('SELECT nested()').fetchone(), (7,))
        row = self.row('owner.binding')
        self.assertEqual(row['nested_sql_calls'], 2)
        self.assertEqual(row['sql']['statement']['calls'], 2)
        self.assertEqual(row['sql']['fetch']['calls'], 2)
        self.assertEqual(row['sql']['statement']['unmeasured_calls'], 1)
        self.assertEqual(row['sql']['fetch']['unmeasured_calls'], 1)

    def test_measured_child_inside_native_sql_callback_cannot_claim_exclusive_non_sql_cost(self):
        @costs.measured('owner.history_enqueue')
        def callback():
            return 7
        with closing(costs.connect(':memory:', diagnostic_role='operation_test')) as db:
            db.create_function('measured_child', 0, callback)
            with costs.operation('owner.binding'):
                self.assertEqual(db.execute('SELECT measured_child()').fetchone(), (7,))
        parent = self.row('owner.binding')
        self.assertEqual(parent['child_calls'], 1)
        self.assertEqual(parent['child_unmeasured_calls'], 1)

    def test_disposable_iteration_reports_instrumentation_cost_not_market_capacity(self):
        count = 2000
        with sqlite3.connect(self.path) as setup:
            setup.execute('CREATE TABLE overhead_rows(value INTEGER)')
            setup.executemany('INSERT INTO overhead_rows VALUES(?)', ((value,) for value in range(count)))
        with closing(sqlite3.connect(self.path)) as native, \
                closing(costs.connect(self.path, diagnostic_role='iteration_overhead_test')) as selected:
            for db in (native, selected):
                self.assertEqual(len(list(db.execute('SELECT value FROM overhead_rows ORDER BY value'))), count)
            results = []
            for label, db, measured in (('native', native, False),
                                        ('selected_without_operation', selected, False),
                                        ('selected_with_operation', selected, True)):
                wall_started, cpu_started = time.perf_counter_ns(), time.thread_time_ns()
                rows = checksum = 0
                with costs.operation('owner.rolling_store') if measured else nullcontext():
                    for row in db.execute('SELECT value FROM overhead_rows ORDER BY value'):
                        rows += 1
                        checksum += row[0]
                cpu_ns, wall_ns = time.thread_time_ns() - cpu_started, time.perf_counter_ns() - wall_started
                self.assertEqual((rows, checksum), (count, count * (count - 1) // 2))
                results.append(dict(path=label, rows=rows, wall_nanoseconds=wall_ns, cpu_nanoseconds=cpu_ns))
        sql = self.row('owner.rolling_store')['sql']
        self.assertEqual(sql['statement']['calls'], 1)
        self.assertEqual(sql['fetch']['calls'], count + 1)
        self.assertEqual(sql['fetch']['failed_calls'], 0)
        print('operation_cost_iteration_overhead=' + json.dumps(dict(
            scope='DISPOSABLE_SQL_ITERATION_INSTRUMENTATION_COST_NOT_MARKET_CAPACITY',
            results=results), sort_keys=True))


if __name__ == '__main__':
    unittest.main()
