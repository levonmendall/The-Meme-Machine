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
OUT = Path("solana-skilled-wallet-alpha-study.json")

ENTRY_DELAYS = (15, 60)
HORIZONS = (60, 300, 900, 3600)
ENTRY_TOL = 90
OUTCOME_TOL = 180
ROLLING = 300
ACTIVE_MAX_AGE = 60
DEDUP_SECONDS = 1800
CONTROL_EXCLUSION_SECONDS = 900
MAX_MATCH_DISTANCE = 4.0


def public_json(url: str) -> dict:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    r = requests.get(url, headers=headers, timeout=(20, 60))
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
        mcap = event.get("marketCapQuote")
        if isinstance(mcap, (int, float)) and mcap > 0:
            self.market_cap = float(mcap)

    def features(self, now: int, fallback_event: dict | None = None) -> dict | None:
        self.purge(now)
        if self.last_ts is None or self.last_price is None:
            return None
        if now - self.last_ts > ACTIVE_MAX_AGE:
            return None

        market_cap = self.market_cap
        if market_cap is None and fallback_event is not None:
            raw = fallback_event.get("marketCapQuote")
            if isinstance(raw, (int, float)) and raw > 0:
                market_cap = float(raw)
        if not market_cap:
            return None

        pre5 = None
        if self.trades and self.trades[0][1] > 0:
            pre5 = self.last_price / self.trades[0][1] - 1.0

        return {
            "market_cap_quote": market_cap,
            "pre5_return": pre5,
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

    d = 1.5 * abs(
        math.log(a["market_cap_quote"] / b["market_cap_quote"])
    )

    if a.get("pre5_return") is not None and b.get("pre5_return") is not None:
        d += abs(a["pre5_return"] - b["pre5_return"]) / 0.20

    d += 0.75 * abs(
        math.log1p(a.get("volume5_quote") or 0.0)
        - math.log1p(b.get("volume5_quote") or 0.0)
    )
    d += 0.5 * abs(
        math.log1p(a.get("trade_count5") or 0)
        - math.log1p(b.get("trade_count5") or 0)
    )

    age_a = a.get("token_age_seconds")
    age_b = b.get("token_age_seconds")
    if age_a and age_b and age_a > 0 and age_b > 0:
        d += 0.5 * abs(math.log1p(age_a) - math.log1p(age_b))

    return d


def new_role() -> dict:
    return {
        str(delay): {
            "entry_target": None,
            "entry_ts": None,
            "entry_price": None,
            "prices": {},
            "max_price": None,
            "min_price": None,
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
                and ts - state["entry_target"] <= ENTRY_TOL
            ):
                state["entry_ts"] = ts
                state["entry_price"] = price
                state["max_price"] = price
                state["min_price"] = price
            continue

        if ts < state["entry_ts"]:
            continue

        if ts <= state["entry_ts"] + max(HORIZONS):
            state["max_price"] = max(state["max_price"], price)
            state["min_price"] = min(state["min_price"], price)

        for horizon in HORIZONS:
            key = str(horizon)
            target_ts = state["entry_ts"] + horizon
            if (
                key not in state["prices"]
                and ts >= target_ts
                and ts - target_ts <= OUTCOME_TOL
            ):
                state["prices"][key] = {"ts": ts, "price": price}


def exact_sign_p(pos: int, neg: int) -> float | None:
    n = pos + neg
    if not n:
        return None
    from math import comb

    k = min(pos, neg)
    tail = sum(comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


def bootstrap_ci(values: list[float], seed: int = 180926) -> list[float | None]:
    vals = [
        float(x)
        for x in values
        if isinstance(x, (int, float)) and math.isfinite(float(x))
    ]
    if len(vals) < 2:
        return [None, None]

    rng = random.Random(seed)
    means = []
    for _ in range(5000):
        means.append(
            sum(vals[rng.randrange(len(vals))] for _ in range(len(vals)))
            / len(vals)
        )
    means.sort()
    return [
        means[int(0.025 * len(means))],
        means[int(0.975 * len(means)) - 1],
    ]


def summarize(
    records: list[dict],
    delay: int,
    horizon: int,
    persistent_only: bool = False,
) -> dict:
    edge_key = f"edge_{delay}s_{horizon}s"
    target_key = f"target_return_{delay}s_{horizon}s"
    control_key = f"control_return_{delay}s_{horizon}s"

    rows = [
        r
        for r in records
        if edge_key in r
        and (not persistent_only or r["persistent_7d_top100"])
    ]
    edges = [r[edge_key] for r in rows]
    targets = [r[target_key] for r in rows]
    controls = [r[control_key] for r in rows]

    by_wallet: dict[str, list[float]] = defaultdict(list)
    by_wallet_mint: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        by_wallet[r["wallet"]].append(r[edge_key])
        by_wallet_mint[(r["wallet"], r["mint"])].append(r[edge_key])

    wallet_edges = [statistics.mean(v) for v in by_wallet.values()]
    wallet_mint_edges = [statistics.mean(v) for v in by_wallet_mint.values()]
    pos = sum(x > 0 for x in edges)
    neg = sum(x < 0 for x in edges)

    return {
        "n": len(rows),
        "wallets": len(by_wallet),
        "wallet_mints": len(by_wallet_mint),
        "target_mean_pct": statistics.mean(targets) if targets else None,
        "target_median_pct": statistics.median(targets) if targets else None,
        "control_mean_pct": statistics.mean(controls) if controls else None,
        "control_median_pct": statistics.median(controls) if controls else None,
        "mean_edge_pp": statistics.mean(edges) if edges else None,
        "median_edge_pp": statistics.median(edges) if edges else None,
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
    }


def main() -> None:
    cohort = load_cohort()
    cohort_by_wallet = {row["wallet"]: row for row in cohort}
    cohort_wallets = set(cohort_by_wallet)

    index = public_json(f"{REPLAY}/index.json")
    hours = index.get("hours") or []
    if not hours:
        raise RuntimeError("no_shrine_archive_hours")

    states: dict[str, MarketState] = {}
    pairs: list[dict] = []
    watch: dict[str, list[tuple[int, str]]] = defaultdict(list)
    last_buy: dict[tuple[str, str], int] = {}
    cohort_buy_times: dict[str, list[int]] = defaultdict(list)
    control_last_used: dict[str, int] = {}

    last_cleanup = 0
    trade_rows = 0
    independent_buy_events = 0
    target_only_events = 0
    downloaded_hours = 0

    def contaminated(mint: str, ts: int) -> bool:
        arr = cohort_buy_times.get(mint) or []
        i = bisect.bisect_left(arr, ts)
        return any(
            0 <= j < len(arr)
            and abs(arr[j] - ts) <= CONTROL_EXCLUSION_SECONDS
            for j in (i - 1, i)
        )

    def choose_control(
        target_features: dict,
        target_mint: str,
        ts: int,
    ) -> tuple[float, str, dict] | None:
        options = []
        for mint, state in states.items():
            if mint == target_mint:
                continue
            if contaminated(mint, ts):
                continue
            if control_last_used.get(mint, 0) > ts - 60:
                continue
            control_features = state.features(ts)
            if not control_features:
                continue
            d = match_distance(target_features, control_features)
            if d is not None and d <= MAX_MATCH_DISTANCE:
                options.append((d, mint, control_features))

        if not options:
            return None

        chosen = min(options, key=lambda x: (x[0], x[1]))
        control_last_used[chosen[1]] = ts
        return chosen

    for hour_name in hours:
        archive_path = download_hour(hour_name)
        downloaded_hours += 1
        try:
            with open(archive_path, "rb") as raw_file:
                reader = zstandard.ZstdDecompressor().stream_reader(raw_file)
                text_stream = io.TextIOWrapper(reader, encoding="utf-8")
                for line in text_stream:
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

                    if action == "migrate":
                        for pair_idx, role_name in watch.get(mint, []):
                            pair = pairs[pair_idx]
                            if pair["event_ts"] <= ts <= pair["event_ts"] + 3600:
                                key = (
                                    "target_graduated"
                                    if role_name == "target"
                                    else "control_graduated"
                                )
                                pair[key] = True
                        continue

                    if action not in ("buy", "sell"):
                        continue

                    price = event.get("price")
                    if not isinstance(price, (int, float)) or price <= 0:
                        continue
                    price = float(price)
                    trade_rows += 1

                    involved = set(event.get("tradersInvolved") or [])
                    cohort_hits = (
                        sorted(involved & cohort_wallets)
                        if action == "buy"
                        else []
                    )

                    # Signal is observable after this wallet buy. Use only state
                    # from strictly before the current trade for matching.
                    pre_state = states.get(mint)
                    pre_features = (
                        pre_state.features(ts, fallback_event=event)
                        if pre_state is not None
                        else None
                    )

                    for wallet in cohort_hits:
                        key = (wallet, mint)
                        previous = last_buy.get(key)
                        cohort_buy_times[mint].append(ts)

                        if (
                            previous is not None
                            and ts - previous < DEDUP_SECONDS
                        ):
                            last_buy[key] = ts
                            continue

                        last_buy[key] = ts
                        independent_buy_events += 1
                        meta = cohort_by_wallet[wallet]

                        control = (
                            choose_control(pre_features, mint, ts)
                            if pre_features
                            else None
                        )

                        pair = {
                            "wallet": wallet,
                            "rank_30d": meta.get("rank_30d"),
                            "roi_30d": meta.get("roi_30d"),
                            "persistent_7d_top100": meta.get(
                                "persistent_7d_top100"
                            ),
                            "mint": mint,
                            "event_ts": ts,
                            "protocol": event.get("protocol"),
                            "quote_mint": event.get("quoteMint"),
                            "event_market_cap_quote": event.get(
                                "marketCapQuote"
                            ),
                            "target_features": pre_features,
                            "control_mint": None,
                            "match_distance": None,
                            "control_features": None,
                            "target": new_role(),
                            "control": new_role(),
                            "target_graduated": False,
                            "control_graduated": False,
                        }

                        if control:
                            d, control_mint, control_features = control
                            pair["control_mint"] = control_mint
                            pair["match_distance"] = d
                            pair["control_features"] = control_features
                        else:
                            target_only_events += 1

                        pair_idx = len(pairs)
                        pairs.append(pair)
                        watch[mint].append((pair_idx, "target"))
                        if pair["control_mint"]:
                            watch[pair["control_mint"]].append(
                                (pair_idx, "control")
                            )

                    state = states.get(mint)
                    if state is None:
                        state = states[mint] = MarketState()
                    state.add_trade(event)

                    for pair_idx, role_name in watch.get(mint, []):
                        update_role(
                            pairs[pair_idx][role_name],
                            ts,
                            price,
                            pairs[pair_idx]["event_ts"],
                        )

                    if ts - last_cleanup >= 300:
                        last_cleanup = ts
                        live_watch = {
                            m
                            for m, entries in watch.items()
                            if any(
                                pairs[i]["event_ts"] + 3900 >= ts
                                for i, _ in entries
                            )
                        }
                        for m in list(states):
                            if (
                                m not in live_watch
                                and (states[m].last_ts or 0) < ts - 7200
                            ):
                                del states[m]
                        for m in list(watch):
                            watch[m] = [
                                (i, k)
                                for i, k in watch[m]
                                if pairs[i]["event_ts"] + 3900 >= ts
                            ]
                            if not watch[m]:
                                del watch[m]
        finally:
            try:
                os.unlink(archive_path)
            except FileNotFoundError:
                pass

    for arr in cohort_buy_times.values():
        arr.sort()

    records = []
    for pair in pairs:
        if pair["control_mint"] and contaminated(
            pair["control_mint"], pair["event_ts"]
        ):
            continue

        row = {
            k: v
            for k, v in pair.items()
            if k not in ("target", "control")
        }

        for delay in ENTRY_DELAYS:
            target = pair["target"][str(delay)]
            control = pair["control"][str(delay)]

            if target["entry_price"]:
                row[f"target_mfe_{delay}s_60m_pct"] = (
                    target["max_price"] / target["entry_price"] - 1
                ) * 100
                row[f"target_mae_{delay}s_60m_pct"] = (
                    target["min_price"] / target["entry_price"] - 1
                ) * 100

            for horizon in HORIZONS:
                key = str(horizon)
                if target["entry_price"] and key in target["prices"]:
                    target_return = (
                        target["prices"][key]["price"]
                        / target["entry_price"]
                        - 1
                    ) * 100
                    row[
                        f"target_return_{delay}s_{horizon}s"
                    ] = target_return

                if (
                    pair["control_mint"]
                    and target["entry_price"]
                    and control["entry_price"]
                    and key in target["prices"]
                    and key in control["prices"]
                ):
                    control_return = (
                        control["prices"][key]["price"]
                        / control["entry_price"]
                        - 1
                    ) * 100
                    row[
                        f"control_return_{delay}s_{horizon}s"
                    ] = control_return
                    row[f"edge_{delay}s_{horizon}s"] = (
                        row[f"target_return_{delay}s_{horizon}s"]
                        - control_return
                    )

        if any(k.startswith("target_return_") for k in row):
            records.append(row)

    summaries = {}
    for delay in ENTRY_DELAYS:
        for horizon in HORIZONS:
            summaries[f"d{delay}_h{horizon}"] = summarize(
                records, delay, horizon, False
            )
            summaries[
                f"d{delay}_h{horizon}_persistent"
            ] = summarize(records, delay, horizon, True)

    per_wallet = {}
    for wallet in cohort_wallets:
        wallet_rows = [r for r in records if r["wallet"] == wallet]
        edges = [
            r["edge_15s_300s"]
            for r in wallet_rows
            if "edge_15s_300s" in r
        ]
        per_wallet[wallet] = {
            "events": len(wallet_rows),
            "paired_5m": len(edges),
            "mean_5m_edge_pp": (
                statistics.mean(edges) if edges else None
            ),
        }

    report = {
        "kind": "solana_high_roi_wallet_forward_alpha_study_v2",
        "research_only": True,
        "provider_spend_usd": 0,
        "cohort_source": (
            "Frozen MadeOnSol public alpha leaderboard cohort "
            "from run 35301582766"
        ),
        "selection": {
            "period": "30d",
            "sort": "roi",
            "min_tokens": 10,
            "exclude_bots": True,
            "top_n": len(cohort),
        },
        "survivorship_warning": (
            "Current 30d winners are selected using outcomes overlapping "
            "the archive. This is exploratory association, not an ex-ante "
            "walk-forward proof."
        ),
        "cohort": cohort,
        "archive_hours": len(hours),
        "downloaded_hours": downloaded_hours,
        "trade_rows_processed": trade_rows,
        "independent_wallet_buy_events": independent_buy_events,
        "pairs_created": len(pairs),
        "target_only_events": target_only_events,
        "complete_records": len(records),
        "summaries": summaries,
        "per_wallet": per_wallet,
        "records": records,
        "design": {
            "dedup": "first wallet/mint buy after 30m quiet",
            "entry_delays_seconds": list(ENTRY_DELAYS),
            "horizons_seconds": list(HORIZONS),
            "control": (
                "same-time active token, same protocol and quote; matched "
                "on market cap, prior-5m return when available, volume, "
                "trade count, and token age when known; controls with "
                "cohort buys +/-15m removed"
            ),
            "primary": "15-second delayed entry, 5-minute forward paired edge",
            "persistent_sensitivity": (
                "wallet also present in frozen 7d top-100 ROI leaderboard"
            ),
        },
        "limitations": [
            "Cohort selection is survivorship-biased; prospective/walk-forward "
            "validation is required before strategy authority.",
            "Shrine can have collector gaps; missing events are not imputed.",
            "Returns are market-price returns and exclude fees/slippage.",
        ],
    }

    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "cohort": len(cohort),
                "persistent": sum(
                    x["persistent_7d_top100"] for x in cohort
                ),
                "archive_hours": len(hours),
                "buy_events": independent_buy_events,
                "pairs_created": len(pairs),
                "complete_records": len(records),
                "primary": summaries["d15_h300"],
                "persistent_primary": summaries["d15_h300_persistent"],
                "d15_1m": summaries["d15_h60"],
                "d15_15m": summaries["d15_h900"],
                "d15_60m": summaries["d15_h3600"],
                "delay60_5m": summaries["d60_h300"],
                "per_wallet": per_wallet,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
