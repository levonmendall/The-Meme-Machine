"""Read-only HANSEM FomoScan timestamp validation.

This probe is isolated from ordinary CI/trading authority. It calls only HANSEM's
free fomo.rankings capability and tests current, one-hour-old, and ancient epoch-ms
'at' values for the three token boards.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://api.hansem.io/v1/skills/run"
BOARDS = ("trending", "most_held", "graduated")
REPORT = Path("hansem-fomoscan-probe-report.json")


def _call(key, board, at=None):
    payload = {"skill": "fomo.rankings", "input": {"board": board}}
    if at is not None:
        payload["input"]["at"] = int(at)
    req = urllib.request.Request(
        BASE,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read(2_000_001)
            if len(raw) > 2_000_000:
                raise RuntimeError("hansem_response_size_limit")
            return {"status": int(r.status), "body": json.loads(raw)}
    except urllib.error.HTTPError as e:
        raw = e.read(64_000)
        try:
            body = json.loads(raw)
        except Exception:
            body = {"error": raw.decode("utf-8", "replace")[:1000]}
        return {"status": int(e.code), "body": body}


def _result(resp):
    body = resp.get("body")
    if isinstance(body, dict) and "result" in body:
        return body["result"]
    return body


def _find_timestamp(obj):
    if isinstance(obj, dict):
        for k in ("at", "capturedAt", "captured_at", "sampledAt", "sampled_at",
                  "timestamp", "snapshotAt", "snapshot_at", "fetched_at"):
            v = obj.get(k)
            if isinstance(v, (int, float, str)) and v not in ("", None):
                return v
        for v in obj.values():
            out = _find_timestamp(v)
            if out is not None:
                return out
    elif isinstance(obj, list):
        for v in obj[:5]:
            out = _find_timestamp(v)
            if out is not None:
                return out
    return None


def _canonical_rows(obj):
    """Extract stable rank/token identity pairs without depending on one envelope."""
    rows = []
    def walk(v):
        if isinstance(v, list):
            for x in v:
                if isinstance(x, dict):
                    rank = x.get("rank")
                    token = x.get("token") if isinstance(x.get("token"), dict) else {}
                    addr = (
                        x.get("mint") or x.get("address") or x.get("tokenAddress") or
                        x.get("token_address") or token.get("address") or token.get("mint")
                    )
                    if rank is not None or addr is not None:
                        rows.append((rank, addr))
                if len(rows) < 100:
                    walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                if len(rows) < 100:
                    walk(x)
    walk(obj)
    # Dedup while preserving order.
    seen = set()
    out = []
    for row in rows:
        key = json.dumps(row, default=str)
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out[:100]


def _fingerprint(obj):
    payload = json.dumps(_canonical_rows(obj), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _summary(resp):
    result = _result(resp)
    return {
        "http_status": resp["status"],
        "provider_timestamp": _find_timestamp(result),
        "row_count_detected": len(_canonical_rows(result)),
        "fingerprint": _fingerprint(result) if resp["status"] == 200 else None,
        "top_level_keys": sorted(result.keys())[:30] if isinstance(result, dict) else None,
        "error": (
            result.get("error") or result.get("message")
            if isinstance(result, dict) and resp["status"] != 200
            else None
        ),
    }


def main():
    key = os.environ.get("HANSEM_API_KEY", "")
    if not key:
        print("HANSEM_API_KEY secret is unavailable", file=sys.stderr)
        return 2

    now_ms = int(time.time() * 1000)
    one_hour_ms = now_ms - 3_600_000
    ancient_ms = 1

    report = {
        "probe_version": "hansem-fomoscan-at-v1",
        "provider": "hansem.io/fomo.rankings",
        "read_only": True,
        "trading_authority": False,
        "solana_rpc_calls": 0,
        "requested": {
            "current": None,
            "one_hour_old": one_hour_ms,
            "ancient": ancient_ms,
        },
        "boards": {},
    }

    for board in BOARDS:
        current = _call(key, board)
        one_hour = _call(key, board, one_hour_ms)
        ancient = _call(key, board, ancient_ms)

        sc = _summary(current)
        sh = _summary(one_hour)
        sa = _summary(ancient)

        if any(x["http_status"] != 200 for x in (sc, sh, sa)):
            classification = "request_failed_or_capability_unavailable"
        elif (
            sc["fingerprint"] == sh["fingerprint"] == sa["fingerprint"]
            and sc["provider_timestamp"] == sh["provider_timestamp"] == sa["provider_timestamp"]
        ):
            classification = "at_ignored"
        elif (
            sh["fingerprint"] != sc["fingerprint"]
            and sa["fingerprint"] != sc["fingerprint"]
        ):
            classification = "at_materially_changes_snapshot"
        else:
            classification = "ambiguous_requires_manual_review"

        report["boards"][board] = {
            "current": sc,
            "one_hour_old": sh,
            "ancient": sa,
            "classification": classification,
        }

    report["all_three_support_historical_at"] = all(
        b["classification"] == "at_materially_changes_snapshot"
        for b in report["boards"].values()
    )
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))

    if not report["all_three_support_historical_at"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
