"""Recover reviewed E27 bytes and publish plain blobs; never move a ref or dispatch."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError

ROOT = Path.cwd().resolve()
HERE = Path(__file__).resolve().parent
OUT = Path(os.environ['RUNNER_TEMP']) / 'e27-complete-publication'
PARENT = 'fdeee2721d2bb63e0ff3234328b06936257493b1'
BRANCH = 'repair/stagee27-archive-ready-allocation-20260928'
PRESERVED_RUN = 36524401712
PRESERVED_ARTIFACT = 'e27-complete-publication-36524401712-1'
PRESERVED_DIGEST = 'sha256:5b39467347bdce0adf529ac3535696b24e2bd3e4466d5a050fdaf9af8ac1f963'
RECOVERED_TREE = 'bf7ab6e2285dfc8163dc9c9842a1bc5ee20e0847'
sys.path.insert(0, str(ROOT))


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def save(name, row):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2) + '\n')


def execute(name, args):
    with (OUT / (name + '.log')).open('wb') as stream:
        result = subprocess.run(args, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    print(json.dumps(dict(step=name, returncode=result.returncode)), flush=True)
    if result.returncode:
        raise RuntimeError('preparation_failed:' + name)


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    assert os.environ['GITHUB_RUN_ATTEMPT'] == '1'
    assert git('rev-parse', 'HEAD') == PARENT and not git('status', '--porcelain')
    from certification.prospective_program import GitHub
    api = GitHub()
    assert api.request('GET', 'git/ref/heads/' + BRANCH)['object']['sha'] == PARENT
    save('parent-identity.json', dict(sha=PARENT, tree=git('rev-parse', 'HEAD^{tree}'),
         control_sha=os.environ['GITHUB_SHA'], run_id=os.environ['GITHUB_RUN_ID']))
    archive, metadata = api.artifact(PRESERVED_RUN, PRESERVED_ARTIFACT)
    assert metadata['digest'] == PRESERVED_DIGEST
    sums = json.loads(archive.read('SHA256.json'))
    for name, expected in sums.items():
        assert hashlib.sha256(archive.read(name)).hexdigest() == expected, name
    save('preserved-artifact.json', metadata)
    prior = OUT / 'preserved'
    prior.mkdir()
    for name in ('reviewed-publication.patch', 'original-build-preflight.json',
                 'exact-build-preflight.json', 'reviewed-manifest-refresh.json',
                 'focused-complete-publication-tests.log'):
        (prior / name).write_bytes(archive.read(name))
    assert json.loads((prior/'exact-build-preflight.json').read_text())['passed'] is True
    assert json.loads((prior/'reviewed-manifest-refresh.json').read_text())['policies_changed'] is False
    execute('recover-reviewed-tree', ['git', 'apply', '--index', str(prior/'reviewed-publication.patch')])
    assert git('write-tree') == RECOVERED_TREE, 'preserved publication tree differs'
    # Evidence-backed independent defect: promotion's legacy adapter returns None
    # for HTTP 204; the unmodified dispatcher crashes after its single POST.
    patch = HERE / 'dispatch-http204-repair.patch'
    execute('apply-demonstrated-dispatch-fix', ['git', 'apply', '--index', str(patch)])
    save('dispatch-defect.json', json.loads((HERE/'dispatch-http204-defect.json').read_text()))
    request_path = ROOT / '.github/stagee27/cohort-request.json'
    request = json.loads(request_path.read_text())
    request['generation'] = 'e27-complete-publication-v2-http204'
    request['reviewed_files'] += ['certification/dispatch_phase_e.py',
                                 'certification/tests/test_stagee25_promotion.py']
    request['superseded_local_candidate'] = 'eec4e05692b05afbd89d8f429065fbb29e262091'
    request_path.write_text(json.dumps(request, indent=2)+'\n')
    git('add', '--', '.github/stagee27/cohort-request.json')
    assert set(git('diff', '--cached', '--name-only').splitlines()) == set(request['reviewed_files'])
    assert not git('diff', '--name-only')
    assert not git('diff', '--cached', '--name-only', '--', 'meme_machine', 'tests')
    execute('reviewed-diff-check', ['git', 'diff', '--cached', '--check'])
    from certification.maintenance_qualification import frozen_inputs
    assert frozen_inputs()
    execute('focused-tree-tests', [sys.executable, '-m', 'unittest', '-v',
        'tests.test_run381_archive_scheduling', 'tests.test_run381_maintenance_overlap',
        'tests.test_run381_retention_progress', 'tests.test_retention_outcomes',
        'certification.tests.test_lifecycle_capacity', 'certification.tests.test_build_consistency',
        'certification.tests.test_stagee24_environment', 'certification.tests.test_dispatch_phase_e',
        'certification.tests.test_stagee25_promotion', 'certification.tests.test_stagee27_cohort_wiring'])
    log = (OUT/'focused-tree-tests.log').read_text()
    total = re.search(r'^Ran (\d+) tests in ', log, re.M)
    assert total and int(total[1]) == 104 and re.search(r'^OK\s*$', log, re.M)
    assert not re.search(r'\bskipped\b', log, re.I)
    tree = git('write-tree')
    (OUT/'reviewed-publication.patch').write_bytes(subprocess.check_output(
        ['git', 'diff', '--cached', '--binary', '--full-index'], cwd=ROOT))
    execute('preserve-candidate-tree', ['git', 'archive', '--format=tar.gz', '--output', str(OUT/'candidate-tree.tar.gz'), tree])
    execute('preserve-source-history', ['git', 'bundle', 'create', str(OUT/'source-history.bundle'), '--all'])
    assert api.request('GET', 'git/ref/heads/' + BRANCH)['object']['sha'] == PARENT
    files = []
    for path in request['reviewed_files']:
        raw = (ROOT/path).read_bytes()
        blob = hashlib.sha1(('blob '+str(len(raw))+'\0').encode()+raw).hexdigest()
        # These two immutable blobs were already published by the connection.
        if path not in ('.github/workflows/stagee-fixed-cohort.yml',
                        'certification/tests/test_stagee27_cohort_wiring.py'):
            try:
                result = api.request('POST', 'git/blobs', dict(encoding='base64',
                    content=base64.b64encode(raw).decode()))
            except HTTPError as exc:
                save('publication-error.json', dict(method='POST', path='git/blobs',
                    status=exc.code, body=exc.read(8192).decode(errors='replace')))
                raise
            assert result['sha'] == blob, path
        files.append(dict(path=path, mode='100644', type='blob', sha=blob))
        save('published-blobs.json', files)
    save('prepared-tree.json', dict(parent=PARENT, parent_tree=git('rev-parse', 'HEAD^{tree}'),
        tree=tree, files=files, tests_run=104, failures=0, errors=0, skipped=0,
        runtime_changed=False, policies_changed=False, gates_changed=False,
        commit_created=False, branch_updated=False, paper_only=True, market_authority=False,
        requires_exact_commit_preflight=True))
    print((OUT/'prepared-tree.json').read_text(), flush=True)


if __name__ == '__main__':
    try:
        main()
    finally:
        if OUT.exists():
            save('SHA256.json', {str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in OUT.rglob('*') if p.is_file() and p.name != 'SHA256.json'})
