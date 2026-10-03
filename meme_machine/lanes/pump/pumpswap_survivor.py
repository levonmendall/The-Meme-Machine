"""Frozen PumpSwap Survivor policy; no pregraduation qualification dependency."""
from fractions import Fraction
import hashlib
import json

from certification.execution_capacity import buyer_persistence, turnover_capacity

STRATEGY_ID = 'pumpswap-survivor-momentum-v1'
POLICY = dict(
    strategy=STRATEGY_ID, paper_only=True, quote='SOL',
    minimum_age_seconds=14400, maximum_age_seconds=604800,
    mayhem_clean_seconds=3600, mayhem_completion_required=True,
    minimum_liquidity_usd_micros=20_000_000_000,
    minimum_reset_bps=1800, base_seconds=3600, compression_bps=6000,
    short_structure_seconds=7200, long_structure_seconds=21600,
    maximum_extension_bps=1500, maximum_base_range_extension_bps=15000,
    minimum_fill_breadth_bps=5000, target_sleeve_bps=25, turnover_divisor=40,
    # These are the existing Pump hard execution/concentration ceilings.
    maximum_roundtrip_loss_bps=600, maximum_double_loss_bps=600,
    maximum_holder_concentration_bps=3000, minimum_size_units=1,
    demand_window_seconds=1800,
    ranking_tiebreak=['independent_buyers','repeat_buyers','repeat_buyer_share_bps'],
    exits=dict(hard_stop_bps=-1200, first_profit_bps=2500, first_sell_bps=2500,
               trail_bps=2000, tight_arm_bps=6000, tight_trail_bps=1500,
               soft_confirmations=2, maximum_hold_seconds=259200),
    reentry=dict(minimum_seconds=3600, minimum_changed_dimensions=2),
)
POLICY_HASH = hashlib.sha256(json.dumps(POLICY,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def price_points(facts):
    now = facts['now']
    points = [(int(r['at']), Fraction(r['price'])) for r in facts['price_points']]
    if (not points or any(p <= 0 for _,p in points)
            or any(b[0] <= a[0] for a,b in zip(points,points[1:]))
            or points[-1][0] != now):
        raise ValueError('survivor_price_history_time')
    return points


def evaluate_entry(facts):
    """All inputs are point-in-time evidence; UNKNOWN cannot become a pass."""
    reasons, features = [], {}
    def reject(reason, condition):
        if condition:
            reasons.append(reason)
    reject('graduation_lineage', facts.get('lineage_proven') is not True
           or facts.get('origin') != 'pump.fun' or facts.get('venue') != 'pumpswap'
           or facts.get('canonical_migration_pool') is not True)
    reject('non_sol_quote', facts.get('quote_asset') != 'SOL')
    reject('authoritative_evidence', facts.get('authoritative') is not True
           or facts.get('continuity_complete') is not True)
    reject('creator_distribution', facts.get('creator_distribution_safe') is not True)
    reject('hard_concentration', facts.get('hard_concentration_pass') is not True)
    reject('exit_liquidity', facts.get('exit_liquidity_available') is not True)
    now, grad = facts.get('now'), facts.get('graduation_at')
    if type(now) is not int or type(grad) is not int:
        reasons.append('unknown_graduation_time')
        return _decision(reasons, features)
    age = now-grad
    reject('age', not POLICY['minimum_age_seconds'] <= age <= POLICY['maximum_age_seconds'])
    mayhem = facts.get('mayhem') or {}
    status = mayhem.get('status')
    identifiable = mayhem.get('agent_identity_proven') is True
    agents = mayhem.get('agent_groups')
    reject('unknown_mayhem', status not in ('never', 'active', 'ended'))
    if status in ('active','ended'):
        if identifiable:
            reject('unknown_mayhem_agent', not agents)
        if status == 'active':
            reasons.append('active_mayhem')
        else:
            ended = mayhem.get('ended_at')
            clean = mayhem.get('clean_since')
            reject('mayhem_clean_window', type(ended) is not int or type(clean) is not int
                   or clean < ended or now-clean < POLICY['mayhem_clean_seconds'])
    liquidity = facts.get('liquidity_usd_micros')
    reject('liquidity_floor', type(liquidity) is not int
           or liquidity < POLICY['minimum_liquidity_usd_micros'])
    try:
        points = price_points(facts)
        extrema={int(r['at']):(Fraction(r.get('low',r['price'])),Fraction(r.get('high',r['price'])))
                 for r in facts['price_points']}
        if any(not 0<extrema[t][0]<=p<=extrema[t][1] for t,p in points):
            raise ValueError('price_extrema')
        price = points[-1][1]
        migration = Fraction(facts['migration_price'])
        reject('migration_price_survival', migration <= 0 or price < migration)
        # The last *completed* hour ends at the breakout decision's predecessor
        # watermark. Breakout points never widen the frozen base they must clear.
        base_end = facts['base_end']
        if type(base_end) is not int or not now-1800 <= base_end < now:
            raise ValueError('base_time')
        def window(start,end):
            witness=next(((t,p) for t,p in reversed(points) if t<=start),None)
            return ([] if witness is None else [witness])+[(t,p) for t,p in points if start<t<=end]
        base = window(base_end-3600,base_end)
        previous = window(base_end-7200,base_end-3600)
        if (not base or not previous or base[0][0] > base_end-3600
                or previous[0][0] > base_end-7200):
            raise ValueError('base_history')
        def bounds(rows,start):
            # A preceding witness contributes its last state at the boundary,
            # not extrema from an earlier interval outside the window.
            return (min(p if t<start else extrema[t][0] for t,p in rows),
                    max(p if t<start else extrema[t][1] for t,p in rows))
        low, high = bounds(base,base_end-3600)
        span = high-low
        prior_low,prior_high=bounds(previous,base_end-7200)
        prior_span = prior_high-prior_low
        reject('base_range', span <= 0 or prior_span <= 0)
        reject('base_compression', span*10000 > prior_span*POLICY['compression_bps'])
        prefix=facts.get('reset_history_prefix')
        if prefix is not None and (prefix['through']>now-86400 or prefix['first_at']<grad
                or prefix['first_at']!=points[0][0]):
            raise ValueError('reset_history_prefix_boundary')
        prebase=[r for r in facts['price_points'] if grad<=int(r['at'])<=base[0][0]
                 and (prefix is None or int(r['at'])>prefix['through'])]
        structure=reduce_reset_history(prebase,prefix)
        reset_at,peak_at=structure['reset_at'],structure['peak_at']
        reset=None if structure['reset'] is None else Fraction(structure['reset'])
        reject('meaningful_reset', reset_at is None)
        if reset_at is not None:
            reject('reset_before_base', reset_at > base[0][0] or peak_at >= reset_at)
            retained_lows=[extrema[t][0] for t,p in points if t>=reset_at]
            retained_lows.append(Fraction(structure['minimum_low']))
            reject('reset_low_breakdown', min(retained_lows)<reset)
        # Three consecutive 20m base lows must not form a descending sequence.
        lows = [min((extrema[t][0] for t,p in base if base_end-3600+i*1200 <= t <= base_end-2400+i*1200),default=None) for i in range(3)]
        reject('lower_low_sequence', None in lows or lows[0] > lows[1] > lows[2])
        p2 = next((p for t,p in reversed(points) if t <= now-7200), None)
        p6 = next((p for t,p in reversed(points) if t <= now-21600), None)
        reject('two_hour_structure', p2 is None or price <= p2)
        six = [(t,p) for t,p in points if t >= now-21600]
        slope = price_time_covariance(six)
        reject('six_hour_structure', p6 is None or slope < 0)
        vwap = facts.get('recovery_vwap')
        reject('recovery_vwap', vwap is None or Fraction(vwap) <= 0 or price <= Fraction(vwap))
        reject('no_continuation', price <= high)
        reject('price_extension', (price-high)*10000 > high*POLICY['maximum_extension_bps'])
        reject('base_range_extension', span <= 0 or (price-high)*10000 > span*POLICY['maximum_base_range_extension_bps'])
        flow = buyer_persistence(facts['demand_events'],now=now,window_seconds=1800,
                                 excluded_groups=(agents or ()) if identifiable else ())
        reject('breadth_growth', flow['independent_buyers'] <= len(flow['previous_buyer_groups']))
        reject('net_buy_flow', flow['buy_flow'] <= flow['sell_flow'])
        cap = turnover_capacity(flow['turnover'], authenticated=facts.get('demand_complete') is True)
        features.update(flow, age_seconds=age, price=str(price), base_low=str(low),base_high=str(high),
                        base_range=str(span),reset_low=None if reset is None else str(reset),
                        reset_at=reset_at,peak_at=peak_at,base_end=base_end,
                        breakout_distance=str(price-high), extension_bps=int((price-high)*10000/high),
                        base_range_extension_bps=None if span <= 0 else int((price-high)*10000/span),
                        turnover_cap=cap)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        reasons.append('incomplete_structure_or_demand')
    return _decision(reasons, features)


def reduce_reset_history(rows,prefix=None):
    """Exact sufficient state for the frozen reset scan, without deleting evidence."""
    state=dict(schema='pump-reset-prefix-v1',policy_hash=POLICY_HASH,through=None,first_at=None,
        peak=None,reset=None,peak_at=None,reset_at=None,running_high=None,high_at=None,
        previous_price=None,new_cycle=False,minimum_low=None)
    if prefix is not None:
        if (set(prefix)!=set(state) or prefix['schema']!=state['schema']
                or prefix['policy_hash']!=POLICY_HASH or type(prefix['through']) is not int
                or type(prefix['first_at']) is not int or prefix['first_at']>prefix['through']):
            raise ValueError('reset_history_prefix_identity')
        state.update(prefix)
    for key in ('peak','reset','running_high','previous_price','minimum_low'):
        if state[key] is not None:
            state[key]=Fraction(state[key])
            if state[key]<=0:raise ValueError('reset_history_prefix_price')
    for row in rows:
        at=int(row['at']);p=Fraction(row['price']);low=Fraction(row.get('low',row['price']))
        if (not 0<low<=p or (state['through'] is not None and at<=state['through'])):
            raise ValueError('reset_history_order')
        if state['first_at'] is None:state['first_at']=at
        if (state['reset_at'] is not None and state['previous_price'] is not None
                and p>state['previous_price'] and not state['new_cycle']):
            state['running_high'],state['high_at']=p,at;state['new_cycle']=True
        if state['running_high'] is None or p>state['running_high']:
            state['running_high'],state['high_at']=p,at
        if (state['running_high']-p)*10000>=state['running_high']*POLICY['minimum_reset_bps']:
            if state['reset_at'] is None or state['high_at']!=state['peak_at'] or p<=state['reset']:
                state.update(peak=state['running_high'],reset=p,peak_at=state['high_at'],reset_at=at,
                    new_cycle=False,minimum_low=low)
        if state['reset_at'] is not None:
            state['minimum_low']=min(state['minimum_low'],low)
        state['previous_price']=p;state['through']=at
    for key in ('peak','reset','running_high','previous_price','minimum_low'):
        if state[key] is not None:state[key]=str(state[key])
    return state


def price_time_covariance(points):
    """The frozen centered sum, with each exact Fraction mean computed once."""
    mean_time=Fraction(sum(t for t,_ in points),len(points))
    mean_price=sum(p for _,p in points)/len(points)
    return sum((t-mean_time)*(p-mean_price) for t,p in points)


def _decision(reasons, features):
    blocked=set(reasons)
    stage='qualified' if not blocked else 'continuation_watch'
    if blocked & {'two_hour_structure','six_hour_structure','recovery_vwap'}:stage='base'
    if blocked & {'base_range','base_compression','lower_low_sequence','reset_before_base','reset_low_breakdown'}:stage='reset'
    if blocked & {'meaningful_reset','migration_price_survival','incomplete_structure_or_demand'}:stage='survivor'
    if blocked & {'age','unknown_graduation_time','unknown_mayhem','active_mayhem','mayhem_clean_window'}:stage='aging'
    return dict(strategy=STRATEGY_ID,policy_hash=POLICY_HASH,paper_only=True,
                candidate=not reasons,all_rejections=reasons,features=features,stage=stage,
                priority=None if reasons else tuple(features[k] for k in POLICY['ranking_tiebreak']))
