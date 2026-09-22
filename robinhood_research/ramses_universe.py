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
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from . import BoundaryError
from .abi import calldata, topic
from .identity import authenticate, load
from .ramses import authenticate_pool, decode_ramses_event, unpack, values
from .ramses_capture import BoundedMultiRpc, LOG_BLOCK_CHUNK, MAX_FACTORY_POOLS
from .ramses_costs import current_native_cycle, observe_receipt_gas, quote_native_cycle
from .ramses_quiet_strategy import (
    POLICY_HASH,
    STRATEGY_VERSION,
    STRATEGY_DOMAIN,
    USDG,
    attach_universe_percentiles,
    classify_pool,
    pool_features,
)
from .ramses_quiet_discovery import discover_quiet_mints

LOOKBACK_BLOCKS = 300
MAX_RECENT_ACTIVE_POOLS = 32
WATCH_COHORT_SIZE = 8
PAPER_ACTIVE_LIQUIDITY_BPS = 50  # 0.5%; v2 local-liquidity cap.
MAX_SWAP_LOGS = 2500
UNIVERSE_BATCH_SIZE = 8
UNIVERSE_BATCH_PAUSE_SECONDS = 0.8
UNIVERSE_RATE_RETRIES = 2
UNIVERSE_RATE_COOLDOWN_SECONDS = 8.0
FACTORY_FETCH_CHUNK = 8
FACTORY_CACHE = Path(os.environ.get(
    "MM_ROBINHOOD_RAMSES_FACTORY_CACHE",
    "robinhood-ramses-all-pool-inventory-cache.json",
))
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
    economic_topics = [
        topic("Swap(address,address,uint24,bytes32,bytes32,uint24,bytes32,bytes32)"),
        topic("DepositedToBins(address,address,uint256[],bytes32[])"),
        topic("WithdrawnFromBins(address,address,uint256[],bytes32[])"),
    ]
    calls = []
    for first in range(start, end + 1, LOG_BLOCK_CHUNK):
        calls.append((
            "eth_getLogs",
            [dict(
                fromBlock=hex(first),
                toBlock=hex(min(end, first + LOG_BLOCK_CHUNK - 1)),
                address=list(addresses),
                topics=[economic_topics],
            )],
        ))
    found = []
    for i in range(0, len(calls), 20):
        for page in rpc.batch(calls[i:i + 20], scope="universe_logs"):
            found.extend(page)
            if len(found) > MAX_SWAP_LOGS * 2:
                raise BoundaryError("ramses_universe_economic_log_capacity")
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


