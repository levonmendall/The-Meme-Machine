"""Consumer ownership for immutable evidence; never strategy or freshness authority."""
from __future__ import annotations

import threading


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
                CREATE TABLE IF NOT EXISTS hydration_failures(
                    reason TEXT PRIMARY KEY, count INTEGER NOT NULL);
                CREATE TRIGGER IF NOT EXISTS evidence_terminals_no_update
                    BEFORE UPDATE ON evidence_terminals BEGIN
                    SELECT RAISE(ABORT,'append_only_evidence_terminals'); END;
                CREATE TRIGGER IF NOT EXISTS evidence_terminals_no_delete
                    BEFORE DELETE ON evidence_terminals BEGIN
                    SELECT RAISE(ABORT,'append_only_evidence_terminals'); END;
            ''')

    def register(self, owner, signatures, kind, deadline):
        b = self.broker
        now = float(b.clock())
        with b.lock, b.db:
            # A repeated request cannot rejuvenate this consumer's original deadline.
            b.db.executemany('INSERT OR IGNORE INTO evidence_consumers '
                            '(owner,signature,kind,deadline,created_at) VALUES(?,?,?,?,?)',
                            [(str(owner), str(s), str(kind), float(deadline), now)
                             for s in dict.fromkeys(signatures)])

    def settle(self, owner=None, reason=None):
        b = self.broker
        now = float(b.clock())
        with b.lock, b.db:
            # Cache completion takes precedence only if it was acquired before the
            # consumer deadline. A late immutable transaction can serve a later consumer.
            b.db.execute('''INSERT OR IGNORE INTO evidence_terminals
                (owner,signature,kind,deadline,observed_at,reason)
                SELECT owner,signature,kind,deadline,?, 'evidence_complete'
                FROM evidence_consumers c WHERE state='waiting' AND EXISTS
                    (SELECT 1 FROM tx_cache t WHERE t.signature=c.signature
                     AND t.cached_at<=c.deadline)''', (now,))
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

    def batch(self, limit=8):
        self.settle()
        b = self.broker
        with b.lock:
            # Only already subscribed pool streams may use background acquisition.
            # Other consumers retain their lane's synchronous authentication path.
            rows = b.db.execute('''SELECT c.signature, MIN(c.deadline)
                FROM evidence_consumers c WHERE c.state='waiting'
                  AND c.kind='stream_prefetch' AND c.deadline>?
                  AND NOT EXISTS(SELECT 1 FROM tx_cache t WHERE t.signature=c.signature)
                GROUP BY c.signature ORDER BY MIN(c.deadline),c.signature LIMIT ?''',
                (float(b.clock()), max(1, min(8, int(limit))))).fetchall()
        return rows

    def failure(self, reason):
        b = self.broker
        with b.lock, b.db:
            b.db.execute('INSERT INTO hydration_failures VALUES(?,1) '
                         'ON CONFLICT(reason) DO UPDATE SET count=count+1', (reason,))

    def telemetry(self):
        self.settle()
        b = self.broker
        with b.lock:
            rows = b.db.execute('SELECT kind,state,COUNT(*) FROM evidence_consumers '
                                'GROUP BY kind,state').fetchall()
            failures = dict(b.db.execute('SELECT reason,count FROM hydration_failures'))
            overdue = b.db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('pending','inflight') "
                                   'AND deadline<?', (float(b.clock()),)).fetchone()[0]
        return dict(scope='shared_solana_broker; not additive across lanes',
                    consumers=[dict(kind=k, state=s, count=n) for k,s,n in rows],
                    by_kind={k:{s:n for kind,s,n in rows if kind==k}
                             for k in sorted({kind for kind,_,_ in rows})},
                    acquisition_failures=failures, overdue_active_jobs=overdue)


class StreamEvidenceService:
    """One incremental reader; provider pacing and foreground priority still apply."""
    def __init__(self, broker, rpc_factory):
        self.broker, self.rpc_factory = broker, rpc_factory
        self.stop = threading.Event()
        self.thread = None
        self.error = None
        self.rpc = None
        self.sessions = []

    def step(self):
        rows = self.broker.consumers.batch()
        if not rows:
            return False
        if self.rpc is None or self.rpc.calls + len(rows) + 8 > self.rpc.limit:
            if self.rpc is not None:
                self.sessions.append(self.rpc.provider_telemetry())
            self.rpc = self.rpc_factory()
            self.rpc.evidence_priority = 90
        self.broker.hydrate_transactions(
            self.rpc, [s for s,_ in rows], kind='stream_prefetch',
            deadline=min(float(self.broker.clock()) + 4, min(d for _,d in rows)),
            batch_size=8, max_batches=1, owner=False)
        self.broker.consumers.settle()
        return True

    def start(self):
        def run():
            try:
                while not self.stop.is_set():
                    self.step()
                    self.stop.wait(.5)
            except Exception as exc:
                # An unexpected worker failure is visible and stops certification.
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
