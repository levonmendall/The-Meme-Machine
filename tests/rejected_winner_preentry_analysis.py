"""Pre-entry rejected-winner development study.

This is hypothesis generation only. It reads a completed natural outcome study,
uses future outcomes only to label historical development examples, and freezes
prospective cohort membership using pre-entry fields only. It never creates order
authority or changes continuation-v1.
"""
from __future__ import annotations
import argparse
import json
from collections import Counter
from pathlib import Path

OUT=Path("pump-rejected-winner-preentry-analysis.json")
CLEAN_MFE_BPS=1500
CLEAN_MAE_FLOOR_BPS=-1000

# Frozen prospective research hypothesis derived from the completed development
# artifact. These are all point-in-time pre-entry fields.
HYPOTHESIS=dict(
    id="concentration_dense_activity_v1",
    authority="research_only",
    automatic_trading_admission=False,
    current_policy_unchanged=True,
    required_actual_reason="concentration",
    min_evidence_events=25,
    min_independent_group_fraction=0.02,
    max_features=3,
    fresh_validation_min_matching=30,
    fresh_validation_min_concentration_controls=30,
    rule_must_not_be_refit_during_validation=True,
    validation_success=dict(
        clean_winner_rate_lift_vs_concentration_controls_min=2.0,
        matching_clean_winner_rate_min=0.15,
        matching_median_mae_bps_gt=-1000,
        matching_below_minus_10pct_rate_max=0.50,
    ),
)


def _clean(row):
    future=row.get("future_outcomes") or {}
    mfe=future.get("max_favorable_bps")
    mae=future.get("max_adverse_bps")
    return (
        isinstance(mfe,(int,float)) and isinstance(mae,(int,float))
        and mfe>=CLEAN_MFE_BPS and mae>CLEAN_MAE_FLOOR_BPS
    )


def _outcome_present(row):
    future=row.get("future_outcomes") or {}
    return (
        isinstance(future.get("max_favorable_bps"),(int,float))
        and isinstance(future.get("max_adverse_bps"),(int,float))
    )


def _features(row):
    q=row.get("qualification_vector") or {}
    events=q.get("evidence_event_count")
    groups=q.get("independent_buyer_groups")
    group_fraction=(
        None if not isinstance(events,(int,float)) or events<=0
        or not isinstance(groups,(int,float))
        else groups/events
    )
    return dict(
        actual_reason=row.get("actual_reason"),
        concentration_bps=q.get("concentration_bps"),
        real_sol_lamports=q.get("real_sol_lamports"),
        evidence_event_count=events,
        independent_buyer_groups=groups,
        independent_group_fraction=group_fraction,
        independent_net_buy_lamports=q.get("independent_net_buy_lamports"),
        price_extension_bps=q.get("price_extension_bps"),
        roundtrip_loss_bps=q.get("roundtrip_loss_bps"),
        signal_age_seconds=q.get("signal_age_seconds"),
        quote_age_seconds=q.get("quote_age_seconds"),
        all_rejections=list(q.get("all_rejections") or []),
    )


def hypothesis_match(row):
    f=_features(row)
    return bool(
        f["actual_reason"]==HYPOTHESIS["required_actual_reason"]
        and isinstance(f["evidence_event_count"],(int,float))
        and f["evidence_event_count"]>=HYPOTHESIS["min_evidence_events"]
        and isinstance(f["independent_group_fraction"],(int,float))
        and f["independent_group_fraction"]>=HYPOTHESIS["min_independent_group_fraction"]
    )


def _summary(rows):
    if not rows:
        return dict(count=0,clean_winners=0,clean_winner_rate=None)
    clean=sum(_clean(r) for r in rows)
    future=[r.get("future_outcomes") or {} for r in rows if _outcome_present(r)]
    maes=[r["max_adverse_bps"] for r in future]
    mfes=[r["max_favorable_bps"] for r in future]
    def median(values):
        s=sorted(values);n=len(s)
        if not n:return None
        return s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2
    return dict(
        count=len(rows),clean_winners=clean,clean_winner_rate=clean/len(rows),
        median_mfe_bps=median(mfes),median_mae_bps=median(maes),
        below_minus_10pct=sum(x<=-1000 for x in maes),
        below_minus_10pct_rate=(None if not maes else sum(x<=-1000 for x in maes)/len(maes)),
    )


