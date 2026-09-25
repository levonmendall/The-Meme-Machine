"""Offline replay of retained rows. Missing timing/evidence stays unmeasurable.

This module has no provider client. Every socket connection is forbidden, even
loopback. Retained normalized evidence is used as recorded, never reauthenticated
or represented as a new chain observation.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from .plane import Plane, digest

UNMEASURABLE='UNMEASURABLE'


def reconstruct(row,capital):
    from robinhood_research.pons import CurveState
    from robinhood_research.pons_selective_continuation import qualification_vector
    c=row['candidate'];r=c['record'];gas=c['gas_meta']
    return qualification_vector(state=CurveState(**c['state']),graduation_threshold=r['graduationThreshold'],
        launch_at=row['launch_at'],snapshots=row['trajectory_snapshots'],events=row['market_events'],
        creator_groups=(r.get('deployer'),r.get('creatorFeeRecipient')),
        current_snipe_bps=c['current_snipe_bps'],lifecycle_gas_quote=2*gas['units_per_side']*gas['gas_price'],
        strategy_capital_quote=capital,asof=c['state']['timestamp'],
        evidence_available_at=row['evaluation_completed_at'],evidence_observed_at=row.get('evidence_observed_at'),
        evidence_acquisition_latency_seconds=row.get('evidence_acquisition_latency_seconds'),pair_token=r['pairToken'],
        wallet_histories=None,creator_history=None,quote_relative_strength_bps=None)


def run(fixture,pons_path,output):
    attempts=[]
    def guard(event,args):
        if event in ('socket.connect','socket.getaddrinfo'):
            attempts.append(event);raise RuntimeError('offline_replay_provider_network_forbidden')
    sys.addaudithook(guard)
    sys.path.insert(0,str(Path(pons_path).resolve()))
    from robinhood_research.pons_selective_continuation import POLICY_HASH
    fixture=Path(fixture);data=json.loads(gzip.decompress(fixture.read_bytes()))
    results=[];divergences=[];compared=0;qualifiers=0
    for retained in data['runs']:
        pons=retained['pons'];rows=pons['rows']
        complete=pons['complete'];native={r.get('curve') for r in rows if r.get('curve')}
        timed=[r for r in rows if r.get('curve') and r.get('evidence_observed_at') is not None and r.get('source_block') is not None and r.get('source_transaction')]
        # Identity/coalescing test on the *same retained decision workload*.
        # One held queue demonstrates bounded work, not invented provider timing.
        with tempfile.TemporaryDirectory() as tmp:
            plane=Plane(Path(tmp)/'replay.sqlite',clock=lambda:0)
            for row in timed:
                obs=row['source_transaction']+':'+str(row.get('source_log_index'))
                plane.observe(row['curve'],'pons',obs,row,
                    ordering=(row['source_block'],row.get('source_log_index') or 0),
                    watermark={'block':row['source_block'],'observation':obs},
                    interpretation={'retained_policy':pons['policy_hash']},observed=row['evidence_observed_at'],
                    deadline=row['evidence_observed_at']+5,priority=2)
            pending=plane.db.execute('SELECT COUNT(*) FROM candidates WHERE pending=1').fetchone()[0]
            snapshot=plane.snapshot();plane.close()
        matched=0
        for row in complete:
            if row['vector'].get('policy_hash')!=POLICY_HASH:continue
            vector=reconstruct(row,pons['strategy_capital_quote']);old=row['vector']
            # The campaign subsequently attaches a non-authorizing wallet overlay
            # from its separate skill book, absent from acquisition inputs.
            differences=[k for k in set(old)|set(vector) if k!='wallet_convergence' and old.get(k)!=vector.get(k)]
            compared+=1;qualifiers+=bool(old.get('current_threshold_pass'))
            if differences:divergences.append(dict(run=retained['run'],curve=row['curve'],fields=differences))
            else:matched+=1
        ramses=retained['ramses']
        results.append(dict(run=retained['run'],pons=dict(
            retained_decision_rows=len(rows),unique_native_candidates_in_retained_rows=len(native),
            complete_canonical_rows=len(complete),equivalent_complete_rows=matched,
            retained_qualifiers=len(pons['qualifiers']),entry_confirmations_retained=len(pons['lifecycles']),
            identity_replay=dict(timed_decision_rows=len(timed),unique_candidates=snapshot['unique_candidates'],
                held_queue_jobs=pending,superseded_transitions=snapshot['transition_events'].get('superseded',0),
                scope='all retained decision observations queued before service; no latency counterfactual'),
            historical_coverage=pons['coverage'],historical_queue=pons['queue'],historical_provider=pons['provider'],
            new_complete_decision_coverage=UNMEASURABLE,new_stale_deadline_censoring=UNMEASURABLE,
            new_logical_reads=UNMEASURABLE,new_physical_requests=UNMEASURABLE),
            ramses=dict(historical=ramses,new_deep_hydrations_avoided=UNMEASURABLE,
                new_complete_evaluations=UNMEASURABLE,new_logical_reads=UNMEASURABLE,new_physical_requests=UNMEASURABLE)))
    report=dict(scope='retained_evidence_and_identity_replay',fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
        provider_calls=0,network_attempts=len(attempts),passed=not divergences and not attempts,
        policy_hash=POLICY_HASH,complete_vectors_compared=compared,qualifiers_compared=qualifiers,
        decision_divergences=divergences,runs=results,unavailable_runs=data['unavailable_runs'],
        limitations=[
            'Compact reviews omit raw observations censored before queue admission, complete provider responses, and counterfactual service timing.',
            'Held-queue identity replay measures coalescing only. It cannot prove improved complete-decision coverage or a censoring percentage.',
            'Wallet skill-book overlay is not retained as complete point-in-time input; core qualification, inputs, reasons and economics are compared separately.',
            'Ramses compact reviews lack per-pool complete prestates and exact route-call responses. Aggregate no-route counts alone cannot certify saved physical transports.',
            'No profitability improvement is inferred.'])
    Path(output).write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('passed','provider_calls','network_attempts','complete_vectors_compared','qualifiers_compared','decision_divergences')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--fixture',required=True);p.add_argument('--pons',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();raise SystemExit(run(a.fixture,a.pons,a.output))
