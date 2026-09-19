"""Shared stream-first Solana evidence broker.

This module is read-only infrastructure. It centralizes finalized event awareness,
immutable transaction hydration, deadline ordering, incremental cursors and provider
backpressure. It grants no strategy/allocation/signing authority.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from websockets.sync.client import connect

from .provider import Unavailable


DEFAULT_BROKER_DB = "solana-evidence-broker.sqlite3"

PRIORITY = {
    "position_monitor": 0,
    "pump_decision": 10,
    "pump_window": 20,
    "dlmm_fresh": 30,
    "research_history": 90,
}


def _priority(kind):
    return int(PRIORITY.get(str(kind), 50))


class EvidenceBroker:
    """Durable local evidence cache/queue with one global hydration controller."""

    def __init__(self, path=None, *, clock=time.time, sleeper=time.sleep):
        value = str(path or os.environ.get(
            "MM_SOLANA_EVIDENCE_BROKER_DB",
            DEFAULT_BROKER_DB,
        ))
        if value != ":memory:":
            Path(value).parent.mkdir(parents=True, exist_ok=True)
        self.path = value
        self.clock = clock
        self.sleep = sleeper
        self.lock = threading.RLock()
        self.db = sqlite3.connect(value, timeout=30, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self):
        with self.lock, self.db:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS stream_state(
                    stream TEXT PRIMARY KEY,
                    connected INTEGER NOT NULL DEFAULT 0,
                    warm_since INTEGER,
                    loss_until INTEGER NOT NULL DEFAULT 0,
                    last_slot INTEGER,
                    gaps INTEGER NOT NULL DEFAULT 0,
                    events INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS stream_events(
                    stream TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    signature TEXT,
                    address TEXT,
                    slot INTEGER NOT NULL,
                    observed_at INTEGER NOT NULL,
                    payload TEXT,
                    PRIMARY KEY(stream,event_key)
                );
                CREATE INDEX IF NOT EXISTS stream_events_lookup
                    ON stream_events(stream,address,slot,observed_at);
                CREATE TABLE IF NOT EXISTS tx_cache(
                    signature TEXT PRIMARY KEY,
                    slot INTEGER,
                    block_time INTEGER,
                    payload TEXT NOT NULL,
                    cached_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cursors(
                    name TEXT PRIMARY KEY,
                    slot INTEGER NOT NULL,
                    signature TEXT,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs(
                    job_key TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    deadline REAL NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    lease_until REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_ready
                    ON jobs(status,priority,deadline,created_at);
                CREATE TABLE IF NOT EXISTS pressure(
                    name TEXT PRIMARY KEY,
                    batch_size INTEGER NOT NULL,
                    cooldown_until REAL NOT NULL,
                    rate_events INTEGER NOT NULL,
                    success_streak INTEGER NOT NULL,
                    reductions INTEGER NOT NULL,
                    recoveries INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signatures(
                    scope TEXT NOT NULL,
                    address TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    slot INTEGER NOT NULL,
                    block_time INTEGER,
                    err INTEGER NOT NULL,
                    confirmation_status TEXT,
                    transaction_index INTEGER,
                    payload TEXT NOT NULL,
                    PRIMARY KEY(scope,address,signature)
                );
                CREATE INDEX IF NOT EXISTS signatures_range
                    ON signatures(scope,address,slot);
                CREATE TABLE IF NOT EXISTS signature_coverage(
                    scope TEXT NOT NULL,
                    address TEXT NOT NULL,
                    newest_signature TEXT,
                    newest_slot INTEGER,
                    oldest_slot INTEGER,
                    covered_through_slot INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(scope,address)
                );
                """
            )
            columns={
                row[1] for row in self.db.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "lease_until" not in columns:
                self.db.execute("ALTER TABLE jobs ADD COLUMN lease_until REAL")
            self.db.execute(
                """INSERT OR IGNORE INTO pressure
                   (name,batch_size,cooldown_until,rate_events,success_streak,reductions,recoveries)
                   VALUES('transaction_hydration',8,0,0,0,0,0)"""
            )

    def close(self):
        with self.lock:
            self.db.close()

    def stream_begin(self, stream, now=None):
        now = int(self.clock() if now is None else now)
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT loss_until,gaps,events FROM stream_state WHERE stream=?",
                (str(stream),),
            ).fetchone()
            loss_until, gaps, events = row if row else (0, 0, 0)
            self.db.execute(
                """INSERT OR REPLACE INTO stream_state
                   (stream,connected,warm_since,loss_until,last_slot,gaps,events)
                   VALUES(?,?,?,?,NULL,?,?)""",
                (str(stream), 1, now, int(loss_until or 0), int(gaps or 0), int(events or 0)),
            )

    def stream_gap(self, stream, now=None, coverage_seconds=30):
        now = int(self.clock() if now is None else now)
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT gaps,events,loss_until FROM stream_state WHERE stream=?",
                (str(stream),),
            ).fetchone()
            gaps, events, loss_until = row if row else (0, 0, 0)
            self.db.execute(
                """INSERT OR REPLACE INTO stream_state
                   (stream,connected,warm_since,loss_until,last_slot,gaps,events)
                   VALUES(?,0,NULL,?,NULL,?,?)""",
                (
                    str(stream),
                    max(int(loss_until or 0), now + int(coverage_seconds)),
                    int(gaps or 0) + 1,
                    int(events or 0),
                ),
            )

    def stream_stop(self, stream):
        with self.lock, self.db:
            self.db.execute(
                "UPDATE stream_state SET connected=0 WHERE stream=?",
                (str(stream),),
            )

    def record_event(
        self, stream, *, slot, observed_at=None, signature=None, address=None, payload=None
    ):
        slot = int(slot)
        observed_at = int(self.clock() if observed_at is None else observed_at)
        signature = None if signature is None else str(signature)
        address = None if address is None else str(address)
        event_key = signature or f"{slot}:{address or ''}"
        body = None if payload is None else json.dumps(payload, sort_keys=True)
        with self.lock, self.db:
            cur = self.db.execute(
                """INSERT OR IGNORE INTO stream_events
                   (stream,event_key,signature,address,slot,observed_at,payload)
                   VALUES(?,?,?,?,?,?,?)""",
                (str(stream), event_key, signature, address, slot, observed_at, body),
            )
            accepted = int(cur.rowcount or 0)
            self.db.execute(
                """INSERT INTO stream_state(stream,connected,warm_since,loss_until,last_slot,gaps,events)
                   VALUES(?,1,?,0,?,0,?)
                   ON CONFLICT(stream) DO UPDATE SET
                     connected=1,
                     last_slot=MAX(COALESCE(last_slot,0),excluded.last_slot),
                     events=events+excluded.events""",
                (str(stream), observed_at, slot, accepted),
            )
        return bool(accepted)

    def recent_events(self, stream, *, since=None, after_slot=None, address=None):
        clauses = ["stream=?"]
        params = [str(stream)]
        if since is not None:
            clauses.append("observed_at>=?")
            params.append(int(since))
        if after_slot is not None:
            clauses.append("slot>?")
            params.append(int(after_slot))
        if address is not None:
            clauses.append("address=?")
            params.append(str(address))
        query = (
            "SELECT signature,address,slot,observed_at,payload FROM stream_events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY slot,event_key"
        )
        with self.lock:
            rows = self.db.execute(query, tuple(params)).fetchall()
        out = []
        for signature, addr, slot, observed_at, payload in rows:
            item = dict(
                signature=signature,
                address=addr,
                slot=int(slot),
                observed_at=int(observed_at),
            )
            if payload:
                item["payload"] = json.loads(payload)
            out.append(item)
        return out

    def stream_status(self, stream, now=None, coverage_seconds=30):
        now = int(self.clock() if now is None else now)
        with self.lock:
            row = self.db.execute(
                """SELECT connected,warm_since,loss_until,last_slot,gaps,events
                   FROM stream_state WHERE stream=?""",
                (str(stream),),
            ).fetchone()
        if not row:
            return dict(
                connected=False, covered=False, warm_seconds=0, loss_until=0,
                last_slot=None, gaps=0, events=0,
            )
        connected, warm_since, loss_until, last_slot, gaps, events = row
        covered = bool(
            connected
            and warm_since is not None
            and now - int(warm_since) >= int(coverage_seconds)
            and now >= int(loss_until or 0)
        )
        return dict(
            connected=bool(connected),
            covered=covered,
            warm_seconds=(0 if warm_since is None else max(0, now - int(warm_since))),
            loss_until=int(loss_until or 0),
            last_slot=(None if last_slot is None else int(last_slot)),
            gaps=int(gaps or 0),
            events=int(events or 0),
        )

    def get_transaction(self, signature):
        with self.lock:
            row = self.db.execute(
                "SELECT payload FROM tx_cache WHERE signature=?",
                (str(signature),),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def put_transaction(self, signature, tx):
        if not isinstance(tx, dict):
            raise ValueError("invalid_transaction_cache_value")
        body = json.dumps(tx, separators=(",", ":"), sort_keys=True)
        slot = tx.get("slot")
        block_time = tx.get("blockTime")
        with self.lock, self.db:
            self.db.execute(
                """INSERT OR REPLACE INTO tx_cache
                   (signature,slot,block_time,payload,cached_at)
                   VALUES(?,?,?,?,?)""",
                (
                    str(signature),
                    None if type(slot) is not int else int(slot),
                    None if type(block_time) is not int else int(block_time),
                    body,
                    int(self.clock()),
                ),
            )
            count = self.db.execute("SELECT COUNT(*) FROM tx_cache").fetchone()[0]
            if count > 20000:
                self.db.execute(
                    """DELETE FROM tx_cache WHERE signature IN (
                       SELECT signature FROM tx_cache ORDER BY cached_at ASC LIMIT ?
                    )""",
                    (count - 18000,),
                )

    def _pressure(self):
        with self.lock:
            row = self.db.execute(
                """SELECT batch_size,cooldown_until,rate_events,success_streak,reductions,recoveries
                   FROM pressure WHERE name='transaction_hydration'"""
            ).fetchone()
        return dict(
            batch_size=int(row[0]),
            cooldown_until=float(row[1]),
            rate_events=int(row[2]),
            success_streak=int(row[3]),
            reductions=int(row[4]),
            recoveries=int(row[5]),
        )

    def _note_pressure_failure(self):
        p = self._pressure()
        old = p["batch_size"]
        new = max(1, old // 2)
        events = p["rate_events"] + 1
        delay = min(16.0, 2.0 * (2 ** min(events - 1, 3)))
        with self.lock, self.db:
            self.db.execute(
                """UPDATE pressure SET batch_size=?,cooldown_until=?,rate_events=?,
                   success_streak=0,reductions=reductions+? WHERE name='transaction_hydration'""",
                (
                    new,
                    max(float(p["cooldown_until"]), float(self.clock()) + delay),
                    events,
                    1 if new < old else 0,
                ),
            )

    def _note_pressure_success(self):
        p = self._pressure()
        streak = p["success_streak"] + 1
        batch = p["batch_size"]
        recover = 0
        if streak >= 8 and batch < 16:
            batch = min(16, batch + 1)
            streak = 0
            recover = 1
        with self.lock, self.db:
            self.db.execute(
                """UPDATE pressure SET batch_size=?,success_streak=?,
                   recoveries=recoveries+? WHERE name='transaction_hydration'""",
                (batch, streak, recover),
            )

    def queue_transaction(self, signature, *, kind, deadline, max_version=1):
        now = float(self.clock())
        payload = json.dumps(
            dict(signature=str(signature), max_supported_transaction_version=int(max_version)),
            sort_keys=True,
        )
        with self.lock, self.db:
            self.db.execute(
                """INSERT INTO jobs(
                       job_key,kind,priority,deadline,payload,status,lease_until,
                       created_at,updated_at)
                   VALUES(?,?,?,?,?,'pending',NULL,?,?)
                   ON CONFLICT(job_key) DO UPDATE SET
                     priority=MIN(priority,excluded.priority),
                     deadline=MIN(deadline,excluded.deadline),
                     status=CASE
                       WHEN jobs.status='complete' THEN 'complete'
                       WHEN jobs.status='inflight'
                         AND COALESCE(jobs.lease_until,0)>excluded.created_at
                         THEN 'inflight'
                       ELSE 'pending'
                     END,
                     lease_until=CASE
                       WHEN jobs.status='complete' THEN jobs.lease_until
                       WHEN jobs.status='inflight'
                         AND COALESCE(jobs.lease_until,0)>excluded.created_at
                         THEN jobs.lease_until
                       ELSE NULL
                     END,
                     updated_at=excluded.updated_at""",
                (
                    f"tx:{signature}",
                    str(kind),
                    _priority(kind),
                    float(deadline),
                    payload,
                    now,
                    now,
                ),
            )

    def _claim_jobs(self, limit, now=None, lease_seconds=15.0):
        """Atomically claim global hydration jobs across broker processes."""
        limit=max(1,int(limit))
        now=float(self.clock() if now is None else now)
        lease_until=now+max(1.0,float(lease_seconds))
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute(
                    """UPDATE jobs SET status='expired',lease_until=NULL,updated_at=?
                       WHERE status IN ('pending','inflight') AND deadline<?""",
                    (now,now),
                )
                self.db.execute(
                    """UPDATE jobs SET status='pending',lease_until=NULL,updated_at=?
                       WHERE status='inflight'
                         AND COALESCE(lease_until,0)<=?
                         AND deadline>=?""",
                    (now,now,now),
                )
                rows=self.db.execute(
                    """SELECT job_key,payload FROM jobs
                       WHERE status='pending' AND deadline>=?
                       ORDER BY priority ASC,deadline ASC,created_at ASC LIMIT ?""",
                    (now,limit),
                ).fetchall()
                if rows:
                    self.db.executemany(
                        """UPDATE jobs SET status='inflight',lease_until=?,updated_at=?
                           WHERE job_key=? AND status='pending'""",
                        [(lease_until,now,row[0]) for row in rows],
                    )
                    keys=[row[0] for row in rows]
                    placeholders=",".join("?" for _ in keys)
                    claimed={
                        row[0] for row in self.db.execute(
                            f"""SELECT job_key FROM jobs
                                WHERE status='inflight'
                                  AND job_key IN ({placeholders})""",
                            tuple(keys),
                        ).fetchall()
                    }
                    rows=[row for row in rows if row[0] in claimed]
                self.db.commit()
                return rows
            except Exception:
                self.db.rollback()
                raise

    def _release_jobs(self, keys):
        keys=[str(key) for key in keys]
        if not keys:
            return
        now=float(self.clock())
        with self.lock,self.db:
            self.db.executemany(
                """UPDATE jobs SET status='pending',lease_until=NULL,updated_at=?
                   WHERE job_key=? AND status='inflight'""",
                [(now,key) for key in keys],
            )

    def _complete_jobs(self, keys):
        keys=[str(key) for key in keys]
        if not keys:
            return
        now=float(self.clock())
        with self.lock,self.db:
            self.db.executemany(
                """UPDATE jobs SET status='complete',lease_until=NULL,updated_at=?
                   WHERE job_key=?""",
                [(now,key) for key in keys],
            )

    def hydrate_transactions(
        self, rpc, signatures, *, kind, deadline=None, max_version=1, batch_size=8
    ):
        deadline = float(self.clock()) + 30.0 if deadline is None else float(deadline)
        requested = []
        seen = set()
        for sig in signatures:
            sig = str(sig)
            if sig and sig not in seen:
                seen.add(sig)
                requested.append(sig)
                if self.get_transaction(sig) is None:
                    self.queue_transaction(
                        sig, kind=kind, deadline=deadline, max_version=max_version
                    )

        while float(self.clock()) < deadline:
            remaining = [sig for sig in requested if self.get_transaction(sig) is None]
            if not remaining:
                break
            p = self._pressure()
            wait = max(0.0, p["cooldown_until"] - float(self.clock()))
            if wait:
                if float(self.clock()) + wait >= deadline:
                    break
                self.sleep(wait)
            jobs=self._claim_jobs(
                max(1,min(int(batch_size),p["batch_size"])),
                float(self.clock()),
            )
            if not jobs:
                break
            payloads = [json.loads(row[1]) for row in jobs]
            params = [[
                row["signature"],
                dict(
                    encoding="json",
                    commitment="finalized",
                    maxSupportedTransactionVersion=int(
                        row["max_supported_transaction_version"]
                    ),
                ),
            ] for row in payloads]
            try:
                values = rpc.call_many(
                    "getTransaction",
                    params,
                    True,
                    batch_size=max(1, min(len(params), p["batch_size"], int(batch_size))),
                )
            except Unavailable:
                self._release_jobs([row[0] for row in jobs])
                self._note_pressure_failure()
                break
            completed = []
            for job, row, tx in zip(jobs, payloads, values):
                if isinstance(tx, dict):
                    self.put_transaction(row["signature"], tx)
                    completed.append(job[0])
            if completed:
                self._complete_jobs(completed)
                self._note_pressure_success()
            completed_set=set(completed)
            incomplete=[row[0] for row in jobs if row[0] not in completed_set]
            if incomplete:
                self._release_jobs(incomplete)
            if not completed:
                break

        result = {sig: self.get_transaction(sig) for sig in requested}
        pending = [sig for sig, tx in result.items() if tx is None]
        return result, dict(
            requested=len(requested),
            hydrated=len(requested) - len(pending),
            pending=len(pending),
            pressure=self._pressure(),
        )

    def cursor(self, name):
        with self.lock:
            row = self.db.execute(
                "SELECT slot,signature FROM cursors WHERE name=?",
                (str(name),),
            ).fetchone()
        if row is None:
            return dict(slot=0, signature=None)
        return dict(slot=int(row[0]), signature=row[1])

    def advance_cursor(self, name, slot, signature=None):
        slot = int(slot)
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT slot FROM cursors WHERE name=?",
                (str(name),),
            ).fetchone()
            if row is not None and slot < int(row[0]):
                raise ValueError("evidence_cursor_regression")
            self.db.execute(
                """INSERT OR REPLACE INTO cursors(name,slot,signature,updated_at)
                   VALUES(?,?,?,?)""",
                (str(name), slot, None if signature is None else str(signature), int(self.clock())),
            )

    def remember_signatures(self, scope, address, rows, *, covered_through_slot=None):
        scope = str(scope)
        address = str(address)
        newest_signature = None
        newest_slot = None
        oldest_slot = None
        normalized = []
        for row in rows or []:
            if not isinstance(row, dict) or not isinstance(row.get("signature"), str):
                raise Unavailable("invalid_signature_row")
            slot = row.get("slot")
            if type(slot) is not int:
                raise Unavailable("invalid_signature_row")
            normalized.append((row, int(slot)))
            if newest_slot is None or int(slot) > newest_slot:
                newest_slot = int(slot)
                newest_signature = str(row["signature"])
            oldest_slot = int(slot) if oldest_slot is None else min(oldest_slot, int(slot))
        with self.lock, self.db:
            for row, slot in normalized:
                self.db.execute(
                    """INSERT OR REPLACE INTO signatures
                       (scope,address,signature,slot,block_time,err,confirmation_status,
                        transaction_index,payload)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        scope,
                        address,
                        str(row["signature"]),
                        slot,
                        (None if row.get("blockTime") is None else int(row["blockTime"])),
                        1 if row.get("err") else 0,
                        row.get("confirmationStatus"),
                        (
                            None
                            if type(row.get("transactionIndex")) is not int
                            else int(row["transactionIndex"])
                        ),
                        json.dumps(row, sort_keys=True),
                    ),
                )
            prior = self.db.execute(
                """SELECT newest_signature,newest_slot,oldest_slot,covered_through_slot
                   FROM signature_coverage WHERE scope=? AND address=?""",
                (scope, address),
            ).fetchone()
            if prior:
                if newest_slot is None or (prior[1] is not None and int(prior[1]) > newest_slot):
                    newest_signature, newest_slot = prior[0], prior[1]
                if oldest_slot is None:
                    oldest_slot = prior[2]
                elif prior[2] is not None:
                    oldest_slot = min(oldest_slot, int(prior[2]))
                covered = max(
                    int(prior[3] or 0),
                    int(covered_through_slot or 0),
                )
            else:
                covered = int(covered_through_slot or 0)
            self.db.execute(
                """INSERT OR REPLACE INTO signature_coverage
                   (scope,address,newest_signature,newest_slot,oldest_slot,covered_through_slot)
                   VALUES(?,?,?,?,?,?)""",
                (scope, address, newest_signature, newest_slot, oldest_slot, covered),
            )

    def signature_rows(self, scope, address, *, start_slot=None, end_slot=None):
        clauses = ["scope=?", "address=?"]
        params = [str(scope), str(address)]
        if start_slot is not None:
            clauses.append("slot>=?")
            params.append(int(start_slot))
        if end_slot is not None:
            clauses.append("slot<=?")
            params.append(int(end_slot))
        with self.lock:
            rows = self.db.execute(
                "SELECT payload FROM signatures WHERE "
                + " AND ".join(clauses)
                + " ORDER BY slot DESC,signature DESC",
                tuple(params),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def signature_coverage(self, scope, address):
        with self.lock:
            row = self.db.execute(
                """SELECT newest_signature,newest_slot,oldest_slot,covered_through_slot
                   FROM signature_coverage WHERE scope=? AND address=?""",
                (str(scope), str(address)),
            ).fetchone()
        if row is None:
            return dict(
                newest_signature=None, newest_slot=None, oldest_slot=None,
                covered_through_slot=0,
            )
        return dict(
            newest_signature=row[0],
            newest_slot=(None if row[1] is None else int(row[1])),
            oldest_slot=(None if row[2] is None else int(row[2])),
            covered_through_slot=int(row[3] or 0),
        )

    def telemetry(self):
        with self.lock:
            tx_count = self.db.execute("SELECT COUNT(*) FROM tx_cache").fetchone()[0]
            pending = self.db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='pending'"
            ).fetchone()[0]
            inflight = self.db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='inflight'"
            ).fetchone()[0]
            expired = self.db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='expired'"
            ).fetchone()[0]
            events = self.db.execute("SELECT COUNT(*) FROM stream_events").fetchone()[0]
            signatures = self.db.execute("SELECT COUNT(*) FROM signatures").fetchone()[0]
        return dict(
            transaction_cache_entries=int(tx_count),
            pending_jobs=int(pending),
            inflight_jobs=int(inflight),
            expired_jobs=int(expired),
            stream_events=int(events),
            signature_rows=int(signatures),
            pressure=self._pressure(),
        )


class _BaseStream:
    def __init__(self, ws_url, broker, stream_key, *, coverage_seconds=30, clock=time.time):
        self.ws_url = str(ws_url)
        self.broker = broker
        self.stream_key = str(stream_key)
        self.coverage_seconds = int(coverage_seconds)
        self.clock = clock
        self.connections = 0
        self.reconnects = 0
        self.last_error_kind = None

    def _subscribe(self, websocket):
        raise NotImplementedError

    def _ingest(self, payload):
        raise NotImplementedError

    def run(self, stop_event, ready_event=None):
        ever_ready = False
        while not stop_event.is_set():
            try:
                with connect(
                    self.ws_url,
                    open_timeout=10,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2_000_000,
                    max_queue=256,
                ) as websocket:
                    self._subscribe(websocket)
                    if ever_ready:
                        self.reconnects += 1
                    ever_ready = True
                    self.connections += 1
                    self.broker.stream_begin(self.stream_key, int(self.clock()))
                    if ready_event is not None and not ready_event.is_set():
                        ready_event.set()
                    while not stop_event.is_set():
                        try:
                            message = websocket.recv(timeout=1)
                        except TimeoutError:
                            continue
                        self._ingest(json.loads(message))
            except Exception as exc:
                if stop_event.is_set():
                    break
                self.last_error_kind = type(exc).__name__
                self.broker.stream_gap(
                    self.stream_key,
                    int(self.clock()),
                    self.coverage_seconds,
                )
                stop_event.wait(1.0)
        self.broker.stream_stop(self.stream_key)


class ProgramLogSignatureStream(_BaseStream):
    """Finalized program log signatures; transaction bodies remain HTTP-authenticated."""

    def __init__(self, ws_url, broker, stream_key, program, **kwargs):
        super().__init__(ws_url, broker, stream_key, **kwargs)
        self.program = str(program)

    def _subscribe(self, websocket):
        websocket.send(json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [
                {"mentions": [self.program]},
                {"commitment": "finalized"},
            ],
        }))
        ack = json.loads(websocket.recv(timeout=10))
        if ack.get("error") or not isinstance(ack.get("result"), int):
            raise RuntimeError("program_log_subscription_rejected")

    def _ingest(self, payload):
        if payload.get("method") != "logsNotification":
            return
        result = payload["params"]["result"]
        value = result["value"]
        if value.get("err"):
            return
        self.broker.record_event(
            self.stream_key,
            signature=value["signature"],
            slot=int(result["context"]["slot"]),
            observed_at=int(self.clock()),
        )


class ProgramAccountWakeStream(_BaseStream):
    """Finalized program-account change wakeups keyed by account pubkey."""

    def __init__(self, ws_url, broker, stream_key, program, *, data_size=None, **kwargs):
        super().__init__(ws_url, broker, stream_key, **kwargs)
        self.program = str(program)
        self.data_size = None if data_size is None else int(data_size)

    def _subscribe(self, websocket):
        config = {"commitment": "finalized", "encoding": "base64"}
        if self.data_size is not None:
            config["filters"] = [{"dataSize": self.data_size}]
        websocket.send(json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "programSubscribe",
            "params": [self.program, config],
        }))
        ack = json.loads(websocket.recv(timeout=10))
        if ack.get("error") or not isinstance(ack.get("result"), int):
            raise RuntimeError("program_account_subscription_rejected")

    def _ingest(self, payload):
        if payload.get("method") != "programNotification":
            return
        result = payload["params"]["result"]
        value = result["value"]
        address = value.get("pubkey")
        if not isinstance(address, str) or not address:
            raise ValueError("program_account_pubkey_missing")
        self.broker.record_event(
            self.stream_key,
            address=address,
            slot=int(result["context"]["slot"]),
            observed_at=int(self.clock()),
        )


class DynamicAddressLogStream:
    """One finalized WebSocket connection with dynamic per-address log subscriptions.

    Solana logsSubscribe accepts one mentions pubkey per subscription. This class
    multiplexes many candidate pool subscriptions over one connection so a PumpSwap
    candidate wakes only on transactions that actually mention that pool.
    """

    def __init__(
        self, ws_url, broker, stream_prefix, *, coverage_seconds=30, clock=time.time
    ):
        self.ws_url=str(ws_url)
        self.broker=broker
        self.stream_prefix=str(stream_prefix)
        self.coverage_seconds=int(coverage_seconds)
        self.clock=clock
        self.lock=threading.RLock()
        self.addresses=set()
        self.connections=0
        self.reconnects=0
        self.last_error_kind=None
        self.active_subscriptions=0

    def stream_key(self,address):
        return self.stream_prefix+":"+str(address)

    def add_address(self,address):
        address=str(address or "").strip()
        if not address:
            raise ValueError("dynamic_log_address_required")
        with self.lock:
            self.addresses.add(address)
        return self.stream_key(address)

    def wanted_addresses(self):
        with self.lock:
            return sorted(self.addresses)

    def status(self):
        return dict(
            connections=int(self.connections),
            reconnects=int(self.reconnects),
            wanted_addresses=len(self.wanted_addresses()),
            active_subscriptions=int(self.active_subscriptions),
            last_error_kind=self.last_error_kind,
        )

    def run(self,stop_event,ready_event=None):
        ever_ready=False
        while not stop_event.is_set():
            active_addresses=[]
            try:
                with connect(
                    self.ws_url,open_timeout=10,ping_interval=20,ping_timeout=20,
                    close_timeout=5,max_size=2_000_000,max_queue=256,
                ) as websocket:
                    pending={}
                    by_address={}
                    by_subscription={}
                    next_id=1
                    if ever_ready:
                        self.reconnects+=1
                    ever_ready=True
                    self.connections+=1
                    self.last_error_kind=None
                    if ready_event is not None and not ready_event.is_set():
                        ready_event.set()

                    while not stop_event.is_set():
                        wanted=self.wanted_addresses()
                        known=set(by_address)|set(pending.values())
                        for address in [a for a in wanted if a not in known][:16]:
                            request_id=next_id;next_id+=1
                            websocket.send(json.dumps({
                                "jsonrpc":"2.0","id":request_id,
                                "method":"logsSubscribe",
                                "params":[
                                    {"mentions":[address]},
                                    {"commitment":"finalized"},
                                ],
                            }))
                            pending[request_id]=address

                        try:
                            message=websocket.recv(timeout=0.25)
                        except TimeoutError:
                            continue
                        payload=json.loads(message)
                        if "id" in payload:
                            request_id=payload.get("id")
                            address=pending.pop(request_id,None)
                            if address is None:
                                continue
                            if payload.get("error") or not isinstance(payload.get("result"),int):
                                raise RuntimeError("address_log_subscription_rejected")
                            subscription=int(payload["result"])
                            by_address[address]=subscription
                            by_subscription[subscription]=address
                            active_addresses=list(by_address)
                            self.active_subscriptions=len(by_address)
                            self.broker.stream_begin(
                                self.stream_key(address),int(self.clock()))
                            continue
                        if payload.get("method")!="logsNotification":
                            continue
                        params=payload.get("params") or {}
                        address=by_subscription.get(params.get("subscription"))
                        if address is None:
                            raise RuntimeError("address_log_unknown_subscription")
                        result=params["result"];value=result["value"]
                        if value.get("err"):
                            continue
                        self.broker.record_event(
                            self.stream_key(address),
                            signature=value["signature"],
                            address=address,
                            slot=int(result["context"]["slot"]),
                            observed_at=int(self.clock()),
                        )
            except Exception as exc:
                if stop_event.is_set():
                    break
                self.last_error_kind=type(exc).__name__
                affected=set(active_addresses)|set(self.wanted_addresses())
                for address in affected:
                    self.broker.stream_gap(
                        self.stream_key(address),int(self.clock()),
                        self.coverage_seconds)
                self.active_subscriptions=0
                stop_event.wait(1.0)
        for address in self.wanted_addresses():
            self.broker.stream_stop(self.stream_key(address))
        self.active_subscriptions=0
