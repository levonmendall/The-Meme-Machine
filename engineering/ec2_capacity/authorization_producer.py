"""Publish one immutable isolated-capacity manifest for separate owner approval.

Run only by the pinned GitHub-hosted producer workflow. Candidate files are data:
this module never imports or executes the candidate, and has no EC2 credentials.
The root deployer independently repeats source, CI, approval and policy checks.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

REPO = 'levonmendall/The-Meme-Machine'
BRANCH = 'ec2-capacity-authorizations'
CI = {
    390790230: '.github/workflows/managed-capacity-offline.yml',
    360046812: '.github/workflows/ci.yml',
}
MAX_SOURCE = 4 * 1024**3
MAX_FILE = 512 * 1024**2
MAX_MANIFEST = 1024 * 1024


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value, length):
    need(type(value) is str and re.fullmatch('[0-9a-f]{%d}' % length, value),
         'exact_digest_required')
    return value


def producer_title(commit, previous, release, review):
    return 'EC2AUTH %s %s %s %s' % (digest(commit, 40), digest(previous, 64),
        digest(release, 64), digest(review, 64))


def source_census(directory, expected_commit):
    """Read committed blobs, with no checkout, hooks or candidate execution."""
    def git(*args):
        return subprocess.check_output(['/usr/bin/git', '--no-optional-locks',
            '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
            '-C', str(directory), *args], stdin=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=90,
            env=dict(PATH='/usr/bin:/bin', LANG='C', GIT_CONFIG_NOSYSTEM='1',
                GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0'))
    commit, tree = git('rev-parse', 'HEAD', 'HEAD^{tree}').decode().splitlines()
    need(commit == digest(expected_commit, 40), 'candidate_commit_mismatch')
    files = {}; total = 0
    for entry in git('ls-tree', '-r', '-z', '--full-tree', tree).split(b'\0'):
        if not entry:
            continue
        metadata, raw_name = entry.split(b'\t', 1)
        mode, kind, oid = metadata.split()
        name = raw_name.decode('utf8')
        need(kind == b'blob' and mode in (b'100644', b'100755') and name and
             not name.startswith('/') and '\\' not in name and
             all(p not in ('', '.', '..') for p in name.split('/')) and
             name not in files and len(files) < 10000, 'candidate_regular_files_only')
        size = int(git('cat-file', '-s', oid.decode()))
        need(0 <= size <= MAX_FILE and total + size <= MAX_SOURCE,
             'candidate_source_bound')
        body = git('cat-file', 'blob', oid.decode())
        need(len(body) == size and hashlib.sha1(
            b'blob ' + str(size).encode() + b'\0' + body).hexdigest() == oid.decode(),
            'candidate_blob_identity')
        files[name] = sha(body); total += size
    need('meme_machine/operational/managed_capacity_workload.py' in files,
         'managed_entrypoint_required')
    return tree, files


def checked_ci(rows, commit):
    need(type(rows) is list and len(rows) == len(CI), 'exact_ci_runs_required')
    result = []; found = set()
    for row in rows:
        need(type(row) is dict, 'ci_shape')
        workflow = row.get('workflow_id')
        need(workflow in CI and workflow not in found and
             row.get('path') == CI[workflow] and row.get('head_sha') == commit and
             row.get('status') == 'completed' and row.get('conclusion') == 'success' and
             row.get('event') == 'pull_request' and
             row.get('repository', {}).get('full_name') == REPO and
             row.get('head_repository', {}).get('full_name') == REPO and
             type(row.get('id')) is int and row['id'] > 0 and
             type(row.get('run_attempt')) is int and row['run_attempt'] > 0,
             'exact_successful_ci_required')
        result.append(dict(run_id=row['id'], attempt=row['run_attempt']))
        found.add(workflow)
    need(found == set(CI), 'exact_ci_runs_required')
    return sorted(result, key=lambda row: row['run_id'])


def release_manifest(template, *, commit, tree, files, previous_commit,
                     previous_release, expected_release, review, ci_rows,
                     producer_run, producer_attempt):
    digest(commit, 40); digest(tree, 40); digest(previous_commit, 40)
    digest(previous_release, 64); digest(expected_release, 64); digest(review, 64)
    need(type(template) is dict and not any(k in template for k in
         ('application_commit', 'application_tree', 'application_files')),
         'fixed_template_required')
    need(type(producer_run) is int and producer_run > 0 and
         type(producer_attempt) is int and producer_attempt > 0,
         'producer_identity_required')
    release = dict(template, application_commit=commit, application_tree=tree,
                   application_files=files)
    need(sha(canonical(release)) == expected_release, 'frozen_release_mismatch')
    value = dict(schema='ec2-approved-isolated-release-v1',
        previous_application_commit=previous_commit,
        previous_release_sha256=previous_release,
        release=release, release_sha256=expected_release,
        ci_runs=checked_ci(ci_rows, commit), producer_run_id=producer_run,
        producer_attempt=producer_attempt, review_evidence_sha256=review)
    need(len(canonical(value)) <= MAX_MANIFEST, 'manifest_bound')
    return value


def github(path, *, method='GET', body=None):
    need(path.startswith('/') and '\n' not in path and '\r' not in path,
         'fixed_github_path')
    token = os.environ['GH_TOKEN']
    request = urllib.request.Request('https://api.github.com/repos/' + REPO + path,
        data=None if body is None else json.dumps(body).encode(), method=method,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
        raw = response.read(2 * 1024**2 + 1)
    need(len(raw) <= 2 * 1024**2, 'github_response_bound')
    return json.loads(raw)


def publish(manifest):
    """The Actions bot proposes data; it cannot approve the protected branch."""
    path = 'releases/' + manifest['release']['application_commit'] + '.json'
    head = github('/git/ref/heads/' + BRANCH)['object']['sha']
    parent = github('/git/commits/' + head)
    entries = github('/git/trees/' + parent['tree']['sha'] + '?recursive=1')
    need(entries.get('truncated') is False and all(
        entry.get('path') != path for entry in entries['tree']), 'release_already_proposed')
    blob = github('/git/blobs', method='POST', body={
        'content': base64.b64encode(canonical(manifest)).decode(), 'encoding': 'base64'})
    tree = github('/git/trees', method='POST', body={'base_tree': parent['tree']['sha'],
        'tree': [{'path': path, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']}]})
    commit = github('/git/commits', method='POST', body={
        'message': 'Propose reviewed isolated release ' + manifest['release']['application_commit'],
        'tree': tree['sha'], 'parents': [head]})
    branch = 'capacity-release-%d-%d' % (manifest['producer_run_id'], manifest['producer_attempt'])
    github('/git/refs', method='POST', body={'ref': 'refs/heads/' + branch, 'sha': commit['sha']})
    return github('/pulls', method='POST', body={
        'title': 'Authorize isolated EC2 source ' + manifest['release']['application_commit'],
        'head': branch, 'base': BRANCH,
        'body': ('Exact frozen nonfunded release; separate owner approval after independent code review is required.\n\n'
                 'Release SHA256: `' + manifest['release_sha256'] + '`\n\n'
                 'Review evidence SHA256: `' + manifest['review_evidence_sha256'] + '`\n\n'
                 'No EC2 installation is performed by this workflow.')})


def main():
    need(os.environ.get('GITHUB_REPOSITORY') == REPO and
         os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and
         os.environ.get('GITHUB_ACTOR_ID') == '307779841', 'owner_producer_dispatch_required')
    commit = digest(os.environ['CAPACITY_APPLICATION'], 40)
    tree, files = source_census(Path(os.environ['CAPACITY_SOURCE']), commit)
    template = json.loads((Path(__file__).parent / 'release-template.json').read_bytes())
    rows = [github('/actions/runs/' + str(int(os.environ[name]))) for name in
            ('CAPACITY_NATIVE_CI_RUN', 'CAPACITY_ADJACENT_CI_RUN')]
    manifest = release_manifest(template, commit=commit, tree=tree, files=files,
        previous_commit=os.environ['CAPACITY_PREVIOUS_APPLICATION'],
        previous_release=os.environ['CAPACITY_PREVIOUS_RELEASE'],
        expected_release=os.environ['CAPACITY_RELEASE'], review=os.environ['CAPACITY_REVIEW'],
        ci_rows=rows, producer_run=int(os.environ['GITHUB_RUN_ID']),
        producer_attempt=int(os.environ['GITHUB_RUN_ATTEMPT']))
    proposal = publish(manifest)
    print(json.dumps(dict(status='ISOLATED_RELEASE_PROPOSED_NOT_APPROVED',
        authorization_pr=proposal['number'], authorization_head=proposal['head']['sha'],
        release_sha256=manifest['release_sha256'], financial_authority=False), sort_keys=True))


if __name__ == '__main__':
    main()
