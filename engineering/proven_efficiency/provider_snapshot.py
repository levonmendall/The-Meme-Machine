"""Sanitized offline attribution of a supplied, consistent provider DB copy.

Uses existing durable counters and bounded audit rings. Never connects to a
provider, writes the input, reconstructs market evidence, or infers a month.
"""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3

from meme_machine.runtime.cu import DEFAULT,estimate


def category(lane,scope):
    if lane!='pons':return 'historical_inactive_family' if lane in ('ramses','meteora') else 'unattributed'
    # usd_valuation uses this scope even when no position exists. Legacy
    # transport priority/scope cannot establish its logical trading consumer.
    if scope=='position_monitor':return 'unattributed'
    if scope=='pons_historical_preparation':return 'history_receipt'
    return 'unattributed'


def quantiles(values):
    values=sorted(values)
    if not values:return None
    return {name:values[min(len(values)-1,int((len(values)-1)*p))]
            for name,p in (('p50',.5),('p95',.95),('p99',.99),('max',1))}


def read_report(path):
    path=Path(path).resolve()
    if not path.is_file() or path.stat().st_size>16*1024*1024:raise ValueError('offline_snapshot_size')
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        if db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise ValueError('offline_snapshot_integrity')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'provider_usage','limits'}<=tables:raise ValueError('offline_snapshot_schema')
        spec=json.loads(DEFAULT.read_bytes());weights=dict(spec['methods'],**spec.get('throughput_overrides',{}))
        def safe_methods(items):
            result=Counter()
            for method,n in items:result[method if method in weights else 'unpriced_method']+=n
            return dict(result)
        counters=defaultdict(Counter)
        for lane,metric,value in db.execute('SELECT lane,metric,SUM(value) FROM provider_usage GROUP BY lane,metric'):
            # Do not export endpoint identities, arbitrary strings, or payloads.
            counters[lane if lane in ('pons','ramses','meteora','pump') else 'unknown'][metric]+=value
        lanes={}
        for lane,counts in sorted(counters.items()):
            methods=safe_methods((k[7:],int(v)) for k,v in counts.items() if k.startswith('method:'))
            starts=int(counts['physical_http_requests']);completed=int(counts['completed_transport_attempts'])
            lanes[lane]=dict(physical_starts=starts,completed_attempts=completed,
                unresolved_counter_difference=starts-completed,
                logical_rpc_elements=int(counts['logical_rpc_calls']),methods=methods,
                estimated_billed_cu=estimate(methods),
                estimated_throughput_cu=(sum(weights[m]*n for m,n in methods.items())
                    if all(m in weights for m in methods) else None),
                retries=int(counts['retries']),responses_429=int(counts['responses_429']),
                recorded_failure_count=sum(v for k,v in counts.items() if k.startswith('failure:')),
                total_queue_wait_seconds=counts['provider_queue_wait_seconds'],
                total_transport_seconds=counts['transport_latency_seconds'],
                delivered_bytes=counts.get('response_bytes'),request_bytes=counts.get('request_bytes'),
                historical_inactive_family=lane in ('ramses','meteora'))
        rings={}
        for table in ('transport_starts','transports'):
            if table not in tables:continue
            if db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]>4096:raise ValueError('offline_audit_ring_bound')
            groups=defaultdict(lambda:dict(records=0,methods=Counter(),failures=0,retries=0,wait=[],latency=[],valuation_scope=0))
            for body, in db.execute('SELECT body FROM '+table+' ORDER BY seq'):
                row=json.loads(body);label=category(row.get('lane'),row.get('scope'))
                group=groups[label];group['records']+=1
                group['methods'].update(safe_methods(Counter(row.get('methods',[])).items()))
                group['valuation_scope']+=int(row.get('lane')=='pons' and row.get('scope')=='position_monitor')
                group['failures']+=int(bool(row.get('boundary') or row.get('rpc_error_code')
                    or row.get('http_status') not in (None,200)))
                group['retries']+=int(row.get('retry_attempt',0)>0)
                for field,key in (('wait_seconds','wait'),('latency_seconds','latency')):
                    if field in row:group[key].append(row[field])
            rings[table]={label:dict(records=g['records'],methods=dict(g['methods']),
                estimated_billed_cu=estimate(g['methods']),failure_records=g['failures'],
                legacy_pons_position_monitor_scope_records=g['valuation_scope'],
                retry_records=g['retries'],queue_wait_seconds=quantiles(g['wait']),
                transport_seconds=quantiles(g['latency'])) for label,g in sorted(groups.items())}
        intervals=[r[0] for r in db.execute('SELECT DISTINCT interval FROM limits ORDER BY interval')]
        endpoints=db.execute('SELECT COUNT(*) FROM limits').fetchone()[0]
    finally:db.close()
    if hashlib.sha256(path.read_bytes()).hexdigest()!=before:raise ValueError('offline_snapshot_mutated')
    return dict(schema_version=1,classification='OBSERVED HISTORICAL LOCAL PROVIDER RECORDS; CU IS ESTIMATED',
        consistent_copy_supplied_by_caller=True,input_sha256=before,input_bytes=path.stat().st_size,
        integrity='quick_check OK; read-only input hash unchanged',lanes=lanes,audit_rings=rings,
        saved_governor=dict(endpoint_rows=endpoints,physical_start_intervals_seconds=intervals),
        total_observed_physical_starts=sum(v['physical_starts'] for v in lanes.values()),
        total_completed_attempts=sum(v['completed_attempts'] for v in lanes.values()),
        total_known_estimated_billed_cu=sum(v['estimated_billed_cu']['known_estimated_cu'] for v in lanes.values()),
        provider_calls_added=0,verified_billed_cu=None,actual_monthly_frequency=None,
        physical_evidence_consumer_native_decision_join=None,
        charged_failures=None,repeat_purchase_avoidability=None,
        limitations=['Audit rings overlap cumulative counters: never add them.',
            'Historical paused-family purchases are retained evidence, not active workloads.',
            'Old rows lack payload bytes, authenticated evidence IDs, consumer identity and native deadlines.',
            'Counter differences are unresolved attempts, not proven charged failures.',
            'Retained monotonic clocks do not establish a billing period or full-month workload.',
            'Scope-based ring attribution cannot distinguish Current from Survivor or certify reuse.'])


def main():
    from operational.tests import network_guard
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();network_guard()
    args.output.write_text(json.dumps(read_report(args.snapshot),indent=2,sort_keys=True)+'\n')


if __name__=='__main__':main()
