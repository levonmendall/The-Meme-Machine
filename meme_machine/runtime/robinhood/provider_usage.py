"""Endpoint ledger views. A transport attempt is counted at the HTTP boundary.

No request arguments, credential, or response bodies enter this ledger. CU is an
estimate using the repository's frozen schedule, never a billing measurement.
"""
from collections import Counter
from contextvars import ContextVar
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time

_active = ContextVar('robinhood_http_attempt', default=None)
_purpose = ContextVar('robinhood_evidence_purpose', default=None)


@contextmanager
def evidence_work(category):
    if category not in ('canonical_verification','deep_watch','final_qualification',
                         'position_maintenance','gap_recovery','discovery','diagnostics'):
        raise ValueError('provider_evidence_category')
    token=_purpose.set(category)
    try:yield
    finally:_purpose.reset(token)


def category(scope,role=None):
    from meme_machine.lanes.pons.provider_admission import _position_work
    if _position_work.get():return 'position_maintenance'
    if _purpose.get():return _purpose.get()
    if role and 'gap_recovery' in role:return 'gap_recovery'
    if role and ('public_observation' in role or role=='pons_discovery_observation'):return 'discovery'
    scope=str(scope).lower()
    if any(x in scope for x in ('repair','gap','recovery')):return 'gap_recovery'
    if any(x in scope for x in ('scout','discovery','startup_nomination')):return 'discovery'
    if any(x in scope for x in ('paper','exit','unwind','monitor')):return 'position_maintenance'
    if 'v4' in scope:return 'deep_watch'
    if any(x in scope for x in ('survivor','entry','selective')):return 'final_qualification'
    if 'natural' in scope:return 'canonical_verification'
    return 'diagnostics'


def _transient_file_size(path):
    """Return zero when a SQLite transient file is checkpointed away mid-snapshot."""
    try:
        return Path(path).stat().st_size
    except FileNotFoundError:
        return 0


def http_started(request_bytes=0):
    from meme_machine.runtime.provider_purchases import purchase_started
    purchase_started(request_bytes)
    current = _active.get()
    if current is not None:
        current['physical_requests'] += 1
        current['request_bytes']=current.get('request_bytes',0)+request_bytes
        row={k:v for k,v in current.items() if k!='path'}
        db=sqlite3.connect(current['path'],timeout=10)
        try:
            # Persist an initiated attempt before external I/O. A process killed
            # in flight leaves an explicit unresolved attempt, never a false zero.
            record(db,row)
            db.execute('INSERT INTO transport_starts(body) VALUES(?)',(json.dumps(row,sort_keys=True),))
            from meme_machine.runtime.storage import audit_ring
            audit_ring(db,'transport_starts','no_start_delete')
            db.commit()
        finally:db.close()


def http_received(response_bytes):
    from meme_machine.runtime.provider_purchases import purchase_received
    purchase_received(response_bytes)
    current=_active.get()
    if current is not None:current['response_bytes']=current.get('response_bytes',0)+response_bytes


