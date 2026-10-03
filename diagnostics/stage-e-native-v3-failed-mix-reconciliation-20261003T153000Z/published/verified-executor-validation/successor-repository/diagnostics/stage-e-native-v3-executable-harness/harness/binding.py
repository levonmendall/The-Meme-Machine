"""Source conservation, exact reviewed assembly and separately frozen runtime."""
import importlib.metadata
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig

from core import (ASSEMBLY, ASSEMBLY_MANIFEST_SHA, CONTRACT, CONTRACT_COMMIT, INFRA,
                  S, T, canonical, contract_file, file_sha, read, relative, require, sha)
from preserve import fsync_dir, persist


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def candidate_integrity(checkout):
    checkout = Path(checkout).resolve()
    require(git(checkout, 'rev-parse', 'HEAD').decode().strip() == S, 'candidate_S_changed')
    require(git(checkout, 'rev-parse', 'HEAD^{tree}').decode().strip() == T, 'candidate_T_changed')
    require(not git(checkout, 'status', '--porcelain', '--untracked-files=all').strip(), 'dirty_candidate')
    before = contract_file('candidate_integrity_before.json')
    for name, info in before['tracked_files'].items():
        path = relative(checkout, name)
        require(path.is_file() and file_sha(path) == info['sha256'], 'candidate_byte_changed:' + name)
        require(bool(path.stat().st_mode & 0o111) == (info['mode'] == '100755'), 'candidate_mode_changed')
    for data in git(checkout, 'ls-files', '-z', '--others', '--ignored', '--exclude-standard').split(b'\0'):
        if data:
            path = relative(checkout, data.decode())
            require(not path.is_symlink() and path.suffix not in ('.py', '.pyc', '.so', '.sh', '.pth', '.zip')
                    and not path.stat().st_mode & 0o111, 'ignored_executable_shadow')
    return dict(candidate_sha=S, candidate_tree=T, candidate_files=len(before['tracked_files']),
                full_candidate_sha256=sha(canonical(before)), changed=[], strategy_policy_changed=False)


def contract_integrity(repository):
    rows = read(CONTRACT / 'package_sha256.json')['artifacts']
    require(file_sha(CONTRACT / 'package_sha256.json') == __import__('core').CONTRACT_MANIFEST_SHA,
            'approved_contract_manifest_changed')
    actual = {p.relative_to(CONTRACT).as_posix() for p in CONTRACT.rglob('*') if p.is_file()}
    require(actual == {r['path'] for r in rows} | {'package_sha256.json'}, 'contract_extra_or_missing_file')
    for row in rows:
        require(file_sha(relative(CONTRACT, row['path'])) == row['sha256'], 'approved_contract_changed')
    changed = git(repository, 'diff', '--name-only', CONTRACT_COMMIT, '--', str(CONTRACT)).strip()
    require(not changed, 'approved_contract_git_delta')
    return dict(commit=CONTRACT_COMMIT, verified_artifacts=len(rows)+1, changed=[], semantics_changed=False)


