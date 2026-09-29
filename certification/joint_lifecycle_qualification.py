"""Fresh E24 qualification: unchanged pressure, explicit joint lifecycle recovery.

E22 and E23 evidence remains immutable. Every old predicate still applies;
this version additionally rejects hot-debt growth, any starved program scope,
miscounted useful work, >=240-second age, and excessive observation overhead.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
import json
import math
import sqlite3
import statistics
import time
from unittest.mock import patch
from certification import cleanup_recovery as recovery
from certification import combined_pressure as legacy
from certification.combined_observer import Interaction, verified as observer_verified, observation_verified

PLAN_PATH=Path(__file__).with_name('joint_lifecycle_qualification_plan.json')
SCOPES=recovery.SCOPES
plan=recovery.plan
original_assessment=recovery.recovery_assessment
original_extended_verified=recovery.extended_verified


class JointBacklogObserver(recovery.BacklogObserver):
    def _capture(self):
        if self.path is None or not self.path.exists():
            return None
        started = time.monotonic()
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',
                                      uri=True, isolation_level=None, timeout=.5)) as db:
            db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
            try:
                counters = dict(db.execute('SELECT key,value FROM counters'))
                frames = counters.get('stream_accepted_messages', 0)
                if not frames:
                    return None
                source_seconds = frames*.27
                row = dict(source_frames=frames, source_seconds=source_seconds,
                           wall_time=time.time(), monotonic=time.monotonic(), scopes={}, cohorts={})
                row['archived_records'] = counters.get('archived_records', 0)
                row['compacted_records'] = counters.get('compacted_records', 0)
                for scope in SCOPES:
                    # Covering counts avoid reading the multi-megabyte payloads.
                    total = db.execute('SELECT COUNT(*) FROM records INDEXED BY records_scope_slot WHERE scope=?', (scope,)).fetchone()[0]
                    hot = db.execute('SELECT COUNT(*) FROM records INDEXED BY records_hot_scope_slot WHERE scope=? AND body IS NOT NULL', (scope,)).fetchone()[0]
                    boundary = db.execute('SELECT value FROM meta WHERE key=?', ('retention_floor:'+scope,)).fetchone()
                    floor = int(boundary[0]) if boundary else 0
                    eligible = db.execute('SELECT COUNT(*) FROM records INDEXED BY records_scope_slot WHERE scope=? AND slot<?', (scope, floor)).fetchone()[0]
                    oldest = db.execute('SELECT slot,COALESCE(market_time,first_seen) FROM records WHERE scope=? ORDER BY slot LIMIT 1', (scope,)).fetchone()
                    row['scopes'][scope] = dict(total=total, hot=hot, archived_pending=total-hot,
                        retirement_floor=floor, below_durable_floor=eligible,
                        oldest_slot=oldest[0] if oldest else None,
                        oldest_age=max(0,time.time()-oldest[1]) if oldest else 0)
                for scope,values in row['scopes'].items():
                    # Same transaction/counter snapshot as the original debt
                    # observation. Age-qualified hot rows are not a claim that
                    # protected rows can be discarded: pins/gaps still fail the
                    # pressure fixture's existing acceptance contract.
                    before=row['wall_time']-plan()['hot_residency_seconds']
                    values['age_eligible_hot']=db.execute(
                        'SELECT COUNT(*) FROM records INDEXED BY records_archive_time '
                        'WHERE body IS NOT NULL AND COALESCE(market_time,first_seen)<? AND scope=?',
                        (before,scope)).fetchone()[0]
                    oldest_hot=db.execute(
                        'SELECT COALESCE(market_time,first_seen) FROM records INDEXED BY records_archive_time '
                        'WHERE body IS NOT NULL AND scope=? '
                        'ORDER BY COALESCE(market_time,first_seen),identity LIMIT 1',
                        (scope,)).fetchone() if values['hot'] else None
                    values['oldest_hot_age']=max(0,row['wall_time']-oldest_hot[0]) if oldest_hot else 0
                row['observation_revision']='joint-lifecycle-snapshot-v1'
                for burst in plan()['burst_source_seconds']:
                    key = str(burst); current = row['scopes']['program:meteora']
                    # Freeze the first nonempty, already-eligible cohort in a
                    # predefined window. New source slots cannot refill it.
                    if (key not in self.cohorts and burst+8 <= source_seconds <= burst+45
                            and current['below_durable_floor'] > 0):
                        self.cohorts[key] = dict(cutoff_slot=current['retirement_floor'],
                            initial=current['below_durable_floor'], source_frames=frames,
                            captured_at=source_seconds)
                    cohort = self.cohorts.get(key)
                    if cohort:
                        remaining = db.execute('SELECT COUNT(*) FROM records INDEXED BY records_scope_slot WHERE scope=? AND slot<?',
                            ('program:meteora',cohort['cutoff_slot'])).fetchone()[0]
                        row['cohorts'][key] = dict(cohort, remaining=remaining)
                row['active_pins'] = db.execute('SELECT COUNT(*) FROM interests WHERE active=1').fetchone()[0]
                row['unresolved_gaps'] = db.execute('SELECT COUNT(*) FROM gaps WHERE repaired IS NULL').fetchone()[0]
            finally:
                db.execute('ROLLBACK')
        row['observer_ms'] = (time.monotonic()-started)*1000
        return row


def useful_work_verified(row):
    """Reconcile committed per-scope flow, not planned work or receipt lengths."""
    metrics=row.get('storage_maintenance') or {}
    scope_rows=row.get('retained_by_scope',[])
    if not isinstance(scope_rows,list) or len(scope_rows)!=len(SCOPES):return False
    if any(not isinstance(r,dict) or r.get('scope') not in SCOPES for r in scope_rows):return False
    remaining={r['scope']:r for r in scope_rows}
    if set(remaining)!=set(SCOPES):return False
    for scope in SCOPES:
        label=scope.split(':',1)[1]
        source=metrics.get('lifecycle.source.'+label+'.records')
        archive=metrics.get('lifecycle.archive.'+label+'.records')
        retired=metrics.get('lifecycle.retention.'+label+'.retired_records')
        if any(type(n) is not int or n<=0 for n in (source,archive,retired)):return False
        hot=remaining[scope].get('hot');pending=remaining[scope].get('archived_pending')
        if any(type(n) is not int or n<0 for n in (hot,pending)):return False
        if source!=hot+pending+retired or archive!=pending+retired:return False
    ipc=row.get('ipc') or {}
    for stage in ('source_commit','archive_commit_plan','retention'):
        prefix='owner.stage.'+stage
        calls=ipc.get(prefix+'.calls')
        if type(calls) is not int or calls<=0:return False
        for kind in ('queue','execution'):
            value=ipc.get(prefix+'.'+kind+'_total_microseconds')
            if type(value) is not int or value<0:return False
    return True


def strict_age_verified(row):
    return all(type(row.get(name)) in (int,float) and math.isfinite(row[name])
               and 0<row[name]<240 for name in ('oldest_hot_age_peak','oldest_retained_age_peak'))


def verified(row,sha):
    return observer_verified(row,sha) and strict_age_verified(row) and useful_work_verified(row)


def extended_verified(row,frames):
    return (original_extended_verified(row,frames) and observation_verified(row)
            and strict_age_verified(row) and useful_work_verified(row))


def recovery_assessment(samples,errors=()):
    result=original_assessment(samples,errors)
    failures=list(result['failures']);p=plan();advancing=[];prior=-1
    for row in samples:
        if row.get('observation_revision')!=p['joint_lifecycle_revision']:
            failures.append('joint_observation_identity_mismatch')
        if row['source_frames']>prior:
            advancing.append(row);prior=row['source_frames']
    scope_reports={};horizon=p['extended_frames']*.27
    for scope in SCOPES:
        reports={}
        for stage in ('hot','age_eligible_hot','archived_pending'):
            if any(type(r.get('scopes',{}).get(scope,{}).get(stage)) is not int
                   or r['scopes'][scope][stage]<0 for r in advancing):
                failures.append('missing_or_invalid_lifecycle_samples:'+scope+':'+stage)
                continue
            debt=lambda row:row['scopes'][scope][stage]
            episodes=[];allowances=[]
            for burst in p['burst_source_seconds']:
                baseline=[r for r in advancing if burst-30<=r['source_seconds']<=burst-5]
                early=[r for r in advancing if burst+8<=r['source_seconds']<=burst+45]
                late=[r for r in advancing if burst+90<=r['source_seconds']<=burst+120]
                if min(len(baseline),len(early),len(late))<3:
                    failures.append('missing_joint_burst_window:'+scope+':'+stage+':'+str(burst))
                    continue
                allowance=max(map(debt,baseline))+p['pipeline_slack_records'];allowances.append(allowance)
                peak=max(map(debt,early));late_mean=statistics.mean(map(debt,late))
                decline=peak-min(map(debt,late))
                ok=late_mean<=allowance and (peak<=allowance or decline>=p['minimum_decline_records'])
                episodes.append(dict(burst_source_seconds=burst,early_peak=peak,late_mean=late_mean,
                    allowed_late_mean=allowance,decline_records=decline,passed=ok))
                if not ok:failures.append('joint_debt_did_not_recover:'+scope+':'+stage+':'+str(burst))
            first=[r for r in advancing if horizon-240<=r['source_seconds']<horizon-120]
            last=[r for r in advancing if horizon-120<=r['source_seconds']<=horizon]
            tail=dict(first_count=len(first),last_count=len(last),passed=False)
            if allowances and min(len(first),len(last))>=10:
                first_mean=statistics.mean(map(debt,first));last_mean=statistics.mean(map(debt,last))
                ok=last_mean<=max(allowances) and last_mean<=first_mean+p['trend_slack_records']
                tail.update(first_mean=first_mean,last_mean=last_mean,envelope=max(allowances),passed=ok)
            if not tail['passed']:failures.append('joint_debt_tail_not_sustainable:'+scope+':'+stage)
            reports[stage]=dict(episodes=episodes,tail=tail)
        ages=[r.get('scopes',{}).get(scope,{}).get('oldest_hot_age') for r in advancing]
        if not ages or any(type(a) not in (int,float) or not math.isfinite(a) or not 0<=a<240 for a in ages):
            failures.append('joint_hot_age_missing_or_outside_limit:'+scope)
        scope_reports[scope]=reports
    overhead=dict(passed=False)
    if len(samples)>=2:
        duration=samples[-1].get('monotonic',0)-samples[0].get('monotonic',0)
        costs=[r.get('observer_ms') for r in samples]
        if duration>0 and all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in costs):
            ratio=sum(costs)/1000/duration;peak=max(costs)
            overhead=dict(wall_seconds=duration,total_observer_ms=sum(costs),
                observer_wall_fraction=ratio,peak_observer_ms=peak,
                passed=ratio<=p['observer_max_wall_fraction'] and peak<=p['observer_max_peak_ms'])
    if not overhead['passed']:failures.append('joint_observer_budget_not_proved')
    result.update(passed=not failures,failures=failures,
                  joint_lifecycle=dict(scopes=scope_reports,observer=overhead,
                      revision='joint-lifecycle-snapshot-v1'))
    return result


@contextmanager
def qualification():
    with ExitStack() as stack:
        stack.enter_context(patch.object(recovery,'PLAN_PATH',PLAN_PATH))
        stack.enter_context(patch.object(recovery,'BacklogObserver',JointBacklogObserver))
        stack.enter_context(patch.object(recovery,'recovery_assessment',recovery_assessment))
        stack.enter_context(patch.object(recovery,'extended_verified',extended_verified))
        stack.enter_context(patch.object(legacy,'Interaction',Interaction))
        stack.enter_context(patch.object(legacy,'verified',verified))
        yield


def main():
    with qualification():return recovery.main()


if __name__=='__main__':raise SystemExit(main())
