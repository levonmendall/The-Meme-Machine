"""Dormant observation anchored inside the original successful replay snapshot.

The approved source's financial actors append only through original _write;
they never rewrite old rows or mutate schema.  Exact known schema and its
SQLite generation must remain continuous.  Hostile raw SQL/root restoring
schema_version, arbitrary Python mutation and hostile SQLite are outside that
premise.  Path metadata associates an owned connection, not kernel FD identity.
This is not held-population, protection, boot, readiness or funding authority.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time

from meme_machine.exact_money import arithmetic
from meme_machine.shared_capital import authority as original
from meme_machine.shared_capital.model import CapitalError, canonical, digest, wire
from meme_machine.shared_capital.runtime import RuntimeCapital


_MAX_ROWS = 256
_MAX_BYTES = 2 * 1024 * 1024
_MAX_STATE_BYTES = 32 * 1024 * 1024
_ANCHOR_ISSUER = object()
_TEXT_FIELDS = ('operation_id', 'body', 'result', 'state_hash', 'previous', 'hash')
_PENDING = (
    ('RESERVATION', 'reservations'), ('COMMITMENT', 'commitments'),
    ('OBLIGATION', 'obligations'), ('PENDING_BACKING', 'pending_backing'),
    ('RUNTIME_PENDING', 'runtime_pending'), ('RUNTIME_INBOX', 'runtime_inbox'),
)


@dataclass(frozen=True)
class _FinancialView:
    """Detached original bodies are immutable JSON text, never authority."""
    status: str
    reason: str
    owner_sha256: str
    schema_version: int
    sequence: int
    journal_hash: str
    state_sha256: str
    cut_sequence: int
    cut_journal_hash: str
    rows: int
    text_bytes: int
    current_members: tuple = field(repr=False)
    terminal_members: tuple = field(repr=False)
    pending: tuple = field(repr=False)
    counts: tuple
    error: Exception | None = field(default=None, repr=False, compare=False)


_FOREIGN_OWNER_VIEW = _FinancialView(
    status='UNKNOWN', reason='FOREIGN_OWNER', owner_sha256='UNAVAILABLE',
    schema_version=-1, sequence=-1, journal_hash='UNAVAILABLE',
    state_sha256='UNAVAILABLE', cut_sequence=-1, cut_journal_hash='UNAVAILABLE',
    rows=0, text_bytes=0, current_members=(), terminal_members=(), pending=(),
    counts=(('RESERVATION', 'UNESTABLISHED'), ('COMMITMENT', 'UNESTABLISHED'),
            ('OBLIGATION', 'UNESTABLISHED'), ('PENDING_DELIVERY', 'UNESTABLISHED'),
            ('PENDING_BACKING', 'UNESTABLISHED'), ('RUNTIME_PENDING', 'UNESTABLISHED'),
            ('RUNTIME_INBOX', 'UNESTABLISHED'), ('GLOBAL_OPEN', 'UNESTABLISHED'),
            ('LEGACY_NATIVE_PENDING', 'UNESTABLISHED')))


class _Deferred(Exception):
    pass


def _lease_check(deadline, cancelled):
    if (type(deadline) not in (int, float) or not math.isfinite(deadline)
            or not callable(cancelled)):
        raise ValueError('held_financial_lease_bounds')
    def check():
        if cancelled():
            raise _Deferred('CANCELLED')
        if time.monotonic() >= deadline:
            raise _Deferred('DEADLINE')
    return check


class _RetainedFinancialRead(RuntimeError):
    """The owner must resolve this borrowed read transaction before any reuse.

    No transaction token exists in SQLite.  Raw COMMIT/reuse while this handoff
    is retained is forbidden: cleanup must not target a later unrelated read.
    Neither cleanup nor this exception may close the original owner connection.
    """
    def __init__(self, prefix, primary, cleanup_error, transaction_active):
        super().__init__('held_financial_owned_read_cleanup_required')
        self.prefix, self.authority = prefix, prefix._authority
        self.primary, self.cleanup_error = primary, cleanup_error
        self.latest_cleanup_error = cleanup_error
        self.transaction_active = transaction_active
        self.cleanup_state = 'RETAINED'
        self.cleanup_attempts = 0


def _normalized_sql(value):
    # Normalize whitespace/keyword case only outside quoted SQL tokens. Do not
    # erase literal changes such as RAISE's diagnostic text or quoted names.
    out, quote, index = [], None, 0
    while index < len(value):
        char = value[index]
        if quote:
            out.append(char)
            if char == quote:
                if index + 1 < len(value) and value[index+1] == quote:
                    out.append(quote);index += 1
                else:quote = None
        elif char in ("'", '"', '`'):
            quote = char;out.append(char)
        elif not char.isspace():
            out.append(char.lower())
        index += 1
    return ''.join(out)


_EXPECTED_SCHEMA = tuple(sorted((
    ('table', 'shared_capital_projection', 'shared_capital_projection', _normalized_sql(
        'CREATE TABLE shared_capital_projection(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL, hash TEXT NOT NULL)')),
    ('table', 'shared_capital_events', 'shared_capital_events', _normalized_sql(
        'CREATE TABLE shared_capital_events(sequence INTEGER PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE,'
        ' body TEXT NOT NULL, result TEXT NOT NULL, state_hash TEXT NOT NULL, previous TEXT NOT NULL, hash TEXT NOT NULL)')),
    ('index', 'sqlite_autoindex_shared_capital_events_1', 'shared_capital_events', None),
    ('trigger', 'shared_capital_no_update', 'shared_capital_events', _normalized_sql(
        "CREATE TRIGGER shared_capital_no_update BEFORE UPDATE ON shared_capital_events BEGIN SELECT RAISE(ABORT,'append_only'); END")),
    ('trigger', 'shared_capital_no_delete', 'shared_capital_events', _normalized_sql(
        "CREATE TRIGGER shared_capital_no_delete BEFORE DELETE ON shared_capital_events BEGIN SELECT RAISE(ABORT,'append_only'); END")),
)))


def _schema(db):
    generation = _one(db, 'PRAGMA main.schema_version')
    if not generation or type(generation[0]) is not int or generation[0] < 0:
        raise CapitalError('held_financial_schema_generation')
    where = " FROM main.sqlite_schema WHERE tbl_name IN ('shared_capital_events','shared_capital_projection')"
    cursor = db.execute('SELECT length(CAST(type AS BLOB)),length(CAST(name AS BLOB)),'
        'length(CAST(tbl_name AS BLOB)),length(CAST(sql AS BLOB))' + where + ' LIMIT 6')
    try:
        metadata = cursor.fetchall()
    finally:
        cursor.close()
    if (len(metadata) != len(_EXPECTED_SCHEMA) or any(
            any(type(size) is not int or not 0 < size <= 128 for size in row[:3])
            or row[3] is not None and (type(row[3]) is not int or not 0 < row[3] <= 16384)
            for row in metadata)):
        raise CapitalError('held_financial_schema_bound')
    # CASE admission remains in the same statement as text materialization,
    # including the post-snapshot check; a catalog race cannot bypass bounds.
    admitted = ["CASE WHEN typeof("+name+")='text' AND length(CAST("+name+
                " AS BLOB)) BETWEEN 1 AND 128 THEN "+name+" END"
                for name in ('type','name','tbl_name')]
    admitted.append("CASE WHEN sql IS NULL THEN NULL WHEN typeof(sql)='text' AND "
                    "length(CAST(sql AS BLOB)) BETWEEN 1 AND 16384 THEN sql ELSE 0 END")
    cursor = db.execute('SELECT '+','.join(admitted) + where + ' LIMIT 6')
    try:
        rows = tuple(sorted((kind, name, table, _normalized_sql(sql) if sql is not None else None)
                            for kind, name, table, sql in cursor))
    finally:
        cursor.close()
    if rows != _EXPECTED_SCHEMA:
        raise CapitalError('held_financial_schema_mismatch')
    if _one(db, 'PRAGMA main.schema_version') != generation:
        raise CapitalError('held_financial_schema_changed')
    return generation[0]


@dataclass(frozen=True)
class _ReplayAnchor:
    capture: object = field(repr=False)
    authority: object = field(repr=False)
    db: object = field(repr=False)
    key: tuple = field(repr=False)
    raw_state: str = field(repr=False)
    sequence: int
    journal_hash: str
    state_sha256: str
    schema_version: int
    issuer: object = field(repr=False)

    def __reduce__(self):
        raise TypeError('held_financial_anchor_is_process_private')


class _FinancialReplayCapture:
    """One private original-verifier capture under an existing native owner."""
    def __init__(self, owner):
        from meme_machine.operational.normal_pump_boot import NativePumpOwnerContext, require_pump_owner_context
        from meme_machine.operational.normal_pons_boot import NativePonsOwnerContext, require_pons_owner_context
        if type(owner) is NativePumpOwnerContext:
            self._require = require_pump_owner_context
        elif type(owner) is NativePonsOwnerContext:
            self._require = require_pons_owner_context
        else:
            raise TypeError('held_financial_private_native_owner_required')
        self._owner = self._require(owner)
        self._thread = (os.getpid(), threading.get_ident())
        self._identity = owner.identity()
        self._owner_sha = owner.identity_sha256
        self._phase, self._failure = 'NEW', None
        self._authority = self._anchor = None

    def __reduce__(self):
        raise TypeError('held_financial_capture_is_process_private')

    def _check(self):
        if self._thread != (os.getpid(), threading.get_ident()):
            raise CapitalError('held_financial_foreign_owner')
        if self._require(self._owner) is not self._owner or self._owner.identity_sha256 != self._owner_sha:
            raise CapitalError('held_financial_owner_changed')

    def _observe(self, operation, *args):
        if self._failure is not None:
            return
        try:
            self._check()
            operation(*args)
        except Exception as exc:
            self._failure, self._phase, self._anchor = exc, 'UNKNOWN', None

    def _begin(self, authority, issuer):
        self._observe(self._start, authority, issuer)

    def _start(self, authority, issuer):
        if (issuer is not original._HELD_REPLAY_ISSUER or self._phase != 'NEW'
                or type(authority) is not RuntimeCapital or type(authority.db) is not sqlite3.Connection):
            raise CapitalError('held_financial_original_replay_required')
        if authority.path.resolve() != Path(self._identity['root'])/'shared-capital.sqlite':
            raise CapitalError('held_financial_owner_root_mismatch')
        self._authority, self._phase = authority, 'VERIFYING'

    def _stage(self, authority, state, summary, issuer):
        self._observe(self._staging, authority, state, summary, issuer)

    def _staging(self, authority, state, summary, issuer):
        if (issuer is not original._HELD_REPLAY_ISSUER or self._phase != 'VERIFYING'
                or authority is not self._authority or not authority._replaying or not authority.db.in_transaction):
            raise CapitalError('held_financial_original_snapshot_required')
        identity = self._identity['launch']
        if (type(state) is not dict or state['epoch_id'] != identity['epoch_id']
                or state['inception_sha256'] != identity['inception_sha256']):
            raise CapitalError('held_financial_owner_epoch_mismatch')
        key = authority._replay_prefix_key()
        if key is None or key[-2:] != (RuntimeCapital._apply, RuntimeCapital._reconcile):
            raise CapitalError('held_financial_original_reducer_required')
        cursor = authority.db.execute('PRAGMA database_list')
        try:
            databases = cursor.fetchall()
        finally:
            cursor.close()
        mains = [row[2] for row in databases if row[1] == 'main']
        if mains != [str(Path(self._identity['root'])/'shared-capital.sqlite')]:
            raise CapitalError('held_financial_owned_connection_mismatch')
        raw = canonical(state)
        if len(raw.encode()) > _MAX_STATE_BYTES or hashlib.sha256(raw.encode()).hexdigest() != summary['state_sha256']:
            raise CapitalError('held_financial_initial_state_bound')
        self._anchor = _ReplayAnchor(self, authority, authority.db, key, raw, summary['events'],
            summary['journal_hash'], summary['state_sha256'], _schema(authority.db), _ANCHOR_ISSUER)
        self._phase = 'STAGED'

    def _publish(self, authority, issuer):
        self._observe(self._publication, authority, issuer)
        # Preserve the original startup cancellation authority after the last
        # fallible capture check and before making the anchor consumable.
        authority._check_startup_replay_cancel()
        if self._phase == 'PUBLISHABLE':
            self._phase = 'PUBLISHED'

    def _publication(self, authority, issuer):
        if (issuer is not original._HELD_REPLAY_ISSUER or self._phase != 'STAGED'
                or authority is not self._authority or authority.db.in_transaction):
            raise CapitalError('held_financial_original_replay_not_finished')
        self._phase = 'PUBLISHABLE'

    def _discard(self, authority, issuer):
        if issuer is original._HELD_REPLAY_ISSUER and authority is self._authority:
            self._anchor, self._phase = None, 'DISCARDED'

    def prefix(self, *, deadline, cancelled):
        self._check()
        if self._failure is not None or self._phase != 'PUBLISHED' or self._anchor is None:
            raise CapitalError('held_financial_anchor_unavailable') from self._failure
        return _FinancialPrefix(self._anchor, deadline=deadline, cancelled=cancelled)


def _one(db, sql, parameters=()):
    cursor = db.execute(sql, parameters)
    try:
        return cursor.fetchone()
    finally:
        cursor.close()


def _hash(value):
    return (type(value) is str and len(value) == 64
            and all(c in '0123456789abcdef' for c in value))


def _head(db, sequence=None):
    where, parameters = ('', ()) if sequence is None else (' WHERE sequence=?', (sequence,))
    suffix = ' ORDER BY sequence DESC LIMIT 1' if sequence is None else ''
    # Check sizes/types in SQLite before transferring any journal text.
    row = _one(db, 'SELECT sequence,typeof(hash),length(CAST(hash AS BLOB)),'
               'typeof(state_hash),length(CAST(state_hash AS BLOB))'
               ' FROM shared_capital_events' + where + suffix, parameters)
    if (not row or type(row[0]) is not int or row[0] < 1
            or row[1:] != ('text', 64, 'text', 64)):
        raise CapitalError('held_financial_head_invalid')
    row = _one(db, 'SELECT sequence,hash,state_hash FROM shared_capital_events WHERE sequence=?', (row[0],))
    if not row or not _hash(row[1]) or not _hash(row[2]):
        raise CapitalError('held_financial_head_invalid')
    return row


class _FinancialPrefix:
    def __init__(self, anchor, *, deadline, cancelled):
        check = _lease_check(deadline, cancelled)
        if type(anchor) is not _ReplayAnchor or anchor.issuer is not _ANCHOR_ISSUER:
            raise CapitalError('held_financial_original_anchor_required')
        capture = anchor.capture
        if type(capture) is not _FinancialReplayCapture:
            raise CapitalError('held_financial_original_anchor_required')
        capture._check()
        if capture._phase != 'PUBLISHED' or capture._anchor is not anchor or capture._failure is not None:
            raise CapitalError('held_financial_anchor_unavailable')
        capture._phase, capture._anchor = 'TAKEN', None
        # Taking an issued anchor is one-shot even if its original caller
        # lease expires. A second call cannot renew that failed acquisition.
        check()
        self._capture = capture
        self._authority, self._db = anchor.authority, anchor.db
        self._owner = (os.getpid(), threading.get_ident())
        self._key, self._schema_version = anchor.key, anchor.schema_version
        self._apply = RuntimeCapital._apply
        self._reconcile = RuntimeCapital._reconcile
        self._failure = None
        self._cut = None
        self._retained = None
        self._view_cache = None
        self._state = json.loads(anchor.raw_state)
        self._sequence, self._anchor, self._state_hash = anchor.sequence, anchor.journal_hash, anchor.state_sha256
        self._identity = tuple(self._state[k] for k in ('epoch_id', 'inception_sha256')) + (digest(self._state['policy']),)
        # A detached original reducer needs no connection, locks or live flags.
        self._adapter = object.__new__(RuntimeCapital)
        self._adapter._replaying = True
        self._adapter._startup_replay_cancel = None
        self._adapter.fault = None
        with arithmetic():
            self._reconcile(self._adapter, self._state)
        # Build once on the creating thread; foreign status refusal must not
        # allocate/mutate an owner projection lazily.
        self._view_cache = self._project(self._state, check)
        self._bound()
        check()

    def __reduce__(self):
        raise TypeError('held_financial_prefix_is_process_private')

    def _bound(self):
        if (os.getpid(), threading.get_ident()) != self._owner:
            raise CapitalError('held_financial_foreign_owner')
        self._capture._check()
        if (self._authority.db is not self._db
                or self._authority._replay_prefix_key() != self._key
                or RuntimeCapital._apply is not self._apply
                or RuntimeCapital._reconcile is not self._reconcile):
            raise CapitalError('held_financial_binding_changed')

    def _schema_current(self):
        if _schema(self._db) != self._schema_version:
            raise CapitalError('held_financial_schema_changed')

    def _raise_retained(self):
        issue = self._retained or getattr(self._authority, '_held_financial_retained_read', None)
        if issue is not None:
            raise issue from issue.primary or issue.cleanup_error

    def cleanup_retained_read(self, *, deadline, cancelled):
        """Same creating owner only; resolve this handoff before authority reuse.

        Caller must not raw-COMMIT/BEGIN or otherwise reuse the borrowed owner
        while retained; SQLite cannot distinguish an unrelated replacement
        transaction.  Revoked provenance does not forbid this physical cleanup.
        """
        if (os.getpid(), threading.get_ident()) != self._owner:
            raise CapitalError('held_financial_foreign_cleanup_owner')
        check = _lease_check(deadline, cancelled)
        issue = self._retained
        if issue is None:
            raise CapitalError('held_financial_no_retained_read')
        try:
            deferred = cancelled() or time.monotonic() >= deadline
        except BaseException as exc:
            issue.latest_cleanup_error, issue.cleanup_state = exc, 'DEFERRED'
            self._raise_retained()
        if deferred:
            issue.cleanup_state = 'DEFERRED'
            self._raise_retained()
        if not self._authority._mutex.acquire(blocking=False):
            issue.cleanup_state = 'OWNER_BUSY'
            self._raise_retained()
        try:
            issue.cleanup_attempts += 1
            if self._db.in_transaction:
                _one(self._db, 'ROLLBACK')
            if self._db.in_transaction:
                raise CapitalError('held_financial_cleanup_still_active')
        except BaseException as exc:
            issue.latest_cleanup_error, issue.cleanup_state = exc, 'RETAINED'
            try:issue.transaction_active = self._db.in_transaction
            except Exception:issue.transaction_active = None
            self._raise_retained()
        finally:
            self._authority._mutex.release()
        issue.transaction_active, issue.cleanup_state = False, 'RELEASED'
        self._retained = None
        if getattr(self._authority, '_held_financial_retained_read', None) is issue:
            self._authority._held_financial_retained_read = None
        self._failure = issue
        # Physical release stays true even if the final response crosses the
        # original lease. No success/covered observation is issued by cleanup.
        try:
            return self._finish_current('UNKNOWN', 'RETAINED_READ_RELEASED', check, error=issue)
        except BaseException as exc:
            issue.latest_cleanup_error = exc
            raise exc from issue.primary or issue

    def _projection(self, state, state_hash):
        meta = _one(self._db, 'SELECT typeof(body),length(CAST(body AS BLOB)),'
                    'typeof(hash),length(CAST(hash AS BLOB)) FROM shared_capital_projection WHERE id=1')
        if (not meta or meta[0] != 'text' or type(meta[1]) is not int
                or not 0 < meta[1] <= _MAX_STATE_BYTES or meta[2:] != ('text', 64)):
            raise CapitalError('held_financial_projection_bound')
        raw, checksum = _one(self._db, 'SELECT body,hash FROM shared_capital_projection WHERE id=1')
        projection = json.loads(raw)
        if checksum != state_hash or digest(projection) != checksum or projection != state:
            raise CapitalError('replayed_projection_mismatch')

    @staticmethod
    def _project(state, check):
        def encoded(row):
            check()
            raw = canonical(row)
            check()
            return raw
        check()
        current, terminal, pending = [], [], []
        for key, row in sorted(state['positions'].items()):
            (current if row['status'] == 'OPEN' else terminal).append((key, encoded(row)))
        for kind, name in _PENDING:
            pending.extend((kind, key, encoded(row)) for key, row in sorted(state.get(name, {}).items()))
        pending.extend(('PENDING_DELIVERY', str(index), encoded(row))
                       for index, row in enumerate(state['pending_deliveries']))
        pending.extend(('GLOBAL_OPEN', key, body) for key, body in current)
        counts = []
        for kind in (*[item[0] for item in _PENDING], 'PENDING_DELIVERY', 'GLOBAL_OPEN'):
            check()
            counts.append((kind, sum(item[0] == kind for item in pending)))
        counts.append(('LEGACY_NATIVE_PENDING', 'UNESTABLISHED'))
        result = tuple(current), tuple(terminal), tuple(pending), tuple(counts)
        check()
        return result

    def _view(self, status, reason, rows=0, text_bytes=0, error=None, *, projection=None,
              snapshot=None, cut=None):
        current, terminal, pending, counts = self._view_cache if projection is None else projection
        sequence, anchor, state_hash = snapshot or (self._sequence, self._anchor, self._state_hash)
        cut = cut or self._cut or (sequence, anchor, state_hash)
        return _FinancialView(status, reason, self._capture._owner_sha, self._schema_version,
                              sequence, anchor, state_hash,
                              cut[0], cut[1], rows, text_bytes, current, terminal, pending, counts, error)

    def _finish_current(self, status, reason, check, *, error=None):
        """Old immutable facts only; refusal never publishes provisional work."""
        result = self._view(status, reason, error=error)
        try:
            check()
        except _Deferred as exc:
            return self._view('UNKNOWN' if error is not None else 'INCOMPLETE', str(exc), error=error)
        except Exception as exc:
            if error is None:self._failure = error = exc
            return self._view('UNKNOWN', 'RETURN_CHECK_FAILED', error=error)
        return result

    def _state_for_join(self, *, deadline, cancelled):
        """Owner-only detached state at the last covered prefix, not live proof.

        Retains original aliases, requests, cursors and delivery identity maps.
        The caller must pair this cut with advance's status and independently
        authenticate native owners; no supplied mapping grants that authority.
        """
        check = _lease_check(deadline, cancelled)
        check()
        self._bound()
        self._raise_retained()
        if self._failure is not None:
            raise CapitalError('held_financial_prefix_unknown') from self._failure
        result = self._sequence, self._anchor, self._state_hash, deepcopy(self._state)
        self._bound()
        check()
        return result

    def advance(self, *, deadline, cancelled, max_rows=_MAX_ROWS, max_bytes=_MAX_BYTES):
        """Replay at most one admitted indexed tail chunk on the owner connection.

        The caller supplies an absolute monotonic deadline.  Existing SQLite
        progress/authorizer handlers are never replaced.  We cannot preempt an
        executing original reducer; check the deadline before and after it and
        discard provisional work on expiry.  No exception settles native work.
        """
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or not callable(cancelled) or type(max_rows) is not int or not 1 <= max_rows <= _MAX_ROWS
                or type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_BYTES):
            raise ValueError('held_financial_advance_bounds')
        check = _lease_check(deadline, cancelled)
        if (os.getpid(), threading.get_ident()) != self._owner:
            # Fixed unavailable projection: no owned state/cache/DB/cap access.
            return _FOREIGN_OWNER_VIEW
        self._raise_retained()
        if self._failure is not None:
            return self._finish_current('UNKNOWN', 'LATCHED', check, error=self._failure)

        own_transaction = False
        locked = False
        rows, used = 0, 0
        candidate = None
        failure = None
        primary = None
        reason = 'TAIL_LIMIT'
        try:
            check()
            self._bound()
            locked = self._authority._mutex.acquire(blocking=False)
            if not locked:
                raise _Deferred('OWNER_BUSY')
            if self._db.in_transaction:
                raise _Deferred('OWNER_TRANSACTION_ACTIVE')
            # A failed execute may have toggled SQLite's transaction state.
            # Reserve cleanup responsibility before the attempt, after proving
            # that no original owner transaction was active under its mutex.
            own_transaction = True
            _one(self._db, 'BEGIN')
            self._schema_current()
            head = _head(self._db)
            if _head(self._db, self._sequence) != (self._sequence, self._anchor, self._state_hash):
                raise CapitalError('capital_journal_integrity')
            cut = self._cut or head
            if head[0] < cut[0] or _head(self._db, cut[0]) != cut:
                raise CapitalError('capital_journal_integrity')
            sql = ('SELECT sequence,' + ','.join('typeof(' + name + '),length(CAST(' + name + ' AS BLOB))'
                   for name in _TEXT_FIELDS) + ' FROM shared_capital_events'
                   ' WHERE sequence>? AND sequence<=? ORDER BY sequence LIMIT ?')
            cursor = self._db.execute(sql, (self._sequence, cut[0], max_rows))
            try:
                metadata = cursor.fetchall()  # At most 256 rows of scalar lengths/types.
            finally:
                cursor.close()
            admitted = []
            for meta in metadata:
                check()
                if meta[0] != self._sequence + len(admitted) + 1:
                    # An unavailable foreign sequence remains incomplete; a later
                    # largest head alone cannot certify this missing interval.
                    reason = 'MISSING_SEQUENCE'
                    break
                pairs = tuple(zip(meta[1::2], meta[2::2]))
                if any(kind != 'text' or type(size) is not int or size < 0 for kind, size in pairs):
                    raise CapitalError('capital_journal_integrity')
                widths = tuple(size for _, size in pairs)
                if not 1 <= widths[0] <= 240 or widths[3:] != (64, 64, 64):
                    raise CapitalError('capital_journal_integrity')
                size = sum(widths)
                if size > _MAX_BYTES:
                    raise CapitalError('held_financial_row_bound')
                if used + size > max_bytes:
                    reason = 'BYTE_LIMIT'
                    break
                admitted.append(meta[0])
                used += size
            candidate = deepcopy(self._state) if admitted else self._state
            sequence, anchor, state_hash = self._sequence, self._anchor, self._state_hash
            if admitted:
                cursor = self._db.execute('SELECT * FROM shared_capital_events'
                    ' WHERE sequence>? AND sequence<=? ORDER BY sequence LIMIT ?',
                    (sequence, admitted[-1], len(admitted)))
                try:
                    with arithmetic():
                        for seq, op, raw, result_raw, checksum, parent, record_hash in cursor:
                            check()
                            event, result = json.loads(raw), json.loads(result_raw)
                            expected = hashlib.sha256((parent + raw + result_raw + checksum).encode()).hexdigest()
                            if (seq != sequence + 1 or parent != anchor or record_hash != expected
                                    or type(event) is not dict or event.get('operation_id') != op):
                                raise CapitalError('capital_journal_integrity')
                            candidate, actual = self._apply(self._adapter, candidate, event)
                            raw_state = canonical(candidate)
                            if len(raw_state.encode()) > _MAX_STATE_BYTES:
                                raise CapitalError('held_financial_state_bound')
                            actual_hash = hashlib.sha256(raw_state.encode()).hexdigest()
                            if wire(actual) != result or actual_hash != checksum:
                                raise CapitalError('nondeterministic_capital_replay')
                            self._reconcile(self._adapter, candidate)
                            check()
                            sequence, anchor, state_hash = seq, record_hash, checksum
                            rows += 1
                finally:
                    cursor.close()
                if rows != len(admitted):
                    raise CapitalError('capital_journal_integrity')
            if sequence == cut[0]:
                if (sequence, anchor, state_hash) != cut:
                    raise CapitalError('capital_journal_integrity')
                if head == cut:
                    self._projection(candidate, state_hash)
                reason = 'CUT_COVERED' if head == cut else 'HEAD_ADVANCED'
            elif not metadata:
                reason = 'MISSING_SEQUENCE'
            identity = tuple(candidate[k] for k in ('epoch_id', 'inception_sha256')) + (digest(candidate['policy']),)
            if identity != self._identity:
                raise CapitalError('held_financial_identity_changed')
            self._bound()
            self._schema_current()
            check()
        except _Deferred as exc:
            candidate = None
            reason = str(exc)
            primary = exc
        except Exception as exc:
            candidate = None
            primary = failure = exc
        except BaseException as exc:
            primary = exc
            raise
        finally:
            try:
                if own_transaction:
                    cleanup_error = None
                    active = None
                    try:
                        if self._db.in_transaction:
                            _one(self._db, 'ROLLBACK')
                    except BaseException as exc:
                        cleanup_error = exc
                    try:active = self._db.in_transaction
                    except Exception as exc:cleanup_error = cleanup_error or exc
                    if cleanup_error is not None or active is not False:
                        issue = _RetainedFinancialRead(self, primary, cleanup_error, active)
                        self._retained = issue
                        self._authority._held_financial_retained_read = issue
                        raise issue from primary or cleanup_error
            finally:
                if locked:
                    self._authority._mutex.release()
        if failure is not None:
            self._failure = failure
            return self._finish_current('UNKNOWN', 'REPLAY_FAILED', check, error=failure)
        if candidate is None:
            return self._finish_current('INCOMPLETE', reason, check)
        # The original owner mutex protects only this connection.  Another
        # authorized writer may have committed beyond the fixed read snapshot.
        locked = False
        try:
            self._bound()
            check()
            locked = self._authority._mutex.acquire(blocking=False)
            if not locked:
                raise _Deferred('OWNER_BUSY')
            if self._db.in_transaction:
                raise _Deferred('OWNER_TRANSACTION_ACTIVE')
            self._schema_current()
            latest = _head(self._db)
            if latest[0] < cut[0] or latest[0] == cut[0] and latest != cut:
                raise CapitalError('capital_journal_integrity')
            self._bound()
            self._schema_current()
            check()
        except _Deferred as exc:
            return self._finish_current('INCOMPLETE', str(exc), check)
        except Exception as exc:
            self._failure = exc
            return self._finish_current('UNKNOWN', 'HEAD_CHECK_FAILED', check, error=exc)
        finally:
            if locked:
                self._authority._mutex.release()
        covered = sequence == cut[0]
        if covered and latest != cut:
            reason = 'HEAD_ADVANCED'
        try:
            projection = self._project(candidate, check) if rows else self._view_cache
            result = self._view('COVERED_CUT' if covered and latest == cut else 'INCOMPLETE',
                reason, rows, used, projection=projection,
                snapshot=(sequence, anchor, state_hash), cut=cut)
            self._bound()
            check()
        except _Deferred as exc:
            return self._finish_current('INCOMPLETE', str(exc), check)
        except Exception as exc:
            self._failure = exc
            return self._finish_current('UNKNOWN', 'PROJECTION_FAILED', check, error=exc)
        # All fallible projection/detach work precedes this original-lease
        # publication point. Expiry leaves the prior state/cursor/cache intact.
        self._state = candidate
        self._sequence, self._anchor, self._state_hash = sequence, anchor, state_hash
        self._view_cache = projection
        self._cut = None if covered else cut
        return result
