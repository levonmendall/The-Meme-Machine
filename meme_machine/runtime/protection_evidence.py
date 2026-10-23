"""Offline protection-proof core; not a producer, readiness gate or host attestation.

The supplied connection belongs to an existing native owner. This module adds
only its own append-only table/triggers, never edits financial/native rows and
never completes, commits or rolls back a caller's transaction. Proof errors are
data: callers must close proof acceptance/new-risk admission while continuing
the original native monitor and exits. No production caller is wired here.

All times are integer nanoseconds. Monotonic clocks are comparable only within
one boot/process-start/generation. USD cache hits retain their original source
acquisition and expiry; they do not create fresh acquisitions. Hash integrity
does not authenticate a host: protected extraction must bind the window heads,
financial cursors, source and boot before an operational acceptance claim.

Retention is deliberately a hard capacity stop, never an eviction/prune flag.
Unverified/failed records remain intact. External authenticated archival and
verified compaction are not implemented and must precede sustained use beyond
these bounds. Installation is additive; the old executable can ignore this table.

Integration limits: construction can raise on schema/storage/admission errors;
future producer factories must contain that failure outside native protection.
Payload bounds do not reserve financial page/WAL/disk headroom. In particular,
Pons Current's existing 64 MiB native cap is shared with this additive table.
Financial headroom, authenticated archival, pending-exit execution evidence and
protected-host/source extraction are unimplemented prerequisites to wiring.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import threading
import time
from typing import Protocol


ZERO = '0' * 64
TABLE = 'protection_evidence_v1'
NS = 1_000_000_000
CADENCE = {'pump_current': 5*NS, 'pump_survivor': 5*NS,
           'pons_current': 5*NS, 'pons_survivor': 3*NS}
# These are held-risk acquisition profiles, never simulated-fill promises.
# The evidence resolver must bind the selected branch to real acquisition
# evidence. A producer cannot supply an expanded numeric limit.
PROFILES = {
    'pump_current_monitor': ('pump_current', 5*NS, False),
    'pump_survivor_monitor': ('pump_survivor', 5*NS, False),
    'pons_current_private_monitor': ('pons_current', 5*NS, False),
    'pons_current_shared_monitor': ('pons_current', 5*NS, True),
    'pons_survivor_private_monitor': ('pons_survivor', 5*NS, False),
    'pons_survivor_shared_monitor': ('pons_survivor', 3*NS, False),
}
KINDS = {'OWNER', 'OPEN', 'TURN', 'CLOSE', 'END'}
CREATE = f'''CREATE TABLE {TABLE}(
    sequence INTEGER PRIMARY KEY CHECK(sequence BETWEEN 1 AND 32768),
    receipt_id TEXT NOT NULL UNIQUE CHECK(length(CAST(receipt_id AS BLOB))<=256),
    body TEXT NOT NULL CHECK(length(CAST(body AS BLOB))<=16384),
    previous TEXT NOT NULL CHECK(length(previous)=64),
    hash TEXT NOT NULL UNIQUE CHECK(length(hash)=64),
    total_bytes INTEGER NOT NULL CHECK(total_bytes BETWEEN 0 AND 67108864))'''
TRIGGERS = {f'{TABLE}_no_{op.lower()}':
    f"CREATE TRIGGER {TABLE}_no_{op.lower()} BEFORE {op} ON {TABLE} "
    "BEGIN SELECT RAISE(ABORT,'protection_append_only'); END"
    for op in ('UPDATE', 'DELETE')}


class ProofError(ValueError):
    """A missing/invalid proof, never authority to stop an existing native exit."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def require(condition, code):
    if not condition:
        raise ProofError(code)


def integer(value, code='invalid_clock', *, positive=False):
    require(type(value) is int and int(positive) <= value <= 2**63-1, code)
    return value


def text(value, code='invalid_identity', maximum=256):
    require(isinstance(value, str) and 0 < len(value.encode()) <= maximum
            and all(32 <= ord(c) < 127 for c in value), code)
    return value


def checksum(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), 'invalid_checksum')
    return value


def exact_keys(value, keys, code='invalid_fields'):
    require(type(value) is dict and set(value) == set(keys), code)


def reference(value):
    exact_keys(value, ('sequence', 'hash'))
    integer(value['sequence'], 'invalid_reference', positive=True)
    checksum(value['hash'])
    return value


def native_reference(value):
    exact_keys(value, ('hash',))
    checksum(value['hash'])
    return value


def owner(value):
    exact_keys(value, ('boot_id', 'pid', 'process_start_ticks', 'generation'))
    text(value['boot_id']); text(value['generation'])
    integer(value['pid'], 'invalid_pid', positive=True)
    integer(value['process_start_ticks'], 'invalid_process_start', positive=True)
    return value


def binding(value):
    exact_keys(value, ('source_sha256', 'policy_sha256', 'configuration_sha256',
        'epoch_id', 'inception_sha256', 'native_genesis_sha256', 'regime'))
    for key in ('source_sha256', 'policy_sha256', 'configuration_sha256',
                'inception_sha256', 'native_genesis_sha256'):
        checksum(value[key])
    text(value['epoch_id'])
    require(value['regime'] in CADENCE, 'invalid_regime')
    return value


def _stable_binding(value):
    # Source/configuration/policy changes start a new OWNER epoch; they never
    # overwrite historical bindings or require rewriting a financial database.
    return {key:value[key] for key in ('epoch_id', 'inception_sha256', 'native_genesis_sha256', 'regime')}


def sample_clock():
    """Capture an actual wall read bracketed by monotonic reads, without retiming.

    No guessed tolerance: the bracket preserves scheduling/read uncertainty.
    A discontinuity which cannot share a consistent offset with the acceptance
    anchors is explicitly UNVERIFIED; it never fabricates a deadline or expiry.
    """
    before = time.monotonic_ns()
    wall = time.time_ns()
    after = time.monotonic_ns()
    return dict(at_ns=before, wall_ns=wall, sample_end_ns=after)


def _clock_pair(at, wall, after):
    integer(at); integer(wall); integer(after)
    require(after >= at, 'invalid_clock_sample_bracket')
    return wall-after, wall-at


