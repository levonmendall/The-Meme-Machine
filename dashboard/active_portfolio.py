"""Explicit selection of one canonical financial feed; no trading authority.

The original cache and receiver remain an archive.  Selecting the existing Pons
experiment creates neither an epoch nor a financial record, and never falls back
to the original account when its own evidence is missing.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import urlsplit

from .model import canonical, stamp
from .simulator import SimulatorChannel, BASELINE_STRATEGY
from .snapshots import SnapshotReader, SnapshotStore, freshness, validate


EXPERIMENT_EPOCH = 'paper-pons-simulator-1000-20261024'
EXPERIMENT_INCEPTION = '0098b5790dee06e6b540a1e02fad0db562d115006f10b3575b36ba4e0f221474'
NATIVE_SOURCE = 'ba6ef30d27c379ef03324cf72356bdcc8b1d73e2'
RISK_SHA256 = 'b91e83300994b6c02fe5e6bdbeb031cc391e6c8caa97af9fa6df1ecbc4aa979c'
SOURCE_MODE = 'pons_experiment'


def _safe_path(path):
    """Do not follow a cache or parent symlink, including a dangling symlink."""
    path = Path(os.path.abspath(path))
    for item in (*reversed(path.parents), path):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError('active_snapshot_symlink')
        if item == path:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('active_snapshot_file')
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('active_snapshot_parent')
    return path


def _separate_paths(active, archive):
    active, archive = _safe_path(active), _safe_path(archive)
    if active == archive or (active.exists() and archive.exists()
                             and os.path.samefile(active, archive)):
        raise ValueError('active_snapshot_archive_alias')


def _file_identity(path):
    info = path.lstat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _admission(value, *, source, epoch, inception, captured):
    """A dated report of resident authority, never dashboard authority itself."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('active_admission_shape')
    if (value.get('schema') != 'pons-current-paper-report-v1'
            or value.get('source_commit') != source or value.get('epoch_id') != epoch
            or value.get('inception_sha256') != inception
            or value.get('policy_sha256') != BASELINE_STRATEGY['policy_sha256']):
        raise ValueError('active_admission_identity')
    if value.get('state') not in ('UNAVAILABLE', 'DISABLED', 'WARMING', 'READY',
                                  'MANAGING', 'FAILED', 'STOPPED', 'STALE'):
        raise ValueError('active_admission_state')
    for name in ('permission_enabled', 'new_risk_enabled'):
        if value.get(name) is not None and type(value[name]) is not bool:
            raise ValueError('active_admission_permission')
    authority = value.get('authority_sha256')
    if authority is not None and (type(authority) is not str
                                  or not re.fullmatch('[a-f0-9]{64}', authority)):
        raise ValueError('active_admission_authority')
    if value.get('permission_enabled') is True and authority is None:
        raise ValueError('active_admission_authority')
    if value.get('new_risk_enabled') is True and (value.get('permission_enabled') is not True
            or value['state'] not in ('READY', 'MANAGING')):
        raise ValueError('active_admission_permission')
    if value['state'] == 'READY' and value.get('permission_enabled') is not True:
        raise ValueError('active_admission_permission')
    if value['state'] == 'DISABLED' and value.get('permission_enabled') is not False:
        raise ValueError('active_admission_permission')
    heartbeat = value.get('heartbeat_at')
    if heartbeat is None:
        if value['state'] != 'UNAVAILABLE':
            raise ValueError('active_admission_clock')
    elif stamp(heartbeat) > stamp(captured):
        raise ValueError('active_admission_clock')
    return {key: value.get(key) for key in ('schema', 'source_commit', 'epoch_id',
        'inception_sha256', 'policy_sha256', 'state', 'heartbeat_at',
        'permission_enabled', 'new_risk_enabled', 'authority_sha256')}


