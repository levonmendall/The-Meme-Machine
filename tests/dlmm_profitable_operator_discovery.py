"""Comprehensive Meteora DLMM profitable-operator discovery.

Phase A exhausts every observable eligible SOL-paired pool and discovers authenticated
LP signers without reading PnL. Phase B may run only from a committed frozen census
cohort. Outcome ranking, capital-efficiency reconstruction, fleet clustering and any
subsequent rule derivation remain research-only and have no allocation authority.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import threading
import time

from meme_machine import dlmm
from tests import dlmm_alchemy_provider as solana_provider
from tests import dlmm_wallet_strategy_discovery as legacy

PROTOCOL=Path("DLMM_PROFITABLE_OPERATOR_DISCOVERY_V1.json")
CENSUS_OUT=Path("dlmm-profitable-operator-census.json")
CENSUS_CHECKPOINT=Path("dlmm-profitable-operator-census-checkpoint.json")
DEFAULT_COHORT=Path("DLMM_PROFITABLE_OPERATOR_COHORT_V1.json")
RANK_OUT=Path("dlmm-profitable-operator-ranking.json")
RANK_CHECKPOINT=Path("dlmm-profitable-operator-ranking-checkpoint.json")
DEEP_OUT=Path("dlmm-profitable-operator-deep-reconstruction.json")

POOL_PAGE_SIZE=1000
SIGNATURE_LIMIT=96
TX_BODY_TARGET=32
TX_BODY_SCAN_LIMIT=56
PER_POOL_RPC_LIMIT=160

DAYS_BACK=120
PORTFOLIO_PAGE_SIZE=50
MAX_PORTFOLIO_PAGES=20
POSITION_PAGE_SIZE=100
MAX_POSITION_PAGES=100

MIN_CLOSED_POSITIONS=20
MIN_DISTINCT_POOLS=3
TOP_PER_RANK=25

METEORA_REQUESTS_PER_SECOND=20
DEFAULT_METEORA_WORKERS=12
MAX_METEORA_WORKERS=16
METEORA_RETRY_ATTEMPTS=3

WSOL=dlmm.WSOL


def _dec(value,default=0.0):
    try:
        return float(Decimal(str(default if value is None else value)))
    except (InvalidOperation,ValueError,TypeError):
        return float(default)


def _protocol_signature():
    body=PROTOCOL.read_bytes()
    return hashlib.sha256(body).hexdigest()


def _atomic_json(path,body):
    path=Path(path)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(body,indent=2,sort_keys=True)+"\n")
    tmp.replace(path)


def _eligible_pool(row):
    if not isinstance(row,dict) or row.get("is_blacklisted") is not False:
        return False
    if _dec(row.get("tvl"))<50000:
        return False
    if _dec((row.get("volume") or {}).get("24h"))<25000:
        return False
    return legacy._sol_paired(row)


def _pool_record(row):
    return dict(
        address=row["address"],name=row.get("name"),created_at=row.get("created_at"),
        tvl=row.get("tvl"),volume_24h=(row.get("volume") or {}).get("24h"),
        fees_24h=(row.get("fees") or {}).get("24h"),
        fee_tvl_24h=(row.get("fee_tvl_ratio") or {}).get("24h"),
        dynamic_fee_pct=row.get("dynamic_fee_pct"),
        current_price=row.get("current_price"),
        token_x=(row.get("token_x") or {}).get("address"),
        token_y=(row.get("token_y") or {}).get("address"),
        token_x_symbol=(row.get("token_x") or {}).get("symbol"),
        token_y_symbol=(row.get("token_y") or {}).get("symbol"),
    )


def census_pools():
    pools=[];seen=set();page=1;pages=None
    while True:
        payload=legacy._json_get("/pools",dict(
            page=page,page_size=POOL_PAGE_SIZE,sort_by="tvl:desc",
            filter_by="is_blacklisted=false && tvl>=50000 && volume_24h>=25000",
        ))
        rows=payload.get("data") if isinstance(payload,dict) else None
        if not isinstance(rows,list):
            raise RuntimeError("dlmm_operator_pool_census_shape")
        if pages is None:
            raw_pages=payload.get("pages")
            pages=int(raw_pages) if raw_pages is not None else None
        for row in rows:
            if not _eligible_pool(row):
                continue
            address=row.get("address")
            if not isinstance(address,str) or address in seen:
                continue
            seen.add(address);pools.append(_pool_record(row))
        if (pages is not None and page>=pages) or not rows or len(rows)<POOL_PAGE_SIZE:
            break
        page+=1
        if page>10000:
            raise RuntimeError("dlmm_operator_pool_census_page_bound")
    pools.sort(key=lambda x:x["address"])
    if not pools:
        raise RuntimeError("dlmm_operator_no_eligible_sol_pools")
    return pools


def _census_signature(pools):
    return dict(
        protocol_sha256=_protocol_signature(),
        pool_addresses=[p["address"] for p in pools],
        signature_limit=SIGNATURE_LIMIT,
        readable_transaction_target=TX_BODY_TARGET,
        transaction_scan_limit=TX_BODY_SCAN_LIMIT,
        max_supported_transaction_version=legacy.MAX_SUPPORTED_TRANSACTION_VERSION,
        wallet_selection="all_authenticated_lp_signers_no_per_pool_cap",
    )


def _load_census_checkpoint(pools):
    signature=_census_signature(pools)
    if not CENSUS_CHECKPOINT.exists():
        return signature,{}
    body=json.loads(CENSUS_CHECKPOINT.read_text())
    if body.get("kind")!="dlmm_profitable_operator_census_checkpoint_v1":
        raise RuntimeError("dlmm_operator_census_checkpoint_kind")
    if body.get("signature")!=signature:
        raise RuntimeError("dlmm_operator_census_checkpoint_mismatch")
    rows=body.get("pool_results") or {}
    if not isinstance(rows,dict):
        raise RuntimeError("dlmm_operator_census_checkpoint_shape")
    return signature,rows


def _write_census_checkpoint(signature,pools,rows,started):
    completed=sum(bool(v.get("complete")) for v in rows.values())
    _atomic_json(CENSUS_CHECKPOINT,dict(
        kind="dlmm_profitable_operator_census_checkpoint_v1",
        status=("complete" if completed==len(pools) else "partial"),
        signature=signature,started_at=started,updated_at=int(time.time()),
        pool_count=len(pools),completed_pools=completed,pool_results=rows,
    ))


def _scan_pool(pool,pacer):
    rpc=solana_provider.new_rpc(limit=PER_POOL_RPC_LIMIT,pacer=pacer)
    sigs=rpc.call("getSignaturesForAddress",[
        pool["address"],dict(limit=SIGNATURE_LIMIT,commitment="finalized")
    ],True)
    recent=[s for s in sigs if isinstance(s,dict) and not s.get("err")]
    readable,failures=legacy._read_recent_transactions(
        rpc,recent,target=TX_BODY_TARGET,scan_limit=TX_BODY_SCAN_LIMIT)
    exhaustive_low_history=(
        len(recent)<TX_BODY_TARGET and len(readable)==len(recent) and not failures)
    complete=len(readable)>=TX_BODY_TARGET or exhaustive_low_history
    events=[]
    for sig,tx in readable:
        events.extend(legacy._actor_events(tx,pool["address"],0,sig))
    events.sort(key=lambda e:(-e["slot"],e.get("signature") or "",e["execution_order"]))
    return dict(
        complete=complete,
        coverage_mode=("target_depth" if len(readable)>=TX_BODY_TARGET
                       else "exhaustive_low_history" if exhaustive_low_history
                       else "incomplete"),
        finalized_signatures_available=len(recent),
        readable_transactions=len(readable),
        unreadable_transactions=failures,
        lp_actor_events=events,
        rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,
        rpc_failures=rpc.failures,rpc_retries=rpc.retries,
        provider_topology=(rpc.provider_telemetry()
                           if hasattr(rpc,"provider_telemetry") else None),
    )


def census():
    pools=census_pools()
    signature,rows=_load_census_checkpoint(pools)
    started=int(time.time())
    pacer=solana_provider.AlchemyPacer()
    _write_census_checkpoint(signature,pools,rows,started)
    by_address={p["address"]:p for p in pools}
    for index,pool in enumerate(pools,1):
        address=pool["address"]
        if rows.get(address,{}).get("complete"):
            continue
        try:
            result=_scan_pool(pool,pacer)
        except Exception as exc:
            result=dict(complete=False,coverage_mode="error",
                        error=type(exc).__name__,lp_actor_events=[])
        rows[address]=result
        _write_census_checkpoint(signature,pools,rows,started)
        print(json.dumps(dict(
            phase="pool_census",pool=address,index=index,total=len(pools),
            complete=bool(result.get("complete")),
            events=len(result.get("lp_actor_events") or []),
        ),sort_keys=True),flush=True)

    action_counts=defaultdict(Counter);pool_sets=defaultdict(set);latest={}
    all_complete=True;total_events=0
    for address in signature["pool_addresses"]:
        result=rows.get(address) or {}
        all_complete=all_complete and bool(result.get("complete"))
        for e in result.get("lp_actor_events") or []:
            total_events+=1
            wallet=e["wallet"]
            action_counts[wallet][e["action"]]+=1
            pool_sets[wallet].add(address)
            prior=latest.get(wallet)
            if prior is None or int(e["slot"])>int(prior["slot"]):
                latest[wallet]=e
    wallets=[]
    for wallet in sorted(latest):
        e=latest[wallet]
        wallets.append(dict(
            wallet=wallet,latest_observed_slot=e["slot"],
            latest_observed_pool=e["pool"],latest_observed_action=e["action"],
            observed_lp_actions=dict(sorted(action_counts[wallet].items())),
            observed_distinct_pools=len(pool_sets[wallet]),
        ))
    report=dict(
        kind="dlmm_profitable_operator_census_v1",
        status=("candidate_cohort_ready" if all_complete else
                "incomplete_provider_evidence"),
        protocol_sha256=signature["protocol_sha256"],
        pnl_data_read=False,pnl_endpoints_forbidden=True,
        allocation_authority=False,strategy_freeze_permitted=False,
        pool_count=len(pools),completed_pools=sum(
            bool((rows.get(p["address"]) or {}).get("complete")) for p in pools),
        wallet_count=len(wallets),total_lp_actor_events=total_events,
        pool_universe=pools,wallets=wallets,pool_results=rows,
        rpc_pacer=pacer.telemetry(),
    )
    _atomic_json(CENSUS_OUT,report)
    print(json.dumps(dict(status=report["status"],pools=len(pools),
                          wallets=len(wallets),events=total_events),sort_keys=True))
    if not all_complete:
        raise RuntimeError("dlmm_operator_census_incomplete")
    return report


class _ApiPacer:
    def __init__(self,rps=METEORA_REQUESTS_PER_SECOND):
        self.interval=1.0/float(rps);self.lock=threading.Lock();self.next=0.0
    def pace(self):
        with self.lock:
            now=time.monotonic();wait=max(0.0,self.next-now)
            if wait: time.sleep(wait);now=time.monotonic()
            self.next=max(now,self.next)+self.interval


API_PACER=_ApiPacer()


def _api(path,params=None):
    last=None
    for attempt in range(METEORA_RETRY_ATTEMPTS):
        try:
            API_PACER.pace()
            return legacy._json_get(path,params,allow_pnl=True)
        except Exception as exc:
            last=exc
            if attempt+1<METEORA_RETRY_ATTEMPTS:
                time.sleep(0.5*(attempt+1))
    raise last


def _portfolio(wallet):
    pools=[];total_positions=None
    for page in range(1,MAX_PORTFOLIO_PAGES+1):
        payload=_api("/portfolio",dict(
            user=wallet,page=page,page_size=PORTFOLIO_PAGE_SIZE,days_back=DAYS_BACK))
        data=payload.get("pools") if isinstance(payload,dict) else None
        if not isinstance(data,list):
            raise RuntimeError("dlmm_operator_portfolio_shape")
        pools.extend(data)
        if total_positions is None:
            total_positions=int(payload.get("totalPositions") or 0)
        if not payload.get("hasNext"):
            return pools,int(total_positions or 0),False
    return pools,int(total_positions or 0),True


def _closed_positions(wallet,pools):
    cutoff=int(time.time())-DAYS_BACK*86400
    out=[];truncated=False
    for pool in pools:
        address=pool.get("poolAddress")
        if not isinstance(address,str): continue
        for page in range(1,MAX_POSITION_PAGES+1):
            payload=_api(f"/positions/{address}/pnl",dict(
                user=wallet,status="closed",page=page,page_size=POSITION_PAGE_SIZE))
            positions=payload.get("positions") if isinstance(payload,dict) else None
            if not isinstance(positions,list):
                raise RuntimeError("dlmm_operator_position_shape")
            for pos in positions:
                closed=pos.get("closedAt")
                if isinstance(closed,int) and closed>=cutoff:
                    row=legacy._position_metrics(pos)
                    row.update(
                        pool=address,
                        fee_per_tvl_24h=_dec(pos.get("feePerTvl24h")),
                        lower_bin_id=pos.get("lowerBinId"),
                        upper_bin_id=pos.get("upperBinId"),
                        pool_active_bin_id=pos.get("poolActiveBinId"),
                        withdrawal_usd=_dec((((pos.get("allTimeWithdrawals") or {})
                                           .get("total") or {}).get("usd"))),
                    )
                    out.append(row)
            if not payload.get("hasNext"):
                break
        else:
            truncated=True
    return out,truncated


def _realized_path_metrics(positions):
    rows=sorted(
        (p for p in positions if isinstance(p.get("closed_at"),int)),
        key=lambda p:(p["closed_at"],p.get("position") or ""))
    equity=0.0;peak=0.0;max_dd=0.0
    weeks=defaultdict(float)
    for p in rows:
        pnl=float(p["pnl_usd"]);equity+=pnl;peak=max(peak,equity)
        max_dd=max(max_dd,peak-equity)
        weeks[int(p["closed_at"])//604800]+=pnl
    active=list(weeks.values())
    return dict(
        profitable_position_rate=(None if not rows else
                                  sum(p["pnl_usd"]>0 for p in rows)/len(rows)),
        max_realized_drawdown_usd=max_dd,
        profitable_active_week_rate=(None if not active else
                                     sum(x>0 for x in active)/len(active)),
        active_weeks=len(active),
    )


def _history(position):
    payload=_api(f"/positions/{position}/historical",dict(order_direction="asc"))
    events=payload.get("events") if isinstance(payload,dict) else None
    if not isinstance(events,list):
        raise RuntimeError("dlmm_operator_history_shape")
    clean=[]
    for e in events:
        if not isinstance(e,dict): continue
        clean.append(dict(
            signature=e.get("signature"),ix_index=e.get("ixIndex"),
            event_type=e.get("eventType"),position=e.get("positionAddress"),
            pool=e.get("poolAddress"),wallet=e.get("userAddress"),
            block_time=e.get("blockTime"),slot=e.get("slot"),
            token_x=e.get("tokenX"),token_y=e.get("tokenY"),
            amount_x=e.get("amountX"),amount_y=e.get("amountY"),
            amount_x_usd=_dec(e.get("amountXUsd")),
            amount_y_usd=_dec(e.get("amountYUsd")),
            total_usd=_dec(e.get("totalUsd")),
        ))
    clean.sort(key=lambda e:(int(e.get("block_time") or 0),
                             int(e.get("slot") or 0),int(e.get("ix_index") or 0)))
    return clean


def _capital_timeline(positions,histories):
    """Event-time contributed-capital timeline across overlapping positions.

    The Meteora historical API gives exact add/remove/claim events and event-time USD
    values. We maintain contributed capital per position. Removes retire contributed
    basis but never create negative risk capital; a terminal close retires any residual
    basis. This avoids cumulative-deposit double counting while staying explicit that
    the metric is contributed-capital exposure, not continuously marked-to-market TVL.
    """
    events=[]
    close_by_position={p.get("position"):p.get("closed_at") for p in positions}
    for position,rows in histories.items():
        for e in rows:
            if e.get("event_type") in ("add","remove"):
                events.append((int(e.get("block_time") or 0),
                               int(e.get("slot") or 0),
                               int(e.get("ix_index") or 0),position,e))
        closed=close_by_position.get(position)
        if isinstance(closed,int):
            events.append((closed,2**63-1,2**31-1,position,{"event_type":"terminal"}))
    events.sort()
    basis=defaultdict(float);total=0.0;capital_seconds=0.0;last=None;segments=[]
    for ts,_slot,_ix,position,e in events:
        if ts<=0: continue
        if last is not None and ts>last and total>0:
            capital_seconds+=total*(ts-last)
            segments.append(dict(start=last,end=ts,capital_usd=total))
        kind=e["event_type"]
        if kind=="add":
            amount=max(0.0,float(e["total_usd"]))
            basis[position]+=amount;total+=amount
        elif kind=="remove":
            amount=min(basis[position],max(0.0,float(e["total_usd"])))
            basis[position]-=amount;total-=amount
        elif kind=="terminal":
            amount=basis.pop(position,0.0);total-=amount
        total=max(0.0,total);last=ts
    return dict(
        capital_hours_usd=capital_seconds/3600.0,
        peak_concurrent_contributed_capital_usd=max(
            [x["capital_usd"] for x in segments] or [0.0]),
        exposure_segments=segments,
        residual_contributed_capital_usd=sum(basis.values()),
        methodology="event_time_contributed_capital_basis_not_continuous_mark_to_market",
    )


def _wallet_rank_row(wallet):
    pools,total_positions,portfolio_truncated=_portfolio(wallet)
    positions,truncated=_closed_positions(wallet,pools)
    if portfolio_truncated or truncated:
        raise RuntimeError("dlmm_operator_wallet_history_truncated")
    path=_realized_path_metrics(positions)
    pnl=sum(float(p["pnl_usd"]) for p in positions)
    fees=sum(float(p["fee_usd"]) for p in positions)
    histories={}
    for p in positions:
        address=p.get("position")
        if address: histories[address]=_history(address)
    capital=_capital_timeline(positions,histories)
    ch=capital["capital_hours_usd"]
    # Network execution costs are filled during deep on-chain reconstruction; primary
    # rank is fail-closed for after-cost capital efficiency until that stage completes.
    return dict(
        wallet=wallet,total_positions_api=total_positions,
        measured_closed_positions=len(positions),
        distinct_pools=len({p["pool"] for p in positions}),
        api_realized_pnl_usd=pnl,fee_income_usd=fees,
        inventory_token_price_pnl_usd=pnl-fees,
        capital_hours_usd=ch,
        gross_pnl_per_capital_hour=(None if ch<=0 else pnl/ch),
        **path,capital_timeline=capital,
        positions=positions,histories=histories,
    )


def _rank_signature(cohort):
    wallets=[x["wallet"] for x in cohort.get("wallets") or []]
    return dict(protocol_sha256=_protocol_signature(),
                cohort_hash=cohort.get("cohort_hash"),wallets=wallets,
                days_back=DAYS_BACK)


def _load_rank_checkpoint(signature):
    if not RANK_CHECKPOINT.exists(): return {}
    body=json.loads(RANK_CHECKPOINT.read_text())
    if body.get("kind")!="dlmm_profitable_operator_rank_checkpoint_v1" or body.get("signature")!=signature:
        raise RuntimeError("dlmm_operator_rank_checkpoint_mismatch")
    rows=body.get("rows") or {}
    if not isinstance(rows,dict): raise RuntimeError("dlmm_operator_rank_checkpoint_shape")
    return rows


def _write_rank_checkpoint(signature,rows,failures,started):
    _atomic_json(RANK_CHECKPOINT,dict(
        kind="dlmm_profitable_operator_rank_checkpoint_v1",
        status=("complete" if len(rows)==len(signature["wallets"]) and not failures else "partial"),
        signature=signature,started_at=started,updated_at=int(time.time()),
        completed_wallets=len(rows),failed_wallets=len(failures),
        rows=rows,failures=failures,
    ))


def rank(cohort_path=DEFAULT_COHORT):
    cohort=json.loads(Path(cohort_path).read_text())
    if cohort.get("kind")!="dlmm_profitable_operator_cohort_v1" or cohort.get("status")!="frozen_pre_pnl":
        raise RuntimeError("dlmm_operator_cohort_not_frozen")
    if cohort.get("pnl_data_read_before_freeze") is not False:
        raise RuntimeError("dlmm_operator_pnl_leakage")
    signature=_rank_signature(cohort);rows=_load_rank_checkpoint(signature)
    failures={};started=int(time.time())
    pending=[w for w in signature["wallets"] if w not in rows]
    workers=int(os.environ.get("DLMM_OPERATOR_METEORA_WORKERS",DEFAULT_METEORA_WORKERS))
    if not 1<=workers<=MAX_METEORA_WORKERS:
        raise RuntimeError("dlmm_operator_worker_bound")
    _write_rank_checkpoint(signature,rows,failures,started)
    with ThreadPoolExecutor(max_workers=min(workers,max(1,len(pending))),
                            thread_name_prefix="dlmm-operator") as executor:
        future_map={executor.submit(_wallet_rank_row,w):w for w in pending}
        for future in as_completed(future_map):
            wallet=future_map[future]
            try:
                rows[wallet]=future.result();state="completed"
            except Exception as exc:
                failures[wallet]=dict(error=type(exc).__name__);state="failed"
            _write_rank_checkpoint(signature,rows,failures,started)
            print(json.dumps(dict(phase="wallet_rank",wallet=wallet,state=state,
                                  completed=len(rows),failed=len(failures),
                                  total=len(signature["wallets"])),sort_keys=True),flush=True)
    if failures:
        raise RuntimeError(f"dlmm_operator_rank_incomplete:{len(failures)}")

    data=list(rows.values())
    eligible=[r for r in data if
              r["measured_closed_positions"]>=MIN_CLOSED_POSITIONS and
              r["distinct_pools"]>=MIN_DISTINCT_POOLS and
              r["api_realized_pnl_usd"]>0]
    def ordered(key,reverse=True):
        valid=[r for r in eligible if r.get(key) is not None]
        return sorted(valid,key=lambda r:(((-r[key]) if reverse else r[key]),r["wallet"]))
    ranking_specs={
        "absolute_pnl_usd":("api_realized_pnl_usd",True),
        "gross_pnl_per_capital_hour":("gross_pnl_per_capital_hour",True),
        "profitable_position_rate":("profitable_position_rate",True),
        "max_realized_drawdown_usd":("max_realized_drawdown_usd",False),
        "profitable_active_week_rate":("profitable_active_week_rate",True),
    }
    rankings={
        name:ordered(row_key,reverse=descending)
        for name,(row_key,descending) in ranking_specs.items()
    }
    candidate=set()
    for name,ranking in rankings.items():
        if not ranking: continue
        row_key,descending=ranking_specs[name]
        cutoff=min(TOP_PER_RANK,len(ranking))
        value=ranking[cutoff-1][row_key]
        for row in ranking:
            better=(row[row_key]>=value if descending else row[row_key]<=value)
            if better: candidate.add(row["wallet"])
    report=dict(
        kind="dlmm_profitable_operator_ranking_v1",
        status="gross_capital_efficiency_complete_network_cost_pending",
        protocol_sha256=signature["protocol_sha256"],
        cohort_hash=signature["cohort_hash"],wallet_count=len(data),
        eligible_wallet_count=len(eligible),candidate_wallets=sorted(candidate),
        ranking_metrics={
            name:[dict(wallet=r["wallet"],value=r[ranking_specs[name][0]],
                       positions=r["measured_closed_positions"],
                       pools=r["distinct_pools"]) for r in ranking]
            for name,ranking in rankings.items()
        },
        all_wallets=data,
        note=("Network execution-cost and final after-cost capital-efficiency ranking "
              "are intentionally deferred to authenticated on-chain deep reconstruction."),
    )
    _atomic_json(RANK_OUT,report)
    print(json.dumps(dict(wallets=len(data),eligible=len(eligible),
                          candidates=len(candidate)),sort_keys=True))
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("phase",choices=("census","rank"))
    p.add_argument("--cohort",default=str(DEFAULT_COHORT))
    args=p.parse_args()
    if args.phase=="census": census()
    else: rank(Path(args.cohort))


if __name__=="__main__":
    main()
