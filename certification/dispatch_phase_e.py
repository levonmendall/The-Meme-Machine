"""Dispatch exactly once and bind canonical Phase E to the reviewed commit.

No token is logged. A durable local intent is written BEFORE the POST; ambiguous
network errors are resolved by GET-only reconciliation, never another POST.
The caller supplies the reverified fixed-cohort and final-build receipts.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

WORKFLOW='directional-six-regime-nonmarket.yml'
BRANCH='cert/autonomous-paper-machinery-20260927'
ACTIVE={'queued','in_progress','waiting','pending','requested'}


def require_sha(sha):
    if not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError('invalid_exact_sha')


def prerequisites(cohort,build,runtime,plan_sha):
    require_sha(runtime)
    trials=cohort.get('trials',[])
    if not (cohort.get('passed') is True and not cohort.get('failures')
            and cohort.get('integration_sha')==runtime and cohort.get('plan_sha256')==plan_sha
            and len(trials)==4 and {r.get('trial') for r in trials}==
                {'combined-1','combined-2','combined-3','recovery-1'}
            and all(r.get('passed') is True for r in trials)):
        raise ValueError('fixed_cohort_not_accepted')
    if not (build.get('passed') is True and not build.get('failures')
            and build.get('integration_sha')==runtime and build.get('paper_only') is True):
        raise ValueError('complete_build_not_verified')


def run_identity(row,sha):
    if not (row.get('head_sha')==sha and row.get('head_branch')==BRANCH
            and row.get('event')=='workflow_dispatch' and row.get('run_attempt')==1
            and row.get('path')=='.github/workflows/'+WORKFLOW
            and type(row.get('id')) is int):
        raise ValueError('canonical_run_identity_mismatch')
    for workflow in row.get('referenced_workflows',[]):
        if workflow.get('sha')!=sha:
            raise ValueError('canonical_reusable_workflow_sha_mismatch')
    return row


def request(repo,method,path,data=None):
    body=None if data is None else json.dumps(data).encode()
    req=urllib.request.Request('https://api.github.com/repos/'+repo+'/'+path,
        data=body,method=method,headers={
            'Authorization':'Bearer '+os.environ['GH_TOKEN'],
            'Accept':'application/vnd.github+json','Content-Type':'application/json',
            'X-GitHub-Api-Version':'2026-03-10'})
    with urllib.request.urlopen(req,timeout=30) as response:
        raw=response.read()
        return json.loads(raw) if raw else {}


def store(path,row,exclusive=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x' if exclusive else 'w') as stream:
        json.dump(row,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())


def dispatch(repo,sha,runtime,plan_sha,cohort,build,output,*,api=request,sleep=time.sleep,polls=12):
    require_sha(sha);prerequisites(cohort,build,runtime,plan_sha)
    if not re.fullmatch('[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):
        raise ValueError('invalid_repository')
    output=Path(output);intent=output.with_suffix('.intent.json')
    # Verify the exact canonical branch and both identical trees before authority.
    ref=api(repo,'GET','git/ref/heads/'+BRANCH)
    if ref.get('object',{}).get('sha')!=sha:
        raise ValueError('canonical_branch_moved')
    commit=api(repo,'GET','git/commits/'+sha)
    parent=api(repo,'GET','git/commits/'+runtime)
    if commit.get('tree',{}).get('sha')!=parent.get('tree',{}).get('sha'):
        raise ValueError('canonical_tree_not_reviewed')
    query='actions/workflows/'+WORKFLOW+'/runs?'+urllib.parse.urlencode({'branch':BRANCH,'per_page':100})
    before=api(repo,'GET',query).get('workflow_runs',[])
    if any(r.get('status') in ACTIVE for r in before):
        raise ValueError('competing_canonical_run')
    existing=[r for r in before if r.get('head_sha')==sha and r.get('event')=='workflow_dispatch']
    if existing:
        raise ValueError('canonical_sha_already_dispatched')
    row=dict(canonical_sha=sha,runtime_sha=runtime,plan_sha256=plan_sha,
             previous_run_ids=[r['id'] for r in before],paper_only=True,
             market_authority=False,created_at=dt.datetime.now(dt.timezone.utc).isoformat(),post_attempts=1)
    store(intent,row,exclusive=True)
    post_error=None;receipt={}
    try:
        receipt=api(repo,'POST','actions/workflows/'+WORKFLOW+'/dispatches',
                    {'ref':BRANCH,'inputs':{'expected_sha':sha}})
    except (OSError,urllib.error.URLError,ValueError) as exc:
        post_error=type(exc).__name__
    row['dispatch_response_run_id']=receipt.get('workflow_run_id')
    row['post_error_type']=post_error;store(output,row)
    for _ in range(polls):
        if receipt.get('workflow_run_id'):
            candidates=[api(repo,'GET','actions/runs/'+str(receipt['workflow_run_id']))]
        else:
            candidates=[r for r in api(repo,'GET',query).get('workflow_runs',[])
                        if r.get('id') not in row['previous_run_ids'] and r.get('head_sha')==sha]
        if len(candidates)>1:raise ValueError('duplicate_canonical_runs')
        if candidates:
            run=run_identity(candidates[0],sha)
            row.update(dispatched=True,run_id=run['id'],run_url=run.get('html_url'),
                       run_status=run.get('status'),conclusion=run.get('conclusion'))
            store(output,row);return row
        sleep(5)
    raise RuntimeError('dispatch_not_confirmed_do_not_retry_post')


def main():
    parser=argparse.ArgumentParser()
    for name in ('repo','sha','runtime','plan-sha256','cohort','build','output'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    dispatch(args.repo,args.sha,args.runtime,args.plan_sha256,
             json.loads(Path(args.cohort).read_text()),json.loads(Path(args.build).read_text()),args.output)


if __name__=='__main__':main()