@dataclass(frozen=True)
class Limits:
    max_records: int = 8192
    max_bytes: int = 8*1024*1024
    max_record_bytes: int = 8192

    def value(self):
        require(type(self.max_records) is int and 8 <= self.max_records <= 32768,
                'invalid_record_bound')
        require(type(self.max_bytes) is int and 4096 <= self.max_bytes <= 64*1024*1024,
                'invalid_byte_bound')
        require(type(self.max_record_bytes) is int and 1024 <= self.max_record_bytes <= 16384,
                'invalid_payload_bound')
        return dict(max_records=self.max_records, max_bytes=self.max_bytes,
                    max_record_bytes=self.max_record_bytes)


@dataclass(frozen=True)
class AppendResult:
    receipt: dict | None = None
    failure: str | None = None

    @property
    def proof_available(self):
        # This is NOT a readiness/acceptance result.
        return self.failure is None and self.receipt is not None


class ReceiptResolver(Protocol):
    """Trusted read-only adapters over authenticated, consistent native/shared state.

    native() returns a raw exact journal envelope, not ``verified: true``.
    shared() returns raw runtime_prepare and runtime_commit SQL row envelopes.
    census() must derive *all* intersecting lifetimes from the authoritative
    financial cursors, including already-open and retired/closed-between-sample
    positions. It returns start_cursor/end_cursor and lifecycles with native
    lifecycle_id, entry_hash and terminal_hash (None if still held). Existing
    full native/financial replay remains a separate mandatory gate.
    Quote acquisitions must retain their own explicit boot/process identity;
    provider source_generation is not a process clock-domain identifier.
    initial_entry() is optional for recovered windows. Where initial-monitor
    grace is needed, it returns all original immutable entry/scheduler envelopes
    matching the actual financial lifecycle/birth, capped at two to expose
    ambiguity. It must never synthesize a receipt from OPEN or current clocks.
    """
    def native(self, ref: dict) -> dict: ...
    def shared(self, ref: dict) -> dict: ...
    def acquisition(self, evidence_sha256: str) -> dict: ...
    def usd_acquisition(self, acquisition_id: str) -> dict: ...
    def census(self, start_cursor: dict, end_cursor: dict) -> dict: ...
    def initial_entry(self, lifecycle_id: str, birth_ref: dict) -> list[dict]: ...


def _schema(db):
    require(db.execute("SELECT sql FROM sqlite_master WHERE name=?", (TABLE,)).fetchone()
            == (CREATE,), 'proof_schema_mismatch')
    for name, sql in TRIGGERS.items():
        require(db.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
                == (sql,), 'proof_trigger_mismatch')


def _native_genesis(db, expected):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'genesis' in names:
        row = db.execute('SELECT body FROM genesis WHERE id=1').fetchone()
        require(row is not None and digest(json.loads(row[0])) == expected, 'native_genesis_mismatch')
    elif 'records' in names:
        row = db.execute('SELECT body,hash FROM records WHERE category=? AND hash=?',
                         ('pons_selective_paper_genesis', expected)).fetchone()
        require(row is not None and digest(json.loads(row[0])) == row[1], 'native_genesis_mismatch')
    else:raise ProofError('existing_native_store_required')


def _decode_row(row, limits):
    seq, receipt_id, raw, previous, hash_value, total = row
    integer(seq, 'invalid_sequence', positive=True); text(receipt_id, maximum=256)
    require(isinstance(raw, str) and len(raw.encode()) <= limits.max_record_bytes,
            'proof_payload_capacity')
    checksum(previous); checksum(hash_value); integer(total, 'invalid_total_bytes')
    body = json.loads(raw)
    require(canonical(body) == raw and digest([seq, receipt_id, previous, body]) == hash_value,
            'proof_hash_mismatch')
    return body


class ProtectionJournal:
    """One native-owner connection; call after its financial transaction completes.

    Installation/appends fail before mutation if the connection is already in a
    transaction. A zero busy timeout bounds writer admission without altering
    the native connection's lasting configuration. Only the transaction begun
    here is rolled back. try_append storage/validation errors return a sticky
    proof failure. Construction itself raises: a future integration must contain
    factory failure, retain proof unavailability and keep native protection running.
    """
    def __init__(self, db, identity, *, limits=Limits()):
        self.db, self.thread = db, threading.get_ident()
        self.binding = json.loads(canonical(binding(identity)))
        self.limits = limits
        self.limits.value()
        self.failure = None
        self._install()

    def _admit(self):
        require(threading.get_ident() == self.thread, 'native_owner_thread_required')
        require(not self.db.in_transaction, 'caller_transaction_active')

    def _transaction(self, function):
        self._admit()
        # Setting connection busy_timeout does not begin/commit a SQL transaction.
        timeout = self.db.execute('PRAGMA busy_timeout').fetchone()[0]
        began = False
        try:
            self.db.execute('PRAGMA busy_timeout=0')
            self.db.execute('BEGIN IMMEDIATE'); began = True
            result = function()
            self.db.execute('COMMIT'); began = False
            return result
        except BaseException:
            if began and self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise
        finally:
            self.db.execute(f'PRAGMA busy_timeout={int(timeout)}')

    def _install(self):
        def install():
            # Refuse a financial/shared-only connection or an empty new database.
            names = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            require('journal' in names or 'records' in names, 'existing_native_store_required')
            _native_genesis(self.db, self.binding['native_genesis_sha256'])
            if TABLE not in names:
                self.db.execute(CREATE)
                for sql in TRIGGERS.values():self.db.execute(sql)
                body = dict(kind='GENESIS', binding=_stable_binding(self.binding), limits=self.limits.value())
                self._insert('genesis', body)
            _schema(self.db)
            row = self.db.execute(f'SELECT * FROM {TABLE} WHERE sequence=1').fetchone()
            require(row is not None and row[1] == 'genesis' and row[3] == ZERO,
                    'proof_genesis_missing')
            require(_decode_row(row, self.limits) == dict(kind='GENESIS', binding=_stable_binding(self.binding),
                    limits=self.limits.value()), 'proof_binding_mismatch')
        self._transaction(install)

    def _insert(self, receipt_id, body):
        raw = canonical(body); size = len(raw.encode())
        require(size <= self.limits.max_record_bytes, 'proof_payload_capacity')
        old = self.db.execute(f'SELECT * FROM {TABLE} WHERE receipt_id=?', (receipt_id,)).fetchone()
        if old:
            require(_decode_row(old, self.limits) == body, 'conflicting_proof_receipt')
            return dict(sequence=old[0], hash=old[4])
        last = self.db.execute(f'SELECT * FROM {TABLE} ORDER BY sequence DESC LIMIT 1').fetchone()
        if last:
            _decode_row(last, self.limits)
            seq, previous, total = last[0]+1, last[4], last[5]+size
        else:seq, previous, total = 1, ZERO, size
        require(seq <= self.limits.max_records and total <= self.limits.max_bytes,
                'proof_storage_capacity')
        hash_value = digest([seq, receipt_id, previous, body])
        self.db.execute(f'INSERT INTO {TABLE} VALUES(?,?,?,?,?,?)',
                        (seq, receipt_id, raw, previous, hash_value, total))
        return dict(sequence=seq, hash=hash_value)

    def try_append(self, kind, payload):
        """Persist evidence only. A returned receipt never grants risk authority.

        Callers supply original clocks, not booleans claiming deadline success.
        Do not wrap this call in a native financial transaction. A prior failure
        stays latched on this journal instance; restart cannot erase its missing
        interval from the independent verifier's census/turn checks.
        """
        try:
            self._admit()
            require(self.failure is None, self.failure or 'proof_unavailable')
            require(kind in KINDS, 'invalid_proof_kind')
            _payload(kind, payload)
            if kind == 'OWNER':
                require(payload['binding'] == self.binding, 'owner_source_binding_mismatch')
            payload = json.loads(canonical(payload))
            # Logical identity fences conflicting retries, not just body equality.
            key = [kind, payload['owner'], payload.get('lifecycle_id'), payload.get('turn')]
            body = dict(kind=kind, data=payload)
            ref = self._transaction(lambda:self._insert(digest(key), body))
            return AppendResult(receipt=ref)
        except Exception as exc:
            self.failure = str(exc) if isinstance(exc, ProofError) else 'proof_write_unavailable'
            return AppendResult(failure=self.failure)

    def head(self):
        self._admit()
        row = self.db.execute(f'SELECT sequence,hash FROM {TABLE} ORDER BY sequence DESC LIMIT 1').fetchone()
        return dict(sequence=row[0], hash=row[1])


