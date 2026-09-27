"""Durable, exact-source PAPER window authority; no implicit dispatch retries.

Native state is separate from entry authority. This controller reuses the Git-ref
CAS and repository-wide market contention inventory used by the one-shot runner.
It never alters that runner's independent one-shot authorization contract.
"""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from certification.campaign_state import LANES, identity
from certification.journal import digest
from certification.run import ROOT
from certification.single_campaign_control import StateStore, contention, first_attempt

SCHEMA = 'autonomous-paper-controller-v1'
WORKFLOW = 'autonomous-paper.yml'
WORKFLOW_PATH = '.github/workflows/' + WORKFLOW
STATE_PATH = 'certification/AUTONOMOUS_PAPER_STATE.json'
MAX_WINDOWS = 168
NORMAL_SECONDS = 3600
POSITION_SECONDS = 3000
REVIEW_GATES = frozenset(('identity', 'engineering', 'native_assurance', 'evidence_snapshot',
                         'state_capsule', 'accounting', 'position_continuity',
                         'no_infrastructure_censoring', 'paper_only'))


def campaign_id(value):
    if not re.fullmatch('[a-z0-9-]{8,100}', value or ''):
        raise ValueError('autonomous_campaign_id')
    return value


def store_for(api, campaign):
    campaign_id(campaign)
    return StateStore(api, {'authorization_id': campaign},
                      ref='state/autonomous-paper-' + digest(campaign)[:24], path=STATE_PATH)


def _bound(state, expected):
    if (not state or state.get('schema') != SCHEMA or state.get('identity') != expected
            or expected.get('paper_only') is not True or expected.get('live_money') is not False
            or state.get('authorization_hash') != digest(state.get('authorization'))
            or state['authorization'].get('identity') != expected
            or state['authorization'].get('campaign_id') != state.get('campaign_id')):
        raise ValueError('autonomous_authority_identity')


def workflow_contract(api, runtime_ref, expected):
    """A registered workflow AND its exact dispatch-ref bytes must be available."""
    if not re.fullmatch('cert/autonomous-paper-[a-z0-9-]+', runtime_ref or ''):
        raise ValueError('autonomous_runtime_ref')
    sha = expected['integration_sha']
    ref = api.request('GET', 'git/ref/heads/' + runtime_ref)
    if ref['object']['sha'] != sha:
        raise ValueError('autonomous_runtime_ref_drift')
    registered = api.request('GET', 'actions/workflows/' + WORKFLOW)
    if registered.get('state') != 'active' or registered.get('path') != WORKFLOW_PATH:
        raise ValueError('autonomous_workflow_unavailable')
    file = api.request('GET', 'contents/' + WORKFLOW_PATH + '?ref=' + sha)
    local = (ROOT / WORKFLOW_PATH).read_bytes()
    raw = base64.b64decode(file['content'], validate=False)
    if file.get('encoding') != 'base64' or raw != local:
        raise ValueError('autonomous_workflow_contract_drift')
    return dict(workflow_id=registered['id'], ref=runtime_ref, sha=sha,
                workflow_sha256=hashlib.sha256(raw).hexdigest())


def _event(state, action, **detail):
    # Full history is the append-only Git commit chain, not an expanding hot blob.
    state['recent_events'] = (state.get('recent_events', []) + [
        dict(action=action, at=time.time(), **detail)])[-32:]


def _artifact_metadata(api, run_id, name):
    from certification.single_campaign_control import all_pages
    rows = all_pages(api, f'actions/runs/{int(run_id)}/artifacts', 'artifacts')
    found = [row for row in rows if row.get('name') == name]
    if (len(found) != 1 or found[0].get('expired')
            or not re.fullmatch('sha256:[0-9a-f]{64}', found[0].get('digest', ''))):
        raise ValueError('autonomous_artifact_not_preserved')
    row = found[0]
    return dict(id=row['id'], name=name, digest=row['digest'], workflow_run_id=int(run_id))


def artifact_name(state, run_id):
    return f'autonomous-paper-{state["campaign_id"]}-{state["window"]["index"]}-{int(run_id)}'


