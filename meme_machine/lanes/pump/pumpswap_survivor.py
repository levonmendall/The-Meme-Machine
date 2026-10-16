"""Funded PumpSwap postgraduation and Survivor policy on one native worker."""
from fractions import Fraction
import hashlib
import json

from meme_machine.runtime.execution_capacity import buyer_persistence, turnover_capacity
from meme_machine.paper_policy_revision import ACTIVE_REVISION, PREDECESSOR_REVISION

STRATEGY_ID = 'pumpswap-survivor-momentum-v1'
POLICY = dict(
    strategy=STRATEGY_ID, paper_only=True, quote='SOL', revision=ACTIVE_REVISION,
    minimum_age_seconds=600, mature_age_seconds=14400, maximum_age_seconds=604800,
    bridge_tiers=[
        dict(name='10m-30m',minimum_age_seconds=600,maximum_age_seconds=1800,
             base_seconds=120,short_structure_seconds=300,demand_window_seconds=120),
        dict(name='30m-2h',minimum_age_seconds=1800,maximum_age_seconds=7200,
             base_seconds=300,short_structure_seconds=900,demand_window_seconds=300),
        dict(name='2h-4h',minimum_age_seconds=7200,maximum_age_seconds=14400,
             base_seconds=900,short_structure_seconds=3600,demand_window_seconds=900),
    ],
    bridge_minimum_independent_buyers=6,bridge_maximum_demand_concentration_bps=4000,
    mayhem_clean_seconds=3600, mayhem_completion_required=True,
    minimum_liquidity_usd_micros=20_000_000_000,
    minimum_reset_bps=300, base_seconds=3600, compression_bps=10000,
    short_structure_seconds=7200, long_structure_seconds=21600,
    maximum_extension_bps=1500, maximum_base_range_extension_bps=15000,
    minimum_fill_breadth_bps=5000, target_sleeve_bps=500, turnover_divisor=40,
    # These are the existing Pump hard execution/concentration ceilings.
    maximum_roundtrip_loss_bps=600, maximum_double_loss_bps=600,
    maximum_holder_concentration_bps=3000, minimum_size_units=1,
    demand_window_seconds=1800,
    ranking_tiebreak=['independent_buyers','repeat_buyers','repeat_buyer_share_bps'],
    exits=dict(hard_stop_bps=-1200, first_profit_bps=2500, first_sell_bps=2500,
               trail_bps=2000, tight_arm_bps=6000, tight_trail_bps=1500,
               soft_confirmations=2, maximum_hold_seconds=259200),
    bridge_exits=dict(hard_stop_bps=-800, first_profit_bps=1500, first_sell_bps=2500,
               trail_arm_bps=1, trail_bps=1400, tight_arm_bps=6000, tight_trail_bps=1400,
               soft_confirmations=2, maximum_hold_seconds=259200),
    reentry=dict(verified_settlement_required=True,distinct_rally_cycle_required=True,
                 require_post_settlement_peak=True,setup_spacing_execution_veto=False,
                 minimum_seconds=3600, minimum_changed_dimensions=2),
)
def policy_hash(policy=POLICY):
    return hashlib.sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest()


POLICY_HASH = policy_hash()


def price_points(facts):
    now = facts['now']
    points = [(int(r['at']), Fraction(r['price'])) for r in facts['price_points']]
    if (not points or any(p <= 0 for _,p in points)
            or any(b[0] <= a[0] for a,b in zip(points,points[1:]))
            or points[-1][0] != now):
        raise ValueError('survivor_price_history_time')
    return points


