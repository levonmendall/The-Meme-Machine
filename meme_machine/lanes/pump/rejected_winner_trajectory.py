"""Frozen research-only 15-second trajectory confirmation for rejected Pump winners.

This module cannot grant order authority. It is a prospective research hypothesis
layered after concentration_dense_activity_v1 and before any hypothetical entry.
All fixed economic ceilings/floors reuse continuation-v1 values; only directional
trajectory requirements are new.
"""
from __future__ import annotations

from statistics import mean, median

from .research import CURRENT_THRESHOLDS

RULE = dict(
    id="concentration_dense_activity_15s_trajectory_v1",
    authority="research_only",
    automatic_trading_admission=False,
    continuation_v1_unchanged=True,
    stage1_hypothesis_id="concentration_dense_activity_v1",
    confirmation_seconds=15,
    min_independent_group_delta=1,
    min_independent_net_buy_delta_lamports=1,
    concentration_must_not_increase=True,
    real_sol_must_not_decrease=True,
    min_real_sol_lamports=CURRENT_THRESHOLDS["min_real_sol_lamports"],
    max_price_extension_bps=CURRENT_THRESHOLDS["max_price_extension_bps"],
    max_roundtrip_loss_bps=CURRENT_THRESHOLDS["max_roundtrip_loss_bps"],
    roundtrip_cost_must_not_increase=True,
    independent_group_fraction_must_not_decrease=True,
    price_extension_requires_broadening=True,
    validation_min_confirmed=30,
    validation_min_passes=10,
    rule_must_not_be_refit_during_validation=True,
    success=dict(
        clean_winner_rate_min=0.20,
        median_mae_bps_gt=-1000,
        below_minus_10pct_rate_max=0.50,
        mean_shadow_exit_return_bps_gt=0,
    ),
)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _group_fraction(vector):
    events=vector.get("evidence_event_count")
    groups=vector.get("independent_buyer_groups")
    if not _number(events) or events <= 0 or not _number(groups):
        return None
    return float(groups)/float(events)


def evaluate(initial, confirm):
    """Return frozen trajectory features and pass/fail from point-in-time fields."""
    initial=initial or {}
    confirm=confirm or {}
    required=(
        "concentration_bps","real_sol_lamports","independent_buyer_groups",
        "independent_net_buy_lamports","price_extension_bps","roundtrip_loss_bps",
        "evidence_event_count",
    )
    if any(not _number(initial.get(k)) for k in required):
        return dict(complete=False, passed=False, reason="incomplete_initial_vector")
    if any(not _number(confirm.get(k)) for k in required):
        return dict(complete=False, passed=False, reason="incomplete_confirmation_vector")

    initial_fraction=_group_fraction(initial)
    confirm_fraction=_group_fraction(confirm)
    if initial_fraction is None or confirm_fraction is None:
        return dict(complete=False, passed=False, reason="incomplete_group_fraction")

    group_delta=int(confirm["independent_buyer_groups"])-int(initial["independent_buyer_groups"])
    net_delta=int(confirm["independent_net_buy_lamports"])-int(initial["independent_net_buy_lamports"])
    concentration_delta=int(confirm["concentration_bps"])-int(initial["concentration_bps"])
    liquidity_delta=int(confirm["real_sol_lamports"])-int(initial["real_sol_lamports"])
    extension_delta=int(confirm["price_extension_bps"])-int(initial["price_extension_bps"])
    roundtrip_delta=int(confirm["roundtrip_loss_bps"])-int(initial["roundtrip_loss_bps"])
    fraction_delta=confirm_fraction-initial_fraction

    checks=dict(
        independent_groups_accelerating=group_delta >= RULE["min_independent_group_delta"],
        independent_net_buy_accelerating=net_delta >= RULE["min_independent_net_buy_delta_lamports"],
        concentration_not_worsening=concentration_delta <= 0,
        executable_liquidity_not_worsening=liquidity_delta >= 0,
        executable_liquidity_floor=int(confirm["real_sol_lamports"]) >= RULE["min_real_sol_lamports"],
        price_extension_within_frozen_cap=int(confirm["price_extension_bps"]) <= RULE["max_price_extension_bps"],
        roundtrip_cost_within_frozen_cap=int(confirm["roundtrip_loss_bps"]) <= RULE["max_roundtrip_loss_bps"],
        roundtrip_cost_not_worsening=roundtrip_delta <= 0,
        independent_group_fraction_not_worsening=fraction_delta >= 0,
        price_extension_supported_by_broadening=(extension_delta <= 0 or fraction_delta > 0),
    )
    return dict(
        complete=True,
        passed=all(checks.values()),
        reason=("trajectory_pass" if all(checks.values()) else "trajectory_reject"),
        checks=checks,
        initial_independent_group_fraction=initial_fraction,
        confirmation_independent_group_fraction=confirm_fraction,
        independent_group_delta=group_delta,
        independent_net_buy_delta_lamports=net_delta,
        concentration_delta_bps=concentration_delta,
        real_sol_delta_lamports=liquidity_delta,
        price_extension_delta_bps=extension_delta,
        roundtrip_loss_delta_bps=roundtrip_delta,
        independent_group_fraction_delta=fraction_delta,
    )


