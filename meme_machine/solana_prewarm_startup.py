"""The canonical owner alone releases Model B candidate consumers.

Publication lag is a wait, never a cold-reconstruction signal. A stage, socket
ACK or state checkpoint cannot manufacture interval coverage.
"""
import json,sqlite3,time,uuid
from contextlib import closing
from pathlib import Path
from .solana_evidence_plane import EvidenceUnavailable,canonical,digest
from .solana_rolling_history import program_scope

PHASES=('BOOT','RESTORE_DURABLE_FRONTIER','RESTORE_NORMALIZED_HISTORY',
    'INSTALL_BASE_INTERESTS','START_ROLLING_FEEDS','RECOVERY_OVERLAP',
    'WAIT_FOR_DURABLE_PUBLICATION','VERIFY_CONTIGUOUS_COVERAGE',
    'RELEASE_CANDIDATE_CONSUMERS','STEADY_STATE')
SCHEMA='''
CREATE TABLE IF NOT EXISTS prewarm_startup(
 id INTEGER PRIMARY KEY CHECK(id=1),session TEXT NOT NULL,phase TEXT NOT NULL,
 started REAL NOT NULL,changed REAL NOT NULL,released INTEGER NOT NULL,
 body TEXT NOT NULL,hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prewarm_startup_transitions(
 sequence INTEGER PRIMARY KEY,session TEXT NOT NULL,phase TEXT NOT NULL,
 at REAL NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prewarm_startup_feeds(
 session TEXT NOT NULL,family TEXT NOT NULL,lo INTEGER NOT NULL,hi INTEGER NOT NULL,
 ack_at REAL NOT NULL,native_at REAL,PRIMARY KEY(session,family));
CREATE TABLE IF NOT EXISTS prewarm_membership_revision(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL);
INSERT OR IGNORE INTO prewarm_membership_revision VALUES(1,0);
'''

