"""Frozen research controller for Ramses Active Wide Maker rebalance v3.

Independent of the legacy Ramses fee-pulse policy. No allocation authority,
provider calls, signing, or transaction submission. The controller consumes
already-authenticated state and candidate economics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from . import BoundaryError

VERSION = "ramses-active-wide-maker-rebalance-v3"
PAPER_ONLY = True
ALLOCATION_AUTHORITY = False

WIDTH_CANDIDATES = (65, 90, 120, 150, 200)
MIN_WIDTH = 65
MAX_LOCAL_LIQUIDITY_BPS = 50
SIZE_REDUCTION_BPS = (50, 25, 12, 6, 3, 1)
TARGET_REMINT_SECONDS = 180
HARD_REMINT_DEADLINE_SECONDS = 210

INSIDE_MAX_D = 1.0
WATCH_MAX_D = 1.5
RECENTER_MAX_D = 3.0

COMPOUND_OVERLAP_MIN = 0.50
RECENTER_OVERLAP_MAX = 0.10
CAPITAL_RATIO_MIN = 0.80
CAPITAL_RATIO_MAX = 1.20


@dataclass(frozen=True)
class ReplacementCandidate:
    width_bins: int
    sidedness: str
    active_inside: bool
    full_unwind_executable: bool
    after_cost_fee_return_bps: int | float | None
    two_x_cost_return_bps: int | float | None
    overlap_fraction: float
    capital_preservation_ratio: int | float | None
    size_bps: int | None = None


def normalized_displacement(lower_bin: int, upper_bin: int, active_bin: int) -> float:
    lower=int(lower_bin);upper=int(upper_bin);active=int(active_bin)
    if lower>upper:
        raise BoundaryError("wide_maker_invalid_range")
    center=(lower+upper)/2.0
    half=max(0.5,(upper-lower)/2.0)
    return abs(active-center)/half


def _validate_candidate(candidate: ReplacementCandidate) -> None:
    if candidate.width_bins < 1:
        raise BoundaryError("wide_maker_invalid_width")
    if not 0.0 <= float(candidate.overlap_fraction) <= 1.0:
        raise BoundaryError("wide_maker_invalid_overlap")
    if candidate.size_bps is not None and candidate.size_bps not in SIZE_REDUCTION_BPS:
        raise BoundaryError("wide_maker_invalid_size")


def candidate_eligible(candidate: ReplacementCandidate, *, mode: str) -> bool:
    _validate_candidate(candidate)
    if mode not in ("compound_resize","recenter"):
        raise BoundaryError("wide_maker_invalid_mode")
    if candidate.width_bins < MIN_WIDTH or candidate.width_bins not in WIDTH_CANDIDATES:
        return False
    if candidate.sidedness != "two_sided":
        return False
    if not candidate.active_inside or not candidate.full_unwind_executable:
        return False
    if candidate.after_cost_fee_return_bps is None or candidate.after_cost_fee_return_bps <= 0:
        return False
    if candidate.two_x_cost_return_bps is None or candidate.two_x_cost_return_bps <= 0:
        return False
    ratio=candidate.capital_preservation_ratio
    if ratio is None or not CAPITAL_RATIO_MIN <= float(ratio) <= CAPITAL_RATIO_MAX:
        return False
    overlap=float(candidate.overlap_fraction)
    if mode=="compound_resize":
        return overlap >= COMPOUND_OVERLAP_MIN
    return overlap <= RECENTER_OVERLAP_MAX


def select_replacement(candidates: Iterable[ReplacementCandidate], *, mode: str):
    eligible=[c for c in candidates if candidate_eligible(c,mode=mode)]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda c:(float(c.after_cost_fee_return_bps),-int(c.width_bins)),
    )


def choose_executable_size(
    executable_by_bps: Mapping[int,bool],
    *,
    governed_target_bps: int=MAX_LOCAL_LIQUIDITY_BPS,
):
    if governed_target_bps <= 0 or governed_target_bps > MAX_LOCAL_LIQUIDITY_BPS:
        raise BoundaryError("wide_maker_invalid_governed_size")
    for bps in SIZE_REDUCTION_BPS:
        if bps <= governed_target_bps and executable_by_bps.get(bps) is True:
            return bps
    return None


def _risk_exit(
    *,
    unwind_deteriorated: bool,
    inventory_risk_quote: int | float,
    remaining_fee_reserve_quote: int | float,
) -> bool:
    return bool(unwind_deteriorated) or float(inventory_risk_quote) > float(remaining_fee_reserve_quote)


def rebalance_decision(
    *,
    lower_bin: int,
    upper_bin: int,
    active_bin: int,
    evidence_complete: bool,
    current_unwind_executable: bool,
    fee_reserve_quote: int | float,
    rebalance_cycle_cost_quote: int | float,
    inventory_risk_quote: int | float,
    remaining_fee_reserve_quote: int | float,
    unwind_deteriorated: bool,
    candidates: Sequence[ReplacementCandidate],
):
    """Apply the frozen v3 hysteresis controller."""
    if not evidence_complete:
        return {"action":"fail_closed","reason":"evidence_incomplete","replacement":None}
    if rebalance_cycle_cost_quote < 0 or fee_reserve_quote < 0:
        raise BoundaryError("wide_maker_invalid_cost_or_fee")

    d=normalized_displacement(lower_bin,upper_bin,active_bin)
    risk_exit=_risk_exit(
        unwind_deteriorated=unwind_deteriorated,
        inventory_risk_quote=inventory_risk_quote,
        remaining_fee_reserve_quote=remaining_fee_reserve_quote,
    )

    if d <= INSIDE_MAX_D:
        if risk_exit:
            return {"action":"exit","reason":"risk_exit_inside","D":d,"replacement":None}
        economic_compound=(
            current_unwind_executable
            and float(fee_reserve_quote) >= 2.0*float(rebalance_cycle_cost_quote)
        )
        if not economic_compound:
            return {"action":"hold","reason":"inside_productive_range","D":d,"replacement":None}
        choice=select_replacement(candidates,mode="compound_resize")
        if choice is None:
            return {"action":"hold","reason":"no_valid_compound_replacement","D":d,"replacement":None}
        return {"action":"compound_resize","reason":"fee_reserve_pays_rebalance","D":d,
                "replacement":choice.__dict__}

    if d < WATCH_MAX_D:
        if risk_exit or not current_unwind_executable:
            return {"action":"exit","reason":"edge_watch_risk_exit","D":d,"replacement":None}
        return {"action":"watch","reason":"hysteresis_no_partial_shift","D":d,"replacement":None}

    if d <= RECENTER_MAX_D:
        if not current_unwind_executable:
            return {"action":"exit","reason":"current_unwind_unavailable","D":d,"replacement":None}
        choice=select_replacement(candidates,mode="recenter")
        if choice is None:
            return {"action":"exit","reason":"no_valid_recenter_replacement","D":d,"replacement":None}
        return {"action":"recenter","reason":"normalized_displacement_recenter_band","D":d,
                "replacement":choice.__dict__}

    return {"action":"exit_no_chase","reason":"normalized_displacement_overrun","D":d,"replacement":None}


def remint_deadline_action(elapsed_seconds: int | float):
    elapsed=float(elapsed_seconds)
    if elapsed < 0:
        raise BoundaryError("wide_maker_invalid_elapsed")
    if elapsed <= HARD_REMINT_DEADLINE_SECONDS:
        return {"action":"continue_same_decision","stale":False,"elapsed_seconds":elapsed}
    return {"action":"discard_and_recompute","stale":True,"elapsed_seconds":elapsed}
