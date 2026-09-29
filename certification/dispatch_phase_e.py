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
import tempfile
import hashlib
import urllib.error
import urllib.parse
import urllib.request

WORKFLOW='directional-six-regime-nonmarket.yml'
BRANCH='cert/autonomous-paper-machinery-20260927'
ACTIVE={'queued','in_progress','waiting','pending','requested'}
FULL_GATES=frozenset({
    'exact_source_offline','native_crash_matrix','restart_safety',
    'integrated_current_policy','historical_exposure_resolution',
    'historical_registry_released','resource_bounds','mature_solana_pressure',
    'combined_mature_solana_pressure','joined_eight_day_system',
    'exact_integration_identity','six_regime_integration',
    'preserved_production_adapter_contracts','bounded_preserved_validation',
})



def require_sha(sha):
    if not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError('invalid_exact_sha')


def prerequisites(cohort,build,runtime,plan_sha):
    require_sha(runtime)
    if not re.fullmatch('[0-9a-f]{64}',plan_sha):
        raise ValueError('invalid_plan_sha256')
    trials=cohort.get('trials',[])
    if not (cohort.get('passed') is True and not cohort.get('failures')
            and cohort.get('canonical_authority') is False
            and cohort.get('integration_sha')==runtime and cohort.get('plan_sha256')==plan_sha
            and len(trials)==4 and {r.get('trial') for r in trials}==
                {'combined-1','combined-2','combined-3','recovery-1'}
            and all(r.get('passed') is True for r in trials)):
        raise ValueError('fixed_cohort_not_accepted')
    gates=build.get('gates') or {}
    if not (build.get('passed') is True and not build.get('failures')
            and build.get('integration_sha')==runtime and build.get('expected_integration_sha')==runtime
            and build.get('engineering_certification')=='CERTIFIED_NON_MARKET_ENGINEERING'
            and build.get('validation_scope')=='preserved_evidence_only'
            and build.get('paper_only') is True and build.get('live_money') is False
            and FULL_GATES.issubset(gates) and all(value is True for value in gates.values())):
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
    """Publish a complete durable JSON file, never a truncated dispatch intent.

    An exclusive hard link is the no-clobber publication boundary. Updates use
    atomic replacement; both paths fsync the directory after publishing.
    """
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    temporary=Path(name)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(row,stream,indent=2);stream.write('\n')
            stream.flush();os.fsync(stream.fileno())
        if exclusive:os.link(temporary,path)
        else:os.replace(temporary,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def canonical_runs(repo,api):
    """No omitted page may hide an active or previously dispatched run."""
    rows=[]
    for page in range(1,101):
        query='actions/workflows/'+WORKFLOW+'/runs?'+urllib.parse.urlencode(
            {'branch':BRANCH,'per_page':100,'page':page})
        result=api(repo,'GET',query)
        batch=result.get('workflow_runs',[])
        if not isinstance(batch,list):raise ValueError('invalid_workflow_runs')
        rows.extend(batch)
        if len(batch)<100:
            if result.get('total_count',len(rows))>len(rows):
                raise ValueError('incomplete_canonical_run_listing')
            return rows
    raise ValueError('canonical_run_listing_bound_exceeded')


def _reconcile(repo,row,output,api,sleep,polls):
    sha=row['canonical_sha']
    for _ in range(polls):
        if row.get('dispatch_response_run_id'):
            candidates=[api(repo,'GET','actions/runs/'+str(row['dispatch_response_run_id']))]
        else:
            # Keep wrong-SHA/new-event rows in the candidate set: a branch race
            # is an identity failure, not permission to ignore it and retry POST.
            candidates=[r for r in canonical_runs(repo,api)
                        if r.get('id') not in row['previous_run_ids']]
        if len(candidates)>1:raise ValueError('duplicate_canonical_runs')
        if candidates:
            run=run_identity(candidates[0],sha)
            row.update(dispatched=True,run_id=run['id'],run_url=run.get('html_url'),
                       run_status=run.get('status'),conclusion=run.get('conclusion'),
                       canonical_authority=False,artifacts_verified=False)
            store(output,row);return row
        sleep(5)
    raise RuntimeError('dispatch_not_confirmed_do_not_retry_post')


def reconcile_existing(repo,output,*,api=request,sleep=time.sleep,polls=12):
    """Resume a lost response using GET only; never submit another dispatch."""
    output=Path(output);intent=output.with_suffix('.intent.json')
    row=json.loads(intent.read_text())
    if (row.get('repository')!=repo or row.get('post_attempts')!=1 or
            row.get('canonical_sha')!=row.get('runtime_sha')):
        raise ValueError('dispatch_intent_identity_mismatch')
    require_sha(row['canonical_sha'])
    # An existing result contains an authoritative API response ID when one was
    # returned. It cannot override any identity in the pre-POST durable intent.
    if output.exists():
        receipt=json.loads(output.read_text())
        if any(receipt.get(k)!=v for k,v in row.items()):
            raise ValueError('dispatch_receipt_intent_mismatch')
        row=receipt
    return _reconcile(repo,row,output,api,sleep,polls)


def dispatch(repo,sha,runtime,plan_sha,cohort,build,output,*,api=request,sleep=time.sleep,polls=12):
    require_sha(sha);prerequisites(cohort,build,runtime,plan_sha)
    if sha!=runtime:raise ValueError('canonical_sha_not_verified_candidate')
    if not re.fullmatch('[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):
        raise ValueError('invalid_repository')
    output=Path(output);intent=output.with_suffix('.intent.json')
    # Tree equivalence is insufficient: the certified candidate SHA must match.
    ref=api(repo,'GET','git/ref/heads/'+BRANCH)
    if ref.get('object',{}).get('sha')!=sha:
        raise ValueError('canonical_branch_moved')
    before=canonical_runs(repo,api)
    if any(r.get('status') in ACTIVE for r in before):
        raise ValueError('competing_canonical_run')
    existing=[r for r in before if r.get('head_sha')==sha and r.get('event')=='workflow_dispatch']
    if existing:
        raise ValueError('canonical_sha_already_dispatched')
    row=dict(repository=repo,canonical_sha=sha,runtime_sha=runtime,plan_sha256=plan_sha,
             canonical_authority=False,artifacts_verified=False,
             cohort_sha256=hashlib.sha256(json.dumps(cohort,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
             build_sha256=hashlib.sha256(json.dumps(build,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
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
    return _reconcile(repo,row,output,api,sleep,polls)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--reconcile-only',action='store_true')
    for name in ('sha','runtime','plan-sha256','cohort','build'):
        parser.add_argument('--'+name)
    args=parser.parse_args()
    if args.reconcile_only:
        reconcile_existing(args.repo,args.output)
    else:
        if not all((args.sha,args.runtime,args.plan_sha256,args.cohort,args.build)):
            parser.error('fresh dispatch requires candidate, plan and verification receipts')
        dispatch(args.repo,args.sha,args.runtime,args.plan_sha256,
                 json.loads(Path(args.cohort).read_text()),json.loads(Path(args.build).read_text()),args.output)


if __name__=='__main__':main()
