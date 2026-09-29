"""Pinned verification precedes exact-object publication. Never dispatch a cohort."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = 'levonmendall/The-Meme-Machine'
SHA = 'dc08f9064cf5e37b63f383f52aa709d0afc1723f'
TREE = '68736cf664169dee665762019800bf87ca0f1f67'
PARENT = 'ce4257309cb1f6ec68e38d363320edf62d59db7f'
CANONICAL = 'a775849c940d48bc8f809e99c075e421744bc53f'
BRANCH = 'recovery/qualify-publish-exact-dc08f906-20260929'
CONTROL_PARENT = '7fc626640f43851ba141578800e5bcfb95e1c1eb'
PUBLICATION = 'refs/heads/publication/exact-dc08f906-20260929'
BASE = Path(__file__).resolve().parent
REQ = json.loads((BASE / 'request.json').read_text())
RUNTIME = Path(os.environ['GITHUB_WORKSPACE']) / 'runtime'
OUT = Path(os.environ['RUNNER_TEMP']) / 'exact-dc08-qualification'
OUT.mkdir(parents=True, exist_ok=True)

def demand(condition, reason):
    if not condition:
        raise RuntimeError(reason)

def save(name, value):
    (OUT / name).write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')

def git(*args, cwd=RUNTIME):
    return subprocess.check_output(['git', *args], cwd=cwd).decode().strip()

def identity():
    row = dict(sha=git('rev-parse', 'HEAD'), tree=git('rev-parse', 'HEAD^{tree}'),
               parent=git('rev-parse', 'HEAD^'), clean=not git('status', '--porcelain'))
    demand(row == dict(sha=SHA, tree=TREE, parent=PARENT, clean=True), 'runtime_identity_or_cleanliness')
    return row

def snapshot():
    names = git('ls-files', '-z').split('\0')
    rows = {p: hashlib.sha256((RUNTIME / p).read_bytes()).hexdigest() for p in names if p}
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    demand(len(rows) == REQ['source_files'] and digest == REQ['source_digest'], 'source_bytes_mismatch')
    return dict(files=rows, digest=digest)

def get(path, missing=False):
    request = urllib.request.Request('https://api.github.com/repos/' + REPO + '/' + path,
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if missing and exc.code == 404:
            return None
        raise

def state_guard():
    repair = get('git/ref/heads/repair/stagee27-archive-ready-allocation-20260928')
    canonical = get('git/ref/heads/cert/autonomous-paper-machinery-20260927')
    demand(repair['object']['sha'] == PARENT, 'repair_ref_advanced')
    demand(canonical['object']['sha'] == CANONICAL, 'canonical_ref_advanced')
    run_id = int(os.environ['GITHUB_RUN_ID'])
    for status in ('queued', 'in_progress'):
        data = get('actions/runs?status=' + status + '&per_page=100')
        demand(data['total_count'] <= 100, 'incomplete_competing_run_listing')
        demand(all(r['id'] == run_id or r['path'] == '.github/workflows/ci.yml'
                   for r in data['workflow_runs']), 'competing_authority_run')
    data = get('actions/runs?head_sha=' + SHA + '&per_page=100')
    demand(data['total_count'] == 0, 'candidate_has_prior_workflow')
    save('remote-state.json', dict(repair=PARENT, canonical=CANONICAL,
         no_candidate_runs=True, run_id=run_id, checked_at=time.time()))

def control_guard():
    control = Path(os.environ['GITHUB_WORKSPACE']) / 'control'
    demand(os.environ['GITHUB_RUN_ATTEMPT'] == '1', 'no_reruns')
    demand(os.environ['GITHUB_REF'] == 'refs/heads/' + BRANCH, 'wrong_control_branch')
    demand(git('rev-parse', 'HEAD', cwd=control) == os.environ['GITHUB_SHA'], 'control_head_mismatch')
    demand(git('rev-parse', 'HEAD^', cwd=control) == CONTROL_PARENT, 'control_parent_mismatch')
    demand(REQ['runtime'] == dict(sha=SHA, tree=TREE, parent=PARENT), 'request_identity')
    demand(REQ['expected_tests'] == 286, 'wrong_test_count')
    demand(not any(REQ[k] for k in ('cohort_authority', 'canonical_authority', 'market_authority')), 'control_authority')
    actual = set(git('diff', '--name-only', CONTROL_PARENT, 'HEAD', cwd=control).splitlines())
    expected = {'.github/exact-dc08/chunk-%02d' % i for i in range(19)}
    expected |= {'.github/exact-dc08/request.json', '.github/exact-dc08/qualify_publish.py',
                 '.github/workflows/qualify-publish-exact-dc08f906.yml'}
    demand(actual == expected, 'unexpected_control_diff')
    demand(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == REQ['driver_sha256'], 'driver_hash')

def command(name, args, timeout=900):
    began = time.time()
    row = dict(command=args, started=began, finished=None, returncode=None)
    save(name + '.json', row)
    print(json.dumps(dict(step=name, status='started')), flush=True)
    try:
        with (OUT / (name + '.log')).open('w') as log:
            result = subprocess.run(args, cwd=RUNTIME, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        row['returncode'] = result.returncode
    except BaseException as exc:
        row['exception'] = type(exc).__name__ + ':' + str(exc)
        raise
    finally:
        row['finished'] = time.time()
        save(name + '.json', row)
        print(json.dumps(dict(step=name, returncode=row['returncode'])), flush=True)
    demand(row['returncode'] == 0, 'step_failed:' + name)
    return row

def restore():
    control_guard()
    state_guard()
    demand(git('rev-parse', 'HEAD') == PARENT and not git('status', '--porcelain'), 'restore_base')
    parts = []
    for i, item in enumerate(REQ['chunks']):
        data = (BASE / ('chunk-%02d' % i)).read_bytes()
        digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        demand(digest == item['blob'] and len(data) == item['bytes'], 'chunk_identity:' + str(i))
        parts.append(data)
    data = b''.join(parts)
    demand(len(data) == 37966 and hashlib.sha256(data).hexdigest() == REQ['bundle_sha256'], 'bundle_hash')
    bundle = OUT / 'exact-candidate.bundle'
    bundle.write_bytes(data)
    git('bundle', 'verify', str(bundle))
    git('fetch', str(bundle), 'HEAD')
    git('checkout', '--detach', SHA)
    row = identity()
    demand(sorted(git('diff', '--name-only', PARENT, SHA).splitlines()) == sorted(REQ['changed_files']), 'candidate_diff')
    plan = RUNTIME / 'certification/stagee24_qualification_plan.json'
    demand(hashlib.sha256(plan.read_bytes()).hexdigest() == REQ['plan_sha256'], 'frozen_plan')
    save('restored-identity.json', row)
    save('source-before.json', snapshot())
    (OUT / 'commit.raw').write_bytes(subprocess.check_output(['git', 'cat-file', 'commit', SHA], cwd=RUNTIME))
    command('git-integrity', ['git', 'fsck', '--full', '--no-reflogs'])
    save('control-binding.json', dict(control_sha=os.environ['GITHUB_SHA'], run_id=int(os.environ['GITHUB_RUN_ID']),
        attempt=1, request=REQ, publication_done=False, cohort_dispatched=False))

def qualify():
    control_guard()
    identity()
    snapshot()
    result = dict(passed=False, runtime_sha=SHA, tests=None, failure=None,
                  cohort_dispatched=False, canonical_authority=False, market_authority=False)
    try:
        command('frozen-environment', [sys.executable, '-m', 'certification.qualification_environment',
                                     '--output', str(OUT / 'environment.json')])
        env = json.loads((OUT / 'environment.json').read_text())
        demand(env['passed'] and env['python'] == '3.12.14' and env['dependencies'] == {'websockets': '17.1'}, 'pinned_environment')
        worktrees = Path(os.environ['RUNNER_TEMP']) / 'dc08-native-lanes'
        command('prepare-native-build', [sys.executable, '-m', 'certification.run', 'prepare', '--worktrees', str(worktrees)])
        command('exact-native-build', [sys.executable, '-m', 'certification.build_consistency', 'verify',
             '--worktrees', str(worktrees), '--expected-sha', SHA, '--output', str(OUT / 'build-consistency.json')])
        command('focused-integrated-286', [sys.executable, '-m', 'unittest', '-v', *REQ['test_modules']])
        text = (OUT / 'focused-integrated-286.log').read_text()
        footers = re.findall(r'^Ran (\d+) tests? in ([0-9.]+)s\s*\n\s*\n(OK[^\n]*|FAILED[^\n]*)', text, re.M)
        demand(bool(footers), 'test_footer_missing')
        count, seconds, status = footers[-1]
        demand(int(count) == 286 and status.strip() == 'OK', 'test_count_failure_or_skips')
        result['tests'] = dict(run=286, passed=286, failures=0, errors=0, skips=0, seconds=float(seconds))
        save('source-after.json', snapshot())
        identity()
        result.update(passed=True, environment=env, source_unchanged=True, finished=time.time())
    except BaseException as exc:
        result['failure'] = type(exc).__name__ + ':' + str(exc)
        raise
    finally:
        save('qualification-result.json', result)

def publish():
    control_guard()
    identity()
    snapshot()
    result = json.loads((OUT / 'qualification-result.json').read_text())
    demand(result['passed'] and result['runtime_sha'] == SHA and result['tests']['passed'] == 286, 'qualification_not_green')
    demand(result['environment']['python'] == '3.12.14' and result['environment']['dependencies'] == {'websockets': '17.1'}, 'publication_environment')
    state_guard()
    existing = get('git/ref/' + PUBLICATION.removeprefix('refs/'), missing=True)
    demand(existing is None or existing['object']['sha'] == SHA, 'publication_ref_conflict')
    save('publication-intent.json', dict(sha=SHA, tree=TREE, parent=PARENT, ref=PUBLICATION,
         qualification_completed=True, run_id=int(os.environ['GITHUB_RUN_ID']), attempts=1,
         canonical_authority=False, cohort_authority=False, market_authority=False))
    if existing is None:
        auth = base64.b64encode(('x-access-token:' + os.environ['GH_TOKEN']).encode()).decode()
        print('::add-mask::' + auth, flush=True)
        env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_CONFIG_COUNT='1',
                   GIT_CONFIG_KEY_0='http.https://github.com/.extraheader', GIT_CONFIG_VALUE_0='AUTHORIZATION: basic ' + auth)
        try:
            p = subprocess.run(['git', 'push', '--porcelain', '--force-with-lease=' + PUBLICATION + ':',
                'https://github.com/' + REPO + '.git', SHA + ':' + PUBLICATION], cwd=RUNTIME, env=env,
                capture_output=True, text=True, timeout=120)
            (OUT / 'push.log').write_text((p.stdout + p.stderr).replace(os.environ['GH_TOKEN'], '[REDACTED]').replace(auth, '[REDACTED]'))
            save('push-result.json', dict(returncode=p.returncode, attempts=1))
        except subprocess.TimeoutExpired:
            save('push-result.json', dict(ambiguous_timeout=True, attempts=1))
        # Reconcile by GET, never issue a second push after an ambiguous response.
    remote = get('git/commits/' + SHA)
    demand(remote['sha'] == SHA and remote['tree']['sha'] == TREE and [p['sha'] for p in remote['parents']] == [PARENT], 'remote_object_identity')
    demand(get('git/ref/' + PUBLICATION.removeprefix('refs/'))['object']['sha'] == SHA, 'publication_ref_identity')
    state_guard()
    save('remote-identity.json', remote)
    save('publication-result.json', dict(sha=SHA, tree=TREE, parent=PARENT, ref=PUBLICATION,
         remote_verified=True, qualification_passed=True, cohort_dispatched=False, canonical_promoted=False))
    print(json.dumps(dict(sha=SHA, qualified=True, published=True, cohort_dispatched=False)), flush=True)

def seal():
    manifest = {str(p.relative_to(OUT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(OUT.rglob('*')) if p.is_file() and p.name != 'SHA256.json'}
    save('SHA256.json', manifest)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['restore', 'qualify', 'publish', 'seal'])
    args = parser.parse_args()
    try:
        globals()[args.phase]()
    except BaseException as exc:
        save(args.phase + '-failure.json', dict(type=type(exc).__name__, error=str(exc), runtime_sha=SHA))
        raise
