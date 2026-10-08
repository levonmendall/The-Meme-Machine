"""Paper lifecycle state for pump-acceleration-independent-v1.

This is intentionally not a capital allocator.  A caller must obtain a budget from
shared portfolio governance first.  The lifecycle then tracks only this strategy's
reservation/fill/gradation/exit state and rejects qualifications from every other
strategy namespace.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from .pump_acceleration_strategy import (
    POLICY, STRATEGY_ID, ExitObservation, Qualification, continuation_eligible,
    exit_decision, mode_max_hold_s, policy_hash,
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
    realized_quote_units: int = 0
    partial_harvest_taken: bool = False
    demand_deterioration_streak: int = 0
    hold_extensions_used: int = 0
    closed_at: int | None = None
    original_basis: int = 0
    original_quantity: int = 0
    first_tail_crossed_at: int | None = None
    bridged: bool = False
    bridged_at: int | None = None
    bridge_deadline: int | None = None
    scale_committed: bool = False
    scale_request: str | None = None
    scale_cost: int = 0
    scale_quantity: int = 0


class PumpAccelerationPaperLifecycle:
    """Independent native lifecycle; funding follows the selected authority."""

    def __init__(self, *, book=None, lifecycle_id=None, entry_evidence=None):
        self.reservation=None
        self.position=None
        self.history=[]
        self.book=book
        self.lifecycle_id=lifecycle_id
        self.entry_evidence=entry_evidence or {}
        self.sleeve=None
        if book is not None:
            from meme_machine.runtime.directional_sleeve import open_sleeve
            self.sleeve=open_sleeve('pump',book.identity['initial'])
        if book is not None and not lifecycle_id:
            raise ValueError("durable_lifecycle_id_required")

    def reserve(self, qualification: Qualification, budget_quote_units: int, now: int):
        if qualification.strategy_id != STRATEGY_ID:
            raise ValueError("foreign_strategy_qualification")
        if qualification.policy_hash != policy_hash():
            raise ValueError("stale_strategy_policy_qualification")
        if not qualification.qualified:
            raise ValueError("unqualified_strategy_signal")
        if budget_quote_units <= 0:
            raise ValueError("invalid_budget")
        if self.reservation is not None or self.position is not None:
            raise ValueError("lifecycle_already_active")
        if self.sleeve is not None:
            self.sleeve.reserve(self.lifecycle_id,strategy=STRATEGY_ID,
                amount=int(budget_quote_units),at=int(now),asset=qualification.mint,
                funding_evidence=dict(qualification=asdict(qualification),snapshot=self.entry_evidence))
        if self.book is not None:
            try:
                self.book.reserve(self.lifecycle_id,int(budget_quote_units),int(now),
                                  dict(qualification=asdict(qualification),snapshot=self.entry_evidence))
            except BaseException:
                if self.sleeve is not None:
                    from meme_machine.runtime.journal import digest
                    replay=self.book.replay()
                    present=self.book.db.execute('SELECT 1 FROM positions WHERE id=?',(self.lifecycle_id,)).fetchone()
                    if not present:
                        self.sleeve.release(self.lifecycle_id,pnl=0,at=int(now),native_verified=replay['verified'],
                            terminal_hash=digest(dict(native_absent=self.lifecycle_id,replay=replay)),cancelled=True)
                    self.sleeve.close();self.sleeve=None
                raise
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
            original_basis=int(cost_quote_units),original_quantity=int(tokens),
        )
        if self.book is not None:
            from meme_machine.runtime.directional_continuation import native_sync
            native_sync(self.book,self.sleeve,self.lifecycle_id)
        self.history.append(dict(event="filled",position=asdict(self.position)))
        self.reservation=None
        return asdict(self.position)

    def cancel(self, reason: str, now: int):
        if self.reservation is None:
            raise ValueError("no_active_reservation")
        if self.book is not None:
            self.book.transition(self.lifecycle_id,"cancelled",int(now),
                                 evidence=dict(reason=str(reason)))
            if self.sleeve is not None:
                from meme_machine.runtime.directional_sleeve import native_terminal
                self.book.replay()
                native_terminal(self.sleeve,self.lifecycle_id,self.book._load(self.lifecycle_id),int(now),verified=True)
                self.sleeve.close();self.sleeve=None
        self.history.append(dict(event="cancelled",reason=str(reason),time=int(now),reservation=dict(self.reservation)))
        self.reservation=None

    def authenticate_graduation(self, now: int, authenticated: bool):
        if self.position is None:
            raise ValueError("no_open_position")
        if self.position.surface != "pump.fun":
            return asdict(self.position)
        if not authenticated:
            raise ValueError("unauthenticated_graduation")
        if self.book is not None:
            self.book.transition(self.lifecycle_id,'strategy_graduation',int(now),
                                 evidence=dict(authenticated=True,surface='pumpswap'))
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
        if self.position.scale_committed:
            from meme_machine.runtime.directional_continuation import reference_return
            ret=reference_return(executable_proceeds_quote_units,self.position.tokens,
                self.position.original_basis,self.position.original_quantity)
        self.position.peak_return_bps=max(self.position.peak_return_bps,ret)
        if self.position.peak_return_bps>=10000 and self.position.first_tail_crossed_at is None:
            self.position.first_tail_crossed_at=int(now)
        if int(demand_score) < int(POLICY.demand_exit_score) and ret > 0:
            self.position.demand_deterioration_streak+=1
        else:
            self.position.demand_deterioration_streak=0
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
            demand_deterioration_streak=int(self.position.demand_deterioration_streak),
            hold_extensions_used=int(self.position.hold_extensions_used),
            executable=True,
        )
        base=mode_max_hold_s(self.position.mode)
        age=int(now)-int(self.position.opened_at)
        hold_extended=False
        if (
            age >= base*(1+self.position.hold_extensions_used)
            and self.position.hold_extensions_used < POLICY.max_hold_extensions
            and continuation_eligible(observation)
        ):
            self.position.hold_extensions_used+=1
            hold_extended=True
            observation=ExitObservation(
                **{
                    **observation.__dict__,
                    "hold_extensions_used":int(self.position.hold_extensions_used),
                }
            )
            self.history.append(dict(
                event="hold_extended",time=int(now),mode=self.position.mode,
                extension_number=int(self.position.hold_extensions_used),
                prior_deadline_seconds=base*int(self.position.hold_extensions_used),
                next_deadline_seconds=base*(1+int(self.position.hold_extensions_used)),
                return_bps=int(ret),demand_score=int(demand_score),
            ))
        reason=exit_decision(observation)
        if reason=='timeout' and self.position.exit_reason is None:
            from meme_machine.runtime.directional_continuation import bridge_state
            state=dict(opened_at=self.position.opened_at,
                realization_taken=self.position.partial_harvest_taken,
                high_water_bps=self.position.peak_return_bps,
                bridged=self.position.bridged,bridged_at=self.position.bridged_at,
                bridge_deadline=self.position.bridge_deadline)
            updated,expired=bridge_state(state,(evidence or {}).get('continuation',{}),
                now=int(now),ordinary_expired=True)
            for field in ('bridged','bridged_at','bridge_deadline'):
                if field in updated:setattr(self.position,field,updated[field])
            if not expired:reason=None
        if reason is not None and self.position.exit_reason is None:
            self.position.exit_reason=reason
            self.position.exit_intended_at=int(now)
        reason=self.position.exit_reason
        partial_harvest_bps=(
            int(POLICY.first_profit_sell_bps)
            if (
                reason is None
                and not self.position.partial_harvest_taken
                and self.position.tokens > 1
                and ret >= int(POLICY.first_profit_bps)
            )
            else 0
        )
        self.history.append(dict(
            event="mark",time=int(now),proceeds=int(executable_proceeds_quote_units),
            return_bps=int(ret),demand_score=int(demand_score),exit_reason=reason,
            demand_deterioration_streak=int(self.position.demand_deterioration_streak),
            partial_harvest_bps=partial_harvest_bps,hold_extended=hold_extended,
        ))
        return dict(
            return_bps=int(ret),peak_return_bps=int(self.position.peak_return_bps),
            exit_reason=reason,partial_harvest_bps=partial_harvest_bps,
            hold_extended=hold_extended,
            demand_deterioration_streak=int(self.position.demand_deterioration_streak),
            hold_extensions_used=int(self.position.hold_extensions_used),
        )

    def harvest(self, tokens_sold: int, executable_proceeds_quote_units: int, now: int, *, evidence=None):
        if self.position is None:
            raise ValueError("no_open_position")
        tokens_sold=int(tokens_sold)
        proceeds=int(executable_proceeds_quote_units)
        if tokens_sold <= 0 or tokens_sold >= self.position.tokens:
            raise ValueError("invalid_partial_harvest_size")
        if proceeds < 0:
            raise ValueError("invalid_partial_harvest")
        if self.book is not None:
            self.book.transition(
                self.lifecycle_id,"partial_harvest",int(now),
                amount=proceeds,tokens=tokens_sold,
                evidence=dict(execution=evidence),
            )
        before_tokens=int(self.position.tokens)
        before_basis=int(self.position.basis_quote_units)
        basis_removed=before_basis*tokens_sold//before_tokens
        if basis_removed <= 0:
            raise ValueError("partial_harvest_basis_zero")
        realized=proceeds-basis_removed
        self.position.tokens=before_tokens-tokens_sold
        self.position.basis_quote_units=before_basis-basis_removed
        self.position.realized_quote_units+=realized
        self.position.partial_harvest_taken=True
        if self.book is not None:
            from meme_machine.runtime.directional_continuation import native_sync
            native_sync(self.book,self.sleeve,self.lifecycle_id)
        row=dict(
            event="partial_harvest",time=int(now),tokens_sold=tokens_sold,
            proceeds_quote_units=proceeds,basis_removed_quote_units=basis_removed,
            realized_quote_units=realized,
            cumulative_realized_quote_units=int(self.position.realized_quote_units),
            remaining_tokens=int(self.position.tokens),
            remaining_basis_quote_units=int(self.position.basis_quote_units),
        )
        self.history.append(row)
        return dict(row)

    def add(self,cost,tokens,now,*,request,evidence):
        """One native incremental commit; every original risk/clock field survives."""
        if self.position is None or self.position.exit_reason:
            raise ValueError('scale_position_state')
        if self.position.scale_request==request:
            if (self.position.scale_cost,self.position.scale_quantity)!=(cost,tokens):
                raise ValueError('scale_duplicate_conflict')
            return asdict(self.position)
        if self.position.scale_committed or min(cost,tokens)<=0:
            raise ValueError('scale_position_state')
        if self.book is not None:
            self.book.transition(self.lifecycle_id,'scale_add',int(now),amount=int(cost),tokens=int(tokens),
                evidence=dict(evidence,request=request))
        self.position.tokens+=int(tokens);self.position.basis_quote_units+=int(cost)
        self.position.scale_committed=True;self.position.scale_request=request
        self.position.scale_cost=int(cost);self.position.scale_quantity=int(tokens)
        return asdict(self.position)

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
        self.position.realized_quote_units+=(
            int(executable_proceeds_quote_units)-self.position.basis_quote_units
        )
        if self.sleeve is not None and self.book is not None:
            from meme_machine.runtime.directional_sleeve import native_terminal
            self.book.replay()
            native_terminal(self.sleeve,self.lifecycle_id,self.book._load(self.lifecycle_id),int(now),verified=True)
            self.sleeve.close();self.sleeve=None
        self.position.closed_at=int(now)
        closed=asdict(self.position)
        self.history.append(dict(event="settled",position=closed))
        self.position=None
        return closed

    @classmethod
    def restore(cls, book, lifecycle_id):
        """Replay the canonical journal through the unchanged strategy methods.

        No JSON report is read and no ledger event is written during recovery.
        Committed-but-not-applied in-memory transitions are recovered exactly once.
        """
        import json
        book.replay()
        with book.lock:
            anchor=book._archive()
            saved=(anchor or {}).get('controller_snapshots',{}).get(lifecycle_id)
            records=list((anchor or {}).get('controller_events',{}).get(lifecycle_id,[]))
            records.extend(json.loads(raw) for raw, in book.db.execute(
                'SELECT body FROM journal ORDER BY seq'))
            expected=book._load(lifecycle_id)
        records=[row for row in records if row['position']['id']==lifecycle_id]
        if saved:
            state=saved['state'];life=cls(lifecycle_id=lifecycle_id,entry_evidence=saved['entry_evidence'])
            life.reservation=state['reservation']
            life.position=PaperPosition(**state['position']) if state['position'] else None
            life.history=list(state['history'])
            prior=anchor['positions'][lifecycle_id]
        elif not records or records[0]['action']!='reserved':
            raise ValueError('pump_recovery_reservation_missing')
        else:
            first=records[0]['evidence']
            life=cls(lifecycle_id=lifecycle_id,entry_evidence=first.get('snapshot') or {})
            prior=None
        for row in records:
            action=row['action'];at=row['at'];position=row['position'];evidence=row['evidence']
            if action=='reserved':
                q=dict(evidence['qualification'])
                q['reasons']=tuple(q['reasons']);q['confirmations']=tuple(q['confirmations'])
                life.reserve(Qualification(**q),position['reserved'],at)
            elif action=='filled':
                life.fill(position['tokens'],position['basis'],at,evidence['surface'],
                          evidence=evidence.get('execution'))
            elif action=='cancelled':
                life.cancel(evidence['reason'],at)
            elif action=='strategy_graduation':
                life.authenticate_graduation(at,evidence['authenticated'])
            elif action=='mark':
                life.mark(position['mark'],at,evidence['demand_score'],
                          evidence.get('postgrad_demand_confirmed',False),
                          evidence=evidence.get('execution'))
            elif action=='partial_harvest':
                sold=prior['tokens']-position['tokens']
                removed=prior['basis']-position['basis']
                proceeds=position['realized']-prior['realized']+removed
                life.harvest(sold,proceeds,at,evidence=evidence.get('execution'))
            elif action=='scale_add':
                life.add(position['basis']-prior['basis'],position['tokens']-prior['tokens'],at,
                    request=evidence['request'],evidence=evidence)
            elif action=='settled':
                if life.position.exit_reason!=evidence['exit_reason']:
                    raise ValueError('pump_recovery_exit_thesis_mismatch')
                life.settle(position['proceeds'],at,evidence=evidence.get('execution'))
            else:
                raise ValueError('pump_recovery_unknown_event')
            prior=position
        if expected['status']=='reserved':
            if life.position is not None or life.reservation is None:
                raise ValueError('pump_recovery_reservation_disagreement')
        elif expected['status']=='open':
            if (life.position is None or life.position.tokens!=expected['tokens']
                    or life.position.basis_quote_units!=expected['basis']
                    or life.position.realized_quote_units!=expected['realized']):
                raise ValueError('pump_recovery_inventory_disagreement')
        elif life.position is not None or life.reservation is not None:
            raise ValueError('pump_recovery_terminal_disagreement')
        life.book=book
        return life

    def snapshot(self):
        return dict(
            strategy_id=STRATEGY_ID,
            lifecycle_id=self.lifecycle_id,
            capital_authority=False,
            reservation=None if self.reservation is None else dict(self.reservation),
            position=None if self.position is None else asdict(self.position),
            history=list(self.history),
        )
