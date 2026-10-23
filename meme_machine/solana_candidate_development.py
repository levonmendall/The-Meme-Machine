"""Cooperative owner quanta for candidate development; never entry authority.

Every completed quantum returns to the existing owner FIFO. Scheduling cursors
advance only after its native transaction commits, and may restart from zero.
No transaction, proof verdict or mutable financial state crosses that boundary.
"""
from dataclasses import dataclass
import copy
import time

from .runtime.operation_costs import operation
from .runtime.operating_families import active_sql
from .solana_evidence_plane import EvidenceUnavailable


DISPATCH = 'DISPATCH'
DEFERRED = 'DEFERRED'
IDLE = 'IDLE'
DEVELOPMENT_QUANTUM = 16
MICROBATCH_TRANSITIONS = 16
MICROBATCH_SECONDS = .005


@dataclass(frozen=True)
class PlanningStep:
    state: str
    plan: tuple | None = None
    yield_quantum: bool = False


class DevelopmentCandidates:
    """Indexed pending selection, independent of retained candidate population.

    Exact-key triggers maintain the scheduling projection; the market rows and
    bindings remain authoritative. A bounded keyset rebuild admits old rows
    before selection starts and survives interruption without a population cap.
    """
    QUEUE = 'candidate_development_ready_v1'
    STATE = 'candidate_development_state_v1'

    def __init__(self, history, minimum):
        self.history = history
        self.db = history.db
        self.minimum = minimum
        from .solana_selective_history import DEVELOPMENT_BOUND
        with history.writer.transaction():
            self.db.execute(f'''CREATE TABLE IF NOT EXISTS {self.QUEUE}(
                address TEXT PRIMARY KEY,first_seen REAL NOT NULL)''')
            self.db.execute(f'''CREATE INDEX IF NOT EXISTS candidate_development_order_v1
                ON {self.QUEUE}(first_seen,address)''')
            self.db.execute(f'''CREATE TABLE IF NOT EXISTS {self.STATE}(
                id INTEGER PRIMARY KEY CHECK(id=1),minimum INTEGER NOT NULL,
                after_address TEXT NOT NULL,complete INTEGER NOT NULL CHECK(complete IN (0,1)))''')
            # Empty installation needs no future rebuild: exact-key triggers
            # below already account for every subsequent live insertion.
            empty=self.db.execute("SELECT 1 FROM market_observations WHERE family='pump' LIMIT 1").fetchone() is None
            self.db.execute(f"INSERT OR IGNORE INTO {self.STATE} VALUES(1,?,'',?)", (minimum,int(empty)))
            if self.db.execute(f'SELECT minimum FROM {self.STATE} WHERE id=1').fetchone() != (minimum,):
                raise EvidenceUnavailable('candidate_development_policy_migration_required')
            criterion = DEVELOPMENT_BOUND.replace('fields', 'NEW.fields')
            populate = f'''INSERT INTO {self.QUEUE}(address,first_seen)
                SELECT NEW.address,NEW.first_seen WHERE
                ({criterion} IS NULL OR {criterion}>=(SELECT minimum FROM {self.STATE} WHERE id=1))
                AND NOT EXISTS(SELECT 1 FROM evidence_bindings b WHERE b.family='pump' AND b.address=NEW.address)
                ON CONFLICT(address) DO UPDATE SET first_seen=excluded.first_seen;'''
            for action in ('INSERT', 'UPDATE'):
                self.db.execute(f'''CREATE TRIGGER IF NOT EXISTS candidate_development_market_{action.lower()}_v1
                    AFTER {action} ON market_observations WHEN NEW.family='pump'
                    BEGIN DELETE FROM {self.QUEUE} WHERE address=NEW.address; {populate} END''')
            self.db.execute(f'''CREATE TRIGGER IF NOT EXISTS candidate_development_market_move_v1
                AFTER UPDATE OF family,address ON market_observations
                WHEN OLD.family='pump' AND (OLD.family IS NOT NEW.family OR OLD.address IS NOT NEW.address)
                BEGIN DELETE FROM {self.QUEUE} WHERE address=OLD.address; END''')
            self.db.execute(f'''CREATE TRIGGER IF NOT EXISTS candidate_development_market_delete_v1
                AFTER DELETE ON market_observations WHEN OLD.family='pump'
                BEGIN DELETE FROM {self.QUEUE} WHERE address=OLD.address; END''')
            for action in ('INSERT', 'UPDATE'):
                self.db.execute(f'''CREATE TRIGGER IF NOT EXISTS candidate_development_binding_{action.lower()}_v1
                    AFTER {action} ON evidence_bindings WHEN NEW.family='pump'
                    BEGIN DELETE FROM {self.QUEUE} WHERE address=NEW.address; END''')
            restore_old = f'''INSERT OR IGNORE INTO {self.QUEUE}(address,first_seen)
                SELECT address,first_seen FROM market_observations m
                WHERE family='pump' AND address=OLD.address AND
                ({DEVELOPMENT_BOUND} IS NULL OR {DEVELOPMENT_BOUND}>=(SELECT minimum FROM {self.STATE} WHERE id=1))
                AND NOT EXISTS(SELECT 1 FROM evidence_bindings b WHERE b.family='pump' AND b.address=m.address);'''
            self.db.execute(f'''CREATE TRIGGER IF NOT EXISTS candidate_development_unbind_v1
                AFTER DELETE ON evidence_bindings WHEN OLD.family='pump'
                BEGIN {restore_old} END''')
            self.db.execute(f'''CREATE TRIGGER IF NOT EXISTS candidate_development_binding_move_v1
                AFTER UPDATE OF family,address ON evidence_bindings
                WHEN OLD.family='pump' AND (OLD.family IS NOT NEW.family OR OLD.address IS NOT NEW.address)
                BEGIN {restore_old} END''')
            self.db.execute('''CREATE INDEX IF NOT EXISTS candidate_reactivated_family_v1
                ON candidate_lifecycle(state,family)''')
            self.db.execute('''CREATE INDEX IF NOT EXISTS candidate_reactivation_seen_v1
                ON candidate_history_outbox(family,address,kind,json_extract(body,'$.epoch'),json_extract(body,'$.seen'))''')

    def backfill(self, timing):
        from .solana_selective_history import DEVELOPMENT_BOUND
        with self.history.writer.transaction():
            with timing.phase('selection'):
                after, complete = self.db.execute(
                    f'SELECT after_address,complete FROM {self.STATE} WHERE id=1').fetchone()
                if complete:
                    return True
                rows = self.db.execute('''SELECT address FROM market_observations
                    WHERE family='pump' AND address>? ORDER BY address LIMIT ?''',
                    (after, DEVELOPMENT_QUANTUM)).fetchall()
                for address, in rows:
                    self.db.execute(f'''INSERT OR IGNORE INTO {self.QUEUE}(address,first_seen)
                        SELECT address,first_seen FROM market_observations m
                        WHERE family='pump' AND address=? AND
                        ({DEVELOPMENT_BOUND} IS NULL OR {DEVELOPMENT_BOUND}>=?) AND
                        NOT EXISTS(SELECT 1 FROM evidence_bindings b WHERE b.family='pump' AND b.address=m.address)''',
                        (address, self.minimum))
                complete = len(rows) < DEVELOPMENT_QUANTUM
                self.db.execute(f'UPDATE {self.STATE} SET after_address=?,complete=? WHERE id=1',
                    (rows[-1][0] if rows else after, int(complete)))
        return complete

    def next(self):
        from .solana_selective_history import DEVELOPMENT_BOUND
        rows=self.db.execute(f'''SELECT address,first_seen FROM {self.QUEUE}
            ORDER BY first_seen,address LIMIT ?''', (DEVELOPMENT_QUANTUM,)).fetchall()
        result=[]
        for address,first_seen in rows:
            current=self.db.execute('''SELECT first_seen FROM market_observations m
                WHERE family='pump' AND address=? AND
                ('''+DEVELOPMENT_BOUND+''' IS NULL OR '''+DEVELOPMENT_BOUND+'''>=?) AND
                NOT EXISTS(SELECT 1 FROM evidence_bindings b WHERE b.family='pump' AND b.address=m.address)''',
                (address,self.minimum)).fetchone()
            if current!=(first_seen,):
                raise EvidenceUnavailable('candidate_development_projection_mismatch')
            result.append((address,))
        return result

    def reactivated(self, after):
        def page(cursor):
            rows = []
            for family in sorted(self.history.active_families):
                rows.extend(self.db.execute('''SELECT rowid,family,address,lower_slot
                    FROM candidate_lifecycle INDEXED BY candidate_reactivated_family_v1
                    WHERE state='reactivated' AND family=? AND rowid>? ORDER BY rowid LIMIT ?''',
                    (family, cursor, DEVELOPMENT_QUANTUM)).fetchall())
            return sorted(rows)[:DEVELOPMENT_QUANTUM]
        rows = page(after)
        return rows if rows or not after else page(0)


