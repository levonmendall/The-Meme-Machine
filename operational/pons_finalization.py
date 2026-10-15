"""Read-only, provider-free Pons audit of the retained repository evidence.

Historical decisions are never qualification labels. Each complete input vector
is reconstructed using the operational policy. Missing paths, raw authority,
fills, coverage denominators and billing data stay missing.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

SOURCE_COMMIT='5bd1a8bfb58b0a9e3df2b0a5194c6b11e0328bd0'
SOURCE_TREE='65c2f85f1c67676372ab2b449499d76a17bb224f'
ARCHIVE_COMMIT='d1fc161401869522db9abbf50e3f6073e80a4374'
ARCHIVED_STRATEGY_COMMIT='3de3d376847531ccb90e260cfcc96c37587ccb23'
FIXTURE_SHA256='1be70cb9f53bfc9bce039f6913813a6d2a0a21dde39b6b10bf95b9123f47597f'
ATTRIBUTION_PATHS={
    'hourly-pons-attribution.json':'certification/results/hourly-35578433187-pons-rpc-attribution.json',
    'hourly-provider-attribution.json':'certification/results/hourly-35589047835-provider-attribution.json',
    'smoke-pons-attribution.json':'certification/results/smoke-35578433187-pons-rpc-attribution.json',
    'smoke-provider-attribution.json':'certification/results/smoke-35589047835-provider-attribution.json',
}
MISSING='UNMEASURABLE'


def network_guard(attempts):
    def guard(event,args):
        if event in ('socket.connect','socket.getaddrinfo'):
            attempts.append(event)
            raise RuntimeError('pons_finalization_network_forbidden')
    sys.addaudithook(guard)


def reconstruct(row,capital,*,policy=None):
    from meme_machine.lanes.pons.pons import CurveState
    from meme_machine.lanes.pons.pons_selective_continuation import qualification_vector
    candidate=row['candidate'];record=candidate['record'];gas=candidate['gas_meta']
    return (policy or qualification_vector)(state=CurveState(**candidate['state']),
        graduation_threshold=record['graduationThreshold'],launch_at=row['launch_at'],
        snapshots=row['trajectory_snapshots'],events=row['market_events'],
        creator_groups=(record.get('deployer'),record.get('creatorFeeRecipient')),
        current_snipe_bps=candidate['current_snipe_bps'],
        lifecycle_gas_quote=2*gas['units_per_side']*gas['gas_price'],strategy_capital_quote=capital,
        asof=candidate['state']['timestamp'],evidence_available_at=row['evaluation_completed_at'],
        evidence_observed_at=row.get('evidence_observed_at'),
        evidence_acquisition_latency_seconds=row.get('evidence_acquisition_latency_seconds'),
        pair_token=record['pairToken'],wallet_histories=None,creator_history=None,
        quote_relative_strength_bps=None)


def load_policy(path):
    spec=importlib.util.spec_from_file_location('meme_machine.lanes.pons._frozen_audit_policy',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def controlled_tail_paths():
    """Real frozen action functions, hypothetical paths, no historical labels."""
    from decimal import Decimal
    from meme_machine.lanes.pons.pons_selective_continuation import runner_action
    from meme_machine.runtime.directional_continuation import BRIDGE_SECONDS,BRIDGE_GATES,bridge_state,scale_budget
    scenarios=[]
    equity=Decimal(100000);basis=equity*Decimal('.05');quantity=basis
    first=runner_action(tokens=int(quantity),partial_taken=False,after_cost_return_bps=1800,
        high_water_return_bps=1800,seconds_since_high=0,new_buyer_growth=True,buy_quote=2,sell_quote=1)
    sold=Decimal(first['exit_tokens']);partial=sold*Decimal('1.18');remaining=quantity-sold
    class RealizedSleeve:
        def sizing_basis(self,bps):
            # The first harvest realizes only its profit, not gross proceeds.
            realized=int(equity+partial-sold)
            return dict(realized_equity=realized,target=realized*bps//10000,available=realized)
    gates={gate:True for gate in BRIDGE_GATES}
    scale_state=dict(opened_at=0,realization_taken=True,original_basis=int(basis),
        high_water_bps=10000,first_tail_crossed_at=60)
    bridge,expired=bridge_state(scale_state,gates,now=181,ordinary_expired=True)
    assert bridge['bridged'] and not expired and bridge['bridge_deadline']==BRIDGE_SECONDS
    add=Decimal(scale_budget(scale_state,{**gates,'after_cost_return_bps':10000,
        'fresh_strategy_requalified':True,'fresh_execution_requalified':True},
        now=960,sleeve=RealizedSleeve(),execution_allowance=int(basis)))
    assert add==basis/2
    for multiple in (2,5,10,25,50):
        high=(multiple-1)*10000;floor=high*6000//10000
        action=runner_action(tokens=int(remaining),partial_taken=True,after_cost_return_bps=floor,
            high_water_return_bps=high,seconds_since_high=0,new_buyer_growth=True,buy_quote=2,sell_quote=1)
        assert action['action']=='full_exit'
        exit_price=1+Decimal(floor)/10000;exit_value=remaining*exit_price
        pnl=partial+exit_value-basis
        intermediate=None
        if multiple>=5:
            common=dict(tokens=int(remaining),partial_taken=True,high_water_return_bps=11000,
                seconds_since_high=0,new_buyer_growth=True,buy_quote=2,sell_quote=1)
            assert runner_action(after_cost_return_bps=8200,**common)['action']=='hold'
            ordinary_exit=remaining*Decimal('1.82')
            intermediate=dict(path=['1','1.18','2.10','1.82',str(multiple),str(exit_price)],
                right_tail_survives_13_percent_post_2x_pullback=True,
                always_12_percent_trail_exit_price='1.82',
                incremental_pnl_vs_ordinary_trail=str(exit_value-ordinary_exit))
        add_exit=add/2*exit_price;incremental_add_pnl=add_exit-add
        scenarios.append(dict(underlying_multiple=multiple,strategy_entry_price='1',sleeve_equity=str(equity),
            original_basis=str(basis),partial_realization_proceeds=str(partial),staged_add_basis='0',
            peak_remaining_position_value=str(remaining*multiple),exit_price=str(exit_price),exit_value=str(exit_value),
            realized_pnl=str(pnl),return_on_position_basis=str(pnl/basis),sleeve_contribution=str(pnl/equity),
            right_tail_pnl_vs_12_percent_gross_price_trail=str((exit_price-Decimal(multiple)*Decimal('.88'))*remaining),
            historical=False,first_profit_at_seconds=60,peak_at_seconds=600,exit_at_seconds=601,
            intermediate_pullback_comparison=intermediate,
            conditional_one_add=dict(add_at_seconds=960,first_2x_at_seconds=60,add_price='2',
                incremental_basis=str(add),incremental_exit_value=str(add_exit),incremental_pnl=str(incremental_add_pnl),
                sleeve_contribution=str(incremental_add_pnl/equity),
                total_realized_pnl=str(pnl+incremental_add_pnl),
                total_sleeve_contribution=str((pnl+incremental_add_pnl)/equity),
                incremental_drawdown_from_add_price_to_exit=str(max(Decimal(0),add-add_exit)),
                bridge_at_seconds=181,bridge_deadline=bridge['bridge_deadline'],
                hypothetical_invocations=1,historical_invocations=MISSING,
                assumptions=['first harvest complete; 2x persists 900 seconds before the add',
                    'within 15% of HWM and fully fresh strategy/execution requalification',
                    'all approved bridge gates true; capital, capacity and reservation available',
                    'peak at 1200s and exit at 1201s; same original basis/HWM risk reference',
                    'frictionless fills and no other intervening exit']),
            bridge_max_seconds_from_original_open=BRIDGE_SECONDS,
            assumptions=['complete original qualification and executable entry','frictionless executable size',
                'no pre-2x trail, adverse-flow, structural or safety exit','fresh independent demand',
                'valid graduation/continuation or bridge gates whenever their timing is required',
                'peak reached within the approved hold/bridge horizon','base scenario has no staged add or reservation conflict']))
    return dict(scope='hypothetical_mechanics_only',scenarios=scenarios,
        major_winner_capture=MISSING,staged_add_historical_invocations=MISSING,
        staged_add_historical_incremental_pnl=MISSING,tail_bridge_historical_invocations=MISSING,
        tail_bridge_historical_incremental_pnl=MISSING,
        suppressors=['12% ordinary trail can exit a volatile winner before 2x',
            'stop, adverse flow, structural/safety exits remain active',
            '36h Current bridge and 72h Survivor hold can end exposure before a later peak',
            'full fresh add requalification, available cash/capacity and same-asset reservations',
            'peak-profit tail retains 60% of remaining-lot peak profit at its floor; it does not retain the peak price'])


def audit(fixture,*,source_policy=None,archived_policy=None,attribution=()):
    raw=Path(fixture).read_bytes();checksum=hashlib.sha256(raw).hexdigest()
    if checksum!=FIXTURE_SHA256:raise ValueError('pons_fixture_checksum')
    data=json.loads(gzip.decompress(raw))
    from meme_machine.lanes.pons.pons_selective_continuation import POLICY,POLICY_HASH,POLICY_REVISION
    from meme_machine.lanes.pons.pons_postgrad_survivor import STRATEGY_VERSION,POLICY_HASH as survivor_hash
    frozen=load_policy(source_policy) if source_policy else None
    archived=load_policy(archived_policy) if archived_policy else None
    complete=[];all_rows=[];runs=[];methods=Counter();hits=Counter();misses=Counter();physical=0;logical=0;estimated_cu=0
    for run in data['runs']:
        pons=run['pons'];all_rows.extend(pons['rows'])
        for index,row in enumerate(pons['complete']):complete.append((run['run'],index,pons['strategy_capital_quote'],row))
        provider=pons['provider'];efficiency=provider.get('rpc_efficiency') or {};cache=efficiency.get('cache') or {}
        methods.update(provider.get('method_counts') or {});hits.update(cache.get('hits') or {});misses.update(cache.get('misses') or {})
        physical+=efficiency.get('physical_http_requests') or 0;logical+=efficiency.get('logical_wire_calls') or 0
        estimated_cu+=efficiency.get('estimated_cu') or 0
        runs.append(dict(run=run['run'],retained_rows=len(pons['rows']),complete_inputs=len(pons['complete']),
            recorded_policy_hash=pons['policy_hash'],historical_coverage=pons['coverage'],historical_queue=pons['queue'],
            historical_provider=provider,recorded_lifecycle_statuses=dict(Counter(r.get('status') for r in pons['lifecycles'])),
            warning='historical coverage, classifications, estimates and lifecycle rows are observations, not strategy or outcome labels'))
    def order(item):
        run,index,capital,row=item
        return (row['candidate']['state']['timestamp'],int(row['source_block'],16) if isinstance(row['source_block'],str) else row['source_block'],row.get('source_log_index') or 0,run,index)
    decisions=[];gates=Counter();divergences=[];past_checks=0
    for run,index,capital,row in sorted(complete,key=order):
        vector=reconstruct(row,capital);asof=vector['asof'];passed=vector['current_threshold_pass'];gates.update(vector['all_rejections'])
        future_snapshots=[p for p in row['trajectory_snapshots'] if p['at']>asof]
        future_events=[e for e in row['market_events'] if e['event_at']>asof]
        if future_snapshots or future_events:raise ValueError('pons_retained_input_future_data')
        past_checks+=1
        if frozen:
            before=reconstruct(row,capital,policy=frozen.qualification_vector)
            differences=[k for k in set(vector)|set(before) if vector.get(k)!=before.get(k)]
            if differences:divergences.append(dict(run=run,index=index,fields=sorted(differences)))
        comparison=reconstruct(row,capital,policy=archived.qualification_vector) if archived else None
        decisions.append(dict(run=run,index=index,curve=row['curve'],token=row['token'],asof=asof,
            retained_nominal_strategy_capital_quote=capital,
            first_observable_at=MISSING,first_complete_evidence_at=MISSING,
            retained_observed_at=row.get('evidence_observed_at'),retained_evidence_complete_at=row['evaluation_completed_at'],
            current_threshold_pass=passed,all_rejections=vector['all_rejections'],vector=vector,
            archived_strategy_reconstruction=None if comparison is None else dict(policy_hash=comparison['policy_hash'],
                current_threshold_pass=comparison['current_threshold_pass'],all_rejections=comparison['all_rejections']),
            authoritative_raw_coverage=MISSING,winner_multiple=MISSING,qualified_before_large_move=MISSING))
    from meme_machine.lanes.pons.pons_attempts import decision_category
    dispositions=Counter(decision_category(d['vector']) for d in decisions)
    candidate_ids={r['curve'] for r in all_rows if r.get('curve')}
    attr=[]
    for path in attribution:
        source=json.loads(Path(path).read_text())
        attr.append(dict(file=Path(path).name,archive_path=ATTRIBUTION_PATHS.get(Path(path).name,Path(path).name),
            archive_commit=ARCHIVE_COMMIT,sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            exception_only_failures=source.get('exception_only_failures'),response_error_members=source.get('response_error_members'),scope=source.get('scope')))
    hit_total=sum(hits.values());miss_total=sum(misses.values())
    return dict(schema='pons-finalization-evidence-v1',source=dict(operational_commit=SOURCE_COMMIT,operational_tree=SOURCE_TREE,
        archive_commit=ARCHIVE_COMMIT,archived_strategy_commit=ARCHIVED_STRATEGY_COMMIT,fixture_sha256=checksum,
        fixture_path='certification/evidence/robinhood-runs-355-368.json.gz',fixture_source=data['source'],
        reference_offline_replay='certification/robinhood/replay.py',
        reference_replay_note='Read for fixture semantics; this audit independently reconstructs market vectors and never treats stored decisions as labels.'),
        current_strategy=dict(version=POLICY,revision=POLICY_REVISION,hash=POLICY_HASH),
        survivor_strategy=dict(version=STRATEGY_VERSION,hash=survivor_hash),
        retained_runs=len(runs),unavailable_runs=data['unavailable_runs'],retained_decision_rows=len(all_rows),
        identified_curves_in_retained_rows=len(candidate_ids),rows_missing_curve=sum(not r.get('curve') for r in all_rows),
        complete_reconstructed_vectors=len(decisions),complete_distinct_curves=len({d['curve'] for d in decisions}),
        current_qualifying_evaluations=sum(d['current_threshold_pass'] for d in decisions),
        current_qualifying_distinct_curves=len({d['curve'] for d in decisions if d['current_threshold_pass']}),
        rejections_by_gate=dict(sorted(gates.items())),dispositions=dict(dispositions),
        chronological_point_in_time_checks=past_checks,economic_vector_divergences_from_operational_source=divergences,
        archived_policy_note='The archive predates the operational policy. Both are reconstructed; recorded decisions are not labels.',
        opportunity_recall=dict(name='PONS_CURRENT_WINNER_RECALL',denominator=MISSING,major_winners=MISSING,
            observable_before_move=MISSING,qualified_before_move=MISSING,strategy_rejected_major_winners=MISSING,
            machinery_missed_major_winners=MISSING,late_evidence=MISSING,late_provider_scheduler=MISSING,
            not_in_target_universe=MISSING,decisions=decisions),
        performance={k:MISSING for k in ('current_entries','survivor_qualifiers','survivor_entries','qualified_but_unfunded',
            'wins','losses','realized_pnl','marked_pnl','profit_factor','win_rate','median_hold','max_drawdown',
            'capital_utilization','peak_deployment','right_tail_contribution','staged_add_contribution',
            'average_executable_roundtrip_cost')},
        provider=dict(retained_pons_reported_physical_http_requests=physical,retained_pons_reported_logical_wire_calls=logical,
            retained_report_estimated_cu=estimated_cu,method_counts=dict(methods),cache_hits=dict(hits),cache_misses=dict(misses),
            reported_cache_hit_fraction=None if hit_total+miss_total==0 else hit_total/(hit_total+miss_total),
            cache_fraction_scope='reported transport-cache hits/(hits+misses); session hits/coalescing are separate; roles not separable',
            requests_per_day=MISSING,batches_per_day=MISSING,canonical_cu_per_day=MISSING,bytes=MISSING,
            monthly_pons_alchemy_cost=MISSING,position_rpc=MISSING,official_public_rpc=MISSING,sequencer_observation=MISSING,
            immutable_reused_rpc=MISSING,cost_allocation='Pons reported counters only; no Ramses or Solana totals added',attribution=attr),
        controlled_right_tail=controlled_tail_paths(),runs=runs,
        limitations=['No continuous raw all-market launch/graduation census or discovery denominator is retained.',
            'Complete normalized vectors lack a full raw log-range census, receipt/header set and provider response trace.',
            'Only 33 point-in-time complete inputs across 19 curves exist; six of fourteen runs are unavailable.',
            'No independent winner-price paths, filled execution quotes, complete Survivor history or portfolio chronology exist.',
            'Reconstructed vectors use the retained nominal strategy_capital_quote; no historical durable realized-equity ledger establishes compounding or portfolio sizing chronology.',
            'Seven recorded legacy lifecycle attempts are entry_failed; that is not a clean-room simulation of the current strategy.',
            'Reported provider counters combine roles and lack complete elapsed/batch/bytes/billing-plan attribution.',
            'Offline synthetic mechanics and queue tests cannot certify actual five-second provider deadlines or execution capacity.',
            'No missing field is filled with a new provider observation.'])


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--fixture',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--source-policy');parser.add_argument('--archived-policy')
    parser.add_argument('--attribution',action='append',default=[]);args=parser.parse_args(argv)
    attempts=[];network_guard(attempts)
    report=audit(args.fixture,source_policy=args.source_policy,archived_policy=args.archived_policy,attribution=args.attribution)
    report['provider_calls']=0;report['network_attempts']=len(attempts)
    Path(args.output).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:report[k] for k in ('complete_reconstructed_vectors','current_qualifying_evaluations',
        'current_qualifying_distinct_curves','economic_vector_divergences_from_operational_source','provider_calls','network_attempts')}))
    return bool(attempts or report['economic_vector_divergences_from_operational_source'])


if __name__=='__main__':raise SystemExit(main())
