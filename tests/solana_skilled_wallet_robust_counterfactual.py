from __future__ import annotations

import bisect
import io
import json
import math
import os
import random
import statistics
import tempfile
import time
from collections import defaultdict, deque
from pathlib import Path

import requests
import zstandard

REPLAY = "https://replay.shrine.trade/pump"
COHORT_FILE = Path("tests/fixtures/solana_alpha_wallet_cohort_frozen.json")
OUT = Path("solana-skilled-wallet-robust-counterfactual.json")

ENTRY_DELAYS = (15, 60)
HORIZONS = (60, 300, 900)
ROLLING = 300
ACTIVE_MAX_AGE = 60
DEDUP_SECONDS = 1800
CONTROL_EXCLUSION_SECONDS = 900
MAX_CONTROL_DISTANCE = 3.0
MAX_CONTROLS = 12
PRIMARY_DISTANCE = 2.0
MIN_CONTROLS = 3
ENTRY_TOLERANCE = 90
OUTCOME_TOLERANCE = 180
MATCH_THRESHOLDS = (1.0, 1.5, 2.0, 2.5, 3.0)
TAILS = (10.0, 25.0, 50.0, 100.0)


def public_json(url: str) -> dict:
    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=(20, 60),
    )
    r.raise_for_status()
    return r.json()


def load_cohort() -> list[dict]:
    data = json.loads(COHORT_FILE.read_text())
    persistent = set(data["persistent_7d_top100"])
    rows = []
    for row in data["cohort"]:
        item = dict(row)
        item["persistent_7d_top100"] = item["wallet"] in persistent
        rows.append(item)
    return rows


def download_hour(hour_name: str, attempts: int = 5) -> str:
    url = f"{REPLAY}/{hour_name}.jsonl.zst"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/octet-stream"}
    last_exc: Exception | None = None
    for attempt in range(attempts):
        fd, path = tempfile.mkstemp(prefix="shrine-hour-", suffix=".jsonl.zst")
        os.close(fd)
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(20, 600)) as r:
                r.raise_for_status()
                with open(path, "wb") as out:
                    for chunk in r.iter_content(chunk_size=4 * 1024 * 1024):
                        if chunk:
                            out.write(chunk)
            if os.path.getsize(path) <= 0:
                raise RuntimeError("empty_archive_hour")
            return path
        except Exception as exc:
            last_exc = exc
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            if attempt + 1 < attempts:
                time.sleep(min(5 * (attempt + 1), 20))
    assert last_exc is not None
    raise last_exc


class MarketState:
    def __init__(self) -> None:
        self.trades: deque[tuple[int, float, float]] = deque()
        self.volume = 0.0
        self.count = 0
        self.last_ts: int | None = None
        self.last_price: float | None = None
        self.market_cap: float | None = None
        self.protocol: str | None = None
        self.quote_mint: str | None = None
        self.created_ts: int | None = None

    def purge(self, now: int) -> None:
        cutoff = now - ROLLING
        while self.trades and self.trades[0][0] < cutoff:
            _, _, quote_amount = self.trades.popleft()
            self.volume -= quote_amount
            self.count -= 1

    def add_trade(self, event: dict) -> None:
        ts = int(event["timestamp"])
        price = float(event["price"])
        quote_amount = abs(float(event.get("quoteAmount") or 0.0))
        self.purge(ts)
        self.trades.append((ts, price, quote_amount))
        self.volume += quote_amount
        self.count += 1
        self.last_ts = ts
        self.last_price = price
        self.protocol = event.get("protocol")
        self.quote_mint = event.get("quoteMint")
        raw_mcap = event.get("marketCapQuote")
        if isinstance(raw_mcap, (int, float)) and raw_mcap > 0:
            self.market_cap = float(raw_mcap)

    def features(self, now: int, fallback_event: dict | None = None) -> dict | None:
        self.purge(now)
        if (
            self.last_ts is None
            or self.last_price is None
            or now - self.last_ts > ACTIVE_MAX_AGE
            or self.count < 2
        ):
            return None

        market_cap = self.market_cap
        if market_cap is None and fallback_event is not None:
            raw = fallback_event.get("marketCapQuote")
            if isinstance(raw, (int, float)) and raw > 0:
                market_cap = float(raw)
        if not market_cap or not self.trades or self.trades[0][1] <= 0:
            return None

        return {
            "market_cap_quote": market_cap,
            "pre5_return": self.last_price / self.trades[0][1] - 1.0,
            "volume5_quote": max(self.volume, 0.0),
            "trade_count5": self.count,
            "protocol": self.protocol,
            "quote_mint": self.quote_mint,
            "token_age_seconds": (
                now - self.created_ts if self.created_ts is not None else None
            ),
        }


