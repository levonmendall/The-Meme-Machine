"""Research-only DLMM range economics.

This module builds an ex-ante 60-second economic case for the exact proposed
one-sided liquidity range. It has no allocation authority and never reads outcome
data. Inputs are a finalized decision state plus a verified warmup tape.

The range case measures:
- current liquidity inside the proposed bins;
- verified warmup volume that actually traversed those bins;
- verified warmup volume within a configurable adjacent-bin band;
- LP-fee generation in and near the proposed range;
- a transparent fee-capture proxy for the fixed paper capital;
- the resulting 60-second net-fee case after fixed entry/exit costs.

The fee-capture estimate is deliberately labeled a proxy: it applies the decision-time
capital share of current range liquidity to the verified pre-entry fee flow. It is not
used as execution authority.
"""
from __future__ import annotations

import math

from . import dlmm
from .dlmm_paper import CAPITAL, ENTRY_COST, EXIT_COST
from .dlmm_tape import VerifiedTape
from .provider import Unavailable

DEFAULT_HORIZON_SECONDS = 60
DEFAULT_HURDLE_BPS = 35
DEFAULT_NEAR_BIN_DISTANCE = 1


def _to_sol(state, amount, token, bin_id):
    amount = int(amount)
    if amount <= 0:
        return 0
    if token == dlmm.WSOL:
        return amount
    p = dlmm.price(int(bin_id), state["step"])
    if state["y"] == dlmm.WSOL:
        return amount * p // dlmm.Q
    return amount * dlmm.Q // p


def proposed_range_ids(state, width):
    width = int(width)
    if width <= 0:
        raise ValueError("dlmm_range_width")
    active = int(state["active"])
    sol_y = state["y"] == dlmm.WSOL
    ids = (
        list(range(active - width, active))
        if sol_y
        else list(range(active + 1, active + width + 1))
    )
    if any(str(bid) not in state["bins"] for bid in ids):
        raise Unavailable("dlmm_research_missing_range_bin")
    return ids


def _range_liquidity_sol(state, ids):
    total = 0
    by_bin = {}
    for bid in ids:
        row = state["bins"][str(bid)]
        value = (
            _to_sol(state, row.get("x", 0), state["x"], bid)
            + _to_sol(state, row.get("y", 0), state["y"], bid)
        )
        by_bin[str(bid)] = int(value)
        total += int(value)
    return total, by_bin


def _lp_fee_amount(item):
    fee = int(item.get("fee", 0))
    if "protocol_fee_pre_host" in item:
        protocol_pre = int(item.get("protocol_fee_pre_host", 0))
    else:
        protocol_pre = int(item.get("protocol_fee", 0)) + int(item.get("host_fee", 0))
    return max(0, fee - protocol_pre)


def _distance_to_range(bin_id, lower, upper):
    if lower <= bin_id <= upper:
        return 0
    return lower - bin_id if bin_id < lower else bin_id - upper


