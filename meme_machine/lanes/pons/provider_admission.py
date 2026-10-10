"""Optional cross-process read-only transport admission for concurrent meme_machine.runtime.

Endpoint credentials never enter SQLite. Existing role pacers and error recovery
remain authoritative; this adds a shared physical-transport ceiling and telemetry.
"""
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
from . import BoundaryError


POSITION_BURST = 8
FOREGROUND_AGE_SECONDS = 3
_decision_priority = ContextVar('candidate_decision_priority',default=None)
_position_work = ContextVar('provider_position_work',default=False)
_foreground_work = ContextVar('provider_foreground_work',default=False)


def position_work(function):
    from inspect import isgeneratorfunction
    if isgeneratorfunction(function):
        @wraps(function)
        def steps(*args,**kwargs):
            token=_position_work.set(True)
            try:return (yield from function(*args,**kwargs))
            finally:_position_work.reset(token)
        return steps
    @wraps(function)
    def wrapped(*args,**kwargs):
        token=_position_work.set(True)
        try:return function(*args,**kwargs)
        finally:_position_work.reset(token)
    return wrapped


def foreground_work(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        token=_foreground_work.set(True)
        try:return function(*args,**kwargs)
        finally:_foreground_work.reset(token)
    return wrapped


@contextmanager
def native_lifecycle_work(*,held):
    """Entry probing cannot inherit held-position priority from its controller."""
    position_token=_position_work.set(bool(held))
    decision_token=_decision_priority.set(0 if held else 5)
    try:yield
    finally:
        _decision_priority.reset(decision_token)
        _position_work.reset(position_token)


def decision_work(priority_class):
    if priority_class not in range(6):raise ValueError('candidate_priority_class')
    def decorate(function):
        @wraps(function)
        def wrapped(*args,**kwargs):
            from meme_machine.operational.position_continuation import position_only
            if priority_class>=3 and not _position_work.get() and position_only():
                raise BoundaryError('bootstrap_optional_work_closed')
            token=_decision_priority.set((0,5,10,20,30,50)[priority_class])
            try:return function(*args,**kwargs)
            finally:_decision_priority.reset(token)
        return wrapped
    return decorate


@contextmanager
def optional_paper_shadow_work():
    """Observe held pools only with spare non-position provider priority.

    Never inherit the native position controller's priority zero. Funding-
    closed / POSITION_ONLY protection refuses all optional shadow requests.
    Errors and exhaustion are diagnostics, never reasons to delay native exits.
    """
    from meme_machine.operational.position_continuation import position_only
    if position_only():
        raise BoundaryError('bootstrap_optional_work_closed')
    position_token=_position_work.set(False)
    decision_token=_decision_priority.set(30)
    try:
        yield
    finally:
        _decision_priority.reset(decision_token)
        _position_work.reset(position_token)


def next_ticket(db,endpoint,now,interval):
    from meme_machine.runtime.operating_families import active_scope_sql
    live=active_scope_sql("COALESCE(m.lane,'shared')")
    first=db.execute("SELECT q.id,q.priority,m.lane,q.deadline FROM queue q "
        "LEFT JOIN queue_meta m ON m.id=q.id WHERE "+live+" AND q.endpoint=? ORDER BY "
        "CASE WHEN q.priority=0 THEN 0 WHEN q.priority>=50 AND q.created<=? THEN 5 ELSE q.priority END,"
        "q.deadline,q.created,q.id LIMIT 1",(endpoint,now-FOREGROUND_AGE_SECONDS)).fetchone()
    if not first or first[1]!=0 or first[3]<=now+interval:return first
    service=db.execute('SELECT lane,consecutive FROM position_service WHERE endpoint=?',(endpoint,)).fetchone()
    if not service or service[0]!=first[2] or service[1]<POSITION_BURST:return first
    aged=db.execute('SELECT q.id,q.priority,m.lane,q.deadline FROM queue q '
        'JOIN queue_meta m ON m.id=q.id WHERE '+live+' AND q.endpoint=? AND q.priority>0 '
        'AND (m.lane<>? OR q.priority<=10) AND q.created<=? ORDER BY q.deadline,q.created,q.id LIMIT 1',
        (endpoint,first[2],now-FOREGROUND_AGE_SECONDS)).fetchone()
    return aged or first


def record_service(db,endpoint,lane,is_position):
    previous=db.execute('SELECT lane,consecutive FROM position_service WHERE endpoint=?',(endpoint,)).fetchone()
    count=(previous[1]+1 if previous and previous[0]==lane else 1) if is_position else 0
    db.execute('INSERT INTO position_service VALUES(?,?,?) ON CONFLICT(endpoint) '
        'DO UPDATE SET lane=excluded.lane,consecutive=excluded.consecutive',(endpoint,lane,count))


def fingerprint(endpoint):
    from meme_machine.runtime.robinhood import provider_authority as authority
    try:return authority.fingerprint(endpoint)
    except ValueError:pass
    from urllib.parse import urlsplit
    p=urlsplit(endpoint.strip())
    normalized=f'{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip("/")}'
    if p.query: normalized+='?'+p.query
    return hashlib.sha256(normalized.encode()).hexdigest()


def priority(scope):
    if _position_work.get():return 0
    if _decision_priority.get() is not None:return _decision_priority.get()
    if _foreground_work.get():return 10
    scope=str(scope).lower()
    if any(x in scope for x in ('paper','monitor','exit','unwind','settle','lifecycle')):return 0
    if any(x in scope for x in ('entry','fill','confirmation')):return 5
    if any(x in scope for x in ('repair','gap')):return 40
    if any(x in scope for x in ('selective','evidence','candidate','pons_natural')):return 10
    return 50


class Admission:
    def __init__(self,path,endpoint,*,lane,interval=0.5,clock=time.monotonic,sleeper=time.sleep):
        from meme_machine.runtime.operating_families import require_active
        require_active(lane)
        if interval < .5:raise BoundaryError('provider_aggregate_ceiling_invalid')
        from pathlib import Path
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.path=path;self.endpoint=fingerprint(endpoint);self.lane=lane
        self.clock=clock;self.sleep=sleeper;self.interval=interval
        self.session=uuid.uuid4().hex
        db=self.connect()
        db.executescript('''
            CREATE TABLE IF NOT EXISTS transport_starts(seq INTEGER PRIMARY KEY,body TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS no_start_update BEFORE UPDATE ON transport_starts BEGIN SELECT RAISE(ABORT,'append_only'); END;
            CREATE TRIGGER IF NOT EXISTS no_start_delete BEFORE DELETE ON transport_starts BEGIN SELECT RAISE(ABORT,'append_only'); END;
            CREATE TABLE IF NOT EXISTS provider_usage(endpoint TEXT,lane TEXT,metric TEXT,value REAL,PRIMARY KEY(endpoint,lane,metric));
            CREATE TABLE IF NOT EXISTS limits(endpoint TEXT PRIMARY KEY,next_at REAL NOT NULL,
                cooldown REAL NOT NULL,interval REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS queue(id TEXT PRIMARY KEY,endpoint TEXT NOT NULL,
                priority INTEGER NOT NULL,created REAL NOT NULL,deadline REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS queue_meta(id TEXT PRIMARY KEY,lane TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS position_service(endpoint TEXT PRIMARY KEY,lane TEXT,consecutive INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS admissions(seq INTEGER PRIMARY KEY,body TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS no_admission_update BEFORE UPDATE ON admissions BEGIN SELECT RAISE(ABORT,'append_only'); END;
            CREATE TRIGGER IF NOT EXISTS no_admission_delete BEFORE DELETE ON admissions BEGIN SELECT RAISE(ABORT,'append_only'); END;
            CREATE TABLE IF NOT EXISTS transports(seq INTEGER PRIMARY KEY,body TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS no_transport_update BEFORE UPDATE ON transports
                BEGIN SELECT RAISE(ABORT,'append_only'); END;
            CREATE TRIGGER IF NOT EXISTS no_transport_delete BEFORE DELETE ON transports
                BEGIN SELECT RAISE(ABORT,'append_only'); END;
        ''')
        db.execute('INSERT INTO limits VALUES(?,0,0,?) ON CONFLICT(endpoint) DO UPDATE SET interval=MAX(interval,excluded.interval)',(self.endpoint,interval))
        db.close()
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None)
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
        return db
    def acquire(self,scope,deadline=None,*,methods=None):
        from meme_machine.operational.position_continuation import position_only
        if (_decision_priority.get() or 0)>=20 and not _position_work.get() and position_only():
            raise BoundaryError('bootstrap_optional_work_closed')
        from meme_machine.runtime.operating_families import active_scope_sql
        live="id IN (SELECT q.id FROM queue q LEFT JOIN queue_meta m ON m.id=q.id WHERE "+active_scope_sql("COALESCE(m.lane,'shared')")+")"
        ticket=uuid.uuid4().hex;started=self.clock();deadline=min(started+30,deadline) if deadline is not None else started+30
        granted=False;failure=None
        db=self.connect()
        try:
            if deadline<=started:raise BoundaryError('provider_shared_admission_deadline')
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM queue WHERE '+live+' AND deadline<=?',(started,))
            db.execute('DELETE FROM queue_meta WHERE id NOT IN (SELECT id FROM queue)')
            if (db.execute('SELECT COUNT(*) FROM queue WHERE '+live+' AND endpoint=?',(self.endpoint,)).fetchone()[0]>=256
                    and priority(scope)!=0):
                # Candidate backlog cannot refuse admission to an existing
                # position's safety work. The transport ceiling is unchanged.
                raise BoundaryError('provider_shared_queue_capacity')
            db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',(ticket,self.endpoint,priority(scope),started,deadline))
            db.execute('INSERT INTO queue_meta VALUES(?,?)',(ticket,self.lane))
            depth=db.execute('SELECT COUNT(*) FROM queue WHERE '+live+' AND endpoint=?',(self.endpoint,)).fetchone()[0]
            db.execute('COMMIT')
            while True:
                now=self.clock()
                if now>=deadline:raise BoundaryError('provider_shared_admission_deadline')
                db.execute('BEGIN IMMEDIATE')
                db.execute('DELETE FROM queue WHERE '+live+' AND deadline<=?',(now,))
                next_at,cooldown,interval=db.execute('SELECT next_at,cooldown,interval FROM limits WHERE endpoint=?',(self.endpoint,)).fetchone()
                first=next_ticket(db,self.endpoint,now,interval)
                if first and first[0]==ticket and now>=max(next_at,cooldown):
                    db.execute('UPDATE limits SET next_at=? WHERE endpoint=?',(now+interval,self.endpoint))
                    record_service(db,self.endpoint,self.lane,first[1]==0)
                    db.execute('DELETE FROM queue WHERE id=?',(ticket,));db.execute('COMMIT')
                    granted=True
                    return dict(wait_seconds=now-started,queue_depth=depth,admitted_at=now)
                db.execute('COMMIT')
                self.sleep(min(0.05,max(0.001,max(next_at,cooldown)-now)))
        except BoundaryError as exc:
            failure=str(exc);raise
        finally:
            if db.in_transaction:db.execute('ROLLBACK')
            db.execute('DELETE FROM queue WHERE id=?',(ticket,))
            db.execute('DELETE FROM queue_meta WHERE id=?',(ticket,))
            db.execute('INSERT INTO admissions(body) VALUES(?)',(json.dumps(dict(lane=self.lane,
                endpoint_fingerprint=self.endpoint,scope=scope,created=started,deadline=deadline,
                ended=self.clock(),wait_seconds=self.clock()-started,granted=granted,
                request_id=ticket,methods=methods,transport_attempted=False,
                priority=priority(scope),failure_domain=None if granted else 'local_admission',
                reason='granted' if granted else failure or 'admission_failed')),))
            from meme_machine.runtime.storage import audit_ring
            audit_ring(db,'admissions','no_admission_delete')
            db.close()
    def telemetry(self):
        from meme_machine.runtime.robinhood.provider_usage import snapshot
        return snapshot(self.path,self.endpoint)

    def invoke(self,call,methods,scope,retry_count=0,deadline=None,timing=None,batch=False,role=None):
        from meme_machine.runtime.robinhood.provider_usage import _active
        from meme_machine.runtime.robinhood.provider_authority import failure_class
        attempt=dict(physical_requests=0,path=str(self.path),endpoint_fingerprint=self.endpoint,
            lane=self.lane,session=self.session,methods=methods,scope=scope,retry_attempt=retry_count,batch=batch)
        from meme_machine.runtime.robinhood.provider_usage import category
        attempt['category']=category(scope,role)
        from meme_machine.runtime.provider_purchases import work_label
        attempt['purchase_work']=work_label(family='pons')
        token=_active.set(attempt)
        try:admitted=self.acquire(scope,deadline,methods=methods)
        except BaseException:
            _active.reset(token)
            raise
        started=self.clock();boundary=None;http_status=None;rpc_code=None
        attempt['admitted_at']=admitted['admitted_at']
        if timing is not None:
            timing.setdefault("first_transport_monotonic",started)
            timing["shared_provider_queue_wait_seconds"]=timing.get("shared_provider_queue_wait_seconds",0)+admitted["wait_seconds"]
        try:
            result=call()
            http_status=200
            return result
        except Exception as exc:
            boundary=failure_class(exc)
            match=re.fullmatch(r'provider_http_(\d+)',boundary)
            http_status=int(match[1]) if match else None
            match=re.fullmatch(r'provider_rpc_(-?\d+)',boundary)
            rpc_code=int(match[1]) if match else None
            raise BoundaryError(boundary) from None
        finally:
            if timing is not None:timing["provider_transport_seconds"]=timing.get("provider_transport_seconds",0)+self.clock()-started
            _active.reset(token)
            row=dict(lane=self.lane,endpoint_fingerprint=self.endpoint,session=self.session,
                     category=attempt['category'],response_bytes=attempt.get('response_bytes',0),
                     purchase_work=attempt['purchase_work'],
                     methods=methods,scope=scope,http_status=http_status,rpc_error_code=rpc_code,
                     boundary=boundary,retry_count=retry_count,
                     retry_attempt=retry_count,physical_requests=attempt["physical_requests"],batch=batch,
                     latency_seconds=self.clock()-started,**admitted)
            db=self.connect()
            try:
                db.execute('BEGIN IMMEDIATE')
                if http_status==429 or rpc_code==429:
                    db.execute('UPDATE limits SET cooldown=MAX(cooldown,?) WHERE endpoint=?',(self.clock()+8,self.endpoint))
                from meme_machine.runtime.robinhood.provider_usage import record
                record(db,row,wire=False)
                db.execute('INSERT INTO transports(body) VALUES(?)',(json.dumps(row,sort_keys=True),))
                from meme_machine.runtime.storage import audit_ring
                audit_ring(db,'transports','no_transport_delete')
                db.execute('COMMIT')
            finally:db.close()


def configured(endpoint, mandatory=False):
    from meme_machine.runtime.robinhood.provider_authority import paths
    path=paths()['provider'] if mandatory else os.environ.get('MM_PROVIDER_DB')
    if not path:return None
    return Admission(path,endpoint,lane=os.environ.get('MM_RUNTIME_LANE','unknown'))
