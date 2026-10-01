"""Finite M1 old/new evidence using identical regression inputs; paper only."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE = 'dc08f9064cf5e37b63f383f52aa709d0afc1723f'
FOCUSED = 'tests.test_m1_maintenance_completion'
AFFECTED = [
    'tests.test_production_maintenance_arbiter',
    'tests.test_retention_outcomes',
    'tests.test_run381_retention_progress',
    'tests.test_run381_archive_scheduling',
    'tests.test_run381_maintenance_overlap',
    'tests.test_archive_pipeline',
    'tests.test_solana_evidence_retention',
    'tests.test_solana_retention_working_set',
    'tests.test_stagee24_maintenance_integrity',
    'tests.test_solana_checkpoint_owner',
    'tests.test_solana_evidence_service_runtime',
]
def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
def run(name, command, output, cwd=ROOT):
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    (output / (name + '.log')).write_text(result.stdout)
    print(result.stdout, flush=True)
    return dict(command=command, exit_code=result.returncode)
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    patch = subprocess.check_output(['git', 'diff', '--binary', BASE, 'HEAD'], cwd=ROOT)
    (output / 'repair.patch').write_bytes(patch)
    summary = dict(
        production_base=BASE, production_tree=git('rev-parse', BASE + '^{tree}'),
        sha=git('rev-parse', 'HEAD'), tree=git('rev-parse', 'HEAD^{tree}'),
        branch=os.getenv('GITHUB_REF_NAME'), python=sys.version,
        platform=platform.platform(), sqlite=sqlite3.sqlite_version,
        changed_files=git('diff', '--name-only', BASE, 'HEAD').splitlines(),
        paper_only=True, material_executions=0, canonical_stage_e=False,
        stage_f=False, merged=False)
    old_runner = """import json,os,sys,unittest
from tests import test_m1_maintenance_completion as test
suite=unittest.TestSuite([test.M1NativeCompletionTests('test_urgent_completion_clears_decision_before_next_ordinary_admission')])
result=unittest.TextTestRunner(verbosity=2,stream=sys.stdout).run(suite)
row=dict(test.EVIDENCE, tests=result.testsRun,failures=len(result.failures),errors=len(result.errors))
with open(os.environ['M1_OLD_JSON'],'w') as handle:json.dump(row,handle,indent=2,sort_keys=True)
sys.exit(0 if result.wasSuccessful() else 1)
"""
    with tempfile.TemporaryDirectory(prefix='m1-baseline-') as td:
        old = Path(td) / 'old'
        subprocess.run(['git', 'worktree', 'add', '--detach', str(old), BASE],
                       cwd=ROOT, check=True)
        shutil.copyfile(ROOT / 'tests/test_m1_maintenance_completion.py',
                        old / 'tests/test_m1_maintenance_completion.py')
        env = dict(os.environ, M1_OLD_JSON=str(output / 'old-repro.json'))
        result = subprocess.run([sys.executable, '-c', old_runner], cwd=old, env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (output / 'old-repro.log').write_text(result.stdout)
        print(result.stdout, flush=True)
    old_row = json.loads((output / 'old-repro.json').read_text())
    summary['old'] = dict(exit_code=result.returncode, tests=old_row['tests'],
                         failures=old_row['failures'], errors=old_row['errors'])
    old_confirmed = (
        result.returncode == 1 and old_row['tests'] == 1 and
        old_row['failures'] == 1 and old_row['errors'] == 0 and
        old_row['after_interruption']['pending'] is not None and
        old_row['first_error']['message'] == 'evidence_background_yield' and
        old_row['next_error']['message'] == 'maintenance_decision_in_flight' and
        old_row['after_interruption']['archive_progress'] == [512, 512] and
        old_row['after_interruption']['hot'] == 1288 and
        old_row['after_interruption']['integrity'] == 'ok' and
        not old_row['after_interruption']['transaction_open'] and
        old_row['provider_calls'] == 0 and old_row['all_accepted_futures_done'])
    summary['old_fails_confirmed'] = old_confirmed
    if old_confirmed:
        summary['focused'] = run('new-focused', [sys.executable, '-m', 'unittest',
                                    FOCUSED, '-v'], output)
        summary['affected'] = run('affected', [sys.executable, '-m', 'unittest',
                                    *AFFECTED, '-v'], output)
        summary['deterministic'] = run('deterministic', [sys.executable, '-m',
                                    'unittest', 'discover', '-v'], output)
        summary['resource'] = run('resource', [sys.executable, '-m',
                                    'tests.resource_check'], output)
    passed = old_confirmed and all(summary.get(key, {}).get('exit_code') == 0
                                  for key in ('focused', 'affected', 'resource'))
    summary['result'] = 'OLD_FAILS_NEW_PASSES' if passed else 'VERIFICATION_INCOMPLETE'
    write(output / 'RESULTS.json', summary)
    print('M1_VERIFICATION ' + json.dumps(summary, sort_keys=True), flush=True)
    return 0 if passed else 1
if __name__ == '__main__':
    raise SystemExit(main())
