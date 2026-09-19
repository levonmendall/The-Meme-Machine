"""Read-only preflight: do not overlap existing market jobs or stale lane heads."""
import json
import os
from pathlib import Path
import subprocess
from urllib.request import Request,urlopen
from certification.run import manifest,ROOT,atomic

LIVE_NAMES={'pons-selective-market-test','solana-dlmm-independent-v1',
            'pump-acceleration-natural-prospective','robinhood-ramses-extended-test',
            'four-lane-certification'}

def main():
    output=Path('certification-preflight.json')
    spec=manifest();lines=subprocess.check_output(['git','ls-remote','origin','refs/heads/*'],cwd=ROOT,text=True).splitlines()
    heads={ref.removeprefix('refs/heads/'):sha for sha,ref in (line.split() for line in lines)}
    changed=[lane for lane,row in spec['lanes'].items() if heads.get(row['source_branch'])!=row['source_sha']]
    active=[]
    token=os.environ.get('GITHUB_TOKEN')
    if not token:raise RuntimeError('github_read_token_required_for_contention_preflight')
    for state in ('in_progress','queued'):
        for page in range(1,11):
            url=f'https://api.github.com/repos/{spec["repository"]}/actions/runs?status={state}&per_page=100&page={page}'
            req=Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
            with urlopen(req,timeout=30) as response:data=json.load(response)
            runs=data.get('workflow_runs',[])
            for row in runs:
                if row['name'] in LIVE_NAMES and str(row['id'])!=os.environ.get('GITHUB_RUN_ID'):
                    active.append(dict(id=row['id'],name=row['name'],status=row['status']))
            if len(runs)<100:break
        else:raise RuntimeError('active_run_pagination_bound')
    result=dict(lane_heads_changed=changed,conflicting_market_runs=active,passed=not changed and not active)
    atomic(output,result);print(json.dumps(result))
    if not result['passed']:raise SystemExit(1)

if __name__=='__main__':main()