def released(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='prewarm_startup'").fetchone():return False
    row=db.execute('SELECT released,body,hash FROM prewarm_startup WHERE id=1').fetchone()
    if row is None:return False
    if digest(json.loads(row[1]))!=row[2]:raise EvidenceUnavailable('prewarm_startup_corrupt')
    return bool(row[0])

def require_released(db):
    if not released(db):raise EvidenceUnavailable('rolling_publication_pending')

def candidate_release(path):
    if not path:return True # Provider-free lifecycle unit tests have no plane.
    if not Path(path).exists():return False
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:return released(db)


class PrewarmStartup:
    def __init__(self,history):
        self.history=history;self.db=history.db;self.writer=history.writer
        self.db.executescript(SCHEMA)
        # Exact state changes, not repeated setters, invalidate the membership
        # plan. All triggers execute inside the sole canonical owner transaction.
        for table,fields in (
                ('service_interests',()),('interests',('active','priority','lifecycle','lower_slot')),
                ('market_observations',('fields',)),('evidence_bindings',('coverage_scope',))):
            for operation in ('INSERT','DELETE','UPDATE'):
                if operation=='UPDATE' and not fields:continue
                condition='' if operation!='UPDATE' else ' WHEN '+' OR '.join('OLD.'+f+' IS NOT NEW.'+f for f in fields)
                prefix='OLD' if operation=='DELETE' else 'NEW'
                if table=='market_observations':
                    tests=[prefix+".family='meteora'", "json_extract("+prefix+".fields,'$.wsol_pair_locator')=1"]
                    if operation=='UPDATE':tests.append("json_extract(OLD.fields,'$.wsol_pair_locator') IS NOT json_extract(NEW.fields,'$.wsol_pair_locator')")
                    condition=' WHEN '+' AND '.join(tests)
                if table=='evidence_bindings':
                    condition=' WHEN EXISTS(SELECT 1 FROM service_interests s WHERE s.scope='+prefix+'.canonical_scope AND s.address='+prefix+'.address)'
                    if operation=='UPDATE':condition+=' AND OLD.coverage_scope IS NOT NEW.coverage_scope'
                self.db.execute('CREATE TRIGGER IF NOT EXISTS prewarm_revision_'+table+'_'+operation+
                    ' AFTER '+operation+' ON '+table+condition+' BEGIN UPDATE prewarm_membership_revision SET revision=revision+1 WHERE id=1; END')

    @property
    def clock(self):return self.history.clock

    def snapshot(self):
        row=self.db.execute('SELECT session,phase,started,changed,released,body,hash FROM prewarm_startup WHERE id=1').fetchone()
        if row is None:return dict(phase='NOT_STARTED',released=False)
        body=json.loads(row[5])
        if digest(body)!=row[6]:raise EvidenceUnavailable('prewarm_startup_corrupt')
        return dict(session=row[0],phase=row[1],started=row[2],changed=row[3],released=bool(row[4]),**body)

    def transition(self,phase,details=None):
        current=self.snapshot();old=current['phase']
        if phase!='FAIL_CLOSED' and (old=='FAIL_CLOSED' or PHASES.index(phase)!=PHASES.index(old)+1):
            raise EvidenceUnavailable('prewarm_startup_transition_order')
        body={k:v for k,v in current.items() if k not in ('session','phase','started','changed','released')}
        body.update(details or {});now=self.clock()
        with self.writer.transaction():
            self.db.execute('UPDATE prewarm_startup SET phase=?,changed=?,released=?,body=?,hash=? WHERE id=1',
                (phase,now,int(phase in ('RELEASE_CANDIDATE_CONSUMERS','STEADY_STATE')),canonical(body),digest(body)))
            self.db.execute('INSERT INTO prewarm_startup_transitions(session,phase,at,body,hash) VALUES(?,?,?,?,?)',
                (current['session'],phase,now,canonical(body),digest(body)))

    def begin(self):
        # These immutable checkpoints advanced only after canonical content,
        # CandidateHistory and contiguous coverage durably committed.
        frontiers={f:(r[0] if r else None) for f in ('pump','pumpswap')
            for r in [self.db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',(program_scope(f),)).fetchone()]}
        now=self.clock();session=uuid.uuid4().hex
        body=dict(model='MODEL_B_ROLLING_NORMALIZED_PREWARM',legacy_startup_active=False,
            restored_frontiers=frontiers,normalized_records=self.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0])
        with self.writer.transaction():
            self.db.execute('INSERT OR REPLACE INTO prewarm_startup VALUES(1,?,?,?,?,0,?,?)',
                (session,'BOOT',now,now,canonical(body),digest(body)))
            self.db.execute('INSERT INTO prewarm_startup_transitions(session,phase,at,body,hash) VALUES(?,?,?,?,?)',
                (session,'BOOT',now,canonical(body),digest(body)))
        for phase in PHASES[1:5]:self.transition(phase)
        return self.snapshot()

    def feed_ack(self,family,lo,hi):
        current=self.snapshot()
        if current['phase']=='NOT_STARTED':return
        if family not in ('pump','pumpswap') or lo<1 or hi<lo:raise EvidenceUnavailable('prewarm_startup_feed_boundary')
        with self.writer.transaction():
            self.db.execute('INSERT OR IGNORE INTO prewarm_startup_feeds VALUES(?,?,?,?,?,NULL)',
                (current['session'],family,lo,hi,self.clock()))

    def native(self,families):
        current=self.snapshot()
        if current['phase']=='NOT_STARTED':return
        with self.writer.transaction():
            for family in families:self.db.execute('UPDATE prewarm_startup_feeds SET native_at=COALESCE(native_at,?) WHERE session=? AND family=?',
                (self.clock(),current['session'],family))

    def advance(self):
        current=self.snapshot()
        if current['phase'] in ('NOT_STARTED','STEADY_STATE','FAIL_CLOSED'):return current
        feeds=self.db.execute('SELECT family,lo,hi,ack_at,native_at FROM prewarm_startup_feeds WHERE session=?',(current['session'],)).fetchall()
        if len(feeds)!=2 or any(r[4] is None for r in feeds):return current
        if current['phase']=='START_ROLLING_FEEDS':
            self.transition('RECOVERY_OVERLAP',dict(feeds_connected_at=max(r[4] for r in feeds),
                required_intervals={f:[lo,hi] for f,lo,hi,_,_ in feeds}))
            self.transition('WAIT_FOR_DURABLE_PUBLICATION')
        from .solana_selective_runtime import CONTROL
        control=self.db.execute('SELECT MAX(hi) FROM coverage WHERE scope=? AND available<=?',(CONTROL,self.clock())).fetchone()[0]
        if control is None or control<max(r[2] for r in feeds):return self.snapshot()
        for family,lo,hi,_,_ in feeds:
            if self.history.rolling.missing(family,program_scope(family),lo,hi):return self.snapshot()
            if self.history.lifecycle.unconsumed(program_scope(family),through=hi):return self.snapshot()
        self.transition('VERIFY_CONTIGUOUS_COVERAGE',dict(coverage_verified_at=self.clock(),canonical_control_frontier=control))
        # Only an actual canonical normalized event supplies this milestone;
        # a quiet closed interval can release consumers without inventing one.
        first=self.db.execute('SELECT MIN(first_seen) FROM rolling_economic_events WHERE first_seen>=?',(current['started'],)).fetchone()[0]
        self.transition('RELEASE_CANDIDATE_CONSUMERS',dict(consumers_released_at=self.clock(),first_rolling_event_at=first))
        self.transition('STEADY_STATE',dict(steady_at=self.clock()))
        return self.snapshot()

    def fail(self,reason):
        if self.snapshot()['phase']!='NOT_STARTED':self.transition('FAIL_CLOSED',dict(failure=reason,legacy_fallback=False))
