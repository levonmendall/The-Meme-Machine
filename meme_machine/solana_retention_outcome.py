"""Committed cleanup outcomes, separate from scheduler control flow.

This is a scheduling/telemetry value, never evidence or retirement authority.
A partial examination cannot assert that the unexamined database is empty.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScopeRetentionOutcome:
    scope: str
    retired_records: int
    continuity_rows: int
    floor_updates: int
    committed_slices: int
    pending: bool


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
    scopes: tuple[ScopeRetentionOutcome, ...] = ()

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
    by_scope: dict = field(default_factory=dict)
    examined: set = field(default_factory=set)
    remaining: set = field(default_factory=set)
    complete: bool = False
    interrupted: bool = False
    yield_reason: str | None = None

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
        counts=self.by_scope.setdefault(scope,[0,0,0,0])
        for index,value in enumerate((retired,continuity,floor_updates,1)):
            counts[index]+=value
        self.scope(scope, remaining)

    def snapshot(self):
        pending = True if self.remaining else False if self.complete else None
        return RetentionOutcome(self.retired_records, self.continuity_rows,
            self.housekeeping_rows, self.floor_updates, self.committed_slices,
            len(self.examined), pending, self.interrupted, self.yield_reason,
            tuple(ScopeRetentionOutcome(scope,*self.by_scope.get(scope,(0,0,0,0)),
                                        scope in self.remaining)
                  for scope in sorted(self.examined)))
