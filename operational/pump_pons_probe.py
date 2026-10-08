"""Bounded offline process/resource proof on disposable state only.

This is not CAPACITY, RECOVERY or AUTONOMY acceptance. It never accepts a
production state root or contacts a market provider.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from meme_machine.runtime.operating_families import ACTIVE_LANES,PAUSED_LANES


def processes(parent):
    found={};available={};pending=[parent]
    ticks=os.sysconf('SC_CLK_TCK');page=os.sysconf('SC_PAGE_SIZE')
    # This workspace exposes /proc/PID/stat but not task/PID/children.
    # Resolve actual PPids, never infer a live process from a health projection.
    for root in Path('/proc').iterdir():
        if not root.name.isdigit():continue
        try:available[int(root.name)]=(root/'stat').read_text().rsplit(')',1)[1].split()
        except (OSError,ValueError):continue
    while pending:
        pid=pending.pop()
        try:
            root=Path('/proc')/str(pid)
            fields=available[pid]
            command=(root/'cmdline').read_bytes().replace(b'\0',b' ').decode()
            lane=next((f for f in (*ACTIVE_LANES,*PAUSED_LANES) if '--lane '+f+' ' in command),'shared')
            found[pid]=dict(lane=lane,cpu_seconds=(int(fields[11])+int(fields[12]))/ticks,
                rss_bytes=int(fields[21])*page)
            pending.extend(child for child,stat in available.items() if int(stat[1])==pid)
        except (OSError,ValueError,IndexError,KeyError):continue
    return found


def sample_run(root,seconds,*,crash=False):
    output=root.parent/('crash.log' if crash else 'restart.log')
    with output.open('w') as log:
        p=subprocess.Popen([sys.executable,'-m','meme_machine.operational','offline',
            '--state-root',str(root),'--seconds',str(seconds)],stdout=log,stderr=subprocess.STDOUT,
            env={k:v for k,v in os.environ.items() if not k.startswith('MM_') and not any(x in k for x in ('RPC_URL','PRIVATE_KEY','API_KEY'))},
            start_new_session=True)
        start=time.monotonic();samples=0;peak_rss=0;cpu={};lane_peaks={f:0 for f in (*ACTIVE_LANES,*PAUSED_LANES,'shared')};killed=False
        try:
            while p.poll() is None:
                if time.monotonic()-start>seconds+20:raise TimeoutError('offline_probe_timeout')
                rows=processes(p.pid);samples+=1
                peak_rss=max(peak_rss,sum(r['rss_bytes'] for r in rows.values()))
                for pid,r in rows.items():cpu[pid]=max(cpu.get(pid,0),r['cpu_seconds'])
                for lane in lane_peaks:lane_peaks[lane]=max(lane_peaks[lane],sum(r['lane']==lane for r in rows.values()))
                if any(rows[r]['lane'] in PAUSED_LANES for r in rows):raise AssertionError('paused_process_observed')
                health=root/'health.json'
                if crash and not killed and health.exists():
                    value=json.loads(health.read_text())
                    row=value['lanes']['pump']
                    if row.get('reconciled') and row.get('pid'):
                        os.kill(row['pid'],signal.SIGKILL);killed=True
                time.sleep(.05)
            if p.returncode:raise RuntimeError(output.read_text()[-4000:])
        finally:
            if p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=5)
        elapsed=time.monotonic()-start
        return dict(samples=samples,elapsed_seconds=elapsed,peak_processes_by_family=lane_peaks,
            peak_aggregate_rss_bytes=peak_rss,sampled_process_cpu_seconds=sum(cpu.values()),
            average_percent_of_two_vcpu=sum(cpu.values())/elapsed/2*100,
            pump_crash_injected=killed,health=json.loads((root/'health.json').read_text()))


def probe():
    from meme_machine.operational.backup import state_identity
    with tempfile.TemporaryDirectory(prefix='pump-pons-offline-') as td:
        root=Path(td)/'state'
        first=sample_run(root,8,crash=True)
        baseline=state_identity(root)
        second=sample_run(root,4)
        restored=state_identity(root)
        if baseline['epoch_id']!=restored['epoch_id'] or baseline['inception_sha256']!=restored['inception_sha256']:
            raise AssertionError('epoch_changed')
        if first['health']['lanes']['pump']['restarts']<1:raise AssertionError('pump_not_recovered')
        paused={}
        for lane in PAUSED_LANES:
            files=[p for p in (root/lane).rglob('*') if p.is_file()]
            for run in (first,second):
                row=run['health']['lanes'][lane]
                if row['phase']!='PAUSED' or row['pid'] is not None or row['restarts']!=0:raise AssertionError('pause_lost')
            if files:raise AssertionError('paused_files_created')
            paused[lane]=dict(max_processes=0,restarts=0,new_files=0,new_bytes=0,
                strategy_databases=0,strategy_queues=0,strategy_jobs=0,
                provider_measurement='offline fixture has no provider transport')
        for run in (first,second):run.pop('health')
        for run in (first,second):
            if any(run['peak_processes_by_family'][lane]!=1 for lane in ACTIVE_LANES):
                raise AssertionError('active_process_measurement_incomplete')
        return dict(kind='OFFLINE_ONLY',paper_only=True,acceptance_phase=False,
            before_and_after_live_comparison='UNAVAILABLE',fixture_provider_requests=0,
            paused=paused,runs=[first,second],same_epoch=True,same_inception=True,
            inception=restored['replayed_state']['receipt']['starting_capital'],
            pending_deliveries=len(restored['pending_deliveries']),reconciliation=restored['reconciliation'],
            checks=restored['checks'],positions=len(restored['replayed_state']['positions']))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    args=parser.parse_args();result=probe()
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
