"""Durable, exact-revision paper certification program owned by GitHub Actions.

State lives on a separate append-only Git commit history, never the frozen runtime
branch. A dispatch intent is committed before a request is sent. Ambiguous dispatch,
source drift, missing evidence and engineering failure halt fresh admission.
"""
from __future__ import annotations
import argparse
import base64
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPRedirectHandler,urlopen
import uuid
import zipfile

from certification.journal import canonical,digest
from certification.prospective_acceptance import LANES,protocol,merge_records,evaluate
from certification.run import ROOT,git,manifest,source_integrity,implementation_hash

REPOSITORY='levonmendall/The-Meme-Machine'
CANONICAL_BRANCH='cert/prospective-market-v1'
STATE_PATH='certification/PROSPECTIVE_PROGRAM_STATE.json'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class GitHub:
    def __init__(self):
        if os.environ.get('GITHUB_REPOSITORY')!=REPOSITORY:raise ValueError('program_repository')
        self.token=os.environ.get('GH_TOKEN') or os.environ['GITHUB_TOKEN']

    def request(self,method,path,body=None):
        request=Request('https://api.github.com/repos/'+REPOSITORY+'/'+path,
            data=None if body is None else canonical(body).encode(),method=method,
            headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json',
                     'X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'})
        with urlopen(request,timeout=30) as response:
            raw=response.read()
            return json.loads(raw) if raw else None

    def pages(self,path,key):
        rows=[]
        for page in range(1,101):
            batch=self.request('GET',path+('&' if '?' in path else '?')+f'per_page=100&page={page}')[key]
            rows.extend(batch)
            if len(batch)<100:return rows
        raise ValueError('program_pagination_capacity')

    def artifact(self,run_id,name):
        matches=[a for a in self.pages(f'actions/runs/{int(run_id)}/artifacts','artifacts') if a['name']==name]
        if len(matches)!=1 or matches[0].get('expired'):raise ValueError('program_artifact_missing_or_ambiguous')
        item=matches[0]
        request=Request(item['archive_download_url'],headers={'Authorization':'Bearer '+self.token})
        try:
            with build_opener(NoRedirect).open(request,timeout=30) as response:raw=response.read()
        except HTTPError as exc:
            if exc.code not in (301,302,303,307,308):raise
            # The signed storage request must never receive the GitHub credential.
            with urlopen(exc.headers['Location'],timeout=60) as response:raw=response.read(512*1024*1024+1)
        if len(raw)>512*1024*1024:raise ValueError('program_artifact_size_bound')
        if 'sha256:'+hashlib.sha256(raw).hexdigest()!=item.get('digest'):
            raise ValueError('program_artifact_digest')
        return zipfile.ZipFile(io.BytesIO(raw)),item


def _member(archive,suffix):
    names=[n for n in archive.namelist() if n==suffix or n.endswith('/'+suffix)]
    if len(names)!=1:raise ValueError('program_evidence_member:'+suffix)
    info=archive.getinfo(names[0])
    if info.file_size>20*1024*1024:raise ValueError('program_evidence_size')
    return json.loads(archive.read(names[0]))


def certificate(api,run_id,sha,worktrees=None):
    run=api.request('GET',f'actions/runs/{int(run_id)}')
    if run['head_sha']!=sha:raise ValueError('program_certificate_sha')
    jobs=api.pages(f'actions/runs/{int(run_id)}/jobs','jobs')
    full=[j for j in jobs if j['name'].split(' / ')[-1]=='offline-prerequisites']
    if len(full)!=1 or full[0]['conclusion']!='success':raise ValueError('program_full_nonmarket_not_passed')
    archive,item=api.artifact(run_id,f'non-market-certification-{sha}-{run["run_attempt"]}')
    final=_member(archive,'final-acceptance.json');offline=_member(archive,'offline/result.json')
    if (final.get('passed') is not True or final.get('integration_sha')!=sha
            or not final.get('gates') or not all(final['gates'].values())
            or offline.get('passed') is not True or offline.get('integration_sha')!=sha
            or offline.get('source_manifest_hash')!=digest(manifest())
            or offline.get('source_diff_hashes')!={lane:r['source_diff_sha256'] for lane,r in manifest()['lanes'].items()}):
        raise ValueError('program_certificate_identity_or_gate')
    if worktrees and source_integrity(worktrees)!=offline['source_diff_hashes']:
        raise ValueError('program_prepared_source_mismatch')
    return dict(passed=True,integration_sha=sha,implementation_hash=implementation_hash(),
        source_manifest_hash=offline['source_manifest_hash'],source_diff_hashes=offline['source_diff_hashes'],
        full_nonmarket_run_id=int(run_id),full_nonmarket_artifact_id=item['id'],artifact_digest=item['digest'])