class ActivePortfolioStore(SnapshotStore):
    """Original canonical wire contract, pinned to the explicitly selected owner."""
    def __init__(self, path, *, archive_path, epoch, candidate, inception_sha256,
                 clock=time.time):
        if (epoch != EXPERIMENT_EPOCH or type(candidate) is not str
                or not re.fullmatch('[a-f0-9]{40}', candidate)):
            raise ValueError('active_selection_identity')
        self.archive_path = Path(archive_path)
        self.reason = None
        _separate_paths(path, archive_path)
        super().__init__(path, epoch=epoch, candidate=candidate, clock=clock,
                         inception_sha256=inception_sha256)
        if self.value is not None:
            self._validate_selected(self.value)
        self._durable_identity = _file_identity(self.path) if self.value is not None else None

    def _validate_selected(self, value):
        validate(value, epoch=self.epoch, candidate=self.candidate,
                 inception_sha256=self.inception_sha256)
        source = value['source']
        if source['publisher_commit'] != self.candidate or source['deployed_commit'] != NATIVE_SOURCE:
            raise ValueError('active_snapshot_source')
        if value['service'].get('unit') != 'meme-machine-pons-current.service':
            raise ValueError('active_snapshot_service')
        book = value['portfolio']
        if book.get('bundle') is None:
            raise ValueError('active_canonical_bundle_required')
        proof = book.get('observation', {}).get('financial_statement')
        if (not isinstance(proof, dict) or proof.get('epoch_id') != self.epoch
                or proof.get('inception_sha256') != self.inception_sha256
                or proof.get('risk_sha256') != RISK_SHA256
                or type(proof.get('journal_sequence')) is not int
                or not 0 <= proof['journal_sequence'] <= book['bundle']['sequence']):
            raise ValueError('active_financial_statement_identity')
        for key in ('journal_hash', 'projection_sha256'):
            if type(proof.get(key)) is not str or not re.fullmatch('[a-f0-9]{64}', proof[key]):
                raise ValueError('active_financial_statement_hash')
        admission = value['observer'].get('financial_admission')
        _admission(admission, source=self.candidate,
                   epoch=self.epoch, inception=self.inception_sha256,
                   captured=value['captured_at'])
        if admission is not None and (admission.get('ledger_sequence') != proof['journal_sequence']
                or admission.get('ledger_sha256') != proof['journal_hash']):
            raise ValueError('active_admission_ledger_binding')

    def accept(self, value):
        with self.lock:
            _separate_paths(self.path, self.archive_path)
            self._validate_selected(value)
            if self._durable_identity is not None and self._durable_identity != _file_identity(self.path):
                raise ValueError('active_snapshot_changed_outside_receiver')
            if self.value is not None and canonical(value) == canonical(self.value):
                # A retry of retained evidence cannot renew its timestamp.
                return dict(idempotent=True, sequence=(value['portfolio'].get('bundle') or {}).get('sequence'))
            if self.value is not None and stamp(value['captured_at']) == stamp(self.value['captured_at']):
                raise ValueError('active_snapshot_timestamp_conflict')
            if self.value is not None:
                old = self.value['portfolio']['observation']['financial_statement']
                new = value['portfolio']['observation']['financial_statement']
                if new['journal_sequence'] < old['journal_sequence']:
                    raise ValueError('active_journal_regression')
                if new['journal_sequence'] == old['journal_sequence'] and new != old:
                    raise ValueError('active_journal_equivocation')
            super().accept(value)
            self._durable_identity = _file_identity(self.path)
            self.reason = None
            return dict(idempotent=False, sequence=(value['portfolio'].get('bundle') or {}).get('sequence'))

    def get(self):
        with self.lock:
            try:
                _separate_paths(self.path, self.archive_path)
                if self._durable_identity != _file_identity(self.path):
                    raise ValueError('active_snapshot_changed_outside_receiver')
            except FileNotFoundError:
                self.reason = 'UNAVAILABLE'
                return None
            except (OSError, ValueError):
                self.reason = 'FAIL_CLOSED'
                return None
            self.reason = None
            return super().get()


class _UnavailableStore:
    def __init__(self, reason, candidate=None):
        self.reason, self.candidate = reason, candidate

    def get(self):
        return None


