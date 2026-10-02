"""Static observer preflight only. Never starts or constructs a pressure trial."""
import ast
import hashlib
import json
import os
import platform
import resource
import socket
import sys
from pathlib import Path

ASSEMBLY = Path('/workspace/observer-work/assembly')
SOURCE = ASSEMBLY / 'source'
EXPECTED_DIGEST = '08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659'
OUT = Path('/workspace/observer-work/package')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def write(name, row):
    (OUT / name).write_bytes(json.dumps(row, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n')


def main():
    OUT.mkdir(exist_ok=True)
    manifest = json.loads((ASSEMBLY / 'assembly.json').read_bytes())
    env = manifest['identity']['environment_identity']
    stdlib = Path(env['stdlib'])
    sys.path[:] = [str(SOURCE)] + [p for p in sys.path if p and
        (Path(p).resolve().is_relative_to(stdlib) or p.endswith('python312.zip'))] + [env['dependency_root']]
    sys.dont_write_bytecode = True
    from certification.stage_e_native_v2.binding import verify_assembly, environment_identity
    from certification.stage_e_native_v2.contract import validate_inputs
    from certification.stage_e_native_v2.observer import verify
    checked = verify_assembly(ASSEMBLY, EXPECTED_DIGEST)
    actual_env = environment_identity()
    assert actual_env == env, 'reviewed_execution_environment_mismatch'
    ids = validate_inputs(SOURCE)
    spec = json.loads((SOURCE / 'certification/stage_e_native_v2/observer-contract-v2.json').read_bytes())
    plan = json.loads((SOURCE / 'certification/stage_e_native_v2/plan-v2.json').read_bytes())
    occurrences = []
    for name in manifest['files']:
        if Path(name).suffix in ('.py', '.json', '.md'):
            raw = (SOURCE / name).read_text()
            for n, line in enumerate(raw.splitlines(), 1):
                if spec['workload_identity'] in line:
                    occurrences.append({'path': name, 'line': n, 'text': line.strip()})
    wire_path = 'tests/test_run380_production_pressure.py'
    wire_text = (SOURCE / wire_path).read_text()
    wire_ast = ast.parse(wire_text)
    wire = next(node for node in wire_ast.body if isinstance(node, ast.ClassDef) and node.name == 'Wire')
    recv = next(node for node in wire.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'recv')
    driver_path = 'certification/run381_pressure.py'
    driver_text = (SOURCE / driver_path).read_text()
    lines = lambda path, needles: [dict(line=n, text=line.strip()) for n, line in
        enumerate((SOURCE / path).read_text().splitlines(), 1) if any(x in line for x in needles)]
    workload_sources = {
        name: sha((SOURCE / name).read_bytes()) for name in (
            'certification/combined_pressure.py', 'certification/combined_observer.py',
            'certification/run381_pressure.py', 'certification/cleanup_recovery.py',
            'certification/lifecycle_capacity.py', 'certification/stagee24_qualification_plan.json',
            'certification/tests/fixtures/run380-production-templates.json.gz',
            wire_path, 'certification/stage_e_native_v2/clock.py',
            'certification/stage_e_native_v2/fixtures.py',
            'certification/stage_e_native_v2/fixtures/run380-v2.json',
            'certification/stage_e_native_v2/material.py',
            'certification/stage_e_native_v2/runner.py')}
    cohort = plan['retained_material_contract']
    declaration = dict(
        workload_identity=spec['workload_identity'],
        retained_plan_cohort=[dict(id=x, frames=cohort['extended_frames'] if x == 'recovery-1'
            else cohort['repeat_frames']) for x in cohort['trials']],
        cadence_us=cohort['cadence_us'], pause_frames=cohort['pause_frames'],
        pause_seconds=cohort['pause_seconds'], sample_wall_seconds=cohort['sample_wall_seconds'],
        owner_seconds_per_frame=cohort['owner_seconds_per_frame'],
        archive_seconds_per_thousand=cohort['archive_seconds_per_thousand'],
        additional_commit_latency_seconds=cohort['additional_commit_latency_seconds'],
        approved_v2_clock_domains=plan['clock_domains'], source_hashes=workload_sources,
        executable_equal_byte_driver=None, actual_frame_tape_sha256=None,
        frame_tape_status='UNBOUND: no approved executable clock/source adapter identified')
    write('WORKLOAD_BINDING.json', declaration)
    workload_hash = sha(canonical(declaration))
    blocker = dict(
        classification='IDENTITY_OR_WORKLOAD_MISMATCH', phase='STATIC_BEFORE_TRIAL_1',
        benchmark_trials_started=0, benchmark_trial_executions=0,
        no_pressure_runtime_or_Wire_recv_called=True,
        workload_identity_occurrences=occurrences,
        retained_wire_recv_ast=ast.dump(recv, include_attributes=False),
        retained_wire_clock_statements=lines(wire_path, ['self.start=time.time()', 'due=self.start', 'int(due)']),
        retained_embedded_event_retiming=lines(driver_path, ['at=int(clock', "struct.pack_into('<q'", 'retime,message']),
        native_fixed_clock_statements=lines('certification/stage_e_native_v2/fixtures.py',
            ["s['frames']", "s['clock']['wall_epoch']", 'at = int(due', 'clock.begin']),
        native_run380_declared_frames=json.loads((SOURCE /
            'certification/stage_e_native_v2/fixtures/run380-v2.json').read_bytes())['frames'],
        explanation=[
            'The observer workload identity appears only in the observer contract; no executable mapping is declared.',
            'The retained full cohort is combined-1/2/3 at 2223 frames and recovery-1 at 4445 frames.',
            'Retained Wire fixes due=start+n*.27 within each run, but start is the current real wall time; blockTime and embedded event timestamps therefore differ between sequential arms.',
            'Caching those bytes for the next arm retains older finalized/economic timestamps, conflicting with the unchanged <45 second source-lag and <240 second age bounds.',
            'The v2 pure fixture builder uses the declared fixed epoch, but its Run380 fixture has 240 frames and rejects indices >=240. It is a separate material fixture, not a complete retained-cohort driver.',
            'An external wrapper is authorized, but selecting a new full-cohort source/clock adapter without an approved binding would change the workload or clocks that the request holds immutable.'
        ], workload_descriptor_sha256=workload_hash,
        actual_workload_bytes_sha256=None, no_acceptance_credit=True)
    write('STATIC_BLOCKER.json', blocker)
    host = dict(hostname=socket.gethostname(), runner='managed-cloud /workspace; local static preflight only',
        cpu_count=os.cpu_count(), cpu_affinity=sorted(os.sched_getaffinity(0)),
        cpu_quota=Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
        memory_limit=Path('/sys/fs/cgroup/memory.max').read_text().strip(),
        memory=Path('/proc/meminfo').read_text(), cpu_info=Path('/proc/cpuinfo').read_text(),
        platform=platform.platform(), filesystem=dict(root='/workspace', mountinfo=Path('/proc/self/mountinfo').read_text(),
            block_size=os.statvfs(OUT).f_frsize, total_bytes=os.statvfs(OUT).f_blocks*os.statvfs(OUT).f_frsize),
        resource_limits={k:list(resource.getrlimit(getattr(resource,k))) for k in
            ('RLIMIT_CPU','RLIMIT_AS','RLIMIT_NOFILE','RLIMIT_NPROC')},
        execution_environment={k:os.environ.get(k) for k in
            ('PATH','LANG','LC_ALL','TZ','PYTHONDONTWRITEBYTECODE','PYTHONNOUSERSITE')},
        no_scheduler_or_cpu_tuning=True)
    write('ENVIRONMENT.json', dict(environment_identity=actual_env, host=host))
    origins=[]
    dependency_files = env['dependencies']['websockets']['files']
    for name, module in sorted(sys.modules.items()):
        raw=getattr(module, '__file__', None)
        if not raw: continue
        path=Path(raw).resolve()
        if path.is_relative_to(SOURCE):
            want=manifest['files'][path.relative_to(SOURCE).as_posix()]['sha256']; category='assembled'
        elif str(path) in dependency_files:
            want=dependency_files[str(path)]; category='approved_dependency'
        elif str(path) in env['stdlib_files']:
            want=env['stdlib_files'][str(path)]; category='standard_library'
        elif path==Path(__file__).resolve():
            want=sha(path.read_bytes()); category='external_static_diagnostics_harness'
        else: raise ValueError('foreign_static_module_origin:'+name+':'+str(path))
        assert sha(path.read_bytes())==want, name
        origins.append(dict(module=name, origin=str(path), sha256=want, category=category))
    write('STATIC_MODULE_ORIGINS.json', origins)
    identity=dict(checked['identity'], assembly_digest=EXPECTED_DIGEST,
        observer_environment_sha256=sha(canonical(dict(environment_identity=actual_env, host=host))),
        workload_descriptor_sha256=workload_hash)
    diagnostic_measurement = dict(contract=spec['version'], identity=identity,
        workload_identity=spec['workload_identity'], baseline=spec['baseline'], metric=spec['metric'],
        estimator=spec['estimator'], repetition_policy=spec['repetition_policy'], raw_pairs=[],
        numerator_ns=0, denominator_ns=0, ratio=None)
    try:
        verifier=verify(diagnostic_measurement, identity)
        raise AssertionError('incomplete_diagnostic_measurement_unexpectedly_accepted:'+str(verifier))
    except ValueError as exc:
        write('NATIVE_VERIFIER_DIAGNOSTIC.json',dict(native_module='certification.stage_e_native_v2.observer.verify',
            native_module_sha256=sha((SOURCE/'certification/stage_e_native_v2/observer.py').read_bytes()),
            invocation='verify(incomplete_diagnostic_object_with_no_raw_pairs, bound_identity)',
            result=False, exception_type=type(exc).__name__, exception=str(exc),
            formal_complete_fresh_measurement_verification=False,
            reason='No benchmark trial started; no complete measurement exists.',
            diagnostic_measurement=diagnostic_measurement))
    verify_assembly(ASSEMBLY, EXPECTED_DIGEST)
    write('STATIC_IDENTITY_VALIDATION.json',dict(candidate_sha=identity['candidate_sha'],candidate_tree=identity['candidate_tree'],
        assembly_before=EXPECTED_DIGEST, assembly_after=EXPECTED_DIGEST, exact_files=len(manifest['files']),
        input_identity=ids, environment_exact_match=True, module_origins_valid=True,
        child_process_origins=[], child_process_status='No workload child started',
        benchmark_trials_started=0, provider_calls=0, provider_attempts=0,
        candidate_runtime_modified=False, observer_samples=0, dropped_samples=0,
        qualification_or_performance_trials_executed=False))
    print(json.dumps(dict(assembly_digest=EXPECTED_DIGEST, exact_files=len(manifest['files']),
        environment_exact_match=True, workload_binding_valid=False,
        workload_descriptor_sha256=workload_hash, benchmark_trials_started=0)))


if __name__ == '__main__':
    main()
