# All-market certification state

Runtime remains paper-only. This checkpoint is on the separate state branch; its commit is not the runtime SHA.

```json
{
  "acceptance_policy_identity": "d4c0b1b29b976fc034f768a3180f2c58a3b62dedae4d76dbceec0cb39edd9936",
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
  "candidate_sha": "1c6da29d08bfbe42e39ea1c8068933aae6b15cdb",
  "canonical_sha": null,
  "certified_sha": "1c6da29d08bfbe42e39ea1c8068933aae6b15cdb",
  "completed_blocks_by_lane": {
    "meteora": 0,
    "pons": 0,
    "pump": 0,
    "ramses": 0
  },
  "current_cohort_id": "prospective-four-lane-v6-coverage-repair-20260924",
  "current_economic_metrics": {},
  "current_phase": "READY",
  "economic_acceptance_established": false,
  "engineering_blockers": [],
  "historical_references": {
    "cancelled_run": 35905479952,
    "coverage_repair": {
      "censored_workflow": 35935431384,
      "certification_run_id": 35948638345,
      "defects": {
        "meteora": [
          "source_census_starved_by_evidence",
          "off_pool_mint_supply_projection_mismatch"
        ],
        "pons": [
          "redundant_authenticated_factory_rounds",
          "redundant_cached_age_trajectory",
          "http_over_original_evidence_deadline"
        ],
        "pump": [
          "known_negative_signatures_reentered_history_hydration"
        ],
        "ramses": [
          "preentry_receipt_optional_timestamp_comparison"
        ]
      },
      "predecessor_cohort": "prospective-four-lane-v5-market-assurance-20260923",
      "predecessor_record_sha256": "90b6440a6429f8dc1f14f0ae63900bbcb2e7d8523c9719d55ad2561e6da8ff48",
      "predecessor_records_excluded": true,
      "predecessor_sha": "c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66",
      "repair_sha": "1c6da29d08bfbe42e39ea1c8068933aae6b15cdb",
      "schema": "target-market-coverage-repair-lineage-v1",
      "successor_cohort": "prospective-four-lane-v6-coverage-repair-20260924"
    },
    "previous_nonmarket_run": 35907893183,
    "previous_observations_excluded": true,
    "provider_shape_probe": 35909625490,
    "superseded_market_run": 35915320840,
    "superseded_nonmarket_run": 35914189762
  },
  "history": [],
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
  "last_completed_action": {},
  "latest_certification_run": 35948638345,
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
  "next_action": "dispatch_smoke_then_hourly",
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
    "cohort_age_hours": 7.119622495439318e-05,
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
    "meteora": "c6906c074f683f44a220281579f1c0ab86c8ce34e05f2ed1703b5eda4557e5af",
    "pons": "eba51a72058bb6a72a0e7e5d78db4fbc4d8c0b6e3a8327b0e8adc44bd507558e",
    "pump": "924799d001c51f898422a2494b75b1afcf2869583572af471f1bcc42d2176cd8",
    "ramses": "1264b5213376b8f1fa7b8e2c5d0359b20be1ef44f7dddd4a1c6441e811a05173"
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
  "updated_at": 1790218518.5400684
}
```
