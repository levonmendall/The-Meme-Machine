"""Run-scoped, endpoint-bound immutable reads. Dynamic state is never cached here."""
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from .provider import Unavailable


class ImmutableReads:
    def __init__(self,path,url):
        self.path=path
        self.endpoint=hashlib.sha256(url.encode()).hexdigest()
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS solana_immutable_reads(
                endpoint TEXT,method TEXT,key TEXT,value TEXT,at REAL,lane TEXT,
                PRIMARY KEY(endpoint,method,key));
                CREATE TABLE IF NOT EXISTS solana_read_leases(endpoint TEXT,method TEXT,key TEXT,owner TEXT,expires REAL,
                PRIMARY KEY(endpoint,method,key));
                CREATE TABLE IF NOT EXISTS solana_finalized_frontier(endpoint TEXT PRIMARY KEY,slot INTEGER);
                CREATE TABLE IF NOT EXISTS solana_reuse_events(id INTEGER PRIMARY KEY,endpoint TEXT,lane TEXT,method TEXT,kind TEXT,at REAL);
                CREATE TRIGGER IF NOT EXISTS solana_reuse_no_delete BEFORE DELETE ON solana_reuse_events BEGIN SELECT RAISE(ABORT,'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS solana_reuse_no_update BEFORE UPDATE ON solana_reuse_events BEGIN SELECT RAISE(ABORT,'append_only'); END;''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=30)
        try:
            with db:yield db
        finally:db.close()

    def finalized(self,slot):
        if type(slot) is not int or slot<0:return
        with self.connect() as db:db.execute('INSERT INTO solana_finalized_frontier VALUES(?,?) ON CONFLICT(endpoint) DO UPDATE SET slot=MAX(slot,excluded.slot)',(self.endpoint,slot))

    def event(self,db,method,kind):
        db.execute('INSERT INTO solana_reuse_events(endpoint,lane,method,kind,at) VALUES(?,?,?,?,?)',
            (self.endpoint,os.environ.get('MM_CERTIFICATION_LANE','unknown'),method,kind,time.time()))

    def eligible(self,method,params):
        if method=='getGenesisHash' and not params:return True
        if method!='getBlockTime' or len(params)!=1 or type(params[0]) is not int:return False
        with self.connect() as db:
            row=db.execute('SELECT slot FROM solana_finalized_frontier WHERE endpoint=?',(self.endpoint,)).fetchone()
        return row is not None and 0<=params[0]<=row[0]

    def call(self,method,params,fetch,deadline=None):
        if not self.eligible(method,params):return fetch()
        key=json.dumps(params,separators=(',',':'));owner=uuid.uuid4().hex
        deadline=time.time()+30 if deadline is None else deadline
        while time.time()<deadline:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT value,lane FROM solana_immutable_reads WHERE endpoint=? AND method=? AND key=?',(self.endpoint,method,key)).fetchone()
                if row:
                    self.event(db,method,'cross_lane_hit' if row[1]!=os.environ.get('MM_CERTIFICATION_LANE','unknown') else 'hit')
                    return json.loads(row[0])
                # Lease lasts beyond the bounded HTTP retry path, and cannot be
                # stolen during a live fetch merely because a consumer expired.
                db.execute('DELETE FROM solana_read_leases WHERE expires<?',(time.time(),))
                changed=db.execute('INSERT OR IGNORE INTO solana_read_leases VALUES(?,?,?,?,?)',
                    (self.endpoint,method,key,owner,time.time()+60)).rowcount
                if changed:self.event(db,method,'miss')
            if changed:break
            _stop_sleep(min(.01,max(0,deadline-time.time())))
        else:raise Unavailable('immutable_read_consumer_deadline')
        try:
            value=fetch()
            valid=(method=='getGenesisHash' and isinstance(value,str) and bool(value)) or (method=='getBlockTime' and type(value) is int and value>0)
            if valid:
                with self.connect() as db:
                    db.execute('INSERT OR IGNORE INTO solana_immutable_reads VALUES(?,?,?,?,?,?)',
                        (self.endpoint,method,key,json.dumps(value),time.time(),os.environ.get('MM_CERTIFICATION_LANE','unknown')))
            return value
        finally:
            with self.connect() as db:db.execute('DELETE FROM solana_read_leases WHERE endpoint=? AND method=? AND key=? AND owner=?',(self.endpoint,method,key,owner))


class ImmutableRPCMixin:
    def _shared_reads(self):
        path=os.environ.get('MM_SOLANA_EVIDENCE_BROKER_DB')
        if not path:return None
        identity=(path,self.url)
        if getattr(self,'_immutable_identity',None)!=identity:
            self._immutable_identity=identity
            self._immutable_reads=ImmutableReads(path,self.url)
            from .solana_evidence_broker import EvidenceBroker
            pacer=getattr(self,'read_pacer',self)
            if getattr(pacer,'_broker_identity',None)!=(path,self.url):
                pacer._broker_identity=(path,self.url)
                pacer._immutable_broker=EvidenceBroker(path)
            self._immutable_broker=pacer._immutable_broker
        return self._immutable_reads

    def _assert_transaction_authority(self):
        # Genesis proofs can authenticate a newly configured endpoint independently;
        # transaction bodies from the previous authority cannot silently follow it.
        with self._immutable_broker.lock,self._immutable_broker.db:
            db=self._immutable_broker.db
            db.execute('CREATE TABLE IF NOT EXISTS transaction_authority(endpoint TEXT PRIMARY KEY)')
            prior=db.execute('SELECT endpoint FROM transaction_authority').fetchone()
            if prior and prior[0]!=self._immutable_reads.endpoint:
                raise Unavailable('shared_transaction_authority_changed')
            db.execute('INSERT OR IGNORE INTO transaction_authority VALUES(?)',(self._immutable_reads.endpoint,))

    @staticmethod
    def _body_params(params):
        return (len(params)==2 and isinstance(params[0],str) and isinstance(params[1],dict)
                and params[1].get('commitment')=='finalized' and params[1].get('encoding','json')=='json'
                and params[1].get('maxSupportedTransactionVersion',0)==1)

    def _body_read(self,params_list,batch_size):
        self._assert_transaction_authority()
        deadline=getattr(self,'evidence_deadline',None) or time.time()+30
        priority=getattr(self,'evidence_priority',20)
        kind='position_monitor' if priority==0 else 'dlmm_fresh' if os.environ.get('MM_CERTIFICATION_LANE')=='meteora' else 'pump_window'
        result,meta=self._immutable_broker.hydrate_transactions(self,[p[0] for p in params_list],
            kind=kind,deadline=deadline,batch_size=batch_size,
            owner=f'direct:{kind}:{deadline!r}')
        if meta['pending']:raise Unavailable('transaction_evidence_incomplete')
        return [result[p[0]] for p in params_list]

    def call(self,method,params=None,priority=False,**kwargs):
        params=params or [];shared=self._shared_reads()
        if shared and method=='getTransaction' and not getattr(self,'_broker_transport',False) and self._body_params(params):
            return self._body_read([params],1)[0]
        fetch=lambda:super(ImmutableRPCMixin,self).call(method,params,priority,**kwargs)
        value=shared.call(method,params,fetch,getattr(self,'evidence_deadline',None)) if shared else fetch()
        if shared and method=='getMultipleAccounts' and len(params)>1 and params[1].get('commitment')=='finalized' and isinstance(value,dict):
            shared.finalized(value.get('context',{}).get('slot'))
        if shared and method=='getTransaction' and self._body_params(params) and isinstance(value,dict):shared.finalized(value.get('slot'))
        return value

    def call_many(self,method,params_list,priority=False,batch_size=8):
        shared=self._shared_reads()
        if shared and method=='getTransaction' and not getattr(self,'_broker_transport',False) and all(self._body_params(p) for p in params_list):
            return self._body_read(params_list,batch_size)
        if shared and method=='getTransaction' and all(self._body_params(p) for p in params_list):self._assert_transaction_authority()
        values=super().call_many(method,params_list,priority,batch_size=batch_size)
        if shared and method=='getTransaction':
            for p,v in zip(params_list,values):
                if self._body_params(p) and isinstance(v,dict):shared.finalized(v.get('slot'))
        return values


def _stop_sleep(seconds):
    from meme_machine.runtime.stop import sleep
    return sleep(seconds,sleeper=time.sleep)
