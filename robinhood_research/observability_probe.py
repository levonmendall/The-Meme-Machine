"""Bounded lane-level Robinhood observability proof.

Compares provider roles without granting cross-provider trade authority. It never logs
endpoint URLs or credentials.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

from . import BoundaryError, CHAIN_ID
from .provider_topology import (
    configured_discovery_rpc,
    configured_dlmm_rpc,
    configured_rpc,
    configured_shadow_rpc,
    public_diagnostic_rpc,
    topology_metadata,
)
from .sequencer_feed import SequencerFeedObserver


REPORT = Path(
    os.environ.get(
        "MM_ROBINHOOD_OBSERVABILITY_REPORT",
        "robinhood-observability-report.json",
    )
)


def _head(rpc, label):
    chain = rpc.verify_chain()
    if chain != CHAIN_ID:
        raise BoundaryError("wrong_chain")
    latest = rpc.call(
        "eth_getBlockByNumber", ["latest", False], scope="observability"
    )
    if not isinstance(latest, dict):
        raise BoundaryError("observability_head_shape")
    number = int(latest["number"], 16)
    timestamp = int(latest["timestamp"], 16)
    now = int(time.time())
    if timestamp > now + 5:
        raise BoundaryError("observability_future_head")
    telemetry = rpc.telemetry()
    return dict(
        provider=label,
        provider_kind=telemetry.get("provider_kind"),
        role=telemetry.get("role"),
        chain_id=chain,
        number=number,
        hash=latest["hash"],
        timestamp=timestamp,
        age_seconds=max(0, now - timestamp),
        pacing=telemetry.get("pacing"),
        automatic_failover=telemetry.get("automatic_failover"),
    )


def _comparison(a, b):
    if a is None or b is None:
        return None
    same_height = a["number"] == b["number"]
    return dict(
        height_delta=a["number"] - b["number"],
        same_height=same_height,
        same_hash=(a["hash"] == b["hash"] if same_height else None),
        timestamp_delta_seconds=a["timestamp"] - b["timestamp"],
    )


def _observe(result, key, rpc, label):
    if rpc is None:
        result["providers"][key] = None
        return None
    try:
        row = _head(rpc, label)
        result["providers"][key] = row
        return row
    except (BoundaryError, ValueError, KeyError, TypeError) as exc:
        result["limitations"].append(key + ":" + str(exc))
        result["providers"][key] = None
        return None


def run(primary_endpoint, *, feed_seconds=5.0):
    started = time.time()
    result = dict(
        kind="robinhood_lane_observability_v2",
        chain_id=CHAIN_ID,
        authority="observation_only",
        strategy_authority=False,
        allocation_authority=False,
        signing=False,
        submission=False,
        live_money=False,
        started_at=started,
        providers={},
        comparisons={},
        sequencer=None,
        limitations=[],
    )

    directional = configured_rpc(
        primary_endpoint,
        limit=40,
        per_scope=20,
        retries=0,
    )
    discovery = configured_discovery_rpc(
        primary_endpoint,
        limit=40,
        per_scope=20,
        retries=0,
    )
    dlmm = configured_dlmm_rpc(
        primary_endpoint,
        limit=40,
        per_scope=20,
        retries=0,
    )
    shadow = configured_shadow_rpc(
        limit=20,
        per_scope=20,
        retries=0,
    )
    public = public_diagnostic_rpc(limit=20, per_scope=20, retries=0)

    p = _observe(result, "directional_evidence", directional, "directional_evidence")
    d = _observe(result, "pons_discovery", discovery, "pons_discovery")
    l = _observe(result, "ramses_dlmm", dlmm, "ramses_dlmm")
    s = _observe(result, "shadow", shadow, "shadow_diagnostic")
    u = _observe(result, "robinhood_public", public, "robinhood_public_diagnostic")

    result["comparisons"] = dict(
        directional_vs_discovery=_comparison(p, d),
        directional_vs_dlmm=_comparison(p, l),
        directional_vs_shadow=_comparison(p, s),
        directional_vs_public=_comparison(p, u),
    )

    try:
        result["sequencer"] = SequencerFeedObserver().sample(
            seconds=feed_seconds,
            max_frames=200,
        )
    except (BoundaryError, OSError, ValueError) as exc:
        result["limitations"].append("sequencer:" + str(exc))
        result["sequencer"] = dict(
            authority="observation_only",
            available=False,
            error=str(exc),
        )

    result["topology"] = topology_metadata()
    result["primary_is_alchemy"] = (
        (p or {}).get("provider_kind") == "alchemy"
    )
    result["provider_telemetry"] = dict(
        directional=directional.telemetry(),
        discovery=discovery.telemetry(),
        dlmm=dlmm.telemetry(),
        shadow=(None if shadow is None else shadow.telemetry()),
        public=public.telemetry(),
    )
    result["ended_at"] = time.time()
    result["complete_core"] = bool(
        p and d and l and result.get("sequencer", {}).get("messages", 0) > 0
    )
    return result


if __name__ == "__main__":
    report = run(os.environ.get("MM_ROBINHOOD_READ_RPC_URL", ""))
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["providers"].get("directional_evidence") else 2)