class StateStore:
    def __init__(self,api,proto):
        self.api=api;self.ref='cert/cohort-state-'+digest(proto['cohort_id'])[:12]
        self.head=None;self.tree=None

    def read(self):
        try:self.head=self.api.request('GET','git/ref/heads/'+self.ref)['object']['sha']
        except HTTPError as exc:
            if exc.code==404:return None
            raise
        commit=self.api.request('GET','git/commits/'+self.head);self.tree=commit['tree']['sha']
        entries=self.api.request('GET','git/trees/'+self.tree+'?recursive=1')['tree']
        item=next(x for x in entries if x['path']==STATE_PATH)
        blob=self.api.request('GET','git/blobs/'+item['sha'])
        return json.loads(base64.b64decode(blob['content']))

    def write(self,state):
        parent=self.head or state['integration_sha']
        if self.tree is None:self.tree=self.api.request('GET','git/commits/'+parent)['tree']['sha']
        state['updated_at']=time.time()
        tree=self.api.request('POST','git/trees',dict(base_tree=self.tree,tree=[
            dict(path=STATE_PATH,mode='100644',type='blob',content=json.dumps(state,sort_keys=True,indent=2)+'\n'),
            dict(path='docs/ALL_MARKET_CERTIFICATION_STATE.md',mode='100644',type='blob',content=checkpoint(state)),
        ]))
        commit=self.api.request('POST','git/commits',dict(message='Record prospective certification transition [skip ci]',
            tree=tree['sha'],parents=[parent]))
        if self.head:
            self.api.request('PATCH','git/refs/heads/'+self.ref,dict(sha=commit['sha'],force=False))
        else:self.api.request('POST','git/refs',dict(ref='refs/heads/'+self.ref,sha=commit['sha']))
        self.head=commit['sha'];self.tree=tree['sha']


def checkpoint(state):
    evaluation=state.get('evaluation') or {};lanes=evaluation.get('lanes') or {}
    records=merge_records(state.get('records',[]))
    latest=records[-1] if records else {};rows=latest.get('lanes') or {}
    view=dict(updated_at=state.get('updated_at'),canonical_sha=state.get('canonical_sha'),
        candidate_sha=state['integration_sha'],certified_sha=state['integration_sha'],
        prospective_sha=state['integration_sha'] if state.get('current_workflow_run_id') or records else None,
        strategy_identity_by_lane=state.get('strategy_identity_by_lane'),
        source_diff_hash_by_lane=state.get('source_diff_hash_by_lane'),
        acceptance_policy_identity=state['protocol_sha256'],current_phase=state['phase'],
        current_cohort_id=state['cohort_id'],latest_certification_run=state['certification_run_id'],
        latest_market_run=state.get('current_workflow_run_id'),
        last_completed_action=(state.get('history') or [{}])[-1],
        engineering_blockers=[state['halt_reason']] if state.get('halt_reason') else [],
        lane_health={lane:rows.get(lane,{}) for lane in LANES},
        machinery_certified_by_lane={lane:True for lane in LANES},
        natural_lifecycle_observed_by_lane={lane:lanes.get(lane,{}).get('natural_settlements',0)>0 for lane in LANES},
        economic_acceptance_established=state['phase']=='EVALUATED' and evaluation.get('promotion_eligible') is True,
        next_action=state['next_action'],operational_limit=state['operational_limit'],
        historical_references=state.get('historical_references'),history=state.get('history'))
    for field,key in (('natural_settlements_by_lane','natural_settlements'),('completed_blocks_by_lane','completed_blocks'),
                      ('observation_hours','observation_hours'),('calendar_span','calendar_span_hours'),
                      ('active_blocks','active_blocks'),('infrastructure_censoring','maximum_infrastructure_censoring_fraction')):
        view[field]={lane:lanes.get(lane,{}).get(key,0) for lane in LANES}
    view['accounting_reconciliation']={lane:rows.get(lane,{}).get('accounting_reconciled') for lane in LANES}
    view['current_economic_metrics']=evaluation
    from certification.prospective_acceptance import admitted
    proto,_=protocol()
    accepted=[r for r in records if admitted(r,proto)]
    view['assurance_by_lane']={lane:rows.get(lane,{}).get('assurance',{}) for lane in LANES}
    for lane in LANES:
        view['assurance_by_lane'][lane]=deepcopy(view['assurance_by_lane'][lane])
        view['assurance_by_lane'][lane]['last_valid_block']=accepted[-1]['run_id'] if accepted else None
    view['operational_validity']=dict(accepted_blocks=len(accepted),censored_blocks=len(records)-len(accepted),
        observed_hours=sum(r.get('observation_hours',0) for r in records),
        accepted_observation_hours=sum(r.get('observation_hours',0) for r in accepted),
        cohort_age_hours=max(0,(state.get('updated_at',state['created_at'])-state['created_at'])/3600))
    view['market_observation_validity']={lane:rows.get(lane,{}).get('assurance',{}).get('coverage_health','coverage_unknown') for lane in LANES}
    view['material_lane_coverage_gaps']={lane:rows.get(lane,{}).get('assurance',{}).get('coverage_gaps',[]) for lane in LANES}
    view['portfolio_reconciliation']=dict(
        all_lane_ledgers_reconciled=bool(rows) and all(rows.get(lane,{}).get('accounting_reconciled') is True for lane in LANES),
        native_quote_units_are_never_summed=True,
        normalized_portfolio=evaluation.get('portfolio'))
    from certification.market_assurance import economic_marks
    view['realized_and_unrealized_by_lane']={lane:economic_marks(lane,
        rows.get(lane,{}).get('assurance',{}).get('accounting_reconciliation',{})) for lane in LANES}
    return '# All-market certification state\n\nRuntime remains paper-only. This checkpoint is on the separate state branch; its commit is not the runtime SHA.\n\n```json\n'+json.dumps(view,indent=2,sort_keys=True)+'\n```\n'