def restore_assembly(checkout, destination):
    """No overlays, imports, fixture generation or runtime work."""
    candidate_integrity(checkout)
    data = (Path(checkout) / 'diagnostics/stage-e-observer-v2/REVIEWED_ASSEMBLY.json').read_bytes()
    require(sha(data) == ASSEMBLY_MANIFEST_SHA, 'reviewed_assembly_manifest')
    import json
    manifest = json.loads(data)
    unsigned = dict(manifest)
    require(unsigned.pop('assembly_digest') == ASSEMBLY and sha(canonical(unsigned)) == ASSEMBLY,
            'reviewed_assembly_digest')
    destination = Path(destination)
    destination.mkdir(exist_ok=False)
    source = destination / 'source'
    source.mkdir()
    for name, info in manifest['files'].items():
        payload = git(checkout, 'cat-file', 'blob', info['git_blob'])
        require(len(payload) == info['bytes'] and sha(payload) == info['sha256'], 'assembly_source_bytes')
        path = relative(source, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        path.chmod(0o555 if info['mode'] == '100755' else 0o444)
    (destination / 'assembly.json').write_bytes(data)
    (destination / 'assembly.json').chmod(0o444)
    for folder in sorted((p for p in source.rglob('*') if p.is_dir()), reverse=True):
        fsync_dir(folder)
        folder.chmod(0o555)
    fsync_dir(source)
    source.chmod(0o555)
    fsync_dir(destination)
    destination.chmod(0o555)
    return verify_assembly(destination)


def verify_assembly(destination):
    destination = Path(destination).resolve()
    require(file_sha(destination / 'assembly.json') == ASSEMBLY_MANIFEST_SHA, 'assembly_manifest_drift')
    manifest = read(destination / 'assembly.json')
    require(manifest['assembly_digest'] == ASSEMBLY, 'assembly_digest_drift')
    source = destination / 'source'
    files = {p.relative_to(source).as_posix(): p for p in source.rglob('*') if not p.is_dir() or p.is_symlink()}
    require(set(files) == set(manifest['files']), 'assembly_content_added_or_missing')
    for name, path in files.items():
        info = manifest['files'][name]
        require(not path.is_symlink() and path.is_file() and file_sha(path) == info['sha256']
                and not path.stat().st_mode & 0o222
                and bool(path.stat().st_mode & 0o111) == (info['mode'] == '100755'), 'assembly_drift:' + name)
    return manifest


def infrastructure_identity():
    files = {p.name: dict(sha256=file_sha(p), bytes=p.stat().st_size,
                         mode='100755' if p.stat().st_mode & 0o111 else '100644')
             for p in sorted(INFRA.iterdir()) if p.is_file() and p.suffix in ('.py', '.sh')}
    entries = {p.name: dict(sha256=file_sha(p), bytes=p.stat().st_size,
                           mode='100755' if p.stat().st_mode & 0o111 else '100644')
               for p in sorted(INFRA.parent.glob('*.py'))}
    return dict(files=files, entrypoints=entries,
                digest=sha(canonical(dict(files=files, entrypoints=entries))), version='external-stage-e-v3-source')


def runtime_identity(source):
    """Read-only inspection; rejects unapproved dependency files without installing."""
    dist = importlib.metadata.distribution('websockets')
    require(platform.python_version() == '3.12.14' and dist.version == '17.1', 'frozen_runtime_version')
    lock = read(Path(source) / 'certification/stage_e_native_v2/dependency-lock-v2.json')['websockets']
    package = {}
    absolute = {}
    for name in dist.files or []:
        path = Path(dist.locate_file(name)).resolve()
        if path.is_file() and path.suffix != '.pyc' and path.name not in ('RECORD', 'INSTALLER', 'REQUESTED'):
            package[str(name)] = file_sha(path)
            absolute[str(path)] = package[str(name)]
    require(package == lock['files'], 'dependency_lock_bytes')
    tooling = {}
    for name, version in {'PyYAML':'6.0.2','jsonschema':'4.23.0'}.items():
        tool = importlib.metadata.distribution(name)
        require(tool.version == version, 'frozen_tooling_dependency:'+name)
        hashes = {str(Path(tool.locate_file(p)).resolve()):file_sha(tool.locate_file(p))
                  for p in tool.files or [] if Path(tool.locate_file(p)).is_file()
                  and Path(p).suffix != '.pyc' and Path(p).name not in ('RECORD','INSTALLER','REQUESTED')}
        tooling[name] = dict(version=version,files=hashes,digest=sha(canonical(hashes)))
    stdlib = Path(sysconfig.get_path('stdlib')).resolve()
    stdlib_files = {}
    for folder, dirs, names in os.walk(stdlib):
        dirs[:] = [d for d in dirs if d not in ('site-packages', 'dist-packages', '__pycache__')]
        for name in names:
            path = Path(folder) / name
            if path.suffix in ('.py', '.so') and path.is_file():
                stdlib_files[str(path.resolve())] = file_sha(path)
    mapped = {}
    for line in Path('/proc/self/maps').read_text().splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[-1].startswith('/'):
            path = Path(parts[-1])
            require(path.is_file(), 'deleted_runtime_mapping')
            mapped[str(path.resolve())] = file_sha(path)
    tools = {}
    for name in ('git', 'openssl', 'unshare', 'ps', 'ldd', 'sh'):
        path = shutil.which(name)
        require(path is not None, 'required_OS_tool:' + name)
        tools[name] = dict(path=str(Path(path).resolve()), sha256=file_sha(path))
    # Freeze the actual shared-library closure of every approved extension.
    # ldd only inspects these trusted interpreter/stdlib ELF files; no workload.
    import re
    elf_files = [str(Path(sys.executable).resolve())] + [p for p in stdlib_files if p.endswith('.so')]
    for path in elf_files:
        result = subprocess.run([tools['ldd']['path'], path], capture_output=True, text=True, timeout=10)
        require(result.returncode == 0, 'runtime_shared_library_closure')
        require('not found' not in result.stdout, 'runtime_shared_library_missing')
        for library in re.findall(r'(/[^\s]+)\s+\(0x', result.stdout):
            lib = Path(library).resolve()
            mapped[str(lib)] = file_sha(lib)
    return dict(python=platform.python_version(), python_executable=str(Path(sys.executable).resolve()),
                python_executable_hash=file_sha(sys.executable), sqlite=__import__('sqlite3').sqlite_version,
                platform=platform.platform(), machine=platform.machine(), libc=platform.libc_ver(),
                kernel=platform.release(), os_release_sha256=file_sha('/etc/os-release'),
                stdlib=str(stdlib), stdlib_files=stdlib_files, stdlib_digest=sha(canonical(stdlib_files)),
                dependency_root=str(Path(dist.locate_file('')).resolve()),
                dependencies={'websockets': dict(version=dist.version, files=absolute, digest=sha(canonical(absolute)))},
                tooling_dependencies=tooling,
                mapped_libraries=mapped, os_tools=tools)
