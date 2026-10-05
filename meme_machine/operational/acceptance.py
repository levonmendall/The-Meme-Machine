"""Later Droplet mechanics checks. Never imported or run by the PAPER service."""
import argparse,json,os,signal,time
from pathlib import Path
from .supervisor import validate_environment
from meme_machine.runtime.usd_valuation import utc

REQUIRED_SECONDS={'CAPACITY':3600,'AUTONOMY':129600}
CGROUP_ROOT=Path('/sys/fs/cgroup')

def require_owned_pid(pid):
    import subprocess
    group=subprocess.check_output(['systemctl','show','meme-machine-paper.service',
        '-p','ControlGroup','--value'],text=True,timeout=3).strip()
    if group!='/system.slice/meme-machine-paper.service':raise ValueError('PAPER_process_ownership_unavailable')
    owned={int(value) for value in (CGROUP_ROOT/group.lstrip('/')/'cgroup.procs').read_text().split()}
    if isinstance(pid,bool) or pid not in owned:raise ValueError('recovery_target_not_owned_by_PAPER_unit')


def read(path):
    if path.stat().st_size>16*1024*1024:raise ValueError('acceptance_input_bound')
    return json.loads(path.read_text())


def observe(root):
    health=read(root/'health.json');portfolio=read(root/'portfolio.json')
    if health.get('offline') or not health['epoch_id'].startswith('paper-'):raise ValueError('genuine_PAPER_epoch_required')
    if portfolio['epoch_id']!=health['epoch_id']:raise ValueError('epoch_mismatch')
    from dashboard.model import stamp
    age=time.time()-stamp(health['at'])
    if not 0<=age<=10:raise ValueError('supervisor_health_stale')
    if health.get('stopping'):raise ValueError('supervisor_stopping')
    if set(health['lanes'])!={'pump','pons','meteora','ramses'}:raise ValueError('four_lanes_required')
    rss=0
    for pid in [health['pid']]+[r['pid'] for r in health['lanes'].values()]:
        os.kill(pid,0)
        for line in Path('/proc/'+str(pid)+'/status').read_text().splitlines():
            if line.startswith('VmRSS:'):rss+=int(line.split()[1])*1024
    checks=portfolio['reconciliation']['checks']
    if not checks or any(v is not True for v in checks.values()):raise ValueError('portfolio_not_reconciled')
    for lane,row in health['lanes'].items():
        if row.get('reconciled') is not True or row.get('exit_code') is not None:
            raise ValueError(lane+'_not_reconciled_or_running')
    return health,portfolio,rss


def measure(root,seconds,*,clock=time.monotonic,sleeper=time.sleep):
    started=clock();deadline=started+seconds;samples=0;max_rss=0;max_queue=0;errors=[];last=None;frontiers={}
    outage_at=None;recovered_events=0;outage_seconds=0
    while clock()<deadline:
        try:
            health,portfolio,rss=observe(root);last=portfolio
            max_rss=max(max_rss,rss)
            if rss>=8*1024**3:raise ValueError('process_memory_exceeds_Droplet_RAM')
            for provider in ('solana','robinhood'):
                row=health['providers'].get(provider,{})
                if row.get('state')!='CURRENT':raise ValueError(provider+'_provider_unavailable')
                max_queue=max(max_queue,row['queue_depth'])
                if row['oldest_wait_seconds']>30:raise ValueError(provider+'_queue_exceeds_native_deadline')
            for row in health['providers'].get('evidence',{}).get('frontiers',[]):
                history=frontiers.setdefault(row['scope'],[row['slot'],row['slot']]);history[1]=max(history[1],row['slot'])
            samples+=1
            if outage_at is not None:
                outage_seconds+=clock()-outage_at;recovered_events+=1;outage_at=None
        except (OSError,ValueError,KeyError) as error:
            if outage_at is None:outage_at=clock()
            reason=str(error)
            if reason in ('epoch_mismatch','portfolio_not_reconciled','genuine_PAPER_epoch_required') or clock()-outage_at>=180:
                errors.append(type(error).__name__+':'+reason);errors=errors[-32:]
        sleeper(min(5,max(0,deadline-clock())))
    if outage_at is not None:errors.append('system_not_healthy_at_phase_end')
    advanced=any(last>first for first,last in frontiers.values())
    if not advanced:errors.append('target_evidence_frontier_did_not_advance')
    return dict(passed=bool(samples) and not errors,samples=samples,max_process_rss_bytes=max_rss,max_provider_queue=max_queue,
        target_frontiers=frontiers,errors=errors,pnl=last['balances'] if last else None,
        elapsed_seconds=clock()-started,self_healing_events=recovered_events,transient_outage_seconds=outage_seconds)


