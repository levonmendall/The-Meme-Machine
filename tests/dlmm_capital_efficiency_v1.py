"""Prospective research runner for frozen DLMM capital-efficiency-v1.

The candidate is frozen in DLMM_CAPITAL_EFFICIENCY_V1.json before live outcomes.
It grants no allocation, signing, submission, or live-money authority.

Thesis:
- discover broadly across SOL-paired DLMM pools without a fixed TVL floor;
- qualify only when the exact proposed 70-bin SOL-side range exhibits high fee capture
  relative to local active liquidity, genuinely two-way/reverting flow, controlled
  drift, and a cheap stress unwind;
- manage inventory aggressively through prespecified early withdrawal conditions;
- settle every paper lifecycle back to SOL with the same integer DLMM mechanics.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
import statistics
import time

from meme_machine import dlmm, pump
from meme_machine.dlmm_paper import CAPITAL, ENTRY_COST, EXIT_COST
from meme_machine.dlmm_tape import (
    VerifiedTape,
    apply_external_adjustment,
    chain_verified_tapes,
    ordered_tape_actions,
    replay_swap_event,
)
from meme_machine.provider import Unavailable
from tests import dlmm_alchemy_provider as provider
from tests import dlmm_profitability_pilot as pilot
from tests import dlmm_strategy_high_activity as activity
from tests import dlmm_strategy_point_in_time as pit
from tests import dlmm_wallet_strategy_discovery as api

RULE_PATH=Path("DLMM_CAPITAL_EFFICIENCY_V1.json")
OUT=Path("dlmm-capital-efficiency-v1-live.json")

DISCOVERY_PAGE_SIZE=250
DISCOVERY_PAGES_PER_SOURCE=2
DISCOVERY_SOURCES=(
    ("volume_30m","volume_30m:desc"),
    ("fee_tvl_ratio_30m","fee_tvl_ratio_30m:desc"),
)
PER_POOL_RPC_LIMIT=240
DISCOVERY_RPC_LIMIT=120


def load_rule(path=RULE_PATH):
    body=json.loads(Path(path).read_text())
    if body.get("kind")!="dlmm_capital_efficiency_v1":
        raise RuntimeError("dlmm_capital_efficiency_rule_kind")
    if body.get("status")!="frozen_pre_prospective":
        raise RuntimeError("dlmm_capital_efficiency_rule_not_frozen")
    if body.get("authority",{}).get("allocation") is not False:
        raise RuntimeError("dlmm_capital_efficiency_authority")
    if int(body["position"]["capital_lamports"])!=CAPITAL:
        raise RuntimeError("dlmm_capital_efficiency_capital_drift")
    if int(body["economics"]["fixed_round_trip_cost_lamports"])!=ENTRY_COST+EXIT_COST:
        raise RuntimeError("dlmm_capital_efficiency_cost_drift")
    return body


def _range_ids(state,width):
    if type(width) is not int or not 2<=width<=70:
        raise ValueError("dlmm_capital_efficiency_width")
    active=int(state["active"])
    if state["y"]==dlmm.WSOL:
        ids=list(range(active-width,active))
    elif state["x"]==dlmm.WSOL:
        ids=list(range(active+1,active+width+1))
    else:
        raise ValueError("dlmm_capital_efficiency_requires_sol")
    if any(str(bid) not in state["bins"] for bid in ids):
        raise Unavailable("dlmm_capital_efficiency_missing_range_bin")
    return ids


def _bidask_bps(active,ids):
    smallest,largest=min(ids),max(ids)
    if smallest<=active<=largest:
        raise ValueError("dlmm_capital_efficiency_bidask_side")
    mean=smallest if active<smallest else largest
    std=(largest-smallest)/4
    variance=max(std*std,1.0)
    raw=[math.exp(((bid-mean)**2)/(2*variance)) for bid in ids]
    total=sum(raw)
    bps=[int(v/total*10000) for v in raw]
    bps[-1 if active<smallest else 0]+=10000-sum(bps)
    if min(bps)<0 or sum(bps)!=10000:
        raise ValueError("dlmm_capital_efficiency_bidask_weights")
    return bps


def _deposit(state,width,capital=CAPITAL):
    ids=_range_ids(state,width)
    bps=_bidask_bps(state["active"],ids)
    amounts=[capital*b//10000 for b in bps]
    amounts[-1]+=capital-sum(amounts)
    v=deepcopy(state)
    sol_y=state["y"]==dlmm.WSOL
    shares={};fee_start={}
    for bid,amount in zip(ids,amounts):
        b=v["bins"][str(bid)]
        # One-sided SOL placement requires no pre-existing opposite asset in the
        # exact target bin; this matches the pinned point-in-time paper mechanics.
        if b["x" if sol_y else "y"]:
            raise Unavailable("dlmm_capital_efficiency_non_sol_bin_composition")
        x,y=(0,amount) if sol_y else (amount,0)
        share=dlmm.deposit_share(b,x,y)
        if share<=0 or share+b["supply"]>dlmm.U128:
            raise Unavailable("dlmm_capital_efficiency_invalid_share")
        shares[str(bid)]=share
        fee_start[str(bid)]={"x":b["fee_x"],"y":b["fee_y"]}
        b["x"]+=x;b["y"]+=y;b["supply"]+=share
    return dict(
        lower=min(ids),upper=max(ids),shares=shares,fee_start=fee_start,
        virtual=v,idle_sol=0,entry_active=state["active"],
        entry_slot=state["slot"],entry_time=state["time"],width=width,
    )


def _advance_position(position,tape):
    if not isinstance(tape,VerifiedTape):
        raise TypeError("dlmm_capital_efficiency_verified_tape_required")
    p=deepcopy(position);v=deepcopy(p["virtual"])
    for kind,item in ordered_tape_actions(tape):
        if kind=="swap":
            v,_=replay_swap_event(v,item)
        else:
            v=apply_external_adjustment(v,item,counterfactual=True)
        v["slot"]=(item.get("cursor") or [item.get("slot",v["slot"])])[0]
        if isinstance(item.get("time"),int):
            v["time"]=max(v["time"],item["time"])
    v["slot"]=tape.terminal["slot"];v["time"]=tape.terminal["time"]
    p["virtual"]=v
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
        assets["x"]+=x;assets["y"]+=y
        assets["fee_x"]+=fx;assets["fee_y"]+=fy
        b["x"]-=x;b["y"]-=y;b["supply"]-=share
    return state,assets


def _mark(position):
    state,assets=_withdraw(position)
    sol_side="x" if state["x"]==dlmm.WSOL else "y"
    token_side="y" if sol_side=="x" else "x"
    sol=assets[sol_side]+assets["fee_"+sol_side]+position["idle_sol"]
    token=assets[token_side]+assets["fee_"+token_side]
    token_value=0
    if token:
        _,quote=dlmm.swap(
            deepcopy(state),token,sol_side=="y",state["time"])
        token_value=int(quote["output"])
        sol+=token_value
    fees_sol=assets["fee_"+sol_side]
    # Token-denominated fees are included in token_value above and are not split
    # from principal without another counterfactual liquidation.
    pnl=sol-CAPITAL-ENTRY_COST-EXIT_COST
    return dict(
        resolved=True,ending_sol_lamports=sol,pnl_lamports=pnl,
        pnl_bps=pnl*10000/CAPITAL,
        token_inventory_raw=token,token_liquidation_lamports=token_value,
        token_inventory_fraction_of_initial_capital=token_value/CAPITAL,
        fee_sol_inventory_lamports=fees_sol,
        active_bin=state["active"],time=state["time"],slot=state["slot"],
    )


def _range_liquidity_sol(state,ids):
    total=0
    for bid in ids:
        b=state["bins"][str(bid)]
        total+=pit._to_sol(state,b["x"],state["x"],bid)
        total+=pit._to_sol(state,b["y"],state["y"],bid)
    return total


def _distance_to_range_bps(state,bin_id,lower,upper):
    if lower<=bin_id<=upper:return 0.0
    edge=lower if bin_id<lower else upper
    p0=dlmm.price(edge,state["step"]);p1=dlmm.price(bin_id,state["step"])
    return abs(p1-p0)*10000/p0


def _event_sol_value(start,event,key):
    bid=event["observed"]["start"]
    token=start["x"] if event["for_y"] else start["y"]
    return pit._to_sol(start,event[key],token,bid)


def _event_fee_sol(start,event):
    bid=event["observed"]["start"]
    token=start["x"] if event["for_y"] else start["y"]
    return pit._to_sol(start,event["observed"]["fee"],token,bid)


def _stress_unwind(state,fraction):
    stress_sol=max(1,int(CAPITAL*float(fraction)))
    p=dlmm.price(state["active"],state["step"])
    if state["y"]==dlmm.WSOL:
        token=max(1,stress_sol*dlmm.Q//p)
        for_y=True
    elif state["x"]==dlmm.WSOL:
        token=max(1,stress_sol*p//dlmm.Q)
        for_y=False
    else:
        raise ValueError("dlmm_capital_efficiency_stress_sol")
    _,quote=dlmm.swap(deepcopy(state),token,for_y,state["time"])
    output=int(quote["output"])
    loss=max(0,stress_sol-output)
    return dict(
        stressed_sol_lamports=stress_sol,token_input_raw=token,
        executable_sol_output_lamports=output,
        unwind_loss_lamports=loss,
        unwind_loss_bps=loss*10000/stress_sol,
    )


def pre_entry_features(warm_start,warm,entry,rule):
    width=int(rule["position"]["width_bins"])
    ids=_range_ids(entry,width);lower=min(ids);upper=max(ids)
    range_liquidity=_range_liquidity_sol(entry,ids)

    touch_swaps=0;touch_volume=0;touch_fees=0
    toward=0;away=0;flat=0;toward_touch=0
    travel=0;movement=[];touch_seen=False;touch_then_revert=False
    first_near=None;last_near=None
    for event in warm.events:
        start_bin=event["observed"]["start"];end_bin=event["observed"]["end"]
        vol=_event_sol_value(warm_start,event,"amount")
        fee=_event_fee_sol(warm_start,event)
        lo,hi=sorted((start_bin,end_bin))
        intersects=hi>=lower and lo<=upper
        d0=_distance_to_range_bps(entry,start_bin,lower,upper)
        d1=_distance_to_range_bps(entry,end_bin,lower,upper)
        if intersects:
            touch_swaps+=1;touch_volume+=vol;touch_fees+=fee;touch_seen=True
        if min(d0,d1)<=200:
            if first_near is None:first_near=start_bin
            last_near=end_bin;travel+=abs(end_bin-start_bin)
            if d1<d0:
                toward+=vol
                if intersects:toward_touch+=vol
            elif d1>d0:
                away+=vol
                if touch_seen:touch_then_revert=True
            else:
                flat+=vol
            delta=end_bin-start_bin
            if delta:movement.append(1 if delta>0 else -1)

    reversals=sum(a!=b for a,b in zip(movement,movement[1:]))
    directional=toward+away
    two_way=0.0 if directional<=0 else 2*min(toward,away)/directional
    net=0 if first_near is None or last_near is None else abs(last_near-first_near)
    drift=0.0 if travel<=0 else net/travel
    observed=max(1,int(warm.terminal["time"])-int(warm_start["time"]))
    capture_share=(
        0.0 if range_liquidity<=0
        else CAPITAL/(range_liquidity+CAPITAL))
    estimated_capture=touch_fees*capture_share
    projected=estimated_capture*int(
        rule["qualification"]["fee_projection_seconds"])/observed
    stress=_stress_unwind(
        entry,rule["qualification"]["stress_inventory_fraction_of_capital"])
    broad=activity.regime_features(warm_start,warm)
    return dict(
        range_lower=lower,range_upper=upper,width_bins=width,
        range_liquidity_sol_lamports=range_liquidity,
        capital_share_of_range_after_entry=(
            None if range_liquidity<=0 else CAPITAL/(range_liquidity+CAPITAL)),
        range_liquidity_to_capital_multiple=range_liquidity/CAPITAL,
        range_touch_swaps=touch_swaps,
        range_touch_volume_sol_lamports=touch_volume,
        range_touch_fee_sol_lamports=touch_fees,
        range_turnover_bps=(
            0.0 if range_liquidity<=0 else touch_volume*10000/range_liquidity),
        estimated_fee_capture_share=capture_share,
        estimated_warmup_range_fee_capture_lamports=estimated_capture,
        projected_range_fee_capture_lamports=projected,
        projected_fee_capture_cost_multiple=(
            projected/(ENTRY_COST+EXIT_COST)),
        flow_into_range_volume_sol_lamports=toward_touch,
        toward_range_volume_sol_lamports=toward,
        away_from_range_volume_sol_lamports=away,
        flat_range_distance_volume_sol_lamports=flat,
        two_way_balance=two_way,reversal_count=reversals,
        touch_then_revert=touch_then_revert,
        near_range_bin_travel=travel,near_range_net_bin_drift=net,
        near_range_drift_ratio=drift,
        warmup_seconds=observed,
        current_fee_bps=dlmm.total_fee(entry)*10000/dlmm.FEE_PRECISION,
        broad_turnover_bps=broad["turnover_bps"],
        broad_fee_density_bps=broad["fee_density_bps"],
        broad_direction_balance=broad["direction_balance"],
        broad_drift_ratio=broad["drift_ratio"],
        stress_unwind=stress,
    )


def qualify(features,rule):
    q=rule["qualification"]
    checks=dict(
        capacity=features["range_liquidity_to_capital_multiple"]
            >=float(q["min_range_liquidity_to_capital_multiple"]),
        fee=features["projected_range_fee_capture_lamports"]
            >=float(q["min_projected_range_fee_capture_lamports"]),
        flow=(not q["require_flow_into_range"]
              or features["flow_into_range_volume_sol_lamports"]>0),
        two_way=features["two_way_balance"]>=float(q["min_two_way_balance"]),
        reversal=(not q["require_reversal_or_touch_then_revert"]
                  or features["reversal_count"]>0
                  or features["touch_then_revert"]),
        drift=features["near_range_drift_ratio"]
            <=float(q["max_near_range_drift_ratio"]),
        unwind=features["stress_unwind"]["unwind_loss_bps"]
            <=float(q["max_stress_unwind_loss_bps"]),
    )
    return dict(
        passes=all(checks.values()),checks=checks,
        failed=[k for k,v in checks.items() if not v],
        fitted_thresholds=False,
        rule="capital_efficiency_v1",
    )


def _candidate(row,source,source_rank):
    volume=row.get("volume") or {};fees=row.get("fees") or {}
    return dict(
        address=row.get("address"),name=row.get("name"),
        token_x=(row.get("token_x") or {}).get("address"),
        token_y=(row.get("token_y") or {}).get("address"),
        tvl=float(row.get("tvl") or 0),
        volume_30m=float(volume.get("30m") or 0),
        fees_30m=float(fees.get("30m") or 0),
        fee_tvl_ratio_30m=float(
            (row.get("fee_tvl_ratio") or {}).get("30m") or 0),
        dynamic_fee_pct=float(row.get("dynamic_fee_pct") or 0),
        source=source,source_rank=source_rank,
    )


def discover(max_candidates):
    merged={}
    for source,sort_by in DISCOVERY_SOURCES:
        for page in range(1,DISCOVERY_PAGES_PER_SOURCE+1):
            payload=api._json_get("/pools",dict(
                page=page,page_size=DISCOVERY_PAGE_SIZE,
                sort_by=sort_by,filter_by="is_blacklisted=false",
            ))
            rows=payload.get("data") if isinstance(payload,dict) else None
            if not isinstance(rows,list):
                raise RuntimeError("dlmm_capital_efficiency_discovery_shape")
            for raw_rank,row in enumerate(rows,1):
                if not isinstance(row,dict) or not api._sol_paired(row):
                    continue
                x=(row.get("token_x") or {}).get("address")
                y=(row.get("token_y") or {}).get("address")
                if (x==dlmm.WSOL)==(y==dlmm.WSOL):
                    continue
                address=row.get("address")
                if not isinstance(address,str):
                    continue
                item=merged.setdefault(address,_candidate(
                    row,source,(page-1)*DISCOVERY_PAGE_SIZE+raw_rank))
                item.setdefault("discovery_sources",[]).append(dict(
                    source=source,rank=(page-1)*DISCOVERY_PAGE_SIZE+raw_rank))
            if len(rows)<DISCOVERY_PAGE_SIZE:
                break

    candidates=list(merged.values())
    for item in candidates:
        ranks={x["source"]:x["rank"] for x in item["discovery_sources"]}
        item["volume_rank"]=ranks.get("volume_30m")
        item["fee_density_rank"]=ranks.get("fee_tvl_ratio_30m")
        # Deterministic broad-union priority: strong showing in either discovery
        # surface first, then favor evidence appearing in both.
        available=[x for x in (item["volume_rank"],item["fee_density_rank"])
                   if isinstance(x,int)]
        item["best_discovery_rank"]=min(available) if available else 10**9
        item["source_count"]=len(item["discovery_sources"])
    candidates.sort(key=lambda x:(
        x["best_discovery_rank"],-x["source_count"],x["address"]))
    return candidates[:max_candidates]


def _far_edge_escaped(position,state):
    if state["y"]==dlmm.WSOL:
        return state["active"]<position["lower"]
    return state["active"]>position["upper"]


def _sum_rpc_metrics(rpcs):
    return dict(
        calls=sum(int(r.calls) for r in rpcs),
        http_requests=sum(int(r.http_requests) for r in rpcs),
        failures=sum(int(r.failures) for r in rpcs),
        retries=sum(int(r.retries) for r in rpcs),
    )


def _rotate_adapter(adapter,pacer,candidate_rpcs,all_rpcs):
    if int(adapter.rpc.calls)<200:
        return adapter
    rpc=provider.new_rpc(limit=PER_POOL_RPC_LIMIT,pacer=pacer)
    candidate_rpcs.append(rpc);all_rpcs.append(rpc)
    return dlmm.Adapter(rpc)


def _dynamic_lifecycle(adapter,address,entry,rule,pacer,candidate_rpcs,all_rpcs):
    management=rule["management"]
    max_hold=int(management["maximum_hold_seconds"])
    segment_seconds=int(management["observation_segment_seconds"])
    position=_deposit(entry,int(rule["position"]["width_bins"]))
    current=entry;tapes=[];segments=[];elapsed=0
    reason="maximum_hold_seconds"

    while elapsed<max_hold:
        duration=min(segment_seconds,max_hold-elapsed)
        adapter=_rotate_adapter(
            adapter,pacer,candidate_rpcs,all_rpcs)
        phase,tape,terminal,effective_start=pilot._observe_phase(
            adapter,address,current,duration,allow_snapshot_reset=False)
        segment=dict(phase,segment=len(segments),requested_seconds=duration)
        if not phase["verified"]:
            return dict(
                complete=False,reason=phase["terminal_classification"],
                segments=segments+[segment],verified_hold_seconds=elapsed,
            )
        if effective_start["slot"]!=current["slot"]:
            raise Unavailable("dlmm_capital_efficiency_segment_start_changed")
        position=_advance_position(position,tape)
        current=terminal;tapes.append(tape);elapsed+=duration
        mark=_mark(position)
        recent=activity.regime_features(effective_start,tape)
        segment.update(mark=mark,recent_flow=recent)
        segments.append(segment)

        exit_reason=None
        if _far_edge_escaped(position,current):
            exit_reason="active_bin_escaped_far_edge"
        elif mark["token_inventory_fraction_of_initial_capital"]>0.50:
            exit_reason="token_inventory_exceeds_50pct_capital"
        elif (
            recent["warmup_swaps"]>=int(
                management["minimum_swaps_for_one_way_flow_exit"])
            and recent["direction_balance"]==0
            and recent["drift_ratio"]==1
        ):
            exit_reason="fully_one_way_monotonic_segment"
        if exit_reason:
            reason=exit_reason
            break

    combined=chain_verified_tapes(entry,tapes)
    final=_mark(position)
    return dict(
        complete=True,exit_reason=reason,realized_hold_seconds=elapsed,
        verified_segment_count=len(segments),segments=segments,
        lineage=combined.lineage,final=final,
    )


def _rpc_metrics(rpc):
    return dict(
        calls=int(rpc.calls),http_requests=int(rpc.http_requests),
        failures=int(rpc.failures),retries=int(rpc.retries),
    )


def _delta(a,b):
    return {k:int(b.get(k,0))-int(a.get(k,0)) for k in b}


def run_live(target_complete=None,max_attempted=None):
    rule=load_rule()
    target_complete=int(target_complete or
                        rule["prospective_test"]["target_complete_observations"])
    max_attempted=int(max_attempted or
                      rule["prospective_test"]["max_attempted_pools"])
    if not 1<=target_complete<=int(
            rule["prospective_test"]["target_complete_observations"]):
        raise ValueError("dlmm_capital_efficiency_target_bound")
    if not target_complete<=max_attempted<=int(
            rule["prospective_test"]["max_attempted_pools"]):
        raise ValueError("dlmm_capital_efficiency_attempt_bound")

    discovery_cap=max_attempted*4
    candidates=discover(discovery_cap)
    pacer=provider.AlchemyPacer()
    report=dict(
        kind="dlmm_capital_efficiency_v1_prospective",
        rule_revision=rule.get("revision"),
        frozen_rule=rule,
        allocation_authority=False,signing=False,submission=False,live_money=False,
        post_freeze_only=True,
        selector_uses_outcome_data=False,
        discovery_candidates=candidates,
        target_complete_observations=target_complete,
        max_attempted_pools=max_attempted,
        started=int(time.time()),
        attempts=[],qualified_lifecycles=[],
    )

    attempted=0;complete=0;qualification_counts=Counter()
    rpc_objects=[]
    for candidate in candidates:
        if attempted>=max_attempted or complete>=target_complete:
            break
        attempted+=1
        rpc=provider.new_rpc(limit=PER_POOL_RPC_LIMIT,pacer=pacer)
        rpc_objects.append(rpc);adapter=dlmm.Adapter(rpc)
        candidate_rpcs=[rpc]
        attempt=dict(
            attempt=attempted,pool=candidate["address"],candidate=candidate,
            qualification=None,warmup=None,lifecycle=None,
        )
        try:
            start=pilot._fresh_supported_start(adapter,candidate)
            phase,warm,entry,warm_start=pilot._observe_phase(
                adapter,candidate["address"],start,
                int(rule["warmup"]["seconds"]),allow_snapshot_reset=True)
            attempt["warmup"]=phase
            if not phase["verified"]:
                attempt["terminal_classification"]=phase["terminal_classification"]
                attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
                report["attempts"].append(attempt);continue
            if not warm.events:
                attempt["terminal_classification"]="verified_zero_swap"
                attempt["qualification"]=dict(
                    passes=False,failed=["no_warmup_flow"],checks={})
                qualification_counts["no_warmup_flow"]+=1
                attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
                report["attempts"].append(attempt);continue

            features=pre_entry_features(warm_start,warm,entry,rule)
            decision=qualify(features,rule)
            attempt["pre_entry_features"]=features
            attempt["qualification"]=decision
            for failed in decision["failed"]:qualification_counts[failed]+=1
            if not decision["passes"]:
                attempt["terminal_classification"]="economic_rejection"
                attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
                report["attempts"].append(attempt);continue

            lifecycle=_dynamic_lifecycle(
                adapter,candidate["address"],entry,rule,
                pacer,candidate_rpcs,rpc_objects)
            attempt["lifecycle"]=lifecycle
            attempt["terminal_classification"]=(
                "complete" if lifecycle["complete"] else lifecycle["reason"])
            attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
            report["attempts"].append(attempt)
            if lifecycle["complete"]:
                complete+=1
                report["qualified_lifecycles"].append(dict(
                    pool=candidate["address"],candidate=candidate,
                    pre_entry_features=features,qualification=decision,
                    **lifecycle,
                ))
        except (Unavailable,ValueError,KeyError,TypeError,OverflowError) as exc:
            attempt["terminal_classification"]="exception"
            attempt["reason"]=str(exc)[:180]
            attempt["rpc"]=_sum_rpc_metrics(candidate_rpcs)
            report["attempts"].append(attempt)

    resolved=[
        x for x in report["qualified_lifecycles"]
        if (x.get("final") or {}).get("resolved")
    ]
    pnls=[x["final"]["pnl_bps"] for x in resolved]
    exits=Counter(x["exit_reason"] for x in resolved)
    provider_totals=dict(
        calls=sum(x.calls for x in rpc_objects),
        http_requests=sum(x.http_requests for x in rpc_objects),
        failures=sum(x.failures for x in rpc_objects),
        retries=sum(x.retries for x in rpc_objects),
    )
    report.update(
        ended=int(time.time()),attempted_pool_count=attempted,
        complete_qualified_lifecycle_count=complete,
        target_met=complete>=target_complete,
        qualification_failure_counts=dict(sorted(qualification_counts.items())),
        resolved_lifecycle_count=len(resolved),
        profitable_lifecycle_count=sum(x["final"]["pnl_lamports"]>0 for x in resolved),
        profitable_rate=(None if not resolved else
                         sum(x["final"]["pnl_lamports"]>0 for x in resolved)/len(resolved)),
        mean_pnl_bps=(None if not pnls else statistics.fmean(pnls)),
        median_pnl_bps=(None if not pnls else statistics.median(pnls)),
        exit_reason_counts=dict(sorted(exits.items())),
        rpc=provider_totals,alchemy_pacer=pacer.telemetry(),
        conclusion=(
            "prospective_target_complete"
            if complete>=target_complete
            else "prospective_sample_incomplete_no_threshold_change"
        ),
    )
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(
        conclusion=report["conclusion"],attempted=attempted,
        qualified=complete,resolved=len(resolved),
        profitable_rate=report["profitable_rate"],
        median_pnl_bps=report["median_pnl_bps"],
        qualification_failures=report["qualification_failure_counts"],
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
        failure=dict(
            kind="dlmm_capital_efficiency_v1_prospective",
            conclusion="experiment_failed_before_valid_terminal_result",
            allocation_authority=False,error=str(exc)[:180],ended=int(time.time()))
        OUT.write_text(json.dumps(failure,indent=2,sort_keys=True)+"\n")
        print(json.dumps(failure,sort_keys=True))
        raise


if __name__=="__main__":
    main()
