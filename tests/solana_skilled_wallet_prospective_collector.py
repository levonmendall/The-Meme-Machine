from __future__ import annotations

import io
import json
import math
import os
import statistics
import tempfile
import time
import urllib.parse
import zipfile
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import zstandard

REPLAY = "https://replay.shrine.trade/pump"
CONTRACT_PATH = Path("tests/fixtures/solana_skilled_wallet_prospective_contract.json")
COHORT_PATH = Path("tests/fixtures/solana_alpha_wallet_cohort_frozen.json")
STATE_PATH = Path("prospective_state.json")
EVENTS_PATH = Path("prospective_events.jsonl")
SUMMARY_PATH = Path("prospective_summary.json")
ARTIFACT_NAME = "prospective-skilled-wallet-state"

PROTOCOLS = {"PUMPFUN", "PUMPSWAP"}
ROLLING_SECONDS = 300
ACTIVE_MAX_AGE = 60
ENTRY_TOLERANCE = 90
OUTCOME_TOLERANCE = 180
MAX_CATCHUP_HOURS = 2


def utc_ts(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def hour_name(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y/%m/%d/%H")


def hour_start_ts(name: str) -> int:
    return int(
        datetime.strptime(name, "%Y/%m/%d/%H")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def github_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "meme-machine-prospective-wallet-study",
    }


def restore_latest_state() -> dict | None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = str(os.environ.get("GITHUB_RUN_ID", ""))
    token = os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        return None

    url = (
        f"https://api.github.com/repos/{repo}/actions/artifacts"
        f"?per_page=100&name={urllib.parse.quote(ARTIFACT_NAME)}"
    )
    response = requests.get(url, headers=github_headers(), timeout=30)
    response.raise_for_status()
    artifacts = [
        a
        for a in response.json().get("artifacts", [])
        if not a.get("expired")
        and str((a.get("workflow_run") or {}).get("id")) != run_id
    ]
    artifacts.sort(key=lambda a: a.get("created_at") or "", reverse=True)

    for artifact in artifacts:
        try:
            download = requests.get(
                artifact["archive_download_url"],
                headers=github_headers(),
                timeout=60,
                allow_redirects=True,
            )
            download.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(download.content)) as zf:
                try:
                    raw = zf.read(STATE_PATH.name)
                except KeyError:
                    continue
            text = raw.decode("utf-8").strip()
            # Compatibility with the initial collector artifact, which ended
            # in the two literal characters backslash+n rather than a newline.
            if text.endswith("\\n"):
                text = text[:-2].rstrip()
            state = json.loads(text)
            if isinstance(state, dict) and state.get("test_name"):
                return state
        except Exception:
            continue
    return None


def public_json(url: str) -> dict:
    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=(20, 60),
    )
    r.raise_for_status()
    return r.json()


def download_hour(name: str, attempts: int = 5) -> str:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/octet-stream"}
    last_exc: Exception | None = None
    url = f"{REPLAY}/{name}.jsonl.zst"
    for attempt in range(attempts):
        fd, path = tempfile.mkstemp(prefix="prospective-shrine-", suffix=".jsonl.zst")
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
        cutoff = now - ROLLING_SECONDS
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
        raw = event.get("marketCapQuote")
        if isinstance(raw, (int, float)) and raw > 0:
            self.market_cap = float(raw)

    def features(self, now: int, fallback: dict | None = None) -> dict | None:
        self.purge(now)
        if (
            self.last_ts is None
            or self.last_price is None
            or now - self.last_ts > ACTIVE_MAX_AGE
            or self.count < 2
            or not self.trades
            or self.trades[0][1] <= 0
        ):
            return None

        market_cap = self.market_cap
        if market_cap is None and fallback is not None:
            raw = fallback.get("marketCapQuote")
            if isinstance(raw, (int, float)) and raw > 0:
                market_cap = float(raw)
        if not market_cap:
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


def scan_hour_events(name: str) -> list[dict]:
    path = download_hour(name)
    rows = []
    try:
        with open(path, "rb") as raw_file:
            reader = zstandard.ZstdDecompressor().stream_reader(raw_file)
            for line in io.TextIOWrapper(reader, encoding="utf-8"):
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    return rows


