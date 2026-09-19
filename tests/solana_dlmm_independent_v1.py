"""Independent Solana Meteora DLMM strategy v1.

Strategy decisions consume only:
- frozen SOLANA_DLMM_INDEPENDENT_V1.json,
- Solana-mainnet Meteora public pool metrics,
- authenticated Solana DLMM state/tapes.

No prior DLMM strategy, wallet strategy, Robinhood, Pons, or Ramses strategy is an
input. Shared code is limited to generic DLMM integer mechanics and Solana provider
transport.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
import urllib.parse
import urllib.request

from meme_machine import dlmm
from meme_machine.dlmm_tape import (
    MAX_TRANSACTIONS,
    apply_external_adjustment,
    chain_verified_tapes,
    ordered_tape_actions,
    reconstruct,
    replay_swap_event,
)
from meme_machine.provider import Unavailable
from meme_machine.store import encode
from tests import dlmm_alchemy_provider as provider

POLICY_PATH=Path("SOLANA_DLMM_INDEPENDENT_V1.json")
OUT=Path("solana-dlmm-independent-v1-live.json")
API_BASE="https://dlmm.datapi.meteora.ag"

CAPITAL=100_000_000
ENTRY_NETWORK_COST=200_000
EXIT_NETWORK_COST=200_000
ROUND_TRIP_NETWORK_COST=ENTRY_NETWORK_COST+EXIT_NETWORK_COST

DISCOVERY_PAGE_SIZE=250
DISCOVERY_PAGES_PER_SORT=2
DISCOVERY_SORTS=("volume_5m:desc","fee_tvl_ratio_5m:desc","volume_30m:desc")
PER_RPC_LIMIT=240
ROTATE_AT_CALLS=190
CHUNK_SECONDS=2
MAX_WARMUP_RESETS=2


def assert_independence():
    bad_env=sorted(k for k in os.environ if k.startswith("MM_ROBINHOOD_"))
    if bad_env:
        raise RuntimeError("solana_dlmm_robinhood_config_forbidden:"+",".join(bad_env))
    forbidden=("robinhood","pons","ramses")
    imported=[
        name for name in sys.modules
        if any(part in forbidden for part in name.lower().split("."))
    ]
    if imported:
        raise RuntimeError("solana_dlmm_forbidden_strategy_import:"+",".join(sorted(imported)))


def load_policy():
    p=json.loads(POLICY_PATH.read_text())
    if p.get("kind")!="solana_dlmm_independent_v1":
        raise RuntimeError("solana_dlmm_policy_kind")
    if p.get("status")!="frozen_pre_prospective":
        raise RuntimeError("solana_dlmm_policy_not_frozen")
    independence=p.get("independence") or {}
    for key in (
        "wallet_signals","profitable_wallet_labels","prior_dlmm_candidate_outputs",
        "small_pool_study_outputs","capital_efficiency_v1_outputs",
        "robinhood_strategies","pons_strategies","ramses_strategies",
        "robinhood_data","robinhood_provider_config",
    ):
        if independence.get(key) is not False:
            raise RuntimeError("solana_dlmm_independence_drift:"+key)
    if p.get("authority",{}).get("allocation") is not False:
        raise RuntimeError("solana_dlmm_authority")
    if int(p["position"]["capital_lamports"])!=CAPITAL:
        raise RuntimeError("solana_dlmm_capital_drift")
    if int(p["costs"]["round_trip_network_cost_lamports"])!=ROUND_TRIP_NETWORK_COST:
        raise RuntimeError("solana_dlmm_cost_drift")
    return p


def _api(path,params=None):
    if not path.startswith("/"):
        raise ValueError("solana_dlmm_api_path")
    url=API_BASE+path
    if params:
        url+="?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={
        "Accept":"application/json",
        "User-Agent":"meme-machine-solana-dlmm-independent-v1/1",
    })
    with urllib.request.urlopen(req,timeout=20) as response:
        if response.status!=200:
            raise RuntimeError(f"solana_dlmm_api_http:{response.status}")
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:
        raise RuntimeError("solana_dlmm_api_response_bound")
    return json.loads(raw)


def _num(value):
    try:
        x=float(value)
    except (TypeError,ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def _accel(short_value,long_value,long_multiple):
    short=max(0.0,_num(short_value));long=max(0.0,_num(long_value))
    baseline=long/float(long_multiple)
    if baseline<=0:
        return 99.0 if short>0 else 0.0
    return min(99.0,short/baseline)


def _sol_pair(row):
    x=(row.get("token_x") or {}).get("address")
    y=(row.get("token_y") or {}).get("address")
    return (x==dlmm.WSOL) ^ (y==dlmm.WSOL)


def _candidate(row):
    volume=row.get("volume") or {};fees=row.get("fees") or {}
    ratio=row.get("fee_tvl_ratio") or {}
    v5=_num(volume.get("5m"));v30=_num(volume.get("30m"))
    f5=_num(fees.get("5m"));f30=_num(fees.get("30m"))
    vacc=_accel(v5,v30,6);facc=_accel(f5,f30,6)
    density=max(0.0,_num(ratio.get("5m")))
    return dict(
        address=row.get("address"),name=row.get("name"),
        token_x=(row.get("token_x") or {}).get("address"),
        token_y=(row.get("token_y") or {}).get("address"),
        tvl_usd=_num(row.get("tvl")),
        volume_5m_usd=v5,volume_30m_usd=v30,
        fee_5m_usd=f5,fee_30m_usd=f30,
        fee_tvl_ratio_5m=density,
        dynamic_fee_pct=_num(row.get("dynamic_fee_pct")),
        volume_acceleration=vacc,fee_acceleration=facc,
        event_score=math.log1p(v5)*max(vacc,0.01)*max(facc,0.01)*max(density,1e-12),
    )


def discover(policy,scan_cap):
    merged={};errors=[]
    for sort_by in DISCOVERY_SORTS:
        for page in range(1,DISCOVERY_PAGES_PER_SORT+1):
            try:
                payload=_api("/pools",dict(
                    page=page,page_size=DISCOVERY_PAGE_SIZE,
                    sort_by=sort_by,filter_by="is_blacklisted=false",
                ))
            except Exception as exc:
                errors.append(dict(sort=sort_by,page=page,reason=type(exc).__name__))
                break
            rows=payload.get("data") if isinstance(payload,dict) else None
            if not isinstance(rows,list):
                errors.append(dict(sort=sort_by,page=page,reason="api_shape"))
                break
            for raw_rank,row in enumerate(rows,1):
                if not isinstance(row,dict) or not _sol_pair(row):
                    continue
                address=row.get("address")
                if not isinstance(address,str) or not address:
                    continue
                item=merged.get(address)
                if item is None:
                    item=_candidate(row);item["sources"]=[];merged[address]=item
                item["sources"].append(dict(
                    sort=sort_by,rank=(page-1)*DISCOVERY_PAGE_SIZE+raw_rank))
            if len(rows)<DISCOVERY_PAGE_SIZE:
                break

    regime=policy["regime"];accepted=[];rejected=[]
    for item in merged.values():
        failed=[]
        if item["volume_acceleration"]<float(regime["min_volume_acceleration"]):
            failed.append("volume_acceleration")
        if item["fee_acceleration"]<float(regime["min_fee_acceleration"]):
            failed.append("fee_acceleration")
        if failed:
            rejected.append(dict(pool=item["address"],failed=failed,candidate=item))
        else:
            accepted.append(item)
    accepted.sort(key=lambda x:(-x["event_score"],x["address"]))
    return accepted[:scan_cap],rejected,errors


def _rpc_metrics(rpc):
    return dict(
        calls=int(rpc.calls),http_requests=int(rpc.http_requests),
        failures=int(rpc.failures),retries=int(rpc.retries),
    )


def _sum_rpc_metrics(rpcs):
    return dict(
        calls=sum(int(r.calls) for r in rpcs),
        http_requests=sum(int(r.http_requests) for r in rpcs),
        failures=sum(int(r.failures) for r in rpcs),
        retries=sum(int(r.retries) for r in rpcs),
    )


def _new_adapter(pacer,rpcs):
    rpc=provider.new_rpc(limit=PER_RPC_LIMIT,pacer=pacer)
    rpcs.append(rpc)
    return dlmm.Adapter(rpc)


def _rotate(adapter,pacer,rpcs):
    return adapter if int(adapter.rpc.calls)<ROTATE_AT_CALLS else _new_adapter(pacer,rpcs)


def _fresh_supported_start(adapter,candidate):
    snap=adapter.snapshot(candidate["address"],int(time.time()),True,fresh=True)
    state=dlmm.validate(snap,snap["available_time"],"real")
    dlmm.scout(snap,snap["available_time"],dict(
        pool=candidate["address"],x=candidate["token_x"],y=candidate["token_y"]))
    return state


def _capture_chunk(adapter,start,cursor,wait_seconds):
    if wait_seconds<=0:
        raise ValueError("solana_dlmm_chunk_wait")
    time.sleep(wait_seconds)
    end_snapshot=adapter.snapshot_from_state(
        start,int(time.time()),True,fresh=True)
    signatures=adapter.rpc.call(
        "getSignaturesForAddress",
        [start["pool"],dict(limit=64,commitment="finalized")],True)
    if not isinstance(signatures,list):
        raise Unavailable("solana_dlmm_signature_shape")
    if not any(isinstance(s,dict) and isinstance(s.get("slot"),int)
               and s["slot"]<=start["slot"] for s in signatures):
        raise Unavailable("solana_dlmm_signature_census_missing_start_boundary")
    relevant=[
        s for s in signatures
        if isinstance(s,dict) and not s.get("err")
        and isinstance(s.get("slot"),int)
        and start["slot"]<s["slot"]<=end_snapshot["slot"]
    ]
    if len(relevant)>MAX_TRANSACTIONS:
        raise Unavailable("solana_dlmm_transaction_pressure_overflow")
    params=[[
        s["signature"],dict(
            encoding="json",commitment="finalized",
            maxSupportedTransactionVersion=1)
    ] for s in relevant]
    values=(adapter.rpc.call_many(
        "getTransaction",params,True,batch_size=8) if params else [])
    transactions={s["signature"]:tx for s,tx in zip(relevant,values)}
    if len(encode(transactions))>2_000_000:
        raise Unavailable("solana_dlmm_interval_evidence_bound")
    tape=reconstruct(
        start,end_snapshot,signatures,transactions,int(time.time()),cursor)
    actions=ordered_tape_actions(tape)
    next_cursor=(list(actions[-1][1].get("cursor") or cursor)
                 if actions else list(cursor))
    return tape,next_cursor


def _observe_window(adapter,address,start,total_seconds,allow_reset,pacer,rpcs):
    origin=start;current=start
    cursor=[start["slot"],2**31-1,2**31-1]
    chunks=[];elapsed=0;resets=0;meta=[]
    while elapsed<total_seconds:
        adapter=_rotate(adapter,pacer,rpcs)
        duration=min(CHUNK_SECONDS,total_seconds-elapsed)
        try:
            tape,cursor=_capture_chunk(adapter,current,cursor,duration)
        except (Unavailable,ValueError,KeyError,TypeError) as exc:
            reason=str(exc)
            if (allow_reset and reason.startswith("dlmm_snapshot_reset_required:")
                    and resets<MAX_WARMUP_RESETS):
                adapter=_rotate(adapter,pacer,rpcs)
                fresh=dlmm.validate(
                    adapter.snapshot(address,int(time.time()),True,fresh=True),
                    int(time.time()),"real")
                origin=fresh;current=fresh
                cursor=[fresh["slot"],2**31-1,2**31-1]
                chunks=[];meta=[];elapsed=0;resets+=1
                continue
            return dict(
                verified=False,reason=reason,elapsed_seconds=elapsed,
                resets=resets,chunks=meta,
            ),None,current,origin,adapter
        chunks.append(tape);current=tape.terminal;elapsed+=duration
        meta.append(dict(
            start_slot=tape.events[0]["previous_cursor"][0]
                if tape.events else None,
            end_slot=current["slot"],swaps=len(tape.events),
            adjustments=len(tape.terminal_adjustments),
        ))
    combined=chain_verified_tapes(origin,chunks)
    return dict(
        verified=True,elapsed_seconds=elapsed,resets=resets,chunks=meta,
        swaps=len(combined.events),lineage=combined.lineage,
    ),combined,current,origin,adapter


def _to_sol(state,amount,token,bin_id):
    if amount<=0:return 0
    if token==dlmm.WSOL:return int(amount)
    p=dlmm.price(bin_id,state["step"])
    if state["y"]==dlmm.WSOL:
        return int(amount)*p//dlmm.Q
    return int(amount)*dlmm.Q//p


def _event_volume_sol(start,event):
    bid=event["observed"]["start"]
    token=start["x"] if event["for_y"] else start["y"]
    return _to_sol(start,event["amount"],token,bid)


def _event_fee_sol(start,event):
    bid=event["observed"]["start"]
    token=start["x"] if event["for_y"] else start["y"]
    return _to_sol(start,event["observed"]["fee"],token,bid)


def _base_fee_bps(state):
    s=state["parameters"]
    raw=s["base_factor"]*state["step"]*10*10**s["base_fee_power_factor"]
    return raw*10000/dlmm.FEE_PRECISION


def _current_fee_bps(state):
    return dlmm.total_fee(state)*10000/dlmm.FEE_PRECISION


def _fee_uplift(state):
    base=_base_fee_bps(state)
    return (99.0 if base<=0 and _current_fee_bps(state)>0
            else 0.0 if base<=0 else _current_fee_bps(state)/base)


def _movement_half_width(warm,entry,policy):
    r=policy["range"];center=int(entry["active"])
    observed=[]
    for e in warm.events:
        observed.extend([int(e["observed"]["start"]),int(e["observed"]["end"])])
    excursion=max([abs(x-center) for x in observed] or [1])
    scaled=excursion*math.sqrt(
        float(r["intended_holding_seconds"])/float(r["warmup_seconds"]))
    half=int(math.ceil(scaled*float(r["movement_safety_factor"])))
    return max(int(r["min_half_width_bins"]),
               min(int(r["max_half_width_bins"]),half))


def _centered_ids(state,half):
    active=int(state["active"])
    lower=list(range(active-half,active))
    upper=list(range(active+1,active+half+1))
    ids=lower+upper
    if any(str(bid) not in state["bins"] for bid in ids):
        raise Unavailable("solana_dlmm_missing_centered_range_bin")
    return lower,upper


def _range_liquidity_sol(state,ids):
    total=0
    for bid in ids:
        b=state["bins"][str(bid)]
        total+=_to_sol(state,b["x"],state["x"],bid)
        total+=_to_sol(state,b["y"],state["y"],bid)
    return total


def _range_flow_features(start,tape,lower,upper,liquidity_state=None):
    lower_edge=min(lower+upper);upper_edge=max(lower+upper)
    ids=lower+upper
    liquidity_state=start if liquidity_state is None else liquidity_state
    range_liquidity=_range_liquidity_sol(liquidity_state,ids)
    total_volume=total_fee=0
    direction={True:0,False:0}
    movement=[];travel=0
    start_bin=None;end_bin=None
    touches=0
    for event in tape.events:
        s=int(event["observed"]["start"]);e=int(event["observed"]["end"])
        lo,hi=sorted((s,e))
        if hi<lower_edge or lo>upper_edge:
            continue
        touches+=1
        volume=_event_volume_sol(start,event)
        fee=_event_fee_sol(start,event)
        total_volume+=volume;total_fee+=fee
        direction[bool(event["for_y"])]+=volume
        travel+=abs(e-s)
        if start_bin is None:start_bin=s
        end_bin=e
        if e!=s:movement.append(1 if e>s else -1)
    directional=sum(direction.values())
    balance=(0.0 if directional<=0 else
             2*min(direction.values())/directional)
    reversals=sum(a!=b for a,b in zip(movement,movement[1:]))
    drift=(0.0 if travel<=0 or start_bin is None or end_bin is None
           else abs(end_bin-start_bin)/travel)
    seconds=max(1,int(tape.terminal["time"])-int(start["time"]))
    return dict(
        touch_swaps=touches,range_liquidity_sol_lamports=range_liquidity,
        range_volume_sol_lamports=total_volume,
        range_fee_sol_lamports=total_fee,
        volume_rate_sol_lamports_per_second=total_volume/seconds,
        fee_rate_sol_lamports_per_second=total_fee/seconds,
        volume_to_active_liquidity=(
            0.0 if range_liquidity<=0 else total_volume/range_liquidity),
        fee_density=(
            0.0 if range_liquidity<=0 else total_fee/range_liquidity),
        two_way_balance=balance,reversal_count=reversals,
        travel_bins=travel,drift_ratio=drift,
        observed_seconds=seconds,
    )


def _stress_roundtrip(entry,fraction):
    sol_input=max(1,int(CAPITAL*float(fraction)))
    sol_is_x=entry["x"]==dlmm.WSOL
    post,quote=dlmm.swap(
        deepcopy(entry),sol_input,sol_is_x,int(entry["time"]))
    token=int(quote["output"])
    _,back=dlmm.swap(
        deepcopy(post),token,not sol_is_x,int(entry["time"]))
    output=int(back["output"])
    loss=max(0,sol_input-output)
    return dict(
        sol_input_lamports=sol_input,token_output_raw=token,
        executable_sol_back_lamports=output,
        loss_lamports=loss,loss_bps=loss*10000/sol_input,
    )


def pre_entry_features(warm_start,warm,entry,candidate,policy):
    half=_movement_half_width(warm,entry,policy)
    lower,upper=_centered_ids(entry,half)
    flow=_range_flow_features(
        warm_start,warm,lower,upper,liquidity_state=entry)
    q=policy["qualification"]
    liquidity=flow["range_liquidity_sol_lamports"]
    capture_share=(
        0.0 if liquidity<=0 else CAPITAL/(liquidity+CAPITAL))
    projected=(
        flow["range_fee_sol_lamports"]*capture_share
        *float(q["projected_fee_horizon_seconds"])
        /max(1,float(flow["observed_seconds"]))
    )
    stress=_stress_roundtrip(entry,q["stress_inventory_fraction_of_capital"])
    expected_net=projected-ROUND_TRIP_NETWORK_COST-stress["loss_lamports"]
    hours=float(policy["range"]["intended_holding_seconds"])/3600.0
    return dict(
        half_width_bins=half,total_width_bins=half*2,
        lower=min(lower),upper=max(upper),
        range_lower_bins=lower,range_upper_bins=upper,
        capital_to_competing_liquidity_ratio=(
            None if liquidity<=0 else CAPITAL/liquidity),
        competing_liquidity_to_capital_multiple=liquidity/CAPITAL,
        estimated_fee_capture_share=capture_share,
        projected_fee_capture_lamports=projected,
        stress_inventory_roundtrip=stress,
        expected_net_lamports=expected_net,
        expected_after_cost_pnl_bps_per_capital_hour=(
            expected_net/CAPITAL*10000/hours),
        current_fee_bps=_current_fee_bps(entry),
        base_fee_bps=_base_fee_bps(entry),
        dynamic_fee_uplift=_fee_uplift(entry),
        volume_acceleration=candidate["volume_acceleration"],
        fee_acceleration=candidate["fee_acceleration"],
        **flow,
    )


def qualify(features,policy):
    r=policy["regime"];q=policy["qualification"]
    checks=dict(
        volume_acceleration=features["volume_acceleration"]>=float(
            r["min_volume_acceleration"]),
        fee_acceleration=features["fee_acceleration"]>=float(
            r["min_fee_acceleration"]),
        dynamic_fee=features["dynamic_fee_uplift"]>=float(
            r["min_dynamic_fee_uplift_over_base"]),
        capacity=features["competing_liquidity_to_capital_multiple"]>=float(
            q["min_competing_range_liquidity_to_capital_multiple"]),
        two_way=features["two_way_balance"]>=float(q["min_two_way_balance"]),
        drift=features["drift_ratio"]<=float(q["max_drift_ratio"]),
        reversal=(not q["require_reversal"] or features["reversal_count"]>0),
        unwind=features["stress_inventory_roundtrip"]["loss_bps"]<=float(
            q["max_stress_unwind_loss_bps"]),
        expected_net=features["expected_net_lamports"]>=int(
            q["min_expected_net_lamports"]),
    )
    return dict(
        passes=all(checks.values()),checks=checks,
        failed=[k for k,v in checks.items() if not v],
        rule="solana_dlmm_independent_v1",fitted_thresholds=False,
    )


def _equal_split(total,count):
    if count<=0:raise ValueError("solana_dlmm_split_count")
    rows=[total//count]*count
    rows[-1]+=total-sum(rows)
    return rows


def _build_position(entry,features,policy):
    half=int(features["half_width_bins"])
    conversion=int(CAPITAL*float(policy["position"]["sol_share_before_conversion"]))
    remaining=CAPITAL-conversion
    sol_is_x=entry["x"]==dlmm.WSOL
    virtual,quote=dlmm.swap(
        deepcopy(entry),conversion,sol_is_x,int(entry["time"]))
    if int(virtual["active"])!=int(entry["active"]):
        raise Unavailable("solana_dlmm_entry_conversion_moves_active_bin")
    token=int(quote["output"])
    lower,upper=_centered_ids(virtual,half)
    sol_bins=(upper if sol_is_x else lower)
    token_bins=(lower if sol_is_x else upper)
    sol_amounts=_equal_split(remaining,len(sol_bins))
    token_amounts=_equal_split(token,len(token_bins))
    shares={};fee_start={}
    deposits=[]
    for bid,amount in zip(sol_bins,sol_amounts):
        b=virtual["bins"][str(bid)]
        x,y=(amount,0) if sol_is_x else (0,amount)
        if x and b["y"] or y and b["x"]:
            raise Unavailable("solana_dlmm_sol_side_bin_composition")
        share=dlmm.deposit_share(b,x,y)
        if share<=0:raise Unavailable("solana_dlmm_zero_sol_side_share")
        shares[str(bid)]=share;fee_start[str(bid)]={"x":b["fee_x"],"y":b["fee_y"]}
        b["x"]+=x;b["y"]+=y;b["supply"]+=share
        deposits.append(dict(bin=bid,x=x,y=y))
    for bid,amount in zip(token_bins,token_amounts):
        b=virtual["bins"][str(bid)]
        x,y=(0,amount) if sol_is_x else (amount,0)
        if x and b["y"] or y and b["x"]:
            raise Unavailable("solana_dlmm_token_side_bin_composition")
        share=dlmm.deposit_share(b,x,y)
        if share<=0:raise Unavailable("solana_dlmm_zero_token_side_share")
        shares[str(bid)]=share;fee_start[str(bid)]={"x":b["fee_x"],"y":b["fee_y"]}
        b["x"]+=x;b["y"]+=y;b["supply"]+=share
        deposits.append(dict(bin=bid,x=x,y=y))
    return dict(
        lower=min(lower+upper),upper=max(lower+upper),half_width=half,
        shares=shares,fee_start=fee_start,virtual=virtual,
        entry_active=virtual["active"],entry_slot=entry["slot"],
        entry_time=entry["time"],entry_conversion_sol_lamports=conversion,
        entry_conversion_token_raw=token,deposits=deposits,
    )


def _advance_position(position,tape):
    p=deepcopy(position);state=deepcopy(p["virtual"])
    for kind,item in ordered_tape_actions(tape):
        if kind=="swap":
            state,_=replay_swap_event(state,item)
        else:
            state=apply_external_adjustment(state,item,counterfactual=True)
        if isinstance(item.get("slot"),int):state["slot"]=max(state["slot"],item["slot"])
        if isinstance(item.get("time"),int):state["time"]=max(state["time"],item["time"])
    state["slot"]=tape.terminal["slot"];state["time"]=tape.terminal["time"]
    p["virtual"]=state
    return p


def _withdraw(position):
    state=deepcopy(position["virtual"])
    assets={"x":0,"y":0,"fee_x":0,"fee_y":0}
    for bid,share in position["shares"].items():
        b=state["bins"][bid]
        x=dlmm.withdraw_amount(share,b["x"],b["supply"])
        y=dlmm.withdraw_amount(share,b["y"],b["supply"])
        start=position["fee_start"][bid]
        fx=dlmm.claim_fee(share,b["fee_x"]-start["x"])
        fy=dlmm.claim_fee(share,b["fee_y"]-start["y"])
        for k,v in (("x",x),("y",y),("fee_x",fx),("fee_y",fy)):
            assets[k]+=v
        b["x"]-=x;b["y"]-=y;b["supply"]-=share
    return state,assets


def _mark(position):
    state,assets=_withdraw(position)
    sol_side="x" if state["x"]==dlmm.WSOL else "y"
    token_side="y" if sol_side=="x" else "x"
    sol=assets[sol_side]+assets["fee_"+sol_side]
    tokens=assets[token_side]+assets["fee_"+token_side]
    liquidation=0
    if tokens:
        _,quote=dlmm.swap(
            deepcopy(state),tokens,sol_side=="y",int(state["time"]))
        liquidation=int(quote["output"]);sol+=liquidation
    pnl=sol-CAPITAL-ROUND_TRIP_NETWORK_COST
    return dict(
        resolved=True,ending_sol_lamports=sol,pnl_lamports=pnl,
        pnl_bps=pnl*10000/CAPITAL,
        non_sol_inventory_raw=tokens,
        non_sol_inventory_liquidation_lamports=liquidation,
        non_sol_inventory_fraction_of_initial_capital=liquidation/CAPITAL,
        active_bin=state["active"],time=state["time"],slot=state["slot"],
    )


def _segment_exit(position,real_start,tape,real_terminal,entry_flow,policy):
    exit_policy=policy["exit"]
    lower=list(range(position["lower"],position["entry_active"]))
    upper=list(range(position["entry_active"]+1,position["upper"]+1))
    recent=_range_flow_features(real_start,tape,lower,upper)
    mark=_mark(position)
    active=int(real_terminal["active"])
    boundary=(active<=position["lower"]+2 or active>=position["upper"]-2)
    inventory=mark["non_sol_inventory_fraction_of_initial_capital"]>0.60
    directional=(
        recent["touch_swaps"]>=2
        and recent["two_way_balance"]<0.25
        and recent["drift_ratio"]>0.75
    )
    volume_collapse=(
        recent["touch_swaps"]>=2
        and recent["volume_rate_sol_lamports_per_second"]
            <0.50*entry_flow["volume_rate_sol_lamports_per_second"]
    )
    fee_collapse=(
        recent["touch_swaps"]>=2
        and recent["fee_density"]<0.50*entry_flow["fee_density"]
    )
    fee_uplift=_fee_uplift(real_terminal)
    dynamic_fee_collapse=(
        fee_uplift<1.05
        and recent["volume_rate_sol_lamports_per_second"]
            <entry_flow["volume_rate_sol_lamports_per_second"]
    )
    reasons=[]
    if boundary:reasons.append("range_boundary")
    if inventory:reasons.append("inventory_imbalance")
    if directional:reasons.append("one_way_flow")
    if volume_collapse:reasons.append("volume_collapse")
    if fee_collapse:reasons.append("fee_density_collapse")
    if dynamic_fee_collapse:reasons.append("dynamic_fee_collapse")
    return reasons,recent,mark,fee_uplift


def _lifecycle(adapter,address,entry,features,policy,pacer,rpcs):
    position=_build_position(entry,features,policy)
    current=entry;elapsed=0;segments=[];tapes=[]
    max_hold=int(policy["range"]["max_holding_seconds"])
    segment_seconds=int(policy["exit"]["observation_segment_seconds"])
    lower=list(range(features["lower"],entry["active"]))
    upper=list(range(entry["active"]+1,features["upper"]+1))
    entry_flow=dict(
        volume_rate_sol_lamports_per_second=features[
            "volume_rate_sol_lamports_per_second"],
        fee_density=features["fee_density"],
    )
    exit_reason="maximum_holding_time"
    while elapsed<max_hold:
        adapter=_rotate(adapter,pacer,rpcs)
        duration=min(segment_seconds,max_hold-elapsed)
        phase,tape,terminal,effective_start,adapter=_observe_window(
            adapter,address,current,duration,False,pacer,rpcs)
        if not phase["verified"]:
            return dict(
                complete=False,reason=phase["reason"],segments=segments,
                verified_hold_seconds=elapsed,
            ),adapter
        position=_advance_position(position,tape)
        reasons,recent,mark,uplift=_segment_exit(
            position,effective_start,tape,terminal,entry_flow,policy)
        elapsed+=duration;tapes.append(tape)
        segments.append(dict(
            elapsed_seconds=elapsed,lineage=tape.lineage,
            swaps=len(tape.events),recent=recent,mark=mark,
            dynamic_fee_uplift=uplift,exit_reasons=reasons,
        ))
        current=terminal
        if reasons:
            exit_reason=reasons[0];break
    combined=chain_verified_tapes(entry,tapes)
    final=_mark(position)
    hours=max(elapsed/3600.0,1/3600.0)
    final["pnl_bps_per_capital_hour"]=final["pnl_bps"]/hours
    return dict(
        complete=True,exit_reason=exit_reason,realized_hold_seconds=elapsed,
        segments=segments,lineage=combined.lineage,final=final,
    ),adapter


def run_live(target=None,max_attempted=None):
    assert_independence()
    policy=load_policy()
    target=int(target or policy["prospective_test"]["target_complete_lifecycles"])
    max_attempted=int(max_attempted or policy["prospective_test"]["max_attempted_pools"])
    if not 1<=target<=int(policy["prospective_test"]["target_complete_lifecycles"]):
        raise ValueError("solana_dlmm_target_bound")
    if not target<=max_attempted<=int(policy["prospective_test"]["max_attempted_pools"]):
        raise ValueError("solana_dlmm_attempt_bound")

    candidates,api_rejections,api_errors=discover(policy,max_attempted*4)
    pacer=provider.AlchemyPacer();rpcs=[]
    report=dict(
        kind="solana_dlmm_independent_v1_prospective",
        policy_revision=policy.get("revision"),frozen_policy=policy,
        allocation_authority=False,signing=False,submission=False,live_money=False,
        independent_of_robinhood=True,independent_of_all_prior_dlmm_strategies=True,
        selector_uses_outcome_data=False,post_freeze_only=True,
        discovery_candidates=candidates,discovery_api_rejections=api_rejections,
        discovery_errors=api_errors,target_complete_lifecycles=target,
        max_attempted_pools=max_attempted,started=int(time.time()),
        attempts=[],qualified_lifecycles=[],
    )
    attempted=0;complete=0;failure_counts=Counter()
    for candidate in candidates:
        if attempted>=max_attempted or complete>=target:break
        attempted+=1
        candidate_rpcs=[]
        adapter=_new_adapter(pacer,candidate_rpcs);rpcs.extend(candidate_rpcs)
        attempt=dict(attempt=attempted,pool=candidate["address"],candidate=candidate)
        try:
            entry_start=_fresh_supported_start(adapter,candidate)
            phase,warm,entry,warm_origin,adapter=_observe_window(
                adapter,candidate["address"],entry_start,
                int(policy["range"]["warmup_seconds"]),True,pacer,candidate_rpcs)
            # Any rotated RPCs created inside observation are not yet in global list.
            for rpc in candidate_rpcs:
                if rpc not in rpcs:rpcs.append(rpc)
            attempt["warmup"]=phase
            if not phase["verified"]:
                attempt["terminal_classification"]="warmup_unverified"
                attempt["reason"]=phase["reason"]
                failure_counts["warmup_unverified"]+=1
                attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
                report["attempts"].append(attempt);continue
            if not warm.events:
                attempt["terminal_classification"]="no_warmup_flow"
                failure_counts["no_warmup_flow"]+=1
                attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
                report["attempts"].append(attempt);continue
            features=pre_entry_features(warm_origin,warm,entry,candidate,policy)
            decision=qualify(features,policy)
            attempt["pre_entry_features"]=features
            attempt["qualification"]=decision
            for failed in decision["failed"]:failure_counts[failed]+=1
            if not decision["passes"]:
                attempt["terminal_classification"]="qualification_rejection"
                attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
                report["attempts"].append(attempt);continue
            lifecycle,adapter=_lifecycle(
                adapter,candidate["address"],entry,features,policy,pacer,candidate_rpcs)
            for rpc in candidate_rpcs:
                if rpc not in rpcs:rpcs.append(rpc)
            attempt["lifecycle"]=lifecycle
            attempt["terminal_classification"]=(
                "complete" if lifecycle["complete"] else "lifecycle_unverified")
            attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
            report["attempts"].append(attempt)
            if lifecycle["complete"]:
                complete+=1
                report["qualified_lifecycles"].append(dict(
                    pool=candidate["address"],candidate=candidate,
                    pre_entry_features=features,qualification=decision,**lifecycle))
            else:
                failure_counts["lifecycle_unverified"]+=1
        except (Unavailable,ValueError,KeyError,TypeError,OverflowError) as exc:
            attempt["terminal_classification"]="exception"
            attempt["reason"]=str(exc)[:200]
            failure_counts["exception"]+=1
            attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
            report["attempts"].append(attempt)

    resolved=[x for x in report["qualified_lifecycles"]
              if (x.get("final") or {}).get("resolved")]
    pnl=[x["final"]["pnl_bps"] for x in resolved]
    capital_hour=[x["final"]["pnl_bps_per_capital_hour"] for x in resolved]
    exits=Counter(x["exit_reason"] for x in resolved)
    report.update(
        ended=int(time.time()),attempted_pool_count=attempted,
        complete_lifecycle_count=complete,target_met=complete>=target,
        qualification_failure_counts=dict(sorted(failure_counts.items())),
        profitable_lifecycle_count=sum(x["final"]["pnl_lamports"]>0 for x in resolved),
        profitable_rate=(None if not resolved else
                         sum(x["final"]["pnl_lamports"]>0 for x in resolved)/len(resolved)),
        median_pnl_bps=(None if not pnl else statistics.median(pnl)),
        mean_pnl_bps=(None if not pnl else statistics.fmean(pnl)),
        median_pnl_bps_per_capital_hour=(
            None if not capital_hour else statistics.median(capital_hour)),
        mean_pnl_bps_per_capital_hour=(
            None if not capital_hour else statistics.fmean(capital_hour)),
        exit_reason_counts=dict(sorted(exits.items())),
        rpc=_sum_rpc_metrics(rpcs),alchemy_pacer=pacer.telemetry(),
        conclusion=(
            "prospective_target_complete"
            if complete>=target else "prospective_sample_incomplete_no_threshold_change"),
    )
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(
        conclusion=report["conclusion"],attempted=attempted,complete=complete,
        profitable_rate=report["profitable_rate"],
        median_pnl_bps=report["median_pnl_bps"],
        median_pnl_bps_per_capital_hour=report[
            "median_pnl_bps_per_capital_hour"],
        failures=report["qualification_failure_counts"],
        exits=report["exit_reason_counts"],
    ),sort_keys=True))
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--target-complete",type=int)
    p.add_argument("--max-attempted",type=int)
    args=p.parse_args()
    try:
        run_live(args.target_complete,args.max_attempted)
    except Exception as exc:
        body=dict(
            kind="solana_dlmm_independent_v1_prospective",
            conclusion="experiment_failed_before_valid_terminal_result",
            allocation_authority=False,error=str(exc)[:200],ended=int(time.time()))
        OUT.write_text(json.dumps(body,indent=2,sort_keys=True)+"\n")
        print(json.dumps(body,sort_keys=True))
        raise


if __name__=="__main__":
    main()
