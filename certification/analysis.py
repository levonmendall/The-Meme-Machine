"""Descriptive capacity and frozen-policy evidence reports; never promotes policy."""
from collections import Counter,defaultdict
import json
from pathlib import Path
from certification.journal import Journal,digest
from certification.report import LANES


def percentiles(values):
    ordered=sorted(values)
    def q(p):return None if not ordered else ordered[int((len(ordered)-1)*p)]
    return dict(p50=q(.5),p95=q(.95),p99=q(.99),count=len(ordered))


def report(run_dir):
    root=Path(run_dir);result=json.loads((root/'result.json').read_text())
    hours=result.get('elapsed_seconds',0)/3600
    out=dict(run_id=result['run_id'],frozen_policy=True,automatic_promotion=False,
             inference='descriptive_only_no_profitability_or_policy_promotion_claim',lanes={})
    for lane in LANES:
        path=root/lane/'telemetry.sqlite';runtime=result.get('lanes',{}).get(lane,{})
        hours=runtime.get('continuous_uptime_seconds',result.get('elapsed_seconds',0))/3600
        methods=Counter();errors=Counter();latencies=[];queue=[];sessions=set();terminal=Counter()
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
            complete=[dict(x['vector'],observation_id=digest([x.get('source_transaction'),x.get('sequence')])) for x in raw.get('rows',[]) if isinstance(x.get('vector'),dict)]
            incomplete=[x for x in raw.get('rows',[]) if x.get('status')=='incomplete']
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
        out['lanes'][lane]=dict(policy_hash=runtime.get('policy_hash'),funnel=funnel,funnel_per_hour=rates,
            physical_transport_requests=physical,logical_methods=dict(methods),retry_burden=None,
            rpc_latency_seconds=percentiles(latencies),queue_wait_seconds=percentiles(queue),
            evidence_latency_seconds=None,deadline_success_rate=None,cache_reuse=None,
            errors=dict(errors),provider_sessions=len(sessions),process_terminals=dict(terminal),
            requests_per_complete_observation=physical/count if count else None,
            unique_complete_vectors=count,incomplete_rows_visible=len(incomplete),
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
            ])
    (root/'capacity-strategy.json').write_text(json.dumps(out,indent=2)+'\n')
    return out

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('run_dir');args=p.parse_args();report(args.run_dir)
