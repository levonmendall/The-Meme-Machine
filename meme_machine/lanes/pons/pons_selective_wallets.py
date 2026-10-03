"""Independent point-in-time wallet skill ledger for Pons Selective Continuation v1.

This ledger is deliberately strategy-local.  It does not read Solana skilled-wallet
sets, continuation-v1 cohorts, Ramses state, or any shared strategy score.  Only
completed Pons wallet trades explicitly written to this namespace can contribute to
the wallet-convergence overlay.
"""
from collections import defaultdict

from . import BoundaryError
from .evidence import Store

NAMESPACE="pons-selective-continuation-v1"


class WalletSkillBook:
    def __init__(self, path):
        self.store=Store(path,max_records=50_000)

    def close(self):
        self.store.close()

    def record_completed_trade(
        self, *, trade_id, group, token, entry_at, exit_at,
        realized_after_cost_pnl, observed_at, candidate_related=False,
    ):
        entry_at=int(entry_at);exit_at=int(exit_at);observed_at=int(observed_at)
        pnl=int(realized_after_cost_pnl)
        group=str(group).lower();token=str(token).lower()
        if not trade_id or not group or not token:
            raise BoundaryError("invalid_wallet_skill_identity")
        if entry_at<0 or exit_at<entry_at or observed_at<exit_at:
            raise BoundaryError("invalid_wallet_skill_time")
        row=dict(
            namespace=NAMESPACE,trade_id=str(trade_id),group=group,token=token,
            entry_at=entry_at,exit_at=exit_at,observed_at=observed_at,
            realized_after_cost_pnl=pnl,
            candidate_related=bool(candidate_related),
            complete=True,
        )
        self.store.put("pons_selective_wallet_trade",str(trade_id),row)
        return row

    def profiles(self, *, asof):
        asof=int(asof)
        rows=[]
        for body, in self.store.db.execute(
            "SELECT body FROM records WHERE category='pons_selective_wallet_trade'"
        ):
            import json
            row=json.loads(body)
            if row.get("namespace")!=NAMESPACE:
                raise BoundaryError("cross_strategy_wallet_skill")
            if int(row["observed_at"])<=asof and int(row["exit_at"])<=asof:
                rows.append(row)

        by_group=defaultdict(list)
        for row in rows:
            by_group[row["group"]].append(row)
        out=[]
        for group,group_rows in sorted(by_group.items()):
            token_pnl=defaultdict(int)
            total=0
            related=False
            latest=0
            for row in group_rows:
                pnl=int(row["realized_after_cost_pnl"])
                total+=pnl
                token_pnl[row["token"]]+=pnl
                related=related or bool(row.get("candidate_related"))
                latest=max(latest,int(row["observed_at"]))
            out.append(dict(
                group=group,complete=True,history_asof=latest,
                completed_trades=len(group_rows),
                realized_after_cost_pnl=total,
                profitable_tokens=sum(value>0 for value in token_pnl.values()),
                candidate_related=related,
                namespace=NAMESPACE,
            ))
        return out
