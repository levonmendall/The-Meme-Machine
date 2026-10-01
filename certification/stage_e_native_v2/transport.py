"""Read-only future GitHub artifact provenance. Never dispatches or promotes.

These APIs address GitHub qualification transport, not market providers. Native
trials run without this token and without network access. Artifact ZIP digest,
ID and inventory are checked before and after reading original bytes.
"""
import argparse
import io
import json
import os
from pathlib import Path
import re
import tarfile
import urllib.request
import zipfile

from . import REPOSITORY
from .binding import verify_assembly, workflow_identity
from .contract import HERE, canonical, read, sha256, strict_json
from .verify import aggregate, validate_raw

WORKFLOW='.github/workflows/stagee-native-qualification-v2.yml'
REUSABLE='.github/workflows/stagee-native-qualification-v2-reusable.yml'


def verify_run(run, *, candidate, run_id, attempt):
    if (run.get('id')!=int(run_id) or run.get('head_sha')!=candidate or run.get('run_attempt')!=attempt
            or attempt!=1 or run.get('event')!='workflow_dispatch' or run.get('path')!=WORKFLOW):
        raise ValueError('remote_workflow_identity_mismatch')
    refs=run.get('referenced_workflows')
    if not isinstance(refs,list) or len(refs)!=1 or refs[0].get('sha')!=candidate:
        raise ValueError('remote_reusable_workflow_sha_missing_or_wrong')
    path=refs[0].get('path','').split('@',1)[0]
    if path!=REPOSITORY+'/'+REUSABLE:raise ValueError('remote_reusable_workflow_path')
    return dict(workflow_path=WORKFLOW,resolved_workflow_sha=candidate,
        reusable_workflow_path=REUSABLE,reusable_workflow_sha=candidate,
        run_id=str(run_id),attempt=attempt,event='workflow_dispatch',candidate_sha=candidate)


class NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        redirected=super().redirect_request(req,fp,code,msg,headers,newurl)
        if redirected:
            redirected.remove_header('Authorization')
        return redirected


class GitHub:
    def __init__(self):
        token=os.environ.get('GH_TOKEN')
        if not token:raise ValueError('github_transport_token_missing')
        self.token=token
        self.base='https://api.github.com/repos/'+REPOSITORY
        self.opener=urllib.request.build_opener(NoCredentialRedirect())

    def bytes(self,path):
        if not path.startswith('/') or '..' in path:raise ValueError('invalid_github_read_path')
        req=urllib.request.Request(self.base+path,headers=dict(Authorization='Bearer '+self.token,
            Accept='application/vnd.github+json',**{'X-GitHub-Api-Version':'2022-11-28'}))
        with self.opener.open(req,timeout=30) as response:
            result=response.read(256*1024*1024+1)
            if len(result)>256*1024*1024:raise ValueError('artifact_transport_bound')
            return result

    def json(self,path):return strict_json(self.bytes(path))

    def artifacts(self,run_id):
        out=[]
        for page in range(1,101):
            value=self.json(f'/actions/runs/{run_id}/artifacts?per_page=100&page={page}')
            rows=value['artifacts'];out.extend(rows)
            if len(out)>=value['total_count']:
                if len(out)!=value['total_count']:raise ValueError('artifact_pagination_contradiction')
                return out
            if not rows:break
        raise ValueError('incomplete_artifact_inventory')


def artifact_binding(row, candidate, run_id):
    digest=row.get('digest','')
    workflow=row.get('workflow_run',{})
    if (row.get('expired') is not False or type(row.get('id')) is not int
            or not re.fullmatch(r'sha256:[0-9a-f]{64}',digest)
            or workflow.get('id')!=int(run_id) or workflow.get('head_sha')!=candidate):
        raise ValueError('artifact_remote_provenance_invalid')
    return dict(id=row['id'],name=row['name'],digest=digest,run_id=int(run_id),candidate_sha=candidate)


def select_artifacts(rows,candidate,run_id,attempt,matrix):
    expected={'preflight':[]};expected.update({case:[] for case in matrix})
    prefix=f'native-v2-{candidate}-{run_id}-{attempt}-'
    selected=[]
    for row in rows:
        name=row['name']
        if not name.startswith(prefix):continue
        suffix=name[len(prefix):]
        case='preflight' if suffix=='preflight' else next((case for case in matrix if suffix.startswith(case+'-')),None)
        if case is None:
            if suffix=='aggregate':continue
            raise ValueError('foreign_artifact_case')
        expected[case].append(artifact_binding(row,candidate,run_id))
    if any(len(value)!=1 for value in expected.values()):raise ValueError('missing_duplicate_or_replaced_artifact')
    return {case:value[0] for case,value in expected.items()}


