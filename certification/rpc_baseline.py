"""Reproduce CU and duplicate-work baseline from preserved raw campaign artifacts."""
import argparse
from collections import Counter,defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from certification.cu import estimate

def baseline(root, *, run_id=35508695288, artifact_id=None, artifact_sha256=None):
    root=Path(root);run=root/'certification-hourly';result=json.loads((run/'result.json').read_text())
    lanes={};all_methods=Counter()
    # Last launch = earliest normal end minus the measured continuous overlap.
    window_end=min(r['ended_at'] for r in result['lanes'].values())
    window_start=window_end-result['continuous_overlap_seconds']
    db=sqlite3.connect((run/'shared-robinhood-admission.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    pressure=defaultdict(lambda:dict(queue_wait_seconds=0.,transport_seconds=0.,max_queue_depth=0))
    for (body,) in db.execute('SELECT body FROM transports'):
        row=json.loads(body);p=pressure[row['lane']]
        p['queue_wait_seconds']+=row.get('wait_seconds',0);p['transport_seconds']+=row.get('latency_seconds',0)
        p['max_queue_depth']=max(p['max_queue_depth'],row.get('queue_depth',0))
    db.close()
    for lane in ('pons','ramses'):
        methods=Counter();window=Counter();unique=defaultdict(set);requests=0;window_requests=0;lat=[]
        archive=run/lane/'rpc-evidence.jsonl.gz'
        for line in gzip.open(archive,'rt'):
            row=json.loads(line)
            if not row.get('transport_attempted'):continue
            requests+=1;at=row['observed_at_ns']/1e9
            within=window_start<=at<=window_end
            window_requests+=int(within)
            if row.get('transport_duration_seconds') is not None:lat.append(row['transport_duration_seconds'])
            for method,params in row['request']:
                methods[method]+=1;unique[method].add(json.dumps(params,sort_keys=True))
                if within:window[method]+=1
        all_methods.update(methods);lat.sort();native=json.loads((run/lane/('pons-selective-continuation-v1-cohort.json' if lane=='pons' else 'robinhood-ramses-extended-market-report.json')).read_text())
        d=dict(physical_http_requests=requests,logical_rpc_by_method=dict(methods),
            distinct_request_parameters_by_method={m:len(s) for m,s in unique.items()},
            observation_window=dict(physical_http_requests=window_requests,logical_rpc_by_method=dict(window),**estimate(window)),
            **estimate(methods),**pressure[lane],
            provider_latency_seconds={q:lat[int((len(lat)-1)*v)] if lat else None for q,v in [('p50',.5),('p95',.95),('p99',.99)]},
            cache_metrics=native.get('evidence_acquisition'),
            funnel=result['lanes'][lane]['funnel'],natural_settled=result['lanes'][lane]['natural_settled'],
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        if lane=='pons':
            rows=[json.loads(l) for l in (root/'certification-native/hourly/pons/pons-selective-continuation-v1-cohort/candidate-rows.jsonl').read_text().splitlines()]
            d['candidate_row_keys']=sorted(rows[0]) if rows else []
            complete=sum(r.get('vector') is not None for r in rows)
            reasons=Counter(reason for r in rows for reason in (r.get('vector') or {}).get('all_rejections',[]))
            d['stale_after_complete_evidence']=sum('stale_state_after_evidence' in (r.get('vector') or {}).get('all_rejections',[]) for r in rows)
            d['stale_after_complete_fraction']=d['stale_after_complete_evidence']/len(rows) if rows else None
            d['incomplete_reason_counts']=dict(Counter(r.get('boundary','unknown') for r in rows if r.get('vector') is None))
            d.update(evaluated_candidates=len(rows),complete_evidence_candidates=complete,reason_counts=dict(reasons),
                estimated_cu_per_evaluated=d['estimated_cu']/len(rows) if rows else None,
                estimated_cu_per_complete=d['estimated_cu']/complete if complete else None,
                useful_complete_per_request=complete/requests if requests else None,
                useful_complete_per_estimated_cu=complete/d['estimated_cu'] if d['estimated_cu'] else None)
        lanes[lane]=d
    if run_id==35508695288:
        if result['integration_sha']!='6964cfe5c501075e53f3f6f809b85bbdeb50a7cc':
            raise ValueError('baseline_revision_mismatch; specify the current run ID')
        artifact_id=artifact_id or 10605823461
        artifact_sha256=artifact_sha256 or '653ba9aaf63e591b7e6691a8b258103d527de9764b5aca722b15f18f5a564aaa'
    return dict(schema_version=1,run_id=run_id,integration_sha=result['integration_sha'],
        source_artifact_id=artifact_id,source_artifact_sha256=artifact_sha256,
        window_start=window_start,window_end=window_end,continuous_overlap_seconds=result['continuous_overlap_seconds'],
        totals_scope='full campaign including normal drain; observation-window transport counts separate',
        lanes=lanes,totals=estimate(all_methods),
        limitations=['Distinct parameter count is not authenticated unique opportunity count.',
          'Batching does not reduce billed compute units.', 'Cached reuse absent from transport archive must be read from native evidence telemetry.',
          'Provider CU schedule is a documented estimate, not an invoice.'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--artifact-root',required=True);p.add_argument('--output',required=True);p.add_argument('--run-id',type=int,default=35508695288);p.add_argument('--artifact-id',type=int);p.add_argument('--artifact-sha256');a=p.parse_args()
    Path(a.output).write_text(json.dumps(baseline(a.artifact_root,run_id=a.run_id,artifact_id=a.artifact_id,artifact_sha256=a.artifact_sha256),indent=2,sort_keys=True)+'\n')
