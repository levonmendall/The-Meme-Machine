"""Fast prospective smoke test for the active market-native paper path.

This is diagnostic, not certification. It uses the same finalized Pump stream,
MarketNativeRuntime, unchanged continuation-v1 authority, Store, delayed fill path,
and paper-only execution as the full proof, but stops at the first useful boundary:
a provider/evidence defect, a complete full-evidence rejection, a cancelled
reservation, or a genuinely filled paper entry.
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


def _filled_order(state):
    for oid, order in state.get("orders", {}).items():
        if order.get("status") == "settled" and order.get("fill"):
            return oid, order
    return None


def _reserved_order(state):
    for oid, order in state.get("orders", {}).items():
        if order.get("status") == "reserved":
            return oid, order
    return None


def _classify_stage(state, status, previous_full, previous_failures):
    filled = _filled_order(state)
    if filled is not None:
        return "filled_entry", filled[0]
    reserved = _reserved_order(state)
    if reserved is not None:
        return "reserved_order", reserved[0]
    full_now = int(status.get("full_evidence_attempted", 0))
    failures_now = int(status.get("provider_failures", 0))
    if full_now > previous_full and failures_now > previous_failures:
        return "provider_or_evidence_failure_after_full_attempt", None
    if full_now > previous_full:
        if int(status.get("qualified", 0)) > 0:
            return "qualified_without_visible_order", None
        if status.get("full_reason_distribution"):
            return "full_evidence_completed_no_qualification", None
    return None, None


def main():
    if DB.exists():
        DB.unlink()
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
    reservation_seen_at = None
    previous_full = 0
    previous_failures = 0
    exit_code = 0
    hard_deadline = time.monotonic() + WINDOW_SECONDS + DISCOVERY_SECONDS + FILL_WAIT_SECONDS

    try:
        if not ready.wait(15) or stream.error_kind:
            report["limitations"].append("stream_subscription_unavailable")
            report["outcome"] = "stream_start_failure"
            exit_code = 1
        while report["outcome"] is None and time.monotonic() < hard_deadline:
            now = int(time.time())
            if stream.error_kind:
                report["limitations"].append("stream_continuity_lost")
                report["outcome"] = "stream_continuity_lost"
                exit_code = 1
                break

            _monitor_existing(engine, adapter, now, pumpswap_runtime=pumpswap)
            state = store.state
            status = runtime.status()
            stage, oid = _classify_stage(state, status, previous_full, previous_failures)

            if stage == "filled_entry":
                report["outcome"] = stage
                report["target_order_id"] = oid
                break
            if stage == "reserved_order":
                report["target_order_id"] = oid
                if reservation_seen_at is None:
                    reservation_seen_at = time.monotonic()
                    report["reservation_observed_at"] = now
                if time.monotonic() - reservation_seen_at >= FILL_WAIT_SECONDS:
                    order = state["orders"].get(oid, {})
                    report["outcome"] = ("reservation_cancelled" if order.get("status") == "cancelled"
                                         else "reservation_not_filled_within_smoke_window")
                    exit_code = 1
                    break
            else:
                cursor = runtime.tick(tape, now, cursor)
                status = runtime.status()
                if runtime.coverage_ready_at is not None and coverage_ready_at is None:
                    coverage_ready_at = int(runtime.coverage_ready_at)
                    report["coverage_ready_at"] = coverage_ready_at
                stage, oid = _classify_stage(state, status, previous_full, previous_failures)
                if stage == "provider_or_evidence_failure_after_full_attempt":
                    report["outcome"] = stage
                    exit_code = 1
                    break
                if stage in ("full_evidence_completed_no_qualification", "qualified_without_visible_order"):
                    report["outcome"] = stage
                    exit_code = 1 if stage == "qualified_without_visible_order" else 0
                    break
                if (coverage_ready_at is not None and
                        now - coverage_ready_at >= DISCOVERY_SECONDS):
                    report["outcome"] = "no_full_evidence_candidate_in_smoke_window"
                    break

            previous_full = int(status.get("full_evidence_attempted", 0))
            previous_failures = int(status.get("provider_failures", 0))
            report.update(
                current_time=now,
                stream=tape.status(now),
                market_native=status,
                concentration=adapter.concentration_status(),
                funnel=dict(state.get("funnel", {})),
                order_status=(state.get("orders", {}).get(report.get("target_order_id")) or {}).get("status"),
                provider=dict(logical=rpc.calls, transport=rpc.http_requests,
                              failures=rpc.failures, retries=rpc.retries,
                              failure_kinds=dict(rpc.failure_kinds)),
            )
            _save(report)
            stop.wait(1.0)
    finally:
        ended = int(time.time())
        stop.set()
        thread.join(timeout=3)
        try:
            reconciled = bool(store.reconcile())
            archive_verified = bool(store.verify_archive())
        except Exception as exc:
            reconciled = archive_verified = False
            report["limitations"].append(f"integrity_verification_failed:{type(exc).__name__}")
            exit_code = 1
        state = store.state
        status = runtime.status()
        filled = _filled_order(state)
        if filled is not None and report.get("outcome") != "filled_entry":
            report["outcome"] = "filled_entry"
            report["target_order_id"] = filled[0]
        report.update(
            ended=ended,
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
            provider=dict(logical=rpc.calls, transport=rpc.http_requests,
                          failures=rpc.failures, retries=rpc.retries,
                          failure_kinds=dict(rpc.failure_kinds)),
        )
        _save(report)
        store.close()

    print(json.dumps(dict(
        outcome=report.get("outcome"), target_order_id=report.get("target_order_id"),
        market_native=report.get("market_native"), concentration=report.get("concentration"),
        funnel=report.get("funnel"), provider=report.get("provider"),
        reconciled=report.get("reconciled"), archive_verified=report.get("archive_verified"),
        limitations=report.get("limitations"),
    ), sort_keys=True))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
