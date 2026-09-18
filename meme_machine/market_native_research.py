"""Aggregate unbiased market-native evidence and future outcomes for human review.

Prioritized trading vectors remain diagnostics only. The >=50 policy-review gate counts
only fixed-time-slot natural candidates whose full point-in-time evidence completed.
Future labels may describe what happened later, but can never change sample selection,
qualification, or order authority.
"""
from collections import Counter

from .outcome_research import (
    summarize_liquidity_counterfactual, summarize_post_exit_tail, summarize_trackers,
)


def _natural_rows(report):
    kind=report.get('kind')
    if kind=='market_native_natural_sample':
        return report.get('results',[])
    if kind=='market_native_opportunity_outcome_study':
        return report.get('natural_results',[])
    return []


def analyze_market_native_reports(reports, min_sample=50):
    if min_sample < 1:
        raise ValueError('min_sample_must_be_positive')

    natural={}
    prioritized={}
    cohort_trackers=[]
    for report in reports:
        if report.get('qualification_policy') != 'continuation-v1':
            continue
        for row in _natural_rows(report):
            if (row.get('natural_market_native_sample') is not True or
                    row.get('evidence_stage')!='complete'):
                continue
            vector=row.get('qualification_vector')
            nomination_id=row.get('nomination_id')
            if nomination_id and vector:
                natural.setdefault(nomination_id,row)
        if report.get('kind')=='prioritized_market_native_shadow':
            for row in report.get('preflights',[]):
                if not row.get('full_evidence_complete'):
                    continue
                vector=row.get('qualification_vector')
                nomination_id=row.get('nomination_id')
                if nomination_id and vector:
                    prioritized.setdefault(nomination_id,vector)
        if report.get('kind')=='market_native_opportunity_outcome_study':
            cohort_trackers.extend(report.get('cohort_trackers',[]))

    rows=list(natural.values())
    vectors=[r['qualification_vector'] for r in rows]
    first=Counter(v.get('actual_reason') for v in vectors)
    all_rejections=Counter();sole=Counter();multiple=0;qualified=0
    for vector in vectors:
        reasons=[x for x in vector.get('all_rejections',[]) if x]
        if vector.get('actual_reason')=='qualified':
            qualified+=1
        unique=set(reasons)
        for reason in unique:
            all_rejections[reason]+=1
        if len(unique)==1:
            sole[next(iter(unique))]+=1
        elif len(unique)>1:
            multiple+=1

    result=dict(
        authority='research_only',policy='continuation-v1',
        sample_source='market_native_natural_sample_fixed_time_slots',
        selection_bias_control='prioritized trading vectors excluded from threshold sample',
        future_labels_used_for_selection=False,
        unique_complete_market_native_nominations=len(vectors),
        future_outcome_labeled_complete_nominations=sum('future_outcomes' in r for r in rows),
        prioritized_complete_diagnostic_vectors=len(prioritized),
        minimum_review_sample=int(min_sample),sample_ready=len(vectors)>=int(min_sample),
        current_policy_qualified=qualified,
        canonical_first_reason_counts=dict(sorted(first.items(),key=lambda x:str(x[0]))),
        all_rejection_counts=dict(sorted(all_rejections.items())),
        sole_rejection_counts=dict(sorted(sole.items())),
        multiple_rejection_vectors=multiple,
        conclusion=('ready_for_human_threshold_review' if len(vectors)>=int(min_sample)
                    else 'insufficient_sample_for_threshold_revision'),
        automatic_threshold_change=False,
    )

    sensitivity={}
    for vector in vectors:
        values=((vector.get('sensitivity') or {}).get('values') or {})
        for key,grid in values.items():
            bucket=sensitivity.setdefault(key,{})
            for value,passed in grid.items():
                item=bucket.setdefault(str(value),dict(pass_count=0,total=0))
                item['total']+=1
                item['pass_count']+=1 if passed else 0
    result['one_threshold_sensitivity']=sensitivity
    result['liquidity_entry_outcomes']=summarize_liquidity_counterfactual(rows)
    result['qualified_post_exit_tail']=summarize_post_exit_tail(rows)
    result['missed_opportunity_cohorts']=summarize_trackers(cohort_trackers)
    return result
