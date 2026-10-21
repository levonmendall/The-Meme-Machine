"""Unprivileged, provider-free logical replay of the sealed a029 Pump window.

This engineering command never reads an original DB or imports terminal ACKs,
coverage, health or financial state. An independently authenticated export
manifest is required. All application writes go to six newly created stores.
The measured boundary starts after wire decoding, at canonical economic intake.
"""
import argparse
import base64
from collections import Counter
from contextlib import contextmanager, nullcontext
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch


SCHEMA = 'ec2-sealed-market-replay-parcel-v1'
RUNTIME_BASELINE = '533ec284549bb1ce1907808a17a077ee6b641a8c'
SOURCE = dict(request_id='ec2-39625860455-1',
    raw_manifest_sha256='7d42914089386ffbd09ab8604c5faf98b4563cec0c6635063a8ec0e8a452c137',
    application_commit='a02900db323f8527c829273b2b68ac68f4e94377',
    application_tree='b75324275f7e2e4342fe8138c6699e604f5d65fa',
    release_sha256='3b0245aba86912c6dda44b1b284084757fa6b70b5d7485e46aeb3576cf8dc36b',
    generation='cd828b7ab7f5d5a1b089d3e5c58d9caa',
    first_monotonic=173209.046747116, last_monotonic=173329.296718508,
    before=9, after=5090, measured=5081)
MAX_PARCEL = 512 * 1024**2
MAX_LINE = 32 * 1024**2
MAX_ROWS = 100000
BATCH = 64
CONTEXT_TABLES = frozenset(('evidence_bindings', 'native_order_attestations',
    'stream_order', 'stream_receipts', 'coverage', 'gaps', 'candidate_coverage',
    'candidate_gaps', 'rolling_origins', 'rolling_group_members',
    'candidate_history_outbox', 'candidate_pending_proofs', 'candidate_checkpoints',
    'candidates', 'events', 'canonical_event_refs', 'history_coverage', 'source_receipts'))
STAGES = frozenset(('creation_observed', 'postgraduation_unproven', 'native_observation_only',
    'creation_unavailable', 'native_five_second_fairness', 'native_below_curve_attention',
    'native_prospect_screened', 'decision_target_unavailable', 'native_optimistic_rejection',
    'native_full_qualification', 'native_evidence_incomplete'))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def need(value, reason):
    if not value:
        raise ValueError('original_window_' + reason)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def loads(raw):
    return json.loads(raw, object_pairs_hook=_pairs,
        parse_constant=lambda value: need(False, 'nonfinite_json'))