def new_state(contract: dict, cohort: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "test_name": contract["test_name"],
        "frozen_at_utc": contract["frozen_at_utc"],
        "cohort": cohort,
        "processed_hours": [],
        "events": [],
        "cohort_buy_tape": [],
        "collection_stopped_at_200": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def buy_tape_key(row: dict) -> str:
    return "|".join(
        [
            str(row.get("signature") or ""),
            str(row.get("wallet") or ""),
            str(row.get("mint") or ""),
            str(row.get("ts") or ""),
        ]
    )


def event_key(wallet: str, mint: str, signature: str, ts: int) -> str:
    return f"{signature}|{wallet}|{mint}|{ts}"


def previous_distinct_wallets(
    history: dict[str, list[tuple[int, str]]],
    mint: str,
    ts: int,
    seconds: int,
) -> set[str]:
    return {
        wallet
        for event_ts, wallet in history.get(mint, [])
        if ts - seconds <= event_ts < ts
    }


def choose_controls(
    states: dict[str, MarketState],
    target_features: dict,
    target_mint: str,
    ts: int,
    prior_cohort_buys: dict[str, list[tuple[int, str]]],
    contract: dict,
) -> list[dict]:
    candidates = []
    exclusion = int(
        contract["robust_control_rule"]["control_cohort_buy_exclusion_seconds"]
    )
    for mint, state in states.items():
        if mint == target_mint:
            continue
        if previous_distinct_wallets(prior_cohort_buys, mint, ts, exclusion):
            continue
        features = state.features(ts)
        if not features:
            continue
        distance = match_distance(target_features, features)
        if distance is None or distance > 3.0:
            continue
        candidates.append((distance, mint, features))
    candidates.sort(key=lambda x: (x[0], x[1]))
    return [
        {"mint": mint, "distance": distance, "pre_state": features}
        for distance, mint, features in candidates[
            : int(contract["robust_control_rule"]["max_controls"])
        ]
    ]


def process_detection_hour(
    state: dict,
    hour: str,
    available: set[str],
    contract: dict,
    cohort_by_wallet: dict[str, dict],
) -> None:
    start = hour_start_ts(hour)
    end = start + 3600
    freeze_ts = utc_ts(contract["frozen_at_utc"])
    prior_hour = hour_name(start - 3600)

    source_hours = [h for h in (prior_hour, hour) if h in available]
    states: dict[str, MarketState] = {}
    all_buys: dict[str, list[tuple[int, str]]] = defaultdict(list)
    last_seen: dict[tuple[str, str], int] = {}

    existing_tape = {buy_tape_key(x) for x in state["cohort_buy_tape"]}
    existing_events = {x["event_id"] for x in state["events"]}
    cohort_wallets = set(cohort_by_wallet)

    for source_hour in source_hours:
        rows = scan_hour_events(source_hour)
        for event in rows:
            ts = event.get("timestamp")
            mint = event.get("mint")
            action = event.get("action")
            if not isinstance(ts, (int, float)) or not mint:
                continue
            ts = int(ts)

            if action == "create":
                market = states.get(mint)
                if market is None:
                    market = states[mint] = MarketState()
                market.created_ts = ts
                continue

            if action not in ("buy", "sell"):
                continue
            if event.get("protocol") not in PROTOCOLS:
                continue
            price = event.get("price")
            if not isinstance(price, (int, float)) or price <= 0:
                continue

            market = states.get(mint)
            target_features = (
                market.features(ts, fallback=event) if market is not None else None
            )

            involved = sorted(set(event.get("tradersInvolved") or []))
            cohort_hits = [w for w in involved if w in cohort_wallets] if action == "buy" else []

            for wallet in cohort_hits:
                last = last_seen.get((wallet, mint))
                prior_5 = previous_distinct_wallets(all_buys, mint, ts, 300)
                prior_15 = previous_distinct_wallets(all_buys, mint, ts, 900)
                prior_60 = previous_distinct_wallets(all_buys, mint, ts, 3600)

                signature = str(event.get("signature") or "")
                tape_row = {
                    "ts": ts,
                    "wallet": wallet,
                    "mint": mint,
                    "signature": signature,
                    "protocol": event.get("protocol"),
                }
                if ts >= freeze_ts and buy_tape_key(tape_row) not in existing_tape:
                    state["cohort_buy_tape"].append(tape_row)
                    existing_tape.add(buy_tape_key(tape_row))

                is_in_detection_hour = start <= ts < end and ts >= freeze_ts
                is_natural = last is None or ts - last >= int(
                    contract["natural_buy_definition"].split(">=")[1].split()[0]
                ) * 60
                last_seen[(wallet, mint)] = ts
                all_buys[mint].append((ts, wallet))

                if (
                    not is_in_detection_hour
                    or not is_natural
                    or state["collection_stopped_at_200"]
                ):
                    continue

                eid = event_key(wallet, mint, signature, ts)
                if eid in existing_events:
                    continue

                convergence_5 = len(prior_5 | {wallet})
                convergence_15 = len(prior_15 | {wallet})
                convergence_60 = len(prior_60 | {wallet})
                controls = (
                    choose_controls(
                        states, target_features, mint, ts, all_buys, contract
                    )
                    if target_features
                    else []
                )
                meta = cohort_by_wallet[wallet]
                state["events"].append(
                    {
                        "event_id": eid,
                        "sequence": len(state["events"]) + 1,
                        "wallet": wallet,
                        "rank_30d": meta.get("rank_30d"),
                        "roi_30d": meta.get("roi_30d"),
                        "win_rate_30d": meta.get("win_rate_30d"),
                        "tokens_traded_30d": meta.get("tokens_traded_30d"),
                        "persistent_7d_top100": meta.get("persistent_7d_top100"),
                        "mint": mint,
                        "signal_ts": ts,
                        "signal_signature": signature,
                        "protocol": event.get("protocol"),
                        "quote_mint": event.get("quoteMint"),
                        "pre_market_state": target_features,
                        "pre_market_state_available": bool(target_features),
                        "controls": controls,
                        "convergence_wallet_count_5m": convergence_5,
                        "convergence_wallet_count_15m": convergence_15,
                        "convergence_wallet_count_60m": convergence_60,
                        "convergence_signal_15m": convergence_15 >= 2,
                        "outcome_complete": False,
                        "outcome": None,
                    }
                )
                existing_events.add(eid)

                if len(state["events"]) >= int(contract["target_n_final"]):
                    state["collection_stopped_at_200"] = True

            market = states.get(mint)
            if market is None:
                market = states[mint] = MarketState()
            market.add_trade(event)


def first_trade_at_or_after(
    rows: list[dict], target_ts: int, tolerance: int
) -> dict | None:
    for row in rows:
        ts = row["ts"]
        if ts < target_ts:
            continue
        if ts - target_ts <= tolerance:
            return row
        break
    return None


def cohort_contaminated(
    tape_by_mint: dict[str, list[int]],
    mint: str,
    signal_ts: int,
    exclusion: int,
) -> bool:
    return any(
        abs(ts - signal_ts) <= exclusion
        for ts in tape_by_mint.get(mint, [])
    )


def label_mature_outcomes(
    state: dict,
    latest_archive_end: int,
    available: set[str],
    contract: dict,
) -> None:
    pending = [
        e
        for e in state["events"]
        if not e["outcome_complete"]
        and e["signal_ts"] + 3900 <= latest_archive_end
    ]
    if not pending:
        return

    tape_by_mint: dict[str, list[int]] = defaultdict(list)
    for row in state["cohort_buy_tape"]:
        tape_by_mint[row["mint"]].append(int(row["ts"]))

    relevant_mints = set()
    needed_hours = set()
    for event in pending:
        relevant_mints.add(event["mint"])
        relevant_mints.update(c["mint"] for c in event["controls"])
        start = event["signal_ts"]
        stop = event["signal_ts"] + 2 * 3600
        cursor = hour_start_ts(hour_name(start))
        while cursor <= stop:
            h = hour_name(cursor)
            if h in available:
                needed_hours.add(h)
            cursor += 3600

    trades_by_mint: dict[str, list[dict]] = defaultdict(list)
    for h in sorted(needed_hours):
        for event in scan_hour_events(h):
            mint = event.get("mint")
            action = event.get("action")
            ts = event.get("timestamp")
            price = event.get("price")
            if (
                mint not in relevant_mints
                or action not in ("buy", "sell")
                or event.get("protocol") not in PROTOCOLS
                or not isinstance(ts, (int, float))
                or not isinstance(price, (int, float))
                or price <= 0
            ):
                continue
            trades_by_mint[mint].append(
                {"ts": int(ts), "price": float(price)}
            )
    for rows in trades_by_mint.values():
        rows.sort(key=lambda r: r["ts"])

    exclusion = int(
        contract["robust_control_rule"]["control_cohort_buy_exclusion_seconds"]
    )
    max_distance = float(
        contract["robust_control_rule"]["primary_max_match_distance"]
    )
    min_controls = int(
        contract["robust_control_rule"]["minimum_controls"]
    )
    horizons = contract["outcome_horizons_seconds_after_follower_entry"]

    for event in pending:
        outcome = {"entries": {}, "robust": {}}
        for delay in contract["entry_delays_seconds"]:
            target_rows = trades_by_mint.get(event["mint"], [])
            entry = first_trade_at_or_after(
                target_rows, event["signal_ts"] + int(delay), ENTRY_TOLERANCE
            )
            delay_key = str(delay)
            target_result = {
                "entry_ts": entry["ts"] if entry else None,
                "entry_price": entry["price"] if entry else None,
                "returns_pct": {},
            }

            if entry:
                for horizon in horizons:
                    obs = first_trade_at_or_after(
                        target_rows,
                        entry["ts"] + int(horizon),
                        OUTCOME_TOLERANCE,
                    )
                    target_result["returns_pct"][str(horizon)] = (
                        (obs["price"] / entry["price"] - 1.0) * 100
                        if obs
                        else None
                    )
            else:
                for horizon in horizons:
                    target_result["returns_pct"][str(horizon)] = None

            control_results = []
            for control in event["controls"]:
                if control["distance"] > max_distance:
                    continue
                if cohort_contaminated(
                    tape_by_mint, control["mint"], event["signal_ts"], exclusion
                ):
                    continue
                rows = trades_by_mint.get(control["mint"], [])
                c_entry = first_trade_at_or_after(
                    rows, event["signal_ts"] + int(delay), ENTRY_TOLERANCE
                )
                c_returns = {}
                if c_entry:
                    for horizon in horizons:
                        obs = first_trade_at_or_after(
                            rows,
                            c_entry["ts"] + int(horizon),
                            OUTCOME_TOLERANCE,
                        )
                        c_returns[str(horizon)] = (
                            (obs["price"] / c_entry["price"] - 1.0) * 100
                            if obs
                            else None
                        )
                else:
                    for horizon in horizons:
                        c_returns[str(horizon)] = None
                control_results.append(
                    {
                        "mint": control["mint"],
                        "distance": control["distance"],
                        "entry_ts": c_entry["ts"] if c_entry else None,
                        "entry_price": c_entry["price"] if c_entry else None,
                        "returns_pct": c_returns,
                    }
                )

            robust = {}
            for horizon in horizons:
                target_return = target_result["returns_pct"][str(horizon)]
                valid = [
                    c["returns_pct"][str(horizon)]
                    for c in control_results
                    if c["returns_pct"][str(horizon)] is not None
                ]
                robust[str(horizon)] = {
                    "target_return_pct": target_return,
                    "valid_control_count": len(valid),
                    "median_control_return_pct": (
                        statistics.median(valid) if valid else None
                    ),
                    "edge_pp": (
                        target_return - statistics.median(valid)
                        if target_return is not None and len(valid) >= min_controls
                        else None
                    ),
                }

            outcome["entries"][delay_key] = {
                "target": target_result,
                "controls": control_results,
            }
            outcome["robust"][delay_key] = robust

        primary = outcome["robust"]["15"]["300"]
        target_5m = primary["target_return_pct"]
        outcome["primary_tail_flags"] = {
            str(t): (
                target_5m >= float(t) if target_5m is not None else None
            )
            for t in contract["tail_thresholds_pct"]
        }
        event["outcome"] = outcome
        event["outcome_complete"] = True


def robust_rows(state: dict, delay: str = "15", horizon: str = "300") -> list[dict]:
    rows = []
    for event in state["events"]:
        if not event["outcome_complete"] or not event["outcome"]:
            continue
        robust = event["outcome"]["robust"][delay][horizon]
        edge = robust.get("edge_pp")
        if edge is None:
            continue
        rows.append(
            {
                "event": event,
                "edge_pp": edge,
                "target_return_pct": robust["target_return_pct"],
                "control_median_return_pct": robust[
                    "median_control_return_pct"
                ],
            }
        )
    return rows


def summarize(state: dict, contract: dict) -> dict:
    completed = [e for e in state["events"] if e["outcome_complete"]]
    primary = robust_rows(state)
    edges = [r["edge_pp"] for r in primary]

    tails = {}
    for threshold in contract["tail_thresholds_pct"]:
        hits = []
        control_hits = []
        for row in primary:
            target = row["target_return_pct"]
            if target is None:
                continue
            hits.append(target >= float(threshold))
            event = row["event"]
            controls = event["outcome"]["entries"]["15"]["controls"]
            valid = [
                c["returns_pct"]["300"]
                for c in controls
                if c["distance"]
                <= float(
                    contract["robust_control_rule"][
                        "primary_max_match_distance"
                    ]
                )
                and c["returns_pct"]["300"] is not None
            ]
            if valid:
                control_hits.append(
                    sum(v >= float(threshold) for v in valid) / len(valid)
                )
        tails[str(threshold)] = {
            "n": len(hits),
            "target_hit_rate": sum(hits) / len(hits) if hits else None,
            "mean_control_hit_rate": (
                statistics.mean(control_hits) if control_hits else None
            ),
        }

    convergence = {}
    for label, predicate in {
        "single_wallet": lambda e: e["convergence_wallet_count_15m"] == 1,
        "two_plus_wallets": lambda e: e["convergence_wallet_count_15m"] >= 2,
    }.items():
        subset = [
            r for r in primary if predicate(r["event"])
        ]
        convergence[label] = {
            "n": len(subset),
            "mean_edge_pp": (
                statistics.mean(r["edge_pp"] for r in subset)
                if subset
                else None
            ),
            "median_edge_pp": (
                statistics.median(r["edge_pp"] for r in subset)
                if subset
                else None
            ),
            "tail_rates": {
                str(t): (
                    sum(
                        r["target_return_pct"] is not None
                        and r["target_return_pct"] >= float(t)
                        for r in subset
                    )
                    / len(subset)
                    if subset
                    else None
                )
                for t in contract["tail_thresholds_pct"]
            },
        }

    return {
        "test_name": state["test_name"],
        "frozen_at_utc": state["frozen_at_utc"],
        "natural_buy_count": len(state["events"]),
        "completed_outcome_count": len(completed),
        "robust_primary_count": len(primary),
        "stage": (
            "final_complete"
            if len(completed) >= int(contract["target_n_final"])
            else "interim_ready"
            if len(completed) >= int(contract["target_n_interim"])
            else "collecting"
        ),
        "primary_15s_entry_5m": {
            "n": len(primary),
            "mean_edge_pp": statistics.mean(edges) if edges else None,
            "median_edge_pp": statistics.median(edges) if edges else None,
            "beats": sum(x > 0 for x in edges),
            "loses": sum(x < 0 for x in edges),
        },
        "tail_enrichment_5m": tails,
        "convergence_15m": convergence,
    }


def write_outputs(state: dict, summary: dict) -> None:
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    with EVENTS_PATH.open("w") as out:
        for event in state["events"]:
            out.write(json.dumps(event, sort_keys=True) + "\n")
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


def main() -> None:
    contract = json.loads(CONTRACT_PATH.read_text())
    cohort_data = json.loads(COHORT_PATH.read_text())
    persistent = set(cohort_data.get("persistent_7d_top100", []))
    cohort = []
    for row in cohort_data["cohort"]:
        item = dict(row)
        item["persistent_7d_top100"] = item["wallet"] in persistent
        cohort.append(item)
    cohort_by_wallet = {x["wallet"]: x for x in cohort}

    state = restore_latest_state() or new_state(contract, cohort)
    if state["test_name"] != contract["test_name"]:
        raise RuntimeError("state_contract_mismatch")
    if [x["wallet"] for x in state["cohort"]] != [x["wallet"] for x in cohort]:
        raise RuntimeError("frozen_cohort_drift")

    index = public_json(f"{REPLAY}/index.json")
    hours = sorted(index.get("hours") or [])
    if not hours:
        raise RuntimeError("no_archive_hours")
    available = set(hours)
    latest_archive_end = hour_start_ts(hours[-1]) + 3600

    freeze_hour = hour_name(utc_ts(contract["frozen_at_utc"]))
    processed = set(state["processed_hours"])
    new_hours = [
        h for h in hours if h >= freeze_hour and h not in processed
    ][:MAX_CATCHUP_HOURS]

    print(json.dumps({
        "collector_phase": "catchup_plan",
        "new_hours": new_hours,
        "already_processed_hours": len(state["processed_hours"]),
        "natural_buy_count_before": len(state["events"]),
    }, sort_keys=True), flush=True)

    for h in new_hours:
        started = time.time()
        print(json.dumps({
            "collector_phase": "detection_hour_start",
            "hour": h,
            "natural_buy_count_before": len(state["events"]),
        }, sort_keys=True), flush=True)
        process_detection_hour(state, h, available, contract, cohort_by_wallet)
        state["processed_hours"].append(h)
        print(json.dumps({
            "collector_phase": "detection_hour_complete",
            "hour": h,
            "elapsed_seconds": round(time.time() - started, 3),
            "natural_buy_count_after": len(state["events"]),
        }, sort_keys=True), flush=True)

    label_started = time.time()
    print(json.dumps({
        "collector_phase": "label_mature_outcomes_start",
        "natural_buy_count": len(state["events"]),
    }, sort_keys=True), flush=True)
    label_mature_outcomes(
        state, latest_archive_end, available, contract
    )
    print(json.dumps({
        "collector_phase": "label_mature_outcomes_complete",
        "elapsed_seconds": round(time.time() - label_started, 3),
        "completed_outcome_count": sum(
            1 for event in state["events"] if event["outcome_complete"]
        ),
    }, sort_keys=True), flush=True)
    summary = summarize(state, contract)
    write_outputs(state, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
