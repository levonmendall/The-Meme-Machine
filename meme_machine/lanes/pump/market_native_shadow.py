"""Research-only market-native candidate discovery with zero trading authority.

This module does not alter continuation-v1. It nominates mints from finalized Pump
activity without consulting a wallet watchlist. A real buy event is retained only as
an immutable nomination anchor because unchanged Engine.qualify requires one; wallet
identity is not used to decide whether a mint is discovered or ranked.
"""
from collections import defaultdict

from .engine import MAYHEM_AGENT_WALLET, SIGNAL_WINDOW

# Universal discovery is intentionally broader than qualification.  The former
# three-event/three-wallet values remain promotion context only; they are never a
# discovery cutoff.
PROMOTION_WINDOW_EVENTS = 3
PROMOTION_DISTINCT_NON_SYSTEM_WALLETS = 3
# Compatibility names for diagnostics/importers. They are promotion context only.
MIN_WINDOW_EVENTS = PROMOTION_WINDOW_EVENTS
MIN_DISTINCT_NON_SYSTEM_WALLETS = PROMOTION_DISTINCT_NON_SYSTEM_WALLETS
TRIGGER_LABEL = 'fresh_non_system_buy'
REACTIVATION_LABEL = 'fresh_non_system_buy_reactivation'


def discover_market_native(fresh_events, tape, now, already_discovered):
    """Return every mint with fresh finalized non-system buy activity.

    Discovery is deliberately a superset of the trading strategy.  A mint that was
    weak on its first sighting is returned again on later activity so the scheduler
    can detect reactivation.  No price, liquidity, concentration, wallet-skill or
    strategy threshold can suppress market awareness.
    """
    grouped = defaultdict(list)
    for event in fresh_events:
        if event.get('type', 'trade') == 'trade':
            grouped[event['mint']].append(event)

    discovered = []
    for mint, recent in sorted(
        grouped.items(),
        key=lambda item: min((e['market_time'], e['id']) for e in item[1]),
    ):
        fresh_buys = [
            e for e in recent
            if e.get('buy') and e.get('wallet') != MAYHEM_AGENT_WALLET
            and 0 <= int(now) - int(e['market_time']) <= SIGNAL_WINDOW
        ]
        if not fresh_buys:
            continue
        window = tape.window(mint, now)
        non_system_wallets = {
            e['wallet'] for e in window
            if e.get('wallet') and e.get('wallet') != MAYHEM_AGENT_WALLET
        }
        first_discovery = mint not in already_discovered
        anchor = min(fresh_buys, key=lambda e: (e['market_time'], e['id']))
        discovered.append(dict(
            mint=mint,
            discovery_time=int(now),
            nomination=dict(anchor),
            trigger=TRIGGER_LABEL if first_discovery else REACTIVATION_LABEL,
            first_discovery=first_discovery,
            promotion_context_ready=(
                len(window) >= PROMOTION_WINDOW_EVENTS and
                len(non_system_wallets) >= PROMOTION_DISTINCT_NON_SYSTEM_WALLETS
            ),
            window_events=len(window),
            distinct_non_system_wallets=len(non_system_wallets),
            first_window_market_time=min(int(e['market_time']) for e in window),
        ))
    return discovered

def classify_buckets(scout_mints, market_mints, observed_mints):
    scout = set(scout_mints)
    market = set(market_mints)
    observed = set(observed_mints)
    return dict(
        scout_only=sorted(scout-market),
        market_native_only=sorted(market-scout),
        both=sorted(scout & market),
        neither_pending_retrospective_review=sorted(observed-(scout | market)),
    )
