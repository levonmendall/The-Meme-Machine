"""One exact E27 cohort -> required full verification -> official Phase E promotion.

This control-branch driver never changes runtime/canonical refs. Each permitted
workflow dispatch has a remote, exclusive intent; restart recovery is GET-only.
The official candidate workflow retains all proof review, CAS and canonical gates.
"""
from __future__ import annotations
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlencode

ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT))
from certification import dispatch_phase_e as dispatch
from certification import promote_phase_e as promotion
from certification.autonomous_control import _artifact_metadata
from certification.autonomous_window import extract_artifact
from certification.maintenance_qualification import frozen_inputs, qualification
from certification.prospective_program import GitHub
from certification.single_campaign_control import all_pages

SHA = '9356068cc92f9cadbd35adead3c33b532cbd4268'
TREE = 'b7fea73f83b29e569b9c8ffde47ae11ecb04cf1d'
PARENT = 'fdeee2721d2bb63e0ff3234328b06936257493b1'
BRANCH = 'repair/stagee27-archive-ready-allocation-20260928'
OLD_CANONICAL = 'a775849c940d48bc8f809e99c075e421744bc53f'
COHORT = 36525293113
COHORT_WORKFLOW = 'stagee-fixed-cohort.yml'
COHORT_ARTIFACT = f'stagee-fixed-cohort-{SHA}-{COHORT}'
FULL_WORKFLOW = dispatch.WORKFLOW
PROMOTION_WORKFLOW = promotion.WORKFLOW.rsplit('/', 1)[1]
ALLOWED = {'required-full': FULL_WORKFLOW, 'official-promotion': PROMOTION_WORKFLOW}
OUT = Path(os.environ.get('RUNNER_TEMP', '/tmp')) / 'e27-phase-e-continuation'
INTENT_PATH = 'e27-workflow-intent.json'


def store(name, value):
    dispatch.store(OUT / name, value)


def validate_run(row, run_id, workflow, *, event='workflow_dispatch'):
    if not (row.get('id') == run_id and row.get('head_sha') == SHA
            and row.get('head_branch') == BRANCH and row.get('run_attempt') == 1
            and row.get('path') == '.github/workflows/' + workflow
            and row.get('event') == event):
        raise ValueError('continuation_run_identity_mismatch')
    if any(item.get('sha') != SHA for item in row.get('referenced_workflows', [])):
        raise ValueError('continuation_reusable_sha_mismatch')
    return row


def wait_for(api, run_id, workflow, *, event='workflow_dispatch', polls=240, sleep=time.sleep):
    for index in range(polls):
        row = validate_run(api.request('GET', f'actions/runs/{run_id}'), run_id, workflow, event=event)
        store(f'run-{run_id}.json', row)
        if index % 3 == 0 or row.get('status') == 'completed':
            print(json.dumps(dict(run_id=run_id, workflow=workflow, status=row.get('status'),
                                  conclusion=row.get('conclusion'), poll=index + 1)), flush=True)
        if row.get('status') == 'completed':
            if row.get('conclusion') != 'success':
                raise ValueError('continuation_child_failed:' + str(run_id))
            return row
        if row.get('status') not in dispatch.ACTIVE:
            raise ValueError('continuation_unknown_run_state')
        sleep(20)
    raise RuntimeError('continuation_observation_bound_reached_no_new_dispatch')


def workflow_runs(api, workflow):
    return all_pages(api, 'actions/workflows/' + workflow + '/runs?' + urlencode({'branch': BRANCH}), 'workflow_runs')


def check_ref(api):
    if api.request('GET', 'git/ref/heads/' + BRANCH)['object']['sha'] != SHA:
        raise ValueError('continuation_candidate_branch_moved')


