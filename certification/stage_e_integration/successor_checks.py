"""Candidate-specific bounded native housekeeping composition proofs."""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_plane import EvidenceUnavailable, EvidenceWriter
from meme_machine.solana_maintenance_runtime import ArchiveFlight
from tests.maintenance_production_harness import Clock, seed_book
from tests.test_housekeeping_integration import garbage, ledger
from tests.test_production_maintenance_arbiter import native_runtime


WITNESSES = {}
HOUSEKEEPING = '__housekeeping__'
SCOPE = 'program:meteora'


def prepared_case(state, runtime, clock):
    """Age real native orphan demand before creating fresh record obligations."""
    garbage(state.writer, 1)
    initial = runtime.adapter.observe(runtime.generation)
    runtime._demands(initial)
    clock.advance(34.2183)
    seed_book(state, clock, hot=(1, 0, 0), retired=(2000, 0, 0))
    plan = state.archive_plan()
    pending = EvidenceWriter.prepare_and_write_archive(state.writer.path, plan)
    if not pending[0]:
        raise AssertionError('native_prepared_receipt_missing')
    return ArchiveFlight(pending=pending, submitted=clock.monotonic(),
        generation=runtime.generation)


def reservation(runtime, observation):
    """The existing arbiter inequality, applied to fresh actual native needs."""
    needs = runtime._demands(observation)
    t = observation.monotonic
    end = t + 2 * runtime.leases.execution + runtime.leases.owner
    deadlines = {}
    for need in needs:
        if need.side != 'retirement' or not need.units:
            continue
        deadline = min(need.safety_deadline,
            runtime.arbiter.origin.get((need.side, need.scope), t) + runtime.leases.drought)
        if need.recovery_excess:
            deadline = min(deadline, need.recovery_deadline)
        deadlines[need.scope] = deadline
    return dict(at=t, peer_window=end, effective_retirement_deadlines=deadlines,
        archive_peer_reservation_feasible=all(end < d for d in deadlines.values()),
        housekeeping_native_units=observation.housekeeping,
        scopes=[dict(scope=s.scope, hot=s.hot_eligible, retirement=s.retirement_eligible)
            for s in observation.scopes])


