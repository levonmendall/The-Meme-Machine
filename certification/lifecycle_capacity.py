"""Joint lifecycle observation and acceptance; no scheduler or workload changes.

The historical recovery observer is retained. Additional service counters have
an explicit independent snapshot identity; they are never added to overlapping
owner/stage timings or used as source/retirement authority.
"""
from __future__ import annotations
from contextlib import closing
import math
from pathlib import Path
import sqlite3
import statistics
import time

from certification import cleanup_recovery as original

REVISION='joint-hot-archive-retirement-v1'
SCOPES=original.SCOPES
legacy_assessment=original.recovery_assessment


def number(value):
    return type(value) in (int,float) and math.isfinite(value) and value>=0


class LifecycleObserver(original.BacklogObserver):
    def _capture(self):
        row=super()._capture()
        if row is None:return None
        started=time.monotonic()
        with closing(sqlite3.connect(Path(self.path).resolve().as_uri()+'?mode=ro',
                uri=True,isolation_level=None,timeout=.5)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            try:
                counters=dict(db.execute('SELECT key,value FROM counters'))
                snapshot=dict(source_frames=counters.get('stream_accepted_messages',0),
                    monotonic=time.monotonic(),service={},oldest_hot_slot_age={})
                for scope in SCOPES:
                    snapshot['service'][scope]={stage:counters.get('lifecycle.'+stage+'.'+scope,0)
                        for stage in ('ingested','archived','retired','continuity')}
                    # One indexed row per scope. This is explicitly the age of
                    # the oldest *slot*, not a substituted MIN(market_time).
                    # The unchanged driver separately measures global oldest
                    # hot/retained age and its strict 240-second gate still applies.
                    oldest=db.execute('SELECT COALESCE(market_time,first_seen) '
                        'FROM records INDEXED BY records_hot_scope_slot '
                        'WHERE scope=? AND body IS NOT NULL ORDER BY slot LIMIT 1',(scope,)).fetchone()
                    snapshot['oldest_hot_slot_age'][scope]=max(0,time.time()-oldest[0]) if oldest else 0
            finally:db.execute('ROLLBACK')
        row['lifecycle_observation']=snapshot
        row['lifecycle_revision']=REVISION
        row['observer_ms']+=(time.monotonic()-started)*1000
        return row


def _recovery_series(rows,scope,field,plan):
    """Apply the original predefined windows/envelope to *each* debt stage."""
    failures=[];episodes=[]
    debt=lambda row:row['scopes'][scope][field]
    for burst in plan['burst_source_seconds']:
        baseline=[r for r in rows if burst-30<=r['source_seconds']<=burst-5]
        early=[r for r in rows if burst+8<=r['source_seconds']<=burst+45]
        late=[r for r in rows if burst+90<=r['source_seconds']<=burst+120]
        result=dict(burst_source_seconds=burst,passed=False)
        if min(len(baseline),len(early),len(late))>=3:
            baseline_max=max(map(debt,baseline));peak=max(map(debt,early))
            late_mean=statistics.mean(map(debt,late));decline=peak-min(map(debt,late))
            envelope=baseline_max+plan['pipeline_slack_records']
            result.update(baseline_max=baseline_max,early_peak=peak,late_mean=late_mean,
                allowed_late_mean=envelope,decline_records=decline,
                passed=late_mean<=envelope and (peak<=envelope or decline>=plan['minimum_decline_records']))
        episodes.append(result)
        if not result['passed']:failures.append(f'{scope}:{field}:burst:{burst}')
    horizon=plan['extended_frames']*.27
    first=[r for r in rows if horizon-240<=r['source_seconds']<horizon-120]
    last=[r for r in rows if horizon-120<=r['source_seconds']<horizon]
    tail=dict(passed=False)
    if min(len(first),len(last))>=10 and last[-1]['source_seconds']>=horizon-15:
        before=statistics.mean(map(debt,first));after=statistics.mean(map(debt,last))
        envelope=max(e.get('baseline_max',0) for e in episodes)+plan['pipeline_slack_records']
        tail.update(first_mean=before,last_mean=after,allowed_late_mean=envelope,
            passed=after<=envelope and after<=before+plan['trend_slack_records'])
    if not tail['passed']:failures.append(f'{scope}:{field}:sustained_growth_or_missing_tail')
    return dict(passed=not failures,failures=failures,episodes=episodes,tail=tail)


def assessment(samples,errors=()):
    # Preserve the original fixed Meteora cohort and archived-debt acceptance.
    result=legacy_assessment(samples,errors)
    failures=list(result['failures']);advancing=[];last=-1
    for sample in samples:
        try:
            if sample.get('lifecycle_revision')!=REVISION:raise ValueError()
            observed=sample['lifecycle_observation']
            if type(observed['source_frames']) is not int:raise ValueError()
            if observed['source_frames']<sample['source_frames']:raise ValueError()
            for scope in SCOPES:
                for field in ('hot','archived_pending','oldest_age'):
                    if not number(sample['scopes'][scope][field]):raise ValueError()
                if sample['scopes'][scope]['oldest_age']>=240:raise ValueError()
                age=observed['oldest_hot_slot_age'][scope]
                if not number(age) or age>=240:raise ValueError()
                for stage in ('ingested','archived','retired','continuity'):
                    value=observed['service'][scope][stage]
                    if type(value) is not int or value<0:raise ValueError()
            if not number(sample['observer_ms']):raise ValueError()
        except (KeyError,TypeError,ValueError):
            failures.append('invalid_or_missing_lifecycle_observation')
            continue
        if sample['source_frames']>last:
            advancing.append(sample);last=sample['source_frames']
    series={}
    if len(advancing)<30:failures.append('insufficient_joint_lifecycle_observations')
    else:
        for scope in SCOPES:
            series[scope]={}
            for field in ('hot','archived_pending'):
                row=_recovery_series(advancing,scope,field,original.plan())
                series[scope][field]=row;failures.extend(row['failures'])
            service=[r['lifecycle_observation']['service'][scope] for r in advancing]
            for stage in ('ingested','archived','retired','continuity'):
                if any(b[stage]<a[stage] for a,b in zip(service,service[1:])):
                    failures.append(f'{scope}:{stage}:service_counter_regressed')
            if service[-1]['ingested']>service[0]['ingested']:
                if any(service[-1][stage]<=service[0][stage] for stage in ('archived','retired')):
                    failures.append(f'{scope}:lifecycle_service_starved')
    # Instrumentation overhead is a measurement, not CPU time. The ratio is
    # summed short reader wall times divided by the observed wall interval.
    # No overlapping source/owner/archive timing is added into this number.
    overhead=dict(passed=False)
    if len(advancing)>=2:
        elapsed=advancing[-1]['monotonic']-advancing[0]['monotonic']
        measured_ms=sum(r['observer_ms'] for r in advancing[1:])
        ratio=measured_ms/(1000*elapsed) if elapsed>0 else float('inf')
        overhead=dict(observer_wall_fraction=ratio,observer_peak_ms=max(r['observer_ms'] for r in advancing),
            passed=ratio<=original.plan().get('observer_wall_fraction_limit',.01))
    if not overhead['passed']:failures.append('observer_overhead_not_bounded')
    result.update(passed=not failures,failures=sorted(set(failures)),
                  lifecycle_revision=REVISION,joint_lifecycle=series,observer_overhead=overhead)
    return result
