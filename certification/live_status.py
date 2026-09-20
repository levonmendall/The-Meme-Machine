"""Publish bounded aggregate progress to a dedicated GitHub check while lanes run.

No market calls, policy decisions, raw evidence, URLs, or provider credentials are
published. The supervisor retains authoritative JSON, journals and accounting.
The publisher runs outside the supervisor; its network waits cannot delay exits.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.request import Request, urlopen

from certification.report import LANES


def numeric_tree(value, depth=0, field=None):
    if depth > 9:return None
    if value is None or isinstance(value, bool):return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k:numeric_tree(v,depth+1,k) for k,v in list(value.items())[:150]
                if re.fullmatch(r'[A-Za-z0-9_:. -]{1,100}',str(k))
                and not any(s in str(k).lower() for s in ('token','secret','url','authorization','private_key'))}
    if isinstance(value, list):return [numeric_tree(v,depth+1) for v in value[:100]]
    if isinstance(value,str) and field in ('stage','state','last_gate_reason','next_scan_eligibility',
            'finalized_hash','frontier_hash','lane','scope','reason','terminal_reason','funding_state'):
        if re.fullmatch(r'[A-Za-z0-9_: .;-]{1,180}',value):return value
    return None


def snapshot(result, now=None):
    now=time.time() if now is None else now
    observed=result.get('observed_at',result.get('ended_at'))
    age=None if not isinstance(observed,(int,float)) else max(0,now-observed)
    out=dict(schema='four-lane-live-v1',published_at=now,observed_at=observed,
        snapshot_age_seconds=age,stale=age is None or age>120,
        phase=result.get('phase') if result.get('phase') in ('smoke','sustained','hourly') else None,
        certification_scope=result.get('certification',{}).get('scope'),
        required_observation_seconds=result.get('certification',{}).get('required_observation_seconds'),
        elapsed_seconds=result.get('elapsed_seconds'),
        continuous_overlap_seconds=result.get('continuous_overlap_seconds'),lanes={},
        shared_provider=numeric_tree(result.get('shared_provider')),
        certification_status=result.get('certification',{}).get('status','INCOMPLETE'),
        hourly_engineering_status=result.get('hourly_engineering',{}).get('status'),
        supervisor_exit_code=result.get('supervisor_exit_code'),
        supervisor_failed=result.get('supervisor_failed',False))
    for lane in LANES:
        row=result.get('lanes',{}).get(lane,{})
        health=row.get('health')
        fields=('pid','continuous_uptime_seconds','process_restarts','unexpected_exit','exit_code',
            'progress_age_seconds','transport_activity_age_seconds','max_no_activity_seconds',
            'provider_requests','provider_session_count','method_counts','errors','rpc_latency_seconds',
            'funnel','terminal_reasons','open_positions','natural_settled','forced_settled',
            'accounting_reconciled','native_accounting','cohort_accounting','pnl_decomposition',
            'stream_state','finality_state','evidence_state','runtime_resources','telemetry_cost','gates',
            'opportunity_coverage','pipeline_health','scan_progress','last_completed_scan')
        public={k:numeric_tree(row.get(k)) for k in fields}
        public['health']=health if health in ('starting','responsive','responsive_but_strategy_stalled','progress_stalled','exited','terminated') else 'unknown'
        policy=row.get('policy_hash','');public['policy_hash']=policy if re.fullmatch('[a-f0-9]{64}',policy) else None
        version=row.get('strategy_version','');public['strategy_version']=version if re.fullmatch(r'[A-Za-z0-9_. /-]{1,100}',version) else None
        out['lanes'][lane]=public
    return out


def output(result):
    view=snapshot(result)
    rows=['Live paper telemetry; a healthy process is not natural certification.',
          'Snapshots older than 120 seconds are stale. Raw evidence is retained in workflow artifacts.',
          '', '| Lane | Health | Uptime s | Requests | Natural / forced settled | Open |',
          '|---|---|---:|---:|---:|---:|']
    for lane,row in view['lanes'].items():
        rows.append('| {} | {} | {} | {} | {} / {} | {} |'.format(lane,row['health'],
            round(row['continuous_uptime_seconds'] or 0),row['provider_requests'],
            row['natural_settled'],row['forced_settled'],row['open_positions']))
    raw=json.dumps(view,sort_keys=True,separators=(',',':'),allow_nan=False)
    if len(raw.encode())>60000:raise ValueError('live_status_payload_capacity')
    return dict(title='Four-lane paper progress: '+view['certification_status'],summary='\n'.join(rows),text='```json\n'+raw+'\n```')


def request(method, endpoint, body):
    repo=os.environ['GITHUB_REPOSITORY']
    if repo!='levonmendall/The-Meme-Machine':raise ValueError('unexpected_repository')
    data=json.dumps(body).encode()
    req=Request('https://api.github.com/repos/'+repo+endpoint,data=data,method=method,
        headers={'Authorization':'Bearer '+os.environ['GH_CHECKS_TOKEN'],
                 'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28',
                 'Content-Type':'application/json'})
    with urlopen(req,timeout=10) as response:return json.load(response)


def child_environment():
    return {k:v for k,v in os.environ.items() if k not in ('GH_CHECKS_TOKEN','GITHUB_TOKEN','GH_TOKEN')}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    parser.add_argument('--phase',required=True,choices=('smoke','sustained','hourly'))
    parser.add_argument('command',nargs=argparse.REMAINDER);args=parser.parse_args()
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    if command[:3] not in ([sys.executable,'-m','certification.run'], ['python','-m','certification.run']):
        raise ValueError('only_certification_supervisor_is_allowed')
    folder=Path(args.output);folder.mkdir(parents=True,exist_ok=True)
    # Supervisor requires an absent output directory, so use a sibling journal.
    folder.rmdir()
    journal=folder.parent/(folder.name+'-publisher.jsonl')
    context=dict(workflow_run_id=os.environ['GITHUB_RUN_ID'],attempt=os.environ['GITHUB_RUN_ATTEMPT'],
                 integration_sha=os.environ['GITHUB_SHA'],phase=args.phase)
    pending=dict(phase=args.phase,lanes={})
    check=request('POST','/check-runs',dict(name='four-lane-live-'+args.phase,
        head_sha=context['integration_sha'],status='in_progress',
        external_id=context['workflow_run_id']+':'+context['attempt']+':'+args.phase,
        details_url='https://github.com/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+context['workflow_run_id'],
        output=output(pending)))
    endpoint='/check-runs/'+str(check['id'])
    def event(kind,**data):
        with journal.open('a') as handle:
            handle.write(json.dumps(dict(at=time.time(),kind=kind,check_id=check['id'],**context,**data))+'\n');handle.flush();os.fsync(handle.fileno())
    event('publisher_started')
    proc=subprocess.Popen(command,env=child_environment())
    interrupted=False
    def stop(signum,_frame):
        nonlocal interrupted
        if not interrupted and proc.poll() is None:
            interrupted=True;proc.send_signal(signal.SIGINT)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    failures=0;broken=False;last=-float('inf');result=pending
    while True:
        code=proc.poll();now=time.monotonic()
        if now-last>=60 or code is not None:
            last=now
            try:
                path=folder/'result.json'
                if path.exists():result=json.loads(path.read_text())
                if code is not None:
                    result=dict(result,supervisor_exit_code=code,supervisor_failed=bool(code))
                    if code:
                        result['certification']=dict(result.get('certification') or {},status='FAIL')
                body=dict(output=output(result))
                if code is not None:
                    body.update(status='completed',conclusion='cancelled' if interrupted else 'failure' if code or broken else 'neutral',
                        completed_at=datetime.now(timezone.utc).isoformat())
                request('PATCH',endpoint,body);event('published',snapshot_observed_at=result.get('observed_at',result.get('ended_at')))
                failures=0
            except Exception as exc:
                failures+=1;broken=broken or failures>=3
                # Error messages can include URLs; record only the exception type.
                event('publish_failed',error_type=type(exc).__name__,consecutive_failures=failures)
        if code is not None:break
        time.sleep(1)
    event('publisher_finished',supervisor_exit_code=code,visibility_failed=broken,interrupted=interrupted)
    raise SystemExit(code or (1 if broken or failures or interrupted else 0))

if __name__=='__main__':main()