def _clean(outcome):
    if not outcome:
        return False
    mfe=outcome.get("max_favorable_bps")
    mae=outcome.get("max_adverse_bps")
    return _number(mfe) and _number(mae) and mfe >= 1500 and mae > -1000


def _cohort(rows):
    outcomes=[r.get("future_outcomes") or {} for r in rows if r.get("future_outcomes")]
    maes=[int(o["max_adverse_bps"]) for o in outcomes if _number(o.get("max_adverse_bps"))]
    mfes=[int(o["max_favorable_bps"]) for o in outcomes if _number(o.get("max_favorable_bps"))]
    exits=[]
    for o in outcomes:
        shadow=o.get("shadow_exit") or {}
        if shadow.get("triggered") and _number(shadow.get("exit_return_bps")):
            exits.append(int(shadow["exit_return_bps"]))
    return dict(
        count=len(rows),
        outcome_labeled=len(outcomes),
        clean_winners=sum(_clean(o) for o in outcomes),
        clean_winner_rate=(None if not outcomes else sum(_clean(o) for o in outcomes)/len(outcomes)),
        median_mfe_bps=(None if not mfes else median(mfes)),
        median_mae_bps=(None if not maes else median(maes)),
        below_minus_10pct=sum(x <= -1000 for x in maes),
        below_minus_10pct_rate=(None if not maes else sum(x <= -1000 for x in maes)/len(maes)),
        shadow_exits=len(exits),
        mean_shadow_exit_return_bps=(None if not exits else mean(exits)),
        median_shadow_exit_return_bps=(None if not exits else median(exits)),
    )


def summarize(rows):
    complete=[r for r in rows if (r.get("trajectory") or {}).get("complete")]
    passed=[r for r in complete if (r.get("trajectory") or {}).get("passed")]
    failed=[r for r in complete if not (r.get("trajectory") or {}).get("passed")]
    pass_summary=_cohort(passed)
    fail_summary=_cohort(failed)
    ready=len(complete) >= RULE["validation_min_confirmed"] and len(passed) >= RULE["validation_min_passes"]
    criteria=RULE["success"]
    validation_passed=bool(
        ready
        and (pass_summary.get("clean_winner_rate") or 0) >= criteria["clean_winner_rate_min"]
        and isinstance(pass_summary.get("median_mae_bps"), (int,float))
        and pass_summary["median_mae_bps"] > criteria["median_mae_bps_gt"]
        and isinstance(pass_summary.get("below_minus_10pct_rate"), (int,float))
        and pass_summary["below_minus_10pct_rate"] <= criteria["below_minus_10pct_rate_max"]
        and isinstance(pass_summary.get("mean_shadow_exit_return_bps"), (int,float))
        and pass_summary["mean_shadow_exit_return_bps"] > criteria["mean_shadow_exit_return_bps_gt"]
    )
    return dict(
        rule_id=RULE["id"],
        authority="research_only",
        continuation_v1_unchanged=True,
        confirmed=len(complete),
        passes=len(passed),
        rejects=len(failed),
        pass_cohort=pass_summary,
        reject_cohort=fail_summary,
        sample_ready=ready,
        validation_passed=validation_passed,
        trading_authority_granted=False,
    )
