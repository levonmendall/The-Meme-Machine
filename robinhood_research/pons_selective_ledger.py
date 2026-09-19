"""Pons-selective-only restart-safe paper ledger with partial exits.

This ledger is physically isolated from the generic Robinhood Paper ledger:
- its own SQLite position table;
- strategy-prefixed immutable record categories;
- required pons-selective experiment namespace;
- partial-exit state exists only here.

It may consume the generic Quote value object because executable quote validation is a
neutral execution primitive. No generic Paper state or behavior is inherited.
"""
import json

from . import BoundaryError
from .evidence import canonical

STRATEGY_NAMESPACE="pons-selective-continuation-v1"
TABLE="pons_selective_paper"
GENESIS_CATEGORY="pons_selective_paper_genesis"
DECISION_CATEGORY="pons_selective_paper_decision"
JOURNAL_CATEGORY="pons_selective_paper_journal"


class SelectivePaper:
    def __init__(self, store, experiment, capital, *, delay=2, natural_policy_hash=None):
        if not str(experiment).startswith(STRATEGY_NAMESPACE):
            raise BoundaryError("pons_selective_experiment_namespace")
        if capital <= 0 or delay < 1:
            raise BoundaryError("invalid_selective_paper_config")
        if not natural_policy_hash:
            raise BoundaryError("selective_policy_hash_required")
        self.store=store
        self.experiment=str(experiment)
        self.delay=int(delay)
        self.natural_policy_hash=str(natural_policy_hash)
        self.store.db.execute(
            """CREATE TABLE IF NOT EXISTS pons_selective_paper(
                   id TEXT PRIMARY KEY, body TEXT NOT NULL)"""
        )
        self.store.put(
            GENESIS_CATEGORY,self.experiment,
            dict(
                capital=int(capital),delay=self.delay,
                authority="pons_selective_continuation_only",
                strategy_namespace=STRATEGY_NAMESPACE,
                shared_allocator=False,
                natural_policy_hash=self.natural_policy_hash,
                position_table=TABLE,
            ),
        )

    def positions(self):
        out=[]
        for body, in self.store.db.execute(
            f"SELECT body FROM {TABLE}"
        ):
            row=json.loads(body)
            if row.get("experiment")==self.experiment:
                out.append(row)
        return out

    def reconcile(self):
        genesis=self.store.get(GENESIS_CATEGORY,self.experiment)["capital"]
        rows=self.positions()
        realized=sum(int(p["pnl"]) for p in rows if p["status"]=="settled")
        committed=sum(int(p["reserved"]) for p in rows if p["status"]!="settled")
        available=int(genesis)+realized-committed
        if available<0:
            raise BoundaryError("selective_paper_capital_invariant")
        return dict(
            genesis=int(genesis),realized=realized,committed=committed,
            available=available,
            open_exposure=sum(
                int(p["tokens"]) for p in rows if p["status"]!="settled"
            ),
        )

    def _get(self,identity):
        row=self.store.db.execute(
            f"SELECT body FROM {TABLE} WHERE id=?",(identity,)
        ).fetchone()
        if not row:
            raise BoundaryError("selective_paper_position_missing")
        p=json.loads(row[0])
        if p.get("experiment")!=self.experiment:
            raise BoundaryError("selective_cross_experiment_authority")
        return p

    def _save(self,p,action,now):
        self.store.put(
            JOURNAL_CATEGORY,f'{p["id"]}:{p["version"]}',
            dict(
                strategy_namespace=STRATEGY_NAMESPACE,
                action=action,at=int(now),position=p,
            ),
        )
        self.store.db.execute(
            f"INSERT OR REPLACE INTO {TABLE} VALUES(?,?)",
            (p["id"],canonical(p)),
        )

    def reserve(
        self,identity,*,market,amount,gas_budget,now,features,kind="natural"
    ):
        if kind!="natural":
            raise BoundaryError("selective_natural_only")
        if (
            features.get("authority")!="frozen_policy_paper"
            or features.get("qualification")!="qualified"
            or features.get("policy_hash")!=self.natural_policy_hash
            or features.get("strategy_namespace")!=STRATEGY_NAMESPACE
            or features.get("shared_allocator") is not False
        ):
            raise BoundaryError("selective_policy_authority_missing")
        if (
            features.get("asof")!=now
            or features.get("market")!=market
            or int(amount)<=0
            or int(gas_budget)<0
        ):
            raise BoundaryError("invalid_selective_paper_decision")

        self.store.db.execute("BEGIN IMMEDIATE")
        try:
            if self.store.db.execute(
                f"SELECT 1 FROM {TABLE} WHERE id=?",(identity,)
            ).fetchone():
                raise BoundaryError("selective_duplicate_reservation")
            if int(amount)+int(gas_budget)>self.reconcile()["available"]:
                raise BoundaryError("selective_capital_exhausted")
            if len(self.positions())>=100:
                raise BoundaryError("selective_position_capacity")
            p=dict(
                id=identity,experiment=self.experiment,
                strategy_namespace=STRATEGY_NAMESPACE,
                market=market,kind=kind,status="reserved",
                reserved=int(amount)+int(gas_budget),amount=int(amount),
                due=int(now)+self.delay,tokens=0,entry_tokens=0,
                cost=0,remaining_cost=0,realized_pnl=0,
                realized_proceeds=0,pending_exit_tokens=None,
                pnl=0,version=0,last_at=int(now),reason=None,
            )
            self.store.put(
                DECISION_CATEGORY,identity,
                dict(features,strategy_namespace=STRATEGY_NAMESPACE),
            )
            self._save(p,"reserve",now)
            self.store.db.execute("COMMIT")
        except Exception:
            self.store.db.execute("ROLLBACK")
            raise
        return p

    def advance(
        self,identity,*,now,action,quote=None,transition=None,
        finality_ledger=None,cancel_reason=None,exit_tokens=None,
    ):
        self.store.db.execute("BEGIN IMMEDIATE")
        try:
            p=self._get(identity)
            now=int(now)
            if now<int(p["last_at"]):
                raise BoundaryError("selective_paper_time_regression")

            if action=="entry":
                if p["status"]!="reserved" or now<int(p["due"]):
                    raise BoundaryError("selective_entry_not_due")
                quote.check(
                    now,p["market"],"buy",p["amount"],p["kind"],
                    finality_ledger=finality_ledger,
                )
                if quote.stamp.event_at<int(p["due"]):
                    raise BoundaryError("selective_pre_delay_quote")
                cost=int(p["amount"])+int(quote.gas_quote)
                if cost>int(p["reserved"]):
                    raise BoundaryError("selective_entry_exceeds_reservation")
                p.update(
                    tokens=int(quote.amount_out),entry_tokens=int(quote.amount_out),
                    cost=cost,remaining_cost=cost,realized_pnl=0,
                    realized_proceeds=0,pending_exit_tokens=None,status="open",
                )

            elif action=="exit_intent":
                if p["status"]!="open":
                    raise BoundaryError("selective_position_not_open")
                requested=(
                    int(p["tokens"]) if exit_tokens is None else int(exit_tokens)
                )
                if requested<=0 or requested>int(p["tokens"]):
                    raise BoundaryError("invalid_selective_partial_exit_amount")
                p.update(
                    status="exit_pending",due=now+self.delay,
                    pending_exit_tokens=requested,
                )

            elif action=="exit":
                if p["status"]!="exit_pending" or now<int(p["due"]):
                    raise BoundaryError("selective_exit_not_due")
                amount=int(p.get("pending_exit_tokens") or 0)
                if amount<=0 or amount>int(p["tokens"]):
                    raise BoundaryError("invalid_selective_partial_exit_amount")
                try:
                    quote.check(
                        now,p["market"],"sell",amount,p["kind"],
                        finality_ledger=finality_ledger,
                    )
                    if quote.stamp.event_at<int(p["due"]):
                        raise BoundaryError("selective_pre_delay_quote")
                except BoundaryError as exc:
                    if p.get("reason")==str(exc):
                        self.store.db.execute("COMMIT")
                        return p
                    p["reason"]=str(exc)
                else:
                    net=int(quote.amount_out)-int(quote.gas_quote)
                    if net<0:
                        raise BoundaryError("selective_exit_gas_exceeds_proceeds")
                    tokens_before=int(p["tokens"])
                    remaining_cost=int(p["remaining_cost"])
                    sold_cost=(
                        remaining_cost
                        if amount==tokens_before
                        else remaining_cost*amount//tokens_before
                    )
                    p["tokens"]=tokens_before-amount
                    p["remaining_cost"]=remaining_cost-sold_cost
                    p["realized_proceeds"]=int(p["realized_proceeds"])+net
                    p["realized_pnl"]=int(p["realized_pnl"])+net-sold_cost
                    p["pnl"]=p["realized_pnl"]
                    p["reason"]=None
                    p["pending_exit_tokens"]=None
                    if p["tokens"]==0:
                        p.update(
                            status="settled",reserved=0,remaining_cost=0
                        )
                    else:
                        p["status"]="open"

            elif action=="cancel":
                if p["status"]!="reserved" or not cancel_reason:
                    raise BoundaryError("invalid_selective_reservation_cancel")
                p.update(
                    status="settled",reserved=0,reason=str(cancel_reason),tokens=0
                )

            elif action=="transition":
                if (
                    p["status"] not in ("open","exit_pending")
                    or not transition
                    or transition.get("previous_market")!=p["market"]
                ):
                    raise BoundaryError("invalid_selective_pool_transition")
                proof=self.store.get("graduation",transition["proof_hash"])
                if proof!=transition:
                    raise BoundaryError("unproven_selective_pool_transition")
                p["market"]=transition["market"]

            else:
                raise BoundaryError("unsupported_selective_paper_action")

            p["version"]+=1
            p["last_at"]=now
            self._save(p,action,now)
            self.reconcile()
            self.store.db.execute("COMMIT")
            return p
        except Exception:
            self.store.db.execute("ROLLBACK")
            raise
