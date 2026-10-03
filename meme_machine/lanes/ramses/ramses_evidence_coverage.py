"""Causal Ramses screening telemetry; no strategy or allocation authority.

A completed negative cost-route search is a structural no-trade result.  A
missing or failed cost request is not.  Neither a screen nor its rejection is
receipt/header-authenticated pre-entry reconstruction.
"""
from collections import Counter

from .pipeline import censor_class


EARLY_STRATEGY_REASONS = frozenset((
    "quote_asset_not_usdg", "prior_30m_not_quiet", "position_cap_zero",
))
COMPLETE_STRATEGY_REASONS = frozenset((
    "no_wide_entry_candidate", "no_economic_rebalance_candidate",
))
NO_COST_ROUTE = "no_executable_bounded_wnative_quote_route"


def screen_evidence_status(row):
    """Explain the decision boundary without changing the frozen decision."""
    decision = row.get("decision") or {}
    reasons = [str(reason) for reason in decision.get("reasons") or []]
    cost = row.get("cost_evidence") or {}
    conversion = cost.get("conversion") or {}
    early = [reason for reason in reasons if reason in EARLY_STRATEGY_REASONS]
    status = dict(
        schema="ramses-screen-evidence-v1",
        required_for_strategy_decision=True,
        full_reconstruction_required=True,
        full_reconstruction_requested=False,
        evidence_complete=False,
        screening_only=True,
        decision_reasons=reasons,
        cost_evidence_reason=cost.get("reason"),
        causal_bucket=None,
        failed_stage=None,
        classification=None,
        terminal_reason=None,
    )
    if early:
        status.update(
            required_for_strategy_decision=False,
            full_reconstruction_required=False,
            causal_bucket="valid_early_strategy_rejection",
            classification="strategy_rejection", terminal_reason=early[0],
        )
    elif (
        not decision.get("qualified")
        and "cost_evidence_unavailable" in reasons
        and cost.get("source") == "automatic_onchain"
        and cost.get("available") is False
        and cost.get("reason") == NO_COST_ROUTE
        and conversion.get("available") is False
        and conversion.get("reason") == NO_COST_ROUTE
    ):
        # This reason is emitted only after all existing bounded direct/bridge
        # routes have been authenticated and quoted without an acquisition error.
        status.update(
            required_for_strategy_decision=False,
            full_reconstruction_required=False,
            causal_bucket="valid_early_structural_rejection",
            classification="strategy_rejection", terminal_reason=NO_COST_ROUTE,
        )
    elif (
        not decision.get("qualified") and reasons
        and set(reasons).issubset(COMPLETE_STRATEGY_REASONS)
        and cost.get("available") is True
        and row.get("wide_state_hydrated") is True
    ):
        status.update(
            required_for_strategy_decision=False,
            full_reconstruction_required=False,
            causal_bucket="full_reconstruction_became_unnecessary",
            classification="strategy_rejection", terminal_reason=reasons[0],
        )
    elif decision.get("qualified") is True:
        # The connected lifecycle, not the screening row, must supply promotion.
        status.update(causal_bucket="pending_authenticated_reconstruction")
    else:
        reason = str(cost.get("reason") or "cost_evidence_unavailable")
        construction = next((r for r in reasons if r.startswith("strategy_construction:")), None)
        missing_cost = cost.get("available") is not True
        if not missing_cost:
            reason = construction or (reasons[0] if reasons else "screen_evidence_unclassified")
        classification = censor_class(reason)
        bucket = {
            "provider_failed": "provider_failure",
            "consumer_deadline": "deadline_failure",
        }.get(classification, "required_evidence_genuinely_failed")
        status.update(
            causal_bucket=bucket,
            failed_stage="cost_evidence" if missing_cost else "range_construction",
            classification=classification, terminal_reason=reason,
        )
    return status


def screening_evidence_summary(screens, coverage=None):
    """Keep pool identities and pool/frontier attempts as explicit denominators."""
    candidates = set()
    requiring = set()
    unnecessary = set()
    failures = set()
    buckets = Counter()
    candidate_buckets = {}
    attempts = 0
    for screen in screens:
        for row in screen.get("rows") or []:
            status = row.get("evidence_status") or {}
            if not status:
                continue
            attempts += 1
            pool = str(row["pool"])
            candidates.add(pool)
            bucket = status["causal_bucket"]
            buckets[bucket] += 1
            candidate_buckets.setdefault(bucket, set()).add(pool)
            if status["required_for_strategy_decision"]:
                requiring.add(pool)
            else:
                unnecessary.add(pool)
            if status.get("failed_stage"):
                failures.add(pool)
    stages = (coverage or {}).get("stages") or {}
    return dict(
        schema="ramses-screen-evidence-summary-v1",
        identity_scope="unique pools; pool/frontier attempts counted separately; candidate buckets may overlap across frontiers",
        screened_candidates=len(candidates), screening_attempts=attempts,
        candidates_requiring_full_evidence=len(requiring),
        evidence_requested=int(stages.get("evidence_requested") or 0),
        evidence_completed_in_time=int(stages.get("evidence_complete") or 0),
        full_reconstruction_requested=int(stages.get("reconstruction_started") or 0),
        required_evidence_failed=len(failures),
        full_reconstruction_unnecessary_after_valid_rejection=len(unnecessary),
        causal_attempt_counts=dict(sorted(buckets.items())),
        causal_candidate_counts={k: len(v) for k, v in sorted(candidate_buckets.items())},
        completion_authority="opportunity_coverage reconstruction_complete/evidence_complete require connected receipt/header authentication",
    )


def route_preflight_rows(screen):
    """Keep early structural decisions in the opportunity denominator."""
    return [dict(pool=row['pool'],decision=dict(qualified=False,mode='no_trade',
        reasons=['cost_evidence_unavailable']),cost_evidence=row['cost_evidence'],
        wide_state_hydrated=False,route_preflight=True)
        for row in screen.get('route_preflight',[]) if row.get('deep_hydration_avoided')]
