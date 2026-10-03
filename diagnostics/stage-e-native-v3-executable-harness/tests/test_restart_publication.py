"""Tiny native constructor/publication transactions; no service loops or frames."""
from contextlib import closing, nullcontext
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'harness')); sys.path.insert(0, str(ROOT))
from core import COHORT, file_sha
import overload
from preserve import persist, seal
from regression_fixtures import interval, safe_overload_row
from restart_fixtures import WALL, native_reads, raw_state
from verify import OVERLOAD, SCOPES, stress_member_result, verify_restart_raw, verify_trial


class PublicationAssertions:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Patch clocks before frozen imports also bind their default arguments.
        self.enterContext(patch('time.time', return_value=WALL))
        self.enterContext(patch('time.monotonic', return_value=100.0))
        generations = iter(f'{n:032x}' for n in range(10000))
        self.enterContext(patch('uuid.uuid4', side_effect=lambda: SimpleNamespace(hex=next(generations))))
        self.native = self.enterContext(native_reads())
        self.service = importlib.import_module('meme_machine.solana_evidence_service')
        self.maintenance = importlib.import_module('meme_machine.solana_maintenance_runtime')
        config = importlib.import_module('meme_machine.solana_provider_config')
        self.endpoint = config.AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
        # The genuine constructors, health transaction, readers and close run.
        # Service loops, source/maintenance work, providers and helpers cannot.
        forbidden = AssertionError('material_work_forbidden_in_publication_regression')
        for target in ('socket.socket.connect', 'socket.create_connection',
                       'threading.Thread.start', 'subprocess.Popen'):
            self.enterContext(patch(target, side_effect=forbidden))
        self.enterContext(patch.object(self.service, 'serve', side_effect=forbidden))
        for name in ('source', 'archive_plan', 'retention', 'repair_apply'):
            self.enterContext(patch.object(self.service.ServiceState, name, side_effect=forbidden))
        self.enterContext(patch.object(self.maintenance.MaintenanceRuntime, 'turn', side_effect=forbidden))

    def health(self, path):
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as db:
            return {key: json.loads(value) for key, value in db.execute('SELECT key,value FROM service_health')}

    def generation(self, path):
        return self.health(path)['storage_maintenance']['maintenance_arbiter']['generation']

    def seed_old_state(self, root, *, full_profile=False):
        """Hand-written historical evidence; both generations use native publication."""
        root = Path(root); root.mkdir(parents=True, exist_ok=True)
        path = root/'d/db'
        state = self.service.ServiceState(path, self.endpoint)
        try:
            runtime = self.maintenance.MaintenanceRuntime(state)
            old = runtime.generation
            state.storage_metrics['unit_retained_metric'] = 37
            state.fence.health('storage_maintenance', dict(state.storage_metrics))
            self.assertEqual(self.generation(path), old)
            # These are counterfactual SQL rows, never ingested source frames.
            with state.writer.transaction():
                for scope in SCOPES:
                    state.writer.db.execute('INSERT INTO stream_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (scope, 11, 10, 'unit-hash', 'unit-parent', int(WALL-1), '[]', old, WALL-1, 1))
                    state.writer.db.execute('INSERT INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
                        (scope, 10, 11, WALL-1, 'UNIT ONLY'))
                    state.writer.db.execute('INSERT INTO cursors VALUES(?,?,?)', (scope, 11, WALL-1))
                    state.writer.db.execute('INSERT INTO gaps(scope,lo,hi,reason,created) VALUES(?,?,?,?,?)',
                        (scope, 10, None, 'service_restart', WALL-2))
                    state.writer.db.execute('INSERT INTO interests VALUES(?,?,?,?,?,?,?)',
                        ('unit-owner', scope, 3, 10, 'candidate', 1, WALL-7201))
                for key in ('archived_records', 'compacted_records', 'stream_accepted_messages'):
                    state.writer.db.execute('INSERT OR REPLACE INTO counters VALUES(?,?)', (key, 1))
            for scope in SCOPES:
                state.fence.health('finalized_frontier:'+scope,
                    dict(slot=11, time=WALL-(61 if self.reason == 'evidence_finalized_stale' else 1), seen=WALL))
            state.fence.health('owner_scheduler',
                safe_overload_row()['native_restart']['before']['health']['owner_scheduler'])
            state.failed = not full_profile
        finally:
            state.close()
        self.assertEqual(self.generation(path), old)
        self.assertEqual(self.health(path)['phase'], 'OFF' if full_profile else 'FAILED')
        return path, old

    def witness(self, root, *, full_profile=False, publication='native'):
        """Run the actual harness handoff, observing genuine native boundaries."""
        path, old = self.seed_old_state(root, full_profile=full_profile)
        original_runtime = self.maintenance.MaintenanceRuntime
        original_health = self.service.FinalizedFence.health
        original_plane = self.native.runtime.RuntimeEvidence
        original_close = self.service.ServiceState.close
        original_capture = overload.capture_stale_refusals
        trace = ['old-persisted']; current = {}; closing_state = False
        completed_native_publication = False

        def construct(state):
            self.assertEqual(self.generation(path), old)
            runtime = original_runtime(state)
            current.update(state=state, generation=runtime.generation)
            self.assertNotEqual(runtime.generation, old)
            self.assertEqual(state.storage_metrics['maintenance_arbiter']['generation'], runtime.generation)
            self.assertEqual(self.generation(path), old)
            self.assertEqual(self.health(path)['phase'], 'WARMING')
            trace.append('new-in-memory')
            return runtime

        def publish(fence, key, value):
            nonlocal completed_native_publication
            if key != 'storage_maintenance' or closing_state:
                return original_health(fence, key, value)
            self.assertIs(fence, current['state'].fence)
            self.assertEqual(value, current['state'].storage_metrics)
            self.assertEqual(self.generation(path), old)
            self.assertEqual(self.health(path)['phase'], 'WARMING')
            if publication == 'omitted':
                return
            if publication == 'fixture-seeded':
                # A coherently seeded DB is insufficient for this regression:
                # it must observe completion of the actual native health call.
                with closing(sqlite3.connect(path)) as db:
                    db.execute('UPDATE service_health SET value=? WHERE key=?', (json.dumps(value), key)); db.commit()
                return
            if publication == 'wrong':
                value = deepcopy(value); value['maintenance_arbiter']['generation'] = 'wrong-persisted-generation'
            if publication == 'uncommitted':
                current['state'].writer.db.execute('BEGIN IMMEDIATE')
            result = original_health(fence, key, value)
            if publication != 'native':
                return result
            self.assertFalse(current['state'].writer.db.in_transaction)
            self.assertEqual(self.generation(path), current['generation'])
            self.assertEqual(self.health(path)['storage_maintenance'], current['state'].storage_metrics)
            self.assertEqual(self.health(path)['phase'], 'WARMING')
            completed_native_publication = True
            trace.append('new-persisted')
            return result

        def plane(*args, **kwargs):
            if publication in ('native', 'fixture-seeded'):
                self.assertTrue(completed_native_publication, 'native_health_publication_not_exercised')
            trace.append('reader-opened')
            return original_plane(*args, **kwargs, clock=iter((WALL+.125, WALL+.375, WALL+.625)).__next__)

        def capture(*args, **kwargs):
            refusals = original_capture(*args, **kwargs)
            for refusal in refusals:
                self.assertEqual(refusal['phase'], 'WARMING')
                self.assertEqual(refusal['generation'], current['generation'])
                self.assertEqual(refusal['reason'], self.reason)
            trace.append('WARMING-capture')
            return refusals

        def close(state):
            nonlocal closing_state
            closing_state = True
            # Counterfactual uncommitted publication must not leak its transaction.
            if state.writer.db.in_transaction:
                state.writer.db.execute('ROLLBACK')
            original_close(state)
            self.assertEqual(self.health(path)['phase'], 'OFF')
            trace.append('OFF')

        failure = safe_overload_row()['native_restart']
        with patch.object(self.maintenance, 'MaintenanceRuntime', side_effect=construct), \
             patch.object(self.service.FinalizedFence, 'health', publish), \
             patch.object(self.native.runtime, 'RuntimeEvidence', side_effect=plane), \
             patch.object(self.service.ServiceState, 'close', close), \
             patch.object(overload, 'capture_stale_refusals', side_effect=capture):
            proof = overload.restart_witness(path, root,
                native_failure=None if full_profile else failure['native_failure'],
                failure_frames=[] if full_profile else failure['native_failure_frames'])
        self.assertTrue(completed_native_publication)
        self.assertEqual(trace, ['old-persisted', 'new-in-memory', 'new-persisted',
                                 'reader-opened', 'WARMING-capture', 'OFF'])
        self.assertEqual(proof['old_generation'], old)
        self.assertEqual(proof['new_generation'], current['generation'])
        self.assertEqual(proof['after']['health']['storage_maintenance']['unit_retained_metric'], 37)
        return proof

    def test_old_persisted_new_memory_native_published_WARMING_capture_OFF(self):
        proof = self.witness(self.root)
        checked = verify_restart_raw(self.root, {'native_restart': proof})
        self.assertEqual(checked['native_refusals_rechecked'], 3)
        self.assertTrue(checked['native_final_OFF_rechecked'])
        self.assertEqual([r['observed_at'] for r in proof['stale_refusals']], [WALL+.125, WALL+.375, WALL+.625])
        for refusal in proof['stale_refusals']:
            preserved = raw_state(self.root/refusal['raw_state_path'], self.native)
            self.assertEqual(preserved['health']['phase'], 'WARMING')
            self.assertEqual(preserved['health']['storage_maintenance']['maintenance_arbiter']['generation'], proof['new_generation'])

    def test_same_reader_refuses_before_native_publication_and_captures_after_commit(self):
        path, old = self.seed_old_state(self.root)
        state = self.service.ServiceState(path, self.endpoint)
        try:
            runtime = self.maintenance.MaintenanceRuntime(state)
            self.assertEqual(self.generation(path), old)
            self.assertNotEqual(runtime.generation, old)
            plane = self.native.runtime.RuntimeEvidence(path, owner='UNIT ONLY', clock=lambda: WALL+.125)
            try:
                with self.assertRaisesRegex(ValueError, '^refusal_restart_lifecycle_or_generation$'):
                    overload.capture_stale_refusals(plane, SCOPES, self.root, generation=runtime.generation)
                self.assertFalse(plane.reader.db.in_transaction)
                self.assertFalse((self.root/'refusal-native-state').exists())
                state.fence.health('storage_maintenance', dict(state.storage_metrics))
                self.assertEqual(self.generation(path), runtime.generation)
                self.assertEqual(self.health(path)['phase'], 'WARMING')
                refusals = overload.capture_stale_refusals(plane, SCOPES, self.root, generation=runtime.generation)
                self.assertEqual(len(refusals), 3)
                self.assertTrue(all(r['phase'] == 'WARMING' and r['generation'] == runtime.generation for r in refusals))
            finally:
                plane.close()
        finally:
            state.close()
        self.assertEqual(self.health(path)['phase'], 'OFF')

    def assert_failed_publication(self, publication):
        with self.assertRaisesRegex(ValueError, '^refusal_restart_lifecycle_or_generation$'):
            self.witness(self.root, publication=publication)
        # close's later successful publication and OFF cannot rescue capture.
        self.assertEqual(self.health(self.root/'d/db')['phase'], 'OFF')
        self.assertFalse((self.root/'refusal-native-state').exists())

    def test_omitted_health_publication_fails_despite_later_close_publication(self):
        self.assert_failed_publication('omitted')

    def test_wrong_durably_persisted_generation_is_rejected(self):
        self.assert_failed_publication('wrong')

    def test_uncommitted_native_health_publication_cannot_satisfy_capture(self):
        self.assert_failed_publication('uncommitted')

    def test_direct_fixture_generation_seeding_cannot_substitute_for_native_publication(self):
        with self.assertRaisesRegex(AssertionError, 'native_health_publication_not_exercised'):
            self.witness(self.root, publication='fixture-seeded')
        self.assertFalse((self.root/'refusal-native-state').exists())

    def test_final_OFF_is_independently_rechecked_after_real_publication_and_capture(self):
        proof = self.witness(self.root)
        verify_restart_raw(self.root, {'native_restart': proof})
        with closing(sqlite3.connect(self.root/'d/db')) as db:
            db.execute('UPDATE service_health SET value=? WHERE key=?', (json.dumps('WARMING'), 'phase')); db.commit()
        proof['after'] = dict(raw_state(self.root/'d/db', self.native), wall=WALL+2)
        with self.assertRaisesRegex(ValueError, 'final_native_teardown_missing'):
            verify_restart_raw(self.root, {'native_restart': proof})

    def test_final_generation_is_independently_rechecked_after_real_capture(self):
        proof = self.witness(self.root)
        health = self.health(self.root/'d/db')['storage_maintenance']
        health['maintenance_arbiter']['generation'] = 'forged-final-generation'
        with closing(sqlite3.connect(self.root/'d/db')) as db:
            db.execute('UPDATE service_health SET value=? WHERE key=?', (json.dumps(health), 'storage_maintenance')); db.commit()
        proof['after'] = dict(raw_state(self.root/'d/db', self.native), wall=WALL+2)
        with self.assertRaisesRegex(ValueError, 'generation_changed'):
            verify_restart_raw(self.root, {'native_restart': proof})

    def verify_C_terminal_path(self, full_profile):
        """Real handoff/raw verification; source/resource/process boundaries mocked."""
        folder = self.root/'trial'; folder.mkdir()
        members = []; expected = COHORT if full_profile else COHORT[:1]
        for index, (name, frames) in enumerate(expected, 1):
            member = folder/f'm{index}'
            proof = self.witness(member, full_profile=full_profile)
            source = dict(clock_samples=[])
            row = safe_overload_row()
            row.update(member=name, frames=frames, native_restart=proof, source_receipt=source,
                       workload_valid=full_profile, observation_valid=True,
                       failure=proof['native_failure'], failure_frames=proof['native_failure_frames'])
            if name == 'recovery-1':
                row['observer_assessment'] = {'passed': full_profile}
            row.update(stress_member_result(row))
            self.assertTrue(row['mandatory_native_safety_pass'], row['native_safety_errors'])
            persist(member/'result.json', dict(failure=row['failure'], failure_frames=row['failure_frames']))
            persist(member/'MEMBER_RESULT.json', row); persist(member/'SOURCE_RECEIPT.json', source)
            members.append(dict(member=name, frames=frames, valid=True, exit_code=0,
                                member_result_sha256=file_sha(member/'MEMBER_RESULT.json')))
        outcome = 'FULL_PROFILE_SAFETY_PASS' if full_profile else OVERLOAD
        cohort = dict(kind='C', sequence=1, trial_id='UNIT ONLY', mode='stress', declaration_sha256='unit', valid=True,
            members=members, outcome=outcome, complete_profile=full_profile, no_further_members=not full_profile,
            capacity_credit=False, diagnostic_outcome='PASS' if full_profile else 'FAILED_DIAGNOSTIC')
        if not full_profile:
            cohort['terminal_member'] = members[-1]['member']
        clocks = interval(); persist(folder/'COHORT_RESULT.json', cohort)
        persist(folder/'TRIAL_RESULT.json', dict(cohort, start_perf_ns=clocks['start_perf_ns'], end_perf_ns=clocks['end_perf_ns'],
            elapsed_ns=clocks['end_perf_ns']-clocks['start_perf_ns'], execution_interval=clocks))
        persist(folder/'MEASURED_PERSISTENCE_COMPLETE.json', dict(cohort=cohort, all_native_helpers_terminated=True,
            resource_errors=[], no_subtraction=True, no_double_counting=True))
        persist(folder/'PROCESS_TERMINATION.json', dict(trial_process_terminated=True, all_native_helpers_terminated=True,
            real_monotonic_ns=clocks['helpers_terminated_real_monotonic_ns']))
        seal(folder)
        declaration = dict(class_id='C', environment_sha256='unit-env', production_workload_sha256='unit-workload',
            trials=[dict(sequence=1, trial_id='UNIT ONLY', mode='stress')])
        life = dict(pid=21, start_ticks=5, role='member', start_ns=11*10**9, end_ns=18*10**9)
        with patch('verify.native_verifier_context', return_value=nullcontext()), \
             patch('verify.verify_stress_native', return_value=full_profile), \
             patch('verify.verify_native_db'), \
             patch('verify.verify_source', return_value=dict(first_release_ns=12*10**9, last_release_ns=13*10**9, frames=0)), \
             patch('verify.verify_origins', return_value={'lifetimes': [life], 'constraints_sha256': 'UNIT ONLY'}), \
             patch('verify.verify_resource_timeline', return_value={'constraints_sha256': 'UNIT ONLY'}), \
             patch('verify.verify_restart_raw', wraps=verify_restart_raw) as restart:
            result = verify_trial(folder, declaration, declaration_sha256='unit', allocation={})
        self.assertEqual(restart.call_count, len(expected))
        self.assertEqual(result['outcome'], outcome)
        self.assertEqual(result['complete_cohort'], full_profile)
        self.assertEqual(result['safety_only'], not full_profile)
        self.assertEqual(result['diagnostic_outcome'], 'PASS' if full_profile else 'FAILED_DIAGNOSTIC')
        self.assertFalse(result['capacity_credit']); self.assertFalse(result['observer_credit'])

    def test_C_full_profile_uses_corrected_handoff_and_independent_final_verifier(self):
        self.verify_C_terminal_path(True)

    def test_C_safety_only_terminal_uses_corrected_handoff_and_independent_final_verifier(self):
        self.verify_C_terminal_path(False)


class DiscontinuousPublicationTests(PublicationAssertions, unittest.TestCase):
    reason = 'evidence_discontinuous'


class FinalizedStalePublicationTests(PublicationAssertions, unittest.TestCase):
    reason = 'evidence_finalized_stale'
