"""Ramses DLMM quiet-mint strategy derived from blank-slate historical evidence.

Evidence basis (2026-09-21):
- full indexed Ramses history: ~990k swaps / ~992k fee events;
- 218 clean realized LP lifecycles;
- corrected event-time LP fee attribution;
- hot-burst exact replay rejected the old fee-pulse thesis;
- quiet USDG entries were fee-positive in derivation and validation;
- 24-72h was the most robust cross-pool realized holding region;
- public mint geometry is used rather than fitting one universal width.

This module is paper/research only. It does not sign, submit, or grant allocation
authority. The entry signal must be finalized public Ramses mint evidence and all
qualification inputs must be available before paper entry.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from . import BoundaryError
from .ramses import (
    Q,
    mint_effect,
    paper_fee_capture,
    paper_outcome,
    paper_position,
    price,
    quote_value,
    total_fee,
    unpack,
)

STRATEGY_VERSION = "ramses-quiet-mint-v2"
STRATEGY_DOMAIN = "robinhood-ramses-dlmm-independent"
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"

POLICY = {
    "strategy_version": STRATEGY_VERSION,
    "entry": {
        "quote_token": USDG,
        "max_prior_30m_swaps": 2,
        "min_prior_24h_swaps": 10,
        "max_signal_age_seconds": 120,
        "max_signal_bins": 192,
        "max_position_local_liquidity_bps": 50,  # 0.50%
        # Operational cost guard only; not the obsolete 35-bps return hurdle.
        "max_cycle_cost_bps": 20,
    },
    "management": {
        "target_holding_floor_seconds": 24 * 3600,
        "max_holding_seconds": 72 * 3600,
        "max_rebalances": 0,
        "max_inventory_loss_bps": 100,
        # Conservative derivation median fee return (~28 bps) used only as a
        # monitoring reserve, never as an entry profitability claim.
        "conservative_fee_reserve_bps": 28,
    },
    "geometry": {
        "source": "finalized_public_mint",
        "copy_bin_ids": True,
        "copy_sidedness": True,
        "copy_relative_token_amounts": True,
        "universal_width": None,
    },
    "independence": {
        "strategy_domain": STRATEGY_DOMAIN,
        "shared_allocator": False,
        "cross_strategy_candidates": False,
        "cross_strategy_signals": False,
        "cross_strategy_state": False,
        "cross_strategy_performance_attribution": False,
        "signal_source_class": "ramses_public_finalized_mint",
    },
    "allocation_authority": False,
    "paper_only": True,
}
POLICY_HASH = hashlib.sha256(
    json.dumps(POLICY, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def _args(row):
    return row.get("args", row) if isinstance(row, dict) else {}


def _add2(a, b):
    return [int(a[0]) + int(b[0]), int(a[1]) + int(b[1])]


def _swap_rows(prehistory):
    rows = []
    for row in prehistory or []:
        a = _args(row)
        if "id" in a and "amountsIn" in a:
            rows.append((row, a))
    return rows


def pool_features(prestate, prehistory, quote_side, *, pool=None):
    if quote_side not in ("x", "y"):
        raise BoundaryError("invalid_quote_side")
    active = int(prestate["active"])
    step = int(prestate["step"])
    if active not in prestate["bins"]:
        raise BoundaryError("missing_active_bin_prestate")
    rows = _swap_rows(prehistory)
    side_volume = [0, 0]
    path = []
    total_volume = 0
    total_lp_fees_quote = 0
    for _row, a in rows:
        bid = int(a["id"])
        path.append(bid)
        p = price(bid, step)
        incoming = unpack(a["amountsIn"])
        protocol = unpack(a.get("protocolFees", 0))
        gross = _add2(incoming, protocol)
        volume = quote_value(gross, p, quote_side)
        total_volume += volume
        if gross[0] and not gross[1]:
            side_volume[0] += volume
        elif gross[1] and not gross[0]:
            side_volume[1] += volume
        if "totalFees" in a:
            total_fees = unpack(a["totalFees"])
            lp = [
                max(0, int(total_fees[0]) - int(protocol[0])),
                max(0, int(total_fees[1]) - int(protocol[1])),
            ]
            total_lp_fees_quote += quote_value(lp, p, quote_side)
    active_liquidity_quote = quote_value(
        prestate["bins"][active]["reserves"], price(active, step), quote_side
    )
    net_displacement = abs(path[-1] - path[0]) if len(path) > 1 else 0
    gross_crossings = sum(abs(b - a) for a, b in zip(path, path[1:]))
    flow_imbalance_bps = (
        abs(side_volume[0]-side_volume[1]) * 10000 // max(1, total_volume)
        if total_volume else 10000
    )
    return {
        "pool": pool,
        "active_bin": active,
        "bin_step_bps": step,
        "swap_count": len(rows),
        "recent_volume_quote": total_volume,
        "recent_lp_fees_quote": total_lp_fees_quote,
        "active_liquidity_quote": active_liquidity_quote,
        "flow_imbalance_bps": flow_imbalance_bps,
        "gross_bin_crossings": gross_crossings,
        "net_displacement_bins": net_displacement,
        "strictly_pre_entry": True,
        # Compatibility fields retained for reporting; not used to qualify v2.
        "turnover_percentile_bps": None,
        "fee_percentile_bps": None,
        "turnover_bps": total_volume * 10000 // max(1, active_liquidity_quote),
        "total_fee_rate": total_fee(
            prestate["static"], prestate["variable"][0], step
        ),
    }


def attach_universe_percentiles(feature, universe_features):
    # V2 does not qualify on universe percentiles. Preserve compatibility and
    # explicitly mark them as descriptive only.
    out = deepcopy(feature)
    rows = list(universe_features or [])
    if rows:
        for key, target in (
            ("turnover_bps", "turnover_percentile_bps"),
            ("total_fee_rate", "fee_percentile_bps"),
        ):
            vals = sorted(int(r[key]) for r in rows if r.get(key) is not None)
            if vals:
                value = int(out[key])
                out[target] = sum(v <= value for v in vals) * 10000 // len(vals)
    out["universe_percentiles_descriptive_only"] = True
    return out


def _signal_eligibility(signal, *, now, pool, quote_side):
    reasons = []
    if not isinstance(signal, dict):
        return False, ["quiet_mint_signal_missing"]
    if signal.get("kind") != "quiet_mint":
        reasons.append("quiet_mint_signal_kind")
    if signal.get("source_class") != POLICY["independence"]["signal_source_class"]:
        reasons.append("quiet_mint_signal_source")
    if str(signal.get("pool", "")).lower() != str(pool or "").lower():
        reasons.append("quiet_mint_signal_pool")
    if signal.get("finalized") is not True:
        reasons.append("quiet_mint_signal_not_finalized")
    if signal.get("quote_side") != quote_side:
        reasons.append("quiet_mint_quote_side")
    if str(signal.get("quote_token", "")).lower() != USDG:
        reasons.append("quiet_mint_quote_token")
    observed = signal.get("observed_at")
    if type(observed) not in (int, float) or float(observed) > float(now):
        reasons.append("quiet_mint_signal_time")
    elif float(now) - float(observed) > POLICY["entry"]["max_signal_age_seconds"]:
        reasons.append("quiet_mint_signal_stale")
    if int(signal.get("prior_30m_swaps", 10**9)) > POLICY["entry"]["max_prior_30m_swaps"]:
        reasons.append("quiet_mint_not_quiet")
    if int(signal.get("prior_24h_swaps", -1)) < POLICY["entry"]["min_prior_24h_swaps"]:
        reasons.append("quiet_mint_not_established")
    tx = str(signal.get("transaction_hash", ""))
    bh = str(signal.get("block_hash", ""))
    if not tx.startswith("0x") or len(tx) != 66:
        reasons.append("quiet_mint_transaction_identity")
    if not bh.startswith("0x") or len(bh) != 66:
        reasons.append("quiet_mint_block_identity")
    ids = signal.get("bin_ids")
    amounts = signal.get("amounts")
    if (
        not isinstance(ids, list) or not ids
        or len(ids) > POLICY["entry"]["max_signal_bins"]
        or len(set(int(x) for x in ids)) != len(ids)
    ):
        reasons.append("quiet_mint_geometry")
    if not isinstance(amounts, list) or not isinstance(ids, list) or len(amounts) != len(ids):
        reasons.append("quiet_mint_amounts")
    else:
        for row in amounts:
            if (
                not isinstance(row, list) or len(row) != 2
                or any(type(v) is not int or v < 0 for v in row)
                or not any(row)
            ):
                reasons.append("quiet_mint_amounts")
                break
    return not reasons, reasons


def _cost_total(gas_costs):
    if not isinstance(gas_costs, dict) or not gas_costs:
        return None
    if any(type(v) is not int or v < 0 for v in gas_costs.values()):
        raise BoundaryError("invalid_strategy_costs")
    return sum(gas_costs.values())


def _build_quiet_freeze(
    prestate, requested_capital, quote_side, signal, *, entry_timestamp, gas_costs
):
    active = int(prestate["active"])
    step = int(prestate["step"])
    ids = [int(x) for x in signal["bin_ids"]]
    amounts = [[int(v[0]), int(v[1])] for v in signal["amounts"]]
    if any(b not in prestate["bins"] for b in ids):
        raise BoundaryError("quiet_mint_signal_bin_prestate_missing")

    active_liquidity = quote_value(
        prestate["bins"][active]["reserves"], price(active, step), quote_side
    )
    range_liquidity = sum(
        quote_value(prestate["bins"][bid]["reserves"], price(bid, step), quote_side)
        for bid in ids
    )
    local = min(active_liquidity, range_liquidity)
    local_cap = (
        local * POLICY["entry"]["max_position_local_liquidity_bps"] // 10000
    )
    capital = min(int(requested_capital), int(local_cap))
    if capital <= 0:
        raise BoundaryError("quiet_mint_position_cap_zero")

    signal_value = sum(
        quote_value(amount, price(bid, step), quote_side)
        for bid, amount in zip(ids, amounts)
    )
    if signal_value <= 0:
        raise BoundaryError("quiet_mint_signal_value")

    allocations = []
    variable = list(prestate["variable"])
    requirements = [0, 0]
    deposited = [0, 0]
    composition = [0, 0]
    protocol = [0, 0]
    for bid, signal_amount in zip(ids, amounts):
        requested = [
            int(signal_amount[0]) * capital // signal_value,
            int(signal_amount[1]) * capital // signal_value,
        ]
        if not any(requested):
            raise BoundaryError("quiet_mint_scaled_zero_bin")
        b = prestate["bins"][bid]
        effect = mint_effect(
            b["reserves"], b["supply"], requested,
            bin_id=bid, step=step, active_id=active,
            static=prestate["static"], variable=variable,
            timestamp=int(entry_timestamp),
        )
        variable = effect["variable_after"]
        allocations.append({
            "bin_id": bid,
            "pre_reserves": list(b["reserves"]),
            "pre_supply": int(b["supply"]),
            "requested": requested,
            "amounts_in": effect["amounts_in"],
            "deposited": effect["deposited"],
            "shares": effect["shares"],
            "composition_fees": effect["composition_fees"],
            "protocol_fees": effect["protocol_fees"],
            "bin_price": price(bid, step),
        })
        requirements = _add2(requirements, effect["amounts_in"])
        deposited = _add2(deposited, effect["deposited"])
        composition = _add2(composition, effect["composition_fees"])
        protocol = _add2(protocol, effect["protocol_fees"])

    employed = quote_value(requirements, price(active, step), quote_side)
    if employed <= 0:
        raise BoundaryError("quiet_mint_zero_employed")
    costs = _cost_total(gas_costs)
    cost_bps = None if costs is None else costs * 10000 // employed
    proposal = {
        "name": "quiet_public_mint_geometry",
        "mode": "quiet_mint",
        "bins": ids,
        "active_bin": active,
        "quote_side": quote_side,
        "capital_requested": int(requested_capital),
        "capital_employed": int(employed),
        "token_requirements": requirements,
        "pool_deposit": deposited,
        "composition_fees": composition,
        "protocol_entry_fees": protocol,
        "initial_inventory_mix": requirements,
        "initial_spot_value": int(employed),
        "allocations": allocations,
        "signal_transaction_hash": signal["transaction_hash"],
        "signal_block_hash": signal["block_hash"],
        "signal_log_index": int(signal.get("log_index", 0)),
        "signal_bin_count": len(ids),
        "signal_lower_bin": min(ids),
        "signal_upper_bin": max(ids),
        "signal_width_bins": max(ids)-min(ids)+1,
        "public_signal_geometry": True,
        "local_active_liquidity_quote": int(active_liquidity),
        "local_range_liquidity_quote": int(range_liquidity),
        "position_local_liquidity_bps": (
            int(employed) * 10000 // max(1, int(local))
        ),
        "gas_costs": deepcopy(gas_costs) if gas_costs is not None else None,
        "cycle_cost_bps": cost_bps,
        "historical_fee_reserve_quote": (
            int(employed) * POLICY["management"]["conservative_fee_reserve_bps"]
            // 10000
        ),
        # Compatibility with the connected controller; the old pre-entry fee
        # estimate is intentionally not used for an anticipatory strategy.
        "estimated_fee_capture": (
            int(employed) * POLICY["management"]["conservative_fee_reserve_bps"]
            // 10000
        ),
    }
    digest = hashlib.sha256(
        json.dumps([proposal], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "frozen": True,
        "allocation_authority": False,
        "paper_only": True,
        "strategy_evidence_eligible": True,
        "strategy_version": STRATEGY_VERSION,
        "strategy_domain": STRATEGY_DOMAIN,
        "policy_hash": POLICY_HASH,
        "proposal_hash": digest,
        "proposals": [proposal],
    }


def recommended_capital(features, requested_capital):
    if type(requested_capital) is not int or requested_capital <= 0:
        raise BoundaryError("invalid_strategy_capital")
    # Final local-range cap is applied after the public geometry is known.
    active_cap = (
        int(features["active_liquidity_quote"])
        * POLICY["entry"]["max_position_local_liquidity_bps"] // 10000
    )
    return min(int(requested_capital), int(active_cap))


def classify_pool(
    prestate, prehistory, quote_side, *, requested_capital,
    entry_timestamp=None, gas_costs=None, universe_features=None,
    quiet_mint_signal=None, anchor_signal=None, directional_signal=None,
    now=None, pool=None,
):
    """Classify only the blank-slate quiet-mint strategy; all old modes are disabled."""
    if now is None:
        now = entry_timestamp if entry_timestamp is not None else prestate["variable"][3]
    features = pool_features(prestate, prehistory, quote_side, pool=pool)
    if universe_features:
        features = attach_universe_percentiles(features, universe_features)

    eligible, reasons = _signal_eligibility(
        quiet_mint_signal, now=now, pool=pool, quote_side=quote_side
    )
    if not eligible:
        return {
            "mode": "no_trade", "qualified": False, "reasons": reasons,
            "features": features, "freeze": None,
            "strategy_version": STRATEGY_VERSION,
            "strategy_domain": STRATEGY_DOMAIN,
            "policy_hash": POLICY_HASH,
            "allocation_authority": False,
            "old_fee_pulse_disabled": True,
        }

    capital = recommended_capital(features, requested_capital)
    try:
        freeze = _build_quiet_freeze(
            prestate, capital, quote_side, quiet_mint_signal,
            entry_timestamp=int(entry_timestamp if entry_timestamp is not None else now),
            gas_costs=gas_costs,
        )
    except BoundaryError as exc:
        return {
            "mode": "no_trade", "qualified": False,
            "reasons": ["quiet_mint_construction:" + str(exc)],
            "features": features, "freeze": None,
            "strategy_version": STRATEGY_VERSION,
            "strategy_domain": STRATEGY_DOMAIN,
            "policy_hash": POLICY_HASH,
            "allocation_authority": False,
        }
    proposal = freeze["proposals"][0]
    cost_bps = proposal.get("cycle_cost_bps")
    reasons = []
    if cost_bps is None:
        reasons.append("cost_evidence_unavailable")
    elif cost_bps > POLICY["entry"]["max_cycle_cost_bps"]:
        reasons.append("cycle_cost_share")
    if reasons:
        return {
            "mode": "no_trade", "qualified": False, "reasons": reasons,
            "features": features, "freeze": freeze,
            "strategy_version": STRATEGY_VERSION,
            "strategy_domain": STRATEGY_DOMAIN,
            "policy_hash": POLICY_HASH,
            "allocation_authority": False,
        }
    return {
        "mode": "quiet_mint", "qualified": True, "reasons": [],
        "features": features, "freeze": freeze,
        "signal": deepcopy(quiet_mint_signal),
        "strategy_version": STRATEGY_VERSION,
        "strategy_domain": STRATEGY_DOMAIN,
        "policy_hash": POLICY_HASH,
        "allocation_authority": False,
        "old_fee_pulse_disabled": True,
    }


def controller_action(
    decision, *, current_active_bin, elapsed_seconds, rebalances_used,
    opportunity_still_qualified, expected_remaining_fee_quote,
    estimated_inventory_loss_quote, rebalance_cost_quote, unwind_cost_quote,
):
    if not decision.get("qualified") or not decision.get("freeze"):
        return {"action": "exit", "reason": "strategy_not_qualified"}
    if decision.get("mode") != "quiet_mint":
        return {"action": "exit", "reason": "legacy_ramses_mode_disabled"}
    if elapsed_seconds >= POLICY["management"]["max_holding_seconds"]:
        return {"action": "exit", "reason": "max_holding_period"}

    proposal = decision["freeze"]["proposals"][0]
    employed = max(1, int(proposal["capital_employed"]))
    inventory_loss_bps = int(estimated_inventory_loss_quote) * 10000 // employed
    if inventory_loss_bps >= POLICY["management"]["max_inventory_loss_bps"]:
        return {
            "action": "exit", "reason": "inventory_loss_limit",
            "inventory_loss_bps": inventory_loss_bps,
        }

    lo, hi = min(proposal["bins"]), max(proposal["bins"])
    if int(current_active_bin) < lo or int(current_active_bin) > hi:
        return {"action": "exit", "reason": "out_of_range"}

    # A quiet-mint entry intentionally expects the pool to become active after
    # entry, so loss of the *entry* quiet condition is not an exit reason.
    if (
        elapsed_seconds >= POLICY["management"]["target_holding_floor_seconds"]
        and int(expected_remaining_fee_quote) <= int(unwind_cost_quote)
    ):
        return {"action": "exit", "reason": "remaining_fee_below_unwind_cost"}

    # V2 deliberately does not rebalance. Historical evidence favored holding
    # public mint geometry through the fee cycle rather than chasing price.
    return {
        "action": "hold", "reason": "quiet_mint_harvest",
        "entry_condition_requalification_required": False,
        "rebalances_allowed": 0,
    }


def decompose_pnl(decision, replay_result, *, unwind=None, costs=None):
    if not decision.get("freeze"):
        raise BoundaryError("strategy_position_missing")
    position = paper_position(decision["freeze"], 0)
    captured = paper_fee_capture(position, replay_result)
    outcome = paper_outcome(
        position, replay_result["terminal_state"], unwind=unwind, costs=costs,
        lp_fees_captured=captured,
    )
    gross = outcome.get("gross_result")
    fee_pnl = captured["quote_value"]
    inventory_pnl = gross-fee_pnl if isinstance(gross, int) else None
    return {
        "mode": decision.get("mode"),
        "strategy_domain": STRATEGY_DOMAIN,
        "fee_pnl_quote": fee_pnl,
        "inventory_or_directional_pnl_quote": inventory_pnl,
        "execution_cost_quote": outcome.get("total_costs"),
        "gross_result_quote": gross,
        "net_result_quote": outcome.get("after_cost_result"),
        "after_cost_return_bps": outcome.get("after_cost_return_bps"),
        "unresolved_inventory": outcome.get("unresolved_inventory"),
        "outcome": outcome,
    }
