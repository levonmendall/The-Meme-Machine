"""Transactional finalized evidence, independent of strategy/lifecycle authority.

No network access, signing, economic policy, or implicit coverage inference lives
here. A transport adapter must submit verified interval proofs explicitly. A
connected socket, highest observed slot, or elapsed wall time is NOT such a proof.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import queue
import sqlite3
import threading
import time
import uuid


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class EvidenceUnavailable(ValueError):
    pass


class EvidenceConflict(EvidenceUnavailable):
    pass


@dataclass(frozen=True)
class FinalizedRecord:
    identity: str
    scope: str
    slot: int
    signature: str
    program: str
    addresses: tuple[str, ...]
    market_time: int | None
    payload: dict
    source: str
    endpoint_identity: str
    observed_at: float
    event_index: int = 0
    transaction_index: int | None = None
    kind: str = 'event'

    def body(self):
        if (not all((self.identity, self.scope, self.program))
                or self.kind != 'account' and not self.signature
                or type(self.slot) is not int or self.slot < 0
                or type(self.event_index) is not int or self.event_index < 0
                or self.kind not in ('event', 'transaction', 'account')
                or self.source not in ('alchemy_finalized_stream', 'alchemy_finalized_repair')
                or len(self.endpoint_identity) != 64
                or any(c not in '0123456789abcdef' for c in self.endpoint_identity)
                or not isinstance(self.payload, dict)
                or not self.addresses or any(not isinstance(a, str) or not a for a in self.addresses)
                or self.observed_at <= 0
                or self.market_time is not None and
                    (type(self.market_time) is not int or self.market_time > self.observed_at)
                or self.transaction_index is not None and
                    (type(self.transaction_index) is not int or self.transaction_index < 0)):
            raise EvidenceUnavailable('invalid_finalized_record')
        # Observation/source are lineage, not immutable economic content. A repair
        # can confirm the same record without changing its first availability.
        return dict(identity=self.identity, scope=self.scope, slot=self.slot,
                    signature=self.signature, program=self.program,
                    addresses=sorted(set(self.addresses)), market_time=self.market_time,
                    event_index=self.event_index, transaction_index=self.transaction_index,
                    kind=self.kind, payload=self.payload)


@dataclass(frozen=True)
class IntervalProof:
    scope: str
    lower_slot: int
    upper_slot: int
    source: str
    endpoint_identity: str
    witness: dict
    observed_at: float

    def validate(self):
        if (not self.scope or type(self.lower_slot) is not int or self.lower_slot < 0
                or type(self.upper_slot) is not int or self.upper_slot < self.lower_slot
                or self.source not in ('alchemy_finalized_stream', 'alchemy_finalized_repair')
                or len(self.endpoint_identity) != 64
                or any(c not in '0123456789abcdef' for c in self.endpoint_identity)
                or not isinstance(self.witness, dict) or self.observed_at <= 0):
            raise EvidenceUnavailable('invalid_interval_proof')
        # Caller supplies a completed source census, never just a transport ACK.
        if (self.witness.get('finalized') is not True
                or self.witness.get('complete') is not True
                or self.witness.get('scope') != self.scope
                or self.witness.get('lower_slot') != self.lower_slot
                or self.witness.get('upper_slot') != self.upper_slot
                or not self.witness.get('lineage_hash')):
            raise EvidenceUnavailable('incomplete_interval_proof')


SCHEMA = '''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS records(
 identity TEXT PRIMARY KEY,scope TEXT NOT NULL,slot INTEGER NOT NULL,
 signature TEXT NOT NULL,program TEXT NOT NULL,market_time INTEGER,event_index INTEGER NOT NULL,
 transaction_index INTEGER,kind TEXT NOT NULL,body TEXT,hash TEXT NOT NULL,
 first_seen REAL NOT NULL,archive TEXT);
CREATE INDEX IF NOT EXISTS records_scope_slot ON records(scope,slot,event_index);
CREATE INDEX IF NOT EXISTS records_scope_time ON records(scope,market_time,slot,event_index);
CREATE INDEX IF NOT EXISTS records_signature ON records(signature);
CREATE TABLE IF NOT EXISTS addresses(
 address TEXT NOT NULL,identity TEXT NOT NULL REFERENCES records(identity),slot INTEGER NOT NULL,
 PRIMARY KEY(address,identity));
CREATE INDEX IF NOT EXISTS address_window ON addresses(address,slot);
CREATE TABLE IF NOT EXISTS lineage(
 identity TEXT NOT NULL REFERENCES records(identity),source TEXT NOT NULL,
 endpoint TEXT NOT NULL,observed REAL NOT NULL,PRIMARY KEY(identity,source,endpoint));
CREATE TABLE IF NOT EXISTS cursors(scope TEXT PRIMARY KEY,slot INTEGER NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS coverage(
 id INTEGER PRIMARY KEY,scope TEXT NOT NULL,lo INTEGER NOT NULL,hi INTEGER NOT NULL,
 available REAL NOT NULL,proof TEXT NOT NULL,UNIQUE(scope,lo,hi,proof));
CREATE INDEX IF NOT EXISTS coverage_window ON coverage(scope,lo,hi);
CREATE TABLE IF NOT EXISTS gaps(
 id INTEGER PRIMARY KEY,scope TEXT NOT NULL,lo INTEGER NOT NULL,hi INTEGER,
 reason TEXT NOT NULL,created REAL NOT NULL,repaired REAL,
 repair_cursor TEXT,pages INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS gap_window ON gaps(scope,lo,hi,repaired);
CREATE TABLE IF NOT EXISTS interests(
 owner TEXT NOT NULL,scope TEXT NOT NULL,priority INTEGER NOT NULL,
 lower_slot INTEGER NOT NULL,lifecycle TEXT NOT NULL,active INTEGER NOT NULL,
 updated REAL NOT NULL,PRIMARY KEY(owner,scope));
CREATE TABLE IF NOT EXISTS consumers(
 owner TEXT PRIMARY KEY,scope TEXT NOT NULL,slot INTEGER NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS conflicts(
 id INTEGER PRIMARY KEY,identity TEXT NOT NULL,prior TEXT NOT NULL,
 incoming TEXT NOT NULL,observed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS archives(
 name TEXT PRIMARY KEY,hash TEXT NOT NULL,bytes INTEGER NOT NULL,records INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS counters(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
'''


class EvidenceWriter:
    """One process/thread owns all evidence mutations; consumers open read-only DBs."""
    def __init__(self, path, *, clock=time.time, max_hot_bytes=256 * 1024 * 1024):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        if type(max_hot_bytes) is not int or max_hot_bytes < 1024 * 1024:
            raise EvidenceUnavailable('hot_store_capacity_bound')
        self.max_hot_bytes = max_hot_bytes
        self._owner = threading.get_ident()
        self._lock = open(str(self.path) + '.writer.lock', 'a+b')
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise EvidenceUnavailable('evidence_writer_already_running') from None
        try:
            self.db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.executescript(SCHEMA)
            with self.transaction():
                initialized = self.db.execute("SELECT value FROM meta WHERE key='initialized'").fetchone()
                if initialized:
                    self._count('restarts')
                    # Last cursor is durable, but proves nothing after a crash.
                    for scope, slot in self.db.execute('SELECT scope,slot FROM cursors').fetchall():
                        self._gap(scope, slot + 1, None, 'writer_restart')
                self.db.execute("INSERT OR IGNORE INTO meta VALUES('initialized','1')")
        except BaseException:
            if hasattr(self, 'db'):
                self.db.close()
            self._lock.close()
            raise

    def _check(self):
        if threading.get_ident() != self._owner:
            raise EvidenceUnavailable('writer_thread_violation')

    @contextmanager
    def transaction(self):
        self._check()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _count(self, key, count=1):
        self.db.execute('INSERT INTO counters VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=value+excluded.value', (key, count))

    def _gap(self, scope, lo, hi, reason):
        if not self.db.execute('SELECT 1 FROM gaps WHERE scope=? AND lo=? AND hi IS ? AND repaired IS NULL', (scope, lo, hi)).fetchone():
            self.db.execute('INSERT INTO gaps(scope,lo,hi,reason,created) VALUES(?,?,?,?,?)', (scope, lo, hi, reason, self.clock()))
            self._count('gaps_created')

    def gap(self, scope, lo, hi=None, reason='stream_discontinuity'):
        if type(lo) is not int or lo < 0 or hi is not None and (type(hi) is not int or hi < lo):
            raise EvidenceUnavailable('invalid_gap')
        with self.transaction():
            self._gap(scope, lo, hi, reason)

    def reconnect(self, scope, lower_slot):
        """Close the missing range at an authenticated new subscription boundary.

        This never repairs the gap or grants coverage for the new stream.
        """
        with self.transaction():
            rows = self.db.execute('SELECT id,lo FROM gaps WHERE scope=? AND hi IS NULL AND repaired IS NULL', (scope,)).fetchall()
            for identity, lo in rows:
                if lower_slot < lo:
                    raise EvidenceUnavailable('reconnect_cursor_regression')
                self.db.execute('UPDATE gaps SET hi=? WHERE id=?', (max(lo, lower_slot), identity))

    def ingest(self, records, *, proof=None, repair_receipt=None):
        records = tuple(records)
        if len(records) > 2048:
            raise EvidenceUnavailable('ingestion_batch_bound')
        bodies = [(record, record.body()) for record in records]
        if sum(len(canonical(body).encode()) for _, body in bodies) > 16 * 1024 * 1024:
            raise EvidenceUnavailable('ingestion_payload_bound')
        hot_bytes=sum(p.stat().st_size for p in (self.path,Path(str(self.path)+'-wal')) if p.exists())
        if hot_bytes >= self.max_hot_bytes:
            with self.transaction():
                for scope,slot in self.db.execute('SELECT scope,slot FROM cursors').fetchall():
                    self._gap(scope,slot+1,None,'hot_store_capacity')
                self._count('capacity_stops')
            raise EvidenceUnavailable('hot_store_capacity')
        if proof:
            proof.validate()
        conflict = None
        with self.transaction():
            if self.db.execute("SELECT value FROM meta WHERE key='poisoned'").fetchone():
                raise EvidenceConflict('evidence_store_poisoned')
            # Check the entire batch before persisting any of it.
            staged = {}
            for record, body in bodies:
                checksum = digest(body)
                old = self.db.execute('SELECT hash FROM records WHERE identity=?', (record.identity,)).fetchone()
                previous = old[0] if old else staged.get(record.identity)
                if previous and previous != checksum:
                    conflict = (record.identity, previous, checksum)
                    break
                staged[record.identity] = checksum
            if conflict:
                self.db.execute('INSERT INTO conflicts(identity,prior,incoming,observed) VALUES(?,?,?,?)', (*conflict, self.clock()))
                self.db.execute("INSERT OR REPLACE INTO meta VALUES('poisoned','1')")
                self._count('evidence_conflicts')
            else:
                for record, body in bodies:
                    inserted = self.db.execute('INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)',
                        (record.identity, record.scope, record.slot, record.signature, record.program,
                         record.market_time, record.event_index, record.transaction_index, record.kind,
                         canonical(body), digest(body), record.observed_at)).rowcount
                    self.db.executemany('INSERT OR IGNORE INTO addresses VALUES(?,?,?)',
                        [(address, record.identity, record.slot) for address in body['addresses']])
                    self.db.execute('INSERT OR IGNORE INTO lineage VALUES(?,?,?,?)',
                        (record.identity, record.source, record.endpoint_identity, record.observed_at))
                    self.db.execute('INSERT INTO cursors VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET slot=MAX(slot,excluded.slot),updated=excluded.updated',
                        (record.scope, record.slot, self.clock()))
                    if inserted:
                        self._count('ingested_' + record.kind)
                if repair_receipt:
                    gap_id, cursor, max_pages = repair_receipt
                    self._repair_progress(gap_id, cursor, max_pages)
                if proof:
                    self._coverage(proof)
        if conflict:
            raise EvidenceConflict('conflicting_immutable_evidence:' + conflict[0])

    def _coverage(self, proof):
        self.db.execute('INSERT OR IGNORE INTO coverage(scope,lo,hi,available,proof) VALUES(?,?,?,?,?)',
            (proof.scope, proof.lower_slot, proof.upper_slot, proof.observed_at,
             canonical(dict(source=proof.source, endpoint_identity=proof.endpoint_identity, witness=proof.witness))))
        self.db.execute('INSERT INTO cursors VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET slot=MAX(slot,excluded.slot),updated=excluded.updated',
            (proof.scope, proof.upper_slot, self.clock()))
        # A streaming resumption never retrospectively repairs missing history.
        if proof.source == 'alchemy_finalized_repair':
            n = self.db.execute('UPDATE gaps SET repaired=? WHERE scope=? AND lo>=? AND hi<=? AND repaired IS NULL',
                (proof.observed_at, proof.scope, proof.lower_slot, proof.upper_slot)).rowcount
            self._count('gaps_repaired', n)

    def interest(self, owner, scope, *, lower_slot, priority=4, lifecycle='candidate'):
        if (not owner or not scope or type(lower_slot) is not int or lower_slot < 0
                or priority not in range(5) or lifecycle not in ('candidate', 'reserved', 'open', 'research')):
            raise EvidenceUnavailable('invalid_interest')
        if lifecycle == 'open' and priority != 0 or lifecycle == 'reserved' and priority > 1:
            raise EvidenceUnavailable('lifecycle_evidence_priority')
        with self.transaction():
            self.db.execute('INSERT INTO interests VALUES(?,?,?,?,?,1,?) ON CONFLICT(owner,scope) DO UPDATE SET priority=excluded.priority,lower_slot=MIN(lower_slot,excluded.lower_slot),lifecycle=excluded.lifecycle,active=1,updated=excluded.updated',
                (owner, scope, priority, lower_slot, lifecycle, self.clock()))

    def release(self, owner, scope, *, lifecycle_resolved=False):
        with self.transaction():
            row = self.db.execute('SELECT lifecycle FROM interests WHERE owner=? AND scope=? AND active=1', (owner, scope)).fetchone()
            if row and row[0] in ('open', 'reserved') and not lifecycle_resolved:
                raise EvidenceUnavailable('unresolved_lifecycle_interest')
            self.db.execute('UPDATE interests SET active=0,updated=? WHERE owner=? AND scope=?', (self.clock(), owner, scope))

    def acknowledge(self, owner, scope, slot):
        with self.transaction():
            prior = self.db.execute('SELECT scope,slot FROM consumers WHERE owner=?', (owner,)).fetchone()
            if prior and (scope != prior[0] or slot < prior[1]):
                raise EvidenceUnavailable('consumer_cursor_regression')
            self.db.execute('INSERT OR REPLACE INTO consumers VALUES(?,?,?,?)', (owner, scope, slot, self.clock()))

    def repair_progress(self, gap_id, *, cursor, max_pages=16):
        """Bounded durable page receipt. A page alone never grants coverage."""
        with self.transaction():
            self._repair_progress(gap_id, cursor, max_pages)

    def _repair_progress(self, gap_id, cursor, max_pages):
        row = self.db.execute('SELECT pages,repaired FROM gaps WHERE id=?', (gap_id,)).fetchone()
        if not row or row[1] is not None or row[0] >= max_pages:
            raise EvidenceUnavailable('repair_page_budget_or_state')
        self.db.execute('UPDATE gaps SET pages=pages+1,attempts=attempts+1,repair_cursor=? WHERE id=?', (canonical(cursor), gap_id))
        self._count('gap_repair_calls')

    def archive(self, before_time, *, max_records=1000):
        """Bounded, crash-safe compression; immutable hash tombstones stay indexed.

        Keep every record at/after an unresolved interest's lower slot. Delete only
        hot payloads after the compressed archive is durable. Orphan archives after
        interruption are harmless, content-addressed, and reusable on retry.
        """
        self._check()
        if not 1 <= max_records <= 1000:
            raise EvidenceUnavailable('archive_batch_bound')
        rows = self.db.execute('''SELECT r.identity,r.body,r.hash FROM records r
          WHERE r.body IS NOT NULL AND r.market_time < ?
          AND NOT EXISTS(SELECT 1 FROM interests i WHERE i.active=1
             AND i.scope=r.scope AND r.slot>=i.lower_slot)
          ORDER BY r.market_time,r.identity LIMIT ?''', (before_time, max_records)).fetchall()
        if not rows:
            return 0
        raw = ('\n'.join(canonical(dict(identity=k, body=json.loads(b), hash=h)) for k, b, h in rows) + '\n').encode()
        compressed = gzip.compress(raw, mtime=0)
        checksum = hashlib.sha256(compressed).hexdigest()
        directory = self.path.parent / (self.path.name + '.archive')
        directory.mkdir(exist_ok=True)
        target = directory / (checksum + '.jsonl.gz')
        publish_bytes(target, compressed)
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO archives VALUES(?,?,?,?)', (target.name, checksum, len(compressed), len(rows)))
            self.db.executemany('UPDATE records SET body=NULL,archive=? WHERE identity=? AND hash=?', [(target.name, k, h) for k, _, h in rows])
            self._count('archived_records', len(rows))
        return len(rows)

    def close(self):
        self._check()
        self.db.close()
        self._lock.close()


class EvidenceReader:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.queries = 0
        self.db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True,
                                  isolation_level=None, timeout=2)
        self.db.execute('PRAGMA query_only=ON')

    def _healthy(self):
        if self.db.execute("SELECT 1 FROM meta WHERE key='poisoned'").fetchone():
            raise EvidenceConflict('evidence_store_poisoned')

    def covered(self, scope, lower_slot, upper_slot, *, as_of):
        self._healthy()
        if lower_slot < 0 or upper_slot < lower_slot:
            raise EvidenceUnavailable('invalid_query_window')
        # A later repair cannot rewrite a prospective decision's original cutoff.
        if self.db.execute('''SELECT 1 FROM gaps WHERE scope=? AND lo<=?
            AND (hi IS NULL OR hi>=?) AND created<=? AND (repaired IS NULL OR repaired>?) LIMIT 1''',
            (scope, upper_slot, lower_slot, as_of, as_of)).fetchone():
            return False
        cursor = lower_slot
        for lo, hi in self.db.execute('SELECT lo,hi FROM coverage WHERE scope=? AND available<=? AND hi>=? AND lo<=? ORDER BY lo,hi',
                                     (scope, as_of, lower_slot, upper_slot)):
            if lo > cursor:
                return False
            cursor = max(cursor, hi + 1)
            if cursor > upper_slot:
                return True
        return False

    def window(self, scope, lower_slot, upper_slot, *, as_of, address=None, kind=None, limit=2048):
        if not 1 <= limit <= 10000:
            raise EvidenceUnavailable('query_bound')
        self.queries += 1
        self.db.execute('BEGIN')
        try:
            if not self.covered(scope, lower_slot, upper_slot, as_of=as_of):
                raise EvidenceUnavailable('unresolved_evidence_gap')
            sql = 'SELECT r.body,r.archive,r.identity,r.hash FROM records r '
            params = []
            if address:
                sql += 'JOIN addresses a ON a.identity=r.identity AND a.address=? '
                params.append(address)
            sql += 'WHERE r.scope=? AND r.slot BETWEEN ? AND ? AND r.first_seen<=? '
            params.extend((scope, lower_slot, upper_slot, as_of))
            if kind:
                sql += 'AND r.kind=? '
                params.append(kind)
            sql += 'ORDER BY r.slot,r.transaction_index,r.event_index,r.identity LIMIT ?'
            rows = self.db.execute(sql, (*params, limit + 1)).fetchall()
            if len(rows) > limit:
                raise EvidenceUnavailable('local_evidence_query_bound')
            result = []
            for body, archive, identity, checksum in rows:
                if body is None:
                    # Normal hot decisions never perform archive I/O implicitly.
                    raise EvidenceUnavailable('evidence_requires_offline_archive_restore')
                parsed = json.loads(body)
                if digest(parsed) != checksum:
                    raise EvidenceConflict('local_evidence_hash_mismatch:' + identity)
                result.append(parsed)
            return result
        finally:
            self.db.execute('ROLLBACK')

    def telemetry(self):
        self._healthy()
        return dict(cursors=[dict(scope=s, slot=n, updated=t) for s, n, t in self.db.execute('SELECT * FROM cursors')],
            coverage_windows=self.db.execute('SELECT COUNT(*) FROM coverage').fetchone()[0],
            unresolved_gaps=self.db.execute('SELECT COUNT(*) FROM gaps WHERE repaired IS NULL').fetchone()[0],
            consumer_lag=[dict(owner=o, scope=s, slots=max(0, top-n), updated=t) for o,s,n,t,top in self.db.execute('SELECT c.owner,c.scope,c.slot,c.updated,r.slot FROM consumers c JOIN cursors r ON c.scope=r.scope')],
            counters=dict(self.db.execute('SELECT * FROM counters')), local_queries=self.queries,
            hot_bytes=sum(p.stat().st_size for p in (self.path, Path(str(self.path)+'-wal')) if p.exists()),
            archive_bytes=self.db.execute('SELECT COALESCE(SUM(bytes),0) FROM archives').fetchone()[0])

    def close(self):
        self.db.close()


from .durable_publication import publish_bytes, publish_json


class IngestionService:
    """Bounded single-writer actor. Strategy queries have no callbacks into it.

    Socket adapters own their I/O threads. They submit bounded immutable batches;
    queue overload latches a discontinuity, which the writer commits before it
    accepts another proof. Consumers cannot stall ingestion by holding Python locks.
    """
    def __init__(self, path, *, capacity=64):
        self.path = path
        self.queue = queue.Queue(maxsize=capacity)
        self.failed = None
        self._loss = threading.Event()
        self._stop = threading.Event()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name='solana-evidence-writer', daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(5):
            raise EvidenceUnavailable('writer_start_timeout')
        self.check()

    def check(self):
        if self.failed:
            raise EvidenceUnavailable('writer_failed') from self.failed

    def submit(self, records, *, proof=None):
        self.check()
        # Freeze before queueing, including nested mutable payloads.
        records = tuple(FinalizedRecord(**json.loads(canonical(r.__dict__))) for r in records)
        if len(records) > 2048:
            raise EvidenceUnavailable('ingestion_batch_bound')
        if proof:
            proof = IntervalProof(**json.loads(canonical(proof.__dict__)))
        try:
            self.queue.put_nowait((records, proof))
        except queue.Full:
            self._loss.set()
            raise EvidenceUnavailable('ingestion_backlog_gap') from None

    def _run(self):
        writer = None
        try:
            writer = EvidenceWriter(self.path)
            self.ready.set()
            while not self._stop.is_set() or not self.queue.empty():
                if self._loss.is_set():
                    # Fail the service instead of losing the unknown interval or
                    # accepting queued coverage that might bridge dropped data.
                    for scope, slot in writer.db.execute('SELECT scope,slot FROM cursors').fetchall():
                        writer.gap(scope, slot, reason='ingestion_queue_overflow')
                    raise EvidenceUnavailable('ingestion_queue_overflow')
                try:
                    records, proof = self.queue.get(timeout=.05)
                except queue.Empty:
                    continue
                try:
                    writer.ingest(records, proof=proof)
                finally:
                    self.queue.task_done()
        except BaseException as exc:
            self.failed = exc
            self.ready.set()
        finally:
            if writer:
                writer.close()

    def close(self):
        self._stop.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise EvidenceUnavailable('writer_stop_timeout')
        self.check()
