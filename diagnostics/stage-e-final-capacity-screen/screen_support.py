"""Read-only screen observation and identity checks. Never maintenance authority."""
import asyncio
import contextlib
import copy
import hashlib
import importlib.metadata
import json
import multiprocessing
import os
from pathlib import Path
import resource
import socket
import sys
import time
import urllib.request
from unittest.mock import patch


def canonical(row):
    return json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(path, row):
    path.write_text(json.dumps(row, indent=2, sort_keys=True)+'\n')


def initialize_child():
    """Spawn workers retain the same Internet firewall and source identity."""
    begin=time.monotonic()
    directory=Path(os.environ['MM_SCREEN_FIREWALL_DIR'])
    directory.mkdir(parents=True,exist_ok=True)
    real_connect=socket.socket.connect
    real_connect_ex=socket.socket.connect_ex
    def deny(kind):
        def rejected(*args,**kwargs):
            with (directory/('attempt-'+str(os.getpid())+'.jsonl')).open('a') as stream:
                stream.write(json.dumps({'kind':kind,'pid':os.getpid()})+'\n')
            raise PermissionError('provider_attempt_forbidden:'+kind)
        return rejected
    def connect(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):return deny('connect')(sock,address)
        return real_connect(sock,address)
    def connect_ex(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):return deny('connect_ex')(sock,address)
        return real_connect_ex(sock,address)
    socket.socket.connect=connect
    socket.socket.connect_ex=connect_ex
    socket.create_connection=deny('create_connection')
    socket.getaddrinfo=deny('getaddrinfo')
    urllib.request.urlopen=deny('urlopen')
    pre=json.loads(Path(os.environ['MM_SCREEN_PREDECLARATION']).read_bytes())
    for name,want in pre['screen_files'].items():
        assert digest((Path(__file__).parent/name).read_bytes())==want,name
    write(directory/('child-'+str(os.getpid())+'.json'),{
        'pid':os.getpid(),'commit':pre['arms'][os.environ['MM_SCREEN_ARM']]['commit'],
        'tree':pre['arms'][os.environ['MM_SCREEN_ARM']]['tree'],
        'assembly_digest':pre['arms'][os.environ['MM_SCREEN_ARM']]['assembly_digest'],
        'firewall_enabled':True,'startup_observation_seconds':time.monotonic()-begin})


def verify_arm():
    pre_path=Path(os.environ['MM_SCREEN_PREDECLARATION'])
    pre=json.loads(pre_path.read_bytes())
    arm=os.environ['MM_SCREEN_ARM']
    bound=pre['arms'][arm]
    assembly=Path(os.environ['MM_SCREEN_ASSEMBLY'])
    manifest=json.loads((assembly/'assembly.json').read_bytes())
    own=manifest.pop('assembly_digest')
    assert own==bound['assembly_digest']==digest(canonical(manifest))
    assert manifest['identity']['candidate_sha']==bound['commit']
    assert manifest['identity']['candidate_tree']==bound['tree']
    source=assembly/'source'
    assert str(source)==os.environ['MM_SCREEN_SOURCE']
    actual={p.relative_to(source).as_posix():p for p in source.rglob('*') if p.is_file()}
    assert set(actual)==set(manifest['files'])
    for name,info in manifest['files'].items():
        path=actual[name]
        assert not path.is_symlink() and not path.stat().st_mode & 0o222
        assert digest(path.read_bytes())==info['sha256'], name
    from certification.stage_e_native_v2.binding import environment_identity
    environment=environment_identity()
    assert environment==pre['environment_identity'], 'environment_drift'
    here=Path(__file__).parent
    for name,want in pre['screen_files'].items():
        assert digest((here/name).read_bytes())==want, name
    return dict(arm=arm,commit=bound['commit'],tree=bound['tree'],assembly_digest=own,
        run_id=pre['execution_key'],attempt=1,predeclaration_sha256=digest(pre_path.read_bytes()),
        exact_source_files_verified=len(actual),environment_exact_match=True,
        observer_configuration=pre['instrumentation'])


def measured(g, name, fn):
    begin=time.monotonic()
    try:
        return fn()
    finally:
        g.add(name,time.monotonic()-begin)