class ActivePortfolioReader(SnapshotReader):
    def _load(self):
        if self.store.reason:
            return None, self.store.reason
        return super()._load()

    def system(self):
        result = super().system()
        snap = self.snapshot or {}
        service = snap.get('service', {})
        admission = _admission(snap.get('observer', {}).get('financial_admission'),
            source=self.store.candidate, epoch=EXPERIMENT_EPOCH,
            inception=getattr(self.store, 'inception_sha256', EXPERIMENT_INCEPTION),
            captured=snap.get('captured_at')) if snap else None
        state = 'UNAVAILABLE'
        if admission:
            state = admission['state']
            if freshness(snap.get('captured_at'), self.clock()) != 'CURRENT' or freshness(
                    admission['heartbeat_at'], self.clock(), 45) != 'CURRENT':
                state = 'STALE'
            elif service.get('ActiveState') != 'active' or service.get('SubState') != 'running':
                state = 'STOPPED'
            elif admission['permission_enabled'] is False and state != 'MANAGING':
                state = 'DISABLED'
        result.update(paper_state=state, trading_admission=admission,
                      financial_source=SOURCE_MODE)
        return result

    def view(self):
        result = super().view()
        identity = dict(epoch_id=EXPERIMENT_EPOCH,
            inception_sha256=getattr(self.store, 'inception_sha256', EXPERIMENT_INCEPTION),
            source_commit=self.store.candidate)
        result['portfolio'].update(financial_source=SOURCE_MODE,
            selected_financial_identity=identity,
            financial_source_label='Existing independent Pons experimental PAPER account')
        result['system']['selected_financial_identity'] = deepcopy(identity)
        # Selected runtime and native application are different truthful source
        # identities. The legacy original reader compares one shared commit.
        operations = result['system']['operations']
        operations['alerts'] = [alert for alert in operations['alerts']
                                if alert != 'candidate_not_deployed']
        return result


class SelectedOperationsChannel(SimulatorChannel):
    """Only reports a binding when both independent authenticated feeds agree."""
    def __init__(self, channel, reader):
        super().__init__(channel.store, reason=channel.reason)
        self.financial_reader = reader

    def response(self, method, target):
        result = super().response(method, target)
        if result is None or result[0] != 200 or urlsplit(target).path != '/api/dashboard/live':
            return result
        status, headers, raw = result
        live = json.loads(raw)
        financial = self.financial_reader.view()
        p = financial['portfolio']
        selected = p['selected_financial_identity']
        identity = live.get('identity') or {}
        bound = (live['state'] == 'CURRENT' and p['state'] == 'CURRENT'
                 and p.get('snapshot_state') == 'CURRENT'
                 and all(identity.get(key) == selected[key] for key in (
                     'epoch_id', 'inception_sha256', 'source_commit')))
        live.update(financial_source=SOURCE_MODE, account_cutover=dict(
            state='VERIFIED' if bound else 'UNAVAILABLE',
            current_owner_epoch=selected['epoch_id'],
            inception_sha256=selected['inception_sha256'],
            reason='AUTHENTICATED_SELECTED_CANONICAL_BINDING' if bound
                else 'SELECTED_CANONICAL_BINDING_UNAVAILABLE'))
        return status, headers, json.dumps(live, separators=(',', ':'), allow_nan=False).encode()


@dataclass
class Selection:
    reader: object
    store: object = None
    selected: bool = False


def select_financial_source(environ, original_reader, original_store, *, clock=time.time):
    """Bad selected configuration fails closed instead of showing other capital."""
    mode = environ.get('MM_DASHBOARD_FINANCIAL_SOURCE', 'original')
    if mode == 'original':
        return Selection(original_reader)
    candidate = environ.get('MM_DASHBOARD_ACTIVE_CANDIDATE')
    try:
        if mode != SOURCE_MODE or original_store is None:
            raise ValueError('active_selection_configuration')
        epoch = environ['MM_DASHBOARD_ACTIVE_EPOCH']
        inception = environ['MM_DASHBOARD_ACTIVE_INCEPTION_SHA256']
        if epoch != EXPERIMENT_EPOCH or inception != EXPERIMENT_INCEPTION:
            raise ValueError('active_selection_account')
        if type(candidate) is not str or not re.fullmatch('[a-f0-9]{40}', candidate):
            raise ValueError('active_selection_source')
        store = ActivePortfolioStore(environ['MM_DASHBOARD_ACTIVE_SNAPSHOT_PATH'],
            archive_path=original_store.path, epoch=epoch, candidate=candidate,
            inception_sha256=inception, clock=clock)
        return Selection(ActivePortfolioReader(store, clock=clock), store, True)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, OverflowError, RecursionError):
        return Selection(ActivePortfolioReader(_UnavailableStore('FAIL_CLOSED', candidate),
                                              clock=clock), selected=True)
