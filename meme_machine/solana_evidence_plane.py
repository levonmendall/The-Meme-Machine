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
from meme_machine.runtime.sqlite_files import transient_file_size
import queue
import sqlite3
import threading
import time
import uuid
from .solana_provider_config import public_value
from .solana_evidence_storage import install as install_storage, encode as encode_body, decode as _decode_body, archive_body, collect as collect_storage, prepare as prepare_storage, publish as publish_storage, publish_addresses

STORAGE_WARNING_BYTES = 512 * 1024 * 1024
STORAGE_CRITICAL_BYTES = 128 * 1024 * 1024


def storage_health(path, *, required_bytes=0):
    path = Path(path)
    archive = path.parent / (path.name + '.archive')
    locations = (path.parent, archive if archive.exists() else path.parent)
    free = [os.statvfs(p).f_bavail * os.statvfs(p).f_frsize for p in locations]
    remaining = min(free) - required_bytes
    return dict(free_bytes=min(free), database_free_bytes=free[0], archive_free_bytes=free[1],
                warning_bytes=STORAGE_WARNING_BYTES, critical_bytes=STORAGE_CRITICAL_BYTES,
                state=('critical' if remaining < STORAGE_CRITICAL_BYTES else
                       'warning' if remaining < STORAGE_WARNING_BYTES else 'ok'))


def require_storage(path, *, required_bytes=0):
    if storage_health(path, required_bytes=required_bytes)['state'] == 'critical':
        raise EvidenceUnavailable('storage_capacity_critical')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class EvidenceUnavailable(ValueError):
    pass


class EvidenceConflict(EvidenceUnavailable):
    pass


def decode_body(raw,db=None,*,chunks=None,decoded_chunks=None):
    try:return _decode_body(raw,db,chunks=chunks,decoded_chunks=decoded_chunks)
    except (ValueError,TypeError,KeyError) as exc:raise EvidenceConflict('hot_evidence_corrupt') from exc


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
        public_value(self.__dict__)
        return self._body()

    def serialized_body(self):
        # Source/availability are lineage rather than economic content. Check
        # them separately, then reuse the immutable canonical body for the
        # credential scan, hash, bound and hot encoding instead of dumping the
        # entire large payload once just to scan it and again to persist it.
        public_value(dict(source=self.source,endpoint_identity=self.endpoint_identity,
                          observed_at=self.observed_at))
        body=self._body();raw=canonical(body);public_value(raw)
        return body,raw

    def _body(self):
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
class PreparedRecord:
    """Trusted local decoder output; never accepted from a provider/consumer JSON."""
    record: FinalizedRecord
    addresses: tuple
    checksum: str
    byte_count: int
    encoded: str | bytes
    chunks: tuple


def prepare_record(record):
    body,raw=record.serialized_body()
    encoded,chunks=prepare_storage(body,canonical_body=raw)
    return PreparedRecord(record,tuple(body['addresses']),hashlib.sha256(raw.encode()).hexdigest(),
                          len(raw.encode()),encoded,chunks)


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
        public_value(self.__dict__)
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
-- Seek the first hot slot without traversing an archived retention backlog.
-- This is an access path only: cutoff, archive proofs, pins and slices are unchanged.
CREATE INDEX IF NOT EXISTS records_hot_scope_slot ON records(scope,slot) WHERE body IS NOT NULL;
CREATE INDEX IF NOT EXISTS records_scope_time ON records(scope,market_time,slot,event_index);
CREATE INDEX IF NOT EXISTS records_signature ON records(signature);
CREATE INDEX IF NOT EXISTS records_archive_time ON records(COALESCE(market_time,first_seen),identity) WHERE body IS NOT NULL;
CREATE INDEX IF NOT EXISTS records_archive_ref ON records(archive) WHERE archive IS NOT NULL;
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
CREATE TABLE IF NOT EXISTS interest_checkpoints(
 owner TEXT NOT NULL,scope TEXT NOT NULL,lower_slot INTEGER NOT NULL,
 consumed_slot INTEGER NOT NULL,hash TEXT NOT NULL,updated REAL NOT NULL,
 PRIMARY KEY(owner,scope));
CREATE TABLE IF NOT EXISTS service_interests(
 owner TEXT NOT NULL,scope TEXT NOT NULL,address TEXT NOT NULL,evidence_class TEXT NOT NULL,
 PRIMARY KEY(owner,scope,address));
CREATE INDEX IF NOT EXISTS service_interest_address ON service_interests(address,owner,scope);
CREATE VIEW IF NOT EXISTS account_interest_bounds AS
 SELECT 'account:'||s.address AS scope,
 MIN(CASE WHEN c.owner IS NULL THEN 0 ELSE i.lower_slot END) AS lower_slot
 FROM service_interests s JOIN interests i ON i.owner=s.owner AND i.scope=s.scope
 LEFT JOIN interest_checkpoints c ON c.owner=i.owner AND c.scope=i.scope
 WHERE i.active=1 GROUP BY s.address;
CREATE VIEW IF NOT EXISTS account_interest_floors AS
 SELECT b.scope,MIN(b.lower_slot,COALESCE((SELECT MAX(r.slot) FROM records r
 WHERE r.scope=b.scope AND r.kind='account' AND r.body IS NOT NULL
 AND r.slot<=b.lower_slot),b.lower_slot)) AS floor
 FROM account_interest_bounds b;
