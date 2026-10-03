"""Review-only CLI: no material execution command, fixture generator or runner."""
import argparse
import ast
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0,str(HERE/'harness'))
from core import CONTRACT, INFRA, S, T, canonical, file_sha, read, require, sha, stopped, workload
from binding import candidate_integrity, contract_integrity, infrastructure_identity, runtime_identity


def source_checkout():
    return Path(os.environ.get('MM_V3_CANDIDATE_CHECKOUT','/workspace/The-Meme-Machine-S')).resolve()


def static_checks():
    source = source_checkout()
    conservation = candidate_integrity(source)
    approved = contract_integrity(REPO)
    parsed = []
    for path in HERE.rglob('*.py'):
        ast.parse(path.read_bytes(),filename=str(path))
        parsed.append(path.relative_to(HERE).as_posix())
    original = ast.parse((CONTRACT/'evidence/dd75942dcc7498156f80808397c594a6767871e9/diagnostics/stage-e-observer-v2-self-hosted/infra/workload.py').read_bytes())
    stress = ast.parse((INFRA/'stress.py').read_bytes())
    predicates = ast.parse((INFRA/'stress_predicates.py').read_bytes())
    fn = lambda tree,name: next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    require(ast.dump(fn(original,'checkpoint'),include_attributes=False) ==
            ast.dump(fn(stress,'checkpoint'),include_attributes=False),'C_reader_tail_interference_changed')
    require(ast.dump(fn(original,'common_valid'),include_attributes=False) ==
            ast.dump(fn(predicates,'common_valid'),include_attributes=False),'C_original_diagnostic_predicates_changed')
    production = (INFRA/'production.py').read_text()
    tree = ast.parse(production)
    prohibited = ('MeasuredServiceState','MeasuredProcessPool','run381_pressure','SQLTimings',
                  'COMMIT_LATENCY_SECONDS','OWNER_SECONDS_PER_FRAME','ARCHIVE_SECONDS_PER_THOUSAND')
    require(not any(name in production for name in prohibited),'synthetic_profile_in_A_B')
    require(not any(isinstance(n,ast.Call) and ast.unparse(n.func)=='time.sleep' for n in ast.walk(tree)),
            'synthetic_sleep_in_A_B')
    state = next(n for n in ast.walk(tree) if isinstance(n,ast.ClassDef) and n.name=='State')
    require({n.name for n in state.body if isinstance(n,ast.FunctionDef)} == {'__init__','close'},
            'A_B_native_source_archive_commit_or_retirement_override')
    service = ast.parse((source/'meme_machine/solana_evidence_service.py').read_bytes())
    pools = [n for n in ast.walk(service) if isinstance(n,ast.Call) and ast.unparse(n.func)=='ProcessPoolExecutor']
    require(len(pools)==1 and ast.unparse(pools[0]) ==
            "ProcessPoolExecutor(max_workers=STREAM_DECODE_WORKERS, mp_context=multiprocessing.get_context('spawn'))",'native_worker_limits')
    require('measured_contention=True' in (INFRA/'stress.py').read_text(), 'C_contention_removed')
    for text in ('self.sent in (800,1400)','self.pause_started+8','time.sleep(1.25)','time.sleep(.1)','time.sleep(.75)'):
        require(text in (INFRA/'stress.py').read_text(),'C_injection_removed:'+text)
    require(workload('A')['artificial_contention'] == workload('B')['artificial_contention'], 'A_B_delay_bindings_differ')
    review_workflow = REPO/'.github/workflows/stagee-native-v3-executable-review.yml'
    require('workflow_dispatch:' in review_workflow.read_text() and 'execute.py' not in review_workflow.read_text(),
            'review_workflow_material_entrypoint')
    template = HERE/'workflows/stagee-native-v3-material.yml.preview'
    require('NOT AUTHORIZED / PREVIEW ONLY' in template.read_text() and 'if: ${{ false }}' in template.read_text(),
            'material_workflow_preview_guard')
    return dict(candidate=conservation,approved_contract=approved,parsed_sources=parsed,
        production_injection_exclusion=True,C_exact_checkpoint_AST=True,C_exact_common_valid_AST=True,
        exact_native_two_worker_pool=True,source_frames_released=0,stage_e='RED',stage_f='NOT STARTED')


