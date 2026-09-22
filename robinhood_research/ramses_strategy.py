"""Ramses Active Wide Maker v1 / rebalance-v3 paper strategy.

The active strategy is the operator-derived USDG, quiet-entry, wide two-sided
maker policy.  Legacy Fee Pulse helpers remain only as deterministic compatibility
utilities for older evidence and tests; classify_pool never grants them strategy
authority.  This module remains paper/research only and cannot sign or submit.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from . import BoundaryError
from .ramses_active_wide_maker import normalized_displacement
from .ramses import (
    HURDLE_BPS,
    PRECISION,
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

STRATEGY_VERSION = "ramses-active-wide-maker-v1/rebalance-v3"
STRATEGY_DOMAIN = "robinhood-ramses-dlmm-independent"
USDG_ADDRESS = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"

POLICY = {
    "strategy_version": STRATEGY_VERSION,
    "policy_revision": "profitability-v1-active-wide-maker-v3",
    "policy_purpose": "prospective_natural_paper_validation_of_operator_derived_active_wide_maker",
    "machinery_proof_only": False,
    "profitability_authority": True,
    "one_natural_settled_lifecycle_target": False,
    "active_wide_maker": {
        "quote_token": USDG_ADDRESS,
        "prior_30m_swaps_max": 2,
        "width_candidates": [65, 90, 120, 150, 200],
        "min_width_bins": 65,
        "default_sidedness": "two_sided",
        "max_position_local_liquidity_bps": 50,
        "capital_preservation_min_bps": 8000,
        "capital_preservation_max_bps": 12000,
        "rebalance_requires_positive_after_cost_edge": True,
        "rebalance_requires_positive_two_x_cost_stress": True,
        "initial_entry_requires_positive_projected_edge": False,
    },
    # Legacy helpers are retained for historical replay only.  classify_pool
    # never authorizes these modes under the active policy.
    "fee_pulse": {
        "min_turnover_percentile_bps": 8000,
        "min_fee_percentile_bps": 7000,
        "min_volume_acceleration_milli": 0,
        "min_chop_ratio_milli": 0,
        "max_flow_imbalance_bps": 10000,
        "min_fee_to_inventory_milli": 750,
        "min_net_to_cost_milli": 1000,
        "universe_percentiles_hard_gate": False,
        "net_to_cost_hard_gate": False,
        "min_projected_return_bps": -150000,
        "max_position_active_liquidity_bps": 1000,
        "core_allocation_bps": 7000,
        "max_outer_width": 3,
    },
    "controller": {
        "inside_hold_max_d": 1.0,
        "edge_watch_max_d": 1.5,
        "recenter_max_d": 3.0,
        "target_remint_seconds": 180,
        "hard_same_decision_deadline_seconds": 210,
        "max_holding_seconds": 604800,
        "max_rebalances": 8,
        "rebalance_edge_to_cost_milli": 1000,
    },
    "signals": {
        "max_age_seconds": 30,
        "min_confidence_bps": 8000,
        "min_expected_net_bps": HURDLE_BPS + 1,
        "max_path_width": 3,
    },
    "independence": {
        "strategy_domain": STRATEGY_DOMAIN,
        "shared_allocator": False,
        "cross_strategy_candidates": False,
        "cross_strategy_signals": False,
        "cross_strategy_state": False,
        "cross_strategy_performance_attribution": False,
        "anchor_source_class": "external_reference",
        "directional_source_class": "ramses_independent_model",
    },
    "validation": {
        "minimum_eligible_rebalances": 20,
        "minimum_distinct_pools": 5,
        "minimum_win_rate": 0.55,
        "median_after_cost_return_bps": ">0",
        "mean_after_cost_return_bps": ">0",
        "two_x_cost_stress_median_bps": ">0",
        "two_x_cost_stress_mean_bps": ">0",
        "historical_holdout_reuse": False,
    },
    "hurdle_bps": 0,
    "reference_profitability_hurdle_bps": HURDLE_BPS,
    "allocation_authority": False,
    "paper_only": True,
}
POLICY_HASH = hashlib.sha256(
    json.dumps(POLICY, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def _args(row):
    return row.get("args", row) if isinstance(row, dict) else {}


def _add2(a, b):
    return [a[0] + b[0], a[1] + b[1]]


def _sub2(a, b):
    if b[0] > a[0] or b[1] > a[1]:
        raise BoundaryError("strategy_state_underflow")
    return [a[0] - b[0], a[1] - b[1]]


def _percentile(values, numerator, denominator):
    if not values:
        return 0
    ordered = sorted(int(v) for v in values)
    index = max(0, min(len(ordered) - 1, (len(ordered) * numerator + denominator - 1) // denominator - 1))
    return ordered[index]


def _percentile_rank_bps(value, values):
    values = [int(v) for v in values]
    if not values:
        return None
    return sum(1 for v in values if v <= int(value)) * 10000 // len(values)


def _range_amount(budget, bid, active, p, quote_side, reserves):
    if bid < active:
        return [0, budget if quote_side == "y" else budget * p // Q]
    if bid > active:
        return [budget * Q // p if quote_side == "y" else budget, 0]
    liquidity = reserves[0] * p + reserves[1] * Q
    target = budget * Q if quote_side == "y" else budget * p
    if not liquidity:
        return [0, budget] if quote_side == "y" else [budget, 0]
    x = reserves[0] * target // liquidity
    y = reserves[1] * target // liquidity
    return [x, y] if x or y else ([0, budget] if quote_side == "y" else [budget, 0])


def _distribute(total, ids, weights):
    if total <= 0 or not ids or len(ids) != len(weights) or sum(weights) <= 0:
        raise BoundaryError("invalid_strategy_budget")
    weight_total = sum(weights)
    amounts = [total * w // weight_total for w in weights]
    amounts[0] += total - sum(amounts)
    return dict(zip(ids, amounts))


def _swap_rows(prehistory):
    rows = []
    for row in prehistory or []:
        a = _args(row)
        if "id" not in a or "amountsIn" not in a:
            continue
        rows.append((row, a))
    return rows


def pool_features(prestate, prehistory, quote_side, *, pool=None):
    """Compute strictly pre-entry fee-density and inventory-risk features."""
    if quote_side not in ("x", "y"):
        raise BoundaryError("invalid_quote_side")
    active = int(prestate["active"])
    step = int(prestate["step"])
    if active not in prestate["bins"]:
        raise BoundaryError("missing_active_bin_prestate")
    rows = _swap_rows(prehistory)
    path = []
    volumes = []
    side_volume = [0, 0]
    total_lp_fees_quote = 0
    for _row, a in rows:
        bid = int(a["id"])
        path.append(bid)
        p = price(bid, step)
        gross = _add2(unpack(a["amountsIn"]), unpack(a.get("protocolFees", 0)))
        volume = quote_value(gross, p, quote_side)
        volumes.append(volume)
        if gross[0] and not gross[1]:
            side_volume[0] += volume
        elif gross[1] and not gross[0]:
            side_volume[1] += volume
        if "totalFees" in a:
            lp = _sub2(unpack(a["totalFees"]), unpack(a.get("protocolFees", 0)))
            total_lp_fees_quote += quote_value(lp, p, quote_side)

    total_volume = sum(volumes)
    half = max(1, len(volumes) // 2)
    early = sum(volumes[:half])
    late = sum(volumes[half:]) if len(volumes) > 1 else 0
    volume_acceleration_milli = late * 1000 // max(1, early)
    gross_crossings = sum(abs(b - a) for a, b in zip(path, path[1:]))
    net_displacement = abs(path[-1] - path[0]) if len(path) > 1 else 0
    chop_ratio_milli = gross_crossings * 1000 // (1 + net_displacement)
    flow_imbalance_bps = (
        abs(side_volume[0] - side_volume[1]) * 10000 // total_volume
        if total_volume else 10000
    )

    active_bin = prestate["bins"][active]
    active_liquidity_quote = quote_value(active_bin["reserves"], price(active, step), quote_side)
    turnover_bps = total_volume * 10000 // max(1, active_liquidity_quote)
    rate = total_fee(prestate["static"], prestate["variable"][0], step)
    base_rate = prestate["static"][0] * step * 10**10
    dynamic_rate = max(0, rate - base_rate)

    excursions = [abs(b - active) for b in path] or [1]
    p75 = max(1, _percentile(excursions, 3, 4))
    p95 = max(p75, _percentile(excursions, 19, 20))
    max_width = POLICY["fee_pulse"]["max_outer_width"]
    p75 = min(max_width, p75)
    p95 = min(max_width, p95)

    return {
        "pool": pool,
        "active_bin": active,
        "bin_step_bps": step,
        "swap_count": len(rows),
        "recent_volume_quote": total_volume,
        "recent_lp_fees_quote": total_lp_fees_quote,
        "active_liquidity_quote": active_liquidity_quote,
        "turnover_bps": turnover_bps,
        "volume_acceleration_milli": volume_acceleration_milli,
        "gross_bin_crossings": gross_crossings,
        "net_displacement_bins": net_displacement,
        "chop_ratio_milli": chop_ratio_milli,
        "flow_imbalance_bps": flow_imbalance_bps,
        "side_volume_quote": side_volume,
        "total_fee_rate": rate,
        "base_fee_rate": base_rate,
        "dynamic_fee_rate": dynamic_rate,
        "total_fee_ppm": rate * 1_000_000 // PRECISION,
        "dynamic_fee_ppm": dynamic_rate * 1_000_000 // PRECISION,
        "movement_risk_bps": net_displacement * step,
        "core_width": p75,
        "outer_width": p95,
        "turnover_percentile_bps": None,
        "fee_percentile_bps": None,
        "strictly_pre_entry": True,
    }


def attach_universe_percentiles(feature, universe_features):
    rows = list(universe_features or [])
    if not rows:
        return deepcopy(feature)
    out = deepcopy(feature)
    turnover = [r["turnover_bps"] for r in rows if r.get("turnover_bps") is not None]
    fees = [r["total_fee_rate"] for r in rows if r.get("total_fee_rate") is not None]
    out["turnover_percentile_bps"] = _percentile_rank_bps(out["turnover_bps"], turnover)
    out["fee_percentile_bps"] = _percentile_rank_bps(out["total_fee_rate"], fees)
    out["universe_size"] = len(rows)
    return out


def _recent_metrics(prehistory, ids, allocations, step, quote_side):
    lo, hi = min(ids), max(ids)
    within = near = fee_capture = 0
    owned = {a["bin_id"]: a for a in allocations}
    for _row, a in _swap_rows(prehistory):
        bid = int(a["id"])
        p = price(bid, step)
        gross = _add2(unpack(a["amountsIn"]), unpack(a.get("protocolFees", 0)))
        volume = quote_value(gross, p, quote_side)
        if lo <= bid <= hi:
            within += volume
        if lo - 1 <= bid <= hi + 1:
            near += volume
        if bid in owned and "totalFees" in a:
            lp = _sub2(unpack(a["totalFees"]), unpack(a.get("protocolFees", 0)))
            alloc = owned[bid]
            denom = alloc["pre_supply"] + alloc["shares"]
            if denom:
                fee_capture += quote_value(
                    [v * alloc["shares"] // denom for v in lp], p, quote_side
                )
    return {
        "recent_within_range_volume": within,
        "near_range_volume": near,
        "estimated_fee_capture": fee_capture,
    }


def _cost_total(gas_costs):
    if gas_costs is None:
        return None
    if not isinstance(gas_costs, dict) or not gas_costs:
        raise BoundaryError("invalid_strategy_costs")
    if any(type(v) is not int or v < 0 for v in gas_costs.values()):
        raise BoundaryError("invalid_strategy_costs")
    return sum(gas_costs.values())


def _freeze(prestate, capital, quote_side, ids, budget_map, *, name, mode,
            entry_timestamp=None, prehistory=None, gas_costs=None, extra=None):
    if type(capital) is not int or capital <= 0 or capital >= Q:
        raise BoundaryError("invalid_strategy_capital")
    active, step = int(prestate["active"]), int(prestate["step"])
    entry_timestamp = prestate["variable"][3] if entry_timestamp is None else int(entry_timestamp)
    if entry_timestamp < prestate["variable"][3]:
        raise BoundaryError("invalid_entry_timestamp")
    if any(b not in prestate["bins"] for b in ids):
        raise BoundaryError("missing_strategy_range_prestate")

    allocations = []
    variable = list(prestate["variable"])
    requirements = [0, 0]
    deposit = [0, 0]
    composition = [0, 0]
    protocol = [0, 0]
    for bid in ids:
        budget = int(budget_map[bid])
        if budget <= 0:
            continue
        b = prestate["bins"][bid]
        p = price(bid, step)
        requested = _range_amount(budget, bid, active, p, quote_side, b["reserves"])
        effect = mint_effect(
            b["reserves"], b["supply"], requested,
            bin_id=bid, step=step, active_id=active, static=prestate["static"],
            variable=variable, timestamp=entry_timestamp,
        )
        variable = effect["variable_after"]
        allocations.append({
            "bin_id": bid,
            "pre_reserves": list(b["reserves"]),
            "pre_supply": b["supply"],
            "requested": requested,
            "amounts_in": effect["amounts_in"],
            "deposited": effect["deposited"],
            "shares": effect["shares"],
            "composition_fees": effect["composition_fees"],
            "protocol_fees": effect["protocol_fees"],
            "bin_price": p,
        })
        requirements = _add2(requirements, effect["amounts_in"])
        deposit = _add2(deposit, effect["deposited"])
        composition = _add2(composition, effect["composition_fees"])
        protocol = _add2(protocol, effect["protocol_fees"])
    if not allocations:
        raise BoundaryError("empty_strategy_range")

    spot = price(active, step)
    employed = quote_value(requirements, spot, quote_side)
    metrics = _recent_metrics(prehistory, ids, allocations, step, quote_side)
    features = pool_features(prestate, prehistory, quote_side)
    risk = employed * features["movement_risk_bps"] // 10000
    projected_before_costs = (
        metrics["estimated_fee_capture"] - quote_value(protocol, spot, quote_side) - risk
    )
    costs = _cost_total(gas_costs)
    after = projected_before_costs - costs if costs is not None else None
    return_bps = after * 10000 // employed if after is not None and employed else None
    proposal = {
        "name": name,
        "mode": mode,
        "bins": list(ids),
        "active_bin": active,
        "quote_side": quote_side,
        "capital_requested": capital,
        "capital_employed": employed,
        "token_requirements": requirements,
        "pool_deposit": deposit,
        "composition_fees": composition,
        "protocol_entry_fees": protocol,
        "initial_inventory_mix": requirements,
        "initial_spot_value": employed,
        "allocations": allocations,
        "base_fee": prestate["static"][0] * step * 10**10,
        "dynamic_fee": max(0, total_fee(prestate["static"], prestate["variable"][0], step)
                           - prestate["static"][0] * step * 10**10),
        "protocol_share_bps": prestate["static"][5],
        "lp_share_bps": 10000 - prestate["static"][5],
        "modeled_inventory_risk_reserve": risk,
        "movement_risk_bps": features["movement_risk_bps"],
        "projected_before_costs": projected_before_costs,
        "projected_after_cost_result": after,
        "projected_return_bps": return_bps,
        "gas_costs": deepcopy(gas_costs) if gas_costs is not None else None,
        "hurdle_bps": POLICY["hurdle_bps"],
        "exceeds_hurdle": return_bps is not None and return_bps >= POLICY["hurdle_bps"],
        **metrics,
    }
    if extra:
        proposal.update(deepcopy(extra))
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
        "hurdle_bps": POLICY["hurdle_bps"],
        "proposal_hash": digest,
        "proposals": [proposal],
    }


def build_fee_pulse_freeze(prestate, capital, quote_side, *, entry_timestamp=None,
                           prehistory=None, gas_costs=None, features=None):
    features = deepcopy(features) if features is not None else pool_features(prestate, prehistory, quote_side)
    active = int(prestate["active"])
    core = max(1, min(POLICY["fee_pulse"]["max_outer_width"], int(features["core_width"])))
    outer = max(core, min(POLICY["fee_pulse"]["max_outer_width"], int(features["outer_width"])))
    ids = list(range(active - outer, active + outer + 1))
    core_ids = [b for b in ids if abs(b - active) <= core]
    buffer_ids = [b for b in ids if b not in core_ids]
    core_bps = POLICY["fee_pulse"]["core_allocation_bps"] if buffer_ids else 10000
    core_budget = capital * core_bps // 10000
    buffer_budget = capital - core_budget
    budget_map = {}
    budget_map.update(_distribute(core_budget, core_ids, [1] * len(core_ids)))
    if buffer_ids:
        budget_map.update(_distribute(buffer_budget, buffer_ids, [1] * len(buffer_ids)))
    return _freeze(
        prestate, capital, quote_side, ids, budget_map,
        name="fee_pulse_adaptive", mode="fee_pulse", entry_timestamp=entry_timestamp,
        prehistory=prehistory, gas_costs=gas_costs,
        extra={
            "core_width": core,
            "outer_width": outer,
            "core_allocation_bps": core_bps,
            "buffer_allocation_bps": 10000 - core_bps,
        },
    )


def build_path_freeze(prestate, capital, quote_side, *, direction, mode,
                      entry_timestamp=None, prehistory=None, gas_costs=None, width=1):
    if direction not in ("up", "down"):
        raise BoundaryError("invalid_strategy_direction")
    if mode not in ("anchor_pulse", "directional_converter"):
        raise BoundaryError("invalid_strategy_mode")
    width = max(1, min(POLICY["signals"]["max_path_width"], int(width)))
    active = int(prestate["active"])
    ids = (
        list(range(active + 1, active + width + 1))
        if direction == "up"
        else list(range(active - width, active))
    )
    weights = [width - abs(b - active) + 1 for b in ids]
    budget_map = _distribute(capital, ids, weights)
    return _freeze(
        prestate, capital, quote_side, ids, budget_map,
        name=f"{mode}_{direction}", mode=mode, entry_timestamp=entry_timestamp,
        prehistory=prehistory, gas_costs=gas_costs,
        extra={"direction": direction, "path_width": width, "one_sided": True},
    )


def recommended_capital(features, requested_capital):
    if type(requested_capital) is not int or requested_capital <= 0:
        raise BoundaryError("invalid_strategy_capital")
    ceiling = (
        features["active_liquidity_quote"]
        * POLICY["active_wide_maker"]["max_position_local_liquidity_bps"]
        // 10000
    )
    return min(requested_capital, ceiling)


def evaluate_fee_pulse(features, proposal):
    p = POLICY["fee_pulse"]
    reasons = []
    percentile_targets = {
        "turnover": features.get("turnover_percentile_bps") is not None
            and features["turnover_percentile_bps"] >= p["min_turnover_percentile_bps"],
        "fee": features.get("fee_percentile_bps") is not None
            and features["fee_percentile_bps"] >= p["min_fee_percentile_bps"],
    }
    if features["volume_acceleration_milli"] < p["min_volume_acceleration_milli"]:
        reasons.append("volume_acceleration")
    if features["chop_ratio_milli"] < p["min_chop_ratio_milli"]:
        reasons.append("insufficient_two_way_chop")
    if features["flow_imbalance_bps"] > p["max_flow_imbalance_bps"]:
        reasons.append("flow_imbalance")
    position_bps = proposal["capital_employed"] * 10000 // max(1, features["active_liquidity_quote"])
    if position_bps > p["max_position_active_liquidity_bps"]:
        reasons.append("position_share")
    fee_to_inventory = proposal["estimated_fee_capture"] * 1000 // max(1, proposal["modeled_inventory_risk_reserve"])
    if fee_to_inventory < p["min_fee_to_inventory_milli"]:
        reasons.append("fee_to_inventory")
    costs = _cost_total(proposal.get("gas_costs"))
    if costs is None:
        reasons.append("cost_evidence_unavailable")
        net_to_cost = None
    else:
        net = proposal.get("projected_after_cost_result")
        net_to_cost = (net * 1000 // max(1, costs)) if isinstance(net, int) else None
        if net is None or proposal.get("projected_return_bps") is None or proposal["projected_return_bps"] < p["min_projected_return_bps"]:
            reasons.append("cash_hurdle")
    return {
        "qualified": not reasons,
        "reasons": reasons,
        "fee_to_inventory_milli": fee_to_inventory,
        "net_to_cost_milli": net_to_cost,
        "position_active_liquidity_bps": position_bps,
        "hurdle_bps": p["min_projected_return_bps"],
        "percentile_targets": percentile_targets,
        "net_to_cost_target_met": net_to_cost is not None and net_to_cost >= p["min_net_to_cost_milli"],
    }


def _signal_eligible(signal, *, now, kind):
    """Require fresh, explicitly independent non-strategy signal provenance."""
    if not isinstance(signal, dict):
        return False, [f"{kind}_signal_missing"]
    reasons = []
    if signal.get("kind") != kind:
        reasons.append(f"{kind}_signal_kind")
    required_source = (
        POLICY["independence"]["anchor_source_class"]
        if kind == "anchor"
        else POLICY["independence"]["directional_source_class"]
    )
    if signal.get("source_class") != required_source:
        reasons.append(f"{kind}_signal_source")
    forbidden = {
        str(signal.get("source_strategy", "")).lower(),
        str(signal.get("upstream_strategy", "")).lower(),
        str(signal.get("candidate_source", "")).lower(),
    }
    if any(
        any(token in value for token in ("pons", "pump", "continuation", "solana", "other_strategy"))
        for value in forbidden if value
    ):
        reasons.append("cross_strategy_signal_forbidden")
    observed_at = signal.get("observed_at")
    if type(observed_at) not in (int, float) or now < observed_at:
        reasons.append(f"{kind}_signal_time")
    elif now - observed_at > POLICY["signals"]["max_age_seconds"]:
        reasons.append(f"{kind}_signal_stale")
    if int(signal.get("confidence_bps", -1)) < POLICY["signals"]["min_confidence_bps"]:
        reasons.append(f"{kind}_signal_confidence")
    if int(signal.get("expected_net_bps", -1)) < POLICY["signals"]["min_expected_net_bps"]:
        reasons.append(f"{kind}_signal_edge")
    if signal.get("direction") not in ("up", "down"):
        reasons.append(f"{kind}_signal_direction")
    if kind == "directional" and signal.get("conversion_side") not in ("x", "y"):
        reasons.append("directional_conversion_side")
    return not reasons, reasons

def _wide_range_ids(active, width):
    width=int(width)
    if width < POLICY["active_wide_maker"]["min_width_bins"]:
        raise BoundaryError("wide_maker_width_below_minimum")
    left=(width-1)//2
    right=width-1-left
    return list(range(int(active)-left,int(active)+right+1))


def _active_wide_freezes(
    prestate, capital, quote_side, *, entry_timestamp, prehistory, gas_costs,
    rebalance_reference_capital=None,
):
    active=int(prestate["active"])
    costs=_cost_total(gas_costs)
    rows=[]
    for width in POLICY["active_wide_maker"]["width_candidates"]:
        ids=_wide_range_ids(active,width)
        if any(b not in prestate.get("bins",{}) for b in ids):
            continue
        budget_map=_distribute(capital,ids,[1]*len(ids))
        freeze=_freeze(
            prestate,capital,quote_side,ids,budget_map,
            name="active_wide_"+str(width),
            mode="active_wide_maker",
            entry_timestamp=entry_timestamp,
            prehistory=prehistory,
            gas_costs=gas_costs,
            extra={"active_wide_width_bins":width,"two_sided":True},
        )
        proposal=freeze["proposals"][0]
        employed=int(proposal["capital_employed"])
        reference=(
            int(rebalance_reference_capital)
            if rebalance_reference_capital is not None
            else int(capital)
        )
        preservation_bps=employed*10000//max(1,reference)
        before=proposal.get("projected_before_costs")
        two_x=(
            int(before)-2*int(costs)
            if costs is not None and isinstance(before,int)
            else None
        )
        two_x_bps=(
            two_x*10000//employed
            if isinstance(two_x,int) and employed>0
            else None
        )
        proposal["capital_preservation_bps"]=preservation_bps
        proposal["two_x_cost_stress_result"]=two_x
        proposal["two_x_cost_return_bps"]=two_x_bps
        freeze["proposal_hash"]=hashlib.sha256(
            json.dumps(
                freeze["proposals"],sort_keys=True,separators=(",",":")
            ).encode()
        ).hexdigest()
        rows.append(freeze)
    return rows


def _active_wide_candidate_ok(freeze, *, rebalance):
    proposal=freeze["proposals"][0]
    p=POLICY["active_wide_maker"]
    if not proposal.get("two_sided"):
        return False
    if int(proposal.get("active_wide_width_bins") or 0) < p["min_width_bins"]:
        return False
    preservation=int(proposal.get("capital_preservation_bps") or 0)
    if not p["capital_preservation_min_bps"] <= preservation <= p["capital_preservation_max_bps"]:
        return False
    if rebalance:
        if p["rebalance_requires_positive_after_cost_edge"]:
            if not isinstance(proposal.get("projected_after_cost_result"),int) or proposal["projected_after_cost_result"] <= 0:
                return False
        if p["rebalance_requires_positive_two_x_cost_stress"]:
            if not isinstance(proposal.get("two_x_cost_stress_result"),int) or proposal["two_x_cost_stress_result"] <= 0:
                return False
    return True


def classify_pool(prestate, prehistory, quote_side, *, requested_capital,
                  entry_timestamp=None, gas_costs=None, universe_features=None,
                  anchor_signal=None, directional_signal=None, now=None, pool=None,
                  quote_token=USDG_ADDRESS, rebalance_reference_capital=None):
    """Classify only the Active Wide Maker v3 policy.

    Anchor/directional/Fee Pulse arguments remain accepted for call-site
    compatibility but cannot grant current strategy authority.
    """
    if now is None:
        now = entry_timestamp if entry_timestamp is not None else prestate["variable"][3]
    features=pool_features(prestate,prehistory,quote_side,pool=pool)
    if universe_features:
        features=attach_universe_percentiles(features,universe_features)
    features["prior_30m_swap_count"]=int(features.get("swap_count") or 0)
    reasons=[]
    if str(quote_token or "").lower()!=USDG_ADDRESS:
        reasons.append("quote_asset_not_usdg")
    rebalance=rebalance_reference_capital is not None
    if not rebalance and features["prior_30m_swap_count"] > POLICY["active_wide_maker"]["prior_30m_swaps_max"]:
        reasons.append("prior_30m_not_quiet")
    capital=recommended_capital(features,requested_capital)
    if capital<=0:
        reasons.append("position_cap_zero")
    if gas_costs is None:
        reasons.append("cost_evidence_unavailable")
    freezes=[]
    if not reasons:
        freezes=_active_wide_freezes(
            prestate,capital,quote_side,
            entry_timestamp=(
                prestate["variable"][3]
                if entry_timestamp is None else int(entry_timestamp)
            ),
            prehistory=prehistory,
            gas_costs=gas_costs,
            rebalance_reference_capital=rebalance_reference_capital,
        )
        freezes=[f for f in freezes if _active_wide_candidate_ok(f,rebalance=rebalance)]
        if not freezes:
            reasons.append(
                "no_economic_rebalance_candidate"
                if rebalance else "no_wide_entry_candidate"
            )
    if reasons:
        return {
            "mode":"no_trade","qualified":False,"reasons":reasons,
            "features":features,"freeze":None,"policy_hash":POLICY_HASH,
            "strategy_version":STRATEGY_VERSION,"strategy_domain":STRATEGY_DOMAIN,
            "allocation_authority":False,"paper_only":True,
            "legacy_signals_ignored":bool(anchor_signal or directional_signal),
        }
    choice=max(
        freezes,
        key=lambda f:(
            int(f["proposals"][0].get("projected_after_cost_result") or -10**80),
            -int(f["proposals"][0]["active_wide_width_bins"]),
        ),
    )
    verify=hashlib.sha256(
        json.dumps(choice["proposals"],sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()
    if verify!=choice["proposal_hash"]:
        raise BoundaryError("wide_maker_proposal_hash")
    return {
        "mode":"active_wide_maker","qualified":True,"reasons":[],
        "features":features,"freeze":choice,"policy_hash":POLICY_HASH,
        "strategy_version":STRATEGY_VERSION,"strategy_domain":STRATEGY_DOMAIN,
        "allocation_authority":False,"paper_only":True,
        "rebalance_candidate":rebalance,
        "ignored_legacy_modes":["fee_pulse","anchor_pulse","directional_converter"],
    }


def controller_action(decision, *, current_active_bin, elapsed_seconds, rebalances_used,
                      opportunity_still_qualified, expected_remaining_fee_quote,
                      estimated_inventory_loss_quote, rebalance_cost_quote, unwind_cost_quote):
    """Apply Active Wide Maker v3 displacement hysteresis.

    The initial quiet-entry condition is not re-applied to an open position.
    A pool becoming active after entry is therefore not itself an exit signal.
    """
    if not decision.get("qualified") or not decision.get("freeze"):
        return {"action":"exit","reason":"strategy_not_qualified"}
    proposal=decision["freeze"]["proposals"][0]
    bins=proposal["bins"]
    d=normalized_displacement(min(bins),max(bins),int(current_active_bin))
    fee_reserve_known=isinstance(expected_remaining_fee_quote,int)
    risk_exit=(
        fee_reserve_known
        and int(estimated_inventory_loss_quote)
            > int(expected_remaining_fee_quote)
    )
    if d <= POLICY["controller"]["inside_hold_max_d"]:
        if risk_exit:
            return {"action":"exit","reason":"inventory_risk_dominates","D":d}
        return {"action":"hold","reason":"inside_productive_range","D":d}
    if d < POLICY["controller"]["edge_watch_max_d"]:
        if risk_exit:
            return {"action":"exit","reason":"edge_watch_risk_exit","D":d}
        return {"action":"hold","reason":"hysteresis_no_partial_shift","D":d}
    if d <= POLICY["controller"]["recenter_max_d"]:
        if not fee_reserve_known:
            return {
                "action":"exit",
                "reason":"recenter_fee_reserve_unavailable",
                "D":d,
            }
        remaining_edge=(
            int(expected_remaining_fee_quote)
            - int(estimated_inventory_loss_quote)
            - int(unwind_cost_quote)
            - int(rebalance_cost_quote)
        )
        if remaining_edge > 0:
            return {
                "action":"rebalance",
                "reason":"normalized_displacement_recenter_band",
                "remaining_edge":remaining_edge,
                "D":d,
            }
        return {
            "action":"exit",
            "reason":"recenter_not_economic",
            "remaining_edge":remaining_edge,
            "D":d,
        }
    return {"action":"exit","reason":"normalized_displacement_overrun_no_chase","D":d}


def decompose_pnl(decision, replay_result, *, unwind=None, costs=None):
    """Separate fee skill from inventory/directional P&L and execution costs."""
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
    inventory_pnl = gross - fee_pnl if isinstance(gross, int) else None
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
