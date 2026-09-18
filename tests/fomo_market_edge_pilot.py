"""Free market-data pilot for incremental FOMO timing value.

Research-only. Uses recent FomoAPI Solana feed events plus keyless GeckoTerminal
minute OHLCV. It never calls the Meme Machine strategy, Solana RPC, creates orders,
or changes qualification.

Design:
- take the first eligible FOMO feed BUY per unique Solana token in the recent feed;
- use the next full minute open as the actionable event entry (conservative);
- measure 5m/15m/60m forward returns and 60m MFE/MAE;
- for each token, choose an earlier non-FOMO control minute on the SAME TOKEN whose
  preceding 15m return is closest to the event's preceding 15m return;
- require the control's 60m outcome to finish before the FOMO event vicinity;
- compare event vs matched control with an exact paired sign-flip test.

This is an exploratory pilot, not strategy authority or profitability proof.
"""
from __future__ import annotations

import itertools
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

FOMO_BASE = "https://api.fomoapi.io"
GT_BASE = "https://api.geckoterminal.com/api/v2"
REPORT = Path("fomo-market-edge-pilot.json")
MAX_EVENTS = 12
MIN_EVENT_AGE_MINUTES = 75
MAX_EVENT_AGE_HOURS = 20
CONTROL_LOOKBACK_HOURS = 7
CONTROL_GAP_MINUTES = 90
FOMO_EXCLUSION_MINUTES = 15
HORIZONS = (5, 15, 60)


