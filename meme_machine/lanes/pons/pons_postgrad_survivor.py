"""Independent Pons post-graduation survivor-momentum strategy.

This module is intentionally independent of the existing pre-graduation Pons
strategy.  It contains only deterministic market-selection and lifecycle policy.
Shared transport, authenticated Pons graduation proof, V4 market evidence and paper
accounting may be supplied by adapters, but no pre-graduation qualification,
position, wallet score or outcome is an input.

The policy was designed from open-market Pons post-graduation behavior observed
2026-09-19..2026-09-26. Native funded execution remains PAPER ONLY.
"""
from __future__ import annotations

import hashlib
import json
from meme_machine.paper_policy_revision import ACTIVE_REVISION


STRATEGY_VERSION="pons-postgrad-survivor-momentum-v1"

POLICY=dict(
    revision=ACTIVE_REVISION,
    authority=dict(
        paper_only=True,
        live_money=False,
        signing=False,
        submission=False,
        independent_of_pregraduation=True,
    ),
    universe=dict(
        min_seconds_after_graduation=4*60*60,
        max_seconds_after_graduation=7*24*60*60,
        native_quote_only=True,
    ),
    trend=dict(
        min_since_graduation_return_bps=300,
        min_long_return_bps=750,
        min_6h_return_bps=300,
        min_2h_return_bps=100,
        min_6h_efficiency_bps=2000,
        min_reset_pullback_bps=300,
        max_reset_pullback_bps=4000,
        min_breakout_bps=50,
        max_breakout_extension_bps=1500,
        base_seconds=2*60*60,
        breakout_exclusion_seconds=15*60,
        long_window_seconds=24*60*60,
        medium_window_seconds=6*60*60,
        short_window_seconds=2*60*60,
    ),
    demand=dict(
        min_independent_buyers_30m=4,
        min_new_independent_buyers_30m=1,
        min_buy_sell_ratio_bps=12_500,
        min_buy_acceleration_bps=11_000,
        require_buy_acceleration=False,
        max_largest_buyer_share_bps=4000,
        max_creator_sell_quote=0,
    ),
    confirmation=dict(repeat_window_seconds=1800,hard_repeat_threshold=None,
        ranking_tiebreak=['repeat_independent_buyers_30m','repeat_buyer_share_bps']),
    reentry=dict(minimum_seconds=3600,minimum_changed_dimensions=2,
        cycle_identity='rally-cycle-v1',minimum_completed_base_seconds=900,
        require_distinct_post_breakout_peak=True,require_verified_settlement=True,
        require_global_release_ack=True,require_no_pending_financial_obligations=True),
    execution=dict(
        target_capital_bps=500,
        minimum_capital_bps=5,
        min_turnover_multiple=30,
        max_immediate_roundtrip_loss_bps=450,
        max_double_size_roundtrip_loss_bps=650,
        # Legacy journal identity only. The owner's 2026-10-09 admission change
        # removes this count veto; funding remains the native sleeve's decision.
        max_open_positions=2,
        minimum_fill_breadth_bps=5000,
        sizing_search_steps=32,
    ),
    exit=dict(
        hard_stop_bps=-1000,
        first_profit_bps=2000,
        first_sell_bps=2500,
        trailing_arm_bps=2000,
        trailing_drawdown_bps=1200,
        tighter_trailing_arm_bps=4000,
        tighter_trailing_drawdown_bps=1000,
        demand_failure_ratio_bps=8000,
        demand_failure_confirmations=2,
        no_new_high_seconds=6*60*60,
        no_new_high_return_ceiling_bps=500,
        max_hold_seconds=72*60*60,
    ),
)
POLICY_HASH=hashlib.sha256(
    json.dumps(POLICY,sort_keys=True,separators=(",",":")).encode()
).hexdigest()


def _points(rows):
    out=[]
    for row in rows or ():
        if isinstance(row,dict):
            at=int(row["at"]);price=int(row["price_index"])
        else:
            at=int(row[0]);price=int(row[1])
        if price<=0:
            raise ValueError("nonpositive_price")
        out.append((at,price))
    out.sort()
    if any(b[0]<=a[0] for a,b in zip(out,out[1:])):
        raise ValueError("nonmonotone_price_time")
    return out


def _window(points,now,seconds):
    rows=[row for row in points if now-int(seconds)<=row[0]<=now]
    return rows