def recovery(root):
    import fcntl
    from .backup import state_identity
    baseline,portfolio,_=observe(root)
    original_epoch=portfolio['epoch_id'];results=[]
    # Existing supervisor fencing is tested without initializing a second writer.
    with (root/'supervisor.lock').open('r') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:pass
        else:raise ValueError('PAPER_supervisor_single_writer_fence_missing')
    for lane in ('pump','pons','meteora','ramses','supervisor'):
        health,_,_=observe(root)
        old=health['pid'] if lane=='supervisor' else health['lanes'][lane]['pid']
        before=state_identity(root)
        started=time.monotonic()
        require_owned_pid(old)
        os.kill(old,signal.SIGKILL)
        deadline=time.monotonic()+180;recovered=False
        while time.monotonic()<deadline:
            time.sleep(2)
            try:
                now,current,_=observe(root)
                pid=now['pid'] if lane=='supervisor' else now['lanes'][lane]['pid']
                reconciled=all(r.get('reconciled') is True for r in now['lanes'].values()) if lane=='supervisor' else now['lanes'][lane].get('reconciled') is True
                if pid!=old and reconciled:
                    if current['epoch_id']!=original_epoch:raise ValueError('recovery_changed_epoch')
                    ids=[p['id'] for p in current['positions']]
                    if len(ids)!=len(set(ids)):raise ValueError('duplicate_economic_lifecycle')
                    after=state_identity(root)
                    prior=before['replayed_state'];latest=after['replayed_state']
                    if (after['inception_sha256']!=before['inception_sha256'] or after['sequence']<before['sequence']):
                        raise ValueError('recovery_lost_portfolio_identity_or_journal')
                    for family in ('pump','pons','meteora','ramses'):
                        missing=[p for key,p in prior['positions'].items() if p['lane']==family and key not in latest['positions']]
                        if latest['retired'][family]['count']-prior['retired'][family]['count']<len(missing):
                            raise ValueError('recovery_lost_position')
                    if after['pending_deliveries']:
                        continue
                    # Existing native restoration/reconciliation is a mandatory
                    # precursor to discovery, exercised by the native regressions.
                    recovered=True;break
            except (OSError,ValueError,KeyError):continue
        results.append(dict(target=lane,recovered=recovered,elapsed_seconds=time.monotonic()-started,
            pending_deliveries_reconciled=recovered,native_reconciled=recovered))
        if not recovered:break
    return dict(passed=len(results)==5 and all(r['recovered'] for r in results),recoveries=results,
        epoch_id=original_epoch,single_writer_fencing=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('CAPACITY','RECOVERY','AUTONOMY'))
    parser.add_argument('--state-root',default=os.environ.get('MM_STATE_ROOT'))
    parser.add_argument('--seconds',type=int,default=None)
    parser.add_argument('--result-path',type=Path,default=None)
    args=parser.parse_args()
    if not args.state_root:parser.error('MM_STATE_ROOT is required')
    required=REQUIRED_SECONDS.get(args.phase)
    seconds=args.seconds if args.seconds is not None else required
    if required is not None and seconds<required:parser.error(args.phase+' requires its full '+str(required)+' second window')
    # Environment and valuation repair must precede later deployment acceptance.
    validate_environment()
    root=Path(args.state_root).resolve()
    result=recovery(root) if args.phase=='RECOVERY' else measure(root,seconds)
    result.update(phase=args.phase,at=utc(time.time()),profitability_gate=False)
    from meme_machine.portfolio_accounting import _atomic_json
    _atomic_json(args.result_path or root/('acceptance-'+args.phase.lower()+'.json'),result)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