def check():
    evidence = HERE/'evidence';evidence.mkdir(exist_ok=True)
    before = static_checks()
    stream = io.StringIO()
    loader = unittest.TestLoader()
    suites = [loader.discover(str(HERE/'tests'),pattern='test_*.py')]
    # The entire existing 55-test Astra contract suite is finite and static.
    # Its source locator is adjusted in memory only; approved files stay intact.
    sys.path.insert(0,str(CONTRACT))
    import static_validation
    static_validation.SOURCE = source_checkout()
    suites.append(unittest.TestLoader().discover(str(CONTRACT),pattern='test_*.py'))
    result = unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.TestSuite(suites))
    after = static_checks()
    require(before==after,'source_changed_during_tests')
    log = stream.getvalue()
    (evidence/'unit_validation.log').write_text(log)
    row = dict(version='v3-executable-review-tests',python=sys.version.split()[0],tests_run=result.testsRun,
        failed=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        passed=result.wasSuccessful(),source_frames_released=0,
        capacity_workload_executed=False,observer_campaign_executed=False,synthetic_stress_executed=False,
        provider_workload_executed=False,stage_e='RED',stage_f='NOT STARTED',
        static=after,infrastructure=infrastructure_identity())
    (evidence/'test_results.json').write_bytes(canonical(row)+b'\n')
    print(json.dumps({k:row[k] for k in ('tests_run','passed','failed','errors','skipped','source_frames_released')}))
    require(result.wasSuccessful(),'review_tests_failed')
    return row


def inspect_environment():
    from attest import inspect
    snapshot = None
    errors = []
    try:
        snapshot = inspect([HERE])
    except Exception as exc:
        errors.append(type(exc).__name__+':'+str(exc))
    runtime = None
    try:
        runtime = runtime_identity(source_checkout())
    except Exception as exc:
        errors.append(type(exc).__name__+':'+str(exc))
    # Inspection is evidence about the review executor, never allocation proof.
    import importlib.metadata
    import platform
    observed_runtime=dict(python=platform.python_version(),websockets=importlib.metadata.version('websockets'),
                          sqlite=__import__('sqlite3').sqlite_version,machine=platform.machine())
    row = dict(version='v3-nonmaterial-review-executor-inspection',snapshot=snapshot,runtime=runtime,
        observed_runtime=observed_runtime,
        inspection_errors=errors,authenticated_allocation_proof_present=False,
        production_envelope_admitted=False,**stopped('review executor only; no signed dedicated allocation capability'))
    evidence=HERE/'evidence';evidence.mkdir(exist_ok=True)
    (evidence/'environment_inspection.json').write_bytes(canonical(row)+b'\n')
    print(json.dumps(dict(inspection_errors=errors,production_envelope_admitted=False,source_frames_released=0)))
    return row


def package_manifest():
    require(not any(p.is_symlink() or p.suffix in ('.pyc','.pyo') for p in HERE.rglob('*')),
            'review_package_symlink_or_cached_executable')
    files = [p for p in HERE.rglob('*') if p.is_file() and p.name!='package-manifest.json']
    files.append(REPO/'.github/workflows/stagee-native-v3-executable-review.yml')
    rows = [dict(path=p.relative_to(REPO).as_posix(),bytes=p.stat().st_size,sha256=file_sha(p),
                 mode='100755' if p.stat().st_mode & 0o111 else '100644') for p in sorted(files)]
    return dict(version='stage-e-native-v3-executable-review-package',self_hash_excluded=True,artifacts=rows,
                candidate_sha=S,candidate_tree=T,approved_contract_commit=__import__('core').CONTRACT_COMMIT,
                approved_contract_manifest_sha256=__import__('core').CONTRACT_MANIFEST_SHA,
                execution_authorized=False,source_frames_released=0,stage_e='RED',stage_f='NOT STARTED')


