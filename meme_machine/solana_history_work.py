"""Pump history planning on committed facts, outside the canonical SQL owner.

One isolated, CPU-bounded worker leaves the existing native/archive pool intact. The
canonical owner alone creates obligations, verifies inputs, and publishes the
original RollingHistory.prepare mutations. No provider or capital authority.
"""
from .runtime.operation_costs import measured

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from .solana_evidence_plane import EvidenceUnavailable,canonical,digest
from .solana_selective_history import SelectiveHistory,coverage_points
from .solana_rolling_history import RollingHistory,MODEL_B,program_scope
from .runtime.sqlite_failure import connect as diagnostic_connect

INPUT_BYTES=16*1024*1024
READ_SECONDS=.1
WORK_SECONDS=30
VERSION='pump-history-work-v1'
_PROOF_CACHE=OrderedDict() # Per worker, original eight-entry / 512-KiB bound.
SCHEMA='''
CREATE TABLE IF NOT EXISTS rolling_preparation_jobs(
 id TEXT PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL,
 priority INTEGER NOT NULL,deadline REAL NOT NULL,status TEXT NOT NULL,
 token TEXT,lease_until REAL,retry_at REAL NOT NULL,attempts INTEGER NOT NULL,
 created REAL NOT NULL,updated REAL NOT NULL,result_hash TEXT);
CREATE INDEX IF NOT EXISTS rolling_preparation_dispatch
 ON rolling_preparation_jobs(status,retry_at,priority,deadline,created);
CREATE INDEX IF NOT EXISTS rolling_preparation_expiry ON rolling_preparation_jobs(status,deadline);
CREATE INDEX IF NOT EXISTS rolling_preparation_candidate ON rolling_preparation_jobs(
 json_extract(body,'$.family'),json_extract(body,'$.address'),json_extract(body,'$.lo'),deadline,status);
CREATE TABLE IF NOT EXISTS rolling_history_versions(scope TEXT PRIMARY KEY,version INTEGER NOT NULL);
'''


def enabled():
    value=os.environ.get('MM_SOLANA_HISTORY_SEPARATED','0')
    if value not in ('0','1'):raise EvidenceUnavailable('historical_processing_configuration')
    return value=='1'


def dependency_stamp(rolling,spec,*,as_of=None):
    """Indexed dependency metadata, never decompression or an entry verdict.

    Revision triggers detect even an in-place rewrite with an unchanged hash.
    Exact financial consumers still run their original fresh completeness checks.
    """
    from .lanes.pump.pump_acceleration_strategy import policy_hash
    from .lanes.pump.pumpswap_survivor import POLICY_HASH
    h=rolling.history;db=rolling.db;family,address,lo,hi=(spec[k] for k in ('family','address','lo','hi'))
    scope=h.scope_for(family,address)
    binding=db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
    market=address if binding is None else binding[0]
    origin=db.execute('SELECT lower_slot,receipt FROM rolling_origins WHERE family=? AND address=?',(family,market)).fetchone()
    observed=db.execute('SELECT first_slot FROM candidate_lifecycle WHERE family=? AND address=?',(family,address)).fetchone()
    scopes=rolling.scopes(family,scope)
    versions=[(s,db.execute('SELECT version FROM rolling_history_versions WHERE scope=?',(s,)).fetchone()) for s in scopes]
    future=max((db.execute('SELECT COALESCE(MAX(last_available),0) FROM candidate_coverage WHERE scope=? AND hi>=? AND lo<=?',
        (s,lo,hi)).fetchone()[0] for s in scopes),default=0)
    from .solana_history_delivery import generation
    return digest([VERSION,policy_hash(),POLICY_HASH,spec,binding,origin,observed,versions,
        db.execute('SELECT MIN(lo) FROM candidate_coverage WHERE scope=?',(program_scope(family),)).fetchone(),
        db.execute('SELECT deadline,priority FROM rolling_publication_waits WHERE family=? AND address=? AND lo=? AND hi=?',
            (family,address,origin[0] if family=='pump' and lo==0 and origin else lo,hi)).fetchone(),
        generation(h.lifecycle),min(h.clock() if as_of is None else as_of,future)])


