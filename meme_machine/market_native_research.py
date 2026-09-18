"""Aggregate natural market-native evidence for human continuation-v1 review.

Trading-prioritizer outputs are useful diagnostics but are selection-biased by design,
so they are explicitly excluded from the minimum threshold-review sample. Only the
fixed-time-slot natural collector contributes to the >=50 review gate.

This module cannot edit continuation-v1 and cannot authorize orders.
"""
from collections import Counter


def analyze_market_native_reports(reports, min_sample=50):
    if min_sample < 1:
        raise ValueError('min_sample_must_be_positive')

    natural={}
    prioritized={}
    for report in reports:
        if report.get('qualification_policy') != 'continuation-v1':
            continue
        kind=report.get('kind')
        if kind=='market_native_natural_sample':
            for row in report.get('results',[]):
                if (row.get('natural_market_native_sample') is not True or
                        row.get('evidence_stage')!='complete'):
                    continue
                vector=row.get('qualification_vector')
                nomination_id=row.get('nomination_id')
                if nomination_id and vector:
                    natural.setdefault(nomination_id,vector)
        elif kind=='prioritized_market_native_shadow':
            # Report separately but never let trading prioritization bias threshold review.
            for row in report.get('preflights',[]):
                if not row.get('full_evidence_complete'):
                    continue
                vector=row.get('qualification_vector')
                nomination_id=row.get('nomination_id')
                if nomination_id and vector:
                    prioritized.setdefault(nomination_id,vector)

    vectors=list(natural.values())
    first=Counter(v.get('actual_reason') for v in vectors)
    all_rejections=Counter()
    sole=Counter()
    multiple=0
    qualified=0
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
        authority='research_only',
        policy='continuation-v1',
        sample_source='market_native_natural_sample_fixed_time_slots',
        selection_bias_control='prioritized trading vectors excluded from threshold sample',
        unique_complete_market_native_nominations=len(vectors),
        prioritized_complete_diagnostic_vectors=len(prioritized),
        minimum_review_sample=int(min_sample),
        sample_ready=len(vectors)>=int(min_sample),
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
    return result
