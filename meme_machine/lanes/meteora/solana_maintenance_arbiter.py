"""Production two-sided arbitration, derived from the preserved reference.

One owner-entry decision, no worker pool or competing scheduler. Reservations
are expiring admission/execution leases, NOT extrapolated historical maxima.
The liveness theorem is conditional on the declared lease/clock/ready/progress
assumptions. Violations revoke admission rather than renew successful service.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import time
from typing import Mapping

from .solana_evidence_control import COMMAND_SECONDS
from .solana_evidence_plane import EvidenceUnavailable
from .solana_maintenance_state import (PRESERVATION_SECONDS, RESIDENCE_SECONDS,
    RECOVERY_SOURCE_SECONDS, PIPELINE_SLACK_RECORDS, NativeObservation)

SIDES = ('archive', 'retirement')


@dataclass(frozen=True)
class ServiceLeases:
    """An operating contract with checked expiry, not a timing forecast.

    Owner admission and a bounded maintenance call each get the existing
    command-lifetime budget. The next opposite-side call reserves BOTH. The
    unchanged source-stall budget bounds waiting for the one archive worker.
    No telemetry high-water mark can increase these leases.
    """
    owner: float = COMMAND_SECONDS
    execution: float = COMMAND_SECONDS
    clock_error: float = COMMAND_SECONDS
    worker: float = 15.0

    def validate(self):
        if any(not math.isfinite(n) or n <= 0 for n in vars(self).values()):
            raise EvidenceUnavailable('maintenance_invalid_service_lease')
        if self.drought <= 0:
            raise EvidenceUnavailable('maintenance_no_two_sided_reservation')

    @property
    def pair(self):
        return 2*self.execution + 2*self.owner + self.clock_error

    @property
    def drought(self):
        return RESIDENCE_SECONDS-PRESERVATION_SECONDS-self.pair


class ClockModel:
    """Project timestamp deadlines, NOT source rates, into monotonic time.

    Validated source timestamps cannot exceed their wall receive timestamp.
    Therefore, with |wall-(anchor_wall+elapsed_mono)| <= error, a source deadline
    D cannot be reached before anchor_mono + D-anchor_wall-error. This remains
    conservative during stalled source delivery and arbitrarily fast catch-up.
    It does not assert 120 source-seconds == 120 elapsed wall-seconds.
    """
    def __init__(self, wall, monotonic, error):
        self.wall = wall
        self.monotonic = monotonic
        self.error = error
        self.last = monotonic
        self.source = {}

    def check(self, wall, monotonic, source: Mapping[str, float | None]):
        if (not all(math.isfinite(n) for n in (wall, monotonic)) or
                monotonic < self.last or
                abs(wall-(self.wall+monotonic-self.monotonic)) > self.error):
            raise EvidenceUnavailable('maintenance_clock_relationship_invalid')
        self.last = monotonic
        for scope, at in source.items():
            if at is None:
                continue
            if not math.isfinite(at) or at > wall:
                raise EvidenceUnavailable('maintenance_source_clock_invalid')
            # A missing old row after retirement is NOT source-clock regression.
            # Keep the validated high-water; new source provenance is checked by
            # FinalizedFence independently of this scheduling coordinate.
            self.source[scope] = max(self.source.get(scope, at), at)

    def project(self, absolute_wall_or_source_deadline):
        if not math.isfinite(absolute_wall_or_source_deadline):
            raise EvidenceUnavailable('maintenance_deadline_invalid')
        return self.monotonic+absolute_wall_or_source_deadline-self.wall-self.error


@dataclass(frozen=True)
class Need:
    scope: str
    side: str
    units: int
    records: int
    safety_deadline: float
    recovery_deadline: float | None
    recovery_excess: int


@dataclass(frozen=True)
class Decision:
    sequence: int
    side: str
    started: float
    deadline: float
    reason: str
    scopes: tuple[str, ...]
    deadline_by_side: tuple[tuple[str, float], ...]
    need_by_side: tuple[tuple[str, float], ...]


class MaintenanceArbiter:
    def __init__(self, generation, leases=None):
        self.generation = generation
        self.leases = leases or ServiceLeases()
        self.leases.validate()
        self.origin = {}
        self.sequence = 0
        self.pending = None
        self.failed = False
        self.last_now = float('-inf')
        self.last_side = None
        self.rates = {s: deque(maxlen=8) for s in SIDES}
        self.max_gap = {s: 0.0 for s in SIDES}
        self.max_scope_gap = {}

    def _clock(self, now):
        if not math.isfinite(now) or now < self.last_now:
            self.failed = True
            raise EvidenceUnavailable('maintenance_clock_regressed')
        self.last_now = now

    def restore_progress(self, scope, side, when, now):
        if when > now or not math.isfinite(when):
            raise EvidenceUnavailable('maintenance_progress_clock_invalid')
        key = side, scope
        if key not in self.origin:
            # On restart, preserve past drought rather than gifting a new lease.
            self.origin[key] = when

    def rate(self, side):
        # Measured rates only rank surplus; never extend lease or safety times.
        return max(1.0, min(self.rates[side], default=1.0))

    def choose(self, *, generation, as_of, now, needs, ready):
        self._clock(now)
        if self.failed:
            raise EvidenceUnavailable('maintenance_admission_revoked')
        if self.pending is not None:
            raise EvidenceUnavailable('maintenance_decision_in_flight')
        if generation != self.generation or now-as_of > self.leases.owner or now < as_of:
            raise EvidenceUnavailable('maintenance_stale_or_wrong_generation')
        if set(ready) != set(SIDES) or any(type(v) is not bool for v in ready.values()):
            raise EvidenceUnavailable('maintenance_readiness_incomplete')
        by_side = {s: [] for s in SIDES}
        seen = set()
        for n in needs:
            key = n.side, n.scope
            if (n.side not in SIDES or key in seen or type(n.units) is not int or n.units < 0 or
                    type(n.records) is not int or n.records < 0 or n.records > n.units or
                    not math.isfinite(n.safety_deadline)):
                raise EvidenceUnavailable('maintenance_demand_invalid')
            seen.add(key)
            if n.units:
                self.origin.setdefault(key, now)
                by_side[n.side].append(n)
            else:
                self.origin.pop(key, None)
        deadlines, scores, scope_order = {}, {}, {}
        for side in SIDES:
            if not by_side[side]:
                continue
            scope_deadlines = {}
            pressure = 0.0
            for n in by_side[side]:
                deadline = min(n.safety_deadline, self.origin[side, n.scope]+self.leases.drought)
                if n.recovery_excess:
                    if n.recovery_deadline is None or not math.isfinite(n.recovery_deadline):
                        raise EvidenceUnavailable('maintenance_missing_recovery_clock')
                    deadline = min(deadline, n.recovery_deadline)
                if deadline <= now:
                    raise EvidenceUnavailable('maintenance_service_deadline_exhausted')
                scope_deadlines[n.scope] = deadline
                # Safety applies below the recovery slack as well. Low debt is
                # NOT permission to ignore age, continuity, floors or housekeeping.
                pressure += n.units / self.rate(side) / (n.safety_deadline-now)
                if n.recovery_excess:
                    pressure += n.recovery_excess / self.rate(side) / (n.recovery_deadline-now)
            deadlines[side] = min(scope_deadlines.values())
            scores[side] = pressure
            scope_order[side] = tuple(sorted(scope_deadlines, key=lambda s: (scope_deadlines[s], s)))
        # Deadlines of temporarily unready work still constrain peer admissions.
        feasible = []
        for side in deadlines:
            if not ready[side]:
                continue
            finish = now+self.leases.execution
            if finish >= deadlines[side]:
                continue
            if all(finish+self.leases.owner+self.leases.execution < deadline
                   for other, deadline in deadlines.items() if other != side):
                feasible.append(side)
        if not feasible:
            if deadlines and any(now+self.leases.execution+self.leases.owner >= d for d in deadlines.values()):
                raise EvidenceUnavailable('maintenance_cannot_reserve_both_sides')
            return None
        preferred = min(deadlines, key=lambda s: (-scores[s], deadlines[s], s==self.last_side, s))
        side = preferred if preferred in feasible else min(feasible, key=lambda s: deadlines[s])
        self.sequence += 1
        self.pending = Decision(self.sequence, side, now, deadlines[side],
            'debt_surplus' if side == preferred else 'peer_reservation', scope_order[side],
            tuple(sorted(deadlines.items())), tuple(sorted(scores.items())))
        return self.pending

    def complete(self, decision, now, progress, *, record_progress=None):
        self._clock(now)
        if decision is not self.pending:
            raise EvidenceUnavailable('maintenance_completion_identity')
        self.pending = None
        if now-decision.started > self.leases.execution or now >= decision.deadline:
            self.failed = True
            raise EvidenceUnavailable('maintenance_execution_lease_exceeded')
        record_progress = record_progress or {}
        if any(type(n) is not int or n < 0 for n in progress.values()):
            self.failed = True
            raise EvidenceUnavailable('maintenance_durable_progress_invalid')
        if decision.side == 'archive' and sum(record_progress.values()) > 512:
            self.failed = True
            raise EvidenceUnavailable('maintenance_archive_slice_exceeds_512')
        for scope, units in progress.items():
            key = decision.side, scope
            if units and key in self.origin:
                gap = now-self.origin[key]
                self.max_gap[decision.side] = max(self.max_gap[decision.side], gap)
                self.max_scope_gap[key] = max(self.max_scope_gap.get(key, 0), gap)
                self.origin[key] = now
        elapsed = now-decision.started
        count = sum(record_progress.values())
        if count and elapsed > 0:
            self.rates[decision.side].append(count/elapsed)
        if any(progress.values()):
            self.last_side = decision.side
        # No progress deliberately leaves the successful-service clock unchanged.