def fingerprint(path, maximum):
    """No atime comparison: reading a previously unread file may update atime."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_size <= maximum, 'input_file')
        digest = hashlib.sha256()
        while raw := os.read(fd, 1024**2):
            digest.update(raw)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mode', 'st_uid', 'st_gid',
                  'st_nlink', 'st_mtime_ns', 'st_ctime_ns')
        need(tuple(getattr(before, k) for k in fields) ==
             tuple(getattr(os.fstat(fd), k) for k in fields), 'input_changed')
        return before.st_size, digest.hexdigest()
    finally:
        os.close(fd)


class Parcel:
    """Index bounded lines, not entire decoded market context in memory."""
    def __init__(self, directory, expected_manifest_sha256):
        need(type(expected_manifest_sha256) is str and
             re.fullmatch('[0-9a-f]{64}', expected_manifest_sha256), 'manifest_pin')
        self.directory = Path(directory).absolute()
        need(self.directory.resolve(strict=True) == self.directory, 'parcel_path')
        self.manifest_path = self.directory / 'manifest.json'
        self.path = self.directory / 'market-inputs.jsonl'
        self.manifest_fingerprint = fingerprint(self.manifest_path, 2 * 1024**2)
        need(self.manifest_fingerprint[1] == expected_manifest_sha256, 'manifest_hash')
        fd = os.open(self.manifest_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as source:
            raw_manifest = source.read(2 * 1024**2 + 1)
        need(len(raw_manifest) <= 2 * 1024**2 and sha(raw_manifest) == expected_manifest_sha256, 'manifest_hash')
        manifest = self.manifest = loads(raw_manifest)
        need(manifest['schema'] == SCHEMA and manifest['source'] == SOURCE, 'source_lineage')
        for key in ('financial_authority', 'old_ack_authority_imported',
                    'exact_historical_visibility_proven', 'original_sqlite_layout_preserved',
                    'original_quote_oracle_concentration_inputs_available',
                    'full_strategy_decision_equivalence_proven'):
            need(manifest.get(key) is False, 'unsupported_authority_or_context')
        need(manifest['warmup_inputs'] == SOURCE['before'] and
             manifest['measured_inputs'] == SOURCE['measured'], 'cohort_size')
        self.fingerprint = fingerprint(self.path, MAX_PARCEL)
        need(self.fingerprint == (manifest['bytes'], manifest['parcel_sha256']), 'parcel_hash')
        self.inputs, self.native, self.context = [], {}, Counter()
        self.original_qualifications = {}; self.native_context_by_scope = Counter()
        rows = 0; read_digest = hashlib.sha256(); encodings = Counter()
        # Open through NOFOLLOW too, and bind each indexed line by hash. A
        # changed file cannot substitute an event after initial authentication.
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as source:
            while True:
                offset = source.tell()
                raw = source.readline(MAX_LINE + 1)
                if not raw:
                    break
                rows += 1
                read_digest.update(raw)
                need(rows <= MAX_ROWS and len(raw) <= MAX_LINE and raw.endswith(b'\n'), 'parcel_bound')
                row = loads(raw)
                kind = row.get('kind')
                if kind == 'input':
                    need(set(row) == {'kind', 'role', 'sequence', 'identity', 'scope', 'slot', 'first_seen'}, 'input_shape')
                    need(row['role'] in ('warmup', 'measured') and row['scope'] == 'program:pump'
                         and type(row['sequence']) is int and type(row['slot']) is int
                         and number(row['first_seen']) and row['first_seen'] > 0, 'input_shape')
                    self.inputs.append(row)
                elif kind == 'native_record':
                    value = row['value']; identity = value['identity']
                    need(type(identity) is str and identity not in self.native and
                         row['role'] in ('warmup', 'measured', 'context') and
                         value['historical_commit_visibility_proven'] is False, 'native_shape')
                    self.native[identity] = (offset, len(raw), sha(raw), row['role'])
                    encodings[value['storage_encoding']] += 1
                    if row['role'] == 'context':
                        scope = value['scope']
                        self.native_context_by_scope[scope if scope in
                            ('program:pump', 'program:pumpswap', 'program:meteora') else 'other_scope'] += 1
                elif kind == 'market_context':
                    need(row['table'] in CONTEXT_TABLES and
                         row['temporal_use'] == 'lineage_only_no_early_state_or_ack_import' and
                         row['historical_visibility_proven'] is False and
                         len(row['columns']) == len(row['row']), 'context_authority')
                    self.context[row['table']] += 1
                elif kind == 'context_table':
                    need(row['table'] in CONTEXT_TABLES and row['available'] is False, 'context_shape')
                elif kind == 'retained_market_facts':
                    need(row['source_health_normalized'] is False and
                         row['historical_health_timeline_available'] is False, 'health_authority')
                elif kind == 'original_qualification':
                    need(row['identity'] not in self.original_qualifications and
                         row['stage'] in STAGES and type(row['sequence']) is int and
                         type(row['slot']) is int and row['full_complete'] is False and
                         row['financial_authority'] is False and
                         row['source_identity'] == 'pump-source:'+row['identity'] and
                         type(row['body_sha256']) is str and re.fullmatch('[0-9a-f]{64}', row['body_sha256']) and
                         row['temporal_use'] == 'terminal_observation_only_no_fresh_state_import' and
                         row['original_decision_clock_available'] is False, 'original_observation_shape')
                    self.original_qualifications[row['identity']] = row
                else:
                    need(False, 'packet_kind')
        need(read_digest.hexdigest() == manifest['parcel_sha256'] and
             rows == manifest['rows'] and len(self.native) == manifest['native_records'] and
             dict(self.context) == manifest['context_rows'], 'parcel_counts')
        self.original_encodings = dict(encodings)
        self.inputs.sort(key=lambda row: row['sequence'])
        need(len(self.inputs) == SOURCE['after'] and
             len({row['identity'] for row in self.inputs}) == len(self.inputs) and
             len({row['sequence'] for row in self.inputs}) == len(self.inputs), 'cohort_population')
        first, last = manifest['endpoints']['first'], manifest['endpoints']['last']
        need(first['monotonic'] == SOURCE['first_monotonic'] and
             last['monotonic'] == SOURCE['last_monotonic'] and
             first['incoming_native_events'] == 9 and last['incoming_native_events'] == 5090 and
             first['durably_observed_native_events'] == 0 and last['durably_observed_native_events'] == 4062,
             'endpoint_values')
        self.warmup = [r for r in self.inputs if r['sequence'] <= first['latest_source_sequence']]
        self.measured = [r for r in self.inputs if r['sequence'] > first['latest_source_sequence']]
        need(len(self.warmup) == 9 and len(self.measured) == 5081 and
             self.warmup[-1]['sequence'] == first['latest_source_sequence'] and
             self.inputs[-1]['sequence'] == last['latest_source_sequence'], 'endpoint_membership')
        for row in self.inputs:
            need(row['identity'] in self.native and self.native[row['identity']][3] == row['role'] and
                 row['role'] == ('warmup' if row in self.warmup else 'measured'), 'native_membership')
        ordered = [[r[k] for k in ('sequence', 'identity', 'scope', 'slot', 'first_seen')]
                   for r in self.measured]
        need(sha(canonical(ordered)) == manifest['measured_identities_sha256'], 'cohort_digest')
        original = manifest['original_qualification']
        observations = sorted(self.original_qualifications.values(), key=lambda row: row['sequence'])
        stages = dict(Counter(row['stage'] for row in observations))
        need(original['available'] is True and manifest['original_selected_observation_membership_available'] is True and
             len(observations) == original['observations'] == last['durably_observed_native_events'] and
             len({row['sequence'] for row in observations}) == len(observations) and
             observations[-1]['sequence'] == original['cursor'] == last['durable_sequence'] and
             stages == original['stages'] == last['stages'], 'original_observation_boundary')
        known = {row['identity']: row for row in self.inputs}
        membership = Counter()
        for row in observations:
            item = known.get(row['identity'])
            if item is not None:
                need((row['sequence'], row['slot']) == (item['sequence'], item['slot']), 'original_observation_identity')
            membership['outside_window' if item is None else item['role']] += 1
        need(original['selected_observed'] == membership['measured'] and
             original['warmup_observed'] == membership['warmup'] and
             original['outside_window_observed'] == membership['outside_window'] and
             original['selected_unobserved'] == len(self.measured)-membership['measured'] and
             original['warmup_unobserved'] == len(self.warmup)-membership['warmup'] and
             original['body_rows_sha256'] == sha(canonical([
                [r['sequence'], r['identity'], r['body_sha256']] for r in observations])), 'original_observation_digest')
        self.unchanged()

    def unchanged(self):
        need(fingerprint(self.manifest_path, 2 * 1024**2) == self.manifest_fingerprint and
             fingerprint(self.path, MAX_PARCEL) == self.fingerprint, 'input_changed')

    def record(self, item):
        from meme_machine.solana_evidence_plane import FinalizedRecord, decode_body
        offset, length, expected, role = self.native[item['identity']]
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as source:
            source.seek(offset); raw = source.read(length)
        need(sha(raw) == expected, 'indexed_event_changed')
        value = loads(raw)['value']; body = value['canonical']
        encoding = value['storage_encoding']
        if encoding != 'cold_canonical':
            need(encoding in ('text', 'SEP1'), 'storage_encoding')
            stored = value['storage_body'] if encoding == 'text' else base64.b64decode(value['storage_body'], validate=True)
            chunks = {r['hash']: base64.b64decode(r['compressed_base64'], validate=True)
                      for r in value['hot_chunks']}
            need(decode_body(stored, chunks=chunks) == body, 'encoded_canonical_mismatch')
        else:
            need(value['storage_body'] is None and
                 re.fullmatch('[0-9a-f]{64}', value['cold_archive_sha256'] or ''), 'cold_lineage')
        need(sha(canonical(body)) == value['hash'], 'canonical_hash')
        for key in ('identity', 'scope', 'slot'):
            need(value[key] == body[key] == item[key], 'canonical_identity')
        need(value['first_seen'] == item['first_seen'] and body['kind'] == 'event' and
             body['scope'] == 'program:pump', 'canonical_availability')
        for key in ('signature', 'program', 'market_time', 'event_index', 'transaction_index', 'kind'):
            need(value[key] == body[key], 'canonical_metadata')
        lineage = value['source_lineage']
        need(bool(lineage) and all(r['source'] in ('alchemy_finalized_stream', 'alchemy_finalized_repair') and
             type(r['endpoint_sha256']) is str and re.fullmatch('[0-9a-f]{64}', r['endpoint_sha256']) and
             number(r['observed_at']) and r['observed_at'] > 0 for r in lineage), 'source_lineage_missing')
        witness = min(lineage, key=lambda r: (r['observed_at'], r['source'], r['endpoint_sha256']))
        record = FinalizedRecord(**dict(body, addresses=tuple(body['addresses']),
            source=witness['source'], endpoint_identity=witness['endpoint_sha256'],
            observed_at=value['first_seen']))
        need(record.body() == body, 'record_roundtrip')
        return record, value['hash'], encoding


class Costs:
    """Benchmark-local probes; counts statements separately from SQLite API time.

    Connection factories retain their existing class, including failure
    annotation. Install the trace before returning EVERY new connection, so
    source readers opened lazily have no uncounted first query. No SQL text,
    arguments, result values or database paths are retained in measurements.
    """
    def __init__(self):
        self.phase = 'setup'; self.rows = {}; self.stages = {}; self.connections = 0
        self.encoding = 'not_native_input'; self.primitives = {}
        self.publication_batches = []; self.classification_sql = {}

    def metric(self, role, bucket):
        return self.rows.setdefault((self.phase, role, bucket),
            dict(calls=0, wall_nanoseconds=0, cpu_nanoseconds=0, failures=0))

    def timed(self, role, bucket, function, *args, **kwargs):
        row = self.metric(role, bucket)
        wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
        try:
            return function(*args, **kwargs)
        except BaseException:
            row['failures'] += 1; raise
        finally:
            row['calls'] += 1
            row['wall_nanoseconds'] += time.perf_counter_ns() - wall
            row['cpu_nanoseconds'] += time.thread_time_ns() - cpu

    @contextmanager
    def stage(self, name):
        old, self.phase = self.phase, name
        try:
            yield
        finally:
            self.phase = old

    @contextmanager
    def primitives_probe(self):
        """Actual reached decode arguments; hash bytes include all SHA users.

        SHA costs are grouped by the last native decode's representation for
        this read turn, not asserted to be exclusively canonical authentication.
        Probe timings overlap stage totals and cannot be added to them.
        """
        from meme_machine import solana_evidence_plane as plane
        original_decode, original_sha = plane.decode_body, hashlib.sha256
        costs = self
        def add(kind, count, size):
            row = costs.primitives.setdefault((costs.phase, costs.encoding, kind),
                dict(calls=0, input_bytes=0))
            row['calls'] += count; row['input_bytes'] += size
        def decode(raw, *args, **kwargs):
            costs.encoding = 'text' if type(raw) is str else 'SEP1' if type(raw) is bytes and raw.startswith(b'SEP1') else 'other'
            add('decode_body', 1, len(raw.encode()) if type(raw) is str else len(raw))
            return original_decode(raw, *args, **kwargs)
        class Hash:
            def __init__(self, data=b'', **kwargs):
                add('sha256_constructor', 1, len(data))
                self.inner = original_sha(data, **kwargs)
            def update(self, data):
                add('sha256_update', 1, len(data)); return self.inner.update(data)
            def copy(self):
                copied = object.__new__(Hash); copied.inner = self.inner.copy()
                return copied
            def __getattr__(self, name):
                return getattr(self.inner, name)
        with patch.object(plane, 'decode_body', decode), patch.object(hashlib, 'sha256', Hash):
            yield

    @contextmanager
    def sqlite(self, root):
        original = sqlite3.connect; costs = self
        def connect(database, *args, **kwargs):
            # Preserve each requested failure-attribution factory. Positional
            # factory ambiguity is refused, never silently replaced.
            need(len(args) < 5, 'positional_sqlite_factory')
            base = kwargs.pop('factory', sqlite3.Connection)
            filename = str(database).split('?', 1)[0].removeprefix('file:')
            path = Path(filename).resolve()
            need(path.is_relative_to(root), 'sqlite_outside_fresh_store')
            fallback = ('qualification' if path.name == 'qualification.sqlite' else
                        'history_read' if path.name == 'history.sqlite' and kwargs.get('uri') else
                        'history' if path.name == 'history.sqlite' else
                        'canonical_read' if kwargs.get('uri') else 'canonical')
            def role(db):
                return getattr(db, '_failure_metadata', {}).get('role', fallback)
            # Failure-aware connections supply their own Cursor; preserving
            # that base retains original error codes and ownership metadata.
            from meme_machine.runtime.sqlite_failure import Connection, Cursor
            cursor_base = Cursor if issubclass(base, Connection) else sqlite3.Cursor
            class MeasuredCursor(cursor_base):
                def execute(self, sql, parameters=(), /):
                    return costs.timed(role(self.connection), 'statement_api', super().execute, sql, parameters)
                def executemany(self, sql, parameters, /):
                    return costs.timed(role(self.connection), 'statement_many_api', super().executemany, sql, parameters)
                def executescript(self, sql, /):
                    return costs.timed(role(self.connection), 'script_api', super().executescript, sql)
                def fetchone(self):
                    return costs.timed(role(self.connection), 'fetch_api', super().fetchone)
                def fetchall(self):
                    return costs.timed(role(self.connection), 'fetch_api', super().fetchall)
                def fetchmany(self, size=None):
                    return costs.timed(role(self.connection), 'fetch_api', super().fetchmany, *(() if size is None else (size,)))
                def __next__(self):
                    # Exhaustion is a normal iterator result, not a SQL error.
                    wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
                    try:
                        return super().__next__()
                    finally:
                        row = costs.metric(role(self.connection), 'iterate_api')
                        row['calls'] += 1; row['wall_nanoseconds'] += time.perf_counter_ns()-wall
                        row['cpu_nanoseconds'] += time.thread_time_ns()-cpu
            class MeasuredConnection(base):
                def cursor(self, factory=None):
                    need(factory is None, 'custom_cursor_unmeasured')
                    # Preserve the original factory's cursor-open/error path;
                    # our subclass also retains that factory's Cursor base.
                    return super().cursor(factory=MeasuredCursor)
                def execute(self, sql, parameters=(), /):
                    if issubclass(base, Connection):
                        return super().execute(sql, parameters)
                    return self.cursor().execute(sql, parameters)
                def executemany(self, sql, parameters, /):
                    return self.cursor().executemany(sql, parameters)
                def executescript(self, sql, /):
                    return self.cursor().executescript(sql)
                def commit(self):
                    return costs.timed(role(self), 'transaction_api', super().commit)
                def rollback(self):
                    return costs.timed(role(self), 'transaction_api', super().rollback)
                def __exit__(self, *args):
                    return costs.timed(role(self), 'transaction_context_api', super().__exit__, *args)
            db = original(database, *args, factory=MeasuredConnection, **kwargs)
            costs.connections += 1
            def trace(sql):
                words = sql.lstrip().split(None, 1)
                verb = words[0].upper() if words else 'OTHER'
                if verb not in ('SELECT', 'WITH', 'INSERT', 'UPDATE', 'DELETE', 'BEGIN', 'COMMIT',
                                'ROLLBACK', 'SAVEPOINT', 'RELEASE', 'PRAGMA', 'CREATE', 'DROP', 'ALTER'):
                    verb = 'OTHER'
                costs.metric(role(db), 'trace_' + verb)['calls'] += 1
            db.set_trace_callback(trace)
            return db
        with patch.object(sqlite3, 'connect', connect):
            yield

    def sql_snapshot(self):
        # Copy process-local counters only; never issue an attribution query.
        return {key: dict(row) for key, row in self.rows.items()
                if key[2].startswith('trace_') or key[2].endswith('_api')}

    def attribute_classification(self, stage, before):
        need(stage in STAGES, 'profile_classification_stage')
        for (phase, role, bucket), row in self.sql_snapshot().items():
            previous = before.get((phase, role, bucket), {})
            delta = {key: value-previous.get(key, 0) for key, value in row.items()}
            need(all(value >= 0 for value in delta.values()), 'profile_sql_counter_reset')
            if not any(delta.values()):
                continue
            target = self.classification_sql.setdefault((stage, phase, role, bucket),
                dict(calls=0, wall_nanoseconds=0, cpu_nanoseconds=0, failures=0))
            for key, value in delta.items():
                target[key] += value

    @contextmanager
    def publication_probe(self):
        # Observe the returned real batch; no second lookup or old publisher.
        from meme_machine import solana_history_delivery as delivery
        original = delivery.capture
        def capture(*args, **kwargs):
            snapshot = original(*args, **kwargs)
            if snapshot is not None:
                rows = snapshot['rows']
                self.publication_batches.append(dict(phase=self.phase,
                    N_outbox_rows=len(rows),
                    U_distinct_binding_keys=len({(row[1], row[2]) for row in rows}),
                    E_empty_second_phase=int(not snapshot['proofs'] and not snapshot['refresh']),
                    proof_rows=len(snapshot['proofs']), refresh_rows=len(snapshot['refresh'])))
            return snapshot
        with patch.object(delivery, 'capture', capture):
            yield

    def classification_report(self):
        return [dict(stage=stage, phase=phase, role=role, bucket=bucket, **row)
                for (stage, phase, role, bucket), row in sorted(self.classification_sql.items())]

    def report(self):
        return [dict(phase=phase, role=role, bucket=bucket, **value)
                for (phase, role, bucket), value in sorted(self.rows.items())]

    def primitive_report(self):
        return [dict(phase=phase, native_input_encoding=encoding, primitive=kind, **row)
                for (phase, encoding, kind), row in sorted(self.primitives.items())]


@contextmanager
def no_network():
    def refused(*args, **kwargs):
        raise ValueError('original_window_network_refused')
    with patch.object(socket.socket, 'connect', refused), patch.object(socket.socket, 'connect_ex', refused), \
         patch.object(socket, 'create_connection', refused):
        yield


def publish(life, *, interrupt_before_ack=False):
    from meme_machine.solana_history_delivery import capture, deliver, acknowledge
    batches = rows = 0
    while snapshot := capture(life):
        result = deliver(snapshot)
        if interrupt_before_ack:
            # deliver closed its external writer after the durable commit.
            # Drop the result, recapture the still-pending original outbox,
            # then use the actual idempotent consumer and owner ACK again.
            repeated = capture(life)
            need(repeated['rows'] == snapshot['rows'], 'recovery_outbox_changed')
            result = deliver(repeated); snapshot = repeated
            interrupt_before_ack = False
        need(acknowledge(life, snapshot, result), 'publication_ack_refused')
        batches += 1; rows += len(snapshot['rows'])
    return dict(batches=batches, outbox_rows=rows)


def _semantic(reader, expected):
    digest = hashlib.sha256(); by_role = Counter(); stages = Counter()
    cohort_stages = {'warmup': Counter(), 'measured': Counter()}
    rows = reader.db.execute('SELECT sequence,identity,body,hash,stage FROM observations ORDER BY sequence').fetchall()
    need(len(rows) == len(expected), 'observation_population')
    mapping = []
    for sequence, identity, body, checksum, stage in rows:
        item = expected[identity]
        need(sha(body.encode()) == checksum, 'observation_hash')
        digest.update(canonical([item['sequence'], identity, body, stage])+b'\n')
        mapping.append([item['sequence'], identity, sequence])
        by_role[item['role']] += 1; stages[stage] += 1
        cohort_stages[item['role']][stage] += 1
    state = list(reader.db.execute('SELECT mint,last_evaluated FROM candidate_state ORDER BY mint'))
    digest.update(canonical(state))
    return dict(semantic_sha256=digest.hexdigest(), mapping_sha256=sha(canonical(mapping)),
        original_to_fresh_sequence=mapping, completed=dict(by_role), stages=dict(stages),
        stages_by_cohort={key: dict(value) for key, value in cohort_stages.items()},
        durable_sequence=rows[-1][0] if rows else None)


def original_comparison(reader, parcel):
    originals = getattr(parcel, 'original_qualifications', {})
    if not originals:
        return dict(available=False, original_decision_clock_replayed=False)
    transitions = Counter(); equal_bodies = 0; missing = 0; by_cohort = Counter()
    fresh = {identity: (checksum, stage) for identity, checksum, stage in
             reader.db.execute('SELECT identity,hash,stage FROM observations')}
    cohort = {r['identity']: r['role'] for r in parcel.inputs}
    for identity, original in originals.items():
        by_cohort[cohort.get(identity, 'outside_window')] += 1
        new = fresh.get(identity)
        if new is None:
            missing += 1
        else:
            transitions[original['stage']+'->'+new[1]] += 1
            equal_bodies += new[0] == original['body_sha256']
    return dict(available=True, original_observations=len(originals), original_membership=dict(by_cohort),
        original_body_hash_matches=equal_bodies, original_ids_without_fresh_observation=missing,
        stage_transitions=dict(transitions), original_decision_clock_replayed=False,
        scope='exact_original_ID_and_classification_comparison_not_original_context_or_clock_equivalence')


def run_one(parcel, directory, implementation, *, profile=False):
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_evidence_service import FinalizedFence
    from meme_machine.solana_selective_history import SelectiveHistory
    from meme_machine.solana_selective_source import STATE_SCHEMA
    from meme_machine.solana_candidate_lifecycle import CandidateLifecycle
    from meme_machine.solana_rolling_history import RollingHistory
    from meme_machine.solana_prewarm_startup import SCHEMA as STARTUP_SCHEMA
    from meme_machine.operational.managed_native_pump import install_nonfinancial_history
    from meme_machine.operational.managed_pump_qualification import QualificationReader
    from meme_machine.operational.managed_qualification_replay import ReferenceReader, NoNetworkProvider
    directory.mkdir(mode=0o700)
    warmup_count, measured_count, total_count = len(parcel.warmup), len(parcel.measured), len(parcel.inputs)
    clock = SimpleNamespace(value=parcel.inputs[0]['first_seen'])
    costs = Costs(); timings = {}; fresh_encodings = Counter(); original_encodings = Counter()
    progress = []
    def operation(name, function, *args, **kwargs):
        with costs.stage(name):
            return costs.timed('stage_total', name, function, *args, **kwargs)
    config = SimpleNamespace(root=directory, evidence=directory/'canonical.sqlite',
        history=directory/'history.sqlite', generation='original-window-logical-replay-v1',
        # Identity of the unchanged frozen application runtime being compared,
        # distinct from the consumer tool's own source hash in the report.
        source_revision=RUNTIME_BASELINE)
    base = ReferenceReader if implementation == 'reference' else QualificationReader
    class ProfiledReader(base):
        def _evaluate(self, *args):
            before = time.perf_counter_ns(), time.thread_time_ns()
            sql_before = costs.sql_snapshot()
            value = super()._evaluate(*args)
            costs.attribute_classification(value[0]['stage'], sql_before)
            row = costs.stages.setdefault(value[0]['stage'], dict(events=0, wall_nanoseconds=0, cpu_nanoseconds=0))
            row['events'] += 1; row['wall_nanoseconds'] += time.perf_counter_ns()-before[0]
            row['cpu_nanoseconds'] += time.thread_time_ns()-before[1]
            return value
    Reader = ProfiledReader if profile else base
    reader = writer = None; acknowledgements = []; commands = []
    def prepare(reader):
        need(reader._open(), 'reader_open')
        reader.plane.acknowledge = lambda *args: acknowledgements.append(args)
        def refused(**request):
            from meme_machine.solana_evidence_plane import EvidenceUnavailable
            commands.append(request)
            raise EvidenceUnavailable('original_window_ipc_refused')
        reader.plane.command = refused
    def consume():
        while True:
            snapshot = reader.step()
            if not snapshot.get('processed_this_turn'):
                return snapshot
    def admit(items):
        from meme_machine.solana_economic_preparation import prepare_economic_record
        # benchmark() authenticated and decoded this immutable input population
        # before either timing/cost pass. Replay begins at normalized admission.
        records = [parcel.record(item) for item in items]
        clock.value = max(clock.value, max(r.observed_at for r, _, _ in records))
        prepared = operation('economic_preparation', lambda: [prepare_economic_record(r) for r, _, _ in records])
        operation('economic_ingest', history.ingest, prepared)
    with no_network(), costs.sqlite(directory) if profile else nullcontext(), \
         costs.primitives_probe() if profile else nullcontext(), \
         costs.publication_probe() if profile else nullcontext():
        try:
            writer = EvidenceWriter(config.evidence, clock=lambda: clock.value)
            endpoint = parcel.record(parcel.inputs[0])[0].endpoint_identity
            fence = FinalizedFence(writer, endpoint_identity=endpoint)
            history = SelectiveHistory(writer, fence.endpoint_identity, clock=lambda: clock.value)
            history.db.executescript(STATE_SCHEMA); history.db.executescript(STARTUP_SCHEMA)
            history.lifecycle = life = CandidateLifecycle(history, candidate_path=config.history)
            history.rolling = RollingHistory(history); life.delivery_separated = True
            fence.health('topology', 'candidate_hybrid_v1')
            install_nonfinancial_history(config)
            operation('prelude_admission', admit, parcel.warmup)
            provider = NoNetworkProvider()
            reader = Reader(config, clock=lambda: clock.value, provider=provider, decision_target=None)
            prepare(reader)
            initial = reader.snapshot()
            need(initial['incoming_native_events'] == warmup_count and initial['durably_observed_native_events'] == 0 and
                 initial['native_event_backlog'] == warmup_count, 'initial_state')
            wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
            for start in range(0, len(parcel.measured), BATCH):
                operation('canonical_admission', admit, parcel.measured[start:start+BATCH])
                operation('publication', publish, life)
                snapshot = operation('qualification', consume)
                progress.append(dict(selected_admitted=min(start+BATCH, measured_count),
                    incoming=snapshot['incoming_native_events'],
                    observed=snapshot['durably_observed_native_events'],
                    backlog=snapshot['native_event_backlog'], elapsed_nanoseconds=time.perf_counter_ns()-wall))
            timings.update(wall_nanoseconds=time.perf_counter_ns()-wall,
                           cpu_nanoseconds=time.thread_time_ns()-cpu)
            timings.update(selected_events_per_second=measured_count/(timings['wall_nanoseconds']/1e9),
                           total_events_per_second=total_count/(timings['wall_nanoseconds']/1e9),
                           scope='selected_normalized_admission_plus_total_publication_observation',
                           profiled=profile, usable_for_timing_comparison=not profile)
            expected = {r['identity']: r for r in parcel.inputs}
            with costs.stage('validation'):
                native = {identity: (checksum, seen, encoding) for identity, checksum, seen, encoding
                          in history.db.execute('SELECT identity,hash,first_seen,typeof(body) FROM canonical_evidence')}
                for item in parcel.inputs:
                    record, checksum, encoding = parcel.record(item)
                    value = native[item['identity']]
                    need(value[:2] == (checksum, record.observed_at), 'ingest_changed_economics')
                    original_encodings[encoding] += 1
                    fresh_encodings['text' if value[2] == 'text' else 'SEP1' if value[2] == 'blob' else 'cold_canonical'] += 1
                semantic = _semantic(reader, expected)
                need(snapshot['native_event_backlog'] == 0 and semantic['completed'] == {'warmup': warmup_count, 'measured': measured_count}, 'incomplete_window')
                history_events = []
                for lane, candidate, identity in reader.history.db.execute(
                        'SELECT lane,candidate,identity FROM canonical_event_refs ORDER BY lane,candidate,identity'):
                    history_events.append(reader.history.event(lane, candidate, identity))
                history_hash = sha(canonical(history_events))
                history_state = {table: sha(canonical(list(reader.history.db.execute(
                    'SELECT * FROM '+table+' ORDER BY '+order)))) for table, order in
                    (('candidates', 'lane,candidate'), ('source_receipts', 'id'))}
                original = original_comparison(reader, parcel)
                for table in ('funding', 'decisions'):
                    need(reader.history.db.execute('SELECT count(*) FROM '+table).fetchone() == (0,), 'financial_state')
            original_snapshot = reader.snapshot(); reader.close(); reader = None
            with costs.stage('restart'):
                resumed = Reader(config, clock=lambda: clock.value, provider=NoNetworkProvider(), decision_target=None)
                reader = resumed; prepare(reader)
                restarted = reader.step()
                need(restarted.get('processed_this_turn') == 0 and
                     {k: v for k, v in restarted.items() if k != 'processed_this_turn'} == original_snapshot and
                     _semantic(reader, expected) == semantic, 'restart_parity')
            return dict(implementation=implementation, timing=timings, initial=initial,
                final=original_snapshot, **semantic, history_semantic_sha256=history_hash,
                history_state_sha256=history_state, original_comparison=original,
                ack_intents_sha256=sha(canonical(acknowledgements)),
                command_intents_sha256=sha(canonical(commands)), reader_restart_verified=True,
                stage_costs=costs.stages, sql=costs.report(),
                publication_batches=costs.publication_batches,
                publication_population_totals={key: sum(row[key] for row in costs.publication_batches)
                    for key in ('N_outbox_rows', 'U_distinct_binding_keys', 'E_empty_second_phase', 'proof_rows', 'refresh_rows')},
                classification_sql=costs.classification_report(),
                classification_sql_scope='inside_evaluate_only_excludes_outer_event_auth_current_event_lookup_observation_cursor_writes',
                publication_population_scope='N_rows_U_distinct_family_address_E_empty_proofs_refresh_per_real_capture_profile_only',
                controlled_batch_progress=progress,
                controlled_backlog_scope='serial_batch_schedule_bounds_queue_by_construction_not_live_arrival_capacity',
                primitive_costs=costs.primitive_report(),
                original_input_storage_encodings=dict(original_encodings),
                fresh_input_storage_encodings=dict(fresh_encodings),
                sqlite_connections=costs.connections, first_lazy_source_queries_traced=profile,
                provider_requests=0, missing_provider_inputs=provider.missing,
                decision_target='unavailable_no_original_oracle_retained',
                full_strategy_equivalence_proven=False, financial_authority=False)
        finally:
            if reader is not None:
                reader.close()
            if writer is not None:
                writer.close()


def benchmark(parcel, directory):
    directory = Path(directory).absolute()
    need(directory.parent.resolve(strict=True) == directory.parent and not directory.exists(), 'new_output_required')
    directory.mkdir(mode=0o700)
    original_umask = os.umask(0o077)
    try:
        wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
        digest = hashlib.sha256()
        selected_wall = selected_cpu = None
        for index, row in enumerate(parcel.inputs):
            if index == len(parcel.warmup):
                selected_wall, selected_cpu = time.perf_counter_ns(), time.thread_time_ns()
            record, checksum, _ = parcel.record(row)
            digest.update(canonical([row['sequence'], record.identity, checksum])+b'\n')
        lightweight = dict(events=len(parcel.inputs), measured_events=len(parcel.measured),
            identity_content_sha256=digest.hexdigest(), wall_nanoseconds=time.perf_counter_ns()-wall,
            cpu_nanoseconds=time.thread_time_ns()-cpu,
            selected_wall_nanoseconds=time.perf_counter_ns()-selected_wall,
            selected_cpu_nanoseconds=time.thread_time_ns()-selected_cpu,
            scope='authentication_count_floor_only_no_strategy_equivalence')
        # Share immutable normalized inputs, never mutated original DB rows.
        # No decoder/provider work is hidden inside the timed admission region.
        # A body/hash postcheck below detects mutation of the replay inputs.
        records = {row['identity']: parcel.record(row) for row in parcel.inputs}
        class FrozenParcel:
            def __getattr__(self, key):
                return getattr(parcel, key)
            def record(self, row):
                return records[row['identity']]
        frozen = FrozenParcel()
        profiled = [run_one(frozen, directory/('profile-'+implementation), implementation, profile=True)
                    for implementation in ('reference', 'optimized')]
        results = []
        for index, implementation in enumerate(('reference', 'optimized', 'optimized', 'reference')):
            results.append(run_one(frozen, directory/(str(index)+'-'+implementation), implementation))
        compared = ('semantic_sha256', 'mapping_sha256', 'completed', 'stages', 'stages_by_cohort',
                    'durable_sequence', 'history_semantic_sha256', 'history_state_sha256',
                    'original_comparison', 'ack_intents_sha256', 'command_intents_sha256')
        coherent = all(all(row[key] == results[0][key] for key in compared) for row in profiled+results)
        need(coherent, 'abba_semantic_mismatch')
        for record, checksum, _ in records.values():
            need(sha(canonical(record.body())) == checksum, 'normalized_input_mutated')
        parcel.unchanged()
        return dict(schema='original-pump-window-logical-compute-v1',
            source=parcel.manifest['source'], source_manifest_sha256=parcel.manifest_fingerprint[1],
            runtime_baseline_commit=RUNTIME_BASELINE, consumer_source_sha256=sha(Path(__file__).read_bytes()),
            input_parcel_sha256=parcel.fingerprint[1], original_endpoints=parcel.manifest['endpoints'],
            original_selected_observation_membership_available=bool(getattr(parcel, 'original_qualifications', {})),
            input_events=len(parcel.inputs), selected_events=len(parcel.measured), initial_pending=len(parcel.warmup), initial_observed=0,
            coherent=coherent, lightweight=lightweight, runs=results, profiled_runs=profiled,
            context_rows_preserved_as_lineage=dict(parcel.context), context_rows_imported_as_state=0,
            original_all_native_storage_encodings=parcel.original_encodings,
            native_context_preserved_not_admitted_by_scope=dict(getattr(parcel, 'native_context_by_scope', {})),
            selected_event_dropping=False, other_family_workload_replayed=False,
            schedule='source_sequence_prefix_batches64_clock_nondecreasing_max_first_seen',
            timing_order='ABBA_fresh_stores_two_pairs_same_host_cache_neutrality_not_guaranteed',
            measurement_boundary='normalized_canonical_economic_admission_publication_qualification',
            original_sqlite_layout_preserved=False, original_network_timing_replayed=False,
            original_decision_clock_replayed=False, original_visibility_timing_replayed=False,
            original_stage_comparison_scope='cursor_bound_original4062_exact_ID_membership_and_classification_vs_fresh5090',
            full_strategy_equivalence_proven=False, throughput_readiness_proven=False,
            financial_readiness_proven=False, financial_authority=False,
            unavailable_inputs=['historical_health_timeline', 'proof_commit_visibility',
                'quote_oracle_concentration', 'final_context_original_commit_visibility'],
            sql_timing_scope='API_and_fetch_wall_CPU_with_probe_overhead_not_statement_trace_duration',
            timed_pass_instrumentation='batch_stage_timers_only_no_SQL_or_primitive_or_per_event_probes',
            profile_order='independent_reference_optimized_cost_pair_before_timed_ABBA',
            native_acquisition_join_repair_exercised=False,
            profiled_observation_population='all5090_includes9_prelude_selected_timing_denominator5081',
            profile_stage_timing_scope='includes_counter_copy_and_population_probes_do_not_compare_to_old_profile_wall',
            original_inputs_unchanged=True)
    finally:
        os.umask(original_umask)



SEMANTIC_FIELDS = ('semantic_sha256', 'mapping_sha256', 'original_to_fresh_sequence',
    'completed', 'stages', 'stages_by_cohort', 'durable_sequence',
    'history_semantic_sha256', 'history_state_sha256', 'original_comparison',
    'ack_intents_sha256', 'command_intents_sha256', 'reader_restart_verified',
    'initial', 'final', 'decision_target', 'missing_provider_inputs',
    'provider_requests', 'financial_authority', 'full_strategy_equivalence_proven',
    'original_input_storage_encodings', 'fresh_input_storage_encodings')
COHORT_FIELDS = ('source', 'source_manifest_sha256', 'input_parcel_sha256', 'original_endpoints',
    'input_events', 'selected_events', 'initial_pending', 'initial_observed', 'schedule',
    'measurement_boundary', 'selected_event_dropping', 'other_family_workload_replayed',
    'context_rows_imported_as_state', 'context_rows_preserved_as_lineage',
    'original_all_native_storage_encodings', 'native_context_preserved_not_admitted_by_scope',
    'original_selected_observation_membership_available', 'original_decision_clock_replayed',
    'original_visibility_timing_replayed', 'original_network_timing_replayed',
    'original_sqlite_layout_preserved', 'unavailable_inputs')


def compare_reports(previous, candidate):
    """Compare authenticated report data only; no app/database/provider imports."""
    for report in (previous, candidate):
        need(report.get('schema') == 'original-pump-window-logical-compute-v1' and
             report.get('coherent') is True and report.get('original_inputs_unchanged') is True and
             report.get('financial_authority') is False and
             report.get('full_strategy_equivalence_proven') is False and
             report.get('throughput_readiness_proven') is False, 'comparison_report_boundary')
    need(all(key in previous and key in candidate and previous[key] == candidate[key]
             for key in COHORT_FIELDS), 'comparison_input_or_scope_mismatch')
    comparisons = []; equivalent = True
    for collection, implementations in (('profiled_runs', ('reference', 'optimized')),
            ('runs', ('reference', 'optimized', 'optimized', 'reference'))):
        old, new = previous.get(collection), candidate.get(collection)
        need(type(old) is list and type(new) is list and len(old) == len(new) == len(implementations),
             'comparison_arm_population')
        for index, (left, right, implementation) in enumerate(zip(old, new, implementations)):
            need(left.get('implementation') == right.get('implementation') == implementation and
                 left.get('reader_restart_verified') is True and right.get('reader_restart_verified') is True,
                 'comparison_arm_identity')
            different = [key for key in SEMANTIC_FIELDS if key not in left or key not in right or left[key] != right[key]]
            progress = lambda row: [{key: item[key] for key in
                ('selected_admitted', 'incoming', 'observed', 'backlog')}
                for item in row['controlled_batch_progress']]
            if progress(left) != progress(right):
                different.append('controlled_batch_progress_counts')
            equivalent = equivalent and not different
            comparisons.append(dict(collection=collection, index=index, implementation=implementation,
                same_semantics=not different, differing_fields=different))
    timing = {}
    if equivalent:
        for implementation in ('reference', 'optimized'):
            old = [row for row in previous['runs'] if row['implementation'] == implementation]
            new = [row for row in candidate['runs'] if row['implementation'] == implementation]
            need(all(row['timing'].get('profiled') is False and
                     row['timing'].get('usable_for_timing_comparison') is True for row in old+new),
                 'comparison_unprofiled_timing_required')
            measured = {}
            for metric in ('wall_nanoseconds', 'cpu_nanoseconds'):
                before = [row['timing'][metric] for row in old]
                after = [row['timing'][metric] for row in new]
                need(all(type(value) is int and value > 0 for value in before+after), 'comparison_timing_shape')
                left, right = sum(before)/len(before), sum(after)/len(after)
                measured[metric] = dict(previous=before, candidate=after, previous_mean=left,
                    candidate_mean=right, reduction_percent=100*(left-right)/left)
            timing[implementation] = measured
    original = previous['runs'][0]['original_comparison']
    return dict(schema='original-pump-window-report-comparison-v1', same_authenticated_inputs=True,
        same_semantics=equivalent, arms=comparisons, timing_comparison_available=equivalent,
        unprofiled_timing=timing, previous_runtime=previous.get('runtime_baseline_commit'),
        candidate_runtime=candidate.get('runtime_baseline_commit'),
        previous_consumer_sha256=previous.get('consumer_source_sha256'),
        candidate_consumer_sha256=candidate.get('consumer_source_sha256'),
        original_observations=original.get('original_observations'),
        original_body_hash_matches=original.get('original_body_hash_matches'),
        original_observation_body_differences=(original['original_observations']-original['original_body_hash_matches']
            if type(original.get('original_observations')) is int and
               type(original.get('original_body_hash_matches')) is int else None),
        original_clock_or_missing_quote_differences_resolved=False,
        original_decision_clock_replayed=False, native_acquisition_join_repair_exercised=False,
        profile_stage_wall_times_directly_comparable=False,
        timing_limits='different_runs_host_activity_and_cache_order_not_controlled_ABBA_only_within_each_report',
        qualification_sql_scope='inside_evaluate_excludes_outer_event_auth_current_lookup_observation_cursor_writes',
        full_strategy_equivalence_proven=False, throughput_readiness_proven=False, financial_authority=False)


def compare_main(arguments):
    parser = argparse.ArgumentParser(description='Compare SHA-pinned replay reports using stdlib only.')
    parser.add_argument('previous', type=Path); parser.add_argument('candidate', type=Path)
    parser.add_argument('--previous-sha256', required=True); parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--new-output', required=True, type=Path)
    args = parser.parse_args(arguments); reports = []
    for path, expected in ((args.previous, args.previous_sha256), (args.candidate, args.candidate_sha256)):
        need(type(expected) is str and re.fullmatch('[0-9a-f]{64}', expected), 'comparison_report_pin')
        before = fingerprint(path, 32*1024**2)
        need(before[1] == expected, 'comparison_report_hash')
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, 'rb') as source:
            raw = source.read(32*1024**2+1)
        need(len(raw) <= 32*1024**2 and sha(raw) == expected and fingerprint(path, 32*1024**2) == before,
             'comparison_report_changed')
        reports.append(loads(raw))
    result = compare_reports(*reports)
    result.update(previous_report_sha256=args.previous_sha256, candidate_report_sha256=args.candidate_sha256)
    output = args.new_output.absolute()
    need(output.parent.resolve(strict=True) == output.parent, 'comparison_output_parent')
    _report(output, canonical(result)+b'\n')
    print(json.dumps(dict(schema=result['schema'], same_semantics=result['same_semantics'],
        comparison_sha256=sha(canonical(result)+b'\n'), financial_authority=False), sort_keys=True))
    return result

def main():
    if sys.argv[1:2] == ['compare-reports']:
        result = compare_main(sys.argv[2:])
        raise SystemExit(0 if result['same_semantics'] else 2)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parcel', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--new-output-directory', required=True, type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    need(os.geteuid() != 0, 'unprivileged_consumer_required')
    if not args.worker:
        # Use the existing engineering admission/watchdog lifecycle; the
        # supervisor's accounting does not insert SQL/probes into timed work.
        from meme_machine.operational.artifact_storage import Scratch
        output = args.new_output_directory.absolute()
        need(output.parent.resolve(strict=True) == output.parent and not output.exists(), 'new_output_required')
        with Scratch() as scratch:
            target = scratch.path/'compute'
            command = [sys.executable, '-m', 'engineering.diagnostics.replay_original_pump_window',
                '--worker', '--parcel', str(args.parcel.absolute()),
                '--manifest-sha256', args.manifest_sha256, '--new-output-directory', str(target)]
            child = subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL)
            try:
                while child.poll() is None:
                    scratch.check(); time.sleep(.25)
                scratch.check()
                need(child.returncode == 0, 'worker_failed_retained_scratch')
                descriptor = os.open(target/'report.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                with os.fdopen(descriptor, 'rb') as source:
                    raw = source.read(32*1024**2+1)
                need(len(raw) <= 32*1024**2, 'report_bound')
                result = loads(raw)
                need(result['coherent'] is True and result['source_manifest_sha256'] == args.manifest_sha256,
                     'worker_report_binding')
                output.mkdir(mode=0o700)
                _report(output/'report.json', raw)
                scratch.success = True
                print(json.dumps(dict(schema=result['schema'], coherent=True,
                    selected_events=result['selected_events'], report_sha256=sha(raw),
                    full_strategy_equivalence_proven=False), sort_keys=True))
                return
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=5)
    parcel = Parcel(args.parcel, args.manifest_sha256)
    result = benchmark(parcel, args.new_output_directory)
    raw = canonical(result)+b'\n'
    _report(args.new_output_directory/'report.json', raw)


def _report(path, raw):
    fd = os.open(path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())


if __name__ == '__main__':
    main()
