"""Prepare one reviewed E27 publication; never move a ref or dispatch a market run."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path.cwd().resolve()
HERE = Path(__file__).resolve().parent
OUT = Path(os.environ['RUNNER_TEMP']) / 'e27-complete-publication'
PARENT = 'fdeee2721d2bb63e0ff3234328b06936257493b1'
BRANCH = 'repair/stagee27-archive-ready-allocation-20260928'
BASELINE = '23f06ed84e5b5e2d4efd074618ab44ae7ed58011'
MESSAGE = '[runtime-v2-promotion] Complete E27 exact-source manifests and fixed-cohort wiring\n\nPreserve the verified E27 runtime and test-discovery repair. Refresh only reviewed native overlay identities; add the missing exact-head four-trial prerequisite runner. No workload, capacity threshold, strategy, evidence or market-authority changes.'
sys.path.insert(0, str(ROOT))


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', *args], cwd=cwd, text=True).strip()


def save(name, row):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2) + '\n')


def command(name, args, *, cwd=ROOT, allow_failure=False):
    with (OUT / (name + '.log')).open('wb') as log:
        row = subprocess.run(args, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    print(json.dumps(dict(step=name, returncode=row.returncode)), flush=True)
    if row.returncode and not allow_failure:
        raise RuntimeError('candidate_preparation_step_failed:' + name)
    return row.returncode


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    assert os.environ['GITHUB_RUN_ATTEMPT'] == '1'
    assert git('rev-parse', 'HEAD') == PARENT and not git('status', '--porcelain')
    from certification.prospective_program import GitHub
    api = GitHub()
    assert api.request('GET', 'git/ref/heads/' + BRANCH)['object']['sha'] == PARENT
    save('source-identity.json', dict(sha=PARENT, tree=git('rev-parse', 'HEAD^{tree}'),
        parent=git('rev-parse', 'HEAD^'), control_sha=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'], paper_only=True, market_authority=False))
    original = json.loads((ROOT / 'certification/sources.json').read_text())
    rel = 'meme_machine/solana_evidence_service.py'
    actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
    declared = original['lanes']['pump']['composed_file_hashes'][rel]
    assert actual != declared, 'no demonstrated source-manifest defect'
    assert not (ROOT / '.github/workflows/stagee-fixed-cohort.yml').exists()
    save('demonstrated-blockers.json', dict(runtime_sha=PARENT, service_file=rel,
        declared_sha256=declared, actual_sha256=actual,
        promotion_requires_exact_head_cohort=True, fixed_cohort_workflow_missing=True,
        runtime_changed=False, classification=['candidate_artifact_build_identity', 'certification_orchestration']))
    current_lanes = Path(os.environ['RUNNER_TEMP']) / 'e27-current-lanes'
    command('original-prepare', [sys.executable, '-m', 'certification.run', 'prepare', '--worktrees', str(current_lanes)])
    rc = command('original-build-preflight', [sys.executable, '-m', 'certification.build_consistency', 'verify',
        '--worktrees', str(current_lanes), '--expected-sha', PARENT,
        '--output', str(OUT / 'original-build-preflight.json')], allow_failure=True)
    old_result = json.loads((OUT / 'original-build-preflight.json').read_text())
    assert rc != 0 and old_result['passed'] is False
    assert old_result['failures'] == ['frozen_source_file_drift:pump:' + rel], old_result

    request = json.loads((HERE / 'cohort-request.json').read_text())
    assert request['expected_parent'] == PARENT
    helper = ROOT / 'certification/build_consistency.py'
    text = helper.read_text()
    anchor = "    'tests/test_run381_retention_progress.py',\n"
    assert text.count(anchor) == 1
    helper.write_text(text.replace(anchor, anchor + "    'tests/test_run381_archive_scheduling.py',\n"))
    for source, target in [
        ('stagee-fixed-cohort.yml', '.github/workflows/stagee-fixed-cohort.yml'),
        ('test_stagee27_cohort_wiring.py', 'certification/tests/test_stagee27_cohort_wiring.py'),
        ('cohort-request.json', '.github/stagee27/cohort-request.json'),
    ]:
        destination = ROOT / target
        assert not destination.exists()
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / source, destination)

    baseline_root = Path(os.environ['RUNNER_TEMP']) / 'e27-reviewed-baseline'
    baseline_lanes = Path(os.environ['RUNNER_TEMP']) / 'e27-baseline-lanes'
    command('baseline-checkout', ['git', 'worktree', 'add', '--detach', str(baseline_root), BASELINE])
    command('baseline-prepare', [sys.executable, '-m', 'certification.run', 'prepare', '--worktrees', str(baseline_lanes)], cwd=baseline_root)
    command('reviewed-manifest-refresh', [sys.executable, '-m', 'certification.build_consistency', 'refresh',
        '--worktrees', str(current_lanes), '--baseline-worktrees', str(baseline_lanes),
        '--output', str(OUT / 'reviewed-manifest-refresh.json')])
    refresh = json.loads((OUT / 'reviewed-manifest-refresh.json').read_text())
    assert refresh['passed'] is True and refresh['policies_changed'] is False
    changed = set(git('diff', '--name-only').splitlines()) | set(git('ls-files', '--others', '--exclude-standard').splitlines())
    assert changed == set(request['reviewed_files']), changed
    git('add', '--', *request['reviewed_files'])
    command('publication-diff-check', ['git', 'diff', '--check', '--cached'])
    (OUT / 'reviewed-publication.patch').write_bytes(subprocess.check_output(['git', 'diff', '--cached', '--binary', '--full-index']))
    tree = git('write-tree')
    stamp = datetime.now(timezone.utc).replace(microsecond=0)
    identity = dict(name='github-actions[bot]', email='41898282+github-actions[bot]@users.noreply.github.com', date=stamp.isoformat().replace('+00:00', 'Z'))
    env = dict(os.environ, GIT_AUTHOR_NAME=identity['name'], GIT_AUTHOR_EMAIL=identity['email'],
        GIT_COMMITTER_NAME=identity['name'], GIT_COMMITTER_EMAIL=identity['email'],
        GIT_AUTHOR_DATE=identity['date'], GIT_COMMITTER_DATE=identity['date'])
    sha = subprocess.check_output(['git', 'commit-tree', tree, '-p', PARENT], input=MESSAGE+'\n', text=True, env=env).strip()
    # This is an isolated preparation checkout; only the reviewed files are staged.
    git('reset', '--hard', sha)
    assert not git('status', '--porcelain')
    command('exact-build-preflight', [sys.executable, '-m', 'certification.build_consistency', 'verify',
        '--worktrees', str(current_lanes), '--expected-sha', sha, '--output', str(OUT / 'exact-build-preflight.json')])
    command('focused-complete-publication-tests', [sys.executable, '-m', 'unittest', '-v',
        'tests.test_run381_archive_scheduling', 'tests.test_run381_maintenance_overlap',
        'tests.test_run381_retention_progress', 'tests.test_retention_outcomes',
        'certification.tests.test_lifecycle_capacity', 'certification.tests.test_build_consistency',
        'certification.tests.test_stagee24_environment', 'certification.tests.test_dispatch_phase_e',
        'certification.tests.test_stagee25_promotion', 'certification.tests.test_stagee27_cohort_wiring'])
    log = (OUT / 'focused-complete-publication-tests.log').read_text()
    total = re.search(r'^Ran (\d+) tests in ', log, re.M)
    assert total and re.search(r'^OK\s*$', log, re.M) and not re.search(r'\bskipped\b', log, re.I)
    from certification.maintenance_qualification import frozen_inputs
    assert frozen_inputs()
    assert api.request('GET', 'git/ref/heads/' + BRANCH)['object']['sha'] == PARENT
    entries = [dict(path=path, mode='100644', type='blob', content=(ROOT/path).read_text()) for path in request['reviewed_files']]
    remote_tree = api.request('POST', 'git/trees', dict(base_tree=git('rev-parse', PARENT+'^{tree}'), tree=entries))
    assert remote_tree['sha'] == tree, 'remote tree differs from verified local tree'
    # Publish this exact Git object once, but do not move any branch or dispatch.
    remote = api.request('POST', 'git/commits', dict(message=MESSAGE, tree=tree, parents=[PARENT], author=identity, committer=identity))
    save('remote-commit.json', remote)
    assert remote['sha'] == sha, ('remote commit identity differs', remote['sha'], sha)
    save('candidate.json', dict(sha=sha, tree=tree, parent=PARENT, reviewed_files=request['reviewed_files'],
        tests_run=int(total[1]), failures=0, errors=0, skipped=0, build_preflight_passed=True,
        remote_exact_identity=True, branch_updated=False, policies_changed=False, runtime_changed=False,
        paper_only=True, market_authority=False, canonical_authority=False))
    command('git-fsck', ['git', 'fsck', '--full', '--no-reflogs'])
    command('source-bundle', ['git', 'bundle', 'create', str(OUT/'source-and-lane-history.bundle'), '--all'])
    print((OUT / 'candidate.json').read_text(), flush=True)


if __name__ == '__main__':
    try:
        main()
    finally:
        if OUT.exists():
            sums = {str(p.relative_to(OUT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in OUT.rglob('*') if p.is_file() and p.name != 'SHA256.json'}
            save('SHA256.json', sums)