def build():
    from declaration import preview
    from ledger import fresh_campaign
    from verify import gate_status
    evidence = read(HERE/'evidence/environment_inspection.json')
    snapshot = evidence['snapshot'] or {}
    runtime = evidence['runtime'] or {'identity_error':evidence['inspection_errors']}
    environment = dict(runtime_dependency_identities=runtime,
                       observed_constraints={k:snapshot.get(k) for k in ('boot_id','hostname','cpu','topology','affinity','cgroup')},
                       allocated_resources='UNATTESTED_REVIEW_EXECUTOR')
    d = preview('B',fresh_campaign('B'),executor=dict(executor_id='review-only-unattested',
        boot_id=snapshot.get('boot_id'),hostname=snapshot.get('hostname'),scope_pid=snapshot.get('scope_pid')),
        environment=environment,workflow=dict(event='local_static_deterministic',attempt=1,run_id='EXECUTABLE_REVIEW_ONLY'),
        paths={'future_execution_paths':'NOT_BOUND_NOT_AUTHORIZED'})
    (HERE/'PREDECLARATION_PREVIEW.json').write_bytes(canonical(d)+b'\n')
    ledger = dict(version='v3-preview-only-ledger',campaign=d['campaign'],execution_authorized=False,
        slots=[dict(row,status='UNUSED',started=False,elapsed_ns=None) for row in d['trials']],
        actual_slots_reserved=False,retries=0,replacements=0,material_trials_started=0,
        v2_history='OBSERVER_V2: INVALID_PAIR',historical_elapsed_carried_forward=False,acceptance_credit=False)
    (HERE/'LEDGER_PREVIEW.json').write_bytes(canonical(ledger)+b'\n')
    (HERE/'GATE_STATUS.json').write_bytes(canonical(dict(gates=gate_status(),stage_e='RED',stage_f='NOT STARTED'))+b'\n')
    class_bindings = {}
    for kind, module in {'A':'production.py','B':'production.py','C':'stress.py'}.items():
        spec = workload(kind)
        class_bindings[kind] = dict(contract_workload_sha256=sha(canonical(spec)),
            adapter=module,adapter_sha256=file_sha(INFRA/module),
            cohort=spec['cohort'],artificial_contention=spec['artificial_contention'],
            clock=spec['clock'],tape_binding=spec['tape_binding'],worker_limits=spec['worker_limits'],
            acceptance=spec['acceptance'] if kind!='C' else spec['overload'],
            executed=False,source_frames_released=0)
    class_bindings['A']['full_shape_prerequisites']=workload('A')['predecessor_full_shape_cases']
    class_bindings['B'].update(prerequisite=workload('B')['prerequisite'],modes=workload('B')['modes'],
        estimator=workload('B')['estimator'],strict_integer_rule='numerator_ns * 100 < denominator_ns',
        pairs=3,retries=0,replacements=0,warmups=0)
    class_bindings['C'].update(performance_failure='FAILED_DIAGNOSTIC',wrapper_stop_native_credit=False,
        capacity_credit=False,native_restart='actual C database only; zero further source frames')
    bindings=dict(version='external-native-v3-executable-bindings',candidate_sha=S,candidate_tree=T,
        contract_commit=__import__('core').CONTRACT_COMMIT,assembly_digest=__import__('core').ASSEMBLY,
        classes=class_bindings,execution_authorized=False,stage_e='RED',stage_f='NOT STARTED')
    (HERE/'EXECUTABLE_BINDINGS.json').write_bytes(canonical(bindings)+b'\n')
    identity=infrastructure_identity()
    (HERE/'source_hashes.json').write_bytes(canonical(identity)+b'\n')
    (HERE/'package-manifest.json').write_bytes(canonical(package_manifest())+b'\n')
    verify_package()
    print(json.dumps(dict(package_manifest_sha256=file_sha(HERE/'package-manifest.json'),
                          infrastructure_digest=identity['digest'],execution_authorized=False)))


def verify_package():
    expected = read(HERE/'package-manifest.json')
    require(expected == package_manifest(),'package_artifact_readback_mismatch')
    require(read(HERE/'PREDECLARATION_PREVIEW.json')['execution_authorized'] is False,'preview_authorized')
    return expected


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('check','inspect','build','verify-package','static'))
    args=p.parse_args()
    if args.command=='check':check()
    elif args.command=='inspect':inspect_environment()
    elif args.command=='build':build()
    elif args.command=='static':print(json.dumps(static_checks()))
    else:
        result=verify_package();print(json.dumps(dict(verified_artifacts=len(result['artifacts']),
                                                     package_manifest_sha256=file_sha(HERE/'package-manifest.json'))))


if __name__=='__main__':main()
