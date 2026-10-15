"""Native journal boundaries for the ported shared USD portfolio.

This is accounting plumbing. Native strategy decisions, quantities, quotes and
clocks remain authoritative. An entry obtains USD capital before its journal
commit; restart proves every retained delivery against that same journal.
"""
from decimal import Decimal
from meme_machine.exact_money import exact, proportional_basis_release
import json
import os
import time

from meme_machine.portfolio_accounting import PortfolioIntegrityError
from meme_machine.runtime.portfolio import NativePortfolio
from meme_machine.runtime.usd_valuation import utc


class NativeBoundary:
    def __init__(self, database, lane, book, *, value_reader):
        self.client = NativePortfolio(database, lane)
        self.lane, self.book, self.value_reader = lane, book, value_reader
        self.prepared = []

    def journal_hashes(self):
        if self.lane in ("pump", "pons") and hasattr(self.book, "identity"):
            if self.book.replay()['verified'] is not True:raise PortfolioIntegrityError('native_replay_required')
            return {row[0] for row in self.book.db.execute("SELECT hash FROM journal")}
        if self.lane == "pons":
            self.book.positions()
            from meme_machine.lanes.pons.pons_selective_ledger import JOURNAL_CATEGORY
            return {row[0] for row in self.book.store.db.execute("SELECT hash FROM records WHERE category=?",(JOURNAL_CATEGORY,))}
        if self.lane == "meteora":
            self.book.reconcile()
            from contextlib import closing
            with closing(self.book.connect()) as db:
                return {row[0] for row in db.execute("SELECT hash FROM events")}
        self.book.reconcile()
        return {row[0] for row in self.book.db.execute("SELECT hash FROM ramses_strategy_journal")}

    def recover(self):
        hashes = self.journal_hashes()
        for native, event in self.client.pending():
            if event.native_journal_hash in hashes:
                self.client.committed(native, event_key=event.native_event_id, journal_hash=event.native_journal_hash)
            else:
                self._abort(native,event)

    def _abort(self, native, event):
        if getattr(self.client,'shared',False):
            return self.client.abort(native,event)
        # No lane writer exists concurrently with its own recovery. The verified
        # absence of this exact native event proves that its fill never committed.
        with self.client.writer() as (account, producer):
            account.db.execute("DELETE FROM portfolio_native_pending WHERE lane=? AND native=?", (self.lane,native))
            rid = producer._reservation_id(self.lane,event.data.get("native_reservation_id",event.native_lifecycle_id))
            held = rid in account.snapshot()["reservations"]
        if held and event.kind in ("reserve","rebalance"):
            self.client.deliver(native,event_key="abort:"+event.native_journal_hash, journal_hash=event.native_journal_hash,
                kind="release",at=event.at,data={"native_reservation_id":event.data.get("native_reservation_id",event.native_lifecycle_id)})

    def flush(self):
        hashes = self.journal_hashes()
        for native, event in self.prepared:
            if event.native_journal_hash not in hashes:
                raise PortfolioIntegrityError("native_commit_not_durable")
            self.client.committed(native,event_key=event.native_event_id,journal_hash=event.native_journal_hash)
        self.prepared.clear()
        from meme_machine.runtime.status import update
        update('MANAGING',reconciled=True,accounting_reconciled=True)

    @exact
    def record(self, native, action, position, previous, *, at, checksum, quote=None, data=None):
        if action not in ('reserved','reserve','filled','entry','open','partial_harvest','exit','exit_intent','settled','settle','cancelled','cancel','scale_add','mark','monitor','liquidity_writeoff','writeoff'):
            return
        data = data or {}
        # Cancelling an unfilled intent and declaring a missing mark consume no
        # market value. Provider outages must not strand their capital holds.
        unavailable=(action=='exit_intent' or (action in ('mark','monitor') and
            isinstance(data.get('observation'),dict) and data['observation'].get('after_cost_return_bps') is None))
        needs_value = action not in ('cancelled','cancel') and not unavailable and not (self.lane=='ramses' and action in ('mark','monitor'))
        value = self.value_reader(at) if needs_value else None
        native_at=at
        valuation_acquired_at=max(native_at,int(time.time())) if value is not None else None
        # USD publication uses its acquisition clock; native strategy/journal
        # time and immutable observation/expiry evidence are preserved.
        if value is not None:at=valuation_acquired_at
        def validate_value():
            if value is not None:
                freshness_at=max(native_at,valuation_acquired_at,int(time.time()))
                value.amount(0,freshness_at)
        validate_value()
        amount = lambda raw: format(value.amount(int(raw),valuation_acquired_at),"f")
        evidence = value.evidence(valuation_acquired_at) if value is not None else None
        facts = None
        kind = None
        aliases = {"reserved":"reserve", "filled":"enter", "partial_harvest":"harvest", "settled":"settle", "cancelled":"release", "entry":"enter", "open":"enter", "cancel":"release"}
        kind = aliases.get(action, action)
        if kind == "reserve":
            raw = position.get("reserved",data.get("amount"))
            facts = {"amount": amount(raw)}
        elif kind == "release":
            facts = {}
        elif kind == "enter":
            raw = position.get("basis",position.get("remaining_cost",position.get("reserved",data.get("capital"))))
            if self.lane=='meteora':raw=position['basis']+position['entry_cost']
            asset = position.get("market", position.get("pool", (data.get("entry_state") or {}).get("pool", "native-asset")))
            # Qualified native market identity is public, never an endpoint or key.
            asset = str(asset).replace("/", "-")[:100]
            facts = {"asset":asset,"basis":amount(raw),"fee":"0","strategy_id":self.book.identity["lane"] if isinstance(getattr(self.book,"identity",None),dict) else self.lane}
        elif kind in ("harvest","exit","settle","liquidity_writeoff","writeoff"):
            with self.client.writer() as (account, producer):
                alias = self.client._alias(account,native)
                p = account.snapshot()["positions"].get(producer._canonical_lifecycle(self.lane,alias))
                if p is None: raise PortfolioIntegrityError("USD_entry_missing_before_native_exit")
                remaining = p["remaining_basis"]
            terminal = position.get("status") in ("settled","written_off") or kind in ("settle","writeoff","liquidity_writeoff")
            old_basis = (previous or {}).get("basis", (previous or {}).get("remaining_cost", (previous or {}).get("reserved",0)))
            new_basis = position.get("basis",position.get("remaining_cost",0))
            if kind == "exit" and position.get("reason") is not None:return
            released = remaining if terminal else proportional_basis_release(remaining, old_basis-new_basis, old_basis)
            if self.lane == "meteora":
                mark = data.get("mark") or {}
                proceeds = 0 if kind == "writeoff" else mark["ending_sol_lamports"]-position.get("exit_cost",0)
            elif self.lane == "ramses":
                proceeds = int((previous or {})["reserved"])+int(position["realized"])
            elif quote is not None:
                proceeds = int(quote["amount_out"])-int(quote["gas_quote"])
            elif terminal:
                proceeds = position.get("proceeds",0)
            else:
                proceeds = position["realized"]-(previous or {})["realized"]+old_basis-new_basis
            kind = "settle" if terminal else "harvest"
            facts = {"gross_proceeds":amount(proceeds),"fee":"0"}
            if terminal:facts["exit_reason"] = "native-exit"
            else:facts["basis_released"] = format(released,"f")
        elif kind == "scale_add":
            raw = position.get("scale_cost") or int(quote["amount_in"])+int(quote["gas_quote"])
            reservation = "add:"+checksum
            with self.client.writer() as (account,producer):
                alias=self.client._alias(account,native)
                original=account.snapshot()['positions'][producer._canonical_lifecycle(self.lane,alias)]['capital']
                equity=account.sleeve_equity(self.lane)
                added=Decimal(amount(raw))
                if added>equity*Decimal('.025') or added>original*Decimal('.5') or original+added>equity*Decimal('.075'):
                    raise PortfolioIntegrityError('increment_exceeds_realized_USD_lifecycle_limit')
            kind = "rebalance"
            facts = {"basis_released":"0","gross_proceeds":"0","basis_added":amount(raw),"fee":"0","native_reservation_id":reservation}
        elif kind in ("mark","monitor","exit_intent"):
            if self.lane == "ramses" or unavailable:
                # The controller's token inventory/fee marks stay native until
                # a verified liquidation quote exists; no invented USD mark.
                facts = {"state":"UNAVAILABLE"}
            else:
                raw = position.get("mark")
                if isinstance(raw,dict): raw = raw.get("executable_net",raw.get("ending_sol_lamports",0)-position.get("exit_cost",0))
                if self.lane == "meteora": raw = data["mark"]["ending_sol_lamports"]-position["exit_cost"]
                facts = {"state":"CURRENT","net_liquidation_value":amount(raw)}
            kind = "mark"
        else:
            return
        if facts is None:return
        if self.lane in ('pump','pons'):
            risk=data.get('risk_state') or data.get('position_state') or position.get('controller_state') or {}
            observed=data.get('observation') or {}
            last=risk.get('last_action') or risk.get('pending_action') or {}
            reason=risk.get('exit_reason') or last.get('reason') or risk.get('recovery_exit_reason') or data.get('exit_reason')
            pending=(position.get('status')=='exit_pending' or
                last.get('action') in ('full_exit','partial_exit') or bool(risk.get('exit_reason')) or bool(risk.get('pending_action')))
            current=not unavailable and bool(risk) and observed.get('evidence_current',True) is True
            state=('EXIT_PENDING' if pending else 'DEGRADED_PROTECTION' if not current else 'MONITORING')
            last_action=last.get('action') or ('full_exit' if risk.get('exit_reason') else
                ('full_exit' if last.get('exit_tokens')==position.get('tokens') else 'partial_exit') if risk.get('pending_action') else
                'hold' if kind=='mark' else action)
            protective=reason in ('risk','risk_stop','hard_stop','runner_trail','runner_trailing_stop',
                'pregraduation_runner_trailing_stop','high_water_trailing_stop',
                'trailing_momentum_exit','tail_gain_giveback','tail_gain_giveback_exit','invalid_exit_liquidity','creator_distribution')
            facts['protection']=dict(state=state,observed_at=utc(native_at),
                evidence_current=current,pending_exit=pending,last_reason=reason,
                last_action=last_action,decision_kind=('PROTECTIVE_EXIT' if protective else 'STRATEGY_EXIT') if pending and reason else None,
                high_water_bps=risk.get('high_water_bps',risk.get('high_water')),
                remaining_quantity=position.get('tokens'))
            opened=risk.get('opened_at',native_at if kind=='enter' else None)
            if opened is not None:facts['protection']['entered_at']=utc(opened)
            observed_return=observed.get('after_cost_return_bps')
            if (observed_return is None and current and kind=='mark'
                    and not position.get('scale_request') and type(position.get('mark')) is int):
                basis=position.get('basis',position.get('remaining_cost'))
                if type(basis) is int and basis>0:
                    observed_return=(position['mark']-basis)*10000//basis
            if current and type(observed_return) is int:
                facts['protection']['observed_return_bps']=observed_return
                if pending and reason:
                    facts['protection']['actionable_at']=utc(native_at)
                    facts['protection']['trigger_return_bps']=observed_return
            if kind in ('harvest','settle'):
                released_native=old_basis-new_basis
                if released_native>0:
                    facts['protection']['executed_return_bps']=(proceeds-released_native)*10000//released_native
                    facts['protection']['execution_at']=utc(native_at)
                if kind=='settle':
                    facts['protection'].update(pending_exit=False,state='PROTECTIVE_EXIT' if protective else 'STRATEGY_EXIT',
                        decision_kind='PROTECTIVE_EXIT' if protective else 'STRATEGY_EXIT')
        if kind in ('enter','harvest','settle','rebalance'):
            cost=0
            if quote:cost=int(quote.get('gas_quote',0))+int(quote.get('fee_quote',0))
            elif isinstance(data.get('execution'),dict):cost=int(data['execution'].get('gas',0))
            if self.lane=='meteora':
                cost=int(position.get('entry_cost',0)) if kind=='enter' else int(position.get('exit_cost',0))+int((data.get('mark') or {}).get('unwind_cost_lamports',0))
            if self.lane=='ramses' and kind=='settle':cost=int((position.get('outcome') or {}).get('execution_cost_quote',0))
            facts['included_fee']=amount(cost)
        add_reserved=False
        try:
            validate_value()
            if action=='scale_add' and not getattr(self.client,'shared',False):
                self.client.deliver(native,event_key="add-reserve:"+checksum,journal_hash=checksum,
                    kind="rebalance_reserve",at=utc(native_at),data={"amount":amount(raw),"native_reservation_id":reservation})
                add_reserved=True
                validate_value()
            extra={}
            if getattr(self.client,'shared',False):
                units=position.get('basis',position.get('remaining_cost',position.get('reserved',0)))
                if action=='scale_add':units=raw
                extra['metadata']=dict(native_basis_units=int(units))
            event = self.client.prepare(native,event_key="native:"+checksum,journal_hash=checksum,kind=kind,at=utc(at),data=facts,
                value_evidence=evidence if kind not in ("reserve","release") and facts.get("state")!="UNAVAILABLE" else None,**extra)
        except BaseException:
            if add_reserved:
                self.client.deliver(native,event_key="failed-add-release:"+checksum,journal_hash=checksum,
                    kind="release",at=utc(at),data={"native_reservation_id":reservation})
            raise
        self.prepared.append((native,event))


def attach(book,lane):
    database = os.environ.get("MM_PORTFOLIO_ACCOUNTING_DB")
    if not database:return None
    from meme_machine.runtime.usd_valuation import NativeValueReader,native_reader
    # Pons Current and Survivor account in the same native unit. When overlap
    # is installed, consume the same validated per-process reader warmed by
    # their due native turns; never move a native journal across threads.
    reader=(native_reader('pons') if lane=='pons' and
        os.environ.get('MM_PONS_USD_ACQUISITION_OVERLAP')=='1' else NativeValueReader(lane,book))
    boundary = NativeBoundary(database,lane,book,value_reader=reader)
    boundary.recover()
    return boundary
