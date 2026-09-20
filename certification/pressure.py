"""Incremental read-only view of the lanes' shared provider admission evidence."""
from collections import Counter
import json
from pathlib import Path
import sqlite3
import time


class PressureView:
    def __init__(self, path):
        self.path=Path(path);self.sequence=0;self.lanes={};self.endpoints={};self.retry_counters={}
        self.admission_sequence=0;self.admissions={}

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
                        max_wait_seconds=0,total_wait_seconds=0,last_grant_monotonic=None,grants_by_minute={}))
                    stats['requested']+=1;stats['granted']+=int(event['granted']);stats['failed']+=int(not event['granted'])
                    stats['max_wait_seconds']=max(stats['max_wait_seconds'],event['wait_seconds'])
                    stats['total_wait_seconds']+=event['wait_seconds']
                    if event['granted']:
                        stats['last_grant_monotonic']=event['ended']
                        minute=str(int(event['ended']//60));stats['grants_by_minute'][minute]=stats['grants_by_minute'].get(minute,0)+1
                    self.admission_sequence=seq
            endpoints=[dict(identity=e,interval_seconds=i,cooldown_remaining_seconds=max(0,c-now),requests=self.endpoints.get(e,0)) for e,c,i in db.execute('SELECT endpoint,cooldown,interval FROM limits')]
            queues=[dict(endpoint=e,depth=n,oldest_wait_seconds=max(0,now-oldest)) for e,n,oldest in db.execute('SELECT endpoint,COUNT(*),MIN(created) FROM queue GROUP BY endpoint')]
            return dict(state='observed',last_sequence=self.sequence,lanes=self.lanes,endpoints=endpoints,queues=queues,
                        admission_by_lane=self.admissions)
        finally:db.close()
