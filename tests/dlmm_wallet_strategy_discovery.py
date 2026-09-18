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

API_BASE="https://dlmm.datapi.meteora.ag"
DISCOVERY_OUT=Path("dlmm-wallet-cohort-discovery.json")
ANALYSIS_OUT=Path("dlmm-wallet-derived-analysis.json")
DEFAULT_COHORT=Path("DLMM_WALLET_COHORT_V1.json")

POOL_SAMPLE=12
POOL_PAGE_SIZE=100
SIGNATURE_LIMIT=64
TX_BODY_LIMIT_PER_POOL=24
TX_BODY_SCAN_LIMIT_PER_POOL=40
MAX_SUPPORTED_TRANSACTION_VERSION=1
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
MIN_REPEATABLE_PROFITABLE_WALLETS=3
REPEATABILITY_SUPPORT=2/3

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


def _failure_delta(before,after):
    keys=set(before)|set(after)
    return {k:int(after.get(k,0))-int(before.get(k,0))
            for k in sorted(keys) if int(after.get(k,0))-int(before.get(k,0))}


def _read_recent_transactions(rpc,signatures,target=TX_BODY_LIMIT_PER_POOL,
                              scan_limit=TX_BODY_SCAN_LIMIT_PER_POOL):
    """Read the newest finalized bodies in order, replacing unreadable RPC rows.

    Provider availability must not turn one unreadable transaction into an implicit
    LP/non-LP classification. Discovery therefore advances to the next finalized
    signature, records the missing evidence, and requires the same fixed number of
    readable transaction bodies before a pool is considered complete.
    """
    readable=[];failures=[]
    for sig in list(signatures)[:scan_limit]:
        if len(readable)>=target:
            break
        before=dict(rpc.failure_kinds)
        try:
            tx=rpc.call("getTransaction",[
                sig["signature"],dict(
                    encoding="json",commitment="finalized",
                    maxSupportedTransactionVersion=MAX_SUPPORTED_TRANSACTION_VERSION,
                )
            ],True)
        except alchemy_provider.Unavailable as exc:
            failures.append(dict(
                signature=sig.get("signature"),slot=sig.get("slot"),
                status="provider_unavailable",
                error=str(exc),failure_kind_delta=_failure_delta(
                    before,dict(rpc.failure_kinds)),
            ))
            continue
        if not tx:
            failures.append(dict(
                signature=sig.get("signature"),slot=sig.get("slot"),
                status="null_transaction",error="finalized_body_unavailable",
                failure_kind_delta=_failure_delta(before,dict(rpc.failure_kinds)),
            ))
            continue
        if (tx.get("meta") or {}).get("err"):
            failures.append(dict(
                signature=sig.get("signature"),slot=sig.get("slot"),
                status="transaction_error",error="finalized_transaction_failed",
                failure_kind_delta=_failure_delta(before,dict(rpc.failure_kinds)),
            ))
            continue
        readable.append((sig,tx))
    return readable,failures


def discover_wallet_cohort():
    pools=discover_pools()
    pacer=alchemy_provider.AlchemyPacer()
    all_events=[];pool_telemetry=[];all_pools_complete=True
    for pool in pools:
        rpc=alchemy_provider.new_rpc(limit=PER_POOL_RPC_LIMIT,pacer=pacer)
        sigs=rpc.call("getSignaturesForAddress",[
            pool["address"],dict(limit=SIGNATURE_LIMIT,commitment="finalized")
        ],True)
        recent=[s for s in sigs if isinstance(s,dict) and not s.get("err")]
        readable,read_failures=_read_recent_transactions(rpc,recent)
        pool_complete=len(readable)>=TX_BODY_LIMIT_PER_POOL
        all_pools_complete=all_pools_complete and pool_complete
        found=0
        for sig,tx in readable:
            rows=_actor_events(tx,pool["address"],pool["rank"],sig)
            all_events.extend(rows);found+=len(rows)
        pool_telemetry.append(dict(
            pool=pool["address"],rank=pool["rank"],
            finalized_signatures_available=len(recent),
            transaction_scan_limit=TX_BODY_SCAN_LIMIT_PER_POOL,
            readable_transactions=len(readable),
            transactions_examined=len(readable),
            pool_complete=pool_complete,
            unreadable_transactions=read_failures,
            lp_actor_events=found,rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,
            rpc_failures=rpc.failures,rpc_retries=rpc.retries,
            rpc_failure_kinds=dict(sorted(rpc.failure_kinds.items())),
            rpc_failure_methods=dict(sorted(rpc.failure_methods.items())),
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
        status=("candidate_cohort_ready"
                if all_pools_complete and len(selected)>=MIN_FROZEN_WALLETS else
                "incomplete_provider_evidence" if not all_pools_complete else
                "insufficient_candidate_cohort"),
        allocation_authority=False,prospective_trading_enabled=False,
        pnl_data_read=False,pnl_endpoints_forbidden_during_discovery=True,
        cohort_frozen=False,
        methodology="recent_lp_actor_sampling_before_any_pnl_read",
        api_base=API_BASE,pool_selection=dict(
            sol_paired_only=True,sort_by="fee_tvl_ratio_24h:desc",
            filter_by="is_blacklisted=false && tvl>=50000 && volume_24h>=25000",
            pool_sample=POOL_SAMPLE,signature_limit=SIGNATURE_LIMIT,
            tx_body_limit_per_pool=TX_BODY_LIMIT_PER_POOL,
            tx_body_scan_limit_per_pool=TX_BODY_SCAN_LIMIT_PER_POOL,
            unreadable_signature_policy=(
                "advance_in_finalized_recency_order_and_fail_pool_if_target_not_met"),
            max_wallets_per_pool=MAX_WALLETS_PER_POOL,target_wallets=TARGET_WALLETS,
        ),
        all_pools_complete=all_pools_complete,
        pools=pools,wallet_count=len(selected),wallets=selected,
        total_lp_actor_events=len(all_events),pool_telemetry=pool_telemetry,
        alchemy_pacer=pacer.telemetry(),
    )
    DISCOVERY_OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(status=report["status"],wallets=len(selected),
                          pools=len(pools),events=len(all_events)),sort_keys=True))
    if not all_pools_complete:
        raise RuntimeError("dlmm_wallet_provider_evidence_incomplete")
    if len(selected)<MIN_FROZEN_WALLETS:
        raise RuntimeError("dlmm_wallet_candidate_cohort_too_small")
    return report


