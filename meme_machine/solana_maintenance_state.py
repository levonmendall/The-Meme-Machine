"""Bounded owner-side maintenance observations; never evidence/mutation authority.

The record synopsis is updated in the SAME SQLite transaction as native records.
It contains counts and immutable time/slot coordinates, not evidence payloads.
A capped read or VM-budget exhaustion is unknown, never an empty work queue.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
import math
import json
import sqlite3
import time

from .solana_evidence_plane import EvidenceUnavailable

PRESERVATION_SECONDS = 180.0
RESIDENCE_SECONDS = 240.0
RECOVERY_SOURCE_SECONDS = 120.0
PIPELINE_SLACK_RECORDS = 1000
MAX_SCOPES = 260  # three program scopes plus the existing <=256 account universe
MAX_BUCKETS = 4096
MAX_PINS = 8192
MAX_DETAIL_RECORDS = 8192
OBSERVATION_VM_STEPS = 250_000
PROGRESS_INTERVAL = 1000
PROGRAM_SCOPES = ('program:meteora', 'program:pump', 'program:pumpswap')


def retirement_suffix(writer,scope,top,before_time):
    """One expired disjoint range outside required gaps and whole witnesses.

    An unresolved gap does not reference all future history, or the history
    between separate gaps. Keep open gaps/pins/account floors and the fresh hot
    tail. Remove each retired range's whole coverage witnesses with its raw rows,
    so expired history cannot falsely answer a complete query with no records.
    """
    db=writer.db
    gaps=db.execute('SELECT lo,hi FROM gaps WHERE scope=? AND repaired IS NULL AND hi IS NOT NULL ORDER BY lo,hi LIMIT ?',
                    (scope,MAX_PINS+1)).fetchall()
    if not gaps:return None
    if len(gaps)>MAX_PINS:raise EvidenceUnavailable('maintenance_gap_range_bound')
    merged=[]
    for lo,hi in gaps:
        if merged and lo<=merged[-1][1]+1:merged[-1]=(merged[-1][0],max(hi,merged[-1][1]))
        else:merged.append((lo,hi))
    bound=top+1
    for query in ('SELECT MIN(lower_slot) FROM interests WHERE scope=? AND active=1',
                  'SELECT MIN(lo) FROM gaps WHERE scope=? AND repaired IS NULL AND hi IS NULL'):
        value=db.execute(query,(scope,)).fetchone()[0]
        if value is not None:bound=min(bound,value)
    account=writer._account_floor(scope)
    if account is not None:bound=min(bound,account)
    continuity=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE name IN ('stream_receipts','stream_deliveries','stream_order')")]
    for index in range(len(merged)-1,-1,-1):
        start=merged[index][1]+1
        end=min(bound,merged[index+1][0] if index+1<len(merged) else top+1)
        if start>=end:continue
        hot=db.execute('SELECT MIN(slot) FROM records WHERE scope=? AND slot>=? AND body IS NOT NULL',(scope,start)).fetchone()[0]
        recent=db.execute('SELECT MIN(lo) FROM coverage WHERE scope=? AND lo>=? AND available>=?',(scope,start,before_time)).fetchone()[0]
        for value in (hot,recent):
            if value is not None:end=min(end,value)
        if start>=end:continue
        # Bound overlap-chain work. An unknown interval stays protected.
        for _ in range(64):
            cross=db.execute('SELECT MAX(hi) FROM coverage WHERE scope=? AND lo<? AND hi>=?',(scope,start,start)).fetchone()[0]
            if cross is None:break
            start=cross+1
        else:continue
        for _ in range(64):
            cross=db.execute('SELECT MIN(lo) FROM coverage WHERE scope=? AND lo<? AND hi>=?',(scope,end,end)).fetchone()[0]
            if cross is None:break
            end=cross
        else:continue
        if start>=end:continue
        # An empty newest interval must not hide older eligible work between
        # gaps. These indexed lookups match the native retirement predicates.
        predicates=[('records','slot>=? AND slot<? AND body IS NULL'),
                    ('coverage','lo>=? AND hi<?'),
                    ('gaps','lo>=? AND hi<? AND repaired IS NOT NULL')]
        predicates += [(name,'slot>=? AND slot<?') for name in continuity]
        if any(db.execute('SELECT 1 FROM '+table+' WHERE scope=? AND '+predicate+' LIMIT 1',
                          (scope,start,end)).fetchone() for table,predicate in predicates):
            return start,end
    return None

SCHEMA = '''
CREATE TABLE IF NOT EXISTS maintenance_cohorts(
 scope TEXT NOT NULL, slot INTEGER NOT NULL, at REAL NOT NULL,
 hot INTEGER NOT NULL CHECK(hot>=0), archived INTEGER NOT NULL CHECK(archived>=0),
 PRIMARY KEY(scope,slot,at));
CREATE INDEX IF NOT EXISTS maintenance_hot_time ON maintenance_cohorts(scope,at,slot) WHERE hot>0;
CREATE INDEX IF NOT EXISTS maintenance_archived_slot ON maintenance_cohorts(scope,slot,at) WHERE archived>0;
CREATE INDEX IF NOT EXISTS maintenance_archived_time ON maintenance_cohorts(scope,at,slot) WHERE archived>0;
CREATE TABLE IF NOT EXISTS maintenance_progress(
 scope TEXT NOT NULL,side TEXT NOT NULL,at REAL NOT NULL,units INTEGER NOT NULL,
 record_at REAL,records INTEGER NOT NULL,PRIMARY KEY(scope,side));
CREATE TABLE IF NOT EXISTS maintenance_episodes(
 scope TEXT NOT NULL,side TEXT NOT NULL,source_deadline REAL NOT NULL,
 wall_started REAL NOT NULL,envelope INTEGER NOT NULL,
 PRIMARY KEY(scope,side));
CREATE TABLE IF NOT EXISTS maintenance_nonrecord_demand(
 scope TEXT NOT NULL,side TEXT NOT NULL,wall_started REAL NOT NULL,
 PRIMARY KEY(scope,side));
CREATE INDEX IF NOT EXISTS maintenance_interest_bound ON interests(scope,active,lower_slot,owner);
CREATE INDEX IF NOT EXISTS maintenance_gap_bound ON gaps(scope,repaired,lo,hi);
CREATE INDEX IF NOT EXISTS maintenance_recent_coverage ON coverage(scope,available,lo);
CREATE INDEX IF NOT EXISTS maintenance_retired_slot ON records(scope,slot) WHERE body IS NULL;
'''

# Explicit column update list excludes immutable metadata mutations. The native
# record API rejects content changes; the extra trigger fails closed if a future
# caller tries to change a synopsis key without a matching migration.
TRIGGERS = '''
CREATE TRIGGER IF NOT EXISTS maintenance_record_insert AFTER INSERT ON records BEGIN
 INSERT INTO maintenance_cohorts VALUES(NEW.scope,NEW.slot,COALESCE(NEW.market_time,NEW.first_seen),NEW.body IS NOT NULL,NEW.body IS NULL)
 ON CONFLICT(scope,slot,at) DO UPDATE SET hot=hot+excluded.hot,archived=archived+excluded.archived;
END;
CREATE TRIGGER IF NOT EXISTS maintenance_record_archive AFTER UPDATE OF body ON records
 WHEN (OLD.body IS NULL)!=(NEW.body IS NULL) BEGIN
 UPDATE maintenance_cohorts SET hot=hot+(NEW.body IS NOT NULL)-(OLD.body IS NOT NULL),
 archived=archived+(NEW.body IS NULL)-(OLD.body IS NULL)
 WHERE scope=OLD.scope AND slot=OLD.slot AND at=COALESCE(OLD.market_time,OLD.first_seen);
 SELECT CASE WHEN changes()!=1 THEN RAISE(ABORT,'maintenance_synopsis_missing') END;
END;
CREATE TRIGGER IF NOT EXISTS maintenance_record_delete AFTER DELETE ON records BEGIN
 UPDATE maintenance_cohorts SET hot=hot-(OLD.body IS NOT NULL),archived=archived-(OLD.body IS NULL)
 WHERE scope=OLD.scope AND slot=OLD.slot AND at=COALESCE(OLD.market_time,OLD.first_seen);
 SELECT CASE WHEN changes()!=1 THEN RAISE(ABORT,'maintenance_synopsis_missing') END;
 DELETE FROM maintenance_cohorts WHERE scope=OLD.scope AND slot=OLD.slot AND at=COALESCE(OLD.market_time,OLD.first_seen) AND hot=0 AND archived=0;
END;
CREATE TRIGGER IF NOT EXISTS maintenance_record_key BEFORE UPDATE OF scope,slot,market_time,first_seen ON records
 WHEN NEW.scope!=OLD.scope OR NEW.slot!=OLD.slot OR NEW.market_time IS NOT OLD.market_time OR NEW.first_seen!=OLD.first_seen BEGIN
 SELECT RAISE(ABORT,'maintenance_immutable_record_coordinate');
END;
'''


ORPHAN_SPECS=(('address','address_keys','id','address_refs','address_id'),
              ('chunk','hot_chunks','hash','hot_refs','hash'),
              ('archive','archives','name','records','archive'))


def orphan_triggers(*, updates=True):
    definitions={}
    for kind,table,key,refs,refkey in ORPHAN_SPECS:
        bodies={
            'key_insert':f"INSERT OR IGNORE INTO maintenance_orphans SELECT '{kind}',CAST(NEW.{key} AS TEXT) WHERE NOT EXISTS(SELECT 1 FROM {refs} WHERE {refkey}=NEW.{key});",
            'key_delete':f"DELETE FROM maintenance_orphans WHERE kind='{kind}' AND key=CAST(OLD.{key} AS TEXT);",
            'ref_insert':f"DELETE FROM maintenance_orphans WHERE kind='{kind}' AND key=CAST(NEW.{refkey} AS TEXT);",
            'ref_delete':f"INSERT OR IGNORE INTO maintenance_orphans SELECT '{kind}',CAST(OLD.{refkey} AS TEXT) WHERE OLD.{refkey} IS NOT NULL AND EXISTS(SELECT 1 FROM {table} WHERE {key}=OLD.{refkey}) AND NOT EXISTS(SELECT 1 FROM {refs} WHERE {refkey}=OLD.{refkey});",
        }
        for suffix,body in bodies.items():
            target=table if suffix.startswith('key') else refs
            operation='INSERT' if suffix.endswith('insert') else 'DELETE'
            name='orphan_'+kind+'_'+suffix
            definitions[name]=f'CREATE TRIGGER {name} AFTER {operation} ON {target} BEGIN {body} END'
        if kind=='archive' or updates:
            name='orphan_'+kind+'_ref_update'
            # Archive v1 already supplied this update trigger. Keep its exact SQL.
            old=f"INSERT OR IGNORE INTO maintenance_orphans SELECT '{kind}',"+(f'OLD.{refkey}' if kind=='archive' else f'CAST(OLD.{refkey} AS TEXT)')+f" WHERE OLD.{refkey} IS NOT NULL AND EXISTS(SELECT 1 FROM {table} WHERE {key}=OLD.{refkey}) AND NOT EXISTS(SELECT 1 FROM {refs} WHERE {refkey}=OLD.{refkey});"
            new=f"DELETE FROM maintenance_orphans WHERE kind='{kind}' AND key="+(f'NEW.{refkey}' if kind=='archive' else f'CAST(NEW.{refkey} AS TEXT)')+';'
            definitions[name]=f'CREATE TRIGGER {name} AFTER UPDATE OF {refkey} ON {refs} BEGIN {new} {old} END'
    return definitions


def _verify_orphan_triggers(db,expected):
    found=dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name GLOB 'orphan_*'"))
    normalized=lambda sql:' '.join(sql.rstrip(';').split()).replace('CREATE TRIGGER IF NOT EXISTS','CREATE TRIGGER')
    if found.keys()!=expected.keys() or any(normalized(found[k])!=normalized(v) for k,v in expected.items()):
        raise EvidenceUnavailable('maintenance_synopsis_trigger_identity')


def install_housekeeping_witnesses(db):
    """Exact orphan predicates; atomic batches before source admission.

    An incomplete install restarts its disposable synopsis from scratch. A
    completed install must prove its trigger definitions before it is trusted.
    Neither marker names maintenance obligations nor modifies their deadlines.
    """
    db.execute("CREATE TABLE IF NOT EXISTS maintenance_orphans(kind TEXT NOT NULL,key TEXT NOT NULL,PRIMARY KEY(kind,key)) WITHOUT ROWID")
    expected=orphan_triggers()
    v1=db.execute("SELECT 1 FROM meta WHERE key='maintenance_orphans_v1'").fetchone()
    v2=db.execute("SELECT 1 FROM meta WHERE key='maintenance_orphans_v2'").fetchone()
    if v1:
        prior=expected if v2 else orphan_triggers(updates=False)
        _verify_orphan_triggers(db,prior)
        if v2:return
        # A v1 synopsis may already have missed reference UPDATEs. Rebuild the
        # disposable index before admission instead of trusting stale witnesses.
    # No source/consumer is admitted during an incomplete installation.
    db.execute('BEGIN IMMEDIATE')
    try:
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'orphan_*'").fetchall():
            db.execute('DROP TRIGGER '+name)
        db.execute('DELETE FROM maintenance_orphans')
        db.execute("DELETE FROM meta WHERE key IN ('maintenance_orphans_v1','maintenance_orphans_v2')")
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK');raise
    for kind,table,key,refs,refkey in ORPHAN_SPECS:
        cursor=None
        while True:
            rows=db.execute('SELECT '+key+' FROM '+table+(' WHERE '+key+'>?' if cursor is not None else '')+' ORDER BY '+key+' LIMIT 512', (cursor,) if cursor is not None else ()).fetchall()
            if not rows:break
            db.execute('BEGIN IMMEDIATE')
            try:
                for (value,) in rows:
                    if not db.execute('SELECT 1 FROM '+refs+' WHERE '+refkey+'=? LIMIT 1',(value,)).fetchone():
                        db.execute('INSERT INTO maintenance_orphans VALUES(?,?)',(kind,str(value)))
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK');raise
            cursor=rows[-1][0]
    try:
        db.execute('BEGIN IMMEDIATE')
        for sql in expected.values():db.execute(sql)
        db.execute("INSERT OR REPLACE INTO meta VALUES('maintenance_orphans_v1','1')")
        db.execute("INSERT OR REPLACE INTO meta VALUES('maintenance_orphans_v2','1')")
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:db.execute('ROLLBACK')
        raise


def install(writer):
    """Restartable 512-row migration, before source/consumer service is admitted.

    The existing exclusive writer lease prevents other writers during migration.
    A crash leaves a durable cursor; triggers are enabled only after backfill.
    """
    db = writer.db
    db.executescript(SCHEMA)
    install_housekeeping_witnesses(db)
    done = db.execute("SELECT value FROM meta WHERE key='maintenance_synopsis_v1'").fetchone()
    if done:
        expected = {'maintenance_record_insert', 'maintenance_record_archive',
                    'maintenance_record_delete', 'maintenance_record_key'}
        found = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'maintenance_record_%'")}
        if found != expected:
            raise EvidenceUnavailable('maintenance_synopsis_trigger_identity')
        return
    row = db.execute("SELECT value FROM meta WHERE key='maintenance_backfill_cursor'").fetchone()
    cursor = int(row[0]) if row else 0
    while True:
        rows = db.execute('SELECT rowid,scope,slot,COALESCE(market_time,first_seen),body IS NOT NULL FROM records WHERE rowid>? ORDER BY rowid LIMIT 512', (cursor,)).fetchall()
        if not rows:
            break
        grouped = defaultdict(lambda: [0, 0])
        for rowid, scope, slot, at, hot in rows:
            grouped[scope, slot, at][0 if hot else 1] += 1
        with writer.transaction():
            db.executemany('INSERT INTO maintenance_cohorts VALUES(?,?,?,?,?) ON CONFLICT(scope,slot,at) DO UPDATE SET hot=hot+excluded.hot,archived=archived+excluded.archived',
                           [(*key, *counts) for key, counts in grouped.items()])
            cursor = rows[-1][0]
            db.execute("INSERT OR REPLACE INTO meta VALUES('maintenance_backfill_cursor',?)", (str(cursor),))
    # executescript commits implicitly, so the script carries its own atomic
    # completion marker. A restart may observe either the whole set or none.
    db.executescript('BEGIN IMMEDIATE;\n'+TRIGGERS+"\nINSERT OR REPLACE INTO meta VALUES('maintenance_synopsis_v1','1');\nDELETE FROM meta WHERE key='maintenance_backfill_cursor';\nCOMMIT;")


def progress(writer, scope, side, units, records=0):
    """Call inside the transaction that publishes the associated durable work."""
    if not writer.db.in_transaction:
        raise EvidenceUnavailable('maintenance_progress_outside_transaction')
    if type(units) is not int or units < 0 or side not in ('archive', 'retirement'):
        raise EvidenceUnavailable('maintenance_progress_shape')
    if units:
        writer.db.execute('INSERT INTO maintenance_progress VALUES(?,?,?,?,?,?) ON CONFLICT(scope,side) DO UPDATE SET at=excluded.at,units=units+excluded.units,record_at=CASE WHEN excluded.records>0 THEN excluded.record_at ELSE record_at END,records=records+excluded.records',
                          (scope, side, writer.clock(), units, writer.clock() if records else None, records))


@dataclass(frozen=True)
class ScopeState:
    scope: str
    hot_eligible: int
    hot_oldest: float | None
    archived_pending: int
    retirement_eligible: int
    retirement_oldest: float | None
    blocked_retirement_oldest: float | None
    continuity: int
    floor_changed: bool
    floor: int
    pins: int
    gaps: int
    account_floor: int | None
    source_time: float | None

    @property
    def retirement_units(self):
        return self.retirement_eligible + self.continuity + int(self.floor_changed)


@dataclass(frozen=True)
class NativeObservation:
    generation: str
    monotonic: float
    wall: float
    scopes: tuple[ScopeState, ...]
    housekeeping: int
    recent_progress: tuple[tuple, ...]
    vm_steps: int
    elapsed: float


class DebtAgeAdapter:
    def __init__(self, writer, *, monotonic=time.monotonic, wall=time.time):
        self.writer = writer
        self.monotonic = monotonic
        self.wall = wall
        self.steps = 0
        self._details = 0

    @contextmanager
    def budget(self):
        """Compose, rather than disable, the owner's urgent SQL preemption."""
        previous = getattr(self.writer, '_owner_progress_handler', None)
        self.steps = 0
        exhausted = False
        def handler():
            nonlocal exhausted
            self.steps += PROGRESS_INTERVAL
            if self.steps > OBSERVATION_VM_STEPS:
                exhausted = True
                return 1
            return previous() if previous else 0
        self.writer.db.set_progress_handler(handler, PROGRESS_INTERVAL)
        try:
            yield
        except sqlite3.OperationalError as exc:
            if exhausted:
                raise EvidenceUnavailable('maintenance_observation_vm_bound') from exc
            raise
        finally:
            self.writer.db.set_progress_handler(previous, PROGRESS_INTERVAL if previous else 0)

    def bounded(self, sql, args=(), limit=MAX_BUCKETS):
        cursor = self.writer.db.execute(sql+' LIMIT ?', (*args, limit+1))
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        if len(rows) > limit:
            raise EvidenceUnavailable('maintenance_observation_row_bound')
        return rows

    def _hot(self, scope, cutoff, pins, gaps, account_floor):
        rows = self.bounded('SELECT slot,at,hot FROM maintenance_cohorts INDEXED BY maintenance_hot_time WHERE scope=? AND hot>0 AND at<? ORDER BY at,slot', (scope, cutoff))
        debt = 0
        oldest = None
        db = self.writer.db
        self.steps += len(rows)*(1+len(pins)+len(gaps))
        if self.steps > OBSERVATION_VM_STEPS:
            raise EvidenceUnavailable('maintenance_observation_python_bound')
        eligible = []
        for slot, at, hot in rows:
            if hot <= 0 or not math.isfinite(at):
                raise EvidenceUnavailable('maintenance_synopsis_contradiction')
            if (account_floor is not None and slot >= account_floor or
                    any(slot >= lo and (hi is None or slot <= hi) for lo, hi in gaps)):
                continue
            applicable = [(owner, lo, addressed) for owner, lo, addressed in pins if slot >= lo]
            if any(not addressed for _, _, addressed in applicable):
                continue
            eligible.append((slot, at, hot, bool(applicable)))
        pinned = defaultdict(int)
        slots = sorted({slot for slot, _, _, addressed in eligible if addressed})
        if slots:
            # Seek the actual pinned addresses through the native address index
            # once. Scanning every unrelated hot record in every cohort repeats
            # the same correlated pin lookup and exhausts the bounded VM budget.
            # DISTINCT retains the original EXISTS semantics for overlapping pins.
            matches = self.bounded('''SELECT DISTINCT r.identity,r.slot,COALESCE(r.market_time,r.first_seen)
                FROM interests i INDEXED BY maintenance_interest_bound
                CROSS JOIN service_interests s CROSS JOIN address_keys k
                CROSS JOIN address_refs a INDEXED BY address_window CROSS JOIN records r
                WHERE i.scope=? AND i.active=1 AND s.owner=i.owner AND s.scope=i.scope
                AND k.address=s.address AND a.address_id=k.id AND a.slot IN ('''+
                ','.join('?' for _ in slots)+''') AND r.rowid=a.record_id AND r.scope=i.scope
                AND r.slot>=i.lower_slot AND r.body IS NOT NULL
                AND COALESCE(r.market_time,r.first_seen)<?''',
                (scope,*slots,cutoff),MAX_DETAIL_RECORDS-self._details)
            self._details += len(matches)
            self.steps += len(matches)
            if self.steps > OBSERVATION_VM_STEPS:
                raise EvidenceUnavailable('maintenance_observation_python_bound')
            for _, slot, at in matches:
                pinned[slot,at] += 1
        for slot, at, hot, addressed in eligible:
            count = hot
            if addressed:
                count -= pinned[slot,at]
                if count < 0:
                    raise EvidenceUnavailable('maintenance_pin_count_contradiction')
            if count:
                debt += count
                oldest = at if oldest is None else min(oldest, at)
        return debt, oldest

    def _source_frontier(self, scope, wall):
        """Read the durable finalized-block coordinate, never removable receipts.

        FinalizedFence publishes this small value in the receipt transaction.
        Native retention never deletes it. Absence is explicitly unknown; a hot
        record timestamp or an extant receipt cannot replace this authority.
        Persisted recovery episodes are owned by MaintenanceRuntime, not this
        observation, and therefore cannot be restarted by receipt collection.
        """
        row = self.writer.db.execute(
            "SELECT substr(value,1,1025) FROM service_health WHERE key=?",
            ('finalized_frontier:'+scope,)).fetchone()
        if row is None:
            return None
        try:
            raw = row[0]
            if not isinstance(raw,str) or len(raw)>1024:
                raise ValueError('frontier size')
            value = json.loads(raw)
            if not isinstance(value,dict):
                raise ValueError('frontier shape')
            slot, at, seen = value['slot'], value['time'], value['seen']
            if (type(slot) is not int or slot<0 or type(at) is not int or at<=0
                    or type(seen) not in (int,float) or not math.isfinite(seen)
                    or not at<=seen<=wall):
                raise ValueError('frontier coordinates')
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            raise EvidenceUnavailable('maintenance_finalized_frontier_invalid') from exc
        return at

    def observe(self, generation):
        writer = self.writer
        writer._check()
        if writer.db.in_transaction:
            raise EvidenceUnavailable('maintenance_observation_inside_transaction')
        begin = self.monotonic()
        wall = self.wall()
        if not generation or not math.isfinite(wall) or wall <= 0:
            raise EvidenceUnavailable('maintenance_observation_clock')
        self._details = 0
        results = []
        db = writer.db
        with self.budget():
            if db.execute("SELECT 1 FROM meta WHERE key='poisoned'").fetchone():
                raise EvidenceUnavailable('maintenance_store_poisoned')
            cursors = self.bounded('SELECT scope,slot FROM cursors ORDER BY scope', limit=MAX_SCOPES)
            known = dict(cursors)
            for scope in PROGRAM_SCOPES:
                known.setdefault(scope, -1)
            if len(known) > MAX_SCOPES:
                raise EvidenceUnavailable('maintenance_scope_bound')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for scope, top in sorted(known.items()):
                pins = self.bounded('''SELECT i.owner,i.lower_slot,EXISTS(SELECT 1 FROM service_interests s WHERE s.owner=i.owner AND s.scope=i.scope)
                    FROM interests i WHERE i.scope=? AND i.active=1''', (scope,), MAX_PINS)
                gaps = self.bounded('SELECT lo,hi FROM gaps WHERE scope=? AND repaired IS NULL', (scope,), MAX_PINS)
                account_floor = writer._account_floor(scope)
                hot_debt, hot_oldest = self._hot(scope, wall-PRESERVATION_SECONDS, pins, gaps, account_floor)
                oldest_slot = db.execute('SELECT slot FROM records INDEXED BY records_hot_scope_slot WHERE scope=? AND body IS NOT NULL ORDER BY slot LIMIT 1', (scope,)).fetchone()
                floor = oldest_slot[0] if oldest_slot else top+1
                recent = db.execute('SELECT MIN(lo) FROM coverage WHERE scope=? AND available>=?', (scope, wall-PRESERVATION_SECONDS)).fetchone()[0]
                if recent is not None:
                    floor = min(floor, recent)
                if pins:
                    floor = min(floor, min(p[1] for p in pins))
                if account_floor is not None:
                    floor = min(floor, account_floor)
                suffix=retirement_suffix(writer,scope,top,wall-PRESERVATION_SECONDS)
                if gaps:
                    floor = min(floor, min(g[0] for g in gaps))
                old = db.execute('SELECT value FROM meta WHERE key=?', ('retention_floor:'+scope,)).fetchone()
                old_floor = int(old[0]) if old else 0
                if oldest_slot is not None and old_floor > oldest_slot[0]:
                    raise EvidenceUnavailable('maintenance_floor_ahead_of_hot_evidence')
                floor = max(floor, old_floor)
                if floor < 0:
                    raise EvidenceUnavailable('maintenance_floor_contradiction')
                archived = self.bounded('SELECT slot,at,archived FROM maintenance_cohorts INDEXED BY maintenance_archived_slot WHERE scope=? AND archived>0 ORDER BY slot,at', (scope,))
                def removable(slot):return slot<floor or suffix is not None and suffix[0]<=slot<suffix[1]
                eligible = sum(n for slot, _, n in archived if removable(slot))
                eligible_oldest = min((at for slot, at, n in archived if removable(slot) and n), default=None)
                # Pins/coverage may intentionally retain rows. An unpinned hot
                # floor dependency cannot be ignored merely because retirement
                # cannot delete those rows yet: it tightens archive safety too.
                blocked_oldest = min((at for slot, at, n in archived if slot >= floor and n), default=None)
                if pins or gaps or account_floor is not None or recent is not None:
                    blocked_oldest = None
                continuity = 0
                for table, field, predicate in [('coverage','hi',''), ('gaps','hi',' AND repaired IS NOT NULL'),
                        *[(t,'slot','') for t in ('stream_receipts','stream_deliveries','stream_order') if t in tables]]:
                    # Need a bounded work witness, not a full history count. A
                    # saturated continuity backlog is represented conservatively
                    # as pending, never as zero or exact record debt.
                    found = db.execute('SELECT 1 FROM '+table+' WHERE scope=? AND '+field+'<?'+predicate+' LIMIT 1', (scope, floor)).fetchone()
                    continuity += int(found is not None)
                    if suffix is not None:
                        # Coverage/gap witnesses are retired only in their
                        # entirety, matching the native mutation's bounds.
                        lower='lo' if table in ('coverage','gaps') else field
                        found=db.execute('SELECT 1 FROM '+table+' WHERE scope=? AND '+lower+'>=? AND '+field+'<?'+predicate+' LIMIT 1',
                            (scope,*suffix)).fetchone()
                        continuity+=int(found is not None)
                source_at = self._source_frontier(scope, wall)
                results.append(ScopeState(scope, hot_debt, hot_oldest,
                    sum(n for _, _, n in archived), eligible, eligible_oldest,
                    blocked_oldest, continuity, top>=0 and (old is None or floor!=old_floor), floor,
                    len(pins), len(gaps), account_floor, source_at))
            # These are work witnesses, not potentially unbounded garbage scans.
            # Independent of archived_pending; low record debt does not erase GC.
            housekeeping = 0
            housekeeping += int(db.execute('SELECT 1 FROM archive_gc LIMIT 1').fetchone() is not None)
            housekeeping += int(self.writer.archive_orphan_probe_due())
            for kind in ('archive','chunk','address'):
                housekeeping += int(db.execute('SELECT 1 FROM maintenance_orphans WHERE kind=? LIMIT 1',(kind,)).fetchone() is not None)
            recent_progress = tuple(self.bounded('SELECT scope,side,at,units,record_at,records FROM maintenance_progress ORDER BY scope,side', limit=MAX_SCOPES*2+2))
        end = self.monotonic()
        if end < begin:
            raise EvidenceUnavailable('maintenance_clock_regressed')
        return NativeObservation(generation, end, wall, tuple(results), housekeeping,
                                 recent_progress, self.steps, end-begin)
