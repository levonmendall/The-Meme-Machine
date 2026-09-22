"""Create the immutable Branch B holdout rule only after preregistered development passes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ANALYSIS = Path("ramses-branch-b-analysis.json")
COST = Path("ramses-branch-b-cost-anchor.json")
COST_FALLBACK = Path("ramses-branch-b-cost-route-fallback.json")
RULE = Path("RAMSES_BRANCH_B_FROZEN_RULE_V1.json")
FROZEN_COST = Path("RAMSES_BRANCH_B_FROZEN_COST_ANCHOR_V1.json")
FROZEN_COST_FALLBACK = Path("RAMSES_BRANCH_B_FROZEN_COST_ROUTE_FALLBACK_V1.json")


def digest(body):
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def main():
    analysis = json.loads(ANALYSIS.read_text())
    cost = json.loads(COST.read_text())
    fallback = json.loads(COST_FALLBACK.read_text()) if COST_FALLBACK.exists() else None

    if (
        analysis.get("kind") != "ramses_branch_b_analysis_v1"
        or analysis.get("phase") != "development"
    ):
        raise RuntimeError("branch_b_freeze_analysis")

    decision = analysis.get("decision") or {}
    if decision.get("status") != "freeze_ready":
        raise RuntimeError("branch_b_development_not_freeze_ready")

    cost_sha = digest(cost)
    if (
        decision.get("cost_anchor_sha256") != cost_sha
        or analysis.get("cost_anchor_sha256") != cost_sha
    ):
        raise RuntimeError("branch_b_freeze_cost_digest")

    fallback_sha = None
    if fallback is not None:
        if (
            fallback.get("kind") != "ramses_branch_b_cost_route_fallback_v1"
            or fallback.get("frozen") is not True
            or fallback.get("strategy_parameters_changed") is not False
            or fallback.get("cost_model_changed") is not False
            or fallback.get("cost_anchor_sha256") != cost_sha
        ):
            raise RuntimeError("branch_b_freeze_cost_fallback")
        fallback_sha = digest(fallback)

    hold = int(decision["hold_seconds"])
    if hold not in (86400, 259200):
        raise RuntimeError("branch_b_freeze_hold")

    selected = decision.get("selected_metrics") or {}
    rule = dict(
        kind="ramses_branch_b_frozen_rule_v1",
        frozen=True,
        research_only=True,
        allocation_authority=False,
        holdout_outcomes_read_before_freeze=False,
        strategy="Ramses Quiet-Mint Harvest v1 / branch_B_public_mint_geometry",
        quote_asset="USDG",
        prior_30m_max_swaps=2,
        prior_24h_min_swaps=10,
        event="finalized public DLMMMint",
        entry="first block after signal mint",
        geometry="exact authenticated public mint bin set, sidedness, and relative distribution",
        sizing_ceiling_bps=50,
        sizing_reduction_schedule_bps=[50, 25, 12, 6, 3, 1],
        full_entry_unwind_required=True,
        hold_seconds=hold,
        rebalance="none",
        conservative_cost_model=(
            "frozen Ramses receipt-gas cycle converted by executable WNATIVE/USDG "
            "route; when an entry-block direct route is unavailable, use the "
            "pre-frozen conservative upper envelope of prior verified direct routes"
        ),
        two_x_cost_stress_required=True,
        cost_anchor_sha256=cost_sha,
        cost_route_fallback_sha256=fallback_sha,
        cost_route_fallback_frozen=(fallback_sha is not None),
        source_development_metrics=selected,
        development_analysis_sha256=digest(analysis),
        holdout_criteria=dict(
            median_after_cost_return_bps=">0",
            mean_after_cost_return_bps=">0",
            win_rate=">0.55",
            minimum_distinct_pools=3,
            two_x_cost_stress_median_bps=">0",
            two_x_cost_stress_mean_bps=">0",
        ),
    )

    RULE.write_text(json.dumps(rule, indent=2, sort_keys=True) + "\n")
    FROZEN_COST.write_text(json.dumps(cost, indent=2, sort_keys=True) + "\n")
    if fallback is not None:
        FROZEN_COST_FALLBACK.write_text(
            json.dumps(fallback, indent=2, sort_keys=True) + "\n"
        )

    print(
        json.dumps(
            {
                "status": "frozen",
                "hold_seconds": hold,
                "cost_anchor_sha256": cost_sha,
                "cost_route_fallback_sha256": fallback_sha,
                "development_analysis_sha256": rule[
                    "development_analysis_sha256"
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
