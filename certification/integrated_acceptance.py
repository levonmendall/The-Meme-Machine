"""Integrated deterministic current-policy acceptance across all four prepared lanes.

This gate composes authentic/captured protocol decoding, current-policy qualification,
native paper lifecycle/settlement, durable recovery, and shared-provider contention.
It does not use future outcomes, live money, signing, or natural-market qualification.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import time

from certification.governor import Governor

LANES=("pump","pons","meteora","ramses")

BUNDLES={
    "pump":{
        "protocol":[
            "tests.test_captured.Captured.test_real_accounts_and_quotes",
            "tests.test_pump_acceleration_history.NegativeHistoryReuseTests",
        ],
        "qualification":[
            "tests.test_pump_acceleration_strategy.PumpAccelerationStrategyTests.test_strong_late_curve_can_qualify",
            "tests.test_pump_acceleration_strategy.PumpAccelerationStrategyTests.test_fill_time_persistence_rejects_decayed_thesis",
        ],
        "lifecycle":[
            "tests.test_paper_accounting.PaperAccountingTests.test_actual_lifecycle_replays_after_close_without_recycling_genesis",
            "tests.test_paper_accounting.PaperAccountingTests.test_duplicate_settlement_and_namespace_fail_closed",
        ],
    },
    "pons":{
        "protocol":[
            "robinhood_tests.test_captured.CapturedProviderTests.test_captured_mainnet_identity_and_bounded_provider_evidence",
            "robinhood_tests.test_coverage_acquisition",
            "robinhood_tests.test_pons_factory_hint_reuse",
        ],
        "qualification":[
            "robinhood_tests.test_pons_selective_continuation.PonsSelectivePolicyTests.test_clean_late_curve_acceleration_can_qualify",
            "robinhood_tests.test_pons_selective_continuation.PonsSelectivePolicyTests.test_fill_time_persistence_rejects_decayed_continuation",
        ],
        "lifecycle":[
            "robinhood_tests.test_pons_position_provider_recovery.PositionRecoveryTests.test_post_entry_429_refreshes_evidence_on_same_lifecycle_then_settles",
            "robinhood_tests.test_pons_position_provider_recovery.PositionRecoveryTests.test_pending_exit_session_auth_recovery_keeps_ledger_and_original_clock",
            "robinhood_tests.test_pons_partial_accounting.PartialAccountingTests.test_partial_cash_basis_costs_and_risk_time_survive_reopen_and_recycling",
        ],
    },
    "meteora":{
        "protocol":[
            "tests.test_dlmm_reference.OfficialReference.test_real_captured_swap_interval_exact_state_and_fee_attribution",
            "tests.test_meteora_discovery_scheduler",
            "tests.test_meteora_mint_supply",
        ],
        "qualification":[
            "tests.test_solana_dlmm_independent_v1.SolanaDlmmIndependentV1Tests.test_qualification_requires_authenticated_density_flow_capacity_and_unwind",
        ],
        "lifecycle":[
            "tests.test_dlmm_independent_accounting.DurableIndependentAccounting.test_full_lifecycle_reopens_replays_and_recycles_only_actual_cash",
            "tests.test_dlmm_independent_accounting.DurableIndependentAccounting.test_failed_monitor_keeps_position_and_cost_reserve",
            "tests.test_dlmm_independent_accounting.DurableIndependentAccounting.test_structural_unreplayable_monitor_writes_off_without_stranding",
        ],
    },
    "ramses":{
        "protocol":[
            "robinhood_tests.test_captured.CapturedProviderTests.test_captured_mainnet_identity_and_bounded_provider_evidence",
            "robinhood_tests.test_ramses_preentry_metadata",
        ],
        "qualification":[
            "robinhood_tests.test_ramses_connected_lifecycle.RamsesConnectedLifecycleTests.test_first_ranked_genuine_qualifier_is_selected",
            "robinhood_tests.test_ramses_connected_lifecycle.RamsesConnectedLifecycleTests.test_canonical_reclassification_reuses_scanner_prestate_without_state_rpc",
        ],
        "lifecycle":[
            "robinhood_tests.test_ramses_connected_lifecycle.RamsesConnectedLifecycleTests.test_ledger_persists_monitor_segment_and_rebalance_checkpoints",
            "robinhood_tests.test_ramses_connected_lifecycle.RamsesConnectedLifecycleTests.test_partial_unwind_liquidity_holds_position_open_for_retry",
            "robinhood_tests.test_ramses_capital_replay.RamsesCapitalReplay.test_rebalance_lost_ack_retry_after_reopen_does_not_duplicate_management",
        ],
    },
}

def _run_tests(cwd,tests,log):
    started=time.monotonic()
    proc=subprocess.run(
        [sys.executable,"-m","unittest","-v",*tests],
        cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        text=True,timeout=240,
    )
    Path(log).write_text(proc.stdout)
    return dict(
        passed=proc.returncode==0,
        exit_code=proc.returncode,
        tests=list(tests),
        seconds=time.monotonic()-started,
        log=Path(log).name,
    )

def _lane(lane,root,out,governor):
    cwd=root/lane
    rows={}
    waits={}
    # Protocol/candidate evidence shares foreground acquisition.
    waits["protocol"]=governor.acquire(
        "integrated-acceptance",lane,priority=20,deadline_seconds=30,
        methods=("protocol_fixture",),
    )
    rows["protocol"]=_run_tests(
        cwd,BUNDLES[lane]["protocol"],out/f"{lane}-protocol.log")

    waits["qualification"]=governor.acquire(
        "integrated-acceptance",lane,priority=20,deadline_seconds=30,
        methods=("qualification",),
    )
    rows["qualification"]=_run_tests(
        cwd,BUNDLES[lane]["qualification"],out/f"{lane}-qualification.log")

    # Once exposure exists, lifecycle work is priority zero.
    waits["lifecycle"]=governor.acquire(
        "integrated-acceptance",lane,priority=0,deadline_seconds=30,
        methods=("position_lifecycle",),
    )
    rows["lifecycle"]=_run_tests(
        cwd,BUNDLES[lane]["lifecycle"],out/f"{lane}-lifecycle.log")

    return dict(
        lane=lane,
        passed=all(x["passed"] for x in rows.values()),
        stages=rows,
        governor_wait_seconds=waits,
        protocol_capture_proven=rows["protocol"]["passed"],
        current_policy_qualification_proven=rows["qualification"]["passed"],
        lifecycle_settlement_recovery_proven=rows["lifecycle"]["passed"],
    )

def run(worktrees,output):
    root=Path(worktrees).resolve()
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    governor=Governor(out/"integrated-governor.sqlite",interval=.5)
    started=time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={lane:pool.submit(_lane,lane,root,out,governor) for lane in LANES}
        lanes={lane:futures[lane].result() for lane in LANES}
    elapsed=time.monotonic()-started
    g=governor.status()
    grants={row["lane"]:row["granted"] for row in g["lane_grants"]}
    waits={row["lane"]:row["queue_wait_seconds"] for row in g["lane_grants"]}
    fairness=(
        all(grants.get(lane)==3 for lane in LANES)
        and not g["queues"]
        and all(lane in waits for lane in LANES)
    )
    result=dict(
        scope="integrated_non_market_current_policy_acceptance",
        passed=all(row["passed"] for row in lanes.values()) and fairness,
        lanes=lanes,
        contention=dict(
            simultaneous_lanes=4,
            total_seconds=elapsed,
            governor=g,
            every_lane_received_three_stage_grants=fairness,
            position_lifecycle_priority=0,
            foreground_priority=20,
        ),
        contracts=dict(
            protocol="captured/authentic protocol evidence is decoded by lane-native code",
            qualification="current frozen policy admits/rejects through native strategy authority",
            lifecycle="native paper lifecycle reaches settlement/recovery invariants without live money",
            contention="all four lane bundles execute concurrently through one shared physical-request governor",
        ),
        paper_only=True,
        live_money=False,
        natural_market_required=False,
    )
    (out/"result.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(dict(
        passed=result["passed"],
        lanes={k:v["passed"] for k,v in lanes.items()},
        grants=grants,
        elapsed_seconds=elapsed,
    ),sort_keys=True))
    return 0 if result["passed"] else 1

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--worktrees",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    raise SystemExit(run(a.worktrees,a.output))
