"""Durable local sealing and bounded GitHub transport; never executes a trial.

Large evidence files are published as numbered <=16-MiB blobs. Original paths,
sizes and SHA-256 are verified after reconstruction; a partial commit is refused.
The transport callback is injectable for deterministic tests. Live writes are an
explicit future operation and can create only a fresh evidence branch.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import urllib.request

from frozen import *
from preserve import fsync_dir, persist, seal, verify_inventory, redundant_copy

CHUNK_BYTES = 16 * 1024**2
REPO = 'levonmendall/The-Meme-Machine'
MANIFEST = 'TRANSPORT_MANIFEST.json'


def safe_file(root, name):
    require(type(name) is str and name and '\\' not in name and not Path(name).is_absolute()
            and '..' not in Path(name).parts, 'unsafe_publication_path')
    root = Path(root).resolve()
    p = root / name
    for ancestor in (p, *p.parents):
        if ancestor == root.parent: break
        require(not ancestor.is_symlink(), 'publication_symlink')
    require(p.resolve().is_relative_to(root), 'publication_path_escape')
    return p


def exclusive_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(data); out.flush(); os.fsync(out.fileno())
    for parent in (path.parent, *path.parent.parents):
        fsync_dir(parent)
        if parent == ROOT or parent == Path('/'): break
    require(file_sha(path) == sha(data), 'local_durable_readback_failed')


def snapshot_tree(root):
    root = Path(root).resolve()
    require(root.is_dir(), 'evidence_root_missing')
    rows = []
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'evidence_symlink')
        s = path.lstat()
        if stat.S_ISDIR(s.st_mode): continue
        require(stat.S_ISREG(s.st_mode), 'nonregular_evidence')
        rows.append(dict(path=path.relative_to(root).as_posix(), bytes=s.st_size,
                         sha256=file_sha(path)))
    require(rows, 'empty_evidence_cannot_be_preserved')
    return rows


def stage_transport(source, output, *, class_id, campaign, declaration_sha256, inventory_name):
    require(class_id in ('A', 'B', 'C', 'FINAL', 'PREFLIGHT', 'PRESERVED'), 'transport_class')
    require(re.fullmatch(r'[A-Za-z0-9_.-]{1,180}', campaign) and re.fullmatch(r'[0-9a-f]{64}', declaration_sha256),
            'transport_identity')
    verify_inventory(source, name=inventory_name)
    rows = snapshot_tree(source)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    artifacts = []
    for index, row in enumerate(rows):
        chunks = []
        with safe_file(source, row['path']).open('rb') as stream:
            n = 0
            while block := stream.read(CHUNK_BYTES):
                name = f'blobs/{index:06d}/{n:06d}.bin'
                exclusive_bytes(output / name, block)
                chunks.append(dict(path=name, bytes=len(block), sha256=sha(block)))
                n += 1
        artifacts.append(dict(row, chunks=chunks))
    require(snapshot_tree(source) == rows, 'evidence_changed_during_transport_staging')
    m = dict(version='stage-e-native-v3-chunked-evidence-transport', **FROZEN,
        class_id=class_id, campaign=campaign, declaration_sha256=declaration_sha256,
        inventory_name=inventory_name, inventory_sha256=file_sha(Path(source) / inventory_name),
        source_artifacts=artifacts, chunk_bytes=CHUNK_BYTES, evidence_acceptance_asserted=False)
    persist(output / MANIFEST, m)
    fsync_dir(output.parent)
    return m


def validate_transport(m):
    exact_frozen(m)
    require(m.get('version') == 'stage-e-native-v3-chunked-evidence-transport'
            and m.get('evidence_acceptance_asserted') is False and m.get('chunk_bytes') == CHUNK_BYTES,
            'transport_manifest_schema')
    rows = m['source_artifacts']
    require(type(rows) is list and rows and len(rows) <= 100000, 'transport_artifact_bound')
    seen, chunks = set(), set()
    for i, row in enumerate(rows):
        name = row['path']
        require(type(name) is str and name and not Path(name).is_absolute()
                and '..' not in Path(name).parts and '\\' not in name and name not in seen,
                'transport_duplicate_or_unsafe_artifact')
        seen.add(name)
        require(type(row['bytes']) is int and row['bytes'] >= 0
                and re.fullmatch(r'[0-9a-f]{64}', row['sha256']), 'transport_artifact_identity')
        total = 0
        expected_count = (row['bytes'] + CHUNK_BYTES - 1) // CHUNK_BYTES
        require(type(row['chunks']) is list and len(row['chunks']) == expected_count,
                'partial_transport_chunk_inventory')
        for n, chunk in enumerate(row['chunks']):
            require(chunk['path'] == f'blobs/{i:06d}/{n:06d}.bin' and chunk['path'] not in chunks
                    and type(chunk['bytes']) is int and chunk['bytes'] == min(CHUNK_BYTES, row['bytes'] - total)
                    and re.fullmatch(r'[0-9a-f]{64}', chunk['sha256']), 'transport_chunk_identity')
            chunks.add(chunk['path']); total += chunk['bytes']
        require(total == row['bytes'], 'partial_transport_bytes')
    require(m['inventory_name'] in seen, 'transport_seal_missing')
    return chunks | {MANIFEST}


def readback_manifest(manifest_bytes, fetch_bytes, list_paths, output, *, expected_manifest_sha256):
    require(sha(manifest_bytes) == expected_manifest_sha256, 'remote_transport_manifest_changed')
    # Strict duplicate-key parsing via approved reader, without trusting PASS flags.
    def pairs(items):
        d = {}
        for k, v in items:
            require(k not in d, 'duplicate_remote_json_key'); d[k] = v
        return d
    m = json.loads(manifest_bytes, object_pairs_hook=pairs,
                   parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_remote_json')))
    expected_paths = validate_transport(m)
    require(set(list_paths) == expected_paths and len(list_paths) == len(expected_paths),
            'partial_torn_or_extra_remote_publication')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for row in m['source_artifacts']:
        path = safe_file(output, row['path']); path.parent.mkdir(parents=True, exist_ok=True)
        h, total = hashlib.sha256(), 0
        with path.open('xb') as out:
            for chunk in row['chunks']:
                data = fetch_bytes(chunk['path'])
                require(type(data) is bytes and len(data) == chunk['bytes'] and sha(data) == chunk['sha256'],
                        'remote_chunk_missing_torn_or_mismatched')
                out.write(data); h.update(data); total += len(data)
            out.flush(); os.fsync(out.fileno())
        require(total == row['bytes'] and h.hexdigest() == row['sha256'] and file_sha(path) == row['sha256'],
                'independent_remote_artifact_hash_mismatch')
    for directory in sorted((p for p in output.rglob('*') if p.is_dir()), reverse=True): fsync_dir(directory)
    fsync_dir(output); fsync_dir(output.parent)
    verify_inventory(output, name=m['inventory_name'])
    require(file_sha(output / m['inventory_name']) == m['inventory_sha256'], 'remote_raw_inventory_changed')
    require(snapshot_tree(output) == [{k: row[k] for k in ('path', 'bytes', 'sha256')} for row in m['source_artifacts']],
            'remote_reconstruction_inventory_mismatch')
    return dict(version='stage-e-native-v3-independent-remote-readback', **FROZEN,
        manifest_sha256=expected_manifest_sha256, inventory_sha256=m['inventory_sha256'],
        class_id=m['class_id'], campaign=m['campaign'], declaration_sha256=m['declaration_sha256'],
        output=str(output.resolve()), independently_recomputed_sha256=True,
        complete=True, acceptance_credit=False, artifacts=len(m['source_artifacts']))


class GitHub:
    """Credential-aware API; only Git data on this repository, no workflows."""
    def __init__(self):
        self.base = 'https://api.github.com/repos/' + REPO

    def __call__(self, method, path, value=None):
        require(method in ('GET', 'POST') and path.startswith('/git/'), 'transport_API_scope')
        headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
        token = os.environ.get('GH_TOKEN')
        if token: headers['Authorization'] = 'Bearer ' + token
        require(method == 'GET' or token, 'publication_credential_missing')
        body = canonical(value) if value is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(32 * 1024**2 + 1)
        require(len(data) <= 32 * 1024**2, 'GitHub_response_bound')
        return json.loads(data)


def publish_transport(staged, branch, *, parent_commit, api):
    require(branch.startswith('diagnostics/stage-e-native-v3-evidence/')
            and re.fullmatch(r'[A-Za-z0-9_./-]{1,240}', branch) and '..' not in branch,
            'publication_branch_must_be_fresh_evidence_namespace')
    require(re.fullmatch(r'[0-9a-f]{40}', parent_commit), 'publication_parent_commit')
    m = read(Path(staged) / MANIFEST); paths = validate_transport(m)
    require({r['path'] for r in snapshot_tree(staged)} == paths, 'staged_publication_missing_or_extra')
    for row in m['source_artifacts']:
        h = hashlib.sha256()
        for chunk in row['chunks']:
            p = safe_file(staged, chunk['path'])
            require(p.stat().st_size == chunk['bytes'] and file_sha(p) == chunk['sha256'],
                    'staged_publication_modified_after_manifest')
            h.update(p.read_bytes())
        require(h.hexdigest() == row['sha256'], 'staged_reassembled_bytes_mismatch')
    before = snapshot_tree(staged)
    elements = []
    for path in sorted(paths):
        data = safe_file(staged, path).read_bytes()
        blob = api('POST', '/git/blobs', dict(content=base64.b64encode(data).decode(), encoding='base64'))
        require(re.fullmatch(r'[0-9a-f]{40}', blob['sha']), 'GitHub_blob_identity')
        elements.append(dict(path=path, mode='100644', type='blob', sha=blob['sha']))
    tree = api('POST', '/git/trees', dict(tree=elements))
    commit = api('POST', '/git/commits', dict(message='[skip ci] Preserve native-v3 evidence bytes',
                                           tree=tree['sha'], parents=[parent_commit]))
    require(snapshot_tree(staged) == before, 'staged_bytes_changed_during_publication')
    # Creating a ref is exclusive. There is deliberately no update-ref/retry path.
    api('POST', '/git/refs', dict(ref='refs/heads/' + branch, sha=commit['sha']))
    return dict(branch=branch, commit=commit['sha'], tree=tree['sha'], manifest_sha256=file_sha(Path(staged) / MANIFEST),
                readback_required=True, acceptance_credit=False)


def readback_github(commit, output, *, expected_manifest_sha256, api):
    require(re.fullmatch(r'[0-9a-f]{40}', commit), 'immutable_remote_commit_required')
    tree = api('GET', '/git/trees/' + commit + '?recursive=1')
    require(tree.get('truncated') is False, 'truncated_remote_inventory')
    entries = [r for r in tree['tree'] if r['type'] == 'blob']
    require(all(r['type'] in ('blob', 'tree') for r in tree['tree']) and all(r['mode'] == '100644' for r in entries),
            'remote_link_or_executable_transport')
    indexed = {r['path']: r for r in entries}
    require(len(indexed) == len(entries) and MANIFEST in indexed, 'remote_manifest_missing_or_duplicated')
    def fetch(path):
        blob = api('GET', '/git/blobs/' + indexed[path]['sha'])
        require(blob['encoding'] == 'base64', 'remote_blob_encoding')
        return base64.b64decode(blob['content'].replace('\n', ''), validate=True)
    receipt = readback_manifest(fetch(MANIFEST), fetch, list(indexed), output,
                                expected_manifest_sha256=expected_manifest_sha256)
    require(api('GET', '/git/trees/' + commit + '?recursive=1') == tree, 'remote_tree_changed_during_readback')
    return dict(receipt, repository=REPO, commit=commit)


def preserve_fixture_or_evidence(source, redundant, *, inventory_name='RAW_INVENTORY.json'):
    """Operator must use fresh destinations. No campaign registry is touched."""
    require(Path(source).resolve() != Path(redundant).resolve(), 'redundant_copy_alias')
    seal(source, name=inventory_name)
    receipt = redundant_copy(source, redundant, name=inventory_name)
    for path in Path(redundant).rglob('*'):
        if path.is_file(): path.chmod(0o444)
    for path in sorted((p for p in Path(redundant).rglob('*') if p.is_dir()), reverse=True): path.chmod(0o555)
    fsync_dir(Path(redundant)); fsync_dir(Path(redundant).parent)
    return dict(receipt, source=str(Path(source).resolve()), files_fsynced=True,
                parent_directories_fsynced=True, redundant_files_immutable=True,
                acceptance_credit=False)
