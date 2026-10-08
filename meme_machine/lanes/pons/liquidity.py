"""Exact normalized-bin conformance harness; NOT a verified Ramses simulator.

Ramses raw events, share mint/burn rounding, dynamic fees, fee-only behavior, token
ordering and fee claiming must be reconstructed before a live adapter is enabled.
This harness tests range accounting on explicit synthetic before/after states.
"""
from dataclasses import asdict, dataclass
from fractions import Fraction
from typing import Protocol

from . import BoundaryError
from .evidence import Stamp, digest


@dataclass(frozen=True)
class Bin:
    id: int
    x: int
    y: int
    shares: int
    price_num: int
    price_den: int

    def value(self):
        if min(self.x, self.y, self.shares) < 0 or min(self.price_num, self.price_den) <= 0:
            raise BoundaryError('invalid_bin_state')
        if self.shares == 0 and self.x + self.y:
            raise BoundaryError('missing_share_supply')
        return Fraction(self.x*self.price_num, self.price_den) + self.y


@dataclass(frozen=True)
class BinDelta:
    at: int
    observed_at: int
    bin_id: int
    before: Bin
    after: Bin
    kind: str
    volume_quote: int = 0
    lp_fee_quote: int = 0
    protocol_fee_quote: int = 0
    total_fee_quote: int = 0
    fee_rate_ppm: int = 0


def apply_delta(state, event):
    if event.kind not in ('swap', 'add', 'remove', 'claim'):
        raise BoundaryError('unsupported_mutation')
    if event.at > event.observed_at or event.bin_id != event.before.id or event.bin_id != event.after.id:
        raise BoundaryError('exact_bin_identity_mismatch')
    if state.get(event.bin_id) != event.before:
        raise BoundaryError('bin_replay_gap_or_conflict')
    event.before.value()
    event.after.value()
    if min(event.volume_quote, event.lp_fee_quote, event.protocol_fee_quote, event.total_fee_quote, event.fee_rate_ppm) < 0:
        raise BoundaryError('negative_bin_accounting')
    if event.total_fee_quote != event.lp_fee_quote + event.protocol_fee_quote:
        raise BoundaryError('fee_conservation_failure')
    if event.kind in ('swap','claim') and event.before.shares != event.after.shares:
        raise BoundaryError('swap_or_claim_share_supply_changed')
    if event.kind != 'swap' and any((event.volume_quote,event.lp_fee_quote,event.protocol_fee_quote,event.total_fee_quote)):
        raise BoundaryError('nonswap_fee_or_volume')
    if event.kind == 'swap' and event.total_fee_quote != event.volume_quote*event.fee_rate_ppm//1000000:
        raise BoundaryError('normalized_variable_fee_mismatch')
    if event.kind == 'add' and (event.after.shares <= event.before.shares or event.after.x < event.before.x or event.after.y < event.before.y):
        raise BoundaryError('invalid_add_liquidity')
    if event.kind == 'remove' and (event.after.shares >= event.before.shares or event.after.x > event.before.x or event.after.y > event.before.y):
        raise BoundaryError('invalid_remove_liquidity')
    state[event.bin_id] = event.after


