"""Descriptive capacity and frozen-policy evidence reports; never promotes policy."""
from collections import Counter,defaultdict
import json
from pathlib import Path
from certification.journal import Journal,digest
from certification.report import LANES
from certification.pressure import PressureView


def percentiles(values):
    ordered=sorted(values)
    def q(p):return None if not ordered else ordered[int((len(ordered)-1)*p)]
    return dict(p50=q(.5),p95=q(.95),p99=q(.99),count=len(ordered))


def cache_measurements(state):
    cache=(state or {}).get('cache') or {}
    pairs={}
    for key,hits in cache.items():
        if not key.endswith('_hit') or not isinstance(hits,int):continue
        name=key[:-4];misses=cache.get(name+'_miss')
        if not isinstance(misses,int):continue
        pairs[name]=dict(hits=hits,misses=misses,hit_fraction=hits/(hits+misses) if hits+misses else None)
    return dict(scope='native_cumulative_lookup_counters_not_sum_of_repeated_checkpoints',by_cache=pairs) if pairs else None


def partition_pons(rows):
    complete=[];censored=[]
    for row in rows:
        vector=row.get('vector') or {};age=vector.get('decision_state_age_seconds')
        limit=(vector.get('thresholds') or {}).get('max_state_age_seconds')
        fresh=isinstance(age,(int,float)) and isinstance(limit,(int,float)) and 0<=age<=limit
        if vector.get('complete') is True and fresh:
            complete.append(dict(vector,observation_id=digest([row.get('source_transaction'),row.get('sequence')])))
        else:censored.append(row)
    return complete,censored