class SuccessorChecks(unittest.TestCase):
    def test_component_semantic_ast_and_frozen_identity_equivalence(self):
        root = Path(__file__).resolve().parents[2]
        mapping = json.loads((root / 'diagnostics/stage-e-integration-successor/component-map.json').read_text())
        reference = mapping['semantic_equivalence_references']

        def method(path, cls, name):
            return next(n for c in ast.parse((root / path).read_text()).body
                if isinstance(c, ast.ClassDef) and c.name == cls for n in c.body
                if isinstance(n, ast.FunctionDef) and n.name == name)

        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

        runtime = 'meme_machine/solana_maintenance_runtime.py'
        plane = 'meme_machine/solana_evidence_plane.py'
        for name in ('_complete_decision', '_cooperative'):
            self.assertEqual(digest(ast.dump(method(runtime, 'MaintenanceRuntime', name))),
                reference['m1_a2_method_ast'][name])
        self.assertEqual(digest(ast.dump(method(runtime, 'MaintenanceRuntime', '_housekeeping_first'))),
            reference['historical_housekeeping_selector_ast'])
        self.assertEqual(digest([ast.dump(n) for n in method(plane, 'EvidenceWriter', '_retention_housekeeping').body]),
            reference['existing_gc_body_ast'])
        retained = method(plane, 'EvidenceWriter', 'retain')
        loops = [ast.dump(n) for n in retained.body if isinstance(n, ast.For)
            and isinstance(n.target, ast.Tuple) and any(isinstance(t, ast.Name) and t.id == 'index'
                for t in n.target.elts)]
        self.assertEqual(digest(loops), reference['existing_scope_loop_ast'])
        for path, expected in reference['protected_base_bytes'].items():
            self.assertEqual(hashlib.sha256((root / path).read_bytes()).hexdigest(), expected, path)
        for path, expected in reference['unchanged_q2_bytes'].items():
            self.assertEqual(hashlib.sha256((root / path).read_bytes()).hexdigest(), expected, path)
        for info in mapping['integration_files'].values():
            self.assertIn(info['classification'], ('M1', 'A2', 'HOUSEKEEPING', 'Q2', 'INTEGRATION_ONLY'))
        observer = json.loads((root / 'certification/stage_e_native_v2/observer-contract-v2.json').read_text())
        self.assertEqual(observer['acceptance'], 'ratio < 0.01')
        self.assertIs(observer['measured'], False)
        skips = json.loads((root / 'certification/stage_e_native_v2/historical-skips-v2.json').read_text())['skips']
        self.assertEqual(len(skips), 46)
        self.assertEqual(sum(r['disposition'] == 'executed only in prepared assembly qualification' for r in skips), 33)
        self.assertEqual(sum(r['disposition'] == 'executed only in future canonical qualification' for r in skips), 13)
        self.assertTrue(all(r['status'] == 'NOT_EXECUTED' and r['passing'] is False for r in skips))
        WITNESSES[self.id()] = dict(semantic_equivalence=True, protected_files=len(reference['protected_base_bytes']),
            unchanged_q2_files=len(reference['unchanged_q2_bytes']), original_skips=46,
            prepared_unexecuted=33, canonical_unexecuted=13, observer='NOT_EXECUTED',
            acceptance=observer['acceptance'], material='NOT_EXECUTED')

    def test_receipt74_old_fails_new_passes_archive_peer_feasibility(self):
        arms = {}
        WITNESSES[self.id()] = arms
        for treatment in (False, True):
            with native_runtime() as (state, runtime, clock):
                flight = prepared_case(state, runtime, clock)
                before = reservation(runtime, runtime.adapter.observe(runtime.generation))
                receipt = flight.pending[1]
                self.assertFalse(before['archive_peer_reservation_feasible'])
                hk = before['effective_retirement_deadlines'][HOUSEKEEPING]
                self.assertGreater(hk, before['at'] + runtime.leases.execution)
                self.assertLessEqual(hk, before['peer_window'])
                self.assertTrue(all(d > before['peer_window'] for scope, d in
                    before['effective_retirement_deadlines'].items() if scope != HOUSEKEEPING))

                def source_queued():
                    clock.advance(.1)
                    return 'source'

                state.writer._retention_yield_requested = source_queued
                # The control is ordinary retirement under the same M1/A2 code.
                # Only approved prefix eligibility is suppressed in this arm.
                with patch.object(runtime, '_housekeeping_first',
                        wraps=runtime._housekeeping_first) if treatment else \
                        patch.object(runtime, '_housekeeping_first', return_value=False):
                    result = runtime.turn(flight, clock.monotonic())
                outcome = result['retention_outcome']
                after = reservation(runtime, runtime.adapter.observe(runtime.generation))
                arms['integrated' if treatment else 'ordinary_control'] = dict(
                    generation=runtime.generation, before=before, after=after,
                    selected_side=result['side'], retired_records=outcome.retired_records,
                    housekeeping_units=outcome.housekeeping_rows,
                    committed_ledger=ledger(state.writer), event=dict(runtime.ring[-1]),
                    receipt_retained=flight.pending is not None and flight.pending[1] == receipt,
                    integrity=state.writer.db.execute('PRAGMA integrity_check').fetchone()[0])
                self.assertEqual(result['side'], 'retirement')
                self.assertIsNotNone(flight.pending)
                self.assertEqual(flight.pending[1], receipt)
                self.assertFalse(getattr(state, '_housekeeping_retention', False))
                self.assertEqual(outcome.yield_reason, 'source')
                self.assertEqual(arms['integrated' if treatment else 'ordinary_control']['integrity'], 'ok')
                if treatment:
                    self.assertEqual(outcome.retired_records, 0)
                    self.assertGreater(outcome.housekeeping_rows, 0)
                    self.assertEqual(outcome.housekeeping_rows, before['housekeeping_native_units'])
                    self.assertEqual(ledger(state.writer), (outcome.housekeeping_rows, 0))
                    self.assertEqual(runtime.ring[-1]['durable_records'], {})
                    self.assertEqual(runtime.ring[-1]['durable_progress'].get(HOUSEKEEPING),
                        outcome.housekeeping_rows)
                    self.assertTrue(after['archive_peer_reservation_feasible'])
                else:
                    self.assertEqual(outcome.retired_records, 768)
                    self.assertEqual(outcome.housekeeping_rows, 0)
                    self.assertIsNone(ledger(state.writer))
                    self.assertFalse(after['archive_peer_reservation_feasible'])
        # Feasibility is the proof. A later archive selection is not required.

    def test_housekeeping_committed_prefix_lease_expiry_preserves_units_without_service(self):
        with native_runtime() as (state, runtime, clock):
            flight = prepared_case(state, runtime, clock)
            before = reservation(runtime, runtime.adapter.observe(runtime.generation))

            def source_after_expiry():
                self.assertFalse(state.writer.db.in_transaction)
                self.assertGreater(ledger(state.writer)[0], 0)
                clock.advance(runtime.leases.execution + .1)
                return 'source'

            state.writer._retention_yield_requested = source_after_expiry
            with self.assertRaisesRegex(EvidenceUnavailable, 'maintenance_execution_lease_exceeded'):
                runtime.turn(flight, clock.monotonic())
            event = runtime.ring[-1]
            WITNESSES[self.id()] = dict(generation=runtime.generation, before=before,
                committed_ledger=ledger(state.writer), event=dict(event),
                admission_revoked=runtime.arbiter.failed, receipt_retained=flight.pending is not None,
                integrity=state.writer.db.execute('PRAGMA integrity_check').fetchone()[0])
            self.assertEqual(ledger(state.writer), (before['housekeeping_native_units'], 0))
            self.assertEqual(event['durable_progress'].get(HOUSEKEEPING), before['housekeeping_native_units'])
            self.assertEqual(event['durable_records'], {})
            self.assertEqual(event['completion'], 'failed_closed')
            self.assertTrue(runtime.arbiter.failed)
            self.assertIsNotNone(runtime.failure)
            self.assertIsNone(runtime.arbiter.last_side)
            self.assertEqual(list(runtime.arbiter.rates['retirement']), [])
            self.assertIsNotNone(flight.pending)
            self.assertFalse(state._housekeeping_retention)
            self.assertFalse(state.writer.db.in_transaction)
            self.assertEqual(WITNESSES[self.id()]['integrity'], 'ok')

    def test_housekeeping_restart_restores_committed_progress_without_duplicate_credit(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db'
            with native_runtime(clock=clock, path=path) as (state, runtime, _):
                flight = prepared_case(state, runtime, clock)
                state.writer._retention_yield_requested = lambda: 'source'
                first = runtime.turn(flight, clock.monotonic())['retention_outcome']
                committed = ledger(state.writer)
                progress = state.writer.db.execute("SELECT at,units,records FROM maintenance_progress "
                    "WHERE scope=? AND side='retirement'", (HOUSEKEEPING,)).fetchone()
                original_generation = runtime.generation
                started = state.writer.db.execute("SELECT wall_started FROM maintenance_nonrecord_demand "
                    "WHERE scope=? AND side='retirement'", (HOUSEKEEPING,)).fetchone()[0]
                self.assertEqual(first.retired_records, 0)
                self.assertEqual(committed, (first.housekeeping_rows, 0))
            clock.advance(.5)
            with native_runtime(clock=clock, path=path) as (state, runtime, _):
                self.assertNotEqual(runtime.generation, original_generation)
                self.assertEqual(ledger(state.writer), committed)
                self.assertFalse(getattr(state, '_housekeeping_retention', False))
                garbage(state.writer, 1)
                observation = runtime.adapter.observe(runtime.generation)
                needs = runtime._demands(observation)
                restored = runtime.last_progress['retirement', HOUSEKEEPING]
                hk = next(n for n in needs if n.scope == HOUSEKEEPING)
                expected = max(runtime.clock.project(started), runtime.clock.project(progress[0])) + runtime.leases.drought
                self.assertAlmostEqual(hk.safety_deadline, expected)
                self.assertEqual(restored[3], committed[0])
                state.writer._retention_yield_requested = lambda: 'source'
                second = runtime.turn(ArchiveFlight(), clock.monotonic())['retention_outcome']
                event = runtime.ring[-1]
                WITNESSES[self.id()] = dict(original_generation=original_generation,
                    restarted_generation=runtime.generation, committed_ledger=committed,
                    restored_progress=list(restored), housekeeping_deadline=hk.safety_deadline,
                    expected_deadline=expected, retirement_continuation=second.retired_records,
                    event=dict(event), final_ledger=ledger(state.writer),
                    integrity=state.writer.db.execute('PRAGMA integrity_check').fetchone()[0])
                self.assertEqual(second.retired_records, 768)
                self.assertEqual(second.housekeeping_rows, 0)
                self.assertEqual(ledger(state.writer), committed)
                self.assertEqual(event['durable_progress'].get(HOUSEKEEPING, 0), 0)
                self.assertNotIn(HOUSEKEEPING, event['durable_records'])
                self.assertIsNone(runtime.arbiter.pending)
                self.assertIsNone(runtime.failure)
                self.assertEqual(WITNESSES[self.id()]['integrity'], 'ok')
