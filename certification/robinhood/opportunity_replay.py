"""Bounded Pons policy comparison using only evidence committed at d1fc1614.

No general dataset is created. Missing early features/outcomes remain UNKNOWN.
Policies and the selection rule are frozen in the Pons source tree before this
validation. This command also verifies the actual composed production policy.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys

FIXTURE_SHA256='1be70cb9f53bfc9bce039f6913813a6d2a0a21dde39b6b10bf95b9123f47597f'
RUNS=(357,358,360,362,364,366,367,368)
UNKNOWN=dict(value=None,status='UNMEASURABLE',denominator=0)


def validate_point_in_time(row, asof):
    if any(e['event_at']>asof for e in row['market_events']):raise ValueError('future_event')
    if any(s['at']>asof for s in row['trajectory_snapshots']):raise ValueError('future_snapshot')


def run(fixture,pons,output,supplement):
    attempts=[]
    def guard(event,args):
        if event in ('socket.connect','socket.getaddrinfo'):
            attempts.append(event);raise RuntimeError('strategy_replay_network_forbidden')
    sys.addaudithook(guard)
    sys.path.insert(0,str(Path(pons).resolve()))
    from robinhood_research import pons_selective_continuation as policy
    from robinhood_research.pons_opportunity_research import preservation,fill_hysteresis,acceptable,SELECTED_POLICY
    from certification.robinhood.replay import reconstruct
    raw=Path(fixture).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=FIXTURE_SHA256:raise ValueError('evidence_cutoff_changed')
    data=json.loads(gzip.decompress(raw))
    if tuple(r['run'] for r in data['runs'])!=RUNS:raise ValueError('run_population_changed')
    spec_path=Path(pons)/'research/pons-opportunity-preservation-v2/policies.json'
    spec=json.loads(spec_path.read_text());spec_hash=hashlib.sha256(spec_path.read_bytes()).hexdigest()
    if policy.POLICY_HASH!=spec['baseline_policy_hash']:raise ValueError('unapproved_production_policy')
    manifest=[];units={};decisions=[];fills=[];divergences=[];known_early=0
    for run in data['runs']:
        n=run['run'];retained=run['pons'];rows=retained['rows']
        anchors={};regimes={};complete=retained['complete']
        for row in sorted(complete,key=lambda x:(x['vector']['asof'],x['source_transaction'])):
            v=reconstruct(row,retained['strategy_capital_quote']);old=row['vector']
            if any(old.get(k)!=v.get(k) for k in set(old)|set(v) if k!='wallet_convergence'):
                divergences.append(dict(run=n,curve=row['curve']))
            validate_point_in_time(row,v['asof'])
            curve=row['curve'];regimes.setdefault(curve,0)
            if v['current_threshold_pass']:
                if curve in anchors and policy.reentry_regime_reset(anchors[curve],v):regimes[curve]+=1
                anchors[curve]=v
            key=(n,curve,regimes[curve]);units.setdefault(key,[]).append(v)
            # These are already completed canonical vectors. They cannot stand in
            # for the absent earlier preflight features or counterfactual timing.
            facts=dict(scope_valid=v['pair_token']==policy.ZERO,provenance_valid=True,
                progress_bps=v['progress_bps'],token_age_seconds=v['token_age_seconds'],
                current_snipe_bps=v['current_snipe_bps'],trajectory=v['trajectory'],
                creator_adverse=bool(v['demand']['creator_sell_quote_15s'] or (v.get('creator_history') or {}).get('adverse')))
            disposition=preservation(facts)
            decisions.append(dict(run=n,curve=curve,regime=regimes[curve],source_transaction=row['source_transaction'],
                qualified=v['current_threshold_pass'],reasons=v['all_rejections'],
                amount_quote=v['proposed_size']['amount_quote'],modeled_roundtrip_loss_bps=v['roundtrip_loss_bps'],
                policy_1_state_on_completed_vector=disposition['state'],
                original_precanonical_state='UNKNOWN',forward_outcome='UNKNOWN'))
        for row in rows:
            if row.get('screened_out') and row.get('prospect_preflight') is not None:known_early+=1
        for life in retained['lifecycles']:
            p=life.get('entry_persistence') or {};d=p.get('demand') or {}
            hard=[]
            if d.get('creator_sell_quote_15s',0)>0:hard.append('creator_distribution')
            if d.get('current_net_quote',0)<=0:hard.append('nonpositive_net_demand')
            observation=dict(observation_id=life['source_transaction'],at=life['started_at'],trusted=True,
                quote_age_seconds=p.get('quote_age_after_confirmation_seconds'),hard_invalidators=hard,
                soft_deterioration=bool(p.get('reasons')))
            outcome=fill_hysteresis(None,observation)
            fills.append(dict(run=n,curve=life['curve'],source_transaction=life['source_transaction'],
                baseline_status=life['status'],policy_2_action=outcome['action'],
                hard_invalidators=outcome['hard_invalidators'],quote_age_seconds=observation['quote_age_seconds'],
                entry_tokens=(life.get('final_position') or {}).get('entry_tokens'),
                forward_observations=len(life.get('monitor') or []),counterfactual_economics='UNMEASURABLE'))
        manifest.append(dict(run=n,retained_decision_rows=len(rows),
            rows_with_native_identity=sum(bool(r.get('curve')) for r in rows),
            native_curves=len({r['curve'] for r in rows if r.get('curve')}),
            screened_observations=sum(r.get('screened_out') is True for r in rows),
            complete_vectors=len(complete),complete_native_curves=len({r['curve'] for r in complete}),
            grade_a_units=sum(k[0]==n for k in units),
            qualified_grade_a_units=sum(k[0]==n and any(v['current_threshold_pass'] for v in vs) for k,vs in units.items()),
            recorded_lifecycle_attempts=len(retained['lifecycles'])))
    supplemental=json.loads(Path(supplement).read_text())
    supplemental_states=Counter()
    for r in supplemental['observations']:
        # Specific preflight facts absent from the compact primary rows. No
        # decision-time feature or later price is filled from another observation.
        facts=dict(scope_valid=r['pair_token']==policy.ZERO,provenance_valid=r['code_factory_authentication']=='passed',
            current_snipe_bps=r['current_snipe_bps'])
        supplemental_states[preservation(facts)['state']]+=1
    qualified=sum(any(v['current_threshold_pass'] for v in vs) for vs in units.values())
    fills_count=sum(bool(f['entry_tokens']) for f in fills)
    metrics=dict(incremental_unique_winners=None,incremental_losers=None,downside_change=None,canonical_workload_change=None)
    folds=[]
    for omitted in RUNS:
        relevant=[m for m in manifest if m['run']!=omitted]
        folds.append(dict(omitted_run=omitted,grade_a_units=sum(m['grade_a_units'] for m in relevant),
            complete_vectors=sum(m['complete_vectors'] for m in relevant),selected_policy=0,
            revised_policy_acceptable=acceptable(metrics),reason='forward_outcomes_and_workload_unestablished'))
    report=dict(schema='pons-opportunity-comparison-v1',fixture_sha256=FIXTURE_SHA256,policy_spec_sha256=spec_hash,
        implementation_sha256={name:hashlib.sha256((Path(pons)/'robinhood_research'/name).read_bytes()).hexdigest()
            for name in ('pons_selective_continuation.py','pons_selective_paper.py','pons_opportunity_research.py')},
        policy_hash=policy.POLICY_HASH,selected_policy=SELECTED_POLICY,production_strategy_changed=False,
        evidence_cutoff=spec['evidence_cutoff_integration'],provider_calls=0,network_attempts=len(attempts),
        manifest=dict(detailed_runs=manifest,aggregate_or_partial_runs=data['unavailable_runs'],
            primary_unit=spec['unit'],grade_a_units=len(units),complete_vector_rows=len(decisions),
            complete_native_curves=len({(d['run'],d['curve']) for d in decisions}),
            grade_b_supported_unique_opportunities=0,forward_labeled_grade_a_units=0,
            early_screen_rows_with_required_features=known_early,
            supplementary_preflight=dict(path=str(Path(supplement).name),sha256=hashlib.sha256(Path(supplement).read_bytes()).hexdigest(),
                observations=len(supplemental['observations']),candidate_states=dict(supplemental_states),
                scope='overlapping diagnostic subset; not added to primary denominator',forward_outcomes=0)),
        policies=dict(policy_0='RETAINED',policy_1='NOT_SELECTED: incremental preservation and workload unmeasurable',
            policy_2='NOT_SELECTED: all seven recorded quotes violate unchanged freshness; no fresh executable soft-only comparison',
            policy_3='NOT_EVALUATED: no replicated Grade-A forward outcome support',probe='UNMEASURABLE'),
        comparison=dict(baseline=dict(grade_a_qualifying_units=qualified,grade_a_denominator=len(units),
                qualifying_vector_rows=sum(d['qualified'] for d in decisions),complete_vector_denominator=len(decisions),
                recorded_fills=fills_count,recorded_attempt_denominator=len(fills)),
            selected=dict(grade_a_qualifying_units=qualified,grade_a_denominator=len(units),
                qualifying_vector_rows=sum(d['qualified'] for d in decisions),complete_vector_denominator=len(decisions),
                recorded_fills=fills_count,recorded_attempt_denominator=len(fills)),
            grade_a_winner_capture=UNKNOWN,grade_b_preservation=UNKNOWN,loser_admission=UNKNOWN,
            executable_after_cost_economics=UNKNOWN,downside=UNKNOWN,canonical_workload_counterfactual=UNKNOWN,
            measured_modeled_roundtrip_bps=dict(denominator=len(decisions),min=min(d['modeled_roundtrip_loss_bps'] for d in decisions),max=max(d['modeled_roundtrip_loss_bps'] for d in decisions))),
        robustness=dict(method='leave_one_run_out_no_refitting',folds=folds,all_folds_retain_baseline=all(f['selected_policy']==0 for f in folds)),
        chronology={name:dict(runs=runs,grade_a_units=sum(k[0] in runs for k in units),
            qualified_units=sum(k[0] in runs and any(v['current_threshold_pass'] for v in vs) for k,vs in units.items())) for name,runs in spec['chronology'].items()},
        decisions=decisions,fill_attempts=fills,decision_divergences=divergences,
        unavailable=['early decision-time progress/age/trajectory for most screened rows','forward executable marks for unentered candidates',
            'fresh qualification-to-fill soft-only observations','provider service/deadline counterfactuals','complete point-in-time wallet skill overlay','probe/scale observations'],
        passed=not divergences and not attempts and SELECTED_POLICY==0 and not acceptable(metrics))
    Path(output).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:report[k] for k in ('passed','selected_policy','policy_hash','provider_calls','network_attempts','comparison','chronology')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--fixture',required=True);p.add_argument('--pons',required=True)
    p.add_argument('--supplement',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    raise SystemExit(run(a.fixture,a.pons,a.output,a.supplement))
