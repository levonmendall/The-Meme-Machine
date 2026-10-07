"""Durable Solana candidate observation, ordered economics and work scheduling.

This layer has no trading or capital authority.  Cheap candidates and normalized
economic events are retained without a candidate-count cap.  Expensive evidence
work is admitted separately by an earliest-deadline-first scheduler.  Strategy
qualification is durable before any funding outcome is recorded.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time

from meme_machine.runtime.journal import canonical,digest


class CandidateDeadlineMissed(RuntimeError):
    def __init__(self,work):
        self.work=work
        super().__init__("candidate_decision_deadline_missed:"+str(work["id"]))


def economic_event_cursor(event):
    """Log indices are only comparable within one ordered transaction."""
    return (int(event['slot']),int(event.get('_economic_order',0)),int(event.get('index',0)))


def order_economic_records(records,db,scope):
    """Use native order or a certified order within one filtered scope.

    A single transaction needs only its instruction/event order. Multiple
    transactions cannot be ordered by signature or log-line index. Filtered
    ranks are relative witnesses, never fabricated native transaction indices.
    """
    groups={}
    for row in records:groups.setdefault(row['slot'],[]).append(row)
    result=[]
    for slot,rows in sorted(groups.items()):
        signatures={r['signature'] for r in rows}
        native=all(type(r.get('transaction_index')) is int for r in rows)
        orders={}
        if native:orders={r['signature']:r['transaction_index'] for r in rows}
        else:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='stream_order'").fetchone()
            if exists:
                orders=dict(db.execute('SELECT signature,rank FROM stream_order WHERE scope=? AND slot=?',
                                       (scope,slot)))
            if not signatures.issubset(orders):
                if len(signatures)==1:orders={next(iter(signatures)):0}
                else:raise ValueError('candidate_history_transaction_order_missing')
        for row in sorted(rows,key=lambda r:(orders[r['signature']],r['event_index'])):
            result.append((row,orders[row['signature']]))
    return result


def _enable_wal(db,*,seconds=30.0,monotonic=time.monotonic,sleeper=time.sleep):
    """Make concurrent Pump/Meteora opens safe without retrying strategy work."""
    deadline=monotonic()+float(seconds)
    db.execute("PRAGMA busy_timeout=0")
    try:
        while True:
            try:return db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            except sqlite3.OperationalError as exc:
                code=getattr(exc,"sqlite_errorcode",None)
                if code is None or (code & 255) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                    raise
                remaining=deadline-monotonic()
                if remaining<=0:raise
                sleeper(min(.05,remaining))
    finally:
        db.execute("PRAGMA busy_timeout=30000")


class CandidateHistory:
    def __init__(self,path=None,*,clock=time.time,worker_capacity=None):
        value=path or os.environ.get("MM_SOLANA_CANDIDATE_HISTORY_DB")
        if not value:raise ValueError("candidate_history_path_required")
        self.path=Path(value)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.clock=clock
        self.worker_capacity=int(worker_capacity or os.environ.get("MM_SOLANA_EXPENSIVE_WORKERS","2"))
        if not 1<=self.worker_capacity<=32:raise ValueError("candidate_history_worker_capacity")
        self.db=sqlite3.connect(str(self.path),timeout=30,isolation_level=None,check_same_thread=False)
        self.db.execute("PRAGMA busy_timeout=30000")
        _enable_wal(self.db)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS candidates(
          lane TEXT NOT NULL,candidate TEXT NOT NULL,surface TEXT NOT NULL,
          first_observed INTEGER NOT NULL,last_observed INTEGER NOT NULL,
          decision_deadline INTEGER,body TEXT NOT NULL,hash TEXT NOT NULL,
          PRIMARY KEY(lane,candidate));
        CREATE INDEX IF NOT EXISTS candidates_deadline
          ON candidates(decision_deadline,lane,candidate);

        CREATE TABLE IF NOT EXISTS events(
          lane TEXT NOT NULL,candidate TEXT NOT NULL,identity TEXT NOT NULL,
          slot INTEGER NOT NULL,transaction_index INTEGER,event_index INTEGER NOT NULL,
          market_time INTEGER NOT NULL,kind TEXT NOT NULL,
          body TEXT NOT NULL,hash TEXT NOT NULL,
          PRIMARY KEY(lane,candidate,identity));
        CREATE INDEX IF NOT EXISTS candidate_events_order
          ON events(lane,candidate,slot,transaction_index,event_index,identity);

        CREATE TABLE IF NOT EXISTS decisions(
          id TEXT PRIMARY KEY,lane TEXT NOT NULL,candidate TEXT NOT NULL,
          mode TEXT NOT NULL,observed_at INTEGER NOT NULL,qualified INTEGER NOT NULL,
          body TEXT NOT NULL,hash TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS decisions_candidate
          ON decisions(lane,candidate,observed_at,mode);

        CREATE TABLE IF NOT EXISTS funding(
          id TEXT PRIMARY KEY,decision_id TEXT NOT NULL,lane TEXT NOT NULL,
          candidate TEXT NOT NULL,status TEXT NOT NULL,at INTEGER NOT NULL,
          reason TEXT,body TEXT NOT NULL,hash TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS funding_decision ON funding(decision_id,at);

        CREATE TABLE IF NOT EXISTS work(
          id TEXT PRIMARY KEY,lane TEXT NOT NULL,candidate TEXT NOT NULL,
          kind TEXT NOT NULL,ready_at REAL NOT NULL,deadline REAL NOT NULL,
          estimate_seconds REAL NOT NULL,priority INTEGER NOT NULL,
          status TEXT NOT NULL,worker TEXT,lease_until REAL,
          created_at REAL NOT NULL,updated_at REAL NOT NULL,
          body TEXT NOT NULL,hash TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS work_edf
          ON work(status,ready_at,deadline,priority,created_at,id);
        CREATE TABLE IF NOT EXISTS work_observations(
          id TEXT PRIMARY KEY,work_id TEXT NOT NULL,kind TEXT NOT NULL,
          at REAL NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history_coverage(
          id TEXT PRIMARY KEY,scope TEXT NOT NULL,lower_slot INTEGER NOT NULL,
          upper_slot INTEGER NOT NULL,lower_time INTEGER NOT NULL,
          upper_time INTEGER NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS work_history_requirements(
          work_id TEXT PRIMARY KEY,scope TEXT NOT NULL,lo INTEGER NOT NULL,hi INTEGER NOT NULL,
          retry_at REAL NOT NULL,created REAL NOT NULL,reason TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS work_history_proofs(
          id TEXT PRIMARY KEY,scope TEXT NOT NULL,lo INTEGER NOT NULL,hi INTEGER NOT NULL,
          available REAL NOT NULL,hash TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS work_history_proof_scope ON work_history_proofs(scope,lo,hi);
        CREATE TABLE IF NOT EXISTS canonical_event_refs(
          lane TEXT NOT NULL,candidate TEXT NOT NULL,identity TEXT NOT NULL,
          slot INTEGER NOT NULL,transaction_index INTEGER,event_index INTEGER NOT NULL,
          market_time INTEGER NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL,
          PRIMARY KEY(lane,candidate,identity));
        CREATE INDEX IF NOT EXISTS canonical_ref_order ON canonical_event_refs(lane,candidate,slot,transaction_index,event_index);
        CREATE TABLE IF NOT EXISTS state_checkpoints(
          id TEXT PRIMARY KEY,scope TEXT NOT NULL,candidate TEXT NOT NULL,slot INTEGER NOT NULL,
          market_time INTEGER NOT NULL,available REAL NOT NULL,frontier INTEGER NOT NULL,
          proof TEXT NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS checkpoint_frontier ON state_checkpoints(scope,candidate,slot);
        """)

    @contextmanager
    def transaction(self):
        # A bounded outbox batch commits all native observations in one FULL
        # transaction. Nested helpers retain their atomic rollback boundaries.
        if self.db.in_transaction:
            self._transaction_sequence=getattr(self,'_transaction_sequence',0)+1
            name='candidate_'+str(self._transaction_sequence)
            self.db.execute('SAVEPOINT '+name)
            try:
                yield
                self.db.execute('RELEASE '+name)
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute('ROLLBACK TO '+name);self.db.execute('RELEASE '+name)
                raise
            return
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:self.db.execute("ROLLBACK")
            raise

    def close(self):
        for db in getattr(self,'_source_readers',{}).values():db.close()
        self.db.close()

    def append_reference(self,lane,candidate,record,*,path,identity,kind,payload_fields=None):
        """Index/view only. Economics remain in the one canonical reservoir."""
        ref=dict(path=str(Path(path).resolve()),canonical_identity=record['identity'],
            canonical_hash=digest(record),fields=dict(payload_fields or {}))
        body=self._reference_body(lane,candidate,identity,kind,ref)
        with self.transaction():
            old=self.event(lane,candidate,identity)
            if old is not None and old!=body:raise ValueError('candidate_history_event_conflict')
            self.db.execute('INSERT OR IGNORE INTO canonical_event_refs VALUES(?,?,?,?,?,?,?,?,?,?)',
                (lane,candidate,identity,body['slot'],body['transaction_index'],body['event_index'],
                 body['market_time'],kind,canonical(ref),digest(ref)))
            # One-way migration removes an identical legacy copy, not its history.
            self.db.execute('DELETE FROM events WHERE lane=? AND candidate=? AND identity=?',(lane,candidate,identity))
        return body

    def _reference_body(self,lane,candidate,identity,kind,ref):
        from meme_machine.solana_evidence_plane import decode_body
        self._source_readers=getattr(self,'_source_readers',{})
        if ref['path'] not in self._source_readers:
            self._source_readers[ref['path']]=sqlite3.connect(Path(ref['path']).as_uri()+'?mode=ro',uri=True,timeout=30)
        db=self._source_readers[ref['path']]
        row=db.execute('SELECT body,hash,archive FROM canonical_evidence WHERE identity=?',(ref['canonical_identity'],)).fetchone()
        if row is None:raise ValueError('candidate_canonical_reference_missing')
        if row[0] is not None:r=decode_body(row[0],db)
        else:
            import hashlib,zlib
            manifest=db.execute('SELECT path,hash FROM scoped_cold_manifests WHERE id=?',(row[2],)).fetchone()
            if manifest is None:raise ValueError('candidate_canonical_reference_requires_restore')
            packed=Path(manifest[0]).read_bytes()
            if hashlib.sha256(packed).hexdigest()!=manifest[1]:raise ValueError('candidate_history_corruption')
            decoder=zlib.decompressobj();raw=decoder.decompress(packed,32*1024*1024+1)
            if not decoder.eof or len(raw)>32*1024*1024:raise ValueError('candidate_canonical_archive_bound')
            r=next((x['record'] for x in json.loads(raw) if x['record']['identity']==ref['canonical_identity']),None)
        if r is None or digest(r)!=row[1] or row[1]!=ref['canonical_hash']:raise ValueError('candidate_history_corruption')
        # Scoped Meteora packets already contain only the authenticated
        # instruction, balance, event and ordering fields consumed by DLMM.
        # An index resolves that one packet; it never stores a per-pool copy.
        payload=r['payload']['event'] if r['kind']=='event' else r['payload']
        return dict(lane=lane,candidate=candidate,identity=identity,slot=r['slot'],
            transaction_index=r['transaction_index'],event_index=r['event_index'],market_time=r['market_time'],
            kind=kind,payload=dict(payload,**ref['fields']))

    def checkpoint(self,scope,candidate,snapshot,*,proof,frontier):
        """Authoritative state anchor, never permission to skip a delta/gap.

        DLMM validate authenticates exact layout/owners/mints/vaults/bins at one
        finalized context. The proof stores that context's RPC receipt hash.
        """
        if scope!='program:meteora':raise ValueError('candidate_checkpoint_scope')
        from meme_machine.lanes.meteora import dlmm
        state=dlmm.validate(snapshot,snapshot['available_time'],'real')
        if state['pool']!=candidate or len(proof)!=64 or type(frontier) is not int or frontier<0:
            raise ValueError('candidate_checkpoint_identity')
        body=dict(snapshot=snapshot,state=state,history_frontier=frontier)
        identity=digest([scope,candidate,snapshot['slot'],proof])
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO state_checkpoints VALUES(?,?,?,?,?,?,?,?,?,?)',
                (identity,scope,candidate,snapshot['slot'],snapshot['market_time'],snapshot['available_time'],
                 frontier,proof,canonical(body),digest(body)))
        return identity

    def latest_checkpoint(self,scope,candidate,*,as_of,maximum_age=None):
        for raw,checksum,available in self.db.execute('SELECT body,hash,available FROM state_checkpoints WHERE scope=? AND candidate=? AND available<=? ORDER BY slot DESC',(scope,candidate,as_of)):
            body=json.loads(raw)
            if digest(body)!=checksum:raise ValueError('candidate_history_corruption')
            if maximum_age is None or as_of-body['snapshot']['market_time']<=maximum_age:return body
        return None

    @staticmethod
    def _required(value,name):
        value=str(value or "")
        if not value:raise ValueError("candidate_history_"+name)
        return value

    def observe(self,lane,candidate,*,surface,observed_at,decision_deadline=None,metadata=None):
        lane=self._required(lane,"lane");candidate=self._required(candidate,"candidate")
        surface=self._required(surface,"surface");observed_at=int(observed_at)
        deadline=None if decision_deadline is None else int(decision_deadline)
        if deadline is not None and deadline<observed_at:
            raise ValueError("candidate_history_deadline_before_observation")
        metadata=dict(metadata or {})
        with self.transaction():
            prior=self.db.execute(
                "SELECT first_observed,last_observed,decision_deadline,body,hash FROM candidates WHERE lane=? AND candidate=?",
                (lane,candidate)).fetchone()
            first=observed_at if prior is None else min(observed_at,int(prior[0]))
            last=observed_at if prior is None else max(observed_at,int(prior[1]))
            prior_deadline=None if prior is None else prior[2]
            if prior is not None:
                prior_body=json.loads(prior[3])
                if digest(prior_body)!=prior[4]:raise ValueError("candidate_history_corruption")
                metadata=dict(prior_body.get("metadata") or {},**metadata)
            if deadline is None:deadline=prior_deadline
            # A fresh reactivation may have a new decision window. Work items
            # retain their original immutable deadlines independently.
            body=dict(lane=lane,candidate=candidate,surface=surface,first_observed=first,
                      last_observed=last,decision_deadline=deadline,metadata=metadata)
            encoded=canonical(body);checksum=digest(body)
            self.db.execute("""INSERT OR REPLACE INTO candidates
                (lane,candidate,surface,first_observed,last_observed,decision_deadline,body,hash)
                VALUES(?,?,?,?,?,?,?,?)""",
                (lane,candidate,surface,first,last,deadline,encoded,checksum))
        return body

    def candidate(self,lane,candidate):
        row=self.db.execute("SELECT body,hash FROM candidates WHERE lane=? AND candidate=?",
                            (lane,candidate)).fetchone()
        if row is None:return None
        body=json.loads(row[0])
        if digest(body)!=row[1]:raise ValueError("candidate_history_corruption")
        return body

    def candidates(self,*,lane=None):
        sql="SELECT body,hash FROM candidates"
        args=()
        if lane is not None:
            sql+=" WHERE lane=?";args=(str(lane),)
        sql+=" ORDER BY first_observed,lane,candidate"
        result=[]
        for raw,checksum in self.db.execute(sql,args):
            body=json.loads(raw)
            if digest(body)!=checksum:raise ValueError("candidate_history_corruption")
            result.append(body)
        return result

    def append_event(self,lane,candidate,*,identity,slot,transaction_index,event_index,
                     market_time,kind,payload):
        lane=self._required(lane,"lane");candidate=self._required(candidate,"candidate")
        identity=self._required(identity,"event_identity");kind=self._required(kind,"event_kind")
        if type(slot) is not int or slot<0 or type(event_index) is not int or event_index<0:
            raise ValueError("candidate_history_event_order")
        if transaction_index is not None and (type(transaction_index) is not int or transaction_index<0):
            raise ValueError("candidate_history_transaction_order")
        if type(market_time) is not int or not isinstance(payload,dict):
            raise ValueError("candidate_history_event_shape")
        body=dict(lane=lane,candidate=candidate,identity=identity,slot=slot,
                  transaction_index=transaction_index,event_index=event_index,
                  market_time=market_time,kind=kind,payload=payload)
        encoded=canonical(body);checksum=digest(body)
        with self.transaction():
            ref=self.db.execute('SELECT body,hash FROM canonical_event_refs WHERE lane=? AND candidate=? AND identity=?',(lane,candidate,identity)).fetchone()
            if ref:
                value=json.loads(ref[0])
                if digest(value)!=ref[1] or self._reference_body(lane,candidate,identity,kind,value)!=body:
                    raise ValueError('candidate_history_event_conflict')
                return body
            old=self.db.execute(
                "SELECT body,hash FROM events WHERE lane=? AND candidate=? AND identity=?",
                (lane,candidate,identity)).fetchone()
            if old:
                if old[0]!=encoded or old[1]!=checksum:raise ValueError("candidate_history_event_conflict")
                return body
            self.db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                (lane,candidate,identity,slot,transaction_index,event_index,
                 market_time,kind,encoded,checksum))
        return body

    def events(self,lane,candidate,*,through=None):
        sql="""SELECT body,hash FROM events WHERE lane=? AND candidate=?"""
        args=[lane,candidate]
        if through is not None:
            sql+=" AND market_time<=?";args.append(int(through))
        # Unknown transaction order sorts after proven order in the same slot.
        sql+=" ORDER BY slot,(COALESCE(json_extract(body,'$.payload._economic_order'),transaction_index) IS NULL),COALESCE(json_extract(body,'$.payload._economic_order'),transaction_index),event_index,identity"
        result=[]
        for raw,checksum in self.db.execute(sql,args):
            body=json.loads(raw)
            if digest(body)!=checksum:raise ValueError("candidate_history_corruption")
            result.append(body)
        refs='SELECT identity,kind,body,hash FROM canonical_event_refs WHERE lane=? AND candidate=?'
        params=[lane,candidate]
        if through is not None:refs+=' AND market_time<=?';params.append(int(through))
        for identity,kind,raw,checksum in self.db.execute(refs,params):
            ref=json.loads(raw)
            if digest(ref)!=checksum:raise ValueError('candidate_history_corruption')
            result.append(self._reference_body(lane,candidate,identity,kind,ref))
        result.sort(key=lambda r:(r['slot'],r['payload'].get('_economic_order',r['transaction_index']) is None,
            r['payload'].get('_economic_order',r['transaction_index']) or 0,r['event_index'],r['identity']))
        return result

    def event(self,lane,candidate,identity):
        row=self.db.execute('SELECT body,hash FROM events WHERE lane=? AND candidate=? AND identity=?',
                            (lane,candidate,identity)).fetchone()
        if row is None:
            ref=self.db.execute('SELECT kind,body,hash FROM canonical_event_refs WHERE lane=? AND candidate=? AND identity=?',(lane,candidate,identity)).fetchone()
            if ref is None:return None
            body=json.loads(ref[1])
            if digest(body)!=ref[2]:raise ValueError('candidate_history_corruption')
            return self._reference_body(lane,candidate,identity,ref[0],body)
        body=json.loads(row[0])
        if digest(body)!=row[1]:raise ValueError('candidate_history_corruption')
        return body

    def event_order_status(self,lane,candidate):
        """An identity tie breaker cannot manufacture chain transaction order."""
        total,unknown,native_missing=self.db.execute("""SELECT COUNT(*),
            COALESCE(SUM(transaction_index IS NULL AND json_type(body,'$.payload._economic_order') IS NOT 'integer'),0),
            COALESCE(SUM(transaction_index IS NULL),0)
            FROM (SELECT transaction_index,body FROM events WHERE lane=? AND candidate=?
                  UNION ALL SELECT transaction_index,body FROM canonical_event_refs WHERE lane=? AND candidate=?)""",
            (lane,candidate,lane,candidate)).fetchone()
        return dict(events=total,unknown_transaction_order=unknown,
                    native_index_missing=native_missing,
                    complete=total>0 and unknown==0)

    def retain_pump_source_history(self,rows,*,graduation_horizon=None):
        retained=0
        for record in rows or ():
            event=dict(record.get('event') or {})
            mint=str(event.get('mint') or '')
            if not mint:continue
            at=int(event.get('market_time') or record['market_time'])
            prior=self.candidate('pump',mint)
            kind=str(event.get('event_type') or 'economic')
            promoted=kind=='migration' or (prior is not None and prior['surface']=='pumpswap')
            deadline=(at+graduation_horizon if kind=='migration' and graduation_horizon is not None else None)
            metadata=dict(source='solana_finalized_evidence_plane')
            for key in ('creator','pool'):
                if event.get(key):metadata[key]=str(event[key])
            self.observe('pump',mint,surface='pumpswap' if promoted else 'pump.fun',
                observed_at=at,decision_deadline=deadline,metadata=metadata)
            self.append_event('pump',mint,identity='pump-source:'+str(record['identity']),
                slot=int(record['slot']),transaction_index=record.get('transaction_index'),
                event_index=int(record['event_index']),market_time=at,
                kind='pump_'+kind,payload=event)
            retained+=1
        return retained

    def retain_pumpswap_record(self,candidate,record,transaction_order):
        """Current and Survivor commit one canonical normalized event.

        Relative filtered ranks are retained as order witnesses in the payload.
        The native chain index remains null unless the canonical source has it.
        This representation is independent of a consumer's requested window.
        """
        event=dict(record['payload']['event'])
        event['_economic_order']=int(transaction_order)
        return self.append_event('pump',candidate,
            identity=str(event.get('id') or record['identity']),slot=int(record['slot']),
            transaction_index=record.get('transaction_index'),event_index=int(record['event_index']),
            market_time=int(record['market_time']),kind='pumpswap_trade',payload=event)

    def commit_coverage(self,scope,lower_slot,upper_slot,lower_time,upper_time,*,proof_hash,candidate=None):
        """A canonical reader supplies the proof after all normalized rows commit.

        This does not infer continuity from an earliest event or a highest slot.
        Empty covered intervals are witnesses too. Failed/partial consumption
        cannot advance this boundary.
        """
        if (not scope or any(type(v) is not int for v in (lower_slot,upper_slot,lower_time,upper_time))
                or lower_slot<0 or upper_slot<lower_slot or upper_time<lower_time
                or len(proof_hash)!=64):raise ValueError('candidate_history_coverage_shape')
        if candidate is not None:scope=scope+'\x1f'+self._required(candidate,'candidate')
        body=dict(scope=scope,lower_slot=lower_slot,upper_slot=upper_slot,
                  lower_time=lower_time,upper_time=upper_time,proof_hash=proof_hash)
        identity=digest(body)
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO history_coverage VALUES(?,?,?,?,?,?,?,?)',
                (identity,scope,lower_slot,upper_slot,lower_time,upper_time,canonical(body),digest(body)))
        return identity

    def covered_events(self,lane,candidate,scope,lower_time,upper_time,*,upper_slot=None):
        windows=[]
        # Candidate-filtered delivery proves this identity only. The legacy
        # program-wide coverage remains valid for the earlier full source, but
        # selective publication must never mint it for every other candidate.
        scoped=scope+'\x1f'+candidate
        coverage_scope=scoped if self.db.execute('SELECT 1 FROM history_coverage WHERE scope=? LIMIT 1',(scoped,)).fetchone() else scope
        for raw,checksum in self.db.execute('SELECT body,hash FROM history_coverage WHERE scope=? ORDER BY lower_slot,upper_slot',(coverage_scope,)):
            body=json.loads(raw)
            if digest(body)!=checksum:raise ValueError('candidate_history_corruption')
            windows.append(body)
        lower=next((w for w in reversed(windows) if w['lower_time']<=lower_time),None)
        if lower is None:raise ValueError('candidate_history_continuity_missing')
        end=lower['upper_slot'];end_time=lower['upper_time']
        for window in windows:
            if lower['lower_slot']<=window['lower_slot']<=end+1:
                end=max(end,window['upper_slot']);end_time=max(end_time,window['upper_time'])
        if end_time<upper_time or (upper_slot is not None and end<upper_slot):
            raise ValueError('candidate_history_continuity_missing')
        rows=[r for r in self.events(lane,candidate,through=upper_time)
              if lower_time<=r['market_time'] and (upper_slot is None or r['slot']<=upper_slot)
              and (r['kind'].startswith('pumpswap_') if scope=='program:pumpswap'
                   else r['kind'].startswith('pump_'))]
        if any(r['transaction_index'] is None and type(r['payload'].get('_economic_order')) is not int for r in rows):
            raise ValueError('candidate_history_transaction_order_missing')
        return [dict(r['payload']) for r in rows]

    def wait_for_history(self,identity,scope,lo,hi,*,retry_at,reason='required_history_unsealed',now=None):
        """Release a warming lease until an exact durable interval is ready.

        The timer is a wakeup for explicit failure/timeout handling, never a
        continuity proof or a new economic decision deadline.
        """
        now=float(self.clock() if now is None else now)
        if not scope or type(lo) is not int or type(hi) is not int or not 0<=lo<=hi:
            raise ValueError('candidate_history_work_requirement')
        with self.transaction():
            row=self.db.execute('SELECT deadline,status FROM work WHERE id=?',(identity,)).fetchone()
            if row is None:raise ValueError('candidate_history_work_unknown')
            if row[1]=='deadline_missed':raise ValueError('candidate_history_deadline_disposition_immutable')
            self.db.execute('INSERT OR REPLACE INTO work_history_requirements VALUES(?,?,?,?,?,?,?)',
                (identity,scope,lo,hi,min(float(retry_at),row[0]),now,reason))
            self.db.execute("UPDATE work SET status='pending',worker=NULL,lease_until=NULL,ready_at=?,updated_at=? WHERE id=?",
                (now,now,identity))
            self._work_observation(identity,'history_blocked',now,dict(scope=scope,lo=lo,hi=hi,reason=reason,deadline_reset=False))

    def commit_history_readiness(self,scope,lo,hi,*,proof_hash,available=None):
        """Receive a canonical complete witness after consumer durability.

        These are scheduling receipts, not normalized economic history or entry
        authority. Disjoint complete islands cannot fill an unproved interval.
        """
        at=float(self.clock() if available is None else available)
        if not scope or type(lo) is not int or type(hi) is not int or not 0<=lo<=hi or len(proof_hash)!=64:
            raise ValueError('candidate_history_work_proof')
        body=dict(scope=scope,lo=lo,hi=hi,proof_hash=proof_hash)
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO work_history_proofs VALUES(?,?,?,?,?,?)',
                (digest(body),scope,lo,hi,at,proof_hash))
            spans=self.db.execute('SELECT lo,hi FROM work_history_proofs WHERE scope=? AND available<=? ORDER BY lo,hi',(scope,at)).fetchall()
            for identity,lower,upper in self.db.execute('SELECT work_id,lo,hi FROM work_history_requirements WHERE scope=?',(scope,)).fetchall():
                cursor=lower
                for a,b in spans:
                    if b<cursor:continue
                    if a>cursor:break
                    cursor=max(cursor,b+1)
                    if cursor>upper:break
                if cursor>upper:
                    self.db.execute('DELETE FROM work_history_requirements WHERE work_id=?',(identity,))
                    self._work_observation(identity,'history_ready',at,dict(scope=scope,lo=lower,hi=upper,proof_hash=proof_hash,deadline_reset=False))

    def record_decision(self,lane,candidate,*,mode,observed_at,qualified,decision):
        lane=self._required(lane,"lane");candidate=self._required(candidate,"candidate")
        mode=self._required(mode,"mode");observed_at=int(observed_at)
        if type(qualified) is not bool or not isinstance(decision,dict):
            raise ValueError("candidate_history_decision_shape")
        body=dict(lane=lane,candidate=candidate,mode=mode,observed_at=observed_at,
                  qualified=qualified,decision=decision)
        identity=digest([lane,candidate,mode,observed_at,body])
        encoded=canonical(body);checksum=digest(body)
        with self.transaction():
            old=self.db.execute("SELECT body,hash FROM decisions WHERE id=?",(identity,)).fetchone()
            if old:
                if old[0]!=encoded or old[1]!=checksum:raise ValueError("candidate_history_decision_conflict")
            else:
                self.db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?)",
                    (identity,lane,candidate,mode,observed_at,int(qualified),encoded,checksum))
        return identity

    def record_funding(self,decision_id,lane,candidate,*,status,at,reason=None,details=None):
        if status not in ("funded","denied"):raise ValueError("candidate_history_funding_status")
        lane=self._required(lane,"lane");candidate=self._required(candidate,"candidate")
        decision_id=self._required(decision_id,"decision_id");at=int(at)
        body=dict(decision_id=decision_id,lane=lane,candidate=candidate,status=status,
                  at=at,reason=None if reason is None else str(reason),details=dict(details or {}))
        identity=digest([decision_id,status,at,body["reason"],body["details"]])
        encoded=canonical(body);checksum=digest(body)
        with self.transaction():
            decision=self.db.execute("SELECT lane,candidate,qualified FROM decisions WHERE id=?",(decision_id,)).fetchone()
            if decision is None:
                raise ValueError("candidate_history_funding_without_decision")
            if decision!=(lane,candidate,1):
                raise ValueError("candidate_history_funding_without_qualification")
            # One qualification decision has exactly one funding disposition.
            # A retry of the same disposition is idempotent; funded->denied (or
            # denied->funded) would rewrite economic history and is rejected.
            prior=self.db.execute(
                "SELECT id,status,body,hash FROM funding WHERE decision_id=? ORDER BY at,id LIMIT 1",
                (decision_id,)).fetchone()
            if prior:
                prior_body=json.loads(prior[2])
                if digest(prior_body)!=prior[3]:raise ValueError("candidate_history_corruption")
                if prior[1]!=status:
                    raise ValueError("candidate_history_funding_outcome_conflict")
                return prior[0]
            old=self.db.execute("SELECT body,hash FROM funding WHERE id=?",(identity,)).fetchone()
            if old:
                if old[0]!=encoded or old[1]!=checksum:raise ValueError("candidate_history_funding_conflict")
            else:self.db.execute("INSERT INTO funding VALUES(?,?,?,?,?,?,?,?,?)",
                (identity,decision_id,lane,candidate,status,at,body["reason"],encoded,checksum))
        return identity

    def funding_outcome(self,decision_id):
        row=self.db.execute(
            "SELECT id,status,body,hash FROM funding WHERE decision_id=? ORDER BY at,id LIMIT 1",
            (str(decision_id),)).fetchone()
        if row is None:return None
        body=json.loads(row[2])
        if digest(body)!=row[3]:raise ValueError("candidate_history_corruption")
        return dict(body,id=row[0])

    def enqueue(self,lane,candidate,*,kind,ready_at,deadline,estimate_seconds,
                payload=None,priority=50,identity=None):
        lane=self._required(lane,"lane");candidate=self._required(candidate,"candidate")
        kind=self._required(kind,"work_kind")
        ready_at=float(ready_at);deadline=float(deadline);estimate=float(estimate_seconds)
        if estimate<=0 or deadline<0:raise ValueError("candidate_history_work_window")
        if type(priority) is not int:raise ValueError("candidate_history_work_priority")
        payload=dict(payload or {})
        identity=identity or digest([lane,candidate,kind,ready_at,deadline,payload])
        body=dict(lane=lane,candidate=candidate,kind=kind,ready_at=ready_at,deadline=deadline,
                  estimate_seconds=estimate,priority=priority,payload=payload)
        encoded=canonical(body);checksum=digest(body);now=float(self.clock())
        with self.transaction():
            old=self.db.execute("SELECT body,hash,status FROM work WHERE id=?",(identity,)).fetchone()
            if old:
                if old[0]!=encoded or old[1]!=checksum:raise ValueError("candidate_history_work_conflict")
                return identity
            self.db.execute("""INSERT INTO work
                (id,lane,candidate,kind,ready_at,deadline,estimate_seconds,priority,status,
                 worker,lease_until,created_at,updated_at,body,hash)
                VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL,?,?,?,?)""",
                (identity,lane,candidate,kind,ready_at,deadline,estimate,priority,"pending",
                 now,now,encoded,checksum))
            depth=self.db.execute("SELECT COUNT(*) FROM work WHERE status IN ('pending','active')").fetchone()[0]
            if depth>self.worker_capacity:
                self._work_observation(identity,'capacity_pressure',now,
                    dict(queue_depth=depth,worker_capacity=self.worker_capacity,
                         economic_rejection=False))
        return identity

    def _work_observation(self,identity,kind,at,details):
        body=dict(work_id=identity,kind=kind,at=at,details=details)
        self.db.execute("INSERT OR IGNORE INTO work_observations VALUES(?,?,?,?,?,?)",
            (digest(body),identity,kind,at,canonical(body),digest(body)))

    def work_observations(self,*,kind=None):
        sql="SELECT body,hash FROM work_observations"
        args=()
        if kind is not None:sql+=" WHERE kind=?";args=(kind,)
        result=[]
        for raw,checksum in self.db.execute(sql+" ORDER BY at,id",args):
            body=json.loads(raw)
            if digest(body)!=checksum:raise ValueError('candidate_history_corruption')
            result.append(body)
        return result

    def claim(self,worker,*,now=None,capacity=None,lane=None):
        worker=self._required(worker,"worker")
        lane=None if lane is None else self._required(lane,"lane")
        now=float(self.clock() if now is None else now)
        capacity=self.worker_capacity if capacity is None else int(capacity)
        if not 1<=capacity<=32:raise ValueError("candidate_history_worker_capacity")
        missed=None;claimed=None
        with self.transaction():
            self.db.execute("""UPDATE work SET status='pending',worker=NULL,lease_until=NULL,updated_at=?
                WHERE status='active' AND lease_until IS NOT NULL AND lease_until<=?""",(now,now))
            active=self.db.execute(
                "SELECT COUNT(*) FROM work WHERE status='active' AND lease_until>?",(now,)).fetchone()[0]
            where="""status='pending' AND ready_at<=? AND (deadline<=? OR NOT EXISTS(
                SELECT 1 FROM work_history_requirements r WHERE r.work_id=work.id AND r.retry_at>?))"""
            args=[now,now,now]
            if lane is not None:where+=" AND lane=?";args.append(lane)
            # Safety/positions/continuation precede admission; admission is EDF.
            row=self.db.execute("""SELECT id,lane,candidate,kind,ready_at,deadline,estimate_seconds,
                    priority,created_at,body,hash FROM work WHERE """+where+
                " ORDER BY CASE WHEN priority<=2 THEN priority ELSE 3 END,deadline,priority,created_at,id LIMIT 1",args).fetchone()
            if row is not None:
                keys=("id","lane","candidate","kind","ready_at","deadline","estimate_seconds",
                      "priority","created_at","body","hash")
                work=dict(zip(keys,row))
                body=json.loads(work.pop("body"));checksum=work.pop("hash")
                if digest(body)!=checksum:raise ValueError("candidate_history_corruption")
                work["payload"]=body["payload"]
                # Estimates reserve resources; they are not evidence that an
                # opportunity is already impossible. A conservative upper bound
                # must never reject a job that can still finish in time.
                if now>=float(work["deadline"]):
                    self.db.execute("""UPDATE work SET status='deadline_missed',worker=NULL,
                        lease_until=NULL,updated_at=? WHERE id=?""",(now,work["id"]))
                    self._work_observation(work["id"],'deadline_missed',now,
                        dict(work=work,active_workers=active,worker_capacity=capacity,
                             economic_rejection=False,qualification_complete=False))
                    missed=work
                elif active<capacity:
                    from meme_machine.solana_prewarm_startup import candidate_release
                    if not candidate_release(os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB')):return None
                    lease=min(work["deadline"],now+max(1.0,work["estimate_seconds"]*2.0))
                    self.db.execute("""UPDATE work SET status='active',worker=?,lease_until=?,updated_at=?
                        WHERE id=? AND status='pending'""",(worker,lease,now,work["id"]))
                    claimed=dict(work,status="active",worker=worker,lease_until=lease)
        # Persist the failure before propagating it. Raising inside transaction()
        # rolled back PR #120's only record of the miss and blocked later jobs.
        if missed is not None:raise CandidateDeadlineMissed(missed)
        return claimed

    def complete(self,identity,*,status="complete",details=None,now=None):
        if status not in ("complete","deferred","failed"):raise ValueError("candidate_history_work_status")
        now=float(self.clock() if now is None else now)
        with self.transaction():
            row=self.db.execute("SELECT body,hash,status FROM work WHERE id=?",(str(identity),)).fetchone()
            if row is None:raise ValueError("candidate_history_work_unknown")
            if row[2]=="deadline_missed":raise ValueError("candidate_history_deadline_disposition_immutable")
            body=json.loads(row[0])
            if digest(body)!=row[1]:raise ValueError("candidate_history_corruption")
            if now>float(body['deadline']):
                status='deadline_missed'
                details=dict(details or {},qualification_complete=False,
                             economic_rejection=False,completed_after_deadline=True)
            if status=="deferred":
                # Preserve the original deadline. Deferral changes only readiness
                # and never turns saturation into a candidate rejection.
                delay=float((details or {}).get("delay_seconds",0.25))
                ready=min(float(body["deadline"]),now+max(0.0,delay))
                self.db.execute("""UPDATE work SET status='pending',ready_at=?,worker=NULL,
                    lease_until=NULL,updated_at=? WHERE id=?""",(ready,now,str(identity)))
            else:
                self.db.execute("""UPDATE work SET status=?,worker=NULL,lease_until=NULL,
                    updated_at=? WHERE id=?""",(status,now,str(identity)))
            self._work_observation(str(identity),status,now,dict(details or {}))
        return dict(id=str(identity),status=status,details=dict(details or {}))

    def pending(self,*,lane=None):
        if lane is None:
            return self.db.execute("SELECT COUNT(*) FROM work WHERE status='pending'").fetchone()[0]
        return self.db.execute("SELECT COUNT(*) FROM work WHERE status='pending' AND lane=?",(str(lane),)).fetchone()[0]

    def telemetry(self,*,now=None):
        now=float(self.clock() if now is None else now)
        states=dict(self.db.execute("SELECT status,COUNT(*) FROM work GROUP BY status"))
        oldest=self.db.execute("SELECT MIN(deadline) FROM work WHERE status='pending'").fetchone()[0]
        queued=self.db.execute("SELECT MIN(created_at),COUNT(*) FROM work WHERE status='pending'").fetchone()
        pressure=self.work_observations(kind='capacity_pressure')
        return dict(capacity_pressure=len(pressure),
                    deadline_misses=len(self.work_observations(kind='deadline_missed')),
                    maximum_queue_depth=max((p['details']['queue_depth'] for p in pressure),default=0),
                    oldest_queued_age_seconds=0 if queued[0] is None else max(0,now-queued[0]),
                    candidates=self.db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
                    events=self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                    decisions=self.db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0],
                    funding=self.db.execute("SELECT COUNT(*) FROM funding").fetchone()[0],
                    work=states,oldest_pending_deadline=oldest,
                    oldest_pending_slack_seconds=None if oldest is None else float(oldest)-now,
                    worker_capacity=self.worker_capacity)


class ThreadLocalCandidateHistory:
    """Shared lane facade with one native SQLite connection per worker thread."""
    def __init__(self,path,*,clock=time.time):
        import threading
        self.path=Path(path);self.clock=clock;self._local=threading.local()
    def _history(self):
        history=getattr(self._local,'history',None)
        if history is None:
            history=CandidateHistory(self.path,clock=self.clock);self._local.history=history
        return history
    def __getattr__(self,name):return getattr(self._history(),name)
    def close(self):
        history=getattr(self._local,'history',None)
        if history is not None:history.close();self._local.history=None

def open_candidate_history(*,clock=time.time):
    path=os.environ.get("MM_SOLANA_CANDIDATE_HISTORY_DB")
    return None if not path else ThreadLocalCandidateHistory(path,clock=clock)
