"""Dormant, private observation of an already-replayed shared financial journal.

This is not a boot, owner, protection, readiness or funding capability.  The
caller must construct it at the authentic owner replay seam.  RuntimeCapital
does not record its constructing thread; this helper binds only *its own*
creating PID/thread.  A covered journal cut is not live all-writer completeness.
No runtime imports or installs this helper by default.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
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


class _Deferred(Exception):
    pass


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
    def __init__(self, authority, state, replay_proof):
        if type(authority) is not RuntimeCapital or type(authority.db) is not sqlite3.Connection:
            raise CapitalError('held_financial_original_authority_required')
        self._authority, self._db = authority, authority.db
        self._owner = (os.getpid(), threading.get_ident())
        self._key = authority._replay_prefix_key()
        self._apply = RuntimeCapital._apply
        self._reconcile = RuntimeCapital._reconcile
        if self._key is None or self._key[-2:] != (self._apply, self._reconcile):
            raise CapitalError('held_financial_original_reducer_required')
        self._failure = None
        self._cut = None
        # This cache is populated only by the original successful verifier.
        # Do not call _authenticated_replay_prefix: that scans the whole journal.
        if not original._REPLAY_PREFIX_LOCK.acquire(blocking=False):
            raise CapitalError('held_financial_initial_replay_unavailable')
        try:
            cached = original._REPLAY_PREFIXES.get(self._key)
        finally:
            original._REPLAY_PREFIX_LOCK.release()
        if cached is None:
            raise CapitalError('held_financial_initial_replay_unavailable')
        sequence, anchor, state_hash, raw_state = cached
        expected = dict(events=sequence, journal_hash=anchor, state_sha256=state_hash, conservation=True)
        if (type(replay_proof) is not dict or replay_proof != expected
                or type(state) is not dict or canonical(state) != raw_state
                or hashlib.sha256(raw_state.encode()).hexdigest() != state_hash):
            raise CapitalError('held_financial_initial_replay_mismatch')
        self._state = json.loads(raw_state)
        self._sequence, self._anchor, self._state_hash = sequence, anchor, state_hash
        self._identity = tuple(self._state[k] for k in ('epoch_id', 'inception_sha256')) + (digest(self._state['policy']),)
        # A detached original reducer needs no connection, locks or live flags.
        self._adapter = object.__new__(RuntimeCapital)
        self._adapter._replaying = True
        self._adapter._startup_replay_cancel = None
        self._adapter.fault = None
        with arithmetic():
            self._reconcile(self._adapter, self._state)
        if not authority._mutex.acquire(blocking=False):
            raise CapitalError('held_financial_owner_busy')
        own_transaction = False
        try:
            self._bound()
            if self._db.in_transaction:
                raise CapitalError('held_financial_owner_transaction_active')
            _one(self._db, 'BEGIN')
            own_transaction = True
            if _head(self._db) != (sequence, anchor, state_hash):
                raise CapitalError('held_financial_initial_head_changed')
            self._projection(self._state, state_hash)
            self._bound()
        finally:
            try:
                if own_transaction and self._db.in_transaction:
                    from meme_machine.runtime.sqlite_failure import preserving_cleanup
                    with preserving_cleanup():
                        _one(self._db, 'ROLLBACK')
            finally:
                authority._mutex.release()

    def _bound(self):
        if (os.getpid(), threading.get_ident()) != self._owner:
            raise CapitalError('held_financial_foreign_owner')
        if (self._authority.db is not self._db
                or self._authority._replay_prefix_key() != self._key
                or RuntimeCapital._apply is not self._apply
                or RuntimeCapital._reconcile is not self._reconcile):
            raise CapitalError('held_financial_binding_changed')

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

    def _view(self, status, reason, rows=0, text_bytes=0, error=None):
        state = self._state
        current, terminal, pending = [], [], []
        for key, row in sorted(state['positions'].items()):
            (current if row['status'] == 'OPEN' else terminal).append((key, canonical(row)))
        for kind, name in _PENDING:
            pending.extend((kind, key, canonical(row)) for key, row in sorted(state.get(name, {}).items()))
        # Keep original delivery bodies/order and their original identities.
        pending.extend(('PENDING_DELIVERY', str(index), canonical(row))
                       for index, row in enumerate(state['pending_deliveries']))
        pending.extend(('GLOBAL_OPEN', key, body) for key, body in current)
        counts = tuple((kind, sum(item[0] == kind for item in pending))
                       for kind in (*[item[0] for item in _PENDING], 'PENDING_DELIVERY', 'GLOBAL_OPEN'))
        # This selected shared journal cannot establish the separate legacy
        # native pending population.  Never encode its absence as zero.
        counts += (('LEGACY_NATIVE_PENDING', 'UNESTABLISHED'),)
        cut = self._cut or (self._sequence, self._anchor, self._state_hash)
        return _FinancialView(status, reason, self._sequence, self._anchor, self._state_hash,
                              cut[0], cut[1], rows, text_bytes, tuple(current), tuple(terminal),
                              tuple(pending), counts, error)

    def _state_for_join(self):
        """Owner-only detached state at the last covered prefix, not live proof.

        Retains original aliases, requests, cursors and delivery identity maps.
        The caller must pair this cut with advance's status and independently
        authenticate native owners; no supplied mapping grants that authority.
        """
        self._bound()
        if self._failure is not None:
            raise CapitalError('held_financial_prefix_unknown') from self._failure
        return self._sequence, self._anchor, self._state_hash, deepcopy(self._state)

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
        if (os.getpid(), threading.get_ident()) != self._owner:
            # Do not touch the connection or mutate owner state from a foreign thread.
            return self._view('UNKNOWN', 'FOREIGN_OWNER')
        if self._failure is not None:
            return self._view('UNKNOWN', 'LATCHED', error=self._failure)

        def check():
            if cancelled():
                raise _Deferred('CANCELLED')
            if time.monotonic() >= deadline:
                raise _Deferred('DEADLINE')

        own_transaction = False
        locked = False
        rows, used = 0, 0
        candidate = None
        failure = None
        reason = 'TAIL_LIMIT'
        try:
            check()
            self._bound()
            locked = self._authority._mutex.acquire(blocking=False)
            if not locked:
                raise _Deferred('OWNER_BUSY')
            if self._db.in_transaction:
                raise _Deferred('OWNER_TRANSACTION_ACTIVE')
            _one(self._db, 'BEGIN')
            own_transaction = True
            head = _head(self._db)
            if _head(self._db, self._sequence) != (self._sequence, self._anchor, self._state_hash):
                raise CapitalError('capital_journal_integrity')
            if self._cut is None:
                self._cut = head
            cut = self._cut
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
            candidate = deepcopy(self._state)
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
            check()
        except _Deferred as exc:
            candidate = None
            reason = str(exc)
        except Exception as exc:
            candidate = None
            failure = exc
        finally:
            try:
                if own_transaction and self._db.in_transaction:
                    try:
                        _one(self._db, 'ROLLBACK')
                    except Exception as exc:
                        candidate = None
                        failure = failure or exc
            finally:
                if locked:
                    self._authority._mutex.release()
        if failure is not None:
            self._failure = failure
            return self._view('UNKNOWN', 'REPLAY_FAILED', error=failure)
        if candidate is None:
            return self._view('INCOMPLETE', reason)
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
            latest = _head(self._db)
            if latest[0] < cut[0] or latest[0] == cut[0] and latest != cut:
                raise CapitalError('capital_journal_integrity')
            self._bound()
            check()
        except _Deferred as exc:
            return self._view('INCOMPLETE', str(exc))
        except Exception as exc:
            self._failure = exc
            return self._view('UNKNOWN', 'HEAD_CHECK_FAILED', error=exc)
        finally:
            if locked:
                self._authority._mutex.release()
        self._state = candidate
        self._sequence, self._anchor, self._state_hash = sequence, anchor, state_hash
        covered = sequence == cut[0]
        if covered and latest != cut:
            reason = 'HEAD_ADVANCED'
        result = self._view('COVERED_CUT' if covered and latest == cut else 'INCOMPLETE',
                            reason, rows, used)
        if covered:
            self._cut = None
        return result