def _payload(kind, p):
    common = ('owner', 'at_ns', 'wall_ns', 'sample_end_ns')
    owner(p['owner']); integer(p['at_ns']); integer(p['wall_ns'])
    _clock_pair(p['at_ns'], p['wall_ns'], p['sample_end_ns'])
    if kind == 'OWNER':
        exact_keys(p, common + ('binding',)); binding(p['binding'])
        return
    if kind == 'END':
        exact_keys(p, common)
        return
    text(p['lifecycle_id'], maximum=2048)
    if kind == 'OPEN':
        exact_keys(p, common + ('lifecycle_id', 'birth_ref', 'native_ref', 'shared_ref', 'due_ns'))
        native_reference(p['birth_ref']); native_reference(p['native_ref'])
        reference(p['shared_ref']); integer(p['due_ns'])
    elif kind == 'CLOSE':
        exact_keys(p, common + ('lifecycle_id', 'native_ref', 'shared_ref'))
        native_reference(p['native_ref']); reference(p['shared_ref'])
    else:
        exact_keys(p, common + ('lifecycle_id', 'turn', 'previous_turn', 'outcome', 'reason',
            'native_before', 'native_after', 'shared_ref', 'timing', 'quote', 'usd', 'usd_requirement'))
        integer(p['turn'], 'invalid_turn', positive=True); checksum(p['previous_turn'])
        require(p['outcome'] in ('COMPLETE', 'FAILED', 'UNAVAILABLE', 'INTERRUPTED'), 'invalid_outcome')
        text(p['reason'], maximum=128)
        native_reference(p['native_before']); native_reference(p['native_after'])
        if p['shared_ref'] is not None:reference(p['shared_ref'])
        timing = p['timing']
        exact_keys(timing, ('due_ns', 'started_ns', 'deadline_ns', 'decision_ns',
            'risk_completed_ns', 'native_durable_ns', 'shared_ack_ns', 'completed_ns', 'next_due_ns'))
        for key, value in timing.items():
            if key in ('native_durable_ns', 'shared_ack_ns') and value is None:continue
            integer(value)
        if p['quote'] is not None:_quote(p['quote'])
        if p['usd'] is not None:_usd(p['usd'])
        require(p['usd_requirement'] in ('REQUIRED', 'NOT_CONSUMED'), 'invalid_usd_requirement')
        require((p['usd'] is None) == (p['usd_requirement'] == 'NOT_CONSUMED'),
                'usd_consumption_declaration_mismatch')


def _quote(q):
    exact_keys(q, ('evidence_sha256', 'profile', 'acquisition_owner', 'position_sha256', 'quantity', 'source_generation',
        'provider_sha256', 'block_id', 'block_sha256', 'started_ns', 'completed_ns', 'deadline_ns'))
    for key in ('evidence_sha256', 'position_sha256', 'provider_sha256', 'block_sha256'):checksum(q[key])
    for key in ('quantity', 'started_ns', 'completed_ns', 'deadline_ns'):integer(q[key])
    text(q['source_generation']); text(q['block_id'])
    owner(q['acquisition_owner'])
    require(q['profile'] in PROFILES, 'unsupported_protection_profile')


def _usd(u):
    exact_keys(u, ('evidence_id', 'evidence_sha256', 'acquisition_id', 'acquisition_owner',
        'acquired_ns', 'acquisition_completed_ns', 'observed_wall_ns', 'valid_until_wall_ns',
        'requested_ns', 'lock_acquired_ns', 'consumed_ns', 'consumed_wall_ns', 'consumed_sample_end_ns', 'mode'))
    text(u['evidence_id']); text(u['acquisition_id']); checksum(u['evidence_sha256'])
    owner(u['acquisition_owner'])
    require(u['mode'] in ('FRESH', 'CACHE', 'PREFETCH'), 'invalid_usd_mode')
    for key in ('acquired_ns', 'acquisition_completed_ns', 'observed_wall_ns',
                'valid_until_wall_ns', 'requested_ns', 'lock_acquired_ns', 'consumed_ns', 'consumed_wall_ns'):
        integer(u[key])
    _clock_pair(u['consumed_ns'], u['consumed_wall_ns'], u['consumed_sample_end_ns'])


