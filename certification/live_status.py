"""Publish bounded aggregate progress to a dedicated GitHub check while lanes run.

No market calls, policy decisions, raw evidence, URLs, or provider credentials are
published. The supervisor retains authoritative JSON, journals and accounting.
The publisher runs outside the supervisor; its network waits cannot delay exits.
"""
import argparse
from collections import Counter
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

LIVE_STATUS_TARGET_BYTES=50_000
LIVE_STATUS_MAX_BYTES=60_000


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
    if isinstance(value,str) and field=='method' and value in ('getGenesisHash','getBlockTime'):
        return value
    if isinstance(value,str) and field=='kind' and value in (
            'hit','miss','cross_lane_hit','pump_window','dlmm_fresh','dlmm_window',
            'stream_prefetch','research_history','position_monitor','position_exit'):
        return value
    if isinstance(value,str) and field=='denominator_status' and value in ('measured','zero_or_unmeasured_no_efficiency_claim'):
        return value
    if isinstance(value,str) and field in ('stage','state','last_gate_reason','next_scan_eligibility',
            'finalized_hash','frontier_hash','lane','scope','reason','terminal_reason','funding_state'):
        if re.fullmatch(r'[A-Za-z0-9_: .;-]{1,180}',value):return value
    return None



def compact_evidence_state(value):
    """Bound the public view, never the native session/evidence archive.

    Session totals cover the full list, not just the recent display sample.
    Physical transports and logical methods remain independent denominators.
    """
    if not isinstance(value,dict):return value
    sessions=value.get('completed_sessions')
    if not isinstance(sessions,list):return value
    result=dict(value)
    totals={k:0 for k in ('logical_requests','transport_requests','requests','retries')}
    present={k:False for k in totals}
    counters={k:Counter() for k in ('methods','logical_methods','failures','immutable_reuse')}
    for row in sessions:
        if not isinstance(row,dict):continue
        for key in totals:
            val=row.get(key)
            if isinstance(val,(int,float)) and not isinstance(val,bool):
                totals[key]+=val;present[key]=True
        for key in counters:
            for method,count in (row.get(key) or {}).items():
                if isinstance(count,(int,float)) and not isinstance(count,bool):counters[key][method]+=count
    result['completed_session_summary']=dict(
        session_count=len(sessions),
        totals={k:totals[k] if present[k] else None for k in totals},
        **{k:dict(v) for k,v in counters.items()},
        displayed_recent_sessions=min(2,len(sessions)),
        full_history_retained_in_raw_artifacts=True)
    result['completed_sessions']=sessions[-2:]
    return result


def compact_finality_state(value):
    """Keep terminal frontier history bounded without losing its aggregate truth."""
    if not isinstance(value,dict) or not isinstance(value.get('observations'),list):
        return value
    observations=value['observations'];result=dict(value)
    reasons=Counter(row.get('gate_reason','unknown') for row in observations if isinstance(row,dict))
    result['observation_summary']=dict(count=len(observations),gate_reasons=dict(reasons),
        expensive_scans=sum(row.get('expensive_scan') is True for row in observations if isinstance(row,dict)),
        displayed_recent_observations=min(2,len(observations)),
        full_history_retained_in_raw_artifacts=True)
    result['observations']=observations[-2:]
    return result


def snapshot(result, now=None):
    now=time.time() if now is None else now
    observed=result.get('observed_at',result.get('ended_at'))
    age=None if not isinstance(observed,(int,float)) else max(0,now-observed)
    out=dict(schema='four-lane-live-v1',published_at=now,observed_at=observed,
        snapshot_age_seconds=age,stale=age is None or age>120,
        phase=result.get('phase') if result.get('phase') in ('smoke','sustained','hourly') else None,
        certification_scope=('ten_minute_engineering_smoke' if result.get('phase')=='smoke' else result.get('certification',{}).get('scope')),
        required_observation_seconds=(600 if result.get('phase')=='smoke' else result.get('certification',{}).get('required_observation_seconds')),
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
            'provider_requests','provider_session_count','method_counts','errors',
            'provider_method_errors','provider_http_status_errors','provider_rpc_error_codes','rpc_latency_seconds',
            'rpc_efficiency','estimated_alchemy','funnel','terminal_reasons','open_positions','natural_settled','forced_settled',
            'accounting_reconciled','native_accounting','cohort_accounting','pnl_decomposition',
            'stream_state','finality_state','evidence_state','runtime_resources','telemetry_cost','gates',
            'opportunity_coverage','pipeline_health','scan_progress','last_completed_scan')
        public={k:numeric_tree(compact_evidence_state(row.get(k)) if k=='evidence_state' else row.get(k)) for k in fields}
        public['finality_state']=numeric_tree(compact_finality_state(row.get('finality_state')))
        public['health']=health if health in ('starting','responsive','responsive_but_strategy_stalled','progress_stalled','exited','terminated') else 'unknown'
        policy=row.get('policy_hash','');public['policy_hash']=policy if re.fullmatch('[a-f0-9]{64}',policy) else None
        version=row.get('strategy_version','');public['strategy_version']=version if re.fullmatch(r'[A-Za-z0-9_. /-]{1,100}',version) else None
        out['lanes'][lane]=public
    return out


