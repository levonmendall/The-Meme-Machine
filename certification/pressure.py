"""Incremental read-only view of the lanes' shared provider admission evidence."""
from collections import Counter
import json
from pathlib import Path
import sqlite3
import time


class PressureView:
    def __init__(self, path):
        self.path=Path(path);self.sequence=0;self.lanes={};self.endpoints={}

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
                stats['retries']+=row.get('retry_count',0)
                stats['max_queue_depth']=max(stats['max_queue_depth'],row.get('queue_depth',0))
                stats['queue_wait_seconds']+=row.get('wait_seconds',0)
                stats['transport_seconds']+=row.get('latency_seconds',0)
                self.endpoints[endpoint]=self.endpoints.get(endpoint,0)+1
                self.sequence=seq
            now=time.monotonic()
            endpoints=[dict(identity=e,interval_seconds=i,cooldown_remaining_seconds=max(0,c-now),requests=self.endpoints.get(e,0)) for e,c,i in db.execute('SELECT endpoint,cooldown,interval FROM limits')]
            queues=[dict(endpoint=e,depth=n,oldest_wait_seconds=max(0,now-oldest)) for e,n,oldest in db.execute('SELECT endpoint,COUNT(*),MIN(created) FROM queue GROUP BY endpoint')]
            return dict(state='observed',last_sequence=self.sequence,lanes=self.lanes,endpoints=endpoints,queues=queues)
        finally:db.close()