def _native(ref, resolver, lifecycle):
    native_reference(ref)
    e = resolver.native(dict(ref))
    exact_keys(e, ('format', 'sequence', 'previous', 'body', 'hash'))
    checksum(e['hash']); require(e['hash'] == ref['hash'], 'native_reference_mismatch')
    require(type(e['body']) is dict, 'native_body_unavailable')
    if e['format'] == 'survivor':
        integer(e['sequence'], 'invalid_native_sequence', positive=True); checksum(e['previous'])
        require(digest([e['sequence'], e['previous'], e['body']]) == e['hash'], 'native_hash_mismatch')
    elif e['format'] == 'pons_current':
        require(e['sequence'] is None and e['previous'] is None
                and digest(e['body']) == e['hash'], 'native_hash_mismatch')
    else:raise ProofError('unsupported_native_receipt')
    p = e['body'].get('position')
    require(type(p) is dict and p.get('id') == lifecycle, 'native_lifecycle_mismatch')
    require(p.get('status') in ('open', 'exit_pending', 'settled', 'written_off'), 'native_position_state')
    return e


def _shared_row(row):
    exact_keys(row, ('sequence', 'operation_id', 'body', 'result', 'state_hash', 'previous', 'hash'))
    integer(row['sequence'], 'invalid_shared_sequence', positive=True)
    for key in ('state_hash', 'previous', 'hash'):checksum(row[key])
    raw, result_raw = canonical(row['body']), canonical(row['result'])
    expected = hashlib.sha256((row['previous']+raw+result_raw+row['state_hash']).encode()).hexdigest()
    require(expected == row['hash'] and row['body'].get('operation_id') == row['operation_id'],
            'shared_hash_mismatch')
    return row['body']


def _shared(ref, resolver, lifecycle, native_hash, identity):
    reference(ref)
    pair = resolver.shared(dict(ref))
    exact_keys(pair, ('prepare', 'commit'))
    prep, ack = pair['prepare'], pair['commit']
    pb, cb = _shared_row(prep), _shared_row(ack)
    require((ack['sequence'], ack['hash']) == (ref['sequence'], ref['hash']), 'shared_reference_mismatch')
    require(pb.get('action') == 'runtime_prepare' and cb.get('action') == 'runtime_commit'
            and prep['sequence'] < ack['sequence'], 'shared_delivery_not_committed')
    pd, cd = pb['data'], cb['data']
    require(pd.get('native_id') == lifecycle and cd.get('native_id') == lifecycle
            and pd.get('journal_hash') == native_hash == cd.get('journal_hash')
            and pd.get('event_key') == cd.get('event_key')
            and pd.get('lane') == cd.get('lane')
            and type(prep['result']) is dict and prep['result'].get('epoch_id') == identity['epoch_id']
            and ack['result'] == dict(accepted=True), 'shared_native_binding_mismatch')
    return pd


@dataclass(frozen=True)
class Window:
    identity: dict
    owner: dict
    start_ns: int
    end_ns: int
    start_wall_ns: int
    end_wall_ns: int
    start_cursor: dict
    end_cursor: dict
    head: dict
    # None denotes an exact zero-width synthetic sample. Real extraction must
    # retain sample_clock()'s actual second monotonic read at both boundaries.
    start_sample_end_ns: int | None = None
    end_sample_end_ns: int | None = None

    @classmethod
    def from_samples(cls, identity, owner_identity, start, end, start_cursor, end_cursor, head):
        for sample in (start, end):
            exact_keys(sample, ('at_ns', 'wall_ns', 'sample_end_ns'))
            _clock_pair(sample['at_ns'], sample['wall_ns'], sample['sample_end_ns'])
        return cls(identity, owner_identity, start['at_ns'], end['at_ns'], start['wall_ns'], end['wall_ns'],
                   start_cursor, end_cursor, head, start['sample_end_ns'], end['sample_end_ns'])


@dataclass(frozen=True)
class Verification:
    ok: bool
    reason: str
    head: dict | None = None
    lifecycles: int = 0
    turns: int = 0
    held_coverage: bool = False
    native_path_resolved: bool = False
    scope: str = 'LOCAL_RESOLVED_EVIDENCE_ONLY_HOST_ATTESTATION_REQUIRED'


def verify_window(db, window, resolver, *, limits=Limits()):
    """Read-only independent proof check; no readiness mutation or host claim.

    A trusted resolver must use consistent authenticated native/shared snapshots;
    caller-supplied success flags and latest protection projections are unusable.
    Cursor resolution must include retired lifetimes, not just current positions.
    No rows outside the exact pinned head are silently accepted as evidence.
    """
    try:
        return _verify_window(db, window, resolver, limits)
    except Exception as exc:
        return Verification(False, str(exc) if isinstance(exc, ProofError) else 'proof_resolution_unavailable')


