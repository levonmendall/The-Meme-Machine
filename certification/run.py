"""Reproducible pinned-worktree verification and concurrent live-paper supervisor."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
from certification.journal import canonical,digest,Journal
from certification.governor import Governor
from certification.pressure import PressureView
from certification.report import LANES,dashboard,evaluate,summarize

ROOT=Path(__file__).resolve().parents[1]
REPORTS={'pump':'pump-acceleration-natural-prospective.json','meteora':'solana-dlmm-independent-v1-live.json',
         'pons':'pons-selective-continuation-v1-cohort.json','ramses':'robinhood-ramses-extended-market-report.json'}


def atomic(path,data):
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(canonical(data)+'\n');os.replace(temp,path)


def git(*args,cwd=ROOT):
    return subprocess.check_output(['git',*args],cwd=cwd,text=True).strip()


def manifest():return json.loads((ROOT/'certification/sources.json').read_text())


def implementation_hash():
    files=sorted(p for p in (ROOT/'certification').rglob('*') if p.is_file() and p.suffix in ('.py','.json','.patch'))
    return digest({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def source_integrity(worktrees):
    observed={}
    for lane,row in manifest()['lanes'].items():
        cwd=Path(worktrees)/lane
        if git('rev-parse','HEAD',cwd=cwd)!=row.get('execution_sha',row['source_sha']):raise ValueError('worktree_head_drift:'+lane)
        diff=subprocess.check_output(['git','diff','--binary','HEAD'],cwd=cwd)
        observed[lane]=hashlib.sha256(diff).hexdigest()
        patch={'pump':'pump-accounting.patch','meteora':'meteora-checkpoint.patch','pons':'pons-cohort-capital.patch','ramses':'ramses-admission.patch'}.get(lane)
        expected=(ROOT/'certification/patches'/patch).read_bytes() if patch else b''
        # Compare git's normalized diff to the pinned overlay applied at preparation.
        if diff.strip()!=expected.strip():raise ValueError('unreviewed_lane_mutation:'+lane)
    return observed


def prepare(destination):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=False)
    spec=manifest()
    for lane,row in spec['lanes'].items():
        work=destination/lane
        execution=row.get('execution_sha',row['source_sha'])
        subprocess.run(['git','fetch','origin',execution],cwd=ROOT,check=True)
        subprocess.run(['git','worktree','add','--detach',str(work),execution],cwd=ROOT,check=True)
        for file,expected in row['file_hashes'].items():
            if hashlib.sha256((work/file).read_bytes()).hexdigest()!=expected:raise ValueError('source_hash_mismatch:'+lane+':'+file)
        patch={'pump':'pump-accounting.patch','meteora':'meteora-checkpoint.patch','pons':'pons-cohort-capital.patch','ramses':'ramses-admission.patch'}.get(lane)
        if patch:
            subprocess.run(['git','apply','--index',str(ROOT/'certification/patches'/patch)],cwd=work,check=True)
    atomic(destination/'manifest.json',spec)
    return destination


def verify(worktrees,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    rows={}
    source_hashes=source_integrity(worktrees)
    for lane in LANES:
        cwd=Path(worktrees)/lane
        command=[sys.executable,'-m','unittest','discover']+(['-s','robinhood_tests'] if lane in ('pons','ramses') else [])+['-v']
        commands=[command]
        if lane in ('pump','meteora'):commands.append([sys.executable,'-m','tests.resource_check'])
        if lane=='meteora':commands.append([sys.executable,'-m','tests.dlmm_resource_check'])
        rows[lane]=[]
        for index,cmd in enumerate(commands):
            started=time.time();log=output/f'{lane}-gate-{index}.log'
            with log.open('wb') as f:r=subprocess.run(cmd,cwd=cwd,stdout=f,stderr=subprocess.STDOUT)
            complete=index!=0 or ('\nRan ' in log.read_text() and '\nOK' in log.read_text())
            rows[lane].append(dict(command=cmd,exit_code=r.returncode,summary_complete=complete,started_at=started,ended_at=time.time(),log=log.name,sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
    result=dict(passed=all(x['exit_code']==0 and x['summary_complete'] for lane in rows.values() for x in lane),lanes=rows,
                source_manifest_hash=digest(manifest()),integration_sha=git('rev-parse','HEAD'),implementation_hash=implementation_hash(),source_diff_hashes=source_hashes)
    atomic(output/'deterministic.json',result)
    return result


def lane_environment(lane,source,run,run_id=None):
    env={k:v for k,v in os.environ.items() if not k.startswith(('MM_','GITHUB_','GH_')) and not any(x in k.upper() for x in ('TOKEN','SECRET','PRIVATE_KEY'))}
    for key in source['rpc_configuration_variables']:
        if os.environ.get(key):env[key]=os.environ[key]
    if lane=='ramses':
        # Optional existing authorized inputs; strategy code still authenticates.
        for key in ('MM_ROBINHOOD_RAMSES_COSTS_BY_POOL_JSON','MM_ROBINHOOD_RAMSES_SIGNALS_BY_POOL_JSON'):
            if key in os.environ:env[key]=os.environ[key]
    env.update(PYTHONPATH=str(ROOT),PYTHONUNBUFFERED='1',MM_CERT_SOURCE_SHA=source['source_sha'],
               MM_CERT_GOVERNOR_DB=str(run/'shared-provider.sqlite'),
               MM_CERTIFICATION_RUN_ID=run_id or run.name,MM_CERTIFICATION_LANE=lane)
    if lane in ('pump','meteora'):env['MM_SOLANA_EVIDENCE_BROKER_DB']=str(run/'shared-solana-evidence.sqlite')
    else:env.update(MM_CERTIFICATION_PROVIDER_DB=str(run/'shared-robinhood-admission.sqlite'),MM_CERTIFICATION_LANE=lane)
    return env


def sustained_readiness():
    # These are demonstrated source-level blockers, not configuration overrides.
    # Never bypass a bounded study by looping/restarting it or padding idle uptime.
    return [
        'pump:runner discovery clamps at 3300s; lifetime evidence cap 120; detailed cost decomposition and full economic replay remain incomplete',
        'meteora:runner rejects runtime above 7200s; single finite census and attempt/target early exits; native journal integrated; continuous census and raw-chain replay validation remain',
        'pons:cohort capital guard implemented; unresolved trials require recovery/reconciliation; enrollment/qualifier early-stop conditions remain',
        'ramses:runner returns on first natural lifecycle; multi-asset cumulative capital accounting remains unproven',
    ]


def launch(worktrees,output,seconds,phase,gate_file):
    if phase=='sustained' and seconds<14400:raise ValueError('four_hour_minimum')
    gate=json.loads(Path(gate_file).read_text())
    if not gate.get('passed') or gate.get('source_manifest_hash')!=digest(manifest()):raise ValueError('exact_source_deterministic_gate_required')
    if gate.get('integration_sha')!=git('rev-parse','HEAD'):raise ValueError('integration_sha_gate_mismatch')
    if gate.get('implementation_hash')!=implementation_hash():raise ValueError('implementation_gate_mismatch')
    if gate.get('source_diff_hashes')!=source_integrity(worktrees):raise ValueError('source_gate_mismatch')
    run=Path(output).resolve();run.mkdir(parents=True,exist_ok=False)
    spec=manifest();run_id=str(uuid.uuid4())
    atomic(run/'manifest.json',dict(**spec,integration_sha=git('rev-parse','HEAD'),run_id=run_id,
                                  operational_overlay_sha256=hashlib.sha256((ROOT/'certification/patches/meteora-checkpoint.patch').read_bytes()).hexdigest()))
    if phase=='sustained':
        blockers=sustained_readiness()
        result=dict(run_id=run_id,phase=phase,status='BLOCKED',blockers=blockers,lanes={},elapsed_seconds=0)
        result['certification']=evaluate(result);atomic(run/'result.json',result);dashboard(result,run/'status.html')
        return result
    for lane,row in spec['lanes'].items():
        if git('rev-parse','HEAD',cwd=Path(worktrees)/lane)!=row.get('execution_sha',row['source_sha']):raise ValueError('worktree_head_drift:'+lane)
        for f,h in row['file_hashes'].items():
            if hashlib.sha256((Path(worktrees)/lane/f).read_bytes()).hexdigest()!=h:raise ValueError('policy_or_config_drift:'+lane)
    required=('MM_SOLANA_READ_RPC_URL','MM_ROBINHOOD_READ_RPC_URL')
    missing=[k for k in required if not os.environ.get(k)]
    if missing:
        result=dict(run_id=run_id,phase=phase,status='BLOCKED',blockers=['missing_authorized_runtime_variable:'+k for k in missing],lanes={},elapsed_seconds=0)
        result['certification']=evaluate(result);atomic(run/'result.json',result);dashboard(result,run/'status.html');return result
    provider_config={}
    for lane,row in spec['lanes'].items():
        provider_config[lane]={k:dict(configured=bool(os.environ.get(k)),identity=(hashlib.sha256(os.environ[k].encode()).hexdigest()[:16] if os.environ.get(k) else None)) for k in row['rpc_configuration_variables']}
    atomic(run/'provider-identities.json',provider_config)
    journal=Journal(run/'supervisor.sqlite');governor=Governor(run/'shared-provider.sqlite')
    pressure=PressureView(run/'shared-robinhood-admission.sqlite')
    started=time.monotonic();start_wall=time.time();processes={};files={};rows={};interrupted=False;terminal_times={}
    common_start=started
    last_console=0
    try:
        for lane,row in spec['lanes'].items():
            folder=run/lane;folder.mkdir()
            out=(folder/'process.log').open('wb');files[lane]=out
            cmd=[sys.executable,'-m','certification.worker','--lane',lane,'--output',str(folder),'--policy-hash',row['policy_hash'],'--seconds',str(seconds)]
            proc=subprocess.Popen(cmd,cwd=Path(worktrees)/lane,env=lane_environment(lane,row,run,run_id),stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
            launched=time.monotonic();processes[lane]=(proc,launched)
            rows[lane]=dict(pid=proc.pid,strategy_version=row['strategy_version'],policy_hash=row['policy_hash'],process_restarts=0,health='starting',natural_settled=0,forced_settled=0,gates={})
            journal.append(lane,'launch','process_launch',dict(pid=proc.pid,command=cmd,source_sha=row['source_sha'],launched_monotonic=launched))
        # Drain lets normal policy-defined exits finish. It is never counted as
        # a replacement for an interrupted observation window.
        common_start=max(start for _proc,start in processes.values())
        hard_deadline=common_start+seconds+1800
        while True:
            now=time.monotonic();alive=False
            for lane,(proc,launched) in processes.items():
                row=rows[lane];code=proc.poll();path=run/lane/'status.json';status={}
                if path.exists():
                    try:status=json.loads(path.read_text())
                    except (ValueError,OSError):status={}
                    row.update({k:status[k] for k in ('phase','provider_requests','method_counts','errors','rpc_latency_seconds','telemetry_archive_seconds') if k in status})
                    progress=status.get('last_progress_monotonic')
                    row['progress_age_seconds']=None if progress is None else now-progress
                    if 'exit_code' not in row:row['health']='responsive' if progress is not None and now-progress<300 else 'progress_stalled'
                    if status.get('report') is not None:
                        row.update(summarize(lane,status['report']))
                    if status.get('policy_hash')!=row['policy_hash']:row['gates']['policy_unchanged']=False
                activity_file=run/lane/'activity.json'
                if activity_file.exists() and code is None:
                    try:activity=json.loads(activity_file.read_text())
                    except (ValueError,OSError):activity={}
                    if activity.get('pid')==proc.pid and activity.get('lane')==lane:
                        at=activity.get('at_monotonic',0)
                        if isinstance(at,(int,float)) and 0<=now-at<300:
                            row['health']='responsive';row['transport_activity_age_seconds']=now-at
                        if isinstance(at,(int,float)) and at>(status.get('last_progress_monotonic') or 0):
                            row.update({k:activity[k] for k in ('provider_requests','method_counts','errors','provider_session_count') if k in activity})
                if code is None:
                    alive=True;row['continuous_uptime_seconds']=now-launched
                elif 'exit_code' not in row:
                    reported=status.get('terminal_monotonic')
                    ended=reported if isinstance(reported,(int,float)) and launched<=reported<=now else now
                    terminal_times[lane]=ended
                    row.update(exit_code=code,ended_at=time.time(),continuous_uptime_seconds=ended-launched,unexpected_exit=code!=0 or ended-common_start<seconds,health='exited')
                    journal.append(lane,'exit','process_exit',dict(exit_code=code,observed_monotonic=now,unexpected=row['unexpected_exit']))
                    report=Path(worktrees)/lane/REPORTS[lane]
                    if report.exists():
                        raw=report.read_bytes();(run/lane/REPORTS[lane]).write_bytes(raw)
                        try:row.update(summarize(lane,json.loads(raw)))
                        except ValueError:row['report_parse_error']=True
                row['open_positions_unknown']=row.get('open_positions') is None
            result=dict(run_id=run_id,phase=phase,status='RUNNING' if alive else 'FINISHED',started_at=start_wall,observed_at=time.time(),elapsed_seconds=now-started,continuous_overlap_seconds=max(0,min(terminal_times.values(),default=now)-common_start),lanes=rows,shared_provider=dict(solana=governor.status(),robinhood=pressure.snapshot()),source_manifest_hash=digest(spec))
            result['certification']=evaluate(result);atomic(run/'result.json',result);dashboard(result,run/'status.html')
            if now-last_console>=60:
                print(canonical(dict(run_id=run_id,elapsed_seconds=now-started,lanes={k:{f:v for f,v in r.items() if f in ('health','phase','continuous_uptime_seconds','provider_requests','natural_settled','forced_settled','unexpected_exit')} for k,r in rows.items()})),flush=True)
                last_console=now
                if os.environ.get('GITHUB_STEP_SUMMARY'):
                    summary=['| Lane | Health | Uptime seconds | Requests | Natural / forced settled |','|---|---|---:|---:|---:|']
                    for k,r in rows.items():summary.append(f"| {k} | {r.get('health')} | {r.get('continuous_uptime_seconds',0):.1f} | {r.get('provider_requests','unknown')} | {r.get('natural_settled',0)} / {r.get('forced_settled',0)} |")
                    Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('\n'.join(summary)+'\n\nCertification is not PASS while required controls remain unproven.\n')
            if not alive:break
            if now>=hard_deadline:
                result['shutdown_reason']='bounded_drain_deadline';interrupted=True;break
            time.sleep(2)
    finally:
        # A terminated lane is a failure and its unresolved positions stay visible.
        for lane,(proc,launched) in processes.items():
            if proc.poll() is None:
                interrupted=True;os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                rows[lane].update(unexpected_exit=True,exit_code=proc.returncode,health='terminated',shutdown_positions='explicitly_unresolved')
                journal.append(lane,'supervisor_stop','forced_process_stop',dict(exit_code=proc.returncode))
            files[lane].close()
        result=dict(run_id=run_id,phase=phase,status='FAILED' if interrupted else 'FINISHED',started_at=start_wall,ended_at=time.time(),elapsed_seconds=time.monotonic()-started,continuous_overlap_seconds=max(0,min(terminal_times.values(),default=time.monotonic())-common_start),source_manifest_hash=digest(spec),lanes=rows,shared_provider=dict(solana=governor.status(),robinhood=pressure.snapshot()))
        result['certification']=evaluate(result);atomic(run/'result.json',result);dashboard(result,run/'status.html');journal.close()
        from certification.analysis import report
        report(run)
    return result


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--worktrees',required=True)
    p=sub.add_parser('verify');p.add_argument('--worktrees',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('run');p.add_argument('--worktrees',required=True);p.add_argument('--output',required=True);p.add_argument('--gate',required=True)
    p.add_argument('--seconds',type=int,default=600);p.add_argument('--phase',choices=['smoke','sustained'],default='smoke')
    args=parser.parse_args()
    if args.command=='prepare':print(prepare(args.worktrees));return
    if args.command=='verify':
        r=verify(args.worktrees,args.output);print(canonical(r));raise SystemExit(0 if r['passed'] else 1)
    r=launch(args.worktrees,args.output,args.seconds,args.phase,args.gate)
    print(canonical(r))
    raise SystemExit(0 if r['certification']['status']=='PASS' else 1)

if __name__=='__main__':main()