def _inventory_digest(addresses):
    raw=json.dumps(list(addresses),separators=(",",":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _load_durable_inventory(factory,runtime_sha256):
    try:
        row=json.loads(FACTORY_CACHE.read_text())
    except FileNotFoundError:
        return None
    except (OSError,ValueError,TypeError):
        return None
    addresses=row.get("addresses")
    if (
        row.get("kind")!="ramses_all_pool_inventory_cache_v1"
        or str(row.get("factory","")).lower()!=str(factory).lower()
        or row.get("factory_runtime_sha256")!=runtime_sha256
        or not isinstance(addresses,list)
        or row.get("count")!=len(addresses)
        or row.get("addresses_sha256")!=_inventory_digest(addresses)
        or len(set(addresses))!=len(addresses)
        or any(_factory_address(a)!=a.lower() for a in addresses)
    ):
        return None
    return dict(
        addresses=list(addresses),
        asof_block=int(row.get("asof_block") or 0),
    )


def _persist_durable_inventory(factory,runtime_sha256,block,addresses):
    row=dict(
        kind="ramses_all_pool_inventory_cache_v1",
        chain_id=4663,
        factory=str(factory).lower(),
        factory_runtime_sha256=runtime_sha256,
        count=len(addresses),
        asof_block=int(block),
        addresses=list(addresses),
        addresses_sha256=_inventory_digest(addresses),
    )
    raw=json.dumps(row,sort_keys=True,separators=(",",":")).encode()
    tmp=FACTORY_CACHE.with_suffix(FACTORY_CACHE.suffix+".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp,FACTORY_CACHE)


def _factory_calls(factory,indices,block):
    return [
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
        for i in indices
    ]


def _factory_rows(rpc,factory,indices,block,scope):
    """Read exact factory indices in small batches and isolate -32000 failures."""
    out=[]
    recoveries=int(getattr(rpc,"_roi_factory_batch_recoveries",0) or 0)
    for first in range(0,len(indices),FACTORY_FETCH_CHUNK):
        chunk=indices[first:first+FACTORY_FETCH_CHUNK]
        calls=_factory_calls(factory,chunk,block)
        try:
            rows=rpc.batch(calls,scope=scope)
        except BoundaryError as exc:
            if str(exc)!="provider_rpc_-32000":
                raise
            recoveries+=1
            rows=[]
            for index,call in zip(chunk,calls):
                try:
                    rows.append(rpc.call(call[0],call[1],scope=scope+"_isolated"))
                except BoundaryError as member_exc:
                    setattr(rpc,"_roi_factory_member_failure",dict(
                        index=int(index),
                        block=int(block),
                        boundary=str(member_exc),
                        scope=str(scope),
                    ))
                    raise BoundaryError(
                        "ramses_universe_factory_member_"
                        +str(index)+":"+str(member_exc)
                    ) from None
        if len(rows)!=len(chunk):
            raise BoundaryError("ramses_universe_factory_batch_shape")
        out.extend(rows)
    setattr(rpc,"_roi_factory_batch_recoveries",recoveries)
    return out


def _enumerate_factory(rpc, factory, block, *, factory_runtime_sha256=None):
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
    durable_hit=False
    if not cached and factory_runtime_sha256:
        durable=_load_durable_inventory(factory,factory_runtime_sha256)
        if durable is not None:
            cached=durable
            durable_hit=True

    cached_addresses = list(cached.get("addresses") or [])
    cached_block = cached.get("asof_block")

    if cached_block is not None and int(block) < int(cached_block):
        raise BoundaryError("ramses_universe_inventory_block_regression")
    if len(cached_addresses) > count:
        raise BoundaryError("ramses_universe_factory_count_regression")

    sentinel_indices = []
    if cached_addresses:
        sentinel_indices = sorted(set((0, len(cached_addresses) - 1)))
        sentinel_rows = _factory_rows(
            rpc,factory,sentinel_indices,block,"universe_inventory_verify"
        )
        for i, raw in zip(sentinel_indices, sentinel_rows):
            if _factory_address(raw) != cached_addresses[i]:
                raise BoundaryError("ramses_universe_factory_inventory_changed")

    start_index = len(cached_addresses)
    missing_indices = list(range(start_index, count))
    appended = []
    if missing_indices:
        rows = _factory_rows(
            rpc,factory,missing_indices,block,"universe_inventory"
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
    if factory_runtime_sha256:
        _persist_durable_inventory(
            factory,factory_runtime_sha256,block,addresses
        )

    setattr(rpc, "_roi_factory_inventory_cache_hit", bool(cached_addresses))
    setattr(rpc, "_roi_factory_inventory_durable_hit", bool(durable_hit))
    setattr(rpc, "_roi_factory_inventory_reused", len(cached_addresses))
    setattr(rpc, "_roi_factory_inventory_fetched", len(appended))
    setattr(rpc, "_roi_factory_inventory_sentinel_reads", len(sentinel_indices))
    return addresses


def _decode_economic_logs(logs, addresses):
    allowed = set(a.lower() for a in addresses)
    by_pool = {}
    cost_events = []
    category = {
        "Swap": "unwind",
        "DepositedToBins": "add_liquidity",
        "WithdrawnFromBins": "remove_liquidity",
    }
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
        name = decoded["name"]
        if name not in category:
            raise BoundaryError("ramses_universe_non_economic_log")
        cost_events.append(dict(
            pool=address,
            category=category[name],
            block=int(event["blockNumber"], 16),
            block_hash=event["blockHash"],
            transaction_hash=event["transactionHash"],
        ))
        if name != "Swap":
            continue
        by_pool.setdefault(address, []).append(dict(
            block=int(event["blockNumber"], 16),
            block_hash=event["blockHash"],
            transaction_hash=event["transactionHash"],
            transaction_index=int(event["transactionIndex"], 16),
            log_index=int(event["logIndex"], 16),
            args=decoded["args"],
        ))
    return by_pool, cost_events


def _decode_histories(logs, addresses):
    """Compatibility wrapper returning only strictly pre-entry Swap history."""
    histories, _cost_events = _decode_economic_logs(logs, addresses)
    return histories


def _authenticate_quiet_signal(rpc, signal, pool, finalized_block):
    """Promote index nomination to finalized on-chain evidence or fail closed."""
    if not isinstance(signal, dict):
        return None
    tx = str(signal.get("transaction_hash") or "").lower()
    if not tx.startswith("0x") or len(tx) != 66:
        raise BoundaryError("quiet_mint_transaction_identity")
    receipt = rpc.call(
        "eth_getTransactionReceipt", [tx], scope="quiet_signal_auth"
    )
    if not receipt or int(receipt.get("status", "0x0"), 16) != 1:
        raise BoundaryError("quiet_mint_receipt")
    block = int(receipt.get("blockNumber", "0x0"), 16)
    if block <= 0 or block > int(finalized_block):
        raise BoundaryError("quiet_mint_not_finalized")
    header = rpc.call(
        "eth_getBlockByNumber", [hex(block), False], scope="quiet_signal_auth"
    )
    if (
        not header
        or int(header.get("number", "0x0"), 16) != block
        or header.get("hash") != receipt.get("blockHash")
    ):
        raise BoundaryError("quiet_mint_header_identity")

    wanted_log = int(signal.get("log_index", -1))
    matches = []
    for event in receipt.get("logs") or []:
        if str(event.get("address") or "").lower() != str(pool).lower():
            continue
        if int(event.get("logIndex", "-0x1"), 16) != wanted_log:
            continue
        decoded = decode_ramses_event(
            load("ramses_pool_implementation")["abi"], event
        )
        if decoded["name"] == "DepositedToBins":
            matches.append((event, decoded["args"]))
    if len(matches) != 1:
        raise BoundaryError("quiet_mint_event_identity")
    event, args = matches[0]
    ids = [int(x) for x in args["ids"]]
    amounts = [unpack(x) for x in args["amounts"]]
    if ids != [int(x) for x in signal.get("bin_ids") or []]:
        raise BoundaryError("quiet_mint_bin_identity")
    expected = [[int(v[0]), int(v[1])] for v in (signal.get("amounts") or [])]
    if amounts != expected:
        raise BoundaryError("quiet_mint_amount_identity")
    out = dict(signal)
    out.update(
        finalized=True,
        block=block,
        block_hash=receipt["blockHash"],
        observed_at=int(header["timestamp"], 16),
        receipt_authenticated=True,
        index_evidence_only=False,
    )
    return out


def _prestate(rpc, factory, address, block, *, extra_bins=None):
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
    bins = sorted(set(range(active - 3, active + 4)) | {
        int(b) for b in (extra_bins or [])
    })
    if len(bins) > 200 or any(b < 0 or b >= 2**24 for b in bins):
        raise BoundaryError("ramses_universe_signal_bin_capacity")
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
    signal = row.get("quiet_mint_signal") or {}
    decision = row.get("decision") or {}
    f = row["features"]
    return (
        1 if decision.get("qualified") and decision.get("mode") == "quiet_mint" else 0,
        int(signal.get("observed_at") or 0),
        int(signal.get("prior_24h_swaps") or 0),
        int(f.get("active_liquidity_quote") or 0),
        row["pool"],
    )


def scan(
    endpoint,
    *,
    lookback_blocks=LOOKBACK_BLOCKS,
    max_recent_active_pools=MAX_RECENT_ACTIVE_POOLS,
    gas_costs_by_pool=None,
    signals_by_pool=None,
    cost_state=None,
    finalized_frontier=None,
):
    """Scan the complete factory and classify the bounded recently-active cohort."""
    if type(lookback_blocks) is not int or not 10 <= lookback_blocks <= 1200:
        raise BoundaryError("invalid_ramses_universe_lookback")
    if type(max_recent_active_pools) is not int or not 1 <= max_recent_active_pools <= 48:
        raise BoundaryError("invalid_ramses_universe_candidate_cap")
    gas_costs_by_pool = {
        str(k).lower(): v for k, v in (gas_costs_by_pool or {}).items()
    }
    signals_by_pool = {
        str(k).lower(): v for k, v in (signals_by_pool or {}).items()
    }
    cost_state = {} if cost_state is None else cost_state
    if not isinstance(gas_costs_by_pool, dict) or not isinstance(signals_by_pool, dict):
        raise BoundaryError("invalid_ramses_universe_context")

    rpc = BoundedMultiRpc(
        endpoint,
        max_sessions=7,
        batch_size=UNIVERSE_BATCH_SIZE,
        batch_pause=UNIVERSE_BATCH_PAUSE_SECONDS,
        rate_retries=UNIVERSE_RATE_RETRIES,
        rate_cooldown=UNIVERSE_RATE_COOLDOWN_SECONDS,
        adaptive_batch_floor=2,
    )
    started = time.time()
    rpc.verify_chain()
    if finalized_frontier is None:
        frontier = rpc.call(
            "eth_getBlockByNumber",
            ["finalized", False],
            scope="universe_frontier",
        )
        frontier_source = "scanner_rpc"
    else:
        if not isinstance(finalized_frontier, dict):
            raise BoundaryError("invalid_ramses_finalized_frontier")
        required = ("number", "hash", "timestamp", "parentHash")
        if any(not isinstance(finalized_frontier.get(k), str) for k in required):
            raise BoundaryError("invalid_ramses_finalized_frontier")
        try:
            end_probe = int(finalized_frontier["number"], 16)
            timestamp_probe = int(finalized_frontier["timestamp"], 16)
            int(finalized_frontier["hash"], 16)
            int(finalized_frontier["parentHash"], 16)
        except (TypeError, ValueError):
            raise BoundaryError("invalid_ramses_finalized_frontier") from None
        if (
            end_probe < 0
            or timestamp_probe <= 0
            or len(finalized_frontier["hash"]) != 66
            or len(finalized_frontier["parentHash"]) != 66
        ):
            raise BoundaryError("invalid_ramses_finalized_frontier")
        frontier = dict(finalized_frontier)
        frontier_source = "pinned_external_finalized_header"
    end = int(frontier["number"], 16)
    start = max(0, end - lookback_blocks + 1)

    # Public index nominates quiet-mint candidates; exact chain authentication
    # below is still mandatory before any candidate can qualify.
    auto_signals = discover_quiet_mints(now=int(frontier["timestamp"], 16))
    merged_signals = {str(k).lower(): dict(v) for k, v in auto_signals.items()}
    for key, value in signals_by_pool.items():
        if not isinstance(value, dict):
            raise BoundaryError("invalid_ramses_pool_signal_context")
        row = dict(merged_signals.get(str(key).lower()) or {})
        row.update(value)
        merged_signals[str(key).lower()] = row
    signals_by_pool = merged_signals

    factory_pin = load("ramses_factory")
    factory = factory_pin["address"]
    factory_code = rpc.call("eth_getCode", [factory, hex(end)], scope="universe_identity")
    factory_identity = authenticate("ramses_factory", factory, factory_code)

    addresses = _enumerate_factory(
        rpc,factory,end,
        factory_runtime_sha256=factory_identity["runtime_sha256"],
    )
    logs = _batched_logs(rpc, start, end, addresses)
    histories, cost_events = _decode_economic_logs(logs, addresses)
    observe_receipt_gas(rpc, cost_events, cost_state)

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
    # Quiet-mint signal pools are never dropped merely because they are locally
    # quiet; fill the remaining state budget with the most active pools.
    signal_pools = [
        p for p in sorted(signals_by_pool)
        if p in set(addresses)
    ]
    active_by_pool = {r["pool"]: r for r in activity}
    candidate_pools = list(signal_pools)
    for item in activity:
        if item["pool"] not in candidate_pools:
            candidate_pools.append(item["pool"])
        if len(candidate_pools) >= max_recent_active_pools:
            break
    candidate_pools = candidate_pools[:max_recent_active_pools]
    active_cohort = [
        active_by_pool.get(
            p,
            dict(pool=p, swaps=0, latest_swap_block=0),
        )
        for p in candidate_pools
    ]

    rows = []
    exclusions = Counter()
    for activity_row in active_cohort:
        address = activity_row["pool"]
        signal_context = signals_by_pool.get(address, {})
        quiet_nomination = (
            signal_context.get("quiet_mint")
            if isinstance(signal_context.get("quiet_mint"), dict)
            else signal_context
            if signal_context.get("kind") == "quiet_mint"
            else None
        )
        try:
            # Authenticate the public mint before using its geometry.
            authenticated_signal = (
                _authenticate_quiet_signal(rpc, quiet_nomination, address, end)
                if quiet_nomination is not None
                else None
            )
            extra_bins = (
                authenticated_signal.get("bin_ids")
                if authenticated_signal is not None else None
            )
            auth, prestate = _prestate(
                rpc, factory, address, end, extra_bins=extra_bins
            )
            if auth["token_y"].lower() == USDG:
                quote_side = "y"
            elif auth["token_x"].lower() == USDG:
                quote_side = "x"
            else:
                raise BoundaryError("quiet_mint_non_usdg")
            if authenticated_signal is not None:
                authenticated_signal["quote_side"] = quote_side
                authenticated_signal["quote_token"] = USDG
            history = histories.get(address, [])
            feature = pool_features(prestate, history, quote_side, pool=address)
            rows.append(dict(
                pool=address,
                quote_side=quote_side,
                token_x=auth["token_x"],
                token_y=auth["token_y"],
                bin_step=auth["bin_step"],
                swap_count=activity_row["swaps"],
                latest_swap_block=activity_row["latest_swap_block"],
                prestate=prestate,
                prehistory=history,
                features=feature,
                quiet_mint_signal=authenticated_signal,
            ))
        except BoundaryError as exc:
            exclusions[str(exc)] += 1

    features = [r["features"] for r in rows]
    for row in rows:
        row["features"] = attach_universe_percentiles(row["features"], features)

    native_costs = None
    native_cost_meta = dict(
        available=False,
        reason="no_active_pool_for_cost_acquisition",
    )
    if rows:
        native_costs, native_cost_meta = current_native_cycle(rpc, cost_state)

    classified = []
    for row in rows:
        f = row["features"]
        capital = max(1, f["active_liquidity_quote"] * PAPER_ACTIVE_LIQUIDITY_BPS // 10000)
        signal_context = signals_by_pool.get(row["pool"], {})
        if signal_context and not isinstance(signal_context, dict):
            raise BoundaryError("invalid_ramses_pool_signal_context")
        manual_costs = gas_costs_by_pool.get(row["pool"])
        if manual_costs is not None:
            costs = manual_costs
            cost_evidence = dict(
                available=True,
                source="explicit_manual_override",
                quote_costs=dict(manual_costs),
            )
        elif native_costs is None:
            costs = None
            cost_evidence = dict(native_cost_meta)
            cost_evidence["source"] = "automatic_onchain"
        else:
            try:
                costs, conversion_meta = quote_native_cycle(
                    rpc, factory, row, end, native_costs, cost_state
                )
                cost_evidence = dict(native_cost_meta)
                cost_evidence.update(
                    source="automatic_onchain",
                    conversion=conversion_meta,
                    available=bool(costs),
                )
                if costs is not None:
                    cost_evidence["quote_costs"] = dict(costs)
                elif "reason" not in cost_evidence:
                    cost_evidence["reason"] = conversion_meta.get(
                        "reason", "quote_conversion_unavailable"
                    )
            except BoundaryError as exc:
                costs = None
                cost_evidence = dict(
                    available=False,
                    source="automatic_onchain",
                    reason="cost_acquisition_boundary:" + str(exc),
                )
        try:
            decision = classify_pool(
                row["prestate"],
                row["prehistory"],
                row["quote_side"],
                requested_capital=capital,
                entry_timestamp=int(frontier["timestamp"], 16),
                gas_costs=costs,
                universe_features=features,
                quiet_mint_signal=row.get("quiet_mint_signal"),
                anchor_signal=None,
                directional_signal=None,
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
            "gas_costs": (dict(costs) if isinstance(costs, dict) else None),
            "cost_evidence": cost_evidence,
            "quiet_mint_signal": deepcopy(row.get("quiet_mint_signal")),
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
        finalized_frontier_source=frontier_source,
        lookback_start_block=start,
        lookback_blocks=end - start + 1,
        factory_pool_count=len(addresses),
        factory_inventory_cache=dict(
            hit=bool(getattr(rpc, "_roi_factory_inventory_cache_hit", False)),
            durable_hit=bool(
                getattr(rpc, "_roi_factory_inventory_durable_hit", False)
            ),
            durable_cache_path=str(FACTORY_CACHE),
            batch_recoveries=int(
                getattr(rpc, "_roi_factory_batch_recoveries", 0) or 0
            ),
            member_failure=getattr(rpc, "_roi_factory_member_failure", None),
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
        total_swap_logs=sum(len(v) for v in histories.values()),
        total_economic_logs=len(logs),
        cost_model=dict(
            available=bool(native_costs),
            sample_counts=native_cost_meta.get("sample_counts"),
            proxy_categories=native_cost_meta.get("proxy_categories"),
            transactions_observed=native_cost_meta.get("transactions_observed"),
            gas_price_native_raw=native_cost_meta.get("gas_price_native_raw"),
        ),
        pools_with_automatic_cost_evidence=sum(
            1 for r in classified
            if (r.get("cost_evidence") or {}).get("source") == "automatic_onchain"
            and (r.get("cost_evidence") or {}).get("available")
        ),
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