def _position_metrics(position):
    created=position.get("createdAt");closed=position.get("closedAt")
    hold=(int(closed)-int(created)
          if isinstance(created,int) and isinstance(closed,int) and closed>=created else None)
    lower=position.get("lowerBinId");upper=position.get("upperBinId")
    width=(int(upper)-int(lower)+1
           if isinstance(lower,int) and isinstance(upper,int) and upper>=lower else None)
    fees=((position.get("allTimeFees") or {}).get("total") or {})
    deps=((position.get("allTimeDeposits") or {}).get("total") or {})
    fee_usd=_dec(fees.get("usd"));dep_usd=_dec(deps.get("usd"))
    return dict(
        position=position.get("positionAddress"),created_at=created,closed_at=closed,
        hold_seconds=hold,width_bins=width,pnl_usd=float(_dec(position.get("pnlUsd"))),
        pnl_sol=(None if position.get("pnlSol") is None else float(_dec(position.get("pnlSol")))),
        pnl_pct=float(_dec(position.get("pnlPctChange"))),
        pnl_sol_pct=(None if position.get("pnlSolPctChange") is None
                     else float(_dec(position.get("pnlSolPctChange")))),
        fee_usd=float(fee_usd),deposit_usd=float(dep_usd),
        fee_to_deposit=(None if dep_usd<=0 else float(fee_usd/dep_usd)),
    )


def _hold_bucket(seconds):
    if seconds is None:
        return None
    return ("<15m" if seconds<900 else "15-60m" if seconds<3600 else
            "1-4h" if seconds<14400 else "4-24h" if seconds<86400 else ">=24h")


def _width_bucket(width):
    if width is None:
        return None
    return "<=10" if width<=10 else "11-25" if width<=25 else "26-50" if width<=50 else ">50"


def _dominant(values):
    values=[v for v in values if v is not None]
    if not values:
        return dict(value=None,count=0,total=0,support=None)
    counts=Counter(values)
    # Deterministic tie-break: lexical label order, never outcome magnitude.
    value,count=sorted(counts.items(),key=lambda kv:(-kv[1],str(kv[0])))[0]
    return dict(value=value,count=count,total=len(values),support=count/len(values))


def _wallet_behavior_profile(wallet):
    positions=wallet.get("positions") or []
    holds=[p.get("hold_seconds") for p in positions if p.get("hold_seconds") is not None]
    widths=[p.get("width_bins") for p in positions if p.get("width_bins") is not None]
    fee_rates=[p.get("fee_to_deposit") for p in positions if p.get("fee_to_deposit") is not None]
    detail=wallet.get("detailed_positions") or []
    rebalanced=sum(
        bool((p.get("history") or {}).get("repeated_add") or
             (p.get("history") or {}).get("repeated_remove"))
        for p in detail
    )
    return dict(
        wallet=wallet.get("wallet"),
        closed_positions=len(positions),
        dominant_hold_bucket=_dominant([_hold_bucket(v) for v in holds]),
        dominant_width_bucket=_dominant([_width_bucket(v) for v in widths]),
        median_hold_seconds=(None if not holds else statistics.median(holds)),
        median_width_bins=(None if not widths else statistics.median(widths)),
        median_fee_to_deposit=(None if not fee_rates else statistics.median(fee_rates)),
        rebalance_proxy_rate=(None if not detail else rebalanced/len(detail)),
        distinct_closed_pools=wallet.get("distinct_closed_pools"),
    )