def remote_intent(api, purpose, workflow, inputs, previous):
    name = f'heads/cert/e27-{purpose}-intent-{SHA}'
    expected = dict(schema='e27-workflow-intent-v1', candidate=SHA, tree=TREE, branch=BRANCH,
        purpose=purpose, workflow=workflow, inputs=inputs, cohort_run=COHORT,
        paper_only=True, market_authority=False)
    visible = promotion.read_optional_ref(api, name)
    if visible is not None:
        content = api.request('GET', f'contents/{INTENT_PATH}?ref=' + visible['object']['sha'])
        if content.get('encoding') != 'base64':
            raise ValueError('continuation_intent_encoding')
        row = json.loads(base64.b64decode(content['content']))
        if any(row.get(key) != value for key, value in expected.items()) or row.get('post_attempts') != 1:
            raise ValueError('continuation_remote_intent_mismatch')
        store(purpose + '-intent.json', row)
        return row, False
    row = dict(expected, previous_run_ids=[item['id'] for item in previous], post_attempts=1,
               actor_run_id=int(os.environ['GITHUB_RUN_ID']))
    text = json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n'
    tree = api.request('POST', 'git/trees', {'tree': [dict(path=INTENT_PATH, mode='100644', type='blob', content=text)]})
    commit = api.request('POST', 'git/commits', dict(message='Preserve exact E27 workflow dispatch intent [skip ci]',
                                                    tree=tree['sha'], parents=[]))
    # Atomic create only. Never update, force, delete, or retry this intent.
    created = api.request('POST', 'git/refs', dict(ref='refs/' + name, sha=commit['sha']))
    visible = promotion.read_optional_ref(api, name)
    if created.get('object', {}).get('sha') != commit['sha'] or visible.get('object', {}).get('sha') != commit['sha']:
        raise ValueError('continuation_intent_not_durable')
    store(purpose + '-intent.json', row)
    return row, True


