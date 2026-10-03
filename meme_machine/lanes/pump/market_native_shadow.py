"""Research-only market-native candidate discovery with zero trading authority.

This module does not alter continuation-v1. It nominates mints from finalized Pump
activity without consulting a wallet watchlist. A real buy event is retained only as
an immutable nomination anchor because unchanged Engine.qualify requires one; wallet
identity is not used to decide whether a mint is discovered or ranked.
"""
from collections import defaultdict

from .engine import MAYHEM_AGENT_WALLET, SIGNAL_WINDOW

# Broad acquisition hygiene only; deliberately not optimized from outcomes.
MIN_WINDOW_EVENTS = 3
MIN_DISTINCT_NON_SYSTEM_WALLETS = 3
TRIGGER_LABEL = 'fresh_buy+3_window_events+3_distinct_non_system_wallets'


def discover_market_native(fresh_events, tape, now, already_discovered):
    """Return newly discovered mints from observable market activity only.

    Discovery requires a fresh finalized buy plus a minimally populated 60-second
    window. No named wallet, skill score, watchlist membership, price move, liquidity,
    concentration, or outcome-derived threshold is consulted here.
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
        if mint in already_discovered:
            continue
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
        if len(window) < MIN_WINDOW_EVENTS:
            continue
        if len(non_system_wallets) < MIN_DISTINCT_NON_SYSTEM_WALLETS:
            continue

        # Deterministic real-event anchor only. Selection above never used wallet
        # identity, profitability, liquidity, price, or any strategy gate.
        anchor = min(fresh_buys, key=lambda e: (e['market_time'], e['id']))
        discovered.append(dict(
            mint=mint,
            discovery_time=int(now),
            nomination=dict(anchor),
            trigger=TRIGGER_LABEL,
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
