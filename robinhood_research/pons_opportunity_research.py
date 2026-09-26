"""Frozen offline policy candidates. Not imported by production admission.

Selection requires executable retained evidence. WATCH/DEFER do not grant entry
or trigger provider work. Scheduling, persistence and runtime authority remain
with the existing Candidate Plane. Production baseline is retained unless the
preregistered acceptance gate is demonstrated.
"""
from .pons_selective_continuation import ENTRY_THRESHOLDS as E

SELECTED_POLICY = 0


def preservation(facts):
    """Cheap deterministic pre-canonical disposition; unknown is not eligible."""
    def result(state,reason):return dict(state=state,reason=reason,entry_authority=False)
    if facts.get('scope_valid') is False or facts.get('provenance_valid') is False:
        return result('REJECTED_TERMINAL','scope_or_provenance')
    if facts.get('creator_adverse') is True:
        return result('REJECTED_TERMINAL','creator_adverse')
    if facts.get('scope_valid') is not True or facts.get('provenance_valid') is not True:
        return result('DEFERRED','unknown_scope_or_provenance')
    age=facts.get('token_age_seconds');progress=facts.get('progress_bps')
    if age is not None and age>E['max_token_age_seconds']:
        return result('REJECTED_TERMINAL','over_age')
    if facts.get('graduated') or (progress is not None and progress>E['max_curve_progress_bps']):
        return result('REJECTED_TERMINAL','beyond_pregraduation_regime')
    if age is not None and age<E['min_token_age_seconds']:
        return result('DEFERRED','too_young')
    if facts.get('current_snipe_bps') not in (None,0):
        return result('DEFERRED','temporary_snipe')
    if progress is not None and progress<E['min_curve_progress_bps']:
        return result('WATCHING','early_progress')
    if age is None or progress is None or facts.get('current_snipe_bps') is None:
        return result('DEFERRED','readiness_unknown')
    trajectory=facts.get('trajectory') or {}
    if not trajectory.get('complete'):return result('WATCHING','trajectory_incomplete')
    eta=trajectory.get('graduation_eta_seconds')
    if (trajectory.get('progress_15s_bps',0)<E['min_progress_15s_bps'] or not trajectory.get('accelerating') or
        eta is None or not E['min_graduation_eta_seconds']<=eta<=E['max_graduation_eta_seconds']):
        return result('WATCHING','trajectory_not_ready')
    remaining=facts.get('remaining_seconds');service=facts.get('measured_service_seconds')
    if remaining is None or service is None or remaining<=max(0,service):
        return result('DEFERRED','original_deadline_feasibility_unproven')
    return result('PROMOTED','canonical_evidence_needed')


def promotion_order(facts):
    """Ordinal tiers only; no fitted coefficients or allocation authority."""
    d=facts.get('demand') or {};t=facts.get('trajectory') or {}
    return (int(facts.get('scope_valid') is True and facts.get('provenance_valid') is True),
            int(preservation(facts)['state']=='PROMOTED'),
            int(t.get('complete') is True and t.get('accelerating') is True),
            int(d.get('current_net_quote',0)>0 and d.get('independent_groups',0)>=E['min_independent_groups']),
            int(facts.get('remaining_seconds',0)>facts.get('measured_service_seconds',float('inf'))))


def bounded_promotions(observations,consumed,*,slots=1):
    if slots not in (0,1):raise ValueError('existing_single_hydration_dispatch_bound')
    if len(observations)>E['max_market_events']:raise ValueError('bounded_observation_batch')
    unique={}
    for row in observations:
        key=(row['candidate'],row['generation'])
        if key in unique and unique[key]!=row:raise ValueError('conflicting_observation')
        unique[key]=row
    eligible=[r for k,r in unique.items() if k not in consumed and preservation(r)['state']=='PROMOTED']
    ordered=sorted(eligible,key=lambda r:(tuple(-n for n in promotion_order(r)),r['candidate'],r['generation']))
    return ordered[:slots]


def fill_hysteresis(previous,observation):
    """Research-only state transition; HOLD never means execute a stale quote."""
    p=previous or {};o=observation
    key=o['observation_id']
    if p.get('observation_id')==key:
        if p.get('observation')!=o:raise ValueError('conflicting_observation')
        return dict(p)
    if p.get('at') is not None and o['at']<=p['at']:raise ValueError('nonmonotone_observation')
    if p.get('action')=='CANCEL':return dict(p)
    hard=list(o.get('hard_invalidators') or [])
    if o.get('trusted') is not True:hard.append('untrusted')
    age=o.get('quote_age_seconds')
    if age is None or age<0 or age>E['max_state_age_seconds']:hard.append('stale_quote')
    soft=bool(o.get('soft_deterioration'));n=p.get('consecutive_soft',0)+1 if soft else 0
    action=('CANCEL' if hard or o.get('severe') or n>=2 else 'HOLD' if soft else 'READY')
    return dict(observation_id=key,observation=dict(o),at=o['at'],action=action,
                consecutive_soft=n,hard_invalidators=hard,entry_authority=False)


def acceptable(metrics):
    """Unknown evidence cannot select a more permissive strategy."""
    fields=('incremental_unique_winners','incremental_losers','downside_change','canonical_workload_change')
    if any(metrics.get(k) is None for k in fields):return False
    return (metrics['incremental_unique_winners']>0 and metrics['incremental_losers']<=0 and
            metrics['downside_change']<=0 and metrics['canonical_workload_change']<=0)
