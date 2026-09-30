"""Fresh provider-free diagnosis; no qualification, repair, signing or live market."""
from __future__ import annotations
import argparse, asyncio, contextlib, dataclasses, hashlib, importlib.metadata, json
import os, platform, resource, socket, sqlite3, subprocess, sys, threading, time, traceback
from collections import deque
from concurrent.futures import Future, ProcessPoolExecutor as NativePool
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

from certification import run381_pressure as workload
from certification.combined_observer import Interaction
from meme_machine import solana_evidence_service as service
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceWriter
from meme_machine.solana_evidence_runtime import RuntimeEvidence
from meme_machine.solana_maintenance_runtime import MaintenanceRuntime
from meme_machine.solana_maintenance_arbiter import MaintenanceArbiter
from meme_machine import solana_checkpoint

BASE = 'dc08f9064cf5e37b63f383f52aa709d0afc1723f'
ROOT = Path(__file__).resolve().parents[2]
SCOPES = ('program:meteora', 'program:pump', 'program:pumpswap')
REVISION = 'fresh-capacity-v1'
G = None


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def identity():
    def manifest(ref):
        return {line.split('\t', 1)[1]: line.split('\t', 1)[0]
                for line in git('ls-tree', '-r', ref).splitlines()}
    old, new = manifest(BASE), manifest('HEAD')
    assert all(new.get(k) == v for k, v in old.items()), 'production_blob_or_mode_changed'
    added = set(new) - set(old)
    assert all(k.startswith('diagnostics/stage-e-fresh-causal-isolation/') or
               k == '.github/workflows/stage-e-fresh-causal-isolation.yml' for k in added)
    return dict(source_sha=BASE, source_tree=git('rev-parse', BASE+'^{tree}'),
                diagnostic_sha=git('rev-parse', 'HEAD'), diagnostic_tree=git('rev-parse', 'HEAD^{tree}'),
                diagnostic_revision=REVISION, preexisting_files_verified=len(old),
                all_preexisting_blobs_and_modes_unchanged=True,
                diagnostic_hashes={k: hashlib.sha256((ROOT/k).read_bytes()).hexdigest()
                                   for k in sorted(added) if (ROOT/k).is_file()})


