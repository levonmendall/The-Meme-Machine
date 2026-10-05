"""Independent observation-only actionable condition persistence and metrics."""
import argparse
import json
import os
from pathlib import Path
import time

from .observation import atomic_json,read_json,stamp,SAMPLE_BOUND

PERSISTENCE=300
CRITICAL=frozenset(('epoch_mismatch','reconciliation_failure','database_integrity_failure'))

def conditions(sample,epoch,now):
    found=set()
    if not sample or not 0<=now-sample.get('timestamp',0)<=60:
        return {'observation_unavailable'}
    p=sample.get('portfolio',{})
    if p.get('epoch_id') and p['epoch_id']!=epoch:found.add('epoch_mismatch')
    if p.get('reconciliation_failure') or any(v is False for v in p.get('checks',{}).values()):
        found.add('reconciliation_failure')
    if p.get('state')!='CURRENT':found.add('portfolio_observation_unavailable')
    for key in ('portfolio','solana','solana_provider','robinhood_provider'):
        if sample.get(key,{}).get('integrity_failure'):found.add('database_integrity_failure')
    if any(row.get('integrity_failure') for row in sample.get('database_integrity',{}).values()):
        found.add('database_integrity_failure')
    service=sample.get('host',{}).get('service',{})
    if service.get('ActiveState')!='active':found.add('paper_service_unavailable')
    for disk in sample.get('host',{}).get('disks',{}).values():
        if disk.get('free_bytes',0)<max(2*1024**3,disk.get('total_bytes',0)*.05) or disk.get('percent_used',0)>=85:found.add('storage_exhaustion_risk')
    s=sample.get('solana',{})
    if s.get('state')!='CURRENT':found.add('evidence_unavailable')
    gap=s.get('repair_backlog',{})
    if gap.get('open_gaps',0) and gap.get('oldest_created') is not None and now-gap['oldest_created']>PERSISTENCE:
        found.add('persistent_evidence_gap')
    heartbeat=s.get('heartbeat')
    if isinstance(heartbeat,(int,float)) and now-heartbeat>60:found.add('evidence_heartbeat_stale')
    for provider in ('solana','robinhood'):
        row=sample.get(provider+'_provider',{})
        if row.get('state')!='CURRENT':found.add(provider+'_provider_unavailable')
        if row.get('oldest_wait_seconds',0)>30:found.add(provider+'_request_queue_stalled')
    for lane in ('pump','pons','meteora','ramses'):
        row=sample.get('lanes',{}).get(lane,{})
        if row.get('reconciled') is not True:found.add(lane+'_reconciliation_unavailable')
        if row.get('phase')=='VALUATION_UNAVAILABLE':found.add(lane+'_valuation_unavailable')
        if p.get('positions_by_lane',{}).get(lane,0)>0 and now-row.get('progress_at',0)>PERSISTENCE:
            found.add(lane+'_position_management_stalled')
    for lane in ('pump','pons'):
        row=sample.get('six_regimes',{}).get(lane.title()+' Survivor',{})
        details=row.get('machinery') or {}
        positions=(details.get('accounting') or {}).get('open_positions',0)
        completed=(details.get('machinery') or {}).get('last_step_completed_at',0)
        if positions>0 and now-completed>PERSISTENCE:
            found.add(lane+'_survivor_position_management_stalled')
    return found

def evaluate(sample,previous,epoch,now=None,*,expect_running=True):
    now=time.time() if now is None else now
    current=conditions(sample,epoch,now) if expect_running else set()
    previous=previous or {};first=previous.get('first_seen',{})
    progress={}
    solana=(sample or {}).get('solana',{})
    counters_to_watch={'evidence_stream_receive':solana.get('counters',{}).get('stream_messages'),
        'evidence_committed_frontier':solana.get('all_frontiers',{}).get('highest_slot')}
    for code,value in counters_to_watch.items():
        if not isinstance(value,(int,float)):continue
        old=previous.get('progress',{}).get(code,{})
        at=now if value!=old.get('value') else old.get('at',now)
        progress[code]=dict(value=value,at=at)
        if expect_running and now-at>PERSISTENCE:current.add(code+'_stalled')
    counters={'service':int(sample.get('host',{}).get('service',{}).get('NRestarts','0'))} if sample else {}
    counters.update({lane:int(row.get('restarts',0)) for lane,row in (sample or {}).get('lanes',{}).items()})
    restarts={}
    for component,count in counters.items():
        events=[t for t in previous.get('restart_events',{}).get(component,[]) if now-t<600]
        old=previous.get('restart_counters',{}).get(component,count)
        if count>old:events.extend([now]*min(count-old,32))
        restarts[component]=events[-64:]
        if len(events)>=5 and expect_running:current.add(component+'_repeated_failure')
    times={code:first.get(code,now) for code in current}
    actionable=sorted(code for code,at in times.items() if now-at>=(60 if code in CRITICAL else PERSISTENCE))
    cleared=sorted(set(first)-current)
    state='OWNER_ACTION_REQUIRED' if actionable else 'FAIL_CLOSED' if current & CRITICAL else 'DEGRADED' if current else 'SELF_HEALING_EVENT' if cleared else 'CURRENT'
    return dict(at=stamp(),timestamp=now,state=state,actionable=actionable,conditions=sorted(current),
        first_seen=times,self_healed=cleared,restart_counters=counters,restart_events=restarts,
        progress=progress,
        paper_only=True,observation_only=True,expect_running=expect_running)

def write_metrics(folder,value):
    path=Path(folder)/'meme_machine.prom';temp=path.with_suffix('.prom.tmp')
    lines=['# TYPE meme_machine_owner_action_required gauge',
        'meme_machine_owner_action_required '+str(int(bool(value['actionable']))),
        '# TYPE meme_machine_monitor_heartbeat_seconds gauge',
        'meme_machine_monitor_heartbeat_seconds '+str(value['timestamp'])]
    for code in value['conditions']:
        lines.append('meme_machine_actionable_condition{condition="'+code+'"} '+str(int(code in value['actionable'])))
    with temp.open('w') as stream:
        stream.write('\n'.join(lines)+'\n');stream.flush();os.fsync(stream.fileno())
    temp.chmod(0o644);os.replace(temp,path)

def main():
    import subprocess
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observer',default='/var/lib/meme-machine-observer')
    parser.add_argument('--output',default='/var/lib/meme-machine-monitor')
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args();folder=Path(args.output);folder.mkdir(parents=True,exist_ok=True)
    epoch=read_json('/etc/meme-machine/storage.json')['epoch_id']
    while True:
        try:sample=read_json(Path(args.observer)/'latest.json',SAMPLE_BOUND)
        except (OSError,ValueError):sample={}
        try:previous=read_json(folder/'status.json')
        except (OSError,ValueError):previous={}
        expect=subprocess.run(['systemctl','is-enabled','--quiet','meme-machine-paper.service'],timeout=3).returncode==0
        row=evaluate(sample,previous,epoch,expect_running=expect)
        atomic_json(folder/'status.json',row);write_metrics(folder,row)
        if args.once:return 0
        time.sleep(15)

if __name__=='__main__':raise SystemExit(main())