def capture(rolling,spec):
    """Only indexed reads/copying. Proof decompression starts after DB close."""
    h=rolling.history;db=rolling.db
    family,address,lo,hi=(spec[k] for k in ('family','address','lo','hi'))
    scope=h.scope_for(family,address)
    binding=db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',
        (family,address)).fetchone()
    market=address if binding is None else binding[0]
    origin=db.execute('SELECT lower_slot,receipt FROM rolling_origins WHERE family=? AND address=?',
        (family,market)).fetchone()
    observed=db.execute('SELECT first_slot FROM candidate_lifecycle WHERE family=? AND address=?',
        (family,address)).fetchone()
    start=db.execute('SELECT MIN(lo) FROM candidate_coverage WHERE scope=?',(program_scope(family),)).fetchone()[0]
    session=db.execute('SELECT session FROM prewarm_startup WHERE id=1').fetchone()
    provider=db.execute("SELECT value FROM service_health WHERE key='provider'").fetchone()
    filename=next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main')
    stat=Path(filename).stat()
    generation=(session,None if provider is None else json.loads(provider[0]),stat.st_dev,stat.st_ino)
    resolved_lo=origin[0] if family=='pump' and lo==0 and origin else lo
    prior=db.execute('SELECT deadline,priority FROM rolling_publication_waits WHERE family=? AND address=? AND lo=? AND hi=?',
        (family,address,resolved_lo,hi)).fetchone()
    queries=[]
    if family=='pump' and lo==0 and not origin:
        slot=hi if observed is None else observed[0]
        if start is None or slot>=start:
            queries.append(rolling.missing_inputs(family,program_scope(family),slot,slot))
    queries.append(rolling.missing_inputs(family,scope,resolved_lo,hi))
    scopes=rolling.scopes(family,scope)
    frontier=db.execute('SELECT MAX(hi) FROM candidate_coverage WHERE scope IN ('+','.join('?' for _ in scopes)+')',scopes).fetchone()[0]
    # Publication after the requested upper bound cannot invalidate an older
    # request merely because the global program frontier continues advancing.
    frontier=None if frontier is None else min(frontier,hi)
    result=dict(scope=scope,binding=binding,origin=origin,observed=observed,start=start,
        generation=generation,prior=prior,frontier=frontier,queries=queries)
    size=sum(len(packed) for q in queries for b in q['branches'] for _,_,packed,_ in b['rows'])
    if size>INPUT_BYTES:raise EvidenceUnavailable('historical_input_capacity')
    return result


class CPUBudget:
    """Bound optional work's CPU duty without sleeping in the canonical owner."""
    def __init__(self,fraction,*,wall=WORK_SECONDS):
        self.cpu=time.process_time();self.started=time.monotonic()
        self.fraction=fraction;self.wall=wall
    def __call__(self):
        if time.monotonic()-self.started>self.wall:
            raise EvidenceUnavailable('historical_worker_deadline')
        delay=(time.process_time()-self.cpu)/self.fraction-(time.monotonic()-self.started)
        while delay>0:
            time.sleep(min(delay,.02))
            if time.monotonic()-self.started>self.wall:
                raise EvidenceUnavailable('historical_worker_deadline')
            delay=(time.process_time()-self.cpu)/self.fraction-(time.monotonic()-self.started)


