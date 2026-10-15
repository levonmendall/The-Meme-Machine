"""Committed cleanup outcomes, separate from scheduler control flow.

This is a scheduling/telemetry value, never evidence or retirement authority.
A partial examination cannot assert that the unexamined database is empty.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass, field
import math
import time

from .solana_candidate_phases import runnable_snapshot

RETENTION_PHASES = ('plan', 'transaction', 'housekeeping', 'post')


@dataclass(frozen=True)
class RetentionOutcome:
    retired_records: int = 0
    continuity_rows: int = 0
    housekeeping_rows: int = 0
    floor_updates: int = 0
    committed_slices: int = 0
    examined_scopes: int = 0
    pending: bool | None = None
    interrupted: bool = False
    yield_reason: str | None = None

    @property
    def made_progress(self):
        return bool(self.retired_records or self.continuity_rows or
                    self.housekeeping_rows or self.floor_updates)

    @property
    def pressure(self):
        # An exception, changed telemetry, or successful past work is not backlog.
        return self.pending is True

    @property
    def retry(self):
        return self.pending is not False

    def __bool__(self):
        raise TypeError("retention_outcome_requires_explicit_field")


@dataclass
class RetentionProgress:
    retired_records: int = 0
    continuity_rows: int = 0
    housekeeping_rows: int = 0
    floor_updates: int = 0
    committed_slices: int = 0
    examined: set = field(default_factory=set)
    remaining: set = field(default_factory=set)
    complete: bool = False
    interrupted: bool = False
    yield_reason: str | None = None
    timing_enabled: bool = False
    timing_unmeasured: bool = False
    phase_totals: dict = field(default_factory=dict, repr=False)

    def _timing_sample(self):
        wall, cpu = time.monotonic(), time.thread_time()
        if any(type(value) not in (int, float) or not math.isfinite(value)
               for value in (wall, cpu)):
            return None
        try:runnable = runnable_snapshot()
        except BaseException:runnable = None
        return wall, cpu, runnable

    @contextmanager
    def phase(self, name):
        """Optional exclusive costs, independent of committed progress.

        The caller wraps the original operation, including context-manager exit.
        Missing probes remain explicit; telemetry never replaces its exception.
        """
        if not self.timing_enabled:
            yield
            return
        started = None
        try:
            if name in RETENTION_PHASES:started = self._timing_sample()
        except BaseException:
            pass
        try:
            yield
        finally:
            try:
                ended = self._timing_sample()
                if (name not in RETENTION_PHASES or started is None or ended is None
                        or ended[0] < started[0] or ended[1] < started[1]):
                    self.timing_unmeasured = True
                else:
                    for kind, value in (('wall', ended[0]-started[0]),
                                        ('cpu', ended[1]-started[1])):
                        key = 'retention_phase.'+name+'.'+kind+'_us'
                        self.phase_totals[key] = self.phase_totals.get(key, 0)+int(value*1_000_000)
                a = None if started is None else started[2]
                b = None if ended is None else ended[2]
                if (name in RETENTION_PHASES and isinstance(a, tuple) and isinstance(b, tuple)
                        and len(a) == len(b) == 3 and a[:2] == b[:2]
                        and all(type(value) is int for value in (*a, *b))
                        and a[0] > 0 and a[1] > 0 and 0 <= a[2] <= b[2]):
                    key = 'retention_phase.'+name+'.runnable_us'
                    self.phase_totals[key] = self.phase_totals.get(key, 0)+(b[2]-a[2])//1000
                else:
                    self.timing_unmeasured = True
            except BaseException:
                self.timing_unmeasured = True

    def timing_metrics(self):
        """At most thirteen fixed numeric fields; no defaults for absent phases."""
        if not self.timing_enabled:return {}
        expected = {'retention_phase.'+name+'.'+kind+'_us'
                    for name in RETENTION_PHASES for kind in ('wall', 'cpu', 'runnable')}
        result = {key:self.phase_totals[key] for key in expected if key in self.phase_totals}
        # This per-call flag becomes a cumulative incomplete-call count in the
        # existing service metrics. An unentered phase is NOT_EXERCISED, not
        # recorder loss or a fabricated healthy zero.
        result['retention_phase.unmeasured'] = int(self.timing_unmeasured)
        return result

    def scope(self, name, remaining):
        self.examined.add(name)
        if remaining:
            self.remaining.add(name)
        else:
            self.remaining.discard(name)

    def commit(self, scope, retired, continuity, floor_updates, remaining):
        # Called only AFTER the production transaction has durably committed.
        self.retired_records += retired
        self.continuity_rows += continuity
        self.floor_updates += floor_updates
        self.committed_slices += 1
        self.scope(scope, remaining)

    def snapshot(self):
        pending = True if self.remaining else False if self.complete else None
        return RetentionOutcome(self.retired_records, self.continuity_rows,
            self.housekeeping_rows, self.floor_updates, self.committed_slices,
            len(self.examined), pending, self.interrupted, self.yield_reason)
