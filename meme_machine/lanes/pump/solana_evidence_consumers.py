"""Consumer ownership for immutable evidence; never strategy or freshness authority."""
from __future__ import annotations

import os
import json
import sqlite3
import threading
from .solana_signature_identity import DEFAULT_SIGNATURE
import time


class EvidenceConsumers:
    def __init__(self, broker):
        self.broker = broker
        with broker.lock, broker.db:
            broker.db.executescript('''
                CREATE TABLE IF NOT EXISTS evidence_consumers(
                    owner TEXT NOT NULL, signature TEXT NOT NULL, kind TEXT NOT NULL,
                    deadline REAL NOT NULL, created_at REAL NOT NULL,
                    state TEXT NOT NULL DEFAULT 'waiting',
                    PRIMARY KEY(owner,signature));
                CREATE INDEX IF NOT EXISTS consumers_ready
                    ON evidence_consumers(state,kind,deadline);
                CREATE TABLE IF NOT EXISTS evidence_terminals(
                    id INTEGER PRIMARY KEY, owner TEXT NOT NULL, signature TEXT NOT NULL,
                    kind TEXT NOT NULL, deadline REAL NOT NULL, observed_at REAL NOT NULL,
                    reason TEXT NOT NULL, UNIQUE(owner,signature));
                CREATE TABLE IF NOT EXISTS acquisition_phases(
                    seq INTEGER PRIMARY KEY,lane TEXT NOT NULL,owner TEXT,kind TEXT,
                    phase TEXT NOT NULL,at REAL NOT NULL,deadline REAL,signatures TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS acquisition_phases_no_update BEFORE UPDATE ON acquisition_phases
                    BEGIN SELECT RAISE(ABORT,'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS acquisition_phases_no_delete BEFORE DELETE ON acquisition_phases
                    BEGIN SELECT RAISE(ABORT,'append_only'); END;
                CREATE TABLE IF NOT EXISTS hydration_attempt_failures(
                    seq INTEGER PRIMARY KEY,lane TEXT NOT NULL,owner TEXT,candidate_id TEXT,
                    kind TEXT,at REAL NOT NULL,reason TEXT NOT NULL,signatures TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS hydration_attempt_no_update BEFORE UPDATE ON hydration_attempt_failures
                    BEGIN SELECT RAISE(ABORT,'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS hydration_attempt_no_delete BEFORE DELETE ON hydration_attempt_failures
                    BEGIN SELECT RAISE(ABORT,'append_only'); END;
                CREATE TABLE IF NOT EXISTS attributed_hydration_failures(
                    lane TEXT NOT NULL,reason TEXT NOT NULL,count INTEGER NOT NULL,PRIMARY KEY(lane,reason));
                CREATE TABLE IF NOT EXISTS hydration_failures(
                    reason TEXT PRIMARY KEY, count INTEGER NOT NULL);
                CREATE TRIGGER IF NOT EXISTS evidence_terminals_no_update
                    BEFORE UPDATE ON evidence_terminals BEGIN
                    SELECT RAISE(ABORT,'append_only_evidence_terminals'); END;
                CREATE TRIGGER IF NOT EXISTS evidence_terminals_no_delete
                    BEFORE DELETE ON evidence_terminals BEGIN
                    SELECT RAISE(ABORT,'append_only_evidence_terminals'); END;
            ''')

            broker.db.execute('BEGIN IMMEDIATE')
            columns={r[1] for r in broker.db.execute('PRAGMA table_info(evidence_consumers)')}
            for name,decl in (('lane',"TEXT NOT NULL DEFAULT 'unknown'"),
                              ('candidate_id','TEXT'),('first_transport_at','REAL')):
                if name not in columns:broker.db.execute(f'ALTER TABLE evidence_consumers ADD COLUMN {name} {decl}')

    def register(self, owner, signatures, kind, deadline, *, candidate_id=None):
        b = self.broker
        now = float(b.clock())
        with b.lock, b.db:
            # A repeated request cannot rejuvenate this consumer's original deadline.
            b.db.executemany('INSERT OR IGNORE INTO evidence_consumers '
                            '(owner,signature,kind,deadline,created_at,lane,candidate_id) VALUES(?,?,?,?,?,?,?)',
                            [(str(owner), str(s), str(kind), float(deadline), now, os.environ.get('MM_CERTIFICATION_LANE','unknown'), candidate_id)
                             for s in dict.fromkeys(signatures)])
        self.reject_default_signature(str(owner))

    def reject_default_signature(self, owner=None):
        """Invalid identity is terminal acquisition evidence, never provider failure."""
        b=self.broker
        with b.lock,b.db:
            b.db.execute('BEGIN IMMEDIATE')
            rows=b.db.execute("SELECT owner,signature,kind,deadline,lane FROM evidence_consumers c "
                "WHERE signature=? AND state='waiting' AND (? IS NULL OR owner=?) "
                "AND NOT EXISTS(SELECT 1 FROM evidence_terminals t WHERE t.owner=c.owner AND t.signature=c.signature)",
                (DEFAULT_SIGNATURE,owner,owner)).fetchall()
            for consumer,signature,kind,deadline,lane in rows:
                now=float(b.clock())
                b.db.execute('INSERT INTO evidence_terminals(owner,signature,kind,deadline,observed_at,reason) VALUES(?,?,?,?,?,?)',
                    (consumer,signature,kind,deadline,now,'invalid_default_transaction_signature'))
                b.db.execute('INSERT INTO acquisition_phases(lane,owner,kind,phase,at,deadline,signatures) VALUES(?,?,?,?,?,?,?)',
                    (lane,consumer,kind,'invalid_default_transaction_signature',now,deadline,json.dumps([signature])))
                b.db.execute("UPDATE evidence_consumers SET state='invalid_default_transaction_signature' WHERE owner=? AND signature=? AND state='waiting'",
                    (consumer,signature))

    def settle(self, owner=None, reason=None):
        self.reject_default_signature()
        b = self.broker
        now = float(b.clock())
        with b.lock, b.db:
            # Cache completion takes precedence only if it was acquired before the
            # consumer deadline. A late immutable transaction can serve a later consumer.
            b.db.execute('''INSERT OR IGNORE INTO evidence_terminals
                (owner,signature,kind,deadline,observed_at,reason)
                SELECT owner,signature,kind,deadline,?, 'evidence_complete'
                FROM evidence_consumers c WHERE state='waiting' AND EXISTS
                    (SELECT 1 FROM immutable_transactions t WHERE t.signature=c.signature
                     AND t.cached_at<=c.deadline UNION SELECT 1 FROM tx_cache t WHERE t.signature=c.signature AND t.cached_at<=c.deadline)''', (now,))
            if owner is not None:
                b.db.execute('''INSERT OR IGNORE INTO evidence_terminals
                    (owner,signature,kind,deadline,observed_at,reason)
                    SELECT owner,signature,kind,deadline,?,? FROM evidence_consumers
                    WHERE state='waiting' AND owner=?''', (now, str(reason), str(owner)))
            b.db.execute('''INSERT OR IGNORE INTO evidence_terminals
                (owner,signature,kind,deadline,observed_at,reason)
                SELECT owner,signature,kind,deadline,?, 'consumer_deadline_expired'
                FROM evidence_consumers WHERE state='waiting' AND deadline<?''', (now, now))
            b.db.execute('''UPDATE evidence_consumers SET state=(SELECT reason
                FROM evidence_terminals t WHERE t.owner=evidence_consumers.owner
                    AND t.signature=evidence_consumers.signature)
                WHERE state='waiting' AND EXISTS(SELECT 1 FROM evidence_terminals t
                    WHERE t.owner=evidence_consumers.owner
                        AND t.signature=evidence_consumers.signature)''')

    def first_transport(self, signatures):
        b=self.broker
        with b.lock,b.db:
            b.db.executemany("UPDATE evidence_consumers SET first_transport_at=? "
                "WHERE signature=? AND state='waiting' AND first_transport_at IS NULL",
                [(float(b.clock()),str(s)) for s in signatures])

    def foreground_pending(self):
        b=self.broker
        with b.lock:
            return b.db.execute("SELECT 1 FROM evidence_consumers WHERE state='waiting' "
                "AND kind NOT IN ('stream_prefetch','research_history') AND deadline>? LIMIT 1",
                (float(b.clock()),)).fetchone() is not None

    def batch(self, limit=8):
        self.settle()
        b = self.broker
        if self.foreground_pending():return []
        with b.lock:
            # Only already subscribed pool streams may use background acquisition.
            # Other consumers retain their lane's synchronous authentication path.
            rows = b.db.execute('''SELECT c.signature, MIN(c.deadline)
                FROM evidence_consumers c WHERE c.state='waiting'
                  AND c.kind='stream_prefetch' AND c.deadline>?
                  AND NOT EXISTS(SELECT 1 FROM immutable_transactions t WHERE t.signature=c.signature)
                GROUP BY c.signature ORDER BY MIN(c.deadline),c.signature LIMIT ?''',
                (float(b.clock()), max(1, min(8, int(limit))))).fetchall()
        return rows

    def phase(self,phase,*,owner,kind,deadline,signatures):
        b=self.broker
        with b.lock,b.db:
            b.db.execute('INSERT INTO acquisition_phases(lane,owner,kind,phase,at,deadline,signatures) VALUES(?,?,?,?,?,?,?)',
                (os.environ.get('MM_CERTIFICATION_LANE','unknown'),str(owner),kind,phase,
                 float(b.clock()),float(deadline),json.dumps(list(signatures))))

    def failure(self, reason, *, owner=None, candidate_id=None, kind=None, signatures=()):
        b = self.broker
        with b.lock, b.db:
            b.db.execute('INSERT INTO hydration_attempt_failures(lane,owner,candidate_id,kind,at,reason,signatures) VALUES(?,?,?,?,?,?,?)',
                (os.environ.get('MM_CERTIFICATION_LANE','unknown'),str(owner) if owner else None,candidate_id,kind,
                 float(b.clock()),reason,json.dumps(list(signatures))))
            b.db.execute('INSERT INTO attributed_hydration_failures VALUES(?,?,1) '
                         'ON CONFLICT(lane,reason) DO UPDATE SET count=count+1',
                         (os.environ.get('MM_CERTIFICATION_LANE','unknown'),reason))
            b.db.execute('INSERT INTO hydration_failures VALUES(?,1) '
                         'ON CONFLICT(reason) DO UPDATE SET count=count+1', (reason,))

    def telemetry(self, lane=None):
        self.settle()
        lane=lane or os.environ.get('MM_CERTIFICATION_LANE','unknown')
        b = self.broker
        with b.lock:
            rows = b.db.execute('SELECT kind,state,COUNT(*) FROM evidence_consumers '
                                'WHERE lane=? GROUP BY kind,state',(lane,)).fetchall()
            failures = dict(b.db.execute('SELECT reason,count FROM hydration_failures'))
            phases=dict(b.db.execute('SELECT phase,count(*) FROM acquisition_phases WHERE lane=? GROUP BY phase',(lane,)))
            deadline_rows=b.db.execute('''SELECT kind,
                CASE WHEN created_at>=deadline THEN 'already_expired_before_enqueue'
                     WHEN first_transport_at IS NULL THEN 'expired_before_transport'
                     ELSE 'expired_after_transport_started' END,COUNT(*)
                FROM evidence_consumers WHERE lane=? AND state='consumer_deadline_expired'
                GROUP BY 1,2''',(lane,)).fetchall()
            unique_failures=dict(b.db.execute('SELECT reason,COUNT(DISTINCT candidate_id) FROM hydration_attempt_failures WHERE lane=? AND candidate_id IS NOT NULL GROUP BY reason',(lane,)))
            lane_failures=dict(b.db.execute('SELECT reason,count FROM attributed_hydration_failures WHERE lane=?',(lane,)))
            overdue = b.db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('pending','inflight') "
                                   'AND deadline<?', (float(b.clock()),)).fetchone()[0]
            unique=dict(b.db.execute("SELECT state,COUNT(DISTINCT candidate_id) FROM evidence_consumers "
                "WHERE lane=? AND candidate_id IS NOT NULL GROUP BY state",(lane,)))
            candidates=b.db.execute("SELECT COUNT(DISTINCT candidate_id) FROM evidence_consumers "
                "WHERE lane=? AND candidate_id IS NOT NULL",(lane,)).fetchone()[0]
        return dict(scope='lane_attributed_logical_consumers; candidate_states_may_overlap',lane=lane,
                    acquisition_phase_attempts=phases,
                    deadline_decomposition=[dict(kind=k,stage=s,count=n) for k,s,n in deadline_rows],
                    candidate_interests=candidates,unique_candidate_states=unique,
                    unique_candidate_acquisition_failures=unique_failures,
                    opportunity_denominator_source='native_candidate_funnel_not_consumer_count',
                    shared_acquisition_failures=failures,
                    consumers=[dict(kind=k, state=s, count=n) for k,s,n in rows],
                    by_kind={k:{s:n for kind,s,n in rows if kind==k}
                             for k in sorted({kind for kind,_,_ in rows})},
                    acquisition_failures=lane_failures, shared_overdue_active_jobs=overdue)


