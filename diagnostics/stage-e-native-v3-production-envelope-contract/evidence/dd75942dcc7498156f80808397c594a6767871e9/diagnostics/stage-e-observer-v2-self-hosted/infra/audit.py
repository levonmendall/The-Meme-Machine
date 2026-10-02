"""Pretrial proofs using pure construction and infrastructure probes, no replay."""
import ast
import concurrent.futures
from contextlib import ExitStack
import json
import multiprocessing
from pathlib import Path
import socket
import threading
import time
from unittest.mock import patch
import bound_runtime as bound
from core import BASE,INFRA,REAL_NS,COHORT,MODES,file_sha,persist


def child_clock_probe():
    # This external probe runs no candidate function, frame, DB or service.
    return dict(pid=__import__('os').getpid(),clock=bound.CLOCK.sample(),
        isolated=__import__('sys').flags.isolated,no_site=__import__('sys').flags.no_site,
        provider_attempts=bound.PROVIDER_ATTEMPTS,origin_receipt=bound.receipt('probe'))


def differential_proof():
    import workload
    from certification import combined_observer as qualification
    traces={};optional={}
    class Reader:
        def __init__(self,trace):self.trace=trace
        def execute(self,sql):
            self.trace.append(['reader',sql]);return [('counter',1)] if sql.startswith('SELECT') else []
        def close(self):self.trace.append(['close'])
    class Control:
        def __init__(self):
            self.lock=threading.Lock();self.batching_phase=1;self.checkpoint_phase=0
            self.reader_phase=0;self.tail_pending=0
            self.metrics=dict(burst_evidence=[{}],held_reader_cycles=0,tail_delay_cycles=0)
    for observed in (False,True):
        label='observed' if observed else 'baseline';trace=[];called=[];control=Control()
        def native(path):trace.append(['native_checkpoint']);return (0,1,1)
        def eligible(reader):called.append('native_eligible');return True
        def window(reader,path,before,sample):called.append('native_observe_window');return sample
        with patch.object(workload.sqlite3,'connect',lambda *a,**k:Reader(trace)),\
             patch.object(workload.time,'sleep',lambda seconds:trace.append(['sleep',seconds])),\
             patch.object(qualification,'eligible',eligible),patch.object(qualification,'observe_window',window):
            workload.checkpoint(control,'/pure-proof/db',native,observed)
        traces[label]=trace;optional[label]=called
        assert control.metrics['held_reader_cycles']==control.metrics['tail_delay_cycles']==1
    assert traces['baseline']==traces['observed']
    assert optional['baseline']==[]
    assert optional['observed']==['native_eligible','native_observe_window']
    tree=ast.parse((INFRA/'workload.py').read_text())
    # Lifecycle creation is gated by observed mode and recovery member, exactly
    # as the native fixed cohort, not added to the three combined members.
    observed_creation=[n for n in ast.walk(tree) if isinstance(n,ast.IfExp)
        and isinstance(n.body,ast.Call) and isinstance(n.body.func,ast.Attribute)
        and n.body.func.attr=='LifecycleObserver']
    assert len(observed_creation)==1
    assert ast.unparse(observed_creation[0].test)=="observed and params['member'] == 'recovery-1'"
    return dict(passed=True,common_checkpoint_traces=traces,qualification_calls=optional,
        lifecycle_creation_gate=ast.unparse(observed_creation[0].test),
        baseline_lifecycle_threads=0,observed_lifecycle_interval_seconds=5,
        same_worker_limits=dict(shared_decoder_and_archive_spawn_pool=2,extra_archive_workers=0),same_cohort=COHORT,
        same_pressure=dict(owner_seconds_per_frame=.165,archive_seconds_per_thousand=.36,
            additional_commit_latency_seconds=.006,cadence_us=270000,pause_frames=[800,1400],pause_seconds=8),
        common_driver='unchanged run381_pressure.run; SQLTimings and pressure monitoring are part of the same pressure driver in both modes',
        observed_only=['native qualification revision and source-completion observation bookkeeping',
            'eligible/read_current/observe_window within held snapshot',
            'native LifecycleObserver recovery thread/read-only snapshots/JSONL persistence',
            'native pure recovery assessment and observed evidence serialization'],
        measured_boundaries='Before isolated trial process startup through all four member processes, observer joins, native teardown, receipts, persistence and helper termination',
        no_source_frames_released=True,no_candidate_service_started=True)