def _repeatability(profiles):
    hold=_dominant([
        p["dominant_hold_bucket"]["value"] for p in profiles
        if p["dominant_hold_bucket"]["value"] is not None
    ])
    width=_dominant([
        p["dominant_width_bucket"]["value"] for p in profiles
        if p["dominant_width_bucket"]["value"] is not None
    ])
    rebalance_labels=[]
    for p in profiles:
        rate=p.get("rebalance_proxy_rate")
        if rate is not None:
            rebalance_labels.append("active" if rate>=0.5 else "passive")
    rebalance=_dominant(rebalance_labels)
    sufficient_wallets=len(profiles)>=MIN_REPEATABLE_PROFITABLE_WALLETS
    repeatable=bool(
        sufficient_wallets and
        hold["support"] is not None and hold["support"]>=REPEATABILITY_SUPPORT and
        width["support"] is not None and width["support"]>=REPEATABILITY_SUPPORT
    )
    exact_hold=None;exact_width=None
    if repeatable:
        hold_values=[
            p["median_hold_seconds"] for p in profiles
            if p["dominant_hold_bucket"]["value"]==hold["value"] and
               p["median_hold_seconds"] is not None
        ]
        width_values=[
            p["median_width_bins"] for p in profiles
            if p["dominant_width_bucket"]["value"]==width["value"] and
               p["median_width_bins"] is not None
        ]
        if hold_values:
            exact_hold=int(round(statistics.median(hold_values)))
        if width_values:
            exact_width=max(1,int(round(statistics.median(width_values))))
    return dict(
        required_profitable_wallets=MIN_REPEATABLE_PROFITABLE_WALLETS,
        required_cross_wallet_support=REPEATABILITY_SUPPORT,
        profitable_wallets=len(profiles),
        hold_bucket_consensus=hold,
        width_bucket_consensus=width,
        rebalance_preference=rebalance,
        repeatable_behavior_identified=repeatable,
        derived_hold_seconds=exact_hold,
        derived_width_bins=exact_width,
    )


def _history_features(position_address):
    payload=_json_get(f"/positions/{position_address}/historical",
                      dict(order_direction="asc"),allow_pnl=True)
    events=payload.get("events") if isinstance(payload,dict) else None
    if not isinstance(events,list):
        raise RuntimeError("dlmm_wallet_history_shape")
    counts=Counter(str(e.get("eventType")) for e in events)
    return dict(
        event_count=len(events),event_counts=dict(sorted(counts.items())),
        add_count=counts.get("add",0),remove_count=counts.get("remove",0),
        claim_fee_count=counts.get("claim_fee",0),
        claim_reward_count=counts.get("claim_reward",0),
        repeated_add=counts.get("add",0)>1,
        repeated_remove=counts.get("remove",0)>1,
    )


def analyze_frozen_cohort(path=DEFAULT_COHORT):
    body=json.loads(Path(path).read_text())
    if body.get("kind")!="dlmm_wallet_cohort_v1" or body.get("status")!="frozen_pre_pnl":
        raise RuntimeError("dlmm_wallet_cohort_not_frozen_pre_pnl")
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
                m=_position_metrics(position);m["pool"]=address
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
            detailed.append(dict(**p,history=_history_features(p["position"])))
        wallet["detailed_positions"]=detailed

    all_detail=[p for w in eligible for p in w.get("detailed_positions",[])]
    hold_buckets=Counter()
    width_buckets=Counter()
    rebalance_positions=0
    for p in all_detail:
        label=_hold_bucket(p.get("hold_seconds"))
        if label is not None:
            hold_buckets[label]+=1
        label=_width_bucket(p.get("width_bins"))
        if label is not None:
            width_buckets[label]+=1
        hist=p.get("history") or {}
        if hist.get("repeated_add") or hist.get("repeated_remove"):
            rebalance_positions+=1

    behavior_profiles=[_wallet_behavior_profile(w) for w in eligible]
    repeatability=_repeatability(behavior_profiles)

    report=dict(
        kind="dlmm_wallet_derived_analysis_v1",
        status="behavior_discovery_only_no_strategy_frozen",
        allocation_authority=False,prospective_trading_enabled=False,
        cohort_hash=body.get("cohort_hash"),cohort_frozen_at=body.get("frozen_at"),
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
            rebalance_proxy_positions=rebalance_positions,
            rebalance_proxy_rate=(None if not all_detail else rebalance_positions/len(all_detail)),
            profitable_wallet_profiles=behavior_profiles,
            repeatability=repeatability,
        ),
        strategy_candidate_status=(
            "repeatable_behavior_found_candidate_not_frozen"
            if repeatability["repeatable_behavior_identified"] else
            "no_repeatable_behavior_candidate_not_permitted"
        ),
        prospective_candidate_seed=(
            None if not repeatability["repeatable_behavior_identified"] else dict(
                entry_signal="future_onchain_lp_add_by_any_frozen_profitable_wallet",
                pool_universe="same_preregistered_SOL_paired_universe",
                range_placement="symmetric_about_current_active_bin",
                width_bins=repeatability["derived_width_bins"],
                hold_seconds=repeatability["derived_hold_seconds"],
                rebalance_preference=repeatability["rebalance_preference"]["value"],
                allocation_authority=False,
                paper_only=True,
            )
        ),
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