class StreamEvidenceService:
    """Sparse cache warmer; foreground evidence never depends on prefetch success."""
    def __init__(self, broker, rpc_factory):
        self.broker, self.rpc_factory = broker, rpc_factory
        self.pacer = None
        self.stop = threading.Event()
        self.thread = None
        self.error = None
        self.rpc = None
        self.sessions = []
        self.prefetch_interval_seconds = 0.5
        self.next_prefetch_at = -float('inf')
        self.provider_busy_deferrals = 0
        self.interval_deferrals = 0
        self.prefetch_batches = 0

    def _shared_provider_idle(self):
        path=os.environ.get('MM_CERT_GOVERNOR_DB')
        if not path:
            return True
        if not os.path.exists(path):
            return False
        try:
            db=sqlite3.connect(path,timeout=.1)
            try:
                row=db.execute("SELECT next_at,cooldown FROM pressure WHERE provider='solana'").fetchone()
                queued=db.execute("SELECT COUNT(*) FROM queue WHERE provider='solana'").fetchone()[0]
            finally:
                db.close()
        except sqlite3.Error:
            return False
        return bool(row and not queued and time.monotonic()>=max(float(row[0]),float(row[1])))

    def step(self):
        now=float(self.broker.clock())
        if now<self.next_prefetch_at:
            self.interval_deferrals+=1
            return False
        if not self._shared_provider_idle():
            self.provider_busy_deferrals+=1
            return False
        rows = self.broker.consumers.batch()
        if not rows:
            return False
        self.next_prefetch_at=now+self.prefetch_interval_seconds
        if self.rpc is None or self.rpc.calls + len(rows) + 8 > self.rpc.limit:
            if self.rpc is not None:
                self.sessions.append(self.rpc.provider_telemetry())
            self.rpc = self.rpc_factory()
            if self.pacer is not None:
                self.rpc.read_pacer=self.pacer
                self.rpc.alchemy_pacer=self.pacer
            self.pacer=getattr(self.rpc,'read_pacer',None)
            self.rpc.evidence_priority = 90
        self.broker.hydrate_transactions(
            self.rpc, [s for s,_ in rows], kind='stream_prefetch',
            deadline=min(float(self.broker.clock()) + 8, min(d for _,d in rows)),
            batch_size=8, max_batches=1, owner=False)
        self.broker.consumers.settle()
        self.prefetch_batches+=1
        return True

    def start(self):
        def run():
            try:
                while not self.stop.is_set():
                    self.step()
                    self.stop.wait(.5)
            except Exception as exc:
                # An unexpected worker failure is visible and stops meme_machine.runtime.
                self.error = type(exc).__name__
        self.thread = threading.Thread(target=run, name='solana-stream-evidence', daemon=True)
        self.thread.start()

    def check(self):
        if self.error:
            raise RuntimeError('stream_evidence_service_failed:' + self.error)

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=40)
            if self.thread.is_alive():
                raise RuntimeError('stream_evidence_service_shutdown_timeout')
        self.check()
        if self.rpc is not None:
            self.sessions.append(self.rpc.provider_telemetry())