def match_distance(a: dict, b: dict) -> float | None:
    if a["protocol"] != b["protocol"] or a["quote_mint"] != b["quote_mint"]:
        return None

    distance = 1.5 * abs(
        math.log(a["market_cap_quote"] / b["market_cap_quote"])
    )
    distance += abs(a["pre5_return"] - b["pre5_return"]) / 0.20
    distance += 0.75 * abs(
        math.log1p(a["volume5_quote"]) - math.log1p(b["volume5_quote"])
    )
    distance += 0.5 * abs(
        math.log1p(a["trade_count5"]) - math.log1p(b["trade_count5"])
    )

    age_a = a.get("token_age_seconds")
    age_b = b.get("token_age_seconds")
    if age_a and age_b and age_a > 0 and age_b > 0:
        distance += 0.5 * abs(math.log1p(age_a) - math.log1p(age_b))
    return distance


def new_role() -> dict:
    return {
        str(delay): {
            "entry_target": None,
            "entry_ts": None,
            "entry_price": None,
            "prices": {},
        }
        for delay in ENTRY_DELAYS
    }


def update_role(role: dict, ts: int, price: float, event_ts: int) -> None:
    for delay in ENTRY_DELAYS:
        state = role[str(delay)]
        if state["entry_target"] is None:
            state["entry_target"] = event_ts + delay

        if state["entry_price"] is None:
            if (
                ts >= state["entry_target"]
                and ts - state["entry_target"] <= ENTRY_TOLERANCE
            ):
                state["entry_ts"] = ts
                state["entry_price"] = price
            continue

        if ts < state["entry_ts"]:
            continue

        for horizon in HORIZONS:
            key = str(horizon)
            target_ts = state["entry_ts"] + horizon
            if (
                key not in state["prices"]
                and ts >= target_ts
                and ts - target_ts <= OUTCOME_TOLERANCE
            ):
                state["prices"][key] = {"ts": ts, "price": price}


def exact_sign_p(pos: int, neg: int) -> float | None:
    n = pos + neg
    if not n:
        return None
    from math import comb

    k = min(pos, neg)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / (2**n))


def trimmed_mean(values: list[float], fraction: float) -> float | None:
    vals = sorted(float(x) for x in values if math.isfinite(float(x)))
    if not vals:
        return None
    cut = int(len(vals) * fraction)
    kept = vals[cut : len(vals) - cut] if cut and 2 * cut < len(vals) else vals
    return statistics.mean(kept) if kept else None


def winsorized_mean(values: list[float], cap: float) -> float | None:
    vals = [max(-cap, min(cap, float(x))) for x in values if math.isfinite(float(x))]
    return statistics.mean(vals) if vals else None


def bootstrap_ci(values: list[float], seed: int = 190926) -> list[float | None]:
    vals = [float(x) for x in values if math.isfinite(float(x))]
    if len(vals) < 2:
        return [None, None]
    rng = random.Random(seed)
    means = []
    for _ in range(5000):
        means.append(
            sum(vals[rng.randrange(len(vals))] for _ in range(len(vals))) / len(vals)
        )
    means.sort()
    return [
        means[int(0.025 * len(means))],
        means[int(0.975 * len(means)) - 1],
    ]