def semantic_audit():
    source=BASE/'assembly/source'
    service_tree=ast.parse((source/'meme_machine/solana_evidence_service.py').read_bytes())
    pools=[n for n in ast.walk(service_tree) if isinstance(n,ast.Call)
        and isinstance(n.func,ast.Name) and n.func.id=='ProcessPoolExecutor']
    assert len(pools)==1
    assert ast.unparse(pools[0])=="ProcessPoolExecutor(max_workers=STREAM_DECODE_WORKERS, mp_context=multiprocessing.get_context('spawn'))"
    worker_counts=[n for n in ast.walk(service_tree) if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='STREAM_DECODE_WORKERS' for t in n.targets)]
    assert len(worker_counts)==1 and ast.literal_eval(worker_counts[0].value)==2
    archive_submissions=[n for n in ast.walk(service_tree) if isinstance(n,ast.Call)
        and ast.unparse(n.func)=='decoder_pool.submit' and n.args
        and ast.unparse(n.args[0])=='EvidenceWriter.prepare_and_write_archive']
    assert len(archive_submissions)==1
    selected=list((source/'meme_machine').glob('*.py'))
    selected += [source/name for name in [
        'certification/run381_pressure.py','certification/combined_pressure.py',
        'certification/combined_observer.py','certification/cleanup_recovery.py',
        'certification/lifecycle_capacity.py','certification/pressure_diagnostics.py',
        'tests/test_run380_production_pressure.py','tests/test_run373_dispatch_throughput.py',
        'tests/evidence_ipc_harness.py']]
    consumers=[];files={}
    for path in selected:
        tree=ast.parse(path.read_bytes());name=str(path.relative_to(source));files[name]=file_sha(path)
        aliases={}
        for n in ast.walk(tree):
            if isinstance(n,ast.Import):
                for a in n.names:
                    if a.name in ('time','datetime'):aliases[a.asname or a.name]=a.name
            if isinstance(n,ast.ImportFrom) and n.module in ('time','datetime'):
                for a in n.names:aliases[a.asname or a.name]=n.module+'.'+a.name
        for n in ast.walk(tree):
            if isinstance(n,ast.Call):expression=ast.unparse(n.func)
            elif isinstance(n,ast.Attribute):expression=ast.unparse(n)
            else:continue
            base=expression.split('.')[0]
            if base not in aliases:continue
            resolved=aliases[base]+expression[len(base):]
            if resolved.startswith('datetime.') and resolved.endswith(('.now','.utcnow','.today')):
                raise ValueError('unprojected_calendar_consumer:'+name+':'+str(n.lineno))
            if resolved.startswith('time.'):
                method=resolved[5:]
                domains={'time':'projected wall','time_ns':'projected wall nanoseconds',
                    'monotonic':'projected semantic monotonic','monotonic_ns':'projected semantic monotonic nanoseconds',
                    'sleep':'real operating-system wait','thread_time_ns':'real thread CPU',
                    'perf_counter':'real elapsed measurement','perf_counter_ns':'real elapsed measurement'}
                if method not in domains:
                    if isinstance(n,ast.Call):raise ValueError('unclassified_clock_consumer:'+resolved+':'+name)
                    continue
                consumers.append(dict(file=name,line=n.lineno,consumer=resolved,domain=domains[method]))
            elif resolved.startswith('datetime.'):
                consumers.append(dict(file=name,line=n.lineno,consumer=resolved,domain='pure input timestamp parsing'))
    return dict(version='semantic-clock-and-bootstrap-audit-v1',passed=True,
        source_files=files,consumers=consumers,actual_pool_expression=ast.unparse(pools[0]),
        actual_pool_workers=2,archive_uses_same_pool=True,extra_workload_pools=0,
        setup='Semantic wall 1800000000 and monotonic 100 remain frozen until first source-data release, independently for each member.',
        activation='Shared mmap anchor stores real monotonic_ns exactly once immediately before first data return; subscription ACKs do not activate.',
        projection='Integer nanoseconds from real monotonic_ns; both semantic domains share the same immutable anchor.',
        headroom='All post-release decompression, observer overhead, real sleeps, pauses, scheduler delays, backpressure and maintenance consume aging/deadline headroom.',
        economic_timestamps='Immutable v2 fixture event and block bytes; no receive-time, trial-specific, or pause retiming.',
        scheduler='BaseEventLoop.time, all standard-library time module bindings and clock aliases, including late imports, use captured real functions. Candidate consumers receive the projected functions before import. OS sleeps remain real.',
        children='The exact S service shares two spawn workers between decoder and archive jobs. Both workers and the resource tracker enter the external isolated bootstrap before candidate imports or native probes. No extra archive pool is created. The separate pure fork probe proves inheritance capability and is not a workload worker.',
        cache='-I -S -B plus a verified non-existing -X pycache_prefix; finder compiles approved source bytes and rejects sourceless/cached origins.',
        network='Kernel network namespace without interfaces; Python audit blocks and counts IP connection/bind/send and DNS attempts, preserves Unix IPC.',
        qualification_reads='Native eligible/read_current/observe_window and LifecycleObserver use read-only operations; they never supply workload authority.',
        original_driver_timestamps='Original PreservedWire and run381 Wire are bypassed by external TapeWire; no retimer function executes.',
        started_trials=0,started_members=0)


def runtime_proof():
    output=Path(bound.PARAMS['output'])
    assert bound.CLOCK.anchor()==0
    assert time.time()==1800000000 and time.monotonic()==100
    with concurrent.futures.ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as p:
        frozen=p.submit(child_clock_probe).result(timeout=30)
        assert frozen['clock']['wall']==1800000000 and frozen['clock']['monotonic']==100
        anchor=bound.CLOCK.activate();time.sleep(.03)
        active=p.submit(child_clock_probe).result(timeout=30)
        assert active['clock']['anchor_real_monotonic_ns']==anchor
        assert active['clock']['wall']>1800000000 and active['clock']['monotonic']>100
    with concurrent.futures.ProcessPoolExecutor(max_workers=1,initializer=bound.fork_initializer) as p:
        inherited=p.submit(child_clock_probe).result(timeout=30)
        assert inherited['clock']['anchor_real_monotonic_ns']==anchor
    a,b=socket.socketpair()
    try:a.sendall(b'pure-clock-proof');assert b.recv(64)==b'pure-clock-proof'
    finally:a.close();b.close()
    assert not bound.PROVIDER_ATTEMPTS
    differential=differential_proof();semantic=semantic_audit()
    persist(output/'DIFFERENTIAL_PROOF.json',differential)
    persist(output/'SEMANTIC_CLOCK_AUDIT.json',semantic)
    persist(output/'BOOTSTRAP_PROOF.json',dict(version='external-child-bootstrap-proof-v1',
        passed=True,frozen_spawn=frozen,active_spawn=active,inherited_fork=inherited,
        unix_ipc_allowed=True,provider_attempts=[],source_frames=0,candidate_services=0,
        started_trials=0,started_members=0))
