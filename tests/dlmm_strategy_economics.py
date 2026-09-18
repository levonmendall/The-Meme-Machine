"""Research-only DLMM economic strategy selection.

This module does not grant allocation authority. It converts an authenticated
point-in-time warmup tape into range-specific pre-entry features and compares
price-normalized one-sided SOL bid placements. The existing foundation_spot /
sdk_bidask fixed-width grid remains available as an outcome shadow control.

Development mode is intentionally not a profitability claim. Its provisional gate is
anchored only to the already-modeled round-trip cost hurdle and the market behavior a
one-sided SOL bid needs: actual flow into the proposed range plus subsequent two-way /
reverting activity. Development outcomes are used later to define and freeze a rule.
Holdout mode must use a separately committed frozen rule and cannot auto-tune it.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from meme_machine import dlmm
from meme_machine.dlmm_paper import CAPITAL, ENTRY_COST, EXIT_COST, HOLD_SECONDS
from meme_machine.dlmm_tape import VerifiedTape
from meme_machine.provider import Unavailable
from tests import dlmm_strategy_point_in_time as pit

FIXED_COST = ENTRY_COST + EXIT_COST
FIXED_COST_BPS = FIXED_COST * 10_000 / CAPITAL
NORMALIZED_TARGET_BPS = (100, 200, 400, 800)
APPROACH_THRESHOLDS_BPS = (50, 100, 200)
MIN_NORMALIZED_WIDTH = 2
MAX_NORMALIZED_WIDTH = max(pit.WIDTHS)
RULE_PATH = Path("DLMM_STRATEGY_RULE_V1.json")
DEVELOPMENT_MIN_COMPLETED = 30
DEVELOPMENT_MIN_DISTINCT_POOLS = 5
HOLDOUT_MIN_COMPLETED = 100
HOLDOUT_MIN_DISTINCT_POOLS = 10


def _price_distance_bps(state, bin_id):
    active = state["active"]
    p0 = dlmm.price(active, state["step"])
    p1 = dlmm.price(bin_id, state["step"])
    return abs(p1 - p0) * 10_000 / p0


def width_distance_bps(state, width):
    if type(width) is not int or not MIN_NORMALIZED_WIDTH <= width <= MAX_NORMALIZED_WIDTH:
        raise ValueError("dlmm_economic_width")
    far = state["active"] - width if state["y"] == dlmm.WSOL else state["active"] + width
    return _price_distance_bps(state, far)


def normalized_width(state, target_bps):
    if target_bps <= 0:
        raise ValueError("dlmm_economic_target_distance")
    choices = [
        (abs(width_distance_bps(state, width) - target_bps), width)
        for width in range(MIN_NORMALIZED_WIDTH, MAX_NORMALIZED_WIDTH + 1)
    ]
    return min(choices)[1]


def normalized_placements(state):
    return [
        dict(
            strategy="sdk_bidask",
            target_distance_bps=target,
            width=normalized_width(state, target),
            actual_distance_bps=width_distance_bps(
                state, normalized_width(state, target)
            ),
        )
        for target in NORMALIZED_TARGET_BPS
    ]


def _path_intersects_range(start_bin, end_bin, lower, upper):
    lo, hi = sorted((start_bin, end_bin))
    return hi >= lower and lo <= upper


def _distance_to_range_bps(placement_state, bin_id, lower, upper):
    if lower <= bin_id <= upper:
        return 0.0
    edge = lower if bin_id < lower else upper
    p0 = dlmm.price(edge, state["step"])
    p1 = dlmm.price(bin_id, state["step"])
    return abs(p1 - p0) * 10_000 / p0


def _event_sol_value(history_start, event, key):
    bid = event["observed"]["start"]
    token = state["x"] if event["for_y"] else state["y"]
    return pit._to_sol(state, event[key], token, bid)


def _event_fee_sol(history_start, event):
    bid = event["observed"]["start"]
    token = state["x"] if event["for_y"] else state["y"]
    return pit._to_sol(state, event["observed"]["fee"], token, bid)


def _range_liquidity_sol(state, ids):
    total = 0
    for bid in ids:
        b = state["bins"][str(bid)]
        total += pit._to_sol(state, b["x"], state["x"], bid)
        total += pit._to_sol(state, b["y"], state["y"], bid)
    return total


def range_specific_features(history_start, warmup, strategy, width, placement_state=None):
    """Features known at entry time for exactly the proposed liquidity range.

    The proposed range is anchored to placement_state (the authenticated entry
    snapshot after warmup). Warmup events remain historical evidence only. The exact
    same-width warmup counterfactual is evaluated from history_start because only that
    state can legitimately anchor the verified historical tape.
    """
    if not isinstance(warmup, VerifiedTape):
        raise TypeError("dlmm_economic_verified_warmup_required")
    if strategy not in pit.STRATEGIES:
        raise ValueError("dlmm_economic_strategy")
    placement_state = history_start if placement_state is None else placement_state
    ids = pit._range_ids(placement_state, width)
    lower, upper = min(ids), max(ids)
    events = list(warmup.events)
    range_liquidity = _range_liquidity_sol(placement_state, ids)

    touch_swaps = touch_volume = touch_fees = 0
    approach = {
        threshold: dict(swaps=0, volume_sol_lamports=0, fee_sol_lamports=0)
        for threshold in APPROACH_THRESHOLDS_BPS
    }
    toward_volume = away_volume = flat_volume = 0
    toward_touch_volume = 0
    near_travel = 0
    movement_signs = []
    touch_seen = False
    touch_then_revert = False
    first_near_start = None
    last_near_end = None

    for event in events:
        start_bin = event["observed"]["start"]
        end_bin = event["observed"]["end"]
        volume = _event_sol_value(history_start, event, "amount")
        fee = _event_fee_sol(history_start, event)
        intersects = _path_intersects_range(start_bin, end_bin, lower, upper)
        d0 = _distance_to_range_bps(placement_state, start_bin, lower, upper)
        d1 = _distance_to_range_bps(placement_state, end_bin, lower, upper)
        min_distance = 0.0 if intersects else min(d0, d1)

        if intersects:
            touch_swaps += 1
            touch_volume += volume
            touch_fees += fee
            touch_seen = True

        for threshold in APPROACH_THRESHOLDS_BPS:
            if min_distance <= threshold:
                item = approach[threshold]
                item["swaps"] += 1
                item["volume_sol_lamports"] += volume
                item["fee_sol_lamports"] += fee

        if min_distance <= max(APPROACH_THRESHOLDS_BPS):
            if first_near_start is None:
                first_near_start = start_bin
            last_near_end = end_bin
            near_travel += abs(end_bin - start_bin)
            if d1 < d0:
                toward_volume += volume
                if intersects:
                    toward_touch_volume += volume
            elif d1 > d0:
                away_volume += volume
                if touch_seen:
                    touch_then_revert = True
            else:
                flat_volume += volume
            delta = end_bin - start_bin
            if delta:
                movement_signs.append(1 if delta > 0 else -1)

    reversals = sum(
        1 for left, right in zip(movement_signs, movement_signs[1:])
        if left != right
    )
    directional_volume = toward_volume + away_volume
    two_way_balance = (
        0.0
        if directional_volume <= 0
        else 2 * min(toward_volume, away_volume) / directional_volume
    )
    net_drift = (
        0 if first_near_start is None or last_near_end is None
        else abs(last_near_end - first_near_start)
    )
    drift_ratio = 0.0 if near_travel <= 0 else net_drift / near_travel

    warmup_eval = pit.evaluate(history_start, warmup, strategy, width)
    gross_fee = (
        int(warmup_eval.get("gross_fee_value_lamports", 0))
        if warmup_eval.get("resolved")
        else 0
    )
    observed_seconds = max(
        1, int(warmup.terminal["time"]) - int(history_start["time"])
    )
    projected_60s_fee = gross_fee * HOLD_SECONDS / observed_seconds
    projected_surplus = projected_60s_fee - FIXED_COST

    return dict(
        strategy=strategy,
        width=width,
        lower=lower,
        upper=upper,
        range_distance_bps=width_distance_bps(placement_state, width),
        placement_active_bin=placement_state["active"],
        warmup_start_active_bin=history_start["active"],
        range_liquidity_sol_lamports=range_liquidity,
        range_touch_swaps=touch_swaps,
        range_touch_volume_sol_lamports=touch_volume,
        range_touch_fee_sol_lamports=touch_fees,
        approach_50bps=approach[50],
        approach_100bps=approach[100],
        approach_200bps=approach[200],
        toward_range_volume_sol_lamports=toward_volume,
        away_from_range_volume_sol_lamports=away_volume,
        flat_range_distance_volume_sol_lamports=flat_volume,
        flow_into_range_volume_sol_lamports=toward_touch_volume,
        two_way_balance=two_way_balance,
        near_range_bin_travel=near_travel,
        near_range_net_bin_drift=net_drift,
        near_range_drift_ratio=drift_ratio,
        reversal_count=reversals,
        touch_then_revert=touch_then_revert,
        warmup_counterfactual_resolved=bool(warmup_eval.get("resolved")),
        warmup_counterfactual_pnl_bps=warmup_eval.get("pnl_bps"),
        warmup_counterfactual_gross_fee_lamports=gross_fee,
        warmup_observed_seconds=observed_seconds,
        projected_60s_gross_fee_lamports=projected_60s_fee,
        projected_60s_fee_surplus_lamports=projected_surplus,
        fixed_cost_lamports=FIXED_COST,
        fixed_cost_bps=FIXED_COST_BPS,
    )


def development_economic_case(features):
    """Cost-anchored provisional gate; no outcome data and no fitted thresholds.

    This is intentionally only a development rule. The eventual frozen holdout rule
    must be defined from accumulated development observations and committed separately.
    """
    fee_hurdle = features["projected_60s_fee_surplus_lamports"] >= 0
    flow_into_bid = features["flow_into_range_volume_sol_lamports"] > 0
    two_way_or_revert = (
        features["away_from_range_volume_sol_lamports"] > 0
        and (
            features["reversal_count"] > 0
            or features["touch_then_revert"]
            or features["two_way_balance"] > 0
        )
    )
    return dict(
        passes=bool(fee_hurdle and flow_into_bid and two_way_or_revert),
        fee_hurdle_pass=bool(fee_hurdle),
        flow_into_bid_pass=bool(flow_into_bid),
        two_way_or_revert_pass=bool(two_way_or_revert),
        rule="development_cost_hurdle_plus_range_entry_plus_reversion",
        fitted_thresholds=False,
    )


def development_candidates(history_start, warmup, placement_state=None):
    placement_state = history_start if placement_state is None else placement_state
    rows = []
    seen = set()
    for placement in normalized_placements(placement_state):
        key = (placement["strategy"], placement["width"])
        # Multiple target distances can map to the same integer width on coarse pools.
        # Keep the closest declared target once, while preserving actual distance.
        if key in seen:
            continue
        seen.add(key)
        features = range_specific_features(
            history_start,
            warmup,
            placement["strategy"],
            placement["width"],
            placement_state=placement_state,
        )
        gate = development_economic_case(features)
        rows.append(dict(**placement, features=features, economic_case=gate))
    return rows


def select_development_candidate(history_start, warmup, placement_state=None):
    rows = development_candidates(
        history_start, warmup, placement_state=placement_state
    )
    eligible = [row for row in rows if row["economic_case"]["passes"]]
    if not eligible:
        return None, rows
    eligible.sort(
        key=lambda row: (
            row["features"]["projected_60s_fee_surplus_lamports"],
            row["features"]["two_way_balance"],
            row["features"]["flow_into_range_volume_sol_lamports"],
            -row["features"]["near_range_drift_ratio"],
        ),
        reverse=True,
    )
    selected = eligible[0]
    return dict(
        strategy=selected["strategy"],
        width=selected["width"],
        target_distance_bps=selected["target_distance_bps"],
        actual_distance_bps=selected["actual_distance_bps"],
        rule=selected["economic_case"]["rule"],
        study_phase="development",
        economic_features=selected["features"],
        economic_case=selected["economic_case"],
    ), rows


def load_frozen_rule(path=RULE_PATH):
    if not Path(path).exists():
        raise Unavailable("dlmm_holdout_rule_not_frozen")
    body = json.loads(Path(path).read_text())
    if body.get("status") != "frozen" or body.get("version") != 1:
        raise Unavailable("dlmm_holdout_rule_not_frozen")
    required = {
        "frozen_at",
        "development_cutoff_time",
        "strategy",
        "target_distance_bps",
        "min_projected_60s_fee_surplus_lamports",
        "require_flow_into_range",
        "require_two_way_or_revert",
    }
    if not required.issubset(body):
        raise Unavailable("dlmm_holdout_rule_shape")
    return body


def select_holdout_candidate(
    history_start, warmup, observation_started, rule, placement_state=None
):
    """Apply one already-frozen development rule without fitting on holdout."""
    if observation_started <= int(rule["frozen_at"]):
        raise Unavailable("dlmm_holdout_observation_not_post_freeze")
    placement_state = history_start if placement_state is None else placement_state
    width = normalized_width(
        placement_state, int(rule["target_distance_bps"])
    )
    features = range_specific_features(
        history_start,
        warmup,
        rule["strategy"],
        width,
        placement_state=placement_state,
    )
    fee_ok = (
        features["projected_60s_fee_surplus_lamports"]
        >= int(rule["min_projected_60s_fee_surplus_lamports"])
    )
    flow_ok = (
        not bool(rule["require_flow_into_range"])
        or features["flow_into_range_volume_sol_lamports"] > 0
    )
    revert_ok = (
        not bool(rule["require_two_way_or_revert"])
        or (
            features["away_from_range_volume_sol_lamports"] > 0
            and (
                features["reversal_count"] > 0
                or features["touch_then_revert"]
                or features["two_way_balance"] > 0
            )
        )
    )
    if not (fee_ok and flow_ok and revert_ok):
        return None, features
    return dict(
        strategy=rule["strategy"],
        width=width,
        target_distance_bps=int(rule["target_distance_bps"]),
        actual_distance_bps=width_distance_bps(placement_state, width),
        rule="frozen_holdout_rule_v1",
        study_phase="holdout",
        economic_features=features,
        frozen_rule=dict(rule),
    ), features


def sample_protocol():
    return dict(
        development_min_completed=DEVELOPMENT_MIN_COMPLETED,
        development_min_distinct_pools=DEVELOPMENT_MIN_DISTINCT_POOLS,
        holdout_min_completed=HOLDOUT_MIN_COMPLETED,
        holdout_min_distinct_pools=HOLDOUT_MIN_DISTINCT_POOLS,
        automatic_rule_freeze=False,
        development_profitability_claim_allowed=False,
        holdout_requires_committed_frozen_rule=True,
        holdout_must_begin_after_rule_freeze=True,
    )
