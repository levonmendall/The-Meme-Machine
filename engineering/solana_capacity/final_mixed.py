"""Bounded Model B mixed proof using the unchanged production transport/owner.

Continuous owner sampling and a pre-stop durable census distinguish live drain
from shutdown. Unfinished and partially ready obligations remain explicit.
"""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

from . import certify
from .live_probe import LiveProbe,normal_drain


def position_disposition(row):
    if row.get('bootstrap'):return 'bootstrap_prerequisite'
    if row.get('ready') and row.get('dependencies',{}).get('ordered_history_ready'):
        return 'completed'
    return 'failed' if row.get('error') else 'incomplete'


def candidate_census(path):
    """Observe lazy restoration without creating or initializing its database."""
    if not path.exists():return dict(initialized=False,work=[],requirements=[])
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='work'").fetchone():
            return dict(initialized=False,work=[],requirements=[])
        db.row_factory=sqlite3.Row
        return dict(initialized=True,work=[dict(r) for r in db.execute('SELECT * FROM work')],
            requirements=[dict(r) for r in db.execute('SELECT * FROM work_history_requirements')])


def required_gap_census(db):
    """Resolve active scopes once, rather than joining all views for each gap.

    This observer must not become the workload's dominant owner command. IN
    retains every alias/view and every required gap; it changes no admission or
    completeness rule. A read census has no authority to seal history.
    """
    cursor=db.execute('''SELECT g.* FROM candidate_gaps g WHERE repaired IS NULL AND g.scope IN(
        SELECT b.coverage_scope FROM candidate_lifecycle c JOIN evidence_bindings b
        ON b.family=c.family AND b.address=c.address
        WHERE c.state IN ('queued','warming','active','reactivated'))''')
    names=[c[0] for c in cursor.description]
    return [dict(zip(names,row)) for row in cursor]


