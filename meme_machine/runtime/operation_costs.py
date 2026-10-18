"""Opt-in costs for fixed reached operations, using existing health publication.

These are diagnostic counters, never readiness or authority. SQL covers only
selected instrumented connections. Thread CPU includes native SQLite and Python
callbacks; wall minus CPU does not identify I/O, GIL or lock waits. Parent
operation costs overlap their children. SQL belongs to the innermost operation
on the actual executing thread. No SQL, arguments, frames or disk logs are kept.
SQL counts are API boundaries: executemany/executescript each count once, and
script-internal transaction controls remain within that statement duration.
Direct-child durations are invocation-local synchronous attribution. Subtract
them only with complete child timing; parent residuals include probe overhead.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import math
import os
import sqlite3
import threading
from time import monotonic, thread_time, time as wall_time

from meme_machine.solana_candidate_phases import runnable_snapshot


NAMES = (
    'owner.reactivation_lookup', 'owner.reactivation_cold',
    'owner.reactivation_promote', 'owner.reactivation_demote',
    'owner.binding', 'owner.history_enqueue',
    'pons.current_discovery', 'pons.current_prime', 'pons.current_hydration',
    'pons.current_entry_turn', 'pons.current_owner_turn', 'pons.current_shared_acquire',
    'pons.survivor_restore', 'pons.survivor_step', 'pons.survivor_enrich',
    'pons.reporting', 'pons.usd_read', 'pons.scale_prepare',
    'owner.economic_ingest', 'owner.rolling_store', 'owner.order_attest',
    'owner.history_outbox', 'owner.checkpoint', 'owner.maintenance',
    'owner.scout_commit', 'owner.control_commit', 'owner.delivery_capture',
    'owner.delivery_ack', 'owner.proof_publish', 'owner.history_plan',
    'pump.observed_candidates_restore', 'pump.observed_candidate_events',
    'pump.restore_metadata', 'pump.restore_hot_bodies', 'pump.restore_source_capture',
    'pump.restore_cold_metadata', 'pump.restore_manifests', 'pump.restore_chunks',
)
RESTORE_COUNT_NAMES = (
    'pages_started', 'pages_completed', 'references', 'source_groups',
    'hot_keys_selected', 'hot_bytes_selected', 'cold_keys_selected', 'scalar_source_reads',
    'fallback_reference_size', 'fallback_reference_parse', 'fallback_reference_shape',
    'fallback_source_snapshot_expired', 'fallback_source_read_error',
    'fallback_encoded_budget', 'fallback_prepared_budget', 'fallback_prepare_error',
    'fallback_chunk_shape', 'fallback_chunk_snapshot_expired',
    'fallback_chunk_read_error', 'fallback_chunk_budget',
)
SQL_BUCKETS = ('statement', 'statement_many', 'fetch', 'transaction', 'checkpoint')
ACTIVE_LIMIT = 16
_SKIP_RUNNABLE = frozenset(('owner.order_attest', *(name for name in NAMES if name.startswith('pump.restore_'))))
_FIELDS = (
    'calls', 'failed_calls', 'unmeasured_calls', 'runnable_measured_calls',
    'runnable_unavailable_calls', 'submitted_calls', 'pending_calls',
    'cancelled_before_execution_calls', 'queue_calls', 'queue_unmeasured_calls',
    'queue_total_microseconds', 'queue_peak_microseconds',
    'selected_connection_calls', 'uninstrumented_connection_calls',
    'uninstrumented_cursor_calls', 'uninstrumented_executor_calls', 'nested_sql_calls',
    'child_calls', 'child_unmeasured_calls',
    'child_wall_seconds_total_microseconds', 'child_cpu_seconds_total_microseconds',
    *(name + '_' + kind + '_microseconds'
      for name in ('wall_seconds', 'cpu_seconds', 'runnable_wait_seconds')
      for kind in ('total', 'peak')),
)
_SQL_FIELDS = ('calls', 'failed_calls', 'unmeasured_calls',
               'wall_microseconds', 'cpu_microseconds')


def _new_rows():
    return {name: dict({field: 0 for field in _FIELDS},
                       sql={bucket: {field: 0 for field in _SQL_FIELDS}
                            for bucket in SQL_BUCKETS}) for name in NAMES}


_rows = _new_rows()
_lock = threading.Lock()
_current = ContextVar('operation_costs_current', default=None)
_active = {}
_sequence = 0
_recorder_valid = True
_recording_lost_calls = 0
_active_overflow_calls = 0
_restore_counts = dict.fromkeys(RESTORE_COUNT_NAMES, 0)


def enabled():
    return os.environ.get('MM_OPERATION_COST_DIAGNOSTICS') == '1'


def restore_counts(values):
    """Merge one fixed page's numeric facts; optional recording cannot mask work.

    The caller buffers locally, so there is no per-reference lock or process
    probe. A zero is meaningful only after at least one page reached this merge;
    an empty snapshot population is UNEXERCISED, not evidence of zero fallbacks.
    """
    if not enabled():
        return
    try:
        if (type(values) is not dict or set(values) != set(RESTORE_COUNT_NAMES)
                or any(type(value) is not int or value < 0 for value in values.values())):
            raise ValueError('operation_cost_restore_counts')
        with _lock:
            for name, value in values.items():
                _restore_counts[name] += value
    except BaseException:
        _lost()


def _validate(name):
    if not isinstance(name, str) or name not in _rows:
        raise ValueError('operation_cost_identity')


def _lost():
    # A failed recorder must not invoke another fallible recorder or mask work.
    global _recorder_valid, _recording_lost_calls
    _recorder_valid = False
    _recording_lost_calls += 1


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _sample(name):
    wall = monotonic()
    cpu = thread_time()
    if not _number(wall) or not _number(cpu):
        return None
    try:
        runnable = None if name in _SKIP_RUNNABLE else runnable_snapshot()
    except BaseException:
        runnable = None
    return wall, cpu, runnable


def _safe_sample(name):
    try:
        return _sample(name)
    except BaseException:
        return None


def _deltas(started, ended):
    if started is None or ended is None:
        return None
    wall, cpu = _microseconds(started[0], ended[0]), _microseconds(started[1], ended[1])
    return None if wall is None or cpu is None else (wall, cpu)


def _microseconds(started, ended):
    if not _number(started) or not _number(ended) or ended < started:
        return None
    micros = (ended - started) * 1_000_000
    return int(micros) if _number(micros) else None


def _merge(state, started, ended, failed, queued_at):
    delta = _deltas(started, ended)
    with _lock:
        row = _rows[state['name']]
        row['calls'] += 1
        row['failed_calls'] += int(failed)
        if delta is None:
            row['unmeasured_calls'] += 1
        else:
            for metric, micros in zip(('wall_seconds', 'cpu_seconds'), delta):
                row[metric + '_total_microseconds'] += micros
                row[metric + '_peak_microseconds'] = max(row[metric + '_peak_microseconds'], micros)
        a = None if started is None else started[2]
        b = None if ended is None else ended[2]
        if (isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b) == 3
                and a[:2] == b[:2] == (state['pid'], state['native_thread_id'])
                and type(a[2]) is int and type(b[2]) is int and b[2] >= a[2]):
            micros = (b[2] - a[2]) // 1000
            row['runnable_measured_calls'] += 1
            row['runnable_wait_seconds_total_microseconds'] += micros
            row['runnable_wait_seconds_peak_microseconds'] = max(
                row['runnable_wait_seconds_peak_microseconds'], micros)
        else:
            row['runnable_unavailable_calls'] += 1
        if queued_at is not False:
            micros = None if started is None else _microseconds(queued_at, started[0])
            if micros is None:
                row['queue_unmeasured_calls'] += 1
            else:
                row['queue_calls'] += 1
                row['queue_total_microseconds'] += micros
                row['queue_peak_microseconds'] = max(row['queue_peak_microseconds'], micros)
        for field in ('selected_connection_calls', 'uninstrumented_connection_calls',
                      'uninstrumented_cursor_calls', 'nested_sql_calls',
                      'child_calls', 'child_wall_seconds_total_microseconds',
                      'child_cpu_seconds_total_microseconds'):
            row[field] += state[field]
        child_unmeasured = state['child_unmeasured_calls'] + state['pending_children']
        if (delta is not None and
                (state['child_wall_seconds_total_microseconds'] > delta[0]
                 or state['child_cpu_seconds_total_microseconds'] > delta[1])):
            child_unmeasured = max(child_unmeasured, state['child_calls'])
        row['child_unmeasured_calls'] += child_unmeasured
        for bucket in SQL_BUCKETS:
            for field in _SQL_FIELDS:
                row['sql'][bucket][field] += state['sql'][bucket][field]


@contextmanager
def _operation(name, queued_at=False):
    global _sequence, _active_overflow_calls
    parent = _local_state()
    state = dict(name=name, pid=os.getpid(), native_thread_id=threading.get_native_id(),
                 sql={bucket: {field: 0 for field in _SQL_FIELDS} for bucket in SQL_BUCKETS},
                 selected_connection_calls=0, uninstrumented_connection_calls=0,
                 uninstrumented_cursor_calls=0, nested_sql_calls=0, sql_depth=0,
                 child_calls=0, child_unmeasured_calls=0,
                 child_wall_seconds_total_microseconds=0, child_cpu_seconds_total_microseconds=0,
                 pending_children=0, overlapping_children=False, active=True)
    started = _safe_sample(name)
    identity = None
    token = None
    parent_linked = False
    failed = False
    try:
        try:
            token = _current.set(state)
            if parent is not None:
                parent['child_calls'] += 1
                parent['pending_children'] += 1
                parent_linked = True
                if parent['pending_children'] > 1:
                    parent['overlapping_children'] = True
            with _lock:
                if len(_active) < ACTIVE_LIMIT:
                    _sequence += 1
                    identity = _sequence
                    _active[identity] = dict(operation=name, invocation=identity,
                        pid=state['pid'], native_thread_id=state['native_thread_id'],
                        started_monotonic=None if started is None else started[0])
                else:
                    _active_overflow_calls += 1
        except BaseException:
            _lost()
        try:
            yield
        except BaseException:
            failed = True
            raise
    finally:
        ended = _safe_sample(name)
        if (state['pid'] != os.getpid()
                or state['native_thread_id'] != threading.get_native_id()):
            ended = None
        try:
            if parent_linked and parent['active']:
                parent['pending_children'] -= 1
                delta = _deltas(started, ended)
                if (delta is None or parent['overlapping_children'] or parent['sql_depth']
                        or _current.get() is not state
                        or (parent['pid'], parent['native_thread_id']) !=
                           (state['pid'], state['native_thread_id'])):
                    parent['child_unmeasured_calls'] += 1
                else:
                    parent['child_wall_seconds_total_microseconds'] += delta[0]
                    parent['child_cpu_seconds_total_microseconds'] += delta[1]
        except BaseException:
            _lost()
        finally:
            state['active'] = False
        try:
            if token is not None:
                _current.reset(token)
        except BaseException:
            _lost()
        try:
            _merge(state, started, ended, failed, queued_at)
        except BaseException:
            _lost()
        finally:
            if identity is not None:
                try:
                    with _lock:
                        _active.pop(identity, None)
                except BaseException:
                    _lost()


@contextmanager
def operation(name):
    """Measure actual synchronous work; nested operation totals overlap."""
    _validate(name)
    if not enabled():
        yield
        return
    with _operation(name):
        yield


def measured(name):
    """Decorate a synchronous operation; arguments/results are never retained."""
    _validate(name)
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not enabled():
                return function(*args, **kwargs)
            with _operation(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def _pending(name, submitted=0, pending=0, cancelled=0):
    try:
        with _lock:
            row = _rows[name]
            row['submitted_calls'] += submitted
            row['pending_calls'] += pending
            row['cancelled_before_execution_calls'] += cancelled
    except BaseException:
        _lost()


def _run_submitted(name, queued_at, function, args, kwargs):
    _pending(name, pending=-1)
    with _operation(name, queued_at):
        return function(*args, **kwargs)


def submit(executor, name, function, *args, **kwargs):
    """Return the executor's original Future, timing its actual worker thread.

    Cancellation before execution uses the executor's own semantics. Accepted
    running work retains its completion. Aggregates are local to each process;
    this does not introduce cross-process telemetry or copy caller contexts.
    """
    _validate(name)
    if not enabled():
        return executor.submit(function, *args, **kwargs)
    from concurrent.futures import ProcessPoolExecutor
    if isinstance(executor, ProcessPoolExecutor):
        # Process-local counters cannot describe the parent's pending work.
        # Preserve the original process callable and report this coverage gap.
        future = executor.submit(function, *args, **kwargs)
        try:
            with _lock:
                _rows[name]['submitted_calls'] += 1
                _rows[name]['uninstrumented_executor_calls'] += 1
                _rows[name]['queue_unmeasured_calls'] += 1
        except BaseException:
            _lost()
        return future
    try:
        queued_at = monotonic()
        if not _number(queued_at):
            queued_at = None
    except BaseException:
        queued_at = None
    _pending(name, submitted=1, pending=1)
    try:
        future = executor.submit(_run_submitted, name, queued_at, function, args, kwargs)
    except BaseException:
        _pending(name, submitted=-1, pending=-1)
        raise
    def completed(result):
        try:
            if result.cancelled():
                _pending(name, pending=-1, cancelled=1)
        except BaseException:
            _lost()
    try:
        future.add_done_callback(completed)
    except BaseException:
        _lost()
    return future


def _local_state():
    try:
        state = _current.get()
        if (state is not None and state['pid'] == os.getpid()
                and state['native_thread_id'] == threading.get_native_id()
                and state.get('active', False)):
            return state
    except BaseException:
        _lost()
    return None


def _coverage(field):
    try:
        state = _local_state()
        if state is not None:
            state[field] += 1
    except BaseException:
        _lost()


def _current_operation():
    state = _local_state()
    return state['name'] if state is not None and state['name'] in NAMES else None


def connect(database, *args, diagnostic_role, **kwargs):
    """Preserve native connection/factory behavior unless explicitly opted in.

    An explicitly supplied factory remains authoritative. It is reported as
    uninstrumented rather than replaced with a diagnostic subclass.
    """
    if not enabled():
        return sqlite3.connect(database, *args, **kwargs)
    if len(args) >= 5 or 'factory' in kwargs:
        _coverage('uninstrumented_connection_calls')
        return sqlite3.connect(database, *args, **kwargs)
    from .sqlite_failure import connect as diagnostic_connect
    _coverage('selected_connection_calls')
    return diagnostic_connect(database, *args, diagnostic_role=diagnostic_role, **kwargs)


def _sql_started(phase, wall_started, *, api=None):
    """Private hooks: no sampling or environment lookup outside an operation."""
    try:
        state = _local_state()
        if state is None or phase in ('cursor_open', 'close'):
            return None
        root = phase.split('.', 1)[0]
        bucket = ('checkpoint' if root == 'checkpoint' else
                  'transaction' if root in ('BEGIN', 'COMMIT', 'ROLLBACK', 'SAVEPOINT',
                                             'RELEASE', 'context_exit') else
                  'fetch' if '.' in phase else
                  'statement_many' if api == 'executemany' else 'statement')
        nested = state['sql_depth'] > 0
        state['sql_depth'] += 1
        if nested:
            state['nested_sql_calls'] += 1
        try:
            cpu_started = thread_time()
            if not _number(wall_started) or not _number(cpu_started):
                cpu_started = None
        except BaseException:
            cpu_started = None
        return state, bucket, wall_started, cpu_started, nested
    except BaseException:
        _lost()
        return None


def _sql_finished(measurement, failed):
    try:
        state, bucket, started, cpu_started, nested = measurement
        state['sql_depth'] -= 1
        row = state['sql'][bucket]
        row['calls'] += 1
        row['failed_calls'] += int(failed)
        try:
            ended, cpu_ended = monotonic(), thread_time()
            wall_micros = None if nested or cpu_started is None else _microseconds(started, ended)
            cpu_micros = None if nested or cpu_started is None else _microseconds(cpu_started, cpu_ended)
        except BaseException:
            wall_micros = cpu_micros = None
        if wall_micros is None or cpu_micros is None:
            row['unmeasured_calls'] += 1
        else:
            row['wall_microseconds'] += wall_micros
            row['cpu_microseconds'] += cpu_micros
    except BaseException:
        _lost()


def snapshot():
    """Copy bounded process-local counters at these actual collection clocks."""
    try:
        sampled_monotonic, sampled_wall = monotonic(), wall_time()
        if not _number(sampled_monotonic) or not _number(sampled_wall):
            raise ValueError('operation_cost_collection_clock')
        with _lock:
            active = [dict(row) for row in _active.values() if row['pid'] == os.getpid()]
            reached = {row['operation'] for row in active}
            reached.update(name for name, row in _rows.items()
                           if row['calls'] or row['submitted_calls'] or row['pending_calls'])
            rows = {name: dict({field: _rows[name][field] for field in _FIELDS},
                              sql={bucket: dict(_rows[name]['sql'][bucket]) for bucket in SQL_BUCKETS})
                    for name in NAMES if name in reached}
            return dict(version=1, enabled=enabled(), pid=os.getpid(),
                collected_monotonic=sampled_monotonic, collected_wall=sampled_wall,
                recorder_valid=_recorder_valid, recording_lost_calls=_recording_lost_calls,
                active_limit=ACTIVE_LIMIT, active_overflow_calls=_active_overflow_calls,
                rows=rows, active=active, not_reached=[name for name in NAMES if name not in reached],
                restore_reference_counts=dict(_restore_counts) if _restore_counts['pages_started'] else {},
                restore_reference_count_scope='PAGE_TOTALS_FIRST_FALLBACK_REASON_PER_REFERENCE',
                not_reached_status='UNEXERCISED',
                sql_scope='SELECTED_INSTRUMENTED_CONNECTIONS_IN_INNERMOST_OPERATION',
                sql_nested_scope='OUTERMOST_NATIVE_BOUNDARY_DURATIONS_ONLY',
                operation_scope='PARENT_OPERATION_TOTALS_OVERLAP_CHILDREN',
                child_scope='DIRECT_SYNCHRONOUS_CHILDREN_SAME_PID_TID_PROBE_OVERHEAD_REMAINS')
    except BaseException:
        _lost()
        return dict(version=1, enabled=enabled(), pid=os.getpid(), recorder_valid=False,
                    recording_lost_calls=_recording_lost_calls, available=False)
