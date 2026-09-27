"""Fail-closed joined longevity, recovery and provider evidence gate."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from certification.journal import canonical
from certification.resource_churn import grouped_tables


def evaluate(soak,crash,provider,long_horizon,expected):
    samples=soak.get('samples',[])
    checks=dict(exact_identity=all(row.get('identity')==expected for row in (soak,crash,provider,long_horizon)),
        eight_days=soak.get('measurement_complete') is True and soak.get('virtual_seconds',0)>=192*3600
            and len(samples)>=192 and not soak.get('error'),
        crash=crash.get('passed') is True,provider=provider.get('passed') is True,
        approved_long_lifecycles=long_horizon.get('passed') is True,
        terminal_drain=soak.get('terminal_drained') is True,
        final_successor=soak.get('final_successor_accounting_exact') is True,
        paper_only=all(row.get('paper_only') is True for row in (soak,crash,provider,long_horizon))
            and expected.get('paper_only') is True and expected.get('live_money') is False)
    control=soak.get('controller',[])
    checks['bounded_controller']=(len(control)>=168 and all(
        s['tables']['controller:recent_events']<=32 and s['tables']['controller:window']<=1
        and s['tables']['controller:predecessor']<=1 for s in control)
        and max(s['bytes'] for s in control[-24:])-min(s['bytes'] for s in control[-24:])<4096)
    tail=samples[-48:];baseline=samples[:-24];recent=samples[-24:]
    violations=[]
    if len(samples)<192:violations.append('short_measurement')
    if samples:
        groups=[grouped_tables(s) for s in samples]
        for key in set().union(*(s.keys() for s in groups)):
            old=max(g.get(key,0) for g in groups[:-24]) if len(groups)>24 else 0
            new=max(g.get(key,0) for g in groups[-24:])
            # The unchanged 64-active-candidate cap excludes one newly retired
            # tombstone until the next immutable predecessor is installed.
            if '/history.sqlite:candidates' in key:bound=65
            elif '/history.sqlite:meta' in key:bound=64+5
            else:bound=old
            if new>bound:violations.append(dict(table=key,before=old,after=new,bound=bound))
        for kind in ('capsule','preseal'):
            values=[s if kind=='capsule' else s.get('preseal',{}) for s in tail]
            if any('bytes' not in x for x in values):violations.append('missing_'+kind);continue
            # Existing pages may be allocated once at the age frontier. A full
            # two-day tail must fit a small fixed page band, never a rising limit.
            if max(x['bytes'] for x in values)-min(x['bytes'] for x in values)>16*4096:
                violations.append(kind+'_hot_bytes_not_plateaued')
        for s in samples:
            if (s.get('fd')!=soak.get('base_fd') or s.get('threads')!=soak.get('base_threads')
                    or s.get('children')!=[] or s.get('wal_bytes')!=0):violations.append('parent_resource:'+str(s['hour']))
            workers=s.get('workers',{})
            if set(workers)!={'pump','pons','meteora','ramses'}:violations.append('worker_receipts_missing')
            for lane,row in workers.items():
                # Every native worker is reaped at the established campaign
                # boundary; no worker, queue, FD or thread can cross that fence.
                if row['children'] or row['threads']!=1:violations.append('worker_resource:'+lane)
        checks['accounting']=all(set(s['accounting'])=={'pump','pons','meteora','ramses'}
            and all(p.get('verified') is True for p in s['accounting'].values())
            and s.get('projection_violations') is False for s in samples)
        checks['normal_and_position_windows']=(any(s.get('mode')=='position' for s in samples)
            and sum(s.get('mode')=='hourly' for s in samples)>168)
        checks['both_survivors_active']=all(any(s['accounting'][lane].get('survivor',{}).get('active') is True
            and s['accounting'][lane]['survivor']['accounting']['settled']>0 for s in samples) for lane in ('pump','pons'))
    else:checks['accounting']=False
    checks['bounded_hot_state']=not violations
    return dict(schema='joined-paper-system-acceptance-v1',passed=all(checks.values()),identity=expected,
        gates=checks,violations=violations,paper_only=True,market_collection=False,
        windows=len(samples),virtual_seconds=soak.get('virtual_seconds'),
        steady_hot_bytes=[min((s['bytes'] for s in tail),default=0),max((s['bytes'] for s in tail),default=0)],
        crash_cuts=crash.get('cuts'),provider_tests=provider.get('tests'),long_horizon_tests=long_horizon.get('tests'))


def run(soak,sources,output):
    from certification.campaign_state import identity
    from certification.joined_matrix import run as matrix
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    expected=identity();measurement=json.loads((Path(soak)/'result.json').read_text())
    if measurement['identity']!=expected:raise ValueError('joined_source_identity_changed')
    crash=matrix(soak,sources,output/'crash')
    for kind in ('provider','long_horizon'):
        with (output/(kind+'.log')).open('w') as stream:
            process=subprocess.run([sys.executable,'-m','certification.joined_proofs','--sources',str(sources),
                '--output',str(output/(kind+'.json')),'--kind',kind],stdout=stream,stderr=subprocess.STDOUT,timeout=180)
        if process.returncode:raise ValueError('joined_reused_proof_failed:'+kind)
    report=evaluate(measurement,crash,json.loads((output/'provider.json').read_text()),
        json.loads((output/'long_horizon.json').read_text()),expected)
    if identity()!=expected:raise ValueError('joined_source_identity_changed')
    (output/'result.json').write_text(canonical(report));print(canonical(report))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--soak',required=True);p.add_argument('--sources',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();raise SystemExit(run(a.soak,a.sources,a.output))
