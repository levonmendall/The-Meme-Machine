"""Research-only economic shadow ranking for Pump continuation candidates.

The active continuation-v1 prioritizer is intentionally unchanged. This module uses
only finalized point-in-time Pump events already available at the decision timestamp
and produces a second, non-authoritative ordering for outcome research.

It is not an expected-return model yet. The purpose is to accumulate unbiased forward
labels that can later show whether flow acceleration, buyer breadth, sell pressure and
price extension contain incremental economic information beyond policy-feasibility
ranking.
"""
from __future__ import annotations

from .engine import MAYHEM_AGENT_WALLET
from .outcome_research import price_parts, return_bps


def _window(events, now, seconds):
    floor = int(now) - int(seconds)
    return [e for e in events if floor <= int(e.get("market_time", 0)) <= int(now)]


def _stats(events):
    buy = [e for e in events if e.get("buy")]
    sell = [e for e in events if not e.get("buy")]
    buy_lamports = sum(int(e.get("amount", 0)) for e in buy)
    sell_lamports = sum(int(e.get("amount", 0)) for e in sell)
    total = buy_lamports + sell_lamports
    return dict(
        events=len(events),
        buys=len(buy),
        sells=len(sell),
        unique_buyers=len({e.get("wallet") for e in buy if e.get("wallet")}),
        unique_sellers=len({e.get("wallet") for e in sell if e.get("wallet")}),
        gross_buy_lamports=buy_lamports,
        gross_sell_lamports=sell_lamports,
        net_buy_lamports=buy_lamports - sell_lamports,
        buy_share_bps=(0 if total <= 0 else buy_lamports * 10_000 // total),
        sell_pressure_bps=(0 if total <= 0 else sell_lamports * 10_000 // total),
    )


def continuation_economic_features(candidate, tape, now):
    nomination = candidate["nomination"]
    anchor = nomination["wallet"]
    events = []
    for event in tape.window(candidate["mint"], int(now)):
        wallet = event.get("wallet")
        if wallet in (anchor, MAYHEM_AGENT_WALLET):
            continue
        try:
            if int(event.get("amount", 0)) <= 0 or int(event.get("tokens", 0)) <= 0:
                continue
            if int(event.get("market_time", 0)) > int(now):
                continue
        except (TypeError, ValueError):
            continue
        events.append(event)
    events.sort(key=lambda e: (
        int(e.get("market_time", 0)), int(e.get("slot", 0)), int(e.get("index", 0))
    ))

    w10 = _stats(_window(events, now, 10))
    w30 = _stats(_window(events, now, 30))
    w60 = _stats(_window(events, now, 60))
    prior20_net = w30["net_buy_lamports"] - w10["net_buy_lamports"]
    flow_acceleration = (
        w10["net_buy_lamports"] // 10
        - prior20_net // 20
    )

    recent_buyers = {
        e.get("wallet") for e in _window(events, now, 10)
        if e.get("buy") and e.get("wallet")
    }
    prior_buyers = {
        e.get("wallet") for e in events
        if int(now) - 30 <= int(e.get("market_time", 0)) < int(now) - 10
        and e.get("buy") and e.get("wallet")
    }
    buyer_acceleration = len(recent_buyers) - len(prior_buyers)

    price_change_bps = None
    if len(events) >= 2:
        try:
            first_num, first_den = price_parts(events[0])
            last_num, last_den = price_parts(events[-1])
            price_change_bps = return_bps(
                first_num, first_den, last_num, last_den
            )
        except ValueError:
            pass

    return dict(
        research_only=True,
        order_authority=False,
        future_outcomes_used=False,
        model="continuation_economic_shadow_v1",
        mint=candidate["mint"],
        nomination_id=nomination["id"],
        observed_at=int(now),
        window_10s=w10,
        window_30s=w30,
        window_60s=w60,
        flow_acceleration_lamports_per_second=int(flow_acceleration),
        buyer_acceleration=int(buyer_acceleration),
        price_change_bps=price_change_bps,
        positive_extension_bps=max(0, int(price_change_bps or 0)),
    )


def economic_priority_key(features):
    """Smaller is better. This is a transparent shadow ordering, not an alpha score."""
    w10 = features["window_10s"]
    return (
        -int(w10["net_buy_lamports"]),
        -int(w10["unique_buyers"]),
        -int(features["flow_acceleration_lamports_per_second"]),
        -int(features["buyer_acceleration"]),
        int(w10["sell_pressure_bps"]),
        int(features["positive_extension_bps"]),
        str(features["mint"]),
    )


def choose_economic_shadow(rows, tape, now):
    """Choose one point-in-time economic shadow candidate without trading authority."""
    enriched = []
    for candidate, metric in rows:
        if not getattr(metric, "possible", False):
            continue
        features = continuation_economic_features(candidate, tape, now)
        enriched.append((candidate, metric, features))
    if not enriched:
        return None
    return min(enriched, key=lambda row: economic_priority_key(row[2]))