def _get_json(url, headers=None, attempts=4):
    headers = dict(headers or {})
    for attempt in range(attempts):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise RuntimeError("response_too_large")
                return int(r.status), dict(r.headers.items()), json.loads(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read(64_000)
            if exc.code == 429 and attempt + 1 < attempts:
                delay = float(exc.headers.get("Retry-After") or (7 + 3 * attempt))
                time.sleep(min(delay, 20))
                continue
            try:
                body = json.loads(raw)
            except Exception:
                body = {"error": raw.decode("utf-8", "replace")[:1000]}
            return int(exc.code), dict(exc.headers.items()), body
    raise RuntimeError("unreachable")


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _alerts_from_body(body):
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return []
    for key in ("alerts", "items", "events", "data"):
        value = body.get(key)
        if isinstance(value, list):
            return value
    return []


def _event_ts_seconds(row):
    value = row.get("ts")
    if isinstance(value, (int, float)):
        return int(value / 1000) if value > 10_000_000_000 else int(value)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except Exception:
            return None
    return None


def _fetch_fomo_alerts(key, now):
    since = now - timedelta(hours=24)
    params = urllib.parse.urlencode({
        "chain": "solana",
        "since": _iso(since),
        "limit": 100,
    })
    status, headers, body = _get_json(
        FOMO_BASE + "/v2/alerts?" + params,
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
    )
    if status != 200:
        raise RuntimeError("fomo_alerts_http_" + str(status))
    rows = _alerts_from_body(body)
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _event_ts_seconds(row)
        mint = row.get("tokenAddress")
        chain = str(row.get("chain") or "").lower()
        typ = str(row.get("alertType") or row.get("type") or "").lower()
        source = str(row.get("source") or "").lower()
        if (
            ts is None
            or not isinstance(mint, str)
            or len(mint) < 30
            or chain != "solana"
            or typ not in {"buy", "sell"}
            or source not in {"feed", ""}
        ):
            continue
        clean.append({
            "ts": ts,
            "mint": mint,
            "symbol": row.get("token"),
            "side": typ,
            "usd_value": row.get("usdValue"),
            "trader": row.get("trader"),
            "event_id": row.get("eventId") or row.get("id"),
        })
    return clean, {
        "status": status,
        "credit_cost": headers.get("x-credits-cost"),
        "credits_remaining": headers.get("x-credits-remaining"),
        "returned_rows": len(rows),
        "usable_solana_trade_rows": len(clean),
        "since": _iso(since),
    }


def _gt_get(path, params=None):
    query = urllib.parse.urlencode(params or {})
    url = GT_BASE + path + (("?" + query) if query else "")
    status, _, body = _get_json(
        url,
        headers={"Accept": "application/json;version=20230203"},
    )
    # Public API is approximately 10 calls/minute. Pace deliberately.
    time.sleep(6.2)
    return status, body


def _top_pool(mint):
    status, body = _gt_get(f"/networks/solana/tokens/{mint}/pools", {"page": 1})
    if status != 200 or not isinstance(body, dict):
        return None
    data = body.get("data")
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    attrs = first.get("attributes") or {}
    return {
        "address": attrs.get("address") or first.get("id", "").split("_")[-1],
        "name": attrs.get("name"),
        "reserve_usd": attrs.get("reserve_in_usd"),
        "volume_h24_usd": (attrs.get("volume_usd") or {}).get("h24")
        if isinstance(attrs.get("volume_usd"), dict) else None,
    }


def _ohlcv(mint, pool, event_ts):
    before = event_ts + 65 * 60
    status, body = _gt_get(
        f"/networks/solana/pools/{pool}/ohlcv/minute",
        {
            "aggregate": 1,
            "before_timestamp": before,
            "limit": 600,
            "currency": "usd",
            "token": mint,
        },
    )
    if status != 200 or not isinstance(body, dict):
        return {}
    try:
        rows = body["data"]["attributes"]["ohlcv_list"]
    except Exception:
        return {}
    out = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        ts = int(row[0])
        try:
            out[ts] = {
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        except (TypeError, ValueError):
            continue
    return out


def _minute(ts):
    return (int(ts) // 60) * 60


def _open_at(candles, ts, tolerance=120):
    target = _minute(ts)
    for offset in (0, 60, -60, 120, -120):
        row = candles.get(target + offset)
        if row and row["open"] > 0:
            return target + offset, row["open"]
    return None, None


def _return_between(candles, start_ts, end_ts):
    s_ts, s = _open_at(candles, start_ts)
    e_ts, e = _open_at(candles, end_ts)
    if s is None or e is None or s <= 0:
        return None
    return (e / s - 1.0) * 100.0


def _mfe_mae(candles, entry_ts, entry_price, minutes=60):
    if entry_price is None or entry_price <= 0:
        return None, None
    rows = [
        row for ts, row in candles.items()
        if entry_ts <= ts < entry_ts + minutes * 60
    ]
    if not rows:
        return None, None
    high = max(r["high"] for r in rows)
    low = min(r["low"] for r in rows)
    return (high / entry_price - 1) * 100, (low / entry_price - 1) * 100


def _near_fomo_event(ts, all_event_times):
    gap = FOMO_EXCLUSION_MINUTES * 60
    return any(abs(ts - other) <= gap for other in all_event_times)


def _matched_control(candles, event_entry_ts, event_pre15, all_event_times):
    if event_pre15 is None:
        return None
    earliest = event_entry_ts - CONTROL_LOOKBACK_HOURS * 3600
    latest = event_entry_ts - CONTROL_GAP_MINUTES * 60
    candidates = []
    for ts in sorted(candles):
        if ts < earliest or ts > latest:
            continue
        if _near_fomo_event(ts, all_event_times):
            continue
        # Need 15m prehistory and 60m forward data.
        pre = _return_between(candles, ts - 15 * 60, ts)
        fwd60 = _return_between(candles, ts, ts + 60 * 60)
        if pre is None or fwd60 is None:
            continue
        candidates.append((abs(pre - event_pre15), ts, pre))
    if not candidates:
        return None
    _, ts, pre = min(candidates, key=lambda x: (x[0], x[1]))
    _, entry = _open_at(candles, ts)
    result = {
        "entry_ts": ts,
        "pre15_return_pct": pre,
    }
    for h in HORIZONS:
        result[f"return_{h}m_pct"] = _return_between(candles, ts, ts + h * 60)
    mfe, mae = _mfe_mae(candles, ts, entry, 60)
    result["mfe_60m_pct"] = mfe
    result["mae_60m_pct"] = mae
    return result


def _median(values):
    vals = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    return statistics.median(vals) if vals else None


def _mean(values):
    vals = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    return statistics.mean(vals) if vals else None


def _paired_signflip_p(diffs):
    vals = [float(v) for v in diffs if v is not None and math.isfinite(v)]
    n = len(vals)
    if n == 0 or n > 18:
        return None
    observed = abs(statistics.mean(vals))
    total = 0
    extreme = 0
    for signs in itertools.product((-1.0, 1.0), repeat=n):
        value = abs(sum(s * v for s, v in zip(signs, vals)) / n)
        total += 1
        if value >= observed - 1e-12:
            extreme += 1
    return extreme / total


def main():
    key = os.environ.get("FOMOAPI_KEY", "")
    if not key:
        print("FOMOAPI_KEY unavailable", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    alerts, fomo_meta = _fetch_fomo_alerts(key, now)
    now_ts = int(now.timestamp())

    # Full set is used only to exclude candidate control minutes near known FOMO
    # activity on the same token.
    times_by_mint = {}
    for row in alerts:
        times_by_mint.setdefault(row["mint"], []).append(row["ts"])

    buys = [
        row for row in alerts
        if row["side"] == "buy"
        and MIN_EVENT_AGE_MINUTES * 60 <= now_ts - row["ts"] <= MAX_EVENT_AGE_HOURS * 3600
    ]
    # Oldest first; first eligible event per mint prevents choosing a later winner.
    buys.sort(key=lambda r: (r["ts"], r["mint"], str(r.get("event_id"))))
    selected = []
    seen = set()
    for row in buys:
        if row["mint"] in seen:
            continue
        seen.add(row["mint"])
        selected.append(row)
        if len(selected) >= MAX_EVENTS:
            break

    observations = []
    skipped = []
    for event in selected:
        pool = _top_pool(event["mint"])
        if not pool or not pool.get("address"):
            skipped.append({"symbol": event["symbol"], "reason": "no_geckoterminal_pool"})
            continue
        candles = _ohlcv(event["mint"], pool["address"], event["ts"])
        event_entry_ts = _minute(event["ts"]) + 60
        entry_ts, entry = _open_at(candles, event_entry_ts)
        if entry is None:
            skipped.append({"symbol": event["symbol"], "reason": "missing_event_candles"})
            continue

        pre15 = _return_between(candles, entry_ts - 15 * 60, entry_ts)
        event_metrics = {
            "entry_ts": entry_ts,
            "pre15_return_pct": pre15,
        }
        complete = True
        for h in HORIZONS:
            value = _return_between(candles, entry_ts, entry_ts + h * 60)
            event_metrics[f"return_{h}m_pct"] = value
            complete = complete and value is not None
        mfe, mae = _mfe_mae(candles, entry_ts, entry, 60)
        event_metrics["mfe_60m_pct"] = mfe
        event_metrics["mae_60m_pct"] = mae
        complete = complete and mfe is not None and mae is not None and pre15 is not None
        if not complete:
            skipped.append({"symbol": event["symbol"], "reason": "incomplete_forward_or_pre_event_candles"})
            continue

        control = _matched_control(
            candles,
            entry_ts,
            pre15,
            times_by_mint.get(event["mint"], []),
        )
        if control is None:
            skipped.append({"symbol": event["symbol"], "reason": "no_same_token_momentum_matched_control"})
            continue

        observations.append({
            "symbol": event["symbol"],
            "mint": event["mint"],
            "fomo_event_ts": event["ts"],
            "fomo_usd_value": event["usd_value"],
            "fomo_trader": event["trader"],
            "pool": pool,
            "event": event_metrics,
            "control": control,
        })

    comparisons = {}
    for h in HORIZONS:
        event_vals = [o["event"][f"return_{h}m_pct"] for o in observations]
        control_vals = [o["control"][f"return_{h}m_pct"] for o in observations]
        diffs = [a - b for a, b in zip(event_vals, control_vals)]
        comparisons[f"{h}m"] = {
            "n": len(diffs),
            "event_mean_return_pct": _mean(event_vals),
            "event_median_return_pct": _median(event_vals),
            "control_mean_return_pct": _mean(control_vals),
            "control_median_return_pct": _median(control_vals),
            "paired_mean_edge_pct_points": _mean(diffs),
            "paired_median_edge_pct_points": _median(diffs),
            "event_beats_control_count": sum(d > 0 for d in diffs),
            "exact_two_sided_signflip_p": _paired_signflip_p(diffs),
        }

    mfe_diffs = [o["event"]["mfe_60m_pct"] - o["control"]["mfe_60m_pct"] for o in observations]
    mae_diffs = [o["event"]["mae_60m_pct"] - o["control"]["mae_60m_pct"] for o in observations]

    report = {
        "kind": "fomo_market_edge_pilot_v1",
        "research_only": True,
        "strategy_data_used": False,
        "solana_rpc_calls": 0,
        "provider_spend_usd": 0,
        "design": {
            "event": "first eligible recent FOMO feed buy per unique Solana token",
            "actionable_entry_proxy": "next full one-minute GeckoTerminal candle open after FOMO event",
            "control": "same token, earlier non-FOMO minute with nearest preceding-15m return",
            "control_lookback_hours": CONTROL_LOOKBACK_HOURS,
            "fomo_exclusion_minutes": FOMO_EXCLUSION_MINUTES,
            "horizons_minutes": list(HORIZONS),
            "max_events": MAX_EVENTS,
        },
        "fomo": fomo_meta,
        "eligible_unique_buys_considered": len(selected),
        "matched_pairs": len(observations),
        "skipped": skipped,
        "comparisons": comparisons,
        "path_metrics_60m": {
            "event_mean_mfe_pct": _mean([o["event"]["mfe_60m_pct"] for o in observations]),
            "control_mean_mfe_pct": _mean([o["control"]["mfe_60m_pct"] for o in observations]),
            "paired_mean_mfe_edge_pct_points": _mean(mfe_diffs),
            "event_mean_mae_pct": _mean([o["event"]["mae_60m_pct"] for o in observations]),
            "control_mean_mae_pct": _mean([o["control"]["mae_60m_pct"] for o in observations]),
            "paired_mean_mae_difference_pct_points": _mean(mae_diffs),
        },
        "observations": observations,
        "interpretation_guard": (
            "Exploratory pilot only. Positive post-event differences can support further testing "
            "but do not establish causality or profitability; FOMO activity may coincide with "
            "unobserved news, liquidity, or social momentum."
        ),
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "matched_pairs": report["matched_pairs"],
        "eligible_unique_buys_considered": report["eligible_unique_buys_considered"],
        "comparisons": report["comparisons"],
        "path_metrics_60m": report["path_metrics_60m"],
        "skipped": report["skipped"],
    }, indent=2, sort_keys=True))
    return 0 if observations else 3


if __name__ == "__main__":
    raise SystemExit(main())
