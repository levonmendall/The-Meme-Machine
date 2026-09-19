"""Low-impact stage-1 screen for the DLMM small-pool profitability study."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time

from tests import dlmm_profitable_operator_discovery as op

COHORT=Path("DLMM_PROFITABLE_OPERATOR_COHORT_V1.json")
CHECKPOINT=Path("dlmm-small-pool-screen-checkpoint.json")
OUT=Path("dlmm-small-pool-screen.json")
WORKERS=8

# Keep this study below the Meteora 30-RPS ceiling while the original operator review
# may still be active at up to 20 RPS.
op.API_PACER=op._ApiPacer(rps=8)


def _atomic(path,body):
    path=Path(path);tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(body,indent=2,sort_keys=True)+"\n");tmp.replace(path)


def _row(wallet):
    pools,total_positions,portfolio_truncated=op._portfolio(wallet)
    positions,truncated=op._closed_positions(wallet,pools)
    if portfolio_truncated or truncated:
        raise RuntimeError("dlmm_small_pool_screen_truncated")
    path=op._realized_path_metrics(positions)
    pnl=sum(float(p.get("pnl_usd") or 0.0) for p in positions)
    fees=sum(float(p.get("fee_usd") or 0.0) for p in positions)
    return dict(
        wallet=wallet,total_positions_api=total_positions,
        measured_closed_positions=len(positions),
        distinct_pools=len({p.get("pool") for p in positions if p.get("pool")}),
        api_realized_pnl_usd=pnl,fee_income_usd=fees,
        inventory_token_price_pnl_usd=pnl-fees,
        provisional_eligible=(
            len(positions)>=20
            and len({p.get("pool") for p in positions if p.get("pool")})>=3
            and pnl>0
        ),
        positions=positions,**path,
    )


def main():
    cohort=json.loads(COHORT.read_text())
    if cohort.get("kind")!="dlmm_profitable_operator_cohort_v1" or cohort.get("status")!="frozen_pre_pnl":
        raise RuntimeError("dlmm_small_pool_screen_cohort")
    if cohort.get("pnl_data_read_before_freeze") is not False:
        raise RuntimeError("dlmm_small_pool_screen_pnl_leakage")
    wallets=[x["wallet"] for x in cohort.get("wallets") or []]
    rows={}
    if CHECKPOINT.exists():
        body=json.loads(CHECKPOINT.read_text())
        if body.get("cohort_hash")!=cohort.get("cohort_hash"):
            raise RuntimeError("dlmm_small_pool_screen_checkpoint_mismatch")
        rows=body.get("wallets") or {}
    started=int(time.time())
    pending=[w for w in wallets if w not in rows]
    with ThreadPoolExecutor(max_workers=min(WORKERS,max(1,len(pending)))) as executor:
        future_map={executor.submit(_row,w):w for w in pending}
        for future in as_completed(future_map):
            wallet=future_map[future];rows[wallet]=future.result()
            _atomic(CHECKPOINT,dict(
                kind="dlmm_small_pool_screen_checkpoint_v1",
                cohort_hash=cohort.get("cohort_hash"),
                started_at=started,updated_at=int(time.time()),
                completed_wallets=len(rows),wallets=rows,
            ))
            print(json.dumps(dict(
                phase="small_pool_screen",wallet=wallet,completed=len(rows),
                total=len(wallets),eligible=rows[wallet]["provisional_eligible"],
            ),sort_keys=True),flush=True)
    ordered=[rows[w] for w in wallets]
    eligible=[r for r in ordered if r["provisional_eligible"]]
    report=dict(
        kind="dlmm_small_pool_screen_v1",
        status="provisional_screen_complete_final_after_cost_label_pending",
        cohort_hash=cohort.get("cohort_hash"),
        wallet_count=len(ordered),
        provisional_eligible_wallet_count=len(eligible),
        provisional_eligible_wallets=[r["wallet"] for r in eligible],
        criteria=dict(
            min_closed_positions=20,min_distinct_pools=3,
            require_api_realized_pnl_usd_positive=True,
            final_after_network_cost_label_pending=True,
        ),
        meteora_request_cap_rps=8,
        wallets=ordered,
    )
    _atomic(OUT,report)
    print(json.dumps(dict(
        wallets=len(ordered),provisional_eligible=len(eligible),
        positions=sum(r["measured_closed_positions"] for r in ordered),
    ),sort_keys=True))


if __name__=="__main__":
    main()
