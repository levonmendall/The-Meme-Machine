"""Density-screened sequential DLMM profitability research.

This runner is research-only. It preserves the certified DLMM simulator, fixed costs,
the fixed ex-ante sdk_bidask width-8 selector, point-in-time separation, the unchanged
MAX_TRANSACTIONS verifier bound, and disabled allocation authority.

Candidate pools are observed one at a time. Before either a warmup or outcome window
can spend getTransaction/reconstruction work, one cheap finalized signature census
checks whether transaction density has already made that window uncertifiable under
the existing verifier capacity. Over-capacity and provider failures remain explicit
censoring outcomes; neither is converted into "no opportunity".

The batch stops when it has a target number of fully verified warmup+outcome windows,
subject to bounded candidate and provider budgets.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

from meme_machine import dlmm, pump
from meme_machine.dlmm_paper import CAPITAL, ENTRY_COST, EXIT_COST
from meme_machine.dlmm_tape import MAX_TRANSACTIONS
from meme_machine.postgrad import PoolScanRPC
from meme_machine.provider import Unavailable
from tests import dlmm_boundary_acquisition as boundary
from tests import dlmm_dense_acquisition as dense
from tests import dlmm_strategy_high_activity as research
from tests import dlmm_strategy_high_activity_batched as run


TARGET_COMPLETED_WINDOWS = 6
MAX_ATTEMPTED_POOLS = 12
PREFLIGHT_SECONDS = 0.5
MAX_ACTIVITY_PAGES = 4
ACTIVITY_PAGE_SIZE = 80
MAX_CANDIDATE_SCAN_MULTIPLIER = 4

run.CHUNK_SECONDS = 2
run._capture_chunk = boundary.capture_chunk
run.ENDPOINT_DIAGNOSTICS = boundary.ENDPOINT_DIAGNOSTICS

_OVER_CAPACITY_REASONS = {
    "dlmm_transaction_bound",
    "dlmm_transaction_pressure_overflow",
}
_PROVIDER_FAILURE_REASONS = {
    "provider_request_failed",
    "provider_error",
}
_PROVIDER_BUDGET_REASONS = {
    "provider_budget_exhausted",
}


def _rpc_metrics(rpc):
    return dict(
        calls=int(getattr(rpc, "calls", 0)),
        http_requests=int(getattr(rpc, "http_requests", 0)),
        failures=int(getattr(rpc, "failures", 0)),
        retries=int(getattr(rpc, "retries", 0)),
    )


def _metric_delta(before, after):
    return {key: int(after.get(key, 0)) - int(before.get(key, 0))
            for key in ("calls", "http_requests", "failures", "retries")}


def _classify_reason(reason):
    reason = str(reason or "")
    if reason in _OVER_CAPACITY_REASONS or "transaction_pressure_overflow" in reason:
        return "over_verification_capacity"
    if reason in _PROVIDER_BUDGET_REASONS:
        return "provider_budget_exhausted"
    if reason in _PROVIDER_FAILURE_REASONS or "provider_request_failed" in reason:
        return "provider_failure"
    return "verification_failure"


def _classify_errors(errors):
    if not errors:
        return "verification_failure"
    classes = [_classify_reason(item.get("reason")) for item in errors]
    for preferred in (
        "over_verification_capacity",
        "provider_budget_exhausted",
        "provider_failure",
        "verification_failure",
    ):
        if preferred in classes:
            return preferred
    return "verification_failure"


def _density_preflight(adapter, start, wait_seconds=PREFLIGHT_SECONDS):
    """Cheap scheduling-only census before any transaction-body reconstruction.

    The census is deliberately not evidence for a verified tape. A passing census only
    means the current half-second boundary has not already exceeded the unchanged
    MAX_TRANSACTIONS capacity. The normal complete signature census and terminal
    reconstruction must still succeed before the phase is treated as verified.
    """
    if wait_seconds < 0:
        raise ValueError("dlmm_profitability_preflight_wait")
    rpc = adapter.rpc
    before = _rpc_metrics(rpc)
    if wait_seconds:
        sleeper = getattr(rpc, "sleep", None)
        if callable(sleeper):
            sleeper(wait_seconds)
        else:
            time.sleep(wait_seconds)
    try:
        rows = rpc.call(
            "getSignaturesForAddress",
            [start["pool"], dict(
                limit=MAX_TRANSACTIONS + 1,
                commitment="finalized",
            )],
            True,
            fresh=True,
        )
        if not isinstance(rows, list) or len(rows) > MAX_TRANSACTIONS + 1:
            raise Unavailable("dlmm_density_preflight_shape")
        successful_post_start = 0
        observed_post_start = 0
        for row in rows:
            if not isinstance(row, dict) or type(row.get("slot")) is not int:
                raise Unavailable("dlmm_density_preflight_shape")
            if row["slot"] <= start["slot"]:
                continue
            observed_post_start += 1
            if not row.get("err"):
                successful_post_start += 1
        classification = (
            "over_verification_capacity"
            if successful_post_start > MAX_TRANSACTIONS
            else "certifiable"
        )
        result = dict(
            classification=classification,
            wait_seconds=float(wait_seconds),
            verification_capacity=MAX_TRANSACTIONS,
            successful_post_start=successful_post_start,
            observed_post_start=observed_post_start,
            start_slot=start["slot"],
        )
    except (Unavailable, ValueError, KeyError, TypeError) as exc:
        reason = str(exc)
        result = dict(
            classification=_classify_reason(reason),
            wait_seconds=float(wait_seconds),
            verification_capacity=MAX_TRANSACTIONS,
            successful_post_start=None,
            observed_post_start=None,
            start_slot=start.get("slot"),
            reason=reason,
        )
    result["rpc"] = _metric_delta(before, _rpc_metrics(rpc))
    return result


def _observe_phase(adapter, address, start, window_seconds, allow_snapshot_reset):
    """Observe one warmup/outcome phase after a density census.

    The preflight wait is part of the requested observation window. The verified
    acquisition therefore receives only the remaining duration. Any transaction that
    arrived during preflight is still inside the verified interval because the
    authenticated starting snapshot is unchanged.
    """
    if window_seconds <= PREFLIGHT_SECONDS:
        raise ValueError("dlmm_profitability_window_too_short")
    phase = dict(
        pool=address,
        requested_window_seconds=float(window_seconds),
        snapshot_reset_allowed=bool(allow_snapshot_reset),
    )
    preflight = _density_preflight(adapter, start)
    phase["preflight"] = preflight
    if preflight["classification"] != "certifiable":
        phase.update(
            verified=False,
            terminal_classification=preflight["classification"],
            errors=[] if "reason" not in preflight else [
                dict(pool=address, stage="density_preflight", reason=preflight["reason"])
            ],
        )
        return phase, None, None, start

    local_states = {address: start}
    before = _rpc_metrics(adapter.rpc)
    advanced, tapes, errors = dense.pressure_advance(
        adapter,
        local_states,
        float(window_seconds) - float(PREFLIGHT_SECONDS),
        allow_snapshot_reset=allow_snapshot_reset,
    )
    phase["acquisition_rpc"] = _metric_delta(before, _rpc_metrics(adapter.rpc))
    phase["errors"] = list(errors)
    if errors or address not in tapes or address not in advanced:
        phase.update(
            verified=False,
            terminal_classification=_classify_errors(errors),
        )
        return phase, None, None, local_states.get(address, start)

    tape = tapes[address]
    terminal = advanced[address]
    effective_start = local_states.get(address, start)
    phase.update(
        verified=True,
        terminal_classification=(
            "verified_zero_swap" if len(tape.events) == 0 else "certifiable"
        ),
        swap_count=len(tape.events),
        effective_start_slot=effective_start["slot"],
        end_slot=terminal["slot"],
        lineage=tape.lineage,
    )
    return phase, tape, terminal, effective_start


def _fetch_activity_page(page):
    """Fetch one bounded current Meteora activity page without on-chain authority."""
    if not 1 <= page <= MAX_ACTIVITY_PAGES:
        raise ValueError("dlmm_profitability_activity_page")
    query = urllib.parse.urlencode(dict(
        page=page,
        page_size=ACTIVITY_PAGE_SIZE,
        sort_by="volume_30m:desc",
    ))
    req = urllib.request.Request(
        research.DATA_API + "?" + query,
        headers={
            "User-Agent": "The-Meme-Machine-DLMM-profitability/1.0",
            "Accept": "application/json",
        },
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
    for raw_index, row in enumerate(rows):
        if not research._sol_pair(row):
            continue
        candidate = research._candidate(
            row,
            (page - 1) * ACTIVITY_PAGE_SIZE + raw_index + 1,
            "meteora_data_api_volume_30m",
        )
        candidate["activity_page"] = page
        selected.append(candidate)
    return selected


def _discover_for_scan(adapter, max_attempted_pools):
    """Page activity candidates and apply the existing classic-SPL mint prefilter.

    Full pool/bin validation is deliberately deferred until immediately before each
    attempted observation. This prevents later sequential candidates from starting
    from snapshots that have aged past the verifier's unchanged 60-second interval
    identity/age bound.
    """
    candidate_cap = max_attempted_pools * MAX_CANDIDATE_SCAN_MULTIPLIER
    candidates = []
    seen_addresses = set()
    api_errors = []
    for page in range(1, MAX_ACTIVITY_PAGES + 1):
        try:
            rows = _fetch_activity_page(page)
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
            Unavailable,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            api_errors.append(dict(page=page, reason=type(exc).__name__))
            if page == 1:
                fallback, fallback_error = research.discovery_candidates()
                if fallback_error:
                    api_errors.append(dict(page=1, fallback_error=fallback_error))
                rows = fallback
            else:
                break
        if not rows:
            break
        for candidate in rows:
            address = candidate.get("address")
            if not address or address in seen_addresses:
                continue
            seen_addresses.add(address)
            candidates.append(candidate)
            if len(candidates) >= candidate_cap:
                break
        if len(candidates) >= candidate_cap:
            break

    mint_by_candidate = []
    unique_mints = []
    for candidate in candidates:
        x, y = candidate.get("token_x"), candidate.get("token_y")
        token = y if x == dlmm.WSOL else x if y == dlmm.WSOL else None
        mint_by_candidate.append(token)
        if token and token not in unique_mints:
            unique_mints.append(token)

    valid_mints = set()
    rejections = []
    for offset in range(0, len(unique_mints), ACTIVITY_PAGE_SIZE):
        chunk = unique_mints[offset:offset + ACTIVITY_PAGE_SIZE]
        response = adapter.rpc.call(
            "getMultipleAccounts",
            [chunk, dict(encoding="base64", commitment="finalized")],
            True,
            fresh=True,
        )
        values = response.get("value") if isinstance(response, dict) else None
        if not isinstance(values, list) or len(values) != len(chunk):
            raise Unavailable("dlmm_research_mint_prefilter_shape")
        for mint, account in zip(chunk, values):
            try:
                if not account or account.get("owner") != pump.TOKEN_PROGRAM:
                    raise ValueError("dlmm_unsupported_token_program_or_version")
                pump.mint_info(account)
                valid_mints.add(mint)
            except (ValueError, KeyError, TypeError) as exc:
                rejections.append(dict(
                    pool=None,
                    mint=mint,
                    reason=str(exc)[:140],
                    stage="mint_prefilter",
                ))

    filtered = []
    for candidate, token in zip(candidates, mint_by_candidate):
        if token and token in valid_mints:
            filtered.append(candidate)
        else:
            rejections.append(dict(
                pool=candidate.get("address"),
                name=candidate.get("name"),
                reason="mint_prefilter_rejected",
                stage="mint_prefilter",
            ))
    return filtered, rejections, api_errors


def _fresh_supported_start(adapter, candidate):
    """Authenticate a current pool snapshot immediately before observation."""
    address = candidate["address"]
    snap = adapter.snapshot(address, int(time.time()), True, fresh=True)
    state = dlmm.validate(snap, snap["available_time"], "real")
    if candidate.get("token_x") and candidate.get("token_y"):
        dlmm.scout(
            snap,
            snap["available_time"],
            dict(
                pool=address,
                x=candidate["token_x"],
                y=candidate["token_y"],
            ),
        )
    return state


def _evaluate_completed_window(cycle, address, warm_start, warm, entry, outcome, end_state):
    features = research.regime_features(warm_start, warm)
    choice = research.select_variant(features)
    opportunity = dict(
        cycle=cycle,
        pool=address,
        warmup_start_slot=warm_start["slot"],
        entry_slot=entry["slot"],
        end_slot=end_state["slot"],
        warmup_lineage=warm.lineage,
        outcome_lineage=outcome.lineage,
        outcome_swaps=len(outcome.events),
        warmup_host_fee_swaps=sum(
            int((event.get("observed") or {}).get("host_fee", 0) > 0)
            for event in warm.events
        ),
        outcome_host_fee_swaps=sum(
            int((event.get("observed") or {}).get("host_fee", 0) > 0)
            for event in outcome.events
        ),
        features=features,
        selected=choice,
    )
    results = []
    selected_results = []
    for strategy in research.STRATEGIES:
        for width in research.WIDTHS:
            try:
                result = research.evaluate(entry, outcome, strategy, width)
            except (Unavailable, ValueError, KeyError, TypeError, OverflowError) as exc:
                result = dict(
                    strategy=strategy,
                    width=width,
                    resolved=False,
                    reason=str(exc),
                )
            result.update(
                cycle=cycle,
                pool=address,
                entry_slot=entry["slot"],
                end_slot=end_state["slot"],
                warmup_swaps=features["warmup_swaps"],
                outcome_swaps=len(outcome.events),
                turnover_bps=features["turnover_bps"],
                fee_density_bps=features["fee_density_bps"],
                direction_balance=features["direction_balance"],
                drift_ratio=features["drift_ratio"],
                selected=bool(
                    choice
                    and strategy == choice["strategy"]
                    and width == choice["width"]
                ),
            )
            results.append(result)
            if result["selected"]:
                selected_results.append(result)
    return opportunity, results, selected_results


def _attempt_candidate(
    adapter,
    candidate,
    start,
    window_seconds,
    attempt_index,
    rpc_before=None,
    fresh_start_rpc=None,
):
    before = rpc_before or _rpc_metrics(adapter.rpc)
    address = candidate["address"]
    attempt = dict(
        attempt=attempt_index,
        pool=address,
        name=candidate.get("name"),
        discovery_rank=candidate.get("rank"),
        discovery_source=candidate.get("source"),
        candidate_start_slot=start["slot"],
        verification_capacity=MAX_TRANSACTIONS,
        fresh_start_rpc=dict(fresh_start_rpc or {}),
    )

    warm_phase, warm, entry, warm_start = _observe_phase(
        adapter, address, start, window_seconds, allow_snapshot_reset=True
    )
    attempt["warmup"] = warm_phase
    if not warm_phase["verified"]:
        attempt.update(
            completed_window=False,
            terminal_classification=warm_phase["terminal_classification"],
            rpc=_metric_delta(before, _rpc_metrics(adapter.rpc)),
        )
        return attempt, None, [], []

    if len(warm.events) == 0:
        attempt.update(
            completed_window=False,
            terminal_classification="verified_zero_swap",
            warmup_swaps=0,
            outcome_skipped="fixed_selector_requires_nonzero_verified_warmup_activity",
            strategy_selected=False,
            rpc=_metric_delta(before, _rpc_metrics(adapter.rpc)),
        )
        return attempt, None, [], []

    outcome_phase, outcome, end_state, _ = _observe_phase(
        adapter, address, entry, window_seconds, allow_snapshot_reset=False
    )
    attempt["outcome"] = outcome_phase
    if not outcome_phase["verified"]:
        attempt.update(
            completed_window=False,
            terminal_classification=outcome_phase["terminal_classification"],
            rpc=_metric_delta(before, _rpc_metrics(adapter.rpc)),
        )
        return attempt, None, [], []

    overall = (
        "verified_zero_swap"
        if len(warm.events) == 0 and len(outcome.events) == 0
        else "certifiable"
    )
    attempt.update(
        completed_window=True,
        terminal_classification=overall,
        warmup_swaps=len(warm.events),
        outcome_swaps=len(outcome.events),
        rpc=_metric_delta(before, _rpc_metrics(adapter.rpc)),
    )
    opportunity, results, selected = _evaluate_completed_window(
        attempt_index - 1, address, warm_start, warm, entry, outcome, end_state
    )
    attempt["strategy_selected"] = opportunity["selected"] is not None
    return attempt, opportunity, results, selected


def run_live(
    target_completed=TARGET_COMPLETED_WINDOWS,
    max_attempted_pools=MAX_ATTEMPTED_POOLS,
    window_seconds=12,
):
    if not 1 <= target_completed <= TARGET_COMPLETED_WINDOWS:
        raise ValueError("dlmm_profitability_target_bound")
    if not target_completed <= max_attempted_pools <= MAX_ATTEMPTED_POOLS:
        raise ValueError("dlmm_profitability_attempt_bound")
    if not 5 <= window_seconds <= research.MAX_WINDOW_SECONDS:
        raise ValueError("dlmm_profitability_window_bound")

    run.ADVANCE_DIAGNOSTICS.clear()
    boundary.ENDPOINT_DIAGNOSTICS.clear()
    dense.ENDPOINT_CAPTURE_HIGH_WATER.clear()

    rpc_url = os.environ.get("MM_SOLANA_READ_RPC_URL") or "https://api.mainnet.solana.com"
    rpc = PoolScanRPC(rpc_url, limit=240)
    adapter = dlmm.Adapter(rpc)

    discovery_start = _rpc_metrics(rpc)
    candidates, rejections, api_errors = _discover_for_scan(
        adapter, max_attempted_pools
    )
    discovery_rpc = _metric_delta(discovery_start, _rpc_metrics(rpc))
    observation_start_calls = rpc.calls

    report = dict(
        kind="dlmm_profitability_density_screened_point_in_time_v3",
        base="pr4_verified_simulator",
        allocation_authority=False,
        prospective_allocation_enabled=False,
        capital_lamports=CAPITAL,
        fixed_cost_lamports=ENTRY_COST + EXIT_COST,
        shadow_strategies=list(research.STRATEGIES),
        shadow_widths=list(research.WIDTHS),
        selected_strategy=research.SELECTED_STRATEGY,
        selected_width=research.SELECTED_WIDTH,
        selector_uses_outcome_data=False,
        selector_rule="nonzero_verified_warmup_activity_only",
        point_in_time=True,
        verification_capacity=MAX_TRANSACTIONS,
        density_preflight_seconds=PREFLIGHT_SECONDS,
        density_preflight_signature_limit=MAX_TRANSACTIONS + 1,
        target_completed_windows=target_completed,
        max_attempted_pools=max_attempted_pools,
        window_seconds=window_seconds,
        candidate_scanning_policy="activity_ranked_candidates_until_completed_window_target_or_safety_bound",
        discovery_source="meteora_data_api_current_volume_30m_then_finalized_onchain",
        discovery_api_errors=api_errors,
        discovery_candidates=candidates,
        discovery_rejections=rejections,
        candidate_revalidation_rejections=[],
        discovered_supported_pools=[],
        discovery_rpc=discovery_rpc,
        activity_pages_scanned=sorted({
            int(item.get("activity_page", 1)) for item in candidates
        }),
        candidate_scan_cap=max_attempted_pools * MAX_CANDIDATE_SCAN_MULTIPLIER,
        started=int(time.time()),
        attempts=[],
        density_exclusions=[],
        opportunities=[],
        results=[],
        selected_results=[],
        interval_errors=[],
        profitability_conclusion="not_established",
        density_generalization_warning=(
            "High-density pools excluded by the unchanged 16-transaction verifier "
            "capacity are explicit censored observations. Profitability measured on "
            "the remaining certifiable subset must not be generalized to all DLMM pools."
        ),
    )

    completed = 0
    attempted = 0
    candidate_scanned = 0
    supported_pools = []
    for candidate in candidates:
        if completed >= target_completed or attempted >= max_attempted_pools:
            break
        candidate_scanned += 1
        address = candidate["address"]
        fresh_before = _rpc_metrics(rpc)
        try:
            start = _fresh_supported_start(adapter, candidate)
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            reason = str(exc)
            rejection = dict(
                candidate_scan=candidate_scanned,
                pool=address,
                name=candidate.get("name"),
                discovery_rank=candidate.get("rank"),
                reason=reason,
                terminal_classification=_classify_reason(reason),
                rpc=_metric_delta(fresh_before, _rpc_metrics(rpc)),
            )
            report["candidate_revalidation_rejections"].append(rejection)
            if rejection["terminal_classification"] == "provider_budget_exhausted":
                break
            continue

        attempted += 1
        supported_pools.append(address)
        fresh_rpc = _metric_delta(fresh_before, _rpc_metrics(rpc))
        attempt, opportunity, results, selected = _attempt_candidate(
            adapter,
            candidate,
            start,
            window_seconds,
            attempted,
            rpc_before=fresh_before,
            fresh_start_rpc=fresh_rpc,
        )
        report["attempts"].append(attempt)
        if attempt["terminal_classification"] == "over_verification_capacity":
            exclusion = dict(
                attempt=attempted,
                pool=address,
                name=candidate.get("name"),
                discovery_rank=candidate.get("rank"),
                terminal_classification="over_verification_capacity",
            )
            if attempt.get("warmup"):
                exclusion["warmup_preflight"] = attempt["warmup"].get("preflight")
                exclusion["warmup_terminal"] = attempt["warmup"].get(
                    "terminal_classification"
                )
            if attempt.get("outcome"):
                exclusion["outcome_preflight"] = attempt["outcome"].get("preflight")
                exclusion["outcome_terminal"] = attempt["outcome"].get(
                    "terminal_classification"
                )
            report["density_exclusions"].append(exclusion)
        for phase_name in ("warmup", "outcome"):
            phase = attempt.get(phase_name)
            if phase and phase.get("errors"):
                report["interval_errors"].extend(
                    dict(
                        attempt=attempted,
                        phase=phase_name,
                        terminal_classification=phase["terminal_classification"],
                        **error,
                    )
                    for error in phase["errors"]
                )
        if not attempt["completed_window"]:
            if attempt["terminal_classification"] == "provider_budget_exhausted":
                break
            continue
        completed += 1
        report["opportunities"].append(opportunity)
        report["results"].extend(results)
        report["selected_results"].extend(selected)

    stats, best = research._summary(report["results"])
    pools = {item["pool"] for item in report["opportunities"]}
    warm_nonempty = sum(
        item["features"]["warmup_swaps"] > 0 for item in report["opportunities"]
    )
    outcome_nonempty = sum(
        item["outcome_swaps"] > 0 for item in report["opportunities"]
    )
    selected_resolved = [
        item for item in report["selected_results"] if item.get("resolved")
    ]
    selected_pnl = [item["pnl_bps"] for item in selected_resolved]
    host_fee_swaps = sum(
        item.get("warmup_host_fee_swaps", 0)
        + item.get("outcome_host_fee_swaps", 0)
        for item in report["opportunities"]
    )
    observation_rpc_calls = rpc.calls - observation_start_calls
    terminal_counts = Counter(
        item["terminal_classification"] for item in report["attempts"]
    )
    phase_counts = Counter(
        phase["terminal_classification"]
        for item in report["attempts"]
        for phase_name in ("warmup", "outcome")
        for phase in [item.get(phase_name)]
        if phase
    )
    sample_complete = completed >= target_completed

    report.update(
        ended=int(time.time()),
        candidate_scanned_count=candidate_scanned,
        attempted_pool_count=attempted,
        discovered_supported_pools=sorted(supported_pools),
        zero_activity_warmup_count=sum(
            item["terminal_classification"] == "verified_zero_swap"
            for item in report["attempts"]
        ),
        completed_window_count=completed,
        completed_window_target_met=sample_complete,
        terminal_classification_counts=dict(sorted(terminal_counts.items())),
        phase_terminal_classification_counts=dict(sorted(phase_counts.items())),
        density_exclusion_count=len(report["density_exclusions"]),
        density_exclusion_rate=(
            None if not attempted else len(report["density_exclusions"]) / attempted
        ),
        strategy_stats=stats,
        best_observed_variant=best,
        distinct_pools=len(pools),
        opportunity_count=len(report["opportunities"]),
        nonempty_warmup_count=warm_nonempty,
        nonempty_outcome_count=outcome_nonempty,
        selected_trade_count=len(report["selected_results"]),
        selected_resolved_count=len(selected_resolved),
        host_fee_swap_count=host_fee_swaps,
        selected_mean_pnl_bps=(
            None if not selected_pnl else statistics.fmean(selected_pnl)
        ),
        selected_median_pnl_bps=(
            None if not selected_pnl else statistics.median(selected_pnl)
        ),
        selected_profitable_rate=(
            None
            if not selected_pnl
            else sum(value > 0 for value in selected_pnl) / len(selected_pnl)
        ),
        completed_window_sample_adequate=sample_complete,
        repeatability_sample_adequate=False,
        conclusion=(
            "completed_window_pilot_acquired_repeatability_not_established"
            if sample_complete
            else "insufficient_completed_window_sample"
        ),
        rpc_calls=rpc.calls,
        rpc_http_requests=rpc.http_requests,
        rpc_failures=rpc.failures,
        rpc_retries=rpc.retries,
        provider_failure_kinds=rpc.failure_kinds,
        provider_failure_methods=rpc.failure_methods,
        rpc_batch_fallbacks=rpc.batch_fallbacks,
        rpc_batch_fallback_items=rpc.batch_fallback_items,
        rpc_null_retries=rpc.null_retries,
        observation_rpc_calls=observation_rpc_calls,
        rpc_calls_per_attempted_pool=(
            None if not attempted else observation_rpc_calls / attempted
        ),
        rpc_calls_per_completed_observation=(
            None if not completed else observation_rpc_calls / completed
        ),
        total_rpc_calls_per_completed_observation=(
            None if not completed else rpc.calls / completed
        ),
        transaction_retrieval="census_gated_serialized_dense_getTransaction",
        candidate_prefilter="single_finalized_getMultipleAccounts_classic_spl_mints",
        activity_rank_rows_examined_max=ACTIVITY_PAGE_SIZE * MAX_ACTIVITY_PAGES,
        evidence_extension_diagnostics=run.ADVANCE_DIAGNOSTICS,
        endpoint_snapshot_diagnostics=boundary.ENDPOINT_DIAGNOSTICS,
        historical_last_update_reference=run.historical_last_update_reference(),
    )
    research.REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(
        conclusion=report["conclusion"],
        attempted_pools=attempted,
        completed_windows=completed,
        density_exclusions=report["density_exclusion_count"],
        terminal_classifications=report["terminal_classification_counts"],
        selected_trades=report["selected_trade_count"],
        selected_median_pnl_bps=report["selected_median_pnl_bps"],
        rpc_calls=report["rpc_calls"],
        rpc_calls_per_attempted_pool=report["rpc_calls_per_attempted_pool"],
        rpc_calls_per_completed_observation=report[
            "rpc_calls_per_completed_observation"
        ],
    ), sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target-completed", type=int, default=TARGET_COMPLETED_WINDOWS
    )
    parser.add_argument(
        "--max-attempted-pools", type=int, default=MAX_ATTEMPTED_POOLS
    )
    parser.add_argument("--window-seconds", type=int, default=12)
    args = parser.parse_args()
    try:
        run_live(
            target_completed=args.target_completed,
            max_attempted_pools=args.max_attempted_pools,
            window_seconds=args.window_seconds,
        )
    except Exception as exc:
        failure = dict(
            kind="dlmm_profitability_density_screened_point_in_time_v3",
            allocation_authority=False,
            prospective_allocation_enabled=False,
            profitability_conclusion="not_established",
            conclusion="experiment_failed_before_valid_sample",
            error=str(exc)[:160],
            ended=int(time.time()),
        )
        research.REPORT.write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n"
        )
        print(json.dumps(failure, sort_keys=True))
        raise


if __name__ == "__main__":
    main()
