"""Research-only qualification attribution for the frozen continuation-v1 policy.

Nothing in this module grants order authority.  Engine.qualify remains the canonical
entry decision.  These helpers expose the contemporaneous values behind every gate and
answer counterfactual questions without changing any production threshold.
"""
from collections import Counter

from . import pump
from .engine import GAS, MAYHEM_AGENT_WALLET, SIGNAL_WINDOW
from .store import digest

CURRENT_THRESHOLDS = dict(
    max_concentration_bps=3500,
    min_real_sol_lamports=10_000_000_000,
    max_evidence_events=100,
    min_independent_groups=3,
    min_net_buy_lamports=1_000_000_000,
    max_price_extension_bps=12_000,
    max_roundtrip_loss_bps=500,
)

# Analysis-only neighborhoods.  Inclusion here never changes Engine.qualify and never
# authorizes a paper reservation.  The current value is always included explicitly.
SENSITIVITY_GRID = dict(
    max_concentration_bps=[3000, 3500, 4000, 4500],
    min_real_sol_lamports=[5_000_000_000, 7_500_000_000, 10_000_000_000, 12_500_000_000],
    max_evidence_events=[75, 100, 125, 150],
    min_independent_groups=[2, 3, 4],
    min_net_buy_lamports=[500_000_000, 1_000_000_000, 1_500_000_000],
    max_price_extension_bps=[11_000, 12_000, 13_000],
    max_roundtrip_loss_bps=[300, 500, 700],
)


def _ordered_add(rows, value):
    if value and value not in rows:
        rows.append(value)