def _small_dict(value,limit=24):
    if not isinstance(value,dict):return value
    return dict(list(value.items())[:limit])


def compact_snapshot(view):
    """Small GitHub Check projection. Full sanitized snapshots remain on disk."""
    out={k:view.get(k) for k in (
        'schema','published_at','observed_at','snapshot_age_seconds','stale','phase',
        'certification_scope','required_observation_seconds','elapsed_seconds',
        'continuous_overlap_seconds','certification_status','hourly_engineering_status',
        'supervisor_exit_code','supervisor_failed')}
    out['payload_mode']='compact'
    out['lanes']={}
    funnel_keys=(
        'discovered','screened','unique_discovered','unique_admitted','unique_evaluated',
        'unique_evidence_requested','unique_evidence_complete','unique_decision_evidence_complete',
        'unique_reconstruction_complete','unique_reconstruction_incomplete','unique_qualified',
        'unique_entry_reserved','unique_entry_filled','unique_entry_cancelled',
        'unique_settled','completed_scans')
    for lane in LANES:
        row=(view.get('lanes') or {}).get(lane) or {}
        funnel=row.get('funnel') or {}
        pipeline=row.get('pipeline_health') or {}
        out['lanes'][lane]=dict(
            health=row.get('health'),
            continuous_uptime_seconds=row.get('continuous_uptime_seconds'),
            provider_requests=row.get('provider_requests'),
            natural_settled=row.get('natural_settled'),
            forced_settled=row.get('forced_settled'),
            open_positions=row.get('open_positions'),
            unexpected_exit=row.get('unexpected_exit'),
            exit_code=row.get('exit_code'),
            process_restarts=row.get('process_restarts'),
            accounting_reconciled=row.get('accounting_reconciled'),
            progress_age_seconds=row.get('progress_age_seconds'),
            transport_activity_age_seconds=row.get('transport_activity_age_seconds'),
            errors=_small_dict(row.get('errors')),
            provider_http_status_errors=_small_dict(row.get('provider_http_status_errors')),
            provider_method_errors=_small_dict(row.get('provider_method_errors')),
            gates=_small_dict(row.get('gates'),12),
            funnel={k:funnel.get(k) for k in funnel_keys if k in funnel},
            pipeline_health={k:pipeline.get(k) for k in ('stage','state','stage_age_seconds','stall_bound_seconds')
                             if k in pipeline},
        )
    shared=view.get('shared_provider') or {}
    provider_summary={}
    for network in ('solana','robinhood'):
        row=shared.get(network)
        if isinstance(row,dict):
            queues=row.get('queues')
            provider_summary[network]=dict(
                state=row.get('state'),
                queue_count=len(queues) if isinstance(queues,list) else None)
    reuse=shared.get('robinhood_reuse')
    if isinstance(reuse,dict):
        provider_summary['robinhood_reuse']=dict(inflight_jobs=reuse.get('inflight_jobs'))
    out['shared_provider']=provider_summary
    return out


def _render_output(view):
    rows=['Live paper telemetry; a healthy process is not natural certification.',
          'Snapshots older than 120 seconds are stale. Raw evidence is retained in workflow artifacts.',
          '', '| Lane | Health | Uptime s | Requests | Natural / forced settled | Open |',
          '|---|---|---:|---:|---:|---:|']
    for lane,row in (view.get('lanes') or {}).items():
        rows.append('| {} | {} | {} | {} | {} / {} | {} |'.format(
            lane,row.get('health'),round(row.get('continuous_uptime_seconds') or 0),
            row.get('provider_requests'),row.get('natural_settled'),
            row.get('forced_settled'),row.get('open_positions')))
    raw=json.dumps(view,sort_keys=True,separators=(',',':'),allow_nan=False)
    return dict(title='Four-lane paper progress: '+str(view.get('certification_status','INCOMPLETE')),
                summary='\n'.join(rows),text='```json\n'+raw+'\n```')


