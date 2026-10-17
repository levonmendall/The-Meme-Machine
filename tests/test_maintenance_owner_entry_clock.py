"""Owner callback entry, diagnostic prefix and unchanged native execution lease.

The service cases run the actual serve(), admission and SQLite owner. Only the
offline harness clock, provider-free transport and explicit scheduling faults
are controlled; successful archive/retirement mutations remain native.
"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack
import threading
import unittest
from unittest.mock import patch

from meme_machine import solana_evidence_service as service
from meme_machine import solana_maintenance_runtime as production
from meme_machine.runtime import operation_costs as costs
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_owner_admission import OwnerAdmission
from tests import test_production_maintenance_arbiter as native_fixture
from tests.maintenance_production_harness import Clock, run_case, seed_book


def _cells(function):
    return dict(zip(function.__code__.co_freevars,
                    (cell.cell_contents for cell in function.__closure__ or ())))


class OwnerTurnProbe:
    """Delay the real accepted turn before its serialized service callback.

    The measured decorator itself samples the injected diagnostic prefix. No
    arbiter observation, Need, native mutation or runtime return is replaced.
    """
    def __init__(self, clock, *, queue_delay=0, prefix=0, target=1,
                 stop_after=False, stop_while_pending=False):
        self.clock = clock
        self.queue_delay, self.prefix, self.target = queue_delay, prefix, target
        self.stop_after, self.stop_while_pending = stop_after, stop_while_pending
        self.events, self.entries, self.futures = [], [], []
        self.archive_events = []
        self.admission = self.archive_future = None
        self.ordinal = 0
        self.active = self.sampled = False
        self.stop = None

    def __enter__(self):
        self.stack = ExitStack()
        loop = asyncio.get_running_loop()
        original_serve, original_submit = service.serve, PriorityOwner.submit
        original_sample, original_entry = costs._safe_sample, OwnerAdmission.entry
        original_archive = service.ServiceState.archive_commit_slice_and_plan

        async def observed_serve(*args, stop=None, **kwargs):
            self.stop = stop
            return await original_serve(*args, stop=stop, **kwargs)

        def entry(admission, offer):
            self.admission = admission
            self.entries.append(self.clock.monotonic())
            return original_entry(admission, offer)

        def archive_commit(state, plan, receipt):
            if not self.stop_while_pending or self.archive_events:
                return original_archive(state, plan, receipt)
            event = dict(changes_before=state.writer.db.total_changes,
                         plan_records=len(plan))
            self.archive_events.append(event)
            release = threading.Event()

            def request_stop():
                self.archive_future = self.admission.maintenance_future
                event['pending_at_stop'] = (self.archive_future is not None
                                           and not self.archive_future.done())
                self.stop.set()
                # Release accepted work on the next event-loop turn. The real
                # native commit and its outcome must survive waiter cleanup.
                loop.call_soon(release.set)

            loop.call_soon_threadsafe(request_stop)
            if not release.wait(5):
                raise AssertionError('offline_archive_release_timeout')
            try:
                outcome = original_archive(state, plan, receipt)
                event['outcome'] = outcome
                return outcome
            except BaseException as exc:
                event['error'] = exc
                raise
            finally:
                event.update(changes_after=state.writer.db.total_changes,
                             transaction_open=state.writer.db.in_transaction)

        def sample(name):
            if name == 'owner.maintenance' and self.active and not self.sampled:
                self.sampled = True
                self.events[-1]['prefix_start'] = self.clock.monotonic()
                self.clock.advance(self.prefix)
                self.events[-1]['prefix_end'] = self.clock.monotonic()
            return original_sample(name)

        def submit(owner, fn, **kwargs):
            callback = _cells(fn).get('fn')
            if (not callable(callback) or callback.__name__ != 'turn'
                    or callback.__module__ != service.__name__):
                return original_submit(owner, fn, **kwargs)
            self.ordinal += 1
            if self.ordinal != self.target:
                return original_submit(owner, fn, **kwargs)
            submitted = _cells(callback)['submitted']
            event = dict(submitted=submitted)
            self.events.append(event)

            def entered(state):
                self.clock.advance(self.queue_delay)
                event.update(callback_entry=self.clock.monotonic(),
                             changes_before=state.writer.db.total_changes,
                             admission_entries_before=len(self.entries))
                self.active = True
                try:
                    result = fn(state)
                    event['result'] = result
                    return result
                except BaseException as exc:
                    event['error'] = exc
                    raise
                finally:
                    self.active = False
                    event.update(changes_after=state.writer.db.total_changes,
                                 admission_entries_after=len(self.entries))
                    if self.stop_after:
                        loop.call_soon_threadsafe(self.stop.set)

            entered.owner_operation = fn.owner_operation
            future = original_submit(owner, entered, **kwargs)
            self.futures.append(future)
            return future

        self.stack.enter_context(patch.dict('os.environ',
            {'MM_OPERATION_COST_DIAGNOSTICS': '1'}))
        self.stack.enter_context(patch.object(service, 'serve', observed_serve))
        self.stack.enter_context(patch.object(PriorityOwner, 'submit', submit))
        self.stack.enter_context(patch.object(OwnerAdmission, 'entry', entry))
        self.stack.enter_context(patch.object(costs, '_safe_sample', sample))
        self.stack.enter_context(patch.object(service.ServiceState,
            'archive_commit_slice_and_plan', archive_commit))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)


class OwnerEntryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_serve_entry_2_9_then_diagnostic_prefix_3_01_is_valid(self):
        clock = Clock()
        with OwnerTurnProbe(clock, queue_delay=2.9, prefix=.11) as probe:
            box = await run_case(clock=clock,
                seed=lambda state, at: seed_book(state, at, hot=(100, 0, 0)),
                turns=5)
        self.assertFalse(box['errors'], [str(error) for error in box['errors']])
        self.assertEqual(box['integrity'], 'ok')
        self.assertIsNone(box['runtime'].failure)
        event, = probe.events
        self.assertAlmostEqual(event['callback_entry'] - event['submitted'], 2.9)
        self.assertAlmostEqual(event['prefix_end'] - event['submitted'], 3.01)
        if 'error' in event:
            self.assertIs(type(event['error']), EvidenceUnavailable)
            self.assertEqual(str(event['error']), 'evidence_background_yield')
        first = next(row for row in box['runtime'].ring
                     if row.get('owner_delay', 0) > 2)
        self.assertAlmostEqual(first['owner_delay'], 2.9)
        self.assertGreaterEqual(first['execution'], .109)
        self.assertLess(first['execution'], box['runtime'].leases.execution)
        self.assertFalse(any('maintenance_owner_lease_exceeded' in row.get('error', '')
                             for row in box['runtime'].ring))
        self.assertGreaterEqual(box['counters'].get('archived_records', 0), 100)
        self.assertTrue(any(side == 'archive' for side, _, _ in box['operations']))
        self.assertTrue(all(f.done() and not f.cancelled() for f in probe.futures))

    async def test_expired_before_callback_is_nonfatal_before_admission_or_mutation(self):
        clock = Clock()
        with OwnerTurnProbe(clock, queue_delay=3.01, stop_after=True) as probe:
            box = await run_case(clock=clock,
                seed=lambda state, at: seed_book(state, at, hot=(100, 0, 0)),
                turns=3)
        self.assertFalse(box['errors'], [str(error) for error in box['errors']])
        self.assertIsNone(box['runtime'].failure)
        self.assertFalse(box['runtime'].arbiter.failed)
        self.assertEqual(box['turns'], 0)
        event, = probe.events
        self.assertEqual(str(event['error']), 'evidence_command_expired')
        self.assertEqual(event['changes_before'], event['changes_after'])
        self.assertEqual(event['admission_entries_before'], event['admission_entries_after'])
        self.assertNotIn('prefix_start', event)
        self.assertFalse(box['operations'])
        self.assertEqual(box['counters'].get('archived_records', 0), 0)
        self.assertEqual(box['health']['phase'], 'OFF')
        self.assertEqual(box['integrity'], 'ok')

    async def test_stop_joins_pending_accepted_native_commit(self):
        clock = Clock()
        with OwnerTurnProbe(clock, stop_while_pending=True) as probe:
            box = await run_case(clock=clock,
                seed=lambda state, at: seed_book(state, at, hot=(100, 0, 0)),
                turns=16)
        event, = probe.archive_events
        self.assertTrue(event['pending_at_stop'])
        self.assertFalse(box['errors'], [str(error) for error in box['errors']])
        self.assertIsNotNone(probe.archive_future)
        self.assertTrue(probe.archive_future.done())
        self.assertFalse(probe.archive_future.cancelled())
        if probe.archive_future.exception() is not None:
            self.assertIs(type(probe.archive_future.exception()), EvidenceUnavailable)
            self.assertEqual(str(probe.archive_future.exception()), 'evidence_background_yield')
        self.assertNotIn('error', event)
        self.assertGreater(event['plan_records'], 0)
        self.assertGreater(event['changes_after'], event['changes_before'])
        self.assertFalse(event['transaction_open'])
        self.assertIsNone(box['runtime'].failure)
        self.assertEqual(box['counters'].get('archived_records', 0), 100)
        self.assertEqual(box['health']['phase'], 'OFF')
        self.assertEqual(box['integrity'], 'ok')


class OwnerEntryNativeClockTests(unittest.TestCase):
    def assert_refused_before_native(self, runtime, state, submitted, owner_entered):
        statements = []
        before = state.writer.db.total_changes
        state.writer.db.set_trace_callback(statements.append)
        try:
            with patch.object(runtime.adapter, 'observe',
                    wraps=runtime.adapter.observe) as observe:
                with self.assertRaisesRegex(EvidenceUnavailable,
                        'maintenance_owner_lease_exceeded'):
                    runtime.turn(production.ArchiveFlight(), submitted,
                                 owner_entered=owner_entered)
                observe.assert_not_called()
        finally:
            state.writer.db.set_trace_callback(None)
        self.assertFalse(statements)
        self.assertEqual(state.writer.db.total_changes, before)
        self.assertTrue(runtime.arbiter.failed)
        self.assertIn('maintenance_owner_lease_exceeded', runtime.failure)

    def test_forged_invalid_or_nonfinite_entry_clocks_fail_closed_before_sql(self):
        cases = [
            ('negative_submission', -1, 0, 0),
            ('entry_before_submission', 1, 0, 1),
            ('future_entry', 0, 2, 1),
            ('negative_entry', 0, -1, 1),
            ('nan_submission', float('nan'), 0, 1),
            ('infinite_submission', float('inf'), 0, 1),
            ('nan_entry', 0, float('nan'), 1),
            ('infinite_entry', 0, float('inf'), 1),
            ('nan_current', 0, 0, float('nan')),
            ('infinite_current', 0, 0, float('inf')),
            ('boolean_entry', 0, True, 1),
            ('string_submission', '0', 0, 1),
        ]
        for name, submitted, entered, current in cases:
            with self.subTest(name=name), native_fixture.native_runtime() as (state, runtime, clock):
                native_fixture.orphan_chunk(state.writer, name)
                with patch.object(runtime, 'monotonic', return_value=current):
                    self.assert_refused_before_native(runtime, state, submitted, entered)
                self.assertEqual(state.writer.db.execute(
                    'SELECT COUNT(*) FROM hot_chunks').fetchone()[0], 1)

    def test_direct_caller_default_entry_keeps_fatal_queue_expiry(self):
        with native_fixture.native_runtime() as (state, runtime, clock):
            native_fixture.orphan_chunk(state.writer, 'direct-expired')
            clock.advance(3.01)
            self.assert_refused_before_native(runtime, state, 0, None)
            with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_admission_revoked'):
                runtime.turn(production.ArchiveFlight(), clock.monotonic())

    def test_execution_prefix_at_deadline_refuses_before_observation_and_sql(self):
        for elapsed in (3.0, 3.01):
            with self.subTest(elapsed=elapsed), native_fixture.native_runtime() as (state, runtime, clock):
                native_fixture.orphan_chunk(state.writer, 'prefix-expired')
                clock.advance(elapsed)
                before, statements = state.writer.db.total_changes, []
                state.writer.db.set_trace_callback(statements.append)
                try:
                    with patch.object(runtime.adapter, 'observe',
                            wraps=runtime.adapter.observe) as observe:
                        with self.assertRaisesRegex(EvidenceUnavailable,
                                'maintenance_execution_lease_exceeded'):
                            runtime.turn(production.ArchiveFlight(), 0, owner_entered=0)
                        observe.assert_not_called()
                finally:
                    state.writer.db.set_trace_callback(None)
                self.assertFalse(statements)
                self.assertEqual(state.writer.db.total_changes, before)
                self.assertTrue(runtime.arbiter.failed)
                self.assertIn('maintenance_execution_lease_exceeded', runtime.failure)

    def test_late_native_commit_stays_durable_but_revokes_success_and_admission(self):
        with native_fixture.native_runtime() as (state, runtime, clock):
            native_fixture.orphan_chunk(state.writer, 'late-real-commit')
            original_retention = state.retention
            committed = []

            def late_retention(*args, **kwargs):
                outcome = original_retention(*args, **kwargs)
                committed.append(state.writer.db.in_transaction)
                clock.advance(3.01)
                return outcome

            with patch.object(state, 'retention', side_effect=late_retention):
                with self.assertRaisesRegex(EvidenceUnavailable,
                        'maintenance_execution_lease_exceeded'):
                    runtime.turn(production.ArchiveFlight(), 0, owner_entered=0)
            self.assertEqual(committed, [False])
            self.assertEqual(state.writer.db.execute(
                'SELECT COUNT(*) FROM hot_chunks').fetchone()[0], 0)
            self.assertEqual(state.writer.db.execute(
                "SELECT units,records FROM maintenance_progress "
                "WHERE scope='__housekeeping__' AND side='retirement'").fetchone(), (1, 0))
            self.assertEqual(runtime.ring[-1]['durable_progress']['__housekeeping__'], 1)
            self.assertEqual(runtime.ring[-1]['completion'], 'failed_closed')
            self.assertTrue(runtime.arbiter.failed)
            self.assertIn('maintenance_execution_lease_exceeded', runtime.failure)
            with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_admission_revoked'):
                runtime.turn(production.ArchiveFlight(), clock.monotonic())
            self.assertEqual(state.writer.db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