def qualification_vector(engine, nomination, evidence, now):
    """Return all measurable gate values while preserving Engine.qualify authority."""
    vector = dict(
        policy='continuation-v1',
        authority='research_only',
        thresholds=dict(CURRENT_THRESHOLDS),
        actual_reason=None,
        evaluation_error=None,
        all_rejections=[],
        margins={},
    )
    try:
        actual_reason = engine.qualify(nomination, evidence, now)
    except (ValueError, KeyError, TypeError) as exc:
        actual_reason = 'unavailable_executable_evidence'
        vector['evaluation_error'] = str(exc) or type(exc).__name__
    vector['actual_reason'] = actual_reason

    snap = evidence.get('snapshot') or {}
    try:
        c, rates = engine.validate_snapshot(snap, now)
    except (ValueError, KeyError, TypeError) as exc:
        vector.update(snapshot_valid=False,
                      snapshot_error=str(exc) or type(exc).__name__,
                      current_threshold_pass=False)
        _ordered_add(vector['all_rejections'], actual_reason)
        vector['sensitivity'] = sensitivity(vector)
        return vector

    vector.update(
        snapshot_valid=True,
        snapshot_error=None,
        nomination_valid=bool(nomination.get('mint') == snap.get('mint') and
                              nomination.get('wallet') in engine.seeds),
        signal_age_seconds=(now-int(nomination.get('market_time', now))),
        signal_fresh=False,
        market_window_covered=bool(evidence.get('covered')),
        concentration_bps=evidence.get('concentration_bps'),
        curve_complete=bool(c.complete),
        real_sol_lamports=int(c.real_sol),
        evidence_event_count=len(evidence.get('events') or []),
        mayhem_mode=bool(pump.curve_mode(snap['accounts'][0])['mayhem']),
        quote_age_seconds=now-int(snap['market_time']),
        market_events_valid=True,
        market_event_error=None,
        independent_buyer_groups=None,
        independent_net_buy_lamports=None,
        price_extension_bps=None,
        roundtrip_loss_bps=None,
        roundtrip_loss_lamports=None,
        allocator_reason=None,
    )
    vector['signal_fresh'] = bool(
        nomination.get('market_time') is not None and
        nomination.get('available_time') is not None and
        nomination['market_time'] <= nomination['available_time'] <= now and
        now-nomination['market_time'] <= SIGNAL_WINDOW)

    failures = vector['all_rejections']
    if not vector['nomination_valid']:
        _ordered_add(failures, 'invalid_nomination')
    if not vector['signal_fresh']:
        _ordered_add(failures, 'stale_signal')
    if not vector['market_window_covered']:
        _ordered_add(failures, 'incomplete_market_window')
    if vector['concentration_bps'] is None:
        _ordered_add(failures, 'missing_concentration')
    elif int(vector['concentration_bps']) > CURRENT_THRESHOLDS['max_concentration_bps']:
        _ordered_add(failures, 'concentration')
    if vector['curve_complete'] or vector['real_sol_lamports'] < CURRENT_THRESHOLDS['min_real_sol_lamports']:
        _ordered_add(failures, 'exit_liquidity')
    if vector['evidence_event_count'] > CURRENT_THRESHOLDS['max_evidence_events']:
        _ordered_add(failures, 'evidence_capacity')

    excluded = {engine.group(nomination.get('wallet')), engine.group(c.creator)}
    if vector['mayhem_mode']:
        excluded.add(engine.group(MAYHEM_AGENT_WALLET))
    participants = set()
    net = 0
    seen = {}
    for event in evidence.get('events') or []:
        try:
            event_id = event['id']
            event_hash = digest(event)
            if event_id in seen:
                if seen[event_id] != event_hash:
                    vector['market_events_valid'] = False
                    vector['market_event_error'] = 'conflicting_market_event'
                    _ordered_add(failures, 'conflicting_market_event')
                    break
                continue
            seen[event_id] = event_hash
            if event['amount'] <= 0 or event['tokens'] <= 0:
                vector['market_events_valid'] = False
                vector['market_event_error'] = 'invalid_trade_amount'
                _ordered_add(failures, 'invalid_trade_amount')
                break
            if (event['mint'] != snap['mint'] or
                    not now-SIGNAL_WINDOW <= event['market_time'] <= event['available_time'] <= now or
                    event['slot'] > snap['slot']):
                vector['market_events_valid'] = False
                vector['market_event_error'] = 'invalid_market_window'
                _ordered_add(failures, 'invalid_market_window')
                break
            if engine.group(event['wallet']) in excluded:
                continue
            net += int(event['amount']) * (1 if event['buy'] else -1)
            if event['buy']:
                participants.add(engine.group(event['wallet']))
        except (KeyError, TypeError, ValueError):
            vector['market_events_valid'] = False
            vector['market_event_error'] = 'invalid_market_window'
            _ordered_add(failures, 'invalid_market_window')
            break

    if vector['market_events_valid']:
        vector['independent_buyer_groups'] = len(participants)
        vector['independent_net_buy_lamports'] = net
        if (len(participants) < CURRENT_THRESHOLDS['min_independent_groups'] or
                net < CURRENT_THRESHOLDS['min_net_buy_lamports']):
            _ordered_add(failures, 'independent_demand')

    try:
        if int(nomination.get('tokens', 0)) > 0 and int(nomination.get('amount', 0)) > 0:
            denominator = int(c.token) * int(nomination['amount'])
            vector['price_extension_bps'] = pump.ceildiv(
                int(c.sol) * int(nomination['tokens']) * 10_000, denominator)
            if vector['price_extension_bps'] > CURRENT_THRESHOLDS['max_price_extension_bps']:
                _ordered_add(failures, 'extended_price')
        else:
            _ordered_add(failures, 'extended_price')
    except (TypeError, ValueError, ZeroDivisionError):
        _ordered_add(failures, 'extended_price')

    amount = engine.store.state['initial']//20
    try:
        tokens, cost, _ = pump.buy(c, amount, rates)
        proceeds, _ = pump.sell(c, tokens, rates)
        loss = int(cost) + 2*GAS - int(proceeds)
        vector['roundtrip_loss_lamports'] = loss
        vector['roundtrip_loss_bps'] = pump.ceildiv(max(0, loss)*10_000, int(cost))
        if loss*10_000 > int(cost)*CURRENT_THRESHOLDS['max_roundtrip_loss_bps']:
            _ordered_add(failures, 'roundtrip_cost')
    except (ValueError, KeyError, TypeError, ZeroDivisionError):
        vector['roundtrip_loss_bps'] = None

    try:
        vector['allocator_reason'] = engine.allocator.allowed(
            'spot', amount, snap['mint'], engine.group(c.creator), now)
    except (ValueError, KeyError, TypeError):
        vector['allocator_reason'] = 'allocator_unavailable'
    _ordered_add(failures, vector['allocator_reason'])

    vector['margins'] = dict(
        concentration_bps=(None if vector['concentration_bps'] is None else
                           CURRENT_THRESHOLDS['max_concentration_bps']-int(vector['concentration_bps'])),
        real_sol_lamports=vector['real_sol_lamports']-CURRENT_THRESHOLDS['min_real_sol_lamports'],
        evidence_events=CURRENT_THRESHOLDS['max_evidence_events']-vector['evidence_event_count'],
        independent_groups=(None if vector['independent_buyer_groups'] is None else
                            vector['independent_buyer_groups']-CURRENT_THRESHOLDS['min_independent_groups']),
        net_buy_lamports=(None if vector['independent_net_buy_lamports'] is None else
                          vector['independent_net_buy_lamports']-CURRENT_THRESHOLDS['min_net_buy_lamports']),
        price_extension_bps=(None if vector['price_extension_bps'] is None else
                             CURRENT_THRESHOLDS['max_price_extension_bps']-vector['price_extension_bps']),
        roundtrip_loss_bps=(None if vector['roundtrip_loss_bps'] is None else
                            CURRENT_THRESHOLDS['max_roundtrip_loss_bps']-vector['roundtrip_loss_bps']),
    )
    if actual_reason != 'qualified':
        _ordered_add(failures, actual_reason)
    vector['current_threshold_pass'] = _passes_thresholds(vector, {})
    vector['sensitivity'] = sensitivity(vector)
    return vector