def prepare_history(path,job):
    """Restartable, provider-free worker; never open a writable DB connection."""
    if job['spec'].get('kind')=='cold_restore':
        from .solana_history_restore import prepare
        return prepare(path,job)
    started=time.monotonic();cpu=time.process_time()
    at=job['as_of'];spec=job['spec']
    rolling=RollingHistory.__new__(RollingHistory)
    history=SelectiveHistory.__new__(SelectiveHistory)
    rolling.history=history;history.rolling=rolling;history.clock=lambda:at
    rolling._history_input_byte_limit=INPUT_BYTES
    rolling._coverage_span_cache=_PROOF_CACHE
    with closing(diagnostic_connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,
            diagnostic_role='historian.prepare_read',timeout=.1,isolation_level=None)) as db:
        history.db=rolling.db=db
        db.execute('PRAGMA query_only=ON')
        until=time.monotonic()+READ_SECONDS
        db.set_progress_handler(lambda:int(time.monotonic()>until),1000)
        db.execute('BEGIN')
        snapshot=capture(rolling,spec)
        db.execute('ROLLBACK')
    read_seconds=time.monotonic()-started
    # No SQLite snapshot or lock survives the potentially slow calculation.
    history.db=rolling.db=None
    budget=CPUBudget(.75 if job['priority']<=2 else .25)
    rolling._history_cpu_budget=budget
    queries=[]
    for inputs in snapshot['queries']:
        queries.append((inputs['requested'],rolling.missing_from_inputs(inputs)))
        budget()
    return dict(id=job['id'],token=job['token'],spec=spec,snapshot=snapshot,
        queries=queries,result_hash=digest(queries),
        metrics=dict(read_seconds=read_seconds,wall_seconds=time.monotonic()-started,
            cpu_seconds=time.process_time()-cpu,proof_points_decoded=getattr(rolling,'_history_decoded_points',0),
            proof_fragments_read=sum(len(b['rows']) for q in snapshot['queries'] for b in q['branches'])))


