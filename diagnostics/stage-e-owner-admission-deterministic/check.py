"""Run only the finite native completion prerequisite; no material continuation."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = 'dc08f9064cf5e37b63f383f52aa709d0afc1723f'
EVIDENCE_BASE = '0b3bca8d8cf09dfdad924d3dc68e5cc0f10e7e45'
BRANCH = 'diagnostics/stage-e-owner-admission-deterministic-20261001'
PREFIX = 'diagnostics/stage-e-owner-admission-deterministic/'

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()

def manifest(ref):
    return {line.split('\t', 1)[1]: line.split('\t', 1)[0]
            for line in git('ls-tree', '-r', ref).splitlines()}

def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    head = git('rev-parse', 'HEAD')
    current, production, preserved = manifest(head), manifest(BASE), manifest(EVIDENCE_BASE)
    assert all(current.get(path) == identity for path, identity in production.items())
    assert all(current.get(path) == identity for path, identity in preserved.items())
    changed = git('diff', '--name-only', EVIDENCE_BASE, head).splitlines()
    assert all(path.startswith(PREFIX) or
               path == '.github/workflows/owner-admission-deterministic.yml'
               for path in changed), changed
    request = json.loads((HERE / 'execution-request.json').read_text())
    assert request == dict(
        authorization='OWNER_ADMISSION_DESIGN_APPROVED_FOR_DETERMINISTIC_IMPLEMENTATION',
        kind='native_completion_prerequisite_only', diagnostic_branch=BRANCH,
        production_base=BASE, material_executions=0,
        material_budget_consumed=6, material_budget_unused=0,
        pressure_workloads=False, m1_repair=False, fixture_revision=2)
    patch = subprocess.check_output(['git', 'diff', '--binary', EVIDENCE_BASE, head], cwd=ROOT)
    (args.output / 'diagnostic.patch').write_bytes(patch)
    static = dict(
        production_base=BASE, production_tree=git('rev-parse', BASE + '^{tree}'),
        evidence_base=EVIDENCE_BASE, diagnostic_branch=BRANCH, diagnostic_sha=head,
        diagnostic_tree=git('rev-parse', 'HEAD^{tree}'), changed_files=changed,
        protected_production_files=len(production), protected_evidence_files=len(preserved),
        protected_blobs_and_modes_unchanged=True, production_runtime_changed=False,
        gate_implemented=False, treatment_runtime_tree=None,
        housekeeping_patch_applied=False, canonical_workflows_unchanged=True,
        material_executions=0, budget=dict(consumed=6, unused=0, ceiling=6),
        patch_sha256=hashlib.sha256(patch).hexdigest())
    write(args.output / 'STATIC_VERIFICATION.json', static)
    write(args.output / 'ENVIRONMENT.json', dict(
        python=sys.version, platform=platform.platform(), sqlite=sqlite3.sqlite_version,
        run_id=os.getenv('GITHUB_RUN_ID'), attempt=os.getenv('GITHUB_RUN_ATTEMPT'),
        command='python diagnostics/stage-e-owner-admission-deterministic/check.py --output <directory>'))
    print('OWNER_ADMISSION_STATIC ' + json.dumps(static, sort_keys=True), flush=True)
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        'owner_admission_native_prerequisite', HERE / 'test_native_completion_prerequisite.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.NativeCompletionPrerequisiteTests)
    result = unittest.TextTestRunner(verbosity=2, failfast=True, stream=sys.stdout).run(suite)
    write(args.output / 'M1_EVIDENCE.json', module.EVIDENCE)
    print('OWNER_ADMISSION_NATIVE_EVIDENCE ' + json.dumps(module.EVIDENCE, sort_keys=True), flush=True)
    blocked_m1 = (
        bool(result.failures) and
        (module.EVIDENCE.get('first_error') or {}).get('message') == 'evidence_background_yield' and
        module.EVIDENCE.get('after_interruption', {}).get('pending') is not None and
        (module.EVIDENCE.get('next_error') or {}).get('message') == 'maintenance_decision_in_flight')
    summary = dict(
        status='BLOCKED_BY_M1' if blocked_m1 else 'NATIVE_PREREQUISITE_PASS' if result.wasSuccessful()
               else 'PREREQUISITE_FIXTURE_OR_OTHER_FAILURE',
        tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        skipped=len(result.skipped), expected_failures=len(result.expectedFailures),
        assertions_weakened=False, gate_implemented=False,
        admission_matrix='NOT_REACHED' if not result.wasSuccessful() else 'NOT_RUN',
        recovery_regression='NOT_REACHED' if not result.wasSuccessful() else 'NOT_RUN',
        material_executions=0, budget=dict(consumed=6, unused=0, ceiling=6),
        stage_e='RED', stage_f='NOT_STARTED', paper_only=True)
    write(args.output / 'RESULTS.json', summary)
    print('OWNER_ADMISSION_PREREQUISITE_RESULTS ' + json.dumps(summary, sort_keys=True), flush=True)
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in args.output.iterdir() if path.is_file()}
    hashes.update({'input:' + path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in HERE.iterdir() if path.is_file()})
    workflow = ROOT / '.github/workflows/owner-admission-deterministic.yml'
    hashes['input:workflow.yml'] = hashlib.sha256(workflow.read_bytes()).hexdigest()
    write(args.output / 'FILE_HASHES.json', hashes)
    print('OWNER_ADMISSION_FILE_HASHES ' + json.dumps(hashes, sort_keys=True), flush=True)
    return 0 if result.wasSuccessful() else 1

if __name__ == '__main__':
    raise SystemExit(main())