def _passes_thresholds(vector, overrides):
    """Counterfactual only; never used by Engine.consider or paper authority."""
    t = dict(CURRENT_THRESHOLDS)
    t.update(overrides)
    required = (
        vector.get('snapshot_valid'), vector.get('nomination_valid'), vector.get('signal_fresh'),
        vector.get('market_window_covered'), vector.get('concentration_bps') is not None,
        not vector.get('curve_complete', True), vector.get('market_events_valid'),
        vector.get('independent_buyer_groups') is not None,
        vector.get('independent_net_buy_lamports') is not None,
        vector.get('price_extension_bps') is not None,
        vector.get('roundtrip_loss_bps') is not None,
        vector.get('allocator_reason') is None,
    )
    if not all(required):
        return False
    return bool(
        int(vector['concentration_bps']) <= t['max_concentration_bps'] and
        int(vector['real_sol_lamports']) >= t['min_real_sol_lamports'] and
        int(vector['evidence_event_count']) <= t['max_evidence_events'] and
        int(vector['independent_buyer_groups']) >= t['min_independent_groups'] and
        int(vector['independent_net_buy_lamports']) >= t['min_net_buy_lamports'] and
        int(vector['price_extension_bps']) <= t['max_price_extension_bps'] and
        int(vector['roundtrip_loss_bps']) <= t['max_roundtrip_loss_bps'])


def sensitivity(vector):
    rows = {}
    for key, values in SENSITIVITY_GRID.items():
        rows[key] = {str(value): _passes_thresholds(vector, {key:value}) for value in values}
    return dict(kind='one_threshold_at_a_time', authority='research_only', values=rows)


def analyze_reports(reports, min_sample=50):
    """Aggregate natural vectors, deduplicating repeated observations by nomination id."""
    dedup = {}
    for report in reports:
        for row in report.get('results', []):
            vector = row.get('qualification_vector')
            nomination_id = row.get('nomination_id')
            if not vector or not nomination_id or row.get('evidence_stage') != 'complete':
                continue
            dedup.setdefault(nomination_id, vector)
    vectors = list(dedup.values())
    first = Counter(v.get('actual_reason') for v in vectors)
    all_rejections = Counter()
    sole = Counter()
    multi = 0
    for vector in vectors:
        rejects = [x for x in vector.get('all_rejections', []) if x and x != 'qualified']
        all_rejections.update(rejects)
        if len(rejects) == 1:
            sole[rejects[0]] += 1
        elif len(rejects) > 1:
            multi += 1

    sensitivity_counts = {}
    for key, values in SENSITIVITY_GRID.items():
        sensitivity_counts[key] = {}
        for value in values:
            passed = sum(_passes_thresholds(v, {key:value}) for v in vectors)
            pivotal = sum((not _passes_thresholds(v, {})) and _passes_thresholds(v, {key:value})
                          for v in vectors)
            sensitivity_counts[key][str(value)] = dict(pass_count=passed, pivotal_rejects=pivotal)

    return dict(
        kind='qualification_rejection_attribution',
        policy='continuation-v1',
        authority='research_only',
        unique_complete_nominations=len(vectors),
        minimum_sample=min_sample,
        sample_sufficient=len(vectors) >= min_sample,
        actual_reason_counts=dict(sorted(first.items())),
        all_rejection_counts=dict(sorted(all_rejections.items())),
        sole_rejection_counts=dict(sorted(sole.items())),
        multi_rejection_candidates=multi,
        current_qualified=sum(v.get('actual_reason') == 'qualified' for v in vectors),
        one_threshold_sensitivity=sensitivity_counts,
        decision='insufficient_sample_for_threshold_revision' if len(vectors) < min_sample else
                 'sample_ready_for_human_threshold_review',
    )