def _worker_limits():
    # Isolated from the original native/archive pool and canonical process.
    # These are physical per-process bounds, never cumulative usage limits.
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(512*1024**2,512*1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
    os.nice(5)


def _isolated_worker_limits():
    from .runtime.isolated_native_execution import install_isolated_native_execution
    install_isolated_native_execution()
    _worker_limits()


class HistoryExecutor:
    """A crash replaces only this one lazy worker, never canonical intake."""
    def __init__(self,*,native_resources=None):
        if native_resources is not None:
            from .runtime.isolated_native_resources import require_resources
            require_resources(native_resources)
        self.pool=None
        self._isolated=native_resources is not None
    def submit(self,fn,*args):
        if self.pool is not None and getattr(self.pool,'_broken',False):
            self.pool.shutdown(wait=True,cancel_futures=True);self.pool=None
        if self.pool is None:
            if self._isolated:
                from .runtime.isolated_native_executor import IsolatedSpawnExecutor
                self.pool=IsolatedSpawnExecutor(max_workers=1,
                    initializer=_isolated_worker_limits,role='history')
            else:
                self.pool=ProcessPoolExecutor(max_workers=1,
                    mp_context=multiprocessing.get_context('spawn'),initializer=_worker_limits)
        return self.pool.submit(fn,*args)
    def close(self):
        if self.pool is not None:self.pool.shutdown(wait=True,cancel_futures=True);self.pool=None


def compatible(old,new):
    """Reject reorgs/rebinding/deletion; accept verified monotone publication.

    Identical older fragments need only a fresh byte hash. If the current final
    fragment appended, compare its exact old point prefix (at most 256 points),
    never repeat the entire historical proof calculation in the owner.
    """
    for key in ('scope','binding','origin','observed','start','generation','prior'):
        if old[key]!=new[key]:return False
    if old['frontier'] is not None and (new['frontier'] is None or new['frontier']<old['frontier']):return False
    if len(old['queries'])!=len(new['queries']):return False
    for before,after in zip(old['queries'],new['queries'],strict=True):
        if any(before[k]!=after[k] for k in ('requested','lo','hi')):return False
        if len(before['branches'])!=len(after['branches']):return False
        for a,b in zip(before['branches'],after['branches'],strict=True):
            if any(a[k]!=b[k] for k in ('scope','floor','gaps')):return False
            current={lo:(hi,packed,checksum) for lo,hi,packed,checksum in b['rows']}
            for lo,hi,packed,checksum in a['rows']:
                row=current.get(lo)
                if row is None:return False
                new_hi,new_packed,new_checksum=row
                if hashlib.sha256(new_packed).hexdigest()!=new_checksum:
                    raise EvidenceUnavailable('historical_current_proof_corrupt')
                if (hi,packed,checksum)==row:continue
                points=coverage_points(packed,checksum)
                if len(points)>256 or new_hi<hi:return False
                extended=coverage_points(new_packed,new_checksum)
                if extended[:len(points)]!=points:return False
            # New independently authenticated coverage can only improve an old
            # conservative plan; current gaps and every existing point above
            # are still checked. Dispatch rechecks all missing intervals afresh.
    return True


class HistoricalTasks:
    """Durable obligations, one lease, bounded immutable in-flight memory."""
    def __init__(self,history):
        self.history=history;self.db=history.db;self.writer=history.writer
        for statement in SCHEMA.split(';'):
            if statement.strip():self.db.execute(statement)
        columns={r[1] for r in self.db.execute('PRAGMA table_info(rolling_preparation_jobs)')}
        for name in ('dependency','metric','metric_hash'):
            if name not in columns:self.db.execute('ALTER TABLE rolling_preparation_jobs ADD COLUMN '+name+' TEXT')
        for table in ('candidate_coverage','candidate_gaps'):
            for action in ('INSERT','UPDATE','DELETE'):
                side='OLD' if action=='DELETE' else 'NEW'
                self.db.execute('CREATE TRIGGER IF NOT EXISTS history_revision_'+table+'_'+action+' AFTER '+action+' ON '+table+''' BEGIN
                    INSERT INTO rolling_history_versions VALUES('''+side+'''.scope,1)
                    ON CONFLICT(scope) DO UPDATE SET version=version+1;
                    '''+('INSERT INTO rolling_history_versions SELECT OLD.scope,1 WHERE OLD.scope!=NEW.scope ON CONFLICT(scope) DO UPDATE SET version=version+1;' if action=='UPDATE' else '')+' END')
        # The sole owner is recreated after a source restart; no former process
        # can publish its result through this new actor. Keep original deadlines.
        self.db.execute("UPDATE rolling_preparation_jobs SET status='pending',token=NULL,lease_until=NULL WHERE status='active'")

    @property
    def clock(self):return self.history.clock

    @measured('owner.history_enqueue')
    def enqueue(self,family,address,lo,hi,*,deadline,priority=4,reason=None):
        if family not in ('pump','pumpswap') or family not in self.history.active_families:
            raise EvidenceUnavailable('historical_family')
        if (type(lo) is not int or type(hi) is not int or not 0<=lo<=hi
                or type(priority) is not int or not 0<=priority<=6):
            raise EvidenceUnavailable('candidate_history_request_shape')
        spec=dict(family=family,address=address,lo=lo,hi=hi,reason=reason)
        identity=digest([family,address,lo,hi]);raw=canonical(spec);now=self.clock()
        prior=self.db.execute('SELECT id,status,priority,deadline,dependency,metric,metric_hash FROM rolling_preparation_jobs WHERE id=?',(identity,)).fetchone()
        if prior is None:
            prior=self.db.execute("""SELECT id,status,priority,deadline,dependency,metric,metric_hash FROM rolling_preparation_jobs
                WHERE json_extract(body,'$.family')=? AND json_extract(body,'$.address')=? AND json_extract(body,'$.lo')=?
                AND deadline<=? AND status='complete' AND json_extract(body,'$.hi')=? ORDER BY updated DESC LIMIT 1""",
                (family,address,lo,deadline,hi)).fetchone()
        if prior:identity=prior[0];prior=prior[1:]
        if prior and prior[0]=='complete' and prior[1]<=priority and prior[2]<=deadline:
            if prior[3]==dependency_stamp(self.history.rolling,spec):
                if hashlib.sha256(prior[4].encode()).hexdigest()!=prior[5]:raise EvidenceUnavailable('historical_metric_corrupt')
                return json.loads(prior[4])
        # A not-yet-started request can cover a newer upper bound for the same
        # candidate and original deadline. It retains every earlier slot and
        # leaves original publication/boundary waits durable. Active jobs and
        # independent regimes are never overwritten.
        pending=self.db.execute("""SELECT id,body,priority,deadline FROM rolling_preparation_jobs
            WHERE json_extract(body,'$.family')=? AND json_extract(body,'$.address')=?
            AND json_extract(body,'$.lo')=? AND deadline=? AND status='pending'
            AND json_extract(body,'$.kind') IS NULL ORDER BY created LIMIT 1""",
            (family,address,lo,deadline)).fetchone()
        if pending:
            previous=json.loads(pending[1])
            if previous['reason']==reason:
                identity=pending[0];spec['hi']=max(hi,previous['hi']);raw=canonical(spec)
                if raw==pending[1] and pending[2]<=priority:return self.pending_metric(identity,deadline)
        with self.writer.transaction():
            self.db.execute("""INSERT OR IGNORE INTO rolling_preparation_jobs
                (id,body,hash,priority,deadline,status,token,lease_until,retry_at,attempts,created,updated,result_hash)
                VALUES(?,?,?,?,?,'pending',NULL,NULL,0,0,?,?,NULL)""",
                (identity,raw,digest(spec),priority,deadline,now,now))
            # Same obligation/lease, never another job or a fresh deadline.
            self.db.execute("""UPDATE rolling_preparation_jobs SET
                priority=MIN(priority,?),deadline=MIN(deadline,?),
                body=CASE WHEN status='active' THEN body ELSE ? END,
                hash=CASE WHEN status='active' THEN hash ELSE ? END,
                status=CASE WHEN status='complete' THEN 'pending' ELSE status END,
                updated=? WHERE id=?""",(priority,deadline,raw,digest(spec),now,identity))
        return self.pending_metric(identity,deadline)

    def pending_metric(self,identity,deadline):
        return dict(model=MODEL_B,history_already_complete_at_promotion=False,
            missing_intervals=None,backfill_jobs=[],boundary_state='HISTORICAL_PLANNING_PENDING',
            decision_deadline=deadline,entry_authority=False,historical_job=identity)

    @measured('owner.reactivation_cold')
    def cold_ready(self,family,address,*,epoch,deadline):
        from .solana_history_restore import metadata
        if metadata(self.history,family,address) is None:return True
        spec=dict(kind='cold_restore',family=family,address=address,lo=0,hi=0,epoch=epoch,reason=None)
        identity=digest(['cold_restore',family,address,epoch]);raw=canonical(spec);now=self.clock()
        with self.writer.transaction():
            self.db.execute("""INSERT OR IGNORE INTO rolling_preparation_jobs
                (id,body,hash,priority,deadline,status,token,lease_until,retry_at,attempts,created,updated,result_hash)
                VALUES(?,?,?,3,?,'pending',NULL,NULL,0,0,?,?,NULL)""",
                (identity,raw,digest(spec),deadline,now,now))
        return False

    def missing_for_dispatch(self,job):
        """Reuse only the exact current, verified local plan before paid reads.

        This is acquisition scheduling, never qualification authority. A stale
        or absent plan becomes an off-owner obligation, not a presumed gap.
        """
        candidates=self.db.execute("""SELECT body,dependency,metric,metric_hash FROM rolling_preparation_jobs
            WHERE json_extract(body,'$.family')=? AND json_extract(body,'$.address')=? AND status='complete'
            AND json_extract(metric,'$.lower_slot')<=? AND json_extract(metric,'$.upper_slot')>=?
            ORDER BY updated DESC LIMIT 1""",(job['family'],job['address'],job['lo'],job['hi'])).fetchone()
        if candidates:
            body,stamp,raw,checksum=candidates;spec=json.loads(body)
            if stamp==dependency_stamp(self.history.rolling,spec):
                if hashlib.sha256(raw.encode()).hexdigest()!=checksum:raise EvidenceUnavailable('historical_metric_corrupt')
                gaps=json.loads(raw).get('missing_intervals')
                if gaps is not None:return [(max(lo,job['lo']),min(hi,job['hi'])) for lo,hi in gaps if lo<=job['hi'] and hi>=job['lo']]
        self.enqueue(job['family'],job['address'],job['lo'],job['hi'],deadline=job['deadline'],priority=job['priority'])
        return None

    def resume_waits(self,table,*,limit,after):
        boundary=table=='rolling_boundary_waits'
        columns=('family,address,observed_slot,upper_slot,deadline,priority,created' if boundary
            else 'family,address,lo,hi,deadline,priority')
        rows=self.history.rolling.pending_slice(table,columns,limit=limit,after=after)
        with self.writer.transaction():
            for row in rows:
                _,family,address,lo,hi,deadline,priority,*created=row
                if family not in ('pump','pumpswap'):continue
                if self.clock()>=deadline:
                    fields=dict(family=family,address=address,deadline=deadline,deadline_reset=False)
                    if boundary:fields.update(observed_slot=lo,created=created[0])
                    else:fields.update(lo=lo,hi=hi)
                    self.history._observation(None,'boundary_deadline_missed' if boundary else 'publication_deadline_missed',fields)
                    self.db.execute('UPDATE '+table+" SET status='deadline_missed' WHERE rowid=?",(row[0],))
                elif priority<=2:
                    # Original urgent completeness checks cannot queue behind
                    # unrelated optional CPU work. Protection retains its path.
                    metric=self.history.rolling.prepare(family,address,0 if boundary else lo,hi,deadline=deadline,priority=priority)
                    if not metric.get('boundary_state') and (boundary or not metric['missing_intervals']):
                        self.db.execute('UPDATE '+table+" SET status='resolved' WHERE rowid=?",(row[0],))
                else:self.enqueue(family,address,0 if boundary else lo,hi,deadline=deadline,priority=priority)
        return rows[-1][0] if rows else 0

    def claim(self):
        now=self.clock()
        with self.writer.transaction():
            self.db.execute("UPDATE rolling_preparation_jobs SET status='pending',token=NULL WHERE status='active' AND lease_until<=?",(now,))
            expired=self.db.execute("SELECT id,deadline FROM rolling_preparation_jobs WHERE status='pending' AND deadline<=? ORDER BY deadline,id LIMIT 16",(now,)).fetchall()
            for identity,deadline in expired:
                self.db.execute("UPDATE rolling_preparation_jobs SET status='deadline_missed',updated=? WHERE id=?",(now,identity))
                self.history._observation(identity,'historical_processing_deadline_missed',
                    dict(deadline=deadline,deadline_reset=False,candidate_retained=True,complete=False))
            if self.db.execute("SELECT 1 FROM rolling_preparation_jobs WHERE status='active' LIMIT 1").fetchone():return None
            row=self.db.execute("""SELECT id,body,hash,priority,deadline FROM rolling_preparation_jobs
                WHERE status='pending' AND retry_at<=? AND deadline>? ORDER BY
                CASE WHEN priority<=2 THEN priority ELSE 3 END,deadline,priority,created,id LIMIT 1""",(now,now)).fetchone()
            if row is None:return None
            identity,raw,checksum,priority,deadline=row;spec=json.loads(raw)
            if digest(spec)!=checksum:raise EvidenceUnavailable('historical_job_corrupt')
            token=uuid.uuid4().hex
            self.db.execute("UPDATE rolling_preparation_jobs SET status='active',token=?,lease_until=?,updated=? WHERE id=?",
                (token,now+WORK_SECONDS+5,now,identity))
            return dict(id=identity,token=token,spec=spec,priority=priority,deadline=deadline,as_of=now,
                endpoint_identity=self.history.endpoint_identity)

    def resume_sync(self,*,limit):
        """Rollback-only: drain new obligations through the original algorithm."""
        for _ in range(limit):
            job=self.claim()
            if job is None:break
            with self.writer.transaction():
                if job['spec'].get('kind')=='cold_restore':
                    from .solana_scoped_retirement import ScopedRetirement
                    ScopedRetirement(self.history).restore(job['spec']['family'],job['spec']['address'])
                else:self.history.rolling.prepare(**job['spec'],priority=job['priority'],deadline=job['deadline'])
                self.db.execute("UPDATE rolling_preparation_jobs SET status='complete',token=NULL,lease_until=NULL,updated=? WHERE id=? AND token=?",
                    (self.clock(),job['id'],job['token']))

    def defer(self,job,reason,*,stale=False,diagnostic=None):
        with self.writer.transaction():
            row=self.db.execute("SELECT attempts FROM rolling_preparation_jobs WHERE id=? AND token=? AND status='active'",(job['id'],job['token'])).fetchone()
            if row is None:return False
            attempts=row[0]+int(not stale);now=self.clock()
            delay=.1 if stale else min(30,.5*2**min(attempts-1,6))
            self.db.execute("""UPDATE rolling_preparation_jobs SET status='pending',token=NULL,
                lease_until=NULL,retry_at=?,attempts=?,updated=? WHERE id=?""",
                (now+delay,attempts,now,job['id']))
            body=dict(reason=reason,complete=False,candidate_retained=True,deadline_reset=False)
            if diagnostic is not None:
                from .runtime.sqlite_failure import MAX_TERMINAL_BYTES
                if type(diagnostic) is str and len(diagnostic.encode())<=MAX_TERMINAL_BYTES:
                    body['failure_diagnostic']=diagnostic
                else:body['failure_diagnostic']='recorder_valid=false:historical_diagnostic_bound'
            self.history._observation(job['id'],'historical_result_stale' if stale else 'historical_worker_unavailable',body)
        return False

    def apply(self,job,result):
        if job['spec'].get('kind')=='cold_restore':
            from .solana_history_restore import apply
            return apply(self,job,result)
        if (result['id']!=job['id'] or result['token']!=job['token'] or result['spec']!=job['spec']
                or digest(result['queries'])!=result['result_hash']):
            raise EvidenceUnavailable('historical_result_identity')
        with self.writer.transaction():
            row=self.db.execute("SELECT priority,deadline,body,hash FROM rolling_preparation_jobs WHERE id=? AND token=? AND status='active'",(job['id'],job['token'])).fetchone()
            if row is None:return False
            if row[2:]!=(canonical(job['spec']),digest(job['spec'])):return self.defer(job,'request_changed',stale=True)
            if self.clock()>=row[1]:return self.defer(job,'original_deadline_expired',stale=True)
            rolling=self.history.rolling
            limit=getattr(rolling,'_history_input_byte_limit',None)
            rolling._history_input_byte_limit=INPUT_BYTES
            try:fresh=capture(rolling,job['spec'])
            finally:rolling._history_input_byte_limit=limit
            if not compatible(result['snapshot'],fresh):return self.defer(job,'source_or_checkpoint_changed',stale=True)
            queries={tuple(key):gaps for key,gaps in result['queries']}
            if set(queries)!={tuple(q['requested']) for q in result['snapshot']['queries']}:
                raise EvidenceUnavailable('historical_result_queries')
            for inputs in result['snapshot']['queries']:
                previous=inputs['lo']-1
                for lo,hi in queries[tuple(inputs['requested'])]:
                    if not inputs['lo']<=lo<=hi<=inputs['hi'] or lo<=previous:
                        raise EvidenceUnavailable('historical_result_intervals')
                    previous=hi
            rolling._prepared_missing=queries
            try:
                metric=rolling.prepare(**job['spec'],priority=row[0],deadline=row[1])
            finally:rolling._prepared_missing=None
            family,address=job['spec']['family'],job['spec']['address']
            if not metric.get('boundary_state'):
                self.db.execute("UPDATE rolling_boundary_waits SET status='resolved' WHERE family=? AND address=? AND status='pending'",(family,address))
            if metric.get('missing_intervals')==[]:
                self.db.execute("""UPDATE rolling_publication_waits SET status='resolved'
                    WHERE family=? AND address=? AND lo=? AND hi=? AND status='pending'""",
                    (family,address,job['spec']['lo'],job['spec']['hi']))
            raw=canonical(metric)
            stamp=dependency_stamp(rolling,job['spec'])
            # A result computed before new monotone coverage is conservative
            # and safe to apply, but must not cache its old gaps as the verdict
            # for the improved snapshot. Recompute once when demanded again.
            identical=all(a['rows']==b['rows'] for q,r in zip(result['snapshot']['queries'],fresh['queries'],strict=True)
                for a,b in zip(q['branches'],r['branches'],strict=True))
            reusable=identical and stamp==dependency_stamp(rolling,job['spec'],as_of=job['as_of'])
            self.db.execute("UPDATE rolling_preparation_jobs SET status='complete',token=NULL,lease_until=NULL,updated=?,result_hash=?,dependency=?,metric=?,metric_hash=? WHERE id=?",
                (self.clock(),result['result_hash'],stamp if reusable else None,raw,hashlib.sha256(raw.encode()).hexdigest(),job['id']))
            self.history._observation(job['id'],'historical_prepare_committed',
                dict(worker=result['metrics'],entry_authority=False,deadline_reset=False))
        return metric
