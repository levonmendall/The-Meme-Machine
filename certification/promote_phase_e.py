"""Evidence-gated, one-shot promotion and explicit canonical Phase E dispatch.

Only the dedicated manual PAPER workflow calls the write path. Raw artifact
hashes, all fixed trials, complete machinery gates, and immutable source bytes
are checked before a durable remote intent is created. A lost response burns
that intent; reconciliation is GET-only. No market or deployment authority.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any
from urllib.error import HTTPError

from certification import dispatch_phase_e as dispatch
from certification.autonomous_control import _artifact_metadata
from certification.autonomous_window import extract_artifact
from certification.journal import digest
from certification.maintenance_qualification import PLAN_PATH, frozen_inputs, qualification
from certification.prospective_program import GitHub, REPOSITORY
from certification.qualification_environment import PYTHON, DEPENDENCIES
from certification.run import ROOT, implementation_hash, manifest
from certification.single_campaign_control import all_pages, checkout_files

WORKFLOW = '.github/workflows/stagee-accepted-candidate-promotion.yml'
INTENT_FILE = 'phase-e-intent.json'
CERTIFICATE_JOBS = {'durability-prerequisites', 'offline-prerequisites'}


def read(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text())
    if not isinstance(row, dict):
        raise ValueError('phase_e_receipt_not_object')
    return row


def successful_run(api: Any, run_id: int, sha: str) -> dict[str, Any]:
    row = api.request('GET', f'actions/runs/{run_id}')
    if (row.get('id') != run_id or row.get('head_sha') != sha
            or row.get('run_attempt') != 1 or row.get('status') != 'completed'
            or row.get('conclusion') != 'success'):
        raise ValueError('phase_e_prerequisite_run_not_exact_success')
    for item in row.get('referenced_workflows', []):
        if item.get('sha') != sha:
            raise ValueError('phase_e_prerequisite_reusable_sha')
    return row


def require_actor(api: Any, actor: int, sha: str) -> dict[str, Any]:
    row = api.request('GET', f'actions/runs/{actor}')
    if (row.get('id') != actor or row.get('head_sha') != sha
            or row.get('path') != WORKFLOW or row.get('event') != 'workflow_dispatch'
            or row.get('run_attempt') != 1 or row.get('status') != 'in_progress'):
        raise ValueError('phase_e_promotion_actor_identity')
    return row


def require_full_jobs(api: Any, run_id: int) -> None:
    jobs = all_pages(api, f'actions/runs/{run_id}/attempts/1/jobs', 'jobs')
    for required in CERTIFICATE_JOBS:
        matches = [job for job in jobs if job.get('name', '').split(' / ')[-1] == required]
        if (len(matches) != 1 or matches[0].get('status') != 'completed'
                or matches[0].get('conclusion') != 'success'):
            raise ValueError('phase_e_complete_job_missing_or_failed:' + required)


def verify_environment(row: dict[str, Any]) -> None:
    if (row.get('passed') is not True or row.get('failures') != []
            or row.get('python') != PYTHON or row.get('dependencies') != DEPENDENCIES
            or row.get('policy_predecessor_available') is not True
            or row.get('canonical_authority') is not False):
        raise ValueError('phase_e_frozen_environment_not_verified')


def verify_evidence(cohort_root: Path, build_root: Path, sha: str,
                    output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recompute acceptance from original files; never accept a summary alone."""
    from certification import cleanup_recovery, final_acceptance
    if not frozen_inputs():
        raise ValueError('phase_e_frozen_inputs_changed')
    verify_environment(read(cohort_root / 'environment.json'))
    with qualification():
        cohort = cleanup_recovery.aggregate(cohort_root, sha)
    # The downloadable artifact must include the raw fixed trial directories.
    # The old rejected cohorts cannot satisfy the new plan hash and assessments.
    offline = read(build_root / 'offline/result.json')
    spec = manifest()
    if (offline.get('passed') is not True or offline.get('integration_sha') != sha
            or offline.get('implementation_hash') != implementation_hash()
            or offline.get('source_manifest_hash') != digest(spec)
            or offline.get('source_diff_hashes') != {
                lane: row['source_diff_sha256'] for lane, row in spec['lanes'].items()}):
        raise ValueError('phase_e_complete_source_identity')
    output.mkdir(parents=True, exist_ok=True)
    final_acceptance.run(build_root, output / 'recomputed-build.json', sha, preserved_only=True)
    build = read(output / 'recomputed-build.json')
    if build != read(build_root / 'final-acceptance.json'):
        raise ValueError('phase_e_complete_acceptance_changed')
    plan_sha = hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest()
    dispatch.prerequisites(cohort, build, sha, plan_sha)
    dispatch.store(output / 'recomputed-cohort.json', cohort)
    return cohort, build


