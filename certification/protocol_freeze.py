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
    review=(ROOT/".github/workflows/prospective-cohort-review.yml").read_text()
    nonmarket=(ROOT/".github/workflows/non-market-certification.yml").read_text()
    required_four=(
        "python -m certification.chain_binding",
        "python -m certification.prospective_acceptance record",
        "Start automatic durable continuation for open long-horizon positions",
    )
    for value in required_four:
        if value not in four:failures.append("four_lane_control_missing:"+value)
    if "Chain next bounded continuation slice when still open" not in cont:
        failures.append("continuation_self_chain_missing")
    if "Amend original prospective block when this lane reaches a terminal state" not in cont:
        failures.append("continuation_prospective_amendment_missing")
    if "prospective_acceptance amend-continuation" not in cont:
        failures.append("continuation_amendment_command_missing")
    if "actions: write" not in cont:
        failures.append("continuation_actions_write_missing")
    for value in ("prospective_program review", "EXPECTED_SHA", "inputs.expected_integration_sha"):
        if value not in review:failures.append("cohort_review_control_missing:"+value)
    retention=protocol.get("autonomy_acceptance",{}).get(
        "prospective_artifact_retention_days")
    if retention!=90:
        failures.append("prospective_retention_not_repository_max")
    for name,text in (("four_lane",four),("continuation",cont),("cohort_review",review),
                      ("non_market",nonmarket)):
        if "retention-days: 365" in text:
            failures.append(name+":unsupported_retention_request")
    autonomy=protocol.get("autonomy_acceptance",{})
    if (autonomy.get("frozen_paper_certification_program_authorized_before_economic_acceptance") is not True
            or autonomy.get("automatic_new_campaign_scheduler_may_activate_only_after_lane_and_portfolio_economic_pass") is not False):
        failures.append("explicit_frozen_certification_program_authority_missing")
    program=(ROOT/"certification/prospective_program.py").read_text()
    for control in ("program_full_nonmarket_not_passed", "program_dispatch_already_claimed",
                    "program_canonical_sha_drift", "preserve_repair_recertify_successor_cohort"):
        if control not in program:failures.append("certification_program_control_missing:"+control)
    # Owner's later one-workflow authorization narrows scheduling authority only;
    # historical profitability/autonomy qualification criteria remain unchanged.
    try:
        from certification.single_campaign_control import configuration
        one=configuration()
        for text,control in ((four,'single_campaign_control claim'),
                             (four,'single_campaign_control begin-phase'),
                             (four,'single_campaign_control end-phase'),
                             (four,'single_campaign_control finish'),
                             (cont,'single_campaign_control prohibit --action continuation'),
                             (review,'single_campaign_control review'),
                             (program,"prohibit_if_enabled('successor_dispatch')")):
            if control not in text:failures.append('single_campaign_control_missing:'+control)
        smoke=(ROOT/'certification/smoke_continuation.py').read_text()
        if "prohibit_if_enabled('smoke_continuation_'+a.command)" not in smoke:
            failures.append('single_campaign_smoke_continuation_not_disabled')
        if '\n  push:' in four.split('permissions:',1)[0]:
            failures.append('single_campaign_implicit_push_market_trigger')
        if 'if: success() && inputs.single_campaign != true' not in four:
            failures.append('single_campaign_continuation_not_disabled')
    except (OSError,ValueError):
        failures.append('single_campaign_authorization_invalid_or_missing')
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