def terminal_output(result,integration_sha=None):
    """Tiny terminal payload used when a normal final Check update cannot publish."""
    phase=result.get('phase')
    engineering=(result.get('smoke_engineering') if phase=='smoke'
                 else result.get('hourly_engineering') if phase=='hourly' else {}) or {}
    lanes={}
    for lane in LANES:
        row=(result.get('lanes') or {}).get(lane) or {}
        lanes[lane]=dict(
            health=row.get('health'),
            exit_code=row.get('exit_code'),
            unexpected_exit=row.get('unexpected_exit'),
            open_positions=row.get('open_positions'),
            infrastructure_failure=bool(row.get('infrastructure_failure')))
    payload=dict(
        schema='four-lane-live-terminal-v1',payload_mode='terminal_fallback',
        integration_sha=integration_sha if isinstance(integration_sha,str) and re.fullmatch(r'[a-f0-9]{40}',integration_sha) else None,
        phase=phase,status=result.get('status'),
        certification_status=(result.get('certification') or {}).get('status','INCOMPLETE'),
        engineering_status=engineering.get('status'),
        supervisor_exit_code=result.get('supervisor_exit_code'),
        supervisor_failed=result.get('supervisor_failed',False),
        lanes=lanes)
    body=_render_output(dict(payload,certification_status=payload['certification_status']))
    if len(body['text'].encode())>LIVE_STATUS_MAX_BYTES:
        raise ValueError('terminal_live_status_payload_capacity')
    return body


def output(result):
    view=snapshot(result);view['payload_mode']='full'
    body=_render_output(view)
    if len(body['text'].encode())<=LIVE_STATUS_TARGET_BYTES:return body
    compact=compact_snapshot(view)
    body=_render_output(compact)
    if len(body['text'].encode())<=LIVE_STATUS_TARGET_BYTES:return body
    return terminal_output(result)

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
    snapshots=folder.parent/(folder.name+'-live-snapshots.jsonl')
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
    failures=0;broken=False;publication_failures=0;last=-float('inf');result=pending
    terminal_check_closed=False
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
                view=snapshot(result)
                with snapshots.open('a') as handle:
                    handle.write(json.dumps(view,sort_keys=True,separators=(',',':'))+'\n')
                    handle.flush();os.fsync(handle.fileno())
                body=dict(output=output(result))
                if code is not None:
                    body.update(status='completed',conclusion='cancelled' if interrupted else 'failure' if code else 'neutral',
                        completed_at=datetime.now(timezone.utc).isoformat())
                request('PATCH',endpoint,body)
                if code is not None:terminal_check_closed=True
                event('published',snapshot_observed_at=result.get('observed_at',result.get('ended_at')),
                      payload_mode='bounded',terminal=code is not None)
                failures=0
            except Exception as exc:
                failures+=1;publication_failures+=1;broken=broken or failures>=3
                # Error messages can include URLs; record only the exception type.
                event('publish_failed',error_type=type(exc).__name__,consecutive_failures=failures,
                      terminal=code is not None)
                if code is not None:
                    fallback=dict(
                        output=terminal_output(result,context['integration_sha']),
                        status='completed',
                        conclusion='cancelled' if interrupted else 'failure' if code else 'neutral',
                        completed_at=datetime.now(timezone.utc).isoformat())
                    try:
                        request('PATCH',endpoint,fallback)
                        terminal_check_closed=True;failures=0
                        event('terminal_fallback_published',supervisor_exit_code=code)
                    except Exception as terminal_exc:
                        publication_failures+=1
                        event('terminal_fallback_failed',error_type=type(terminal_exc).__name__)
        if code is not None:break
        time.sleep(1)
    event('publisher_finished',supervisor_exit_code=code,
          visibility_failed=bool(publication_failures),publication_failures=publication_failures,
          terminal_check_closed=terminal_check_closed,interrupted=interrupted)
    # Publication is observability only. The child supervisor remains authoritative.
    # A genuine operator interruption is still not a successful workflow.
    raise SystemExit(code or (1 if interrupted else 0))

if __name__=='__main__':main()