def prospective_validation_summary(rows):
    eligible=[
        r for r in rows
        if r.get("evidence_stage")=="complete" and _outcome_present(r)
    ]
    matched=[r for r in eligible if hypothesis_match(r)]
    controls=[
        r for r in eligible
        if r.get("actual_reason")=="concentration" and not hypothesis_match(r)
    ]
    match=_summary(matched);control=_summary(controls)
    lift=(
        None if not control.get("clean_winner_rate")
        else match.get("clean_winner_rate",0)/control["clean_winner_rate"]
    )
    ready=bool(
        match["count"]>=HYPOTHESIS["fresh_validation_min_matching"]
        and control["count"]>=HYPOTHESIS["fresh_validation_min_concentration_controls"]
    )
    criteria=HYPOTHESIS["validation_success"]
    passed=bool(
        ready
        and lift is not None
        and lift>=criteria["clean_winner_rate_lift_vs_concentration_controls_min"]
        and (match.get("clean_winner_rate") or 0)>=criteria["matching_clean_winner_rate_min"]
        and isinstance(match.get("median_mae_bps"),(int,float))
        and match["median_mae_bps"]>criteria["matching_median_mae_bps_gt"]
        and isinstance(match.get("below_minus_10pct_rate"),(int,float))
        and match["below_minus_10pct_rate"]<=criteria["matching_below_minus_10pct_rate_max"]
    )
    return dict(
        hypothesis_id=HYPOTHESIS["id"],authority="research_only",
        order_authority=False,rule_refit_allowed=False,
        matching=match,concentration_controls=control,
        clean_winner_rate_lift_vs_controls=lift,
        sample_ready=ready,validation_passed=passed,
        trading_authority_granted=False,
    )


def analyze(body):
    natural=[
        r for r in body.get("natural_results") or []
        if r.get("evidence_stage")=="complete" and _outcome_present(r)
    ]
    rejected=[
        r for r in natural
        if not bool((r.get("qualification_vector") or {}).get("current_threshold_pass"))
    ]
    concentration=[r for r in rejected if r.get("actual_reason")=="concentration"]
    matched=[r for r in rejected if hypothesis_match(r)]
    clean=[r for r in rejected if _clean(r)]
    matched_clean=[r for r in matched if _clean(r)]

    by_reason=Counter(r.get("actual_reason") for r in clean)
    overall=_summary(rejected);conc=_summary(concentration);match=_summary(matched)
    lift_all=(
        None if not overall["clean_winner_rate"]
        else match["clean_winner_rate"]/overall["clean_winner_rate"]
    )
    lift_conc=(
        None if not conc["clean_winner_rate"]
        else match["clean_winner_rate"]/conc["clean_winner_rate"]
    )

    winner_rows=[]
    for row in clean:
        f=_features(row);future=row["future_outcomes"]
        winner_rows.append(dict(
            mint=row.get("mint"),qualified_at=row.get("qualified_at"),
            clean_mfe_bps=future.get("max_favorable_bps"),
            clean_mae_bps=future.get("max_adverse_bps"),
            hypothesis_match=hypothesis_match(row),pre_entry=f,
        ))

    freeze_permitted=bool(
        len(matched_clean)>=3 and lift_conc is not None and lift_conc>=2.0
    )
    report=dict(
        kind="pump_rejected_winner_preentry_development_v1",
        source_kind=body.get("kind"),
        qualification_policy=body.get("qualification_policy"),
        authority="research_only",
        automatic_threshold_change=False,
        continuation_v1_unchanged=True,
        future_outcomes_used_only_for_development_labels=True,
        future_outcomes_used_for_prospective_membership=False,
        clean_winner_definition=dict(
            min_mfe_bps=CLEAN_MFE_BPS,mae_must_be_gt_bps=CLEAN_MAE_FLOOR_BPS),
        complete_natural_with_outcomes=len(natural),
        rejected_with_outcomes=overall,
        clean_rejected_winners=len(clean),
        clean_rejected_winners_by_primary_reason=dict(sorted(by_reason.items())),
        concentration_rejected=conc,
        frozen_hypothesis=HYPOTHESIS,
        historical_hypothesis_match=match,
        historical_clean_winner_lift_vs_all_rejected=lift_all,
        historical_clean_winner_lift_vs_concentration_rejected=lift_conc,
        historical_hypothesis_risk_warning=(
            "historical matched cohort remains high-risk; this is not a trading rule"),
        prospective_research_freeze_permitted=freeze_permitted,
        trading_rule_freeze_permitted=False,
        winner_profiles=winner_rows,
        next_step=(
            "collect a fresh natural prospective cohort with membership frozen before outcomes; "
            "do not change continuation-v1 or grant order authority"
        ),
    )
    return report


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--output",default=str(OUT))
    args=ap.parse_args()
    body=json.loads(Path(args.input).read_text())
    report=analyze(body)
    Path(args.output).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "rejected":report["rejected_with_outcomes"]["count"],
        "clean_rejected_winners":report["clean_rejected_winners"],
        "matched":report["historical_hypothesis_match"]["count"],
        "matched_clean":report["historical_hypothesis_match"]["clean_winners"],
        "lift_vs_concentration":report["historical_clean_winner_lift_vs_concentration_rejected"],
        "research_freeze":report["prospective_research_freeze_permitted"],
        "trading_freeze":report["trading_rule_freeze_permitted"],
    },sort_keys=True))


if __name__=="__main__":
    main()