def evaluate_entry(facts, policy=POLICY):
    """All inputs are point-in-time evidence; UNKNOWN cannot become a pass."""
    reasons, features, evaluated = [], {}, {}
    purpose=facts.get('qualification_purpose','entry')
    if purpose not in ('entry','ongoing'):
        raise ValueError('invalid_qualification_purpose')
    def reject(reason, condition):
        evaluated[reason]=not condition
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
        return _decision(reasons, features,policy=policy,purpose=purpose,evaluated=evaluated)
    age = now-grad
    tier = next((tier for tier in policy.get('bridge_tiers', ())
                 if tier['minimum_age_seconds'] <= age < tier['maximum_age_seconds']), None)
    bridge = tier is not None
    base_seconds = tier['base_seconds'] if bridge else policy['base_seconds']
    short_seconds = tier['short_structure_seconds'] if bridge else policy['short_structure_seconds']
    demand_seconds = tier['demand_window_seconds'] if bridge else policy['demand_window_seconds']
    features.update(age_seconds=age,execution_profile='pump_postgrad_bridge' if bridge else 'pump_survivor',
                    maturity_tier=tier['name'] if bridge else '4h-7d',
                    base_seconds=base_seconds,demand_window_seconds=demand_seconds,
                    short_structure_seconds=short_seconds,market_time=now,
                    decision_at=facts.get('decision_at',now),
                    evidence_acquired_at=facts.get('evidence_acquired_at'),
                    evidence_available_at=facts.get('evidence_available_at'),
                    canonical_slot=facts.get('canonical_slot'))
    reject('age', age < policy['minimum_age_seconds'] or
           (purpose=='entry' and age > policy['maximum_age_seconds']))
    reject('reset_history_revision_detail_unavailable',bool(facts.get('reset_history_revision_detail_unavailable')))
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
                   or clean < ended or now-clean < policy['mayhem_clean_seconds'])
    liquidity = facts.get('liquidity_usd_micros')
    reject('liquidity_floor', type(liquidity) is not int
           or liquidity < policy['minimum_liquidity_usd_micros'])
    try:
        points = price_points(facts)
        extrema={int(r['at']):(Fraction(r.get('low',r['price'])),Fraction(r.get('high',r['price'])))
                 for r in facts['price_points']}
        if any(not 0<extrema[t][0]<=p<=extrema[t][1] for t,p in points):
            raise ValueError('price_extrema')
        price = points[-1][1]
        migration = Fraction(facts['migration_price'])
        reject('migration_price_survival', migration <= 0 or price < migration)
        # The completed base ends at an authenticated predecessor watermark.
        # Young maturities use complete age-appropriate windows; the four-hour
        # Survivor still uses its original one-hour base and two-hour structure.
        # Breakout observations never widen the base they must clear.
        base_end = facts['base_end']
        if type(base_end) is not int or not now-1800 <= base_end < now:
            raise ValueError('base_time')
        def window(start,end):
            witness=next(((t,p) for t,p in reversed(points) if t<=start),None)
            return ([] if witness is None else [witness])+[(t,p) for t,p in points if start<t<=end]
        base = window(base_end-base_seconds,base_end)
        previous = window(base_end-2*base_seconds,base_end-base_seconds)
        if (not base or not previous or base[0][0] > base_end-base_seconds
                or previous[0][0] > base_end-2*base_seconds):
            raise ValueError('base_history')
        def bounds(rows,start):
            # A preceding witness contributes its last state at the boundary,
            # not extrema from an earlier interval outside the window.
            return (min(p if t<start else extrema[t][0] for t,p in rows),
                    max(p if t<start else extrema[t][1] for t,p in rows))
        low, high = bounds(base,base_end-base_seconds)
        span = high-low
        prior_low,prior_high=bounds(previous,base_end-2*base_seconds)
        prior_span = prior_high-prior_low
        reject('base_range', span <= 0 or prior_span <= 0)
        reject('base_compression', span*10000 > prior_span*policy['compression_bps'])
        prefix=facts.get('reset_history_prefix')
        if prefix is not None and (prefix['through']>now-86400 or prefix['first_at']<grad
                or prefix['first_at']!=points[0][0]):
            raise ValueError('reset_history_prefix_boundary')
        prebase=[r for r in facts['price_points'] if grad<=int(r['at'])<=base[0][0]
                 and (prefix is None or int(r['at'])>prefix['through'])]
        structure=reduce_reset_history(prebase,prefix,policy=policy)
        reset_at,peak_at=structure['reset_at'],structure['peak_at']
        reset=None if structure['reset'] is None else Fraction(structure['reset'])
        reject('meaningful_reset', reset_at is None)
        if reset_at is not None:
            reject('reset_before_base', reset_at > base[0][0] or peak_at >= reset_at)
            retained_lows=[extrema[t][0] for t,p in points if t>=reset_at]
            retained_lows.append(Fraction(structure['minimum_low']))
            reject('reset_low_breakdown', min(retained_lows)<reset)
        # Each third of the completed base needs an authenticated price witness;
        # a descending sequence remains blocked at every maturity.
        third = base_seconds//3
        lows = [min((extrema[t][0] for t,p in base
                     if base_end-base_seconds+i*third <= t <= base_end-base_seconds+(i+1)*third),
                    default=None) for i in range(3)]
        reject('lower_low_sequence', None in lows or lows[0] > lows[1] > lows[2])
        p2 = next((p for t,p in reversed(points) if t <= now-short_seconds), None)
        reject('two_hour_structure', p2 is None or price <= p2)
        if bridge:
            reject('complete_graduation_history', points[0][0] != grad or
                   facts.get('continuity_complete') is not True)
        nominal=policy['long_structure_seconds']
        effective=min(age,nominal)
        start=now-effective
        witness=next(((t,p) for t,p in reversed(points) if grad<=t<=start),None)
        complete=(effective>0 and witness is not None and
                  facts.get('continuity_complete') is True and points[-1][0]==now)
        earliest=next((t for t,_ in points if t>=grad),now)
        covered=max(0,now-max(start,earliest))
        features['long_structure_window']=dict(nominal_seconds=nominal,effective_seconds=effective,
            window_start=start,covered_seconds=covered,complete=complete,
            boundary_witness_at=None if witness is None else witness[0])
        if policy.get('revision') in (PREDECESSOR_REVISION,ACTIVE_REVISION):
            # The boundary's last authenticated state is carried to the exact
            # start. Earlier extrema and pre-graduation values stay outside it.
            long=[] if witness is None else [(start,witness[1])]+[(t,p) for t,p in points if start<t<=now]
            slope=None if not long else price_time_covariance(long)
            reject('six_hour_structure',not complete or slope is None or slope < 0)
        else:
            p6=next((p for t,p in reversed(points) if t<=now-nominal),None)
            slope=price_time_covariance([(t,p) for t,p in points if t>=now-nominal])
            reject('six_hour_structure',p6 is None or slope < 0)
        vwap = facts.get('recovery_vwap')
        reject('recovery_vwap', vwap is None or Fraction(vwap) <= 0 or price <= Fraction(vwap))
        reject('no_continuation', price <= high)
        reject('price_extension', (price-high)*10000 > high*policy['maximum_extension_bps'])
        reject('base_range_extension', span <= 0 or (price-high)*10000 > span*policy['maximum_base_range_extension_bps'])
        flow = buyer_persistence(facts['demand_events'],now=now,window_seconds=demand_seconds,
                                 excluded_groups=(agents or ()) if identifiable else ())
        reject('breadth_growth', flow['independent_buyers'] <= len(flow['previous_buyer_groups']))
        reject('net_buy_flow', flow['buy_flow'] <= flow['sell_flow'])
        if bridge:
            reject('bridge_buyer_breadth', flow['independent_buyers'] < policy['bridge_minimum_independent_buyers'])
            reject('bridge_demand_concentration', flow['concentration_bps'] > policy['bridge_maximum_demand_concentration_bps'])
        cap = turnover_capacity(flow['turnover'], authenticated=facts.get('demand_complete') is True)
        features.update(flow, age_seconds=age, price=str(price), base_low=str(low),base_high=str(high),
                        base_range=str(span),reset_low=None if reset is None else str(reset),
                        reset_at=reset_at,peak_at=peak_at,base_start=base_end-base_seconds,base_end=base_end,
                        # A later hydration cannot relabel an earlier canonical
                        # crossing of this completed base as a fresh breakout.
                        # Retain explicit predecessor policy timestamp semantics.
                        breakout_at=(next((t for t,p in points if t>base_end and extrema[t][1]>high),None)
                                     if policy.get('revision')==ACTIVE_REVISION else now),
                        reset_depth_bps=None if reset is None else int((Fraction(structure['peak'])-reset)*10000/Fraction(structure['peak'])),
                        preceding_base_range=str(prior_span),base_compression_bps=None if prior_span<=0 else int(span*10000/prior_span),
                        breakout_distance=str(price-high), extension_bps=int((price-high)*10000/high),
                        base_range_extension_bps=None if span <= 0 else int((price-high)*10000/span),
                        turnover_cap=cap)
        if policy.get('revision') in (PREDECESSOR_REVISION,ACTIVE_REVISION):
            # A changed reset reducer can select a different historical cycle.
            # These compare the observed setup's predicates, not a second trade
            # engine or a claim about the complete preceding policy decision.
            features['previous_predicate_context']=dict(scope='selected_setup_only',
                six_hour_witness_unavailable=age<nominal or not complete,
                selected_reset_below_1800_bps=None if reset is None else
                    (Fraction(structure['peak'])-reset)*10000<Fraction(structure['peak'])*1800,
                base_above_6000_bps_compression=span*10000>prior_span*6000,
                complete_previous_policy_decision='unavailable_not_replayed')
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        reasons.append('incomplete_structure_or_demand')
    return _decision(reasons, features,policy=policy,purpose=purpose,evaluated=evaluated)


