"""One committed owner turn's bounded scheduling work, never proof authority.

Only preparation bookkeeping is shared by decisions. Jobs, ordering, original
deadlines, scope and completeness are still read at every final decision.
"""
from contextlib import contextmanager
import threading
import time
import uuid

from .solana_evidence_plane import EvidenceUnavailable


class PlanningQuantum:
    LIMIT = 16

    def __init__(self, history, *, deadline=None):
        if history.db is not history.writer.db:
            raise EvidenceUnavailable('planning_quantum_writer')
        check=getattr(history.writer,'_check',None)
        if check is not None:check()
        self.history = history
        self.writer = history.writer
        self.db = history.db
        self.owner = threading.get_ident()
        self.active = True
        self.decisions = 0
        self.refused_decision = False
        self.deadline = deadline
        self.yield_required = False
        self.seed = None
        self.fanout_done = False
        self.backfill = None
        self.ranks = {}
        self.expiry = {}
        self.expiry_remaining = self.LIMIT
        self.token = uuid.uuid4().hex
        if not self.db.in_transaction:
            raise EvidenceUnavailable('planning_quantum_transaction')
        # The guard is uncommitted: rollback followed by a new BEGIN cannot
        # revive this turn's volatile cursors. close() removes it before COMMIT.
        self.db.execute('CREATE TEMP TABLE IF NOT EXISTS owner_planning_quantum_guard_v1(token TEXT PRIMARY KEY)')
        self.db.execute('INSERT INTO temp.owner_planning_quantum_guard_v1 VALUES(?)', (self.token,))

    def validate(self, history):
        if (not self.active or history is not self.history or history.writer is not self.writer
                or history.db is not self.db or threading.get_ident() != self.owner
                or not self.db.in_transaction):
            raise EvidenceUnavailable('planning_quantum_scope')
        try:
            present = self.db.execute('SELECT 1 FROM temp.owner_planning_quantum_guard_v1 WHERE token=?',
                (self.token,)).fetchone()
        except Exception:
            present = None
        if present != (1,):
            self.active = False
            raise EvidenceUnavailable('planning_quantum_rolled_back')

    def exhausted(self):
        return (self.yield_required or self.decisions >= self.LIMIT or
            self.deadline is not None and time.perf_counter() >= self.deadline)

    @contextmanager
    def decision(self, history, *, defer_exhausted=False):
        self.validate(history)
        if self.exhausted():
            if not defer_exhausted:
                raise EvidenceUnavailable('planning_quantum_exhausted')
            # Public planning is cooperative work: exhaustion is a committed
            # yield, while direct strict callers retain their abuse guard.
            self.refused_decision=True
            self.yield_required=True
            yield False
            return
        self.refused_decision=False
        self.decisions += 1
        try:
            yield True
            self.validate(history)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.active and threading.get_ident() == self.owner and self.db.in_transaction:
            try:
                self.db.execute('DELETE FROM temp.owner_planning_quantum_guard_v1 WHERE token=?', (self.token,))
            except Exception:
                pass
        self.active = False