def _run(api, run_id, state, *, terminal=False):
    run = api.request('GET', f'actions/runs/{int(run_id)}')
    if (run.get('head_sha') != state['identity']['integration_sha']
            or run.get('head_branch') != state['runtime_ref']
            or run.get('path', '').split('@')[0] != WORKFLOW_PATH
            or run.get('event') != 'workflow_dispatch' or str(run.get('run_attempt')) != '1'):
        raise ValueError('autonomous_workflow_run_identity')
    if terminal and (run.get('status') != 'completed' or run.get('conclusion') != 'success'):
        raise ValueError('autonomous_predecessor_not_terminal_success')
    return run


def authorize(api, expected, campaign, runtime_ref, certificate_run_id, actor_run,
              *, attempt='1', maximum_windows=MAX_WINDOWS):
    """Consume explicit authority once; first market dispatch is the smoke only."""
    from certification.prospective_program import certificate
    first_attempt(attempt); campaign_id(campaign)
    if type(maximum_windows) is not int or not 2 <= maximum_windows <= MAX_WINDOWS:
        raise ValueError('autonomous_window_bound')
    store = store_for(api, campaign)
    if store.read() is not None:
        raise ValueError('autonomous_authorization_consumed')
    contract = workflow_contract(api, runtime_ref, expected)
    cert_run = api.request('GET', f'actions/runs/{int(certificate_run_id)}')
    if cert_run.get('status') != 'completed' or cert_run.get('conclusion') != 'success':
        raise ValueError('autonomous_certificate_not_terminal_success')
    receipt = certificate(api, certificate_run_id, expected['integration_sha'])
    for key in ('integration_sha', 'implementation_hash', 'source_manifest_hash', 'source_diff_hashes'):
        if receipt.get(key) != expected[key]:
            raise ValueError('autonomous_certificate_identity:' + key)
    if expected.get('paper_only') is not True or expected.get('live_money') is not False:
        raise ValueError('autonomous_paper_only')
    authorization = dict(campaign_id=campaign, identity=expected, certificate=receipt,
                         maximum_normal_windows=maximum_windows,
                         normal_seconds=NORMAL_SECONDS, position_seconds=POSITION_SECONDS,
                         reviewed_smoke_required=True, retry_allowed=False)
    state = dict(schema=SCHEMA, campaign_id=campaign, identity=expected,
                 authorization=authorization, authorization_hash=digest(authorization),
                 runtime_ref=runtime_ref, workflow_contract=contract, phase='SMOKE_READY',
                 smoke_accepted=False, normal_windows_completed=0, window=None,
                 previous=None, created_at=time.time(), recent_events=[])
    _run(api, actor_run, state)
    contention(api, exclude_run=actor_run)
    _event(state, 'authorization_consumed', actor_run=int(actor_run))
    store.write(state)
    return state


