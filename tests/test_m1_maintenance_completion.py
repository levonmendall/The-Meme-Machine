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
                        material_executions=0, gate_implemented=False,
                        m1_repair_applied=False, completion_assertion_weakened=False)

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
                                generation=runtime.generation)
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
