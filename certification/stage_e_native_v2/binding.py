"""Exact commit, complete immutable source assembly and per-process origins."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import sysconfig

from . import REPOSITORY
from .contract import HERE,canonical, identities, read, sha256, validate_inputs

EXECUTABLE_SUFFIXES = frozenset(('.py','.pyc','.pyo','.so','.pth','.sh','.bash','.js','.mjs','.zip','.whl'))


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root)


def tracked_entries(root, sha):
    entries = {}
    for line in git(root, 'ls-tree', '-rz', '--full-tree', sha).split(b'\0'):
        if not line:
            continue
        header, name = line.split(b'\t', 1)
        mode, kind, blob = header.decode().split()
        name = name.decode()
        if kind != 'blob' or mode not in ('100644','100755') or Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('unsupported_assembly_git_entry:' + name)
        entries[name] = dict(mode=mode, blob=blob)
    if not entries:
        raise ValueError('empty_candidate_tree')
    return entries


def check_checkout(root, expected_sha, expected_tree):
    root = Path(root).resolve()
    if git(root, 'rev-parse', 'HEAD').decode().strip() != expected_sha:
        raise ValueError('different_candidate_commit_even_if_equal_tree')
    if git(root, 'rev-parse', expected_sha+'^{tree}').decode().strip() != expected_tree:
        raise ValueError('candidate_tree_mismatch')
    entries = tracked_entries(root, expected_sha)
    if git(root, 'diff', '--no-ext-diff', '--name-only', expected_sha).strip():
        raise ValueError('dirty_tracked_content')
    for name, info in entries.items():
        path = root / name
        if path.is_symlink() or not path.is_file() or path.read_bytes() != git(root, 'cat-file', 'blob', info['blob']):
            raise ValueError('tracked_bytes_mismatch:' + name)
        if bool(path.stat().st_mode & 0o111) != (info['mode'] == '100755'):
            raise ValueError('tracked_mode_mismatch:' + name)
    # Git status alone omits ignored files. Inspect both ignored and untracked.
    extras = git(root, 'ls-files', '-z', '--others', '--exclude-standard').split(b'\0')
    extras += git(root, 'ls-files', '-z', '--others', '--ignored', '--exclude-standard').split(b'\0')
    for raw in extras:
        if not raw:
            continue
        path = root / raw.decode()
        if path.is_symlink() or path.suffix.lower() in EXECUTABLE_SUFFIXES or path.is_file() and path.stat().st_mode & 0o111:
            raise ValueError('untracked_or_ignored_executable_shadow:' + raw.decode())
    return entries


def environment_identity():
    # Runtime dependencies are separately versioned AND content pinned.
    dist = importlib.metadata.distribution('websockets')
    if platform.python_version() != '3.12.14' or dist.version != '17.1':
        raise ValueError('frozen_environment_mismatch')
    files = {}
    package_files={}
    for name in dist.files or []:
        path = Path(dist.locate_file(name)).resolve()
        if path.is_file() and path.suffix != '.pyc' and path.name not in ('RECORD','INSTALLER','REQUESTED'):
            files[str(path)] = sha256(path.read_bytes())
            package_files[str(name)] = files[str(path)]
    if not files:
        raise ValueError('dependency_identity_missing')
    lock=read(HERE/'dependency-lock-v2.json')['websockets']
    if dist.version!=lock['version'] or package_files!=lock['files']:
        raise ValueError('unapproved_dependency_bytes')
    # sys.base_prefix is the approved standard library, never a local module root.
    stdlib = str(Path(sysconfig.get_path('stdlib')).resolve())
    dependency_root = str(Path(dist.locate_file('')).resolve())
    stdlib_files={}
    for directory,dirs,names in os.walk(stdlib):
        dirs[:]=[d for d in dirs if d not in ('site-packages','dist-packages','__pycache__')]
        for name in names:
            p=Path(directory)/name
            if p.suffix in ('.py','.so') and p.is_file():stdlib_files[str(p.resolve())]=sha256(p.read_bytes())
    return dict(python=platform.python_version(), python_executable=str(Path(sys.executable).absolute()),
        python_executable_hash=sha256(Path(sys.executable).read_bytes()), sqlite=__import__('sqlite3').sqlite_version,
        platform=platform.platform(), stdlib=stdlib, stdlib_files=stdlib_files,
        stdlib_digest=sha256(canonical(stdlib_files)),dependency_root=dependency_root,
        dependencies={'websockets': {'version':dist.version, 'files':files,
            'digest':sha256(canonical(files))}})


def workflow_identity(row, candidate):
    required = {'workflow_path','resolved_workflow_sha','reusable_workflow_path',
                'reusable_workflow_sha','run_id','attempt','event','candidate_sha'}
    if not isinstance(row,dict) or set(row) != required:
        raise ValueError('workflow_identity_missing')
    if row['workflow_path'] != '.github/workflows/stagee-native-qualification-v2.yml' or row['reusable_workflow_path'] != '.github/workflows/stagee-native-qualification-v2-reusable.yml':
        raise ValueError('wrong_workflow_path')
    if any(row[k] != candidate for k in ('resolved_workflow_sha','reusable_workflow_sha','candidate_sha')):
        raise ValueError('workflow_must_resolve_to_exact_candidate')
    if row['attempt'] != 1 or type(row['attempt']) is not int:
        raise ValueError('wrong_attempt_no_passing_retry')
    if row['event'] not in ('workflow_dispatch','local_static_deterministic') or not isinstance(row['run_id'],str) or not row['run_id']:
        raise ValueError('wrong_event_or_run')
    return row


def assemble(checkout, output, *, candidate, tree, workflow, expected_plan_hash, expected_input_hash):
    checkout, output = Path(checkout).resolve(), Path(output).resolve()
    if output.is_relative_to(checkout):
        raise ValueError('assembly_must_be_isolated')
    entries = check_checkout(checkout, candidate, tree)
    ids = validate_inputs(checkout)
    if ids['plan_hash'] != expected_plan_hash or ids['input_manifest_hash'] != expected_input_hash:
        raise ValueError('predeclared_plan_or_input_changed')
    workflow_identity(workflow, candidate)
    env = environment_identity()
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'; source.mkdir()
    files = {}
    for name, info in entries.items():
        data = git(checkout, 'cat-file', 'blob', info['blob'])
        path = source / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data); path.chmod(0o555 if info['mode'] == '100755' else 0o444)
        files[name] = dict(sha256=sha256(data), git_blob=info['blob'], mode=info['mode'], bytes=len(data))
    identity = dict(repository=REPOSITORY, candidate_sha=candidate, candidate_tree=tree,
        **ids, workflow_identity=workflow, environment_identity=env,
        assembly_recipe='exact-git-tree-v2;generated=[];overlays=[];outputs=external',
        expected_trial_matrix=read(source/'certification/stage_e_native_v2/trial-definition-v2.json')['deterministic_matrix'])
    manifest = dict(version='stage-e-reviewed-execution-assembly-v2', identity=identity, files=files)
    digest = sha256(canonical(manifest)); manifest['assembly_digest'] = digest
    (output / 'assembly.json').write_bytes(canonical(manifest)); (output/'assembly.json').chmod(0o444)
    for directory in sorted((p for p in source.rglob('*') if p.is_dir()), reverse=True):
        directory.chmod(0o555)
    source.chmod(0o555); output.chmod(0o555)
    verify_assembly(output, digest)
    return manifest


def verify_assembly(assembly, digest):
    assembly = Path(assembly).resolve()
    manifest = read(assembly/'assembly.json')
    own = manifest.pop('assembly_digest', None)
    if own != digest or sha256(canonical(manifest)) != digest:
        raise ValueError('wrong_or_substituted_assembly')
    source = assembly/'source'
    actual = {p.relative_to(source).as_posix():p for p in source.rglob('*') if not p.is_dir() or p.is_symlink()}
    if set(actual) != set(manifest['files']):
        raise ValueError('assembly_content_added_or_missing')
    for name, path in actual.items():
        info = manifest['files'][name]
        if (path.is_symlink() or not path.is_file() or sha256(path.read_bytes()) != info['sha256']
                or path.stat().st_mode & 0o222 or bool(path.stat().st_mode & 0o111) != (info['mode']=='100755')):
            raise ValueError('assembly_drift:' + name)
    if {p.name for p in assembly.iterdir()} != {'source','assembly.json'}:
        raise ValueError('unexpected_assembly_content')
    if validate_inputs(source) != {k:manifest['identity'][k] for k in identities(source)}:
        raise ValueError('assembly_input_identity')
    manifest['assembly_digest'] = own
    return manifest


def origin_proof(manifest, source):
    source = Path(source).resolve()
    env = manifest['identity']['environment_identity']
    dependency_files = env['dependencies']['websockets']['files']
    stdlib = Path(env['stdlib'])
    rows = []
    for name, module in sorted(sys.modules.items()):
        raw = getattr(module, '__file__', None)
        if not raw:
            continue
        path = Path(raw).resolve()
        if path.is_relative_to(source):
            rel = path.relative_to(source).as_posix()
            expected = manifest['files'].get(rel, {}).get('sha256')
            category = 'assembled'
        elif str(path) in dependency_files:
            expected = dependency_files[str(path)]; category = 'approved_dependency'
        elif str(path) in env['stdlib_files']:
            expected = env['stdlib_files'][str(path)]; category = 'standard_library'
        else:
            raise ValueError('foreign_local_module_origin:' + name + ':' + str(path))
        actual = sha256(path.read_bytes())
        if actual != expected:
            raise ValueError('runtime_module_hash_mismatch:' + name)
        rows.append(dict(module=name, origin=str(path), sha256=actual, category=category))
    if not any(r['category']=='assembled' and r['module'].endswith('.runner') for r in rows):
        raise ValueError('trial_entrypoint_origin_missing')
    return rows


def launch(assembly, digest, case, output):
    manifest = verify_assembly(assembly, digest)
    source = Path(assembly).resolve()/'source'; output = Path(output).resolve()
    if output.is_relative_to(Path(assembly).resolve()):
        raise ValueError('execution_output_inside_assembly')
    output.mkdir(parents=True, exist_ok=False)
    env = {k:os.environ[k] for k in ('PATH','LANG','LC_ALL','TZ') if k in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               MM_STAGE_E_V2_ASSEMBLY=str(Path(assembly).resolve()), MM_STAGE_E_V2_DIGEST=digest)
    args = [sys.executable, '-I', '-S', str(source/'certification/stage_e_native_v2/bootstrap.py'),
            '--case',case,'--output',str(output)]
    result = subprocess.run(args, cwd=output, env=env, text=True, capture_output=True, timeout=120)
    verify_assembly(assembly,digest)
    (output/'process.log').write_text(result.stdout+result.stderr)
    return result
