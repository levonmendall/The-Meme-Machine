"""Point-in-time descriptive features, never a copied Solana qualification policy."""
from dataclasses import asdict, dataclass
from fractions import Fraction

from . import BoundaryError
from .evidence import Stamp, digest


def ratio(a, b):
    return float(Fraction(a, b)) if b else None


@dataclass(frozen=True)
class Trade:
    identity: str
    market: str
    participant: str
    side: str
    quote: int
    tokens: int
    stamp: Stamp


def features(*, market, origin, asof, launch_at, coverage_start, coverage_end,
             trades, liquidity, previous_liquidity, full_exit_depth,
             entry_cost, round_trip_cost, state_stamp, creator_behavior=None, concentration=None,
             lp_additions=None, lp_removals=None, slippage_bps=None, gas_quote=None,
             graduation_state=None, pregraduation_source=None):
    state_stamp.check(asof, 5)
    if coverage_start > asof-120 or coverage_end < asof or launch_at > asof:
        raise BoundaryError('incomplete_feature_coverage')
    if len(trades) > 10000:
        raise BoundaryError('feature_event_capacity')
    if any(x is None or x < 0 for x in (liquidity, previous_liquidity, full_exit_depth, entry_cost, round_trip_cost)):
        raise BoundaryError('missing_economic_state')
    seen = {}
    for t in trades:
        t.stamp.check(asof, 120)
        if t.market != market or t.side not in ('buy', 'sell') or t.quote <= 0 or t.tokens <= 0:
            raise BoundaryError('invalid_trade_evidence')
        if t.identity in seen and seen[t.identity] != t:
            raise BoundaryError('conflicting_trade')
        seen[t.identity] = t
        if t.stamp.kind != state_stamp.kind:
            raise BoundaryError('mixed_evidence_kind')
    rows = sorted(seen.values(), key=lambda t: (t.stamp.event_at, t.identity))
    if len({t.stamp.kind for t in rows}) > 1:
        raise BoundaryError('mixed_evidence_kind')

    def window(start, end):
        selected = [t for t in rows if start < t.stamp.event_at <= end]
        buys, sells = [t for t in selected if t.side == 'buy'], [t for t in selected if t.side == 'sell']
        gross_buy, gross_sell = sum(t.quote for t in buys), sum(t.quote for t in sells)
        return dict(gross_buy=gross_buy, gross_sell=gross_sell, net_buy=gross_buy-gross_sell,
                    unique_buyers=len({t.participant for t in buys}),
                    unique_sellers=len({t.participant for t in sells}), transactions=len(selected),
                    sell_pressure=ratio(gross_sell, gross_buy+gross_sell))

    windows = {}
    for seconds in (5, 10, 30, 60):
        current = window(asof-seconds, asof)
        prior = window(asof-2*seconds, asof-seconds)
        current.update(buyer_acceleration=current['unique_buyers']-prior['unique_buyers'],
                       net_flow_acceleration=current['net_buy']-prior['net_buy'],
                       transaction_acceleration=current['transactions']-prior['transactions'])
        # Include last price at or before window start; never a later surrogate.
        anchor = [t for t in rows if t.stamp.event_at <= asof-seconds]
        current['price_change'] = float(Fraction(rows[-1].quote*anchor[-1].tokens,
                                                rows[-1].tokens*anchor[-1].quote)-1) if anchor and rows else None
        windows[str(seconds)] = current
    extension = float(Fraction(rows[-1].quote*rows[0].tokens, rows[-1].tokens*rows[0].quote)-1) if rows else None
    value = dict(market=market, origin=origin, asof=asof, age_seconds=asof-launch_at,
                 windows=windows, liquidity=liquidity, liquidity_change=liquidity-previous_liquidity,
                 executable_full_exit_depth=full_exit_depth, entry_cost=entry_cost,
                 round_trip_cost=round_trip_cost, observed_window_extension=extension,
                 creator_behavior=creator_behavior, participant_concentration=concentration,
                 lp_additions=lp_additions, lp_removals=lp_removals,
                 slippage_bps=slippage_bps, gas_quote=gas_quote, state_stamp=asdict(state_stamp),
                 graduation_state=graduation_state, pregraduation_source=pregraduation_source,
                 participant_semantics='observed_addresses_not_independent_wallets',
                 unavailable_features=[name for name, v in [('creator_behavior', creator_behavior),
                     ('concentration', concentration), ('lp_additions', lp_additions),
                     ('lp_removals', lp_removals), ('slippage_bps', slippage_bps),
                     ('gas_quote', gas_quote)] if v is None],
                 trade_evidence_hash=digest([asdict(t) for t in rows]),
                 authority='research_only', qualification='policy_not_established')
    return value