def summary(rows: list[dict], edge_key: str) -> dict:
    chosen = [r for r in rows if edge_key in r]
    edges = [r[edge_key] for r in chosen]
    pos = sum(x > 0 for x in edges)
    neg = sum(x < 0 for x in edges)

    by_wallet: dict[str, list[float]] = defaultdict(list)
    by_wallet_mint: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in chosen:
        by_wallet[row["wallet"]].append(row[edge_key])
        by_wallet_mint[(row["wallet"], row["mint"])].append(row[edge_key])

    wallet_edges = [statistics.mean(v) for v in by_wallet.values()]
    wallet_mint_edges = [statistics.mean(v) for v in by_wallet_mint.values()]

    positive_sum = sum(x for x in edges if x > 0)
    top5_positive_share = None
    if positive_sum > 0:
        top5_positive_share = (
            sum(sorted((x for x in edges if x > 0), reverse=True)[:5])
            / positive_sum
        )

    return {
        "n": len(edges),
        "wallets": len(by_wallet),
        "wallet_mints": len(by_wallet_mint),
        "mean_edge_pp": statistics.mean(edges) if edges else None,
        "median_edge_pp": statistics.median(edges) if edges else None,
        "trimmed_5pct_mean_edge_pp": trimmed_mean(edges, 0.05),
        "trimmed_10pct_mean_edge_pp": trimmed_mean(edges, 0.10),
        "winsorized_50pp_mean_edge_pp": winsorized_mean(edges, 50.0),
        "bootstrap95_mean_edge": bootstrap_ci(edges),
        "beats": pos,
        "loses": neg,
        "sign_p": exact_sign_p(pos, neg),
        "wallet_cluster_mean_edge_pp": (
            statistics.mean(wallet_edges) if wallet_edges else None
        ),
        "wallet_cluster_sign_p": exact_sign_p(
            sum(x > 0 for x in wallet_edges),
            sum(x < 0 for x in wallet_edges),
        ),
        "wallet_mint_cluster_mean_edge_pp": (
            statistics.mean(wallet_mint_edges) if wallet_mint_edges else None
        ),
        "wallet_mint_cluster_sign_p": exact_sign_p(
            sum(x > 0 for x in wallet_mint_edges),
            sum(x < 0 for x in wallet_mint_edges),
        ),
        "top5_positive_edge_share": top5_positive_share,
    }