def record(db, row, *, wire=True):
    """Update the shared materialized counters in the transport audit transaction."""
    counts=Counter()
    n=row.get('physical_requests',0) if wire else 0
    if not wire:counts['completed_transport_attempts']=row.get('physical_requests',0)
    purpose=row.get('category','unclassified')
    if not wire:
        counts['response_bytes']=row.get('response_bytes',0)
        counts['category:'+purpose+':response_bytes']=row.get('response_bytes',0)
    counts['physical_http_requests']=n
    from meme_machine.runtime.provider_purchases import OPERATIONS,FAMILIES,CONSUMERS,PURPOSES
    label=row.get('purchase_work',{});operation=label.get('operation','unattributed')
    if operation not in OPERATIONS:operation='unattributed'
    # Fixed domains preserve family/consumer/purpose even after the bounded
    # transport audit is trimmed. This uses the existing counter transaction.
    family=label.get('family','unknown');consumer=label.get('consumer','unknown')
    acquisition=label.get('purpose','unknown')
    if family not in FAMILIES:family='unknown'
    if consumer not in CONSUMERS:consumer='unknown'
    if acquisition not in PURPOSES:acquisition='unknown'
    origin=label.get('origin_operation',operation)
    if origin not in OPERATIONS:origin='unattributed'
    prefix='purchase_work:'+':'.join((operation,family,consumer,acquisition,origin))+':'
    if n:
        counts[prefix+'physical_http_requests']=n
        counts[prefix+'request_bytes']=row.get('request_bytes',0)
        counts.update({prefix+'method:'+m:v for m,v in Counter(row['methods']).items()})
        counts[prefix+'retry_requests']=int(row.get('retry_attempt',0)>0)
    if not wire:
        counts[prefix+'delivered_payload_bytes']=row.get('response_bytes',0)
        counts[prefix+'failed_requests']=int(bool(row.get('boundary')))
    if n:
        counts['request_bytes']=row.get('request_bytes',0)
        counts['category:'+purpose+':request_bytes']=row.get('request_bytes',0)
        counts['category:'+purpose+':physical_http_requests']=n
        counts['category:'+purpose+':logical_rpc_calls']=len(row['methods'])
        counts.update({'category:'+purpose+':method:'+m:v for m,v in Counter(row['methods']).items()})
        counts['logical_rpc_calls']=len(row['methods'])
        counts.update({'method:'+m:v for m,v in Counter(row['methods']).items()})
        counts['retries']=int(row.get('retry_attempt',0)>0)
        if row.get('batch'):
            counts['batch_transports']=n;counts['batch_members']=len(row['methods'])
        for label,words in [('repair',('repair','gap')),('execution_current_state',('paper','exit','unwind','confirm','current','execution'))]:
            if any(w in row.get('scope','') for w in words):
                counts[label+'_transports']=n;counts[label+'_logical_calls']=len(row['methods'])
    counts['responses_429']=int(row.get('http_status')==429 or row.get('rpc_error_code')==429)
    counts['provider_queue_wait_seconds']=row.get('wait_seconds',0)
    counts['transport_latency_seconds']=row.get('latency_seconds',0)
    counts['category:'+purpose+':scheduling_wait_seconds']=row.get('wait_seconds',0)
    counts['category:'+purpose+':latency_seconds']=row.get('latency_seconds',0)
    if row.get('boundary'):counts['failure:'+row['boundary']]=1
    db.executemany('INSERT INTO provider_usage VALUES(?,?,?,?) ON CONFLICT(endpoint,lane,metric) DO UPDATE SET value=value+excluded.value',
        [(row['endpoint_fingerprint'],row['lane'],key,value) for key,value in counts.items()])


