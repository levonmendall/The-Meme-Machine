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
    args=parser.parse_args();output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    summary=dict(base_sha=BASE,base_tree=git('rev-parse',BASE+'^{tree}'),
        treatment_sha=git('rev-parse','HEAD'),treatment_tree=git('rev-parse','HEAD^{tree}'),
        branch=os.getenv('GITHUB_REF_NAME'),python=sys.version,sqlite=sqlite3.sqlite_version,
        platform=platform.platform(),paper_only=True,material_executions=0,stage_e='RED',
        stage_f='NOT_STARTED',housekeeping_carried=False)
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
    write(output,'RESULTS.json',summary)
    print('PHASE2_RESULTS '+json.dumps(summary,sort_keys=True),flush=True)
    return 0 if summary['result'] in ('BASE_NATIVE_PREREQUISITE_GREEN','FOCUSED_GREEN') else 1

if __name__=='__main__':
    raise SystemExit(main())
