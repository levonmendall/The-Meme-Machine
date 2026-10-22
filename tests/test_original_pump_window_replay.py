"""Disposable public-API tests for the engineering-only logical replay command."""
from copy import deepcopy
import asyncio
import sys
import threading
from collections import Counter
from pathlib import Path
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from engineering.diagnostics import replay_original_pump_window as replay
from engineering.diagnostics import replay_original_pump_window as original
from engineering.diagnostics import replay_concurrent_pump_window as concurrent
from meme_machine.solana_economic_preparation import prepare_economic_record
from meme_machine.solana_selective_history import PROGRAMS, economic_records
from tests.test_solana_selective_evidence import FIXTURE


def captured():
    rows = [row for tx in deepcopy(FIXTURE['pump']) for row in economic_records(
        'pump', PROGRAMS['pump'], tx, endpoint_identity='a'*64,
        seen=1791400000.25, source='alchemy_finalized_stream')]
    creation = next(r for r in rows if r.payload['event']['event_type'] == 'create')
    trades = [r for r in rows if r.payload['event']['event_type'] == 'trade'
              and r.payload['event']['mint'] == creation.payload['event']['mint']]
    assert trades
    return [prepare_economic_record(r).record for r in (creation, *trades[:2])]


class CapturedParcel:
    """Small captured cohort exercises the same internal consumer APIs.

    The externally accepted Parcel still requires the exact frozen9/5081
    source. This fixture does not impersonate that production window.
    """
    def __init__(self):
        records = captured()
        self.records = {r.identity: r for r in records}
        self.inputs = [dict(kind='input', role='warmup' if i == 0 else 'measured',
            sequence=100+3*i, identity=r.identity, scope=r.scope, slot=r.slot,
            first_seen=r.observed_at) for i, r in enumerate(records)]
        self.warmup, self.measured = self.inputs[:1], self.inputs[1:]
        self.manifest = dict(source={'fixture': 'captured_public_native_records'},
                             endpoints={'fixture': True})
        self.manifest_fingerprint = (0, 'a'*64); self.fingerprint = (0, 'b'*64)
        self.context = Counter({'coverage': 1}); self.original_encodings = {'text': len(records)}
        observed = dict(schema='managed-pump-qualification-v1',
            source_identity='pump-source:'+records[0].identity, native_kind='pump_create',
            stage='creation_observed', full_qualification_complete=False, financial_authority=False)
        self.original_qualifications = {records[0].identity: dict(stage='creation_observed',
            body_sha256=replay.sha(replay.canonical(observed)))}
        self.checked = False

    def record(self, item):
        row = deepcopy(self.records[item['identity']])
        return row, replay.sha(replay.canonical(row.body())), 'text'

    def unchanged(self):
        self.checked = True


class OriginalWindowReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_actual_captured_pipeline_abba_preserves_pending_prelude_and_semantics(self):
        parcel = CapturedParcel()
        with patch('meme_machine.operational.managed_pump_qualification.MarketSnapshotProvider',
                   side_effect=AssertionError('no_network_provider_construction')):
            result = replay.benchmark(parcel, self.root/'abba')
        self.assertTrue(result['coherent']); self.assertTrue(parcel.checked)
        self.assertEqual([r['implementation'] for r in result['runs']],
                         ['reference', 'optimized', 'optimized', 'reference'])
        self.assertEqual(result['context_rows_imported_as_state'], 0)
        self.assertEqual(result['context_rows_preserved_as_lineage'], {'coverage': 1})
        self.assertFalse(result['full_strategy_equivalence_proven'])
        self.assertFalse(result['throughput_readiness_proven'])
        hashes = {r['semantic_sha256'] for r in result['runs']}
        self.assertEqual(len(hashes), 1)
        self.assertEqual([r['implementation'] for r in result['architecture_runs']],
                         ['owner_optimized', 'optimized', 'optimized', 'owner_optimized'])
        for row in result['architecture_runs']:
            self.assertEqual(row['qualification_implementation'], 'optimized')
            self.assertEqual(row['semantic_sha256'], result['runs'][0]['semantic_sha256'])
            self.assertEqual(row['history_semantic_sha256'], result['runs'][0]['history_semantic_sha256'])
            self.assertEqual(row['history_state_sha256'], result['runs'][0]['history_state_sha256'])
            self.assertTrue(row['reader_restart_verified'])
            self.assertFalse(row['publication_thread_handoff_exercised'])
        counts = []
        for row in result['runs']:
            self.assertEqual(row['publication_implementation'],
                'owner_capture' if row['implementation'] == 'reference' else 'readonly_capture_actor')
            self.assertFalse(row['publication_thread_handoff_exercised'])
            self.assertEqual(row['initial']['durably_observed_native_events'], 0)
            self.assertEqual(row['initial']['native_event_backlog'], 1)
            self.assertEqual(row['completed'], {'warmup': 1, 'measured': len(parcel.measured)})
            self.assertEqual(row['final']['native_event_backlog'], 0)
            self.assertTrue(row['reader_restart_verified'])
            self.assertFalse(row['first_lazy_source_queries_traced'])
            self.assertTrue(row['timing']['usable_for_timing_comparison'])
            self.assertEqual(row['primitive_costs'], [])
            self.assertEqual(row['publication_batches'], [])
            self.assertEqual(row['classification_sql'], [])
            self.assertFalse(any(m['bucket'].startswith('trace_') for m in row['sql']))
            self.assertEqual(row['provider_requests'], 0)
            self.assertEqual(row['original_input_storage_encodings'], row['fresh_input_storage_encodings'])
            self.assertEqual(row['fresh_input_storage_encodings'], {'text': len(parcel.inputs)})
            self.assertEqual(row['stages']['creation_observed'], 1)
            self.assertEqual(row['original_comparison']['original_membership'], {'warmup': 1})
            self.assertEqual(row['original_comparison']['original_body_hash_matches'], 1)
            self.assertFalse(row['original_comparison']['original_decision_clock_replayed'])
            self.assertEqual(sum(row['stages'].values()), len(parcel.inputs))
        for row in result['profiled_runs']:
            self.assertFalse(row['timing']['usable_for_timing_comparison'])
            self.assertTrue(row['first_lazy_source_queries_traced'])
            self.assertTrue(any(m['role'] == 'qualification' and m['bucket'] == 'trace_INSERT'
                                and m['calls'] > 0 for m in row['sql']))
            self.assertTrue(any(m['role'] == 'qualification' and m['bucket'] == 'trace_COMMIT'
                                and m['calls'] > 0 for m in row['sql']))
            self.assertTrue(any(m['role'] == 'candidate_reference' and m['bucket'] == 'trace_SELECT'
                                and m['calls'] > 0 for m in row['sql']))
            self.assertTrue(any(m['primitive'] == 'decode_body' and m['native_input_encoding'] == 'text'
                                and m['calls'] > 0 for m in row['primitive_costs']))
            self.assertTrue(row['publication_batches'])
            for batch in row['publication_batches']:
                self.assertLessEqual(batch['U_distinct_binding_keys'], batch['N_outbox_rows'])
                self.assertEqual(batch['E_empty_second_phase'], int(not batch['proof_rows'] and not batch['refresh_rows']))
            self.assertTrue(row['classification_sql'])
            self.assertFalse(any(m['role'] == 'qualification' and m['bucket'] in ('trace_INSERT', 'trace_UPDATE')
                                 for m in row['classification_sql']))
            self.assertTrue(all(m['stage'] in replay.STAGES for m in row['classification_sql']))
            counts.append(sum(m['calls'] for m in row['sql'] if m['phase'] == 'qualification'
                              and m['bucket'] in ('trace_SELECT', 'trace_WITH')))
        self.assertGreater(counts[0], counts[1])
        comparison = replay.compare_reports(result, deepcopy(result))
        self.assertTrue(comparison['same_semantics'])
        self.assertTrue(comparison['timing_comparison_available'])
        self.assertFalse(comparison['native_acquisition_join_repair_exercised'])
        changed = deepcopy(result); changed['runs'][1]['history_state_sha256']['source_receipts'] = '0'*64
        mismatch = replay.compare_reports(result, changed)
        self.assertFalse(mismatch['same_semantics']); self.assertFalse(mismatch['timing_comparison_available'])
        self.assertEqual(mismatch['unprofiled_timing'], {})
        self.assertIn('history_state_sha256', mismatch['arms'][3]['differing_fields'])
        self.assertTrue(comparison['architecture_comparison_available'])
        self.assertEqual(len(comparison['arms']), 10)
        changed = deepcopy(result); changed['architecture_runs'][1]['history_state_sha256']['source_receipts'] = '0'*64
        mismatch = replay.compare_reports(result, changed)
        self.assertFalse(mismatch['same_semantics']); self.assertFalse(mismatch['timing_comparison_available'])
        self.assertIn('history_state_sha256', mismatch['arms'][7]['differing_fields'])
        legacy = deepcopy(result); del legacy['architecture_runs']
        compatible = replay.compare_reports(legacy, result)
        self.assertTrue(compatible['same_semantics'])
        self.assertFalse(compatible['architecture_comparison_available'])
        self.assertEqual(len(compatible['arms']), 6)
        changed = deepcopy(result); changed['input_parcel_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'comparison_input_or_scope_mismatch'):
            replay.compare_reports(result, changed)
        # The new stores remain private under an ordinary caller umask too.
        for path in (self.root/'abba').rglob('*.sqlite'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_unprofiled_arm_never_copies_sql_counters_or_observes_publication_populations(self):
        # Directly invoking a single arm must establish the same private-file
        # umask as benchmark(), which normally owns the arm's setup boundary.
        previous = os.umask(0o077)
        try:
            with (patch.object(replay.Costs, 'sql_snapshot', side_effect=AssertionError('profile_only')),
                  patch.object(replay.Costs, 'publication_probe', side_effect=AssertionError('profile_only'))):
                result = replay.run_one(CapturedParcel(), self.root/'no-probes', 'optimized')
        finally:
            os.umask(previous)
        self.assertEqual(result['classification_sql'], [])
        self.assertEqual(result['publication_batches'], [])
        self.assertFalse(result['timing']['profiled'])

    def test_classification_sql_deltas_exclude_other_classifications_and_batch_writes(self):
        costs = replay.Costs(); costs.phase = 'qualification'
        before = costs.sql_snapshot()
        costs.metric('candidate_reference', 'trace_SELECT')['calls'] += 3
        costs.attribute_classification('creation_unavailable', before)
        # The real observation write is outside _evaluate and is not assigned
        # to either classification merely because it occurs between them.
        costs.metric('qualification', 'trace_INSERT')['calls'] += 1
        before = costs.sql_snapshot()
        costs.metric('qualification', 'trace_SELECT')['calls'] += 1
        costs.attribute_classification('native_five_second_fairness', before)
        rows = costs.classification_report()
        self.assertEqual(sum(row['calls'] for row in rows), 4)
        self.assertEqual({row['stage'] for row in rows}, {'creation_unavailable', 'native_five_second_fairness'})
        self.assertFalse(any(row['bucket'] == 'trace_INSERT' for row in rows))

    def test_external_commit_before_ack_replays_original_outbox_without_duplicates(self):
        self._external_commit_before_ack(actor=False)

    def test_read_actor_commit_before_ack_reconstructs_from_durable_outbox(self):
        self._external_commit_before_ack(actor=True)

    def _external_commit_before_ack(self, *, actor):
        from meme_machine.solana_evidence_plane import EvidenceWriter
        from meme_machine.solana_evidence_service import FinalizedFence
        from meme_machine.solana_selective_history import SelectiveHistory
        from meme_machine.solana_selective_source import STATE_SCHEMA
        from meme_machine.solana_prewarm_startup import SCHEMA as STARTUP_SCHEMA
        from meme_machine.solana_candidate_lifecycle import CandidateLifecycle
        from meme_machine.solana_rolling_history import RollingHistory
        from meme_machine.runtime.candidate_history import CandidateHistory
        row = captured()[-1]
        writer = EvidenceWriter(self.root/'source.sqlite', clock=lambda: row.observed_at)
        self.addCleanup(writer.close)
        fence = FinalizedFence(writer, endpoint_identity='a'*64)
        history = SelectiveHistory(writer, fence.endpoint_identity, clock=lambda: row.observed_at)
        history.db.executescript(STATE_SCHEMA); history.db.executescript(STARTUP_SCHEMA)
        history.lifecycle = life = CandidateLifecycle(history, candidate_path=self.root/'history.sqlite')
        history.rolling = RollingHistory(history); life.delivery_separated = True
        history.ingest([prepare_economic_record(row)])
        result = replay.publish(life, actor_state={} if actor else None, interrupt_before_ack=True)
        self.assertGreater(result['outbox_rows'], 0)
        self.assertIsNone(history.db.execute(
            'SELECT 1 FROM candidate_history_outbox WHERE consumed IS NULL').fetchone())
        consumer = CandidateHistory(life.path)
        try:
            self.assertEqual(consumer.db.execute('SELECT count(*) FROM canonical_event_refs').fetchone(), (1,))
            actual = consumer.event('pump', row.payload['event']['mint'], 'pump-source:'+row.identity)
            self.assertEqual(actual['slot'], row.slot)
            self.assertEqual(actual['payload']['available_time'], int(row.observed_at))
            self.assertEqual(consumer.db.execute('SELECT count(*) FROM funding').fetchone(), (0,))
            self.assertEqual(consumer.db.execute('SELECT count(*) FROM decisions').fetchone(), (0,))
        finally:
            consumer.close()

    def test_sql_probe_retains_diagnostic_errors_and_first_lazy_query(self):
        from meme_machine.runtime.sqlite_failure import connect
        costs = replay.Costs()
        with costs.sqlite(self.root):
            db = sqlite3.connect(self.root/'qualification.sqlite', isolation_level=None)
            db.execute('CREATE TABLE data(value INTEGER)')
            db.execute('BEGIN IMMEDIATE'); db.execute('INSERT INTO data VALUES(1)'); db.execute('COMMIT')
            self.assertEqual(db.execute('SELECT value FROM data').fetchall(), [(1,)])
            db.close()
            lazy = connect((self.root/'qualification.sqlite').as_uri()+'?mode=ro',
                diagnostic_role='candidate_reference', uri=True)
            self.assertEqual(lazy.execute('SELECT count(*) FROM data').fetchone(), (1,))
            with self.assertRaises(sqlite3.OperationalError) as failure:
                lazy.execute('SELECT missing FROM data')
            self.assertEqual(failure.exception.sqlite_errorcode, sqlite3.SQLITE_ERROR)
            self.assertEqual(lazy._failure_metadata['role'], 'candidate_reference')
            lazy.close()
        rows = costs.report()
        self.assertEqual(sum(r['calls'] for r in rows if r['role'] == 'candidate_reference'
                             and r['bucket'] == 'trace_SELECT'), 1)
        self.assertTrue(any(r['role'] == 'qualification' and r['bucket'] == 'trace_COMMIT' for r in rows))
        self.assertTrue(any(r['bucket'] == 'fetch_api' and r['wall_nanoseconds'] > 0 for r in rows))
        with costs.sqlite(self.root):
            with self.assertRaisesRegex(ValueError, 'sqlite_outside_fresh_store'):
                sqlite3.connect(self.root.parent/'unapproved.sqlite')

    def test_network_probe_is_deny_only_and_output_must_be_create_only(self):
        import socket
        with replay.no_network():
            with self.assertRaisesRegex(ValueError, 'network_refused'):
                socket.create_connection(('127.0.0.1', 1))
        existing = self.root/'exists'; existing.mkdir()
        with self.assertRaisesRegex(ValueError, 'new_output_required'):
            replay.benchmark(CapturedParcel(), existing)

    def test_manifest_pin_and_duplicate_keys_refuse_before_pipeline(self):
        directory = self.root/'parcel'; directory.mkdir()
        path = directory/'manifest.json'
        path.write_bytes(b'{"schema":"wrong"}\n')
        with self.assertRaisesRegex(ValueError, 'manifest_hash'):
            replay.Parcel(directory, '0'*64)
        with self.assertRaisesRegex(ValueError, 'duplicate_json_key'):
            replay.loads(b'{"x":1,"x":2}')
        with self.assertRaisesRegex(ValueError, 'nonfinite_json'):
            replay.loads(b'{"x":NaN}')
        path.unlink(); path.symlink_to(self.root/'outside')
        with self.assertRaises(OSError):
            replay.Parcel(directory, '0'*64)

    def parcel(self):
        """Small-body full5090 cohort tests exact external selection rules."""
        directory = self.root/'full-cohort'; directory.mkdir()
        inputs, native = [], []
        for index in range(5090):
            identity = 'public-fixture-native-'+str(index)
            role = 'warmup' if index < 9 else 'measured'
            item = dict(kind='input', role=role, sequence=100+3*index,
                identity=identity, scope='program:pump', slot=100+index, first_seen=1791400000.25)
            inputs.append(item)
            body = dict(identity=identity, scope='program:pump', slot=item['slot'],
                signature='signature-'+str(index), program=PROGRAMS['pump'], addresses=['mint'],
                market_time=1791399999, event_index=0, transaction_index=index, kind='event',
                payload=dict(event=dict(event_type='trade', mint='mint', slot=item['slot'], market_time=1791399999)))
            value = dict(body, hash=replay.sha(replay.canonical(body)), first_seen=item['first_seen'], archive=None,
                canonical=body, storage_encoding='text', storage_body=replay.canonical(body).decode(), hot_chunks=[],
                cold_archive_sha256=None, source_lineage=[dict(source='alchemy_finalized_stream',
                    endpoint_sha256='a'*64, observed_at=item['first_seen'])], historical_commit_visibility_proven=False)
            value.pop('payload'); value.pop('addresses')
            native.append(dict(kind='native_record', role=role, value=value))
        context = dict(kind='market_context', table='coverage', columns=['available'], row=[1791400000.],
            temporal_use='lineage_only_no_early_state_or_ack_import', historical_visibility_proven=False)
        observations = [dict(kind='original_qualification', sequence=r['sequence'], identity=r['identity'],
            candidate='mint', slot=r['slot'], body_sha256='b'*64, stage='creation_unavailable', full_complete=False,
            source_identity='pump-source:'+r['identity'], financial_authority=False,
            temporal_use='terminal_observation_only_no_fresh_state_import', original_decision_clock_available=False)
            for r in inputs[:4062]]
        rows = inputs+native+[context]+observations
        raw = b''.join(replay.canonical(row)+b'\n' for row in rows)
        (directory/'market-inputs.jsonl').write_bytes(raw)
        manifest = dict(schema=replay.SCHEMA, source=replay.SOURCE, warmup_inputs=9, measured_inputs=5081,
            financial_authority=False, old_ack_authority_imported=False, exact_historical_visibility_proven=False,
            original_sqlite_layout_preserved=False, original_quote_oracle_concentration_inputs_available=False,
            full_strategy_decision_equivalence_proven=False, bytes=len(raw), parcel_sha256=replay.sha(raw),
            rows=len(rows), native_records=len(native), context_rows={'coverage': 1},
            original_selected_observation_membership_available=True,
            original_qualification=dict(available=True, observations=4062, cursor=inputs[4061]['sequence'],
                stages={'creation_unavailable': 4062}, selected_observed=4053, warmup_observed=9,
                outside_window_observed=0, selected_unobserved=1028, warmup_unobserved=0,
                body_rows_sha256=replay.sha(replay.canonical([
                    [r['sequence'], r['identity'], r['body_sha256']] for r in observations]))),
            measured_identities_sha256=replay.sha(replay.canonical([
                [r[k] for k in ('sequence', 'identity', 'scope', 'slot', 'first_seen')] for r in inputs[9:]])),
            endpoints=dict(first=dict(monotonic=replay.SOURCE['first_monotonic'], incoming_native_events=9,
                durably_observed_native_events=0, durable_sequence=None, stages={}, latest_source_sequence=inputs[8]['sequence']),
                last=dict(monotonic=replay.SOURCE['last_monotonic'], incoming_native_events=5090,
                durably_observed_native_events=4062, durable_sequence=inputs[4061]['sequence'],
                stages={'creation_unavailable': 4062}, latest_source_sequence=inputs[-1]['sequence'])))
        return directory, manifest

    def test_actual_parcel_schema_verifies_exact_noncontiguous5081_membership(self):
        directory, manifest = self.parcel()
        raw = replay.canonical(manifest)
        (directory/'manifest.json').write_bytes(raw)
        parcel = replay.Parcel(directory, replay.sha(raw))
        self.assertEqual(len(parcel.warmup), 9); self.assertEqual(len(parcel.measured), 5081)
        self.assertEqual(parcel.measured[0]['sequence']-parcel.warmup[-1]['sequence'], 3)
        record, checksum, encoding = parcel.record(parcel.measured[0])
        self.assertEqual(encoding, 'text')
        self.assertEqual(replay.sha(replay.canonical(record.body())), checksum)
        self.assertEqual(parcel.context, {'coverage': 1})
        self.assertEqual(len(parcel.original_qualifications), 4062)
        self.assertEqual(parcel.manifest['original_qualification']['selected_observed'], 4053)
        for case in ('cohort_digest', 'endpoint_membership', 'authority', 'late_observation'):
            changed = deepcopy(manifest)
            if case == 'cohort_digest':
                changed['measured_identities_sha256'] = '0'*64
            elif case == 'endpoint_membership':
                changed['endpoints']['first']['latest_source_sequence'] += 1
            elif case == 'late_observation':
                changed['endpoints']['last']['durable_sequence'] += 3
            else:
                changed['old_ack_authority_imported'] = True
            raw = replay.canonical(changed); (directory/'manifest.json').write_bytes(raw)
            with self.subTest(case=case), self.assertRaises(ValueError):
                replay.Parcel(directory, replay.sha(raw))


class ConcurrentWindowReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_real_owner_actor_and_qualifier_overlap_preserve_all_semantics_and_restart(self):
        parcel = CapturedParcel()
        switch_interval = sys.getswitchinterval()
        # The public cohort has no oracle/quote/concentration input. No real
        # provider may be constructed to fill that missing evidence.
        with patch('meme_machine.operational.managed_pump_qualification.MarketSnapshotProvider',
                   side_effect=AssertionError('no_provider_construction')):
            result = concurrent.benchmark(parcel, self.root/'concurrent', batch=1, rate=5, seconds=30)
        self.assertTrue(result['engineering_validation_passed'])
        self.assertTrue(result['coherent']); self.assertTrue(result['concurrency_exercised'])
        self.assertEqual(result['semantic_fields'], list(original.SEMANTIC_FIELDS))
        self.assertEqual(len(result['semantic_fields']), 22)
        self.assertEqual(result['different_semantic_fields'], [])
        self.assertEqual(result['different_stores'], [])
        self.assertTrue(parcel.checked)
        self.assertTrue(result['production_admission_and_owner_policy'])
        self.assertEqual(result['owner_thread_fairness_seconds'], .0005)
        self.assertEqual(sys.getswitchinterval(), switch_interval)
        self.assertEqual(result['input_provenance'], 'public_fixture')
        self.assertTrue(result['publication_thread_handoff_exercised'])
        self.assertFalse(result['actor_capture_service_cpu_separately_measured'])
        self.assertFalse(result['financial_authority'])
        self.assertFalse(result['throughput_readiness_proven'])
        self.assertFalse(result['full_qualification_proven'])
        self.assertEqual(result['quote_inputs'], 'unavailable_no_synthetic_quotes')
        self.assertEqual(result['context_rows_imported_as_state'], 0)
        left, right = result['runs']
        self.assertEqual(left['store_fingerprints'], right['store_fingerprints'])
        self.assertEqual(len(left['store_fingerprints']), 6)
        for row in result['runs']:
            self.assertTrue(row['distinct_pipeline_threads'])
            self.assertTrue(row['production_work_capabilities']['candidate_delivery_capture_actor'])
            self.assertIsInstance(row['production_work_capabilities']['candidate_delivery_publication_handoff'], bool)
            self.assertTrue(row['reader_restart_verified'])
            self.assertTrue(row['owner_actor_restart_verified'])
            self.assertEqual(row['initial']['native_event_backlog'], len(parcel.warmup))
            self.assertEqual(row['final']['native_event_backlog'], 0)
            self.assertEqual(row['completed'], {'warmup':len(parcel.warmup), 'measured':len(parcel.measured)})
            self.assertEqual(row['provider_requests'], 0)
            self.assertGreater(row['owner_counters']['owner.stage.candidate_delivery_ack.calls'], 0)
            self.assertNotIn('owner.stage.candidate_delivery_capture.calls', row['owner_counters'])
            self.assertEqual(row['counters']['offered_measured_events'], len(parcel.measured))
            self.assertEqual(row['counters']['admitted_measured_events'], len(parcel.measured))
            self.assertLessEqual(row['counters']['arrival_queue_peak_batches'], concurrent.ARRIVAL_BATCHES)
        self.assertGreater(right['counters']['delivery_before_intake_finished'], 0)
        self.assertGreater(right['counters']['observed_before_intake_finished'], 0)
        self.assertGreater(right['counters']['intake_turns_without_qualification_drain'], 0)
        self.assertEqual(left['counters'].get('intake_turns_without_qualification_drain', 0), 0)

    def test_every_original_semantic_field_is_required_and_mutation_fails(self):
        arm = {key: ['retained', key] for key in original.SEMANTIC_FIELDS}
        arm['store_fingerprints'] = {key:'original' for key in concurrent.STORE_FIELDS}
        self.assertTrue(concurrent.compare_arms(arm, deepcopy(arm))['coherent'])
        for key in original.SEMANTIC_FIELDS:
            with self.subTest(field=key):
                changed = deepcopy(arm); changed[key].append('mutated')
                result = concurrent.compare_arms(arm, changed)
                self.assertFalse(result['coherent']); self.assertEqual(result['different_semantic_fields'], [key])
                del changed[key]
                self.assertFalse(concurrent.compare_arms(arm, changed)['coherent'])
        changed = deepcopy(arm); changed['store_fingerprints']['canonical_native'] = 'mutated'
        self.assertEqual(concurrent.compare_arms(arm, changed)['different_stores'], ['canonical_native'])
        changed = deepcopy(arm); changed['store_fingerprints']['unknown'] = 'unreviewed'
        self.assertFalse(concurrent.compare_arms(arm, changed)['coherent'])

    def test_cohort_order_and_authentication_are_checked_before_private_stores(self):
        parcel = CapturedParcel()
        parcel.inputs[1]['sequence'] = parcel.inputs[0]['sequence']
        with self.assertRaisesRegex(ValueError, 'concurrent_cohort_order'):
            concurrent.benchmark(parcel, self.root/'rejected', seconds=1)
        self.assertFalse((self.root/'rejected').exists())
        parcel = CapturedParcel()
        record = parcel.records[parcel.inputs[1]['identity']]
        parcel.inputs[1]['first_seen'] = record.observed_at + 1
        with self.assertRaisesRegex(ValueError, 'concurrent_normalized_identity'):
            concurrent.benchmark(parcel, self.root/'rejected-auth', seconds=1)
        self.assertFalse((self.root/'rejected-auth').exists())

    def test_arrival_batch_and_deadline_limits_reject_unbounded_options(self):
        for batch, rate, seconds in ((0, 10, 1), (65, 10, 1), (1, 0, 1),
                                     (1, float('inf'), 1), (1, 1, 0), (1, 1, 1801)):
            with self.subTest(batch=batch, rate=rate, seconds=seconds), self.assertRaises(ValueError):
                concurrent.limits(batch, rate, seconds)

    def test_repeated_cancellation_of_either_physical_reader_open_closes_returned_handles(self):
        from meme_machine.operational.managed_pump_qualification import QualificationReader
        native_open, native_close = QualificationReader._open, QualificationReader.close
        for blocked_open in (1, 2):
            with self.subTest(open=blocked_open):
                opened = threading.Event(); release = threading.Event()
                opening_threads = []; closed = []
                def held(reader):
                    fresh = reader.db is None
                    result = native_open(reader)
                    if fresh and result:
                        opening_threads.append(threading.get_ident())
                        if len(opening_threads) == blocked_open:
                            opened.set()
                            if not release.wait(10):raise RuntimeError('test_reader_open_release_deadline')
                    return result
                def close(reader):
                    closed.append(threading.get_ident())
                    return native_close(reader)
                async def scenario():
                    parcel = CapturedParcel(); records, batches, _ = concurrent.freeze(parcel, 1)
                    task = asyncio.create_task(concurrent.run_arm(parcel, records, batches,
                        self.root/('reader-cancel-'+str(blocked_open)), concurrent=True, rate=5, seconds=20))
                    try:
                        async def entered():
                            while not opened.is_set():
                                if task.done():task.result()
                                await asyncio.sleep(.001)
                        await asyncio.wait_for(entered(), 10)
                        task.cancel(); await asyncio.sleep(0); task.cancel(); release.set()
                        with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task, 10)
                    finally:
                        release.set()
                        if not task.done():task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                old_umask = os.umask(0o077)
                try:
                    with replay.no_network(), patch.object(QualificationReader, '_open', held), patch.object(QualificationReader, 'close', close):
                        asyncio.run(scenario())
                finally:os.umask(old_umask)
                self.assertEqual(len(opening_threads), blocked_open)
                self.assertEqual(closed, opening_threads)

    def test_repeated_cancellation_joins_native_owner_initialization_before_close(self):
        from meme_machine.solana_evidence_plane import EvidenceWriter
        native_init, native_close = EvidenceWriter.__init__, EvidenceWriter.close
        entered = threading.Event(); release = threading.Event(); initialized = []; closed = []
        def held(writer, *args, **kwargs):
            native_init(writer, *args, **kwargs)
            initialized.append(threading.get_ident()); entered.set()
            if not release.wait(10):raise RuntimeError('test_owner_ready_release_deadline')
        def close(writer):
            closed.append(threading.get_ident()); return native_close(writer)
        async def scenario():
            parcel = CapturedParcel(); records, batches, _ = concurrent.freeze(parcel, 1)
            task = asyncio.create_task(concurrent.run_arm(parcel, records, batches,
                self.root/'owner-ready-cancel', concurrent=True, rate=5, seconds=20))
            try:
                async def opened():
                    while not entered.is_set():
                        if task.done():task.result()
                        await asyncio.sleep(.001)
                await asyncio.wait_for(opened(), 10)
                task.cancel(); await asyncio.sleep(0); task.cancel(); release.set()
                with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task, 10)
            finally:
                release.set()
                if not task.done():task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        old_umask = os.umask(0o077)
        try:
            with replay.no_network(), patch.object(EvidenceWriter, '__init__', held), patch.object(EvidenceWriter, 'close', close):
                asyncio.run(scenario())
        finally:os.umask(old_umask)
        self.assertEqual(len(initialized), 1)
        self.assertEqual(closed, initialized)


if __name__ == '__main__':
    unittest.main()
