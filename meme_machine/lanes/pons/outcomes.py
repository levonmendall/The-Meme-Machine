"""Immutable enrollment and forward executable outcomes; missing exits stay missing."""
from . import BoundaryError
from .evidence import digest
import re

HORIZONS = (15, 60, 300, 900)
TAILS = (1500, 2500, 5000, 10000, -1000)


class Outcomes:
    def __init__(self, store):
        self.store = store

    def enroll(self, identity, *, features, selected_at, entry_cost, tokens,
               cohort, kind, origin, max_gap=5):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,64}', identity):
            raise BoundaryError('invalid_sample_identity')
        if features['asof'] != selected_at or entry_cost <= 0 or tokens <= 0 or max_gap <= 0:
            raise BoundaryError('invalid_enrollment')
        if cohort not in ('natural_unbiased', 'prioritized_research', 'active_paper'):
            raise BoundaryError('unknown_cohort')
        if kind not in ('natural', 'captured', 'synthetic'):
            raise BoundaryError('unknown_evidence_kind')
        if features['state_stamp']['kind'] != kind or features['origin'] != origin:
            raise BoundaryError('enrollment_provenance_mismatch')
        # Enrollment includes frozen policy-free observations; outcome APIs cannot change it.
        self.store.put('enrollment', identity, dict(features=features, selected_at=selected_at,
            entry_cost=entry_cost, tokens=tokens, cohort=cohort, kind=kind, origin=origin,
            horizons=list(HORIZONS), max_gap=max_gap, features_hash=digest(features)))

    def observe(self, identity, *, at, observed_at, market, tokens, net_exit_value,
                reason=None, graduation=False, liquidity_collapse=False):
        e = self.store.get('enrollment', identity)
        if at < e['selected_at'] or observed_at < at or tokens != e['tokens']:
            raise BoundaryError('invalid_forward_observation')
        if at > e['selected_at'] + max(HORIZONS) + e['max_gap']:
            raise BoundaryError('outcome_retention_horizon')
        if net_exit_value is None and not reason:
            raise BoundaryError('missing_exit_reason')
        if net_exit_value is not None and (net_exit_value < 0 or reason is not None):
            raise BoundaryError('invalid_executable_exit')
        self.store.put('outcome_tick', f'{identity}:{at}', dict(at=at, observed_at=observed_at,
            market=market, net_exit_value=net_exit_value, reason=reason,
            graduation=graduation, liquidity_collapse=liquidity_collapse))

    def finish(self, identity, horizon, *, now):
        e = self.store.get('enrollment', identity)
        if horizon not in e['horizons'] or now < e['selected_at'] + horizon:
            raise BoundaryError('forward_horizon_not_due')
        start, due = e['selected_at'], e['selected_at'] + horizon
        ticks = []
        for row in self.store.db.execute('SELECT body FROM records WHERE category=? AND id LIKE ?',
                                         ('outcome_tick', identity + ':%')):
            import json
            tick = json.loads(row[0])
            if start <= tick['at'] <= due and tick['observed_at'] <= now:
                ticks.append(tick)
        ticks.sort(key=lambda x: x['at'])
        times = [start] + [x['at'] for x in ticks] + [due]
        complete = bool(ticks) and max(b-a for a,b in zip(times,times[1:])) <= e['max_gap']
        terminal = ticks[-1] if ticks and ticks[-1]['at'] == due else None
        returns = [x['net_exit_value']*10000//e['entry_cost']-10000 for x in ticks if x['net_exit_value'] is not None]
        unresolved = any(x['net_exit_value'] is None for x in ticks)
        result = dict(identity=identity, horizon=horizon, selected_at=start, due=due,
            complete_path=complete and not unresolved, status='complete' if complete and terminal and not unresolved else 'incomplete',
            return_bps=(terminal['net_exit_value']*10000//e['entry_cost']-10000)
                if terminal and terminal['net_exit_value'] is not None else None,
            observed_mfe_bps=max(returns) if returns else None,
            observed_mae_bps=min(returns) if returns else None,
            # These are sampled-path hits, not claims about unobserved intra-block maxima.
            sampled_tail_hits={str(t): (any(r >= t for r in returns) if t > 0 else any(r <= t for r in returns))
                               if complete and not unresolved else None for t in TAILS},
            impossible_exit=any(x['reason'] == 'impossible_full_position_exit' for x in ticks),
            liquidity_collapse=any(x['liquidity_collapse'] for x in ticks),
            graduation=any(x['graduation'] for x in ticks), cohort=e['cohort'], kind=e['kind'], origin=e['origin'])
        self.store.put('outcome', f'{identity}:{horizon}', result)
        return result


def summarize(outcomes):
    """Never pool V1/V2 or natural/prioritized/synthetic denominators."""
    groups = {}
    for row in outcomes:
        key = (row['origin'], row['cohort'], row['kind'], row['horizon'])
        g = groups.setdefault(key, dict(enrolled=0, incomplete=0, complete=0,
                                       hits={str(t): 0 for t in TAILS}))
        g['enrolled'] += 1
        if row['status'] != 'complete':
            g['incomplete'] += 1
        else:
            g['complete'] += 1
            for tail, hit in row['sampled_tail_hits'].items():
                g['hits'][tail] += int(hit)
    for g in groups.values():
        g['complete_case_tail_probabilities'] = {t: n/g['complete'] if g['complete'] else None for t,n in g['hits'].items()}
        g['missing_outcomes_retained_in_enrollment_denominator'] = True
    return groups
