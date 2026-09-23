"""Verify the frozen prospective certification protocol against executable authority."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROTOCOL=ROOT/"certification/profitability_protocol.json"
SOURCES=ROOT/"certification/sources.json"

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"))

def verify():
    protocol=json.loads(PROTOCOL.read_text())
    sources=json.loads(SOURCES.read_text())
    failures=[]
    if protocol.get("paper_only") is not True or protocol.get("live_money") is not False:
        failures.append("protocol_authority_boundary")
    frozen=protocol.get("frozen_lanes") or {}
    for lane,row in (sources.get("lanes") or {}).items():
        expected=frozen.get(lane)
        if not isinstance(expected,dict):
            failures.append("missing_frozen_lane:"+lane);continue
        observed={
            "strategy_version":row.get("strategy_version"),
            "source_sha":row.get("source_sha"),
            "execution_sha":row.get("execution_sha",row.get("source_sha")),
            "policy_hash":row.get("policy_hash"),
            "source_diff_sha256":row.get("source_diff_sha256"),
        }
        if observed!=expected:failures.append("frozen_lane_drift:"+lane)
    if set(frozen)!=set((sources.get("lanes") or {})):
        failures.append("frozen_lane_set_drift")
    four=(ROOT/".github/workflows/four-lane-certification.yml").read_text()
    cont=(ROOT/".github/workflows/position-continuation.yml").read_text()
    required_four=(
        "python -m certification.chain_binding",
        "python -m certification.prospective_acceptance record",
        "Start automatic durable continuation for open long-horizon positions",
    )
    for value in required_four:
        if value not in four:failures.append("four_lane_control_missing:"+value)
    if "Chain next bounded continuation slice when still open" not in cont:
        failures.append("continuation_self_chain_missing")
    if "actions: write" not in cont:
        failures.append("continuation_actions_write_missing")
    if protocol.get("autonomy_acceptance",{}).get(
            "automatic_new_campaign_scheduler_may_activate_only_after_lane_and_portfolio_economic_pass") is not True:
        failures.append("scheduler_activation_not_gated")
    digest=hashlib.sha256(canonical(protocol).encode()).hexdigest()
    return {
        "passed":not failures,
        "failures":failures,
        "protocol_sha256":digest,
        "source_manifest_sha256":hashlib.sha256(canonical(sources).encode()).hexdigest(),
        "cohort_id":protocol.get("cohort_id"),
        "paper_only":True,
        "live_money":False,
    }

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",required=True);a=p.parse_args()
    result=verify();path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)

if __name__=="__main__":
    main()
