"""Research-only high-activity DLMM point-in-time replay.

Meteora's public Data API is used only to rank current SOL-paired pools before
observation. Every candidate must then pass PR #4's finalized on-chain snapshot
validation. A separate verified warmup interval is observed before the fixed
`sdk_bidask`/8-bin research variant can be selected. Only a later verified interval
is used for counterfactual outcome P&L. No Store or allocation authority is opened.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

from meme_machine import dlmm
from meme_machine.dlmm_paper import CAPITAL, ENTRY_COST, EXIT_COST
from meme_machine.postgrad import PoolScanRPC
from meme_machine.provider import Unavailable
from meme_machine.store import digest
from tests.dlmm_strategy_point_in_time import (
    STRATEGIES,
    WIDTHS,
    _advance,
    _summary,
    evaluate,
    regime_features,
)

DATA_API = "https://dlmm.datapi.meteora.ag/pools"
MAX_POOLS = 4
MAX_CYCLES = 2
MAX_WINDOW_SECONDS = 12
SELECTED_STRATEGY = "sdk_bidask"
SELECTED_WIDTH = 8
REPORT = Path(os.environ.get("MM_DLMM_STRATEGY_REPORT", "dlmm-strategy-report.json"))

# Bounded fallback captured from the public Meteora API on 2026-09-17 before this
# experiment. It is discovery-only; every address still requires current finalized
# on-chain validation. These were the highest-activity supported-looking SOL pairs
# on the first live API page at capture time.
FALLBACK_CANDIDATES = (
    dict(address="6oQ9wVex4mKZti2GsGCfD8FWTMMC9PLQkztRU5cd6MK8", name="SOL-HYPE",
         volume_30m=680805.8786698299, fees_30m=405.99596825355826),
    dict(address="8eybKAvjKJryVweQLg8SRgwUfdP7wHYJ5yyqgfE82DQA", name="ZEC-SOL",
         volume_30m=277126.28530870413, fees_30m=504.6647299680856),
    dict(address="zxTpi4BtaWX3mgdAPoezkMD1hxx8CdeCfrqXMWvSCLX", name="STONK-SOL",
         volume_30m=103247.0244935333, fees_30m=188.52584576715816),
    dict(address="Gc5hVCBydc6k3Z7oc2cQEW4GThFQi2Fqk5HfKABqa2q8", name="PAID-SOL",
         volume_30m=75146.6398141897, fees_30m=750.5057869628653),
)


def _sol_pair(row):
    try:
        x = row["token_x"]["address"]
        y = row["token_y"]["address"]
        cfg = row["pool_config"]
    except (KeyError, TypeError):
        return False
    return (
        (x == dlmm.WSOL) != (y == dlmm.WSOL)
        and not bool(row.get("is_blacklisted"))
        and not bool(row.get("has_farm"))
        and cfg.get("collect_fee_mode") == 0
    )


def _candidate(row, rank, source):
    volume = row.get("volume") or {}
    fees = row.get("fees") or {}
    return dict(
        rank=rank,
        source=source,
        address=row["address"],
        name=row.get("name"),
        token_x=(row.get("token_x") or {}).get("address"),
        token_y=(row.get("token_y") or {}).get("address"),
        volume_30m=float(volume.get("30m", row.get("volume_30m", 0)) or 0),
        volume_1h=float(volume.get("1h", 0) or 0),
        fees_30m=float(fees.get("30m", row.get("fees_30m", 0)) or 0),
        fee_tvl_30m=float((row.get("fee_tvl_ratio") or {}).get("30m", 0) or 0),
        tvl=float(row.get("tvl", 0) or 0),
        bin_step=(row.get("pool_config") or {}).get("bin_step"),
    )


def fetch_high_activity(limit=24):
    if not 4 <= limit <= 100:
        raise ValueError("dlmm_activity_discovery_bound")
    query = urllib.parse.urlencode(dict(
        page=1,
        page_size=limit,
        sort_by="volume_30m:desc",
    ))
    req = urllib.request.Request(
        DATA_API + "?" + query,
        headers={"User-Agent": "The-Meme-Machine-DLMM-research/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise Unavailable("dlmm_activity_api_response_bound")
    body = json.loads(raw)
    rows = body.get("data")
    if not isinstance(rows, list):
        raise Unavailable("dlmm_activity_api_shape")
    selected = []
    for row in rows:
        if not _sol_pair(row):
            continue
        selected.append(_candidate(row, len(selected) + 1, "meteora_data_api_volume_30m"))
        if len(selected) >= MAX_POOLS * 3:
            break
    if not selected:
        raise Unavailable("dlmm_activity_api_no_sol_pairs")
    return selected


def discovery_candidates():
    try:
        rows = fetch_high_activity()
        return rows, None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError,
            Unavailable, ValueError, KeyError, TypeError) as exc:
        fallback = [dict(item, rank=i + 1, source="stamped_2026_09_17_api_fallback")
                    for i, item in enumerate(FALLBACK_CANDIDATES)]
        return fallback, type(exc).__name__


def discover_and_revalidate(adapter, now):
    candidates, api_error = discovery_candidates()
    states = {}
    accepted = []
    rejections = []
    for candidate in candidates:
        address = candidate["address"]
        try:
            snap = adapter.snapshot(address, int(time.time()), True)
            state = dlmm.validate(snap, snap["available_time"], "real")
            if candidate.get("token_x") and candidate.get("token_y"):
                dlmm.scout(snap, snap["available_time"], dict(
                    pool=address, x=candidate["token_x"], y=candidate["token_y"]))
            states[address] = state
            accepted.append(dict(
                **candidate,
                finalized_slot=state["slot"],
                active_bin=state["active"],
                onchain_bin_step=state["step"],
                evidence_hash=digest(snap),
            ))
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            rejections.append(dict(pool=address, name=candidate.get("name"), reason=str(exc)[:140]))
        if len(states) >= MAX_POOLS:
            break
    return states, accepted, rejections, api_error


def select_variant(features):
    """Fixed ex-ante activity gate; no outcome input and no optimized threshold."""
    if features["warmup_swaps"] <= 0 or features["warmup_volume_sol_lamports"] <= 0:
        return None
    return dict(
        strategy=SELECTED_STRATEGY,
        width=SELECTED_WIDTH,
        rule="verified_nonzero_warmup_activity_then_fixed_sdk_bidask_8",
    )


def run_live(cycles=MAX_CYCLES, window_seconds=6):
    if not 1 <= cycles <= MAX_CYCLES or not 5 <= window_seconds <= MAX_WINDOW_SECONDS:
        raise ValueError("dlmm_high_activity_live_bounds")
    rpc_url = os.environ.get("MM_SOLANA_READ_RPC_URL") or "https://api.mainnet.solana.com"
    rpc = PoolScanRPC(rpc_url, limit=240)
    adapter = dlmm.Adapter(rpc)
    states, candidates, rejections, api_error = discover_and_revalidate(adapter, int(time.time()))
    report = dict(
        kind="dlmm_high_activity_point_in_time_replay_v2",
        base="pr4_verified_simulator",
        allocation_authority=False,
        prospective_allocation_enabled=False,
        discovery_source="meteora_data_api_current_volume_30m_then_finalized_onchain",
        discovery_api_error=api_error,
        discovery_candidates=candidates,
        discovery_rejections=rejections,
        capital_lamports=CAPITAL,
        fixed_cost_lamports=ENTRY_COST + EXIT_COST,
        shadow_strategies=list(STRATEGIES),
        shadow_widths=list(WIDTHS),
        selected_strategy=SELECTED_STRATEGY,
        selected_width=SELECTED_WIDTH,
        selector_uses_outcome_data=False,
        selector_rule="nonzero_verified_warmup_activity_only",
        cycles=cycles,
        window_seconds=window_seconds,
        point_in_time=True,
        started=int(time.time()),
        initial_pools=sorted(states),
        opportunities=[],
        results=[],
        selected_results=[],
        interval_errors=[],
    )
    for cycle in range(cycles):
        mid_states, warmups, warm_errors = _advance(adapter, states, window_seconds)
        report["interval_errors"].extend(dict(cycle=cycle, phase="warmup", **e) for e in warm_errors)
        end_states, outcomes, out_errors = _advance(adapter, mid_states, window_seconds)
        report["interval_errors"].extend(dict(cycle=cycle, phase="outcome", **e) for e in out_errors)
        for address in sorted(set(warmups) & set(outcomes)):
            warm = warmups[address]
            outcome = outcomes[address]
            entry = mid_states[address]
            features = regime_features(states[address], warm)
            choice = select_variant(features)
            opportunity = dict(
                cycle=cycle,
                pool=address,
                warmup_start_slot=states[address]["slot"],
                entry_slot=entry["slot"],
                end_slot=end_states[address]["slot"],
                warmup_lineage=warm.lineage,
                outcome_lineage=outcome.lineage,
                outcome_swaps=len(outcome.events),
                warmup_host_fee_swaps=sum(
                    int((event.get("observed") or {}).get("host_fee", 0) > 0)
                    for event in warm.events),
                outcome_host_fee_swaps=sum(
                    int((event.get("observed") or {}).get("host_fee", 0) > 0)
                    for event in outcome.events),
                features=features,
                selected=choice,
            )
            report["opportunities"].append(opportunity)
            for strategy in STRATEGIES:
                for width in WIDTHS:
                    try:
                        result = evaluate(entry, outcome, strategy, width)
                    except (Unavailable, ValueError, KeyError, TypeError, OverflowError) as exc:
                        result = dict(strategy=strategy, width=width, resolved=False, reason=str(exc))
                    result.update(
                        cycle=cycle,
                        pool=address,
                        entry_slot=entry["slot"],
                        end_slot=end_states[address]["slot"],
                        warmup_swaps=features["warmup_swaps"],
                        outcome_swaps=len(outcome.events),
                        turnover_bps=features["turnover_bps"],
                        fee_density_bps=features["fee_density_bps"],
                        direction_balance=features["direction_balance"],
                        drift_ratio=features["drift_ratio"],
                        selected=bool(choice and strategy == choice["strategy"] and width == choice["width"]),
                    )
                    report["results"].append(result)
                    if result["selected"]:
                        report["selected_results"].append(result)
        states = end_states
        if not states:
            break
    stats, best = _summary(report["results"])
    pools = {o["pool"] for o in report["opportunities"]}
    warm_nonempty = sum(o["features"]["warmup_swaps"] > 0 for o in report["opportunities"])
    outcome_nonempty = sum(o["outcome_swaps"] > 0 for o in report["opportunities"])
    selected_resolved = [r for r in report["selected_results"] if r.get("resolved")]
    selected_pnl = [r["pnl_bps"] for r in selected_resolved]
    host_fee_swaps = sum(
        o.get("warmup_host_fee_swaps", 0) + o.get("outcome_host_fee_swaps", 0)
        for o in report["opportunities"])
    pilot_adequate = len(report["opportunities"]) >= 6 and len(pools) >= 3 and outcome_nonempty >= 3
    report.update(
        ended=int(time.time()),
        strategy_stats=stats,
        best_observed_variant=best,
        distinct_pools=len(pools),
        opportunity_count=len(report["opportunities"]),
        nonempty_warmup_count=warm_nonempty,
        nonempty_outcome_count=outcome_nonempty,
        selected_trade_count=len(report["selected_results"]),
        selected_resolved_count=len(selected_resolved),
        host_fee_swap_count=host_fee_swaps,
        selected_mean_pnl_bps=None if not selected_pnl else statistics.fmean(selected_pnl),
        selected_median_pnl_bps=None if not selected_pnl else statistics.median(selected_pnl),
        selected_profitable_rate=None if not selected_pnl else sum(x > 0 for x in selected_pnl) / len(selected_pnl),
        pilot_sample_adequate=pilot_adequate,
        repeatability_sample_adequate=False,
        conclusion=("active_pool_pilot_complete_repeatability_not_established"
                    if pilot_adequate else "insufficient_active_point_in_time_sample"),
        rpc_calls=rpc.calls,
        rpc_http_requests=rpc.http_requests,
        rpc_failures=rpc.failures,
        rpc_retries=rpc.retries,
        provider_failure_kinds=rpc.failure_kinds,
        provider_failure_methods=rpc.failure_methods,
        rpc_batch_fallbacks=rpc.batch_fallbacks,
        rpc_batch_fallback_items=rpc.batch_fallback_items,
        rpc_null_retries=rpc.null_retries,
    )
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(
        conclusion=report["conclusion"],
        pools=report["distinct_pools"],
        opportunities=report["opportunity_count"],
        nonempty_warmups=warm_nonempty,
        nonempty_outcomes=outcome_nonempty,
        selected_trades=report["selected_trade_count"],
        selected_median_pnl_bps=report["selected_median_pnl_bps"],
        best=best,
        rpc_failures=rpc.failures,
    ), sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=MAX_CYCLES)
    parser.add_argument("--window-seconds", type=int, default=6)
    args = parser.parse_args()
    try:
        run_live(args.cycles, args.window_seconds)
    except Exception as exc:
        failure = dict(
            kind="dlmm_high_activity_point_in_time_replay_v2",
            allocation_authority=False,
            prospective_allocation_enabled=False,
            conclusion="experiment_failed_before_valid_sample",
            error=str(exc)[:160],
            ended=int(time.time()),
        )
        REPORT.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n")
        print(json.dumps(failure, sort_keys=True))
        raise


if __name__ == "__main__":
    main()
