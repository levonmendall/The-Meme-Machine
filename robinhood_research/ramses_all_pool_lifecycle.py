"""Connected all-pool Ramses Fee Pulse paper lifecycle.

Canonical path:
all-pool selector -> authenticated qualifier evidence -> frozen range ->
independent Ramses ledger -> paper LP monitoring -> event-driven rebalance/exit ->
same-pool unwind -> settlement -> P&L decomposition.

This module never calls the legacy WNATIVE-only selector and never grants live
money, signing, submission, or shared-allocation authority.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import time

from . import BoundaryError
from .abi import calldata, topic
from .identity import load
from .ramses import (
    decode_ramses_event,
    paper_position,
    paper_removal,
    price,
    quote_value,
    replay,
    values,
    verify_proposal_hash,
)
from .ramses_capture import BoundedMultiRpc, LOG_BLOCK_CHUNK
from .ramses_strategy import (
    POLICY,
    POLICY_HASH,
    STRATEGY_DOMAIN,
    STRATEGY_VERSION,
    classify_pool,
    controller_action,
    decompose_pnl,
    pool_features,
)
from .ramses_strategy_ledger import RamsesStrategyLedger
from .ramses_universe import compact_screen, scan

REPORT = Path(os.environ.get(
    "MM_ROBINHOOD_RAMSES_CONNECTED_REPORT",
    "robinhood-ramses-connected-lifecycle-report.json",
))
DB = Path(os.environ.get(
    "MM_ROBINHOOD_RAMSES_CONNECTED_DB",
    "robinhood-ramses-connected-lifecycle.sqlite",
))

MONITOR_POLL_SECONDS = 30
RESCAN_SECONDS = 300
MAX_MUTATED_BINS = 256
MAX_POOL_LOGS = 5000
MAX_POOL_TRANSACTIONS = 2500
MAX_POOL_BLOCKS = 2500


def _json_env(name):
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        raise BoundaryError("invalid_" + name.lower()) from None
    if not isinstance(value, dict):
        raise BoundaryError("invalid_" + name.lower())
    return value


def _normalize_context(value):
    return {str(k).lower(): v for k, v in (value or {}).items()}


def select_qualifier(screen):
    """Choose the first already-ranked genuine strategy qualifier."""
    if not isinstance(screen, dict) or screen.get("strategy_domain") != STRATEGY_DOMAIN:
        raise BoundaryError("foreign_ramses_screen")
    for row in screen.get("rows", []):
        decision = row.get("decision") or {}
        if (
            decision.get("qualified") is True
            and decision.get("strategy_domain") == STRATEGY_DOMAIN
            and decision.get("strategy_version") == STRATEGY_VERSION
            and decision.get("policy_hash") == POLICY_HASH
            and decision.get("allocation_authority") is False
            and decision.get("freeze")
        ):
            verify_proposal_hash(decision["freeze"])
            return row
    return None


def _batch_logs(rpc, start, end, address, *, scope="lifecycle_logs", topics=None):
    if start > end:
        return []
    calls = []
    for first in range(start, end + 1, LOG_BLOCK_CHUNK):
        calls.append((
            "eth_getLogs",
            [dict(
                fromBlock=hex(first),
                toBlock=hex(min(end, first + LOG_BLOCK_CHUNK - 1)),
                address=address,
                **({"topics": topics} if topics is not None else {}),
            )],
        ))
    found = []
    for i in range(0, len(calls), 20):
        for page in rpc.batch(calls[i:i + 20], scope=scope):
            found.extend(page)
            if len(found) > MAX_POOL_LOGS:
                raise BoundaryError("connected_lifecycle_log_capacity")
    return found


def _snapshot(rpc, address, block, bins, *, initial):
    sigs = [
        "getBinStep()",
        "getActiveId()",
        "getReserves()",
        "getProtocolFees()",
        "getStaticFeeParameters()",
        "getVariableFeeParameters()",
        "getLBHooksParameters()",
    ]
    if initial:
        sigs += ["getTokenX()", "getTokenY()", "implementation()", "getFactory()"]
    vals = rpc.batch(
        [
            ("eth_call", [dict(to=address, data=calldata(sig)), hex(block)])
            for sig in sigs
        ],
        scope="lifecycle_state",
    )
    snap = dict(values={sig: value for sig, value in zip(sigs, vals)}, bins={})
    if int(snap["values"]["getLBHooksParameters()"], 16):
        raise BoundaryError("connected_lifecycle_pool_hooks")
    calls = []
    for bid in bins:
        calls.extend([
            ("eth_call", [dict(to=address, data=calldata("getBin(uint24)", bid)), hex(block)]),
            ("eth_call", [dict(to=address, data=calldata("totalSupply(uint256)", bid)), hex(block)]),
        ])
    raw = rpc.batch(calls, scope="lifecycle_bins") if calls else []
    for i, bid in enumerate(bins):
        snap["bins"][str(bid)] = {
            "getBin(uint24)": raw[2*i],
            "totalSupply(uint256)": raw[2*i+1],
        }
    return snap


def _event_bins(events, proposal_bins):
    bins = set(int(b) for b in proposal_bins)
    abi = load("ramses_pool_implementation")["abi"]
    for event in events:
        d = decode_ramses_event(abi, event)
        a = d["args"]
        if d["name"] in ("Swap", "CompositionFees"):
            bins.add(int(a["id"]))
        elif d["name"] in ("DepositedToBins", "WithdrawnFromBins"):
            bins.update(int(x) for x in a["ids"])
        elif d["name"] == "TransferBatch":
            if (
                a["from"].lower() == "0x" + "00"*20
                or a["to"].lower() == "0x" + "00"*20
            ):
                bins.update(int(x) for x in a["ids"])
    if len(bins) > MAX_MUTATED_BINS:
        raise BoundaryError("connected_lifecycle_bin_capacity")
    return sorted(bins)


def _canonical_preentry_history(rpc, row, screen):
    """Build one receipt/header-authenticated canonical Swap tape for the pool.

    The all-pool scanner and lifecycle use the exact same Swap topic filter.
    Provider duplicates are deduplicated by (blockHash, logIndex); conflicting
    duplicates fail closed.  The returned tape is the only history allowed to
    authorize entry.
    """
    pool = row["pool"].lower()
    start = int(screen["lookback_start_block"])
    end = int(screen["finalized_block"])
    swap_topic = topic(
        "Swap(address,address,uint24,bytes32,bytes32,uint24,bytes32,bytes32)"
    )
    raw = _batch_logs(
        rpc, start, end, pool, scope="qualifier_auth", topics=[swap_topic]
    )
    abi = load("ramses_pool_implementation")["abi"]
    seen = {}
    swaps = []
    for event in raw:
        identity = (event.get("blockHash"), event.get("logIndex"))
        prior = seen.get(identity)
        if prior is not None:
            if prior != event:
                raise BoundaryError("qualifier_history_conflicting_duplicate")
            continue
        seen[identity] = event
        decoded = decode_ramses_event(abi, event)
        if decoded["name"] != "Swap":
            raise BoundaryError("qualifier_history_non_swap_topic")
        swaps.append((event, decoded))
    swaps.sort(
        key=lambda pair: (
            int(pair[0]["blockNumber"], 16),
            int(pair[0]["transactionIndex"], 16),
            int(pair[0]["logIndex"], 16),
        )
    )

    tx_blocks = {}
    for event, _decoded in swaps:
        tx = event["transactionHash"]
        block_hash = event["blockHash"]
        prior = tx_blocks.get(tx)
        if prior is not None and prior != block_hash:
            raise BoundaryError("qualifier_history_transaction_block_conflict")
        tx_blocks[tx] = block_hash
    txs = list(tx_blocks)
    if len(txs) > MAX_POOL_TRANSACTIONS:
        raise BoundaryError("qualifier_history_transaction_capacity")
    receipts = rpc.receipts(
        [(tx, tx_blocks[tx]) for tx in txs],
        scope="qualifier_auth",
    ) if txs else []
    receipt_by_tx = {r["transactionHash"]: r for r in receipts}
    blocks = sorted(set(int(e["blockNumber"], 16) for e, _d in swaps))
    if len(blocks) > MAX_POOL_BLOCKS:
        raise BoundaryError("qualifier_history_block_capacity")
    headers = rpc.blocks(blocks, scope="qualifier_auth") if blocks else []
    header_by_block = {int(h["number"], 16): h for h in headers}

    history = []
    for event, decoded in swaps:
        receipt = receipt_by_tx.get(event["transactionHash"])
        header = header_by_block.get(int(event["blockNumber"], 16))
        if (
            receipt is None
            or header is None
            or int(receipt["status"], 16) != 1
            or receipt["blockHash"] != event["blockHash"]
            or header["hash"] != event["blockHash"]
            or receipt["transactionIndex"] != event["transactionIndex"]
            or event not in receipt["logs"]
        ):
            raise BoundaryError("qualifier_history_receipt_header_disagreement")
        history.append(dict(
            block=int(event["blockNumber"], 16),
            block_hash=event["blockHash"],
            transaction_hash=event["transactionHash"],
            transaction_index=int(event["transactionIndex"], 16),
            log_index=int(event["logIndex"], 16),
            args=decoded["args"],
        ))

    scanner = row.get("prehistory") or []
    scanner_ids = [
        (
            int(x["block"]),
            x.get("block_hash"),
            x["transaction_hash"],
            int(x["transaction_index"]),
            int(x["log_index"]),
        )
        for x in scanner
    ]
    canonical_ids = [
        (
            int(x["block"]),
            x["block_hash"],
            x["transaction_hash"],
            int(x["transaction_index"]),
            int(x["log_index"]),
        )
        for x in history
    ]
    return history, dict(
        authenticated=True,
        swap_logs=len(history),
        transactions=len(txs),
        blocks=len(blocks),
        start_block=start,
        end_block=end,
        scanner_swap_logs=len(scanner),
        identity_match=(scanner_ids == canonical_ids),
        scanner_only=max(0, len(scanner_ids)-len(canonical_ids)),
        canonical_only=max(0, len(canonical_ids)-len(scanner_ids)),
    )


def _frozen_prestate(row, screen):
    """Return the exact finalized state captured by the selector, or fail closed."""
    prestate = row.get("prestate")
    if not isinstance(prestate, dict):
        raise BoundaryError("connected_lifecycle_frozen_prestate_missing")
    expected_block = int(screen["finalized_block"])
    expected_hash = screen["finalized_hash"]
    expected_timestamp = int(screen["finalized_timestamp"])
    if (
        int(row.get("prestate_block", -1)) != expected_block
        or row.get("prestate_block_hash") != expected_hash
        or int(row.get("prestate_timestamp", -1)) != expected_timestamp
    ):
        raise BoundaryError("connected_lifecycle_frozen_prestate_identity")
    if (
        type(prestate.get("active")) is not int
        or type(prestate.get("step")) is not int
        or not isinstance(prestate.get("bins"), dict)
        or prestate["active"] not in prestate["bins"]
    ):
        raise BoundaryError("connected_lifecycle_frozen_prestate_shape")
    return deepcopy(prestate)


def _canonicalize_selected_row(
    rpc, row, screen, *, costs_by_pool=None, signals_by_pool=None
):
    """Reclassify selected pool from authenticated canonical pre-entry evidence."""
    costs_by_pool = costs_by_pool or {}
    signals_by_pool = signals_by_pool or {}
    frozen_prestate = _frozen_prestate(row, screen)
    history, auth = _canonical_preentry_history(rpc, row, screen)
    canonical = deepcopy(row)
    canonical["prestate"] = frozen_prestate
    canonical["prehistory"] = history
    canonical_feature = pool_features(
        frozen_prestate, history, canonical["quote_side"], pool=canonical["pool"]
    )
    peers = [
        r["features"] for r in screen.get("rows", [])
        if r.get("pool", "").lower() != canonical["pool"].lower()
    ]
    universe = peers + [canonical_feature]
    context = signals_by_pool.get(canonical["pool"].lower(), {})
    if context and not isinstance(context, dict):
        raise BoundaryError("connected_lifecycle_signal_context")
    frozen_costs = canonical.get("gas_costs")
    if frozen_costs is None:
        frozen_costs = costs_by_pool.get(canonical["pool"].lower())
    decision = classify_pool(
        frozen_prestate,
        history,
        canonical["quote_side"],
        requested_capital=int(canonical["paper_capital_quote_raw"]),
        entry_timestamp=int(screen["finalized_timestamp"]),
        gas_costs=frozen_costs,
        universe_features=universe,
        anchor_signal=context.get("anchor"),
        directional_signal=context.get("directional"),
        now=int(screen["finalized_timestamp"]),
        pool=canonical["pool"],
    )
    canonical["features"] = decision.get("features") or canonical_feature
    canonical["decision"] = decision
    canonical["evidence_grade"] = "receipt_header_authenticated"
    auth["reclassified"] = True
    auth["qualified_after_authentication"] = bool(decision.get("qualified"))
    auth["prestate_reused_from_scanner"] = True
    auth["prestate_rpc_refetch"] = False
    auth["prestate_block"] = int(canonical["prestate_block"])
    auth["prestate_block_hash"] = canonical["prestate_block_hash"]
    auth["prestate_timestamp"] = int(canonical["prestate_timestamp"])
    return canonical, auth


def _authenticate_preentry_history(rpc, row, screen):
    """Compatibility wrapper returning canonical authentication metadata."""
    _canonical, auth = _canonicalize_selected_row(rpc, row, screen)
    return auth

def _build_segment_replay(rpc, pool, decision, start_block, end_block):
    if end_block <= start_block:
        raise BoundaryError("connected_lifecycle_empty_segment")
    events = _batch_logs(rpc, start_block+1, end_block, pool)
    proposal_bins = decision["freeze"]["proposals"][0]["bins"]
    bins = _event_bins(events, proposal_bins)

    factory = load("ramses_factory")["address"]
    membership, pool_code = rpc.batch(
        [
            (
                "eth_call",
                [dict(to=factory, data=calldata("isPool(address)", pool)), hex(start_block)],
            ),
            ("eth_getCode", [pool, hex(start_block)]),
        ],
        scope="lifecycle_identity",
    )
    if int(membership, 16) != 1:
        raise BoundaryError("connected_lifecycle_factory_membership")

    start_raw = _snapshot(rpc, pool, start_block, bins, initial=True)
    end_raw = _snapshot(rpc, pool, end_block, bins, initial=False)

    tx_blocks = {}
    for event in events:
        tx = event["transactionHash"]
        block_hash = event["blockHash"]
        prior = tx_blocks.get(tx)
        if prior is not None and prior != block_hash:
            raise BoundaryError("connected_lifecycle_transaction_block_conflict")
        tx_blocks[tx] = block_hash
    txs = list(tx_blocks)
    if len(txs) > MAX_POOL_TRANSACTIONS:
        raise BoundaryError("connected_lifecycle_transaction_capacity")
    receipts = rpc.receipts(
        [(tx, tx_blocks[tx]) for tx in txs],
        scope="lifecycle_receipts",
    ) if txs else []

    blocks = sorted(set(
        [start_block, end_block] + [int(e["blockNumber"], 16) for e in events]
    ))
    if len(blocks) > MAX_POOL_BLOCKS:
        raise BoundaryError("connected_lifecycle_block_capacity")
    header_rows = rpc.blocks(blocks, scope="lifecycle_headers")
    headers = {
        str(int(h["number"], 16)): {
            k: h[k] for k in ("number", "hash", "timestamp", "parentHash")
        }
        for h in header_rows
    }
    if str(start_block) not in headers or str(end_block) not in headers:
        raise BoundaryError("connected_lifecycle_header_missing")

    capture = dict(
        pool=pool,
        pool_code=pool_code,
        factory_checks={pool: membership},
        states={str(start_block): start_raw, str(end_block): end_raw},
        logs=events,
        receipts=receipts,
        headers=headers,
        ended_at=time.time(),
        range_freeze=decision["freeze"],
        boundary=None,
    )
    replay_result = replay(capture)
    if replay_result.get("terminal_equality") is not True:
        raise BoundaryError("connected_lifecycle_terminal_equality")
    return capture, replay_result


def _position_state_from_prestate(prestate, decision):
    """Derive the paper overlay state from an already-finalized scanner prestate."""
    proposal = decision["freeze"]["proposals"][0]
    bins = sorted(set(int(b) for b in proposal["bins"]))
    missing=[b for b in bins if b not in prestate.get("bins",{})]
    if missing:
        raise BoundaryError("connected_lifecycle_entry_prestate_missing_bin")
    terminal=dict(
        active=int(prestate["active"]),
        step=int(prestate["step"]),
        bins={
            b: dict(
                reserves=list(prestate["bins"][b]["reserves"]),
                supply=int(prestate["bins"][b]["supply"]),
            )
            for b in bins
        },
    )
    position=paper_position(decision["freeze"],0)
    removal=paper_removal(position,terminal)
    inventory=quote_value(
        removal["amounts"],
        price(terminal["active"],terminal["step"]),
        position["quote_side"],
    )
    loss=max(
        0,
        int(position["proposal"]["initial_spot_value"])-int(inventory),
    )
    return dict(
        active=terminal["active"],
        step=terminal["step"],
        inventory_value=inventory,
        inventory_loss_quote=loss,
    )


def _position_state(rpc, pool, decision, block):
    """Read one monitoring snapshot in a single bounded logical batch."""
    proposal = decision["freeze"]["proposals"][0]
    bins = sorted(set(int(b) for b in proposal["bins"]))
    calls = [
        (
            "eth_call",
            [dict(to=pool, data=calldata("getActiveId()")), hex(block)],
        ),
        (
            "eth_call",
            [dict(to=pool, data=calldata("getBinStep()")), hex(block)],
        ),
    ]
    for bid in bins:
        calls.extend([
            (
                "eth_call",
                [dict(to=pool, data=calldata("getBin(uint24)", bid)), hex(block)],
            ),
            (
                "eth_call",
                [dict(to=pool, data=calldata("totalSupply(uint256)", bid)), hex(block)],
            ),
        ])
    raw = rpc.batch(calls, scope="lifecycle_monitor")
    active = values(raw[0])[0]
    step = values(raw[1])[0]
    terminal = dict(active=active, step=step, bins={})
    payload = raw[2:]
    for i, bid in enumerate(bins):
        terminal["bins"][bid] = dict(
            reserves=values(payload[2*i]),
            supply=values(payload[2*i+1])[0],
        )
    position = paper_position(decision["freeze"], 0)
    removal = paper_removal(position, terminal)
    inventory = quote_value(
        removal["amounts"],
        price(active, step),
        position["quote_side"],
    )
    loss = max(
        0,
        int(position["proposal"]["initial_spot_value"]) - int(inventory),
    )
    return dict(
        active=active,
        step=step,
        inventory_value=inventory,
        inventory_loss_quote=loss,
    )


def _unwind(rpc, pool, decision, replay_result, block):
    position = paper_position(decision["freeze"], 0)
    terminal = replay_result["terminal_state"]
    removal = paper_removal(position, terminal)["amounts"]
    quote_side = position["quote_side"]
    nonquote = 0 if quote_side == "y" else 1
    amount = removal[nonquote]
    if not amount:
        return None
    if amount >= 2**128:
        raise BoundaryError("connected_lifecycle_unwind_amount_capacity")
    for_y = 1 if quote_side == "y" else 0
    raw = rpc.call(
        "eth_call",
        [dict(to=pool, data=calldata("getSwapOut(uint128,bool)", amount, for_y)), hex(block)],
        scope="lifecycle_unwind",
    )
    q = values(raw)
    spot = price(terminal["active"], terminal["step"])
    expected = quote_value(
        [amount, 0] if nonquote == 0 else [0, amount],
        spot,
        quote_side,
    )
    return dict(
        input_side="x" if nonquote == 0 else "y",
        amount_in=amount,
        amount_in_left=q[0],
        amount_out=q[1],
        fee=q[2],
        slippage=max(0, expected-q[1]),
        block=block,
    )


def _segment_costs(costs):
    if not isinstance(costs, dict) or not costs:
        raise BoundaryError("connected_lifecycle_cost_evidence_missing")
    if any(type(v) is not int or v < 0 for v in costs.values()):
        raise BoundaryError("connected_lifecycle_cost_evidence_invalid")
    return dict(costs)


_TRANSIENT_PROVIDER_BOUNDARIES = frozenset(
    set(BoundedMultiRpc.RATE_ERRORS) | {"provider_rate_limit"}
)


def _is_transient_provider_boundary(exc):
    return isinstance(exc, BoundaryError) and str(exc) in _TRANSIENT_PROVIDER_BOUNDARIES


def _paper_ledger_capital(position_capital, costs, max_rebalances):
    """Fund mechanics-only paper accounting without changing position size."""
    if type(position_capital) is not int or position_capital <= 0:
        raise BoundaryError("connected_lifecycle_invalid_position_capital")
    normalized = _segment_costs(costs)
    if type(max_rebalances) is not int or max_rebalances < 0:
        raise BoundaryError("connected_lifecycle_invalid_rebalance_limit")
    # Every closed segment can incur the explicit modeled cycle-cost envelope.
    # The ledger funding covers those costs; the strategy position remains exactly
    # capital_employed and all costs remain charged in after-cost P&L.
    return position_capital + sum(normalized.values()) * (1 + max_rebalances)


def _record_provider_hold(result, ledger, identity, *, stage, boundary, at):
    row = dict(
        action="hold",
        reason="transient_provider_boundary",
        stage=stage,
        boundary=str(boundary),
        at=int(at),
    )
    result.setdefault("provider_holds", []).append(row)
    ledger.checkpoint(identity, action="monitor", detail=row, at=int(at))
    return row


def aggregate_segments(segments):
    """Aggregate fully closed quote-denominated paper segments."""
    if not segments:
        raise BoundaryError("connected_lifecycle_no_segments")
    unresolved = next(
        (
            s["pnl"].get("unresolved_inventory")
            for s in segments
            if s["pnl"].get("unresolved_inventory")
        ),
        None,
    )
    gross = sum(int(s["pnl"].get("gross_result_quote") or 0) for s in segments)
    net_values = [s["pnl"].get("net_result_quote") for s in segments]
    net = None if any(type(v) is not int for v in net_values) else sum(net_values)
    fees = sum(int(s["pnl"].get("fee_pnl_quote") or 0) for s in segments)
    inventory = sum(
        int(s["pnl"].get("inventory_or_directional_pnl_quote") or 0)
        for s in segments
    )
    execution = sum(
        int(s["pnl"].get("execution_cost_quote") or 0) for s in segments
    )
    initial = int(segments[0]["initial_cost_basis"])
    return dict(
        strategy_domain=STRATEGY_DOMAIN,
        strategy_version=STRATEGY_VERSION,
        policy_hash=POLICY_HASH,
        segments=len(segments),
        rebalances=max(0, len(segments)-1),
        fee_pnl_quote=fees,
        inventory_or_directional_pnl_quote=inventory,
        execution_cost_quote=execution,
        gross_result_quote=gross,
        net_result_quote=net,
        after_cost_return_bps=(
            net*10000//initial if type(net) is int and initial else None
        ),
        unresolved_inventory=unresolved,
    )


def _requalify_current_pool(
    screen, pool, capital, costs_by_pool, signals_by_pool
):
    rows = screen.get("rows") or []
    row = next(
        (r for r in rows if r.get("pool", "").lower() == pool.lower()),
        None,
    )
    if row is None:
        return None
    features = [r["features"] for r in rows]
    context = (signals_by_pool or {}).get(pool, {})
    if context and not isinstance(context, dict):
        raise BoundaryError("connected_lifecycle_signal_context")
    return classify_pool(
        row["prestate"],
        row["prehistory"],
        row["quote_side"],
        requested_capital=capital,
        entry_timestamp=int(screen["finalized_timestamp"]),
        gas_costs=(
            row.get("gas_costs")
            if row.get("gas_costs") is not None
            else (costs_by_pool or {}).get(pool)
        ),
        universe_features=features,
        anchor_signal=context.get("anchor"),
        directional_signal=context.get("directional"),
        now=int(screen["finalized_timestamp"]),
        pool=pool,
    )


def run(
    endpoint,
    *,
    costs_by_pool=None,
    signals_by_pool=None,
    db_path=None,
    monitor_poll_seconds=MONITOR_POLL_SECONDS,
    rescan_seconds=RESCAN_SECONDS,
    initial_screen=None,
    cost_state=None,
):
    costs_by_pool = _normalize_context(costs_by_pool)
    signals_by_pool = _normalize_context(signals_by_pool)
    cost_state = {} if cost_state is None else cost_state
    if type(monitor_poll_seconds) not in (int, float) or monitor_poll_seconds <= 0:
        raise BoundaryError("connected_lifecycle_poll")
    if type(rescan_seconds) not in (int, float) or rescan_seconds <= 0:
        raise BoundaryError("connected_lifecycle_rescan")

    result = dict(
        kind="ramses_all_pool_connected_lifecycle_v1",
        strategy_domain=STRATEGY_DOMAIN,
        strategy_version=STRATEGY_VERSION,
        policy_hash=POLICY_HASH,
        paper_only=True,
        allocation_authority=False,
        shared_allocator=False,
        legacy_native_selector_used=False,
        started_at=time.time(),
        status="screening",
    )

    if initial_screen is not None:
        if (
            not isinstance(initial_screen, dict)
            or initial_screen.get("strategy_domain") != STRATEGY_DOMAIN
            or initial_screen.get("policy_hash") != POLICY_HASH
        ):
            raise BoundaryError("foreign_initial_ramses_screen")
        screen = deepcopy(initial_screen)
    else:
        screen = scan(
            endpoint,
            gas_costs_by_pool=costs_by_pool,
            signals_by_pool=signals_by_pool,
            cost_state=cost_state,
        )
    result["initial_screen"] = screen
    scanner_qualifiers = []
    for candidate in screen.get("rows", []):
        decision0 = candidate.get("decision") or {}
        if (
            decision0.get("qualified") is True
            and decision0.get("strategy_domain") == STRATEGY_DOMAIN
            and decision0.get("strategy_version") == STRATEGY_VERSION
            and decision0.get("policy_hash") == POLICY_HASH
            and decision0.get("allocation_authority") is False
            and decision0.get("freeze")
        ):
            verify_proposal_hash(decision0["freeze"])
            scanner_qualifiers.append(candidate)
    if not scanner_qualifiers:
        result.update(
            status="no_trade",
            boundary=None,
            reason="no_genuine_all_pool_qualifier",
            provider=screen.get("provider"),
            ended_at=time.time(),
        )
        return result

    entry_block = int(screen["finalized_block"])
    entry_at = int(screen["finalized_timestamp"])
    rpc = BoundedMultiRpc(
        endpoint,
        max_sessions=16,
        batch_size=20,
        batch_pause=0.5,
        rate_retries=1,
    )
    rpc.verify_chain()
    chosen = None
    attempts = []
    for candidate in scanner_qualifiers:
        canonical_candidate, auth = _canonicalize_selected_row(
            rpc,
            candidate,
            screen,
            costs_by_pool=costs_by_pool,
            signals_by_pool=signals_by_pool,
        )
        attempts.append(dict(
            pool=candidate["pool"].lower(),
            authentication=auth,
            qualified_after_authentication=bool(
                canonical_candidate["decision"].get("qualified")
            ),
            canonical_reasons=canonical_candidate["decision"].get("reasons"),
        ))
        if canonical_candidate["decision"].get("qualified") is True:
            chosen = canonical_candidate
            break
    result["qualifier_authentication_attempts"] = attempts
    if chosen is None:
        result.update(
            status="no_trade",
            boundary=None,
            reason="no_authenticated_all_pool_qualifier",
            provider=rpc.telemetry(),
            ended_at=time.time(),
        )
        return result

    pool = chosen["pool"].lower()
    result["qualifier_authentication"] = attempts[-1]["authentication"]
    decision = deepcopy(chosen["decision"])
    costs = _segment_costs(
        chosen.get("gas_costs")
        if chosen.get("gas_costs") is not None
        else costs_by_pool.get(pool)
    )
    result.update(
        status="qualifier_selected",
        pool=pool,
        quote_asset=chosen["token_y"].lower(),
        qualifier_decision=decision,
        qualifier_cost_evidence=deepcopy(chosen.get("cost_evidence")),
        qualifier_gas_costs=dict(costs),
        entry_block=entry_block,
        entry_at=entry_at,
    )

    db_path = str(db_path or DB)
    if Path(db_path).exists():
        raise BoundaryError("connected_lifecycle_db_already_exists")
    position_capital = int(
        decision["freeze"]["proposals"][0]["capital_employed"]
    )
    paper_capital = _paper_ledger_capital(
        position_capital,
        costs,
        int(POLICY["controller"]["max_rebalances"]),
    )
    result["ledger_funding"] = dict(
        position_capital=position_capital,
        execution_cost_envelope=paper_capital-position_capital,
        paper_capital=paper_capital,
        position_size_unchanged=True,
    )
    ledger = RamsesStrategyLedger(
        db_path,
        paper_capital=paper_capital,
        quote_asset=chosen["token_y"],
    )
    identity = (
        STRATEGY_DOMAIN + ":" + pool + ":" + str(entry_block) + ":"
        + decision["freeze"]["proposal_hash"]
    )
    segments = []
    controller_log = []
    rebalances = 0
    current_capital = paper_capital
    segment_start = entry_block
    last_scan_wall = time.monotonic()
    latest_screen = screen
    overall_started = time.monotonic()
    last_monitor_at = entry_at

    try:
        result["ledger_reserved"] = ledger.reserve(
            identity, pool=pool, decision=decision, at=entry_at
        )
        result["ledger_open"] = ledger.open(identity, at=entry_at)
        result["status"] = "open"

        while True:
            time.sleep(monitor_poll_seconds)
            try:
                frontier = rpc.call(
                    "eth_getBlockByNumber",
                    ["finalized", False],
                    scope="lifecycle_monitor",
                )
            except BoundaryError as exc:
                if not _is_transient_provider_boundary(exc):
                    raise
                _record_provider_hold(
                    result, ledger, identity,
                    stage="frontier", boundary=exc, at=last_monitor_at,
                )
                continue
            block = int(frontier["number"], 16)
            at = int(frontier["timestamp"], 16)
            last_monitor_at = max(last_monitor_at, at)
            if block <= segment_start:
                continue

            if time.monotonic()-last_scan_wall >= rescan_seconds:
                try:
                    latest_screen = scan(
                        endpoint,
                        gas_costs_by_pool=costs_by_pool,
                        signals_by_pool=signals_by_pool,
                        cost_state=cost_state,
                    )
                except BoundaryError as exc:
                    if not _is_transient_provider_boundary(exc):
                        raise
                    _record_provider_hold(
                        result, ledger, identity,
                        stage="rescan", boundary=exc, at=last_monitor_at,
                    )
                finally:
                    last_scan_wall = time.monotonic()

            row = next(
                (
                    r for r in latest_screen.get("rows", [])
                    if r.get("pool", "").lower() == pool
                ),
                None,
            )
            opportunity_qualified = bool(
                row and (row.get("decision") or {}).get("qualified")
            )
            try:
                state_now = _position_state(rpc, pool, decision, block)
            except BoundaryError as exc:
                if not _is_transient_provider_boundary(exc):
                    raise
                _record_provider_hold(
                    result, ledger, identity,
                    stage="position_state", boundary=exc, at=last_monitor_at,
                )
                continue
            proposal = decision["freeze"]["proposals"][0]
            expected_fee = max(
                1, int(proposal.get("estimated_fee_capture") or 0)
            )
            remaining_seconds = max(
                0,
                int(
                    POLICY["controller"]["max_holding_seconds"]
                    - (time.monotonic()-overall_started)
                ),
            )
            expected_remaining_fee = (
                expected_fee * max(1, remaining_seconds)
                // max(1, POLICY["controller"]["max_holding_seconds"])
            )
            total_cost = sum(costs.values())
            rebalance_cost = int(costs.get("rebalance", total_cost))
            unwind_cost = int(
                costs.get("unwind", costs.get("unwind_gas", 0))
            )
            action = controller_action(
                decision,
                current_active_bin=state_now["active"],
                elapsed_seconds=int(time.monotonic()-overall_started),
                rebalances_used=rebalances,
                opportunity_still_qualified=opportunity_qualified,
                expected_remaining_fee_quote=expected_remaining_fee,
                estimated_inventory_loss_quote=state_now["inventory_loss_quote"],
                rebalance_cost_quote=rebalance_cost,
                unwind_cost_quote=unwind_cost,
            )
            controller_row = dict(
                at=at,
                block=block,
                active_bin=state_now["active"],
                inventory_value=state_now["inventory_value"],
                inventory_loss_quote=state_now["inventory_loss_quote"],
                opportunity_qualified=opportunity_qualified,
                action=action,
            )
            controller_log.append(controller_row)
            ledger.checkpoint(
                identity,
                action="monitor",
                detail=controller_row,
                at=at,
            )
            if action["action"] == "hold":
                continue

            try:
                capture, replay_result = _build_segment_replay(
                    rpc, pool, decision, segment_start, block
                )
                unwind = _unwind(
                    rpc, pool, decision, replay_result, block
                )
            except BoundaryError as exc:
                if not _is_transient_provider_boundary(exc):
                    raise
                _record_provider_hold(
                    result, ledger, identity,
                    stage="exit_replay_or_unwind", boundary=exc,
                    at=last_monitor_at,
                )
                continue
            pnl = decompose_pnl(
                decision,
                replay_result,
                unwind=unwind,
                costs=costs,
            )
            segment = dict(
                index=len(segments),
                start_block=segment_start,
                end_block=block,
                start_at=int(
                    capture["headers"][str(segment_start)]["timestamp"], 16
                ),
                end_at=int(capture["headers"][str(block)]["timestamp"], 16),
                exit_reason=action["reason"],
                initial_cost_basis=int(
                    decision["freeze"]["proposals"][0]["capital_employed"]
                ),
                proposal_hash=decision["freeze"]["proposal_hash"],
                terminal_equality=replay_result["terminal_equality"],
                events=replay_result["events"],
                transactions=replay_result["transactions"],
                pnl=pnl,
            )
            segments.append(segment)
            ledger.checkpoint(
                identity,
                action="segment_close",
                detail=dict(
                    segment=segment["index"],
                    end_block=block,
                    exit_reason=action["reason"],
                    net_result_quote=pnl.get("net_result_quote"),
                ),
                at=at,
            )
            if (
                pnl.get("unresolved_inventory")
                or type(pnl.get("net_result_quote")) is not int
            ):
                break
            current_capital = (
                int(segment["initial_cost_basis"])
                + int(pnl["net_result_quote"])
            )
            if action["action"] != "rebalance" or current_capital <= 0:
                break

            fresh = scan(
                endpoint,
                gas_costs_by_pool=costs_by_pool,
                signals_by_pool=signals_by_pool,
                cost_state=cost_state,
            )
            new_decision = _requalify_current_pool(
                fresh,
                pool,
                current_capital,
                costs_by_pool,
                signals_by_pool,
            )
            if (
                not new_decision
                or new_decision.get("qualified") is not True
            ):
                controller_log.append(dict(
                    at=at,
                    block=block,
                    action=dict(
                        action="exit",
                        reason="rebalance_requalification_failed",
                    ),
                ))
                break
            verify_proposal_hash(new_decision["freeze"])
            fresh_row = next(
                (
                    r for r in fresh.get("rows", [])
                    if r.get("pool", "").lower() == pool
                ),
                None,
            )
            if fresh_row is None:
                raise BoundaryError("connected_lifecycle_rebalance_row_missing")
            costs = _segment_costs(
                fresh_row.get("gas_costs")
                if fresh_row.get("gas_costs") is not None
                else costs_by_pool.get(pool)
            )
            decision = new_decision
            latest_screen = fresh
            segment_start = int(fresh["finalized_block"])
            rebalances += 1
            rebalance_row = dict(
                index=rebalances,
                block=segment_start,
                at=int(fresh["finalized_timestamp"]),
                capital=current_capital,
                proposal_hash=decision["freeze"]["proposal_hash"],
            )
            result.setdefault("rebalances", []).append(rebalance_row)
            ledger.checkpoint(
                identity,
                action="rebalance",
                detail=rebalance_row,
                at=rebalance_row["at"],
            )

        aggregate = aggregate_segments(segments)
        terminal_at = int(segments[-1]["end_at"]) if segments else entry_at
        result["segments"] = segments
        result["controller_log"] = controller_log
        result["pnl"] = aggregate
        result["ledger_final"] = ledger.settle(
            identity,
            pnl=aggregate,
            at=terminal_at,
        )
        result["ledger_reconciliation"] = ledger.reconcile()
        result["status"] = result["ledger_final"]["status"]
        result["boundary"] = None
    finally:
        try:
            ledger.close()
        except Exception:
            pass

    result["provider"] = rpc.telemetry()
    result["ended_at"] = time.time()
    return result


def compact_lifecycle_result(result):
    """Strip heavy selector state from persisted/public lifecycle evidence."""
    if not isinstance(result, dict):
        raise BoundaryError("invalid_connected_lifecycle_report")
    public = deepcopy(result)
    if isinstance(public.get("initial_screen"), dict):
        public["initial_screen"] = compact_screen(public["initial_screen"])
    public["selector_prestate_persisted_in_artifact"] = False
    return public


def main():
    costs = _json_env("MM_ROBINHOOD_RAMSES_COSTS_BY_POOL_JSON") or {}
    signals = _json_env("MM_ROBINHOOD_RAMSES_SIGNALS_BY_POOL_JSON") or {}
    result = run(
        os.environ.get("MM_ROBINHOOD_READ_RPC_URL", ""),
        costs_by_pool=costs,
        signals_by_pool=signals,
        db_path=str(DB),
    )
    public_result = compact_lifecycle_result(result)
    raw = json.dumps(public_result, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > 8_000_000:
        raise BoundaryError("connected_lifecycle_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps(dict(
        status=result.get("status"),
        reason=result.get("reason"),
        pool=result.get("pool"),
        segments=len(result.get("segments") or []),
        rebalances=len(result.get("rebalances") or []),
        net_result_quote=(result.get("pnl") or {}).get("net_result_quote"),
        legacy_native_selector_used=result.get("legacy_native_selector_used"),
        provider=(
            result.get("provider")
            or (result.get("initial_screen") or {}).get("provider")
        ),
    )))


if __name__ == "__main__":
    main()