def initial_state(sha,certification_run_id,proto,ph,now):
    return dict(schema='prospective-program-v1',integration_sha=sha,certification_run_id=int(certification_run_id),
        cohort_id=proto['cohort_id'],protocol_sha256=ph,created_at=now,updated_at=now,
        phase='READY',records=[],events={},history=[],reviewed_blocks=[],pending_lanes=[],next_action='dispatch_smoke_then_hourly',
        strategy_identity_by_lane={lane:{k:r[k] for k in ('strategy_version','policy_hash')} for lane,r in proto['frozen_lanes'].items()},
        source_diff_hash_by_lane={lane:r['source_diff_sha256'] for lane,r in proto['frozen_lanes'].items()},
        historical_references=dict(cancelled_run=35905479952,provider_shape_probe=35909625490,
                                   previous_nonmarket_run=35907893183,superseded_nonmarket_run=35914189762,
                                   superseded_market_run=35915320840,previous_observations_excluded=True),
        operational_limit=dict(maximum_blocks=192,maximum_calendar_hours=336),paper_only=True,live_money=False)


def reduce_record(state,record,event_id,proto,ph,now,base_reviewed=False):
    """Pure transition; losses never authorize edits, censoring, or sample removal."""
    state=deepcopy(state);checksum=digest(record)
    if event_id in state['events']:
        if state['events'][event_id]!=checksum:raise ValueError('program_conflicting_event_retry')
        return state
    was_halted=state['phase']=='HALTED'
    if (record.get('integration_sha')!=state['integration_sha'] or record.get('cohort_id')!=state['cohort_id']
            or record.get('protocol_sha256')!=ph or ph!=state['protocol_sha256']):
        raise ValueError('program_record_identity')
    if record.get('workflow_run_id')!=state.get('current_workflow_run_id'):
        raise ValueError('program_foreign_workflow_block')
    if state.get('current_native_run_id') not in (None,record['run_id']):
        raise ValueError('program_foreign_current_block')
    state['current_native_run_id']=record['run_id']
    state['events'][event_id]=checksum;state['records'].append(record)
    if base_reviewed:
        if record.get('continuation_updates'):raise ValueError('program_amendment_not_base_review')
        state['reviewed_blocks']=sorted(set(state.get('reviewed_blocks',[])+[record['run_id']]))
    state['history'].append(dict(at=now,event_id=event_id,native_run_id=record['run_id'],record_sha256=checksum))
    records=merge_records(state['records'])
    current=next(r for r in records if r['run_id']==record['run_id'])
    state['evaluation']=evaluate(records,proto,ph,state['integration_sha'])
    if was_halted:return state
    if record['run_id'] not in state.get('reviewed_blocks',[]):
        state.update(phase='AWAITING_BASE_REVIEW',next_action='await_original_campaign_artifact_review')
        return state
    healthy=(current.get('engineering_pass') is True and current.get('runtime_control_freeze_passed') is True
             and current.get('chain_binding_passed') is True)
    if proto.get('evidence_authority',{}).get('market_assurance_required'):
        healthy=healthy and current.get('market_assurance_passed') is True and current.get('block_admission_passed') is True
    for lane in LANES:
        row=current['lanes'][lane]
        healthy=healthy and all(row.get(k) is True for k in ('identity_match','accounting_reconciled',
            'telemetry_complete','freshness_finality_unchanged'))
        pending_replay=(lane in ('meteora','ramses') and (row.get('economics') or {}).get('flat') is False
                        and row.get('durable_handoff') is True and row.get('native_accounting_replay') is True)
        healthy=healthy and (row.get('durable_replay') is True or pending_replay)
        healthy=healthy and not row.get('unexpected_exit') and not row.get('process_restarts') and not row.get('forced_settled')
        censoring=row.get('infrastructure_censoring_fraction')
        healthy=healthy and isinstance(censoring,(int,float)) and 0<=censoring<=proto['evidence_quality']['maximum_infrastructure_censoring_fraction']
    if not healthy:
        state.update(phase='HALTED',halt_reason='engineering_or_evidence_gate',next_action='preserve_repair_recertify_successor_cohort')
        return state
    pending=[lane for lane in LANES if (current['lanes'][lane].get('economics') or {}).get('flat') is not True]
    if pending:
        if any(lane not in ('meteora','ramses') for lane in pending):
            state.update(phase='HALTED',halt_reason='unsupported_open_position',next_action='reconcile_and_repair')
        else:state.update(phase='CONTINUING',pending_lanes=pending,next_action='monitor_durable_positions')
        return state
    state['pending_lanes']=[]
    quality=all(all(row['quality_checks'].values()) for row in state['evaluation']['lanes'].values())
    portfolio=state['evaluation']['portfolio'];requirements=proto['portfolio_acceptance']
    quality=quality and portfolio['complete_blocks']>=requirements['minimum_complete_portfolio_blocks']
    quality=quality and portfolio['calendar_span_hours']>=requirements['minimum_calendar_span_hours']
    quality=quality and all(row['joint_nonzero_blocks']>=requirements['pairwise_correlation']['minimum_joint_nonzero_blocks']
                               for row in portfolio['correlations'].values())
    if quality:
        state.update(phase='EVALUATED',next_action='review_frozen_economic_result')
    elif (len(records)>=state['operational_limit']['maximum_blocks']
          or now-state['created_at']>=3600*state['operational_limit']['maximum_calendar_hours']):
        state.update(phase='OBSERVATION_LIMIT_REACHED',next_action='review_incomplete_sample_without_changing_thresholds')
    else:state.update(phase='READY',next_action='dispatch_next_frozen_block')
    return state