def dispatch_once(api, purpose, inputs, *, polls=24, sleep=time.sleep):
    if purpose not in ALLOWED or inputs.get('expected_sha') != SHA:
        raise ValueError('continuation_dispatch_not_authorized')
    workflow = ALLOWED[purpose]
    check_ref(api)
    registered = api.request('GET', 'actions/workflows/' + workflow)
    if registered.get('state') != 'active' or registered.get('path') != '.github/workflows/' + workflow:
        raise ValueError('continuation_workflow_not_registered')
    before = workflow_runs(api, workflow)
    matching = [row for row in before if row.get('head_sha') == SHA and row.get('event') == 'workflow_dispatch']
    if len(matching) > 1:
        raise ValueError('continuation_duplicate_candidate_runs')
    if matching:
        row = validate_run(matching[0], matching[0]['id'], workflow)
        store(purpose + '-adopted.json', row)
        return row['id']
    if any(row.get('status') in dispatch.ACTIVE for row in before):
        raise ValueError('continuation_competing_workflow')
    if purpose == 'official-promotion':
        if api.request('GET', 'git/ref/heads/' + dispatch.BRANCH)['object']['sha'] != OLD_CANONICAL:
            raise ValueError('continuation_canonical_predecessor_changed')
    intent, fresh = remote_intent(api, purpose, workflow, inputs, before)
    receipt = {}
    if fresh:
        check_ref(api)
        store(purpose + '-post-boundary.json', dict(intent=intent, post_attempts=1))
        try:
            receipt = api.request('POST', 'actions/workflows/' + workflow + '/dispatches',
                dict(ref=BRANCH, inputs=inputs, return_run_details=True)) or {}
            if not isinstance(receipt, dict):
                raise ValueError('continuation_invalid_dispatch_response')
        except (OSError, ValueError, TypeError) as exc:
            receipt = dict(post_error_type=type(exc).__name__)
        store(purpose + '-post-receipt.json', receipt)
    # No POST occurs when an intent already existed, even after a lost response.
    for index in range(polls):
        run_id = receipt.get('workflow_run_id')
        if type(run_id) is int:
            candidates = [api.request('GET', f'actions/runs/{run_id}')]
        else:
            candidates = [row for row in workflow_runs(api, workflow) if row.get('id') not in intent['previous_run_ids']]
        if len(candidates) > 1:
            raise ValueError('continuation_ambiguous_dispatch')
        if candidates:
            row = validate_run(candidates[0], candidates[0]['id'], workflow)
            store(purpose + '-dispatch.json', row)
            return row['id']
        sleep(5)
    raise RuntimeError('continuation_dispatch_unconfirmed_get_only_no_retry')


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    assert os.environ['GITHUB_RUN_ATTEMPT'] == '1'
    git = lambda *args: subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    assert git('rev-parse', 'HEAD') == SHA and git('rev-parse', 'HEAD^{tree}') == TREE
    assert git('rev-parse', 'HEAD^') == PARENT and not git('status', '--porcelain')
    assert frozen_inputs()
    api = GitHub()
    check_ref(api)
    store('identity.json', dict(candidate=SHA, tree=TREE, parent=PARENT, cohort_run=COHORT,
          driver_run=int(os.environ['GITHUB_RUN_ID']), control_sha=os.environ['GITHUB_SHA'],
          paper_only=True, market_authority=False, canonical_authority=False))
    cohort_run = wait_for(api, COHORT, COHORT_WORKFLOW, event='push')
    reference = _artifact_metadata(api, COHORT, COHORT_ARTIFACT)
    root = extract_artifact(api, reference, OUT / 'cohort')
    promotion.verify_environment(promotion.read(root / 'environment.json'))
    from certification import cleanup_recovery
    with qualification():
        cohort = cleanup_recovery.aggregate(root, SHA)
    store('recomputed-cohort.json', cohort)
    if cohort.get('passed') is not True or cohort.get('failures'):
        raise ValueError('continuation_cohort_not_accepted')
    promotion.successful_run(api, COHORT, SHA)
    if _artifact_metadata(api, COHORT, COHORT_ARTIFACT) != reference:
        raise ValueError('continuation_cohort_artifact_changed')
    full_id = dispatch_once(api, 'required-full', dict(expected_sha=SHA))
    full = wait_for(api, full_id, FULL_WORKFLOW)
    promotion.require_full_jobs(api, full_id)
    if datetime.fromisoformat(cohort_run['updated_at'].replace('Z', '+00:00')) > datetime.fromisoformat(full['run_started_at'].replace('Z', '+00:00')):
        raise ValueError('continuation_full_does_not_follow_cohort')
    promotion_id = dispatch_once(api, 'official-promotion', dict(expected_sha=SHA,
        expected_canonical_sha=OLD_CANONICAL, cohort_run_id=str(COHORT),
        cohort_artifact=COHORT_ARTIFACT, full_run_id=str(full_id)))
    wait_for(api, promotion_id, PROMOTION_WORKFLOW, polls=300)
    archive, metadata = api.artifact(promotion_id, f'phase-e-canonical-review-{SHA}-{promotion_id}-1')
    names = [name for name in archive.namelist() if name == 'canonical-review.json']
    if len(names) != 1:
        raise ValueError('continuation_canonical_review_missing')
    review = json.loads(archive.read(names[0]))
    if not (review.get('passed') is True and review.get('runtime_sha') == SHA
            and review.get('canonical_authority') is True and review.get('artifacts_verified') is True):
        raise ValueError('continuation_canonical_review_not_verified')
    canonical = dispatch.run_identity(api.request('GET', 'actions/runs/' + str(review['run_id'])), SHA)
    if canonical.get('status') != 'completed' or canonical.get('conclusion') != 'success':
        raise ValueError('continuation_canonical_not_terminal_green')
    store('terminal.json', dict(phase_e_certified=True, candidate=SHA, tree=TREE, parent=PARENT,
        cohort_run=COHORT, full_verification_run=full_id, promotion_run=promotion_id,
        canonical_run=canonical['id'], review=review, review_artifact=metadata,
        paper_only=True, market_authority=False, phase_f_dispatched=False))
    print((OUT/'terminal.json').read_text(), flush=True)


if __name__ == '__main__':
    try:
        main()
    finally:
        if OUT.exists():
            store('SHA256.json', {str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in OUT.rglob('*') if p.is_file() and p.name != 'SHA256.json'})
