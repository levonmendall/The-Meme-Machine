"""Bounded, read-only source acquisition for one explicit Pump restoration.

The canonical view and each original reference/hash remain authoritative. SQL
snapshots capture bytes only; payload decoding and cold archive I/O happen after
rollback. This component publishes no history, coverage, acknowledgement or fact
about operational readiness.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import sqlite3
import threading
import time

from .journal import digest
from .sqlite_failure import connect, preserving_cleanup

PAGE_REFERENCES = 128
PAGE_BYTES = 32 * 1024 * 1024
PREPARED_BYTES = 4 * 1024 * 1024
REFERENCE_BYTES = 4 * 1024 * 1024
SNAPSHOT_SECONDS = .025


class _PageExpired(Exception):
    pass


class _ScopedChunkCache:
    """One page-wide byte allowance, with independent source membership."""
    def __init__(self, entries, path):
        self.entries, self.path = entries, path

    def __contains__(self, key): return (self.path, key) in self.entries
    def __getitem__(self, key):
        size, value = self.entries[self.path, key]
        return size, list(value)
    def __setitem__(self, key, value):
        size, decoded = value
        # Native logs are flat string lists. Other valid legacy JSON remains
        # uncached, preserving ordinary decoding without deepcopy's additional
        # recursion limit or mutable aliasing across two returned references.
        if type(decoded) is list and all(type(item) is str for item in decoded):
            self.entries[self.path, key] = size, list(decoded)
    def values(self): return self.entries.values()
    def clear(self):
        for key in tuple(self.entries):
            if key[0] == self.path: del self.entries[key]


@dataclass
class _Lookup:
    reader: object
    lane: str
    candidate: str
    identity: str
    kind: str
    ref: dict
    raw: object = None
    checksum: object = None
    path: object = None
    row: object = None
    manifest: object = None
    prepared: object = None
    chunks: dict = field(default_factory=dict)
    decoded_chunks: dict = field(default_factory=dict)
    fallback: bool = False

    def source(self, history, ref, path):
        self.reader._owned()
        if history is not self.reader.history or ref is not self.ref or self.path is not None and path != self.path:
            raise ValueError('candidate_restore_reference_owner')
        if self.fallback:
            db = self.reader._database(path)
            self.reader.check()
            return db.execute('SELECT body,hash,archive FROM canonical_evidence WHERE identity=?',
                (ref['canonical_identity'],)).fetchone(), db
        return self.row, None


class RestoreReferenceReader:
    def __init__(self, history, cancelled, archives):
        if not callable(cancelled):
            raise ValueError('candidate_history_startup_cancel_check')
        self.history = history
        self.cancelled = cancelled
        if type(archives) is not dict: raise ValueError('candidate_history_restore_archive_scope')
        self.archives = archives
        self.thread = threading.get_native_id()
        self.db = None
        self.path = None
        self.deadline = None
        self.closed = False

    def __enter__(self):
        self.check()
        return self

    def __exit__(self, kind, error, trace):
        with preserving_cleanup(): self.close()
        return False

    def _owned(self):
        if self.closed or threading.get_native_id() != self.thread:
            raise ValueError('candidate_restore_reference_owner')

    def check(self):
        self._owned()
        if self.cancelled():
            from .stop import Shutdown
            raise Shutdown()

    def _progress(self):
        return int(bool(self.cancelled()) or self.deadline is not None and time.monotonic() >= self.deadline)

    def _database(self, path):
        self.check()
        if self.path != path:
            self._close_database()
            self.db = connect(path.as_uri() + '?mode=ro', diagnostic_role='candidate_restore_reference',
                uri=True, timeout=30, isolation_level=None)
            self.path = path
            # This new, private connection owns its callback. Existing normal
            # readers and caller-owned progress handlers are never borrowed.
            self.db.set_progress_handler(self._progress, 1000)
        return self.db

    def _close_database(self):
        db, self.db, self.path = self.db, None, None
        if db is not None:
            db.set_progress_handler(None, 0)
            db.close()

    def close(self):
        if self.closed:
            return
        self._owned()
        try:
            self._close_database()
        finally:
            self.closed = True

    @contextmanager
    def _snapshot(self, db):
        self.check()
        if db.in_transaction:
            raise ValueError('candidate_restore_source_requires_idle_connection')
        self.deadline = time.monotonic() + SNAPSHOT_SECONDS
        try:
            db.execute('BEGIN')
            yield
            self.check()
        except sqlite3.OperationalError as error:
            self.check()
            if ((getattr(error, 'sqlite_errorcode', 0) & 255) == sqlite3.SQLITE_INTERRUPT
                    and self.deadline is not None and time.monotonic() >= self.deadline):
                raise _PageExpired() from error
            raise
        finally:
            # Cancellation/expiry cannot interrupt the owned rollback itself.
            self.deadline = None
            db.set_progress_handler(None, 0)
            try:
                with preserving_cleanup():
                    if db.in_transaction: db.execute('ROLLBACK')
            finally:
                db.set_progress_handler(self._progress, 1000)

    @staticmethod
    def _first(rows, expected=None):
        result = {}
        for row in rows:
            result.setdefault(row[0], row[1:])
            if expected is not None and len(result) == expected: break
        return result

    @staticmethod
    def _marks(keys):
        return ','.join('?' for _ in keys)

    def _source_rows(self, group, budget):
        path = self.history._reference_path(group[0].ref['path'])
        for item in group: item.path = path
        db = self._database(path)
        keys = tuple(dict.fromkeys(item.ref['canonical_identity'] for item in group))
        marks = self._marks(keys)
        with self._snapshot(db):
            metadata = self._first(db.execute('SELECT identity,length(CAST(body AS BLOB)),hash,archive '
                'FROM canonical_evidence WHERE identity IN (' + marks + ')', keys).fetchall())
            selected = []
            for key in keys:
                row = metadata.get(key)
                if row is not None and row[0] is not None and 0 <= row[0] <= budget:
                    selected.append(key); budget -= row[0]
            bodies = self._first(db.execute('SELECT identity,body,hash,archive FROM canonical_evidence '
                'WHERE identity IN (' + self._marks(selected) + ')', selected), len(selected)) if selected else {}
            archives = tuple(dict.fromkeys(row[2] for row in metadata.values() if row[0] is None))
            manifests = self._first(db.execute('SELECT id,path,hash FROM scoped_cold_manifests '
                'WHERE id IN (' + self._marks(archives) + ')', archives).fetchall()) if archives else {}
            for item in group:
                key = item.ref['canonical_identity']; meta = metadata.get(key)
                if meta is None: item.row = None
                elif meta[0] is None:
                    item.row = (None, meta[1], meta[2]); item.manifest = manifests.get(meta[2])
                elif key in bodies: item.row = bodies[key]
                else: item.fallback = True
        return budget

    def _prepare(self, lookups, budget):
        from meme_machine.solana_evidence_storage import prepare_decode
        prepared_bytes = 0
        for item in lookups:
            self.check()
            if item.fallback or item.row is None or item.row[0] is None:
                continue
            try:
                prepared = prepare_decode(item.row[0])
                if prepared_bytes + prepared.inflated_outer_bytes > PREPARED_BYTES:
                    self._fallback((item,))
                    continue
                # Each reference owns its mutable outer, including duplicates.
                item.prepared = prepared
                prepared_bytes += prepared.inflated_outer_bytes
            except Exception:
                # Rich parse exceptions can retain an inflated outer/doc and
                # bypass the successful-preparation byte allowance. Drop them
                # and reproduce the original scalar result/error at this ref's
                # turn. Shutdown is BaseException and propagates immediately.
                self._fallback((item,))
            finally:
                prepared = None
        groups = {}
        for item in lookups:
            if item.prepared is not None:
                groups.setdefault(item.path, []).append(item)
        decoded = {}
        for path, group in groups.items():
            self.check()
            try:
                keys = tuple(dict.fromkeys(checksum for item in group for _, _, checksum in item.prepared.references))
            except (TypeError, ValueError):
                # Preserve original per-reference error precedence. Unusual
                # marker values are evaluated only by the scalar decoder.
                self._fallback(group)
                continue
            if not keys: continue
            try:
                db = self._database(path)
                with self._snapshot(db):
                    sizes = dict(db.execute('SELECT hash,length(body) FROM hot_chunks WHERE hash IN (' +
                        self._marks(keys) + ')', keys))
                    selected = []
                    for key in keys:
                        size = sizes.get(key)
                        if type(size) is int and 0 <= size <= budget:
                            selected.append(key); budget -= size
                    chunks = dict(db.execute('SELECT hash,body FROM hot_chunks WHERE hash IN (' +
                        self._marks(selected) + ')', selected)) if selected else {}
                scoped_decoded = _ScopedChunkCache(decoded, path)
                for item in group:
                    # A genuinely absent chunk remains absent, so finish_decode
                    # raises the original missing-chunk failure in ref order.
                    if any(key in sizes and key not in chunks for _, _, key in item.prepared.references):
                        self._fallback((item,))
                    else:
                        item.chunks = chunks; item.decoded_chunks = scoped_decoded
            except _PageExpired:
                self._fallback(group)
            except (sqlite3.Error, OSError):
                self._fallback(group)
        return budget

    @staticmethod
    def _fallback(items):
        for item in items:
            item.fallback = True
            item.row = item.manifest = item.prepared = None
            # Release speculative buffers without touching another reference's
            # shared compressed/decoded chunk dictionaries.
            item.chunks = {}; item.decoded_chunks = {}

    @staticmethod
    def _reference_bytes(raw):
        if isinstance(raw, str):
            if len(raw) > REFERENCE_BYTES: return len(raw)
            return len(raw) if raw.isascii() else len(raw.encode('utf-8', 'surrogatepass'))
        return len(raw) if isinstance(raw, (bytes, bytearray)) else 0

    def rows(self, lane, candidate, rows):
        """Yield original-order records; only SQL acquisition is grouped."""
        self.check()
        iterator = iter(rows)
        pending = None
        while True:
            lookups = []; reference_bytes = 0
            for _ in range(PAGE_REFERENCES):
                self.check()
                try: row = next(iterator) if pending is None else pending
                except StopIteration: break
                pending = None
                identity, kind, raw, checksum = row
                size = self._reference_bytes(raw)
                if lookups and reference_bytes + size > REFERENCE_BYTES:
                    pending = row
                    break
                item = _Lookup(self, lane, candidate, identity, kind, None, raw, checksum)
                reference_bytes += size
                if size > REFERENCE_BYTES:
                    item.fallback = True
                else:
                    try:
                        ref = json.loads(raw)
                        if digest(ref) != checksum: raise ValueError('candidate_history_corruption')
                        item.ref = ref
                    except Exception:
                        # Reparse at its original turn, with no retained JSON
                        # document/traceback or speculative error precedence.
                        item.fallback = True
                lookups.append(item)
                if size > REFERENCE_BYTES: break
            if not lookups: return
            try:
                groups = {}
                for item in lookups:
                    if item.fallback: continue
                    try:
                        path = item.ref['path']; key = item.ref['canonical_identity']
                        if type(path) is not str or type(key) is not str:
                            item.path = self.history._reference_path(path); item.fallback = True
                        else: groups.setdefault(path, []).append(item)
                    except (ValueError, TypeError, KeyError): item.fallback = True
                budget = PAGE_BYTES
                for group in groups.values():
                    try: budget = self._source_rows(group, budget)
                    except _PageExpired:
                        self._fallback(group)
                    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
                        self._fallback(group)
                self._prepare(lookups, budget)
                for item in lookups:
                    self.check()
                    if item.ref is None:
                        item.ref = json.loads(item.raw)
                        if digest(item.ref) != item.checksum: raise ValueError('candidate_history_corruption')
                    record = self.history._reference_body(lane, candidate, item.identity, item.kind,
                        item.ref, _archive_cache=self.archives, _check=self.check, _restore_lookup=item)
                    # finish_decode mutates this owned outer. Release it before
                    # yielding so decoded chunks exceeding the cache allowance
                    # cannot accumulate in consumed lookups as extra copies of
                    # the original output ownership. Do not clear shared maps.
                    item.row = item.manifest = item.prepared = item.raw = item.ref = None
                    item.chunks = {}; item.decoded_chunks = {}
                    yield record
            finally:
                for item in lookups:
                    item.row = item.manifest = item.prepared = item.raw = None
                    item.chunks.clear(); item.decoded_chunks.clear()
                groups.clear()
                lookups.clear()


def require_reader(value, history):
    if type(value) is not RestoreReferenceReader or value.history is not history:
        raise ValueError('candidate_restore_reference_owner')
    value.check()
    return value
