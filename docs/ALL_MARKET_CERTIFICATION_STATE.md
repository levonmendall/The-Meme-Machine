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
    "initial_smoke_target_market_audit": {
      "aggregate_target_coverage_unknown_for_all_lanes": true,
      "all_native_books_verified_flat": true,
      "artifact_id": 10783726415,
      "artifact_sha256": "fb1631395f78645fcdeff2c7cdf4383aed12d4d8d36ed3adb790a921ac24f8c0",
      "audit_path": "certification/results/target-market-audit-35935431384.json",
      "captured_decisions_replayed": 51,
      "decision_replay_failures": 0,
      "economic_sample_eligible": false,
      "observed_target_counts": {
        "meteora": 10,
        "pons": null,
        "pump": null,
        "ramses": 5
      },
      "operational_validity": "valid",
      "ramses_latest_scan_denominator_not_used_for_multiscan_union": true,
      "workflow_run_id": 35935431384
    },
    "predecessor_recovery": {
      "all_four_native_books_verified_flat": true,
      "certificate_artifact_id": 10782437241,
      "certificate_digest": "sha256:e42f842603ffa071d8374ceb1da0ece47318c49f19f725436e510d39a4b2dfeb",
      "certified_recovery_sha": "c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66",
      "decision_replay_failures": 0,
      "economic_sample_eligible": false,
      "exclusion_reason": "engineering recovery of a failed predecessor; fixed before the outcome; original loss preserved",
      "original_native_event_prefix_retained": true,
      "original_runtime_sha": "b57835dc50dd4047cefed13cfe0be975779af1e8",
      "original_smoke_run_id": 35921058163,
      "pons_natural_entries": 0,
      "pons_natural_settlements": 0,
      "pons_unfilled_cancellations": 2,
      "ramses_decisions_replayed": 5,
      "ramses_modeled_execution_cost_quote_raw": 908348,
      "ramses_native_exit_reason": "inventory_risk_dominates",
      "ramses_original_entry_time_retained": true,
      "ramses_original_position_settled": true,
      "ramses_quote_asset": "0x5fc5360d0400a0fd4f2af552add042d716f1d168",
      "ramses_realized_result_quote_raw": -909334,
      "recovery_artifact_digest": "sha256:d14e954dad53f1c8828b587d05bd57723054a1419a64fc8196cd34492b996c00",
      "recovery_artifact_id": 10783125845,
      "recovery_run_id": 35934526436
    },
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
    },
    {
      "action": "independent_preserved_recovery_artifact_audit",
      "all_four_books_verified_flat": true,
      "artifact_id": 10783125845,
      "at": 1790207637.761,
      "economic_sample_eligible": false,
      "workflow_run_id": 35934526436
    },
    {
      "action": "independent_smoke_target_market_audit",
      "all_native_books_verified_flat": true,
      "artifact_id": 10783726415,
      "at": 1790209296.949,
      "captured_decisions_replayed": 51,
      "corrected_ramses_aggregate_coverage": null,
      "hourly_collection_in_progress": true,
      "hourly_job_id": 107438254109,
      "verified_manifest_files": 75,
      "workflow_run_id": 35935431384
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
    "action": "independent_smoke_target_market_audit",
    "all_native_books_verified_flat": true,
    "artifact_id": 10783726415,
    "at": 1790209296.949,
    "captured_decisions_replayed": 51,
    "corrected_ramses_aggregate_coverage": null,
    "hourly_collection_in_progress": true,
    "hourly_job_id": 107438254109,
    "verified_manifest_files": 75,
    "workflow_run_id": 35935431384
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
  "next_action": "complete_current_hourly_then_review_and_advance",
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
    "cohort_age_hours": 0.5489504143264559,
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
  "updated_at": 1790209296.949
}
```

## Independently reviewed smoke evidence

The initial smoke and its native artifact review passed on `c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66`. The one-hour campaign in workflow 35935431384 is running on that same certified revision. All 75 archived manifest files were independently checksum-verified; all four smoke books were verified flat. Pump replayed 44 captured decisions and Ramses 7 without differences. Pons and Meteora had no captured decisions, so their strategy behavior remains unexercised in this smoke. There were no natural entries or settlements in this smoke, and it is excluded from economic observations.

Observed-market counts use frozen strategy targets. Pump and Pons target membership counts remain unknown; Meteora observed 10 target pairs; Ramses observed five distinct target pools across two completed scan frontiers (four, then three, with two shared). Full-window target coverage remains unknown. The original Ramses report divided the five-pool union by the three-pool latest census; that percentage is invalid and is superseded by `null` in the [independent target-market audit](../certification/results/target-market-audit-35935431384.json). The raw artifact is preserved, and a runtime reporting correction remains required at a future certified revision. All lanes retain their recorded coverage gaps. Strategy rules, native evidence and economic admission are unchanged.
