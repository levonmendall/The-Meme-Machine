"""Workflow adapter for the existing four-lane runtime and position continuation."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys

from certification import autonomous_control as control, campaign_state
from certification.journal import digest
from certification.position_continuation import _atomic
from certification.prospective_program import GitHub, certificate
from certification.run import ROOT, git, source_integrity
from certification.single_campaign_control import checkout_files, first_attempt


def read(path):
    return json.loads(Path(path).read_text())


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def exact_checkout():
    first_attempt(os.environ['GITHUB_RUN_ATTEMPT'])
    expected=os.environ['EXPECTED_SHA']
    checkout_files(expected)
    value=campaign_state.identity()
    if value['integration_sha']!=expected or os.environ.get('GITHUB_SHA')!=expected:
        raise ValueError('autonomous_checkout_or_workflow_sha')
    return value


def extract_artifact(api, reference, destination):
    archive,item=api.artifact(reference['workflow_run_id'],reference['name'])
    if item['id']!=reference['id'] or item['digest']!=reference['digest']:
        raise ValueError('autonomous_download_artifact_identity')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    names=set();size=0
    # Bound decompression separately from the existing 512-MiB ZIP transport bound.
    # These are artifact safeguards, not relaxed runtime hot-storage limits.
    with archive:
        for member in archive.infolist():
            path=PurePosixPath(member.filename);size+=member.file_size
            if (path.is_absolute() or '..' in path.parts or '\\' in member.filename
                    or member.filename in names or stat.S_ISLNK(member.external_attr>>16)
                    or size>8*1024**3 or len(names)>=50000):
                raise ValueError('autonomous_artifact_path_or_size')
            names.add(member.filename)
        archive.extractall(destination)
    return destination


def verify_snapshot(artifact):
    artifact=Path(artifact);snapshot=read(artifact/'evidence-snapshot.json')
    if snapshot.get('snapshot_complete') is not True or snapshot.get('cancelled'):
        raise ValueError('autonomous_snapshot_incomplete')
    for row in snapshot['files']:
        if row.get('error_type'):raise ValueError('autonomous_snapshot_incomplete')
        if 'target' not in row:continue
        name=PurePosixPath(row['target'])
        if name.is_absolute() or '..' in name.parts:raise ValueError('autonomous_snapshot_path')
        path=artifact/name
        if (not path.is_file() or path.is_symlink() or path.stat().st_size!=row['bytes']
                or checksum(path)!=row['sha256']):raise ValueError('autonomous_snapshot_hash')
    return snapshot


def stage(worktrees, output, phase):
    from certification.archive_native import stage as native_stage
    artifact=Path(output)/'artifact'
    snapshot=native_stage(worktrees,output,artifact,phase)
    for row in snapshot['files']:
        if 'target' in row:row['target']=str(Path(row['target']).relative_to(artifact))
    _atomic(artifact/'evidence-snapshot.json',snapshot)
    verify_snapshot(artifact)
    return artifact


def claimed(api, claim):
    expected=exact_checkout()
    if claim.get('identity')!=expected or claim.get('campaign_id')!=os.environ['AUTONOMOUS_CAMPAIGN']:
        raise ValueError('autonomous_claim_identity')
    state=control.store_for(api,claim['campaign_id']).read();control._bound(state,expected)
    if (state['phase'] not in ('PAPER_WINDOW_RUNNING','POSITION_WINDOW_RUNNING')
            or state['window']!=claim.get('window')
            or state['authorization_hash']!=claim.get('authorization_hash')
            or state['window']['workflow_run_id']!=int(os.environ['GITHUB_RUN_ID'])
            or state.get('previous')!=claim.get('previous')):
        raise ValueError('autonomous_claim_not_current')
    control._run(api,int(os.environ['GITHUB_RUN_ID']),state)
    control.contention(api,exclude_run=int(os.environ['GITHUB_RUN_ID']))
    return state


def bound_window(claim):
    w=claim['window']
    row=dict(campaign_id=claim['campaign_id'],index=w['index'],workflow_run_id=w['workflow_run_id'],
        native_run_id=w['native_run_id'],authorization_hash=claim['authorization_hash'])
    if w['index']:row['parent_state_hash']=w['parent_state_hash']
    return row


def normal_review(claim, output, worktrees, previous=None):
    from certification.controls import smoke_engineering,hourly_engineering
    from certification.market_assurance import audit
    output=Path(output);phase=claim['window']['mode'];runtime=output/('certification-'+phase)
    result=read(runtime/'result.json');artifact=stage(worktrees,output,phase)
    prior_assurance=None
    if previous:
        prior_assurance=Path(previous)/'artifact/assurance/market-assurance.json'
        if not prior_assurance.is_file():
            snapshots=read(Path(previous)/'position-after.json')
            if set(snapshots)!=set(control.LANES):raise ValueError('autonomous_prior_positions_missing')
            prior_assurance=output/'prior-position-snapshots.json'
            _atomic(prior_assurance,dict(lanes={lane:dict(snapshot=row) for lane,row in snapshots.items()}))
    assurance=audit(artifact,worktrees,artifact/'assurance',previous=prior_assurance)
    capsule=campaign_state.seal(output/'capsule',worktrees=worktrees,run=runtime,
        window=bound_window(claim),terminal=result,expected_identity=claim['identity'])
    campaign_state.verify(output/'capsule',expected_identity=claim['identity'],expected_state_hash=capsule['state_hash'],
        campaign_id=claim['campaign_id'],prior_index=claim['window']['index'],authorization_hash=claim['authorization_hash'])
    positions={lane:sorted(identity for identity,row in assurance['lanes'][lane]['snapshot']['positions'].items()
        if row.get('status') not in ('settled','cancelled','written_off')) for lane in control.LANES}
    engineering=(smoke_engineering(result) if phase=='smoke' else hourly_engineering(result))
    infrastructure_classes={'provider_failed','capacity_censored','consumer_deadline','local_budget_exhausted',
                            'reconstruction_incomplete','stream_coverage_loss','pipeline_unavailable',
                            'discovery_acquisition_failure','frozen_source_union_not_fully_observed'}
    failures={lane:sorted(set(row.get('coverage_gaps',[]))&infrastructure_classes)
              for lane,row in assurance['lanes'].items()}
    gates=dict(identity=all(result.get(key)==claim['identity'][key] for key in
        ('integration_sha','implementation_hash','source_manifest_hash','source_diff_hashes')),
        engineering=engineering['status']=='PASS',native_assurance=assurance['operational_validity']=='valid',
        evidence_snapshot=True,state_capsule=True,
        accounting=all(proof.get('verified') is True and proof.get('open_positions')==len(positions[lane])
                       for lane,proof in capsule['accounting'].items()),
        position_continuity=all(row['position_watchdog']['status']=='pass'
                               for row in assurance['lanes'].values()),
        no_infrastructure_censoring=not any(failures.values()),
        paper_only=all(row.get('gates',{}).get('paper_only') is True for row in result['lanes'].values()))
    review=dict(identity=claim['identity'],mode=phase,entry_authority=True,state_hash=capsule['state_hash'],
        open_positions=positions,gates=gates,passed=all(gates.values()),engineering=engineering,
        infrastructure_censoring=failures,assurance_hash=digest(assurance))
    _atomic(output/'window-review.json',review)
    from certification.smoke_continuation import register
    if phase=='smoke':
        smoke_state=register(dict(current_workflow_run_id=claim['window']['workflow_run_id'],
            integration_sha=claim['identity']['integration_sha'],history=[]),result,assurance,
            dict(id=0,digest='not_uploaded_yet'),claim['window']['workflow_run_id'])
        # Retain all modern liveness fields; the reusable readiness validator
        # evaluates the original smoke plus independently proven continuations.
        smoke_state['smoke_readiness']=deepcopy(result)
        _atomic(output/'smoke-continuation-state.json',smoke_state)
    if not review['passed']:raise ValueError('autonomous_native_window_review_failed')
    return review


def run_window(api, claim, worktrees, output):
    state=claimed(api,claim);output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    _atomic(output/'claim.json',claim)
    expected=claim['identity'];worktrees=Path(worktrees).resolve()
    if source_integrity(worktrees)!=expected['source_diff_hashes']:
        raise ValueError('autonomous_prepared_source_identity')
    gates=output/'certification-gates';gates.mkdir()
    receipt=certificate(api,state['authorization']['certificate']['full_nonmarket_run_id'],expected['integration_sha'],worktrees)
    if receipt!=state['authorization']['certificate']:raise ValueError('autonomous_certificate_changed')
    _atomic(gates/'deterministic.json',receipt)
    previous=None
    if claim['previous']:
        previous=extract_artifact(api,claim['previous']['artifact'],output.parent/'predecessor')
        capsule=campaign_state.verify(previous/'capsule',expected_identity=expected,
            expected_state_hash=claim['previous']['state_hash'],campaign_id=claim['campaign_id'],
            prior_index=claim['previous']['index'],authorization_hash=claim['authorization_hash'])
        review=read(previous/'window-review.json')
        if digest(review)!=claim['previous']['review_hash'] or review.get('passed') is not True:
            raise ValueError('autonomous_predecessor_review_hash')
        if (previous/'artifact/evidence-snapshot.json').exists():verify_snapshot(previous/'artifact')
        smoke_state=read(previous/'smoke-continuation-state.json')
        if claim.get('smoke_review'):
            smoke_state['smoke_artifact']=claim['smoke_review']['artifact']
        _atomic(output/'smoke-continuation-state.json',smoke_state)
    phase=claim['window']['mode']
    # Existing authenticated endpoint probes run only after exact controller claim.
    for command in ([sys.executable,'-m','certification.chain_binding','--output',str(gates/'chain-binding.json')],
                    [sys.executable,'-m','certification.capabilities','--worktrees',str(worktrees),'--output',str(gates/'rpc-capabilities.json')]):
        subprocess.run(command,cwd=ROOT,check=True,timeout=180)
    if phase=='position':
        from certification.autonomous_positions import run
        return run(claim,worktrees,output,previous)
    smoke_path=None
    if phase=='hourly':
        from certification.smoke_continuation import readiness
        smoke_state=read(output/'smoke-continuation-state.json')
        smoke=readiness(smoke_state,smoke_state['smoke_evidence_run_id'])
        smoke_path=output/'smoke-readiness.json';_atomic(smoke_path,smoke)
    from certification.run import launch
    try:
        launch(worktrees,output/('certification-'+phase),claim['window']['seconds'],phase,
               gates/'deterministic.json',smoke_path,campaign_claim=claim,
               prior_state=previous/'capsule' if previous else None)
    except BaseException:
        if (output/('certification-'+phase)).exists():
            stage(worktrees,output,phase)
        raise
    return normal_review(claim,output,worktrees,previous)


def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=('control','run','finish'))
    p.add_argument('--claim');p.add_argument('--worktrees');p.add_argument('--output',required=True)
    a=p.parse_args();api=GitHub();expected=exact_checkout();campaign=os.environ['AUTONOMOUS_CAMPAIGN']
    run_id=int(os.environ['GITHUB_RUN_ID']);attempt=os.environ['GITHUB_RUN_ATTEMPT']
    if a.operation=='control':
        operation=os.environ['OPERATION']
        if operation=='authorize':
            value=control.authorize(api,expected,campaign,os.environ['GITHUB_REF_NAME'],
                int(os.environ['CERTIFICATE_RUN']),run_id,attempt=attempt,
                maximum_windows=int(os.environ.get('MAXIMUM_WINDOWS') or control.MAX_WINDOWS))
            _atomic(Path(a.output),value)
            value=control.dispatch_next(api,expected,campaign,run_id,attempt=attempt)
        elif operation=='accept':
            value=control.accept_smoke(api,expected,campaign,os.environ['REVIEWED_ARTIFACT_DIGEST'],run_id,attempt=attempt)
            _atomic(Path(a.output),value)
            value=control.dispatch_next(api,expected,campaign,run_id,attempt=attempt)
        elif operation=='window':
            value=control.claim(api,expected,campaign,os.environ['DISPATCH_NONCE'],run_id,attempt=attempt)
            name=f'autonomous-paper-{campaign}-{value["window"]["index"]}-{run_id}'
            with Path(os.environ['GITHUB_ENV']).open('a') as stream:stream.write('AUTONOMOUS_ARTIFACT_NAME='+name+'\n')
        else:raise ValueError('autonomous_operation')
        _atomic(Path(a.output),value)
    elif a.operation=='run':run_window(api,read(a.claim),a.worktrees,a.output)
    else:
        claim=read(a.claim);claimed(api,claim);output=Path(a.output)
        if os.environ['WINDOW_JOB_RESULT']!='success':
            value=control.halt(api,expected,campaign,run_id,'workflow_or_native_window_failed')
        else:
            state=control.store_for(api,campaign).read()
            artifact=control._artifact_metadata(api,run_id,control.artifact_name(state,run_id))
            value=control.finish(api,expected,campaign,run_id,capsule=read(output/'capsule/campaign-state.json'),
                review=read(output/'window-review.json'),artifact=artifact)
            _atomic(Path('autonomous-controller.json'),value)
            if value['phase']!='SMOKE_REVIEW':
                value=control.dispatch_next(api,expected,campaign,run_id,attempt=attempt)
        _atomic(Path('autonomous-controller.json'),value)


if __name__=='__main__':main()
