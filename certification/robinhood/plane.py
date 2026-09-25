"""Crash-safe candidate identities, latest-state intents and fenced evidence commits.

SQLite transactions contain local state only. Provider operations run outside them.
Observation bodies never constitute authenticated evidence. Every decision is bound
both to its generation and to the exact evidence watermark and interpretation.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def process_identity():
    # Linux process start tick fences PID reuse, including a restarted worker.
    return f'{Path("/proc/sys/kernel/random/boot_id").read_text().strip()}:{os.getpid()}:{Path("/proc/self/stat").read_text().rsplit(")",1)[1].split()[19]}'


def alive(identity):
    try:
        boot, pid, start = identity.split(':')
        return (Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
                and Path(f'/proc/{int(pid)}/stat').read_text().rsplit(')',1)[1].split()[19] == start)
    except (OSError, ValueError, IndexError):
        return False


def plane_path(default):
    cache=os.environ.get('MM_CERTIFICATION_RPC_CACHE_DB')
    return Path(cache).with_suffix('.candidates.sqlite') if cache else Path(default)


class Plane:
    def __init__(self, path, *, clock=time.time):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.owner = process_identity()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA foreign_keys=ON')
        if self.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('candidate_store_integrity')
        version=self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0,1):raise ValueError('candidate_store_schema')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS candidates(
          id TEXT PRIMARY KEY,lane TEXT NOT NULL,generation INTEGER NOT NULL,
          interpretation TEXT NOT NULL,latest_id TEXT NOT NULL,observed REAL NOT NULL,
          ordering TEXT NOT NULL,desired TEXT NOT NULL,completed TEXT,
          payload TEXT NOT NULL,state TEXT NOT NULL,reason TEXT,pending INTEGER NOT NULL,
          priority INTEGER NOT NULL,rank REAL NOT NULL,deadline REAL NOT NULL,queued REAL NOT NULL,
          claim TEXT,owner TEXT,claim_generation INTEGER,claim_until REAL,result TEXT);
        CREATE INDEX IF NOT EXISTS candidate_pending ON candidates(lane,pending,priority,deadline);
        CREATE TABLE IF NOT EXISTS observations(
          candidate TEXT NOT NULL,observation TEXT NOT NULL,body TEXT NOT NULL,at REAL NOT NULL,
          PRIMARY KEY(candidate,observation));
        CREATE TABLE IF NOT EXISTS transitions(
          seq INTEGER PRIMARY KEY,candidate TEXT,generation INTEGER,at REAL,kind TEXT,
          reason TEXT,watermark TEXT,interpretation TEXT,details TEXT);
        CREATE TABLE IF NOT EXISTS evidence(
          namespace TEXT,key TEXT,body TEXT,provenance TEXT,created REAL,
          PRIMARY KEY(namespace,key));
        CREATE TABLE IF NOT EXISTS rolling(
          candidate TEXT,identity TEXT,at INTEGER,block INTEGER,body TEXT,provenance TEXT,
          PRIMARY KEY(candidate,identity));
        CREATE TABLE IF NOT EXISTS service(lane TEXT,seconds REAL,logical INTEGER,physical INTEGER,at REAL);
        CREATE TABLE IF NOT EXISTS runtime(key TEXT PRIMARY KEY,body TEXT);
        CREATE TABLE IF NOT EXISTS result_consumption(candidate TEXT,generation INTEGER,at REAL,
          PRIMARY KEY(candidate,generation));
        CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON transitions
          BEGIN SELECT RAISE(ABORT,'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON transitions
          BEGIN SELECT RAISE(ABORT,'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS observations_no_update BEFORE UPDATE ON observations
          BEGIN SELECT RAISE(ABORT,'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS observations_no_delete BEFORE DELETE ON observations
          BEGIN SELECT RAISE(ABORT,'append_only'); END;
        PRAGMA user_version=1;
        ''')
        self.recover()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def _row(self, key):
        row=self.db.execute('SELECT * FROM candidates WHERE id=?',(key,)).fetchone()
        return dict(row) if row else None

    def get(self,key):
        with self.lock:return self._row(key)

    def _audit(self,row,kind,reason=None,**details):
        self.db.execute('INSERT INTO transitions(candidate,generation,at,kind,reason,watermark,interpretation,details) VALUES(?,?,?,?,?,?,?,?)',
            (row['id'],row['generation'],self.clock(),kind,reason,row['desired'],row['interpretation'],canonical(details)))

    def observe(self, key, lane, observation, payload, *, ordering, watermark,
                interpretation, observed, deadline, priority, rank=0, needs_work=True):
        if lane not in ('pons','ramses') or not key or not observation:raise ValueError('candidate_identity')
        if not 0<=priority<=5 or not all(math.isfinite(x) for x in (observed,rank)) or (deadline is not None and not math.isfinite(deadline)):
            raise ValueError('candidate_schedule')
        deadline=math.inf if deadline is None else deadline
        body=canonical(payload); target=canonical(watermark); policy=canonical(interpretation)
        ordering=tuple(ordering)
        with self.transaction():
            row=self._row(key)
            if row and row['interpretation']!=policy:raise ValueError('candidate_interpretation_changed')
            duplicate=self.db.execute('SELECT body FROM observations WHERE candidate=? AND observation=?',(key,observation)).fetchone()
            if duplicate:
                if duplicate[0]!=body:
                    if row:
                        self.db.execute("UPDATE candidates SET state='authoritative_evidence_failure',reason='conflicting_observation',pending=0,generation=generation+1 WHERE id=?",(key,))
                        self._audit(self._row(key),'authoritative_evidence_failure','conflicting_observation',observation=observation,conflict_digest=digest(payload))
                    return 'conflict'
                # Redelivery never refreshes an observation's deadline.
                return 'duplicate'
            self.db.execute('INSERT INTO observations VALUES(?,?,?,?)',(key,observation,body,observed))
            if row and row['interpretation']!=policy:raise ValueError('candidate_interpretation_changed')
            if row and row['reason']=='conflicting_observation':
                self._audit(row,'watching','unresolved_observation_conflict',observation=observation)
                return 'conflict'
            if row and ordering<=tuple(json.loads(row['ordering'])):
                self._audit(row,'superseded','out_of_order_observation',observation=observation)
                return 'older'
            if not row:
                self.db.execute('''INSERT INTO candidates(id,lane,generation,interpretation,latest_id,observed,ordering,desired,payload,state,pending,priority,rank,deadline,queued)
                  VALUES(?,?,1,?,?,?,?,?,?,'discovered',?,?,?,?,?)''',
                  (key,lane,policy,observation,observed,canonical(ordering),target,body,int(needs_work),priority,rank,deadline,observed))
                row=self._row(key);self._audit(row,'discovered',observation=observation)
                return 'created'
            if row['pending'] or row['claim']:
                self._audit(row,'superseded','newer_candidate_state',next_observation=observation)
            self.db.execute('''UPDATE candidates SET generation=generation+1,latest_id=?,observed=?,ordering=?,desired=?,payload=?,
              state='watching',reason=NULL,pending=?,priority=?,rank=?,deadline=?,queued=?,result=NULL WHERE id=?''',
              (observation,observed,canonical(ordering),target,body,int(needs_work),min(priority,row['priority']) if row['priority']<=1 else priority,rank,deadline,row['queued'] if row['pending'] or row['claim'] else observed,key))
            self._audit(self._row(key),'watching','latest_state_coalesced',observation=observation)
            return 'updated'

    def recover(self):
        with self.transaction():
            for raw in self.db.execute('SELECT * FROM candidates WHERE claim IS NOT NULL').fetchall():
                row=dict(raw)
                if not alive(row['owner']) or row['claim_until']<=self.clock():
                    self.db.execute('UPDATE candidates SET claim=NULL,owner=NULL,claim_generation=NULL,claim_until=NULL WHERE id=?',(row['id'],))
                    self._audit(row,'watching','interrupted_work_recovered')

    def estimate(self,lane,*,provider_interval,queued_transports=0,cooldown_seconds=0):
        # A physical first request is the minimum defensible cold-start estimate.
        # Thereafter use the measured p95 end-to-end service, never invented timing.
        with self.lock:
            rows=self.db.execute('SELECT seconds FROM service WHERE lane=? ORDER BY at DESC LIMIT 128',(lane,)).fetchall()
        values=sorted(r[0] for r in rows)
        service=values[math.ceil(.95*len(values))-1] if values else provider_interval
        return max(provider_interval,service)+queued_transports*provider_interval+max(0,cooldown_seconds)

    def claim(self, *, lane=None, key=None, estimate_seconds=0):
        self.recover()
        now=self.clock()
        with self.transaction():
            rows=[dict(r) for r in self.db.execute('SELECT * FROM candidates WHERE pending=1 AND claim IS NULL'+(' AND lane=?' if lane else ''),((lane,) if lane else ())).fetchall()]
            if key is not None:rows=[r for r in rows if r["id"]==key]
            def order(r):
                # Aging applies only below entry confirmation. Safety stays first.
                span=(max(.001,r['deadline']-r['observed']) if math.isfinite(r['deadline'])
                      else self.estimate(r['lane'],provider_interval=.5))
                rounds=int(max(0,now-r['queued'])/span) if r['priority']>1 else 0
                aged=max(2,r['priority']-rounds) if r['priority']>1 else r['priority']
                return (aged,-rounds,r['deadline'],-r['rank'],-r['observed'],r['queued'],r['id'])
            for row in sorted(rows,key=order):
                if row['deadline']<=now:
                    state,reason='freshness_deadline_censored','original_deadline_expired'
                elif now+estimate_seconds>=row['deadline']:
                    state,reason='provider_capacity_defer','measured_service_exceeds_remaining_slack'
                else:
                    token=uuid.uuid4().hex
                    self.db.execute("UPDATE candidates SET claim=?,owner=?,claim_generation=generation,claim_until=?,state='canonical_evidence_requested' WHERE id=?",
                        (token,self.owner,row['deadline'],row['id']))
                    row=self._row(row['id']);self._audit(row,'canonical_evidence_requested',estimate_seconds=estimate_seconds)
                    return row
                self.db.execute('UPDATE candidates SET pending=0,state=?,reason=? WHERE id=?',(state,reason,row['id']))
                self._audit(row,state,reason,estimate_seconds=estimate_seconds)
        return None

    def current(self,work):
        row=self.get(work['id'])
        return bool(row and row['generation']==work['generation'] and row['claim']==work['claim'] and row['desired']==work['desired'] and self.clock()<row['deadline'])

    def finish(self,work,*,result=None,state='canonical_evidence_complete',reason=None,logical=None,physical=None,seconds=None):
        with self.transaction():
            row=self._row(work['id'])
            if (not row or row['claim']!=work['claim'] or row['generation']!=work['generation'] or row['desired']!=work['desired']):
                if row:
                    self._audit(work,'superseded','obsolete_completion')
                    self.db.execute('UPDATE candidates SET claim=NULL,owner=NULL,claim_until=NULL WHERE id=? AND claim=?',(work['id'],work['claim']))
                return False
            if self.clock()>=row['deadline']:
                state,reason,result='freshness_deadline_censored','completion_after_original_deadline',None
            completed=row['desired'] if state=='canonical_evidence_complete' else row['completed']
            self.db.execute('''UPDATE candidates SET completed=?,result=?,state=?,reason=?,pending=0,claim=NULL,owner=NULL,claim_until=NULL WHERE id=?''',
                (completed,canonical(result) if result is not None else None,state,reason,row['id']))
            self._audit(row,state,reason,logical_authenticated_reads=logical,physical_requests=physical)
            if seconds is not None and math.isfinite(seconds) and seconds>=0:
                self.db.execute('INSERT INTO service VALUES(?,?,?,?,?)',(row['lane'],seconds,logical,physical,self.clock()))
                self.db.execute('DELETE FROM service WHERE rowid NOT IN (SELECT rowid FROM service ORDER BY at DESC LIMIT 256)')
            return state=='canonical_evidence_complete'

    def promote(self,work):
        with self.transaction():
            row=self._row(work['id'])
            if not row or row['generation']!=work['generation'] or row['claim']!=work['claim']:return False
            self.db.execute("UPDATE candidates SET priority=MIN(priority,2) WHERE id=?",(row['id'],))
            self._audit(row,'promoted','authenticated_current_state_interest')
            return True

    def decision(self,key,generation,state,reason=None,**details):
        with self.transaction():
            row=self._row(key)
            if not row or row['generation']!=generation or row['completed']!=row['desired']:return False
            if state in ('qualified','entry_confirmation','entry_reserved') and self.clock()>=row['deadline']:return False
            self.db.execute('UPDATE candidates SET state=?,reason=?,priority=? WHERE id=?',(state,reason,1 if state=='entry_confirmation' else row['priority'],key))
            self._audit(row,state,reason,**details)
            return True

    def unconsumed(self,lane):
        """Durable outbox; callers acknowledge only after checkpointing effects."""
        with self.lock:
            return [dict(r) for r in self.db.execute("""SELECT c.* FROM candidates c
              LEFT JOIN result_consumption a ON c.id=a.candidate AND c.generation=a.generation
              WHERE c.lane=? AND c.result IS NOT NULL AND c.completed=c.desired
                AND a.candidate IS NULL ORDER BY c.priority,c.deadline,c.id""",(lane,))]

    def consume(self,key,generation):
        with self.transaction():
            row=self._row(key)
            if not row or row['generation']!=generation or row['completed']!=row['desired']:return False
            self.db.execute('INSERT OR IGNORE INTO result_consumption VALUES(?,?,?)',(key,generation,self.clock()))
            return True

    def put(self,namespace,key,value,provenance):
        body=canonical(value);proof=canonical(provenance)
        with self.transaction():
            old=self.db.execute('SELECT body,provenance FROM evidence WHERE namespace=? AND key=?',(namespace,key)).fetchone()
            if old and (old[0]!=body or old[1]!=proof):raise ValueError('canonical_evidence_conflict')
            self.db.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?)',(namespace,key,body,proof,self.clock()))

    def evidence(self,namespace,key):
        with self.lock:
            row=self.db.execute('SELECT body,provenance FROM evidence WHERE namespace=? AND key=?',(namespace,key)).fetchone()
        return (json.loads(row[0]),json.loads(row[1])) if row else None

    def rolling_put(self,candidate,identity,at,block,value,provenance,*,retention_seconds=60,limit=400):
        # Exact normalized authenticated events, never public observation fields.
        if provenance.get('authority')!='authenticated_receipt_header':raise ValueError('rolling_authority')
        with self.transaction():
            body=canonical(value);proof=canonical(provenance)
            old=self.db.execute('SELECT body,provenance FROM rolling WHERE candidate=? AND identity=?',(candidate,identity)).fetchone()
            if old and tuple(old)!=(body,proof):raise ValueError('rolling_evidence_conflict')
            self.db.execute('INSERT OR IGNORE INTO rolling VALUES(?,?,?,?,?,?)',(candidate,identity,at,block,body,proof))
            newest=self.db.execute('SELECT MAX(at) FROM rolling WHERE candidate=?',(candidate,)).fetchone()[0]
            self.db.execute('DELETE FROM rolling WHERE candidate=? AND at<?',(candidate,newest-retention_seconds))
            self.db.execute('DELETE FROM rolling WHERE candidate=? AND rowid NOT IN (SELECT rowid FROM rolling WHERE candidate=? ORDER BY at DESC,block DESC,identity DESC LIMIT ?)',(candidate,candidate,limit))

    def rolling_get(self,candidate,identity,provenance):
        with self.lock:
            row=self.db.execute('SELECT body,provenance FROM rolling WHERE candidate=? AND identity=?',(candidate,identity)).fetchone()
        if row and row[1]!=canonical(provenance):raise ValueError('rolling_provenance_conflict')
        return json.loads(row[0]) if row else None

    def checkpoint(self,key,value):
        with self.transaction():
            self.db.execute('INSERT INTO runtime VALUES(?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body',(key,canonical(value)))

    def checkpoint_read(self,key):
        with self.lock:
            row=self.db.execute('SELECT body FROM runtime WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None

    def snapshot(self,lane=None):
        with self.lock:
            rows=self.db.execute('SELECT state,COUNT(*) n FROM candidates'+(' WHERE lane=?' if lane else '')+' GROUP BY state',((lane,) if lane else ())).fetchall()
            clause=' WHERE candidate IN (SELECT id FROM candidates WHERE lane=?)' if lane else ''
            params=(lane,) if lane else ()
            events=self.db.execute('SELECT kind,COUNT(*) n FROM transitions'+clause+' GROUP BY kind',params).fetchall()
            observations=self.db.execute('SELECT COUNT(*) FROM observations'+clause,params).fetchone()[0]
        return dict(unique_candidates=sum(r['n'] for r in rows),candidate_states={r['state']:r['n'] for r in rows},observation_events=observations,transition_events={r['kind']:r['n'] for r in events})

    def close(self):
        with self.lock:self.db.close()


def project_native_position(path,lane,candidate_id,position,*,ledger_path,policy):
    """Post-commit projection. Native accounting remains the sole authority.

    This evidence is independently versioned: an exit for a held position is
    never discarded because discovery advanced the candidate generation.
    """
    plane=Plane(path)
    try:
        native_id=position['id'];version=position['version']
        proof=dict(lane=lane,policy=policy,native_ledger=str(ledger_path),schema=1)
        with plane.transaction():
            key='native_position:'+lane+':'+native_id
            raw=plane.db.execute('SELECT body FROM runtime WHERE key=?',(key,)).fetchone()
            old=json.loads(raw[0]) if raw else None
            value=dict(candidate=candidate_id,position=position,provenance=proof,
                priority=0 if position['status']!='settled' else None)
            if old:
                prior=old['position']
                if version<prior['version']:return
                if version==prior['version']:
                    if old!=value:raise ValueError('native_position_projection_conflict')
                    return
            plane.db.execute('INSERT INTO runtime VALUES(?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body',(key,canonical(value)))
            row=plane._row(candidate_id)
            if row:
                kind={'reserved':'entry_reserved','open':'entry_filled','settled':'settled'}.get(position['status'],'position_safety')
                # Repeated open monitor states are position updates, not fills.
                if kind=='entry_filled' and old and old['position']['status'] in ('open','exit_pending'):kind='position_safety'
                plane._audit(row,kind,native_position=native_id,native_version=version,
                    authority='native_paper_ledger',ledger_path=str(ledger_path),position_digest=digest(position))
    finally:plane.close()
