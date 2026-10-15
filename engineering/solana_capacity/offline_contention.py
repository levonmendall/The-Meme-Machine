"""Finite offline shared-ledger/real native-tape contention on the existing host.

Allocator fixtures remain unchanged. Separate processes compete for the same two
CPUs/disk; each owns its disposable database. Pons probes exercise real admission,
not a network transport or economic opportunity. No monetary production state.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
if __package__:
    from .offline_replay import io
else:
    from offline_replay import io


def worker(args):
    source=Path(args.source).resolve();out=Path(args.output).resolve()
    sys.path.insert(0,str(source));os.environ['MM_OPERATIONAL_PHASE']='BOUNDED_PROVIDER_PROOF'
    os.environ['TMPDIR']=str(out)
    from operational.tests import network_guard
    network_guard()
    from operational.shared_capital_probe import quantiles
    cpu=time.process_time();wall=time.monotonic();initial=io()
    if args.mode=='allocator':
        from operational.shared_capital_probe import measure
        from meme_machine.shared_capital import RiskPolicy
        from meme_machine.shared_capital.runtime import SharedNativePortfolio
        samples=[];original=SharedNativePortfolio.deliver
        def observed(self,*a,**kw):
            started=time.monotonic()
            try:return original(self,*a,**kw)
            finally:samples.append(time.monotonic()-started)
        SharedNativePortfolio.deliver=observed
        policy=RiskPolicy(**json.loads((source/'operational/shared-capital-activation/risk-policy.proposed.json').read_text()))
        result=measure(policy);result['native_delivery_latency']=quantiles(samples)
    elif args.mode=='pons':
        from meme_machine.lanes.pons.provider_admission import Admission
        rows=[];errors=[]
        def lane(name,scope):
            a=Admission(out/'pons-admission.sqlite','https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE',lane=name,interval=.5)
            for _ in range(12):
                start=time.monotonic()
                try:a.acquire(scope,deadline=start+5,methods=('eth_getBlockByNumber',))
                except Exception as exc:errors.append(type(exc).__name__)
                rows.append(dict(lane=name,scope=scope,seconds=time.monotonic()-start))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(lane,'pons','pons_selective'),pool.submit(lane,'pons_survivor','pons_survivor_history')]
            for f in futures:f.result()
        result=dict(admission_probes=rows,errors=errors,fixture_deadline_misses=sum(r['seconds']>5 for r in rows),interval=.5,physical_market_requests=0)
    else:raise ValueError('worker_mode')
    final=io();result['worker_resources']=dict(cpu_seconds=time.process_time()-cpu,wall_seconds=time.monotonic()-wall,rss_peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        process_io_delta={k:final[k]-initial[k] for k in initial})
    (out/(args.mode+'.json')).write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')


def command(args,mode,out):
    return [sys.executable,str(Path(__file__).resolve()),'--mode',mode,'--source',args.source,'--capture',args.capture,'--output',str(out)]


def sample(pids):
    result={}
    # Include descendants, whose replay subprocess contains the actual load.
    all_pids=set(pids)
    for _ in range(3):
        for parent in list(all_pids):
            try:all_pids.update(map(int,Path(f'/proc/{parent}/task/{parent}/children').read_text().split()))
            except OSError:pass
    for pid in all_pids:
        try:
            stat=Path(f'/proc/{pid}/stat').read_text().split();ticks=os.sysconf('SC_CLK_TCK')
            result[str(pid)]=dict(cpu_seconds=(int(stat[13])+int(stat[14]))/ticks,
                rss_bytes=int(Path(f'/proc/{pid}/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE'),
                write_bytes=int(next(x.split(':')[1] for x in Path(f'/proc/{pid}/io').read_text().splitlines() if x.startswith('write_bytes:'))))
        except (OSError,ValueError,StopIteration):pass
    return result


def controller(args):
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,TMPDIR=str(out));logs=[];samples=[];codes={}
    try:
        for mode in ('allocator','pons'):
            log=(out/(mode+'-alone.log')).open('w');logs.append(log)
            completed=subprocess.run(command(args,mode,out),env=env,stdout=log,stderr=subprocess.STDOUT,timeout=60)
            if completed.returncode:raise RuntimeError(mode+'_failed')
            (out/(mode+'.json')).rename(out/(mode+'-alone.json'))
        replay=[sys.executable,str(Path(__file__).with_name('offline_replay.py')),'--source',args.source,'--capture',args.capture,'--output',str(out/'ingestion-alone')]
        log=(out/'ingestion-alone.log').open('w');logs.append(log)
        r=subprocess.run(replay,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=45)
        if r.returncode:raise RuntimeError('ingestion_failed')
        processes={}
        for mode in ('allocator','pons'):
            log=(out/(mode+'-combined.log')).open('w');logs.append(log)
            processes[mode]=subprocess.Popen(command(args,mode,out),env=env,stdout=log,stderr=subprocess.STDOUT)
        started=time.monotonic();cycles=[];load=None;load_number=0
        while any(p.poll() is None for p in processes.values()) or load is not None:
            if time.monotonic()-started>60:raise RuntimeError('offline_contention_wall_ceiling')
            if load is not None and load.poll() is not None:
                if load.returncode:raise RuntimeError('load_failed')
                cycles.append(json.loads((out/f'load-{load_number}/result.json').read_text()));load=None
            if load is None and any(p.poll() is None for p in processes.values()):
                load_number+=1;replay[-1]=str(out/f'load-{load_number}')
                log=(out/f'load-{load_number}.log').open('w');logs.append(log)
                load=subprocess.Popen(replay,env=env,stdout=log,stderr=subprocess.STDOUT)
            samples.append(dict(at=time.monotonic()-started,processes=sample([p.pid for p in processes.values()]+([] if load is None else [load.pid]))))
            time.sleep(.2)
        for k,p in processes.items():codes[k]=p.wait()
        if any(codes.values()):raise RuntimeError('combined_worker_failed')
        result=dict(schema='pump-provider-offline-contention-v1',source=args.source,provider_calls=0,
            host=dict(vcpus=os.cpu_count(),memory_bytes=os.sysconf('SC_PHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')),
            combined_seconds=time.monotonic()-started,exit_codes=codes,load_cycles=len(cycles),
            observed_peak_process_group_rss_bytes=max(sum(p['rss_bytes'] for p in s['processes'].values()) for s in samples),
            sampled_whole_process_resources=samples,
            allocator_alone=json.loads((out/'allocator-alone.json').read_text()),allocator_combined=json.loads((out/'allocator.json').read_text()),
            pons_alone=json.loads((out/'pons-alone.json').read_text()),pons_combined=json.loads((out/'pons.json').read_text()),
            ingestion_alone=json.loads((out/'ingestion-alone/result.json').read_text()),combined_ingestion=cycles,
            limitations=['Zero provider workload: Pons probes certify fixture admission only.', 'Original candidate and real position deadlines require authorized live evidence.', 'Profiler overhead belongs to ingestion runs; allocator native fixture includes the same 64 requests and durable deliveries.', 'Peak RSS is sampled at 0.2 seconds; complete child CPU is retained by their result receipts.'])
        (out/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
        print(json.dumps(dict(output=str(out),cycles=len(cycles),alone=result['allocator_alone']['performance']['grant_latency'],combined=result['allocator_combined']['performance']['grant_latency'],native_alone=result['allocator_alone']['native_delivery_latency'],native_combined=result['allocator_combined']['native_delivery_latency'],misses=result['allocator_combined']['performance']['missed_funding_ceiling_5s']),indent=2))
    finally:
        for p in list(locals().get('processes',{}).values())+[locals().get('load')]:
            if p is not None and p.poll() is None:p.terminate();p.wait(timeout=10)
        for f in logs:f.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--capture',required=True);p.add_argument('--output',required=True);p.add_argument('--mode',default='controller')
    args=p.parse_args();worker(args) if args.mode!='controller' else controller(args)


if __name__=='__main__':main()