def _bounded_window(points,now,nominal_seconds,graduation_at,continuity_complete):
    """Use a proven pre-boundary price, never the first accidentally loaded row.

    An authenticated complete event history establishes that the last price at
    or before the boundary held until the next observed change. This carries an
    existing witness into a quiet interval; it invents no price or observation.
    """
    effective=min(max(0,now-graduation_at),int(nominal_seconds))
    start=now-effective
    eligible=[p for p in points if graduation_at<=p[0]<=now]
    before=[p for p in eligible if p[0]<=start]
    witness=before[-1] if before else None
    rows=([witness] if witness is not None else [])+[p for p in eligible if p[0]>start]
    covered=max(0,min(effective,now-max(start,eligible[0][0]))) if eligible else 0
    complete=bool(continuity_complete and witness is not None and
        rows and rows[-1][0]==now and effective>0)
    return rows,dict(nominal_duration_seconds=int(nominal_seconds),
        effective_duration_seconds=effective,covered_duration_seconds=covered,
        window_start=start,window_end=now,complete=complete,
        boundary_witness_at=None if witness is None else witness[0],
        boundary_witness_price_index=None if witness is None else witness[1],
        continuity_complete=bool(continuity_complete))


def return_bps(start,end):
    start=int(start);end=int(end)
    if start<=0 or end<=0:
        raise ValueError("nonpositive_price")
    return (end-start)*10_000//start


def trend_efficiency_bps(prices):
    values=[int(x) for x in prices]
    if len(values)<2 or min(values)<=0:
        return 0
    travel=sum(abs(b-a) for a,b in zip(values,values[1:]))
    if travel<=0:
        return 0
    return abs(values[-1]-values[0])*10_000//travel


def buy_sell_ratio_bps(buy_quote,sell_quote):
    buy=int(buy_quote);sell=int(sell_quote)
    if buy<0 or sell<0:
        raise ValueError("negative_flow")
    if sell==0:
        return 100_000 if buy>0 else 0
    return buy*10_000//sell


def _first_price_at_or_after(points,cutoff):
    for at,price in points:
        if at>=cutoff:
            return price
    return None


