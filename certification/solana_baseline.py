"""Reproducible wire-work baseline. Missing historical metrics stay unknown."""
import argparse
from collections import Counter,defaultdict
import gzip,json,sqlite3
from pathlib import Path
from certification.cu import estimate
from certification.report import summarize
from certification.run import REPORTS

def percentiles(values):
    v=sorted(values)
    return {f'p{p}':v[min(len(v)-1,int((len(v)-1)*p/100))] if v else None for p in (50,95,99)}

def baseline(root,run_id):
    run=Path(root);result=json.loads((run/'result.json').read_text());out={}
    for lane in ('pump','meteora'):
        methods=Counter();errors=Counter();statuses=Counter();codes=Counter();sigs=Counter();batches=Counter();lat=[];wait=[];physical=0;logical=0;replies=set();retry={}
        for line in gzip.open(run/lane/'rpc-evidence.jsonl.gz','rt'):
            r=json.loads(line);statuses[str(r.get('http_status'))]+=1
            if r.get('error'):errors[r['error']]+=1
            codes.update(map(str,r.get('json_rpc_error_codes',[])))
            if r.get('queue_wait_seconds') is not None:wait.append(r['queue_wait_seconds'])
            if r.get('transport_duration_seconds') is not None:lat.append(r['transport_duration_seconds'])
            retry[r['session']]=max(retry.get(r['session'],0),r.get('retry_count') or 0)
            if not r.get('transport_attempted',True):continue
            physical+=1;requests=r['request'] if isinstance(r['request'],list) else [r['request']]
            batches[len(requests)]+=1;logical+=len(requests)
            response=r.get('response');response=response if isinstance(response,list) else [response]
            byid={x.get('id'):x for x in response if isinstance(x,dict)}
            for q in requests:
                m=q['method'];methods[m]+=1
                if m=='getTransaction':
                    sigs[q['params'][0]]+=1
                    if isinstance(byid.get(q.get('id'),{}).get('result'),dict):replies.add(q['params'][0])
        funnel=summarize(lane,json.loads((run/lane/REPORTS[lane]).read_text()))
        out[lane]=dict(physical_http_transports=physical,logical_rpc_members=logical,methods=dict(methods),estimated_cu=estimate(methods),
            batch_size_counts=dict(batches),average_batch_occupancy=logical/physical if physical else None,
            unique_signatures_requested=len(sigs),unique_bodies_returned=len(replies),repeated_transaction_members=sum(sigs.values())-len(sigs),
            http_status_counts=dict(statuses),errors=dict(errors),json_rpc_errors=dict(codes),retries=sum(retry.values()),
            queue_wait_total_seconds=sum(wait),queue_wait=percentiles(wait),transport_latency=percentiles(lat),funnel=funnel,
            foreground_background_split=None,cache_hits=None,cache_misses=None,
            limitations=['Historical wire records do not attribute foreground/background or every cache probe.','Policy cohort differs from current execution-certification; compare engineering replay separately.'])
    db=sqlite3.connect((run/'shared-solana-evidence.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    consumers=list(db.execute('SELECT kind,state,signature FROM evidence_consumers'))
    kinds=defaultdict(set)
    for k,s,sig in consumers:kinds[sig].add(k)
    out['shared_broker']=dict(consumers_created=len(consumers),unique_consumer_signatures=len(kinds),logical_consumers_per_signature=len(consumers)/len(kinds) if kinds else None,
        consumer_states=[dict(kind=k,state=s,count=n,unique_signatures=u) for k,s,n,u in db.execute('SELECT kind,state,count(*),count(DISTINCT signature) FROM evidence_consumers GROUP BY kind,state')],
        hot_cached_bodies=db.execute('SELECT COUNT(*) FROM tx_cache').fetchone()[0],
        cached_bodies_with_only_prefetch_interest=sum(kinds.get(sig)=={'stream_prefetch'} for sig, in db.execute('SELECT signature FROM tx_cache')),
        unique_signatures_observed=db.execute('SELECT COUNT(DISTINCT signature) FROM stream_events').fetchone()[0],
        warning='Consumer deadlines are not missed economic opportunities; hot cache is not total historical hydration.')
    db.close()
    aggregate=Counter()
    for lane in ('pump','meteora'):aggregate.update(out[lane]['methods'])
    return dict(schema='solana-alchemy-baseline-v1',run_id=run_id,integration_sha=result.get('integration_sha'),scope='full observation plus normal drain',
        continuous_overlap_seconds=result.get('continuous_overlap_seconds'),lanes=out,
        aggregate=dict(methods=dict(aggregate),logical_rpc_members=sum(aggregate.values()),physical_http_transports=sum(out[l]['physical_http_transports'] for l in ('pump','meteora')),estimated_cu=estimate(aggregate)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('--run-id',required=True,type=int);p.add_argument('--output',required=True);a=p.parse_args()
    Path(a.output).write_text(json.dumps(baseline(a.root,a.run_id),indent=2,sort_keys=True)+'\n')
