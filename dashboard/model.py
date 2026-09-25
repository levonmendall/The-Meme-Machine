"""Bounded local accounting export reader; no canonical writers or acquisition.

The existing four native books are NOT a common USD portfolio. An explicit
inception receipt and epoch-bound USD export are required before reporting one.
See docs/READ_ONLY_DASHBOARD.md for the producer contract and authority boundary.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import re
import threading
import time

LANES = ('pump', 'pons', 'ramses', 'meteora')
STATES = ('CURRENT', 'STALE', 'UNAVAILABLE', 'FAIL_CLOSED', 'UNKNOWN', 'NOT_INITIALIZED')
CAPITAL = Decimal('500.00')
MAX_BYTES = 4 * 1024 * 1024
MAX_POSITIONS = 5000
MAX_POINTS = 2000
MONEY_FIELDS = ('equity', 'available_cash', 'reserved_cash', 'deployed_capital',
                'realized_pnl', 'unrealized_pnl', 'net_pnl', 'fees', 'shared_costs')
METRICS = MONEY_FIELDS + ('return_pct', 'contribution_pct', 'trades_taken',
    'completed_trades', 'open_positions', 'wins', 'losses', 'breakevens',
    'win_rate', 'average_result', 'largest_winner', 'largest_loser',
    'average_holding_seconds', 'max_drawdown_pct', 'lane_return_pct')


def decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('exact_decimal_required')
    if len(str(value)) > 70 or not re.fullmatch(r'-?\d{1,40}(\.\d{1,24})?', str(value)):
        raise ValueError('invalid_decimal')
    return Decimal(value)


def worse(left, right):
    order = {'CURRENT': 0, 'STALE': 1, 'UNKNOWN': 2, 'UNAVAILABLE': 3, 'NOT_INITIALIZED': 4, 'FAIL_CLOSED': 5}
    return left if order[left] >= order[right] else right


def stamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('utc_timestamp_required')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError('utc_timestamp_required')
    return dt.timestamp()


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', value):
        raise ValueError('invalid_identity')
    return value


def strategy_identity(value):
    if not isinstance(value, str) or '://' in value or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,180}', value):
        raise ValueError('invalid_strategy_identity')
    return value


def safe_hash(value):
    return value if isinstance(value, str) and re.fullmatch('[a-f0-9]{40}|[a-f0-9]{64}', value) else None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def inception_receipt(epoch_id, inception_at, event_id):
    """Construct an immutable receipt for a separately authorized canonical event.

    Does not establish an account, write a file or mint a timestamp. The caller
    must supply the real canonical event/time. No API exposes this function.
    """
    stamp(inception_at)
    return dict(schema='meme-machine-portfolio-inception-v1',
                epoch_id=identity(epoch_id), inception_at=inception_at,
                canonical_event_id=identity(event_id), starting_capital='500.00',
                currency='USD', paper_only=True)


def validate_inception(value):
    expected = inception_receipt(value['epoch_id'], value['inception_at'], value['canonical_event_id'])
    if value != expected:
        raise ValueError('inception_contract')
    return expected


def metric(value=None, state='CURRENT', reason=None, unit=None):
    if value is None and state == 'CURRENT':
        state = 'UNAVAILABLE'
    if isinstance(value, Decimal):
        value = format(value, 'f')
    out = dict(value=value, state=state)
    if reason:
        out['reason'] = reason
    if unit:
        out['unit'] = unit
    return out


def missing_metrics(state, reason):
    return {k: metric(None, state, reason) for k in METRICS}


def read_json(path):
    with Path(path).open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('input_capacity')
    return json.loads(raw, parse_float=Decimal)


def safe_identities(source):
    return {key: safe_hash(source.get(key)) for key in
            ('source_sha', 'policy_hash', 'config_hash', 'source_diff_sha256')}


def native_accounting(row, lane):
    """Allowlisted native atoms, never promoted into the new USD portfolio."""
    source = row.get('cohort_accounting' if lane == 'pons' else 'native_accounting')
    if not isinstance(source, dict):
        return None
    fields = ('initial', 'cash', 'reserved', 'pending', 'basis', 'rent', 'fees', 'realized',
              'genesis', 'booked_realized', 'remaining_cost_basis', 'unsettled',
              'realized_pnl_lamports', 'paper_capital', 'committed', 'open_positions')
    def atoms(value):
        return {k: str(value[k]) for k in fields if type(value.get(k)) is int}
    out = atoms(source)
    if isinstance(source.get('genesis'), dict) and type(source['genesis'].get('capital')) is int:
        out['genesis_capital'] = str(source['genesis']['capital'])
    sleeves = source.get('by_quote_asset')
    if isinstance(sleeves, dict):
        out['by_quote_asset'] = {asset: atoms(value) for asset, value in list(sleeves.items())[:32]
                                if re.fullmatch(r'0x[a-fA-F0-9]{40}', str(asset)) and isinstance(value, dict)}
    return out


def position(row, epoch, observed):
    """Only canonical lifecycle summaries, never individual fills, are accepted."""
    entered = stamp(row['entered_at'])
    if entered < stamp(epoch['inception_at']) or entered > observed:
        raise ValueError('position_outside_epoch')
    state = row['state']
    if state not in ('OPEN', 'SETTLED') or row['lane'] not in LANES:
        raise ValueError('position_state')
    if row.get('exposure_entered') is not True:
        raise ValueError('position_without_exposure')
    settled_at = row.get('settled_at')
    if state == 'SETTLED' and (settled_at is None or not entered <= stamp(settled_at) <= observed):
        raise ValueError('terminal_settlement_required')
    if state == 'OPEN' and settled_at is not None:
        raise ValueError('open_terminal_conflict')
    money = {k: decimal(row[k]) if row.get(k) is not None else None for k in
             ('capital', 'remaining_basis', 'realized_pnl', 'fees', 'gross_result',
              'entry_value', 'exit_value')}
    for key in ('capital', 'remaining_basis', 'fees'):
        if money[key] is not None and money[key] < 0:
            raise ValueError('negative_basis_or_cost')
    if state == 'SETTLED' and money['remaining_basis'] not in (None, 0):
        raise ValueError('settled_remaining_basis')
    if state == 'OPEN' and money['remaining_basis'] is not None and money['remaining_basis'] <= 0:
        raise ValueError('open_without_basis')
    if all(money[k] is not None for k in ('gross_result', 'fees', 'realized_pnl')):
        if money['gross_result'] - money['fees'] != money['realized_pnl']:
            raise ValueError('gross_net_cost_mismatch')
    valuation = row.get('mark')
    mark = None
    if valuation is not None:
        status = valuation.get('state')
        if status not in STATES:
            raise ValueError('mark_state')
        mark = dict(state=status, value=None, as_of=None, valid_until=None)
        if status == 'CURRENT':
            value = decimal(valuation['net_liquidation_value'])
            at, until = stamp(valuation['as_of']), stamp(valuation['valid_until'])
            if value < 0 or not entered <= at <= observed or until < at:
                raise ValueError('mark_clock')
            mark.update(value=str(value), as_of=valuation['as_of'], valid_until=valuation['valid_until'])
    lifecycle = []
    allowed = ('qualification', 'authorization', 'paper_entry', 'monitoring',
               'partial_realization', 'rebalance', 'runner', 'exit', 'settlement')
    for event in row.get('lifecycle', []):
        if event['stage'] not in allowed or not stamp(epoch['inception_at']) <= stamp(event['at']) <= observed:
            raise ValueError('lifecycle_event')
        lifecycle.append(dict(stage=event['stage'], at=event['at']))
    if len(lifecycle) > 100:
        raise ValueError('lifecycle_capacity')
    optional = {}
    for key in ('harvest_state', 'runner_state', 'lp_state', 'range_id', 'rebalance_state', 'exit_reason'):
        if row.get(key) is not None:
            optional[key] = identity(row[key])
    for key in ('rebalance_count',):
        if row.get(key) is not None:
            if type(row[key]) is not int or row[key] < 0:
                raise ValueError('invalid_count')
            optional[key] = row[key]
    if type(row.get('in_range')) is bool:
        optional['in_range'] = row['in_range']
    for key in ('remaining_runner_exposure',):
        if row.get(key) is not None:
            optional[key] = str(decimal(row[key]))
    return dict(id=identity(row['id']), lane=row['lane'], asset=identity(row['asset']),
                state=state, entered_at=row['entered_at'], settled_at=settled_at,
                strategy_id=strategy_identity(row['strategy_id']) if row.get('strategy_id') else None,
                identities=safe_identities(row), lifecycle=lifecycle, mark=mark,
                **{k: str(v) if v is not None else None for k, v in money.items()}, **optional)


def validate_export(raw, epoch, mode):
    if raw.get('schema') != 'meme-machine-portfolio-export-v1' or raw.get('mode') != mode:
        raise ValueError('export_mode_or_schema')
    if raw.get('inception_sha256') != hashlib.sha256(canonical(epoch).encode()).hexdigest():
        raise ValueError('inception_binding')
    if raw.get('epoch_id') != epoch['epoch_id'] or raw.get('complete_lifecycle_coverage') is not True:
        raise ValueError('epoch_or_coverage')
    observed = stamp(raw['as_of'])
    valid_until = stamp(raw['valid_until'])
    if observed < stamp(epoch['inception_at']) or valid_until < observed:
        raise ValueError('accounting_clock')
    if type(raw['sequence']) is not int or raw['sequence'] < 0:
        raise ValueError('export_sequence')
    rows = raw['positions']
    if not isinstance(rows, list) or len(rows) > MAX_POSITIONS:
        raise ValueError('position_capacity')
    selected = [r for r in rows if r.get('epoch_id') == epoch['epoch_id']]
    positions = [position(r, epoch, observed) for r in selected]
    if len({p['id'] for p in positions}) != len(positions):
        raise ValueError('duplicate_position_lifecycle')
    balance = {k: decimal(raw['balances'][k]) if raw['balances'].get(k) is not None else None
               for k in ('equity', 'available_cash', 'reserved_cash', 'deployed_capital', 'realized_pnl', 'fees', 'shared_costs')}
    if raw.get('external_adjustments') not in (None, []):
        raise ValueError('unsupported_external_adjustments')
    for k in ('available_cash', 'reserved_cash', 'deployed_capital', 'fees', 'shared_costs'):
        if balance[k] is not None and balance[k] < 0:
            raise ValueError('negative_cash_or_cost')
    histories = {k: [] for k in ('portfolio',) + LANES}
    rows = raw.get('history', [])
    if len(rows) > MAX_POINTS:
        raise ValueError('history_capacity')
    for row in rows:
        if row.get('epoch_id') != epoch['epoch_id']:
            continue
        series = row['series']
        if series not in histories or not stamp(epoch['inception_at']) <= stamp(row['at']) <= observed:
            raise ValueError('history_epoch_or_clock')
        value = decimal(row['value']) if row.get('value') is not None else None
        if series == 'portfolio' and value is not None and value < 0:
            raise ValueError('negative_equity')
        histories[series].append(dict(at=row['at'], value=str(value) if value is not None else None))
    for rows in histories.values():
        rows.sort(key=lambda x: stamp(x['at']))
        if len({r['at'] for r in rows}) != len(rows):
            raise ValueError('duplicate_history_sample')
    return dict(epoch=epoch, as_of=raw['as_of'], valid_until=raw['valid_until'],
                sequence=raw['sequence'], positions=positions, balances=balance,
                history=histories, excluded_positions=len(raw['positions'])-len(positions),
                identities=safe_identities(raw), history_complete=raw.get('history_complete') is True)


def performance(rows, now, state):
    settled = [p for p in rows if p['state'] == 'SETTLED']
    opened = [p for p in rows if p['state'] == 'OPEN']
    outcomes_complete = all(p['realized_pnl'] is not None for p in settled)
    results = [decimal(p['realized_pnl']) for p in settled if p['realized_pnl'] is not None]
    wins, losses = [x for x in results if x > 0], [x for x in results if x < 0]
    realized = sum((decimal(p['realized_pnl']) for p in rows), Decimal(0)) if all(p['realized_pnl'] is not None for p in rows) else None
    unrealized = Decimal(0)
    mark_state = state
    for p in opened:
        m = p['mark']
        if p['remaining_basis'] is None:
            mark_state = worse(mark_state, 'UNAVAILABLE')
            continue
        if m is None or m['state'] != 'CURRENT':
            mark_state = worse(mark_state, m['state'] if m else 'UNAVAILABLE')
        elif now > stamp(m['valid_until']):
            if mark_state == 'CURRENT':
                mark_state = 'STALE'
        else:
            unrealized += decimal(m['value']) - decimal(p['remaining_basis'])
    valid = mark_state == 'CURRENT'
    net = realized + unrealized if valid and realized is not None else None
    hold = [Decimal(str(stamp(p['settled_at']) - stamp(p['entered_at']))) for p in settled]
    fees = sum((decimal(p['fees']) for p in rows), Decimal(0)) if all(p['fees'] is not None for p in rows) else None
    out = missing_metrics('UNAVAILABLE', 'not_provided_by_canonical_accounting')
    values = dict(realized_pnl=realized, fees=fees, deployed_capital=sum((decimal(p['remaining_basis']) for p in opened), Decimal(0)) if all(p['remaining_basis'] is not None for p in opened) else None,
        trades_taken=len(rows), completed_trades=len(settled), open_positions=len(opened),
        wins=len(wins) if outcomes_complete else None, losses=len(losses) if outcomes_complete else None, breakevens=sum(x == 0 for x in results) if outcomes_complete else None,
        win_rate=Decimal(len(wins))*100/len(wins+losses) if outcomes_complete and (wins or losses) else None,
        average_result=sum(results)/len(results) if outcomes_complete and results else None,
        largest_winner=max(wins) if outcomes_complete and wins else None, largest_loser=min(losses) if outcomes_complete and losses else None,
        average_holding_seconds=sum(hold)/len(hold) if hold else None)
    out.update({k: metric(v, state) for k, v in values.items()})
    out['unrealized_pnl'] = metric(unrealized if valid else None, mark_state, 'canonical_net_liquidation_marks_required' if not valid else None)
    out['net_pnl'] = metric(net, mark_state)
    out['contribution_pct'] = metric(net * 100 / CAPITAL if net is not None else None, mark_state)
    return out


class Reader:
    """Input changes invalidate a bounded cache; reads never import runtime code."""
    def __init__(self, inception=None, accounting=None, telemetry=None, sources=None, *, mode='canonical', clock=time.time):
        if mode not in ('canonical', 'fixture'):
            raise ValueError('mode')
        self.inception, self.accounting, self.telemetry, self.sources = inception, accounting, telemetry, sources
        self.mode, self.clock = mode, clock
        self._cache = None
        self._key = None
        self._epoch_hash = None
        self._sequence = -1
        self._sequence_hash = None
        self._lifecycles = {}
        self._lock = threading.RLock()
        self._view_cache = None
        self._view_key = None
        self._view_until = 0

    def _load(self):
        if self.inception is None:
            return None, 'NOT_INITIALIZED'
        try:
            epoch = validate_inception(read_json(self.inception))
            digest = hashlib.sha256(canonical(epoch).encode()).hexdigest()
            if self._epoch_hash is not None and digest != self._epoch_hash:
                return None, 'FAIL_CLOSED'
            self._epoch_hash = digest
            if self.accounting is None:
                return None, 'UNAVAILABLE'
            stat = Path(self.accounting).stat()
            key = (stat.st_ino, stat.st_mtime_ns, stat.st_size, digest)
            if key != self._key:
                raw = read_json(self.accounting)
                value = validate_export(raw, epoch, self.mode)
                body_hash = hashlib.sha256(canonical(raw).encode()).hexdigest()
                if value['sequence'] < self._sequence or (value['sequence'] == self._sequence and self._sequence_hash not in (None, body_hash)):
                    return None, 'FAIL_CLOSED'
                current = {p['id']: p for p in value['positions']}
                for pid, before in self._lifecycles.items():
                    after = current.get(pid)
                    if after is None or any(before[k] != after[k] for k in ('lane', 'asset', 'entered_at')):
                        return None, 'FAIL_CLOSED'
                    terminal_facts = ('state', 'settled_at', 'capital', 'remaining_basis',
                                      'realized_pnl', 'fees', 'gross_result', 'entry_value',
                                      'exit_value', 'strategy_id')
                    if before['state'] == 'SETTLED' and any(before[k] is not None and before[k] != after[k] for k in terminal_facts):
                        return None, 'FAIL_CLOSED'
                self._lifecycles = deepcopy(current)
                self._sequence, self._sequence_hash = value['sequence'], body_hash
                self._cache, self._key = value, key
            return self._cache, 'CURRENT'
        except FileNotFoundError:
            return None, 'UNAVAILABLE'
        except (OSError, ValueError, TypeError, KeyError, ArithmeticError, AttributeError):
            return None, 'FAIL_CLOSED'

    def system(self):
        now = self.clock()
        out = dict(mode=self.mode, read_model=metric('CURRENT'),
                   accounting=metric(None, 'NOT_INITIALIZED'),
                   telemetry=metric(None, 'UNAVAILABLE'), lanes={})
        spec = {}
        if self.sources:
            try:
                spec = read_json(self.sources).get('lanes', {})
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        result = {}
        if self.telemetry:
            try:
                result = read_json(self.telemetry)
                if not isinstance(result, dict) or not isinstance(result.get('lanes', {}), dict):
                    raise ValueError('telemetry_shape')
                at = result.get('observed_at', result.get('ended_at'))
                fresh = isinstance(at, (int, Decimal)) and 0 <= Decimal(str(now))-at <= 120
                out['telemetry'] = metric('persisted_supervisor', 'CURRENT' if fresh else 'STALE')
                out['observed_at'] = datetime.fromtimestamp(float(at), timezone.utc).isoformat() if isinstance(at, (int, Decimal)) else None
            except (OSError, ValueError, TypeError, OverflowError):
                out['telemetry'] = metric(None, 'FAIL_CLOSED')
                result = {}
        for lane in LANES:
            row = result.get('lanes', {}).get(lane, {})
            if not isinstance(row, dict):
                row = {}
            health = row.get('health', 'unknown')
            known = ('responsive', 'starting', 'responsive_but_strategy_stalled', 'progress_stalled', 'exited', 'terminated', 'unknown')
            if health not in known:
                health = 'unknown'
            state = ('CURRENT' if health == 'responsive' else 'FAIL_CLOSED' if health in ('progress_stalled', 'responsive_but_strategy_stalled', 'terminated') or row.get('unexpected_exit') else 'UNKNOWN')
            if state == 'CURRENT' and out['telemetry']['state'] != 'CURRENT':
                state = out['telemetry']['state']
            # Runtime identities and configured source identities have different provenance.
            configured = spec.get(lane, {}) if isinstance(spec, dict) else {}
            if not isinstance(configured, dict):
                configured = {}
            out['lanes'][lane] = dict(operational=metric(health, state),
                accounting=metric(row.get('accounting_reconciled') if type(row.get('accounting_reconciled')) is bool else None,
                                  'FAIL_CLOSED' if row.get('accounting_reconciled') is False else out['telemetry']['state']),
                evidence=metric(None, 'UNKNOWN', 'process_heartbeat_is_not_evidence_freshness'),
                runtime_identities=safe_identities(row), configured_identities=safe_identities(configured),
                last_evidence_at=None, native_accounting=native_accounting(row, lane),
                progress_age_seconds=metric(str(row['progress_age_seconds']) if isinstance(row.get('progress_age_seconds'), (int, Decimal)) else None, out['telemetry']['state']),
                provider_requests=metric(row.get('provider_requests') if type(row.get('provider_requests')) is int else None, out['telemetry']['state']))
        return out

    def view(self):
        # Share one aggregation among a page's parallel API reads. Invalidate on
        # any source change or exact valuation/telemetry deadline, never extend it.
        with self._lock:
            now = self.clock()
            key = []
            for path in (self.inception, self.accounting, self.telemetry, self.sources):
                try:
                    s = Path(path).stat() if path else None
                    key.append((s.st_ino, s.st_mtime_ns, s.st_size) if s else None)
                except OSError:
                    key.append(None)
            if key == self._view_key and self._view_cache is not None and now < self._view_until:
                return deepcopy(self._view_cache)
            view = self._view()
            deadlines = [now+1]
            if self._cache:
                deadlines.append(stamp(self._cache['valid_until']))
                deadlines.extend(stamp(p['mark']['valid_until']) for p in self._cache['positions']
                                 if p['mark'] and p['mark'].get('valid_until'))
            if view['system'].get('observed_at'):
                deadlines.append(stamp(view['system']['observed_at'])+120)
            self._view_key, self._view_cache, self._view_until = key, view, min(deadlines)
            return deepcopy(view)

    def _view(self):
        with self._lock, localcontext() as context:
            context.prec = 80
            data, state = self._load()
            now = self.clock()
            system = self.system()
            if data is not None:
                if now < stamp(data['as_of']):
                    data, state = None, 'FAIL_CLOSED'
                elif now > stamp(data['valid_until']):
                    state = 'STALE'
            portfolio = dict(state=state, mode=self.mode, desired_starting_capital='500.00',
                starting_capital=metric(None, state), metrics=missing_metrics(state, 'canonical_epoch_accounting_required'),
                as_of=None, reconciliation=metric(None, state), epoch=None)
            lanes = {lane: dict(lane=lane, metrics=missing_metrics(state, 'canonical_epoch_accounting_required'),
                              health=system['lanes'][lane], as_of=None) for lane in LANES}
            history = {k: [] for k in ('portfolio',) + LANES}
            positions = []
            if data is not None:
                positions = deepcopy(data['positions'])
                history = data['history']
                portfolio.update(epoch=data['epoch'], starting_capital=metric(CAPITAL), as_of=data['as_of'],
                                 excluded_historical_positions=data['excluded_positions'], identities=data['identities'])
                for lane in LANES:
                    lanes[lane].update(metrics=performance([p for p in positions if p['lane'] == lane], now, state), as_of=data['as_of'])
                metrics = performance(positions, now, state)
                balance = data['balances']
                for key, value in balance.items():
                    metrics[key] = metric(value, state)
                unrealized = metrics['unrealized_pnl']['value']
                net = balance['realized_pnl'] + decimal(unrealized) if balance['realized_pnl'] is not None and unrealized is not None else None
                metrics['net_pnl'] = metric(net, metrics['unrealized_pnl']['state'])
                metrics['return_pct'] = metric(net*100/CAPITAL if net is not None else None, metrics['net_pnl']['state'])
                metrics['contribution_pct'] = metric(None, 'UNAVAILABLE', 'portfolio_uses_return_pct')
                if unrealized is None:
                    metrics['equity'] = metric(None, metrics['unrealized_pnl']['state'], 'current_valuation_unavailable')
                checks = {}
                realized = sum((decimal(p['realized_pnl']) for p in positions), Decimal(0)) if all(p['realized_pnl'] is not None for p in positions) else None
                if realized is not None and balance['realized_pnl'] is not None and balance['shared_costs'] is not None:
                    checks['lane_realized_less_shared_costs'] = realized-balance['shared_costs'] == balance['realized_pnl']
                if balance['deployed_capital'] is not None and all(p['remaining_basis'] is not None for p in positions):
                    checks['remaining_basis'] = sum((decimal(p['remaining_basis']) for p in positions), Decimal(0)) == balance['deployed_capital']
                if all(balance[k] is not None for k in ('available_cash', 'reserved_cash', 'deployed_capital', 'realized_pnl')):
                    checks['cash_basis_conservation'] = balance['available_cash']+balance['reserved_cash']+balance['deployed_capital'] == CAPITAL+balance['realized_pnl']
                if net is not None and balance['equity'] is not None:
                    checks['equity_equals_inception_plus_net'] = balance['equity'] == CAPITAL+net
                if balance['fees'] is not None and balance['shared_costs'] is not None and all(p['fees'] is not None for p in positions):
                    checks['cost_attribution'] = sum((decimal(p['fees']) for p in positions), Decimal(0))+balance['shared_costs'] == balance['fees']
                reconcile_state = 'FAIL_CLOSED' if False in checks.values() else state if len(checks) == 5 else 'UNAVAILABLE'
                portfolio['reconciliation'] = metric(checks, reconcile_state)
                portfolio['state'] = worse(state, metrics['unrealized_pnl']['state'])
                if reconcile_state == 'FAIL_CLOSED':
                    portfolio['state'] = 'FAIL_CLOSED'
                    for item in metrics.values():
                        if item['value'] is not None:
                            item['state'] = 'FAIL_CLOSED'
                    for lane in lanes.values():
                        for item in lane['metrics'].values():
                            if item['value'] is not None:
                                item['state'] = 'FAIL_CLOSED'
                # Only actual equity history supports drawdown. Lane P&L is not lane equity.
                points = history['portfolio']
                if data['history_complete'] and len(points) >= 2 and all(p['value'] is not None for p in points):
                    peak, worst = Decimal(0), Decimal(0)
                    for p in points:
                        v = decimal(p['value']); peak = max(peak, v)
                        if peak:
                            worst = max(worst, (peak-v)*100/peak)
                    metrics['max_drawdown_pct'] = metric(worst, state)
                portfolio['metrics'] = metrics
                for p in positions:
                    m = performance([p], now, state)
                    p['unrealized_pnl'] = m['unrealized_pnl']
                    p['unrealized_pct'] = metric(decimal(m['unrealized_pnl']['value'])*100/decimal(p['remaining_basis']) if p['state']=='OPEN' and p['remaining_basis'] is not None and m['unrealized_pnl']['value'] is not None else None, m['unrealized_pnl']['state'])
                    p['age_seconds'] = int((stamp(p['settled_at']) if p['settled_at'] else now)-stamp(p['entered_at']))
                    p['current_value'] = metric(p['mark']['value'] if p['mark'] and m['unrealized_pnl']['state']=='CURRENT' else None, m['unrealized_pnl']['state'])
                    p.pop('mark')
                    p['outcome'] = ('winner' if decimal(p['realized_pnl']) > 0 else 'loser' if decimal(p['realized_pnl']) < 0 else 'breakeven') if p['state']=='SETTLED' and p['realized_pnl'] is not None else None
            system['accounting'] = metric(portfolio['reconciliation']['value'], portfolio['reconciliation']['state'])
            system['read_model'] = metric('local_read_only', 'FAIL_CLOSED' if state=='FAIL_CLOSED' else 'CURRENT')
            daily = {}
            for p in positions:
                day = p['entered_at'][:10]
                daily.setdefault(day, dict(entries=0, settlements=0, completed_net_pnl=Decimal(0)))['entries'] += 1
                if p['state'] == 'SETTLED':
                    day = p['settled_at'][:10]
                    d = daily.setdefault(day, dict(entries=0, settlements=0, completed_net_pnl=Decimal(0)))
                    d['settlements'] += 1
                    if p['realized_pnl'] is None:
                        d['completed_net_pnl'] = None
                    elif d['completed_net_pnl'] is not None:
                        d['completed_net_pnl'] += decimal(p['realized_pnl'])
            daily = [dict(day=day, entries=row['entries'], settlements=row['settlements'],
                          completed_net_pnl=str(row['completed_net_pnl']) if row['completed_net_pnl'] is not None else None) for day,row in sorted(daily.items())]
            return dict(portfolio=portfolio, lanes=lanes, positions=positions, history=history, daily=daily,
                        system=system, mode=self.mode, state=portfolio['state'])
