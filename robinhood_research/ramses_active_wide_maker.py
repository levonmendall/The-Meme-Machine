"""Evidence-locked shadow controller for Ramses Active Wide Maker rebalance v1.

Derived from the pre-holdout profitable-operator study. This module has no
allocation authority, provider calls, signing, or submission capability.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from . import BoundaryError

VERSION = "ramses-active-wide-maker-rebalance-v1"
PAPER_ONLY = True
ALLOCATION_AUTHORITY = False

MIN_WIDTH_BINS = 65
MAX_WIDTH_BINS = 200
PROACTIVE_D = 0.50
HARD_D = 1.00
CAPITAL_RATIO_MIN = 0.80
CAPITAL_RATIO_MAX = 1.20
REMINT_MAX_SECONDS = 180

MAX_LOCAL_LIQUIDITY_BPS = 50
SIZE_REDUCTION_BPS = (50, 25, 12, 6, 3, 1)


@dataclass(frozen=True)
class ReplacementCandidate:
    width_bins: int
    sidedness: str
    active_inside: bool
    full_unwind_executable: bool
    after_cost_return_bps: int | float | None
    two_x_cost_return_bps: int | float | None
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
    if candidate.size_bps is not None and candidate.size_bps not in SIZE_REDUCTION_BPS:
        raise BoundaryError("wide_maker_invalid_size")


def candidate_eligible(
    candidate: ReplacementCandidate,
    *,
    allow_directional_repair: bool=False,
) -> bool:
    """Hard replacement gates from the operator study.

    Two-sided placement is the v1 default. A directional repair must be
    explicitly authorized by a separate validated mode.
    """
    _validate_candidate(candidate)
    if not MIN_WIDTH_BINS <= int(candidate.width_bins) <= MAX_WIDTH_BINS:
        return False
    if not candidate.full_unwind_executable:
        return False
    if candidate.after_cost_return_bps is None or float(candidate.after_cost_return_bps) <= 0:
        return False
    if candidate.two_x_cost_return_bps is None or float(candidate.two_x_cost_return_bps) <= 0:
        return False
    ratio=candidate.capital_preservation_ratio
    if ratio is None or not CAPITAL_RATIO_MIN <= float(ratio) <= CAPITAL_RATIO_MAX:
        return False
    if candidate.sidedness!="two_sided" and not allow_directional_repair:
        return False
    return True


def select_replacement(
    candidates: Iterable[ReplacementCandidate],
    *,
    allow_directional_repair: bool=False,
):
    eligible=[
        c for c in candidates
        if candidate_eligible(c,allow_directional_repair=allow_directional_repair)
    ]
    if not eligible:
        return None
    # Economic quality first. On an exact tie, prefer the narrower candidate
    # within the already-wide 65-200 bin band to avoid unnecessary inventory.
    return max(
        eligible,
        key=lambda c:(
            float(c.two_x_cost_return_bps),
            float(c.after_cost_return_bps),
            -int(c.width_bins),
        ),
    )


def choose_executable_size(
    executable_by_bps,
    *,
    governed_target_bps: int=MAX_LOCAL_LIQUIDITY_BPS,
):
    if governed_target_bps <= 0 or governed_target_bps > MAX_LOCAL_LIQUIDITY_BPS:
        raise BoundaryError("wide_maker_invalid_governed_size")
    for bps in SIZE_REDUCTION_BPS:
        if bps <= governed_target_bps and executable_by_bps.get(bps) is True:
            return bps
    return None


def rebalance_decision(
    *,
    lower_bin: int,
    upper_bin: int,
    active_bin: int,
    evidence_complete: bool,
    current_unwind_executable: bool,
    candidates: Iterable[ReplacementCandidate],
    allow_directional_repair: bool=False,
):
    """Apply the frozen v1 pre-burn state machine.

    Actions:
      hold       - remain in the current range.
      rebalance  - burn only with a valid replacement already preflighted.
      exit       - burn to USDG/cash; do not chase a replacement.
      fail_closed- evidence is incomplete/stale.
    """
    if not evidence_complete:
        return {"action":"fail_closed","reason":"evidence_incomplete","replacement":None}

    width=int(upper_bin)-int(lower_bin)+1
    if width <= 0:
        raise BoundaryError("wide_maker_invalid_range")
    d=normalized_displacement(lower_bin,upper_bin,active_bin)
    outside=active_bin<lower_bin or active_bin>upper_bin
    hard=outside or d>=HARD_D or width<MIN_WIDTH_BINS or not current_unwind_executable

    choice=select_replacement(
        candidates,
        allow_directional_repair=allow_directional_repair,
    )

    if hard:
        if choice is None:
            return {"action":"exit","reason":"hard_zone_no_valid_replacement","D":d,"replacement":None}
        return {"action":"rebalance","reason":"hard_zone_valid_replacement","D":d,
                "replacement":choice.__dict__}

    if d>=PROACTIVE_D:
        if choice is None:
            return {"action":"hold","reason":"proactive_zone_replacement_not_ready","D":d,
                    "replacement":None}
        return {"action":"rebalance","reason":"proactive_zone_valid_replacement","D":d,
                "replacement":choice.__dict__}

    return {"action":"hold","reason":"inner_half_valid_range","D":d,"replacement":None}


def post_burn_remint_decision(
    *,
    elapsed_seconds: int | float,
    evidence_complete: bool,
    candidates: Iterable[ReplacementCandidate],
    allow_directional_repair: bool=False,
):
    """After a burn, remint within 180 seconds or remain in USDG/cash."""
    elapsed=float(elapsed_seconds)
    if elapsed < 0:
        raise BoundaryError("wide_maker_invalid_elapsed")
    if not evidence_complete:
        return {"action":"stay_cash","reason":"post_burn_evidence_incomplete","replacement":None}
    if elapsed>REMINT_MAX_SECONDS:
        return {"action":"stay_cash","reason":"remint_window_expired","replacement":None}
    choice=select_replacement(
        candidates,
        allow_directional_repair=allow_directional_repair,
    )
    if choice is None:
        return {"action":"stay_cash","reason":"no_valid_replacement","replacement":None}
    return {"action":"remint","reason":"replacement_contract_passed",
            "replacement":choice.__dict__}
