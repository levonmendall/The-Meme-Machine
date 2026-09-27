"""One bounded position-only window, reusing the native continuation runners."""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from certification import campaign_state
from certification.autonomous_window import read, bound_window, stage
from certification.journal import digest
from certification.position_continuation import _atomic
from certification.run import ROOT, lane_environment, manifest


def native_proof(lane, root, source):
    result=subprocess.run([sys.executable,str(ROOT/'certification/terminal_reconciliation.py'),
        '--lane',lane,'--root',str(root),'--source-root',str(source)],capture_output=True,text=True,timeout=120)
    proof=json.loads(result.stdout)
    if result.returncode or proof.get('verified') is not True:
        raise ValueError('autonomous_position_native_replay:'+lane)
    return proof


def live_ids(snapshot):
    return sorted(identity for identity,row in snapshot['positions'].items()
        if row.get('status') not in ('settled','cancelled','written_off'))


def run(claim, worktrees, output, previous):
    from certification.autonomous_control import REVIEW_GATES
    from certification.evidence_supervisor import EvidenceProcess
    from certification.market_assurance import native_positions,continuity
    from certification.controls import evidence_continuity
    from meme_machine.solana_evidence_health import HealthWatch
    output=Path(output);worktrees=Path(worktrees);window=claim['window']
    if (window['mode']!='position' or window['entry_authority'] is not False
            or set(window['positions'])!=set(campaign_state.LANES) or not any(window['positions'].values())):
        raise ValueError('autonomous_position_only_authority')
    state=output/'position-state';state.mkdir();native=state/'certification-native/position'
    runtime=state/'certification-position';runtime.mkdir()
    capsule=campaign_state.verify(Path(previous)/'capsule',expected_identity=claim['identity'],
        expected_state_hash=window['parent_state_hash'],campaign_id=claim['campaign_id'],
        prior_index=window['index']-1,authorization_hash=claim['authorization_hash'])
    campaign_state.restore(Path(previous)/'capsule',worktrees=native,run=runtime,
        expected_identity=claim['identity'],expected_state_hash=window['parent_state_hash'],
        campaign_id=claim['campaign_id'],prior_index=window['index']-1,authorization_hash=claim['authorization_hash'])
    _atomic(state/'autonomous-position-authority.json',claim)
    _atomic(runtime/'prior-native-result.json',capsule['terminal'])
    spec=manifest();before={};proofs={}
    for lane in campaign_state.LANES:
        proofs[lane]=native_proof(lane,native/lane,worktrees/lane)
        before[lane]=native_positions(native/lane,lane)
        if before[lane]['violations'] or live_ids(before[lane])!=sorted(window['positions'][lane]):
            raise ValueError('autonomous_position_set_drift:'+lane)
        if window['positions'][lane] and proofs[lane].get('durable_handoff') is not True:
            raise ValueError('autonomous_position_controller_unproven:'+lane)
    _atomic(output/'position-before.json',before)
    active=[lane for lane in campaign_state.LANES if window['positions'][lane]]
    solana=[lane for lane in active if lane in ('pump','meteora')]
    evidence=None;shutdown=None;snapshot=None;processes={};files={};outcomes={};watches={}
    started=time.time();deadline=time.monotonic()+window['seconds']+300
    try:
        if solana:
            env=lane_environment('pump',spec['lanes']['pump'],runtime,window['native_run_id'],'position_continuation')
            evidence=EvidenceProcess(runtime,worktrees/'pump',env);evidence.start()
            watches={lane:HealthWatch(time.monotonic()) for lane in solana}
        for lane in active:
            folder=runtime/lane;folder.mkdir();audit=folder/'audit'
            env=lane_environment(lane,spec['lanes'][lane],runtime,window['native_run_id'],'position_continuation')
            env['MM_CONTINUATION_LANE_ROOT']=str(worktrees/lane)
            env['MM_AUTONOMOUS_POSITION_STATE']=str(state)
            command=[sys.executable,'-m','certification.position_continuation','--lane',lane,
                '--state-dir',str(state),'--slice-seconds',str(window['seconds']),
                '--output',str(folder/'position-continuation-result.json'),'--audit-output',str(audit)]
            if solana:command.append('--shared-evidence')
            stream=(folder/'process.log').open('wb');files[lane]=stream
            processes[lane]=subprocess.Popen(command,cwd=worktrees/lane,env=env,stdout=stream,
                                             stderr=subprocess.STDOUT,start_new_session=True)
        while any(process.poll() is None for process in processes.values()):
            if time.monotonic()>deadline:raise TimeoutError('autonomous_position_drain_deadline')
            if evidence is not None:
                health=evidence.check()
                for lane,watch in watches.items():
                    watch.observe((health.get('lanes') or {}).get(lane,dict(usable=False,reason='missing_health')),time.monotonic())
                    if watch.failure:raise ValueError('autonomous_position_evidence_unusable:'+lane)
            if any(process.poll() not in (None,0) for process in processes.values()):
                raise ValueError('autonomous_position_process_failed')
            time.sleep(.5)
        for lane,process in processes.items():
            if process.returncode!=0:raise ValueError('autonomous_position_process_failed:'+lane)
            outcomes[lane]=read(runtime/lane/'position-continuation-result.json')
    finally:
        for process in processes.values():
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGINT)
                except ProcessLookupError:pass
        for process in processes.values():
            if process.poll() is None:
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    process.wait(timeout=5)
        for stream in files.values():stream.close()
        if evidence is not None:
            snapshot=evidence.snapshot();shutdown=evidence.close()
    after={lane:native_positions(native/lane,lane) for lane in campaign_state.LANES}
    proofs={lane:native_proof(lane,native/lane,worktrees/lane) for lane in campaign_state.LANES}
    transfers={lane:continuity(before[lane],after[lane]) for lane in campaign_state.LANES}
    positions={lane:live_ids(after[lane]) for lane in campaign_state.LANES}
    _atomic(output/'position-after.json',after);_atomic(output/'position-continuity.json',transfers)
    no_new_entries=all(set(after[lane]['positions'])==set(before[lane]['positions']) and
        after[lane]['natural_entries']==before[lane]['natural_entries'] for lane in campaign_state.LANES)
    health_failures=[]
    for lane in solana:
        health_failures.extend(evidence_continuity({},lane,snapshot)['failures'])
    for lane,outcome in outcomes.items():
        if outcome.get('last_provider_boundary'):health_failures.append(lane+':'+outcome['last_provider_boundary'])
        if (outcome.get('reason') not in (None,'continuation_slice_complete')
                and outcome.get('handoff_required')):health_failures.append(lane+':'+outcome['reason'])
        if any((outcome.get('pump_current') or {}).get('monitor_failures',{}).values()):
            health_failures.append(lane+':current_monitor_failure')
    terminal=dict(status='FINISHED',phase='position_continuation',run_id=str(window['workflow_run_id']),
        started_at=started,ended_at=time.time(),**{key:claim['identity'][key] for key in
        ('integration_sha','implementation_hash','source_manifest_hash','source_diff_hashes')},
        campaign_window=bound_window(claim),native_run_id=window['native_run_id'],entry_authority=False,
        shared_provider=dict(solana_evidence_plane=snapshot),evidence_service_shutdown=shutdown,
        lanes={lane:dict(exit_code=0,unexpected_exit=False,open_positions=proofs[lane]['open_positions'],
            accounting_reconciled=True,terminal_reconciliation=proofs[lane]) for lane in campaign_state.LANES})
    _atomic(runtime/'result.json',terminal)
    # Stage unchanged flat books too, so all capital and attributed regimes cross
    # the boundary together. No provider/discovery runner is started for flat lanes.
    artifact=stage(native,state,'position')
    artifact.rename(output/'artifact')
    capsule=campaign_state.seal(output/'capsule',worktrees=native,run=runtime,
        window=bound_window(claim),terminal=terminal,expected_identity=claim['identity'],
        discovery_window=capsule['discovery_window'])
    gates=dict(identity=True,engineering=all(r.get('assurance_passed') is True for r in outcomes.values()),
        native_assurance=all(p['verified'] is True for p in proofs.values()),evidence_snapshot=True,state_capsule=True,
        accounting=all(proofs[lane]['open_positions']==len(positions[lane]) for lane in campaign_state.LANES),
        position_continuity=all(r['status']=='pass' for r in transfers.values()) and no_new_entries,
        no_infrastructure_censoring=not health_failures and (shutdown is None or shutdown.get('clean') is True),
        paper_only=no_new_entries and all(set(positions[lane])<=set(window['positions'][lane]) for lane in campaign_state.LANES))
    if set(gates)!=REVIEW_GATES:raise AssertionError('position_review_gate_set')
    review=dict(identity=claim['identity'],mode='position',entry_authority=False,state_hash=capsule['state_hash'],
        open_positions=positions,gates=gates,passed=all(gates.values()),infrastructure_censoring=health_failures,
        continuation_results={lane:digest(row) for lane,row in outcomes.items()})
    _atomic(output/'window-review.json',review)
    if not review['passed']:raise ValueError('autonomous_position_review_failed')
    smoke_state=read(output/'smoke-continuation-state.json')
    from certification.smoke_continuation import complete
    for lane,outcome in outcomes.items():
        if lane in smoke_state.get('smoke_pending_lanes',[]) and not positions[lane]:
            proof=deepcopy(outcome)
            proof.update(accounting=proofs[lane]['accounting'],terminal_replay_verified=True,
                         runtime_identity=dict(integration_sha=claim['identity']['integration_sha']))
            smoke_state=complete(smoke_state,proof,smoke_state['smoke_evidence_run_id'],
                                 str(window['workflow_run_id'])+':'+lane)
    _atomic(output/'smoke-continuation-state.json',smoke_state)
    return review