def environment():
    def read(path):
        try: return Path(path).read_text()[:4096]
        except OSError: return None
    return dict(os=platform.platform(), runner_os=os.getenv('RUNNER_OS'),
                python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                websockets=importlib.metadata.version('websockets'), cpu_count=os.cpu_count(),
                affinity_count=len(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,
                memory=read('/proc/meminfo'), cpu_quota=read('/sys/fs/cgroup/cpu.max'),
                expected=dict(python='3.12.14', websockets='17.1', sqlite='3.45.1'),
                differences={k:v for k,v,w in [('python',platform.python_version(),'3.12.14'),
                    ('sqlite',sqlite3.sqlite_version,'3.45.1'),
                    ('websockets',importlib.metadata.version('websockets'),'17.1')] if v != w},
                run_id=os.getenv('GITHUB_RUN_ID'), run_attempt=os.getenv('GITHUB_RUN_ATTEMPT'))


class Telemetry:
    def __init__(self):
        self.lock=threading.RLock(); self.rows={}; self.ring=deque(maxlen=64)
        self.latest=None; self.runtime=None; self.owner=None; self.state=None
        self.checkpoints=deque(maxlen=8); self.start=time.monotonic()
    def add(self, name, wall=0, cpu=0, units=0, error=False):
        with self.lock:
            row=self.rows.setdefault(name, dict(calls=0,wall=0.,cpu=0.,peak=0.,units=0,errors=0))
            row['calls']+=1; row['wall']+=max(0,wall); row['cpu']+=max(0,cpu)
            row['peak']=max(row['peak'],wall); row['units']+=units; row['errors']+=int(error)
    def measure(self, name, fn, units=0):
        start=time.monotonic(); cpu=time.thread_time(); error=False
        try: return fn()
        except BaseException: error=True; raise
        finally:
            end=time.monotonic(); used=time.thread_time()-cpu
            self.add(name,end-start,used,units,error)
            self.add('diagnostic_wrapper',time.monotonic()-end)
    def snapshot(self):
        with self.lock:
            return dict(metrics={k:dict(v) for k,v in self.rows.items()},
                        scheduling=self.latest, checkpoints=list(self.checkpoints))


def explain(arbiter, needs, ready, now):
    """Read-only reconstruction AFTER native choose; never supplies its decision."""
    by={}; result=[]
    for n in needs:
        if not n.units: continue
        origin=arbiter.origin.get((n.side,n.scope),now)
        service_deadline=origin+arbiter.leases.drought
        recovery=n.recovery_deadline if n.recovery_excess else None
        deadline=min(n.safety_deadline,service_deadline,
                     recovery if recovery is not None else float('inf'))
        by[n.side]=min(by.get(n.side,float('inf')),deadline)
        result.append(dict(scope=n.scope,side=n.side,units=n.units,records=n.records,
            recovery_excess=n.recovery_excess,safety_deadline=n.safety_deadline,
            recovery_deadline=recovery,service_deadline=service_deadline,
            safety_headroom=n.safety_deadline-now,
            recovery_headroom=None if recovery is None else recovery-now,
            service_headroom=service_deadline-now,binding=min(
                [('safety',n.safety_deadline),('service',service_deadline)]+
                ([('recovery',recovery)] if recovery is not None else []),key=lambda v:v[1])[0]))
    finish=now+arbiter.leases.execution
    feasible=[side for side,deadline in by.items() if ready[side] and finish<deadline
              and all(finish+arbiter.leases.owner+arbiter.leases.execution<other_deadline
                      for other,other_deadline in by.items() if other!=side)]
    return dict(at=now,ready=dict(ready),needs=result,deadlines=by,feasible=feasible,
                reservations=dataclasses.asdict(arbiter.leases))


def worker_call(fn, args, kwargs, submitted, archive_floor):
    """Child records dispatch-to-start, execution and return transport separately."""
    start=time.monotonic(); cpu=time.thread_time()
    archive=fn is EvidenceWriter.prepare_and_write_archive
    result=fn(*args,**kwargs)
    native_end=time.monotonic(); used=time.thread_time()-cpu
    wait=max(0,archive_floor*len(result[0])/1000-(native_end-start)) if archive else 0
    if wait: time.sleep(wait)
    return result,dict(queue=start-submitted,native=native_end-start,cpu=used,
        injected_wait=wait,end=time.monotonic(),records=len(result[0]) if archive else 0)


class ObservedPool:
    def __init__(self,*args,**kwargs):
        self.pool=NativePool(*args,**kwargs)
    def submit(self,fn,*args,**kwargs):
        before=time.monotonic()
        label='archive_worker' if fn is EvidenceWriter.prepare_and_write_archive else 'source_worker'
        future=self.pool.submit(worker_call,fn,args,kwargs,before,G.config['archive_floor'])
        after=time.monotonic(); mapped=Future()
        def done(f):
            begin=time.monotonic()
            try:
                value,t=f.result()
                G.add(label+'.dispatch_to_start',t['queue'])
                G.add(label+'.native',t['native'],t['cpu'],t['records'])
                G.add(label+'.injected_wait',t['injected_wait'])
                G.add(label+'.return_transport',max(0,begin-t['end']))
                mapped.set_result(value)
            except BaseException as exc: mapped.set_exception(exc)
            finally: G.add('diagnostic_wrapper',time.monotonic()-begin)
        future.add_done_callback(done)
        G.add('worker_parent_submission',after-before)
        G.add('diagnostic_wrapper',time.monotonic()-after)
        return mapped
    def shutdown(self,*args,**kwargs): return self.pool.shutdown(*args,**kwargs)


class Observer:
    """No payload scan: one short read transaction on the production synopsis."""
    def __init__(self,path,output):
        self.path=path; self.output=output; self.rows=[]; self.errors=[]
        self.stop=threading.Event(); self.thread=threading.Thread(target=self.run,daemon=True)
    def capture(self):
        started=time.monotonic(); wall=time.time()
        if not self.path.exists(): return None
        with contextlib.closing(sqlite3.connect(self.path,timeout=.5,isolation_level=None)) as db:
            db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
            try:
                tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'maintenance_cohorts' not in tables: return None
                c=dict(db.execute('SELECT key,value FROM counters'))
                frames=c.get('stream_accepted_messages',0)
                scope_rows={}
                for scope in SCOPES:
                    values=db.execute('''SELECT SUM(hot),SUM(archived),
                       SUM(CASE WHEN at<? THEN hot ELSE 0 END),MIN(CASE WHEN hot>0 THEN at END),
                       MIN(at) FROM maintenance_cohorts WHERE scope=?''',(wall-180,scope)).fetchone()
                    h,a,e,hot_at,retained_at=values
                    scope_rows[scope]=dict(hot=h or 0,archived_pending=a or 0,eligible_hot=e or 0,
                        recovery_excess=max(0,(e or 0)-1000),
                        hot_age=0 if hot_at is None else wall-hot_at,
                        retained_age=0 if retained_at is None else wall-retained_at,
                        archived=c.get('lifecycle.archived.'+scope,0),
                        retired=c.get('lifecycle.retired.'+scope,0),
                        ingested=c.get('lifecycle.ingested.'+scope,0))
                frontiers={}
                for scope in SCOPES:
                    f=db.execute('SELECT value FROM service_health WHERE key=?',
                                 ('finalized_frontier:'+scope,)).fetchone()
                    if f: frontiers[scope]=json.loads(f[0])
                pins=db.execute('SELECT COUNT(*) FROM interests WHERE active=1').fetchone()[0]
                gaps=db.execute('SELECT COUNT(*) FROM gaps WHERE repaired IS NULL').fetchone()[0]
                episodes=[dict(scope=s,side=side,source_deadline=d,wall_started=w,envelope=e)
                          for s,side,d,w,e in db.execute('SELECT * FROM maintenance_episodes')]
            finally: db.execute('ROLLBACK')
        qualification_time=time.monotonic()-started
        G.add('qualification_observer_equivalent',qualification_time)
        debug=time.monotonic(); snap=G.snapshot()
        native=G.runtime
        observation=native.last_observation if native else None
        # ScopeState values are immutable owner observations; source snapshots
        # and this owner observation have separate timestamps.
        owner_obs=None if observation is None else dataclasses.asdict(observation)
        row=dict(elapsed=time.monotonic()-G.start,wall=wall,frames=frames,source_seconds=frames*.27,
            counters=c,scopes=scope_rows,source_lag=max((wall-f['time'] for f in frontiers.values()),default=0),
            pins=pins,gaps=gaps,arrival_inference_valid=pins==gaps==0,episodes=episodes,
            wal_bytes=Path(str(self.path)+'-wal').stat().st_size if Path(str(self.path)+'-wal').exists() else 0,
            db_bytes=self.path.stat().st_size,owner=G.owner.telemetry() if G.owner else {},
            production_stages=dict(G.state.storage_metrics) if G.state else {},
            owner_observation=owner_obs,**snap)
        # Avoid publishing the production's full duplicate ring every sample.
        row['production_stages'].pop('maintenance_arbiter',None)
        if self.rows:
            old=self.rows[-1]; elapsed=row['elapsed']-old['elapsed']
            for scope,s in scope_rows.items():
                prior=old['scopes'][scope]; drain=s['archived']-prior['archived']
                net=s['eligible_hot']-prior['eligible_hot']
                s.update(interval_seconds=elapsed,archive_drain=drain,net_debt_change=net,
                         eligibility_arrivals_inferred=net+drain,
                         archive_drain_per_second=drain/elapsed,
                         eligibility_arrivals_per_second=(net+drain)/elapsed)
        G.add('periodic_debug_observer',time.monotonic()-debug)
        G.add('periodic_observer_total',time.monotonic()-started)
        return row
    def run(self):
        while not self.stop.is_set():
            try:
                row=self.capture()
                if row:
                    self.rows.append(row)
                    begin=time.monotonic(); raw=json.dumps(row,sort_keys=True)+'\n'
                    G.add('serialization',time.monotonic()-begin)
                    begin=time.monotonic()
                    with (self.output/'timeline.jsonl').open('a') as stream: stream.write(raw)
                    G.add('persistence',time.monotonic()-begin)
                    if len(self.rows)%6==0: print('CAPACITY '+json.dumps(compact(row)),flush=True)
            except Exception as exc: self.errors.append(type(exc).__name__+':'+str(exc))
            self.stop.wait(G.config['sample_seconds'])
    def close(self):
        self.stop.set(); self.thread.join(timeout=5)
        if self.thread.is_alive(): self.errors.append('observer_shutdown_timeout')


def compact(row):
    scheduling=row.get('scheduling') or {}
    return dict(elapsed=round(row['elapsed'],3),frames=row['frames'],source_seconds=row['source_seconds'],
        source_lag=round(row['source_lag'],3),wal_bytes=row['wal_bytes'],
        scopes={s:{k:v for k,v in x.items() if k in ('eligible_hot','recovery_excess','archived_pending',
            'hot_age','retained_age','archived','archive_drain','net_debt_change','eligibility_arrivals_inferred',
            'archive_drain_per_second','eligibility_arrivals_per_second')} for s,x in row['scopes'].items()},
        scheduling={k:v for k,v in scheduling.items() if k in ('at','ready','selected','feasible','needs',
            'owner_delay','worker_age','error')},metrics=row['metrics'],owner=row['owner'])


async def run(config,output):
    global G
    G=Telemetry(); G.config=config
    output.mkdir(parents=True,exist_ok=False)
    ident=identity(); env=environment()
    write=lambda name,value: (output/name).write_text(json.dumps(value,indent=2)+'\n')
    write('identity.json',ident); write('environment.json',env); write('configuration.json',config)
    control=Interaction(); path=output/'runtime'/'db'; path.parent.mkdir()
    observer=Observer(path,output)
    native_source=service.ServiceState.source_batch; native_stage=service.ServiceState._storage_stage
    native_tx=EvidenceWriter.transaction; native_choose=MaintenanceArbiter.choose
    native_checkpoint=EvidenceWriter.checkpoint; native_boundary=solana_checkpoint.checkpoint_and_reclaim
    native_owner_init=PriorityOwner.__init__

    class State(service.ServiceState):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs); G.state=self; control.path=path
        def source_batch(self,items):
            phase=control.source_started(len(items)); start=time.monotonic(); cpu=time.thread_time()
            value=native_source(self,items); end=time.monotonic()
            wait=max(0,config['source_owner_floor']*len(items)-(end-start))
            if wait: time.sleep(wait)
            G.add('source_owner_native',end-start,time.thread_time()-cpu,len(items))
            G.add('source_owner_injected_wait',wait)
            control.source_completed(phase,len(items)); return value

    class Runtime(MaintenanceRuntime):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs); G.runtime=self
        def turn(self,flight,submitted):
            try: return super().turn(flight,submitted)
            finally:
                begin=time.monotonic()
                if G.latest is not None:
                    row=dict(G.latest,owner_delay=begin-submitted,
                             worker_age=None if flight.submitted is None else begin-flight.submitted)
                    if self.ring:
                        event=self.ring[-1]
                        row.update(owner_delay=event.get('owner_delay'),execution=event.get('execution'),
                                   durable_records=event.get('durable_records'),error=event.get('error'))
                    with G.lock: G.latest=row; G.ring.append(row)
                G.add('diagnostic_wrapper',time.monotonic()-begin)

    class Wire(workload.Wire):
        def __init__(self):
            super().__init__(); self.frames=config['frames']; self.paused=set(); self.pause_deadline=None
        async def recv(self,decode=None):
            if self.sent in (800,1400) and self.sent not in self.paused:
                self.paused.add(self.sent)
                sample=await asyncio.to_thread(control.inspect)
                sample['source_seconds']=self.sent*.27
                control.metrics['burst_evidence'].append(sample)
                self.pause_started=time.monotonic(); self.pause_deadline=self.pause_started+8; self.pause_sample=sample
            if self.pause_deadline is not None:
                await asyncio.sleep(max(0,self.pause_deadline-time.monotonic()))
                self.pause_sample['observed_pause_seconds']=time.monotonic()-self.pause_started
                self.pause_deadline=None
                with control.lock: control.phase+=1
            return await super().recv(decode)

    def stage(state,name,fn):
        return G.measure('stage.'+name,lambda:native_stage(state,name,fn))
    @contextlib.contextmanager
    def transaction(writer):
        outer=not writer.db.in_transaction and not getattr(writer,'_source_frame_depth',0)
        if not outer:
            with native_tx(writer): yield
            return
        start=time.monotonic(); cpu=time.thread_time(); changes=writer.db.total_changes
        try:
            with native_tx(writer):
                yield
                if writer.db.total_changes!=changes and config['commit_latency']:
                    delay=time.monotonic(); time.sleep(config['commit_latency'])
                    G.add('transaction_injected_wait',time.monotonic()-delay)
        finally:
            end=time.monotonic(); G.add('outer_transaction',end-start,time.thread_time()-cpu)
            G.add('diagnostic_wrapper',time.monotonic()-end)
    def choose(arbiter,**kw):
        selected=None; error=None
        try:
            selected=native_choose(arbiter,**kw); return selected
        except BaseException as exc:
            error=type(exc).__name__+':'+str(exc); raise
        finally:
            start=time.monotonic()
            row=explain(arbiter,kw['needs'],kw['ready'],kw['now'])
            row.update(selected=selected.side if selected else None,error=error)
            with G.lock: G.latest=row
            G.add('diagnostic_wrapper',time.monotonic()-start)
    def owner_init(owner,*args,**kwargs):
        G.owner=owner; return native_owner_init(owner,*args,**kwargs)
    def checkpoint(p):
        def io(q):
            result=G.measure('checkpoint_passive_native',lambda:native_checkpoint(q))
            with G.lock: G.checkpoints.append(dict(at=time.monotonic(),state=result))
            return result
        return G.measure('checkpoint_with_workload_interaction',lambda:control.checkpoint(p,io))
    def boundary(p):
        return G.measure('checkpoint_boundary_native',lambda:native_boundary(p))
    real_connect=socket.socket.connect
    def local_only(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6): raise RuntimeError('provider_call_forbidden')
        return real_connect(sock,address)
    wire=Wire(); stop=asyncio.Event(); failure=None; failures=[]; queries=0
    async def candidate_reads():
        nonlocal queries
        while not stop.is_set():
            if observer.rows and observer.rows[-1]['frames']>10:
                def read():
                    plane=RuntimeEvidence(path,owner='meteora')
                    try:
                        top=plane.frontier('program:meteora')
                        plane.command(op='ack',owner='meteora:run381',scope='program:meteora',slot=top)
                        counts={s:len(plane.reader.window(s,top,top,as_of=time.time())) for s in SCOPES}
                        assert counts['program:meteora']==128 and all(counts.values())
                    finally: plane.close()
                try: await asyncio.to_thread(read); queries+=1
                except Exception as exc: failures.append(type(exc).__name__+':'+str(exc)); stop.set()
            try: await asyncio.wait_for(stop.wait(),10)
            except TimeoutError: pass
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(service,'ServiceState',State))
        stack.enter_context(patch.object(service.ServiceState,'_storage_stage',stage))
        stack.enter_context(patch.object(EvidenceWriter,'transaction',transaction))
        stack.enter_context(patch.object(MaintenanceArbiter,'choose',choose))
        stack.enter_context(patch('meme_machine.solana_maintenance_runtime.MaintenanceRuntime',Runtime))
        stack.enter_context(patch.object(PriorityOwner,'__init__',owner_init))
        stack.enter_context(patch('concurrent.futures.ProcessPoolExecutor',ObservedPool))
        stack.enter_context(patch.object(EvidenceWriter,'checkpoint',staticmethod(checkpoint)))
        stack.enter_context(patch.object(solana_checkpoint,'checkpoint_and_reclaim',boundary))
        stack.enter_context(patch('websockets.asyncio.client.connect',return_value=wire))
        stack.enter_context(patch.object(socket.socket,'connect',local_only))
        # Native local IPC on Actions; no network provider, token or wallet.
        observer.thread.start()
        runner=asyncio.create_task(service.serve(path,
            'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
        ack=asyncio.create_task(control.acknowledgements())
        reads=asyncio.create_task(candidate_reads())
        try:
            while True:
                if runner.done(): await runner; break
                if stop.is_set(): break
                if observer.rows:
                    last=observer.rows[-1]
                    if last['frames']>=config['frames']: break
                    if last['source_lag']>45: raise RuntimeError('source_clock_fell_behind')
                    if any(s['retained_age']>=240 for s in last['scopes'].values()):
                        raise RuntimeError('retention_clock_fell_behind')
                if time.monotonic()-G.start>config['frames']*.27+120:
                    raise RuntimeError('diagnostic_horizon_exceeded')
                await asyncio.sleep(.25)
        except BaseException as exc:
            failure=type(exc).__name__+':'+str(exc)
            write('failure-stack.json',[dict(file=Path(f.filename).name,line=f.lineno,function=f.name)
                  for f in traceback.extract_tb(exc.__traceback__)[-16:]])
        finally:
            stop.set(); control.stopping=True
            try: await runner
            except BaseException as exc:
                failure=failure or type(exc).__name__+':'+str(exc)
            await asyncio.gather(ack,reads,return_exceptions=True)
            observer.close()
    final=observer.capture()
    if final: observer.rows.append(final); write('final-snapshot.json',final)
    with contextlib.closing(sqlite3.connect(path)) as db:
        counters=dict(db.execute('SELECT key,value FROM counters'))
        health={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM service_health')}
        integrity=db.execute('PRAGMA integrity_check').fetchall()
        pragmas={p:db.execute('PRAGMA '+p).fetchall() for p in ['journal_mode','synchronous','page_count','freelist_count']}
    runtime_elapsed=time.monotonic()-G.start
    write('terminal-ring.json',list(G.ring)); write('native-health.json',health)
    write('interaction.json',control.metrics)
    errors=observer.errors+failures+control.metrics['urgent_errors']
    archive_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in path.parent.glob('*.archive/*.gz')}
    write('archive-hashes.json',archive_hashes)
    metrics=G.snapshot()['metrics']
    overhead=sum(metrics.get(k,{}).get('wall',0) for k in
        ('periodic_observer_total','serialization','persistence','diagnostic_wrapper'))
    result=dict(variant=config['id'],failure=failure,observer_errors=errors,
        completed_frames=counters.get('stream_accepted_messages',0),
        source_seconds=counters.get('stream_accepted_messages',0)*.27,
        planned_frames=config['frames'],runtime_elapsed=runtime_elapsed,
        counters=counters,metrics=metrics,integrity=integrity,pragmas=pragmas,queries=queries,
        provider_calls=0,paper_only=True,canonical_authority=False,stage_e='RED',stage_f='NOT_STARTED',
        diagnostic_overhead_seconds=overhead,diagnostic_overhead_fraction=overhead/runtime_elapsed,
        overlap_warning='Stage, transaction, owner and worker measurements overlap; do not sum.',
        worker_queue_definition='submit-to-child-start includes serialization/IPC and pool queue',
        arrival_definition='delta eligible hot + delta durable archived in same read snapshot; invalid with pins/gaps',
        terminal=G.latest,production_identity=ident,environment=env,configuration=config)
    write('summary.json',result)
    timeline=[compact(r) for r in observer.rows]
    write('capacity-timeline.json',timeline)
    print('RESULT '+json.dumps(result,sort_keys=True),flush=True)
    print('TERMINAL '+json.dumps(list(G.ring)[-8:],sort_keys=True),flush=True)
    return result


def selfcheck():
    from meme_machine.solana_maintenance_arbiter import Need, ServiceLeases
    leases=ServiceLeases()
    for ready in ({'archive':True,'retirement':True},{'archive':False,'retirement':True}):
        for archive_remaining in (5.936821,10.,30.):
            arb=MaintenanceArbiter('g',leases)
            needs=[Need('a','archive',5632,5632,100.,archive_remaining,4632),
                   Need('a','retirement',20,20,100.,None,0)]
            decision=None
            try: decision=arb.choose(generation='g',as_of=0.,now=0.,needs=needs,ready=ready)
            except ValueError: pass
            detail=explain(arb,needs,ready,0.)
            assert decision is None or decision.side in detail['feasible']
            if not ready['archive'] and archive_remaining==5.936821:
                assert detail['feasible']==[] and detail['needs'][0]['binding']=='recovery'
    print('diagnostic arithmetic selfcheck passed')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--selfcheck',action='store_true')
    parser.add_argument('--request'); parser.add_argument('--output')
    args=parser.parse_args()
    if args.selfcheck: selfcheck(); return
    request=json.loads(Path(args.request).read_text())
    assert request['source_sha']==BASE and request['paper_only'] is True
    assert 1<=request['material_variant_number']<=6 and len(request['variants'])==1
    assert not os.getenv('GITHUB_RUN_ATTEMPT') or os.getenv('GITHUB_RUN_ATTEMPT')=='1'
    assert not (ROOT/'diagnostics/stage-e-fresh-causal-isolation/ASTRA_GATE.json').exists()
    config=request['variants'][0]
    plan=json.loads((ROOT/'certification/stagee24_qualification_plan.json').read_text())
    assert config['frames']==plan['extended_frames'] and config['sample_seconds']==plan['sample_wall_seconds']
    assert config['archive_floor']==workload.ARCHIVE_SECONDS_PER_THOUSAND
    assert config['commit_latency']==workload.COMMIT_LATENCY_SECONDS
    assert config['source_owner_floor'] in (0.,workload.OWNER_SECONDS_PER_FRAME)
    asyncio.run(run(config,Path(args.output)))


if __name__=='__main__': main()