def report(run_dir):
    root=Path(run_dir);result=json.loads((root/'result.json').read_text())
    hours=result.get('elapsed_seconds',0)/3600
    out=dict(run_id=result['run_id'],frozen_policy=True,automatic_promotion=False,
             inference='descriptive_only_no_profitability_or_policy_promotion_claim',lanes={})
    admission_path=root/'shared-robinhood-admission.sqlite'
    admission_view=PressureView(admission_path).snapshot() if admission_path.exists() else result.get('shared_provider',{}).get('robinhood',{})
    for lane in LANES:
        path=root/lane/'telemetry.sqlite';runtime=result.get('lanes',{}).get(lane,{})
        hours=runtime.get('continuous_uptime_seconds',result.get('elapsed_seconds',0))/3600
        methods=Counter();errors=Counter();latencies=[];queue=[];sessions=set();terminal=Counter()
        candidate_rows=[];work=defaultdict(list);work_errors=Counter()
        if path.exists():
            journal=Journal(path)
            try:
                for event in journal.records():
                    if event['kind']=='rpc_transport':
                        row=event['body'];sessions.add(row['session'])
                        if row.get('transport_attempted',True):
                            methods.update(row.get('methods',[]))
                            latencies.append(row.get('transport_duration_seconds') or row['duration_seconds'])
                        if row.get('queue_wait_seconds') is not None:queue.append(row['queue_wait_seconds'])
                        if row.get('error'):errors[row['error']]+=1
                    elif event['kind']=='candidate_observation':candidate_rows.append(event['body']['observation'])
                    elif event['kind']=='evidence_work':
                        row=event['body'];work[row['stage']].append(row['duration_seconds'])
                        if row['outcome']=='exception':work_errors[row['stage']]+=1
                    elif event['kind']=='process_terminal':terminal[event['body']['status']]+=1
            finally:journal.close()
        source=root/lane
        # The real runner reports are retained as immutable original artifacts.
        filenames={'pump':'pump-acceleration-natural-prospective.json',
                   'meteora':'solana-dlmm-independent-v1-live.json',
                   'pons':'pons-selective-continuation-v1-cohort.json',
                   'ramses':'robinhood-ramses-extended-market-report.json'}
        file=source/filenames[lane]
        raw=json.loads(file.read_text()) if file.exists() else {}
        complete=[];incomplete=[]
        if lane=='pump':
            complete=raw.get('full_evidence_candidates',[])
            incomplete=[x for x in raw.get('attempts',[]) if x.get('stage')=='incomplete']
            reason_key='reasons'
        elif lane=='pons':
            if candidate_rows:raw=dict(raw,rows=candidate_rows)
            complete,incomplete=partition_pons(raw.get('rows',[]))
            reason_key='all_rejections'
        elif lane=='meteora':
            complete=[dict(x['qualification'],observation_id=digest([x.get('pool'),x.get('attempt'),x.get('handoff_started_at')])) for x in raw.get('attempts',[]) if isinstance(x.get('qualification'),dict)]
            incomplete=[x for x in raw.get('attempts',[]) if not isinstance(x.get('qualification'),dict)]
            reason_key='failed'
        else:
            complete=[dict(x,observation_id=digest([x.get('pool'),s.get('finalized_block')])) for s in raw.get('natural_screens',[]) for x in s.get('rows',[]) if x.get('reasons') is not None]
            reason_key='reasons'
        # Deduplicate identical observations, not distinct time-indexed decisions.
        unique={digest(x):x for x in complete};gates=Counter()
        for x in unique.values():gates.update(set(x.get(reason_key) or []))
        count=len(unique)
        funnel=runtime.get('funnel',{})
        rates={k:(v/hours if isinstance(v,int) and hours else None) for k,v in funnel.items()}
        physical=len(latencies)
        native_latencies=[x['evidence_acquisition_latency_seconds'] for x in raw.get('rows',[])
            if isinstance(x.get('evidence_acquisition_latency_seconds'),(int,float))]
        admission=(admission_view.get('lanes',{}).get(lane) or {})
        timed_deadline=dict(successes=sum(x<=5 for x in native_latencies),denominator=len(native_latencies),
            scope='Pons returned observations with original first-observation latency; excludes unmeasured exceptions') if lane=='pons' else None
        out['lanes'][lane]=dict(policy_hash=runtime.get('policy_hash'),funnel=funnel,funnel_per_hour=rates,
            rate_denominator_seconds=hours*3600,rate_denominator_scope='lane_process_uptime_including_normal_drain',
            physical_transport_requests=physical,logical_methods=dict(methods),retry_burden=admission.get("retries"),
            maximum_provider_queue_depth=admission.get("max_queue_depth"),
            rpc_latency_seconds=percentiles(latencies),queue_wait_seconds=percentiles(queue),
            evidence_latency_seconds=percentiles(native_latencies) if native_latencies else None,
            evidence_work_duration_seconds_by_stage={k:percentiles(v) for k,v in work.items()},
            evidence_work_exceptions_by_stage=dict(work_errors),
            deadline_success_rate=(timed_deadline['successes']/timed_deadline['denominator'] if timed_deadline and timed_deadline['denominator'] else None),
            deadline_denominator=timed_deadline,cache_reuse=cache_measurements(runtime.get('evidence_state')),
            physical_requests_per_second=physical/(hours*3600) if hours else None,
            rpc_archive_seconds=runtime.get('telemetry_archive_seconds'),
            runtime_resources=runtime.get('runtime_resources'),telemetry_cost=runtime.get('telemetry_cost'),
            rpc_archive_wall_time_fraction=(runtime['telemetry_archive_seconds']/(hours*3600)
                if hours and isinstance(runtime.get('telemetry_archive_seconds'),(int,float)) else None),
            maximum_sampled_active_shared_broker_jobs=result.get('maximum_sampled_active_broker_jobs') if lane in ('pump','meteora') else None,
            shutdown_evidence_censoring=result.get('broker_shutdown_terminals') if lane in ('pump','meteora') else None,
            errors=dict(errors),provider_sessions=len(sessions),process_terminals=dict(terminal),
            requests_per_complete_observation=physical/count if count and lane!='ramses' else None,
            unique_complete_vectors=count if lane!='ramses' else None,
            screening_only_vectors=count if lane=='ramses' else None,
            gate_evidence_grade='finalized_screening_not_receipt_authenticated_lifecycle' if lane=='ramses' else 'native_complete_fresh_vectors',
            incomplete_rows_visible=len(incomplete),
            gate_rejections=dict(gates),
            gate_marginal_survival={k:dict(passed=count-n,denominator=count,fraction=(count-n)/count) for k,n in gates.items()} if count else {},
            natural_settled=runtime.get('natural_settled',0),forced_settled=runtime.get('forced_settled',0),
            natural_settled_rate_per_hour=runtime.get('natural_settled',0)/hours if hours else None,
            capital_hour_return=None,liquidity_capacity=None,positive_negative_feature_discrimination=None,
            promotion_decision='not_eligible_without_prospective_out_of_sample_outcomes',
            limitations=[
                'RPC latency is not end-to-end evidence hydration latency.',
                'Marginal gate survival is not conditional sequential gate survival.',
                'Repeated pool/mint observations are not statistically independent.',
                'Missing metrics remain null; evidence censoring is not economic rejection.',
                'Visible incomplete rows may be a lower bound for legacy rolling buffers.',
                'Discovery rate per admission-hour requires native admission timestamps; process-hour rates include drain.',
                'Archive wall-time fraction covers raw RPC persistence only, not all telemetry CPU/I/O.',
            ])
    (root/'capacity-strategy.json').write_text(json.dumps(out,indent=2)+'\n')
    return out

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('run_dir');args=p.parse_args();report(args.run_dir)