def commit_transition(api,proto,sha,ph,transition):
    """Optimistic Git ref serialization; racing callbacks never cancel each other."""
    for attempt in range(8):
        store=StateStore(api,proto);state=store.read()
        if state is not None and (state['integration_sha']!=sha or state['protocol_sha256']!=ph):
            raise ValueError('program_state_identity_successor_cohort_required')
        updated=transition(deepcopy(state))
        if updated==state:return state,False
        try:
            store.write(updated)
            return updated,True
        except HTTPError as exc:
            if exc.code not in (409,422):raise
            # A stale parent cannot fast-forward a competing state commit.
            current=StateStore(api,proto);current.read()
            if current.head==store.head:raise
            time.sleep(min(0.25*2**attempt,3))
    raise ValueError('program_state_contention_exhausted')


def dispatch(api,proto,sha,ph):
    nonce=uuid.uuid4().hex
    def intent(state):
        if state is None:raise ValueError('program_state_missing')
        if state['phase']!='READY':return state
        head=api.request('GET','git/ref/heads/'+CANONICAL_BRANCH)['object']['sha']
        if head!=sha:raise ValueError('program_canonical_sha_drift')
        state.update(phase='DISPATCH_PENDING',dispatch_id=nonce,current_native_run_id=None,
                     current_workflow_run_id=None,canonical_sha=head,next_action='claim_exact_dispatch')
        state['history'].append(dict(at=time.time(),action='dispatch_intent',dispatch_id=nonce))
        return state
    state,created=commit_transition(api,proto,sha,ph,intent)
    if not created:return state
    inputs={
        'phase':'hourly','program':'true','dispatch_id':nonce,
        'certification_run_id':str(state['certification_run_id']),'expected_sha':state['integration_sha']}
    if state.get('smoke_evidence_run_id'):inputs['smoke_run_id']=str(state['smoke_evidence_run_id'])
    api.request('POST','actions/workflows/four-lane-certification.yml/dispatches',dict(ref=CANONICAL_BRANCH,inputs=inputs))
    return state