def extract_assembly(archive,output,digest):
    output=Path(output).resolve()
    if output.exists():raise ValueError('assembly_output_already_exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive,'r:') as tar:
        members=tar.getmembers()
        if not members or len(members)>10000 or sum(m.size for m in members)>256*1024*1024:
            raise ValueError('assembly_tar_bound')
        names=set()
        for member in members:
            parts=Path(member.name).parts
            if (not parts or parts[0]!='assembly' or '..' in parts or Path(member.name).is_absolute()
                    or not (member.isfile() or member.isdir()) or member.name in names):
                raise ValueError('assembly_tar_escape_or_shadow')
            names.add(member.name)
        # Extraction into a fresh unique parent prevents sibling/member attacks.
        staging=output.parent/(output.name+'.unpack');staging.mkdir(exist_ok=False)
        tar.extractall(staging,filter='data')
        (staging/'assembly').rename(output);staging.rmdir()
    return verify_assembly(output,digest)


def declare(output):
    candidate=os.environ['MM_EXPECTED_SHA'];run_id=os.environ['GITHUB_RUN_ID'];attempt=int(os.environ['GITHUB_RUN_ATTEMPT'])
    if os.environ['GITHUB_SHA']!=candidate or os.environ['MM_WORKFLOW_SHA']!=candidate:
        raise ValueError('caller_or_event_sha_not_candidate')
    ref=os.environ['MM_WORKFLOW_REF'].split('@',1)[0]
    if ref!=REPOSITORY+'/'+WORKFLOW:raise ValueError('caller_workflow_ref')
    api=GitHub();run=api.json('/actions/runs/'+run_id)
    row=verify_run(run,candidate=candidate,run_id=run_id,attempt=attempt)
    Path(output).write_bytes(canonical(workflow_identity(row,candidate)))


def aggregate_github(digest,output):
    candidate=os.environ['MM_EXPECTED_SHA'];run_id=os.environ['GITHUB_RUN_ID'];attempt=int(os.environ['GITHUB_RUN_ATTEMPT'])
    api=GitHub();remote=verify_run(api.json('/actions/runs/'+run_id),candidate=candidate,run_id=run_id,attempt=attempt)
    matrix=read(HERE/'trial-definition-v2.json')['deterministic_matrix']
    selected=select_artifacts(api.artifacts(run_id),candidate,run_id,attempt,matrix)
    output=Path(output);output.mkdir(exist_ok=False,parents=True);payloads={}
    for case,row in selected.items():
        raw=api.bytes('/actions/artifacts/'+str(row['id'])+'/zip')
        if 'sha256:'+sha256(raw)!=row['digest']:raise ValueError('artifact_zip_digest_changed')
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names=z.namelist()
            if len(names)!=len(set(names)) or any(Path(n).is_absolute() or '..' in Path(n).parts for n in names):
                raise ValueError('artifact_zip_shadow')
            expected={'assembly.tar','raw-trial-v2.json'} if case=='preflight' else {'raw-trial-v2.json','process.log'}
            if set(names)!=expected:raise ValueError('unexpected_artifact_content')
            payloads[case]={name:z.read(name) for name in names}
    # Byte/digest/ID inventory is immutable across reads; changes invalidate all.
    if selected!=select_artifacts(api.artifacts(run_id),candidate,run_id,attempt,matrix):
        raise ValueError('artifact_replaced_after_read')
    archive=output/'assembly.tar';archive.write_bytes(payloads['preflight']['assembly.tar'])
    assembly=output/'assembly';manifest=extract_assembly(archive,assembly,digest)
    if manifest['identity']['workflow_identity']!=remote:raise ValueError('artifact_workflow_identity')
    for key,env in [('plan_hash','MM_PLAN_HASH'),('input_manifest_hash','MM_INPUT_HASH')]:
        if manifest['identity'][key]!=os.environ[env]:raise ValueError('aggregate_plan_or_input_hash')
    validate_raw(strict_json(payloads['preflight']['raw-trial-v2.json']),manifest,'preflight')
    paths=[];inventory={}
    for case in matrix:
        raw_bytes=payloads[case]['raw-trial-v2.json'];raw=strict_json(raw_bytes)
        path=output/(case+'.json');path.write_bytes(raw_bytes);paths.append(str(path))
        if not selected[case]['name'].endswith('-'+raw['trial_id'].replace(':','_')):
            raise ValueError('artifact_trial_name_replaced')
        inventory[case]=dict(trial_id=raw['trial_id'],sha256=sha256(raw_bytes),candidate_sha=candidate,
            assembly_digest=digest,run_id=run_id,attempt=attempt,generation=raw['generation'])
    (output/'transport-bindings.json').write_bytes(canonical(selected))
    (output/'inventory.json').write_bytes(canonical(inventory))
    row=aggregate(assembly,digest,paths,inventory,output/'aggregate.json')
    # Original trial jobs must also be terminal and successful for a green result.
    jobs=api.json(f'/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100')['jobs']
    failures=[]
    for case in matrix:
        matches=[j for j in jobs if j.get('name','').endswith('trial ('+case+')')]
        if len(matches)!=1 or matches[0].get('status')!='completed' or matches[0].get('conclusion')!='success':
            failures.append(case)
    if failures:
        row['passed']=False;row['failed_jobs']=failures;(output/'aggregate.json').write_bytes(canonical(row))
    return 0 if row['passed'] else 1


def main():
    p=argparse.ArgumentParser();subs=p.add_subparsers(dest='op',required=True)
    d=subs.add_parser('declare');d.add_argument('--output',required=True)
    e=subs.add_parser('extract-assembly');e.add_argument('--archive',required=True);e.add_argument('--output',required=True);e.add_argument('--digest',required=True)
    t=subs.add_parser('trial-id');t.add_argument('--raw',required=True)
    a=subs.add_parser('aggregate-github');a.add_argument('--digest',required=True);a.add_argument('--output',required=True)
    args=p.parse_args()
    if args.op=='declare':declare(args.output)
    elif args.op=='extract-assembly':extract_assembly(args.archive,args.output,args.digest)
    elif args.op=='trial-id':print('trial_id='+read(args.raw)['trial_id'].replace(':','_'))
    elif args.op=='aggregate-github':return aggregate_github(args.digest,args.output)
    return 0


if __name__=='__main__':raise SystemExit(main())
