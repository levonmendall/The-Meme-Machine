"""Deterministic arithmetic reproductions using the unchanged production classes."""
import dataclasses
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    from meme_machine.solana_evidence_plane import EvidenceUnavailable
    from meme_machine.solana_maintenance_arbiter import ClockModel, MaintenanceArbiter, Need, ServiceLeases
    from meme_machine.solana_maintenance_state import PRESERVATION_SECONDS, RESIDENCE_SECONDS
    leases = ServiceLeases()
    fixed = ClockModel(1790439000, 100, leases.clock_error)
    fixed.check(1790439000, 100 + leases.clock_error, {})
    try:
        fixed.check(1790439000, 100 + leases.clock_error + .001, {})
    except EvidenceUnavailable as exc:
        assert str(exc) == "maintenance_clock_relationship_invalid"
        frozen_result = str(exc)
    else:
        raise AssertionError("incoherent frozen clock was accepted")
    advancing = ClockModel(1790439000, 100, leases.clock_error)
    advancing.check(1790439011, 111, {})
    arbiter = MaintenanceArbiter("lane-c", leases)
    wall, mono = 2000000000.0, 100.0
    source_at = wall - 240
    clock = ClockModel(wall, mono, leases.clock_error)
    began = clock.project(source_at + PRESERVATION_SECONDS)
    arbiter.restore_progress("program:meteora", "archive", began, mono)
    need = Need("program:meteora", "archive", 160, 160,
                clock.project(source_at + RESIDENCE_SECONDS), None, 0)
    try:
        arbiter.choose(generation="lane-c", as_of=mono, now=mono,
                       needs=[need], ready={"archive": True, "retirement": True})
    except EvidenceUnavailable as exc:
        assert str(exc) == "maintenance_service_deadline_exhausted"
        aged_result = str(exc)
    else:
        raise AssertionError("already exhausted residence was admitted")
    result = {
        "frozen_wall": frozen_result,
        "advancing_wall_same_monotonic_delta": "accepted",
        "age_240": aged_result,
        "age_240_projected_safety_headroom": need.safety_deadline - mono,
        "age_240_successful_service_headroom": began + leases.drought - mono,
        "leases": dataclasses.asdict(leases),
        "preservation_seconds": PRESERVATION_SECONDS,
        "residence_seconds": RESIDENCE_SECONDS,
        "production_modified": False,
    }
    Path(os.environ["LANE_C_EVIDENCE"], "contract-probe.json").write_text(json.dumps(result, indent=2) + "\n")
    print("LANE_C_CONTRACT_PROBE " + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
