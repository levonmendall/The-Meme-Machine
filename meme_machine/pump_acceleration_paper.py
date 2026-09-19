"""Paper lifecycle state for pump-acceleration-independent-v1.

This is intentionally not a capital allocator.  A caller must obtain a budget from
shared portfolio governance first.  The lifecycle then tracks only this strategy's
reservation/fill/gradation/exit state and rejects qualifications from every other
strategy namespace.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from .pump_acceleration_strategy import (
    STRATEGY_ID, ExitObservation, Qualification, exit_decision,
)


@dataclass
class PaperPosition:
    strategy_id: str
    mode: str
    mint: str
    surface: str
    opened_at: int
    tokens: int
    basis_quote_units: int
    peak_return_bps: int = 0
    graduation_authenticated: bool = False
    graduation_time: int | None = None
    exit_reason: str | None = None
    exit_intended_at: int | None = None
    realized_quote_units: int | None = None
    closed_at: int | None = None


class PumpAccelerationPaperLifecycle:
    """One independent strategy lifecycle; no shared-capital authority."""

    def __init__(self, *, book=None, lifecycle_id=None, entry_evidence=None):
        self.reservation=None
        self.position=None
        self.history=[]
        self.book=book
        self.lifecycle_id=lifecycle_id
        self.entry_evidence=entry_evidence or {}
        if book is not None and not lifecycle_id:
            raise ValueError("durable_lifecycle_id_required")

    def reserve(self, qualification: Qualification, budget_quote_units: int, now: int):
        if qualification.strategy_id != STRATEGY_ID:
            raise ValueError("foreign_strategy_qualification")
        if not qualification.qualified:
            raise ValueError("unqualified_strategy_signal")
        if budget_quote_units <= 0:
            raise ValueError("invalid_budget")
        if self.reservation is not None or self.position is not None:
            raise ValueError("lifecycle_already_active")
        if self.book is not None:
            self.book.reserve(self.lifecycle_id,int(budget_quote_units),int(now),
                              dict(qualification=asdict(qualification),
                                   snapshot=self.entry_evidence))
        self.reservation=dict(
            strategy_id=STRATEGY_ID,
            mode=qualification.mode,
            mint=qualification.mint,
            budget_quote_units=int(budget_quote_units),
            reserved_at=int(now),
            policy_hash=qualification.policy_hash,
            score=int(qualification.score),
        )
        self.history.append(dict(event="reserved",**self.reservation))
        return dict(self.reservation)

    def fill(self, tokens: int, cost_quote_units: int, now: int, surface: str, *, evidence=None):
        if self.reservation is None or self.position is not None:
            raise ValueError("no_active_reservation")
        if tokens <= 0 or cost_quote_units <= 0:
            raise ValueError("invalid_fill")
        if cost_quote_units > self.reservation["budget_quote_units"]:
            raise ValueError("fill_exceeds_budget")
        if surface not in ("pump.fun","pumpswap"):
            raise ValueError("unsupported_surface")
        if self.book is not None:
            self.book.transition(self.lifecycle_id,"filled",int(now),
                                 amount=int(cost_quote_units),tokens=int(tokens),
                                 evidence=dict(surface=surface,execution=evidence))
        self.position=PaperPosition(
            strategy_id=STRATEGY_ID,
            mode=self.reservation["mode"],
            mint=self.reservation["mint"],
            surface=surface,
            opened_at=int(now),
            tokens=int(tokens),
            basis_quote_units=int(cost_quote_units),
        )
        self.history.append(dict(event="filled",position=asdict(self.position)))
        self.reservation=None
        return asdict(self.position)

    def cancel(self, reason: str, now: int):
        if self.reservation is None:
            raise ValueError("no_active_reservation")
        if self.book is not None:
            self.book.transition(self.lifecycle_id,"cancelled",int(now),
                                 evidence=dict(reason=str(reason)))
        self.history.append(dict(event="cancelled",reason=str(reason),time=int(now),reservation=dict(self.reservation)))
        self.reservation=None

    def authenticate_graduation(self, now: int, authenticated: bool):
        if self.position is None:
            raise ValueError("no_open_position")
        if self.position.surface != "pump.fun":
            return asdict(self.position)
        if not authenticated:
            raise ValueError("unauthenticated_graduation")
        self.position.surface="pumpswap"
        self.position.graduation_authenticated=True
        self.position.graduation_time=int(now)
        self.history.append(dict(event="graduation",time=int(now),mint=self.position.mint,surface="pumpswap"))
        return asdict(self.position)

    def mark(self, executable_proceeds_quote_units: int, now: int, demand_score: int,
             postgrad_demand_confirmed: bool=False, *, evidence=None):
        if self.position is None:
            raise ValueError("no_open_position")
        if executable_proceeds_quote_units < 0:
            raise ValueError("invalid_mark")
        if self.book is not None:
            self.book.transition(self.lifecycle_id,"mark",int(now),
                                 amount=int(executable_proceeds_quote_units),
                                 evidence=dict(demand_score=int(demand_score),
                                               postgrad_demand_confirmed=bool(postgrad_demand_confirmed),
                                               execution=evidence))
        basis=self.position.basis_quote_units
        ret=(int(executable_proceeds_quote_units)-basis)*10_000//basis
        self.position.peak_return_bps=max(self.position.peak_return_bps,ret)
        since_grad=(None if self.position.graduation_time is None
                    else int(now)-self.position.graduation_time)
        observation=ExitObservation(
            mode=self.position.mode,
            now=int(now),
            opened_at=self.position.opened_at,
            return_bps=int(ret),
            peak_return_bps=int(self.position.peak_return_bps),
            demand_score=int(demand_score),
            surface=self.position.surface,
            graduated=self.position.graduation_authenticated,
            seconds_since_graduation=since_grad,
            postgrad_demand_confirmed=bool(postgrad_demand_confirmed),
        )
        reason=exit_decision(observation)
        if reason is not None and self.position.exit_reason is None:
            self.position.exit_reason=reason
            self.position.exit_intended_at=int(now)
        self.history.append(dict(
            event="mark",time=int(now),proceeds=int(executable_proceeds_quote_units),
            return_bps=int(ret),demand_score=int(demand_score),exit_reason=reason,
        ))
        return dict(return_bps=int(ret),peak_return_bps=int(self.position.peak_return_bps),exit_reason=reason)

    def settle(self, executable_proceeds_quote_units: int, now: int, *, evidence=None):
        if self.position is None:
            raise ValueError("no_open_position")
        if self.position.exit_reason is None:
            raise ValueError("exit_not_intended")
        if executable_proceeds_quote_units < 0:
            raise ValueError("invalid_settlement")
        if self.book is not None:
            self.book.transition(self.lifecycle_id,"settled",int(now),
                                 amount=int(executable_proceeds_quote_units),
                                 evidence=dict(exit_reason=self.position.exit_reason,execution=evidence))
        self.position.realized_quote_units=int(executable_proceeds_quote_units)-self.position.basis_quote_units
        self.position.closed_at=int(now)
        closed=asdict(self.position)
        self.history.append(dict(event="settled",position=closed))
        self.position=None
        return closed

    def snapshot(self):
        return dict(
            strategy_id=STRATEGY_ID,
            lifecycle_id=self.lifecycle_id,
            capital_authority=False,
            reservation=None if self.reservation is None else dict(self.reservation),
            position=None if self.position is None else asdict(self.position),
            history=list(self.history),
        )
