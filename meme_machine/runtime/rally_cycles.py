"""Authenticated rally identities and read-only comparisons for Survivor re-entry.

A cycle is selected only from point-in-time history already authenticated by the
native Survivor evaluator. No provider calls or trading/portfolio authority live
in this module. Original entry qualification remains independent; repeat funded
entries must establish a distinct completed structural cycle.
"""
from fractions import Fraction
import json

from meme_machine.runtime.journal import digest

SCHEMA = 'survivor-structural-rally-cycle-v1'
SHADOW_SCHEMA = 'survivor-reentry-policy-shadow-v1'


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Fraction(str(value))
    except (ValueError, TypeError, ZeroDivisionError):
        return None
    return str(number) if number > 0 else None


def _cycle(family, asset, *, peak_at, reset_at, base_start_at, base_end_at,
           breakout_at, peak_price, reset_price, base_low, base_high, breakout_price):
    """Construct an exact, restart-stable cycle from existing witnessed structure.

    The rolling base boundaries and current breakout price are evidence, never
    identity inputs: refreshing a quote inside one rally cannot mint a new cycle.
    """
    if family not in ('pump_survivor', 'pons_survivor') or not isinstance(asset, str) or not asset:
        return None
    moments=(peak_at, reset_at, base_start_at, base_end_at, breakout_at)
    if any(type(value) is not int or value < 0 for value in moments):
        return None
    peak_at,reset_at,base_start_at,base_end_at,breakout_at=moments
    if family=='pump_survivor':
        chronological=peak_at < reset_at <= base_start_at < base_end_at < breakout_at
    else:
        chronological=peak_at < base_start_at <= reset_at < base_end_at < breakout_at
    if not chronological:
        return None
    values=[_number(x) for x in (peak_price,reset_price,base_low,base_high,breakout_price)]
    if any(value is None for value in values):
        return None
    peak,reset,low,high,breakout=map(Fraction,values)
    if not (peak > reset and low <= high and breakout > high):
        return None
    fingerprint=digest([SCHEMA,family,asset,peak_at,values[0],reset_at,values[1]])
    return dict(schema=SCHEMA,identity=fingerprint,family=family,asset=asset,
        peak_at=peak_at,reset_at=reset_at,base_start_at=base_start_at,
        base_end_at=base_end_at,breakout_at=breakout_at,
        peak_price=values[0],reset_price=values[1],base_low=values[2],
        base_high=values[3],breakout_price=values[4],
        completed=True,qualification_authority=False,source='authenticated_native_survivor_history')


def pump_cycle(asset, features, *, at):
    """Reuses the Pump peak/reset reducer and its completed preceding-hour base."""
    if not isinstance(features,dict) or (features.get('long_structure_window') or {}).get('complete') is not True:
        return None
    end=features.get('base_end')
    return _cycle('pump_survivor',asset,peak_at=features.get('peak_at'),
        reset_at=features.get('reset_at'),base_start_at=end-3600 if type(end) is int else None,
        base_end_at=end,breakout_at=at,peak_price=features.get('peak_price'),
        reset_price=features.get('reset_low'),base_low=features.get('base_low'),
        base_high=features.get('base_high'),breakout_price=features.get('price'))


def pons_cycle(asset, features, *, at):
    """Reuses Pons's older peak, 2h base, 15m exclusion and fresh breakout."""
    if not isinstance(features,dict) or any(
            (features.get(window) or {}).get('complete') is not True
            for window in ('short_window','medium_window','long_window')):
        return None
    return _cycle('pons_survivor',asset,peak_at=features.get('older_peak_at'),
        reset_at=features.get('reset_at'),base_start_at=features.get('base_start_at'),
        base_end_at=features.get('base_end_at'),breakout_at=at,
        peak_price=features.get('older_peak'),reset_price=features.get('base_low'),
        base_low=features.get('base_low'),base_high=features.get('base_high'),
        breakout_price=features.get('current_price_index'))


def verified_cycle(value):
    """Detect altered identifiers and incomplete or inconsistent archived cycles."""
    if not isinstance(value,dict) or value.get('schema')!=SCHEMA or value.get('completed') is not True:
        return False
    try:
        expected=_cycle(value['family'],value['asset'],peak_at=value['peak_at'],
            reset_at=value['reset_at'],base_start_at=value['base_start_at'],
            base_end_at=value['base_end_at'],breakout_at=value['breakout_at'],
            peak_price=value['peak_price'],reset_price=value['reset_price'],
            base_low=value['base_low'],base_high=value['base_high'],
            breakout_price=value['breakout_price'])
        return expected is not None and expected==value
    except (TypeError,ValueError,KeyError):
        return False


