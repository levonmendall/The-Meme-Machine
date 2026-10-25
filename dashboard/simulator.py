"""Authenticated Pons telemetry intake and nonfinancial dashboard projection.

The retained wire format preserves the installed observer's identity/sequence
contract. Only operations are exposed in the original dashboard; financial views
continue to use the original canonical portfolio. This channel has no execution
authority and its latest-file cache is disposable.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time
from urllib.parse import urlsplit

from .api import HEADERS


SCHEMA = 'pons-simulator-snapshot-v1'
VIEW_SCHEMA = 'pons-simulator-view-v1'
LABEL = 'EXPERIMENTAL PONS CURRENT — SIMULATED TRADING — NO REAL MONEY'
PERSISTENCE = 'EPHEMERAL_UNVERIFIED'
MAX_BYTES = 512 * 1024
MAX_LIFECYCLES = 64
MAX_EQUITY = 500
MAX_EVENTS = 256
STALE_SECONDS = 60
METRICS = {
    'financial': dict.fromkeys((
        'starting_capital', 'cash', 'reserved', 'deployed', 'realized_pnl',
        'unrealized_pnl', 'equity', 'fees', 'gross_pnl', 'net_pnl', 'slippage',
        'open_exposure', 'average_profit', 'average_loss'), 'USD') | {
            'drawdown_pct': 'PERCENT', 'win_rate_pct': 'PERCENT',
            'net_return_pct': 'PERCENT'},
    'activity': dict.fromkeys((
        'pairs_seen', 'events_seen', 'events_processed', 'duplicates', 'gaps',
        'queue_depth', 'entries', 'partial_exits', 'exits', 'round_trips', 'open_positions',
        'winners', 'losers', 'recovered_events', 'dropped_events',
        'unrecovered_events', 'sampled_block_debt', 'launch_events'), 'COUNT') | {
            'average_hold_seconds': 'SECONDS',
            'trade_frequency_per_hour': 'PER_HOUR'},
    'strategy': dict.fromkeys((
        'evaluated', 'eligible', 'rejected', 'volume_quality_passes',
        'manager_decisions', 'manager_rejections'), 'COUNT'),
    'operational': {
        'heartbeat_age_seconds': 'SECONDS', 'processing_latency_ms': 'MILLISECONDS',
        'range_processing_ms': 'MILLISECONDS',
        'cpu_seconds': 'SECONDS', 'memory_bytes': 'BYTES',
        'provider_requests': 'COUNT', 'provider_failures': 'COUNT',
        'connected': 'COUNT'},
}
LIFECYCLE_METRICS = {
    'entry_price': 'USD', 'mark_price': 'USD', 'quantity': 'TOKENS',
    'remaining_quantity': 'TOKENS', 'realized_pnl': 'USD',
    'unrealized_pnl': 'USD', 'fees': 'USD',
}
REASONS = frozenset((
    'NONE', 'NOT_INITIALIZED', 'SNAPSHOT_UNAVAILABLE',
    'CONFIGURATION_UNAVAILABLE', 'STALE_SNAPSHOT', 'SOURCE_STOPPED',
    'SOURCE_FAILED', 'INPUT_UNAVAILABLE', 'QUOTE_UNAVAILABLE',
    'PROVIDER_UNAVAILABLE', 'PROTECTION_UNAVAILABLE',
    'NO_ELIGIBLE_OPPORTUNITY', 'HISTORY_TRUNCATED',
    'MEASUREMENT_UNAVAILABLE', 'ENTRY_RULE_REJECTED', 'POSITION_LIMIT',
    'CAPITAL_UNAVAILABLE', 'TIMEOUT', 'STOP_REQUESTED',
    'AUTHENTICATED_RAW_OBSERVATION_ONLY', 'PROVIDER_CLOCK_IDENTITY_UNAVAILABLE',
    'WAIT_FOR_VERIFIED_PROTECTION',
))
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_COMMIT = re.compile(r'[0-9a-f]{40}\Z')
_EXPERIMENT = re.compile(r'pons-simulator-[a-z0-9][a-z0-9-]{0,79}\Z')
_EPOCH = re.compile(r'paper-pons-simulator-1000-[0-9]{8}\Z')
_DECIMAL = re.compile(r'-?(?:0|[1-9][0-9]{0,29})(?:\.[0-9]{1,18})?\Z')
_UTC = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z\Z')
_VERSION = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}\Z')
_REVISION = re.compile(r'[a-z0-9][a-z0-9._-]{0,95}\Z')
BASELINE_STRATEGY = {
    'version': 'baseline-909738760e6f722b',
    'policy_revision': 'paper-postgrad-rally-v1',
    'policy_sha256': '909738760e6f722b8668a99493f698c3a415867f77f08199a61b0fb047381be7',
    'adaptation_state': 'BASELINE_UNCHANGED',
}


def _need(condition, code='simulator_schema'):
    if not condition:
        raise ValueError(code)


def _keys(value, required, optional=()):
    _need(type(value) is dict and set(required) <= set(value)
          and set(value) <= set(required) | set(optional))


def _clock(value):
    _need(type(value) in (int, float) and math.isfinite(value) and value >= 0,
          'simulator_clock')
    return value


def _stamp(value):
    _need(type(value) is str and _UTC.fullmatch(value) is not None,
          'simulator_timestamp')
    try:
        at = datetime.fromisoformat(value[:-1] + '+00:00').timestamp()
    except (ValueError, OverflowError):
        raise ValueError('simulator_timestamp') from None
    return _clock(at)


def _integer(value, *, minimum=0):
    _need(type(value) is int and minimum <= value <= 2**63 - 1)


def _hash(value):
    _need(type(value) is str and _DIGEST.fullmatch(value) is not None)


def _identity(value):
    _keys(value, ('experiment_id', 'epoch_id', 'source_commit', 'inception_sha256'))
    # Original and protected-pilot epochs cannot be selected by this namespace.
    _need(type(value['experiment_id']) is str
          and _EXPERIMENT.fullmatch(value['experiment_id']) is not None,
          'simulator_experiment')
    _need(type(value['epoch_id']) is str and _EPOCH.fullmatch(value['epoch_id']) is not None,
          'simulator_epoch')
    _need(type(value['source_commit']) is str
          and _COMMIT.fullmatch(value['source_commit']) is not None)
    _hash(value['inception_sha256'])


def _reasons(value):
    _need(type(value) is list and len(value) <= len(REASONS))
    _need(all(type(code) is str and code in REASONS for code in value))
    _need(len(set(value)) == len(value))


def _strategy_version(value):
    _keys(value, ('version', 'policy_revision', 'policy_sha256', 'adaptation_state'))
    _need(type(value['version']) is str and _VERSION.fullmatch(value['version']) is not None,
          'simulator_strategy_version')
    _need(type(value['policy_revision']) is str
          and _REVISION.fullmatch(value['policy_revision']) is not None,
          'simulator_strategy_version')
    _hash(value['policy_sha256'])
    _need(value['adaptation_state'] in ('BASELINE_UNCHANGED', 'EXPERIMENTAL', 'REVERTED'),
          'simulator_strategy_version')
    if value['adaptation_state'] == 'BASELINE_UNCHANGED':
        _need(value == BASELINE_STRATEGY, 'simulator_strategy_baseline')


def _metric(value, unit, captured):
    _keys(value, ('value', 'quality', 'unit', 'as_of'))
    _need(value['unit'] == unit)
    _need(value['quality'] in ('MEASURED', 'ESTIMATED', 'UNAVAILABLE'))
    if value['quality'] == 'UNAVAILABLE':
        _need(value['value'] is None and value['as_of'] is None)
        return
    raw = value['value']
    _need(type(raw) is str and _DECIMAL.fullmatch(raw) is not None,
          'simulator_decimal')
    amount = Decimal(raw)
    _need(amount.is_finite())
    if unit in ('COUNT', 'BYTES'):
        _need(amount >= 0 and amount == amount.to_integral_value())
    elif unit in ('SECONDS', 'MILLISECONDS', 'TOKENS', 'PER_HOUR'):
        _need(amount >= 0)
    _need(_stamp(value['as_of']) <= captured, 'simulator_metric_clock')


def _metric_group(value, catalog, captured):
    _keys(value, (), catalog)
    for name, item in value.items():
        _metric(item, catalog[name], captured)


def snapshot_digest(value):
    """Canonical content identity; timestamps are included and never renewed."""
    unsigned = {key: item for key, item in value.items() if key != 'snapshot_sha256'}
    raw = json.dumps(unsigned, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=True, allow_nan=False).encode('ascii')
    return hashlib.sha256(raw).hexdigest()


def _history_population(value, limit):
    _keys(value, ('rows', 'total', 'complete'))
    _need(type(value['rows']) is list and len(value['rows']) <= limit)
    _need(type(value['complete']) is bool)
    if value['total'] is not None:
        _integer(value['total'])
        _need(value['total'] >= len(value['rows']))
    if value['complete']:
        _need(value['total'] == len(value['rows']))


def _observer(value, identity, captured):
    """Read-side decisions are neither fills nor financial execution authority."""
    _keys(value, ('schema', 'read_only', 'source_commit', 'status', 'heartbeat_at',
                  'market_as_of', 'restart_count', 'current', 'survivor',
                  'decisions', 'history_coverage'))
    _need(value['schema'] == 'pons-readonly-observer-v1' and value['read_only'] is True)
    _need(value['source_commit'] == identity['source_commit'], 'simulator_observer_source')
    _need(value['status'] in ('RUNNING', 'DEGRADED', 'STOPPED', 'FAILED'))
    heartbeat = _stamp(value['heartbeat_at'])
    _need(heartbeat <= captured, 'simulator_observer_clock')
    if value['market_as_of'] is not None:
        _need(_stamp(value['market_as_of']) <= heartbeat, 'simulator_observer_clock')
    _integer(value['restart_count'])
    for strategy in ('current', 'survivor'):
        counts = value[strategy]
        _keys(counts, ('completed', 'eligible', 'wait', 'rejected', 'incomplete'))
        for count in counts.values():
            if count is not None:
                _integer(count)
        if counts['eligible'] is not None and counts['completed'] is not None:
            _need(counts['eligible'] <= counts['completed'], 'simulator_observer_counts')
    _need(value['history_coverage'] in ('COMPLETE', 'INCOMPLETE', 'UNKNOWN'))
    _need(type(value['decisions']) is list and len(value['decisions']) <= 64)
    previous, identities = None, set()
    for row in value['decisions']:
        _keys(row, ('id', 'at', 'strategy', 'action', 'reason',
                    'evidence_sha256', 'qualification'))
        _hash(row['id'])
        _need(row['id'] not in identities)
        identities.add(row['id'])
        at = _stamp(row['at'])
        _need(at <= heartbeat and (previous is None or at >= previous), 'simulator_observer_clock')
        previous = at
        _need(row['strategy'] in ('CURRENT', 'SURVIVOR'))
        _need(row['action'] in ('ENTER', 'WAIT', 'REJECT', 'HOLD', 'EXIT'))
        _need(type(row['reason']) is str and
              re.fullmatch(r'[a-z0-9_.:-]{1,128}', row['reason']) is not None)
        if row['evidence_sha256'] is not None:
            _hash(row['evidence_sha256'])
        _need(row['qualification'] in ('COMPLETE', 'INCOMPLETE'))
        if row['action'] == 'ENTER':
            _need(row['qualification'] == 'COMPLETE' and row['evidence_sha256'] is not None,
                  'simulator_observer_entry_evidence')


def _paper(value, identity, captured, *, lifecycle_count, event_count):
    """A dated resident report, never a Render execution permission."""
    _keys(value, ('schema', 'source_commit', 'epoch_id', 'inception_sha256',
        'policy_sha256', 'authority_sha256', 'permission_enabled', 'new_risk_enabled',
        'state', 'heartbeat_at', 'ledger_sequence', 'ledger_sha256',
        'lifecycle_total', 'lifecycle_truncated', 'event_total', 'events_truncated'))
    _need(value['schema'] == 'pons-current-paper-report-v1'
          and value['source_commit'] == identity['source_commit']
          and value['epoch_id'] == identity['epoch_id']
          and value['inception_sha256'] == identity['inception_sha256']
          and value['policy_sha256'] == BASELINE_STRATEGY['policy_sha256'],
          'simulator_paper_identity')
    for name in ('permission_enabled', 'new_risk_enabled'):
        _need(value[name] is None or type(value[name]) is bool,
              'simulator_paper_permission')
    if value['authority_sha256'] is not None:
        _hash(value['authority_sha256'])
    _need(value['state'] in ('UNAVAILABLE', 'DISABLED', 'WARMING', 'READY',
          'MANAGING', 'FAILED', 'STOPPED', 'STALE'), 'simulator_paper_state')
    if value['heartbeat_at'] is not None:
        _need(_stamp(value['heartbeat_at']) <= captured, 'simulator_paper_clock')
    elif value['state'] != 'UNAVAILABLE':
        raise ValueError('simulator_paper_clock')
    if value['state'] == 'UNAVAILABLE':
        _need(value['permission_enabled'] is None and value['new_risk_enabled'] is None,
              'simulator_paper_permission')
    if value['permission_enabled'] is True:
        _need(value['authority_sha256'] is not None, 'simulator_paper_permission')
    if value['state'] == 'READY':
        _need(value['permission_enabled'] is True, 'simulator_paper_permission')
    if value['state'] == 'DISABLED':
        _need(value['permission_enabled'] is False, 'simulator_paper_permission')
    if value['new_risk_enabled'] is True:
        _need(value['permission_enabled'] is True and value['authority_sha256'] is not None
              and value['state'] in ('READY', 'MANAGING'), 'simulator_paper_permission')
    _need((value['ledger_sequence'] is None) == (value['ledger_sha256'] is None),
          'simulator_paper_ledger')
    if value['ledger_sequence'] is not None:
        _integer(value['ledger_sequence'], minimum=1)
        _hash(value['ledger_sha256'])
    for total, truncated, count in (('lifecycle_total', 'lifecycle_truncated', lifecycle_count),
                                    ('event_total', 'events_truncated', event_count)):
        _need(type(value[truncated]) is bool)
        if value[total] is not None:
            _integer(value[total])
            _need(value[total] >= count, 'simulator_paper_population')
            _need(value[truncated] is (value[total] > count), 'simulator_paper_population')


def validate_snapshot(value, identity):
    _keys(value, ('schema', 'label', 'identity', 'sequence', 'snapshot_sha256',
                  'captured_at', 'execution_state', 'metrics', 'lifecycles',
                  'history', 'reason_codes'), ('strategy_version', 'observer', 'paper'))
    _need(value['schema'] == SCHEMA and value['label'] == LABEL)
    _identity(value['identity'])
    _need(value['identity'] == identity, 'simulator_identity')
    if 'strategy_version' in value:
        _strategy_version(value['strategy_version'])
    _integer(value['sequence'], minimum=1)
    _hash(value['snapshot_sha256'])
    captured = _stamp(value['captured_at'])
    if 'observer' in value:
        _observer(value['observer'], identity, captured)
    _need(value['execution_state'] in ('RUNNING', 'STOPPED', 'FAILED', 'UNKNOWN'))
    _keys(value['metrics'], (), METRICS)
    for name, group in value['metrics'].items():
        _metric_group(group, METRICS[name], captured)
    connected = value['metrics'].get('operational', {}).get('connected')
    if connected and connected['value'] is not None:
        _need(Decimal(connected['value']) in (Decimal(0), Decimal(1)))
    _need(type(value['lifecycles']) is list and len(value['lifecycles']) <= MAX_LIFECYCLES)
    life_ids = set()
    for row in value['lifecycles']:
        _keys(row, ('lifecycle_id', 'asset_id', 'state', 'entered_at', 'updated_at',
                    'settled_at', 'metrics', 'reason_codes'))
        _hash(row['lifecycle_id']); _hash(row['asset_id'])
        _need(row['lifecycle_id'] not in life_ids)
        life_ids.add(row['lifecycle_id'])
        _need(row['state'] in ('OPEN', 'PARTIAL', 'SETTLED', 'FAILED'))
        stamps = {}
        for name in ('entered_at', 'updated_at', 'settled_at'):
            if row[name] is not None:
                stamps[name] = _stamp(row[name])
                _need(stamps[name] <= captured)
        if 'entered_at' in stamps:
            _need(all(at >= stamps['entered_at'] for at in stamps.values()))
        _metric_group(row['metrics'], LIFECYCLE_METRICS, captured)
        _reasons(row['reason_codes'])
    _keys(value['history'], ('equity', 'events'))
    equity, events = value['history']['equity'], value['history']['events']
    _history_population(equity, MAX_EQUITY)
    _history_population(events, MAX_EVENTS)
    previous = None
    for row in equity['rows']:
        _keys(row, ('at', 'equity'))
        at = _stamp(row['at'])
        _need(at <= captured and (previous is None or at >= previous))
        previous = at
        _metric(row['equity'], 'USD', at)
    event_ids = set()
    previous = None
    for row in events['rows']:
        _keys(row, ('at', 'event_id', 'kind', 'lifecycle_id', 'reason_code'))
        at = _stamp(row['at'])
        _need(at <= captured and (previous is None or at >= previous))
        previous = at
        _hash(row['event_id'])
        _need(row['event_id'] not in event_ids)
        event_ids.add(row['event_id'])
        if row['lifecycle_id'] is not None:
            _hash(row['lifecycle_id'])
        _need(row['kind'] in ('ENTRY', 'ADD', 'PARTIAL_EXIT', 'EXIT', 'SETTLEMENT',
                              'REJECTED', 'PROTECTION', 'STOP'))
        _need(type(row['reason_code']) is str and row['reason_code'] in REASONS)
    _reasons(value['reason_codes'])
    if 'paper' in value:
        _paper(value['paper'], identity, captured,
               lifecycle_count=len(value['lifecycles']), event_count=len(events['rows']))
    raw = json.dumps(value, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
    _need(len(raw) <= MAX_BYTES, 'simulator_capacity')
    _need(snapshot_digest(value) == value['snapshot_sha256'], 'simulator_digest')
    return value


def decode_snapshot(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'simulator_capacity')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            _need(key not in result, 'simulator_duplicate_key')
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError('simulator_decimal')

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)


class SimulatorStore:
    """Single-service latest projection; no financial or history authority."""
    def __init__(self, path, *, experiment_id, epoch_id, source_commit, inception_sha256,
                 clock=time.time):
        self.path = Path(path)
        self.identity = dict(experiment_id=experiment_id, epoch_id=epoch_id, source_commit=source_commit,
                             inception_sha256=inception_sha256)
        _identity(self.identity)
        self.clock = clock
        self.lock = threading.RLock()
        self.value = None
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            _need(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_BYTES,
                  'simulator_capacity')
            raw = stream.read(MAX_BYTES + 1)
        self.value = deepcopy(validate_snapshot(decode_snapshot(raw), self.identity))

    def accept(self, value):
        value = deepcopy(value)
        validate_snapshot(value, self.identity)
        with self.lock:
            if self.value is not None:
                _need(value['sequence'] >= self.value['sequence'], 'simulator_sequence_regression')
                if value['sequence'] == self.value['sequence']:
                    _need(value['snapshot_sha256'] == self.value['snapshot_sha256'],
                          'simulator_sequence_equivocation')
                    # Retrying old bytes does not update timestamps or rewrite history.
                    return dict(idempotent=True, sequence=value['sequence'])
                _need(_stamp(value['captured_at']) >= _stamp(self.value['captured_at']),
                      'simulator_timestamp_regression')
            _need(-5 <= _clock(self.clock()) - _stamp(value['captured_at']) <= 120,
                  'simulator_clock')
            raw = json.dumps(value, separators=(',', ':'), ensure_ascii=True,
                             allow_nan=False).encode('ascii')
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            name = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                    name = stream.name
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.path)
                self.value = value
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if name and os.path.exists(name):
                    os.unlink(name)
            return dict(idempotent=False, sequence=value['sequence'])

    def get(self):
        with self.lock:
            return deepcopy(self.value)


def _unavailable(unit):
    return dict(value=None, quality='UNAVAILABLE', unit=unit, as_of=None)


class SimulatorReader:
    def __init__(self, store, *, clock=None):
        self.store = store
        self.clock = clock or (store.clock if store else time.time)

    def view(self):
        value = self.store.get() if self.store else None
        now = _clock(self.clock())
        at = _stamp(value['captured_at']) if value else None
        age = now - at if at is not None else None
        state = ('UNAVAILABLE' if age is None else
                 'CURRENT' if 0 <= age <= STALE_SECONDS else 'STALE')

        def metric(item):
            result = deepcopy(item)
            result['state'] = ('UNAVAILABLE' if item['value'] is None else
                               'CURRENT' if state == 'CURRENT'
                               and 0 <= now - _stamp(item['as_of']) <= STALE_SECONDS else 'STALE')
            return result

        metrics = {}
        for group, catalog in METRICS.items():
            supplied = value['metrics'].get(group, {}) if value else {}
            metrics[group] = {name: metric(supplied.get(name, _unavailable(unit)))
                              for name, unit in catalog.items()}
        lifecycles = deepcopy(value['lifecycles']) if value else []
        for row in lifecycles:
            row['metrics'] = {name: metric(row['metrics'].get(name, _unavailable(unit)))
                              for name, unit in LIFECYCLE_METRICS.items()}
        history = deepcopy(value['history']) if value else {
            name: dict(rows=[], total=None, complete=False) for name in ('equity', 'events')}
        for row in history['equity']['rows']:
            row['equity'] = metric(row['equity'])
        reasons = list(value['reason_codes']) if value else ['SNAPSHOT_UNAVAILABLE']
        if state == 'STALE' and 'STALE_SNAPSHOT' not in reasons:
            reasons.append('STALE_SNAPSHOT')
        result = dict(schema=VIEW_SCHEMA, label=LABEL, state=state,
            persistence=PERSISTENCE,
            source_ledger_authoritative=not bool(value and value.get('observer', {}).get('read_only')),
            identity=deepcopy(self.store.identity) if self.store else None,
            strategy_version=deepcopy(value.get('strategy_version')) if value else None,
            observer=deepcopy(value.get('observer')) if value else None,
            sequence=value['sequence'] if value else None,
            snapshot_sha256=value['snapshot_sha256'] if value else None,
            captured_at=value['captured_at'] if value else None,
            age_seconds=age, execution_state=value['execution_state'] if value else 'UNKNOWN',
            metrics=metrics, lifecycles=lifecycles, history=history, reason_codes=reasons)
        if value and 'paper' in value:
            paper = deepcopy(value['paper'])
            heartbeat = _stamp(paper['heartbeat_at']) if paper['heartbeat_at'] is not None else None
            if paper['state'] != 'UNAVAILABLE' and (state != 'CURRENT' or heartbeat is None
                    or not 0 <= now-heartbeat <= STALE_SECONDS):
                paper['state'] = 'STALE'
            result['paper'] = paper
        return result


class SimulatorChannel:
    def __init__(self, store=None, *, reason='CONFIGURATION_UNAVAILABLE'):
        _need(type(reason) is str and reason in REASONS)
        self.store = store
        self.reader = SimulatorReader(store)
        self.reason = reason

    def response(self, method, target):
        parsed = urlsplit(target)
        retired = (parsed.path == '/api/pons-simulator/state'
                   or parsed.path == '/dashboard/pons-simulator'
                   or parsed.path.startswith('/dashboard/pons-simulator/'))
        if not retired and parsed.path != '/api/dashboard/live':
            return None
        headers = dict(HEADERS)
        if method not in ('GET', 'HEAD'):
            return 405, dict(headers, **{'Content-Type': 'application/json', 'Allow': 'GET, HEAD'}), b'{"error":"read_only"}'
        if retired:
            return 410, dict(headers, **{'Content-Type': 'application/json'}), b'{"error":"dashboard_retired","dashboard":"/dashboard"}'
        if parsed.query:
            return 400, dict(headers, **{'Content-Type': 'application/json'}), b'{"error":"invalid_request"}'
        view = self.reader.view()
        if self.store is None:
            view['reason_codes'] = [self.reason]
        # This is an allowlist, not a relabelled financial snapshot. In particular,
        # no experimental cash, fills, equity series or lifecycle may escape into
        # the original portfolio's cards, chart, position or trade history.
        activity = ('pairs_seen', 'events_seen', 'events_processed', 'duplicates',
                    'gaps', 'queue_depth', 'recovered_events', 'dropped_events',
                    'unrecovered_events', 'sampled_block_debt', 'launch_events')
        result = {key: view[key] for key in (
            'state', 'persistence', 'identity', 'strategy_version', 'observer',
            'sequence', 'snapshot_sha256', 'captured_at', 'age_seconds',
            'execution_state', 'reason_codes')}
        result.update(schema='pons-live-operations-v1', label='Live Pons operations — PAPER only',
            financial_authority=False, source_ledger_authoritative=False,
            financial_source='ORIGINAL_CANONICAL_PORTFOLIO_ONLY',
            account_cutover=dict(state='NOT_ESTABLISHED',
                current_owner_epoch=(view['identity'] or {}).get('epoch_id'),
                reason='NO_AUTHENTICATED_ORIGINAL_EXECUTION_BINDING'),
            metrics=dict(operational=view['metrics']['operational'],
                activity={key: view['metrics']['activity'][key] for key in activity}))
        if 'paper' in view:
            result['paper'] = {key: view['paper'][key] for key in (
                'schema', 'state', 'heartbeat_at', 'source_commit', 'epoch_id',
                'inception_sha256', 'policy_sha256', 'permission_enabled',
                'new_risk_enabled', 'authority_sha256')}
        return 200, dict(headers, **{'Content-Type': 'application/json'}), json.dumps(
            result, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')

    def serve(self, handler):
        result = self.response(handler.command, handler.path)
        if result is None:
            return False
        status, headers, body = result
        handler.send_response(status)
        for key, value in headers.items():
            handler.send_header(key, value)
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        if handler.command != 'HEAD':
            handler.wfile.write(body)
        return True


def configured_channel(environ):
    """Incomplete/bad simulator configuration cannot repoint or break the old feed."""
    keys = ('MM_PONS_SIMULATOR_SNAPSHOT_PATH', 'MM_PONS_SIMULATOR_EXPERIMENT_ID',
            'MM_PONS_SIMULATOR_EPOCH_ID', 'MM_PONS_SIMULATOR_SOURCE_COMMIT',
            'MM_PONS_SIMULATOR_INCEPTION_SHA256')
    values = [environ.get(key) for key in keys]
    if not all(values):
        return SimulatorChannel()
    path, experiment, epoch, source, inception = values
    try:
        original = environ.get('MM_DASHBOARD_SNAPSHOT_PATH')
        if original:
            _need(Path(path).resolve() != Path(original).resolve(), 'simulator_path')
            if Path(path).exists() and Path(original).exists():
                _need(not os.path.samefile(path, original), 'simulator_path')
        store = SimulatorStore(path, experiment_id=experiment, epoch_id=epoch, source_commit=source,
                               inception_sha256=inception)
        return SimulatorChannel(store)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, OverflowError, RecursionError):
        return SimulatorChannel(reason='CONFIGURATION_UNAVAILABLE')
