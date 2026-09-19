"""Standalone DLMM pool eligibility audit; no strategy or provider authority."""
import json
from pathlib import Path

from tests import dlmm_adaptive_operator_discovery as discovery

OUT=Path("dlmm-pool-rejection-audit.json")

def main():
    diagnostic=discovery.diagnose_pool_universe()
    eligible,census=discovery.census_eligible_pools()
    report=dict(
        kind="dlmm_pool_rejection_audit_v1",
        rules_unchanged=True,
        allocation_authority=False,
        strategy_authority=False,
        diagnostic=diagnostic,
        filtered_census=census,
        filtered_eligible_pool_count=len(eligible),
        diagnostic_vs_filtered_difference=(
            None if not diagnostic.get("complete")
            else int(diagnostic.get("eligible_under_current_rules") or 0)-len(eligible)
        ),
    )
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(
        raw_unique=diagnostic.get("observable_unique_pools"),
        raw_complete=diagnostic.get("complete"),
        sol_pairs=diagnostic.get("exact_one_sol_leg_pools"),
        eligible=diagnostic.get("eligible_under_current_rules"),
        filtered_eligible=len(eligible),
        primary=diagnostic.get("primary_classification"),
        overlap=diagnostic.get("overlapping_rejection_reasons"),
    ),sort_keys=True))
    return report

if __name__=="__main__":
    main()