def _verify_window(db, w, resolver, limits):
    binding(w.identity); owner(w.owner); limits.value(); reference(w.head)
    for value in (w.start_ns, w.end_ns, w.start_wall_ns, w.end_wall_ns):integer(value)
    require(w.end_ns > w.start_ns and w.end_wall_ns >= w.start_wall_ns, 'invalid_window')
    reference(w.start_cursor); reference(w.end_cursor)
    require(w.end_cursor['sequence'] >= w.start_cursor['sequence'], 'financial_cursor_regressed')
    _schema(db)
    _native_genesis(db, w.identity['native_genesis_sha256'])
    require(db.execute(f'SELECT sequence,hash FROM {TABLE} ORDER BY sequence DESC LIMIT 1').fetchone()
            == (w.head['sequence'], w.head['hash']), 'pinned_head_not_current_snapshot')
    require(w.head['sequence'] <= limits.max_records, 'proof_record_capacity')
    rows = db.execute(f'SELECT * FROM {TABLE} WHERE sequence<=? ORDER BY sequence',
                      (w.head['sequence'],))
    previous, total, count = ZERO, 0, 0
    spans, generations, last_at = {}, {}, {}
    all_records = []
    for row in rows:
        count += 1
        require(count <= limits.max_records and row[0] == count and row[3] == previous,
                'proof_chain_gap')
        b = _decode_row(row, limits); total += len(row[2].encode())
        require(total == row[5] and total <= limits.max_bytes, 'proof_byte_capacity')
        previous = row[4]
        if count == 1:
            require(row[1] == 'genesis' and b == dict(kind='GENESIS', binding=_stable_binding(w.identity),
                    limits=limits.value()), 'proof_binding_mismatch')
            continue
        exact_keys(b, ('kind', 'data')); kind, p = b['kind'], b['data']
        require(kind in KINDS, 'invalid_proof_kind'); _payload(kind, p)
        g = digest(p['owner']); at = p['at_ns']
        require(at >= last_at.get(g, 0), 'owner_clock_regressed'); last_at[g] = at
        if kind == 'OWNER':
            require(g not in generations, 'duplicate_owner_generation')
            require(_stable_binding(p['binding']) == _stable_binding(w.identity), 'owner_epoch_binding_mismatch')
            generations[g] = dict(start=at, end=None, owner=p['owner'], sequence=row[0], binding=p['binding'])
        else:
            require(g in generations and generations[g]['end'] is None, 'owner_epoch_unavailable')
            if kind == 'END':generations[g]['end'] = at
        all_records.append((kind, p, dict(sequence=row[0], hash=row[4])))
    require(count == w.head['sequence'] and previous == w.head['hash'], 'pinned_head_mismatch')
    generation = digest(w.owner)
    require(generation in generations and generations[generation]['start'] <= w.start_ns,
            'window_owner_unavailable')
    require(generations[generation]['binding'] == w.identity, 'window_source_binding_mismatch')
    require(generations[generation]['end'] is None or generations[generation]['end'] >= w.end_ns,
            'window_owner_interrupted')
    # Another process generation in this pinned store invalidates continuity.
    require(not any(g != generation and epoch['sequence'] > generations[generation]['sequence']
                    for g, epoch in generations.items()),
            'window_owner_changed')
    cadence = CADENCE[w.identity['regime']]
    for kind, p, ref in all_records:
        if p['owner'] != w.owner:continue
        life = p.get('lifecycle_id')
        if kind == 'OPEN':
            require(life not in spans and p['due_ns'] >= p['at_ns']
                    and p['due_ns'] <= p['at_ns']+cadence, 'lifecycle_open_or_schedule_gap')
            birth = _native(p['birth_ref'], resolver, life)
            current = _native(p['native_ref'], resolver, life)
            require(birth['body'].get('action') in ('filled', 'entry', 'open')
                    and current['body']['position']['status'] in ('open', 'exit_pending'), 'lifecycle_birth_unavailable')
            _shared(p['shared_ref'], resolver, life, p['native_ref']['hash'], w.identity)
            spans[life] = dict(open=p, close=None, turns=[], last_native=p['native_ref'],
                               next_due=p['due_ns'], previous_turn=ZERO)
        elif kind == 'TURN':
            require(life in spans and spans[life]['close'] is None, 'turn_without_open_lifecycle')
            s = spans[life]
            # Even an earlier failed turn owns the following schedule. Validate
            # its structural clocks before it may seed an accepted interval.
            _schedule(p, cadence)
            require(p['turn'] == len(s['turns'])+1 and p['previous_turn'] == s['previous_turn']
                    and p['native_before'] == s['last_native'], 'lifecycle_turn_gap')
            require(p['timing']['due_ns'] == s['next_due'], 'original_schedule_changed')
            s['turns'].append(p); s['previous_turn'] = ref['hash']
            s['next_due'] = p['timing']['next_due_ns']; s['last_native'] = p['native_after']
        elif kind == 'CLOSE':
            require(life in spans and spans[life]['close'] is None, 'close_without_open_lifecycle')
            s = spans[life]; s['close'] = p
            end = _native(p['native_ref'], resolver, life)
            require(end['body']['position']['status'] in ('settled', 'written_off')
                    and s['turns'], 'terminal_protection_unproved')
            _shared(p['shared_ref'], resolver, life, p['native_ref']['hash'], w.identity)
    relevant = {life:s for life, s in spans.items() if s['open']['at_ns'] <= w.end_ns
                and (s['close'] is None or s['close']['at_ns'] >= w.start_ns)}
    census = resolver.census(dict(w.start_cursor), dict(w.end_cursor))
    exact_keys(census, ('epoch_id', 'inception_sha256', 'regime', 'start_cursor', 'end_cursor', 'lifecycles'))
    require(census['start_cursor'] == w.start_cursor and census['end_cursor'] == w.end_cursor,
            'financial_census_cursor_mismatch')
    require(all(census[key] == w.identity[key] for key in ('epoch_id', 'inception_sha256', 'regime')),
            'financial_census_binding_mismatch')
    require(type(census['lifecycles']) is list and len(census['lifecycles']) <= limits.max_records,
            'financial_census_unavailable')
    actual = {}
    for item in census['lifecycles']:
        exact_keys(item, ('lifecycle_id', 'entry_hash', 'terminal_hash'))
        text(item['lifecycle_id'], maximum=2048); checksum(item['entry_hash'])
        if item['terminal_hash'] is not None:checksum(item['terminal_hash'])
        require(item['lifecycle_id'] not in actual, 'duplicate_financial_lifecycle')
        actual[item['lifecycle_id']] = item
    require(set(actual) == set(relevant), 'lifetime_census_incomplete')
    anchors = [p for _, p, _ in all_records if p['owner'] == w.owner
               and p['sample_end_ns'] >= w.start_ns and p['at_ns'] <= w.end_ns]
    leading = {}
    for life, s in relevant.items():
        require(actual[life]['entry_hash'] == s['open']['birth_ref']['hash'], 'lifecycle_entry_mismatch')
        terminal = s['close']['native_ref']['hash'] if s['close'] else None
        require(actual[life]['terminal_hash'] == terminal, 'lifecycle_terminal_mismatch')
        require(s['turns'], 'held_protection_unexercised')
        prior = [p for p in s['turns'] if p['timing']['completed_ns'] <= w.start_ns]
        if prior:
            leading[life] = prior[-1]
            require(prior[-1]['outcome'] == 'COMPLETE', 'leading_held_coverage_unproved')
            require(w.start_ns <= prior[-1]['timing']['next_due_ns']+cadence,
                    'leading_held_coverage_gap')
            anchors.append(prior[-1])
        else:
            # Registration is not a held-entry clock, even at/inside the window
            # or in its first OWNER generation. Resolve original independent
            # clocks only when this interval depends on first-monitor grace.
            entry = _initial_entry(s, life, dict(hash=actual[life]['entry_hash']),
                resolver, w.identity, w.owner, generations[generation]['start'], cadence)
            held = entry['held_clock']
            require(max(w.start_ns, held['sample_end_ns']) <= entry['first_deadline_ns'],
                    'leading_held_coverage_gap')
            anchors.append(held)
    offset = _window_clock(w, anchors)
    turns = 0; not_consumed = 0
    for life, s in relevant.items():
        if life in leading:
            require(_turn(leading[life], resolver, life, cadence, w.identity, offset),
                    'leading_required_usd_unproved')
        for p in s['turns']:
            t = p['timing']
            # Verify all retained turns for the intersecting lifetime. Failures
            # before this acceptance window are retained, but do not retroactively
            # fail a later separately recovered interval.
            if t['completed_ns'] < w.start_ns:continue
            # A known original deadline inside the window still owns coverage
            # when its actual dispatch starts after the window has ended.
            if t['started_ns'] > w.end_ns and t['deadline_ns'] > w.end_ns:continue
            consumed = _turn(p, resolver, life, cadence, w.identity, offset)
            not_consumed += int(not consumed); turns += 1
        boundary = min(w.end_ns, s['close']['at_ns']) if s['close'] else w.end_ns
        completed = [p for p in s['turns'] if p['timing']['completed_ns'] <= boundary]
        require(completed, 'held_interval_unproved')
        last = completed[-1]
        require(boundary <= last['timing']['next_due_ns']+cadence, 'held_tail_coverage_gap')
    if not_consumed:
        return Verification(False, 'NATIVE_PATH_RESOLVED_USD_NOT_CONSUMED_NOT_FULL_PROTECTION_PROOF',
                            w.head, len(relevant), turns, False, True)
    # All leading turns reached _turn above; they can cover this interval even
    # when no new turn completes inside it. Preserve the in-window turn count.
    return Verification(True, 'RESOLVED' if relevant else 'UNEXERCISED_NO_HELD_POSITIONS',
                        w.head, len(relevant), turns, bool(relevant and (turns or leading)), True)