CREATE TABLE IF NOT EXISTS conflicts(
 id INTEGER PRIMARY KEY,identity TEXT NOT NULL,prior TEXT NOT NULL,
 incoming TEXT NOT NULL,observed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS archives(
 name TEXT PRIMARY KEY,hash TEXT NOT NULL,bytes INTEGER NOT NULL,records INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS archive_gc(name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS counters(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
'''


def lifecycle_scope(scope):
    """Fixed, payload-free telemetry buckets; never evidence authority."""
    if scope in ('program:meteora','program:pump','program:pumpswap'):
        return scope
    return 'account' if scope.startswith('account:') else 'other'


class EvidenceWriter:
    """One process/thread owns all evidence mutations; consumers open read-only DBs."""
    def __init__(self, path, *, clock=time.time, max_hot_bytes=256 * 1024 * 1024):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        require_storage(self.path)
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
            self.db.execute('PRAGMA auto_vacuum=INCREMENTAL')
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.executescript(SCHEMA)
            install_storage(self.db)
            from .solana_maintenance_state import install as install_maintenance_state
            install_maintenance_state(self)
            with self.transaction():
                initialized = self.db.execute("SELECT value FROM meta WHERE key='initialized'").fetchone()
                if initialized:
                    self._count('restarts')
                    # Last cursor is durable, but proves nothing after a crash.
                    # Account snapshots carry their own slot/freshness; they do
                    # not attest a continuous program interval. Match disconnect
                    # semantics rather than creating unrepairable account gaps.
                    for scope, slot in self.db.execute("SELECT scope,slot FROM cursors WHERE scope NOT LIKE 'account:%'").fetchall():
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
        if getattr(self,'_source_frame_depth',0):
            # The source frame's enclosing savepoint owns rollback. Its helpers
            # propagate errors to that boundary; commands/repair never enter it.
            yield
            return
        # A source batch or command receipt owns the outer commit. Inner helpers
        # must roll back with it; one fsync publishes the entire atomic operation.
        if self.db.in_transaction:
            name='nested_'+uuid.uuid4().hex
            self.db.execute('SAVEPOINT '+name)
            try:
                yield
                self.db.execute('RELEASE '+name)
            except BaseException:
                self.db.execute('ROLLBACK TO '+name)
                self.db.execute('RELEASE '+name)
                raise
            return
        try:
            # SQLITE_INTERRUPT can be reported after BEGIN has already entered
            # a write transaction. Cleanup must cover admission as well as body
            # and commit, or the next checkpoint fails with SQLITE_LOCKED.
            self.db.execute('BEGIN IMMEDIATE')
            yield
            self.db.execute('COMMIT')
        except BaseException:
            # SQLite may already roll back an interrupted statement itself.
            # Preserve its original error when there is no transaction to undo.
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise

    @contextmanager
    def source_frame(self):
        """One rollback boundary for a complete ordered source frame."""
        if getattr(self,'_source_frame_depth',0):
            raise EvidenceUnavailable('nested_source_frame')
        with self.transaction():
            self._source_frame_depth=getattr(self,'_source_frame_depth',0)+1
            try:yield
            finally:self._source_frame_depth-=1

    def _count(self, key, count=1):
        self.db.execute('INSERT INTO counters VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=value+excluded.value', (key, count))

    def _gap(self, scope, lo, hi, reason):
        if not self.db.execute('''SELECT 1 FROM gaps WHERE scope=? AND lo<=? AND repaired IS NULL
            AND (hi IS NULL OR (? IS NOT NULL AND hi>=?))''', (scope, lo, hi, hi)).fetchone():
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
        self._check()
        require_storage(self.path, required_bytes=32 * 1024 * 1024)
        inputs=tuple(records)
        if len(inputs)>2048:raise EvidenceUnavailable('ingestion_batch_bound')
        records=tuple(row.record if isinstance(row,PreparedRecord) else row for row in inputs)
        for record in records:
            floor=self.db.execute('SELECT value FROM meta WHERE key=?',('retention_floor:'+record.scope,)).fetchone()
            if floor and record.slot<int(floor[0]):raise EvidenceUnavailable('record_below_hot_retention_floor')
        try:prepared=tuple(row if isinstance(row,PreparedRecord) else prepare_record(row) for row in inputs)
        except ValueError:
            with self.transaction():self._count('rejected_evidence_records',len(records))
            raise
        if sum(row.byte_count for row in prepared)>16*1024*1024:
            raise EvidenceUnavailable('ingestion_payload_bound')
        hot_bytes=sum(transient_file_size(p) for p in (self.path,Path(str(self.path)+'-wal')))
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
            for row in prepared:
                record=row.record;checksum=row.checksum
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
                scope_insertions={};address_cache={}
                for row in prepared:
                    record=row.record
                    inserted = self.db.execute('INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)',
                        (record.identity, record.scope, record.slot, record.signature, record.program,
                         record.market_time, record.event_index, record.transaction_index, record.kind,
                         publish_storage(self.db,record.identity,row.encoded,row.chunks), staged[record.identity], record.observed_at)).rowcount
                    publish_addresses(self.db,record.identity,record.slot,row.addresses,address_cache)
                    self.db.execute('INSERT OR IGNORE INTO lineage VALUES(?,?,?,?)',
                        (record.identity, record.source, record.endpoint_identity, record.observed_at))
                    self.db.execute('INSERT INTO cursors VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET slot=MAX(slot,excluded.slot),updated=excluded.updated',
                        (record.scope, record.slot, self.clock()))
                    if inserted:
                        self._count('ingested_' + record.kind)
                        bucket=lifecycle_scope(record.scope)
                        scope_insertions[bucket]=scope_insertions.get(bucket,0)+inserted
                # Aggregate inside the same transaction/savepoint. Rolled-back
                # frames and duplicate delivery cannot manufacture useful work.
                for bucket,count in scope_insertions.items():
                    self._count('lifecycle.ingested.'+bucket,count)
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
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='stream_receipts'").fetchone():
                # A completed authenticated repair settles the old receipt too.
                # It does not link receipt sessions or grant stream coverage.
                self.db.execute('UPDATE stream_receipts SET sealed=1 WHERE scope=? AND slot BETWEEN ? AND ?',
                    (proof.scope,proof.lower_slot,proof.upper_slot))

    def interest(self, owner, scope, *, lower_slot, priority=4, lifecycle='candidate'):
        with self.transaction():
            self._interest(owner,scope,lower_slot=lower_slot,priority=priority,lifecycle=lifecycle)

    def _interest(self, owner, scope, *, lower_slot, priority=4, lifecycle='candidate'):
        if (not owner or not scope or type(lower_slot) is not int or lower_slot < 0
                or priority not in range(5) or lifecycle not in ('candidate', 'reserved', 'open', 'research')):
            raise EvidenceUnavailable('invalid_interest')
        if lifecycle == 'open' and priority != 0 or lifecycle == 'reserved' and priority > 1:
            raise EvidenceUnavailable('lifecycle_evidence_priority')
        old = self.db.execute('SELECT lifecycle,active FROM interests WHERE owner=? AND scope=?', (owner,scope)).fetchone()
        if old and old[1] and ((old[0] == 'open' and lifecycle != 'open') or
                              (old[0] == 'reserved' and lifecycle not in ('reserved','open'))):
            raise EvidenceUnavailable('lifecycle_interest_downgrade')
        self.db.execute('INSERT INTO interests VALUES(?,?,?,?,?,1,?) ON CONFLICT(owner,scope) DO UPDATE SET priority=excluded.priority,lower_slot=MIN(lower_slot,excluded.lower_slot),lifecycle=excluded.lifecycle,active=1,updated=excluded.updated',
            (owner, scope, priority, lower_slot, lifecycle, self.clock()))

    def release(self, owner, scope, *, lifecycle_resolved=False):
        with self.transaction():
            row = self.db.execute('SELECT lifecycle FROM interests WHERE owner=? AND scope=? AND active=1', (owner, scope)).fetchone()
            if row and row[0] in ('open', 'reserved') and not lifecycle_resolved:
                raise EvidenceUnavailable('unresolved_lifecycle_interest')
            self.db.execute('UPDATE interests SET active=0,updated=? WHERE owner=? AND scope=?', (self.clock(), owner, scope))

    def advance_interest(self,owner,scope,*,lower_slot,consumed_slot,checkpoint_hash):
        """A consumer acknowledges its durable native replay checkpoint.

        Ordinary interest reassertion remains conservative. This operation moves
        only this owner's consumed prefix, never another lifecycle or gap pin,
        and grants no coverage. The caller must commit its replay state first.
        """
        if (type(lower_slot) is not int or type(consumed_slot) is not int
                or not 0<=lower_slot<=consumed_slot or not isinstance(checkpoint_hash,str)
                or len(checkpoint_hash)!=64 or any(c not in '0123456789abcdef' for c in checkpoint_hash)):
            raise EvidenceUnavailable('interest_checkpoint_shape')
        with self.transaction():
            row=self.db.execute('SELECT lower_slot FROM interests WHERE owner=? AND scope=? AND active=1',
                                (owner,scope)).fetchone()
            top=self.db.execute('SELECT slot FROM cursors WHERE scope=?',(scope,)).fetchone()
            if row is None:raise EvidenceUnavailable('interest_checkpoint_owner_inactive')
            if lower_slot<row[0]:raise EvidenceUnavailable('interest_checkpoint_regression')
            if top is None or consumed_slot>top[0]:raise EvidenceUnavailable('interest_checkpoint_ahead_of_source')
            prior=self.db.execute('SELECT lower_slot,consumed_slot,hash FROM interest_checkpoints WHERE owner=? AND scope=?',
                                  (owner,scope)).fetchone()
            if prior:
                if lower_slot<prior[0] or consumed_slot<prior[1]:
                    raise EvidenceUnavailable('interest_checkpoint_regression')
                if consumed_slot==prior[1] and (lower_slot,consumed_slot,checkpoint_hash)!=prior:
                    raise EvidenceUnavailable('interest_checkpoint_conflict')
            self.db.execute('INSERT OR REPLACE INTO interest_checkpoints VALUES(?,?,?,?,?,?)',
                            (owner,scope,lower_slot,consumed_slot,checkpoint_hash,self.clock()))
            self.db.execute('UPDATE interests SET lower_slot=?,updated=? WHERE owner=? AND scope=?',
                            (lower_slot,self.clock(),owner,scope))

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

    def archive_plan(self,before_time,*,max_records=1000,max_bytes=4*1024*1024):
        return self.prepare_archive(self.archive_snapshot(before_time,max_records=max_records),max_bytes=max_bytes)

    def archive_snapshot(self,before_time,*,max_records=1000,max_bytes=4*1024*1024):
        """Copy the exact bounded archive input using set-based metadata reads."""
        from .solana_archive_snapshot import snapshot
        return snapshot(self,before_time,max_records=max_records,max_bytes=max_bytes)

    @staticmethod
    def prepare_archive(snapshot,*,max_bytes=4*1024*1024):
        return [row for row,raw in EvidenceWriter._archive_rows(snapshot,max_bytes=max_bytes)]

    @staticmethod
    def _archive_rows(snapshot,*,max_bytes,raw_bodies=False):
        size=0;raw_chunks={}
        if not snapshot:return
        for row in snapshot['rows']:
            if raw_bodies:
                try:body,raw=archive_body(row['encoded'],chunks=snapshot['chunks'],raw_chunks=raw_chunks)
                except (ValueError,TypeError,KeyError) as exc:raise EvidenceConflict('hot_evidence_corrupt') from exc
            else:
                body=decode_body(row['encoded'],chunks=snapshot['chunks']);raw=canonical(body)
            cost=len(raw.encode())
            if hashlib.sha256(raw.encode()).hexdigest()!=row['hash']:raise EvidenceConflict('archive_body_hash_mismatch')
            if size and size+cost>max_bytes:break
            yield dict(identity=row['identity'],body=body,hash=row['hash'],
                lineage=[dict(source=src,endpoint_identity=ep,observed_at=at) for src,ep,at in row['lineage']],
                coverage=[dict(lo=lo,hi=hi,available=at,proof=json.loads(proof)) for lo,hi,at,proof in row['coverage']]),raw
            size+=cost

    @staticmethod
    def prepare_and_write_archive(path,snapshot,*,max_bytes=4*1024*1024):
        started=time.monotonic();lines=[];commit=[]
        for row,body_raw in EvidenceWriter._archive_rows(snapshot,max_bytes=max_bytes,raw_bodies=True):
            metadata={k:v for k,v in row.items() if k!='body'}
            # "body" is the first canonical key. Reuse its already hash-checked
            # serialization instead of serializing the full economic record twice.
            lines.append('{"body":'+body_raw+','+canonical(metadata)[1:])
            # The owner needs only these immutable fields to recheck pins and
            # match identity/hash. Full bodies/provenance stay in the durable file,
            # avoiding a second multi-megabyte process-pool transfer and decode.
            commit.append(dict(identity=row['identity'],hash=row['hash'],
                body=dict(scope=row['body']['scope'],slot=row['body']['slot'])))
        prepared=time.monotonic()
        receipt=EvidenceWriter._write_archive_raw(path,'\n'.join(lines)+'\n') if lines else None
        if receipt:receipt['worker_metrics']=dict(prepare_microseconds=int((prepared-started)*1_000_000),
            publish_microseconds=int((time.monotonic()-prepared)*1_000_000),records=len(commit))
        return commit,receipt

    @staticmethod
    def write_archive(path,plan):
        if not plan:return None
        return EvidenceWriter._write_archive_raw(path,'\n'.join(canonical(row) for row in plan)+'\n')

    @staticmethod
    def _write_archive_raw(path,raw):
        public_value(raw)
        # Archival must keep pace with the authenticated stream. Level 1 is
        # lossless and avoids spending the shared worker budget on compression
        # ratio; canonical bodies and content-addressed publication are unchanged.
        compressed=gzip.compress(raw.encode(),compresslevel=1,mtime=0);checksum=hashlib.sha256(compressed).hexdigest()
        require_storage(path, required_bytes=len(compressed) + 32 * 1024 * 1024)
        path=Path(path);directory=path.parent/(path.name+'.archive');directory.mkdir(exist_ok=True)
        target=directory/(checksum+'.jsonl.gz')
        # Register publication before the raw file exists. A killed archive
        # worker cannot leave an unregistered permanent raw payload.
        publish_bytes(target.with_name(target.name+'.pending'),b'pending\n')
        publish_bytes(target,compressed)
        return dict(name=target.name,hash=checksum,bytes=len(compressed))

    def commit_archive(self,plan,receipt):
        if not receipt:return 0
        archived=0
        archived_by_scope={}
        actual_scope_progress={}
        # A service archive may be committed in bounded owner slices after the
        # complete immutable file has already been published off-owner. Preserve
        # the file's full record count in the manifest even when this call owns
        # only one commit slice. Direct/legacy receipts still use len(plan).
        manifest_records=(receipt.get('worker_metrics') or {}).get('records',len(plan))
        if type(manifest_records) is not int or manifest_records < len(plan) or manifest_records < 0:
            raise EvidenceUnavailable('archive_manifest_record_count')
        with self.transaction():
            # A completion retry can follow retirement of its entire prefix.
            # Its metadata receipt remains idempotent without recreating a
            # manifest for a raw file whose references have all expired.
            referenced=any(self.db.execute('SELECT 1 FROM records WHERE identity=?',(row['identity'],)).fetchone() for row in plan)
            added=self.db.execute('INSERT OR IGNORE INTO archives VALUES(?,?,?,?)',(receipt['name'],receipt['hash'],receipt['bytes'],manifest_records)).rowcount if referenced else 0
            if added:self._count('archive_bytes',receipt['bytes'])
            for row in plan:
                # An interest can arrive while compression/fsync is in flight.
                # Recheck pins before dropping even a single hot payload.
                body=row['body'];scope=body['scope'];slot=body['slot']
                pinned=self.db.execute('''SELECT 1 FROM interests i WHERE scope=? AND active=1 AND lower_slot<=?
                    AND (NOT EXISTS(SELECT 1 FROM service_interests s WHERE s.owner=i.owner AND s.scope=i.scope)
                      OR EXISTS(SELECT 1 FROM service_interests s JOIN addresses a ON a.address=s.address
                                WHERE s.owner=i.owner AND s.scope=i.scope AND a.identity=?))
                    UNION ALL SELECT 1 FROM gaps WHERE scope=? AND repaired IS NULL AND lo<=? AND (hi IS NULL OR hi>=?) LIMIT 1''',
                    (scope,slot,row['identity'],scope,slot,slot)).fetchone()
                floor=self._account_floor(scope)
                pinned=pinned or (floor is not None and slot>=floor)
                if not pinned:
                    changed=self.db.execute('UPDATE records SET body=NULL,archive=? WHERE identity=? AND hash=? AND body IS NOT NULL',(receipt['name'],row['identity'],row['hash'])).rowcount
                    archived+=changed
                    if changed:
                        actual_scope_progress[scope]=actual_scope_progress.get(scope,0)+changed
                        bucket=lifecycle_scope(scope)
                        archived_by_scope[bucket]=archived_by_scope.get(bucket,0)+changed
                    self.db.execute('DELETE FROM hot_refs WHERE identity=?',(row['identity'],))
            self._count('archived_records',archived)
            for bucket,count in archived_by_scope.items():
                self._count('lifecycle.archived.'+bucket,count)
            from .solana_maintenance_state import progress
            for scope,count in actual_scope_progress.items():
                progress(self,scope,'archive',count,count)
        pending=self.path.parent/(self.path.name+'.archive')/(receipt['name']+'.pending')
        try:pending.unlink()
        except FileNotFoundError:pass
        return archived

    def _account_floor(self,scope):
        if not scope.startswith('account:'):return None
        # Preserve the last unchanged account value at/before the consumed
        # boundary. Any owner without a durable checkpoint retains all history.
        row=self.db.execute('SELECT floor FROM account_interest_floors WHERE scope=?',(scope,)).fetchone()
        return row[0] if row else None

    def archive(self,before_time,*,max_records=1000):
        plan=self.archive_plan(before_time,max_records=max_records)
        return self.commit_archive(plan,self.write_archive(self.path,plan))

    def retain(self, before_time, *, max_records=1000, archive_first=True, checkpoint=True, housekeeping_first=False):
        """Retire bounded slices; report only committed work and observed backlog.

        The legacy return value remains the number archived by this call.
        ``last_retention_progress`` is reset on every call and remains available
        after a cooperative yield. A rolled-back slice never contributes to it.
        """
        from .solana_retention_outcome import RetentionProgress
        self._check()
        progress=self.last_retention_progress=RetentionProgress()
        if not 1 <= max_records <= 1000:raise EvidenceUnavailable('retention_batch_bound')
        archived=self.archive(before_time,max_records=max_records) if archive_first else 0
        if housekeeping_first:
            # Only the admitted turn's sole peer-blocking obligation is promoted.
            # Publish the existing batch's committed outcome before any yield;
            # keep its ordinary SQL interruptibility and the current scope cursor.
            self._retention_housekeeping(max_records,progress)
            should_yield=getattr(self,'_retention_yield_requested',None)
            yield_class=should_yield() if should_yield else None
            if yield_class:
                progress.interrupted=True;progress.yield_reason=yield_class
                return archived
        source_yield_budget=[2]  # existing three separate 256-record transactions
        scopes=self.db.execute('SELECT scope,slot FROM cursors ORDER BY scope').fetchall()
        resume=getattr(self,'_retention_next_scope',None)
        start=next((i for i,row in enumerate(scopes) if row[0]==resume),0)
        scopes=scopes[start:]+scopes[:start]
        continuity_tables=[name for name in ('stream_receipts','stream_deliveries','stream_order')
            if self.db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone()]
        for index,(scope,top) in enumerate(scopes):
            next_scope=scopes[(index+1)%len(scopes)][0]
            for offset in range(0,max_records,256):
                limit=min(max_records-offset,256)
                # Read-only preparation is preemptible by urgent work. The sole
                # writer cannot interleave a pin/ingest operation before this
                # callback's bounded mutation, and checkpoint workers own no rows.
                floor=self.db.execute('SELECT MIN(slot) FROM records WHERE scope=? AND body IS NOT NULL',(scope,)).fetchone()[0]
                floor=top+1 if floor is None else floor
                recent=self.db.execute('SELECT MIN(lo) FROM coverage WHERE scope=? AND available>=?',(scope,before_time)).fetchone()[0]
                if recent is not None:floor=min(floor,recent)
                pins=[r[0] for r in self.db.execute('SELECT lower_slot FROM interests WHERE scope=? AND active=1 UNION ALL SELECT lo FROM gaps WHERE scope=? AND repaired IS NULL',(scope,scope))]
                if pins:floor=min(floor,min(pins))
                account_floor=self._account_floor(scope)
                if account_floor is not None:floor=min(floor,account_floor)
                old=self.db.execute('SELECT value FROM meta WHERE key=?',('retention_floor:'+scope,)).fetchone()
                floor=max(int(old[0]) if old else 0,floor)
                candidates=[r[0] for r in self.db.execute('SELECT identity FROM records WHERE scope=? AND slot<? AND body IS NULL LIMIT ?',(scope,floor,limit+1))]
                ids=candidates[:limit]
                # One extra key is a bounded lookahead, not a larger deletion.
                queries=[('coverage','id','scope=? AND hi<?',(scope,floor)),
                         ('gaps','id','scope=? AND hi<? AND repaired IS NOT NULL',(scope,floor))]
                queries += [(name,'rowid','scope=? AND slot<?',(scope,floor)) for name in continuity_tables]
                plans=[]
                for table,key,where,args in queries:
                    keys=[r[0] for r in self.db.execute(
                        'SELECT '+key+' FROM '+table+' WHERE '+where+' LIMIT ?',(*args,max_records+1))]
                    plans.append((table,key,where,args,keys))
                more_here=len(candidates)>limit or any(len(keys)>max_records for *_,keys in plans)
                floor_changed=old is None or floor!=int(old[0])
                if not ids and not floor_changed and not any(keys for *_,keys in plans):
                    # No BEGIN/COMMIT and no fabricated "progress" for empty work.
                    progress.scope(scope,False)
                    self._retention_next_scope=next_scope
                    should_yield=getattr(self,'_retention_yield_requested',None)
                    if should_yield and should_yield()=='urgent':
                        progress.interrupted=True;progress.yield_reason='urgent'
                        raise EvidenceUnavailable('evidence_background_yield')
                    break
                resume_scope=[scope if more_here else next_scope]
                removed=[0]
                def committed():
                    progress.commit(scope,len(ids),removed[0],int(floor_changed),more_here)
                with self._retention_transaction(
                        next_scope=lambda r=resume_scope:r[0],urgent_next_scope=next_scope,
                        source_yield_budget=source_yield_budget,after_commit=committed):
                    if ids:
                        marks=','.join('?' for _ in ids)
                        self.db.execute('DELETE FROM address_refs WHERE record_id IN (SELECT rowid FROM records WHERE identity IN ('+marks+'))',ids)
                        self.db.execute('DELETE FROM hot_refs WHERE identity IN ('+marks+')',ids)
                        self.db.execute('DELETE FROM lineage WHERE identity IN ('+marks+')',ids)
                        deleted=self.db.execute('DELETE FROM records WHERE identity IN ('+marks+')',ids).rowcount
                        if deleted!=len(ids):raise EvidenceConflict('retention_delete_identity_mismatch')
                    if floor_changed:
                        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('retention_floor:'+scope,str(floor)))
                    for table,key,where,args,keys in plans:
                        if keys:
                            removed[0]+=self.db.execute(
                                'DELETE FROM '+table+' WHERE '+key+' IN (SELECT '+key+
                                ' FROM '+table+' WHERE '+where+' LIMIT ?)',(*args,max_records)).rowcount
                    if ids:
                        self._count('compacted_records',len(ids))
                        self._count('lifecycle.retired.'+lifecycle_scope(scope),len(ids))
                    if removed[0]:
                        self._count('lifecycle.continuity.'+lifecycle_scope(scope),removed[0])
                    from .solana_maintenance_state import progress as maintenance_progress
                    maintenance_progress(self,scope,'retirement',len(ids)+removed[0]+int(floor_changed),len(ids))
                if not more_here:break
        if not housekeeping_first:
            self._retention_housekeeping(max_records,progress)
        if checkpoint:self.db.execute('PRAGMA wal_checkpoint(PASSIVE)')
        self.db.execute('PRAGMA incremental_vacuum(256)')
        # Scope retirement after a prefix can orphan new operational rows.
        # They were not examined by that batch; do not claim an idle backlog.
        progress.complete=not (housekeeping_first and progress.retired_records)
        return archived

    def _retention_housekeeping(self,max_records,progress):
        # The existing retention floor has already preserved active interests,
        # gaps and recovery references. Queue physical deletion atomically with
        # manifest retirement, so a crash cannot strand permanent raw history.
        garbage=[]
        for table,key,sql in (
            ('archives','name','SELECT name FROM archives WHERE name NOT IN (SELECT DISTINCT archive FROM records WHERE archive IS NOT NULL) LIMIT ?'),
            ('hot_chunks','hash','SELECT hash FROM hot_chunks c WHERE NOT EXISTS(SELECT 1 FROM hot_refs r WHERE r.hash=c.hash) LIMIT ?'),
            ('address_keys','id','SELECT id FROM address_keys k WHERE NOT EXISTS(SELECT 1 FROM address_refs r WHERE r.address_id=k.id) LIMIT ?')):
            limit=max_records
            if table=='archives':limit=min(limit,max(0,4096-self.db.execute('SELECT COUNT(*) FROM archive_gc').fetchone()[0]))
            if not limit:
                progress.remaining.add('gc:archives');continue
            keys=[r[0] for r in self.db.execute(sql,(limit+1,))]
            if len(keys)>limit:progress.remaining.add('gc:'+table)
            if keys:garbage.append((table,key,keys[:limit]))
        if garbage:
            removed=0
            with self.transaction():
                for table,key,keys in garbage:
                    marks=','.join('?' for _ in keys)
                    if table=='archives':
                        directory=self.path.parent/(self.path.name+'.archive')
                        owned=[name for name in keys if len(name)==73 and name.endswith('.jsonl.gz') and
                               all(c in '0123456789abcdef' for c in name[:64]) and (directory/name).exists()]
                        self.db.executemany('INSERT OR IGNORE INTO archive_gc VALUES(?)',((name,) for name in owned))
                    removed+=self.db.execute('DELETE FROM '+table+' WHERE '+key+' IN ('+marks+')',keys).rowcount
                from .solana_maintenance_state import progress as maintenance_progress
                maintenance_progress(self,'__housekeeping__','retirement',removed)
            progress.housekeeping_rows+=removed
        # At most 32 small unlinks per owner admission; no directory-wide scan,
        # no deletion of unknown files or of an archive newly referenced again.
        names=self.db.execute('SELECT name FROM archive_gc ORDER BY name LIMIT ?',
                              (min(32,max_records),)).fetchall()
        directory=self.path.parent/(self.path.name+'.archive')
        expired=[]
        for name, in names:
            if (len(name)!=73 or not name.endswith('.jsonl.gz') or
                    any(c not in '0123456789abcdef' for c in name[:64])):
                raise EvidenceUnavailable('archive_gc_name')
            if self.db.execute('SELECT 1 FROM archives WHERE name=? UNION ALL SELECT 1 FROM records WHERE archive=? LIMIT 1',(name,name)).fetchone():
                expired.append(name)
                continue
            target=directory/name
            if target.is_symlink():raise EvidenceUnavailable('archive_gc_symlink')
            try:target.unlink()
            except FileNotFoundError:pass  # Replay after unlink-before-commit.
            expired.append(name)
        if expired:
            with self.transaction():
                self.db.executemany('DELETE FROM archive_gc WHERE name=?',((name,) for name in expired))
                self._count('archive_files_expired',len(expired))
                from .solana_maintenance_state import progress as maintenance_progress
                maintenance_progress(self,'__housekeeping__','retirement',len(expired))
            progress.housekeeping_rows+=len(expired)
        if self.db.execute('SELECT 1 FROM archive_gc LIMIT 1').fetchone():
            progress.remaining.add('gc:archive_files')
        self._reclaim_published_orphans()

    def archive_orphan_probe_due(self):
        directory=self.path.parent/(self.path.name+'.archive')
        if not directory.exists() or self.clock()<getattr(self,'_next_orphan_probe',0):return False
        with os.scandir(directory) as entries:
            for index,entry in enumerate(entries):
                if index>=10000:raise EvidenceUnavailable('archive_gc_directory_bound')
                if (entry.name.endswith('.jsonl.gz.pending') and
                        self.clock()-entry.stat(follow_symlinks=False).st_mtime>=86400):return True
        return False

    def _reclaim_published_orphans(self):
        if not self.archive_orphan_probe_due():return
        self._next_orphan_probe=self.clock()+60
        directory=self.path.parent/(self.path.name+'.archive')
        cursor=getattr(self,'_orphan_cursor','');names=[]
        with os.scandir(directory) as entries:
            for index,entry in enumerate(entries):
                if index>=10000:raise EvidenceUnavailable('archive_gc_directory_bound')
                if entry.name.endswith('.jsonl.gz.pending') and entry.name>cursor:
                    names.append(entry.name)
                    if len(names)>4:names=sorted(names)[:4]
        if not names:self._orphan_cursor='';return
        for name in sorted(names):
            self._orphan_cursor=name
            marker=directory/name;target=directory/name.removesuffix('.pending')
            if len(target.name)!=73 or any(c not in '0123456789abcdef' for c in target.name[:64]):
                raise EvidenceUnavailable('archive_gc_name')
            if marker.is_symlink() or target.is_symlink():raise EvidenceUnavailable('archive_gc_symlink')
            # Healthy publication/commit needs seconds. One day also preserves
            # interrupted in-flight support until all original references end.
            if self.clock()-marker.stat().st_mtime<86400:continue
            if self.db.execute('SELECT 1 FROM archives WHERE name=?',(target.name,)).fetchone():
                marker.unlink();continue
            if target.exists():
                with target.open('rb') as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=target.name[:64]:
                        raise EvidenceUnavailable('archive_gc_hash')
                needed=False;size=0
                with gzip.open(target,'rb') as stream:
                    for line in stream:
                        size+=len(line)
                        if size>32*1024*1024:raise EvidenceUnavailable('archive_gc_body_bound')
                        row=json.loads(line);body=row['body'];scope=body['scope'];slot=body['slot']
                        needed=bool(self.db.execute('''SELECT 1 FROM records WHERE identity=?
                            UNION ALL SELECT 1 FROM interests WHERE scope=? AND active=1 AND lower_slot<=?
                            UNION ALL SELECT 1 FROM gaps WHERE scope=? AND repaired IS NULL AND lo<=? AND (hi IS NULL OR hi>=?) LIMIT 1''',
                            (row['identity'],scope,slot,scope,slot,slot)).fetchone())
                        if needed:break
                if needed:continue
                target.unlink()
            marker.unlink()
            with self.transaction():self._count('archive_publication_orphans_expired',1)

    @staticmethod
    def checkpoint(path):
        """Copy the durable WAL bulk without holding the logical evidence owner.

        PASSIVE never waits for another writer or reader. The owner completes
        any concurrently appended tail at its next scheduled transaction boundary.
        """
        from contextlib import closing
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=rw',
                                     uri=True,isolation_level=None,timeout=0)) as db:
            return db.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()

    def finish_checkpoint(self):
        """Reclaim the completed WAL tail at the sole writer boundary.

        The service calls this only behind its completed-PASSIVE generation
        fence. Without that fence SQLite may copy a newly appended tail;
        busy_timeout=0 limits lock waiting, not copying or fsync execution.
        Standalone callers retain explicit checkpoint behavior. A pinned
        reader returns busy rather than being waited out or invalidated.
        """
        self._check()
        if self.db.in_transaction:raise EvidenceUnavailable('checkpoint_inside_source_transaction')
        prior=self.db.execute('PRAGMA busy_timeout').fetchone()[0]
        try:
            self.db.execute('PRAGMA busy_timeout=0')
            return self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        finally:
            self.db.execute('PRAGMA busy_timeout='+str(int(prior)))

    @contextmanager
    def _retention_transaction(self,*,next_scope=None,urgent_next_scope=None,source_yield_budget=None,after_commit=None):
        """Only the bounded retention mutation is protected from SQL preemption."""
        self._retention_atomic=True
        try:
            with self.transaction():yield
        finally:self._retention_atomic=False
        if after_commit is not None:after_commit()
        # This is a scheduling hint, not evidence authority. Advance only after
        # the durable slice commits, before an urgent-work yield. Restarting at
        # the first scope on every yield starves later scopes under source load.
        resolved=next_scope() if callable(next_scope) else next_scope
        should_yield=getattr(self,'_retention_yield_requested',None)
        yield_class=should_yield() if should_yield else None
        if yield_class=='urgent':
            self._retention_next_scope=urgent_next_scope if urgent_next_scope is not None else resolved
            self._retention_source_resume_scope=None;self._retention_source_resume_count=0
        elif (yield_class=='source' and source_yield_budget is not None
              and source_yield_budget[0]>0):
            # The fixed E22 cohorts showed that one or two 256-record cleanup
            # slices per owner admission can still accumulate retirement debt
            # after the hot-floor lookup is O(1). Spend at most two additional
            # bounded slices; each remains a separate SQLite transaction.
            # The queued source request remains visible at the next transaction
            # boundary, where we yield (or yield sooner if urgent work arrived).
            source_yield_budget[0]-=1
            self._retention_next_scope=resolved
            self._retention_source_resume_scope=None;self._retention_source_resume_count=0
            return
        elif yield_class=='source' and urgent_next_scope is not None and resolved!=urgent_next_scope:
            # Three bounded slices have now had one owner admission. Rotate before
            # the next cleanup admission so a dense first scope cannot starve
            # later scopes while normal source work is continuously queued.
            self._retention_next_scope=urgent_next_scope
            self._retention_source_resume_scope=None;self._retention_source_resume_count=0
        else:
            self._retention_next_scope=resolved
            self._retention_source_resume_scope=None;self._retention_source_resume_count=0
        if yield_class:
            report=getattr(self,'last_retention_progress',None)
            if report is not None:
                report.interrupted=True;report.yield_reason=yield_class
            raise EvidenceUnavailable('evidence_background_yield')

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
        require_storage(self.path)
        if self.db.execute("SELECT 1 FROM meta WHERE key='poisoned'").fetchone():
            raise EvidenceConflict('evidence_store_poisoned')

    def covered(self, scope, lower_slot, upper_slot, *, as_of):
        self._healthy()
        if lower_slot < 0 or upper_slot < lower_slot:
            raise EvidenceUnavailable('invalid_query_window')
        floor=self.db.execute('SELECT value FROM meta WHERE key=?',('retention_floor:'+scope,)).fetchone()
        if floor and lower_slot<int(floor[0]):return False
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
                parsed = decode_body(body,self.db)
                if digest(parsed) != checksum:
                    raise EvidenceConflict('local_evidence_hash_mismatch:' + identity)
                result.append(parsed)
            return result
        finally:
            self.db.execute('ROLLBACK')

    def telemetry(self):
        # Health remains readable while canonical queries fail closed.
        health={}
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='service_health'").fetchone():
            health={k:json.loads(v) for k,v in self.db.execute('SELECT * FROM service_health')}
        return dict(integrity_poisoned=bool(self.db.execute("SELECT 1 FROM meta WHERE key='poisoned'").fetchone()),storage=storage_health(self.path),service_health=health,ingestion_lag_seconds={k:max(0,time.time()-v['time']) for k,v in health.items() if k.startswith('finalized_frontier:')},cursors=[dict(scope=s, slot=n, updated=t) for s, n, t in self.db.execute('SELECT * FROM cursors')],
            coverage_windows=self.db.execute('SELECT COUNT(*) FROM coverage').fetchone()[0],
            hot_payload_records=self.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0],
            shared_hot_chunks=self.db.execute('SELECT COUNT(*) FROM hot_chunks').fetchone()[0],
            address_references=self.db.execute('SELECT COUNT(*) FROM address_refs').fetchone()[0],
            active_pins=[dict(scope=s,lifecycle=l,count=n,lower_slot=lo) for s,l,n,lo in self.db.execute('SELECT scope,lifecycle,COUNT(*),MIN(lower_slot) FROM interests WHERE active=1 GROUP BY scope,lifecycle')],
            unresolved_gaps=self.db.execute('SELECT COUNT(*) FROM gaps WHERE repaired IS NULL').fetchone()[0],
            consumer_lag=[dict(owner=o, scope=s, slots=max(0, top-n), updated=t) for o,s,n,t,top in self.db.execute('SELECT c.owner,c.scope,c.slot,c.updated,r.slot FROM consumers c JOIN cursors r ON c.scope=r.scope')],
            counters=dict(self.db.execute('SELECT * FROM counters')), local_queries=self.queries,
            hot_bytes=sum(transient_file_size(p) for p in (self.path, Path(str(self.path)+'-wal'))),
            db_bytes=self.path.stat().st_size,
            wal_bytes=transient_file_size(Path(str(self.path)+'-wal')),
            interests=[dict(owner=o,scope=s,priority=p,lower_slot=l,lifecycle=k,updated=t) for o,s,p,l,k,a,t in self.db.execute('SELECT * FROM interests WHERE active=1')],
            retention_floors={k.split(':',1)[1]:int(v) for k,v in self.db.execute("SELECT key,value FROM meta WHERE key LIKE 'retention_floor:%'")},
            archive_bytes=(self.db.execute("SELECT value FROM counters WHERE key='archive_bytes'").fetchone() or [0])[0])

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