def retirement_action(run,jobs):
    if run['status']=='completed':return 'verify_terminal'
    hourly=next((j for j in jobs if j['name']=='hourly-campaign'),{})
    market=next((s for s in hourly.get('steps',[]) if s['name'].startswith('One-hour continuous paper campaign')), {})
    if market.get('started_at') or market.get('status') in ('in_progress','completed'):
        return 'wait_existing_campaign'
    smoke=next((j for j in jobs if j['name']=='concurrent-smoke'),{})
    return 'cancel_before_new_admission' if smoke.get('conclusion')=='success' else 'wait_smoke'


def replay_retirement_books(archive,phase,worktrees):
    """Audit preserved native books without changing the failed run's evidence."""
    source_integrity(worktrees)
    prefix=f'certification-native/{phase}/'
    proofs={};total=0
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        for item in archive.infolist():
            if not item.filename.startswith(prefix) or item.is_dir():continue
            relative=Path(item.filename[len(prefix):])
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('program_native_archive_path')
            total+=item.file_size
            if total>512*1024*1024:raise ValueError('program_native_archive_size')
            path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(item))
        for lane in LANES:
            result=subprocess.run([sys.executable,str(ROOT/'certification/terminal_reconciliation.py'),
                '--lane',lane,'--root',str(root/lane),'--source-root',str((Path(worktrees)/lane).resolve())],
                text=True,capture_output=True,timeout=45)
            proof=json.loads(result.stdout)
            if result.returncode or proof.get('verified') is not True or proof.get('open_positions')!=0:
                raise ValueError('program_retirement_native_unresolved:'+lane+':'+str(proof.get('error_type','ledger_or_exposure')))
            proofs[lane]=proof
    return proofs


