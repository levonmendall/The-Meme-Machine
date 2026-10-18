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
_RECENT_UNREAD=object()


def continuity_retirement_guards(writer,scope,tables):
    """Keep actual CONTROL dependencies, without pinning cold proof intervals.

    Current program children anchor the unread live tail. An older pending
    proof needs its exact lower receipt and the actual last receipt at/before
    its upper bound, not every CONTROL row between those boundaries. These
    predicates run on the sole owner with the existing bounded deletion slice;
    no result is cached across commands or treated as evidence completeness.
    """
    if scope!='control:solana':return {}
    db=writer.db
    present={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('candidate_blocks','candidate_pending_proofs','stream_receipts','prewarm_startup','prewarm_startup_feeds')")}
    if 'stream_receipts' not in present:return {}
    tail=None
    if 'candidate_blocks' in present:
        from .solana_rolling_history import program_scope
        startup=db.execute('SELECT session,started FROM prewarm_startup WHERE id=1').fetchone() if 'prewarm_startup' in present else None
        bounds=[]
        for family in ('pump','pumpswap'):
            child=db.execute('SELECT slot,seen FROM candidate_blocks WHERE scope=?',(program_scope(family),)).fetchone()
            if child is not None and (startup is None or child[1]>=startup[1]):bounds.append(child[0])
            elif startup is not None and 'prewarm_startup_feeds' in present:
                feed=db.execute('SELECT lo FROM prewarm_startup_feeds WHERE session=? AND family=?',(startup[0],family)).fetchone()
                if feed is not None:bounds.append(feed[0])
        tail=min(bounds) if bounds else None
    result={}
    for table in tables:
        if table not in ('stream_receipts','stream_deliveries','stream_order'):
            raise EvidenceUnavailable('maintenance_continuity_table')
        slot=table+'.slot';parts=[];args=()
        if tail is not None:parts.append(slot+'<?');args=(tail,)
        if 'candidate_pending_proofs' in present:
            parts.append('NOT EXISTS(SELECT 1 FROM candidate_pending_proofs p WHERE p.lo='+slot+')')
            parts.append('''NOT EXISTS(SELECT 1 FROM candidate_pending_proofs p
                WHERE p.hi>='''+slot+''' AND p.hi<=COALESCE((SELECT n.slot-1 FROM stream_receipts n
                WHERE n.scope='control:solana' AND n.slot>'''+slot+''' ORDER BY n.slot LIMIT 1),9223372036854775807))''')
        if parts:result[table]=(' AND '+' AND '.join(parts),args)
    return result


def continuity_retirement_page(writer,scope,table,kind,lower,upper,limit,guard):
    """Filter one indexed key page, never an unbounded protected population.

    The volatile cursor is only a scheduling hint. Its fixed horizon lets old
    protected pages wrap even while new CONTROL receipts continue to arrive.
    Callers publish the returned hint only after a commit, or a fully examined
    page with no mutations. A restart merely examines those retained keys again.
    """
    if table not in ('stream_receipts','stream_deliveries','stream_order') or kind not in ('prefix','suffix'):
        raise EvidenceUnavailable('maintenance_continuity_page')
    clause,guard_args=guard
    # The only bound argument is the current child/recovery tail. Push it into
    # the page's indexed range rather than examining protected live-tail rows.
    if guard_args:upper=min(upper,guard_args[0])
    key=(scope,table,kind)
    if upper<=lower:return [],(key,None),False,False
    signature=table!='stream_receipts'
    columns='slot,signature' if signature else 'slot'
    order=columns
    width=2 if signature else 1
    hints=getattr(writer,'_retention_continuity_pages',{})
    after,horizon=hints.get(key,(None,None))
    resumed=after is not None
    if (after is not None and after[0]>=upper or
            horizon is not None and horizon[0]<lower):
        after=horizon=None
    args=(scope,lower,upper)
    base='scope=? AND slot>=? AND slot<?'
    if horizon is None:
        descending='slot DESC,signature DESC' if signature else 'slot DESC'
        horizon=writer.db.execute('SELECT '+columns+' FROM '+table+' WHERE '+base+' ORDER BY '+descending+' LIMIT 1',args).fetchone()
    if horizon is None:return [],(key,None),False,resumed
    compare='('+columns+')' if signature else columns
    markers='('+','.join('?' for _ in range(width))+')' if signature else '?'
    # Use one effective lower bound. With both slot>=lower and key>after,
    # SQLite can seek the weaker slot bound and rewalk protected prefix keys.
    # A complete cursor at/above lower implies that slot bound; a cursor below
    # lower is itself implied. Keep the current upper and fixed horizon intact.
    if after is not None and after[0]>=lower:
        where='scope=? AND '+compare+'>'+markers+' AND slot<?'
        values=(scope,*after,upper)
    else:
        where=base;values=args
    where+=' AND '+compare+'<='+markers
    values=(*values,*horizon)
    rows=writer.db.execute('SELECT rowid,'+columns+' FROM '+table+' WHERE '+where+
        ' ORDER BY '+order+' LIMIT ?',(*values,limit+1)).fetchall()
    page=rows[:limit];more=len(rows)>limit
    # One bounded validation statement, not one SQL round trip per receipt or
    # signature. The IN set is already a fixed key page before filtering.
    selected=[]
    if page:
        rowids=[row[0] for row in page]
        selected=[row[0] for row in writer.db.execute('SELECT rowid FROM '+table+
            ' WHERE rowid IN ('+','.join('?' for _ in rowids)+')'+clause,(*rowids,*guard_args))]
    hint=(tuple(page[-1][1:]),tuple(horizon)) if more else None
    # Earlier protected pages can become eligible between owner turns. Finishing
    # a resumed horizon is not a new proof that its earlier pages are still idle.
    return selected,(key,hint),more,resumed or more


def continuity_retirement_advance(writer,updates):
    if not updates:return
    hints=dict(getattr(writer,'_retention_continuity_pages',{}))
    for key,hint in updates:
        if hint is None:hints.pop(key,None)
        else:hints[key]=hint
    writer._retention_continuity_pages=hints


@dataclass(frozen=True)
class _RetirementFences:
    """Fresh inputs shared only by one read-only owner observation.

    Nothing stores this view across owner commands. Native retirement still
    reads its own mutable fences immediately before changing durable records.
    """
    scope: str
    gaps: tuple
    active_floor: int | None
    open_gap_floor: int | None
    account_floor: int | None
    continuity: tuple
    guards: tuple


def retirement_suffix(writer,scope,top,before_time,*,recent_floor=_RECENT_UNREAD,
                      _fences=None):
    """One expired disjoint range outside required gaps and whole witnesses.

    An unresolved gap does not reference all future history, or the history
    between separate gaps. Keep open gaps/pins/account floors and the fresh hot
    tail. Remove each retired range's whole coverage witnesses with its raw rows,
    so expired history cannot falsely answer a complete query with no records.
    """
    db=writer.db
    if _fences is None:
        gaps=db.execute('SELECT lo,hi FROM gaps WHERE scope=? AND repaired IS NULL AND hi IS NOT NULL ORDER BY lo,hi LIMIT ?',
                        (scope,MAX_PINS+1)).fetchall()
    else:
        if _fences.scope!=scope:raise EvidenceUnavailable('maintenance_observation_scope_mismatch')
        gaps=_fences.gaps
    if not gaps:return None
    if len(gaps)>MAX_PINS:raise EvidenceUnavailable('maintenance_gap_range_bound')
    merged=[]
    for lo,hi in gaps:
        if merged and lo<=merged[-1][1]+1:merged[-1]=(merged[-1][0],max(hi,merged[-1][1]))
        else:merged.append((lo,hi))
    bound=top+1
    bounds=(_fences.active_floor,_fences.open_gap_floor) if _fences is not None else tuple(
        db.execute(query,(scope,)).fetchone()[0] for query in (
            'SELECT MIN(lower_slot) FROM interests WHERE scope=? AND active=1',
            'SELECT MIN(lo) FROM gaps WHERE scope=? AND repaired IS NULL AND hi IS NULL'))
    for value in bounds:
        if value is not None:bound=min(bound,value)
    account=_fences.account_floor if _fences is not None else writer._account_floor(scope)
    if account is not None:bound=min(bound,account)
    # This readonly function and its observation run on the same sole owner.
    # Reuse the exact fresh minimum for older gap starts within this operation;
    # it cannot be borrowed across commands, mutations, blocks or restarts.
    if recent_floor is _RECENT_UNREAD:
        recent_floor=db.execute('SELECT MIN(lo) FROM coverage INDEXED BY maintenance_recent_coverage WHERE scope=? AND available>=?',
            (scope,before_time)).fetchone()[0]
    continuity=(_fences.continuity if _fences is not None else
        tuple(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE name IN ('stream_receipts','stream_deliveries','stream_order')")))
    guards=dict(_fences.guards) if _fences is not None else continuity_retirement_guards(writer,scope,continuity)
    tails=[args[0] for _,args in guards.values() if args]
    if tails:bound=min(bound,min(tails))
    def overlap_index(boundary):
        # Fresh receipt availability does not imply a small historical lo
        # prefix: a reconnect can freshly publish much older blocks. Probe a
        # bounded prefix, then seek the existing hi index when it is large.
        # This selects an access path only; the exact overlap predicates and
        # the observation's unchanged VM budget still govern both fences.
        count=db.execute('''SELECT COUNT(*) FROM (SELECT 1 FROM coverage
            INDEXED BY coverage_window WHERE scope=? AND lo<? LIMIT ?)''',
            (scope,boundary,MAX_BUCKETS+1)).fetchone()[0]
        return 'coverage_window' if count<=MAX_BUCKETS else 'maintenance_coverage_end'
    def has_work(start,end):
        # Overlap fencing can only shrink this range. An empty initial range
        # cannot gain eligible work; avoid scanning its entire older coverage
        # prefix merely to fence witnesses that do not exist here.
        predicates=[('records','slot>=? AND slot<? AND body IS NULL'),
                    ('coverage','lo>=? AND lo<? AND hi<?'),
                    ('gaps','lo>=? AND lo<? AND hi<? AND repaired IS NOT NULL')]
        predicates += [(name,'slot>=? AND slot<?') for name in continuity]
        for table,predicate in predicates:
            guard,guard_args=guards.get(table,('',()))
            args=(scope,start,end,end) if table in ('coverage','gaps') else (scope,start,end)
            if db.execute('SELECT 1 FROM '+table+' WHERE scope=? AND '+predicate+guard+' LIMIT 1',
                          (*args,*guard_args)).fetchone():return True
        return False
    for index in range(len(merged)-1,-1,-1):
        start=merged[index][1]+1
        end=min(bound,merged[index+1][0] if index+1<len(merged) else top+1)
        if start>=end:continue
        hot=db.execute('SELECT MIN(slot) FROM records WHERE scope=? AND slot>=? AND body IS NOT NULL',(scope,start)).fetchone()[0]
        if recent_floor is None or start<=recent_floor:
            recent=recent_floor
        else:
            recent=db.execute('SELECT MIN(lo) FROM coverage INDEXED BY maintenance_recent_coverage WHERE scope=? AND lo>=? AND available>=?',(scope,start,before_time)).fetchone()[0]
        for value in (hot,recent):
            if value is not None:end=min(end,value)
        if start>=end:continue
        if not has_work(start,end):continue
        unfenced=(start,end)
        # Bound overlap-chain work. An unknown interval stays protected.
        for _ in range(64):
            index_name=overlap_index(start)
            cross=db.execute('SELECT MAX(hi) FROM coverage INDEXED BY '+index_name+' WHERE scope=? AND lo<? AND hi>=?',(scope,start,start)).fetchone()[0]
            if cross is None:break
            start=cross+1
        else:continue
        for _ in range(64):
            index_name=overlap_index(end)
            cross=db.execute('SELECT MIN(lo) FROM coverage INDEXED BY '+index_name+' WHERE scope=? AND lo<? AND hi>=?',(scope,end,end)).fetchone()[0]
            if cross is None:break
            end=cross
        else:continue
        if start>=end:continue
        # An empty newest interval must not hide older eligible work between
        # gaps. These indexed lookups match the native retirement predicates.
        # Native intervals have lo<=hi. Give the slot index both ends instead
        # of scanning every later protected interval for a failed hi predicate.
        # All intervening operations are reads on the same sole owner. When
        # neither whole-witness fence moved, the exact initial work witness is
        # still true; do not issue every table probe for a second time.
        if (start,end)==unfenced or has_work(start,end):return start,end
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
CREATE INDEX IF NOT EXISTS maintenance_coverage_end ON coverage(scope,hi,lo);
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
    from .runtime.operating_families import evidence_scope_sql
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
        rows = db.execute('SELECT rowid,scope,slot,COALESCE(market_time,first_seen),body IS NOT NULL FROM records WHERE '+evidence_scope_sql('records.scope')+' AND rowid>? ORDER BY rowid LIMIT 512', (cursor,)).fetchall()
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
            from .runtime.operating_families import evidence_scope_sql,enabled
            cursors = self.bounded('SELECT scope,slot FROM cursors WHERE '+evidence_scope_sql('cursors.scope')+' ORDER BY scope', limit=MAX_SCOPES)
            known = dict(cursors)
            for scope in PROGRAM_SCOPES:
                if scope=='program:meteora' and not enabled('meteora'):continue
                known.setdefault(scope, -1)
            if len(known) > MAX_SCOPES:
                raise EvidenceUnavailable('maintenance_scope_bound')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            continuity_tables=tuple(t for t in ('stream_receipts','stream_deliveries','stream_order') if t in tables)
            for scope, top in sorted(known.items()):
                pins = self.bounded('''SELECT i.owner,i.lower_slot,EXISTS(SELECT 1 FROM service_interests s WHERE s.owner=i.owner AND s.scope=i.scope)
                    FROM interests i WHERE i.scope=? AND i.active=1''', (scope,), MAX_PINS)
                gaps = self.bounded('SELECT lo,hi FROM gaps WHERE scope=? AND repaired IS NULL', (scope,), MAX_PINS)
                account_floor = writer._account_floor(scope)
                hot_debt, hot_oldest = self._hot(scope, wall-PRESERVATION_SECONDS, pins, gaps, account_floor)
                oldest_slot = db.execute('SELECT slot FROM records INDEXED BY records_hot_scope_slot WHERE scope=? AND body IS NOT NULL ORDER BY slot LIMIT 1', (scope,)).fetchone()
                floor = oldest_slot[0] if oldest_slot else top+1
                # MIN(lo)'s slot index can scan expired history for every gap.
                # Seek the existing availability index within the same VM bound.
                recent = db.execute('SELECT MIN(lo) FROM coverage INDEXED BY maintenance_recent_coverage WHERE scope=? AND available>=?', (scope, wall-PRESERVATION_SECONDS)).fetchone()[0]
                if recent is not None:
                    floor = min(floor, recent)
                if pins:
                    floor = min(floor, min(p[1] for p in pins))
                if account_floor is not None:
                    floor = min(floor, account_floor)
                guards=continuity_retirement_guards(writer,scope,continuity_tables)
                # These exact pins, gaps, account floor and CONTROL guards were
                # just read by this unchanged owner observation. Reuse them for
                # suffix planning and continuity witnesses, never a later write.
                fences=_RetirementFences(scope,
                    tuple(sorted((lo,hi) for lo,hi in gaps if hi is not None)),
                    min((p[1] for p in pins),default=None),
                    min((lo for lo,hi in gaps if hi is None),default=None),
                    account_floor,continuity_tables,tuple(guards.items()))
                suffix=retirement_suffix(writer,scope,top,wall-PRESERVATION_SECONDS,
                    recent_floor=recent,_fences=fences)
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
                tails=[args[0] for _,args in guards.values() if args]
                continuity_floor=min(floor,min(tails)) if tails else floor
                for table, field, predicate in [('coverage','hi',''), ('gaps','hi',' AND repaired IS NOT NULL'),
                        *[(t,'slot','') for t in ('stream_receipts','stream_deliveries','stream_order') if t in tables]]:
                    # Need a bounded work witness, not a full history count. A
                    # saturated continuity backlog is represented conservatively
                    # as pending, never as zero or exact record debt.
                    # Native interval witnesses have lo<=hi. Give their slot
                    # index the necessary lower-coordinate bound as well: an
                    # empty prefix must not scan every later protected interval
                    # and exhaust observation's unchanged VM safety budget.
                    interval=table in ('coverage','gaps')
                    prefix=' AND lo<?' if interval else ''
                    args=(scope,continuity_floor,continuity_floor) if interval else (scope,continuity_floor)
                    guard,guard_args=guards.get(table,('',()))
                    found = db.execute('SELECT 1 FROM '+table+' WHERE scope=? AND '+field+'<?'+prefix+predicate+guard+' LIMIT 1', (*args,*guard_args)).fetchone()
                    continuity += int(found is not None)
                    if suffix is not None:
                        # Coverage/gap witnesses are retired only in their
                        # entirety, matching the native mutation's bounds.
                        lower='lo' if table in ('coverage','gaps') else field
                        suffix_upper=' AND lo<?' if interval else ''
                        suffix_args=(scope,*suffix,suffix[1]) if interval else (scope,*suffix)
                        found=db.execute('SELECT 1 FROM '+table+' WHERE scope=? AND '+lower+'>=? AND '+field+'<?'+suffix_upper+predicate+guard+' LIMIT 1',
                            (*suffix_args,*guard_args)).fetchone()
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
