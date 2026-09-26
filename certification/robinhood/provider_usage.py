"""Endpoint ledger views. A transport attempt is counted at the HTTP boundary.

No request arguments, credential, or response bodies enter this ledger. CU is an
estimate using the repository's frozen schedule, never a billing measurement.
"""
from collections import Counter
from contextvars import ContextVar
import json
from pathlib import Path
import sqlite3

_active = ContextVar('robinhood_http_attempt', default=None)


def http_started():
    current = _active.get()
    if current is not None:
        current['physical_requests'] += 1
        row={k:v for k,v in current.items() if k!='path'}
        db=sqlite3.connect(current['path'],timeout=10)
        try:
            # Persist an initiated attempt before external I/O. A process killed
            # in flight leaves an explicit unresolved attempt, never a false zero.
            record(db,row)
            db.execute('INSERT INTO transport_starts(body) VALUES(?)',(json.dumps(row,sort_keys=True),))
            db.commit()
        finally:db.close()


def record(db, row, *, wire=True):
    """Update the shared materialized counters in the transport audit transaction."""
    counts=Counter()
    n=row.get('physical_requests',0) if wire else 0
    if not wire:counts['completed_transport_attempts']=row.get('physical_requests',0)
    counts['physical_http_requests']=n
    if n:
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
    if row.get('boundary'):counts['failure:'+row['boundary']]=1
    db.executemany('INSERT INTO provider_usage VALUES(?,?,?,?) ON CONFLICT(endpoint,lane,metric) DO UPDATE SET value=value+excluded.value',
        [(row['endpoint_fingerprint'],row['lane'],key,value) for key,value in counts.items()])


def _file_size_or_zero(path):
    """Return a transient SQLite sidecar size without TOCTOU failure."""
    try:return Path(path).stat().st_size
    except FileNotFoundError:return 0


def snapshot(path, fingerprint):
    db=sqlite3.connect(path)
    try:
        rows=db.execute('SELECT lane,metric,value FROM provider_usage WHERE endpoint=?',(fingerprint,)).fetchall()
        priorities=dict(db.execute('SELECT priority,COUNT(*) FROM queue WHERE endpoint=? GROUP BY priority',(fingerprint,)))
        has_demand=db.execute("SELECT 1 FROM sqlite_master WHERE name='logical_demand'").fetchone()
        demands=dict(db.execute('SELECT method,n FROM logical_demand WHERE endpoint=?',(fingerprint,))) if has_demand else {}
        limits=db.execute('SELECT interval,cooldown FROM limits WHERE endpoint=?',(fingerprint,)).fetchone()
    finally:db.close()
    from certification.cu import estimate
    by_lane={};totals=Counter()
    for lane,metric,value in rows:
        by_lane.setdefault(lane,Counter())[metric]+=value;totals[metric]+=value
    methods={k[7:]:int(v) for k,v in totals.items() if k.startswith('method:')}
    result={k:totals[k] for k in ('physical_http_requests','logical_rpc_calls','batch_transports','batch_members',
        'retries','responses_429','provider_queue_wait_seconds','transport_latency_seconds','repair_transports',
        'repair_logical_calls','execution_current_state_transports','execution_current_state_logical_calls')}
    result.update(endpoint_fingerprint=fingerprint,logical_calls_by_method=methods,
        consumer_logical_calls=sum(demands.values()),consumer_calls_by_method=demands,
        sanitized_failures={k[8:]:int(v) for k,v in totals.items() if k.startswith('failure:')},
        estimated_cu=estimate(methods),
        by_lane={lane:dict(physical_http_requests=c['physical_http_requests'],logical_rpc_calls=c['logical_rpc_calls'],
            estimated_cu=estimate({k[7:]:int(v) for k,v in c.items() if k.startswith('method:')})) for lane,c in by_lane.items()},
        unresolved_transport_attempts=totals['physical_http_requests']-totals['completed_transport_attempts'],
        physical_count_semantics='initiated HTTP attempts; unresolved attempts may have reached provider',
        health=dict(queue_depth=sum(priorities.values()),queue_by_priority=priorities,repair_backlog=priorities.get(40,0),
            effective_interval_seconds=limits[0],cooldown_until_monotonic=limits[1],database_bytes=Path(path).stat().st_size,
            wal_bytes=_file_size_or_zero(str(path)+'-wal')),
        historical_physical_requests='UNMEASURABLE before boundary instrumentation')
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
