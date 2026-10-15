"""Run-scoped neutral immutable evidence reuse; callers retain authentication authority.

An endpoint digest isolates trust domains. Numeric state reads need an explicit
caller-authenticated hash pin. Mutable tags and unpinned receipts never hit.
The append-only provenance table retains every miss/reuse; errors are not cached.
"""
from collections import Counter
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from . import BoundaryError, CHAIN_ID


def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'))

class EvidenceStore:
    def __init__(self,path=':memory:'):
        self.db=sqlite3.connect(str(path),timeout=2,check_same_thread=False)
        self.lock=threading.RLock();self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS evidence(
            domain TEXT,key TEXT,body TEXT,created REAL,PRIMARY KEY(domain,key));
            CREATE TABLE IF NOT EXISTS gas_quotes(domain TEXT,epoch TEXT,monotonic REAL,at REAL,body TEXT);
            CREATE TABLE IF NOT EXISTS flights(domain TEXT,key TEXT,owner TEXT,PRIMARY KEY(domain,key));
            CREATE TABLE IF NOT EXISTS reuse_events(sequence INTEGER PRIMARY KEY,
            lane TEXT,domain TEXT,method TEXT,outcome TEXT,at REAL,key_digest TEXT,source_at REAL);
            CREATE TRIGGER IF NOT EXISTS reuse_no_update BEFORE UPDATE ON reuse_events
            BEGIN SELECT RAISE(ABORT,'append_only');END;
            CREATE TRIGGER IF NOT EXISTS reuse_no_delete BEFORE DELETE ON reuse_events
            BEGIN SELECT RAISE(ABORT,'append_only');END;''')
    @contextmanager
    def lease(self,domain,keys,deadline=None):
        from meme_machine.runtime.robinhood.plane import process_identity, alive
        keys=sorted(set(k for k in keys if k));owner=process_identity()+'|'+uuid.uuid4().hex
        deadline=time.monotonic()+30 if deadline is None else deadline
        while keys:
            with self.lock:
                self.db.execute('BEGIN IMMEDIATE')
                try:
                    for stale in self.db.execute('SELECT DISTINCT owner FROM flights').fetchall():
                        if '|' in stale[0] and not alive(stale[0].split('|')[0]):
                            self.db.execute('DELETE FROM flights WHERE owner=?',(stale[0],))
                    busy=any(self.db.execute('SELECT 1 FROM flights WHERE domain=? AND key=?',(domain,k)).fetchone() for k in keys)
                    if not busy:
                        self.db.executemany('INSERT INTO flights VALUES(?,?,?)',[(domain,k,owner) for k in keys])
                    self.db.commit()
                except BaseException:self.db.rollback();raise
            if not busy:break
            if time.monotonic()>=deadline:raise BoundaryError('immutable_evidence_wait_deadline')
            _stop_sleep(min(.01,max(0,deadline-time.monotonic())))
        try:yield
        finally:
            with self.lock,self.db:self.db.execute('DELETE FROM flights WHERE owner=?',(owner,))

    def get(self,domain,key):
        with self.lock:
            row=self.db.execute('SELECT body,created FROM evidence WHERE domain=? AND key=?',(domain,key)).fetchone()
        return None if row is None else (json.loads(row[0]),row[1])
    def put(self,domain,key,value):
        body=canonical(value)
        with self.lock,self.db:
            row=self.db.execute('SELECT body FROM evidence WHERE domain=? AND key=?',(domain,key)).fetchone()
            if row and row[0]!=body:
                self.event('shared',domain,'immutable','conflict',key)
                raise BoundaryError('immutable_rpc_evidence_conflict')
            self.db.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?,?)',(domain,key,body,time.time()))
            self.db.execute('DELETE FROM evidence WHERE rowid NOT IN (SELECT rowid FROM evidence ORDER BY created DESC LIMIT 8192)')
    def event(self,lane,domain,method,outcome,key,source_at=None):
        with self.lock,self.db:
            self.db.execute('INSERT INTO reuse_events(lane,domain,method,outcome,at,key_digest,source_at) VALUES(?,?,?,?,?,?,?)',
                (lane,domain,method,outcome,time.time(),hashlib.sha256(key.encode()).hexdigest() if key else None,source_at))
            from meme_machine.runtime.storage import audit_ring
            audit_ring(self.db,'reuse_events','reuse_no_delete',key='sequence')

_stores={};_lock=threading.Lock()
def configured(path=None):
    path=path or os.environ.get('MM_RPC_CACHE_DB')
    if not path:return None
    from pathlib import Path
    path=str(Path(path).resolve());Path(path).parent.mkdir(parents=True,exist_ok=True)
    with _lock:
        if path not in _stores:_stores[path]=EvidenceStore(path)
        return _stores[path]

class Reuse:
    def __init__(self,endpoint,store,lane='unknown'):
        self.domain=hashlib.sha256((str(CHAIN_ID)+':'+endpoint).encode()).hexdigest()
        self.store=store;self.lane=lane;self.counts=Counter();self.chain=None
    def key(self,method,params,pins=None,receipts=None):
        pins=pins or {};receipts=receipts or {}
        if method=='eth_getBlockByHash' and len(params)==2 and params[1] is False:
            return canonical([method,params])
        if method=='eth_getBlockByNumber' and len(params)==2 and params[1] is False and params[0] in pins:
            return canonical(['eth_getBlockByHash',[pins[params[0]],False]])
        if method=='eth_getTransactionReceipt' and params[0] in receipts:
            return canonical([method,params[0],receipts[params[0]]])
        if method in ('eth_call','eth_getCode','eth_getBalance','eth_getStorageAt'):
            index=2 if method=='eth_getStorageAt' else 1
            if len(params)<=index:return None
            block=params[index]
            if isinstance(block,dict):
                # requireCanonical also belongs to the key. Do not substitute tags.
                if not block.get('blockHash'):return None
                identity=block
            elif block in pins:identity={'blockHash':pins[block]}
            else:return None
            resolved=list(params);resolved[index]=identity
            return canonical([method,resolved])
        if method=='eth_getLogs' and len(params)==1:
            query=params[0]
            if query.get('blockHash'):return canonical([method,params])
            first=query.get('fromBlock');last=query.get('toBlock')
            # Exact filter and both immutable bounds; never reuse latest ranges.
            if first==last and first in pins:
                exact=dict(query);exact.pop('fromBlock');exact.pop('toBlock');exact['blockHash']=pins[first]
                return canonical([method,[exact]])
            # Multi-block numeric ranges remain caller-authenticated tape work.
            # Do not durably key a mutable range by only its endpoint hashes.
        return None
    def lookup(self,method,params,pins=None,receipts=None,cost_epoch=None):
        if method=='eth_gasPrice' and cost_epoch:
            epoch,observed,deadline=cost_epoch
            now=time.monotonic()
            with self.store.lock:
                row=self.store.db.execute('SELECT body,at,monotonic FROM gas_quotes WHERE domain=? AND epoch=? AND monotonic>=? AND monotonic<=? ORDER BY monotonic DESC LIMIT 1',
                    (self.domain,epoch,observed,now)).fetchone()
            key='gas_epoch:'+epoch
            if row and now<=deadline:
                self.counts['eth_gasPrice:hit']+=1
                self.store.event(self.lane,self.domain,method,'hit',key,row[1])
                self.gas_quote_origin=dict(observed_at=row[1],observed_monotonic=row[2],reused=True)
                return True,json.loads(row[0]),None
            self.counts['eth_gasPrice:miss']+=1
            self.store.event(self.lane,self.domain,method,'miss',key)
            return False,None,key
        if method=='eth_chainId' and self.chain is not None:
            self.counts['eth_chainId:session_hit']+=1
            self.store.event(self.lane,self.domain,method,'session_hit','session',self.chain[1])
            return True,self.chain[0],None
        key=self.key(method,params,pins,receipts)
        row=self.store.get(self.domain,key) if key else None
        self.counts[method+(':hit' if row else ':miss')]+=1
        self.store.event(self.lane,self.domain,method,'hit' if row else 'miss',key,row[1] if row else None)
        return (True,row[0],key) if row else (False,None,key)
    def remember(self,method,params,value,key):
        if value is None:return
        if method=='eth_gasPrice' and key and key.startswith('gas_epoch:'):
            mono=time.monotonic();at=time.time()
            with self.store.lock,self.store.db:
                self.store.db.execute('INSERT INTO gas_quotes VALUES(?,?,?,?,?)',
                    (self.domain,key[len('gas_epoch:'):],mono,at,canonical(value)))
                self.store.db.execute('DELETE FROM gas_quotes WHERE rowid NOT IN (SELECT rowid FROM gas_quotes ORDER BY at DESC LIMIT 4096)')
            self.gas_quote_origin=dict(observed_at=at,observed_monotonic=mono,reused=False)
            return
        if method=='eth_chainId':
            if int(value,16)!=CHAIN_ID:raise BoundaryError('wrong_chain')
            self.chain=(value,time.time());return
        if method in ('eth_getBlockByHash','eth_getBlockByNumber') and len(params)==2 and params[1] is False:
            if not isinstance(value,dict) or not value.get('hash') or not value.get('number'):raise BoundaryError('immutable_header_shape')
            if method=='eth_getBlockByHash' and value['hash']!=params[0]:raise BoundaryError('immutable_header_identity')
            if method=='eth_getBlockByNumber' and str(params[0]).startswith('0x') and int(value['number'],16)!=int(params[0],16):raise BoundaryError('immutable_header_identity')
            if key and json.loads(key)[1][0]!=value['hash']:raise BoundaryError('immutable_header_pin_disagreement')
            self.store.put(self.domain,canonical(['eth_getBlockByHash',[value['hash'],False]]),value)
        if key:
            if method=='eth_getTransactionReceipt':
                expected=json.loads(key)
                if value.get('transactionHash')!=expected[1] or value.get('blockHash')!=expected[2]:raise BoundaryError('receipt_block_disagreement')
            if method=='eth_getLogs':
                expected=json.loads(key)[1][0]['blockHash']
                if not isinstance(value,list) or any(r.get('blockHash')!=expected or r.get('removed') for r in value):
                    raise BoundaryError('immutable_log_block_disagreement')
            self.store.put(self.domain,key,value)
    def telemetry(self):return dict(self.counts)


def choose_block_receipts(relevant_count,total_transactions,*,supported,remaining_seconds,
                          individual_cu=20,block_cu=20):
    """Bound size, relevance and throughput, not only the inexpensive billing price.

    500 throughput CU for block receipts vs 20 per individual: require 25 relevant
    members, >=50% relevance and <=128 transactions. Never spend urgent slack on
    capability detection. Unknown block size/support uses individual receipts.
    """
    return bool(supported and isinstance(total_transactions,int) and 25<=relevant_count<=total_transactions<=128
        and relevant_count*2>=total_transactions and remaining_seconds>=1
        and block_cu<individual_cu*relevant_count)


def _stop_sleep(seconds):
    from meme_machine.runtime.stop import sleep
    return sleep(seconds,sleeper=time.sleep)