def retire(api,run_id,prior_sha,prior_cohort,prior_ph,proto,worktrees=None):
    prior=deepcopy(proto);prior['cohort_id']=prior_cohort
    def pause(state):
        if state is None or state.get('current_workflow_run_id')!=int(run_id):
            raise ValueError('program_retirement_owner')
        if state['phase']=='HALTED':return state
        state.update(phase='HALTED',halt_reason='superseded_collection_controls',
                     next_action='finish_existing_positions_then_certify_successor')
        state['history'].append(dict(at=time.time(),action='retire_after_preserving_existing_work',workflow_run_id=int(run_id)))
        return state
    commit_transition(api,prior,prior_sha,prior_ph,pause)
    deadline=time.monotonic()+3600;cancel_requested=False
    while time.monotonic()<deadline:
        run=api.request('GET',f'actions/runs/{int(run_id)}')
        if run['head_sha']!=prior_sha or run['head_branch']!=CANONICAL_BRANCH:
            raise ValueError('program_retirement_source')
        jobs=api.pages(f'actions/runs/{int(run_id)}/jobs','jobs')
        action=retirement_action(run,jobs)
        if action=='cancel_before_new_admission' and not cancel_requested:
            # The smoke job uploads evidence only after its flat/native gates pass.
            api.request('POST',f'actions/runs/{int(run_id)}/cancel');cancel_requested=True
        if action=='verify_terminal':
            hourly=next((j for j in jobs if j['name']=='hourly-campaign'),{})
            market=next((s for s in hourly.get('steps',[]) if s['name'].startswith('One-hour continuous paper campaign')), {})
            observed=market.get('conclusion') not in (None,'skipped')
            phase='hourly' if observed else 'smoke'
            prefix='four-lane-hourly' if observed else 'four-lane-certification'
            archive,item=api.artifact(run_id,f'{prefix}-{run_id}-{run["run_attempt"]}')
            result=_member(archive,f'certification-{phase}/result.json')
            identity=(result.get('integration_sha')==prior_sha and set(result.get('lanes',{}))==set(LANES))
            native_proofs=replay_retirement_books(archive,phase,worktrees) if identity and worktrees else None
            flat=identity and (native_proofs is not None or all(
                row.get('open_positions')==0 and row.get('accounting_reconciled') is True
                for row in result['lanes'].values()))
            if flat:return dict(phase='RETIRED',prior_sha=prior_sha,prior_run=int(run_id),
                terminal_artifact_id=item['id'],terminal_artifact_digest=item['digest'],verified_flat=True,
                native_replay=native_proofs,original_engineering_result=result.get('smoke_engineering'),
                next_action='certify_successor',prior_evidence_preserved=True)
            raise ValueError('program_retirement_exposure_unresolved')
        time.sleep(5)
    raise ValueError('program_retirement_wait_bound; existing positions must continue')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('certificate','start','claim','advance','halt','review','retire'))
    parser.add_argument('--run-id');parser.add_argument('--worktrees');parser.add_argument('--output')
    parser.add_argument('--base-reviewed',action='store_true')
    parser.add_argument('--prior-sha');parser.add_argument('--prior-cohort');parser.add_argument('--prior-protocol-sha')
    parser.add_argument('--record');parser.add_argument('--reason',default='workflow_failure_or_missing_evidence')
    a=parser.parse_args();api=GitHub();proto,ph=protocol();sha=git('rev-parse','HEAD')
    if os.environ.get('EXPECTED_SHA',sha)!=sha:raise ValueError('program_checkout_identity')
    if a.command=='certificate':
        receipt=certificate(api,a.run_id,sha,a.worktrees)
        path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(canonical(receipt)+'\n');return
    if a.command=='retire':
        state=retire(api,a.run_id,a.prior_sha,a.prior_cohort,a.prior_protocol_sha,proto,a.worktrees)
    elif a.command=='review':
        state,_=commit_transition(api,proto,sha,ph,lambda s:s)
        if state is None:raise ValueError('program_state_missing')
        state['evaluation']=evaluate(state['records'],proto,ph,sha)
        state['promotion_eligible']=state['phase']=='EVALUATED' and state['evaluation']['promotion_eligible']
    elif a.command=='start':
        certificate(api,a.run_id,sha)
        state,_=commit_transition(api,proto,sha,ph,lambda s:s or initial_state(sha,a.run_id,proto,ph,time.time()))
        api.request('PATCH','git/refs/heads/'+CANONICAL_BRANCH,dict(sha=sha,force=False))
        state=dispatch(api,proto,sha,ph)
    elif a.command=='claim':
        run_id=int(os.environ['GITHUB_RUN_ID']);nonce=os.environ['DISPATCH_ID']
        def claim(state):
            if state is None:raise ValueError('program_state_missing')
            if state.get('dispatch_id')!=nonce:raise ValueError('program_dispatch_identity')
            if state['phase']=='RUNNING' and state.get('current_workflow_run_id')==run_id:return state
            if state['phase']!='DISPATCH_PENDING':raise ValueError('program_dispatch_already_claimed')
            state.update(phase='RUNNING',current_workflow_run_id=run_id,next_action='smoke_then_hourly')
            return state
        state,_=commit_transition(api,proto,sha,ph,claim)
    elif a.command=='halt':
        owner=int(os.environ.get('CAMPAIGN_RUN_ID') or os.environ['GITHUB_RUN_ID'])
        def halt(state):
            if state is None:raise ValueError('program_state_missing')
            if state.get('current_workflow_run_id')!=owner:raise ValueError('program_foreign_halt')
            if state['phase']=='HALTED':return state
            state.update(phase='HALTED',halt_reason=a.reason,next_action='preserve_repair_recertify_successor_cohort')
            state['history'].append(dict(at=time.time(),action='halt',workflow_run_id=os.environ['GITHUB_RUN_ID'],reason=a.reason))
            return state
        state,_=commit_transition(api,proto,sha,ph,halt)
    else:
        record=json.loads(Path(a.record).read_text())
        event_id=os.environ['GITHUB_RUN_ID']+':'+os.environ.get('GITHUB_RUN_ATTEMPT','1')+':'+Path(a.record).name
        state,_=commit_transition(api,proto,sha,ph,
            lambda s:reduce_record(s,record,event_id,proto,ph,time.time(),a.base_reviewed))
        state=dispatch(api,proto,sha,ph)
    if a.output:Path(a.output).write_text(json.dumps(state,sort_keys=True,indent=2)+'\n')
    print(json.dumps({k:state.get(k) for k in ('phase','integration_sha','cohort_id','current_workflow_run_id','next_action')}))


if __name__=='__main__':main()
