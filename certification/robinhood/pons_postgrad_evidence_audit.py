"""Offline audit of retained Pons evidence for independent post-graduation research.

This command never opens sockets and never grants allocation authority. It answers a
narrow question: does the retained runs-355-368 fixture contain an unbiased
post-graduation universe with enough V4 observations to evaluate a new entry strategy
that does not depend on a pre-graduation Pons position?
"""
from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys

FIXTURE = Path("certification/evidence/robinhood-runs-355-368.json.gz")
EXPECTED_SHA256 = "1be70cb9f53bfc9bce039f6913813a6d2a0a21dde39b6b10bf95b9123f47597f"
OUTPUT = Path("pons-postgrad-offline-audit.json")


def _walk_keys(value, prefix=""):
    out = Counter()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out[path] += 1
            out.update(_walk_keys(child, path))
    elif isinstance(value, list):
        for child in value:
            out.update(_walk_keys(child, prefix + "[]"))
    return out


def run():
    attempts = []

    def guard(event, args):
        if event in ("socket.connect", "socket.getaddrinfo"):
            attempts.append(event)
            raise RuntimeError("postgrad_offline_audit_network_forbidden")

    sys.addaudithook(guard)
    raw = FIXTURE.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("retained_fixture_hash_changed")
    data = json.loads(gzip.decompress(raw))

    run_rows = []
    all_lifecycles = []
    top_level_pons_keys = Counter()
    retained_key_paths = Counter()

    for run in data.get("runs", []):
        number = int(run["run"])
        pons = run.get("pons") or {}
        top_level_pons_keys.update(pons.keys())
        retained_key_paths.update(_walk_keys(pons))
        lifecycles = list(pons.get("lifecycles") or [])
        all_lifecycles.extend((number, row) for row in lifecycles)

        v4_monitors = 0
        postgrad_vectors = 0
        graduation_carries = 0
        transitions = 0
        for life in lifecycles:
            monitor = list(life.get("monitor") or [])
            v4_monitors += sum(
                str(m.get("market", "")).lower() in ("v4", "uniswap_v4")
                for m in monitor if isinstance(m, dict)
            )
            postgrad_vectors += int(bool(life.get("post_graduation")))
            graduation_carries += int(bool(life.get("carried_through_graduation")))
            transitions += int(bool(life.get("transition") or life.get("graduation_transition")))

        run_rows.append(dict(
            run=number,
            retained_rows=len(pons.get("rows") or []),
            complete_vectors=len(pons.get("complete") or []),
            lifecycles=len(lifecycles),
            carried_through_graduation=graduation_carries,
            post_graduation_vectors=postgrad_vectors,
            explicit_transitions=transitions,
            v4_monitor_rows=v4_monitors,
            pons_top_level_keys=sorted(pons.keys()),
        ))

    independent_keys = [
        key for key in top_level_pons_keys
        if any(token in str(key).lower() for token in ("graduat", "postgrad", "v4", "pool"))
        and key not in ("lifecycles",)
    ]
    lifecycle_key_union = sorted({
        key for _, life in all_lifecycles for key in life.keys()
    })
    lifecycle_v4_rows = sum(
        str(m.get("market", "")).lower() in ("v4", "uniswap_v4")
        for _, life in all_lifecycles
        for m in (life.get("monitor") or [])
        if isinstance(m, dict)
    )
    lifecycle_postgrad = sum(bool(life.get("post_graduation")) for _, life in all_lifecycles)
    lifecycle_graduated = sum(bool(life.get("carried_through_graduation")) for _, life in all_lifecycles)

    # An independent entry study needs graduations discovered without conditioning on
    # pre-graduation qualification. Lifecycle-only post-grad rows are selection-biased.
    unbiased_universe_available = bool(independent_keys)
    forward_outcomes_available = any(
        any(
            token in str(key).lower()
            for token in ("forward", "return", "outcome", "mark")
        )
        for key in retained_key_paths
        if any(token in key.lower() for token in ("post", "v4", "graduat"))
    )

    report = dict(
        schema="pons-postgrad-offline-evidence-audit-v1",
        fixture_sha256=digest,
        provider_calls=0,
        network_attempts=len(attempts),
        runs=run_rows,
        totals=dict(
            lifecycles=len(all_lifecycles),
            carried_through_graduation=lifecycle_graduated,
            post_graduation_vectors=lifecycle_postgrad,
            v4_monitor_rows=lifecycle_v4_rows,
        ),
        pons_top_level_keys=dict(top_level_pons_keys),
        lifecycle_key_union=lifecycle_key_union,
        independent_postgrad_top_level_keys=sorted(independent_keys),
        unbiased_independent_graduation_universe_available=unbiased_universe_available,
        postgrad_forward_outcome_fields_detected=forward_outcomes_available,
        conclusion=(
            "retained_fixture_can_support_independent_postgrad_replay"
            if unbiased_universe_available and forward_outcomes_available
            else "retained_fixture_insufficient_for_unbiased_independent_postgrad_profitability"
        ),
        next_step=(
            "offline_replay"
            if unbiased_universe_available and forward_outcomes_available
            else "bounded_research_only_prospective_collection"
        ),
        production_strategy_changed=False,
        allocation_authority=False,
        paper_only=True,
        passed=(digest == EXPECTED_SHA256 and not attempts),
    )
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