@contextlib.contextmanager
def instrument(h):
    """The same wrappers in each arm; native functions execute unchanged."""
    from meme_machine.solana_owner_admission import OwnerAdmission
    from meme_machine.solana_evidence_control import PriorityOwner
    from meme_machine.solana_evidence_plane import EvidenceWriter
    g=h.G
    g.provider_attempts=multiprocessing.Value('i',0)
    native_init=OwnerAdmission.__init__
    native_release=OwnerAdmission._release
    native_rendezvous=OwnerAdmission.rendezvous
    native_submit=PriorityOwner.submit
    native_writer_close=EvidenceWriter.close
    native_pool_init=h.ObservedPool.__init__
    native_pool_submit=h.ObservedPool.submit

    def admission_init(obj,*args,**kwargs):
        result=native_init(obj,*args,**kwargs)
        g.a2=obj
        return result

    def admission_release(obj,offer):
        result=native_release(obj,offer)
        begin=time.monotonic()
        g.bounded(g.offers,offer.row,4096)
        g.add('diagnostic_wrapper',time.monotonic()-begin)
        return result

    async def rendezvous(obj,snapshot):
        return await native_rendezvous(obj,snapshot)

    def submit(owner,fn,**kwargs):
        row={'priority':kwargs.get('priority',1),'submit':time.monotonic(),
             'expires':kwargs.get('expires'),'admit_before':kwargs.get('admit_before')}
        def observed(state):
            begin=time.monotonic()
            row['entry']=begin
            # Native selection already happened. This observation cannot reorder it.
            with owner.cv:
                pending=[(x[0],x[1]) for x in owner.queue]
                row['checkpoint_hold']=owner._checkpoint_handoff is not None
            row['queued_at_entry']=pending
            g.add('diagnostic_wrapper',time.monotonic()-begin)
            try:
                return fn(state)
            finally:
                begin=time.monotonic()
                row['end']=begin
                row['execution']=begin-row['entry']
                row['transaction_open_at_return']=bool(state.writer.db.in_transaction)
                g.add('diagnostic_wrapper',time.monotonic()-begin)
        future=native_submit(owner,observed,**kwargs)
        begin=time.monotonic()
        row.update(sequence=future.owner_sequence,accepted=future.owner_accepted_at)
        with g.lock:
            g.outstanding[future.owner_sequence]=future
            g.bounded(g.owner_events,row,32768)
        def done(f):
            begin=time.monotonic()
            with g.lock:
                g.outstanding.pop(f.owner_sequence,None)
            row.update(completion=begin,error=str(f.exception()) if f.exception() else None)
            g.add('diagnostic_wrapper',time.monotonic()-begin)
        future.add_done_callback(done)
        g.add('diagnostic_wrapper',time.monotonic()-begin)
        return future

    def writer_close(writer):
        if g.state is not None and writer is g.state.writer:
            g.writer_close.append({'at':time.monotonic(),'transaction_open':writer.db.in_transaction})
        return native_writer_close(writer)

    def pool_init(obj,*args,**kwargs):
        result=native_pool_init(obj,*args,**kwargs)
        g.pools.append(obj.pool)
        return result

    def pool_submit(obj,*args,**kwargs):
        result=native_pool_submit(obj,*args,**kwargs)
        begin=time.monotonic()
        processes=obj.pool._processes or {}
        g.worker_pids.update(processes)
        g.add('diagnostic_wrapper',time.monotonic()-begin)
        return result

    real_connect=socket.socket.connect
    real_connect_ex=socket.socket.connect_ex
    def attempt(kind):
        with g.provider_attempts.get_lock():g.provider_attempts.value+=1
        raise PermissionError('provider_attempt_forbidden:'+kind)
    def connect(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):return attempt('connect')
        return real_connect(sock,address)
    def connect_ex(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):return attempt('connect_ex')
        return real_connect_ex(sock,address)
    def deny(kind):
        return lambda *a,**kw:attempt(kind)
    with contextlib.ExitStack() as stack:
        for obj,name,value in (
            (OwnerAdmission,'__init__',admission_init),
            (OwnerAdmission,'_release',admission_release),
            (OwnerAdmission,'rendezvous',rendezvous),
            (PriorityOwner,'submit',submit),
            (EvidenceWriter,'close',writer_close),
            (h.ObservedPool,'__init__',pool_init),
            (h.ObservedPool,'submit',pool_submit),
            (socket.socket,'connect',connect),
            (socket.socket,'connect_ex',connect_ex),
            (socket,'getaddrinfo',deny('getaddrinfo')),
            (socket,'create_connection',deny('create_connection')),
            (urllib.request,'urlopen',deny('urlopen'))):
            stack.enter_context(patch.object(obj,name,value))
        yield


async def sample_tasks(g,stop):
    while not stop.is_set():
        begin=time.monotonic()
        try:
            row={'at':begin,'elapsed':begin-g.start,'offered_frames':g.wire.sent,
                'offered_source_seconds':g.wire.sent*.27,'committed_frames':g.frames,
                'committed_source_seconds':g.frames*.27}
            row['offered_due_frames']=0 if g.wire.start is None else min(1334,max(0,int((time.time()-g.wire.start)/.27)+1))
            for task in asyncio.all_tasks():
                for frame in task.get_stack():
                    if frame.f_code.co_filename.endswith('solana_evidence_service.py'):
                        local=frame.f_locals
                        if frame.f_code.co_name=='commit_ordered':
                            row.update({k:local.get(k) for k in ('pending_frames','pending_bytes','receive_sequence')})
                            for k in ('ready','decoded','inbound'):
                                obj=local.get(k)
                                if obj is not None:row[k]=len(obj) if k=='ready' else obj.qsize()
                            row['admitted_data_frames']=max(0,local.get('receive_sequence',0)-1)
                        if 'counts' in local:
                            row['stream_counts']=dict(local['counts'])
            if g.flight:
                row['archive_flight']={'future':g.flight.future is not None,
                    'ready':g.flight.future.done() if g.flight.future else False,
                    'pending':g.flight.pending is not None,'prepared':g.flight.prepared is not None,
                    'age':None if g.flight.submitted is None else begin-g.flight.submitted,
                    'generation':g.flight.generation}
            if g.owner:
                with g.owner.cv:
                    row['owner_queue_depth']=len(g.owner.queue)
                    row['owner_busy']=g.owner._checkpoint_busy
                    row['checkpoint_hold']=g.owner._checkpoint_handoff is not None
            g.queue_latest=row
            g.bounded(g.queue_samples,row,4096)
        except Exception as exc:
            g.observation_errors.append('queue:'+type(exc).__name__+':'+str(exc))
        finally:
            g.add('screen_queue_observation',time.monotonic()-begin)
        try:await asyncio.wait_for(stop.wait(),1)
        except TimeoutError:pass


