"""Bounded owner-thread mechanism attribution, never capacity acceptance.

The unchanged synthetic acquisition helper supplies the entire real SQLite
cohort and conservation checks. Direct wrappers add timing overhead and can
change the actor's real five-ms yield boundary. These timings identify work
inside an owner callback; they do not establish a production service rate.
Root owns registration and execution of this diagnostic.
"""
from contextlib import ExitStack, contextmanager
from functools import wraps
import hashlib
import json
import math
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.runtime import sqlite_failure
from meme_machine.solana_acquisition_scheduler import AcquisitionScheduler
from meme_machine.solana_dispatch_probe import DispatchProbe
from meme_machine.solana_selective_history import SelectiveHistory
from tests import test_owner_throughput_comparison as comparison


MAX_OUTPUT_BYTES = 16 * 1024
MAX_STACK = 32
# Fixed names and count: no SQL, arguments, rows, exceptions or file paths are
# copied into the report. The eighth row discriminates diagnostic ring costs
# without wrapping transaction context managers or changing their semantics.
TARGETS = (
    ('history.plan_step', SelectiveHistory, 'plan_step'),
    ('scheduler.next', AcquisitionScheduler, 'next'),
    ('scheduler._seed_urgent', AcquisitionScheduler, '_seed_urgent'),
    ('scheduler.wake_fanout', AcquisitionScheduler, 'wake_fanout'),
    ('scheduler._wake_rank', AcquisitionScheduler, '_wake_rank'),
    ('scheduler.backfill', AcquisitionScheduler, 'backfill'),
    ('dispatch_probe.step', DispatchProbe, 'step'),
    ('sqlite_failure._breadcrumb', sqlite_failure, '_breadcrumb'),
)


class _OwnerCosts:
    def __init__(self):
        self.owner_ident = None
        self.owner_native_id = None
        self.active = False
        self.stack = []
        self.errors = []
        self.callbacks = 0
        self.callback_cpu_ns = 0
        self.callback_wall_ns = 0
        self.max_depth = 0
        self.rows = [dict(name=name, calls=0, raised=0,
            inclusive_cpu_ns=0, exclusive_cpu_ns=0,
            inclusive_wall_ns=0, exclusive_wall_ns=0)
            for name, _, _ in TARGETS]

    def error(self, code):
        if len(self.errors) < 8:
            self.errors.append(code)

    @contextmanager
    def callback(self):
        ident, native = threading.get_ident(), threading.get_native_id()
        if self.owner_ident is None:
            self.owner_ident, self.owner_native_id = ident, native
        if (ident != self.owner_ident or native != self.owner_native_id
                or self.active or self.stack):
            self.error('callback_thread_or_nesting')
        self.active = True
        cpu, wall = time.thread_time_ns(), time.perf_counter_ns()
        try:
            yield
        finally:
            wall_elapsed = time.perf_counter_ns() - wall
            cpu_elapsed = time.thread_time_ns() - cpu
            self.active = False
            if self.stack:
                self.error('callback_unclosed_frame')
            if min(cpu_elapsed, wall_elapsed) < 0:
                self.error('callback_negative_clock')
            self.callbacks += 1
            self.callback_cpu_ns += cpu_elapsed
            self.callback_wall_ns += wall_elapsed

    def wrap(self, index, original):
        @wraps(original)
        def measured(*args, **kwargs):
            # Patching a method also sees setup and other threads. Only calls
            # made by the actual accepted candidate callback's owner count.
            if not self.active or threading.get_ident() != self.owner_ident:
                return original(*args, **kwargs)
            if threading.get_native_id() != self.owner_native_id:
                self.error('frame_native_thread_changed')
                return original(*args, **kwargs)
            if len(self.stack) >= MAX_STACK:
                self.error('frame_depth_bound')
                return original(*args, **kwargs)
            frame = dict(index=index, child_cpu_ns=0, child_wall_ns=0)
            self.stack.append(frame)
            self.max_depth = max(self.max_depth, len(self.stack))
            cpu, wall = time.thread_time_ns(), time.perf_counter_ns()
            raised = False
            try:
                return original(*args, **kwargs)
            except BaseException:
                raised = True
                raise
            finally:
                wall_elapsed = time.perf_counter_ns() - wall
                cpu_elapsed = time.thread_time_ns() - cpu
                if not self.stack or self.stack[-1] is not frame:
                    self.error('frame_stack_corrupt')
                else:
                    self.stack.pop()
                exclusive_cpu = cpu_elapsed - frame['child_cpu_ns']
                exclusive_wall = wall_elapsed - frame['child_wall_ns']
                if min(cpu_elapsed, wall_elapsed, exclusive_cpu, exclusive_wall) < 0:
                    self.error('frame_negative_clock_or_accounting')
                row = self.rows[index]
                row['calls'] += 1
                row['raised'] += int(raised)
                row['inclusive_cpu_ns'] += cpu_elapsed
                row['exclusive_cpu_ns'] += exclusive_cpu
                row['inclusive_wall_ns'] += wall_elapsed
                row['exclusive_wall_ns'] += exclusive_wall
                if self.stack:
                    self.stack[-1]['child_cpu_ns'] += cpu_elapsed
                    self.stack[-1]['child_wall_ns'] += wall_elapsed
        return measured


