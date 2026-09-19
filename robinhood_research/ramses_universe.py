"""Bounded all-pool Ramses universe scanner for Robinhood Chain.

The earlier Ramses proof intentionally watched only WNATIVE pairs.  Fee Pulse is
an all-pool strategy, so this module enumerates the authenticated Ramses factory,
observes recent finalized swap activity across every pool, constructs exact
pre-entry state only for the recently active cohort, and feeds those states into
the frozen strategy policy.

This is a screening/research plane.  It cannot sign, submit, reserve capital or
turn a screening log into allocation authority.  A selected pool still requires
the exact receipt/header/terminal replay path before its outcome is strategy
evidence.
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import threading
import time

from . import BoundaryError
from .abi import calldata, topic
from .identity import authenticate, load
from .ramses import authenticate_pool, decode_ramses_event, values
from .ramses_capture import BoundedMultiRpc, LOG_BLOCK_CHUNK, MAX_FACTORY_POOLS
from .ramses_strategy import (
    POLICY_HASH,
    STRATEGY_VERSION,
    STRATEGY_DOMAIN,
    attach_universe_percentiles,
    classify_pool,
    pool_features,
)

LOOKBACK_BLOCKS = 300
MAX_RECENT_ACTIVE_POOLS = 32
WATCH_COHORT_SIZE = 8
PAPER_ACTIVE_LIQUIDITY_BPS = 100  # 1%, always below the strategy's 10% ceiling.
MAX_SWAP_LOGS = 2500
REPORT = Path(os.environ.get(
    "MM_ROBINHOOD_RAMSES_UNIVERSE_REPORT",
    "robinhood-ramses-universe-report.json",
))

# Ramses factory membership is append-only. Repeated market screens still verify
# the finalized pair count and cached sentinels, but only fetch newly appended
# indices. This removes hundreds of redundant eth_call operations per screen
# without weakening pool discovery or point-in-time strategy evidence.
_FACTORY_INVENTORY_CACHE = {}
_FACTORY_INVENTORY_LOCK = threading.Lock()


def _batched_logs(rpc, start, end, addresses):
    if start > end or not addresses:
        return []
    sig = topic("Swap(address,address,uint24,bytes32,bytes32,uint24,bytes32,bytes32)")
    calls = []
    for first in range(start, end + 1, LOG_BLOCK_CHUNK):
        calls.append((
            "eth_getLogs",
            [dict(
                fromBlock=hex(first),
                toBlock=hex(min(end, first + LOG_BLOCK_CHUNK - 1)),
                address=list(addresses),
                topics=[sig],
            )],
        ))
    found = []
    for i in range(0, len(calls), 20):
        for page in rpc.batch(calls[i:i + 20], scope="universe_logs"):
            found.extend(page)
            if len(found) > MAX_SWAP_LOGS:
                raise BoundaryError("ramses_universe_swap_log_capacity")
    return found


def _factory_address(raw):
    if not isinstance(raw, str) or not raw.startswith("0x") or len(raw) < 42:
        raise BoundaryError("ramses_universe_factory_inventory")
    address = "0x" + raw[-40:].lower()
    try:
        value = int(address, 16)
    except ValueError:
        raise BoundaryError("ramses_universe_factory_inventory") from None
    if value == 0:
        raise BoundaryError("ramses_universe_factory_inventory")
    return address


def _enumerate_factory(rpc, factory, block):
    count_raw = rpc.call(
        "eth_call",
        [dict(to=factory, data=calldata("getNumberOfLBPairs()")), hex(block)],
        scope="universe_inventory",
    )
    count = values(count_raw)[0]
    if count <= 0 or count > MAX_FACTORY_POOLS:
        raise BoundaryError("ramses_universe_factory_count")

    key = str(factory).lower()
    with _FACTORY_INVENTORY_LOCK:
        cached = dict(_FACTORY_INVENTORY_CACHE.get(key) or {})
        cached_addresses = list(cached.get("addresses") or [])
        cached_block = cached.get("asof_block")

    if cached_block is not None and int(block) < int(cached_block):
        raise BoundaryError("ramses_universe_inventory_block_regression")
    if len(cached_addresses) > count:
        raise BoundaryError("ramses_universe_factory_count_regression")

    # Verify two immutable sentinels before trusting the cached prefix. A mismatch
    # fails closed instead of silently accepting a changed registry.
    sentinel_indices = []
    if cached_addresses:
        sentinel_indices = sorted(set((0, len(cached_addresses) - 1)))
        sentinel_rows = rpc.batch(
            [
                (
                    "eth_call",
                    [
                        dict(
                            to=factory,
                            data=calldata("getLBPairAtIndex(uint256)", i),
                        ),
                        hex(block),
                    ],
                )
                for i in sentinel_indices
            ],
            scope="universe_inventory_verify",
        )
        for i, raw in zip(sentinel_indices, sentinel_rows):
            if _factory_address(raw) != cached_addresses[i]:
                raise BoundaryError("ramses_universe_factory_inventory_changed")

    start_index = len(cached_addresses)
    missing_indices = list(range(start_index, count))
    appended = []
    if missing_indices:
        rows = rpc.batch(
            [
                (
                    "eth_call",
                    [
                        dict(
                            to=factory,
                            data=calldata("getLBPairAtIndex(uint256)", i),
                        ),
                        hex(block),
                    ],
                )
                for i in missing_indices
            ],
            scope="universe_inventory",
        )
        appended = [_factory_address(raw) for raw in rows]

    addresses = cached_addresses + appended
    if len(addresses) != count or len(set(addresses)) != len(addresses):
        raise BoundaryError("ramses_universe_factory_inventory")

    with _FACTORY_INVENTORY_LOCK:
        _FACTORY_INVENTORY_CACHE[key] = dict(
            addresses=tuple(addresses),
            asof_block=int(block),
        )

    setattr(rpc, "_roi_factory_inventory_cache_hit", bool(cached_addresses))
    setattr(rpc, "_roi_factory_inventory_reused", len(cached_addresses))
    setattr(rpc, "_roi_factory_inventory_fetched", len(appended))
    setattr(rpc, "_roi_factory_inventory_sentinel_reads", len(sentinel_indices))
    return addresses


def _decode_histories(logs, addresses):
    allowed = set(a.lower() for a in addresses)
    by_pool = {}
    for event in sorted(
        logs,
        key=lambda e: (
            int(e["blockNumber"], 16),
            int(e["transactionIndex"], 16),
            int(e["logIndex"], 16),
        ),
    ):
        address = event.get("address", "").lower()
        if address not in allowed or event.get("removed"):
            raise BoundaryError("ramses_universe_log_identity")
        decoded = decode_ramses_event(load("ramses_pool_implementation")["abi"], event)
        if decoded["name"] != "Swap":
            raise BoundaryError("ramses_universe_non_swap_log")
        by_pool.setdefault(address, []).append(dict(
            block=int(event["blockNumber"], 16),
            block_hash=event["blockHash"],
            transaction_hash=event["transactionHash"],
            transaction_index=int(event["transactionIndex"], 16),
            log_index=int(event["logIndex"], 16),
            args=decoded["args"],
        ))
    return by_pool


def _prestate(rpc, factory, address, block):
    calls = [
        ("eth_call", [dict(to=factory, data=calldata("isPool(address)", address)), hex(block)]),
        ("eth_getCode", [address, hex(block)]),
        ("eth_call", [dict(to=address, data=calldata("getLBHooksParameters()")), hex(block)]),
        ("eth_call", [dict(to=address, data=calldata("getActiveId()")), hex(block)]),
        ("eth_call", [dict(to=address, data=calldata("getReserves()")), hex(block)]),
        ("eth_call", [dict(to=address, data=calldata("getProtocolFees()")), hex(block)]),
        ("eth_call", [dict(to=address, data=calldata("getStaticFeeParameters()")), hex(block)]),
        ("eth_call", [dict(to=address, data=calldata("getVariableFeeParameters()")), hex(block)]),
    ]
    member, code, hooks, active_raw, reserves_raw, protocol_raw, static_raw, variable_raw = rpc.batch(
        calls, scope="universe_state"
    )
    if int(member, 16) != 1:
        raise BoundaryError("ramses_universe_pool_membership")
    auth = authenticate_pool(code, factory_member=True)
    if int(hooks, 16):
        raise BoundaryError("ramses_universe_hooks_unsupported")
    active = values(active_raw)[0]
    if not 3 <= active < 2**24 - 3:
        raise BoundaryError("ramses_universe_active_bin_boundary")
    bins = list(range(active - 3, active + 4))
    bin_calls = []
    for bid in bins:
        bin_calls.extend([
            ("eth_call", [dict(to=address, data=calldata("getBin(uint24)", bid)), hex(block)]),
            ("eth_call", [dict(to=address, data=calldata("totalSupply(uint256)", bid)), hex(block)]),
        ])
    raw = rpc.batch(bin_calls, scope="universe_bins")
    state = dict(
        active=active,
        step=auth["bin_step"],
        reserves=values(reserves_raw),
        protocol=values(protocol_raw),
        static=values(static_raw),
        variable=values(variable_raw),
        bins={},
    )
    for i, bid in enumerate(bins):
        state["bins"][bid] = dict(
            reserves=values(raw[2 * i]),
            supply=values(raw[2 * i + 1])[0],
        )
    return auth, state


def _selection_key(row):
    f = row["features"]
    return (
        int(f.get("turnover_percentile_bps") or 0),
        int(f.get("fee_percentile_bps") or 0),
        min(10000, int(f.get("chop_ratio_milli") or 0)),
        min(10000, int(f.get("volume_acceleration_milli") or 0)),
        -int(f.get("flow_imbalance_bps") or 10000),
        int(row.get("latest_swap_block") or 0),
        row["pool"],
    )


def scan(
    endpoint,
    *,
    lookback_blocks=LOOKBACK_BLOCKS,
    max_recent_active_pools=MAX_RECENT_ACTIVE_POOLS,
    gas_costs_by_pool=None,
    signals_by_pool=None,
):
    """Scan the complete factory and classify the bounded recently-active cohort."""
    if type(lookback_blocks) is not int or not 10 <= lookback_blocks <= 1200:
        raise BoundaryError("invalid_ramses_universe_lookback")
    if type(max_recent_active_pools) is not int or not 1 <= max_recent_active_pools <= 48:
        raise BoundaryError("invalid_ramses_universe_candidate_cap")
    gas_costs_by_pool = gas_costs_by_pool or {}
    signals_by_pool = signals_by_pool or {}
    if not isinstance(gas_costs_by_pool, dict) or not isinstance(signals_by_pool, dict):
        raise BoundaryError("invalid_ramses_universe_context")

    rpc = BoundedMultiRpc(endpoint, max_sessions=7, batch_size=20, batch_pause=0.5, rate_retries=1)
    started = time.time()
    rpc.verify_chain()
    frontier = rpc.call("eth_getBlockByNumber", ["finalized", False], scope="universe_frontier")
    end = int(frontier["number"], 16)
    start = max(0, end - lookback_blocks + 1)

    factory_pin = load("ramses_factory")
    factory = factory_pin["address"]
    factory_code = rpc.call("eth_getCode", [factory, hex(end)], scope="universe_identity")
    factory_identity = authenticate("ramses_factory", factory, factory_code)

    addresses = _enumerate_factory(rpc, factory, end)
    logs = _batched_logs(rpc, start, end, addresses)
    histories = _decode_histories(logs, addresses)

    # Candidate truncation is pre-entry and outcome-blind: retain the pools with
    # the densest recent finalized swap tape, breaking ties by latest activity.
    activity = []
    for address, rows in histories.items():
        activity.append(dict(
            pool=address,
            swaps=len(rows),
            latest_swap_block=max(r["block"] for r in rows),
        ))
    activity.sort(
        key=lambda r: (r["swaps"], r["latest_swap_block"], r["pool"]),
        reverse=True,
    )
    active_cohort = activity[:max_recent_active_pools]

    rows = []
    exclusions = Counter()
    for activity_row in active_cohort:
        address = activity_row["pool"]
        try:
            auth, prestate = _prestate(rpc, factory, address, end)
            feature = pool_features(prestate, histories[address], "y", pool=address)
            rows.append(dict(
                pool=address,
                quote_side="y",
                token_x=auth["token_x"],
                token_y=auth["token_y"],
                bin_step=auth["bin_step"],
                swap_count=activity_row["swaps"],
                latest_swap_block=activity_row["latest_swap_block"],
                prestate=prestate,
                prehistory=histories[address],
                features=feature,
            ))
        except BoundaryError as exc:
            exclusions[str(exc)] += 1

    features = [r["features"] for r in rows]
    for row in rows:
        row["features"] = attach_universe_percentiles(row["features"], features)

    classified = []
    for row in rows:
        f = row["features"]
        capital = max(1, f["active_liquidity_quote"] * PAPER_ACTIVE_LIQUIDITY_BPS // 10000)
        signal_context = signals_by_pool.get(row["pool"], {})
        if signal_context and not isinstance(signal_context, dict):
            raise BoundaryError("invalid_ramses_pool_signal_context")
        costs = gas_costs_by_pool.get(row["pool"])
        try:
            decision = classify_pool(
                row["prestate"],
                row["prehistory"],
                row["quote_side"],
                requested_capital=capital,
                entry_timestamp=int(frontier["timestamp"], 16),
                gas_costs=costs,
                universe_features=features,
                anchor_signal=signal_context.get("anchor"),
                directional_signal=signal_context.get("directional"),
                now=int(frontier["timestamp"], 16),
                pool=row["pool"],
            )
        except BoundaryError as exc:
            decision = dict(
                mode="no_trade",
                qualified=False,
                reasons=["strategy_construction:" + str(exc)],
                strategy_version=STRATEGY_VERSION,
                strategy_domain=STRATEGY_DOMAIN,
                policy_hash=POLICY_HASH,
                allocation_authority=False,
                freeze=None,
            )
        classified.append({
            "pool": row["pool"],
            "token_x": row["token_x"],
            "token_y": row["token_y"],
            "quote_side": row["quote_side"],
            "swap_count": row["swap_count"],
            "latest_swap_block": row["latest_swap_block"],
            "features": row["features"],
            # Preserve the exact finalized selector inputs in-memory for the
            # authenticated lifecycle handoff.  These are deliberately stripped
            # from public reports by compact_screen() below.
            "prestate": row["prestate"],
            "prehistory": row["prehistory"],
            "prestate_block": end,
            "prestate_block_hash": frontier["hash"],
            "prestate_timestamp": int(frontier["timestamp"], 16),
            "paper_capital_quote_raw": capital,
            "decision": decision,
            # Discovery logs are finalized but not individually receipt-authenticated.
            # This scanner ranks; it does not itself create strategy outcome evidence.
            "evidence_grade": "screening_only",
            "allocation_authority": False,
        })

    ranked = sorted(classified, key=_selection_key, reverse=True)
    watch = [r["pool"] for r in ranked[:WATCH_COHORT_SIZE]]
    no_swap_count = len(addresses) - len(histories)
    result = dict(
        kind="ramses_all_pool_universe_screen_v1",
        strategy_version=STRATEGY_VERSION,
        strategy_domain=STRATEGY_DOMAIN,
        policy_hash=POLICY_HASH,
        paper_only=True,
        allocation_authority=False,
        shared_allocator=False,
        cross_strategy_inputs=False,
        screening_only=True,
        chain_id=4663,
        factory=factory_identity,
        finalized_block=end,
        finalized_hash=frontier["hash"],
        finalized_timestamp=int(frontier["timestamp"], 16),
        lookback_start_block=start,
        lookback_blocks=end - start + 1,
        factory_pool_count=len(addresses),
        factory_inventory_cache=dict(
            hit=bool(getattr(rpc, "_roi_factory_inventory_cache_hit", False)),
            reused_pool_count=int(
                getattr(rpc, "_roi_factory_inventory_reused", 0) or 0
            ),
            fetched_pool_count=int(
                getattr(rpc, "_roi_factory_inventory_fetched", 0) or 0
            ),
            sentinel_reads=int(
                getattr(rpc, "_roi_factory_inventory_sentinel_reads", 0) or 0
            ),
            count_verified_each_scan=True,
            cached_prefix_sentinel_verified=True,
        ),
        pools_with_recent_swaps=len(histories),
        pools_without_recent_swaps=no_swap_count,
        active_state_candidates=len(active_cohort),
        state_complete_pools=len(classified),
        exclusions=dict(exclusions),
        total_swap_logs=len(logs),
        watch_cohort=watch,
        watch_cohort_rule=(
            "preentry lexicographic turnover percentile, fee percentile, chop, "
            "volume acceleration, lower flow imbalance, recency, address"
        ),
        rows=ranked,
        provider=rpc.telemetry(),
        started_at=started,
        ended_at=time.time(),
    )
    return result


def compact_screen(result):
    """Return a report-safe view without duplicating heavy selector state.

    Exact finalized prestate/prehistory remain in-memory on scan() rows for the
    lifecycle.  Public artifacts retain only the immutable state identity and
    concise strategy evidence.
    """
    if not isinstance(result, dict):
        raise BoundaryError("invalid_ramses_universe_report")
    compact = dict(result)
    compact_rows = []
    for row in result.get("rows", []):
        public = dict(row)
        prestate = public.pop("prestate", None)
        prehistory = public.pop("prehistory", None)
        public["prestate_retained_in_memory"] = prestate is not None
        public["prehistory_retained_in_memory"] = prehistory is not None
        public["prehistory_swap_count"] = (
            len(prehistory) if isinstance(prehistory, list) else None
        )
        compact_rows.append(public)
    compact["rows"] = compact_rows
    compact["heavy_selector_state_in_artifact"] = False
    return compact


def _json_env(name):
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        raise BoundaryError("invalid_" + name.lower()) from None
    return value


def main():
    result = scan(
        os.environ.get("MM_ROBINHOOD_READ_RPC_URL", ""),
        gas_costs_by_pool=_json_env("MM_ROBINHOOD_RAMSES_COSTS_BY_POOL_JSON"),
        signals_by_pool=_json_env("MM_ROBINHOOD_RAMSES_SIGNALS_BY_POOL_JSON"),
    )
    public_result = compact_screen(result)
    raw = json.dumps(public_result, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > 4_000_000:
        raise BoundaryError("ramses_universe_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps(dict(
        kind=result["kind"],
        finalized_block=result["finalized_block"],
        factory_pool_count=result["factory_pool_count"],
        pools_with_recent_swaps=result["pools_with_recent_swaps"],
        state_complete_pools=result["state_complete_pools"],
        watch_cohort=result["watch_cohort"],
        qualified=[
            dict(pool=r["pool"], mode=r["decision"]["mode"])
            for r in result["rows"] if r["decision"].get("qualified")
        ],
        provider=result["provider"],
    )))


if __name__ == "__main__":
    main()
