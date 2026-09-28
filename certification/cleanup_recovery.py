"""Fixed-plan E22 cleanup-capacity validation; canonical drivers stay immutable.

Three exact combined replays are independent of this supplemental 1,200-second
run. The supplement reuses the actual production state, measured pressure driver,
and combined Interaction. It adds only a continuous-source tail and read-only,
low-frequency backlog/cohort measurements. No provider or market is contacted.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import subprocess
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT/'certification/cleanup_recovery_plan.json'
SCOPES = ('program:meteora', 'program:pump', 'program:pumpswap')


def plan():
    return json.loads(PLAN_PATH.read_text())


def plan_hash():
    return hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest()


def frozen_inputs():
    return all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == checksum
               for name, checksum in plan()['unchanged_inputs'].items())


def write_json(path, row):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2)+'\n')


class BacklogObserver:
    """One short-lived read snapshot every five seconds; never owner authority."""
    def __init__(self, output):
        self.output = Path(output); self.path = None; self.samples = []
        self.errors = []; self.cohorts = {}; self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name='cleanup-observer', daemon=True)
        self.thread.start()

    def attach(self, path):
        self.path = Path(path)

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

    def _run(self):
        while not self.stop.is_set():
            try:
                row = self._capture()
                if row is not None:
                    self.samples.append(row)
                    with (self.output/'backlog.jsonl').open('a') as target:
                        target.write(json.dumps(row, sort_keys=True)+'\n')
            except Exception as exc:
                # Errors are retained and fail validation; never silently infer
                # capacity from missing observations.
                if not self.stop.is_set():
                    self.errors.append(type(exc).__name__+':'+str(exc))
            self.stop.wait(plan()['sample_wall_seconds'])

    def close(self):
        self.stop.set(); self.thread.join(timeout=5)
        if self.thread.is_alive():
            self.errors.append('observer_shutdown_timeout')


def recovery_assessment(samples, errors=()):
    p = plan(); failures = list(errors); advancing = []; prior = -1
    for row in samples:
        frames = row['source_frames']
        if frames > prior:
            advancing.append(row); prior = frames
        elif frames < prior:
            failures.append('observer_source_regressed')
    if len(advancing) < 30:
        failures.append('insufficient_advancing_observations')
    if any(r.get('active_pins') or r.get('unresolved_gaps') for r in advancing):
        failures.append('unexpected_pin_or_gap')
    def debt(row):
        return row['scopes']['program:meteora']['archived_pending']
    episodes = []
    for burst in p['burst_source_seconds']:
        key = str(burst)
        baseline = [r for r in advancing if burst-30 <= r['source_seconds'] <= burst-5]
        early = [r for r in advancing if burst+8 <= r['source_seconds'] <= burst+45]
        late = [r for r in advancing if burst+90 <= r['source_seconds'] <= burst+120]
        episode = dict(burst_source_seconds=burst, passed=False)
        if len(baseline) < 3 or len(early) < 3 or len(late) < 3:
            failures.append('missing_burst_window:'+key); episodes.append(episode); continue
        baseline_max = max(map(debt,baseline)); peak = max(map(debt,early))
        late_mean = statistics.mean(map(debt,late)); allowance = baseline_max+p['pipeline_slack_records']
        tracked = [r for r in advancing if key in r['cohorts'] and r['source_seconds'] <= burst+120]
        cohort = tracked[0]['cohorts'][key] if tracked else None
        cleared = next((r for r in tracked if r['cohorts'][key]['remaining']==0), None)
        cohort_ok = bool(cohort and cohort['initial']>0 and cleared
                         and cleared['source_frames']>cohort['source_frames'])
        if any(b['cohorts'][key]['remaining'] > a['cohorts'][key]['remaining'] for a,b in zip(tracked,tracked[1:])):
            cohort_ok=False
        # One complete archived cohort must actually retire while new source is
        # committed; aggregate debt must also return to its preburst envelope.
        decline = peak-min(map(debt,late))
        decline_ok = peak <= allowance or decline >= p['minimum_decline_records']
        episode.update(baseline_max=baseline_max, early_peak=peak, late_mean=late_mean,
            allowed_late_mean=allowance, decline_records=decline,
            cohort=cohort, cohort_cleared_at=cleared['source_seconds'] if cleared else None,
            source_frames_during_clearance=cleared['source_frames']-cohort['source_frames'] if cleared and cohort else 0,
            passed=cohort_ok and late_mean<=allowance and decline_ok)
        if not episode['passed']:
            failures.append('cleanup_did_not_recover:'+key)
        episodes.append(episode)
    horizon = p['extended_frames']*.27
    tail = [r for r in advancing if horizon-240 <= r['source_seconds'] < horizon]
    first = [r for r in tail if r['source_seconds']<horizon-120]
    last = [r for r in tail if r['source_seconds']>=horizon-120]
    tail_result = dict(passed=False)
    if len(first)>=10 and len(last)>=10 and last[-1]['source_seconds']>=horizon-15 and episodes:
        first_mean = statistics.mean(map(debt,first)); last_mean = statistics.mean(map(debt,last))
        envelope = max(e.get('baseline_max',0) for e in episodes)+p['pipeline_slack_records']
        tail_result = dict(first_mean=first_mean,last_mean=last_mean,
            source_frame_advance=last[-1]['source_frames']-first[0]['source_frames'],
            passed=last_mean<=envelope and last_mean<=first_mean+p['trend_slack_records'])
    if not tail_result['passed']:
        failures.append('sustained_cleanup_debt_growth_or_missing_tail')
    return dict(passed=not failures, failures=failures, episodes=episodes, tail=tail_result,
                samples=len(advancing),observer_peak_ms=max((r.get('observer_ms',0) for r in samples),default=0))


def sql_phase(sql, native):
    label = native(sql)
    if label is not None:
        return label
    if not sql or sql[0] not in ('S', 'D'):
        return None
    if sql.startswith('SELECT MIN(slot) FROM records WHERE scope='):
        return 'retention_hot_boundary'
    if sql.startswith('SELECT MIN(lo) FROM coverage'):
        return 'retention_recent_boundary'
    if sql.startswith('SELECT lower_slot FROM interests'):
        return 'retention_pins'
    if sql.startswith('SELECT identity FROM records WHERE scope='):
        return 'retention_select_slice'
    if sql.startswith('DELETE FROM address_refs WHERE record_id IN'):
        return 'retention_address_refs'
    for table in ('hot_refs','lineage','records'):
        if sql.startswith('DELETE FROM '+table+' WHERE identity IN'):
            return 'retention_'+table
    for table in ('coverage','gaps','stream_receipts','stream_deliveries','stream_order'):
        if sql.startswith('DELETE FROM '+table+' WHERE '):
            return 'retention_continuity_'+table
    if sql.startswith('DELETE FROM archives WHERE'):
        return 'retention_archive_manifest_gc'
    return None


def extended_verified(row, frames):
    """Same resource and interaction limits, actual extended counts, no rewriting."""
    c=row.get('counters',{}); ipc=row.get('ipc',{}); joint=row.get('combined_load',{})
    bursts=joint.get('burst_evidence',[]); profile=row.get('measured_contention',{})
    return bool(row.get('passed') is True and row.get('frames')==frames
        and row.get('source_seconds')==frames*.27 and c.get('stream_accepted_messages')==frames
        and ipc.get('stream.received_messages')==ipc.get('stream.commit_messages')==frames+1
        and 16<=ipc.get('stream.outstanding_frames_peak',0)<=64
        and 0<ipc.get('stream.dispatch_bytes_peak',0)<=96*1024**2
        and 2<=ipc.get('stream.commit_batch_messages_peak',0)<=8
        and 0<ipc.get('stream.commit_batch_bytes_peak',0)<=16*1024**2
        and all(ipc.get(k,0)>0 for k in ('stream.maintenance_backpressure_batching',
            'stream.maintenance_limited_commit_batches','checkpoint.tail_deferred','checkpoint.boundary_reclaimed'))
        and row.get('provider_calls')==0 and row.get('integrity')==['ok']
        and 0<=row.get('lag_peak',float('inf'))<45
        and 0<row.get('oldest_hot_age_peak',float('inf'))<=240
        and 0<row.get('oldest_retained_age_peak',float('inf'))<=240
        and 0<row.get('hot_peak',float('inf'))<2*1024**3
        and row.get('candidate_checks',0)>1 and row.get('archive_records_verified',0)>0
        and c.get('compacted_records',0)>0
        and not any(v for k,v in c.items() if k.startswith('disconnect:') or k=='capacity_stops')
        and profile.get('profile')=='run381-fullcert-36293751021'
        and profile.get('owner_seconds_per_frame',0)>=.165
        and profile.get('archive_seconds_per_thousand',0)>=.36
        and profile.get('additional_commit_latency_seconds',0)>=.006
        and profile.get('delayed_commits',0)>0
        and joint.get('profile')=='mature-burst-reader-tail-urgent-v2'
        and joint.get('held_reader_cycles',0)>=2 and joint.get('tail_delay_cycles',0)>=2
        and joint.get('urgent_acks',0)>=10 and joint.get('urgent_errors')==[]
        and len(bursts)==2 and all(
            s.get('source_seconds',0)>=210 and s.get('archived_records',0)>0
            and s.get('compacted_records',0)>0 and s.get('observed_pause_seconds',0)>=8
            and all(s.get(k,0)>0 for k in ('multiframe_batches','source_frames_while_reader',
                    'reader_source_advance','reader_compaction_advance'))
            and s.get('reader_snapshot_preserved') is True and s.get('completed_tail_delayed') is True
            for s in bursts))


async def extended_run(output):
    from certification import run381_pressure as original, combined_pressure as combined
    from certification import pressure_diagnostics as diag
    from meme_machine.solana_evidence_plane import EvidenceWriter
    control=combined.Interaction(); native_checkpoint=EvidenceWriter.checkpoint
    observer=BacklogObserver(output); frames=plan()['extended_frames']
    native_classify=diag.statement_class
    class ObservedState(original.MeasuredServiceState):
        def __init__(self,path,config):
            super().__init__(path,config); observer.attach(path)
        def close(self):
            observer.stop.set(); return super().close()
        def source_batch(self,items):
            phase=control.source_started(len(items)); result=super().source_batch(items)
            control.source_completed(phase,len(items)); return result
    class BurstWire(original.Wire):
        def __init__(self):
            super().__init__(); self.paused=set(); self.pause_deadline=None
        async def recv(self,decode=None):
            if self.sent in (800,1400) and self.sent not in self.paused:
                self.paused.add(self.sent); sample=await asyncio.to_thread(control.inspect)
                sample['source_seconds']=self.sent*.27; control.metrics['burst_evidence'].append(sample)
                self.pause_started=time.monotonic(); self.pause_deadline=self.pause_started+8
                self.pause_sample=sample
            if self.pause_deadline is not None:
                await asyncio.sleep(max(0,self.pause_deadline-time.monotonic()))
                self.pause_sample['observed_pause_seconds']=time.monotonic()-self.pause_started
                self.pause_deadline=None
                with control.lock: control.phase+=1
            result=await super().recv(decode)
            if self.sent>=self.frames: control.stopping=True
            return result
    ack=asyncio.create_task(control.acknowledgements())
    try:
        with patch.object(original,'Wire',BurstWire), patch.object(original,'MeasuredServiceState',ObservedState), \
             patch.object(EvidenceWriter,'checkpoint',side_effect=lambda path:control.checkpoint(path,native_checkpoint)), \
             patch.object(diag,'statement_class',new=lambda sql:sql_phase(sql,native_classify)):
            code=await original.run(frames,output,measured_contention=True,diagnostics=True)
    finally:
        control.stopping=True; await asyncio.gather(ack,return_exceptions=False); observer.close()
    row=json.loads((Path(output)/'result.json').read_text())
    row['combined_load']=control.metrics
    assessment=recovery_assessment(observer.samples,observer.errors)
    row['cleanup_recovery']=assessment
    row['passed']=code==0 and extended_verified(row,frames) and assessment['passed']
    if not row['passed'] and not row.get('failure'):
        row['failure']='extended_recovery_not_proved'
    write_json(Path(output)/'extended-result.json',row)
    return row


def aggregate(root,expected_sha):
    from certification.combined_pressure import verified
    rows=[]; failures=[]
    for trial in plan()['trials']:
        matches=list(Path(root).rglob(trial+'/trial.json'))
        if len(matches)!=1:
            failures.append('missing_or_duplicate:'+trial); continue
        metadata=json.loads(matches[0].read_text()); folder=matches[0].parent
        filename='extended-result.json' if trial=='recovery-1' else 'result.json'
        raw=json.loads((folder/filename).read_text())
        ok=(metadata.get('passed') is True and metadata.get('trial')==trial
            and metadata.get('plan_sha256')==plan_hash() and metadata.get('inputs_unchanged') is True
            and metadata.get('integration_sha')==expected_sha and raw.get('integration_sha')==expected_sha)
        if trial=='recovery-1':
            samples=[json.loads(line) for line in (folder/'backlog.jsonl').read_text().splitlines()]
            ok=ok and extended_verified(raw,plan()['extended_frames']) and recovery_assessment(samples)['passed']
        else:
            ok=ok and verified(raw,expected_sha)
        rows.append(dict(trial=trial,passed=ok,retained_age_peak=raw.get('oldest_retained_age_peak')))
        if not ok: failures.append('trial_failed:'+trial)
    return dict(passed=not failures and len(rows)==len(plan()['trials']),failures=failures,trials=rows,
                integration_sha=expected_sha,plan_sha256=plan_hash(),canonical_authority=False)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    parser.add_argument('--trial',choices=plan()['trials']); parser.add_argument('--aggregate')
    parser.add_argument('--expected-sha'); args=parser.parse_args()
    if args.aggregate:
        if not args.expected_sha: parser.error('--expected-sha is required for aggregation')
        result=aggregate(args.aggregate,args.expected_sha); write_json(args.output,result)
    else:
        if not args.trial: parser.error('--trial is required')
        output=Path(args.output); output.mkdir(parents=True,exist_ok=False)
        if not frozen_inputs(): raise ValueError('changed_combined_workload')
        sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        if args.trial=='recovery-1':
            row=asyncio.run(extended_run(output))
        else:
            from certification.combined_pressure import run,verified
            code=asyncio.run(run(output)); row=json.loads((output/'result.json').read_text())
            row['passed']=code==0 and verified(row,sha)
        result=dict(trial=args.trial,passed=row['passed'],integration_sha=sha,
                    plan_sha256=plan_hash(),inputs_unchanged=frozen_inputs(),market_authority=False)
        write_json(output/'trial.json',result)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
