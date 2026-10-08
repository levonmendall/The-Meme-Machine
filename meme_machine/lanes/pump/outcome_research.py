"""Research-only forward outcome labeling for market-native Pump candidates.

Future outcomes are deliberately separate from qualification inputs. Nothing in this
module can authorize an order or alter continuation-v1. It turns later finalized trade
observations into labels for cohorts selected strictly from point-in-time evidence.
"""
from __future__ import annotations

from statistics import median

DEFAULT_HORIZONS = (60, 180, 300, 600, 900, 1800, 3600)
POST_EXIT_HORIZONS = (300, 900, 1800, 3600)
LIQUIDITY_FLOORS = (5_000_000_000, 7_500_000_000, 10_000_000_000)
SUBCLASS_PROTOCOL_VERSION = 'subclass-development-v1'


def price_parts(event):
    amount = int(event.get('amount', 0))
    tokens = int(event.get('tokens', 0))
    if amount <= 0 or tokens <= 0:
        raise ValueError('invalid_trade_price')
    return amount, tokens


def return_bps(base_num, base_den, mark_num, mark_den):
    base_num, base_den = int(base_num), int(base_den)
    mark_num, mark_den = int(mark_num), int(mark_den)
    if min(base_num, base_den, mark_num, mark_den) <= 0:
        raise ValueError('invalid_price_ratio')
    return (mark_num * base_den * 10_000 // (mark_den * base_num)) - 10_000


def new_tracker(mint, origin_time, baseline_num, baseline_den, cohorts, *,
                nomination_id=None, horizons=DEFAULT_HORIZONS, metadata=None):
    return dict(
        mint=mint,
        nomination_id=nomination_id,
        origin_time=int(origin_time),
        baseline_num=int(baseline_num),
        baseline_den=int(baseline_den),
        cohorts=sorted(set(cohorts)),
        horizons=[int(x) for x in horizons],
        marks={},
        max_favorable_bps=None,
        max_adverse_bps=None,
        observed_trade_events=0,
        metadata=dict(metadata or {}),
        shadow_exit=None,
    )


def enable_shadow_exit(tracker, *, opened_time=None, take_profit_bps=1500,
                       risk_bps=-1000, timeout_seconds=900):
    tracker['shadow_exit'] = dict(
        model='trade-price-proxy-v1',
        canonical_execution=False,
        excludes_liquidity_invalidation=True,
        opened_time=int(opened_time if opened_time is not None else tracker['origin_time']),
        take_profit_bps=int(take_profit_bps),
        risk_bps=int(risk_bps),
        timeout_seconds=int(timeout_seconds),
        triggered=False,
        reason=None,
        exit_time=None,
        exit_return_bps=None,
        exit_price_num=None,
        exit_price_den=None,
        post_exit_marks={},
        post_exit_max_entry_return_bps=None,
        post_exit_min_entry_return_bps=None,
    )
    return tracker


def observe_trade(tracker, event):
    if event.get('mint') != tracker.get('mint'):
        return False
    event_time = int(event.get('market_time', 0))
    if event_time < int(tracker['origin_time']):
        return False
    mark_num, mark_den = price_parts(event)
    rbps = return_bps(tracker['baseline_num'], tracker['baseline_den'], mark_num, mark_den)
    tracker['observed_trade_events'] += 1
    best = tracker.get('max_favorable_bps')
    worst = tracker.get('max_adverse_bps')
    tracker['max_favorable_bps'] = rbps if best is None else max(int(best), rbps)
    tracker['max_adverse_bps'] = rbps if worst is None else min(int(worst), rbps)

    age = event_time - int(tracker['origin_time'])
    for horizon in tracker.get('horizons', []):
        key = str(int(horizon))
        if key not in tracker['marks'] and age >= int(horizon):
            tracker['marks'][key] = dict(
                return_bps=rbps,
                market_time=event_time,
                lag_seconds=age-int(horizon),
                price_num=mark_num,
                price_den=mark_den,
            )

    shadow = tracker.get('shadow_exit')
    if shadow:
        opened = int(shadow['opened_time'])
        if event_time >= opened:
            if not shadow['triggered']:
                exit_reason = None
                if rbps <= int(shadow['risk_bps']):
                    exit_reason = 'risk_proxy'
                elif rbps >= int(shadow['take_profit_bps']):
                    exit_reason = 'take_profit_proxy'
                elif event_time-opened >= int(shadow['timeout_seconds']):
                    exit_reason = 'timeout_proxy'
                if exit_reason:
                    shadow.update(
                        triggered=True,
                        reason=exit_reason,
                        exit_time=event_time,
                        exit_return_bps=rbps,
                        exit_price_num=mark_num,
                        exit_price_den=mark_den,
                    )
            else:
                since_exit = event_time-int(shadow['exit_time'])
                for horizon in POST_EXIT_HORIZONS:
                    key = str(horizon)
                    if key not in shadow['post_exit_marks'] and since_exit >= horizon:
                        shadow['post_exit_marks'][key] = dict(
                            entry_return_bps=rbps,
                            market_time=event_time,
                            lag_seconds=since_exit-horizon,
                        )
                hi = shadow.get('post_exit_max_entry_return_bps')
                lo = shadow.get('post_exit_min_entry_return_bps')
                shadow['post_exit_max_entry_return_bps'] = rbps if hi is None else max(int(hi), rbps)
                shadow['post_exit_min_entry_return_bps'] = rbps if lo is None else min(int(lo), rbps)
    return True


def liquidity_floor_eligibility(vector):
    grid = (((vector or {}).get('sensitivity') or {}).get('values') or {}).get(
        'min_real_sol_lamports', {})
    return {str(x): bool(grid.get(str(x), False)) for x in LIQUIDITY_FLOORS}





def two_buyer_research_candidate(vector):
    """Research-only precursor: buyer-count is the sole known preflight blocker."""
    vector=vector or {}
    grid=(((vector.get('sensitivity') or {}).get('values') or {})
          .get('min_independent_groups') or {})
    return bool(
        vector.get('actual_reason')=='independent_demand' and
        int(vector.get('independent_buyer_groups') or -1)==2 and
        grid.get('2',False)
    )


def subclass_research_protocol():
    """Pre-registered development -> freeze -> fresh validation boundary."""
    return dict(
        version=SUBCLASS_PROTOCOL_VERSION,
        authority='research_only',
        automatic_trading_admission=False,
        outcome_definition=dict(
            strong_clean_win='max_favorable_bps>=1500 and max_adverse_bps>-1000',
            horizons_seconds=list(DEFAULT_HORIZONS),
        ),
        two_buyer=dict(
            development_candidate='exactly_2_independent_groups_and_only_buyer_count_blocks_current_policy',
            minimum_complete_development=30,
            maximum_candidate_rule_features=2,
            prospective_validation_minimum=30,
            rule_must_be_frozen_before_validation=True,
        ),
        high_density=dict(
            development_candidate='point_in_time_pump_window_event_count>100',
            minimum_labeled_development=100,
            maximum_candidate_rule_features=3,
            prospective_validation_minimum=50,
            rule_must_be_frozen_before_validation=True,
            trading_event_cap_remains=100,
        ),
    )


def subclass_development_status(trackers):
    """Pre-registered readiness only; never freezes or admits a strategy."""
    protocol=subclass_research_protocol()
    two={}
    dense={}
    for tracker in trackers or []:
        cohorts=set(tracker.get('cohorts') or [])
        if cohorts.intersection({'two_buyer_sole_near_miss',
                                 'two_buyer_sole_near_miss_expanded'}):
            key=(tracker.get('nomination_id'),tracker.get('mint'))
            two.setdefault(key,tracker)
        if 'high_density' in cohorts:
            dense.setdefault(tracker.get('mint'),tracker)
    two_complete=len(two)
    two_labeled=sum(bool(t.get('observed_trade_events')) for t in two.values())
    dense_candidates=len(dense)
    dense_labeled=sum(bool(t.get('observed_trade_events')) for t in dense.values())
    two_min=int(protocol['two_buyer']['minimum_complete_development'])
    dense_min=int(protocol['high_density']['minimum_labeled_development'])
    return dict(
        protocol_version=protocol['version'],
        authority='research_only',
        automatic_trading_admission=False,
        two_buyer=dict(
            complete_development=two_complete,
            outcome_labeled=two_labeled,
            minimum_complete_development=two_min,
            ready_to_freeze_candidate_rule=two_complete>=two_min,
            rule_frozen=False,
            prospective_validation_started=False,
        ),
        high_density=dict(
            development_candidates=dense_candidates,
            outcome_labeled=dense_labeled,
            minimum_labeled_development=dense_min,
            ready_to_freeze_candidate_rule=dense_labeled>=dense_min,
            rule_frozen=False,
            prospective_validation_started=False,
            trading_event_cap_remains=100,
        ),
    )

def is_two_buyer_sole_near_miss(row):
    """True only when 3->2 buyer groups alone flips the frozen vector to pass."""
    vector=(row or {}).get('qualification_vector') or {}
    if row.get('evidence_stage')!='complete':
        return False
    if int(vector.get('independent_buyer_groups') or -1) != 2:
        return False
    grid=(((vector.get('sensitivity') or {}).get('values') or {})
          .get('min_independent_groups') or {})
    return bool(grid.get('2', False)) and not bool(vector.get('current_threshold_pass'))


def summarize_two_buyer_near_misses(natural_rows):
    rows=[r for r in natural_rows if is_two_buyer_sole_near_miss(r)]
    horizons={}
    for horizon in DEFAULT_HORIZONS:
        vals=[]
        for row in rows:
            mark=((row.get('future_outcomes') or {}).get('marks') or {}).get(str(horizon))
            if mark and mark.get('return_bps') is not None:
                vals.append(int(mark['return_bps']))
        horizons[str(horizon)]=dict(
            observed=len(vals),
            median_return_bps=_median(vals),
            positive=sum(x>0 for x in vals),
            above_15pct=sum(x>=1500 for x in vals),
            below_minus_10pct=sum(x<=-1000 for x in vals),
        )
    mfes=[(r.get('future_outcomes') or {}).get('max_favorable_bps') for r in rows]
    maes=[(r.get('future_outcomes') or {}).get('max_adverse_bps') for r in rows]
    return dict(
        authority='research_only',
        trading_threshold_unchanged=True,
        candidate_count=len(rows),
        with_future_trade=sum(bool((r.get('future_outcomes') or {}).get('observed_trade_events')) for r in rows),
        median_mfe_bps=_median(mfes),
        median_mae_bps=_median(maes),
        clean_15pct_winners=sum(
            (r.get('future_outcomes') or {}).get('max_favorable_bps') is not None and
            int((r.get('future_outcomes') or {}).get('max_favorable_bps'))>=1500 and
            (r.get('future_outcomes') or {}).get('max_adverse_bps') is not None and
            int((r.get('future_outcomes') or {}).get('max_adverse_bps'))>-1000
            for r in rows
        ),
        horizons=horizons,
        nomination_ids=[r.get('nomination_id') for r in rows if r.get('nomination_id')],
    )

def high_density_features(events, now):
    """Describe a >100-event Pump window without using future information."""
    now=int(now)
    rows=[]
    for event in events:
        try:
            if not now-60 <= int(event['market_time']) <= now:
                continue
            amount=int(event['amount']);tokens=int(event['tokens'])
            if amount<=0 or tokens<=0:
                continue
            rows.append(event)
        except (KeyError,TypeError,ValueError):
            continue
    rows.sort(key=lambda e:(int(e['market_time']),int(e.get('slot',0)),int(e.get('index',0))))
    wallets={}
    buyers=set();sellers=set()
    gross_buy=gross_sell=0
    buy_count=sell_count=0
    for event in rows:
        amount=int(event['amount']);wallet=event.get('wallet')
        signed=amount if event.get('buy') else -amount
        if wallet:
            wallets[wallet]=wallets.get(wallet,0)+signed
        if event.get('buy'):
            buy_count+=1;gross_buy+=amount
            if wallet: buyers.add(wallet)
        else:
            sell_count+=1;gross_sell+=amount
            if wallet: sellers.add(wallet)

    total_flow=gross_buy+gross_sell
    abs_wallet_flow=sorted((abs(v) for v in wallets.values()),reverse=True)
    top_wallet_share_bps=(0 if not total_flow else
                          (abs_wallet_flow[0]*10_000//total_flow if abs_wallet_flow else 0))
    windows={}
    for seconds in (5,10,30,60):
        subset=[e for e in rows if int(e['market_time'])>=now-seconds]
        buys=sum(1 for e in subset if e.get('buy'))
        sells=len(subset)-buys
        buy_sol=sum(int(e['amount']) for e in subset if e.get('buy'))
        sell_sol=sum(int(e['amount']) for e in subset if not e.get('buy'))
        windows[str(seconds)]=dict(
            events=len(subset),buys=buys,sells=sells,
            buy_share_bps=(0 if not subset else buys*10_000//len(subset)),
            net_buy_lamports=buy_sol-sell_sol,
            gross_buy_lamports=buy_sol,gross_sell_lamports=sell_sol,
            unique_wallets=len({e.get('wallet') for e in subset if e.get('wallet')}),
        )

    price_change_bps=None
    if len(rows)>=2:
        try:
            first_num,first_den=price_parts(rows[0])
            last_num,last_den=price_parts(rows[-1])
            price_change_bps=return_bps(first_num,first_den,last_num,last_den)
        except ValueError:
            pass
    return dict(
        observed_at=now,event_count=len(rows),buy_count=buy_count,sell_count=sell_count,
        unique_buyers=len(buyers),unique_sellers=len(sellers),unique_wallets=len(wallets),
        gross_buy_lamports=gross_buy,gross_sell_lamports=gross_sell,
        net_buy_lamports=gross_buy-gross_sell,
        buy_share_bps=(0 if not rows else buy_count*10_000//len(rows)),
        top_wallet_abs_flow_share_bps=top_wallet_share_bps,
        price_change_bps=price_change_bps,windows=windows,
    )

def _median(values):
    rows=[int(x) for x in values if x is not None]
    return None if not rows else median(rows)


def summarize_trackers(trackers):
    by_cohort={}
    for row in trackers:
        for cohort in row.get('cohorts', []):
            by_cohort.setdefault(cohort, []).append(row)
    result={}
    for cohort, rows in sorted(by_cohort.items()):
        horizons={}
        for horizon in DEFAULT_HORIZONS:
            vals=[]
            for row in rows:
                mark=(row.get('marks') or {}).get(str(horizon))
                if mark:
                    vals.append(mark.get('return_bps'))
            horizons[str(horizon)] = dict(
                observed=len(vals),
                median_return_bps=_median(vals),
                positive=sum(int(x)>0 for x in vals),
                above_15pct=sum(int(x)>=1500 for x in vals),
                below_minus_10pct=sum(int(x)<=-1000 for x in vals),
            )
        result[cohort]=dict(
            count=len(rows),
            with_any_future_trade=sum(bool(r.get('observed_trade_events')) for r in rows),
            median_mfe_bps=_median(r.get('max_favorable_bps') for r in rows),
            median_mae_bps=_median(r.get('max_adverse_bps') for r in rows),
            horizons=horizons,
        )
    return result


def summarize_liquidity_counterfactual(natural_rows):
    result={}
    for floor in LIQUIDITY_FLOORS:
        key=str(floor)
        eligible=[r for r in natural_rows if (r.get('liquidity_floor_eligibility') or {}).get(key)]
        horizons={}
        for horizon in DEFAULT_HORIZONS:
            vals=[]
            for row in eligible:
                mark=(row.get('future_outcomes') or {}).get('marks',{}).get(str(horizon))
                if mark:
                    vals.append(mark.get('return_bps'))
            horizons[str(horizon)]=dict(observed=len(vals),median_return_bps=_median(vals))
        result[key]=dict(
            eligible=len(eligible),
            horizons=horizons,
            qualified_under_current_policy=sum(
                (r.get('qualification_vector') or {}).get('actual_reason')=='qualified'
                for r in eligible),
        )
    return result


def summarize_post_exit_tail(natural_rows):
    rows=[]
    for row in natural_rows:
        shadow=(row.get('future_outcomes') or {}).get('shadow_exit')
        if shadow and shadow.get('triggered'):
            rows.append(shadow)
    return dict(
        shadow_exits=len(rows),
        take_profit_proxy=sum(r.get('reason')=='take_profit_proxy' for r in rows),
        risk_proxy=sum(r.get('reason')=='risk_proxy' for r in rows),
        timeout_proxy=sum(r.get('reason')=='timeout_proxy' for r in rows),
        median_exit_return_bps=_median(r.get('exit_return_bps') for r in rows),
        median_post_exit_max_entry_return_bps=_median(
            r.get('post_exit_max_entry_return_bps') for r in rows),
        note='trade-price proxy only; canonical paper execution remains unchanged',
    )
