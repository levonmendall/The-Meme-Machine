"""Fixed, preregistered feature research over retained native observations.

No provider imports, market calls, strategy mutation, range hindsight, or order
authority. Missing outcomes are censoring, not zero returns. Scoring all fixed
alternatives is deliberately distinct from selecting/promoting a winner.
"""
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import json
from pathlib import Path

from certification.journal import Journal,canonical,digest
from certification.report import LANES


def scores(vector,models):
    out={}
    for model in models:
        value=vector
        for key in model['path'].split('.'):
            value=value.get(key) if isinstance(value,dict) else None
        try:
            number=Decimal(str(value))
            if not number.is_finite():raise InvalidOperation
            if model['direction'] not in (-1,1):raise ValueError('invalid_score_direction')
            out[model['id']]=str(number.copy_negate() if model['direction']==-1 else number)
        except (InvalidOperation,ValueError,TypeError):out[model['id']]=None
    return out


def candidate_vectors(lane,event):
    """Use each lane's complete-observation predicate, never an HTTP result."""
    body=event['body'];kind=event['kind']
    if lane=='pons' and kind=='candidate_observation':
        row=body['observation'];v=row.get('vector') or {};age=v.get('decision_state_age_seconds')
        limit=(v.get('thresholds') or {}).get('max_state_age_seconds')
        complete=v.get('complete') is True and isinstance(age,(int,float)) and isinstance(limit,(int,float)) and 0<=age<=limit
        yield dict(identity=[row.get('token'),row.get('source_transaction'),row.get('sequence')],asset=row.get('token'),
            vector=v,complete=complete,grade='authenticated_complete' if complete else 'censored',
            pre_outcome=True,qualified=v.get('current_threshold_pass') is True)
    if kind!='checkpoint':return
    report=body.get('report') or {}
    if lane=='pump':
        for row in report.get('full_evidence_candidates',[]):
            complete=row.get('stage')=='full_point_in_time'
            yield dict(identity=[row.get('mint'),row.get('mode'),row.get('observed_at')],asset=row.get('mint'),
                vector=row,complete=complete,grade='authenticated_complete' if complete else 'censored',
                pre_outcome=True,qualified=row.get('qualified') is True)
    elif lane=='meteora':
        for row in report.get('attempts',[]):
            v=row.get('pre_entry_features');q=row.get('qualification')
            complete=isinstance(v,dict) and isinstance(q,dict)
            yield dict(identity=[row.get('pool'),row.get('attempt'),row.get('handoff_started_at')],asset=row.get('pool'),
                vector=v or {},complete=complete,grade='authenticated_complete' if complete else 'censored',
                pre_outcome=not bool(row.get('lifecycle')),qualified=(q or {}).get('passes') is True)
    elif lane=='ramses':
        for screen in report.get('natural_screens',[]):
            for row in screen.get('rows',[]):
                yield dict(identity=[row.get('pool'),screen.get('finalized_block')],asset=row.get('pool'),
                    vector=row,complete=False,grade='finalized_screening_only',pre_outcome=True,
                    qualified=row.get('qualified') is True)


def freeze_observation(lane,candidate,event,registry):
    policy=registry['lanes'][lane]['policy_hash']
    observed_policy=event['body'].get('policy_hash')
    if observed_policy!=policy:raise ValueError('shadow_frozen_policy_mismatch')
    cutoff=int(datetime.fromisoformat(registry['registration_not_before_utc']).timestamp()*10**9)
    eligible=(candidate['complete'] and candidate['grade']=='authenticated_complete'
              and candidate['pre_outcome'] and event['at_ns']>=cutoff)
    evidence=dict(lane=lane,source_event_hash=event['hash'],source_at_ns=event['at_ns'],
        candidate=candidate,policy_hash=policy)
    return dict(lane=lane,observation_id=digest([lane,candidate['identity']]),
        asset=candidate['asset'],policy_hash=policy,research_registry_hash=digest(registry),
        strategy_evidence_hash=digest(evidence),source_event_hash=event['hash'],
        source_at_ns=event['at_ns'],evidence_grade=candidate['grade'],
        qualified_by_frozen_policy=candidate['qualified'],prospective_feature_eligible=eligible,
        scores=scores(candidate['vector'],registry['lanes'][lane]['models']),
        outcome_status='unobserved',allocation_authority=False,
        limitations=[] if eligible else ['incomplete_or_screening_only_or_post_outcome_or_before_registration'])