def _utc_ns(value):
    require(isinstance(value, str), 'usd_original_validity_unavailable')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(dt.tzinfo is not None, 'usd_original_validity_unavailable')
    delta = dt.astimezone(timezone.utc)-datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days*86400+delta.seconds)*NS+delta.microseconds*1000


def _window_clock(w, payloads):
    start_after = w.start_ns if w.start_sample_end_ns is None else w.start_sample_end_ns
    end_after = w.end_ns if w.end_sample_end_ns is None else w.end_sample_end_ns
    require(start_after <= w.end_ns, 'window_clock_brackets_overlap')
    intervals = [_clock_pair(w.start_ns, w.start_wall_ns, start_after),
                 _clock_pair(w.end_ns, w.end_wall_ns, end_after)]
    for p in payloads:
        intervals.append(_clock_pair(p['at_ns'], p['wall_ns'], p['sample_end_ns']))
        u = p.get('usd')
        if u is not None:
            intervals.append(_clock_pair(u['consumed_ns'], u['consumed_wall_ns'], u['consumed_sample_end_ns']))
    low, high = max(i[0] for i in intervals), min(i[1] for i in intervals)
    require(low <= high, 'wall_monotonic_clock_step_unverified')
    return low, high


def _initial_entry(span, life, birth_ref, resolver, identity, owner_identity, owner_start, cadence):
    """Resolve original first-monitor eligibility, never a native fill deadline.

    The trusted reader must extract an immutable receipt captured at the actual
    original held-entry boundary and first schedule, not at a later shared ACK
    or OPEN registration. Native journal ``at`` is a caller/strategy timestamp,
    not host COMMIT. No production capture or host authentication is wired here.
    A missing/invalid anchor affects only windows which need initial grace.
    """
    lookup = getattr(resolver, 'initial_entry', None)
    require(callable(lookup), 'initial_entry_clock_unavailable')
    try:matches = lookup(life, dict(birth_ref))
    except ProofError:raise
    except Exception as exc:raise ProofError('initial_entry_clock_unavailable') from exc
    require(type(matches) in (list, tuple), 'initial_entry_receipts_invalid')
    require(bool(matches), 'initial_entry_clock_unavailable')
    require(len(matches) == 1, 'initial_entry_clock_ambiguous')
    receipt = matches[0]
    exact_keys(receipt, ('body', 'hash'), 'initial_entry_receipt_invalid')
    checksum(receipt['hash'])
    body = receipt['body']
    try:raw = canonical(body)
    except (TypeError, ValueError) as exc:raise ProofError('initial_entry_receipt_invalid') from exc
    require(len(raw.encode()) <= 16384, 'initial_entry_receipt_bound')
    require(digest(body) == receipt['hash'], 'initial_entry_hash_mismatch')
    exact_keys(body, ('schema', 'binding', 'owner', 'lifecycle_id', 'birth_ref',
        'entry_shared_ref', 'profile', 'held_clock', 'first_due_ns', 'first_deadline_ns'),
        'initial_entry_fields_invalid')
    require(body['schema'] == 'initial-entry-schedule-v1', 'initial_entry_schema_mismatch')
    binding(body['binding']); owner(body['owner'])
    require(body['binding'] == identity, 'initial_entry_binding_mismatch')
    require(body['owner'] == owner_identity, 'initial_entry_clock_domain')
    require(body['lifecycle_id'] == life and body['birth_ref'] == birth_ref,
            'initial_entry_lifecycle_mismatch')
    native_reference(body['birth_ref']); reference(body['entry_shared_ref'])
    birth = _native(body['birth_ref'], resolver, life)
    require(birth['body'].get('action') in ('filled', 'entry', 'open'), 'initial_entry_birth_unavailable')
    shared = _shared(body['entry_shared_ref'], resolver, life, birth_ref['hash'], identity)
    require(shared.get('kind') == 'enter', 'initial_entry_ack_mismatch')
    profile = body['profile']
    require(type(profile) is str and profile in PROFILES and PROFILES[profile][0] == identity['regime'],
            'initial_entry_profile_mismatch')
    held = body['held_clock']
    exact_keys(held, ('at_ns', 'wall_ns', 'sample_end_ns'), 'initial_entry_clock_invalid')
    _clock_pair(held['at_ns'], held['wall_ns'], held['sample_end_ns'])
    require(owner_start <= held['at_ns'] and held['sample_end_ns'] <= span['open']['at_ns'],
            'initial_entry_registration_before_held_boundary')
    due, deadline = body['first_due_ns'], body['first_deadline_ns']
    integer(due); integer(deadline)
    require(held['sample_end_ns'] <= due <= held['at_ns']+cadence
            and due <= deadline <= due+cadence,
            'initial_entry_schedule_invalid')
    first = span['turns'][0]
    require(due == span['open']['due_ns'] == first['timing']['due_ns']
            and deadline == first['timing']['deadline_ns'], 'initial_entry_schedule_mismatch')
    require(first['quote'] is None or first['quote']['profile'] == profile, 'initial_entry_profile_mismatch')
    return body


