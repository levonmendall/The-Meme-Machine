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
        """)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):self.db.close()

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
                "SELECT first_observed,last_observed,decision_deadline,body FROM candidates WHERE lane=? AND candidate=?",
                (lane,candidate)).fetchone()
            first=observed_at if prior is None else min(observed_at,int(prior[0]))
            last=observed_at if prior is None else max(observed_at,int(prior[1]))
            prior_deadline=None if prior is None else prior[2]
            if deadline is None:deadline=prior_deadline
            elif prior_deadline is not None:deadline=min(int(prior_deadline),deadline)
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
        sql+=" ORDER BY slot,(transaction_index IS NULL),transaction_index,event_index,identity"
        result=[]
        for raw,checksum in self.db.execute(sql,args):
            body=json.loads(raw)
            if digest(body)!=checksum:raise ValueError("candidate_history_corruption")
            result.append(body)
        return result

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
            if self.db.execute("SELECT 1 FROM decisions WHERE id=?",(decision_id,)).fetchone() is None:
                raise ValueError("candidate_history_funding_without_decision")
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
        return dict(id=row[0],status=row[1],**body)

    def enqueue(self,lane,candidate,*,kind,ready_at,deadline,estimate_seconds,
                payload=None,priority=50,identity=None):
        lane=self._required(lane,"lane");candidate=self._required(candidate,"candidate")
        kind=self._required(kind,"work_kind")
        ready_at=float(ready_at);deadline=float(deadline);estimate=float(estimate_seconds)
        if estimate<=0 or deadline<ready_at:raise ValueError("candidate_history_work_window")
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
        return identity

    def claim(self,worker,*,now=None,capacity=None,lane=None):
        worker=self._required(worker,"worker")
        lane=None if lane is None else self._required(lane,"lane")
        now=float(self.clock() if now is None else now)
        capacity=self.worker_capacity if capacity is None else int(capacity)
        if not 1<=capacity<=32:raise ValueError("candidate_history_worker_capacity")
        with self.transaction():
            self.db.execute("""UPDATE work SET status='pending',worker=NULL,lease_until=NULL,updated_at=?
                WHERE status='active' AND lease_until IS NOT NULL AND lease_until<=?""",(now,now))
            active=self.db.execute(
                "SELECT COUNT(*) FROM work WHERE status='active' AND lease_until>?",(now,)).fetchone()[0]
            # If all worker slots are occupied, fail explicitly as soon as the
            # oldest ready job can no longer finish by its deadline.  Saturation
            # is infrastructure truth, never a strategy rejection or silent drop.
            if active>=capacity:
                where="status='pending' AND ready_at<=?"
                args=[now]
                if lane is not None:
                    where+=" AND lane=?";args.append(lane)
                urgent=self.db.execute("""SELECT id,lane,candidate,kind,ready_at,deadline,
                        estimate_seconds,priority,created_at,body,hash FROM work WHERE """+where+
                    " ORDER BY deadline,priority,created_at,id LIMIT 1",args).fetchone()
                if urgent is not None and now+float(urgent[6])>float(urgent[5]):
                    keys=("id","lane","candidate","kind","ready_at","deadline","estimate_seconds",
                          "priority","created_at","body","hash")
                    work=dict(zip(keys,urgent))
                    body=json.loads(work.pop("body"));checksum=work.pop("hash")
                    if digest(body)!=checksum:raise ValueError("candidate_history_corruption")
                    work["payload"]=body["payload"]
                    raise CandidateDeadlineMissed(work)
                return None
            where="status='pending' AND ready_at<=?"
            args=[now]
            if lane is not None:
                where+=" AND lane=?";args.append(lane)
            row=self.db.execute("""SELECT id,lane,candidate,kind,ready_at,deadline,estimate_seconds,
                    priority,created_at,body,hash FROM work WHERE """+where+
                " ORDER BY deadline,priority,created_at,id LIMIT 1",args).fetchone()
            if row is None:return None
            keys=("id","lane","candidate","kind","ready_at","deadline","estimate_seconds",
                  "priority","created_at","body","hash")
            work=dict(zip(keys,row))
            body=json.loads(work.pop("body"));checksum=work.pop("hash")
            if digest(body)!=checksum:raise ValueError("candidate_history_corruption")
            work["payload"]=body["payload"]
            if work["deadline"]<now or now+float(work["estimate_seconds"])>work["deadline"]:
                raise CandidateDeadlineMissed(work)
            lease=min(work["deadline"],now+max(1.0,work["estimate_seconds"]*2.0))
            if lease<=now:raise CandidateDeadlineMissed(work)
            self.db.execute("""UPDATE work SET status='active',worker=?,lease_until=?,updated_at=?
                WHERE id=? AND status='pending'""",(worker,lease,now,work["id"]))
            work.update(status="active",worker=worker,lease_until=lease)
            return work

    def complete(self,identity,*,status="complete",details=None,now=None):
        if status not in ("complete","deferred","failed"):raise ValueError("candidate_history_work_status")
        now=float(self.clock() if now is None else now)
        with self.transaction():
            row=self.db.execute("SELECT body,hash FROM work WHERE id=?",(str(identity),)).fetchone()
            if row is None:raise ValueError("candidate_history_work_unknown")
            body=json.loads(row[0])
            if digest(body)!=row[1]:raise ValueError("candidate_history_corruption")
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
        return dict(id=str(identity),status=status,details=dict(details or {}))

    def pending(self,*,lane=None):
        if lane is None:
            return self.db.execute("SELECT COUNT(*) FROM work WHERE status='pending'").fetchone()[0]
        return self.db.execute("SELECT COUNT(*) FROM work WHERE status='pending' AND lane=?",(str(lane),)).fetchone()[0]

    def telemetry(self,*,now=None):
        now=float(self.clock() if now is None else now)
        states=dict(self.db.execute("SELECT status,COUNT(*) FROM work GROUP BY status"))
        oldest=self.db.execute("SELECT MIN(deadline) FROM work WHERE status='pending'").fetchone()[0]
        return dict(candidates=self.db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
                    events=self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                    decisions=self.db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0],
                    funding=self.db.execute("SELECT COUNT(*) FROM funding").fetchone()[0],
                    work=states,oldest_pending_deadline=oldest,
                    oldest_pending_slack_seconds=None if oldest is None else float(oldest)-now,
                    worker_capacity=self.worker_capacity)


def open_candidate_history(*,clock=time.time):
    path=os.environ.get("MM_SOLANA_CANDIDATE_HISTORY_DB")
    return None if not path else CandidateHistory(path,clock=clock)
