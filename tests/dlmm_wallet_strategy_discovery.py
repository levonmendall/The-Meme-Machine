"""Wallet-derived DLMM strategy research.

Phase A discovers recent LP actors without reading PnL and emits a cohort artifact.
Phase B requires a committed pre-PnL frozen cohort, then analyzes closed-position PnL
and position histories. Neither phase has allocation, signing, or strategy authority.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import statistics
import urllib.parse
import urllib.request

from meme_machine import dlmm, pump
from meme_machine.dlmm_tape import (
    _keys, _ordered_instructions, _un58_data,
    ADD_LIQUIDITY2_IX, ADD_LIQUIDITY_BY_STRATEGY2_IX,
    REMOVE_LIQUIDITY_BY_RANGE2_IX,
)
from tests import dlmm_alchemy_provider as alchemy_provider
from meme_machine.provider import Unavailable

API_BASE="https://dlmm.datapi.meteora.ag"
DISCOVERY_OUT=Path("dlmm-wallet-cohort-discovery.json")
ANALYSIS_OUT=Path("dlmm-wallet-derived-analysis.json")
DEFAULT_COHORT=Path("DLMM_WALLET_COHORT_V1.json")

POOL_SAMPLE=12
POOL_PAGE_SIZE=100
SIGNATURE_LIMIT=64
TX_BODY_LIMIT_PER_POOL=24
TARGET_WALLETS=30
MAX_WALLETS_PER_POOL=5
MIN_FROZEN_WALLETS=12
PER_POOL_RPC_LIMIT=90

PORTFOLIO_DAYS_BACK=120
MAX_POOLS_PER_WALLET=8
MAX_CLOSED_POSITIONS_PER_POOL=100
MAX_HISTORY_POSITIONS_PER_ELIGIBLE_WALLET=20
MIN_CLOSED_POSITIONS=5
MIN_DISTINCT_POOLS=2
MIN_PROFITABLE_POSITION_RATE=0.55

REBALANCE_LIQUIDITY_IX=bytes.fromhex("5c04b0c177b95309")
LP_ACTOR_INSTRUCTIONS={
    ADD_LIQUIDITY2_IX:"add_liquidity2",
    ADD_LIQUIDITY_BY_STRATEGY2_IX:"add_liquidity_by_strategy2",
    REMOVE_LIQUIDITY_BY_RANGE2_IX:"remove_liquidity_by_range2",
    REBALANCE_LIQUIDITY_IX:"rebalance_liquidity",
}


def _json_get(path,params=None,allow_pnl=False):
    if not path.startswith("/"):
        raise ValueError("dlmm_wallet_api_path")
    if not allow_pnl and (path.startswith("/portfolio") or path.startswith("/positions/")):
        raise RuntimeError("dlmm_wallet_discovery_pnl_endpoint_forbidden")
    url=API_BASE+path
    if params:
        url+="?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={
        "Accept":"application/json",
        "User-Agent":"meme-machine-dlmm-wallet-research/1",
    })
    with urllib.request.urlopen(req,timeout=30) as response:
        if response.status!=200:
            raise RuntimeError(f"dlmm_wallet_api_http:{response.status}")
        return json.loads(response.read())


def _dec(value,default="0"):
    try:
        return Decimal(str(default if value is None else value))
    except (InvalidOperation,ValueError,TypeError):
        return Decimal(default)


def _sol_paired(pool):
    x=(pool.get("token_x") or {}).get("address")
    y=(pool.get("token_y") or {}).get("address")
    return x==dlmm.WSOL or y==dlmm.WSOL


def discover_pools():
    payload=_json_get("/pools",dict(
        page=1,page_size=POOL_PAGE_SIZE,
        sort_by="fee_tvl_ratio_24h:desc",
        filter_by="is_blacklisted=false && tvl>=50000 && volume_24h>=25000",
    ))
    rows=payload.get("data") if isinstance(payload,dict) else None
    if not isinstance(rows,list):
        raise RuntimeError("dlmm_wallet_pool_discovery_shape")
    pools=[]
    for row in rows:
        if not isinstance(row,dict) or not _sol_paired(row):
            continue
        address=row.get("address")
        if not isinstance(address,str):
            continue
        pools.append(dict(
            rank=len(pools)+1,address=address,name=row.get("name"),
            tvl=row.get("tvl"),fee_tvl_ratio_24h=(row.get("fee_tvl_ratio") or {}).get("24h"),
            volume_24h=(row.get("volume") or {}).get("24h"),
            pool_created_at=row.get("created_at"),
            token_x=(row.get("token_x") or {}).get("symbol"),
            token_y=(row.get("token_y") or {}).get("symbol"),
        ))
        if len(pools)>=POOL_SAMPLE:
            break
    if len(pools)<4:
        raise RuntimeError(f"dlmm_wallet_pool_sample_too_small:{len(pools)}")
    return pools


def _actor_events(tx,pool,pool_rank,signature_row):
    meta=tx.get("meta") or {};message=(tx.get("transaction") or {}).get("message") or {}
    keys=_keys(meta,message)
    required=int((message.get("header") or {}).get("numRequiredSignatures",0))
    events=[]
    for outer,inner,ix in _ordered_instructions(meta,message):
        pi=ix.get("programIdIndex")
        if type(pi) is not int or not 0<=pi<len(keys) or keys[pi]!=dlmm.PROGRAM:
            continue
        raw=_un58_data(ix.get("data") or "")
        action=LP_ACTOR_INSTRUCTIONS.get(raw[:8])
        if action is None:
            continue
        accounts=ix.get("accounts") or []
        if len(accounts)<=9:
            continue
        if any(type(accounts[i]) is not int or not 0<=accounts[i]<len(keys)
               for i in (0,1,9)):
            continue
        if keys[accounts[1]]!=pool or accounts[9]>=required:
            continue
        events.append(dict(
            wallet=keys[accounts[9]],position=keys[accounts[0]],
            action=action,pool=pool,pool_rank=pool_rank,
            slot=int(tx.get("slot") or signature_row.get("slot") or 0),
            signature=signature_row.get("signature"),
            execution_order=[outer,inner],
        ))
    return events


def discover_wallet_cohort():
    pools=discover_pools()
    pacer=alchemy_provider.AlchemyPacer()
    all_events=[];pool_telemetry=[]
    for pool in pools:
        rpc=alchemy_provider.new_rpc(limit=PER_POOL_RPC_LIMIT,pacer=pacer)
        found=0;body_failures=0;recent=[]
        try:
            sigs=rpc.call("getSignaturesForAddress",[
                pool["address"],dict(limit=SIGNATURE_LIMIT,commitment="finalized")
            ],True)
            recent=[s for s in sigs if isinstance(s,dict) and not s.get("err")][
                :TX_BODY_LIMIT_PER_POOL]
        except Unavailable:
            pool_telemetry.append(dict(
                pool=pool["address"],rank=pool["rank"],transactions_examined=0,
                lp_actor_events=0,body_failures=0,signature_census_failed=True,
                rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,
                rpc_failures=rpc.failures,rpc_retries=rpc.retries,
            ))
            continue
        for sig in recent:
            try:
                tx=rpc.call("getTransaction",[sig["signature"],dict(
                    encoding="json",commitment="finalized",
                    maxSupportedTransactionVersion=0
                )],True)
            except Unavailable:
                body_failures+=1
                continue
            if not tx or (tx.get("meta") or {}).get("err"):
                body_failures+=1
                continue
            rows=_actor_events(tx,pool["address"],pool["rank"],sig)
            all_events.extend(rows);found+=len(rows)
        pool_telemetry.append(dict(
            pool=pool["address"],rank=pool["rank"],transactions_examined=len(recent),
            lp_actor_events=found,body_failures=body_failures,
            signature_census_failed=False,
            rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,
            rpc_failures=rpc.failures,rpc_retries=rpc.retries,
        ))

    all_events.sort(key=lambda x:(-x["slot"],x["pool_rank"],x["signature"] or "",x["execution_order"]))
    action_counts=defaultdict(Counter);pool_sets=defaultdict(set);latest={}
    for e in all_events:
        action_counts[e["wallet"]][e["action"]]+=1
        pool_sets[e["wallet"]].add(e["pool"])
        prior=latest.get(e["wallet"])
        if prior is None or e["slot"]>prior["slot"]:
            latest[e["wallet"]]=e

    selected=[];seen=set();per_pool=Counter()
    for e in all_events:
        wallet=e["wallet"]
        if wallet in seen or per_pool[e["pool"]]>=MAX_WALLETS_PER_POOL:
            continue
        seen.add(wallet);per_pool[e["pool"]]+=1
        selected.append(dict(
            wallet=wallet,discovery_pool=e["pool"],discovery_pool_rank=e["pool_rank"],
            discovery_slot=e["slot"],discovery_signature=e["signature"],
            discovery_action=e["action"],
            observed_lp_actions=dict(sorted(action_counts[wallet].items())),
            observed_distinct_pools=len(pool_sets[wallet]),
        ))
        if len(selected)>=TARGET_WALLETS:
            break

    report=dict(
        kind="dlmm_wallet_cohort_discovery_v1",
        status=("candidate_cohort_ready" if len(selected)>=MIN_FROZEN_WALLETS
                else "insufficient_candidate_cohort"),
        allocation_authority=False,prospective_trading_enabled=False,
        pnl_data_read=False,pnl_endpoints_forbidden_during_discovery=True,
        cohort_frozen=False,
        methodology="recent_lp_actor_sampling_before_any_pnl_read",
        api_base=API_BASE,pool_selection=dict(
            sol_paired_only=True,sort_by="fee_tvl_ratio_24h:desc",
            filter_by="is_blacklisted=false && tvl>=50000 && volume_24h>=25000",
            pool_sample=POOL_SAMPLE,signature_limit=SIGNATURE_LIMIT,
            tx_body_limit_per_pool=TX_BODY_LIMIT_PER_POOL,
            max_wallets_per_pool=MAX_WALLETS_PER_POOL,target_wallets=TARGET_WALLETS,
        ),
        pools=pools,wallet_count=len(selected),wallets=selected,
        total_lp_actor_events=len(all_events),pool_telemetry=pool_telemetry,
        alchemy_pacer=pacer.telemetry(),
    )
    DISCOVERY_OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(status=report["status"],wallets=len(selected),
                          pools=len(pools),events=len(all_events)),sort_keys=True))
    if len(selected)<MIN_FROZEN_WALLETS:
        raise RuntimeError("dlmm_wallet_candidate_cohort_too_small")
    return report


def _closed_by_cutoff(position,cutoff_epoch):
    closed=position.get("closedAt")
    return isinstance(closed,int) and closed<=cutoff_epoch


def _position_metrics(position,bin_step=None):
    created=position.get("createdAt");closed=position.get("closedAt")
    hold=(int(closed)-int(created)
          if isinstance(created,int) and isinstance(closed,int) and closed>=created else None)
    lower=position.get("lowerBinId");upper=position.get("upperBinId")
    width=(int(upper)-int(lower)+1
           if isinstance(lower,int) and isinstance(upper,int) and upper>=lower else None)
    step=None
    try:
        step=int(bin_step) if bin_step is not None else None
    except (ValueError,TypeError):
        step=None
    span_bps=None
    if width is not None and step is not None and step>0:
        span_bps=(math.pow(1.0+step/10000.0,max(0,width-1))-1.0)*10000.0
    fees=((position.get("allTimeFees") or {}).get("total") or {})
    deps=((position.get("allTimeDeposits") or {}).get("total") or {})
    fee_usd=_dec(fees.get("usd"));dep_usd=_dec(deps.get("usd"))
    return dict(
        position=position.get("positionAddress"),created_at=created,closed_at=closed,
        hold_seconds=hold,width_bins=width,bin_step=step,range_span_bps=span_bps,
        pnl_usd=float(_dec(position.get("pnlUsd"))),
        pnl_sol=(None if position.get("pnlSol") is None else float(_dec(position.get("pnlSol")))),
        pnl_pct=float(_dec(position.get("pnlPctChange"))),
        pnl_sol_pct=(None if position.get("pnlSolPctChange") is None
                     else float(_dec(position.get("pnlSolPctChange")))),
        fee_usd=float(fee_usd),deposit_usd=float(dep_usd),
        fee_to_deposit=(None if dep_usd<=0 else float(fee_usd/dep_usd)),
    )


def _event_epoch(event):
    value=event.get("blockTime")
    if isinstance(value,int):
        return value//1000 if value>10_000_000_000 else value
    if isinstance(value,str) and value.isdigit():
        parsed=int(value)
        return parsed//1000 if parsed>10_000_000_000 else parsed
    created=event.get("createdAt")
    if isinstance(created,str):
        try:
            from datetime import datetime
            return int(datetime.fromisoformat(
                created.replace("Z","+00:00")).timestamp())
        except ValueError:
            return None
    return None


def _history_features(position_address,sol_side=None,cutoff_time=None):
    payload=_json_get(f"/positions/{position_address}/historical",
                      dict(order_direction="asc"),allow_pnl=True)
    events=payload.get("events") if isinstance(payload,dict) else None
    if not isinstance(events,list):
        raise RuntimeError("dlmm_wallet_history_shape")
    if cutoff_time is not None:
        events=[
            e for e in events
            if _event_epoch(e) is not None and _event_epoch(e)<=cutoff_time
        ]
    counts=Counter(str(e.get("eventType")) for e in events)
    adds=[e for e in events if e.get("eventType")=="add"]
    first_add=adds[0] if adds else None
    composition=None
    if first_add is not None:
        x=_dec(first_add.get("amountX"));y=_dec(first_add.get("amountY"))
        if x>0 and y>0:
            composition="two_sided"
        elif x>0:
            composition=("sol_only" if sol_side=="x" else "token_only")
        elif y>0:
            composition=("sol_only" if sol_side=="y" else "token_only")
        else:
            composition="zero"
    block_times=[_event_epoch(e) for e in events if _event_epoch(e) is not None]
    return dict(
        event_count=len(events),event_counts=dict(sorted(counts.items())),
        add_count=counts.get("add",0),remove_count=counts.get("remove",0),
        claim_fee_count=counts.get("claim_fee",0),
        claim_reward_count=counts.get("claim_reward",0),
        repeated_add=counts.get("add",0)>1,
        repeated_remove=counts.get("remove",0)>1,
        managed_rebalance_proxy=(
            counts.get("add",0)>1 or counts.get("remove",0)>1
        ),
        first_add_composition=composition,
        history_span_seconds=(
            None if len(block_times)<2 else max(block_times)-min(block_times)
        ),
    )


def analyze_frozen_cohort(path=DEFAULT_COHORT):
    body=json.loads(Path(path).read_text())
    if body.get("kind")!="dlmm_wallet_cohort_v1" or body.get("status")!="frozen_pre_pnl":
        raise RuntimeError("dlmm_wallet_cohort_not_frozen_pre_pnl")
    frozen_at=body.get("frozen_at")
    if not isinstance(frozen_at,str) or not frozen_at.endswith("Z"):
        raise RuntimeError("dlmm_wallet_cohort_freeze_time")
    from datetime import datetime, timezone
    freeze_epoch=int(datetime.fromisoformat(
        frozen_at[:-1]+"+00:00").timestamp())
    if body.get("pnl_data_read_before_freeze") is not False:
        raise RuntimeError("dlmm_wallet_cohort_pnl_leakage")
    wallets=body.get("wallets") or []
    if len(wallets)<MIN_FROZEN_WALLETS:
        raise RuntimeError("dlmm_wallet_frozen_cohort_too_small")

    summaries=[]
    for row in wallets:
        wallet=row["wallet"]
        portfolio=_json_get("/portfolio",dict(
            user=wallet,page=1,page_size=50,days_back=PORTFOLIO_DAYS_BACK
        ),allow_pnl=True)
        pools=portfolio.get("pools") if isinstance(portfolio,dict) else None
        if not isinstance(pools,list):
            raise RuntimeError("dlmm_wallet_portfolio_shape")
        position_rows=[]
        for pool in pools[:MAX_POOLS_PER_WALLET]:
            address=pool.get("poolAddress")
            bin_step=pool.get("binStep")
            if not isinstance(address,str):
                continue
            pnl=_json_get(f"/positions/{address}/pnl",dict(
                user=wallet,status="closed",page=1,
                page_size=MAX_CLOSED_POSITIONS_PER_POOL
            ),allow_pnl=True)
            positions=pnl.get("positions") if isinstance(pnl,dict) else None
            if not isinstance(positions,list):
                raise RuntimeError("dlmm_wallet_position_pnl_shape")
            for position in positions:
                if not _closed_by_cutoff(position,freeze_epoch):
                    continue
                m=_position_metrics(position,bin_step=bin_step)
                m["pool"]=address
                m["pool_token_x"]=pool.get("tokenX")
                m["pool_token_y"]=pool.get("tokenY")
                m["pool_token_x_mint"]=pool.get("tokenXMint")
                m["pool_token_y_mint"]=pool.get("tokenYMint")
                position_rows.append(m)

        usd=[p["pnl_usd"] for p in position_rows]
        sol=[p["pnl_sol"] for p in position_rows if p["pnl_sol"] is not None]
        holds=[p["hold_seconds"] for p in position_rows if p["hold_seconds"] is not None]
        widths=[p["width_bins"] for p in position_rows if p["width_bins"] is not None]
        rates=[p["fee_to_deposit"] for p in position_rows if p["fee_to_deposit"] is not None]
        distinct=len({p["pool"] for p in position_rows})
        positive_rate=(0 if not usd else sum(x>0 for x in usd)/len(usd))
        eligible=(len(position_rows)>=MIN_CLOSED_POSITIONS and
                  distinct>=MIN_DISTINCT_POOLS and sum(usd)>0 and
                  bool(sol) and sum(sol)>0 and
                  positive_rate>=MIN_PROFITABLE_POSITION_RATE)
        summaries.append(dict(
            wallet=wallet,discovery=row,closed_positions=len(position_rows),
            distinct_closed_pools=distinct,total_pnl_usd=sum(usd),
            total_pnl_sol=(None if not sol else sum(sol)),
            profitable_position_rate_usd=positive_rate,
            median_pnl_usd=(None if not usd else statistics.median(usd)),
            median_hold_seconds=(None if not holds else statistics.median(holds)),
            median_width_bins=(None if not widths else statistics.median(widths)),
            median_fee_to_deposit=(None if not rates else statistics.median(rates)),
            eligible_profitable_wallet=eligible,positions=position_rows,
        ))

    eligible=[w for w in summaries if w["eligible_profitable_wallet"]]
    for wallet in eligible:
        detailed=[]
        ranked=sorted(wallet["positions"],key=lambda p:(p["closed_at"] or 0),reverse=True)
        for p in ranked[:MAX_HISTORY_POSITIONS_PER_ELIGIBLE_WALLET]:
            if not p.get("position"):
                continue
            sol_side=(
                "x" if p.get("pool_token_x_mint")==dlmm.WSOL else
                "y" if p.get("pool_token_y_mint")==dlmm.WSOL else None
            )
            detailed.append(dict(
                **p,history=_history_features(
                    p["position"],sol_side=sol_side,cutoff_time=p.get("closed_at")
                )
            ))
        wallet["detailed_positions"]=detailed

    all_detail=[p for w in eligible for p in w.get("detailed_positions",[])]
    hold_buckets=Counter()
    width_buckets=Counter()
    span_buckets=Counter()
    composition_buckets=Counter()
    rebalance_positions=0
    for p in all_detail:
        h=p.get("hold_seconds")
        if h is not None:
            label=("<15m" if h<900 else "15-60m" if h<3600 else
                   "1-4h" if h<14400 else "4-24h" if h<86400 else ">=24h")
            hold_buckets[label]+=1
        w=p.get("width_bins")
        if w is not None:
            label=("<=10" if w<=10 else "11-25" if w<=25 else
                   "26-50" if w<=50 else ">50")
            width_buckets[label]+=1
        span=p.get("range_span_bps")
        if span is not None:
            label=("<=250" if span<=250 else "251-500" if span<=500 else
                   "501-1000" if span<=1000 else "1001-2000" if span<=2000
                   else ">2000")
            span_buckets[label]+=1
        hist=p.get("history") or {}
        comp=hist.get("first_add_composition")
        if comp:
            composition_buckets[comp]+=1
        if hist.get("managed_rebalance_proxy"):
            rebalance_positions+=1

    report=dict(
        kind="dlmm_wallet_derived_analysis_v1",
        status="behavior_discovery_only_no_strategy_frozen",
        allocation_authority=False,prospective_trading_enabled=False,
        cohort_hash=body.get("cohort_hash"),cohort_frozen_at=body.get("frozen_at"),
        development_data_cutoff_epoch=freeze_epoch,
        post_freeze_positions_excluded=True,
        cohort_wallet_count=len(wallets),wallets_analyzed=len(summaries),
        profitable_wallet_definition=dict(
            min_closed_positions=MIN_CLOSED_POSITIONS,
            min_distinct_pools=MIN_DISTINCT_POOLS,
            require_total_pnl_usd_positive=True,
            require_total_pnl_sol_positive=True,
            min_profitable_position_rate_usd=MIN_PROFITABLE_POSITION_RATE,
        ),
        profitable_wallet_count=len(eligible),
        profitable_wallets=eligible,
        cohort_wallet_summaries=summaries,
        behavior_summary=dict(
            detailed_positions=len(all_detail),
            hold_duration_buckets=dict(sorted(hold_buckets.items())),
            width_bin_buckets=dict(sorted(width_buckets.items())),
            normalized_range_span_bps_buckets=dict(sorted(span_buckets.items())),
            first_add_composition_buckets=dict(sorted(composition_buckets.items())),
            rebalance_proxy_positions=rebalance_positions,
            rebalance_proxy_rate=(None if not all_detail else rebalance_positions/len(all_detail)),
        ),
        strategy_candidate_status="not_frozen",
        strategy_candidate_rule=(
            "Do not create a strategy from the legacy 60-second observations. "
            "Any candidate must be derived only from repeatable patterns in this "
            "frozen wallet cohort, reviewed, frozen in a later commit, and then "
            "tested prospectively on post-freeze market data."
        ),
    )
    ANALYSIS_OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(wallets=len(summaries),profitable_wallets=len(eligible),
                          detailed_positions=len(all_detail)),sort_keys=True))
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("phase",choices=("discover","analyze"))
    p.add_argument("--cohort",default=str(DEFAULT_COHORT))
    a=p.parse_args()
    if a.phase=="discover":
        discover_wallet_cohort()
    else:
        analyze_frozen_cohort(Path(a.cohort))


if __name__=="__main__":
    main()