def _schedule(p, cadence):
    """Structural validity is required even outside the acceptance interval."""
    t = p['timing']
    require(t['due_ns'] <= t['started_ns'] <= t['decision_ns'] <= t['risk_completed_ns']
            <= t['completed_ns'] == p['at_ns'], 'protection_clock_order')
    if p['native_after'] != p['native_before']:
        require(t['native_durable_ns'] is not None and t['shared_ack_ns'] is not None
                and t['risk_completed_ns'] <= t['native_durable_ns'] <= t['shared_ack_ns'] <= t['completed_ns'],
                'native_commit_or_ack_unproved')
    else:
        require(t['native_durable_ns'] is None and t['shared_ack_ns'] is None,
                'unchanged_hold_has_no_new_commit_or_ack')
    # An honestly FAILED dispatch may start after its original deadline. Keep
    # that failure and its bounded following schedule. Recorded COMPLETE means
    # processing returned, not verified timeliness: _turn rejects deadline
    # misses in affected/leading coverage. Earlier raw timing failures remain
    # retained without poisoning a later independently verified recovered turn.
    require(t['due_ns'] <= t['deadline_ns'] <= t['due_ns']+cadence,
            'original_schedule_deadline_invalid')
    require(t['completed_ns'] <= t['next_due_ns'] <= t['completed_ns']+cadence,
            'next_schedule_gap')


def _turn(p, resolver, life, cadence, identity, offset):
    require(p['outcome'] == 'COMPLETE', 'held_turn_'+p['outcome'].lower())
    _schedule(p, cadence)
    t = p['timing']
    require(t['risk_completed_ns'] <= t['deadline_ns'], 'original_protection_deadline_missed')
    before = _native(p['native_before'], resolver, life)
    after = _native(p['native_after'], resolver, life)
    require(before['body']['position']['status'] in ('open', 'exit_pending'), 'turn_not_held')
    require(after['body']['position']['status'] in ('open', 'exit_pending'),
            'execution_requires_original_native_profile')
    if p['native_after'] != p['native_before']:
        # This record proves a held-risk observation/mark, not an execution.
        # A blocked durable mark/ACK must not disappear behind component timing.
        require(t['shared_ack_ns'] <= t['deadline_ns'], 'held_risk_delivery_deadline_missed')
    require(t['completed_ns'] <= t['deadline_ns'], 'held_risk_completion_deadline_missed')
    q, u = p['quote'], p['usd']
    require(q is not None and p['shared_ref'] is not None, 'quote_or_ack_unavailable')
    profile = PROFILES[q['profile']]
    require(q['acquisition_owner'] == p['owner'], 'quote_acquisition_clock_domain')
    require(profile[0] == identity['regime'], 'protection_profile_regime_mismatch')
    acquisition = resolver.acquisition(q['evidence_sha256'])
    exact_keys(acquisition, ('source_sha256', 'policy_sha256', 'regime', 'quote',
                             'native_before', 'native_after', 'usd_required'))
    require(type(acquisition['usd_required']) is bool, 'independent_usd_requirement_unavailable')
    require(acquisition == dict(source_sha256=identity['source_sha256'],
        policy_sha256=identity['policy_sha256'], regime=identity['regime'], quote=q,
        native_before=p['native_before'], native_after=p['native_after'],
        usd_required=p['usd_requirement'] == 'REQUIRED'),
        'independent_acquisition_binding_mismatch')
    require(q['position_sha256'] == digest(before['body']['position'])
            and q['quantity'] == before['body']['position'].get('tokens'), 'quote_position_mismatch')
    require(t['started_ns'] <= q['started_ns'] <= q['completed_ns'] <= t['decision_ns']
            and q['completed_ns'] <= q['deadline_ns'] <= q['started_ns']+profile[1],
            'quote_original_deadline_missed')
    if profile[2]:
        require(q['deadline_ns'] <= t['due_ns']+5*NS, 'current_shared_original_due_changed')
    shared = _shared(p['shared_ref'], resolver, life, p['native_after']['hash'], identity)
    if u is None:
        require(p['usd_requirement'] == 'NOT_CONSUMED' and p['native_before'] == p['native_after']
                and acquisition['usd_required'] is False, 'usd_requirement_not_independently_proven')
        # Honest no-op coverage, explicitly NOT full quote/USD protection proof.
        return False
    require(acquisition['usd_required'] is True, 'usd_requirement_not_independently_proven')
    original = resolver.usd_acquisition(u['acquisition_id'])
    keys = ('evidence_id', 'evidence_sha256', 'acquisition_id', 'acquisition_owner',
            'acquired_ns', 'acquisition_completed_ns', 'observed_wall_ns', 'valid_until_wall_ns')
    exact_keys(original, ('source_sha256', 'policy_sha256')+keys)
    require(original == dict(source_sha256=identity['source_sha256'],
        policy_sha256=identity['policy_sha256'], **{key:u[key] for key in keys}),
        'usd_original_acquisition_identity_mismatch')
    require(u['requested_ns'] <= u['lock_acquired_ns'] <= u['consumed_ns'] <= u['consumed_sample_end_ns'] <= t['risk_completed_ns']
            and t['started_ns'] <= u['requested_ns'] and u['consumed_ns'] <= t['risk_completed_ns'],
            'usd_consumption_clock_order')
    # Original acquisition may precede this turn (cache/prefetch), but cannot
    # cross process/boot clocks or be relabelled newly acquired.
    require(u['acquisition_owner'] == p['owner'], 'usd_acquisition_clock_domain')
    require(u['acquired_ns'] <= u['acquisition_completed_ns'] <= u['consumed_ns'],
            'usd_acquisition_clock_order')
    if u['mode'] == 'FRESH':
        require(u['requested_ns'] <= u['acquired_ns'], 'fresh_usd_predates_request')
    elif u['mode'] == 'CACHE':
        require(u['acquisition_completed_ns'] <= u['requested_ns'], 'cache_identity_retimed')
    require(u['observed_wall_ns'] <= u['consumed_wall_ns'] <= u['valid_until_wall_ns'],
            'usd_original_validity_missed')
    own_low, own_high = _clock_pair(u['consumed_ns'], u['consumed_wall_ns'], u['consumed_sample_end_ns'])
    require(max(own_low, offset[0]) <= min(own_high, offset[1]),
            'usd_wall_monotonic_clock_unverified')
    require(u['observed_wall_ns'] <= u['consumed_ns']+offset[0]
            and u['consumed_sample_end_ns']+offset[1] <= u['valid_until_wall_ns'],
            'usd_wall_validity_interval_unverified')
    require(u['consumed_ns'] <= t['deadline_ns'], 'usd_original_deadline_missed')
    ev = shared.get('value_evidence')
    require(type(ev) is dict and ev.get('evidence_id') == u['evidence_id']
            and ev.get('evidence_sha256') == u['evidence_sha256']
            and _utc_ns(ev.get('as_of')) == u['observed_wall_ns']
            and _utc_ns(ev.get('valid_until')) == u['valid_until_wall_ns'], 'shared_usd_evidence_mismatch')
    # A no-op HOLD anchors the unchanged native/shared state; its actual quote
    # and USD consumption are still separate immutable protection evidence.
    require(after['body']['position']['id'] == life, 'native_after_missing')
    return True


