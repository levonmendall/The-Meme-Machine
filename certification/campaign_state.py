"""Exact-identity, restart-safe transfer of existing PAPER campaign state.

This capsule carries state, never entry authority. The controller must separately
admit its next window after reviewing the preserved native artifact. SQLite files
use the existing verified backup path; no new genesis or balance is synthesized.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil

from certification.archive_native import PATTERNS, copy_snapshot
from certification.journal import canonical, digest
from certification.position_continuation import _atomic

SCHEMA = 'autonomous-paper-state-v1'
LANES = ('pump', 'pons', 'meteora', 'ramses')
SHARED = ('solana-evidence-plane.sqlite', 'solana-evidence-plane.sqlite.archive',
          'shared-robinhood-evidence.candidates.sqlite')
MANIFEST = 'campaign-state.json'


def identity():
    from certification.run import ROOT, git, implementation_hash, manifest
    task = json.loads((ROOT/'certification/autonomous_paper_task_manifest.json').read_text())
    if (task.get('lanes') != 4 or task.get('active_regimes') != 6
            or task.get('paper_only') is not True or task.get('live_money') is not False):
        raise ValueError('campaign_state_authority')
    sources = manifest()
    return dict(integration_sha=git('rev-parse', 'HEAD'),
                implementation_hash=implementation_hash(),
                source_manifest_hash=digest(sources), policy_manifest_hash=digest(task),
                source_diff_hashes={lane: sources['lanes'][lane]['source_diff_sha256'] for lane in LANES},
                paper_only=True, live_money=False)


def _checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _relative(name):
    if not isinstance(name, str):
        raise ValueError('campaign_state_path')
    path = PurePosixPath(name)
    if (path.is_absolute() or str(path) != name
            or any(p in ('', '.', '..') for p in path.parts)):
        raise ValueError('campaign_state_path')
    return path


def _allowed(name):
    path = _relative(name)
    if len(path.parts) < 2:
        raise ValueError('campaign_state_path')
    group, top = path.parts[:2]
    if group == 'shared':
        allowed = top in SHARED
    elif group in LANES:
        from fnmatch import fnmatchcase
        allowed = any(fnmatchcase(top, pattern) for pattern in PATTERNS[group])
    else:
        allowed = False
    if not allowed or path.suffix in ('.py', '.pyc', '.so', '.sh', '.env'):
        raise ValueError('campaign_state_unexpected_file')
    return path


def _window(window):
    if (not re.fullmatch('[a-z0-9-]{8,100}', window.get('campaign_id', ''))
            or type(window.get('index')) is not int or window['index'] < 0
            or type(window.get('workflow_run_id')) is not int or window['workflow_run_id'] <= 0
            or not isinstance(window.get('native_run_id'), str) or not window['native_run_id']
            or not re.fullmatch('[0-9a-f]{64}', window.get('authorization_hash', ''))):
        raise ValueError('campaign_state_window_identity')
    if window['index'] and not re.fullmatch('[0-9a-f]{64}', window.get('parent_state_hash', '')):
        raise ValueError('campaign_state_parent_identity')


def seal(destination, *, worktrees, run, window, terminal, expected_identity, discovery_window=None):
    """Called after all owners drain; the ordinary artifact retains the originals."""
    if identity() != expected_identity:
        raise ValueError('campaign_state_source_changed')
    _window(window)
    discovery_window=window if discovery_window is None else discovery_window
    _window(discovery_window)
    if (any(discovery_window[k]!=window[k] for k in ('campaign_id','authorization_hash','native_run_id'))
            or discovery_window['index']>window['index']
            or (terminal.get('phase')!='position_continuation' and discovery_window!=window)):
        raise ValueError('campaign_state_discovery_window')
    if (terminal.get('status') != 'FINISHED' or terminal.get('integration_sha') != expected_identity['integration_sha']
            or terminal.get('implementation_hash') != expected_identity['implementation_hash']
            or set(terminal.get('lanes', {})) != set(LANES)):
        raise ValueError('campaign_state_not_terminal')
    for lane, row in terminal['lanes'].items():
        proof = row.get('terminal_reconciliation') or {}
        if (row.get('exit_code') != 0 or row.get('unexpected_exit')
                or row.get('accounting_reconciled') is not True or proof.get('verified') is not True
                or (proof.get('open_positions') and proof.get('durable_handoff') is not True)):
            raise ValueError('campaign_state_unreconciled:' + lane)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for lane in LANES:
        found = set()
        for pattern in PATTERNS[lane]:
            for source in sorted((Path(worktrees)/lane).glob(pattern)):
                if source in found:
                    continue
                found.add(source)
                copy_snapshot(source, destination/'files'/lane/source.name, records)
    for name in SHARED:
        source = Path(run)/name
        if source.exists():
            copy_snapshot(source, destination/'files/shared'/name, records)
    if any(r.get('error_type') for r in records):
        raise ValueError('campaign_state_snapshot_incomplete')
    files = []
    for path in sorted((destination/'files').rglob('*')):
        if path.is_symlink():
            raise ValueError('campaign_state_symlink')
        if path.is_file():
            name = str(path.relative_to(destination/'files'))
            _allowed(name)
            files.append(dict(path=name, bytes=path.stat().st_size, sha256=_checksum(path)))
    if not files:
        raise ValueError('campaign_state_empty')
    if set(row['path'].split('/')[0] for row in files) != set(LANES) | {'shared'}:
        raise ValueError('campaign_state_incomplete_lanes')
    if not {'shared/'+name for name in SHARED if name.endswith('.sqlite')} <= {r['path'] for r in files}:
        raise ValueError('campaign_state_missing_evidence')
    body = dict(schema=SCHEMA, identity=expected_identity, window=window, discovery_window=discovery_window,
                terminal_hash=digest(terminal), terminal=terminal, files=files, entry_authority=False,
                accounting={lane: terminal['lanes'][lane]['terminal_reconciliation'] for lane in LANES})
    body['state_hash'] = digest(body)
    _atomic(destination/MANIFEST, body)
    return body


def verify(source, *, expected_identity, expected_state_hash, campaign_id, prior_index, authorization_hash):
    source = Path(source)
    body = json.loads((source/MANIFEST).read_text())
    observed = dict(body); checksum = observed.pop('state_hash', None)
    if (checksum != expected_state_hash or digest(observed) != checksum or body.get('schema') != SCHEMA
            or body.get('identity') != expected_identity or body.get('entry_authority') is not False):
        raise ValueError('campaign_state_identity_or_hash')
    window = body['window']; _window(window)
    if (window['campaign_id'] != campaign_id or window['index'] != prior_index
            or window['authorization_hash'] != authorization_hash):
        raise ValueError('campaign_state_campaign_or_window')
    names = set()
    for row in body['files']:
        name = str(_allowed(row['path']))
        if name in names:
            raise ValueError('campaign_state_duplicate_file')
        names.add(name); path = source/'files'/name
        if (any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file()
                or path.stat().st_size != row['bytes'] or _checksum(path) != row['sha256']):
            raise ValueError('campaign_state_file_hash')
    actual = {str(p.relative_to(source/'files')) for p in (source/'files').rglob('*') if p.is_file()}
    if actual != names:
        raise ValueError('campaign_state_unlisted_file')
    return body


def restore(source, *, worktrees, run, expected_identity, expected_state_hash,
            campaign_id, prior_index, authorization_hash):
    """Retrying an interrupted file installation is idempotent, never a dispatch."""
    if identity() != expected_identity:
        raise ValueError('campaign_state_source_changed')
    body = verify(source, expected_identity=expected_identity, expected_state_hash=expected_state_hash,
                  campaign_id=campaign_id, prior_index=prior_index, authorization_hash=authorization_hash)
    root = Path(run); root.mkdir(parents=True, exist_ok=True)
    receipt_path = root/'restored-campaign-state.json'
    expected = dict(state_hash=body['state_hash'], window=body['window'], identity=expected_identity,
                    entry_authority=False, files=len(body['files']),
                    history_snapshots={row['path']:row['sha256'] for row in body['files']
                        if row['path'].endswith('/history.sqlite')})
    if receipt_path.exists() and json.loads(receipt_path.read_text()) != expected:
        raise ValueError('campaign_state_restore_collision')
    for row in body['files']:
        path = _allowed(row['path']); group = path.parts[0]
        base = root if group == 'shared' else Path(worktrees)/group
        target = base.joinpath(*path.parts[1:])
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError('campaign_state_target_symlink')
        if target.exists():
            if not target.is_file() or _checksum(target) != row['sha256']:
                raise ValueError('campaign_state_restore_collision')
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name('.'+target.name+'.handoff.tmp')
        if temporary.is_symlink():
            raise ValueError('campaign_state_target_symlink')
        with (Path(source)/'files'/row['path']).open('rb') as origin, temporary.open('wb') as dest:
            shutil.copyfileobj(origin, dest, 1024*1024); dest.flush(); os.fsync(dest.fileno())
        if _checksum(temporary) != row['sha256']:
            raise ValueError('campaign_state_copy_hash')
        os.replace(temporary, target)
        fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    _atomic(receipt_path, expected)
    return expected


def prepare_window(claim, *, worktrees, run, phase, seconds, prior_state=None):
    """Install a controller-claimed window before any owner or provider starts."""
    expected = identity()
    if (claim.get('schema') != 'autonomous-paper-window-claim-v1'
            or claim.get('identity') != expected):
        raise ValueError('campaign_claim_identity')
    certificate = claim.get('certificate') or {}
    for key in ('integration_sha', 'implementation_hash', 'source_manifest_hash', 'source_diff_hashes'):
        if certificate.get(key) != expected[key]:
            raise ValueError('campaign_claim_certificate')
    if certificate.get('passed') is not True:
        raise ValueError('campaign_claim_certificate')
    window = claim.get('window') or {}
    if (window.get('mode') != phase or window.get('seconds') != seconds
            or phase not in ('smoke', 'hourly') or window.get('entry_authority') is not True):
        raise ValueError('campaign_claim_entry_authority')
    bound = dict(campaign_id=claim.get('campaign_id'), index=window.get('index'),
                 workflow_run_id=window.get('workflow_run_id'), native_run_id=window.get('native_run_id'),
                 authorization_hash=claim.get('authorization_hash'))
    prior = claim.get('previous')
    if bound['index']:
        bound['parent_state_hash'] = window.get('parent_state_hash')
    _window(bound)
    if bound['index'] == 0:
        if prior or prior_state or phase != 'smoke':
            raise ValueError('campaign_claim_initial_window')
    else:
        if (not prior or not prior_state or prior.get('index') != bound['index'] - 1
                or prior.get('state_hash') != bound['parent_state_hash']
                or prior.get('native_run_id') != bound['native_run_id']
                or set(prior.get('positions', {})) != set(LANES)
                or window.get('positions') != prior['positions']
                or any(not isinstance(v,list) or len(set(v))!=len(v) for v in prior['positions'].values())):
            raise ValueError('campaign_claim_prior_state_or_open_positions')
        proof=verify(prior_state,expected_identity=expected,expected_state_hash=prior['state_hash'],
            campaign_id=bound['campaign_id'],prior_index=prior['index'],authorization_hash=bound['authorization_hash'])
        if (set(proof.get('accounting',{}))!=set(LANES)
                or any(row.get('verified') is not True
                    or row.get('open_positions') != len(prior['positions'][lane])
                    or (row.get('open_positions') and row.get('durable_handoff') is not True)
                    for lane,row in proof['accounting'].items())):
            raise ValueError('campaign_claim_native_exposure_identity')
        restore(prior_state, worktrees=worktrees, run=run, expected_identity=expected,
                expected_state_hash=prior['state_hash'], campaign_id=bound['campaign_id'],
                prior_index=prior['index'], authorization_hash=bound['authorization_hash'])
    _atomic(Path(run)/'autonomous-window-claim.json', claim)
    return bound


def restored_window():
    """Lane-side validation of the supervisor's completed state-install receipt."""
    value = os.environ.get('MM_AUTONOMOUS_STATE_RECEIPT')
    if not value:
        return None
    path = Path(value)
    receipt = json.loads(path.read_text())
    claim = json.loads((path.parent/'autonomous-window-claim.json').read_text())
    previous = claim.get('previous') or {}
    if (receipt.get('identity') != identity() or claim.get('identity') != receipt['identity']
            or receipt.get('entry_authority') is not False
            or claim.get('schema') != 'autonomous-paper-window-claim-v1'
            or claim.get('window', {}).get('entry_authority') is not True
            or previous.get('state_hash') != receipt.get('state_hash')
            or previous.get('index') != receipt.get('window', {}).get('index')
            or previous.get('native_run_id') != os.environ.get('MM_CERTIFICATION_RUN_ID')
            or claim.get('campaign_id') != receipt.get('window', {}).get('campaign_id')
            or claim.get('authorization_hash') != receipt.get('window', {}).get('authorization_hash')):
        raise ValueError('campaign_restored_window_authority')
    return claim


def active_window():
    value = os.environ.get('MM_AUTONOMOUS_WINDOW_CLAIM')
    if not value:
        return None
    claim = json.loads(Path(value).read_text())
    window = claim.get('window') or {}
    if (claim.get('schema') != 'autonomous-paper-window-claim-v1'
            or claim.get('identity') != identity()
            or window.get('entry_authority') is not True
            or window.get('native_run_id') != os.environ.get('MM_CERTIFICATION_RUN_ID')):
        raise ValueError('campaign_active_window_identity')
    return dict(campaign_id=claim['campaign_id'], authorization_hash=claim['authorization_hash'],
                index=window['index'], workflow_run_id=window['workflow_run_id'])