def discrimination(rows,model,min_outcomes=30,min_assets=10):
    """After-cost win/loss AUC over separately authenticated outcome joins only.

    No inference with tiny samples; ties contribute exactly one half. Unjoined
    candidates and screening observations are excluded from both denominators.
    """
    usable=[r for r in rows if r.get('prospective_feature_eligible') and r.get('outcome_status')=='authenticated_settled'
            and r.get('scores',{}).get(model) is not None and type(r.get('net_native')) is int]
    assets={r['asset'] for r in usable};wins=[r for r in usable if r['net_native']>0];losses=[r for r in usable if r['net_native']<=0]
    result=dict(outcomes=len(usable),distinct_assets=len(assets),winners=len(wins),nonpositive=len(losses),auc=None,
        promotion_eligible=False,denominator='complete_prospective_authenticated_after_cost_settlements_only')
    if len(usable)<min_outcomes or len(assets)<min_assets or not wins or not losses:
        result['reason']='insufficient_independent_outcome_evidence';return result
    favorable=sum(Fraction(1) if Decimal(w['scores'][model])>Decimal(l['scores'][model]) else
                  Fraction(1,2) if Decimal(w['scores'][model])==Decimal(l['scores'][model]) else Fraction(0)
                  for w in wins for l in losses)
    auc=favorable/(len(wins)*len(losses));result['auc']=dict(numerator=auc.numerator,denominator=auc.denominator)
    result['reason']='exploratory_only_requires_later_prospective_validation';return result


def analyze(run_dir,output,registry_path):
    root=Path(run_dir);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    registry=json.loads(Path(registry_path).read_text());result=json.loads((root/'result.json').read_text())
    summary=dict(run_id=result['run_id'],registry_hash=digest(registry),automatic_promotion=False,
        source_integration_sha=result.get('integration_sha'),analysis_integration_sha=None,lanes={})
    for lane in LANES:
        if result['lanes'][lane]['policy_hash']!=registry['lanes'][lane]['policy_hash']:
            raise ValueError('shadow_source_policy_mismatch')
        path=root/lane/'telemetry.sqlite'
        if not path.exists():raise ValueError('shadow_source_journal_missing:'+lane)
        journal=Journal(path);frozen={};reasons=Counter()
        try:
            for event in journal.records():
                if event['lane']!=lane:raise ValueError('shadow_cross_lane_evidence')
                for candidate in candidate_vectors(lane,event):
                    identity=digest([lane,candidate['identity']])
                    if identity in frozen:continue
                    row=freeze_observation(lane,candidate,event,registry);frozen[identity]=row
                    reasons.update(row['limitations'])
        finally:journal.close()
        rows=list(frozen.values());(output/(lane+'.observations.jsonl')).write_text(''.join(canonical(row)+'\n' for row in rows))
        summary['lanes'][lane]=dict(policy_hash=registry['lanes'][lane]['policy_hash'],observations=len(rows),
            prospective_feature_observations=sum(r['prospective_feature_eligible'] for r in rows),
            natural_qualified=sum(r['qualified_by_frozen_policy'] and r['prospective_feature_eligible'] for r in rows),
            missing_forward_outcomes=len(rows),censor_reasons=dict(reasons),
            models={m['id']:discrimination(rows,m['id'],registry['minimum_outcomes_for_exploratory_discrimination'],registry['minimum_distinct_assets']) for m in registry['lanes'][lane]['models']},
            range_alternatives_studied=0,range_policy=registry['range_policy'],
            limitations=['Native outcome adapters must authenticate full path/cost joins before economic performance can be inferred.',
                'These scores do not select, exclude or allocate any frozen-strategy trade.',
                'No missing mark, fee, cost or forward return is imputed as zero.'])
    (output/'registry.json').write_text(canonical(registry)+'\n')
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--registry',default=str(Path(__file__).with_name('shadow_registry.json')))
    args=parser.parse_args();print(canonical(analyze(args.run_dir,args.output,args.registry)))
