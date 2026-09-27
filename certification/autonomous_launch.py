"""Existing external launch-request pattern for a dispatch-only GitHub connection.

The request branch never becomes runtime source. Its one-use intent is durable
before POST, and the certified workflow independently consumes market authority.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re

from certification import autonomous_control as control, campaign_state
from certification.journal import digest
from certification.position_continuation import _atomic
from certification.prospective_program import GitHub
from certification.run import ROOT
from certification.single_campaign_control import StateStore,checkout_files,first_attempt,contention

BRANCH='launch/autonomous-paper-v1'
WORKFLOW='.github/workflows/autonomous-paper-launch.yml'
FIELDS={'operation','runtime_sha','runtime_ref','campaign_id','certification_run_id',
        'reviewed_artifact_digest','maximum_normal_windows'}


def request(value):
    if set(value)!=FIELDS or value['operation'] not in ('check','authorize','accept'):
        raise ValueError('autonomous_launch_request_fields')
    if (not re.fullmatch('[0-9a-f]{40}',value['runtime_sha'])
            or not re.fullmatch('cert/autonomous-paper-[a-z0-9-]+',value['runtime_ref'])):
        raise ValueError('autonomous_launch_runtime')
    control.campaign_id(value['campaign_id'])
    if (type(value['certification_run_id']) is not int or value['certification_run_id']<0
            or (value['operation']=='authorize' and value['certification_run_id']<=0)
            or type(value['maximum_normal_windows']) is not int
            or not 2<=value['maximum_normal_windows']<=control.MAX_WINDOWS):
        raise ValueError('autonomous_launch_certificate_or_window_bound')
    if value['reviewed_artifact_digest'] and not re.fullmatch('sha256:[0-9a-f]{64}',value['reviewed_artifact_digest']):
        raise ValueError('autonomous_launch_review_digest')
    if value['operation']=='accept' and not value['reviewed_artifact_digest']:
        raise ValueError('autonomous_launch_review_required')
    return value


def launch(api,value,run_id,attempt):
    first_attempt(attempt);value=request(value);checkout_files(value['runtime_sha'])
    expected=campaign_state.identity()
    owner=api.request('GET',f'actions/runs/{int(run_id)}')
    if (owner.get('path','').split('@')[0]!=WORKFLOW or owner.get('head_branch')!=BRANCH
            or owner.get('event')!='push' or str(owner.get('run_attempt'))!='1'
            or '[autonomous-paper-request]' not in (owner.get('head_commit') or {}).get('message','')):
        raise ValueError('autonomous_launch_owner')
    source=api.request('GET','contents/'+WORKFLOW+'?ref='+owner['head_sha'])
    if base64.b64decode(source['content'])!=(ROOT/WORKFLOW).read_bytes():
        raise ValueError('autonomous_launcher_source_changed')
    contract=control.workflow_contract(api,value['runtime_ref'],expected)
    if value['operation']=='check':
        return dict(identity=expected,workflow_contract=contract,dispatch=False,provider_calls=0)
    store=StateStore(api,{'authorization_id':value['campaign_id']},
        ref='state/autonomous-launch-'+digest([value['campaign_id'],value['operation']])[:24],
        path='certification/AUTONOMOUS_LAUNCH_INTENT.json')
    if store.read() is not None:raise ValueError('autonomous_launch_already_consumed')
    state=control.store_for(api,value['campaign_id']).read()
    if value['operation']=='authorize':
        if state is not None:raise ValueError('autonomous_authorization_consumed')
        cert=api.request('GET',f'actions/runs/{value["certification_run_id"]}')
        if (cert.get('head_sha')!=expected['integration_sha'] or cert.get('status')!='completed'
                or cert.get('conclusion')!='success'):
            raise ValueError('autonomous_launch_certificate_not_exact_terminal_success')
        # Full artifact certificate verification remains mandatory in authorize;
        # this request does not grant provider or PAPER entry authority.
    else:
        control._bound(state,expected)
        if (state['phase']!='SMOKE_REVIEW' or
                state['previous']['artifact']['digest']!=value['reviewed_artifact_digest']):
            raise ValueError('autonomous_launch_unreviewed_smoke')
    contention(api,exclude_run=run_id)
    inputs=dict(operation=value['operation'],expected_sha=value['runtime_sha'],
        campaign_id=value['campaign_id'],certification_run_id=str(value['certification_run_id']),
        reviewed_artifact_digest=value['reviewed_artifact_digest'],
        maximum_normal_windows=str(value['maximum_normal_windows']),nonce='launch-'+str(run_id))
    intent=dict(identity=expected,request=value,owner_run_id=int(run_id),owner_sha=owner['head_sha'],
        workflow_contract=contract,dispatch_payload_hash=digest(inputs),
        dispatch_may_have_been_sent=True,retry_allowed=False,entry_authority=False)
    store.write(intent)
    control.workflow_contract(api,value['runtime_ref'],expected);contention(api,exclude_run=run_id)
    api.request('POST','actions/workflows/'+control.WORKFLOW+'/dispatches',
                dict(ref=value['runtime_ref'],inputs=inputs))
    return intent


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    value={key:os.environ['REQUEST_'+key.upper()] for key in FIELDS}
    for key in ('certification_run_id','maximum_normal_windows'):value[key]=int(value[key])
    result=launch(GitHub(),value,int(os.environ['GITHUB_RUN_ID']),os.environ['GITHUB_RUN_ATTEMPT'])
    _atomic(Path(a.output),result)


if __name__=='__main__':main()
