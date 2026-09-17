"""Aggregate prioritized market-native qualification evidence for human policy review.

This module cannot edit continuation-v1 and cannot authorize orders. It consumes saved
``market-native-priority-report.json`` artifacts, deduplicates full point-in-time
qualification vectors by nomination id, and exposes rejection/sensitivity evidence
only after a minimum natural sample is reached.
"""
from collections import Counter


def analyze_market_native_reports(reports, min_sample=50):
    if min_sample < 1:
        raise ValueError('min_sample_must_be_positive')
    dedup={}
    for report in reports:
        if report.get('kind') != 'prioritized_market_native_shadow':
            continue
        if report.get('qualification_policy') != 'continuation-v1':
            continue
        for row in report.get('preflights',[]):
            if not row.get('full_evidence_complete'):
                continue
            vector=row.get('qualification_vector')
            nomination_id=row.get('nomination_id')
            if not nomination_id or not vector:
                continue
            dedup.setdefault(nomination_id,vector)

    vectors=list(dedup.values())
    first=Counter(v.get('actual_reason') for v in vectors)
    all_rejections=Counter()
    sole=Counter()
    multiple=0
    qualified=0
    for vector in vectors:
        reasons=[x for x in vector.get('all_rejections',[]) if x]
        if vector.get('actual_reason')=='qualified':
            qualified+=1
        for reason in set(reasons):
            all_rejections[reason]+=1
        if len(set(reasons))==1:
            sole[reasons[0]]+=1
        elif len(set(reasons))>1:
            multiple+=1

    result=dict(
        authority='research_only',
        policy='continuation-v1',
        sample_source='prioritized_market_native_shadow',
        unique_complete_market_native_nominations=len(vectors),
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
