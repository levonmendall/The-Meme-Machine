"""One owner-authorized smoke -> hourly workflow, with no retry or successor.

The separate Git ref consumes the authorization before the dispatch HTTP request.
Uncertain writes/dispatch responses fail closed. No code in this module retries a
mutation, dispatches continuation, cancels a run, or resolves native exposure.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
import uuid

from certification.journal import canonical, digest
from certification.run import ROOT, git, implementation_hash, manifest
from certification.prospective_acceptance import LANES, protocol

CONFIG = ROOT / 'certification/single_campaign_authorization.json'
STATE_PATH = 'certification/SINGLE_CAMPAIGN_STATE.json'
CONTINUATION_STATE_PATH = 'certification/SINGLE_CAMPAIGN_CONTINUATION_STATE.json'
MARKET_WORKFLOW = '.github/workflows/four-lane-certification.yml'
LAUNCH_BRANCH = 'launch/certified-runtime-authority-v2'
ACTIVE_STATUSES = ('queued', 'in_progress', 'waiting', 'pending', 'requested')
OFFLINE_WORKFLOWS = {
    'non-market-certification.yml', 'evidence-reconstruction-certification.yml',
    'evidence-reconstruction-projection.yml', 'evidence-completion-repair-validation.yml',
    'four-lane-evidence-review.yml', 'four-lane-shadow-review.yml',
    'frozen-campaign-artifact-review.yml', 'frozen-campaign-deterministic-build.yml',
    'lifecycle-clock-certification.yml', 'profitability-edge-current-deterministic.yml',
    'v10-provider-pressure-nonmarket-certification.yml',
    'ramses-v4-offline-certification.yml',
    'ramses-v4-launchable-nonmarket-certification.yml',
    'v12-active-strategy-certification.yml',
    'targeted-repair-validation.yml',
}
OFFLINE_JOBS = {'test', 'tests', 'lint', 'build', 'offline-prerequisites',
                'inspect-retained-failure', 'review', 'deterministic', 'qualification'}
MARKET_WORKFLOWS = {'four-lane-certification.yml', 'position-continuation.yml',
    'single-campaign-launch.yml', 'prospective-cohort-review.yml',
    'all-market-certification.yml', 'coverage-repair-certification.yml',
    'pump-acceleration-natural-prospective.yml', 'pump-http-primary-soak.yml',
    'pump-rejected-winner-study.yml', 'pump-supply-probe.yml', 'provider-shape-probe.yml'}
CI_MARKERS = ('[forced-canary]', '[postgrad-live]', '[discovery-compare-live]',
    '[market-native-priority-live]', '[market-native-smoke-live]', '[market-native-paper-live]',
    '[market-native-cohort-live]', '[post-exit-outcome-live]', '[market-native-outcomes-live]',
    '[market-native-sample-supplement-live]', '[legacy-shadow-connectivity]')


def policy_configuration():
    """Load the certified static single-campaign policy.

    One-shot owner authorization is deliberately not stored in the runtime tree.
    It is supplied by the external launch request after the runtime has already
    been certified, so issuing fresh authority cannot invalidate that certificate.
    """
    row = json.loads(CONFIG.read_text())
    expected = dict(enabled=True, maximum_market_workflows=1,
        phases_in_same_workflow=['smoke', 'hourly'], fresh_smoke_required=True,
        automatic_successors=False, position_continuation_workflows=True,
        workflow_reruns=False, dispatch_retries=False, live_money=False)
    dynamic = ('authorization_id', 'prior_run_observation', 'prior_launch_attempt')
    if (row.get('schema') != 'meme-machine-single-campaign-policy-v2'
            or any(key in row for key in dynamic)
            or any(row.get(k) != v for k, v in expected.items())):
        raise ValueError('single_campaign_policy_invalid')
    return row


def external_authorization_id(value=None):
    value = os.environ.get('SINGLE_AUTHORIZATION_ID', '') if value is None else value
    if not re.fullmatch(r'[a-z0-9-]{8,100}', value or ''):
        raise ValueError('single_campaign_authorization_invalid')
    return value


def configuration():
    row = policy_configuration()
    value = os.environ.get('SINGLE_AUTHORIZATION_ID')
    if value is not None:
        row = dict(row, authorization_id=external_authorization_id(value))
    return row


def require_authorization(config):
    value = config.get('authorization_id')
    if value is None:
        raise ValueError('single_campaign_authorization_missing')
    return external_authorization_id(value)


def runtime_policy(config):
    """Return certificate-bound control bytes, excluding ephemeral owner authority."""
    return {key: value for key, value in config.items() if key != 'authorization_id'}


def prohibit_if_enabled(action):
    if CONFIG.exists():
        policy_configuration()  # A malformed static control cannot restore automation.
        raise ValueError('single_campaign_prohibits_' + action)


def first_attempt(attempt):
    if str(attempt) != '1':
        raise ValueError('single_campaign_rerun_prohibited')


def checkout_files(sha):
    """Require every executable/configuration byte to match its immutable commit."""
    if not re.fullmatch('[0-9a-f]{40}', sha) or git('rev-parse', 'HEAD') != sha:
        raise ValueError('single_campaign_checkout_identity')
    entries = git('ls-tree', '-r', sha, 'certification', '.github/workflows').splitlines()
    frozen = {}
    for entry in entries:
        metadata, name = entry.split('\t', 1)
        mode, kind, oid = metadata.split()
        path = ROOT / name
        if kind == 'blob' and (name.startswith('.github/workflows/') or path.suffix in ('.py', '.json', '.patch')):
            if mode not in ('100644', '100755') or not path.is_file() or path.is_symlink():
                raise ValueError('single_campaign_checkout_file:' + name)
            data = path.read_bytes()
            actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if actual != oid:
                raise ValueError('single_campaign_checkout_file:' + name)
            frozen[name] = oid
    present = {str(path.relative_to(ROOT)) for path in (ROOT / 'certification').rglob('*')
               if path.is_file() and path.suffix in ('.py', '.json', '.patch')}
    present.update(str(path.relative_to(ROOT)) for path in (ROOT / '.github/workflows').iterdir() if path.is_file())
    if present != set(frozen):
        raise ValueError('single_campaign_uncommitted_runtime_configuration')
    return digest(frozen)


def identities(sha, config):
    tree_hash = checkout_files(sha)
    proto, ph = protocol()
    spec = manifest()
    workflows = {name: (ROOT / '.github/workflows' / name).read_text() for name in (
        'four-lane-certification.yml', 'position-continuation.yml',
        'prospective-cohort-review.yml', 'single-campaign-launch.yml',
        'evidence-reconstruction-certification.yml')}
    identity = dict(integration_sha=sha, executable_git_tree_sha256=tree_hash,
        implementation_hash=implementation_hash(), protocol_sha256=ph,
        source_manifest_hash=digest(spec),
        source_diff_hashes={lane: row['source_diff_sha256'] for lane, row in spec['lanes'].items()},
        lane_policies={lane: {key: row[key] for key in ('strategy_version', 'policy_hash')}
                      for lane, row in proto['frozen_lanes'].items()},
        execution_configuration_sha256=digest(dict(authorization_policy=runtime_policy(config),
            workflows=workflows, parameters=dict(phase='hourly', program=False, fresh_smoke=True,
                                                  smoke_seconds=600, hourly_seconds=3600))))
    identity['certification_fingerprint'] = digest(identity)
    return identity


def all_pages(api, path, key):
    """Consume every page; incomplete/capped/ambiguous listings block dispatch."""
    rows = []
    seen = set()
    for page in range(1, 1001):
        data = api.request('GET', path + ('&' if '?' in path else '?') + f'per_page=100&page={page}')
        batch = data.get(key)
        if not isinstance(batch, list):
            raise ValueError('single_campaign_listing_missing')
        for row in batch:
            if not isinstance(row, dict) or row.get('id') in seen or row.get('id') is None:
                raise ValueError('single_campaign_listing_ambiguous')
            seen.add(row['id'])
            rows.append(row)
        # Active workflow state can change while GitHub builds a filtered page;
        # total_count is therefore advisory and may briefly exceed the returned
        # rows.  Exhaust pages until an actual empty page instead of failing on
        # that race.  Full 100-row pages still retain the 1,000-run search cap.
        if not batch:
            return rows
        if path.startswith('actions/runs?') and page == 10 and len(batch) == 100:
            # GitHub's filtered run endpoint caps a search at 1,000 results.
            # Never mistake that API ceiling for a complete quiet inventory.
            raise ValueError('single_campaign_active_listing_search_cap')
    raise ValueError('single_campaign_listing_bound')


def market_run(run, jobs):
    path = str(run.get('path', '')).split('@')[0].rsplit('/', 1)[-1]
    if path in OFFLINE_WORKFLOWS:
        return False
    if path in MARKET_WORKFLOWS:
        return True  # Queued/pending market workflows count before jobs materialize.
    if path == 'ci.yml':
        message = (run.get('head_commit') or {}).get('message', '')
        # Current generic CI is purely offline absent its explicit market markers.
        if any(marker in message for marker in CI_MARKERS):
            return True
        active = [j for j in jobs if j.get('status') != 'completed']
        if active:
            return any(j.get('name', '').split(' / ')[-1] not in OFFLINE_JOBS for j in active)
        # Until jobs exist a mixed historical CI run cannot be assumed offline.
        return True
    active = [j for j in jobs if j.get('status') != 'completed']
    return not active or any(j.get('name', '').split(' / ')[-1] not in OFFLINE_JOBS for j in active)


def contention(api, exclude_run=None, owned_launcher=None):
    conflicts = []
    inspected = []
    seen = set()
    for status in ACTIVE_STATUSES:
        for run in all_pages(api, 'actions/runs?status=' + status, 'workflow_runs'):
            if str(run['id']) == str(exclude_run) or str(run['id']) == str(owned_launcher):
                continue
            # A run moving between active status queries is conservatively inspected once.
            if run['id'] in seen:
                continue
            seen.add(run['id'])
            jobs = all_pages(api, f"actions/runs/{run['id']}/jobs?filter=latest", 'jobs')
            item = dict(run_id=run['id'], path=run.get('path'), status=run.get('status'),
                        market=market_run(run, jobs))
            inspected.append(item)
            if item['market']:
                conflicts.append(item)
    receipt = dict(observed_at=time.time(), statuses=list(ACTIVE_STATUSES),
                   inspected=inspected, conflicts=conflicts, passed=not conflicts)
    if conflicts:
        raise ValueError('single_campaign_other_market_workflow:' + canonical(conflicts))
    return receipt


class StateStore:
    """Append-only commits with a single non-forced ref CAS; no mutation retry."""
    def __init__(self, api, config, *, ref=None, path=STATE_PATH):
        self.api = api
        self.ref = ref or ('cert/single-campaign-' + digest(config['authorization_id'])[:16])
        self.path = str(path)
        self.head = None
        self.tree = None

    def read(self):
        try:
            self.head = self.api.request('GET', 'git/ref/heads/' + self.ref)['object']['sha']
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        self.tree = self.api.request('GET', 'git/commits/' + self.head)['tree']['sha']
        tree = self.api.request('GET', 'git/trees/' + self.tree + '?recursive=1')
        if tree.get('truncated'):
            raise ValueError('single_campaign_state_tree_truncated')
        items = [item for item in tree['tree'] if item['path'] == self.path]
        if len(items) != 1:
            raise ValueError('single_campaign_state_missing')
        blob = self.api.request('GET', 'git/blobs/' + items[0]['sha'])
        return json.loads(base64.b64decode(blob['content']))

    def write(self, state):
        parent = self.head or state['identity']['integration_sha']
        base = self.tree or self.api.request('GET', 'git/commits/' + parent)['tree']['sha']
        state['updated_at'] = time.time()
        tree = self.api.request('POST', 'git/trees', dict(base_tree=base, tree=[dict(
            path=self.path, mode='100644', type='blob', content=canonical(state) + '\n')]))
        commit = self.api.request('POST', 'git/commits', dict(
            message='Preserve consumed single campaign authorization [skip ci]',
            tree=tree['sha'], parents=[parent]))
        if self.head:
            self.api.request('PATCH', 'git/refs/heads/' + self.ref, dict(sha=commit['sha'], force=False))
        else:
            self.api.request('POST', 'git/refs', dict(ref='refs/heads/' + self.ref, sha=commit['sha']))
        self.head, self.tree = commit['sha'], tree['sha']


def continuation_store(api,config,lane):
    if lane not in ('meteora','ramses'):
        raise ValueError('single_campaign_continuation_lane')
    ref='cert/single-campaign-continuation-'+digest(
        config['authorization_id']+':'+lane)[:16]
    return StateStore(api,config,ref=ref,path=CONTINUATION_STATE_PATH)


def continuation_run(api,run_id,state):
    run=api.request('GET',f'actions/runs/{int(run_id)}')
    if (run.get('head_sha')!=state['identity']['integration_sha']
            or run.get('head_branch')!=state['runtime_ref']
            or str(run.get('run_attempt'))!='1'
            or run.get('event')!='workflow_dispatch'
            or str(run.get('path','')).split('@')[0] !=
                '.github/workflows/position-continuation.yml'):
        raise ValueError('single_campaign_continuation_run_identity')
    return run


def continuation_claim(api,config,identity,lane,campaign_run_id,state_run_id,run_id,attempt):
    first_attempt(attempt)
    if config.get('position_continuation_workflows') is not True:
        raise ValueError('single_campaign_continuation_not_authorized')
    main=StateStore(api,config).read()
    if (not main or main.get('identity')!=identity
            or main.get('workflow_run_id')!=int(campaign_run_id)
            or main.get('phase')!='POSITION_CONTINUATION'
            or main.get('continuation_allowed') is not True):
        raise ValueError('single_campaign_continuation_parent_state')
    position=((main.get('phase_records') or {}).get('hourly') or {}).get(
        'native_positions',{}).get(lane) or {}
    if (position.get('open_positions')!=1
            or position.get('open_positions_unknown') is True
            or position.get('accounting_reconciled') is not True
            or position.get('durable_handoff') is not True):
        raise ValueError('single_campaign_continuation_position_not_authorized')
    continuation_run(api,run_id,main)
    store=continuation_store(api,config,lane)
    state=store.read()
    if state is None:
        if int(state_run_id)!=int(campaign_run_id):
            raise ValueError('single_campaign_continuation_initial_source')
        state=dict(
            schema='meme-machine-single-campaign-continuation-v1',
            authorization_id=config['authorization_id'],
            authorization_sha256=digest(config),identity=identity,
            runtime_ref=main['runtime_ref'],campaign_run_id=int(campaign_run_id),
            lane=lane,status='OPEN',last_state_run_id=int(campaign_run_id),
            history=[])
    if (state.get('identity')!=identity
            or state.get('authorization_sha256')!=digest(config)
            or state.get('campaign_run_id')!=int(campaign_run_id)
            or state.get('lane')!=lane
            or state.get('status')!='OPEN'
            or state.get('last_state_run_id')!=int(state_run_id)):
        raise ValueError('single_campaign_continuation_chain_identity')
    state.update(status='RUNNING',active_run_id=int(run_id),
                 source_state_run_id=int(state_run_id))
    state['history'].append(dict(action='claim_position_only_continuation',
                                 run_id=int(run_id),state_run_id=int(state_run_id)))
    store.write(state)
    return state


def continuation_record(api,config,identity,lane,campaign_run_id,run_id,result,job_result):
    store=continuation_store(api,config,lane)
    state=store.read()
    if (not state or state.get('identity')!=identity
            or state.get('campaign_run_id')!=int(campaign_run_id)
            or state.get('status')!='RUNNING'
            or state.get('active_run_id')!=int(run_id)):
        raise ValueError('single_campaign_continuation_record_identity')
    if (job_result!='success' or not isinstance(result,dict)
            or result.get('lane')!=lane
            or result.get('assurance_passed') is not True):
        state.update(status='HALTED_UNRESOLVED',active_run_id=None,
                     failure='continuation_job_or_assurance_failure')
        state['history'].append(dict(action='halt_position_continuation',
                                     run_id=int(run_id),job_result=job_result))
    elif result.get('handoff_required') is True:
        state.update(status='OPEN',active_run_id=None,last_state_run_id=int(run_id))
        state['history'].append(dict(action='continue_same_position',
                                     run_id=int(run_id)))
    else:
        accounting=result.get('accounting') or {}
        if int(accounting.get('unsettled',accounting.get('open_positions',0)) or 0)!=0:
            raise ValueError('single_campaign_continuation_terminal_not_flat')
        state.update(status='SETTLED',active_run_id=None,last_state_run_id=int(run_id))
        state['history'].append(dict(action='position_terminal',
                                     run_id=int(run_id),status=result.get('status')))
    store.write(state)
    return state


def exact_ref(api, runtime_ref, sha):
    if not re.fullmatch(r'cert/single-market-[a-z0-9-]+', runtime_ref):
        raise ValueError('single_campaign_runtime_ref')
    if api.request('GET', 'git/ref/heads/' + runtime_ref)['object']['sha'] != sha:
        raise ValueError('single_campaign_runtime_ref_drift')


def launcher_identity(api, run_id):
    run = api.request('GET', f'actions/runs/{int(run_id)}')
    if (str(run.get('path', '')).split('@')[0] != '.github/workflows/single-campaign-launch.yml'
            or run.get('head_branch') != LAUNCH_BRANCH
            or run.get('event') != 'push' or str(run.get('run_attempt')) != '1'
            or '[single-market-launch]' not in (run.get('head_commit') or {}).get('message', '')):
        raise ValueError('single_campaign_launcher_identity')
    return run


def owned_contention(api, state, run_id):
    # The same authorization's launcher may still be uploading its receipt.
    # It has already consumed its sole POST and cannot authorize another run.
    launcher = launcher_identity(api, state['launcher_run_id'])
    if launcher.get('head_sha') != state['launcher_sha']:
        raise ValueError('single_campaign_launcher_identity_drift')
    return contention(api, run_id, state['launcher_run_id'])


def dispatch_once(api, config, identity, certificate_run_id, runtime_ref, launcher_run, attempt):
    from certification.prospective_program import certificate
    first_attempt(attempt)
    store = StateStore(api, config)
    if store.read() is not None:
        raise ValueError('single_campaign_authorization_already_consumed')
    launcher = launcher_identity(api, launcher_run)
    sha = identity['integration_sha']
    exact_ref(api, runtime_ref, sha)
    run = api.request('GET', f'actions/runs/{int(certificate_run_id)}')
    if run.get('status') != 'completed' or run.get('conclusion') != 'success':
        raise ValueError('single_campaign_certificate_not_terminal_success')
    receipt = certificate(api, certificate_run_id, sha)
    for key in ('integration_sha', 'implementation_hash', 'source_manifest_hash', 'source_diff_hashes'):
        if receipt.get(key) != identity[key]:
            raise ValueError('single_campaign_certificate_identity:' + key)
    quiet = contention(api, launcher_run)
    nonce = uuid.uuid4().hex
    inputs = dict(phase='hourly', program='false', single_campaign='true',
        authorization_id=config['authorization_id'], dispatch_id=nonce, expected_sha=sha,
        certification_run_id=str(certificate_run_id))
    state = dict(schema='meme-machine-single-campaign-state-v1', authorization_id=config['authorization_id'],
        authorization_sha256=digest(config), identity=identity, certificate=receipt,
        phase='DISPATCH_COMMITTED', dispatch_id=nonce, runtime_ref=runtime_ref,
        workflow_run_id=None, launcher_run_id=int(launcher_run), launcher_sha=launcher['head_sha'],
        dispatch_payload_sha256=digest(inputs),
        dispatch_may_have_been_sent=True, retry_allowed=False, successor_allowed=False,
        continuation_allowed=False,
        position_continuation_authorized=bool(config.get('position_continuation_workflows')),
        created_at=time.time(), phase_records={},
        quiet_before_claim=quiet, history=[dict(action='consume_authorization_before_dispatch')])
    store.write(state)  # Any timeout/collision here stops before POST; never retry.
    exact_ref(api, runtime_ref, sha)
    contention(api, launcher_run)  # All statuses/pages again immediately before the single POST.
    api.request('POST', 'actions/workflows/four-lane-certification.yml/dispatches',
                dict(ref=runtime_ref, inputs=inputs))  # Exactly one request, including on ambiguity.
    return state


def owned_state(api, config, identity, run_id, attempt, authorization_id, nonce):
    first_attempt(attempt)
    if authorization_id != config['authorization_id']:
        raise ValueError('single_campaign_authorization_identity')
    store = StateStore(api, config)
    state = store.read()
    if (not state or state.get('identity') != identity or state.get('authorization_sha256') != digest(config)
            or state.get('dispatch_id') != nonce):
        raise ValueError('single_campaign_consumed_authority_required')
    run = api.request('GET', f'actions/runs/{int(run_id)}')
    if (run.get('head_sha') != identity['integration_sha'] or run.get('head_branch') != state['runtime_ref']
            or str(run.get('run_attempt')) != '1' or run.get('event') != 'workflow_dispatch'
            or str(run.get('path', '')).split('@')[0] != MARKET_WORKFLOW):
        raise ValueError('single_campaign_run_identity')
    return store, state


def claim(api, config, identity, run_id, attempt, authorization_id, nonce):
    store, state = owned_state(api, config, identity, run_id, attempt, authorization_id, nonce)
    if state['phase'] != 'DISPATCH_COMMITTED' or state.get('workflow_run_id') is not None:
        raise ValueError('single_campaign_dispatch_already_claimed')
    owned_contention(api, state, run_id)
    state.update(phase='CLAIMED', workflow_run_id=int(run_id))
    state['history'].append(dict(action='claim_once', workflow_run_id=int(run_id)))
    store.write(state)
    return state


def begin_phase(state, phase):
    state = deepcopy(state)
    if phase not in ('smoke', 'hourly') or state['phase'] != 'CLAIMED':
        raise ValueError('single_campaign_phase_not_authorized')
    records = state['phase_records']
    if phase in records:
        raise ValueError('single_campaign_phase_repeated')
    if phase == 'hourly':
        smoke = records.get('smoke', {})
        if smoke.get('job_result') != 'success' or smoke.get('native_exposure') != 'flat':
            raise ValueError('single_campaign_smoke_not_complete_and_flat')
    records[phase] = dict(started_at=time.time(), native_exposure='unknown')
    state['history'].append(dict(action='begin_phase_once', phase=phase))
    return state


def end_phase(state, phase, result, job_result):
    state = deepcopy(state)
    if phase not in state['phase_records'] or 'ended_at' in state['phase_records'][phase]:
        raise ValueError('single_campaign_phase_not_open')
    if result is not None and (result.get('integration_sha') != state['identity']['integration_sha']
                               or result.get('phase') != phase):
        raise ValueError('single_campaign_phase_result_identity')
    lanes = (result or {}).get('lanes', {})
    observations = {lane: {key: lanes.get(lane, {}).get(key) for key in
        ('open_positions', 'open_positions_unknown', 'durable_handoff', 'accounting_reconciled')}
        for lane in LANES}
    known_flat = all(row['open_positions'] == 0 and row['open_positions_unknown'] is not True
                     and row['accounting_reconciled'] is True for row in observations.values())
    durable_open=[lane for lane,row in observations.items()
                  if row['open_positions']==1
                  and row['open_positions_unknown'] is not True
                  and row['accounting_reconciled'] is True
                  and row['durable_handoff'] is True]
    unsafe_open=[lane for lane,row in observations.items()
                 if row['open_positions'] not in (0,None)
                 and lane not in durable_open]
    state['phase_records'][phase].update(ended_at=time.time(), job_result=job_result,
        native_exposure='flat' if known_flat else 'durable_open' if durable_open and not unsafe_open else 'unresolved',
        native_positions=observations,
        native_run_id=(result or {}).get('run_id'), native_result_status=(result or {}).get('status'))
    if phase=='hourly' and job_result=='success' and durable_open and not unsafe_open:
        if state.get('position_continuation_authorized') is not True:
            state.update(phase='HALTED_UNRESOLVED',continuation_allowed=False,
                next_action='owner_review_only; durable positions exist but continuation authority is absent')
        else:
            state.update(phase='POSITION_CONTINUATION',continuation_allowed=True,
                next_action='position_only_continuation; no new discovery, qualification, entry, retry, replacement or successor campaign')
    elif job_result != 'success' or not known_flat or phase == 'hourly':
        state.update(phase='HALTED' if known_flat else 'HALTED_UNRESOLVED',
            continuation_allowed=False,
            next_action='owner_review_only; no successor, retry, replacement or continuation')
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('dispatch', 'claim', 'begin-phase', 'end-phase',
                                            'finish', 'review', 'contention', 'prohibit',
                                            'continuation-claim','continuation-record'))
    parser.add_argument('--phase', choices=('smoke', 'hourly'))
    parser.add_argument('--result'); parser.add_argument('--job-result')
    parser.add_argument('--certificate-run-id'); parser.add_argument('--runtime-ref')
    parser.add_argument('--output'); parser.add_argument('--action', default='continuation')
    parser.add_argument('--lane',choices=('meteora','ramses'))
    parser.add_argument('--campaign-run-id'); parser.add_argument('--state-run-id')
    args = parser.parse_args()
    config = configuration()
    if args.command == 'prohibit':
        prohibit_if_enabled(args.action)
    if args.command not in ('prohibit', 'contention'):
        require_authorization(config)
    from certification.prospective_program import GitHub
    api = GitHub()
    if args.command == 'contention':
        state = contention(api, os.environ.get('GITHUB_RUN_ID'))
    elif args.command == 'review':
        state = StateStore(api, config).read()
        if state is None:
            state = dict(phase='NOT_AUTHORIZED_OR_DISPATCHED', authorization_id=config['authorization_id'])
    else:
        sha = git('rev-parse', 'HEAD')
        if os.environ.get('EXPECTED_SHA') != sha:
            raise ValueError('single_campaign_checkout_identity')
        identity = identities(sha, config)
        run_id = int(os.environ['GITHUB_RUN_ID']); attempt = os.environ['GITHUB_RUN_ATTEMPT']
        if args.command == 'continuation-claim':
            state=continuation_claim(api,config,identity,args.lane,
                int(args.campaign_run_id),int(args.state_run_id),run_id,attempt)
        elif args.command == 'continuation-record':
            path=Path(args.result) if args.result else None
            result=(json.loads(path.read_text()) if path is not None and path.exists() else None)
            state=continuation_record(api,config,identity,args.lane,
                int(args.campaign_run_id),run_id,result,args.job_result)
        elif args.command == 'dispatch':
            if os.environ.get('SINGLE_AUTHORIZATION_ID') != config['authorization_id']:
                raise ValueError('single_campaign_launch_authorization_identity')
            state = dispatch_once(api, config, identity, args.certificate_run_id,
                                  args.runtime_ref, run_id, attempt)
        else:
            auth = os.environ.get('SINGLE_AUTHORIZATION_ID', '')
            nonce = os.environ.get('DISPATCH_ID', '')
            if os.environ.get('SINGLE_CAMPAIGN') != 'true':
                raise ValueError('single_campaign_explicit_dispatch_required')
            if (os.environ.get('SINGLE_PROGRAM_MODE') == 'true'
                    or os.environ.get('SINGLE_SMOKE_RUN_ID')
                    or os.environ.get('SINGLE_REQUESTED_PHASE') != 'hourly'):
                raise ValueError('single_campaign_fresh_smoke_hourly_only')
            if args.command == 'claim':
                state = claim(api, config, identity, run_id, attempt, auth, nonce)
            else:
                store, state = owned_state(api, config, identity, run_id, attempt, auth, nonce)
                if state.get('workflow_run_id') != run_id:
                    raise ValueError('single_campaign_foreign_run')
                if args.command == 'begin-phase':
                    owned_contention(api, state, run_id)
                    state = begin_phase(state, args.phase)
                elif args.command == 'end-phase':
                    path = Path(args.result)
                    result = json.loads(path.read_text()) if path.exists() else None
                    state = end_phase(state, args.phase, result, args.job_result)
                else:
                    if state.get('phase')=='POSITION_CONTINUATION':
                        state['history'].append(dict(action='finish_preserved_position_only_continuation'))
                    else:
                        last = state['phase_records'].get('hourly', state['phase_records'].get('smoke', {}))
                        state.update(phase='HALTED' if last.get('native_exposure') == 'flat' else 'HALTED_UNRESOLVED',
                            continuation_allowed=False,
                            next_action='owner_review_only; no successor, retry, replacement or continuation')
                store.write(state)
    if args.output:
        path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, sort_keys=True, indent=2) + '\n')
    print(canonical({k: state.get(k) for k in ('phase', 'authorization_id', 'workflow_run_id', 'next_action')}))


if __name__ == '__main__':
    main()