class SQLiteReceiptResolver:
    """Concrete SELECT-only native/shared lookup; no replay/host claims.

    Connections are supplied by the authenticated extraction owner. census_reader
    must traverse the actual financial range, including retained retirement
    receipts. acquisition_reader must independently join the real quote/native
    path to a fixed PROFILES entry; usd_reader resolves the original immutable
    acquisition (including entry-time acquisition before the first held turn).
    Neither hook may echo the TURN payload or return a success flag. Missing
    archived native rows fail closed; archive-resolution wiring
    is deliberately not replaced by trusting a caller's ``verified`` boolean.
    Optional initial_entry_reader(lifecycle_id,birth_ref) must return original
    raw {body,hash} envelopes from an independent immutable keyed store. Return
    all exact matches, capped at two, never a latest match or a regenerated OPEN.
    The held_clock brackets the original held boundary, not ACK/registration;
    first_due/deadline retain the original captured schedule. This hook has no
    production producer or authenticated host extraction in this offline core.
    """
    def __init__(self, native_db, shared_db, census_reader, acquisition_reader, usd_reader,
                 *, initial_entry_reader=None):
        self.native_db, self.shared_db, self.census_reader = native_db, shared_db, census_reader
        self.acquisition_reader = acquisition_reader
        self.usd_reader = usd_reader
        self.initial_entry_reader = initial_entry_reader

    def native(self, ref):
        native_reference(ref)
        names = {r[0] for r in self.native_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'journal' in names:
            r = self.native_db.execute('SELECT seq,body,previous,hash FROM journal WHERE hash=?',
                                       (ref['hash'],)).fetchone()
            require(r is not None, 'native_receipt_unavailable')
            return dict(format='survivor', sequence=r[0], previous=r[2], body=json.loads(r[1]), hash=r[3])
        r = self.native_db.execute('SELECT body,hash FROM records WHERE category=? AND hash=?',
            ('pons_selective_paper_journal', ref['hash'])).fetchone()
        require(r is not None, 'native_receipt_unavailable')
        return dict(format='pons_current', sequence=None, previous=None, body=json.loads(r[0]), hash=r[1])

    def _shared(self, *, sequence=None, operation_id=None):
        column, value = ('sequence', sequence) if sequence is not None else ('operation_id', operation_id)
        r = self.shared_db.execute('SELECT sequence,operation_id,body,result,state_hash,previous,hash '
            f'FROM shared_capital_events WHERE {column}=?', (value,)).fetchone()
        require(r is not None, 'shared_receipt_unavailable')
        return dict(sequence=r[0], operation_id=r[1], body=json.loads(r[2]), result=json.loads(r[3]),
                    state_hash=r[4], previous=r[5], hash=r[6])

    def shared(self, ref):
        reference(ref)
        commit = self._shared(sequence=ref['sequence'])
        data = commit['body'].get('data', {})
        text(data.get('lane')); checksum(data.get('journal_hash'))
        prepare = self._shared(operation_id='intent:'+data['lane']+':'+data['journal_hash'])
        return dict(prepare=prepare, commit=commit)

    def census(self, start_cursor, end_cursor):
        for cursor in (start_cursor, end_cursor):
            reference(cursor)
            row = self._shared(sequence=cursor['sequence'])
            _shared_row(row)
            require(row['hash'] == cursor['hash'], 'financial_cursor_not_durable')
        return self.census_reader(start_cursor, end_cursor)

    def acquisition(self, evidence_sha256):
        checksum(evidence_sha256)
        return self.acquisition_reader(evidence_sha256)

    def usd_acquisition(self, acquisition_id):
        text(acquisition_id)
        return self.usd_reader(acquisition_id)

    def initial_entry(self, lifecycle_id, birth_ref):
        text(lifecycle_id, maximum=2048); native_reference(birth_ref)
        require(self.initial_entry_reader is not None, 'initial_entry_clock_unavailable')
        return self.initial_entry_reader(lifecycle_id, dict(birth_ref))
