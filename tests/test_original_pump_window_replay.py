"""Disposable public-API tests for the engineering-only logical replay command."""
from copy import deepcopy
from collections import Counter
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from engineering.diagnostics import replay_original_pump_window as replay
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
        counts = []
        for row in result['runs']:
            self.assertEqual(row['initial']['durably_observed_native_events'], 0)
            self.assertEqual(row['initial']['native_event_backlog'], 1)
            self.assertEqual(row['completed'], {'warmup': 1, 'measured': len(parcel.measured)})
            self.assertEqual(row['final']['native_event_backlog'], 0)
            self.assertTrue(row['reader_restart_verified'])
            self.assertFalse(row['first_lazy_source_queries_traced'])
            self.assertTrue(row['timing']['usable_for_timing_comparison'])
            self.assertEqual(row['primitive_costs'], [])
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
            counts.append(sum(m['calls'] for m in row['sql'] if m['phase'] == 'qualification'
                              and m['bucket'] in ('trace_SELECT', 'trace_WITH')))
        self.assertGreater(counts[0], counts[1])
        # The new stores remain private under an ordinary caller umask too.
        for path in (self.root/'abba').rglob('*.sqlite'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_external_commit_before_ack_replays_original_outbox_without_duplicates(self):
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
        result = replay.publish(life, interrupt_before_ack=True)
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


if __name__ == '__main__':
    unittest.main()
