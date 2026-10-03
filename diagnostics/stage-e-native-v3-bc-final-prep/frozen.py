"""Read-only imports of the exact approved executable. No runner entrypoint."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parents[1]
EXECUTABLE = REPOSITORY / 'diagnostics/stage-e-native-v3-executable-harness'
CONTRACT = REPOSITORY / 'diagnostics/stage-e-native-v3-production-envelope-contract'
EXECUTABLE_COMMIT = 'f480c6b4f7a8442fd148c7ed61bcc4447edaefca'
EXECUTABLE_TREE = '6805846ed6d5c2acb31d843d749b80b923df87a1'
EXECUTABLE_MANIFEST_SHA256 = 'd0047922f45cc85599c25705616152005ab598d65343cb4482e983f34ebd6859'
UNSATISFIED = 'UNSATISFIED_AWAITING_EVIDENCE'
UNRESOLVED_A = 'A_PREREQUISITE_NOT_YET_AVAILABLE'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check_executable():
    manifest = EXECUTABLE / 'package-manifest.json'
    if digest(manifest.read_bytes()) != EXECUTABLE_MANIFEST_SHA256:
        raise ValueError('approved_executable_manifest_changed')
    rows = json.loads(manifest.read_bytes())['artifacts']
    for row in rows:
        name = row['path']
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('approved_executable_unsafe_manifest')
        path = REPOSITORY / name
        if path.is_symlink() or path.stat().st_size != row['bytes'] or digest(path.read_bytes()) != row['sha256']:
            raise ValueError('approved_executable_bytes_changed:' + name)
        if bool(path.stat().st_mode & 0o111) != (row['mode'] == '100755'):
            raise ValueError('approved_executable_mode_changed:' + name)
    actual = {p.relative_to(REPOSITORY).as_posix() for p in EXECUTABLE.rglob('*') if p.is_file()}
    expected = {r['path'] for r in rows if r['path'].startswith(EXECUTABLE.relative_to(REPOSITORY).as_posix() + '/')}
    if actual != expected | {manifest.relative_to(REPOSITORY).as_posix()}:
        raise ValueError('approved_executable_extra_or_missing_file')
    return dict(commit=EXECUTABLE_COMMIT, tree=EXECUTABLE_TREE,
                manifest_sha256=EXECUTABLE_MANIFEST_SHA256, verified_files=len(rows) + 1)


check_executable()
sys.dont_write_bytecode = True
sys.path.insert(0, str(EXECUTABLE / 'harness'))
from core import (ASSEMBLY, CONTRACT_COMMIT, CONTRACT_MANIFEST_SHA, S, T,
                  canonical, contract_file, file_sha, read, relative, require, sha, workload)
from binding import infrastructure_identity
from declaration import preview, TIMING, STOP_RULES, PRESERVATION
from ledger import trial_matrix

FROZEN = dict(candidate_sha=S, candidate_tree=T, assembly_digest=ASSEMBLY,
              contract_commit=CONTRACT_COMMIT, contract_manifest_sha256=CONTRACT_MANIFEST_SHA,
              executable_commit=EXECUTABLE_COMMIT, executable_tree=EXECUTABLE_TREE,
              executable_manifest_sha256=EXECUTABLE_MANIFEST_SHA256)


def unresolved(kind, expected):
    return dict(state=kind, expected_type=expected, value=None)


def exact_frozen(row):
    require(all(row.get(k) == v for k, v in FROZEN.items()), 'wrong_frozen_identity')


def namespace(kind):
    # Template names only; no registry, ledger, lock, mkdir or reservation.
    label = {'B': 'observer', 'C': 'stress'}[kind]
    return f'stage-e-native-v3-{label}-bcprep-20261003-{EXECUTABLE_COMMIT[:12]}'
