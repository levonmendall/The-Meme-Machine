"""Finite Phase 2A verification; no material workload or qualification change."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASE = 'b11b16fbdc4ea0312b2c6f51de37e4d68e1f2da1'
HERE = Path(__file__).resolve().parent

def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()

def write(output,name,row):
    (output/name).write_text(json.dumps(row,indent=2,sort_keys=True)+'\n')

def prerequisite(output):
    sys.path.insert(0,str(ROOT))
    spec=importlib.util.spec_from_file_location('lane_a_prerequisite',
        HERE/'native_completion_prerequisite.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=unittest.TextTestRunner(verbosity=2,stream=sys.stdout).run(
        unittest.defaultTestLoader.loadTestsFromModule(module))
    row=dict(module.EVIDENCE,tested_sha=git('rev-parse','HEAD'),base=BASE,
        tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        skipped=len(result.skipped))
    write(output,'M1_PREREQUISITE.json',row)
    print('PHASE2_M1 '+json.dumps(row,sort_keys=True),flush=True)
    return result.wasSuccessful() and not result.skipped

def command(output,name,args):
    result=subprocess.run(args,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (output/(name+'.log')).write_text(result.stdout)
    print(result.stdout,flush=True)
    row=dict(command=args,exit_code=result.returncode)
    count=re.search(r'Ran (\d+) tests?',result.stdout)
    if count:row['tests']=int(count.group(1))
    for key in ('failures','errors','skipped'):
        count=re.search(key+r'=(\d+)',result.stdout)
        row[key]=int(count.group(1)) if count else 0
    return row

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--prerequisite-only',action='store_true')
    parser.add_argument('--focused-only',action='store_true')
    parser.add_argument('--focused-gates-only',action='store_true')
    args=parser.parse_args();output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    summary=dict(base_sha=BASE,base_tree=git('rev-parse',BASE+'^{tree}'),
        treatment_sha=git('rev-parse','HEAD'),treatment_tree=git('rev-parse','HEAD^{tree}'),
        branch=os.getenv('GITHUB_REF_NAME'),python=sys.version,sqlite=sqlite3.sqlite_version,
        platform=platform.platform(),paper_only=True,material_executions=0,stage_e='RED',
        stage_f='NOT_STARTED',housekeeping_carried=False)
    from static_verify import verify
    summary['static']=verify(output)
    summary['prerequisite_pass']=prerequisite(output)
    if not summary['prerequisite_pass']:
        summary['result']='M1_INTEGRATION_CONFLICT'
    elif args.prerequisite_only:
        summary['result']='BASE_NATIVE_PREREQUISITE_GREEN'
    else:
        code="""import json,sys,unittest
from tests import test_owner_admission_phase2 as module
result=unittest.TextTestRunner(verbosity=2,stream=sys.stdout).run(unittest.defaultTestLoader.loadTestsFromModule(module))
with open(sys.argv[1],'w') as handle:json.dump(module.EVIDENCE,handle,indent=2,sort_keys=True)
print('PHASE2_MATRIX '+json.dumps(module.EVIDENCE,sort_keys=True),flush=True)
sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
"""
        summary['matrix']=command(output,'matrix',[sys.executable,'-c',code,str(output/'MATRIX.json')])
        summary['result']='FOCUSED_GREEN' if summary['matrix']['exit_code']==0 else 'FOCUSED_BLOCKED'
        if not args.focused_only and summary['matrix']['exit_code']==0:
            affected=[
                'tests.test_production_maintenance_arbiter',
                'tests.test_solana_evidence_service_runtime',
                'tests.test_stagee24_maintenance_integrity',
                'tests.test_solana_checkpoint_owner','tests.test_checkpoint_handoff',
                'tests.test_archive_pipeline','tests.test_solana_evidence_retention',
                'tests.test_retention_outcomes','tests.test_run381_retention_progress',
                'tests.test_run381_archive_scheduling','tests.test_run381_maintenance_overlap',
                'tests.test_run372_large_frame_runtime','tests.test_run373_dispatch_throughput',
                'tests.test_run376_dispatch_pressure','tests.test_run379_transport_backpressure',
                'tests.test_run380_atomic_frame','tests.test_stagee19_maintenance_batch_fairness']
            summary['affected']=command(output,'affected',[sys.executable,'-m','unittest',*affected,'-v'])
            summary['m1_focused']=command(output,'m1-focused',[sys.executable,'-m','unittest',
                'tests.test_m1_maintenance_completion','-v'])
            summary['resource']=command(output,'resource',[sys.executable,'-m','tests.resource_check'])
            frozen_tests=["certification.tests.test_cleanup_recovery.CleanupRecoveryTests.test_frozen_original_and_combined_workload_bytes","certification.tests.test_combined_observer.OverlapObservationTests.test_original_workload_is_still_frozen","certification.tests.test_stagee24_environment.QualificationEnvironmentTests.test_new_observation_identity_and_original_workload_are_both_bound","certification.tests.test_stagee27_cohort_wiring.FixedCohortWiringTests.test_matrix_is_exactly_the_existing_frozen_cohort","certification.tests.test_stagee25_promotion.ArtifactPreflightTests.test_aggregate_label_without_environment_and_raw_trials_is_rejected","certification.tests.test_stagee25_promotion.ArtifactPreflightTests.test_raw_machinery_recomputation_rejects_a_forged_green_summary"]
            summary['frozen_integrity']=command(output,'frozen-integrity',[sys.executable,'-m',
                'unittest',*frozen_tests,'-v'])
            green=all(summary[key]['exit_code']==0 for key in ('affected','m1_focused','resource','frozen_integrity'))
            summary['result']='FOCUSED_GATES_GREEN' if green else 'FOCUSED_GATES_BLOCKED'
            if not args.focused_gates_only and green:
                summary['deterministic']=command(output,'deterministic',[sys.executable,'-m',
                    'unittest','discover','-v'])
                summary['result']='DETERMINISTIC_GREEN' if summary['deterministic']['exit_code']==0 else 'DETERMINISTIC_BLOCKED'
            elif not args.focused_gates_only:
                summary['deterministic']=dict(status='NOT_RUN_FOCUSED_GATE_BLOCKED')
    write(output,'RESULTS.json',summary)
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}
    write(output,'FILE_HASHES.json',hashes)
    print('PHASE2_FILE_HASHES '+json.dumps(hashes,sort_keys=True),flush=True)
    print('PHASE2_RESULTS '+json.dumps(summary,sort_keys=True),flush=True)
    return 0 if summary['result'] in ('BASE_NATIVE_PREREQUISITE_GREEN','FOCUSED_GREEN','FOCUSED_GATES_GREEN','DETERMINISTIC_GREEN') else 1

if __name__=='__main__':
    raise SystemExit(main())