def dispatch_next(api, expected, campaign, actor_run, *, attempt='1'):
    """One CAS, then at most one POST. A retained intent is never posted again."""
    first_attempt(attempt)
    store = store_for(api, campaign); state = store.read(); _bound(state, expected)
    if state['phase'] not in ('SMOKE_READY', 'AUTONOMOUS_PAPER_READY', 'POSITION_CONTINUATION'):
        raise ValueError('autonomous_dispatch_not_ready_or_already_consumed')
    _run(api, actor_run, state)
    if state['phase'] != 'SMOKE_READY' and state.get('smoke_accepted') is not True:
        raise ValueError('autonomous_smoke_review_required')
    state['workflow_contract'] = workflow_contract(api, state['runtime_ref'], expected)
    previous = state.get('previous')
    if previous:
        actual = _artifact_metadata(api, previous['workflow_run_id'], previous['artifact']['name'])
        if actual != previous['artifact']:
            raise ValueError('autonomous_predecessor_artifact_drift')
        # The owned predecessor may dispatch once in its tail. Its child cannot
        # claim until the whole predecessor has completed successfully.
        if int(actor_run) != previous['workflow_run_id']:
            _run(api, previous['workflow_run_id'], state, terminal=True)
    contention(api, exclude_run=actor_run)
    mode = ('smoke' if state['phase'] == 'SMOKE_READY' else
            'position' if state['phase'] == 'POSITION_CONTINUATION' else 'hourly')
    if mode == 'hourly' and state['normal_windows_completed'] >= state['authorization']['maximum_normal_windows']:
        state['phase'] = 'STOPPED'; _event(state, 'authorized_window_limit'); store.write(state); return state
    index = 0 if previous is None else previous['index'] + 1
    nonce = uuid.uuid4().hex
    inputs = dict(operation='window', expected_sha=expected['integration_sha'],
                  campaign_id=campaign, nonce=nonce)
    window = dict(index=index, mode=mode, nonce=nonce, workflow_run_id=None,
                  seconds=600 if mode == 'smoke' else POSITION_SECONDS if mode == 'position' else NORMAL_SECONDS,
                  entry_authority=mode != 'position', native_run_id=(previous or {}).get('native_run_id', str(uuid.uuid4())),
                  parent_state_hash=(previous or {}).get('state_hash'),
                  positions=(previous or {}).get('positions', {}))
    state.update(window=window, phase='HANDOFF_PENDING', dispatch_may_have_been_sent=True,
                 retry_allowed=False, dispatch_payload_hash=digest(inputs))
    _event(state, 'intent_before_dispatch', index=index, mode=mode, nonce=nonce)
    store.write(state)
    workflow_contract(api, state['runtime_ref'], expected)
    contention(api, exclude_run=actor_run)
    api.request('POST', 'actions/workflows/' + WORKFLOW + '/dispatches',
                dict(ref=state['runtime_ref'], inputs=inputs))
    return state


def claim(api, expected, campaign, nonce, run_id, *, attempt='1'):
    first_attempt(attempt)
    store = store_for(api, campaign); state = store.read(); _bound(state, expected)
    window = state.get('window') or {}
    if (state['phase'] != 'HANDOFF_PENDING' or window.get('nonce') != nonce
            or window.get('workflow_run_id') is not None):
        raise ValueError('autonomous_stale_or_duplicate_claim')
    run = _run(api, run_id, state)
    # Nonce is part of the actual workflow run-name, not inferred from timing.
    if run.get('display_title') != f'PAPER {campaign} {nonce}':
        raise ValueError('autonomous_dispatch_nonce')
    workflow_contract(api, state['runtime_ref'], expected)
    if state.get('previous'):
        prior = state['previous']; _run(api, prior['workflow_run_id'], state, terminal=True)
        if _artifact_metadata(api, prior['workflow_run_id'], prior['artifact']['name']) != prior['artifact']:
            raise ValueError('autonomous_predecessor_artifact_drift')
    contention(api, exclude_run=run_id)
    window['workflow_run_id'] = int(run_id)
    state['phase'] = 'PAPER_WINDOW_RUNNING' if window['mode'] != 'position' else 'POSITION_WINDOW_RUNNING'
    _event(state, 'window_claimed', index=window['index'], workflow_run_id=int(run_id))
    store.write(state)
    return dict(schema='autonomous-paper-window-claim-v1', identity=expected,
                campaign_id=campaign, authorization_hash=state['authorization_hash'],
                certificate=state['authorization']['certificate'], window=deepcopy(window),
                previous=deepcopy(state.get('previous')), smoke_review=deepcopy(state.get('smoke_review')))