def _feature_set(facts):
    now=int(facts["now"])
    graduation_at=int(facts["graduation_at"])
    points=_points(facts.get("price_points"))
    if not points or points[-1][0]>now:
        raise ValueError("invalid_price_observation_time")
    current=points[-1][1]
    age=max(0,now-graduation_at)

    first_grad=facts.get('graduation_price_index')
    if first_grad is None:
        first_grad=next((price for at,price in points if at==graduation_at),None)
    continuity=facts.get('continuity_complete') is True
    w2,short_window=_bounded_window(points,now,POLICY['trend']['short_window_seconds'],graduation_at,continuity)
    # Six hours is nominal. A four-to-six-hour token requires its entire
    # continuous post-graduation history, without relabeling it as six hours.
    w6,medium_window=_bounded_window(points,now,21600,graduation_at,continuity)
    wlong,long_window=_bounded_window(points,now,POLICY['trend']['long_window_seconds'],graduation_at,continuity)

    r2=(None if not short_window['complete'] else return_bps(w2[0][1],current))
    r6=(None if not medium_window['complete'] else return_bps(w6[0][1],current))
    rlong=(None if not long_window['complete'] else return_bps(wlong[0][1],current))
    rsince=(None if first_grad is None else return_bps(first_grad,current))
    efficiency=(0 if not medium_window['complete'] else trend_efficiency_bps([p for _,p in w6]))

    base_seconds=POLICY["trend"]["base_seconds"]
    exclude=POLICY["trend"]["breakout_exclusion_seconds"]
    prior_base=[
        row for row in points
        if now-base_seconds<=row[0]<=now-exclude
    ]
    older=[
        row for row in points
        if max(graduation_at,now-POLICY["trend"]["long_window_seconds"])
        <=row[0]<now-base_seconds
    ]
    prior_high=(None if not prior_base else max(p for _,p in prior_base))
    older_peak=(None if not older else max(p for _,p in older))
    base_low=(None if not prior_base else min(p for _,p in prior_base))
    breakout=(None if prior_high is None else return_bps(prior_high,current))
    pullback=(
        None if older_peak is None or base_low is None or base_low>=older_peak
        else (older_peak-base_low)*10_000//older_peak
    )
    # These are actual retained canonical observation times. Price magnitudes,
    # buyer counts and rolling window edges cannot identify a new rally.
    peak_at=next((at for at,price in older if price==older_peak),None)
    reset_at=next((at for at,price in prior_base if price==base_low),None)
    base_end=prior_base[-1][0] if prior_base else None
    breakout_at=next((at for at,price in points if base_end is not None
        and at>base_end and prior_high is not None
        and return_bps(prior_high,price)>=POLICY['trend']['min_breakout_bps']),None)

    flow=facts.get("flow_30m") or {}
    prev=facts.get("flow_previous_30m") or {}
    buy=int(flow.get("buy_quote",0));sell=int(flow.get("sell_quote",0))
    prev_buy=None if prev.get('buy_quote') is None else int(prev['buy_quote'])
    ratio=buy_sell_ratio_bps(buy,sell)
    acceleration=(
        None if prev_buy is None else 100_000 if prev_buy==0 and buy>0
        else 0 if prev_buy<=0
        else buy*10_000//prev_buy
    )
    buyers={str(x).lower() for x in flow.get("buyer_groups",())}
    new_population=flow.get('new_buyer_groups')
    new_population_available=(isinstance(new_population,(list,tuple,set,frozenset)) and
        all(isinstance(group,str) and bool(group) for group in new_population))
    new_buyers={str(x).lower() for x in new_population} if new_population_available else None
    previous_population=prev.get('buyer_groups')
    previous_population_available=(isinstance(previous_population,(list,tuple,set,frozenset)) and
        all(isinstance(group,str) and bool(group) for group in previous_population))
    previous_buyers={str(x).lower() for x in previous_population} if previous_population_available else None
    repeat_buyers=None if previous_buyers is None else buyers & previous_buyers
    group_flow=flow.get("buy_quote_by_group",{})
    repeat_quote=None if repeat_buyers is None else sum(int(v) for g,v in group_flow.items() if str(g).lower() in repeat_buyers)
    repeat_share=None if repeat_quote is None or sum(int(v) for v in group_flow.values())!=buy else (0 if buy==0 else repeat_quote*10000//buy)
    turnover=buy+sell

    execution=facts.get("execution") or {}
    roundtrip=execution.get("roundtrip_loss_bps")
    stress=execution.get("double_size_roundtrip_loss_bps")

    capital=int(facts.get("capital_quote",0))
    target=capital*POLICY["execution"]["target_capital_bps"]//10_000
    turnover_cap=turnover//POLICY["execution"]["min_turnover_multiple"]
    proposed=max(0,min(target,turnover_cap))
    minimum=capital*POLICY["execution"]["minimum_capital_bps"]//10_000

    return dict(
        age_seconds=age,current_price_index=current,
        since_graduation_return_bps=rsince,long_return_bps=rlong,
        return_6h_bps=r6,return_2h_bps=r2,efficiency_6h_bps=efficiency,
        medium_window_return_bps=r6,medium_window_efficiency_bps=efficiency,
        return_6h_bps_semantics='return_over_effective_maturity_aware_medium_window',
        effective_long_window_seconds=medium_window['effective_duration_seconds'],
        short_window=short_window,medium_window=medium_window,long_window=long_window,
        reset_pullback_bps=pullback,breakout_bps=breakout,
        base_low=base_low,base_high=prior_high,older_peak=older_peak,
        peak_at=peak_at,reset_at=reset_at,base_start=reset_at,base_end=base_end,
        breakout_at=breakout_at,
        buy_quote_30m=buy,sell_quote_30m=sell,buy_sell_ratio_bps=ratio,
        buy_acceleration_bps=acceleration,
        previous_buyer_population_available=previous_population_available,
        new_buyer_population_available=new_population_available,
        previous_independent_buyers_30m=None if previous_buyers is None else len(previous_buyers),
        total_buyer_population_change=(None if previous_buyers is None else len(buyers)-len(previous_buyers)),
        net_flow_change_quote=(None if prev_buy is None or prev.get('sell_quote') is None
            else (buy-sell)-(prev_buy-int(prev['sell_quote']))),
        independent_buyers_30m=len(buyers),
        repeat_independent_buyers_30m=None if repeat_buyers is None else len(repeat_buyers),
        repeat_buyer_share_bps=repeat_share,
        persistent_buyer_groups=None if repeat_buyers is None else sorted(repeat_buyers),
        new_independent_buyers_30m=None if new_buyers is None else len(new_buyers),
        largest_buyer_share_bps=int(flow.get("largest_buyer_flow_bps",10_000)),
        creator_sell_quote=int(flow.get("creator_sell_quote",0)),
        turnover_quote_30m=turnover,
        roundtrip_loss_bps=(None if roundtrip is None else int(roundtrip)),
        double_size_roundtrip_loss_bps=(None if stress is None else int(stress)),
        proposed_quote_amount=proposed,minimum_quote_amount=minimum,
    )


def evaluate_entry(facts):
    """Return a deterministic, fail-closed post-graduation entry decision."""
    f=_feature_set(facts)
    reasons=[]
    def reject(reason,condition):
        if condition and reason not in reasons:
            reasons.append(reason)

    reject("graduation_lineage",facts.get("lineage_proven") is not True)
    reject("non_native_quote",facts.get("native_quote") is not True)

    u=POLICY["universe"];t=POLICY["trend"];d=POLICY["demand"];e=POLICY["execution"]
    ongoing=facts.get('qualification_scope')=='existing_position_add'
    if not ongoing:
        reject("too_early",f["age_seconds"]<u["min_seconds_after_graduation"])
        reject("too_old",f["age_seconds"]>u["max_seconds_after_graduation"])
    reject('incomplete_medium_window',not f['medium_window']['complete'])
    reject('incomplete_long_window',not f['long_window']['complete'])
    reject('incomplete_short_window',not f['short_window']['complete'])
    reject('missing_new_buyer_population',not f['new_buyer_population_available'])

    for name in (
        "since_graduation_return_bps","long_return_bps","return_6h_bps",
        "return_2h_bps","reset_pullback_bps","breakout_bps",
        "roundtrip_loss_bps","double_size_roundtrip_loss_bps",
    ):
        reject("missing_"+name,f[name] is None)

    if f["since_graduation_return_bps"] is not None:
        reject("weak_since_graduation",
               f["since_graduation_return_bps"]<t["min_since_graduation_return_bps"])
    if f["long_return_bps"] is not None:
        reject("weak_long_trend",f["long_return_bps"]<t["min_long_return_bps"])
    if f["return_6h_bps"] is not None:
        reject("weak_6h_trend",f["return_6h_bps"]<t["min_6h_return_bps"])
    if f["return_2h_bps"] is not None:
        reject("weak_2h_trend",f["return_2h_bps"]<t["min_2h_return_bps"])
    reject("choppy_trend",f["efficiency_6h_bps"]<t["min_6h_efficiency_bps"])
    if f["reset_pullback_bps"] is not None:
        reject("no_meaningful_reset",f["reset_pullback_bps"]<t["min_reset_pullback_bps"])
        reject("reset_too_deep",f["reset_pullback_bps"]>t["max_reset_pullback_bps"])
    if f["breakout_bps"] is not None:
        reject("no_breakout",f["breakout_bps"]<t["min_breakout_bps"])
        reject("late_extension",f["breakout_bps"]>t["max_breakout_extension_bps"])

    reject("insufficient_buyer_breadth",
           f["independent_buyers_30m"]<d["min_independent_buyers_30m"])
    if f['new_independent_buyers_30m'] is not None:
        reject("insufficient_new_breadth",
               f["new_independent_buyers_30m"]<d["min_new_independent_buyers_30m"])
    reject("weak_buy_sell_flow",f["buy_sell_ratio_bps"]<d["min_buy_sell_ratio_bps"])
    acceleration=f['buy_acceleration_bps']
    warnings=(['no_demand_acceleration'] if acceleration is not None and
        acceleration<d['min_buy_acceleration_bps'] else [])
    reject("buyer_concentration",
           f["largest_buyer_share_bps"]>d["max_largest_buyer_share_bps"])
    reject("creator_distribution",
           f["creator_sell_quote"]>d["max_creator_sell_quote"])

    if f["roundtrip_loss_bps"] is not None:
        reject("roundtrip_friction",
               f["roundtrip_loss_bps"]>e["max_immediate_roundtrip_loss_bps"])
    if f["double_size_roundtrip_loss_bps"] is not None:
        reject("stress_friction",
               f["double_size_roundtrip_loss_bps"]>e["max_double_size_roundtrip_loss_bps"])
    reject("insufficient_executable_capacity",
           f["proposed_quote_amount"]<f["minimum_quote_amount"] or
           f["proposed_quote_amount"]<=0)

    priority=(
        int(f["long_return_bps"] or -10**9),
        int(f["return_6h_bps"] or -10**9),
        int(f["independent_buyers_30m"]),
        int(f["buy_sell_ratio_bps"]),
        -int(f["roundtrip_loss_bps"] or 10**9),
        int(f["repeat_independent_buyers_30m"] or 0),
        int(f["repeat_buyer_share_bps"] or 0),
    )
    blocked=set(reasons)
    stage='qualified' if not blocked else 'breakout_watch'
    if blocked & {'no_breakout','late_extension','missing_breakout_bps'}:stage='reset_or_base'
    if blocked & {'no_meaningful_reset','reset_too_deep','missing_reset_pullback_bps'}:stage='trend_eligible'
    if blocked & {'weak_since_graduation','weak_long_trend','weak_6h_trend','weak_2h_trend','choppy_trend'}:stage='survivor'
    if blocked & {'too_early','too_old'}:stage='aging'
    return dict(
        strategy=STRATEGY_VERSION,policy_hash=POLICY_HASH,
        policy_revision=ACTIVE_REVISION,qualification_scope=(
            'existing_position_add' if ongoing else 'initial_entry'),
        initial_entry_authority=not ongoing,
        confirmation_context=dict(authority='confirmation_only',buy_acceleration_bps=acceleration,
            nonblocking_reasons=warnings,previous_policy_would_reject=warnings,
            unavailable_fields=[] if acceleration is not None else ['buy_acceleration_bps']),
        newly_admitted_by_revision=bool(not reasons and warnings),
        paper_only=True,live_money=False,
        candidate=not reasons,all_rejections=reasons,
        proposed_quote_amount=(f["proposed_quote_amount"] if not reasons else 0),
        priority=priority,features=f,stage=stage,
    )


def select_entries(rows,open_positions=0):
    """Cross-sectional selection without fitted weights.

    Eligible survivors are ordered lexicographically by persistent trend, breadth,
    flow and execution cost. Native capital and execution decide funding for
    every eligible row. ``open_positions`` remains a compatible diagnostic input.
    """
    decisions=[evaluate_entry(row) for row in rows]
    eligible=[(row,decision) for row,decision in zip(rows,decisions) if decision["candidate"]]
    eligible.sort(key=lambda pair:tuple(-x for x in pair[1]["priority"]))
    return eligible,decisions


def exit_action(
    *,after_cost_return_bps,high_water_return_bps,hold_seconds,
    seconds_since_high,buy_quote_30m,sell_quote_30m,new_buyers_30m,
    deterioration_streak=0,
):
    """Full-exit lifecycle for the independent post-graduation position."""
    x=POLICY["exit"]
    current=int(after_cost_return_bps);high=max(current,int(high_water_return_bps))
    if current<=x["hard_stop_bps"]:
        return dict(action="full_exit",reason="hard_stop")

    current_index=max(1,10_000+current)
    high_index=max(current_index,10_000+high)
    drawdown=(high_index-current_index)*10_000//high_index
    trail=(
        x["tighter_trailing_drawdown_bps"]
        if high>=x["tighter_trailing_arm_bps"]
        else x["trailing_drawdown_bps"]
    )
    if high>=x["trailing_arm_bps"] and drawdown>=trail:
        return dict(action="full_exit",reason="high_water_trailing_stop")

    ratio=buy_sell_ratio_bps(buy_quote_30m,sell_quote_30m)
    soft=ratio<x["demand_failure_ratio_bps"] and int(new_buyers_30m)<=0
    if soft and int(deterioration_streak)>=x["demand_failure_confirmations"]:
        return dict(action="full_exit",reason="persistent_demand_failure")

    # Keep this legacy helper consistent with the native risk reducer: a low
    # return and old high alone cannot invalidate healthy, continuing demand.
    if (
        soft and int(hold_seconds)>=x["no_new_high_seconds"]
        and int(seconds_since_high)>=x["no_new_high_seconds"]
        and current<x["no_new_high_return_ceiling_bps"]
    ):
        return dict(action="full_exit",reason="stale_thesis")
    if soft:
        return dict(action="hold",reason="demand_deterioration_confirmation")
    return dict(action="hold",reason=None)


def risk_policy():
    x=POLICY['exit']
    return dict(hard_stop_bps=x['hard_stop_bps'],first_profit_bps=x['first_profit_bps'],
        first_sell_bps=x['first_sell_bps'],trail_bps=x['trailing_drawdown_bps'],
        tight_arm_bps=x['tighter_trailing_arm_bps'],tight_trail_bps=x['tighter_trailing_drawdown_bps'],
        soft_confirmations=x['demand_failure_confirmations'],maximum_hold_seconds=x['max_hold_seconds'],
        stale_seconds=x['no_new_high_seconds'],stale_return_ceiling_bps=x['no_new_high_return_ceiling_bps'])
