"""Independent, bounded projection of an external Pons simulator ledger.

This channel cannot read the original portfolio or control either trading service.
Its local latest-file cache is disposable; the external experiment owns history.
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

from .api import HEADERS, STATIC


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
        'queue_depth', 'entries', 'exits', 'round_trips', 'open_positions',
        'winners', 'losers', 'recovered_events', 'dropped_events',
        'unrecovered_events'), 'COUNT') | {
            'average_hold_seconds': 'SECONDS',
            'trade_frequency_per_hour': 'PER_HOUR'},
    'strategy': dict.fromkeys((
        'evaluated', 'eligible', 'rejected', 'volume_quality_passes'), 'COUNT'),
    'operational': {
        'heartbeat_age_seconds': 'SECONDS', 'processing_latency_ms': 'MILLISECONDS',
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
))
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_COMMIT = re.compile(r'[0-9a-f]{40}\Z')
_EXPERIMENT = re.compile(r'pons-simulator-[a-z0-9][a-z0-9-]{0,79}\Z')
_EPOCH = re.compile(r'paper-pons-simulator-1000-[0-9]{8}\Z')
_DECIMAL = re.compile(r'-?(?:0|[1-9][0-9]{0,29})(?:\.[0-9]{1,18})?\Z')
_UTC = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z\Z')


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


def validate_snapshot(value, identity):
    _keys(value, ('schema', 'label', 'identity', 'sequence', 'snapshot_sha256',
                  'captured_at', 'execution_state', 'metrics', 'lifecycles',
                  'history', 'reason_codes'))
    _need(value['schema'] == SCHEMA and value['label'] == LABEL)
    _identity(value['identity'])
    _need(value['identity'] == identity, 'simulator_identity')
    _integer(value['sequence'], minimum=1)
    _hash(value['snapshot_sha256'])
    captured = _stamp(value['captured_at'])
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
        _need(row['kind'] in ('ENTRY', 'PARTIAL_EXIT', 'EXIT', 'SETTLEMENT',
                              'REJECTED', 'PROTECTION', 'STOP'))
        _need(type(row['reason_code']) is str and row['reason_code'] in REASONS)
    _reasons(value['reason_codes'])
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
        return dict(schema=VIEW_SCHEMA, label=LABEL, state=state,
            persistence=PERSISTENCE, source_ledger_authoritative=True,
            identity=deepcopy(self.store.identity) if self.store else None,
            sequence=value['sequence'] if value else None,
            snapshot_sha256=value['snapshot_sha256'] if value else None,
            captured_at=value['captured_at'] if value else None,
            age_seconds=age, execution_state=value['execution_state'] if value else 'UNKNOWN',
            metrics=metrics, lifecycles=lifecycles, history=history, reason_codes=reasons)


class SimulatorChannel:
    def __init__(self, store=None, *, reason='CONFIGURATION_UNAVAILABLE'):
        _need(type(reason) is str and reason in REASONS)
        self.store = store
        self.reader = SimulatorReader(store)
        self.reason = reason

    def response(self, method, target):
        parsed = urlsplit(target)
        files = {
            '/dashboard/pons-simulator': ('pons-simulator.html', 'text/html; charset=utf-8'),
            '/dashboard/pons-simulator/': ('pons-simulator.html', 'text/html; charset=utf-8'),
            '/dashboard/pons-simulator/app.js': ('pons-simulator.js', 'text/javascript; charset=utf-8'),
            '/dashboard/pons-simulator/style.css': ('pons-simulator.css', 'text/css; charset=utf-8'),
        }
        if parsed.path not in files and parsed.path != '/api/pons-simulator/state':
            return None
        headers = dict(HEADERS)
        if method not in ('GET', 'HEAD'):
            return 405, dict(headers, **{'Content-Type': 'application/json', 'Allow': 'GET, HEAD'}), b'{"error":"read_only"}'
        if parsed.query:
            return 400, dict(headers, **{'Content-Type': 'application/json'}), b'{"error":"invalid_request"}'
        if parsed.path in files:
            name, mime = files[parsed.path]
            try:
                return 200, dict(headers, **{'Content-Type': mime}), (STATIC / name).read_bytes()
            except OSError:
                return 503, dict(headers, **{'Content-Type': 'application/json'}), b'{"error":"simulator_unavailable"}'
        view = self.reader.view()
        if self.store is None:
            view['reason_codes'] = [self.reason]
        return 200, dict(headers, **{'Content-Type': 'application/json'}), json.dumps(
            view, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')

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
