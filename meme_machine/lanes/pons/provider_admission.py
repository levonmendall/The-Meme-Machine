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
from dataclasses import dataclass,asdict
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


@dataclass(frozen=True)
class OfflineProfile:
    """An explicit fixture envelope; never loaded by configured()/production.

    This extends the same SQLite admission queue, not the provider authority.
    Account tokens combine Pump and Pons endpoints. CU/spending are conservative
    modeled reservations, including failed attempts, not invoice measurements.
    """
    physical_starts_per_second: float
    account: str='offline-shared-account'
    logical_elements_per_second: int=256
    throughput_units_per_second: int=2000
    method_elements_per_second: int=50
    max_logical_elements: int=50
    max_response_bytes: int=2_000_000
    max_inflight_bytes: int=4_000_000
    max_inflight_requests: int=2
    protective_cohort_seconds: float=0
    protected_fraction: float=.25
    protected_inflight_bytes: int=2_000_000
    modeled_usd_per_million_cu: str='0.525'
    max_modeled_microdollars: int=10_000

    def validate(self):
        import socket
        from decimal import Decimal
        if not getattr(socket.socket.connect,'meme_machine_offline',False):
            raise BoundaryError('provider_profile_requires_offline_network_guard')
        if (not 2<=self.physical_starts_per_second<=25 or not isinstance(self.account,str)
                or not 1<=len(self.account)<=64 or not 0<self.protected_fraction<1
                or not 1<=self.max_logical_elements<=50
                or not 0<self.max_response_bytes<=2_000_000
                or not self.max_response_bytes<=self.protected_inflight_bytes<self.max_inflight_bytes
                or not 2<=self.max_inflight_requests<=64
                or not isinstance(self.protective_cohort_seconds,(int,float))
                or not 0<=self.protective_cohort_seconds<=3
                or any(type(n) is not int or n<=0 for n in (self.logical_elements_per_second,
                    self.throughput_units_per_second,self.method_elements_per_second,self.max_modeled_microdollars))
                or not Decimal(self.modeled_usd_per_million_cu).is_finite()
                or Decimal(self.modeled_usd_per_million_cu)<=0):
            raise BoundaryError('provider_offline_resource_profile_invalid')

    def initialize(self,db,endpoint,now):
        db.executescript('''
            CREATE TABLE IF NOT EXISTS offline_resource_accounts(account TEXT PRIMARY KEY,configuration TEXT,state TEXT);
            CREATE TABLE IF NOT EXISTS offline_resource_members(endpoint TEXT PRIMARY KEY,account TEXT);
            CREATE TABLE IF NOT EXISTS offline_inflight(ticket TEXT PRIMARY KEY,account TEXT,bytes INTEGER);
            CREATE TABLE IF NOT EXISTS offline_protective_phases(account TEXT PRIMARY KEY,owner TEXT,until REAL);
        ''')
        spec=json.dumps(asdict(self),sort_keys=True)
        db.execute('INSERT OR IGNORE INTO offline_resource_accounts VALUES(?,?,?)',
            (self.account,spec,json.dumps(dict(at=now,next_at=now,logical=self.logical_elements_per_second,
                throughput=self.throughput_units_per_second,methods={},spent_microdollars=0,starts=0))))
        if db.execute('SELECT configuration FROM offline_resource_accounts WHERE account=?',(self.account,)).fetchone()[0]!=spec:
            raise BoundaryError('provider_offline_account_profile_conflict')
        db.execute('INSERT OR IGNORE INTO offline_resource_members VALUES(?,?)',(endpoint,self.account))
        if db.execute('SELECT account FROM offline_resource_members WHERE endpoint=?',(endpoint,)).fetchone()[0]!=self.account:
            raise BoundaryError('provider_offline_account_membership_conflict')

    def cost(self,methods):
        from collections import Counter
        from decimal import Decimal,ROUND_CEILING
        from pathlib import Path
        from meme_machine.runtime.cu import DEFAULT
        if not methods or not 1<=len(methods)<=self.max_logical_elements:
            raise BoundaryError('provider_offline_logical_bound')
        spec=json.loads(Path(DEFAULT).read_text());counts=dict(Counter(methods))
        if set(counts)-set(spec['methods']):raise BoundaryError('provider_offline_method_weight_unknown')
        billed=sum(n*spec['methods'][m] for m,n in counts.items())
        throughput=sum(n*spec.get('throughput_overrides',{}).get(m,spec['methods'][m]) for m,n in counts.items())
        micro=int((Decimal(billed)*Decimal(self.modeled_usd_per_million_cu)).to_integral_value(rounding=ROUND_CEILING))
        return dict(logical=len(methods),throughput=throughput,methods=counts,microdollars=micro)

    def first(self,db,now):
        from meme_machine.runtime.operating_families import active_scope_sql
        return db.execute('SELECT q.id,q.priority,m.lane,q.deadline FROM queue q '
            'JOIN offline_resource_members a ON a.endpoint=q.endpoint '
            'LEFT JOIN queue_meta m ON m.id=q.id '
            'LEFT JOIN offline_protective_phases p ON p.account=a.account WHERE a.account=? AND '
            '(p.owner IS NULL OR p.until<=? OR q.id LIKE p.owner||\':%\' '
            'OR q.priority=0 AND q.deadline<=p.until) AND '+active_scope_sql("COALESCE(m.lane,'shared')")+
            ' ORDER BY q.priority,q.deadline,q.created,q.id LIMIT 1',(self.account,now)).fetchone()

    def wait(self,db,ticket,now,cost,protected):
        state=json.loads(db.execute('SELECT state FROM offline_resource_accounts WHERE account=?',(self.account,)).fetchone()[0])
        if state['spent_microdollars']+cost['microdollars']>self.max_modeled_microdollars:
            raise BoundaryError('provider_offline_modeled_spending_ceiling')
        elapsed=max(0,now-state['at']);reserve=0 if protected else self.protected_fraction
        waits=[max(0,state['next_at']-now)]
        for key,rate in (('logical',self.logical_elements_per_second),('throughput',self.throughput_units_per_second)):
            if cost[key]>rate*(1-reserve):raise BoundaryError('provider_offline_request_exceeds_resource_envelope')
            state[key]=min(rate,state[key]+elapsed*rate)
            waits.append(max(0,(cost[key]+rate*reserve-state[key])/rate))
        for method,count in cost['methods'].items():
            rate=self.method_elements_per_second
            if count>rate*(1-reserve):raise BoundaryError('provider_offline_method_capacity')
            available=min(rate,state['methods'].get(method,rate)+elapsed*rate)
            state['methods'][method]=available;waits.append(max(0,(count+rate*reserve-available)/rate))
        # Refill methods absent from this purchase too; one shared time frontier.
        for method in set(state['methods'])-set(cost['methods']):
            state['methods'][method]=min(self.method_elements_per_second,state['methods'][method]+elapsed*self.method_elements_per_second)
        state['at']=now
        inflight,bytes_=db.execute('SELECT COUNT(*),COALESCE(SUM(bytes),0) FROM offline_inflight WHERE account=?',(self.account,)).fetchone()
        cap=self.max_inflight_requests if protected else self.max_inflight_requests-1
        byte_cap=self.max_inflight_bytes if protected else self.max_inflight_bytes-self.protected_inflight_bytes
        if inflight>=cap or bytes_+self.max_response_bytes>byte_cap:waits.append(.01)
        db.execute('UPDATE offline_resource_accounts SET state=? WHERE account=?',(json.dumps(state),self.account))
        return max(waits)

    def reserve(self,db,ticket,now,cost):
        state=json.loads(db.execute('SELECT state FROM offline_resource_accounts WHERE account=?',(self.account,)).fetchone()[0])
        state['logical']-=cost['logical'];state['throughput']-=cost['throughput']
        for method,count in cost['methods'].items():state['methods'][method]-=count
        state['spent_microdollars']+=cost['microdollars'];state['next_at']=now+1/self.physical_starts_per_second
        state['starts']+=1
        db.execute('UPDATE offline_resource_accounts SET state=? WHERE account=?',(json.dumps(state),self.account))
        db.execute('INSERT INTO offline_inflight VALUES(?,?,?)',(ticket,self.account,self.max_response_bytes))


