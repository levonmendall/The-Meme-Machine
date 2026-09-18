"""Offline development-only analysis for the DLMM economic rule.

This module consumes only completed development reports. It searches a small,
predeclared grid over normalized price distance and extra projected fee-surplus
margin. It can emit a *proposal* after the minimum development sample exists, but it
never writes/finalizes the frozen holdout rule automatically.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

from meme_machine.dlmm_paper import ENTRY_COST, EXIT_COST
from tests import dlmm_strategy_economics as economics

FIXED_COST = ENTRY_COST + EXIT_COST
SURPLUS_MARGIN_LAMPORTS = (
    0,
    FIXED_COST // 2,
    FIXED_COST,
    FIXED_COST * 2,
)
MIN_RULE_SELECTED = 5
MIN_RULE_DISTINCT_POOLS = 3
PROPOSAL = Path("dlmm-strategy-rule-proposal.json")


def _eligible(features, margin):
    return (
        features["projected_60s_range_fee_surplus_lamports"] >= margin
        and features["flow_into_range_volume_sol_lamports"] > 0
        and features["away_from_range_volume_sol_lamports"] > 0
        and (
            features["reversal_count"] > 0
            or features["touch_then_revert"]
            or features["two_way_balance"] > 0
        )
    )


def _completed_keys(report):
    return {
        (item["pool"], item["entry_slot"], item["end_slot"])
        for item in report.get("opportunities", [])
    }


def propose_rule(reports):
    reports = list(reports)
    if not reports:
        return dict(status="insufficient_development_sample", reason="no_reports")
    if any(report.get("study_phase") != "development" for report in reports):
        raise ValueError("dlmm_development_analyzer_non_development_report")

    completed = set()
    pools = set()
    rows = []
    for report in reports:
        completed.update(_completed_keys(report))
        pools.update(item["pool"] for item in report.get("opportunities", []))
        rows.extend(
            row for row in report.get("normalized_results", [])
            if row.get("sample_role") == "development" and row.get("resolved")
        )

    if (
        len(completed) < economics.DEVELOPMENT_MIN_COMPLETED
        or len(pools) < economics.DEVELOPMENT_MIN_DISTINCT_POOLS
    ):
        return dict(
            status="insufficient_development_sample",
            completed=len(completed),
            distinct_pools=len(pools),
            required_completed=economics.DEVELOPMENT_MIN_COMPLETED,
            required_distinct_pools=economics.DEVELOPMENT_MIN_DISTINCT_POOLS,
        )

    candidates = []
    for target in economics.NORMALIZED_TARGET_BPS:
        target_rows = [
            row for row in rows if int(row["target_distance_bps"]) == int(target)
        ]
        for margin in SURPLUS_MARGIN_LAMPORTS:
            selected = [
                row for row in target_rows
                if _eligible(row["pre_entry_features"], margin)
            ]
            selected_pools = {row["pool"] for row in selected}
            if (
                len(selected) < MIN_RULE_SELECTED
                or len(selected_pools) < MIN_RULE_DISTINCT_POOLS
            ):
                continue
            pnl = [float(row["pnl_bps"]) for row in selected]
            candidates.append(dict(
                strategy="sdk_bidask",
                target_distance_bps=int(target),
                min_projected_60s_fee_surplus_lamports=int(margin),
                require_flow_into_range=True,
                require_two_way_or_revert=True,
                development_selected_count=len(selected),
                development_distinct_pools=len(selected_pools),
                development_median_pnl_bps=statistics.median(pnl),
                development_mean_pnl_bps=statistics.fmean(pnl),
                development_min_pnl_bps=min(pnl),
                development_profitable_rate=sum(value > 0 for value in pnl) / len(pnl),
            ))

    if not candidates:
        return dict(
            status="no_rule_candidate_meets_development_support",
            completed=len(completed),
            distinct_pools=len(pools),
            predeclared_targets=list(economics.NORMALIZED_TARGET_BPS),
            predeclared_surplus_margins=list(SURPLUS_MARGIN_LAMPORTS),
        )

    # Selection is confined to the development set. The ordering is predeclared:
    # robust center first, then mean, worst observed outcome, and finally sample size.
    candidates.sort(
        key=lambda row: (
            row["development_median_pnl_bps"],
            row["development_mean_pnl_bps"],
            row["development_min_pnl_bps"],
            row["development_selected_count"],
        ),
        reverse=True,
    )
    winner = dict(candidates[0])
    return dict(
        version=1,
        status="proposed",
        automatic_freeze=False,
        development_completed=len(completed),
        development_distinct_pools=len(pools),
        development_rule_search=dict(
            targets_bps=list(economics.NORMALIZED_TARGET_BPS),
            surplus_margin_lamports=list(SURPLUS_MARGIN_LAMPORTS),
            min_selected=MIN_RULE_SELECTED,
            min_distinct_pools=MIN_RULE_DISTINCT_POOLS,
            ordering=[
                "median_pnl_bps",
                "mean_pnl_bps",
                "min_pnl_bps",
                "selected_count",
            ],
        ),
        proposal=winner,
        all_supported_candidates=candidates,
        next_step=(
            "Human review must explicitly copy the approved proposal into "
            "DLMM_STRATEGY_RULE_V1.json, set status=frozen, record frozen_at and "
            "development_cutoff_time, and commit it before any holdout run."
        ),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--output", default=str(PROPOSAL))
    args = parser.parse_args()
    bodies = [json.loads(Path(path).read_text()) for path in args.reports]
    result = propose_rule(bodies)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
