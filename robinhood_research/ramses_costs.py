"""Automatic Ramses paper-cost evidence from finalized on-chain observations.

This module never signs or submits.  It learns gas-unit usage from finalized
Ramses economic transactions, prices those units at the current read-only gas
price, and converts the native cycle cost into each candidate pool's quote token
through an executable direct Ramses WNATIVE route.

Missing operation categories use a conservative 2x worst-observed Ramses gas
unit proxy.  If no Ramses gas sample or no executable direct conversion exists,
cost evidence remains unavailable and strategy qualification fails closed.
"""
from __future__ import annotations

from copy import deepcopy

from . import BoundaryError
from .abi import calldata, scalar, words
from .identity import authenticate, load
from .ramses import authenticate_pool, values

COST_MODEL_VERSION = "ramses-receipt-cost-v1"
SAMPLE_LIMIT = 256
PROXY_MULTIPLIER_BPS = 20000
CATEGORIES = ("add_liquidity", "remove_liquidity", "unwind")


def _p75(values):
    rows = sorted(int(v) for v in values if type(v) is int and v > 0)
    if not rows:
        return None
    return rows[max(0, (len(rows) * 3 + 3) // 4 - 1)]


def _state(state):
    if state is None:
        state = {}
    if not isinstance(state, dict):
        raise BoundaryError("ramses_cost_state_shape")
    state.setdefault("transactions", {})
    state.setdefault("samples", {k: [] for k in CATEGORIES})
    state.setdefault("credited", {k: {} for k in CATEGORIES})
    if (
        not isinstance(state["transactions"], dict)
        or not isinstance(state["samples"], dict)
        or not isinstance(state["credited"], dict)
    ):
        raise BoundaryError("ramses_cost_state_shape")
    for category in CATEGORIES:
        if not isinstance(state["samples"].setdefault(category, []), list):
            raise BoundaryError("ramses_cost_state_shape")
        if not isinstance(state["credited"].setdefault(category, {}), dict):
            raise BoundaryError("ramses_cost_state_shape")
    return state


def observe_receipt_gas(rpc, cost_events, state=None):
    """Accumulate gasUsed samples from finalized Ramses economic transactions."""
    state = _state(state)
    by_tx = {}
    for row in cost_events or []:
        if not isinstance(row, dict):
            raise BoundaryError("ramses_cost_event_shape")
        category = row.get("category")
        if category not in CATEGORIES:
            raise BoundaryError("ramses_cost_event_category")
        tx = row.get("transaction_hash")
        block_hash = row.get("block_hash")
        if not isinstance(tx, str) or not isinstance(block_hash, str):
            raise BoundaryError("ramses_cost_event_identity")
        item = by_tx.setdefault(tx, {"block_hash": block_hash, "categories": set()})
        if item["block_hash"] != block_hash:
            raise BoundaryError("ramses_cost_transaction_block_conflict")
        item["categories"].add(category)

    missing = [
        (tx, item["block_hash"])
        for tx, item in by_tx.items()
        if tx not in state["transactions"]
    ]
    if missing:
        receipts = rpc.receipts(missing, scope="universe_cost_receipts")
        for (tx, block_hash), receipt in zip(missing, receipts):
            try:
                gas_used = int(receipt["gasUsed"], 16)
            except (KeyError, TypeError, ValueError):
                raise BoundaryError("ramses_cost_receipt_gas_missing") from None
            if gas_used <= 0:
                raise BoundaryError("ramses_cost_receipt_gas_invalid")
            state["transactions"][tx] = {
                "block_hash": block_hash,
                "gas_used": gas_used,
            }

    for tx, item in by_tx.items():
        meta = state["transactions"].get(tx)
        if not meta or meta.get("block_hash") != item["block_hash"]:
            raise BoundaryError("ramses_cost_transaction_identity")
        gas_used = int(meta["gas_used"])
        for category in item["categories"]:
            if tx in state["credited"][category]:
                continue
            state["credited"][category][tx] = True
            state["samples"][category].append(gas_used)
            if len(state["samples"][category]) > SAMPLE_LIMIT:
                state["samples"][category] = state["samples"][category][-SAMPLE_LIMIT:]
    return state


def current_native_cycle(rpc, state):
    """Return conservative native-denominated cycle costs at current gas price."""
    state = _state(state)
    all_samples = [
        int(v)
        for category in CATEGORIES
        for v in state["samples"][category]
        if type(v) is int and v > 0
    ]
    if not all_samples:
        return None, {
            "available": False,
            "reason": "no_ramses_gas_samples",
            "model_version": COST_MODEL_VERSION,
        }

    gas_price_raw = rpc.call("eth_gasPrice", [], scope="universe_cost_price")
    try:
        gas_price = int(gas_price_raw, 16)
    except (TypeError, ValueError):
        raise BoundaryError("ramses_cost_gas_price") from None
    if gas_price <= 0:
        raise BoundaryError("ramses_cost_gas_price")

    worst = max(all_samples)
    proxy = max(1, worst * PROXY_MULTIPLIER_BPS // 10000)
    gas_units = {}
    proxy_categories = []
    for category in CATEGORIES:
        estimate = _p75(state["samples"][category])
        if estimate is None:
            estimate = proxy
            proxy_categories.append(category)
        gas_units[category] = estimate

    # One additional conservative transaction-equivalent overhead covers
    # approval/setup/entry bookkeeping not separately visible in pool events.
    gas_units["entry_overhead"] = worst
    native = {
        key: int(units) * gas_price
        for key, units in gas_units.items()
    }
    return native, {
        "available": True,
        "model_version": COST_MODEL_VERSION,
        "gas_price_native_raw": gas_price,
        "gas_units": dict(gas_units),
        "sample_counts": {
            category: len(state["samples"][category])
            for category in CATEGORIES
        },
        "proxy_categories": proxy_categories,
        "proxy_multiplier_bps": PROXY_MULTIPLIER_BPS,
        "native_cycle_cost_raw": sum(native.values()),
        "transactions_observed": len(state["transactions"]),
    }


def _decode_pairs(raw):
    ws = words(raw)
    if len(ws) < 2 or int.from_bytes(ws[0], "big") != 32:
        raise BoundaryError("ramses_cost_pair_array_shape")
    count = int.from_bytes(ws[1], "big")
    if count > 64 or len(ws) != 2 + 4 * count:
        raise BoundaryError("ramses_cost_pair_array_shape")
    out = []
    pos = 2
    for _ in range(count):
        step = scalar("uint16", ws[pos])
        pair = scalar("address", ws[pos + 1])
        created = scalar("bool", ws[pos + 2])
        ignored = scalar("bool", ws[pos + 3])
        pos += 4
        out.append({
            "bin_step": step,
            "pool": pair.lower(),
            "created_by_owner": created,
            "ignored_for_routing": ignored,
        })
    return out


def _wnative(rpc, block, state):
    state = _state(state)
    cached = state.get("wnative")
    if cached:
        return cached
    router_pin = load("ramses_router")
    router = router_pin["address"]
    code, raw = rpc.batch(
        [
            ("eth_getCode", [router, hex(block)]),
            ("eth_call", [dict(to=router, data=calldata("getWNATIVE()")), hex(block)]),
        ],
        scope="universe_cost_identity",
    )
    authenticate("ramses_router", router, code)
    value = "0x" + raw[-40:].lower()
    if int(value, 16) == 0:
        raise BoundaryError("ramses_cost_wnative")
    state["wnative"] = value
    return value


def _candidate_route_quote(rpc, pool, token_x, token_y, wnative, amount, block):
    if token_y.lower() == wnative:
        return {
            "amount_out": amount,
            "route_pool": None,
            "route_kind": "quote_is_wnative",
            "swap_for_y": None,
        }
    if token_x.lower() != wnative:
        return None
    if amount >= 2**128:
        raise BoundaryError("ramses_cost_native_amount_capacity")
    raw = rpc.call(
        "eth_call",
        [
            dict(
                to=pool,
                data=calldata("getSwapOut(uint128,bool)", amount, 1),
            ),
            hex(block),
        ],
        scope="universe_cost_conversion",
    )
    q = values(raw)
    if len(q) < 3 or q[0] != 0 or q[1] <= 0:
        return None
    return {
        "amount_out": q[1],
        "route_pool": pool,
        "route_kind": "candidate_wnative_quote_pool",
        "swap_for_y": True,
        "route_fee_raw": q[2],
    }


def _factory_direct_routes(rpc, factory, wnative, quote, amount, block):
    if amount >= 2**128:
        raise BoundaryError("ramses_cost_native_amount_capacity")
    raw = rpc.call(
        "eth_call",
        [
            dict(
                to=factory,
                data=calldata("getAllLBPairs(address,address)", wnative, quote),
            ),
            hex(block),
        ],
        scope="universe_cost_route",
    )
    pairs = [p for p in _decode_pairs(raw) if not p["ignored_for_routing"]]
    if not pairs:
        return []

    auth_calls = []
    for item in pairs:
        auth_calls.extend([
            ("eth_getCode", [item["pool"], hex(block)]),
            (
                "eth_call",
                [dict(to=item["pool"], data=calldata("getLBHooksParameters()")), hex(block)],
            ),
        ])
    auth_raw = rpc.batch(auth_calls, scope="universe_cost_route")
    candidates = []
    for i, item in enumerate(pairs):
        code = auth_raw[2 * i]
        hooks = auth_raw[2 * i + 1]
        if int(hooks, 16):
            continue
        auth = authenticate_pool(code, factory_member=True)
        tx = auth["token_x"].lower()
        ty = auth["token_y"].lower()
        if tx == wnative and ty == quote:
            swap_for_y = True
        elif ty == wnative and tx == quote:
            swap_for_y = False
        else:
            raise BoundaryError("ramses_cost_route_token_identity")
        candidates.append((item, swap_for_y))

    if not candidates:
        return []
    quote_rows = rpc.batch(
        [
            (
                "eth_call",
                [
                    dict(
                        to=item["pool"],
                        data=calldata(
                            "getSwapOut(uint128,bool)",
                            amount,
                            1 if swap_for_y else 0,
                        ),
                    ),
                    hex(block),
                ],
            )
            for item, swap_for_y in candidates
        ],
        scope="universe_cost_conversion",
    )
    out = []
    for (item, swap_for_y), raw_quote in zip(candidates, quote_rows):
        q = values(raw_quote)
        if len(q) < 3 or q[0] != 0 or q[1] <= 0:
            continue
        out.append({
            "amount_out": q[1],
            "route_pool": item["pool"],
            "route_kind": "direct_wnative_quote_pool",
            "swap_for_y": swap_for_y,
            "route_fee_raw": q[2],
            "route_bin_step": item["bin_step"],
        })
    return out


def quote_native_cycle(rpc, factory, row, block, native_costs, state):
    """Convert native cycle costs into the candidate's token-Y quote units."""
    if not native_costs:
        return None, {
            "available": False,
            "reason": "native_cost_model_unavailable",
            "model_version": COST_MODEL_VERSION,
        }
    total_native = sum(int(v) for v in native_costs.values())
    if total_native <= 0:
        raise BoundaryError("ramses_cost_native_total")

    pool = row["pool"].lower()
    token_x = row["token_x"].lower()
    token_y = row["token_y"].lower()
    wnative = _wnative(rpc, block, state)
    direct = _candidate_route_quote(
        rpc, pool, token_x, token_y, wnative, total_native, block
    )
    routes = [direct] if direct else []
    if not routes:
        routes = _factory_direct_routes(
            rpc, factory, wnative, token_y, total_native, block
        )
    if not routes:
        return None, {
            "available": False,
            "reason": "no_executable_direct_wnative_quote_route",
            "model_version": COST_MODEL_VERSION,
            "quote_token": token_y,
            "wnative": wnative,
        }
    best = max(routes, key=lambda r: int(r["amount_out"]))
    total_quote = int(best["amount_out"])

    keys = list(native_costs)
    quote_costs = {}
    allocated = 0
    for key in keys[:-1]:
        value = total_quote * int(native_costs[key]) // total_native
        quote_costs[key] = value
        allocated += value
    quote_costs[keys[-1]] = total_quote - allocated
    return quote_costs, {
        "available": True,
        "model_version": COST_MODEL_VERSION,
        "quote_token": token_y,
        "wnative": wnative,
        "native_cycle_cost_raw": total_native,
        "quote_cycle_cost_raw": total_quote,
        "conversion": deepcopy(best),
        "conversion_is_executable_get_swap_out": True,
    }


def automatic_pool_costs(rpc, factory, row, block, state):
    native, gas_meta = current_native_cycle(rpc, state)
    if native is None:
        return None, gas_meta
    quote_costs, conversion_meta = quote_native_cycle(
        rpc, factory, row, block, native, state
    )
    meta = dict(gas_meta)
    meta["conversion"] = conversion_meta
    meta["available"] = bool(quote_costs)
    if not quote_costs:
        meta["reason"] = conversion_meta.get("reason", "quote_conversion_unavailable")
        return None, meta
    meta["quote_costs"] = dict(quote_costs)
    return quote_costs, meta
