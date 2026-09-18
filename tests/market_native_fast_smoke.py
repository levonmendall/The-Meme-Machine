"""Fast prospective smoke test for the active market-native paper path.

Diagnostic only; never certification. Uses the same finalized Pump stream,
MarketNativeRuntime, unchanged continuation-v1 authority, Store, delayed fill path,
and paper-only execution as the full proof. It stops at the first useful boundary
and preserves enough bounded evidence to replay or diagnose the selected attempt.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from meme_machine.__main__ import _monitor_existing, _retire_scout_state
from meme_machine.engine import Engine
from meme_machine.market_native_runtime import MarketNativeRuntime
from meme_machine.postgrad import PostGraduationAdapter
from meme_machine.provider import RPC, PumpAdapter
from meme_machine.pumpswap_runtime import PumpSwapPaperRuntime
from meme_machine.store import Store
from meme_machine.stream import PumpLogStream, PumpTape, WINDOW_SECONDS

REPORT = Path("market-native-fast-smoke-report.json")
EVIDENCE = Path("market-native-fast-smoke-evidence.json")
DB = Path("market-native-fast-smoke.db")
DISCOVERY_SECONDS = max(300, min(int(os.environ.get("MM_MARKET_NATIVE_SMOKE_SECONDS", "720")), 900))
PREFLIGHT_BUDGET = max(1, min(int(os.environ.get("MM_MARKET_NATIVE_SMOKE_PREFLIGHT_BUDGET", "12")), 20))
FULL_EVIDENCE_BUDGET = max(1, min(int(os.environ.get("MM_MARKET_NATIVE_SMOKE_FULL_EVIDENCE_BUDGET", "4")), 8))
FILL_WAIT_SECONDS = max(30, min(int(os.environ.get("MM_MARKET_NATIVE_SMOKE_FILL_WAIT_SECONDS", "120")), 180))
RPC_LIMIT = 240
GENESIS_SOL_USD_MICROS = 97_840_000
GENESIS_SOURCE = "2026-09-17 fast market-native smoke; $97.84/SOL paper reference"


def _save(report):
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True))


def _save_evidence(payload):
    EVIDENCE.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _first_active_order(state):
    rows = []
    for oid, order in state.get("orders", {}).items():
        if order.get("status") == "reserved" or (order.get("status") == "settled" and order.get("fill")):
            rows.append((int(order.get("created", 0)), str(oid), oid))
    return min(rows)[2] if rows else None


def _target_order_stage(state, target_id):
    if target_id is None:
        return None
    order = state.get("orders", {}).get(target_id)
    if order is None:
        return "target_order_missing"
    if order.get("status") == "settled" and order.get("fill"):
        return "filled_entry"
    if order.get("status") == "reserved":
        return "reserved_order"
    if order.get("status") == "cancelled":
        return "reservation_cancelled"
    return "unexpected_target_order_state"


def _classify_stage(state, status, previous_full, previous_failures, target_id=None):
    if target_id is not None:
        stage = _target_order_stage(state, target_id)
        if stage is not None:
            return stage, target_id

    active = _first_active_order(state)
    if active is not None:
        return _target_order_stage(state, active), active

    full_now = int(status.get("full_evidence_attempted", 0))
    failures_now = int(status.get("provider_failures", 0))
    if failures_now > previous_failures:
        return (
            "provider_or_evidence_failure_after_full_attempt"
            if full_now > previous_full
            else "provider_or_evidence_failure_during_preflight"
        ), None
    if full_now > previous_full:
        if int(status.get("qualified", 0)) > 0:
            return "qualified_without_visible_order", None
        if status.get("full_reason_distribution"):
            return "full_evidence_completed_no_qualification", None
    return None, None


def _outcome_exit_code(outcome):
    if outcome in ("filled_entry", "full_evidence_completed_no_qualification"):
        return 0
    if outcome in ("no_full_evidence_candidate_in_smoke_window", "hard_deadline_exhausted"):
        return 2
    return 1


def _verify_replayable_store(path):
    store = Store(str(path), "prospective", GENESIS_SOL_USD_MICROS, GENESIS_SOURCE)
    try:
        return bool(store.reconcile() and store.verify_archive())
    finally:
        store.close()


def main():
    for path in (DB, EVIDENCE, REPORT):
        if path.exists():
            path.unlink()

    started = int(time.time())
    report = dict(
        kind="market_native_fast_smoke",
        diagnostic_only=True,
        certification_evidence=False,
        network="solana-mainnet",
        paper_only=True,
        live_money_authority=False,
        signing_authority=False,
        submission_authority=False,
        qualification_policy="continuation-v1",
        qualification_policy_frozen=True,
        discovery_mode="market_native",
        scout_lane_active=False,
        fomo_authority=False,
        dlmm_enabled=False,
        discovery_seconds=DISCOVERY_SECONDS,
        preflight_budget=PREFLIGHT_BUDGET,
        full_evidence_budget=FULL_EVIDENCE_BUDGET,
        fill_wait_seconds=FILL_WAIT_SECONDS,
        started=started,
        outcome=None,
        target_order_id=None,
        limitations=[],
    )
    _save(report)

    url = os.environ.get("MM_SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    store = Store(str(DB), "prospective", GENESIS_SOL_USD_MICROS, GENESIS_SOURCE)
    _retire_scout_state(store)
    engine = Engine(store, [])
    tape = PumpTape()
    stop = threading.Event()
    ready = threading.Event()
    stream = PumpLogStream(url, tape)
    thread = threading.Thread(target=stream.run, args=(stop, ready), daemon=True)
    thread.start()

    rpc = RPC(url, limit=RPC_LIMIT)
    adapter = PumpAdapter(rpc)
    postgrad = PostGraduationAdapter(rpc, scan_rpc=object())
    pumpswap = PumpSwapPaperRuntime(store, postgrad)
    runtime = MarketNativeRuntime(
        engine, adapter, DISCOVERY_SECONDS,
        preflight_budget=PREFLIGHT_BUDGET,
        full_evidence_budget=FULL_EVIDENCE_BUDGET,
    )

    cursor = None
    coverage_ready_at = None
    target_id = None
    reservation_seen_at = None
    previous_full = 0
    previous_failures = 0
    hard_deadline = time.monotonic() + WINDOW_SECONDS + DISCOVERY_SECONDS + FILL_WAIT_SECONDS

    try:
        if not ready.wait(15) or stream.error_kind:
            report["limitations"].append("stream_subscription_unavailable")
            report["outcome"] = "stream_start_failure"

        while report["outcome"] is None and time.monotonic() < hard_deadline:
            now = int(time.time())
            if stream.error_kind:
                report["limitations"].append("stream_continuity_lost")
                report["outcome"] = "stream_continuity_lost"
                break

            _monitor_existing(engine, adapter, now, pumpswap_runtime=pumpswap)
            state = store.state
            status = runtime.status()

            if target_id is not None:
                stage, _ = _classify_stage(
                    state, status, previous_full, previous_failures, target_id=target_id)
                if stage == "filled_entry":
                    report["outcome"] = stage
                    break
                if stage == "reservation_cancelled":
                    report["outcome"] = stage
                    break
                if stage in ("target_order_missing", "unexpected_target_order_state"):
                    report["outcome"] = stage
                    break
                if stage == "reserved_order":
                    if reservation_seen_at is None:
                        reservation_seen_at = time.monotonic()
                        report["reservation_observed_at"] = now
                    if time.monotonic() - reservation_seen_at >= FILL_WAIT_SECONDS:
                        report["outcome"] = "reservation_not_filled_within_smoke_window"
                        break
            else:
                cursor = runtime.tick(tape, now, cursor)
                status = runtime.status()
                if runtime.coverage_ready_at is not None and coverage_ready_at is None:
                    coverage_ready_at = int(runtime.coverage_ready_at)
                    report["coverage_ready_at"] = coverage_ready_at

                stage, oid = _classify_stage(
                    state, status, previous_full, previous_failures)
                if stage == "reserved_order":
                    target_id = oid
                    report["target_order_id"] = oid
                    reservation_seen_at = time.monotonic()
                    report["reservation_observed_at"] = now
                elif stage == "filled_entry":
                    target_id = oid
                    report["target_order_id"] = oid
                    report["outcome"] = stage
                    break
                elif stage is not None:
                    report["outcome"] = stage
                    break

                if (coverage_ready_at is not None and
                        now - coverage_ready_at >= DISCOVERY_SECONDS and
                        report["outcome"] is None):
                    report["outcome"] = "no_full_evidence_candidate_in_smoke_window"
                    break

            previous_full = int(status.get("full_evidence_attempted", 0))
            previous_failures = int(status.get("provider_failures", 0))
            report.update(
                current_time=now,
                target_order_id=target_id,
                stream=tape.status(now),
                market_native=status,
                concentration=adapter.concentration_status(),
                funnel=dict(state.get("funnel", {})),
                order_status=(state.get("orders", {}).get(target_id) or {}).get("status"),
                provider=dict(logical=rpc.calls, transport=rpc.http_requests,
                              failures=rpc.failures, retries=rpc.retries,
                              failure_kinds=dict(rpc.failure_kinds)),
            )
            _save(report)
            stop.wait(1.0)

        if report["outcome"] is None:
            report["outcome"] = "hard_deadline_exhausted"
    finally:
        ended = int(time.time())
        stop.set()
        thread.join(timeout=3)
        integrity_error = None
        try:
            reconciled = bool(store.reconcile())
            archive_verified = bool(store.verify_archive())
        except Exception as exc:
            reconciled = archive_verified = False
            integrity_error = type(exc).__name__
            report["limitations"].append(f"integrity_verification_failed:{integrity_error}")

        state = store.state
        status = runtime.status()
        if target_id is not None and _target_order_stage(state, target_id) == "filled_entry":
            report["outcome"] = "filled_entry"

        evidence = dict(
            kind="market_native_fast_smoke_replay_bundle",
            captured_at=ended,
            outcome=report.get("outcome"),
            target_order_id=target_id,
            diagnostic_last_attempt=status.get("diagnostic_last_attempt"),
            concentration=adapter.concentration_status(),
            provider=dict(logical=rpc.calls, transport=rpc.http_requests,
                          failures=rpc.failures, retries=rpc.retries,
                          failure_kinds=dict(rpc.failure_kinds)),
            target_order=(state.get("orders", {}).get(target_id) if target_id else None),
        )
        _save_evidence(evidence)

        report.update(
            ended=ended,
            target_order_id=target_id,
            stream=tape.status(ended),
            stream_error_kind=stream.error_kind,
            market_native=status,
            concentration=adapter.concentration_status(),
            funnel=dict(state.get("funnel", {})),
            orders={str(k): dict(status=v.get("status"), mint=v.get("mint"),
                                 reason=v.get("reason"), has_fill=bool(v.get("fill")))
                    for k, v in state.get("orders", {}).items()},
            reconciled=reconciled,
            archive_verified=archive_verified,
            integrity_error=integrity_error,
            provider=dict(logical=rpc.calls, transport=rpc.http_requests,
                          failures=rpc.failures, retries=rpc.retries,
                          failure_kinds=dict(rpc.failure_kinds)),
        )
        _save(report)
        store.close()

    try:
        report["artifact_reopen_verified"] = _verify_replayable_store(DB)
    except Exception as exc:
        report["artifact_reopen_verified"] = False
        report["limitations"].append(f"artifact_reopen_failed:{type(exc).__name__}")
    _save(report)

    exit_code = _outcome_exit_code(report["outcome"])
    if not report.get("reconciled") or not report.get("archive_verified") or not report.get("artifact_reopen_verified"):
        exit_code = 1

    print(json.dumps(dict(
        outcome=report.get("outcome"),
        exit_code=exit_code,
        target_order_id=report.get("target_order_id"),
        market_native=report.get("market_native"),
        concentration=report.get("concentration"),
        funnel=report.get("funnel"),
        provider=report.get("provider"),
        reconciled=report.get("reconciled"),
        archive_verified=report.get("archive_verified"),
        artifact_reopen_verified=report.get("artifact_reopen_verified"),
        limitations=report.get("limitations"),
    ), sort_keys=True))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