def _is_candidate_callback(fn):
    """Recognize this unchanged harness's timed closure, never runtime state."""
    code = getattr(fn, '__code__', None)
    if (getattr(fn, '__module__', None) != comparison.__name__
            or getattr(fn, '__qualname__', None) !=
            'run_owner_throughput_comparison.<locals>.work.<locals>.timed'
            or code is None or fn.__closure__ is None):
        return False
    for name, cell in zip(code.co_freevars, fn.__closure__):
        if name == 'candidate':
            return cell.cell_contents is True
    return False


def _recording_owner(base, costs):
    class RecordingOwner(base):
        def submit(self, fn, **options):
            if _is_candidate_callback(fn):
                original = fn
                @wraps(original)
                def fn(*args, **kwargs):
                    with costs.callback():
                        return original(*args, **kwargs)
            # Return the actual accepted Future with its original cancellation,
            # ordering and completion behavior. No scheduling value is replaced.
            return super().submit(fn, **options)
    return RecordingOwner


async def run_owner_planning_costs(directory, *, schedule=None):
    """Match uninstrumented/attributed full cohorts with unchanged acquisition.

    ``None`` preserves the original helper default. A named schedule is passed
    directly to a helper that supports it; this module never synthesizes IDLE,
    rewrites a callback result, advances its clock, or changes convergence.
    """
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    options = {} if schedule is None else dict(schedule=schedule)
    plain = await comparison.run_owner_throughput_comparison(
        directory/'plain', measured=False, **options)
    costs = _OwnerCosts()
    with ExitStack() as stack:
        for index, (_, owner, name) in enumerate(TARGETS):
            stack.enter_context(patch.object(owner, name,
                costs.wrap(index, getattr(owner, name))))
        stack.enter_context(patch.object(comparison, 'PriorityOwner',
            _recording_owner(comparison.PriorityOwner, costs)))
        attributed = await comparison.run_owner_throughput_comparison(
            directory/'attributed', measured=False, **options)

    # Preserve the helper's complete original conservation predicates, including
    # retained pending work, exact canonical evidence and financial restrictions.
    checks = unittest.TestCase()
    for report in (plain, attributed):
        comparison.OwnerThroughputComparisonTests.assert_conserved(checks, report)
    checks.assertEqual(plain['cohort'], attributed['cohort'])
    checks.assertEqual(plain['before'], attributed['before'])
    checks.assertEqual(plain['final'], attributed['final'])
    checks.assertEqual(plain['cancellation_probe'], attributed['cancellation_probe'])
    checks.assertEqual(plain['scheduling'], attributed['scheduling'])
    checks.assertEqual(costs.errors, [])
    checks.assertEqual(costs.stack, [])
    checks.assertFalse(costs.active)
    checks.assertGreater(costs.callbacks, 0)
    checks.assertEqual(costs.callbacks, attributed['counters']['callbacks'])
    checks.assertIsNotNone(costs.owner_ident)
    checks.assertIsNotNone(costs.owner_native_id)
    checks.assertGreater(costs.rows[0]['calls'], 0)
    checks.assertEqual(len(costs.rows), 8)
    exclusive_cpu_ns = sum(row['exclusive_cpu_ns'] for row in costs.rows)
    exclusive_wall_ns = sum(row['exclusive_wall_ns'] for row in costs.rows)
    # Clock reading is nested and integer-valued; negatives are rejected, never
    # clamped. A one-microsecond floor accommodates only clock/float rounding.
    tolerance_ns = max(1000, math.ceil(4 * (costs.callbacks+1) *
        time.get_clock_info('thread_time').resolution * 1_000_000_000))
    helper_cpu_ns = attributed['counters']['callback_thread_cpu_seconds'] * 1_000_000_000
    helper_wall_ns = attributed['counters']['callback_wall_seconds'] * 1_000_000_000
    checks.assertLessEqual(exclusive_cpu_ns, helper_cpu_ns+tolerance_ns)
    checks.assertLessEqual(exclusive_wall_ns, helper_wall_ns+tolerance_ns)
    checks.assertLessEqual(exclusive_cpu_ns, costs.callback_cpu_ns)
    checks.assertLessEqual(exclusive_wall_ns, costs.callback_wall_ns)
    rows = []
    for row in costs.rows:
        checks.assertGreaterEqual(row['calls'], row['raised'])
        projected = dict(name=row['name'], calls=row['calls'], raised=row['raised'])
        for key in ('inclusive_cpu_ns', 'exclusive_cpu_ns',
                'inclusive_wall_ns', 'exclusive_wall_ns'):
            checks.assertIs(type(row[key]), int)
            checks.assertGreaterEqual(row[key], 0)
            seconds = row[key] / 1_000_000_000
            checks.assertTrue(math.isfinite(seconds))
            projected[key.replace('_ns', '_seconds')] = seconds
        rows.append(projected)
    summary = dict(schema='synthetic-owner-planning-costs-v1',
        scope='OWNER_THREAD_DIRECT_WRAPPERS_SYNTHETIC_NOT_CAPACITY_ACCEPTANCE',
        scheduling=attributed['scheduling'],
        provenance=dict(harness_sha256=hashlib.sha256(
            Path(comparison.__file__).read_bytes()).hexdigest(),
            diagnostic_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            full_source_census=False),
        clocks=dict(cpu='thread_time_ns', wall='perf_counter_ns',
            owner_thread_verified=True, owner_native_thread_verified=True,
            maximum_nested_frames=costs.max_depth, accounting_tolerance_ns=tolerance_ns),
        callbacks=costs.callbacks,
        callback_cpu_seconds=attributed['counters']['callback_thread_cpu_seconds'],
        callback_wall_seconds=attributed['counters']['callback_wall_seconds'],
        exclusive_measured_cpu_seconds=exclusive_cpu_ns/1_000_000_000,
        exclusive_measured_wall_seconds=exclusive_wall_ns/1_000_000_000,
        uninstrumented_callback_cpu_seconds=plain['counters']['callback_thread_cpu_seconds'],
        uninstrumented_callbacks=plain['counters']['callbacks'],
        cohort=attributed['cohort'],
        fingerprints=dict(initial_functional=attributed['before']['functional_sha256'],
            final_functional=attributed['final']['functional_sha256'],
            canonical_order=attributed['final']['canonical_order_sha256']),
        matched_full_final_state=True, conservation_passed=True,
        provider_calls=attributed['provider_calls'], financial_authority=attributed['financial_authority'],
        rows=rows, limitations=[
            'Direct wrappers perturb the real five-ms quantum; this is mechanism attribution, not capacity evidence.',
            'The selected helper schedule is unchanged; callback-ticks is an adversarial schedule, not matched market time.',
            'Fresh synthetic SQLite fixtures do not authenticate original market or historical recovery evidence.'])
    encoded = json.dumps(summary, sort_keys=True, separators=(',', ':'), allow_nan=False)
    checks.assertLessEqual(len(encoded.encode()), MAX_OUTPUT_BYTES)
    print('OWNER_PLANNING_COSTS '+encoded, flush=True)
    return summary


class OwnerPlanningCostsTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_owner_planner_costs_are_nested_and_conserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary = await run_owner_planning_costs(Path(temporary)/'costs')
        self.assertEqual(len(summary['rows']), 8)
        self.assertEqual(summary['provider_calls'], 0)
        self.assertFalse(summary['financial_authority'])
