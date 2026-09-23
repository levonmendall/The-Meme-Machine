"""Incremental read-only view of the lanes' shared provider admission evidence."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit
from certification.cu import estimate


class PressureView:
    def __init__(self, path):
        self.path=Path(path);self.sequence=0;self.lanes={};self.endpoints={};self.retry_counters={}
        self.admission_sequence=0;self.admissions={}
        self.endpoint_kinds={}
        endpoints=['https://rpc.mainnet.chain.robinhood.com']+[
            os.environ.get(k,'') for k in ('MM_ROBINHOOD_READ_RPC_URL','MM_ROBINHOOD_DLMM_RPC_URL','MM_ROBINHOOD_DISCOVERY_RPC_URL')]
        for endpoint in filter(None,endpoints):
            p=urlsplit(endpoint.strip());host=(p.hostname or '').lower()
            normalized=f'{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip("/")}'
            if p.query:normalized+='?'+p.query
            kind=('alchemy' if host=='alchemy.com' or host.endswith('.alchemy.com') else
                  'robinhood_public' if host=='rpc.mainnet.chain.robinhood.com' else 'configured_other')
            self.endpoint_kinds[hashlib.sha256(normalized.encode()).hexdigest()]=kind

    def snapshot(self):
        if not self.path.exists():return dict(state='not_initialized',lanes={})
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
        try:
            tables={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'transports','queue','limits'}<=tables:return dict(state='initializing',lanes={})
            for seq,body in db.execute('SELECT seq,body FROM transports WHERE seq>? ORDER BY seq',(self.sequence,)):
                row=json.loads(body);lane=row['lane'];endpoint=row['endpoint_fingerprint']
                stats=self.lanes.setdefault(lane,dict(requests=0,methods=Counter(),http_status=Counter(),rpc_errors=Counter(),retries=0,max_queue_depth=0,queue_wait_seconds=0,transport_seconds=0))
                stats['requests']+=1;stats['methods'].update(row['methods'])
                kind=self.endpoint_kinds.get(endpoint,'unknown')
                stats.setdefault('provider_methods',{}).setdefault(kind,Counter()).update(row['methods'])
                if row.get('http_status') is not None:stats['http_status'][str(row['http_status'])]+=1
                if row.get('rpc_error_code') is not None:stats['rpc_errors'][str(row['rpc_error_code'])]+=1
                # provider_topology records Rpc.retry_count: cumulative within
                # a session, not retries performed by this one transport.
                key=(lane,row.get('session'))
                cumulative=row.get('retry_count',0);previous=self.retry_counters.get(key,0)
                stats['retries']+=max(0,cumulative-previous)
                self.retry_counters[key]=max(previous,cumulative)
                stats['max_queue_depth']=max(stats['max_queue_depth'],row.get('queue_depth',0))
                stats['queue_wait_seconds']+=row.get('wait_seconds',0)
                stats['transport_seconds']+=row.get('latency_seconds',0)
                self.endpoints[endpoint]=self.endpoints.get(endpoint,0)+1
                self.sequence=seq
            now=time.monotonic()
            if 'admissions' in tables:
                for seq,body in db.execute('SELECT seq,body FROM admissions WHERE seq>? ORDER BY seq',(self.admission_sequence,)):
                    event=json.loads(body);lane=event['lane']
                    stats=self.admissions.setdefault(lane,dict(requested=0,granted=0,failed=0,
                        max_wait_seconds=0,total_wait_seconds=0,last_grant_monotonic=None,grants_by_minute={},
                        failed_by_reason={},failed_by_method={},failed_by_scope={},granted_by_priority={}))
                    stats['requested']+=1;stats['granted']+=int(event['granted']);stats['failed']+=int(not event['granted'])
                    stats['max_wait_seconds']=max(stats['max_wait_seconds'],event['wait_seconds'])
                    stats['total_wait_seconds']+=event['wait_seconds']
                    if not event['granted']:
                        for key,values in (
                            ('failed_by_reason',[event.get('reason','admission_failed')]),
                            ('failed_by_scope',[event.get('scope','unknown')]),
                            ('failed_by_method',sorted(set(event.get('methods') or ['unknown'])))):
                            for value in values:stats[key][value]=stats[key].get(value,0)+1
                    if event['granted']:
                        priority=str(event.get('priority','unknown'))
                        stats['granted_by_priority'][priority]=stats['granted_by_priority'].get(priority,0)+1
                        stats['last_grant_monotonic']=event['ended']
                        minute=str(int(event['ended']//60));stats['grants_by_minute'][minute]=stats['grants_by_minute'].get(minute,0)+1
                    self.admission_sequence=seq
            endpoints=[dict(identity=e,interval_seconds=i,cooldown_remaining_seconds=max(0,c-now),requests=self.endpoints.get(e,0)) for e,c,i in db.execute('SELECT endpoint,cooldown,interval FROM limits')]
            queues=[dict(endpoint=e,depth=n,oldest_wait_seconds=max(0,now-oldest)) for e,n,oldest in db.execute('SELECT endpoint,COUNT(*),MIN(created) FROM queue GROUP BY endpoint')]
            for stats in self.lanes.values():
                alchemy=stats['provider_methods'].get('alchemy',Counter())
                stats.update(estimate(alchemy))
                stats['alchemy_logical_calls']=sum(alchemy.values())
                stats['logical_calls']=sum(stats['methods'].values())
                stats['cu_scope']='identified_alchemy_transports_only'
                stats['unknown_provider_logical_calls']=sum(stats['provider_methods'].get('unknown',{}).values())
                if stats['unknown_provider_logical_calls']:stats['estimated_cu']=None
                stats['logical_calls_per_physical_request']=sum(stats['methods'].values())/stats['requests'] if stats['requests'] else None
            total=Counter()
            for stats in self.lanes.values():total.update(stats['provider_methods'].get('alchemy',{}))
            billing=estimate(total);billing['scope']='identified_alchemy_transports_only'
            billing['unknown_provider_logical_calls']=sum(s['unknown_provider_logical_calls'] for s in self.lanes.values())
            if billing['unknown_provider_logical_calls']:billing['estimated_cu']=None
            return dict(state='observed',estimated_cu=billing,last_sequence=self.sequence,lanes=self.lanes,endpoints=endpoints,queues=queues,
                        admission_by_lane=self.admissions)
        finally:db.close()


class ReuseView:
    def __init__(self,path):
        self.path=Path(path);self.sequence=0;self.lanes={}
    def snapshot(self):
        if not self.path.exists():return dict(state='not_initialized',lanes={})
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
        try:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'reuse_events' not in tables:return dict(state='initializing',lanes={})
            for seq,lane,method,outcome in db.execute('SELECT sequence,lane,method,outcome FROM reuse_events WHERE sequence>? ORDER BY sequence',(self.sequence,)):
                stats=self.lanes.setdefault(lane,dict(hits=Counter(),misses=Counter(),session_hits=Counter(),coalesced=Counter()))
                stats['hits' if outcome=='hit' else 'coalesced' if outcome=='coalesced' else 'session_hits' if outcome=='session_hit' else 'misses'][method]+=1
                self.sequence=seq
            return dict(state='observed',last_sequence=self.sequence,lanes=self.lanes,
                inflight_jobs=db.execute('SELECT COUNT(*) FROM flights').fetchone()[0],
                cache_entries=db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],
                database_bytes=self.path.stat().st_size,
                scope='shared provider cache lookups; lane-native caches remain separately reported')
        finally:db.close()
