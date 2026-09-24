"""Preserve long smoke positions and reuse the same admitted preflight when flat.

Smoke and its continuations never become profitability observations. Fresh
campaign admission waits for every original native book to be verified flat.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import time

from certification.prospective_program import (GitHub,CANONICAL_BRANCH,_member,
    commit_transition,dispatch,protocol,git,digest,implementation_hash)
from certification.controls import smoke_engineering,export_readiness

def register(state,result,assurance,artifact,run_id):
    if state is None or state.get('current_workflow_run_id')!=int(run_id):raise ValueError('smoke_program_owner')
    if (result.get('integration_sha')!=state['integration_sha'] or
            result.get('implementation_hash')!=implementation_hash() or
            smoke_engineering(result)['status']!='PASS' or
            assurance.get('runtime_sha')!=state['integration_sha'] or
            assurance.get('run_id')!=result.get('run_id') or assurance.get('operational_validity')!='valid'):
        raise ValueError('smoke_validity_unestablished')
    pending=[lane for lane,row in result['lanes'].items() if row.get('open_positions')]
    if any(lane not in ('meteora','ramses') for lane in pending):raise ValueError('smoke_unsupported_open_lane')
    prior=state.get('smoke_evidence_run_id')
    if prior:
        if prior!=int(run_id):raise ValueError('smoke_evidence_replacement')
        return state
    state=deepcopy(state)
    keys=('phase','status','run_id','continuous_overlap_seconds','source_manifest_hash','implementation_hash','integration_sha','shared_provider','lanes')
    readiness={k:result[k] for k in keys}
    lane_keys=('exit_code','unexpected_exit','process_restarts','open_positions','accounting_reconciled','provider_requests','gates','native_accounting','funnel','durable_handoff','terminal_reconciliation')
    readiness['lanes']={lane:{k:r.get(k) for k in lane_keys} for lane,r in result['lanes'].items()}
    state.update(smoke_evidence_run_id=int(run_id),smoke_readiness=readiness,
        smoke_artifact=dict(id=artifact['id'],digest=artifact['digest']),smoke_pending_lanes=pending,
        smoke_continuation_proofs={})
    if pending:state.update(phase='WAITING_SMOKE_POSITIONS',next_action='continue_original_smoke_positions_until_verified_flat')
    state['history'].append(dict(at=time.time(),action='admitted_smoke_preserved',run_id=int(run_id),pending_lanes=pending))
    return state

def complete(state,result,run_id,event_id):
    if state is None or state.get('smoke_evidence_run_id')!=int(run_id):raise ValueError('smoke_continuation_owner')
    lane=result.get('lane');proofs=state.get('smoke_continuation_proofs',{})
    if lane in proofs:
        if proofs[lane]['result_sha256']!=digest(result):raise ValueError('smoke_terminal_proof_changed')
        return state
    if state['phase']!='WAITING_SMOKE_POSITIONS' or lane not in state.get('smoke_pending_lanes',[]):raise ValueError('smoke_continuation_phase')
    if (result.get('handoff_required') is not False or result.get('terminal_replay_verified') is not True
            or result.get('assurance_passed') is not True or
            (result.get('runtime_identity') or {}).get('integration_sha')!=state['integration_sha']):
        raise ValueError('smoke_continuation_not_verified_flat')
    accounting=result.get('accounting') or {}
    if accounting.get('open_positions')!=0 or any(accounting.get(k,0)!=0 for k in ('committed','reserved','pending','unsettled')):
        raise ValueError('smoke_continuation_native_not_flat')
    state=deepcopy(state)
    state['smoke_continuation_proofs'][lane]=dict(result_sha256=digest(result),result=result,event_id=event_id)
    state['smoke_pending_lanes'].remove(lane)
    state['history'].append(dict(at=time.time(),action='smoke_position_verified_flat',lane=lane,event_id=event_id))
    if not state['smoke_pending_lanes']:state.update(phase='READY',next_action='fresh_hourly_after_preserved_smoke_positions')
    return state

def readiness(state,run_id):
    if state is None or state.get('smoke_evidence_run_id')!=int(run_id) or state.get('smoke_pending_lanes'):
        raise ValueError('smoke_readiness_not_flat')
    row=deepcopy(state['smoke_readiness'])
    if row['integration_sha']!=state['integration_sha'] or row['implementation_hash']!=implementation_hash():
        raise ValueError('smoke_readiness_revision')
    for lane,proof in state.get('smoke_continuation_proofs',{}).items():
        if proof['result_sha256']!=digest(proof['result']):raise ValueError('smoke_continuation_proof_digest')
        lane_row=row['lanes'][lane]
        lane_row['native_accounting_at_smoke_end']=lane_row.get('native_accounting')
        lane_row.update(open_positions=0,accounting_reconciled=True,
            native_accounting=proof['result']['accounting'],
            terminal_reconciliation=dict(verified=True,open_positions=0,accounting=proof['result']['accounting']))
    row['original_artifact']=state['smoke_artifact']
    row['smoke_continuation_proofs']=state.get('smoke_continuation_proofs',{})
    if smoke_engineering(row)['status']!='PASS':raise ValueError('smoke_readiness_invalid')
    return row

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('register','complete','readiness'))
    p.add_argument('--run-id',required=True);p.add_argument('--result');p.add_argument('--output',required=True);a=p.parse_args()
    if a.command in ('register','complete'):
        from certification.single_campaign_control import prohibit_if_enabled
        prohibit_if_enabled('smoke_continuation_'+a.command)
    api=GitHub();proto,ph=protocol();sha=git('rev-parse','HEAD')
    if a.command=='register':
        run=api.request('GET',f'actions/runs/{int(a.run_id)}')
        if run['head_sha']!=sha:raise ValueError('smoke_runtime_identity')
        jobs=api.pages(f'actions/runs/{int(a.run_id)}/jobs','jobs')
        if not any(j['name']=='smoke-artifact-review' and j['conclusion']=='success' for j in jobs):raise ValueError('smoke_artifact_review_missing')
        archive,item=api.artifact(a.run_id,f'four-lane-certification-{a.run_id}-{run["run_attempt"]}')
        result=_member(archive,'certification-smoke/result.json');assurance=_member(archive,'assurance/market-assurance.json')
        state,changed=commit_transition(api,proto,sha,ph,lambda s:register(s,result,assurance,item,a.run_id))
        if changed:
            for lane in state.get('smoke_pending_lanes',[]):
                api.request('POST','actions/workflows/position-continuation.yml/dispatches',dict(ref=CANONICAL_BRANCH,inputs=dict(
                    lane=lane,state_run_id=str(a.run_id),slice_seconds='3000',program='true',expected_sha=sha,
                    campaign_run_id=str(a.run_id),smoke_continuation='true')))
    elif a.command=='complete':
        result=json.loads(Path(a.result).read_text());event_id=os.environ['GITHUB_RUN_ID']+':'+os.environ.get('GITHUB_RUN_ATTEMPT','1')
        state,_=commit_transition(api,proto,sha,ph,lambda s:complete(s,result,a.run_id,event_id))
        state=dispatch(api,proto,sha,ph)
    else:
        state,_=commit_transition(api,proto,sha,ph,lambda s:s)
        if state.get('current_workflow_run_id')!=int(os.environ['GITHUB_RUN_ID']):raise ValueError('smoke_reuse_dispatch_owner')
        value=readiness(state,a.run_id);Path(a.output).write_text(json.dumps(value)+'\n')
        export_readiness(a.output,os.environ['GITHUB_OUTPUT']);return
    Path(a.output).write_text(json.dumps(state,indent=2,sort_keys=True)+'\n')

if __name__=='__main__':main()
