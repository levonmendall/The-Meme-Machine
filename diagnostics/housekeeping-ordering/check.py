"""Focused tests are a mandatory gate; no material execution in this file."""
import argparse, hashlib, json, os, re, subprocess, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent

TARGETS=(
    'tests.test_housekeeping_ordering',
    'tests.test_retention_outcomes',
    'tests.test_solana_evidence_retention',
    'tests.test_stagee19_maintenance_batch_fairness',
    'tests.test_stagee21_retention_access_path',
    'tests.test_production_maintenance_arbiter.AdapterCorrectionsTests',
    'tests.test_production_maintenance_arbiter.HousekeepingRestartTests',
)
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args()
    root=Path(a.root);proof=json.loads((root/'STATIC_VERIFICATION.json').read_text())
    assert proof['verified'] and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert not (root/'execution-ledger.jsonl').exists()
    runs=(
        ('control-reproduction',root/'worktrees/control',
         [sys.executable,'-m','unittest','-v',
          'tests.test_housekeeping_ordering.PrefixTests.test_control_reproduces_768_retirements_and_no_housekeeping']),
        ('treatment-focused',root/'worktrees/treatment',
         [sys.executable,'-m','unittest','-v',*TARGETS]),
        ('resource',root/'worktrees/treatment',[sys.executable,'-m','tests.resource_check']),
    )
    records=[]
    for name,cwd,cmd in runs:
        path=root/(name+'.log')
        with path.open('w') as stream:
            result=subprocess.run(cmd,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,timeout=180)
        text=path.read_text();count=re.search(r'Ran (\d+) tests in',text)
        records.append(dict(name=name,returncode=result.returncode,
            tests=None if count is None else int(count[1]),
            log_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        print('CHECK '+json.dumps(records[-1]),flush=True)
        print('\n'.join(text.splitlines()[-8:]),flush=True)
        if result.returncode:
            (root/'SAFETY_GATE.json').write_text(json.dumps(dict(passed=False,
                checks=records,material_executions=0,budget_consumed=4),indent=2)+'\n')
            raise SystemExit(result.returncode)
    gate=dict(passed=True,checks=records,diagnostic_sha=proof['diagnostic_sha'],
        patch_sha256=proof['patch_sha256'],tests_sha256=proof['tests_sha256'],
        material_executions=0,budget_consumed=4)
    (root/'SAFETY_GATE.json').write_text(json.dumps(gate,indent=2)+'\n')
    print('SAFETY_TESTS_PASSED '+json.dumps(gate,sort_keys=True),flush=True)

if __name__=='__main__':main()
