"""Live admission health; historical readers retain point-in-time replay semantics."""
import json
import sqlite3
from pathlib import Path

HEARTBEAT_SECONDS=15
FINALIZED_LAG_SECONDS=60
STARTUP_SECONDS=90


def evidence_health(reader,scope,now):
    def result(state,reason,**extra):return dict(state=state,usable=state=='USABLE',reason=reason,scope=scope,observed_at=now,**extra)
    try:
        health={k:json.loads(v) for k,v in reader.db.execute('SELECT * FROM service_health')}
        phase=health.get('phase','WARMING')
        if reader.db.execute("SELECT 1 FROM meta WHERE key='poisoned'").fetchone():return result('FAILED','evidence_store_poisoned')
        if phase in ('OFF','FAILED'):return result('FAILED','evidence_service_unavailable')
        if phase=='DRAINING':return result('DRAINING','evidence_service_draining')
        heartbeat=health.get('heartbeat')
        if not isinstance(heartbeat,(int,float)):return result('WARMING','evidence_health_uninitialized')
        if not 0<=now-heartbeat<=HEARTBEAT_SECONDS:return result('FAILED','evidence_heartbeat_stale')
        frontier=health.get('finalized_frontier:'+scope)
        if not frontier:return result('WARMING','evidence_cold_start')
        lag=now-frontier['time'];age=now-frontier['seen']
        if not 0<=lag<=FINALIZED_LAG_SECONDS or not 0<=age<=HEARTBEAT_SECONDS:
            return result('DEGRADED','evidence_finalized_stale',lag_seconds=lag,receipt_age_seconds=age)
        sealed=reader.db.execute('SELECT MAX(hi) FROM coverage WHERE scope=? AND available<=?',(scope,now)).fetchone()[0]
        parent=reader.db.execute('SELECT parent FROM stream_receipts WHERE scope=? AND slot=?',(scope,frontier['slot'])).fetchone()
        if sealed is None or parent is None:return result('WARMING','evidence_cold_start')
        if sealed<parent[0] or not reader.covered(scope,parent[0],sealed,as_of=now):
            return result('DEGRADED','evidence_discontinuous')
        if phase!='ACTIVE':return result('DEGRADED','evidence_source_disconnected')
        hot=sum(p.stat().st_size for p in (reader.path,Path(str(reader.path)+'-wal')) if p.exists())
        if hot>=health.get('hot_limit_bytes',2*1024*1024*1024)*.9:
            return result('DEGRADED','evidence_hot_capacity_pressure')
        return result('USABLE','authoritative_current',frontier_slot=sealed,lag_seconds=lag)
    except (sqlite3.Error,OSError,ValueError,KeyError,TypeError):
        return result('FAILED','evidence_service_unavailable')


class HealthWatch:
    """Bounded warmup and degraded windows; health observations are not evidence."""
    def __init__(self,now):
        self.started=now;self.unhealthy_since=now;self.usable_observations=0
        self.failure=None;self.last=None
    def observe(self,health,now):
        self.last=health
        if health['usable']:
            self.usable_observations+=1;self.unhealthy_since=None
        else:
            if self.unhealthy_since is None:self.unhealthy_since=now
            bound=30 if self.usable_observations else STARTUP_SECONDS
            if now-self.unhealthy_since>=bound:self.failure=health['reason']
        return self.failure
    def snapshot(self):
        return dict(usable_observations=self.usable_observations,failure=self.failure,last=self.last)
