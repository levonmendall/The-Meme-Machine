"""Bounded, exact-source parallel offline prerequisites; no market launch path."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from certification.run import ROOT,atomic,git,integration_integrity,manifest,source_integrity
from certification.journal import digest


def run(worktrees,output):
    integration_integrity()
    roots=Path(worktrees).resolve();out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    barrier=out/'barrier';barrier.mkdir()
    identities=source_integrity(roots)
    env={k:v for k,v in os.environ.items() if not k.startswith(('MM_','GH_','GITHUB_'))
         and not any(s in k.upper() for s in ('TOKEN','SECRET','PRIVATE_KEY'))}
    env['PYTHONUNBUFFERED']='1'
    def suite(lane):
        log=out/(lane+'.log')
        command=[sys.executable,str(ROOT/'certification/offline_tests.py'),'--lane',lane,
            '--output',str(out/(lane+'.json')),'--barrier',str(barrier)]
        with log.open('wb') as stream:
            try:r=subprocess.run(command,cwd=roots/lane,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=300)
            except subprocess.TimeoutExpired:
                return dict(lane=lane,passed=False,boundary='suite_timeout_300_seconds')
        path=out/(lane+'.json')
        value=json.loads(path.read_text()) if path.exists() else dict(lane=lane,passed=False,boundary='missing_result')
        value.update(exit_code=r.returncode,log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
        return value
    started=time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        lanes=dict(zip(('pump','pons','meteora','ramses'),pool.map(suite,('pump','pons','meteora','ramses'))))
    unchanged=source_integrity(roots)==identities
    integration_integrity()
    good=all(row['passed'] for row in lanes.values()) and unchanged
    overlap=max(0,min(row.get('ended_at',0) for row in lanes.values())-max(row.get('started_at',0) for row in lanes.values()))
    result=dict(scope='parallel_offline_prerequisites',passed=good,
        engineering_certification='NOT_CERTIFIED',
        limitation='Component suites do not prove full production orchestration or automatic process recovery.',
        integration_sha=git('rev-parse','HEAD'),source_manifest_hash=digest(manifest()),
        lane_sources=manifest()['lanes'],source_diff_hashes=identities,
        source_unchanged_after_tests=unchanged,component_suite_overlap_seconds=overlap,
        lanes=lanes,test_counts={lane:row.get('tests_run') for lane,row in lanes.items()},started_at=started,ended_at=time.time(),natural_market_run_started=False)
    atomic(out/'result.json',result)
    print(json.dumps(dict(passed=good,engineering_certification='NOT_CERTIFIED',
        test_counts={lane:row.get('tests_run') for lane,row in lanes.items()},
        result=str(out/'result.json'))),flush=True)
    return 0 if good else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--worktrees',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();sys.exit(run(args.worktrees,args.output))
