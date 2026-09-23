"""Aggregate non-market engineering certification from independently scoped gates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

LANES=("pump","pons","meteora","ramses")

def load(path):
    return json.loads(Path(path).read_text())

def run(evidence,output,expected_sha=None):
    root=Path(evidence)
    offline=load(root/"offline/result.json")
    crash=load(root/"crash.json")
    restart=load(root/"restart-safety/result.json")
    integrated=load(root/"integrated-acceptance/result.json")
    historical=load(root/"historical-resolution.json")
    connectivity={lane:load(root/f"{lane}-connectivity.json") for lane in LANES}
    resources={
        "pump":load(root/"pump-resource.json"),
        "meteora_general":load(root/"meteora-resource.json"),
        "meteora_dlmm":load(root/"meteora-dlmm-resource.json"),
    }

    crash_pass=all(bool(row.get("passed")) for row in crash.get("lanes",[])) and {
        row.get("lane") for row in crash.get("lanes",[])
    }==set(LANES)
    historical_pass=(
        historical.get("disposition")=="certified_historical_unreplayable_zero_proceeds_writeoff"
        and historical.get("immutable_original_artifact_preserved") is True
        and historical.get("market_settlement_performed") is False
        and historical.get("after",{}).get("open_positions")==0
        and historical.get("after",{}).get("reserved")==0
        and historical.get("after",{}).get("stale_marks")==0
        and historical.get("after",{}).get("writeoffs")==1
    )
    connectivity_pass=all(row.get("passed") is True for row in connectivity.values())
    resource_pass=(
        resources["pump"].get("real_provider_calls")==0
        and resources["meteora_general"].get("real_provider_calls")==0
        and resources["meteora_dlmm"].get("real_provider_calls")==0
        and resources["pump"].get("peak_rss_kib",0)>0
        and resources["meteora_general"].get("peak_rss_kib",0)>0
        and resources["meteora_dlmm"].get("peak_rss_kib",0)>0
    )
    identity_pass=(not expected_sha or offline.get("integration_sha")==expected_sha)
    gates={
        "exact_source_offline":offline.get("passed") is True,
        "native_crash_matrix":crash_pass,
        "restart_safety":restart.get("passed") is True,
        "integrated_current_policy":integrated.get("passed") is True,
        "historical_exposure_resolution":historical_pass,
        "production_adapter_connectivity":connectivity_pass,
        "resource_bounds":resource_pass,
        "exact_integration_identity":identity_pass,
    }
    passed=all(gates.values())
    result=dict(
        passed=passed,
        engineering_certification=(
            "CERTIFIED_NON_MARKET_ENGINEERING" if passed else "NOT_CERTIFIED"
        ),
        integration_sha=offline.get("integration_sha"),
        expected_integration_sha=expected_sha,
        gates=gates,
        test_counts=offline.get("test_counts"),
        restart_contract=(
            "resume idempotently where native lifecycle context is complete; otherwise "
            "preserve durable exposure and fail closed against fresh admission"
        ),
        integrated_acceptance=integrated,
        historical_resolution=dict(
            disposition=historical.get("disposition"),
            original_artifact_preserved=historical.get("immutable_original_artifact_preserved"),
            market_settlement_performed=historical.get("market_settlement_performed"),
            realized_pnl_lamports=historical.get("after",{}).get("realized_pnl_lamports"),
            open_positions=historical.get("after",{}).get("open_positions"),
            writeoffs=historical.get("after",{}).get("writeoffs"),
        ),
        connectivity={lane:dict(passed=row.get("passed"),scope=row.get("scope")) for lane,row in connectivity.items()},
        natural_market_only=[
            "prospective frequency/distribution of naturally qualifying opportunities",
            "prospective net profitability and outcome distribution",
            "natural fill/slippage/liquidity distribution versus paper assumptions",
            "frequency of naturally occurring post-entry paths",
        ],
        paper_only=True,
        live_money=False,
    )
    Path(output).write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(dict(
        passed=passed,
        engineering_certification=result["engineering_certification"],
        gates=gates,
        integration_sha=result["integration_sha"],
    ),sort_keys=True))
    return 0 if passed else 1

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--evidence",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--expected-sha")
    a=p.parse_args()
    raise SystemExit(run(a.evidence,a.output,a.expected_sha))
