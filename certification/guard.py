"""Read-only preflight: do not overlap existing market jobs or stale lane heads."""
import argparse
import time
import json
import os
from pathlib import Path
import subprocess
from urllib.request import Request,urlopen
from certification.run import manifest,ROOT,atomic

LIVE_NAMES={'pons-selective-market-test','solana-dlmm-independent-v1',
            'pump-acceleration-natural-prospective','robinhood-ramses-extended-test','robinhood-ramses-extended',
            'four-lane-certification'}

UNIVERSAL_READ_ONLY_JOBS={'test','tests','lint','build','inspect-retained-failure'}
REVIEWED_READ_ONLY_JOBS={'offline-prerequisites','review','deterministic','qualification','targeted'}
READ_ONLY_WORKFLOWS={
    'non-market-certification',
    'v9-handoff-continuation-nonmarket-certification',
    'v10-provider-pressure-nonmarket-certification',
    'Ramses v4 offline certification',
    'Ramses v4 launchable non-market certification',
    'v12-active-strategy-certification',
    'targeted-repair-validation',
}


def active_market_job(workflow,job,run=None,spec=None):
    if job.get('status')!='in_progress':return False
    # The pinned Pump source's legacy live-diagnostic is public-Solana-only:
    # its workflow does not inject MM_SOLANA_READ_RPC_URL and its entrypoint uses
    # MM_SOLANA_RPC_URL/public Solana. A bounded authenticated-Alchemy identity
    # probe is therefore provider-disjoint. Pin the exception to the exact reviewed
    # Pump source so any future source revision fails closed back to contention.
    if (workflow=='paper-milestone' and job.get('name')=='live-diagnostic'
            and isinstance(run,dict) and isinstance(spec,dict)
            and run.get('head_sha')==(spec.get('lanes',{}).get('pump',{}).get('source_sha'))):
        return False
    if workflow in LIVE_NAMES:return True
    raw_name=str(job.get('name') or '')
    # Preserve the long-standing CI invariant: exact generic test/lint/build jobs
    # are provider-free even inside mixed workflows such as paper-milestone.
    if raw_name in UNIVERSAL_READ_ONLY_JOBS:
        return False
    name=raw_name.split(' / ')[-1]
    # Additional reusable-workflow job names are non-market only when the wrapper
    # itself has been explicitly reviewed. Unknown wrappers continue to fail closed.
    if workflow in READ_ONLY_WORKFLOWS and name in REVIEWED_READ_ONLY_JOBS:
        return False
    return True


def fetch_json(url,token):
    req=Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
    with urlopen(req,timeout=30) as response:return json.load(response)

def check():
    output=Path('certification-preflight.json')
    spec=manifest();lines=subprocess.check_output(['git','ls-remote','origin','refs/heads/*'],cwd=ROOT,text=True).splitlines()
    heads={ref.removeprefix('refs/heads/'):sha for sha,ref in (line.split() for line in lines)}
    changed=[lane for lane,row in spec['lanes'].items() if heads.get(row['source_branch'])!=row['source_sha']]
    active=[]
    token=os.environ.get('GITHUB_TOKEN')
    if not token:raise RuntimeError('github_read_token_required_for_contention_preflight')
    for state in ('in_progress',):
        for page in range(1,11):
            url=f'https://api.github.com/repos/{spec["repository"]}/actions/runs?status={state}&per_page=100&page={page}'
            data=fetch_json(url,token)
            runs=data.get('workflow_runs',[])
            for row in runs:
                if str(row['id'])==os.environ.get('GITHUB_RUN_ID'):continue
                for job_page in range(1,11):
                    jobs=fetch_json(f'https://api.github.com/repos/{spec["repository"]}/actions/runs/{row["id"]}/jobs?filter=latest&per_page=100&page={job_page}',token).get('jobs',[])
                    active.extend(dict(id=row['id'],name=row['name'],job_id=job['id'],job_name=job['name'],status=job['status']) for job in jobs if active_market_job(row['name'],job,row,spec))
                    if len(jobs)<100:break
                else:raise RuntimeError('active_job_pagination_bound')
            if len(runs)<100:break
        else:raise RuntimeError('active_run_pagination_bound')
    result=dict(lane_heads_changed=changed,conflicting_market_runs=active,passed=not changed and not active)
    atomic(output,result);print(json.dumps(result))
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--wait-seconds',type=int,default=0);args=parser.parse_args()
    if not 0<=args.wait_seconds<=3600:raise ValueError('contention_wait_bound')
    deadline=time.monotonic()+args.wait_seconds
    while True:
        result=check()
        with Path('certification-contention-history.jsonl').open('a') as f:
            f.write(json.dumps(dict(observed_at=time.time(),**result))+'\n')
        if result['passed']:return
        if result['lane_heads_changed'] or time.monotonic()>=deadline:raise SystemExit(1)
        time.sleep(min(30,max(0,deadline-time.monotonic())))

if __name__=='__main__':main()