def finish(api, expected, campaign, run_id, *, capsule, review, artifact):
    """Called only after native review and artifact upload; never trusts green alone."""
    store = store_for(api, campaign); state = store.read(); _bound(state, expected)
    window = state.get('window') or {}
    if (state['phase'] not in ('PAPER_WINDOW_RUNNING', 'POSITION_WINDOW_RUNNING')
            or window.get('workflow_run_id') != int(run_id)):
        raise ValueError('autonomous_terminal_owner')
    _run(api, run_id, state)
    bound_window = dict(campaign_id=campaign, index=window['index'], workflow_run_id=int(run_id),
                        native_run_id=window['native_run_id'], authorization_hash=state['authorization_hash'])
    if window['index']:
        bound_window['parent_state_hash'] = window['parent_state_hash']
    if (capsule.get('identity') != expected or capsule.get('window') != bound_window
            or capsule.get('state_hash') != digest({k:v for k,v in capsule.items() if k != 'state_hash'})
            or capsule.get('entry_authority') is not False):
        raise ValueError('autonomous_terminal_capsule_identity')
    discovery_window=(state['previous']['discovery_window'] if window['mode']=='position' else bound_window)
    if capsule.get('discovery_window')!=discovery_window:
        raise ValueError('autonomous_discovery_window_identity')
    if (review.get('passed') is not True or review.get('identity') != expected
            or review.get('state_hash') != capsule['state_hash']
            or review.get('mode') != window['mode']
            or review.get('entry_authority') != window['entry_authority']
            or set(review.get('gates', {})) != REVIEW_GATES
            or not all(value is True for value in review['gates'].values())):
        raise ValueError('autonomous_native_review_failed')
    actual = _artifact_metadata(api, run_id, artifact_name(state, run_id))
    if actual != artifact:
        raise ValueError('autonomous_terminal_artifact_identity')
    positions = review.get('open_positions')
    if (not isinstance(positions, dict) or set(positions) != set(LANES)
            or any(not isinstance(v, list) or len(v) != len(set(v)) for v in positions.values())):
        raise ValueError('autonomous_position_identity')
    if (set(capsule.get('accounting',{})) != set(LANES)
            or any(capsule['accounting'][lane].get('verified') is not True
                   or capsule['accounting'][lane].get('open_positions') != len(positions[lane])
                   for lane in LANES)):
        raise ValueError('autonomous_native_position_count')
    if window['mode'] == 'position' and any(set(positions[lane])-set(window['positions'][lane]) for lane in LANES):
        raise ValueError('autonomous_continuation_created_position')
    state['previous'] = dict(index=window['index'], workflow_run_id=int(run_id), artifact=actual,
        state_hash=capsule['state_hash'], native_run_id=window['native_run_id'],
        review_hash=digest(review), positions=positions, mode=window['mode'],discovery_window=discovery_window)
    if window['mode'] == 'hourly':
        state['normal_windows_completed'] += 1
    state['phase'] = ('SMOKE_REVIEW' if window['mode'] == 'smoke' else
                      'POSITION_CONTINUATION' if (any(positions.values()) and state['normal_windows_completed'] >=
                        state['authorization']['maximum_normal_windows']) else 'AUTONOMOUS_PAPER_READY')
    _event(state, 'native_review_and_artifact_preserved', index=window['index'], artifact=actual)
    store.write(state); return state


def accept_smoke(api, expected, campaign, reviewed_artifact_digest, actor_run, *, attempt='1'):
    first_attempt(attempt)
    store = store_for(api, campaign); state = store.read(); _bound(state, expected)
    if state['phase'] != 'SMOKE_REVIEW' or state.get('smoke_accepted'):
        raise ValueError('autonomous_smoke_not_awaiting_review')
    previous = state['previous']
    if previous['artifact']['digest'] != reviewed_artifact_digest:
        raise ValueError('autonomous_smoke_review_digest')
    _run(api, actor_run, state); _run(api, previous['workflow_run_id'], state, terminal=True)
    if _artifact_metadata(api, previous['workflow_run_id'], previous['artifact']['name']) != previous['artifact']:
        raise ValueError('autonomous_predecessor_artifact_drift')
    contention(api, exclude_run=actor_run)
    state.update(smoke_accepted=True, phase='AUTONOMOUS_PAPER_READY')
    state['smoke_review']=deepcopy(previous)
    _event(state, 'reviewed_smoke_accepted', artifact_digest=reviewed_artifact_digest, actor_run=int(actor_run))
    store.write(state); return state


def halt(api, expected, campaign, run_id, reason):
    store = store_for(api, campaign); state = store.read(); _bound(state, expected)
    if (state.get('window') or {}).get('workflow_run_id') != int(run_id):
        raise ValueError('autonomous_halt_owner')
    if state['phase'] not in ('PAPER_WINDOW_RUNNING', 'POSITION_WINDOW_RUNNING'):
        return state
    state.update(phase='INFRASTRUCTURE_HALT', halt_reason=str(reason)[:160])
    _event(state, 'window_halted', workflow_run_id=int(run_id), reason=state['halt_reason'])
    store.write(state); return state
