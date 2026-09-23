# All-market certification state

Runtime remains paper-only. This checkpoint is on the separate state branch; its commit is not the runtime SHA.

```json
{
  "acceptance_policy_identity": "131d8f5cd875bd3b2bae70864578043546c0959a04defc93fb225521351baa9f",
  "accounting_reconciliation": {
    "meteora": null,
    "pons": null,
    "pump": null,
    "ramses": null
  },
  "active_blocks": {
    "meteora": 0,
    "pons": 0,
    "pump": 0,
    "ramses": 0
  },
  "assurance_by_lane": {
    "meteora": {
      "last_valid_block": null
    },
    "pons": {
      "last_valid_block": null
    },
    "pump": {
      "last_valid_block": null
    },
    "ramses": {
      "last_valid_block": null
    }
  },
  "calendar_span": {
    "meteora": 0,
    "pons": 0,
    "pump": 0,
    "ramses": 0
  },
  "candidate_sha": "e5f45fa6c88aa9228ca8b8a5d15f9ded6cd48c71",
  "canonical_sha": "b57835dc50dd4047cefed13cfe0be975779af1e8",
  "certified_sha": "e5f45fa6c88aa9228ca8b8a5d15f9ded6cd48c71",
  "completed_blocks_by_lane": {
    "meteora": 0,
    "pons": 0,
    "pump": 0,
    "ramses": 0
  },
  "current_cohort_id": "prospective-four-lane-v4-market-assurance-20260923",
  "current_economic_metrics": {},
  "current_phase": "HALTED",
  "economic_acceptance_established": false,
  "engineering_blockers": [
    "worker_runtime_identity_missing_requires_successor_recertification"
  ],
  "historical_references": {
    "cancelled_run": 35905479952,
    "previous_nonmarket_run": 35907893183,
    "previous_observations_excluded": true,
    "provider_shape_probe": 35909625490,
    "superseded_market_run": 35915320840,
    "superseded_nonmarket_run": 35914189762
  },
  "history": [
    {
      "accepted_blocks": 0,
      "action": "halt_before_fresh_admission",
      "at": 1790205790.645613,
      "reason": "worker_runtime_identity_missing_requires_successor_recertification",
      "recovery_preserved": true,
      "recovery_run_id": 35931988977
    }
  ],
  "infrastructure_censoring": {
    "meteora": 0,
    "pons": 0,
    "pump": 0,
    "ramses": 0
  },
  "lane_health": {
    "meteora": {},
    "pons": {},
    "pump": {},
    "ramses": {}
  },
  "last_completed_action": {
    "accepted_blocks": 0,
    "action": "halt_before_fresh_admission",
    "at": 1790205790.645613,
    "reason": "worker_runtime_identity_missing_requires_successor_recertification",
    "recovery_preserved": true,
    "recovery_run_id": 35931988977
  },
  "latest_certification_run": 35931988977,
  "latest_market_run": null,
  "machinery_certified_by_lane": {
    "meteora": true,
    "pons": true,
    "pump": true,
    "ramses": true
  },
  "market_observation_validity": {
    "meteora": "coverage_unknown",
    "pons": "coverage_unknown",
    "pump": "coverage_unknown",
    "ramses": "coverage_unknown"
  },
  "material_lane_coverage_gaps": {
    "meteora": [],
    "pons": [],
    "pump": [],
    "ramses": []
  },
  "natural_lifecycle_observed_by_lane": {
    "meteora": false,
    "pons": false,
    "pump": false,
    "ramses": false
  },
  "natural_settlements_by_lane": {
    "meteora": 0,
    "pons": 0,
    "pump": 0,
    "ramses": 0
  },
  "next_action": "preserve_recovery_artifact_repair_then_certify_successor",
  "observation_hours": {
    "meteora": 0,
    "pons": 0,
    "pump": 0,
    "ramses": 0
  },
  "operational_limit": {
    "maximum_blocks": 192,
    "maximum_calendar_hours": 336
  },
  "operational_validity": {
    "accepted_blocks": 0,
    "accepted_observation_hours": 0,
    "censored_blocks": 0,
    "cohort_age_hours": 0,
    "observed_hours": 0
  },
  "portfolio_reconciliation": {
    "all_lane_ledgers_reconciled": false,
    "native_quote_units_are_never_summed": true,
    "normalized_portfolio": null
  },
  "prospective_sha": null,
  "realized_and_unrealized_by_lane": {
    "meteora": {
      "realized": null,
      "units": "lamports",
      "unrealized": null,
      "unrealized_status": "not_marked_by_native_ledger"
    },
    "pons": {
      "realized": null,
      "units": "native_quote_raw",
      "unrealized": null,
      "unrealized_status": "not_marked_by_native_ledger"
    },
    "pump": {
      "realized": null,
      "units": "lamports",
      "unrealized": null,
      "unrealized_status": "not_marked_by_native_ledger"
    },
    "ramses": {
      "by_quote_asset": {},
      "unlike_quote_units_summed": false
    }
  },
  "source_diff_hash_by_lane": {
    "meteora": "74ee2eaf30ef9df3b370cc6e311bd91d44f2fcf271f67c635d63db27277d9c64",
    "pons": "8a9d0818606e9c9c8e3ca76ce07f85fe0902aaf761d3de8042b1dd3ff2dd8238",
    "pump": "73382447eba168503b2c7dc909ecd3498cffabeaa116166c45a3af4c7b74836d",
    "ramses": "da50cd26eac0da8898c926facfcb168579894322871a70752043c6251f602d85"
  },
  "strategy_identity_by_lane": {
    "meteora": {
      "policy_hash": "90c711e5e3e521fb79f93bc386af5a3067d0a30c83ae3407c550f70db581f966",
      "strategy_version": "solana-dlmm-independent-v2.0-profitability-fee-density-v1-core-hold-v2"
    },
    "pons": {
      "policy_hash": "19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84",
      "strategy_version": "pons-selective-continuation-v1/profitability-v1-profit-protection-v2"
    },
    "pump": {
      "policy_hash": "b7718de9298e4c825616bed26c87731a65f43c4b12f152b14e1d574eb86eb8d5",
      "strategy_version": "pump-acceleration-independent-v1/profitability-v1-profit-protection-v2"
    },
    "ramses": {
      "policy_hash": "bf75a70fcdf68cf231dd354eab7cb56879bc4c16184553db5c121ea0fdc5d4ef",
      "strategy_version": "ramses-active-wide-maker-v3"
    }
  },
  "updated_at": 1790205790.645613
}
```
