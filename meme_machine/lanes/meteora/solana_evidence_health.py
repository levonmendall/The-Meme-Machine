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
    """Fail closed for evidence use without turning recoverable lag into process death.

    The 60-second finalized freshness rule remains authoritative in evidence_health:
    while stale, RuntimeEvidence refuses reads/admission. A temporary finalized
    backlog can recover without latching a permanent lane failure. Fatal service
    states and non-freshness degradation retain the existing bounded failure
    behavior. Terminal certification separately rejects a window that ends stale.
    """
    RECOVERABLE_REASONS=frozenset(('evidence_finalized_stale',))
    def __init__(self,now):
        self.started=now;self.unhealthy_since=now;self.usable_observations=0
        self.failure=None;self.last=None;self.degraded_since=None
        self.max_recoverable_degraded_seconds=0.0;self.recoveries=0
        self.recoverable_episodes=0;self.recoverable_reason=None
    def observe(self,health,now):
        self.last=health
        if health['usable']:
            self.usable_observations+=1
            if self.degraded_since is not None:
                self.max_recoverable_degraded_seconds=max(
                    self.max_recoverable_degraded_seconds,now-self.degraded_since)
                self.recoveries+=1
            self.unhealthy_since=None;self.degraded_since=None;self.recoverable_reason=None
            return self.failure
        reason=health.get('reason')
        if health.get('state')=='DEGRADED' and reason in self.RECOVERABLE_REASONS:
            if self.degraded_since is None:
                self.degraded_since=now;self.recoverable_episodes+=1
            self.recoverable_reason=reason
            self.max_recoverable_degraded_seconds=max(
                self.max_recoverable_degraded_seconds,now-self.degraded_since)
            # No evidence authority is granted here: health['usable'] remains false.
            # Keep the process alive so the next observation can prove recovery.
            return self.failure
        if self.unhealthy_since is None:self.unhealthy_since=now
        bound=30 if self.usable_observations else STARTUP_SECONDS
        if now-self.unhealthy_since>=bound:self.failure=reason
        return self.failure
    def terminal_failure(self):
        if self.failure:return self.failure
        if self.last is not None and not self.last.get('usable'):
            return self.last.get('reason') or 'evidence_terminal_unusable'
        return None
    def snapshot(self):
        return dict(usable_observations=self.usable_observations,failure=self.failure,last=self.last,
            recoverable_episodes=self.recoverable_episodes,recoveries=self.recoveries,
            recoverable_reason=self.recoverable_reason,
            max_recoverable_degraded_seconds=self.max_recoverable_degraded_seconds,
            terminal_failure=self.terminal_failure())