class CandidateDevelopment:
    """One actor shared by all acquisition workers on the canonical owner."""
    def __init__(self, history, *, clock=time.monotonic):
        self.history = history
        self.clock = clock
        self.phase = 0
        self.poll_at = 0
        self.external_poll_at = 0
        self.external_started = False
        self.external_boundary_done = False
        self.cursors = dict(reactivated=0, boundary=0, publication=0)
        from .lanes.pump.pump_acceleration_strategy import POLICY
        self.candidates = DevelopmentCandidates(history, POLICY.min_curve_progress_bps)
        history.install_planner()

    def _external_hooks(self, timing, batched, housekeeping):
        h=self.history
        if h.db.in_transaction:
            raise EvidenceUnavailable('candidate_hooks_before_canonical_commit')
        # Legacy publishers own separate transactions. They must see committed
        # preparations and finish BEFORE any fresh dispatch/claim is selected.
        boundary=self.phase==4 and not self.external_boundary_done
        admitted=not housekeeping and self.clock()>=self.external_poll_at
        if not batched and (boundary or admitted or not self.external_started):
            with timing.phase('publication'):
                h.lifecycle.publish()
        if 'meteora' in h.active_families and (boundary or admitted):
            # Preserve the original legacy EDF repair contract. Its retained
            # population cost is outside the operating Pump/Pons bound.
            with timing.phase('plan'):
                h.rolling.repair_required_checkpoint_prefixes()
        if boundary:self.external_boundary_done=True
        if boundary or admitted or not self.external_started:
            self.external_started=True
            self.external_poll_at=self.clock()+.1

    def _microbatch(self, timing, frontier, excluding, batched, *, housekeeping):
        from .solana_planning_quantum import PlanningQuantum
        self._external_hooks(timing,batched,housekeeping)
        # Only successfully committed scalar cursors become actor state.
        staged=copy.copy(self)
        staged.cursors=dict(self.cursors)
        cutoff=time.perf_counter()+MICROBATCH_SECONDS
        result=PlanningStep(DEFERRED)
        urgent=True
        with timing.transaction_exit(self.history.writer.transaction(),phase_name='commit'):
            quantum=PlanningQuantum(self.history,deadline=cutoff)
            try:
                for _ in range(MICROBATCH_TRANSITIONS):
                    if urgent:
                        with timing.phase('plan'):
                            result=self.history.plan_step(excluding=excluding,urgent_only=True,quantum=quantum)
                        if result.state==IDLE:
                            urgent=False
                            result=PlanningStep(DEFERRED)
                    elif housekeeping:
                        result=staged._step(timing,frontier,excluding=excluding,batched=batched,quantum=quantum)
                    else:
                        result=staged._plan(timing,excluding,batched,quantum)
                    if (result.state==DISPATCH or result.yield_quantum or
                            result.state==IDLE and not urgent):break
                    if time.perf_counter()>=cutoff:break
            finally:
                quantum.close()
        self.phase,self.poll_at,self.cursors=staged.phase,staged.poll_at,staged.cursors
        self.external_boundary_done=staged.external_boundary_done
        return result

    def step(self, timing, frontier, *, excluding=(), batched=True):
        return self._microbatch(timing,frontier,excluding,batched,housekeeping=True)

    def plan(self, timing, excluding, batched):
        return self._microbatch(timing,None,excluding,batched,housekeeping=False)

    def _step(self, timing, frontier, *, excluding=(), batched=True, quantum=None):
        h = self.history
        db = h.db
        if self.phase == 4:
            result = self._plan(timing, excluding, batched, quantum)
            self.phase = 0
            self.external_boundary_done=False
            return result
        if self.phase == 0 and self.clock() < self.poll_at:
            return self._plan(timing, excluding, batched, quantum)
        phase = self.phase
        if phase == 0 and not self.candidates.backfill(timing):
            # Projection reconstruction cannot monopolize all future turns.
            # Other phases and dispatch still get their explicit quantum.
            self.phase = 1
            return PlanningStep(DEFERRED)
        cursor = None
        with h.writer.transaction():
            if phase == 0:
                with timing.phase('selection'):
                    for address, in self.candidates.next():
                        # Binding suppresses future selection. Its initial
                        # durable preparation must commit in this same unit.
                        h.bind('pump', address)
                        first = db.execute("SELECT first_seen FROM candidate_lifecycle WHERE family='pump' AND address=?",
                                           (address,)).fetchone()[0]
                        h.rolling.prepare('pump', address, 0, frontier, priority=3, deadline=first+150)
            elif phase == 1:
                with timing.phase('reactivation'):
                    with operation('owner.reactivation_lookup'):
                        rows = self.candidates.reactivated(self.cursors['reactivated'])
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
        self.phase = phase+1
        if self.phase == 4:
            self.poll_at = self.clock()+.1
            if not batched or 'meteora' in h.active_families:
                # Commit all canonical preparations first. The next owner turn
                # performs the external hook, then makes a fresh decision.
                return PlanningStep(DEFERRED,yield_quantum=True)
        # A successful housekeeping quantum is progress, never an empty plan.
        return PlanningStep(DEFERRED)

    def _plan(self, timing, excluding, batched, quantum=None):
        with timing.phase('plan'):
            return self.history.plan_step(excluding=excluding,quantum=quantum)