class Admission:
    def __init__(self,path,endpoint,*,lane,interval=0.5,clock=time.monotonic,sleeper=time.sleep,offline_profile=None):
        from meme_machine.runtime.operating_families import require_active
        require_active(lane)
        self.offline_profile=offline_profile
        if offline_profile is not None:
            offline_profile.validate();interval=1/offline_profile.physical_starts_per_second
        elif interval < .5:raise BoundaryError('provider_aggregate_ceiling_invalid')
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
        if offline_profile is not None:offline_profile.initialize(db,self.endpoint,self.clock())
        db.close()
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None)
        try:
            # Established WAL connections need no journal-mode write. Two
            # owners opening a new ledger can race its initial mode change;
            # SQLite may return BUSY immediately despite the connection timeout.
            # Retry only that local setup, never a provider purchase or commit.
            setup_until=time.perf_counter()+10
            for attempt in range(10):
                try:
                    mode=db.execute('PRAGMA journal_mode').fetchone()[0]
                    if mode!='wal':mode=db.execute('PRAGMA journal_mode=WAL').fetchone()[0]
                    if mode!='wal':raise BoundaryError('provider_ledger_wal_required')
                    break
                except sqlite3.OperationalError as error:
                    if (getattr(error,'sqlite_errorcode',None)!=sqlite3.SQLITE_BUSY
                            or attempt==9 or time.perf_counter()+.005>=setup_until):raise
                    time.sleep(.005)
                    # The attempts share the existing ten-second setup budget;
                    # a retry cannot acquire a new ten-second busy wait.
                    db.execute('PRAGMA busy_timeout='+str(max(0,int((setup_until-time.perf_counter())*1000))))
            if attempt:db.execute('PRAGMA busy_timeout=10000')
            db.execute('PRAGMA synchronous=FULL')
            return db
        except BaseException:
            db.close()
            raise

    @contextmanager
    def protective_cohort(self):
        """Offline-only, bounded service of an already-due native cohort.

        Peer starts wait until native commits finish or the three-second bound
        expires. Earlier protective deadlines retain precedence. Already
        in-flight responses still invalidate ordered-proof reuse normally;
        neither checks nor quotes gain a longer lifetime. An unavailable phase
        leaves ordinary admission authoritative, without delaying protection.
        The reservation grants no HTTP starts, logical tokens or spending.
        """
        resources=self.offline_profile
        if resources is None or not resources.protective_cohort_seconds:
            yield
            return
        if not _position_work.get():raise BoundaryError('provider_offline_phase_requires_protection')
        deadline=self.clock()+resources.protective_cohort_seconds
        claimed=False;db=self.connect()
        try:
            now=self.clock();db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM offline_protective_phases WHERE until<=?',(now,))
            phase=db.execute('SELECT owner FROM offline_protective_phases WHERE account=?',
                (resources.account,)).fetchone()
            first=resources.first(db,now)
            if now<deadline and phase is None and (first is None or first[1]>0 or first[3]>deadline):
                db.execute('INSERT INTO offline_protective_phases VALUES(?,?,?)',
                    (resources.account,self.session,deadline));claimed=True
            db.execute('COMMIT')
            yield
        finally:
            if db.in_transaction:db.execute('ROLLBACK')
            if claimed:db.execute('DELETE FROM offline_protective_phases WHERE account=? AND owner=?',
                (resources.account,self.session))
            db.close()
    def acquire(self,scope,deadline=None,*,methods=None):
        from meme_machine.operational.position_continuation import position_only
        if (_decision_priority.get() or 0)>=20 and not _position_work.get() and position_only():
            raise BoundaryError('bootstrap_optional_work_closed')
        from meme_machine.runtime.operating_families import active_scope_sql
        live="id IN (SELECT q.id FROM queue q LEFT JOIN queue_meta m ON m.id=q.id WHERE "+active_scope_sql("COALESCE(m.lane,'shared')")+")"
        resources=self.offline_profile
        ticket=(self.session+':' if resources is not None else '')+uuid.uuid4().hex
        started=self.clock();deadline=min(started+30,deadline) if deadline is not None else started+30
        cost=resources.cost(methods) if resources is not None else None
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
                if resources is not None:first=resources.first(db,now)
                resource_wait=(resources.wait(db,ticket,now,cost,priority(scope)==0)
                    if resources is not None and first and first[0]==ticket else 0)
                if first and first[0]==ticket and now>=max(next_at,cooldown) and resource_wait<=0:
                    if resources is not None:resources.reserve(db,ticket,now,cost)
                    db.execute('UPDATE limits SET next_at=? WHERE endpoint=?',(now+interval,self.endpoint))
                    record_service(db,self.endpoint,self.lane,first[1]==0)
                    db.execute('DELETE FROM queue WHERE id=?',(ticket,));db.execute('COMMIT')
                    granted=True
                    result=dict(wait_seconds=now-started,queue_depth=depth,admitted_at=now)
                    if resources is not None:result['resource_reservation']=ticket
                    return result
                db.execute('COMMIT')
                if resources is None:self.sleep(min(0.05,max(0.001,max(next_at,cooldown)-now)))
                else:
                    wait=max(max(next_at,cooldown)-now,resource_wait)
                    self.sleep(min(.05,wait) if wait>0 else .001)
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

    def complete(self,reservation):
        if self.offline_profile is None:return
        db=self.connect()
        try:db.execute('DELETE FROM offline_inflight WHERE ticket=? AND account=?',
            (reservation,self.offline_profile.account))
        finally:db.close()
    def telemetry(self):
        from meme_machine.runtime.robinhood.provider_usage import snapshot
        return snapshot(self.path,self.endpoint)

    def activity_marker(self):
        """Existing endpoint counters, including other native RPC sessions.

        This detects intervening starts/completions, not completion of legacy
        unresolved purchases or a substitute for canonical block verification.
        """
        db=self.connect()
        try:
            rows=dict(db.execute('SELECT metric,SUM(value) FROM provider_usage WHERE endpoint=? '
                "AND metric IN ('physical_http_requests','completed_transport_attempts') GROUP BY metric",(self.endpoint,)))
            return tuple(rows[k] for k in ('physical_http_requests','completed_transport_attempts')) if len(rows)==2 else None
        finally:db.close()

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
            if self.offline_profile is not None:self.complete(admitted['resource_reservation'])
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
