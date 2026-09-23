# All-market certification state

Runtime remains paper-only. This checkpoint is on the separate state branch; its commit is not the runtime SHA.

```json
{
  "acceptance_policy_identity": "74cf0c2cf75a1fac031d5626754381d1fab51d2e2afa36f705a346028665e9a9",
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
  "calendar_span": {
    "meteora": 0,
    "pons": 0,
    "pump": 0,
    "ramses": 0
  },
  "candidate_sha": "b57835dc50dd4047cefed13cfe0be975779af1e8",
  "canonical_sha": "b57835dc50dd4047cefed13cfe0be975779af1e8",
  "certified_sha": "b57835dc50dd4047cefed13cfe0be975779af1e8",
  "completed_blocks_by_lane": {
    "meteora": 0,
    "pons": 0,
    "pump": 0,
    "ramses": 0
  },
  "current_cohort_id": "prospective-four-lane-v3-complete-sample-20260923",
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
      "at": 1790197994.096657,
      "dispatch_id": "b6bd76a8cc7f409f834e33cbb9b21706"
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
    "at": 1790197994.096657,
    "dispatch_id": "b6bd76a8cc7f409f834e33cbb9b21706"
  },
  "latest_certification_run": 35920022541,
  "latest_market_run": 35921058163,
  "machinery_certified_by_lane": {
    "meteora": true,
    "pons": true,
    "pump": true,
    "ramses": true
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
  "prospective_sha": "b57835dc50dd4047cefed13cfe0be975779af1e8",
  "source_diff_hash_by_lane": {
    "meteora": "a00a177abf1431a274c11f6bac32df5ef17be2893ee9fe23077fa2c4a523237f",
    "pons": "b657828bb6cd7852abd7859b16c4f2009e5cb0f4a3cb150c6bd3cb679689a2bb",
    "pump": "73382447eba168503b2c7dc909ecd3498cffabeaa116166c45a3af4c7b74836d",
    "ramses": "d68289955210b4e602090431096078cd1d0cc82abc04f1141eaf87cf3234d082"
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
  "updated_at": 1790198008.002007
}
```