def reduce_reset_history(rows,prefix=None,*,policy=POLICY):
    """Exact sufficient state for the frozen reset scan, without deleting evidence."""
    identity=policy_hash(policy)
    state=dict(schema='pump-reset-prefix-v1',policy_hash=identity,through=None,first_at=None,
        peak=None,reset=None,peak_at=None,reset_at=None,running_high=None,high_at=None,
        previous_price=None,new_cycle=False,minimum_low=None)
    if prefix is not None:
        if (set(prefix)!=set(state) or prefix['schema']!=state['schema']
                or prefix['policy_hash']!=identity or type(prefix['through']) is not int
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
        if (state['running_high']-p)*10000>=state['running_high']*policy['minimum_reset_bps']:
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


def _decision(reasons, features,*,policy=POLICY,purpose='entry',evaluated=None):
    blocked=set(reasons)
    stage='qualified' if not blocked else 'continuation_watch'
    if blocked & {'two_hour_structure','six_hour_structure','recovery_vwap'}:stage='base'
    if blocked & {'base_range','base_compression','lower_low_sequence','reset_before_base','reset_low_breakdown'}:stage='reset'
    if blocked & {'meaningful_reset','migration_price_survival','incomplete_structure_or_demand'}:stage='survivor'
    if blocked & {'age','unknown_graduation_time','unknown_mayhem','active_mayhem','mayhem_clean_window'}:stage='aging'
    result=dict(strategy=STRATEGY_ID,policy_hash=policy_hash(policy),paper_only=True,
                policy_revision=policy.get('revision','pre-opportunity-access-v1'),qualification_purpose=purpose,
                candidate=not reasons,all_rejections=reasons,features=features,stage=stage,
                priority=None if reasons else tuple(features[k] for k in policy['ranking_tiebreak']))

    if policy.get('revision')==ACTIVE_REVISION:
        from meme_machine.paper_policy_revision import predecessor_hash
        age=features.get('age_seconds')
        predecessor_age_pass=None if age is None else age>=14400
        bridge=features.get('execution_profile')=='pump_postgrad_bridge'
        shared={name:passed for name,passed in (evaluated or {}).items()
                if not name.startswith('bridge_') and name!='complete_graduation_history'}
        for reason in reasons:
            if not reason.startswith('bridge_') and reason!='complete_graduation_history':shared[reason]=False
        result['policy_comparison']=dict(predecessor_revision=PREDECESSOR_REVISION,
            predecessor_policy_hash=predecessor_hash('pump_survivor'),
            scope='exact_predecessor_minimum_age_predicate' if bridge else 'evaluated_shared_entry_predicates',
            predecessor_minimum_age_seconds=14400,predecessor_minimum_age_pass=predecessor_age_pass,
            predecessor_decisive_rejection='age' if predecessor_age_pass is False else None,
            current_candidate=not reasons,newly_admitted_bridge=bridge and purpose=='entry' and not reasons,
            evaluated_shared_predicates=shared,complete_predecessor_decision='not_replayed',
            structural_reentry_validation='separate_native_reservation_gate')
    return result
