"""Optional cross-process read-only transport admission for concurrent certification.

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
from . import BoundaryError


def fingerprint(endpoint):
    from urllib.parse import urlsplit
    p=urlsplit(endpoint.strip())
    normalized=f'{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip("/")}'
    if p.query: normalized+='?'+p.query
    return hashlib.sha256(normalized.encode()).hexdigest()


def priority(scope):
    scope=str(scope).lower()
    if any(x in scope for x in ('paper','monitor','exit','unwind','settle','lifecycle')):return 0
    if any(x in scope for x in ('selective','evidence','candidate')):return 10
    return 50


class Admission:
    def __init__(self,path,endpoint,*,lane,interval=0.5,clock=time.monotonic,sleeper=time.sleep):
        self.path=path;self.endpoint=fingerprint(endpoint);self.lane=lane
        self.clock=clock;self.sleep=sleeper;self.interval=interval
        self.session=uuid.uuid4().hex
        db=self.connect()
        db.executescript('''
            CREATE TABLE IF NOT EXISTS limits(endpoint TEXT PRIMARY KEY,next_at REAL NOT NULL,
                cooldown REAL NOT NULL,interval REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS queue(id TEXT PRIMARY KEY,endpoint TEXT NOT NULL,
                priority INTEGER NOT NULL,created REAL NOT NULL,deadline REAL NOT NULL);
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
    def acquire(self,scope):
        ticket=uuid.uuid4().hex;started=self.clock();deadline=started+30
        db=self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM queue WHERE deadline<=?',(started,))
            if db.execute('SELECT COUNT(*) FROM queue WHERE endpoint=?',(self.endpoint,)).fetchone()[0]>=256:
                raise BoundaryError('provider_shared_queue_capacity')
            db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',(ticket,self.endpoint,priority(scope),started,deadline))
            depth=db.execute('SELECT COUNT(*) FROM queue WHERE endpoint=?',(self.endpoint,)).fetchone()[0]
            db.execute('COMMIT')
            while True:
                now=self.clock()
                if now>=deadline:raise BoundaryError('provider_shared_admission_deadline')
                db.execute('BEGIN IMMEDIATE')
                db.execute('DELETE FROM queue WHERE deadline<=?',(now,))
                first=db.execute('SELECT id FROM queue WHERE endpoint=? ORDER BY priority,created,id LIMIT 1',(self.endpoint,)).fetchone()
                next_at,cooldown,interval=db.execute('SELECT next_at,cooldown,interval FROM limits WHERE endpoint=?',(self.endpoint,)).fetchone()
                if first and first[0]==ticket and now>=max(next_at,cooldown):
                    db.execute('UPDATE limits SET next_at=? WHERE endpoint=?',(now+interval,self.endpoint))
                    db.execute('DELETE FROM queue WHERE id=?',(ticket,));db.execute('COMMIT')
                    return dict(wait_seconds=now-started,queue_depth=depth,admitted_at=now)
                db.execute('COMMIT')
                self.sleep(min(0.05,max(0.001,max(next_at,cooldown)-now)))
        finally:
            if db.in_transaction:db.execute('ROLLBACK')
            db.execute('DELETE FROM queue WHERE id=?',(ticket,));db.close()
    def invoke(self,call,methods,scope,retry_count=0):
        admitted=self.acquire(scope);started=self.clock();boundary=None;http_status=None;rpc_code=None
        try:
            result=call()
            http_status=200
            return result
        except BoundaryError as exc:
            boundary=str(exc)
            match=re.fullmatch(r'provider_http_(\d+)',boundary)
            http_status=int(match[1]) if match else None
            match=re.fullmatch(r'provider_rpc_(-?\d+)',boundary)
            rpc_code=int(match[1]) if match else None
            raise
        finally:
            row=dict(lane=self.lane,endpoint_fingerprint=self.endpoint,session=self.session,
                     methods=methods,scope=scope,http_status=http_status,rpc_error_code=rpc_code,
                     boundary=boundary,retry_count=retry_count,
                     latency_seconds=self.clock()-started,**admitted)
            db=self.connect()
            try:
                db.execute('BEGIN IMMEDIATE')
                if http_status==429 or rpc_code==429:
                    db.execute('UPDATE limits SET cooldown=MAX(cooldown,?) WHERE endpoint=?',(self.clock()+8,self.endpoint))
                db.execute('INSERT INTO transports(body) VALUES(?)',(json.dumps(row,sort_keys=True),))
                db.execute('COMMIT')
            finally:db.close()


def configured(endpoint):
    path=os.environ.get('MM_CERTIFICATION_PROVIDER_DB')
    if not path:return None
    return Admission(path,endpoint,lane=os.environ.get('MM_CERTIFICATION_LANE','unknown'))