class FinalMixed(certify.Certification):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.probe=LiveProbe(self.out/'owner.samples.ndjson.zlib');self.probe.install()
        for name in ('engineering/solana_capacity/final_mixed.py','engineering/solana_capacity/live_probe.py'):
            self.source_hashes[name]=hashlib.sha256(Path(name).read_bytes()).hexdigest()
        self.source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        self.source_tree=subprocess.check_output(['git','rev-parse','HEAD^{tree}'],text=True).strip()
        self.final_debt=None

    def state(self,s):
        result=super().state(s);db=s.writer.db
        def rows(sql):
            cursor=db.execute(sql);names=[c[0] for c in cursor.description]
            return [dict(zip(names,row)) for row in cursor]
        result['acquisitions']=rows('SELECT j.*,r.reason AS repair_cause,r.fields AS repair_fields FROM acquisition_jobs j LEFT JOIN backfill_reasons r ON r.job=j.id')
        result['publication_waits']=rows('SELECT * FROM rolling_publication_waits')
        result['boundary_waits']=rows('SELECT * FROM rolling_boundary_waits')
        result['required_gaps']=required_gap_census(db)
        result['checkpoints']=rows('SELECT * FROM candidate_checkpoints')
        result['canonical_max_slot']=db.execute('SELECT MAX(slot) FROM canonical_evidence').fetchone()[0]
        result['normalized_max_slot']=db.execute('SELECT MAX(slot) FROM rolling_economic_events').fetchone()[0]
        result['counters']=dict(db.execute('SELECT key,value FROM counters'))
        result['owner']=self.probe.owners[0].telemetry() if self.probe.owners else {}
        shared=candidate_census(self.out/'candidate.sqlite')
        result['candidate_history_initialized']=shared['initialized']
        result['candidate_work']=shared['work'];result['history_requirements']=shared['requirements']
        return result

    def should_finish(self,snapshot,cohort_debt):
        if shutil.disk_usage(self.out).free<250_000_000:
            self.errors.append(dict(reason='bounded_capture_disk_guard'));return True
        if time.time()<self.cutoff:return False
        # Keep the feeds, candidates, positions, health and checkpoint work active
        # during this observation. Source shutdown is never a drain mechanism.
        pending=[r['id'] for r in snapshot['acquisitions'] if r['status']=='pending']
        waiting=[r for key in ('publication_waits','boundary_waits') for r in snapshot[key] if r['status']=='pending']
        proof=normal_drain(self.probe.samples,self.steady_started,time.time(),64)
        self.final_debt=dict(acquisitions=pending,rolling_waits=waiting,cohort_work=cohort_debt,
            required_gaps=snapshot['required_gaps'],normal_drain=proof)
        return not pending and not waiting and cohort_debt==0 and not snapshot['required_gaps'] and not self.position_inflight and proof['proven']

    def write(self):
        self.probe.close();super().write()
        path=self.out/'result.json';result=json.loads(path.read_text())
        close=getattr(self,'running_close_at',time.time());release=getattr(self,'steady_started',None)
        samples=[r for r in self.probe.samples if r['at']<=close and not r['closed']]
        steady=[r for r in samples if release is not None and r['at']>=release]
        result.update(schema='model-b-final-mixed-proof-v1',source_commit=self.source_commit,source_tree=self.source_tree,
            running_close=getattr(self,'running_close',None),running_close_at=close,final_debt=self.final_debt,
            running_position_pending=getattr(self,'running_position_pending',{}),
            owner_observation=dict(sample_interval_seconds=.05,capacity=64,N=len(samples),
                peak=max((r['depth'] for r in samples),default=None),depth=certify.quantiles([r['depth'] for r in steady]),
                oldest_wait_seconds=max((r['oldest_wait'] for r in samples),default=None),
                normal_drain=normal_drain(samples,release,close,64),
                time_at_75_percent_seconds=sum(r['depth']>=48 for r in steady)*.05,
                time_at_90_percent_seconds=sum(r['depth']>=58 for r in steady)*.05,
                shutdown_depths=[r['depth'] for r in self.probe.samples if r['at']>close]),
            position_obligations={lane:dict(Counter(position_disposition(r) for r in self.position if r['family']==lane)) for lane in ('pump','pumpswap','meteora')},
            physical_HTTP_requests=len(self.meter.rows)+len(self.meter.failed_attempts),failed_physical_HTTP_requests=self.meter.failed_attempts,
            logical_RPC_methods=dict(Counter(m for r in self.meter.rows for m in r['methods'])),
            monthly_Alchemy_cost='NOT_CERTIFIED',
            measurement_limits=['Provider bytes are delivered application payload, including overlapping duplicates; TLS framing is excluded.',
                'A mark with missing continuation history is incomplete position evidence.',
                'A finally timestamp on a deferred or failed hydration is not qualification readiness.',
                'Short-window production workload incidence is not a certified monthly cost.'])
        path.write_text(json.dumps(result,indent=2)+'\n')


def reconcile(out):
    result=json.loads((out/'result.json').read_text());path=(out/'state/canonical.sqlite').resolve()
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        integrity=db.execute('PRAGMA quick_check').fetchall()
        events=db.execute('SELECT COUNT(*),COUNT(DISTINCT identity),MAX(slot) FROM canonical_evidence').fetchone()
        startup=db.execute('SELECT phase,released,body FROM prewarm_startup WHERE id=1').fetchone()
        checkpoints=[dict(scope=s,slot=n) for s,n in db.execute('SELECT scope,slot FROM candidate_checkpoints')]
    close=result.get('running_close') or {}
    original={(r['scope'],r['slot']) for r in close.get('checkpoints',[])}
    current={(r['scope'],r['slot']) for r in checkpoints}
    no_regression=all(any(s==scope and n>=slot for s,n in current) for scope,slot in original)
    audit=dict(integrity=integrity,canonical_events=events[0],distinct_identities=events[1],canonical_max_slot=events[2],
        startup_phase=None if startup is None else startup[0],consumer_released=None if startup is None else bool(startup[1]),
        checkpoint_not_regressed=no_regression,canonical_not_lost=events[0]>=close.get('canonical_events',0),
        status='PASS' if integrity==[('ok',)] and events[0]==events[1] and no_regression and events[0]>=close.get('canonical_events',0) else 'FAIL')
    (out/'reconciliation.json').write_text(json.dumps(audit,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--seconds',type=int,default=180)
    parser.add_argument('--env',default='/etc/meme-machine/paper.env');args=parser.parse_args()
    if not 30<=args.seconds<=1200:raise SystemExit('certification_window_bound')
    certify.Certification=FinalMixed
    asyncio.run(certify.main(args));reconcile(Path(args.output).resolve())
