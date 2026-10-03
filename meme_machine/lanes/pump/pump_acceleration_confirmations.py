"""Point-in-time confirmation evidence for pump-acceleration-independent-v1.

Historical skilled-wallet evidence comes from the already-frozen Solana alpha cohort.
Funding groups are honored only when explicitly present in the source evidence; no
relationship is invented. Creator quality is built prospectively from launch and
graduation events observed before each decision.

This module supplies confirmation inputs only. It has no strategy, sizing, allocator,
order, signing, or submission authority.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .pump_acceleration_strategy import (
    CreatorQualityRecord,
    WalletSkillRecord,
    creator_confirmation,
    skilled_wallet_convergence,
)


DEFAULT_COHORT=Path("tests/fixtures/solana_alpha_wallet_cohort_frozen.json")
DEFAULT_CONTRACT=Path("tests/fixtures/solana_skilled_wallet_prospective_contract.json")


def _iso_epoch(value):
    return int(datetime.fromisoformat(str(value).replace("Z","+00:00")).timestamp())


@dataclass(frozen=True)
class FrozenWalletProfile:
    wallet: str
    as_of: int
    total_trades: int
    profitable_trades: int
    positive_realized_return: bool
    funding_group: str | None = None
    cluster: str | None = None


class ConfirmationBook:
    def __init__(self, cohort, frozen_at):
        self.cohort_source_run=cohort.get("source_run")
        self.frozen_at=int(frozen_at)
        self.wallets={}
        self.creator_launches={}
        self.mint_creator={}
        self.explicit_funding_groups=0
        for row in cohort.get("cohort") or []:
            wallet=str(row.get("wallet") or "")
            if not wallet:
                continue
            total=max(0,int(row.get("tokens_traded_30d") or 0))
            win=float(row.get("win_rate_30d") or 0.0)
            profitable=max(0,min(total,int(round(win*total))))
            funding=row.get("funding_group")
            funding=str(funding) if funding else None
            if funding:
                self.explicit_funding_groups+=1
            cluster=str(row.get("cluster") or wallet)
            self.wallets[wallet]=FrozenWalletProfile(
                wallet=wallet,as_of=self.frozen_at,total_trades=total,
                profitable_trades=profitable,
                # The source ROI unit is not reinterpreted here. The frozen strategy
                # only requires proof of positive historical realized return, so
                # preserve the sign rather than manufacture a basis-point magnitude.
                positive_realized_return=float(row.get("roi_30d") or 0.0)>0.0,
                funding_group=funding,cluster=cluster,
            )

    @classmethod
    def from_files(cls, cohort_path=DEFAULT_COHORT, contract_path=DEFAULT_CONTRACT):
        cohort=json.loads(Path(cohort_path).read_text())
        contract=json.loads(Path(contract_path).read_text())
        return cls(cohort,_iso_epoch(contract["frozen_at_utc"]))

    def status(self):
        return dict(
            source="frozen_sol_skilled_wallet_prospective_v1",
            cohort_source_run=self.cohort_source_run,
            frozen_at=self.frozen_at,
            wallet_profiles=len(self.wallets),
            explicit_funding_group_rows=self.explicit_funding_groups,
            missing_funding_groups_use_strategy_identity_fallback=True,
            creator_history_source="prospectively_observed_create_and_graduation_events",
            creator_profiles=len(self.creator_launches),
        )

    def observe_creation(self, creation):
        mint=str(creation.get("mint") or "")
        creator=str(creation.get("creator") or "")
        available=int(creation.get("available_time") or creation.get("market_time") or 0)
        if not mint or not creator or available<=0:
            return
        if mint in self.mint_creator:
            return
        self.mint_creator[mint]=creator
        self.creator_launches.setdefault(creator,{})[mint]=dict(
            mint=mint,created_at=available,graduated_at=None)

    def observe_graduation(self, mint, observed_at):
        mint=str(mint)
        creator=self.mint_creator.get(mint)
        if not creator:
            return
        row=(self.creator_launches.get(creator) or {}).get(mint)
        if row is None:
            return
        t=int(observed_at)
        if row["graduated_at"] is None or t<row["graduated_at"]:
            row["graduated_at"]=t

    def funding_group(self, wallet):
        p=self.wallets.get(str(wallet))
        if p is None:
            return None
        return p.funding_group

    def cluster(self, wallet):
        wallet=str(wallet)
        p=self.wallets.get(wallet)
        if p is None:
            return wallet
        return p.funding_group or p.cluster or wallet

    def cluster_map(self, events):
        return {
            str(e.get("wallet")):self.cluster(str(e.get("wallet")))
            for e in events if e.get("wallet")
        }

    def creator_excluded_clusters(self, creator):
        creator=str(creator or "")
        if not creator:
            return set()
        return {self.cluster(creator)}

    def _wallet_record(self, wallet, creator):
        p=self.wallets.get(str(wallet))
        if p is None:
            return None
        creator_cluster=self.cluster(creator) if creator else None
        related=bool(creator and self.cluster(wallet)==creator_cluster)
        return WalletSkillRecord(
            cluster=p.cluster or p.wallet,
            as_of=p.as_of,
            total_trades=p.total_trades,
            profitable_trades=p.profitable_trades,
            realized_return_bps=1 if p.positive_realized_return else 0,
            funding_group=p.funding_group,
            creator_related=related,
        )

    def creator_record(self, creator, observed_at, exclude_mint=None):
        creator=str(creator or "")
        if not creator:
            return None
        t=int(observed_at)
        rows=[]
        for mint,row in (self.creator_launches.get(creator) or {}).items():
            if exclude_mint and mint==exclude_mint:
                continue
            if int(row["created_at"])>=t:
                continue
            rows.append(row)
        if not rows:
            return None
        grads=[
            row for row in rows
            if row.get("graduated_at") is not None and int(row["graduated_at"])<t
        ]
        evidence_times=[int(r["created_at"]) for r in rows]
        evidence_times.extend(int(r["graduated_at"]) for r in grads)
        return CreatorQualityRecord(
            creator=creator,as_of=max(evidence_times),
            launches=len(rows),successful_launches=len(grads),
        )

    def signal_inputs(self, events, observed_at, creator, mint):
        buyers={
            str(e.get("wallet")) for e in events
            if e.get("buy") and e.get("wallet")
        }
        records=[]
        for wallet in sorted(buyers):
            row=self._wallet_record(wallet,creator)
            if row is not None:
                records.append(row)
        skilled=skilled_wallet_convergence(records,int(observed_at))
        creator_row=self.creator_record(creator,int(observed_at),exclude_mint=mint)
        quality=creator_confirmation(creator_row,int(observed_at))
        return dict(
            skilled_wallet_clusters=int(skilled),
            creator_quality_bps=quality,
            creator_history_launches=(0 if creator_row is None else int(creator_row.launches)),
            cluster_map=self.cluster_map(events),
            excluded_clusters=self.creator_excluded_clusters(creator),
            skilled_wallets_observed=len(records),
            explicit_funding_groups_observed=len({
                r.funding_group for r in records if r.funding_group
            }),
        )
