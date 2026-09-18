"""One-shot, read-only FomoAPI validation probe.

This is intentionally separate from ordinary CI and trading authority. It consumes
only FomoAPI free-key capacity when explicitly triggered and never calls Solana RPC,
creates orders, changes qualification, or enables DLMM.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from meme_machine import pump

BASE = "https://api.fomoapi.io"
BOARDS = ("trending", "most-held", "graduated")
REPORT = Path("fomoapi-probe-report.json")
SOLANA_NETWORKS = {"solana", "solana-mainnet", "1399811149"}


def _request(path, params=None, api_key=None):
    query = urllib.parse.urlencode(params or {})
    url = BASE + path + (("?" + query) if query else "")
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise RuntimeError("fomoapi_response_size_limit")
            data = json.loads(raw)
            return {
                "status": int(response.status),
                "data": data,
                "credit_cost": response.headers.get("x-credits-cost"),
                "credits_remaining": response.headers.get("x-credits-remaining"),
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read(32_000)
        try:
            body = json.loads(raw)
        except Exception:
            body = {"error": raw.decode("utf-8", "replace")[:500]}
        return {
            "status": int(exc.code),
            "data": body,
            "credit_cost": exc.headers.get("x-credits-cost"),
            "credits_remaining": exc.headers.get("x-credits-remaining"),
        }


def _tokens(data):
    if not isinstance(data, dict):
        return []
    value = data.get("tokens")
    return value if isinstance(value, list) else []


def _mint(row):
    token = row.get("token") if isinstance(row, dict) else None
    if isinstance(token, dict) and token.get("address"):
        return token["address"]
    return row.get("address") if isinstance(row, dict) else None


def _is_solana(row):
    network = row.get("network") if isinstance(row, dict) else None
    if isinstance(network, dict):
        network = network.get("name") or network.get("id")
    if network is None:
        return False
    return str(network).lower() in SOLANA_NETWORKS


def _validate_solana_mint(value):
    if not isinstance(value, str):
        return False
    try:
        raw = pump.un58(value)
    except ValueError:
        return False
    return len(raw) == 32


def _fingerprint(data):
    rows = []
    for row in _tokens(data):
        rows.append((row.get("rank"), _mint(row), str(row.get("network"))))
    payload = {
        "board": data.get("board") if isinstance(data, dict) else None,
        "capturedAt": data.get("capturedAt") if isinstance(data, dict) else None,
        "rows": rows,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _epoch_ms(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except Exception:
        return None


def _safe_board_summary(name, response):
    data = response["data"]
    rows = _tokens(data)
    solana = [row for row in rows if _is_solana(row)]
    malformed_solana = []
    for row in solana:
        mint = _mint(row)
        if not _validate_solana_mint(mint):
            malformed_solana.append({"rank": row.get("rank"), "mint": mint})
    ranks_valid = all(
        isinstance(row.get("rank"), int) and row.get("rank") > 0
        for row in rows
    )
    return {
        "board": name,
        "http_status": response["status"],
        "available": None if not isinstance(data, dict) else data.get("available", True),
        "captured_at": None if not isinstance(data, dict) else data.get("capturedAt"),
        "source": None if not isinstance(data, dict) else data.get("source"),
        "stale": None if not isinstance(data, dict) else data.get("stale"),
        "token_count": len(rows),
        "solana_token_count": len(solana),
        "all_ranks_valid": ranks_valid,
        "malformed_solana_rows": malformed_solana,
        "credit_cost": response["credit_cost"],
        "credits_remaining": response["credits_remaining"],
        "fingerprint": _fingerprint(data) if isinstance(data, dict) else None,
    }


def _numeric_credit(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def main():
    key = os.environ.get("FOMOAPI_KEY", "")
    if not key:
        print("FOMOAPI_KEY secret is unavailable", file=sys.stderr)
        return 2

    responses = {}
    summaries = {}
    for board in BOARDS:
        response = _request(
            f"/v2/leaderboard/tokens/{board}",
            {"limit": 50},
            key,
        )
        responses[board] = response
        summaries[board] = _safe_board_summary(board, response)

    trending = responses["trending"]
    current_data = trending["data"] if isinstance(trending["data"], dict) else {}
    current_captured_ms = _epoch_ms(current_data.get("capturedAt"))
    one_hour_ago_ms = (
        current_captured_ms - 3_600_000
        if current_captured_ms is not None
        else int((time.time() - 3600) * 1000)
    )

    at_hour = _request(
        "/v2/leaderboard/tokens/trending",
        {"limit": 50, "at": one_hour_ago_ms},
        key,
    )
    at_epoch = _request(
        "/v2/leaderboard/tokens/trending",
        {"limit": 50, "at": 1},
        key,
    )

    current_fp = _fingerprint(current_data)
    hour_data = at_hour["data"] if isinstance(at_hour["data"], dict) else {}
    epoch_data = at_epoch["data"] if isinstance(at_epoch["data"], dict) else {}
    hour_fp = _fingerprint(hour_data) if hour_data else None
    epoch_fp = _fingerprint(epoch_data) if epoch_data else None
    current_at = current_data.get("capturedAt")
    hour_at = hour_data.get("capturedAt")
    epoch_at = epoch_data.get("capturedAt")

    if at_hour["status"] >= 400 or at_epoch["status"] >= 400:
        at_behavior = "rejected_or_unsupported"
    elif (
        at_hour["status"] == 200
        and at_epoch["status"] == 200
        and hour_at == current_at
        and epoch_at == current_at
        and hour_fp == current_fp
        and epoch_fp == current_fp
    ):
        at_behavior = "ignored"
    else:
        hour_ms = _epoch_ms(hour_at)
        if (
            hour_ms is not None
            and abs(hour_ms - one_hour_ago_ms) <= 10 * 60 * 1000
            and hour_ms < (current_captured_ms or hour_ms + 1)
        ):
            at_behavior = "appears_honored"
        else:
            at_behavior = "ambiguous_not_safe_for_replay"

    trader_boards = {}
    trader_calls = []
    for window in ("24h", "7d", "30d"):
        response = _request(f"/v2/leaderboard/{window}", {"limit": 10}, key)
        trader_calls.append(response)
        data = response["data"] if isinstance(response["data"], dict) else {}
        rows = data.get("traders") if isinstance(data.get("traders"), list) else []
        trader_boards[window] = {
            "http_status": response["status"],
            "credit_cost": response["credit_cost"],
            "credits_remaining": response["credits_remaining"],
            "top": [
                {
                    "rank": row.get("rank", index + 1),
                    "handle": row.get("handle"),
                    "display_name": row.get("displayName"),
                    "pnl_usd": row.get("pnlUsd"),
                    "volume_usd": row.get("volumeUsd"),
                    "trades": row.get("trades"),
                    "followers": row.get("followers"),
                    "verified": bool(row.get("verified")),
                }
                for index, row in enumerate(rows[:10])
            ],
        }

    all_calls = list(responses.values()) + [at_hour, at_epoch] + trader_calls
    observed_credit_cost = sum(_numeric_credit(x["credit_cost"]) for x in all_calls)

    report = {
        "probe_version": "fomoapi-live-validation-v1",
        "provider": "fomoapi.io",
        "base_url": BASE,
        "read_only": True,
        "solana_rpc_calls": 0,
        "trading_authority": False,
        "order_authority": False,
        "dlmm_authority": False,
        "boards": summaries,
        "current_trader_leaderboards": trader_boards,
        "historical_at_test": {
            "requested_one_hour_ago_epoch_ms": one_hour_ago_ms,
            "current_status": trending["status"],
            "current_captured_at": current_at,
            "one_hour_status": at_hour["status"],
            "one_hour_captured_at": hour_at,
            "one_hour_same_fingerprint": hour_fp == current_fp,
            "epoch_one_status": at_epoch["status"],
            "epoch_one_captured_at": epoch_at,
            "epoch_one_same_fingerprint": epoch_fp == current_fp,
            "classification": at_behavior,
        },
        "credits": {
            "calls_made": len(all_calls),
            "observed_total_x_credits_cost": observed_credit_cost,
            "per_call_x_credits_cost": [x["credit_cost"] for x in all_calls],
            "last_x_credits_remaining": all_calls[-1]["credits_remaining"],
        },
        "usable_for_prospective_capture": (
            all(s["http_status"] == 200 for s in summaries.values())
            and any(s["solana_token_count"] > 0 for s in summaries.values())
            and all(not s["malformed_solana_rows"] for s in summaries.values())
        ),
        "safe_for_retrospective_replay": at_behavior == "appears_honored",
    }

    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))

    if not all(s["http_status"] == 200 for s in summaries.values()):
        return 3
    if any(s["malformed_solana_rows"] for s in summaries.values()):
        return 4
    if not all(x["http_status"] == 200 for x in trader_boards.values()):
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
