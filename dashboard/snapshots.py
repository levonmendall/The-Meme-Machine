"""One bounded operational snapshot, backed by the existing portfolio reader."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from meme_machine.portfolio_snapshot_transport import validate_snapshot
from .model import Reader, metric, performance, stamp, validate_export, validate_inception

SCHEMA = 'meme-machine-operations-v1'
MAX_BYTES = 12 * 1024 * 1024
STALE_SECONDS = 60
PHASES = ('CAPACITY', 'RECOVERY', 'AUTONOMY')
CHECKS = {'lane_realized_less_shared_costs', 'remaining_basis',
          'cash_basis_conservation', 'cost_attribution'}


def utc(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def freshness(at, now, ttl=STALE_SECONDS):
    if at is None:
        return 'UNAVAILABLE'
    age = now - stamp(at)
    return 'CURRENT' if 0 <= age <= ttl else 'STALE'


def validate(value, *, epoch=None, candidate=None):
    if not isinstance(value, dict) or value.get('schema') != SCHEMA:
        raise ValueError('snapshot_schema')
    stamp(value['captured_at'])
    source = value['source']
    if not isinstance(source, dict):
        raise ValueError('snapshot_source')
    for key in ('candidate_commit', 'deployed_commit', 'publisher_commit'):
        if not re.fullmatch('[0-9a-f]{40}', source.get(key, '')):
            raise ValueError('snapshot_commit')
    if epoch and source.get('epoch_id') != epoch:
        raise ValueError('snapshot_epoch')
    if candidate and source.get('candidate_commit') != candidate:
        raise ValueError('snapshot_candidate')
    for key in ('observer', 'monitor', 'service', 'acceptance', 'portfolio'):
        if not isinstance(value.get(key), dict):
            raise ValueError('snapshot_section')
    for key in ('observer', 'monitor'):
        if value[key].get('at') is not None:
            stamp(value[key]['at'])
    if value['observer'].get('epoch_id') not in (None, source['epoch_id']):
        raise ValueError('observer_epoch')
    for phase in PHASES:
        row = value['acceptance'][phase]
        if row['status'] not in ('NOT_STARTED', 'STARTING', 'RUNNING', 'PASS',
                                'FAIL', 'INTERRUPTED', 'UNAVAILABLE'):
            raise ValueError('acceptance_status')
        if row['status'] == 'PASS':
            duration = {'CAPACITY': 3600, 'RECOVERY': 0, 'AUTONOMY': 129600}[phase]
            if (row.get('verified_result') is not True or row.get('exit_code') != 0
                    or row.get('full_duration_completed') is not True
                    or row.get('elapsed_seconds', -1) < duration
                    or row.get('results', {}).get('passed') is not True):
                raise ValueError('acceptance_pass_without_result')
    book = value['portfolio']
    bundle = book.get('bundle')
    if bundle is not None:
        validate_snapshot(bundle)
        receipt = validate_inception(bundle['receipt'])
        if receipt['epoch_id'] != source['epoch_id']:
            raise ValueError('portfolio_epoch')
        validate_export(bundle['export'], receipt, 'canonical')
    observation = book.get('observation', {})
    if observation.get('state') == 'CURRENT':
        if bundle is None or observation.get('epoch_id') != source['epoch_id']:
            raise ValueError('portfolio_observation_binding')
        if observation.get('sequence') != bundle['sequence']:
            raise ValueError('portfolio_observation_sequence')
        if observation.get('inception_sha256') != bundle['inception_sha256']:
            raise ValueError('portfolio_observation_inception')
        if observation.get('reconciliation') != 'PASS' or set(observation['checks']) != CHECKS:
            raise ValueError('portfolio_observation_reconciliation')
        if any(v is not True for v in observation['checks'].values()):
            raise ValueError('portfolio_observation_checks')
        stamp(observation['at'])
        for key in ('available_cash', 'reserved_cash', 'deployed_capital',
                    'realized_pnl', 'fees', 'shared_costs'):
            raw = bundle['export']['balances'][key]
            if observation['balances'][key] != raw:
                raise ValueError('portfolio_observation_balances')
        for key, amount in observation['balances'].items():
            if amount is not None:
                from .model import decimal
                decimal(amount)
        balance = observation['balances']
        if (Decimal(balance['available_cash']) + Decimal(balance['reserved_cash'])
                + Decimal(balance['deployed_capital']) != Decimal('500.00') + Decimal(balance['realized_pnl'])):
            raise ValueError('portfolio_cash_conservation')
        if balance.get('equity') is not None and (balance.get('unrealized_pnl') is None or
                Decimal(balance['equity']) != Decimal('500.00') + Decimal(balance['realized_pnl']) + Decimal(balance['unrealized_pnl'])):
            raise ValueError('portfolio_equity_conservation')
    # Operational numbers may be floats; all monetary values above use the
    # existing exact Decimal contract. Reject NaN/Infinity anywhere.
    json.dumps(value, allow_nan=False)
    return value


class SnapshotStore:
    def __init__(self, path, *, epoch, candidate, clock=time.time):
        self.path = Path(path)
        self.epoch, self.candidate, self.clock = epoch, candidate, clock
        self.lock = threading.RLock()
        self.value = None
        try:
            if self.path.stat().st_size <= MAX_BYTES:
                self.value = validate(json.loads(self.path.read_bytes()),
                                      epoch=epoch, candidate=candidate)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            pass

    def accept(self, value):
        validate(value, epoch=self.epoch, candidate=self.candidate)
        at = stamp(value['captured_at'])
        if not -5 <= self.clock() - at <= 120:
            raise ValueError('snapshot_clock')
        raw = json.dumps(value, separators=(',', ':'), allow_nan=False).encode()
        if len(raw) > MAX_BYTES:
            raise ValueError('snapshot_capacity')
        with self.lock:
            if self.value:
                if at < stamp(self.value['captured_at']):
                    raise ValueError('snapshot_regression')
                old = self.value['portfolio'].get('bundle')
                new = value['portfolio'].get('bundle')
                if old and new and new['sequence'] < old['sequence']:
                    raise ValueError('portfolio_sequence_regression')
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            name = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                    name = stream.name
                    os.chmod(name, 0o600)
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.path)
            finally:
                if name and os.path.exists(name):
                    os.unlink(name)
            self.value = deepcopy(value)

    def get(self):
        with self.lock:
            return deepcopy(self.value)


class SnapshotReader(Reader):
    def __init__(self, store, *, clock=time.time):
        super().__init__(clock=clock)
        self.store = store
        self.snapshot = None

    def _load(self):
        bundle = (self.snapshot or {}).get('portfolio', {}).get('bundle')
        if bundle is None:
            return None, 'UNAVAILABLE'
        return validate_export(bundle['export'], bundle['receipt'], 'canonical'), 'CURRENT'

    def system(self):
        snap = self.snapshot or {}
        now = self.clock()
        observer = snap.get('observer', {})
        state = freshness(observer.get('at'), now, 45)
        service = snap.get('service', {})
        running = service.get('ActiveState') == 'active' and service.get('SubState') == 'running'
        stopped = service.get('ActiveState') in ('inactive', 'failed')
        lanes = {}
        for lane in ('pump', 'pons', 'meteora', 'ramses'):
            row = observer.get('lanes', {}).get(lane, {})
            phase = ('PAUSED' if lane in ('meteora', 'ramses') else 'STOPPED') if stopped else row.get('phase', 'UNKNOWN')
            row_state = state if stopped else freshness(observer.get('health_at'), now)
            lanes[lane] = dict(operational=metric(phase, row_state),
                accounting=metric(row.get('accounting_reconciled'), 'UNAVAILABLE'),
                evidence=metric(None, 'STALE' if stopped else row_state,
                                'PAPER_STOPPED' if stopped else 'persisted_evidence_only'),
                runtime_identities={}, configured_identities={}, last_evidence_at=None,
                native_accounting=None, progress_age_seconds=metric(None, 'UNAVAILABLE'),
                provider_requests=metric(None, 'UNAVAILABLE'))
        return dict(mode='canonical', read_model=metric('authenticated_snapshot', freshness(snap.get('captured_at'), now)),
                    accounting=metric(None, 'UNAVAILABLE'), telemetry=metric('operational_observer', state),
                    observed_at=observer.get('at'), lanes=lanes,
                    paper_state='RUNNING' if running else 'STOPPED' if stopped else 'UNAVAILABLE')

    def view(self):
        with self._lock:
            self.snapshot = self.store.get()
            view = self._view()
            snap = self.snapshot or {}
            now = self.clock()
            delivery = freshness(snap.get('captured_at'), now)
            book = snap.get('portfolio', {}).get('observation', {})
            ledger_state = freshness(book.get('at'), now) if book.get('state') == 'CURRENT' else book.get('state', 'UNAVAILABLE')
            p = view['portfolio']
            if book.get('state') == 'CURRENT' and p.get('epoch'):
                # Read time is separate from the canonical publication time.
                # Replaying balances never extends a market mark's deadline.
                p['published_as_of'] = p['as_of']
                p['as_of'] = book['at']
                p['observation_source'] = 'validated_read_only_replay'
                for item in p['metrics'].values():
                    if item['state'] == 'STALE' and item['value'] is not None:
                        item['state'] = ledger_state
                raw = self._load()[0]
                for name, lane in view['lanes'].items():
                    lane['metrics'] = performance([row for row in raw['positions'] if row['lane'] == name],
                                                   now, ledger_state, raw['retired'].get(name))
                    lane['as_of'] = book['at']
                for key, amount in book['balances'].items():
                    p['metrics'][key] = metric(amount, ledger_state)
                balances = book['balances']
                if balances.get('unrealized_pnl') is not None:
                    net = Decimal(balances['realized_pnl']) + Decimal(balances['unrealized_pnl'])
                    p['metrics']['net_pnl'] = metric(net, ledger_state)
                    p['metrics']['return_pct'] = metric(net * 100 / Decimal('500.00'), ledger_state)
                p['state'] = ledger_state if balances.get('equity') is not None else 'UNAVAILABLE'
                p['reconciliation'] = metric(book['checks'], ledger_state)
            if delivery != 'CURRENT':
                for item in p['metrics'].values():
                    if item['state'] == 'CURRENT':
                        item['state'] = delivery
                for lane in view['lanes'].values():
                    for item in lane['metrics'].values():
                        if item['state'] == 'CURRENT':
                            item['state'] = delivery
                if p['state'] == 'CURRENT':
                    p['state'] = delivery
            if book.get('state') == 'FAIL_CLOSED':
                p['state'] = 'FAIL_CLOSED'
                p['reconciliation'] = metric(None, 'FAIL_CLOSED')
                for item in p['metrics'].values():
                    item['state'] = 'FAIL_CLOSED'
            view['state'] = p['state']
            operations = deepcopy(snap)
            operations.pop('portfolio', None)
            operations.update(snapshot_state=delivery,
                age_seconds=max(0, now-stamp(snap['captured_at'])) if snap else None,
                observer_state=freshness(snap.get('observer', {}).get('at'), now, 45),
                monitor_state=freshness(snap.get('monitor', {}).get('at'), now, 45),
                portfolio_state=ledger_state, paper_state=view['system']['paper_state'],
                dashboard_commit=os.environ.get('RENDER_GIT_COMMIT'),
                service_id=os.environ.get('RENDER_SERVICE_ID'))
            operations['alerts'] = list(snap.get('monitor', {}).get('conditions', []))
            for label, condition in (
                ('snapshot_'+delivery.lower(), delivery != 'CURRENT'),
                ('observer_'+operations['observer_state'].lower(), operations['observer_state'] != 'CURRENT'),
                ('monitor_'+operations['monitor_state'].lower(), operations['monitor_state'] != 'CURRENT'),
                ('portfolio_'+ledger_state.lower(), ledger_state != 'CURRENT'),
                ('paper_stopped', operations['paper_state'] == 'STOPPED'),
                ('trading_health_stale', freshness(snap.get('observer', {}).get('health_at'), now) != 'CURRENT'),
                ('candidate_not_deployed', bool(snap) and snap['source']['deployed_commit'] != snap['source']['candidate_commit'])):
                if condition:
                    operations['alerts'].append(label)
            p['snapshot_at'], p['snapshot_state'], p['paper_state'] = snap.get('captured_at'), delivery, operations['paper_state']
            view['system']['accounting'] = p['reconciliation']
            view['system']['operations'] = operations
            return view