def legacy_new_regime(previous,current,*,minimum_seconds=3600,minimum_changes=2):
    """Exact former policy, used only for comparison; NEVER funding authority."""
    if not isinstance(previous,dict) or not isinstance(current,dict):
        return False
    if type(previous.get('at')) is not int or type(current.get('at')) is not int:
        return False
    if current['at']-previous['at'] < minimum_seconds:
        return False
    dimensions=('high_reset_cycle','base_id','buyer_population','independent_demand','flow_regime')
    return sum(previous.get(k) is not None and current.get(k) is not None
               and previous[k]!=current[k] for k in dimensions)>=minimum_changes


def structural_new_regime(previous,current):
    """No timing delay: require a different *completed* post-entry rally.

    The native reservation layer separately proves all earlier same-candidate
    lifecycles are settled and that exposure is released. This function never
    treats a prior cancellation, unresolved position or stale quote as permission.
    """
    if not isinstance(previous,dict) or not isinstance(current,dict):
        return False
    old_at=previous.get('at');new_at=current.get('at')
    cycle=current.get('cycle')
    if type(old_at) is not int or type(new_at) is not int or new_at<=old_at:
        return False
    if not verified_cycle(cycle) or cycle['breakout_at']!=new_at:
        return False
    old_cycle=previous.get('cycle')
    if old_cycle is not None:
        if not verified_cycle(old_cycle) or old_cycle['family']!=cycle['family'] or old_cycle['asset']!=cycle['asset']:
            return False
        return (cycle['identity']!=old_cycle['identity']
            and cycle['peak_at']>old_cycle['breakout_at']
            and cycle['reset_at']>old_cycle['breakout_at']
            and cycle['breakout_at']>old_cycle['breakout_at'])
    # An older, pre-cycle-identity PAPER entry is usable as a conservative
    # witnessed setup frontier, never upgraded into a fabricated cycle.
    return cycle['peak_at']>old_at and cycle['reset_at']>old_at


def shadow_comparison(sleeve, strategy, candidate, regime):
    """Observation only: retain old and selected decisions from the SAME facts.

    This read makes no reservation and grants no authority. Native reserve still
    rechecks the selected policy under its existing durable SQLite writer fence.
    """
    prior=[]
    for (raw,) in sleeve.db.execute('SELECT body FROM sleeve_positions'):
        item=json.loads(raw)
        if item.get('strategy')==strategy and item.get('candidate')==candidate and not item.get('cancelled'):
            prior.append(item)
    legacy=selected=True
    settled_at=[]
    legacy_blocked=structural_blocked=active=0
    for position in prior:
        finished=position.get('status')=='settled' and position.get('held')==0 and bool(position.get('terminal_hash'))
        if finished and type(position.get('terminal_at')) is int:
            settled_at.append(position['terminal_at'])
        if not finished:
            active+=1
        old_pass=finished and legacy_new_regime(position.get('regime'),regime)
        new_pass=finished and structural_new_regime(position.get('regime'),regime)
        if not old_pass:legacy_blocked+=1
        if not new_pass:structural_blocked+=1
        legacy=legacy and old_pass
        selected=selected and new_pass
    return dict(schema=SHADOW_SCHEMA,authority='comparison_only',
        candidate=candidate,strategy=strategy,old_rule='setup_plus_3600s_two_feature_changes',
        selected_rule='authenticated_distinct_completed_rally_no_delay',
        prior_filled_lifecycles=len(prior),unresolved_prior_lifecycles=active,
        legacy_allows=legacy,structural_allows=selected,
        legacy_blocking_lifecycles=legacy_blocked,structural_blocking_lifecycles=structural_blocked,
        prior_latest_settlement_at=max(settled_at) if settled_at else None,
        current_observed_at=regime.get('at') if isinstance(regime,dict) else None,
        seconds_since_last_settlement=(regime.get('at')-max(settled_at)
            if settled_at and type(regime.get('at')) is int else None),
        proposed_cycle=(regime.get('cycle') or {}).get('identity') if isinstance(regime,dict) else None,
        disagreement=legacy!=selected,
        outcome_attribution='not_a_counterfactual_trade_or_return')


def with_shadow_gate(decision,sleeve,*,strategy,candidate,regime):
    """Record both policies and reject only repeat entries lacking a new cycle."""
    if not decision.get('candidate'):
        return decision
    shadow=shadow_comparison(sleeve,strategy,candidate,regime)
    result=dict(decision,reentry_shadow=shadow)
    if not shadow['structural_allows']:
        result['candidate']=False
        result['all_rejections']=list(decision.get('all_rejections') or [])+['distinct_structural_rally_required']
        result['stage']='rally_reentry_watch'
        if 'proposed_quote_amount' in result:
            result['proposed_quote_amount']=0
    return result
