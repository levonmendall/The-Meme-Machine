"""Cooperative owner quanta for candidate development; never entry authority.

Every completed quantum returns to the existing owner FIFO. Scheduling cursors
advance only after its native transaction commits, and may restart from zero.
No transaction, proof verdict or mutable financial state crosses that boundary.
"""
from dataclasses import dataclass
import time

from .runtime.operation_costs import operation
from .runtime.operating_families import active_sql


DISPATCH = 'DISPATCH'
DEFERRED = 'DEFERRED'
IDLE = 'IDLE'
DEVELOPMENT_QUANTUM = 16


@dataclass(frozen=True)
class PlanningStep:
    state: str
    plan: tuple | None = None


class CandidateDevelopment:
    """One actor shared by all acquisition workers on the canonical owner."""
    def __init__(self, history, *, clock=time.monotonic):
        self.history = history
        self.clock = clock
        self.phase = 0
        self.poll_at = 0
        self.cursors = dict(reactivated=0, boundary=0, publication=0)

    def step(self, timing, frontier, *, excluding=(), batched=True):
        h = self.history
        db = h.db
        if self.phase == 0 and self.clock() < self.poll_at:
            return self.plan(timing, excluding, batched)
        phase = self.phase
        cursor = None
        with timing.transaction_exit(h.writer.transaction(), phase_name='commit'):
            if phase == 0:
                from .lanes.pump.pump_acceleration_strategy import POLICY
                with timing.phase('selection'):
                    for address, in h.development_candidates(POLICY.min_curve_progress_bps, DEVELOPMENT_QUANTUM):
                        # Binding suppresses future selection. Its initial
                        # durable preparation must commit in this same unit.
                        h.bind('pump', address)
                        first = db.execute("SELECT first_seen FROM candidate_lifecycle WHERE family='pump' AND address=?",
                                           (address,)).fetchone()[0]
                        h.rolling.prepare('pump', address, 0, frontier, priority=3, deadline=first+150)
            elif phase == 1:
                with timing.phase('reactivation'):
                    query = ("SELECT rowid,family,address,lower_slot FROM candidate_lifecycle WHERE "+
                        active_sql('family', solana=True)+
                        " AND state='reactivated' AND rowid>? ORDER BY rowid LIMIT ?")
                    with operation('owner.reactivation_lookup'):
                        rows = db.execute(query, (self.cursors['reactivated'], DEVELOPMENT_QUANTUM)).fetchall()
                        if not rows and self.cursors['reactivated']:
                            rows = db.execute(query, (0, DEVELOPMENT_QUANTUM)).fetchall()
                    for _, family, address, lower in rows:
                        with operation('owner.reactivation_lookup'):
                            epoch = db.execute('SELECT epoch FROM candidate_lifecycle WHERE family=? AND address=?',
                                               (family, address)).fetchone()[0]
                            first = db.execute("SELECT MIN(json_extract(body,'$.seen')) FROM candidate_history_outbox "
                                "WHERE family=? AND address=? AND kind='reactivated' AND json_extract(body,'$.epoch')=?",
                                (family, address, epoch)).fetchone()[0]
                        deadline = (time.time() if first is None else first)+150
                        if deadline <= time.time():
                            h._observation(None, 'promotion_deadline_missed',
                                dict(family=family, address=address, deadline=deadline, deadline_reset=False))
                            h.lifecycle.demote(family, address, reason='original_promotion_deadline_expired')
                            continue
                        if hasattr(h, 'historical_tasks') and family in ('pump', 'pumpswap'):
                            if not h.historical_tasks.cold_ready(family, address, epoch=epoch, deadline=deadline):
                                continue
                        else:
                            from .solana_scoped_retirement import ScopedRetirement
                            ScopedRetirement(h).restore(family, address)
                        h.lifecycle.promote(family, address, deadline=deadline,
                            lower_slot=0 if family == 'pump' else None if family == 'meteora' else lower)
                    cursor = rows[-1][0] if rows else 0
            elif phase == 2:
                with timing.phase('boundaries'):
                    cursor = h.rolling.resume_boundaries(limit=DEVELOPMENT_QUANTUM, after=self.cursors['boundary'])
            else:
                with timing.phase('publication'):
                    cursor = h.rolling.resume_publication(limit=DEVELOPMENT_QUANTUM, after=self.cursors['publication'])
        if phase:
            self.cursors[('reactivated', 'boundary', 'publication')[phase-1]] = cursor
        self.phase = (phase+1) % 4
        if self.phase == 0:
            self.poll_at = self.clock()+.1
        # A successful housekeeping quantum is progress, never an empty plan.
        return PlanningStep(DEFERRED)

    def plan(self, timing, excluding, batched):
        h = self.history
        with timing.phase('plan'):
            if not batched:
                h.lifecycle.publish()
            if 'meteora' in h.active_families:
                h.rolling.repair_required_checkpoint_prefixes()
            return h.plan_step(excluding=excluding)