def range_economic_case(
    decision_state,
    warmup_start_state,
    warmup_tape,
    strategy,
    width,
    observation_seconds,
    *,
    capital_lamports=CAPITAL,
    fixed_cost_lamports=ENTRY_COST + EXIT_COST,
    horizon_seconds=DEFAULT_HORIZON_SECONDS,
    hurdle_bps=DEFAULT_HURDLE_BPS,
    near_bin_distance=DEFAULT_NEAR_BIN_DISTANCE,
):
    """Return a point-in-time economic case for the proposed liquidity range.

    The strategy name is retained for lineage. Range placement follows the current
    one-sided research convention used by the fixed sdk_bidask/width experiment.
    """
    if not isinstance(warmup_tape, VerifiedTape):
        raise TypeError("dlmm_range_case_verified_tape_required")
    if int(observation_seconds) <= 0 or int(horizon_seconds) <= 0:
        raise ValueError("dlmm_range_case_horizon")
    if int(capital_lamports) <= 0 or int(fixed_cost_lamports) < 0:
        raise ValueError("dlmm_range_case_capital")
    if int(near_bin_distance) < 0:
        raise ValueError("dlmm_range_case_near_distance")

    ids = proposed_range_ids(decision_state, width)
    lower, upper = min(ids), max(ids)
    range_liquidity, liquidity_by_bin = _range_liquidity_sol(decision_state, ids)

    state = dict(warmup_start_state)
    state["bins"] = {k: dict(v) for k, v in warmup_start_state["bins"].items()}
    in_volume = near_volume = in_lp_fee = near_lp_fee = 0
    range_hit_swaps = near_hit_swaps = 0
    direction_volume = {True: 0, False: 0}

    for event in warmup_tape.events:
        host = int((event.get("observed") or {}).get("host_fee", 0))
        input_token = state["x"] if event["for_y"] else state["y"]
        next_state, quote = dlmm.swap(
            state,
            int(event["amount"]),
            bool(event["for_y"]),
            int(event["time"]),
            host_fee=host if host else None,
        )
        event_range_hit = False
        event_near_hit = False
        for item in quote.get("traversed", ()):
            bid = int(item["bin"])
            volume_sol = _to_sol(state, item.get("input", 0), input_token, bid)
            fee_sol = _to_sol(state, _lp_fee_amount(item), input_token, bid)
            dist = _distance_to_range(bid, lower, upper)
            if dist == 0:
                in_volume += volume_sol
                in_lp_fee += fee_sol
                event_range_hit = True
            if dist <= int(near_bin_distance):
                near_volume += volume_sol
                near_lp_fee += fee_sol
                event_near_hit = True
        if event_range_hit:
            range_hit_swaps += 1
        if event_near_hit:
            near_hit_swaps += 1
        direction_volume[bool(event["for_y"])] += _to_sol(
            state, int(event["amount"]), input_token, int(quote["start"])
        )
        state = next_state

    capital_share_bps = (
        10_000
        if range_liquidity <= 0
        else int(capital_lamports) * 10_000 // (int(range_liquidity) + int(capital_lamports))
    )
    fee_capture_observed = in_lp_fee * capital_share_bps // 10_000
    projected_fee_capture = (
        fee_capture_observed * int(horizon_seconds) // int(observation_seconds)
    )
    projected_net = projected_fee_capture - int(fixed_cost_lamports)
    projected_net_bps = projected_net * 10_000 / int(capital_lamports)

    total_direction = sum(direction_volume.values())
    direction_balance = (
        0.0
        if total_direction <= 0
        else 2 * min(direction_volume.values()) / total_direction
    )
    near_to_range_volume_ratio = (
        None if near_volume <= 0 else in_volume / near_volume
    )

    return dict(
        research_only=True,
        allocation_authority=False,
        outcome_data_used=False,
        model="range_fee_case_v1",
        strategy=str(strategy),
        width=int(width),
        lower_bin=lower,
        upper_bin=upper,
        range_bins=ids,
        observation_seconds=int(observation_seconds),
        horizon_seconds=int(horizon_seconds),
        hurdle_bps=int(hurdle_bps),
        capital_lamports=int(capital_lamports),
        fixed_cost_lamports=int(fixed_cost_lamports),
        range_liquidity_sol_lamports=int(range_liquidity),
        range_liquidity_by_bin=liquidity_by_bin,
        capital_share_proxy_bps=int(capital_share_bps),
        range_crossing_volume_sol_lamports=int(in_volume),
        near_range_volume_sol_lamports=int(near_volume),
        range_lp_fee_sol_lamports=int(in_lp_fee),
        near_range_lp_fee_sol_lamports=int(near_lp_fee),
        range_hit_swaps=int(range_hit_swaps),
        near_range_hit_swaps=int(near_hit_swaps),
        range_volume_share_of_near=near_to_range_volume_ratio,
        direction_balance=float(direction_balance),
        projected_60s_fee_capture_lamports=int(projected_fee_capture),
        projected_60s_net_lamports=int(projected_net),
        projected_60s_net_bps=float(projected_net_bps),
        passes_pre_entry_hurdle=bool(projected_net_bps >= int(hurdle_bps)),
        fee_capture_is_proxy=True,
        note=(
            "Pre-entry research case only. Verified warmup flow is mapped to the exact "
            "proposed range; projected fee capture uses decision-time range liquidity "
            "and cannot authorize allocation."
        ),
    )