async def mature_boundaries(g,observer,output,stop):
    pre=json.loads(Path(os.environ['MM_SCREEN_PREDECLARATION']).read_bytes())
    while g.wire.start is None and not stop.is_set():
        await asyncio.sleep(.05)
    if stop.is_set():return
    for label,offset in zip(('start','end'),pre['mature_interval']['source_seconds']):
        due=g.wire.start+offset
        try:await asyncio.wait_for(stop.wait(),max(0,due-time.time()))
        except TimeoutError:pass
        if stop.is_set():return
        start=time.monotonic()
        try:
            row=await asyncio.to_thread(observer.capture)
            if row is None:raise ValueError('missing_boundary_snapshot')
            row.update(boundary=label,planned_source_offset=offset,
                source_coordinate_at_acquisition=row['wall']-g.wire.start,
                acquisition_gap=row['wall']-due,source_offered_frames=g.wire.sent)
            g.mature[label]=row
            write(output/('mature-'+label+'.json'),row)
        except Exception as exc:
            g.observation_errors.append('boundary:'+label+':'+type(exc).__name__+':'+str(exc))
        finally:g.add('screen_boundary_observation',time.monotonic()-start)


def finish(g,observer,wire,path,output):
    for row in g.owner_events:
        if row['priority']>=2 and 'sequence' in row:
            older=[x for x in row.get('queued_at_entry',[]) if x[0]>=2 and x[1]<row['sequence']]
            if older:g.fairness_errors.append({'kind':'nonurgent_fifo','sequence':row['sequence'],'older':older})
    write(output/'owner-events.json',g.owner_events)
    write(output/'a2-events.json',g.offers)
    write(output/'source-queues.json',g.queue_samples)
    a2=None if g.a2 is None else g.a2.telemetry()
    health={}
    for pid in sorted(g.worker_pids):
        try:os.kill(pid,0)
        except ProcessLookupError:health[str(pid)]='exited'
        else:health[str(pid)]='alive'
    modules=[]
    source=Path(os.environ['MM_SCREEN_SOURCE'])
    for name,module in sorted(sys.modules.items()):
        raw=getattr(module,'__file__',None)
        if raw:
            p=Path(raw).resolve()
            if p.is_relative_to(source):
                modules.append({'module':name,'path':str(p),'sha256':digest(p.read_bytes())})
    write(output/'runtime-module-origins.json',modules)
    gaps=[b['wall']-a['wall'] for a,b in zip(observer.rows,observer.rows[1:])]
    latest_queue=g.queue_samples[-1] if g.queue_samples else {}
    worker_attempts=list(Path(os.environ['MM_SCREEN_FIREWALL_DIR']).glob('attempt-*.jsonl'))
    child_attempts=sum(len(p.read_text().splitlines()) for p in worker_attempts)
    return {'provider_calls':0,'provider_attempts':g.provider_attempts.value+child_attempts,
        'a2':a2,'owner_unresolved_accepted_futures':len(g.outstanding),
        'owner_thread_alive':g.owner.thread.is_alive() if g.owner else None,
        'owner_fairness_errors':g.fairness_errors,'writer_close':g.writer_close,
        'worker_processes':health,'instrumentation_errors':g.observation_errors,
        'dropped_samples':g.timing_dropped,'periodic_samples':len(observer.rows),
        'measurement_gap_peak_seconds':max(gaps,default=None),
        'measurement_gaps_seconds':gaps,'boundary_acquisition_gaps':{
            k:v['acquisition_gap'] for k,v in g.mature.items()},
        'boundaries_captured':sorted(g.mature),'source_queue_samples':len(g.queue_samples),
        'source_queue_last':latest_queue,'source_offered_frames':wire.sent,
        'native_rolling_evictions':{'a2':(a2 or {}).get('counters',{}).get('evicted_events',0),
            'arbiter':dict(g.runtime.counters).get('evicted_events',0) if g.runtime else 0},
        'observer_cost_is_not_subtracted':True}
