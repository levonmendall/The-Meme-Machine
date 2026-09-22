"""Public Ramses quiet-mint discovery for the v2 paper strategy.

The GraphQL index is used only to nominate a candidate and compute trailing swap
counts. A candidate has no strategy authority until ramses_universe independently
authenticates its finalized transaction receipt/log and pool state on chain.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
import json
import threading
import time
import urllib.request

from . import BoundaryError

ENDPOINT = "https://gateway.kingdom.dev/robinhood/subgraph/v1/graphql"
CHAIN = 4663
PAGE = 1000
MAX_SIGNAL_AGE_SECONDS = 120
LOOKBACK_SECONDS = 24 * 3600
_CACHE_LOCK = threading.Lock()
_CACHE = {"at": 0.0, "signals": {}}
CACHE_TTL_SECONDS = 30


def _addr(value):
    return str(value or "").split(":")[-1].lower()


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _gql(query, variables=None):
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "meme-machine-ramses-quiet-discovery/1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = json.loads(response.read())
    except Exception as exc:
        raise BoundaryError("ramses_quiet_index_unavailable") from exc
    if payload.get("errors"):
        raise BoundaryError("ramses_quiet_index_error")
    return payload.get("data") or {}


def _page(root, fields, *, start_timestamp):
    rows = []
    offset = 0
    while True:
        query = f"""query($limit:Int!,$offset:Int!){{{root}(
          limit:$limit,offset:$offset,
          where:{{chainId:{{_eq:{CHAIN}}},timestamp:{{_gte:{int(start_timestamp)}}}}},
          order_by:{{id:asc}}){{{fields}}}}}"""
        part = _gql(query, {"limit": PAGE, "offset": offset}).get(root) or []
        rows.extend(part)
        if len(part) < PAGE:
            return rows
        offset += PAGE
        if offset > 100000:
            raise BoundaryError("ramses_quiet_index_capacity")


def _count(rows, start, end):
    return bisect_left(rows, int(end)) - bisect_left(rows, int(start))


def discover_quiet_mints(*, now=None, max_signal_age_seconds=MAX_SIGNAL_AGE_SECONDS):
    now = int(time.time() if now is None else now)
    if type(max_signal_age_seconds) is not int or not 1 <= max_signal_age_seconds <= 600:
        raise BoundaryError("ramses_quiet_signal_age")

    with _CACHE_LOCK:
        if (
            _CACHE["signals"]
            and time.monotonic() - float(_CACHE["at"]) < CACHE_TTL_SECONDS
        ):
            return {k: dict(v) for k, v in _CACHE["signals"].items()}

    swap_start = now - LOOKBACK_SECONDS - max_signal_age_seconds
    mint_start = now - max_signal_age_seconds
    swaps = _page(
        "DLMMSwap",
        "id timestamp pool transaction logIndex",
        start_timestamp=swap_start,
    )
    mints = _page(
        "DLMMMint",
        "id timestamp pool recipient sender amountUSD totalAmountX totalAmountY "
        "binIds amountsX amountsY transaction logIndex",
        start_timestamp=mint_start,
    )

    by_pool = defaultdict(list)
    for row in swaps:
        pool = _addr(row.get("pool"))
        ts = _int(row.get("timestamp"))
        if pool and ts > 0:
            by_pool[pool].append(ts)
    for rows in by_pool.values():
        rows.sort()

    candidates = {}
    for mint in mints:
        pool = _addr(mint.get("pool"))
        ts = _int(mint.get("timestamp"))
        if not pool or ts <= 0 or ts > now or now-ts > max_signal_age_seconds:
            continue
        rows = by_pool.get(pool, [])
        prior_30m = _count(rows, ts-1800, ts)
        prior_24h = _count(rows, ts-LOOKBACK_SECONDS, ts)
        if prior_30m > 2 or prior_24h < 10:
            continue
        ids = [_int(x) for x in (mint.get("binIds") or [])]
        xs = [_int(x) for x in (mint.get("amountsX") or [])]
        ys = [_int(x) for x in (mint.get("amountsY") or [])]
        if not ids or len(ids) != len(xs) or len(ids) != len(ys):
            continue
        tx = str(mint.get("transaction") or "").split(":")[-1].lower()
        if not tx.startswith("0x") or len(tx) != 66:
            continue
        signal = {
            "kind": "quiet_mint",
            "source_class": "ramses_public_finalized_mint",
            # finalized is deliberately False until universe RPC authentication.
            "finalized": False,
            "pool": pool,
            "observed_at": ts,
            "transaction_hash": tx,
            "log_index": _int(mint.get("logIndex")),
            "bin_ids": ids,
            "amounts": [[x, y] for x, y in zip(xs, ys)],
            "prior_30m_swaps": prior_30m,
            "prior_24h_swaps": prior_24h,
            "index_evidence_only": True,
            "allocation_authority": False,
        }
        prior = candidates.get(pool)
        if prior is None or (
            signal["observed_at"], signal["log_index"], signal["transaction_hash"]
        ) > (
            prior["observed_at"], prior["log_index"], prior["transaction_hash"]
        ):
            candidates[pool] = signal

    with _CACHE_LOCK:
        _CACHE["at"] = time.monotonic()
        _CACHE["signals"] = {k: dict(v) for k, v in candidates.items()}
    return candidates