def snapshot(path, fingerprint):
    db=sqlite3.connect(path)
    try:
        rows=db.execute('SELECT lane,metric,value FROM provider_usage WHERE endpoint=?',(fingerprint,)).fetchall()
        priorities=dict(db.execute('SELECT priority,COUNT(*) FROM queue WHERE endpoint=? GROUP BY priority',(fingerprint,)))
        has_demand=db.execute("SELECT 1 FROM sqlite_master WHERE name='logical_demand'").fetchone()
        demands=dict(db.execute('SELECT method,n FROM logical_demand WHERE endpoint=?',(fingerprint,))) if has_demand else {}
        limits=db.execute('SELECT interval,cooldown FROM limits WHERE endpoint=?',(fingerprint,)).fetchone()
        now=time.monotonic()
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        queue_rows=db.execute(('SELECT q.created,q.deadline,COALESCE(m.lane,\'shared\') FROM queue q '
            'LEFT JOIN queue_meta m ON m.id=q.id WHERE q.endpoint=? AND q.deadline>?' if 'queue_meta' in tables else
            "SELECT created,deadline,'shared' FROM queue WHERE endpoint=? AND deadline>?"),(fingerprint,now)).fetchall()
        # Bounded retained audit samples. Old records without a start clock are
        # explicitly absent from rate estimates; lifetime counters stay intact.
        starts=[json.loads(r[0]) for r in db.execute('SELECT body FROM transport_starts '
            'WHERE json_extract(body,\'$.endpoint_fingerprint\')=? ORDER BY seq DESC LIMIT 4096',(fingerprint,))] \
            if 'transport_starts' in tables else []
        arrivals=[json.loads(r[0]) for r in db.execute('SELECT body FROM admissions '
            'WHERE json_extract(body,\'$.endpoint_fingerprint\')=? ORDER BY seq DESC LIMIT 4096',(fingerprint,))] \
            if 'admissions' in tables else []
    finally:db.close()
    from meme_machine.runtime.cu import estimate
    by_lane={};totals=Counter()
    for lane,metric,value in rows:
        by_lane.setdefault(lane,Counter())[metric]+=value;totals[metric]+=value
    methods={k[7:]:int(v) for k,v in totals.items() if k.startswith('method:')}
    result={k:totals[k] for k in ('physical_http_requests','logical_rpc_calls','batch_transports','batch_members',
        'retries','responses_429','provider_queue_wait_seconds','transport_latency_seconds','repair_transports',
        'repair_logical_calls','execution_current_state_transports','execution_current_state_logical_calls')}
    result.update(endpoint_fingerprint=fingerprint,logical_calls_by_method=methods,
        request_bytes=totals['request_bytes'],response_bytes=totals['response_bytes'],
        verified_billed_cu=None,billed_cu_status='UNMEASURED',
        work_categories={purpose:{metric[len('category:'+purpose+':'):]:value for metric,value in totals.items()
            if metric.startswith('category:'+purpose+':')} for purpose in
            {metric.split(':')[1] for metric in totals if metric.startswith('category:')}},
        consumer_logical_calls=sum(demands.values()),consumer_calls_by_method=demands,
        sanitized_failures={k[8:]:int(v) for k,v in totals.items() if k.startswith('failure:')},
        estimated_cu=estimate(methods),
        by_lane={lane:dict(physical_http_requests=c['physical_http_requests'],logical_rpc_calls=c['logical_rpc_calls'],
            estimated_cu=estimate({k[7:]:int(v) for k,v in c.items() if k.startswith('method:')})) for lane,c in by_lane.items()},
        unresolved_transport_attempts=totals['physical_http_requests']-totals['completed_transport_attempts'],
        physical_count_semantics='initiated HTTP attempts; unresolved attempts may have reached provider',
        health=dict(queue_depth=sum(priorities.values()),queue_by_priority=priorities,repair_backlog=priorities.get(40,0),
            effective_interval_seconds=limits[0],cooldown_until_monotonic=limits[1],database_bytes=Path(path).stat().st_size,
            wal_bytes=_transient_file_size(str(path)+'-wal')),
        historical_physical_requests='UNMEASURABLE before boundary instrumentation')
    from meme_machine.runtime.provider_purchases import OPERATIONS
    operations={operation:Counter() for operation in OPERATIONS};work={}
    for metric,value in totals.items():
        if metric.startswith('purchase_work:'):
            _,operation,family,consumer,purpose,origin,metric=metric.split(':',6)
            if operation not in operations:continue
            operations[operation][metric]+=value
            work.setdefault((operation,family,consumer,purpose,origin),Counter())[metric]+=value
        elif metric.startswith('operation:'):
            _,operation,metric=metric.split(':',2)
            if operation in operations:operations[operation][metric]+=value
    result['purchase_work']=[dict(zip(('operation','family','consumer','purpose','origin_operation'),key),**dict(value),
        estimated_cu=estimate({k[7:]:int(n) for k,n in value.items() if k.startswith('method:')}),
        verified_billed_cu=None) for key,value in sorted(work.items())]
    result['operation_purchases']={k:dict(v) for k,v in operations.items()}
    for value in result['operation_purchases'].values():
        value['estimated_cu']=estimate({k[7:]:int(n) for k,n in value.items() if k.startswith('method:')})
        value['verified_billed_cu']=None
    result['legacy_unattributed_physical_requests']=max(0,int(totals['physical_http_requests'])-
        sum(int(v.get('physical_http_requests',0)) for v in result['operation_purchases'].values()))
    for value in result['work_categories'].values():
        value['diagnostic_estimated_cu']=estimate({k[7:]:int(n) for k,n in value.items() if k.startswith('method:')})
        value['verified_billed_cu']=None
    recent=[row for row in starts if now-10<=row.get('admitted_at',-float('inf'))<=now]
    recent_methods=Counter(m for row in recent for m in row.get('methods',[]))
    bill=estimate(recent_methods)
    # Throughput has different method weights (notably chainId and receipts).
    schedule=json.loads((Path(__file__).resolve().parents[1]/'alchemy-cu-schedule.json').read_text())
    weights=dict(schedule['methods'],**schedule.get('throughput_overrides',{}))
    unpriced={m:n for m,n in recent_methods.items() if m not in weights}
    known_throughput=sum(weights[m]*n for m,n in recent_methods.items() if m in weights)
    throughput=None if unpriced else known_throughput
    completed=[r for r in arrivals if now-10<=r.get('ended',-float('inf'))<=now]
    arrived=[r for r in arrivals if now-10<=r.get('created',-float('inf'))<=now]
    result['health'].update(oldest_queue_wait_seconds=max([0.]+[max(0.,now-a) for a,_,_ in queue_rows]),
        queue_wait_by_consumer={lane:max([0.]+[max(0.,now-a) for a,_,l in queue_rows if l==lane])
                                for lane in {l for _,_,l in queue_rows}},
        original_deadline_remaining_seconds=min([b-now for _,b,_ in queue_rows],default=None))
    result['rolling_10_seconds']=dict(available='transport_starts' in tables and 'admissions' in tables,
        missing_rate_instrumentation_tables=sorted({'transport_starts','admissions'}-tables),
        records_without_start_clock=sum('admitted_at' not in r for r in starts),
        physical_http_attempts=sum(r.get('physical_requests',0) for r in recent),
        physical_rps=sum(r.get('physical_requests',0) for r in recent)/10,
        logical_rpc_elements=sum(recent_methods.values()),logical_calls_by_method=dict(recent_methods),
        diagnostic_method_cu=bill,diagnostic_throughput_cu=throughput,
        diagnostic_throughput_cups=None if throughput is None else throughput/10,
        known_diagnostic_throughput_cu=known_throughput,unpriced_throughput_methods=unpriced,
        completed_admissions=len(completed),admissions_arrived=len(arrived),
        admission_arrival_rate=len(arrived)/10,
        granted_admission_service_rate=sum(r.get('granted') is True for r in completed)/10,
        rates_are_retained_audit_samples=True,sample_capacity=4096,
        actual_account_capacity=None,verified_billed_cu=None)
    if not result['rolling_10_seconds']['available']:
        for key in ('physical_rps','diagnostic_throughput_cu','diagnostic_throughput_cups',
                    'admission_arrival_rate','granted_admission_service_rate'):
            result['rolling_10_seconds'][key]=None
    return result