def collect(api: Any, sha: str, cohort_run: int, cohort_name: str,
            full_run: int, output: Path) -> dict[str, Any]:
    if (not isinstance(cohort_name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,180}', cohort_name)):
        raise ValueError('phase_e_artifact_name')
    if cohort_run == full_run:
        raise ValueError('phase_e_full_verification_must_follow_cohort')
    source_runs = [successful_run(api, run_id, sha) for run_id in (cohort_run, full_run)]
    # Completed cohort evidence must predate full machinery verification.
    try:
        cohort_end = datetime.fromisoformat(source_runs[0]['updated_at'].replace('Z', '+00:00'))
        build_start = datetime.fromisoformat(source_runs[1]['run_started_at'].replace('Z', '+00:00'))
        if cohort_end.tzinfo is None or build_start.tzinfo is None or cohort_end > build_start:
            raise ValueError('phase_e_verification_order')
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError('phase_e_verification_order') from exc
    require_full_jobs(api, full_run)
    references = {
        'cohort': _artifact_metadata(api, cohort_run, cohort_name),
        'build': _artifact_metadata(api, full_run, f'non-market-certification-{sha}-1'),
    }
    roots = {key: extract_artifact(api, reference, output / key)
             for key, reference in references.items()}
    cohort, build = verify_evidence(roots['cohort'], roots['build'], sha, output / 'verified')
    # Detect deletion, replacement or a rerun while the original bytes were read.
    for run_id in (cohort_run, full_run):
        successful_run(api, run_id, sha)
    for reference in references.values():
        if _artifact_metadata(api, reference['workflow_run_id'], reference['name']) != reference:
            raise ValueError('phase_e_artifact_changed_during_verification')
    return dict(cohort=cohort, build=build, artifacts=references,
                plan_sha256=hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest())


def read_optional_ref(api: Any, name: str) -> dict[str, Any] | None:
    try:
        return api.request('GET', 'git/ref/' + name)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        return None


def intent_ref(sha: str) -> str:
    dispatch.require_sha(sha)
    return 'heads/cert/phase-e-dispatch-intent-' + sha


def reserve_intent(api: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Atomic ref creation is the cross-run one-shot boundary, before any push."""
    name = intent_ref(row['runtime_sha'])
    if read_optional_ref(api, name) is not None:
        raise ValueError('phase_e_intent_already_consumed_use_get_only')
    text = json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n'
    tree = api.request('POST', 'git/trees', {'tree': [
        dict(path=INTENT_FILE, mode='100644', type='blob', content=text)]})
    commit = api.request('POST', 'git/commits', dict(
        message='Preserve one-shot Phase E promotion and dispatch intent [skip ci]',
        tree=tree['sha'], parents=[]))
    # POST exactly once. Conflicts and lost responses stop; no ref replacement.
    result = api.request('POST', 'git/refs', dict(ref='refs/' + name, sha=commit['sha']))
    expected = commit['sha']
    visible = read_optional_ref(api, name) or {}
    if (result.get('ref') != 'refs/' + name
            or result.get('object', {}).get('sha') != expected
            or visible.get('object', {}).get('sha') != expected):
        raise ValueError('phase_e_intent_not_durable')
    return dict(ref='refs/' + name, commit_sha=expected,
                sha256=hashlib.sha256(text.encode()).hexdigest())


def promotion_environment() -> None:
    if (os.environ.get('GITHUB_REPOSITORY') != REPOSITORY
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_RUN_ATTEMPT') != '1'):
        raise ValueError('phase_e_promotion_requires_first_manual_attempt')


def require_origin() -> None:
    origin = subprocess.check_output(['git', 'remote', 'get-url', 'origin'],
                                     cwd=ROOT, text=True).strip()
    allowed = {'https://github.com/' + REPOSITORY, 'https://github.com/' + REPOSITORY + '.git'}
    if origin not in allowed:
        raise ValueError('phase_e_unapproved_publish_origin')


def push_exact(sha: str, old_sha: str) -> None:
    # Ancestor check forbids history loss. The explicit lease is a CAS, not
    # permission to discard someone else's newer canonical commit.
    subprocess.run(['git', 'merge-base', '--is-ancestor', old_sha, sha], cwd=ROOT, check=True)
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'push', '--porcelain',
                    f'--force-with-lease=refs/heads/{dispatch.BRANCH}:{old_sha}',
                    'origin', f'{sha}:refs/heads/{dispatch.BRANCH}'], cwd=ROOT, check=True)


def require_dispatch_workflow(api: Any, sha: str) -> None:
    """Registration and candidate workflow bytes are required before promotion."""
    row = api.request('GET', 'actions/workflows/' + dispatch.WORKFLOW)
    if (row.get('path') != '.github/workflows/' + dispatch.WORKFLOW
            or row.get('state') != 'active'):
        raise ValueError('phase_e_dispatch_workflow_not_registered')
    for filename in (dispatch.WORKFLOW, 'non-market-certification.yml'):
        path = '.github/workflows/' + filename
        content = api.request('GET', 'contents/' + path + '?ref=' + sha)
        if (content.get('encoding') != 'base64'
                or base64.b64decode(content['content']) != (ROOT / path).read_bytes()):
            raise ValueError('phase_e_dispatch_workflow_bytes_changed')


def promote(api: Any, sha: str, old_sha: str, actor: int, evidence: dict[str, Any],
            output: Path, *, push=push_exact) -> dict[str, Any]:
    dispatch.require_sha(sha)
    dispatch.require_sha(old_sha)
    if sha == old_sha:
        raise ValueError('phase_e_candidate_already_canonical')
    dispatch.prerequisites(evidence['cohort'], evidence['build'], sha, evidence['plan_sha256'])
    require_actor(api, actor, sha)
    require_dispatch_workflow(api, sha)
    adapt = lambda repo, method, path, data=None: api.request(method, path, data)
    before = dispatch.canonical_runs(REPOSITORY, adapt)
    if (any(row.get('status') in dispatch.ACTIVE for row in before)
            or any(row.get('head_sha') == sha and row.get('event') == 'workflow_dispatch' for row in before)):
        raise ValueError('phase_e_canonical_run_exists')
    if api.request('GET', 'git/ref/heads/' + dispatch.BRANCH).get('object', {}).get('sha') != old_sha:
        raise ValueError('phase_e_canonical_reference_changed')
    if not evidence.get('artifacts') or set(evidence['artifacts']) != {'cohort', 'build'}:
        raise ValueError('phase_e_artifact_bindings_missing')
    row = dict(schema='phase-e-one-shot-promotion-v1', repository=REPOSITORY,
               runtime_sha=sha, prior_canonical_sha=old_sha, actor_run_id=actor,
               artifacts=evidence['artifacts'], plan_sha256=evidence['plan_sha256'],
               cohort_sha256=digest(evidence['cohort']), build_sha256=digest(evidence['build']),
               previous_run_ids=[r['id'] for r in before], post_attempts=1,
               canonical_authority=False, market_authority=False, paper_only=True)
    claim = reserve_intent(api, row)
    dispatch.store(output / 'remote-intent.json', dict(intent=row, claim=claim), exclusive=True)
    # Any exception from the push/dispatch is a stop. No retry and no rollback
    # that could overwrite concurrent legitimate canonical work.
    push(sha, old_sha)
    actual = api.request('GET', 'git/ref/heads/' + dispatch.BRANCH)
    if actual.get('object', {}).get('sha') != sha:
        raise ValueError('phase_e_promoted_sha_not_confirmed')
    result = dispatch.dispatch(REPOSITORY, sha, sha, evidence['plan_sha256'],
                               evidence['cohort'], evidence['build'], output / 'dispatch.json', api=adapt)
    result['promotion'] = dict(prior_sha=old_sha, promoted_sha=sha, intent=claim)
    dispatch.store(output / 'promotion.json', result)
    return result


def retained_intent(api: Any, sha: str) -> tuple[dict[str, Any], str]:
    dispatch.require_sha(sha)
    ref = read_optional_ref(api, intent_ref(sha))
    if ref is None:
        raise ValueError('phase_e_intent_missing')
    commit_sha = ref['object']['sha']
    content = api.request('GET', f'contents/{INTENT_FILE}?ref={commit_sha}')
    if content.get('encoding') != 'base64':
        raise ValueError('phase_e_intent_encoding')
    row = json.loads(base64.b64decode(content['content']))
    if (row.get('schema') != 'phase-e-one-shot-promotion-v1'
            or row.get('repository') != REPOSITORY or row.get('runtime_sha') != sha
            or row.get('post_attempts') != 1 or row.get('canonical_authority') is not False
            or row.get('market_authority') is not False or row.get('paper_only') is not True
            or not isinstance(row.get('previous_run_ids'), list)):
        raise ValueError('phase_e_intent_identity')
    return row, commit_sha


def reconcile(api: Any, sha: str, output: Path) -> dict[str, Any]:
    """Recover remote intent and observable state using GET requests only."""
    row, commit_sha = retained_intent(api, sha)
    adapt = lambda repo, method, path, data=None: api.request(method, path, data)
    new = [run for run in dispatch.canonical_runs(REPOSITORY, adapt)
           if run.get('id') not in row['previous_run_ids']]
    if len(new) > 1:
        raise ValueError('phase_e_ambiguous_new_runs')
    result = dict(runtime_sha=sha, intent_commit_sha=commit_sha, reconciliation_only=True,
                  canonical_authority=False, market_authority=False, new_post_permitted=False,
                  canonical_sha=api.request('GET', 'git/ref/heads/' + dispatch.BRANCH)['object']['sha'],
                  run=None)
    if new:
        result['run'] = dispatch.run_identity(new[0], sha)
    dispatch.store(output / 'reconciliation.json', result)
    return result


def review_canonical(api: Any, sha: str, run_id: int, output: Path, *,
                     polls: int = 1, sleep=time.sleep) -> dict[str, Any]:
    """Wait/read only. Green Actions status cannot replace raw proof review."""
    if type(polls) is not int or not 1 <= polls <= 360:
        raise ValueError('phase_e_review_poll_bound')
    row, claim_sha = retained_intent(api, sha)
    if run_id in row['previous_run_ids']:
        raise ValueError('phase_e_review_run_predates_intent')
    expected_plan = hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest()
    if row.get('plan_sha256') != expected_plan:
        raise ValueError('phase_e_review_plan_changed')
    result = dict(passed=False, runtime_sha=sha, run_id=run_id, intent_commit_sha=claim_sha,
                  canonical_authority=False, artifacts_verified=False, market_authority=False,
                  paper_only=True, failure=None)
    output.mkdir(parents=True, exist_ok=False)
    dispatch.store(output / 'canonical-review.json', result)
    for index in range(polls):
        run = dispatch.run_identity(api.request('GET', f'actions/runs/{run_id}'), sha)
        result.update(run_status=run.get('status'), conclusion=run.get('conclusion'))
        dispatch.store(output / 'canonical-review.json', result)
        print(json.dumps(dict(run_id=run_id, runtime_sha=sha, poll=index + 1,
                              status=run.get('status'), conclusion=run.get('conclusion'))), flush=True)
        if run.get('status') == 'completed':
            break
        if run.get('status') not in dispatch.ACTIVE:
            raise ValueError('phase_e_unknown_run_status')
        if index + 1 < polls:
            sleep(15)
    else:
        result['failure'] = 'canonical_run_not_terminal_within_review_bound'
        dispatch.store(output / 'canonical-review.json', result)
        return result
    if run.get('conclusion') != 'success':
        # Preserve available raw failure artifacts even for a failed workflow.
        inventory = all_pages(api, f'actions/runs/{run_id}/artifacts', 'artifacts')
        result['available_artifacts'] = [
            {k: a.get(k) for k in ('id', 'name', 'digest', 'expired')} for a in inventory]
        result['artifact_recovery'] = []
        for name in (f'non-market-durability-{sha}-1', f'non-market-certification-{sha}-1'):
            try:
                reference = _artifact_metadata(api, run_id, name)
                extract_artifact(api, reference, output / name)
                result['artifact_recovery'].append(dict(reference=reference, recovered=True))
            except (OSError, ValueError, KeyError) as exc:
                result['artifact_recovery'].append(dict(name=name, recovered=False,
                                                       error_type=type(exc).__name__))
        result['failure'] = 'canonical_workflow_failed'
        dispatch.store(output / 'canonical-review.json', result)
        return result
    try:
        adapt = lambda repo, method, path, data=None: api.request(method, path, data)
        candidates = [r for r in dispatch.canonical_runs(REPOSITORY, adapt)
                      if r.get('id') not in row['previous_run_ids']]
        if len(candidates) != 1 or candidates[0].get('id') != run_id:
            raise ValueError('phase_e_review_dispatch_not_unique')
        cohort_ref = row['artifacts']['cohort']
        evidence = collect(api, sha, cohort_ref['workflow_run_id'], cohort_ref['name'],
                           run_id, output / 'evidence')
        if (evidence['artifacts']['cohort'] != cohort_ref
                or digest(evidence['cohort']) != row['cohort_sha256']):
            raise ValueError('phase_e_review_cohort_changed')
        latest = dispatch.run_identity(api.request('GET', f'actions/runs/{run_id}'), sha)
        if latest.get('status') != 'completed' or latest.get('conclusion') != 'success':
            raise ValueError('phase_e_review_terminal_changed')
        if api.request('GET', 'git/ref/heads/' + dispatch.BRANCH)['object']['sha'] != sha:
            raise ValueError('phase_e_review_canonical_branch_changed')
    except (OSError, ValueError, KeyError) as exc:
        result['failure'] = 'canonical_artifact_review_failed'
        result['error_type'] = type(exc).__name__
        dispatch.store(output / 'canonical-review.json', result)
        raise
    result.update(passed=True, canonical_authority=True, artifacts_verified=True,
                  artifacts=evidence['artifacts'], plan_sha256=evidence['plan_sha256'],
                  final_acceptance_sha256=digest(evidence['build']))
    dispatch.store(output / 'canonical-review.json', result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--old-sha')
    parser.add_argument('--cohort-run', type=int)
    parser.add_argument('--cohort-artifact')
    parser.add_argument('--full-run', type=int)
    parser.add_argument('--output', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--reconcile-only', action='store_true')
    mode.add_argument('--verify-run', type=int)
    parser.add_argument('--polls', type=int, default=1)
    args = parser.parse_args()
    dispatch.require_sha(args.sha)
    api = GitHub()
    if args.verify_run:
        checkout_files(args.sha)
        result = review_canonical(api, args.sha, args.verify_run, args.output, polls=args.polls)
        if not result['passed']:
            raise SystemExit(1)
        return
    if args.reconcile_only:
        reconcile(api, args.sha, args.output)
        return
    if not all((args.old_sha, args.cohort_run, args.cohort_artifact, args.full_run)):
        parser.error('fresh promotion requires exact old SHA and both prerequisite artifact runs')
    promotion_environment()
    require_origin()
    dispatch.require_sha(args.old_sha)
    if args.cohort_run <= 0 or args.full_run <= 0:
        raise ValueError('phase_e_invalid_prerequisite_run_id')
    if os.environ.get('GITHUB_SHA') != args.sha:
        raise ValueError('phase_e_workflow_sha_mismatch')
    checkout_files(args.sha)
    # Reject non-ancestor input before reserving an irreversible remote intent.
    subprocess.run(['git', 'merge-base', '--is-ancestor', args.old_sha, args.sha], cwd=ROOT, check=True)
    args.output.mkdir(parents=True, exist_ok=False)
    dispatch.store(args.output / 'preflight.json', dict(
        runtime_sha=args.sha, prior_canonical_sha=args.old_sha,
        cohort_run_id=args.cohort_run, full_run_id=args.full_run,
        canonical_authority=False, market_authority=False, passed=False))
    evidence = collect(api, args.sha, args.cohort_run, args.cohort_artifact,
                       args.full_run, args.output / 'evidence')
    checkout_files(args.sha)
    promote(api, args.sha, args.old_sha, int(os.environ['GITHUB_RUN_ID']), evidence, args.output)


if __name__ == '__main__':
    main()
