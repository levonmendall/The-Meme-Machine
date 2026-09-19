"""Bounded multi-source Robinhood observability proof.

This diagnostic compares independent chain views and samples the official sequencer
feed. It has no strategy, allocation, signing, submission or execution authority.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

from . import BoundaryError, CHAIN_ID
from .provider_topology import configured_rpc, public_diagnostic_rpc
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
    latest = rpc.call("eth_getBlockByNumber", ["latest", False], scope="observability")
    if not isinstance(latest, dict):
        raise BoundaryError("observability_head_shape")
    number = int(latest["number"], 16)
    timestamp = int(latest["timestamp"], 16)
    now = int(time.time())
    if timestamp > now + 5:
        raise BoundaryError("observability_future_head")
    return dict(
        provider=label,
        chain_id=chain,
        number=number,
        hash=latest["hash"],
        timestamp=timestamp,
        age_seconds=max(0, now - timestamp),
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


def run(primary_endpoint, *, feed_seconds=5.0):
    started = time.time()
    result = dict(
        kind="robinhood_multisource_observability_v1",
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

    topology = configured_rpc(
        primary_endpoint,
        limit=40,
        per_scope=20,
        retries=0,
    )
    primary = topology.primary
    secondary = topology.secondary
    public = public_diagnostic_rpc(limit=20, per_scope=20, retries=0)

    try:
        result["providers"]["primary"] = _head(primary, "authenticated_primary")
    except (BoundaryError, ValueError, KeyError, TypeError) as exc:
        result["limitations"].append("primary:" + str(exc))
        result["providers"]["primary"] = None

    if secondary is None:
        result["limitations"].append("quicknode_secondary_not_configured")
        result["providers"]["quicknode"] = None
    else:
        try:
            result["providers"]["quicknode"] = _head(
                secondary, "quicknode_secondary"
            )
        except (BoundaryError, ValueError, KeyError, TypeError) as exc:
            result["limitations"].append("quicknode:" + str(exc))
            result["providers"]["quicknode"] = None

    try:
        result["providers"]["robinhood_public"] = _head(
            public, "robinhood_public_diagnostic"
        )
    except (BoundaryError, ValueError, KeyError, TypeError) as exc:
        result["limitations"].append("public:" + str(exc))
        result["providers"]["robinhood_public"] = None

    p = result["providers"].get("primary")
    q = result["providers"].get("quicknode")
    u = result["providers"].get("robinhood_public")
    result["comparisons"] = dict(
        primary_vs_quicknode=_comparison(p, q),
        primary_vs_public=_comparison(p, u),
        quicknode_vs_public=_comparison(q, u),
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

    result["topology"] = topology.telemetry()
    result["public_provider"] = public.telemetry()
    result["ended_at"] = time.time()
    result["complete"] = bool(
        result["providers"].get("primary")
        and result["providers"].get("quicknode")
        and result.get("sequencer", {}).get("messages", 0) > 0
    )
    return result


if __name__ == "__main__":
    report = run(os.environ.get("MM_ROBINHOOD_READ_RPC_URL", ""))
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["providers"].get("primary") else 2)