def demand(path, fingerprint, methods):
    """Consumer demand includes exact-cache hits; wire calls remain separate."""
    db=sqlite3.connect(path,timeout=10)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS logical_demand(endpoint TEXT,method TEXT,n INTEGER,PRIMARY KEY(endpoint,method))')
        db.executemany('INSERT INTO logical_demand VALUES(?,?,?) ON CONFLICT(endpoint,method) DO UPDATE SET n=n+excluded.n',
                       [(fingerprint,m,n) for m,n in Counter(methods).items()])
        db.commit()
    finally:db.close()


def cache_snapshot(path, domain):
    if not Path(path).exists():return {}
    db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
    try:
        counts=dict(db.execute('SELECT outcome,COUNT(*) FROM reuse_events WHERE domain=? GROUP BY outcome',(domain,)))
        pending=db.execute('SELECT COUNT(*) FROM flights WHERE domain=?',(domain,)).fetchone()[0]
    finally:db.close()
    hits=sum(counts.get(k,0) for k in ('hit','session_hit','coalesced'))
    return dict(events=counts,zero_physical_request_reuses=hits,
                reuse_ratio=hits/(hits+counts.get('miss',0)) if hits+counts.get('miss',0) else None,
                repair_or_evidence_flights=pending,evidence_cache_conflicts=counts.get('conflict',0))
