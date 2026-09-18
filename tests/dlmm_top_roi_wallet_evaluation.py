"""Broader Solana DLMM top-ROI wallet evaluation.

Phase A samples active LP wallets without any PnL reads.
Phase B analyzes only a committed frozen cohort. It reports raw ROI and a
preregistered robust ROI ranking with minimum history requirements.

No strategy freeze, signing, submission, live money, or allocation authority.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import time

from meme_machine import dlmm
from tests import dlmm_alchemy_provider as alchemy_provider
from tests import dlmm_wallet_strategy_discovery as study

DISCOVERY_OUT=Path("dlmm-top-roi-wallet-discovery.json")
ANALYSIS_OUT=Path("dlmm-top-roi-wallet-analysis.json")
DEFAULT_COHORT=Path("DLMM_TOP_ROI_WALLET_COHORT_V1.json")

POOL_SAMPLE=30
POOL_PAGE_SIZE=500
SIGNATURE_LIMIT=96
TX_BODY_TARGET=32
TX_BODY_SCAN_LIMIT=56
TARGET_WALLETS=80
MIN_WALLETS=40
MAX_WALLETS_PER_POOL=4
PER_POOL_RPC_LIMIT=160

DAYS_BACK=120
PORTFOLIO_PAGE_SIZE=50
MAX_PORTFOLIO_PAGES=20
POSITION_PAGE_SIZE=100
MAX_POSITION_PAGES=10

ROBUST_MIN_CLOSED_POSITIONS=20
ROBUST_MIN_DISTINCT_POOLS=3
ROBUST_MIN_PROFITABLE_POSITION_RATE=0.55


def _dec(v,default=0.0):
    try:
        return float(v)
    except (TypeError,ValueError):
        return float(default)


def discover_pools():
    payload=study._json_get("/pools",dict(
        page=1,page_size=POOL_PAGE_SIZE,
        sort_by="fee_tvl_ratio_24h:desc",
        filter_by="is_blacklisted=false && tvl>=50000 && volume_24h>=25000",
    ))
    rows=payload.get("data") if isinstance(payload,dict) else None
    if not isinstance(rows,list):
        raise RuntimeError("dlmm_top_roi_pool_shape")
    pools=[]
    for row in rows:
        if not isinstance(row,dict) or not study._sol_paired(row):
            continue
        address=row.get("address")
        if not isinstance(address,str):
            continue
        pools.append(dict(
            rank=len(pools)+1,address=address,name=row.get("name"),
            tvl=row.get("tvl"),
            volume_24h=(row.get("volume") or {}).get("24h"),
            fee_tvl_ratio_24h=(row.get("fee_tvl_ratio") or {}).get("24h"),
        ))
        if len(pools)>=POOL_SAMPLE:
            break
    if len(pools)<POOL_SAMPLE:
        raise RuntimeError(f"dlmm_top_roi_pool_sample_short:{len(pools)}")
    return pools


def discover_wallets():
    pools=discover_pools()
    pacer=alchemy_provider.AlchemyPacer()
    all_events=[];telemetry=[];all_complete=True
    for pool in pools:
        rpc=alchemy_provider.new_rpc(limit=PER_POOL_RPC_LIMIT,pacer=pacer)
        sigs=rpc.call("getSignaturesForAddress",[
            pool["address"],dict(limit=SIGNATURE_LIMIT,commitment="finalized")
        ],True)
        recent=[s for s in sigs if isinstance(s,dict) and not s.get("err")]
        readable,failures=study._read_recent_transactions(
            rpc,recent,target=TX_BODY_TARGET,scan_limit=TX_BODY_SCAN_LIMIT)
        complete=len(readable)>=TX_BODY_TARGET
        all_complete=all_complete and complete
        found=0
        for sig,tx in readable:
            rows=study._actor_events(tx,pool["address"],pool["rank"],sig)
            all_events.extend(rows);found+=len(rows)
        telemetry.append(dict(
            pool=pool["address"],rank=pool["rank"],
            finalized_signatures_available=len(recent),
            readable_transactions=len(readable),complete=complete,
            unreadable_transactions=failures,
            lp_actor_events=found,
            rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,
            rpc_failures=rpc.failures,rpc_retries=rpc.retries,
            failure_kinds=dict(sorted(rpc.failure_kinds.items())),
        ))

    all_events.sort(key=lambda x:(-x["slot"],x["pool_rank"],
                                  x["signature"] or "",x["execution_order"]))
    action_counts=defaultdict(Counter);pool_sets=defaultdict(set)
    for e in all_events:
        action_counts[e["wallet"]][e["action"]]+=1
        pool_sets[e["wallet"]].add(e["pool"])

    selected=[];seen=set();per_pool=Counter()
    for e in all_events:
        wallet=e["wallet"]
        if wallet in seen or per_pool[e["pool"]]>=MAX_WALLETS_PER_POOL:
            continue
        seen.add(wallet);per_pool[e["pool"]]+=1
        selected.append(dict(
            wallet=wallet,discovery_pool=e["pool"],
            discovery_pool_rank=e["pool_rank"],discovery_slot=e["slot"],
            discovery_signature=e["signature"],discovery_action=e["action"],
            observed_lp_actions=dict(sorted(action_counts[wallet].items())),
            observed_distinct_pools=len(pool_sets[wallet]),
        ))
        if len(selected)>=TARGET_WALLETS:
            break

    status=("candidate_cohort_ready" if all_complete and len(selected)>=MIN_WALLETS
            else "incomplete_provider_evidence" if not all_complete
            else "insufficient_wallets")
    report=dict(
        kind="dlmm_top_roi_wallet_discovery_v1",status=status,
        pnl_data_read=False,allocation_authority=False,strategy_freeze_permitted=False,
        methodology="recent_finalized_lp_actor_sampling_before_any_pnl_read",
        all_pools_complete=all_complete,pool_count=len(pools),
        total_lp_actor_events=len(all_events),wallet_count=len(selected),
        pools=pools,wallets=selected,pool_telemetry=telemetry,
        alchemy_pacer=pacer.telemetry(),
        boundaries=dict(
            pool_sample=POOL_SAMPLE,signature_limit=SIGNATURE_LIMIT,
            readable_transactions_per_pool=TX_BODY_TARGET,
            max_transactions_attempted_per_pool=TX_BODY_SCAN_LIMIT,
            target_wallets=TARGET_WALLETS,minimum_wallets=MIN_WALLETS,
            max_wallets_per_pool=MAX_WALLETS_PER_POOL,
        ),
    )
    DISCOVERY_OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(status=status,pools=len(pools),events=len(all_events),
                          wallets=len(selected)),sort_keys=True))
    if not all_complete:
        raise RuntimeError("dlmm_top_roi_provider_evidence_incomplete")
    if len(selected)<MIN_WALLETS:
        raise RuntimeError("dlmm_top_roi_candidate_cohort_too_small")
    return report


def _portfolio(wallet):
    pools=[];total_positions=None;page=1
    while page<=MAX_PORTFOLIO_PAGES:
        payload=study._json_get("/portfolio",dict(
            user=wallet,page=page,page_size=PORTFOLIO_PAGE_SIZE,days_back=DAYS_BACK
        ),allow_pnl=True)
        rows=payload.get("pools") if isinstance(payload,dict) else None
        if not isinstance(rows,list):
            raise RuntimeError("dlmm_top_roi_portfolio_shape")
        pools.extend(rows)
        if total_positions is None:
            total_positions=int(payload.get("totalPositions") or 0)
        if not payload.get("hasNext"):
            return pools,total_positions,False
        page+=1
    return pools,total_positions,True


def _position_rows(wallet,pools):
    cutoff=int(time.time())-DAYS_BACK*86400
    rows=[];truncated=False
    for pool in pools:
        address=pool.get("poolAddress")
        if not isinstance(address,str):
            continue
        for page in range(1,MAX_POSITION_PAGES+1):
            payload=study._json_get(f"/positions/{address}/pnl",dict(
                user=wallet,status="closed",page=page,page_size=POSITION_PAGE_SIZE
            ),allow_pnl=True)
            positions=payload.get("positions") if isinstance(payload,dict) else None
            if not isinstance(positions,list):
                raise RuntimeError("dlmm_top_roi_position_shape")
            for pos in positions:
                closed=pos.get("closedAt")
                if isinstance(closed,int) and closed>=cutoff:
                    metric=study._position_metrics(pos);metric["pool"]=address
                    rows.append(metric)
            if not payload.get("hasNext"):
                break
        else:
            truncated=True
    return rows,truncated


def _pool_metrics(pools):
    valid=[]
    for p in pools:
        dep=_dec(p.get("totalDeposit"))
        pnl=_dec(p.get("pnlUsd"))
        pnl_sol=_dec(p.get("pnlSol"))
        dep_sol=_dec(p.get("totalDepositSol"))
        if dep<=0:
            roi=None
        else:
            roi=100.0*pnl/dep
        valid.append(dict(
            pool=p.get("poolAddress"),deposit_usd=dep,pnl_usd=pnl,
            pnl_sol=pnl_sol,deposit_sol=dep_sol,roi_pct=roi,
            api_pnl_pct=_dec(p.get("pnlPctChange")),
            api_pnl_sol_pct=_dec(p.get("pnlSolPctChange")),
        ))
    dep=sum(x["deposit_usd"] for x in valid)
    pnl=sum(x["pnl_usd"] for x in valid)
    dep_sol=sum(x["deposit_sol"] for x in valid)
    pnl_sol=sum(x["pnl_sol"] for x in valid)
    roi=(None if dep<=0 else 100.0*pnl/dep)
    sol_roi=(None if dep_sol<=0 else 100.0*pnl_sol/dep_sol)
    prof=[x for x in valid if x["pnl_usd"]>0]
    pool_rois=[x["roi_pct"] for x in valid if x["roi_pct"] is not None]
    return dict(
        total_deposit_usd=dep,total_pnl_usd=pnl,total_pnl_sol=pnl_sol,
        total_deposit_sol=dep_sol,recent_roi_pct=roi,recent_sol_roi_pct=sol_roi,
        profitable_pool_rate=(None if not valid else len(prof)/len(valid)),
        worst_pool_roi_pct=(None if not pool_rois else min(pool_rois)),
        best_pool_roi_pct=(None if not pool_rois else max(pool_rois)),
        pool_count=len(valid),pools=valid,
    )


def _analyze_wallet(wallet):
    pools,total_positions,portfolio_truncated=_portfolio(wallet)
    metrics=_pool_metrics(pools)
    total=study._json_get("/portfolio/total",dict(user=wallet),allow_pnl=True)
    prelim=bool(
        not portfolio_truncated and
        int(total_positions or 0)>=ROBUST_MIN_CLOSED_POSITIONS and
        metrics["pool_count"]>=ROBUST_MIN_DISTINCT_POOLS and
        metrics["total_pnl_usd"]>0 and metrics["total_pnl_sol"]>0 and
        metrics["recent_roi_pct"] is not None
    )
    positions=[];position_truncated=False
    if prelim:
        positions,position_truncated=_position_rows(wallet,pools)
    pnl_rows=[p["pnl_usd"] for p in positions]
    profitable_rate=(None if not pnl_rows else sum(x>0 for x in pnl_rows)/len(pnl_rows))
    pct=[p["pnl_pct"] for p in positions]
    holds=[p["hold_seconds"] for p in positions if p["hold_seconds"] is not None]
    widths=[p["width_bins"] for p in positions if p["width_bins"] is not None]
    positive=[p["pnl_usd"] for p in positions if p["pnl_usd"]>0]
    largest_win_share=(None if metrics["total_pnl_usd"]<=0 or not positive
                       else max(positive)/metrics["total_pnl_usd"])
    robust=bool(
        prelim and not position_truncated and
        profitable_rate is not None and
        profitable_rate>=ROBUST_MIN_PROFITABLE_POSITION_RATE
    )
    return dict(
        wallet=wallet,portfolio_truncated=portfolio_truncated,
        position_history_truncated=position_truncated,
        total_positions_api=int(total_positions or 0),
        all_time_total_pnl_pct_usd=_dec((total or {}).get("totalPnlPctChange")),
        all_time_total_pnl_pct_sol=_dec((total or {}).get("totalPnlSolPctChange")),
        all_time_total_pnl_usd=_dec((total or {}).get("totalPnlUsd")),
        all_time_total_pnl_sol=_dec((total or {}).get("totalPnlSol")),
        **{k:v for k,v in metrics.items() if k!="pools"},
        pool_metrics=metrics["pools"],
        recent_closed_positions_measured=len(positions),
        profitable_position_rate_usd=profitable_rate,
        median_position_pnl_pct=(None if not pct else statistics.median(pct)),
        median_hold_seconds=(None if not holds else statistics.median(holds)),
        median_width_bins=(None if not widths else statistics.median(widths)),
        largest_winning_position_share_of_total_pnl=largest_win_share,
        robust_roi_eligible=robust,
    )


def analyze(path=DEFAULT_COHORT):
    cohort=json.loads(Path(path).read_text())
    if cohort.get("kind")!="dlmm_top_roi_wallet_cohort_v1" or cohort.get("status")!="frozen_pre_pnl":
        raise RuntimeError("dlmm_top_roi_cohort_not_frozen")
    if cohort.get("pnl_data_read_before_freeze") is not False:
        raise RuntimeError("dlmm_top_roi_pnl_leakage")
    wallets=[x["wallet"] for x in cohort.get("wallets") or []]
    if len(wallets)<MIN_WALLETS:
        raise RuntimeError("dlmm_top_roi_cohort_too_small")

    results=[]
    for i,wallet in enumerate(wallets,1):
        row=_analyze_wallet(wallet)
        row["cohort_order"]=i
        results.append(row)

    raw=[r for r in results if r["recent_roi_pct"] is not None]
    raw.sort(key=lambda r:(-r["recent_roi_pct"],-r["total_positions_api"],r["wallet"]))
    robust=[r for r in results if r["robust_roi_eligible"]]
    robust.sort(key=lambda r:(-r["recent_roi_pct"],-r["total_positions_api"],r["wallet"]))
    for i,r in enumerate(raw,1): r["raw_roi_rank"]=i
    for i,r in enumerate(robust,1): r["robust_roi_rank"]=i

    report=dict(
        kind="dlmm_top_roi_wallet_analysis_v1",
        status="evaluation_complete_no_strategy_frozen",
        allocation_authority=False,strategy_freeze_permitted=False,
        cohort_hash=cohort.get("cohort_hash"),wallet_count=len(wallets),
        evaluation_days=DAYS_BACK,
        robust_rule=dict(
            min_closed_positions=ROBUST_MIN_CLOSED_POSITIONS,
            min_distinct_pools=ROBUST_MIN_DISTINCT_POOLS,
            require_total_pnl_usd_positive=True,
            require_total_pnl_sol_positive=True,
            min_profitable_position_rate_usd=ROBUST_MIN_PROFITABLE_POSITION_RATE,
        ),
        robust_wallet_count=len(robust),
        raw_top_20=raw[:20],robust_top_20=robust[:20],
        all_wallets=results,
        interpretation=(
            "Raw ROI is 120-day aggregated PnL divided by deposits. Robust ROI uses "
            "the same ROI but requires the preregistered minimum history, pool diversity, "
            "positive USD and SOL PnL, and >=55% profitable measured positions. "
            "Meteora all-time portfolio PnL percentages are diagnostic only."
        ),
    )
    ANALYSIS_OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(wallets=len(results),robust=len(robust),
                          top=(None if not robust else {
                              "wallet":robust[0]["wallet"],
                              "roi_pct":robust[0]["recent_roi_pct"],
                              "positions":robust[0]["total_positions_api"],
                              "pools":robust[0]["pool_count"],
                          })),sort_keys=True))
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("phase",choices=("discover","analyze"))
    parser.add_argument("--cohort",default=str(DEFAULT_COHORT))
    args=parser.parse_args()
    if args.phase=="discover":
        discover_wallets()
    else:
        analyze(Path(args.cohort))


if __name__=="__main__":
    main()
