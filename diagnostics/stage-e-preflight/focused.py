"""Run only the three preserved Lane C cases; log state only after fatal errors."""
import dataclasses
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CASES = [
    "tests.test_run379_production_pressure.ProductionPressureTests.test_dense_commits_controls_and_retention_all_progress_with_original_bounds",
    "tests.test_run380_production_pressure.SourceClockPressureTests.test_sustained_source_clock_candidate_progress_and_durable_drain",
    "tests.test_run373_dispatch_throughput.Run373DispatchThroughputTests.test_sustains_run373_shaped_large_frame_rate_without_capacity_disconnect",
]


def main():
    from meme_machine.solana_maintenance_arbiter import MaintenanceArbiter
    from meme_machine.solana_maintenance_runtime import MaintenanceRuntime
    choose = MaintenanceArbiter.choose
    turn = MaintenanceRuntime.turn

    def traced_choose(arbiter, **kwargs):
        try:
            return choose(arbiter, **kwargs)
        except BaseException as exc:
            print("LANE_C_ARBITER_ERROR " + json.dumps({
                "error": type(exc).__name__ + ":" + str(exc),
                "now": kwargs["now"],
                "needs": [dataclasses.asdict(n) for n in kwargs["needs"]],
                "ready": kwargs["ready"],
                "origins": [[side, scope, at] for (side, scope), at in arbiter.origin.items()],
                "pending": dataclasses.asdict(arbiter.pending) if arbiter.pending else None,
                "leases": dataclasses.asdict(arbiter.leases),
            }, sort_keys=True), flush=True)
            raise

    def traced_turn(runtime, *args, **kwargs):
        try:
            return turn(runtime, *args, **kwargs)
        except BaseException as exc:
            if runtime.failure:
                print("LANE_C_RUNTIME_ERROR " + json.dumps({
                    "error": type(exc).__name__ + ":" + str(exc),
                    "monotonic": runtime.monotonic(),
                    "wall": runtime.wall(),
                    "anchor_wall": runtime.clock.wall,
                    "anchor_monotonic": runtime.clock.monotonic,
                    "observation": dataclasses.asdict(runtime.last_observation) if runtime.last_observation else None,
                    "ring": list(runtime.ring),
                    "nonrecord_since": [[side, scope, at] for (side, scope), at in runtime.nonrecord_since.items()],
                }, sort_keys=True), flush=True)
            raise

    MaintenanceArbiter.choose = traced_choose
    MaintenanceRuntime.turn = traced_turn
    try:
        suite = unittest.defaultTestLoader.loadTestsFromNames(CASES)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        MaintenanceArbiter.choose = choose
        MaintenanceRuntime.turn = turn
    summary = {
        "tests": result.testsRun,
        "passes": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skips": len(result.skipped),
        "failure_cases": [t.id() for t, _ in result.failures],
        "error_cases": [t.id() for t, _ in result.errors],
        "skip_cases": [[t.id(), reason] for t, reason in result.skipped],
        "observability": "Post-error numeric state only; original methods, bounds and assertions unchanged.",
    }
    out = Path(os.environ["LANE_C_EVIDENCE"])
    (out / "focused-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("LANE_C_FOCUSED_RESULT " + json.dumps(summary, sort_keys=True), flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