def main() -> None:
    cohort = load_cohort()
    cohort_by_wallet = {x["wallet"]: x for x in cohort}
    cohort_wallets = set(cohort_by_wallet)

    hours = public_json(f"{REPLAY}/index.json").get("hours") or []
    if not hours:
        raise RuntimeError("no_shrine_archive_hours")

    states: dict[str, MarketState] = {}
    events: list[dict] = []
    watch: dict[str, list[tuple[int, str, int | None]]] = defaultdict(list)
    last_buy: dict[tuple[str, str], int] = {}
    cohort_buy_times: dict[str, list[int]] = defaultdict(list)
    control_last_used: dict[str, int] = {}
    last_cleanup = 0
    trade_rows = 0

    def contaminated(mint: str, ts: int) -> bool:
        arr = cohort_buy_times.get(mint) or []
        i = bisect.bisect_left(arr, ts)
        return any(
            0 <= j < len(arr)
            and abs(arr[j] - ts) <= CONTROL_EXCLUSION_SECONDS
            for j in (i - 1, i)
        )

    def choose_controls(target_features: dict, target_mint: str, ts: int) -> list[dict]:
        options = []
        for mint, state in states.items():
            if mint == target_mint or control_last_used.get(mint, 0) > ts - 60:
                continue
            if contaminated(mint, ts):
                continue
            features = state.features(ts)
            if not features:
                continue
            distance = match_distance(target_features, features)
            if distance is None or distance > MAX_CONTROL_DISTANCE:
                continue
            options.append((distance, mint, features))

        options.sort(key=lambda x: (x[0], x[1]))
        selected = []
        for distance, mint, features in options[:MAX_CONTROLS]:
            control_last_used[mint] = ts
            selected.append(
                {
                    "mint": mint,
                    "distance": distance,
                    "features": features,
                    "role": new_role(),
                }
            )
        return selected

    for hour_name in hours:
        path = download_hour(hour_name)
        try:
            with open(path, "rb") as raw_file:
                reader = zstandard.ZstdDecompressor().stream_reader(raw_file)
                for line in io.TextIOWrapper(reader, encoding="utf-8"):
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue

                    ts = event.get("timestamp")
                    mint = event.get("mint")
                    action = event.get("action")
                    if not isinstance(ts, (int, float)) or not mint:
                        continue
                    ts = int(ts)

                    if action == "create":
                        state = states.get(mint)
                        if state is None:
                            state = states[mint] = MarketState()
                        state.created_ts = ts
                        continue

                    if action not in ("buy", "sell"):
                        continue
                    price = event.get("price")
                    if not isinstance(price, (int, float)) or price <= 0:
                        continue
                    price = float(price)
                    trade_rows += 1

                    involved = set(event.get("tradersInvolved") or [])
                    hits = sorted(involved & cohort_wallets) if action == "buy" else []

                    pre_state = states.get(mint)
                    target_features = (
                        pre_state.features(ts, fallback_event=event)
                        if pre_state is not None
                        else None
                    )

                    for wallet in hits:
                        key = (wallet, mint)
                        previous = last_buy.get(key)
                        cohort_buy_times[mint].append(ts)
                        if previous is not None and ts - previous < DEDUP_SECONDS:
                            last_buy[key] = ts
                            continue
                        last_buy[key] = ts

                        if not target_features:
                            continue

                        controls = choose_controls(target_features, mint, ts)
                        meta = cohort_by_wallet[wallet]
                        row = {
                            "wallet": wallet,
                            "rank_30d": meta.get("rank_30d"),
                            "roi_30d": meta.get("roi_30d"),
                            "win_rate_30d": meta.get("win_rate_30d"),
                            "tokens_traded_30d": meta.get("tokens_traded_30d"),
                            "persistent_7d_top100": meta.get("persistent_7d_top100"),
                            "mint": mint,
                            "event_ts": ts,
                            "protocol": event.get("protocol"),
                            "quote_mint": event.get("quoteMint"),
                            "target_features": target_features,
                            "target": new_role(),
                            "controls": controls,
                        }
                        event_idx = len(events)
                        events.append(row)
                        watch[mint].append((event_idx, "target", None))
                        for control_idx, control in enumerate(controls):
                            watch[control["mint"]].append(
                                (event_idx, "control", control_idx)
                            )

                    state = states.get(mint)
                    if state is None:
                        state = states[mint] = MarketState()
                    state.add_trade(event)

                    for event_idx, kind, control_idx in watch.get(mint, []):
                        row = events[event_idx]
                        if kind == "target":
                            update_role(row["target"], ts, price, row["event_ts"])
                        else:
                            update_role(
                                row["controls"][control_idx]["role"],
                                ts,
                                price,
                                row["event_ts"],
                            )

                    if ts - last_cleanup >= 300:
                        last_cleanup = ts
                        live_mints = {
                            m
                            for m, entries in watch.items()
                            if any(
                                events[i]["event_ts"] + 3900 >= ts
                                for i, _, _ in entries
                            )
                        }
                        for m in list(states):
                            if (
                                m not in live_mints
                                and (states[m].last_ts or 0) < ts - 7200
                            ):
                                del states[m]
                        for m in list(watch):
                            watch[m] = [
                                item
                                for item in watch[m]
                                if events[item[0]]["event_ts"] + 3900 >= ts
                            ]
                            if not watch[m]:
                                del watch[m]
        finally:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    for arr in cohort_buy_times.values():
        arr.sort()

    records = []
    for event in events:
        base = {
            k: v
            for k, v in event.items()
            if k not in ("target", "controls")
        }
        valid_controls = [
            c
            for c in event["controls"]
            if not contaminated(c["mint"], event["event_ts"])
        ]

        for delay in ENTRY_DELAYS:
            target_role = event["target"][str(delay)]
            if not target_role["entry_price"]:
                continue

            for horizon in HORIZONS:
                hkey = str(horizon)
                target_price = target_role["prices"].get(hkey)
                if not target_price:
                    continue
                target_return = (
                    target_price["price"] / target_role["entry_price"] - 1
                ) * 100
                base[f"target_return_{delay}s_{horizon}s"] = target_return

                for threshold in MATCH_THRESHOLDS:
                    controls = []
                    distances = []
                    tail_control_returns = []
                    for control in valid_controls:
                        if control["distance"] > threshold:
                            continue
                        state = control["role"][str(delay)]
                        if not state["entry_price"] or hkey not in state["prices"]:
                            continue
                        control_return = (
                            state["prices"][hkey]["price"] / state["entry_price"] - 1
                        ) * 100
                        controls.append(control_return)
                        distances.append(control["distance"])
                        tail_control_returns.append(control_return)

                    if len(controls) < MIN_CONTROLS:
                        continue

                    label = str(threshold).replace(".", "p")
                    control_median = statistics.median(controls)
                    base[
                        f"control_median_{delay}s_{horizon}s_d{label}"
                    ] = control_median
                    base[
                        f"edge_{delay}s_{horizon}s_d{label}"
                    ] = target_return - control_median
                    base[
                        f"control_count_{delay}s_{horizon}s_d{label}"
                    ] = len(controls)
                    base[
                        f"control_mean_distance_{delay}s_{horizon}s_d{label}"
                    ] = statistics.mean(distances)

                    for tail in TAILS:
                        base[
                            f"target_ge_{int(tail)}_{delay}s_{horizon}s"
                        ] = target_return >= tail
                        base[
                            f"control_ge_{int(tail)}_fraction_{delay}s_{horizon}s_d{label}"
                        ] = sum(x >= tail for x in tail_control_returns) / len(
                            tail_control_returns
                        )

        if any(k.startswith("edge_") for k in base):
            records.append(base)

    analyses = {}
    for delay in ENTRY_DELAYS:
        for horizon in HORIZONS:
            for threshold in MATCH_THRESHOLDS:
                label = str(threshold).replace(".", "p")
                edge_key = f"edge_{delay}s_{horizon}s_d{label}"
                analyses[f"d{delay}_h{horizon}_match{threshold}"] = summary(
                    records, edge_key
                )

    primary_key = "edge_15s_300s_d2p0"
    primary_rows = [r for r in records if primary_key in r]
    persistent_rows = [
        r for r in primary_rows if r["persistent_7d_top100"]
    ]

    tail_summary = {}
    for tail in TAILS:
        target_hits = [
            bool(r.get(f"target_ge_{int(tail)}_15s_300s"))
            for r in primary_rows
        ]
        control_fractions = [
            r.get(f"control_ge_{int(tail)}_fraction_15s_300s_d2p0")
            for r in primary_rows
        ]
        control_fractions = [x for x in control_fractions if x is not None]
        tail_summary[str(int(tail))] = {
            "n": len(target_hits),
            "target_hit_rate": (
                sum(target_hits) / len(target_hits) if target_hits else None
            ),
            "mean_matched_control_hit_rate": (
                statistics.mean(control_fractions)
                if control_fractions
                else None
            ),
        }

    subgroup = {}
    subgroup_defs = {
        "rank_1_10": lambda r: (r.get("rank_30d") or 999) <= 10,
        "rank_11_20": lambda r: 11 <= (r.get("rank_30d") or 999) <= 20,
        "persistent_7d": lambda r: bool(r.get("persistent_7d_top100")),
        "win_rate_ge_50pct": lambda r: (r.get("win_rate_30d") or 0) >= 0.50,
        "tokens_traded_ge_20": lambda r: (r.get("tokens_traded_30d") or 0) >= 20,
    }
    for name, fn in subgroup_defs.items():
        chosen = [r for r in primary_rows if fn(r)]
        subgroup[name] = summary(chosen, primary_key)

    report = {
        "kind": "solana_skilled_wallet_robust_counterfactual_v1",
        "research_only": True,
        "provider_spend_usd": 0,
        "cohort_source": "Frozen high-ROI cohort from run 35301582766",
        "events_with_pretrade_features": len(events),
        "records_with_robust_counterfactual": len(records),
        "trade_rows_processed": trade_rows,
        "design": {
            "entry_delays_seconds": list(ENTRY_DELAYS),
            "horizons_seconds": list(HORIZONS),
            "max_controls_per_event": MAX_CONTROLS,
            "minimum_controls_per_estimate": MIN_CONTROLS,
            "match_threshold_sensitivity": list(MATCH_THRESHOLDS),
            "primary": (
                "15s delayed entry; 5m outcome; median of >=3 matched controls "
                "with distance <=2.0"
            ),
            "controls": (
                "same protocol and quote; matched on pre-event market cap, "
                "5m return, volume, trade count, and token age when known"
            ),
        },
        "primary": summary(primary_rows, primary_key),
        "persistent_primary": summary(persistent_rows, primary_key),
        "tail_enrichment_5m": tail_summary,
        "subgroups_exploratory": subgroup,
        "match_sensitivity": analyses,
        "records": records,
        "limitations": [
            "The cohort is retrospectively selected from current 30d ROI, so survivorship bias remains.",
            "Subgroup findings are exploratory and must not be used as strategy thresholds without a fresh sample.",
            "Market returns exclude execution fees and slippage.",
        ],
    }
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "events": report["events_with_pretrade_features"],
                "records": report["records_with_robust_counterfactual"],
                "primary": report["primary"],
                "persistent_primary": report["persistent_primary"],
                "tail_enrichment_5m": report["tail_enrichment_5m"],
                "subgroups_exploratory": report["subgroups_exploratory"],
                "match_sensitivity_5m": {
                    k: v
                    for k, v in analyses.items()
                    if k.startswith("d15_h300")
                },
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
