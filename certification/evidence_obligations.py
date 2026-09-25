"""Read-only evidence obligations; no inference from qualification or profitability."""
from collections import Counter
import json


INFRASTRUCTURE = frozenset((
    "provider_failed", "capacity_censored", "consumer_deadline",
    "reconstruction_incomplete", "local_budget_exhausted",
    "stream_gap",
    "stale_before_evidence", "stale_during_evidence", "stale_after_complete_evidence",
))


def summarize(records):
    """Keep repeat observations separate: an earlier rejection cannot erase a loss.

    Only explicit required/not-required markers establish the denominator. Legacy
    artifacts remain unmeasured instead of being retrospectively relabelled.
    Completion means the native path emitted its authenticated completion marker;
    a screening rejection never manufactures one.
    """
    current = {}
    episodes = []
    seen = Counter()
    early_rejections = 0
    unscoped_requests = 0
    orphan_completions = 0
    failures = Counter()
    for row in records:
        candidate, stage = row["candidate"], row["stage"]
        details = row.get('details') or {}
        key = (candidate, details.get('mode'),
               json.dumps(details.get('observation_id', details.get('decision_at', details.get('frontier'))), sort_keys=True))
        seen[stage] += 1
        classification = row.get("classification")
        if classification in INFRASTRUCTURE:
            failures[classification] += 1
        if stage == "evidence_required":
            episode = dict(candidate=candidate, requested=False, outcome="pending_at_observation_close")
            episodes.append(episode)
            current[key] = episode
            continue
        episode = current.get(key)
        if stage == "evidence_not_required":
            if episode and episode["outcome"] == "pending_at_observation_close":
                episode["outcome"] = "became_unnecessary_after_valid_earlier_rejection"
                current.pop(key, None)
            else:
                early_rejections += 1
            continue
        if stage in ("evidence_requested", "full_evidence_requested"):
            if episode:
                episode["requested"] = True
            else:
                unscoped_requests += 1
        elif stage == "evidence_complete":
            if episode and episode["requested"]:
                episode["outcome"] = "evidence_completed_in_time"
            else:
                orphan_completions += 1
        elif classification in INFRASTRUCTURE or classification == 'superseded_candidate_state':
            affected = [episode] if episode else [
                value for identity, value in current.items() if identity[0] == candidate]
            for value in affected:
                if value["outcome"] == "evidence_completed_in_time":
                    continue
                # A later horizon retirement cannot erase the preceding failure.
                if classification in INFRASTRUCTURE:
                    value["outcome"] = "infrastructure_failed"
                elif value["outcome"] != "infrastructure_failed":
                    value["outcome"] = "superseded_candidate_state"
    measured = bool(seen["evidence_required"] or seen["evidence_not_required"])
    outcomes = Counter(e["outcome"] for e in episodes)
    return dict(
        available=measured,
        denominator_status="explicit_native_obligations" if measured else "legacy_requirement_not_recorded",
        identity_scope="candidate observations; repeated required markers create separate obligations",
        candidates_requiring_full_evidence=len({e["candidate"] for e in episodes}) if measured else None,
        observations_requiring_full_evidence=len(episodes) if measured else None,
        evidence_requested=sum(e["requested"] for e in episodes) if measured else None,
        **{key: outcomes[key] if measured else None for key in (
            "evidence_completed_in_time", "infrastructure_failed",
            "became_unnecessary_after_valid_earlier_rejection", "pending_at_observation_close",
            "superseded_candidate_state")},
        valid_rejections_before_full_evidence_required=early_rejections if measured else None,
        decision_evidence_requested=seen["decision_evidence_requested"] if measured else None,
        decision_evidence_complete=seen["decision_evidence_complete"] if measured else None,
        unscoped_full_requests=unscoped_requests,
        completions_without_scoped_request=orphan_completions,
        infrastructure_failure_observations=dict(failures),
        historical_rows_reclassified=False,
    )