def case60(*, bins, proposed, warmup, asof, warmup_start, capital, costs,
           inventory_risk_reserve, stamp, hurdle_bps=35):
    stamp.check(asof)
    if stamp.kind != 'synthetic':
        raise BoundaryError('ramses_mechanics_unverified')
    if hurdle_bps < 35:
        raise BoundaryError('cost_hurdle_may_not_be_weakened')
    if not 1 <= len(proposed) <= 64 or len(set(proposed)) != len(proposed) or len(bins) != len({b.id for b in bins}):
        raise BoundaryError('invalid_range_bins')
    if capital <= 0 or costs < 0 or inventory_risk_reserve < 0 or warmup_start >= asof:
        raise BoundaryError('invalid_range_economics')
    indexed = {b.id: b for b in bins}
    if any(i not in indexed for i in proposed):
        raise BoundaryError('missing_range_bin')
    if len(warmup) > 10000:
        raise BoundaryError('range_event_capacity')
    if any(e.observed_at > asof or e.at > asof or e.at < warmup_start for e in warmup):
        raise BoundaryError('future_or_outside_warmup')
    if sorted(e.at for e in warmup) != [e.at for e in warmup]:
        raise BoundaryError('unordered_warmup')
    replay = {}
    for e in warmup:
        if e.bin_id not in replay:
            replay[e.bin_id] = e.before
        apply_delta(replay, e)
    if any(indexed.get(i) != b for i, b in replay.items()):
        raise BoundaryError('warmup_snapshot_mismatch')
    liquidity = sum((indexed[i].value() for i in proposed), Fraction(0))
    if liquidity <= 0:
        raise BoundaryError('empty_range')
    # Equal quote-value capital per bin; minting/dilution is a projection, not an exact
    # counterfactual execution. Range policy stays frozen before future data arrives.
    per_bin = Fraction(capital, len(proposed))
    shares = {i: per_bin/(indexed[i].value()+per_bin) for i in proposed}
    range_events = [e for e in warmup if e.bin_id in proposed and e.kind == 'swap']
    near = set(proposed) | {i-1 for i in proposed} | {i+1 for i in proposed}
    projected = sum((e.lp_fee_quote*shares[e.bin_id] for e in range_events), Fraction(0))*60/(asof-warmup_start)
    net = projected-costs-inventory_risk_reserve
    return dict(kind='synthetic', asof=asof, horizon=60, proposed=list(proposed), capital=capital,
                range_liquidity=float(liquidity), range_volume=sum(e.volume_quote for e in range_events),
                near_range_volume=sum(e.volume_quote for e in warmup if e.bin_id in near and e.kind == 'swap'),
                lp_fees=sum(e.lp_fee_quote for e in range_events),
                capital_shares={str(i):float(s) for i,s in shares.items()},
                projected_fees=float(projected), costs=costs, inventory_risk_reserve=inventory_risk_reserve,
                projected_net=float(net), hurdle_bps=hurdle_bps,
                economic_case=net*10000 >= capital*hurdle_bps,
                allocation_authority=False, model='explicit_fee_capture_projection_not_exact_ramses',
                pre_entry_hash=digest([asdict(b) for b in bins]),
                unavailable=['verified_variable_fee_formula', 'exact_counterfactual_share_minting',
                             'adverse_selection_forecast', 'directional_imbalance', 'net_bin_drift'])


def replay60(*, case, initial, events, owned_shares, liquidation, now):
    """Mechanical accounting of supplied synthetic LP shares, not autonomous allocation.

    Residual inventory must have an explicit full-size executable liquidation quote.
    Final rows cannot be retrospectively substituted for the pre-entry proposal.
    """
    if case['kind'] != 'synthetic':
        raise BoundaryError('ramses_mechanics_unverified')
    if now < case['asof']+60 or digest([asdict(b) for b in initial]) != case['pre_entry_hash']:
        raise BoundaryError('outcome_horizon_or_snapshot_mismatch')
    if len(events) > 10000 or sorted(e.at for e in events) != [e.at for e in events]:
        raise BoundaryError('outcome_event_capacity_or_order')
    state = {b.id:b for b in initial}
    if len(state) != len(initial) or set(owned_shares) != set(case['proposed']):
        raise BoundaryError('position_range_mismatch')
    if any(s < 0 or s > state[i].shares for i,s in owned_shares.items()):
        raise BoundaryError('invalid_lp_shares')
    fees, touched = Fraction(0), set()
    for e in events:
        if not case['asof'] < e.at <= case['asof']+60 or e.observed_at > now:
            raise BoundaryError('outside_forward_window')
        if e.bin_id in owned_shares:
            if e.before.shares < owned_shares[e.bin_id] or e.after.shares < owned_shares[e.bin_id]:
                raise BoundaryError('lp_share_conservation')
            if e.kind == 'swap':
                touched.add(e.bin_id)
                fees += Fraction(e.lp_fee_quote*owned_shares[e.bin_id], e.before.shares)
        apply_delta(state, e)
    x = sum(state[i].x*s//state[i].shares for i,s in owned_shares.items() if s)
    y = sum(state[i].y*s//state[i].shares for i,s in owned_shares.items() if s)
    if liquidation is None:
        return dict(status='unresolved', reason='inventory_liquidation_unavailable', residual_x=x, residual_y=y)
    if liquidation['amount_x'] != x or liquidation['at'] != case['asof']+60 or liquidation['net_quote'] < 0:
        raise BoundaryError('liquidation_identity_mismatch')
    terminal = y+liquidation['net_quote']+fees
    return dict(status='synthetic_complete', horizon=60, fee_income=float(fees),
                touched_bins=sorted(touched), residual_x=x, residual_y=y,
                net_result=float(terminal-case['capital']-case['costs']),
                evidence_kind='synthetic', profitability_evidence=False,
                coverage='supplied_tape_only_not_proof_of_mainnet_completeness')


class LiquidityAdapter(Protocol):
    def snapshot(self, pool: str, block: int) -> list[Bin]: ...
    def decode(self, event: dict) -> BinDelta: ...


class RamsesAdapter:
    allocation_authority = False

    def snapshot(self, pool, block):
        raise BoundaryError('ramses_deployment_abi_fee_bin_share_accounting_unverified')

    def decode(self, event):
        raise BoundaryError('ramses_unsupported_raw_mutation')
