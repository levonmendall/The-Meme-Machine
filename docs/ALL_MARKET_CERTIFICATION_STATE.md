# All-market certification state

Runtime remains paper-only. This checkpoint is on the separate state branch; its commit is not the runtime SHA.

```json
{
  "acceptance_policy_identity": "d473936a59a5ab309858c5cfa7347a002677467c90984c0ecffe3986dd053664",
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
  "candidate_sha": "c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66",
  "canonical_sha": "c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66",
  "certified_sha": "c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66",
  "completed_blocks_by_lane": {
    "meteora": 0,
    "pons": 0,
    "pump": 0,
    "ramses": 0
  },
  "current_cohort_id": "prospective-four-lane-v5-market-assurance-20260923",
  "current_economic_metrics": {},
  "current_phase": "RUNNING",
  "economic_acceptance_established": false,
  "engineering_blockers": [],
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
      "action": "dispatch_intent",
      "at": 1790207325.6413314,
      "dispatch_id": "18d4856b9c864d4da0619885d1f8f0cf"
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
    "action": "dispatch_intent",
    "at": 1790207325.6413314,
    "dispatch_id": "18d4856b9c864d4da0619885d1f8f0cf"
  },
  "latest_certification_run": 35934526436,
  "latest_market_run": 35935431384,
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
  "next_action": "smoke_then_hourly",
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
    "cohort_age_hours": 0.00514588024881151,
    "observed_hours": 0
  },
  "portfolio_reconciliation": {
    "all_lane_ledgers_reconciled": false,
    "native_quote_units_are_never_summed": true,
    "normalized_portfolio": null
  },
  "prospective_sha": "c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66",
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
    "ramses": "fb970b518446b807fb4e2aeba87743cd383ef5cb45132839d009e0b7293c78c4"
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
  "updated_at": 1790207339.2526772
}
```
