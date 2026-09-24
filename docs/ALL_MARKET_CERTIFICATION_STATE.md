# All-market certification state

Runtime remains paper-only. This checkpoint is on the separate state branch; its commit is not the runtime SHA.

```json
{
  "acceptance_policy_identity": "d4c0b1b29b976fc034f768a3180f2c58a3b62dedae4d76dbceec0cb39edd9936",
  "accounting_reconciliation": {
    "meteora": true,
    "pons": true,
    "pump": true,
    "ramses": true
  },
  "active_blocks": {
    "meteora": 0,
    "pons": 0,
    "pump": 0,
    "ramses": 0
  },
  "assurance_by_lane": {
    "meteora": {
      "accounting_reconciliation": {
        "accounting": {
          "available": 1000000000,
          "capital_time_through_ns": 0,
          "capital_unit_nanoseconds": 0,
          "cash": 1000000000,
          "economic_replay_verified": false,
          "genesis": {
            "asset": "SOL_lamports",
            "capital": 1000000000,
            "namespace": "solana_meteora_independent_v1",
            "paper_only": true,
            "policy_hash": "a69ec239772a86bc7526594c9822b6fc1e611b45b7e661f618099656b288d55b",
            "run_id": "9225f7e0-b77b-429a-be23-cdd10a334980"
          },
          "journal_events": 1,
          "journal_hash": "bb461fbabd93840be46e3a8641951f34477cf2780051bea2552acf13e813a5c8",
          "marked_equity": 1000000000,
          "net_cash_flows": 0,
          "open_positions": 0,
          "pending": 0,
          "realized_pnl_lamports": 0,
          "reconciled": true,
          "reserved": 0,
          "settled": 0,
          "stale_marks": 0,
          "unrealized_pnl_lamports": 0,
          "unsettled": 0,
          "writeoffs": 0
        },
        "economic_replay_claimed": false,
        "lane": "meteora",
        "open_positions": 0,
        "read_only": true,
        "settlement_inferred": false,
        "verified": true
      },
      "acquisition_latency_seconds": {
        "discovered__screened": {
          "count": 108,
          "max": 3597.135579586029,
          "p50": 2476.996775865555,
          "p95": 3585.6710493564606
        },
        "evidence_complete__qualified": {
          "count": 0,
          "max": null,
          "p50": null,
          "p95": null
        },
        "evidence_requested__evidence_complete": {
          "count": 5,
          "max": 152.39156651496887,
          "p50": 118.40555381774902,
          "p95": 119.99732184410095
        },
        "screened__evidence_requested": {
          "count": 56,
          "max": 5.207428455352783,
          "p50": 1.6278736591339111,
          "p95": 4.824590444564819
        }
      },
      "admission_failures": [],
      "authorized_count": 0,
      "behavioral_liveness": {
        "classification": "awaiting_market_or_policy",
        "discovery_breadth_healthy": "coverage_degraded",
        "evidence_progressing": 1790223690.0112991,
        "position_monitoring_progressing": null,
        "process_alive": false,
        "provider_alive": true,
        "qualification_progressing": 1790223690.1435,
        "settlement_progressing": null,
        "strategy_progressing": 1790223798.759432,
        "target_market_discovery_progressing": 1790223743.4720619
      },
      "candidates_requiring_full_evidence": null,
      "complete_natural_lifecycles": 0,
      "conformance_unavailable": [],
      "coverage_gaps": [
        "reconstruction_incomplete",
        "stream_coverage_loss",
        "discovered_candidates_pending_at_observation_close"
      ],
      "coverage_gaps_by_segment": [
        {
          "segment": {
            "segment": "not_preserved"
          },
          "transition_records": 37
        },
        {
          "discovered_in_page": 166,
          "global_api_total": 131822,
          "global_total_is_strategy_denominator": false,
          "not_discovered_from_acquired_page": 0,
          "observed_at": 1790223739.3089325,
          "one_wsol_pair_count": 166,
          "page": 1,
          "preflight_evaluated_in_page": 59,
          "raw_rows": 250,
          "sort": "fee_tvl_ratio_5m:desc"
        },
        {
          "discovered_in_page": 123,
          "global_api_total": 131822,
          "global_total_is_strategy_denominator": false,
          "not_discovered_from_acquired_page": 0,
          "observed_at": 1790223740.5587394,
          "one_wsol_pair_count": 123,
          "page": 2,
          "preflight_evaluated_in_page": 2,
          "raw_rows": 250,
          "sort": "fee_tvl_ratio_5m:desc"
        },
        {
          "discovered_in_page": 167,
          "global_api_total": 131822,
          "global_total_is_strategy_denominator": false,
          "not_discovered_from_acquired_page": 0,
          "observed_at": 1790223742.089504,
          "one_wsol_pair_count": 167,
          "page": 1,
          "preflight_evaluated_in_page": 61,
          "raw_rows": 250,
          "sort": "volume_5m:desc"
        },
        {
          "discovered_in_page": 50,
          "global_api_total": 131822,
          "global_total_is_strategy_denominator": false,
          "not_discovered_from_acquired_page": 0,
          "observed_at": 1790223743.4534976,
          "one_wsol_pair_count": 50,
          "page": 2,
          "preflight_evaluated_in_page": 3,
          "raw_rows": 250,
          "sort": "volume_5m:desc"
        },
        {
          "discovered_in_page": 160,
          "global_api_total": 131822,
          "global_total_is_strategy_denominator": false,
          "not_discovered_from_acquired_page": 0,
          "observed_at": 1790223745.0118985,
          "one_wsol_pair_count": 160,
          "page": 1,
          "preflight_evaluated_in_page": 57,
          "raw_rows": 250,
          "sort": "volume_30m:desc"
        },
        {
          "discovered_in_page": 170,
          "global_api_total": 131822,
          "global_total_is_strategy_denominator": false,
          "not_discovered_from_acquired_page": 0,
          "observed_at": 1790223746.6482618,
          "one_wsol_pair_count": 170,
          "page": 2,
          "preflight_evaluated_in_page": 32,
          "raw_rows": 250,
          "sort": "volume_30m:desc"
        }
      ],
      "coverage_health": "coverage_degraded",
      "current_open_positions": 0,
      "current_strategy_phase": "trigger_terminal",
      "decision_replay_checked": 5,
      "decision_replay_failures": [],
      "discovered_count": 2076,
      "discovered_too_late": null,
      "discovery_coverage": null,
      "economic_admission": "eligible_subject_to_frozen_block_gate",
      "evidence_attempt_coverage": null,
      "evidence_completion_coverage": 0.08928571428571429,
      "full_evidence_attempted": 56,
      "full_evidence_completed": 5,
      "infrastructure_censoring": {
        "classifications": {
          "no_authentic_activity": 24,
          "reconstruction_incomplete": 37,
          "strategy_rejection": 5,
          "structural_ineligible": 51
        },
        "frozen_policy": "profitability_protocol.json; prospective_acceptance._infra_fraction",
        "overlapping_counts": true
      },
      "last_strategy_progress_at": 1790223798.759432,
      "last_valid_block": "9225f7e0-b77b-429a-be23-cdd10a334980",
      "native_position_records_open": 0,
      "native_unsettled_records": 0,
      "natural_entries": 0,
      "natural_lifecycle": {
        "complete_natural_lifecycle_observed": false,
        "machinery_certified": "separate_exact_sha_certificate",
        "natural_entry_observed": false,
        "natural_exit_observed": false,
        "natural_monitoring_observed": false,
        "natural_partial_realization_observed_if_strategy_triggers_it": false,
        "natural_settlement_observed": false,
        "target_market_coverage_observed": "coverage_degraded"
      },
      "natural_settlements": 0,
      "never_discovered": null,
      "observed_market_count_scope": "strategy_target_only",
      "observed_market_count_status": "target_candidates_observed",
      "observed_source_pair_count": 2076,
      "oldest_open_position_age": null,
      "position_watchdog": {
        "status": "pass",
        "violations": []
      },
      "positions_spanning_blocks": 0,
      "preflight_coverage": 0.05202312138728324,
      "preflight_evaluated_count": 108,
      "provider_health": {
        "errors": {},
        "requests": 1155,
        "rpc_latency_seconds": {
          "p50": 0.085798365,
          "p95": 0.135027103,
          "p99": 0.155252378
        }
      },
      "qualified_count": null,
      "queue_saturation": {
        "classified_candidates": {
          "capacity_censored": 0,
          "consumer_deadline": 0,
          "local_budget_exhausted": 0
        },
        "maximum_concurrent_evaluations": null,
        "queue_time_at_capacity_seconds": null
      },
      "raw_acquired_source_count": 3649,
      "source_coverage": {
        "acquired_source_pages": 6,
        "acquired_union_discovery_coverage": 1.0,
        "acquisition": {
          "census_cycles": 60,
          "census_interval_seconds": 60,
          "coverage": "coverage_unknown",
          "fatal_error": null,
          "first_seen": 2076,
          "invocation": "b02013b4-8c69-4a66-9bc9-e779686ab612",
          "latest_cycle_segments": [
            {
              "details": {
                "global_total_is_strategy_denominator": false,
                "raw_rows": 250
              },
              "page": 1,
              "sort": "fee_tvl_ratio_5m:desc",
              "status": "acquired"
            },
            {
              "details": {
                "global_total_is_strategy_denominator": false,
                "raw_rows": 250
              },
              "page": 2,
              "sort": "fee_tvl_ratio_5m:desc",
              "status": "acquired"
            },
            {
              "details": {
                "global_total_is_strategy_denominator": false,
                "raw_rows": 250
              },
              "page": 1,
              "sort": "volume_5m:desc",
              "status": "acquired"
            },
            {
              "details": {
                "global_total_is_strategy_denominator": false,
                "raw_rows": 250
              },
              "page": 2,
              "sort": "volume_5m:desc",
              "status": "acquired"
            },
            {
              "details": {
                "global_total_is_strategy_denominator": false,
                "raw_rows": 250
              },
              "page": 1,
              "sort": "volume_30m:desc",
              "status": "acquired"
            },
            {
              "details": {
                "global_total_is_strategy_denominator": false,
                "raw_rows": 250
              },
              "page": 2,
              "sort": "volume_30m:desc",
              "status": "acquired"
            }
          ],
          "observation_deadline_at": 1790223797.3032603,
          "oldest_pending_wait_seconds": 3598.890862249,
          "pending": 1918,
          "planned_segments_per_cycle": 6,
          "producer_done": true,
          "producer_running": false,
          "segment_status_counts": {
            "acquired": 360
          },
          "spool": "solana-dlmm-independent-v1-live.discovery.sqlite",
          "target_universe_count": null
        },
        "authority": "Exact frozen DISCOVERY_SORTS, DISCOVERY_PAGES_PER_SORT and DISCOVERY_PAGE_SIZE",
        "census_complete": true,
        "discovered_in_acquired_structural_union": 2076,
        "errors": [],
        "full_strategy_target_universe_count": null,
        "gap_classification": null,
        "inferred_never_observed_outside_acquired_pages": false,
        "late_responses_excluded": [],
        "out_of_target_source_rows": 1573,
        "pending_discovered_candidates": 1918,
        "planned_source_pages": 6,
        "provider_calls_added": 0,
        "raw_acquired_source_union_count": 3649,
        "segments": [
          {
            "discovered_in_page": 166,
            "global_api_total": 131822,
            "global_total_is_strategy_denominator": false,
            "not_discovered_from_acquired_page": 0,
            "observed_at": 1790223739.3089325,
            "one_wsol_pair_count": 166,
            "page": 1,
            "preflight_evaluated_in_page": 59,
            "raw_rows": 250,
            "sort": "fee_tvl_ratio_5m:desc"
          },
          {
            "discovered_in_page": 123,
            "global_api_total": 131822,
            "global_total_is_strategy_denominator": false,
            "not_discovered_from_acquired_page": 0,
            "observed_at": 1790223740.5587394,
            "one_wsol_pair_count": 123,
            "page": 2,
            "preflight_evaluated_in_page": 2,
            "raw_rows": 250,
            "sort": "fee_tvl_ratio_5m:desc"
          },
          {
            "discovered_in_page": 167,
            "global_api_total": 131822,
            "global_total_is_strategy_denominator": false,
            "not_discovered_from_acquired_page": 0,
            "observed_at": 1790223742.089504,
            "one_wsol_pair_count": 167,
            "page": 1,
            "preflight_evaluated_in_page": 61,
            "raw_rows": 250,
            "sort": "volume_5m:desc"
          },
          {
            "discovered_in_page": 50,
            "global_api_total": 131822,
            "global_total_is_strategy_denominator": false,
            "not_discovered_from_acquired_page": 0,
            "observed_at": 1790223743.4534976,
            "one_wsol_pair_count": 50,
            "page": 2,
            "preflight_evaluated_in_page": 3,
            "raw_rows": 250,
            "sort": "volume_5m:desc"
          },
          {
            "discovered_in_page": 160,
            "global_api_total": 131822,
            "global_total_is_strategy_denominator": false,
            "not_discovered_from_acquired_page": 0,
            "observed_at": 1790223745.0118985,
            "one_wsol_pair_count": 160,
            "page": 1,
            "preflight_evaluated_in_page": 57,
            "raw_rows": 250,
            "sort": "volume_30m:desc"
          },
          {
            "discovered_in_page": 170,
            "global_api_total": 131822,
            "global_total_is_strategy_denominator": false,
            "not_discovered_from_acquired_page": 0,
            "observed_at": 1790223746.6482618,
            "one_wsol_pair_count": 170,
            "page": 2,
            "preflight_evaluated_in_page": 32,
            "raw_rows": 250,
            "sort": "volume_30m:desc"
          }
        ],
        "structurally_eligible_acquired_union_count": 2076,
        "target_structural_union_count": 2076,
        "undiscovered_in_acquired_structural_union": 0,
        "union_scope": "acquired ranking pages only; not the full strategy target universe",
        "unobserved_source_pages": []
      },
      "strategy_conformance": "pass",
      "structurally_eligible_count": null,
      "target_market_scope": {
        "authority": "SOLANA_DLMM_INDEPENDENT_V1.json; solana_dlmm_independent_v1 discovery loop",
        "denominator": "Full target-pair inventory is unknown. The bounded ranking-page union measures source acquisition only and does not redefine the target market.",
        "dimensions": [
          "quote_asset",
          "public_sort",
          "pool"
        ],
        "universe": "Nonblacklisted Solana Meteora DLMM pools with exactly one WSOL leg, as defined by the frozen strategy; no minimum TVL or absolute volume."
      },
      "target_market_universe_count": null,
      "upstream_acquisition": {
        "broader_source_rows_are_strategy_observations": false,
        "discovery_progress_at": 1790223743.4720619,
        "native_candidate_discovered_count": 2076,
        "native_funnel_stages": {
          "admitted": 56,
          "discovered": 2076,
          "economic_vector": 5,
          "evaluated": 5,
          "evidence_complete": 5,
          "evidence_requested": 56,
          "forward_observation": 18,
          "fresh_state": 18,
          "prospective_range": 5,
          "reconstruction_complete": 18,
          "reconstruction_started": 18,
          "rejected": 5,
          "screened": 108,
          "terminal": 108,
          "trigger_authenticated": 19,
          "trigger_observed": 19,
          "trigger_started": 23,
          "trigger_terminal": 23,
          "warmup_complete": 14,
          "warmup_started": 18
        }
      }
    },
    "pons": {
      "accounting_reconciliation": {
        "accounting": {
          "available": 1000000000000000000,
          "booked_realized": 0,
          "capital_at_risk_unit_nanoseconds": 0,
          "capital_integral_complete": true,
          "cash": 1000000000000000000,
          "cash_basis_conservation": true,
          "conservation": true,
          "genesis": 1000000000000000000,
          "namespace": "pons-selective-continuation-v1",
          "native_execution_cost": 0,
          "native_observation_complete": true,
          "policy_hash": "19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84",
          "positions": 0,
          "realized": 0,
          "remaining_cost_basis": 0,
          "reserved": 0,
          "unobserved_native_positions": [],
          "unsettled": 0
        },
        "lane": "pons",
        "open_positions": 0,
        "read_only": true,
        "settlement_inferred": false,
        "verified": true
      },
      "acquisition_latency_seconds": {
        "discovered__screened": {
          "count": 693,
          "max": 0.002372264862060547,
          "p50": 0.0006923675537109375,
          "p95": 0.0010886192321777344
        },
        "evidence_complete__qualified": {
          "count": 0,
          "max": null,
          "p50": null,
          "p95": null
        },
        "evidence_requested__evidence_complete": {
          "count": 0,
          "max": null,
          "p50": null,
          "p95": null
        },
        "screened__evidence_requested": {
          "count": 86,
          "max": 3.0259344577789307,
          "p50": 0.574256420135498,
          "p95": 1.7396152019500732
        }
      },
      "admission_failures": [],
      "authorized_count": 0,
      "behavioral_liveness": {
        "classification": "awaiting_market_or_policy",
        "discovery_breadth_healthy": "coverage_degraded",
        "evidence_progressing": null,
        "position_monitoring_progressing": null,
        "process_alive": false,
        "provider_alive": true,
        "qualification_progressing": null,
        "settlement_progressing": null,
        "strategy_progressing": 1790223864.268943,
        "target_market_discovery_progressing": null
      },
      "candidates_requiring_full_evidence": null,
      "complete_natural_lifecycles": 0,
      "conformance_unavailable": [],
      "coverage_gaps": [
        "provider_failed",
        "reconstruction_incomplete"
      ],
      "coverage_gaps_by_segment": [
        {
          "segment": {
            "segment": "not_preserved"
          },
          "transition_records": 240
        }
      ],
      "coverage_health": "coverage_degraded",
      "current_open_positions": 0,
      "current_strategy_phase": "rejected",
      "decision_replay_checked": 0,
      "decision_replay_failures": [],
      "discovered_count": null,
      "discovered_too_late": 1,
      "discovery_coverage": null,
      "economic_admission": "eligible_subject_to_frozen_block_gate",
      "evidence_attempt_coverage": null,
      "evidence_completion_coverage": null,
      "full_evidence_attempted": 86,
      "full_evidence_completed": null,
      "infrastructure_censoring": {
        "classifications": {
          "provider_failed": 1,
          "reconstruction_incomplete": 239,
          "stale_before_evidence": 1,
          "strategy_rejection": 452
        },
        "frozen_policy": "profitability_protocol.json; prospective_acceptance._infra_fraction",
        "overlapping_counts": true
      },
      "last_strategy_progress_at": 1790223864.268943,
      "last_valid_block": "9225f7e0-b77b-429a-be23-cdd10a334980",
      "native_position_records_open": 0,
      "native_unsettled_records": 0,
      "natural_entries": 0,
      "natural_lifecycle": {
        "complete_natural_lifecycle_observed": false,
        "machinery_certified": "separate_exact_sha_certificate",
        "natural_entry_observed": false,
        "natural_exit_observed": false,
        "natural_monitoring_observed": false,
        "natural_partial_realization_observed_if_strategy_triggers_it": false,
        "natural_settlement_observed": false,
        "target_market_coverage_observed": "coverage_degraded"
      },
      "natural_settlements": 0,
      "never_discovered": null,
      "observed_market_count_scope": "strategy_target_only",
      "observed_market_count_status": "unknown_scope_membership",
      "oldest_open_position_age": null,
      "position_watchdog": {
        "status": "pass",
        "violations": []
      },
      "positions_spanning_blocks": 0,
      "preflight_coverage": null,
      "preflight_evaluated_count": null,
      "provider_health": {
        "errors": {
          "eth_getLogs:http_429": 20,
          "provider_http_429": 20,
          "provider_rpc_3": 1
        },
        "requests": 6264,
        "rpc_latency_seconds": {
          "p50": 0.037858544,
          "p95": 0.341123801,
          "p99": 0.776508274
        }
      },
      "qualified_count": null,
      "queue_saturation": {
        "classified_candidates": {
          "capacity_censored": 0,
          "consumer_deadline": 0,
          "local_budget_exhausted": 0
        },
        "maximum_concurrent_evaluations": null,
        "queue_time_at_capacity_seconds": null
      },
      "strategy_conformance": "pass",
      "structurally_eligible_count": null,
      "target_market_scope": {
        "authority": "pons_selective_cohort.operational_configuration; pons_selective_continuation.POLICY",
        "denominator": "Canonical discovery cursor/log windows; independent all-event denominator unavailable.",
        "dimensions": [
          "curve",
          "graduation_state",
          "event_at"
        ],
        "universe": "Native-quote Pons curves in the frozen 50-85% progress, 120-600s age and 20-90s graduation-ETA domain, plus its authenticated graduation/re-entry modes; existing positions retain their lifecycle scope."
      },
      "target_market_universe_count": null,
      "upstream_acquisition": {
        "broader_source_rows_are_strategy_observations": false,
        "discovery_progress_at": 1790223863.8971958,
        "native_candidate_discovered_count": 2056,
        "native_funnel_stages": {
          "admitted": 86,
          "current_state_complete": 452,
          "current_state_queued": 693,
          "current_state_requested": 692,
          "discovered": 2056,
          "evidence_requested": 86,
          "prospect_admitted": 86,
          "prospect_screened": 452,
          "rejected": 452,
          "screened": 693,
          "terminal": 241
        }
      }
    },
    "pump": {
      "accounting_reconciliation": {
        "accounting": {
          "basis": 0,
          "capital_hour_denominator": 3600,
          "capital_unit_seconds": 0,
          "cash": 5110384300,
          "initial": 5110384300,
          "lane": "pump-acceleration-independent-v1",
          "marked_equity": 5110384300,
          "open_positions": 0,
          "pending": 0,
          "policy_hash": "b7718de9298e4c825616bed26c87731a65f43c4b12f152b14e1d574eb86eb8d5",
          "realized": 0,
          "reconciled": true,
          "reserved": 0,
          "run_id": "9225f7e0-b77b-429a-be23-cdd10a334980",
          "settled": 0,
          "unrealized": 0
        },
        "accounting_replay": {
          "cash": 5110384300,
          "events": 0,
          "final_hash": "0000000000000000000000000000000000000000000000000000000000000000",
          "verified": true
        },
        "lane": "pump",
        "open_positions": 0,
        "read_only": true,
        "settlement_inferred": false,
        "verified": true
      },
      "acquisition_latency_seconds": {
        "discovered__screened": {
          "count": 0,
          "max": null,
          "p50": null,
          "p95": null
        },
        "evidence_complete__qualified": {
          "count": 0,
          "max": null,
          "p50": null,
          "p95": null
        },
        "evidence_requested__evidence_complete": {
          "count": 1,
          "max": 72.62018966674805,
          "p50": 72.62018966674805,
          "p95": 72.62018966674805
        },
        "screened__evidence_requested": {
          "count": 0,
          "max": null,
          "p50": null,
          "p95": null
        }
      },
      "admission_failures": [],
      "authorized_count": 0,
      "behavioral_liveness": {
        "classification": "awaiting_market_or_policy",
        "discovery_breadth_healthy": "coverage_degraded",
        "evidence_progressing": 1790223518.091707,
        "position_monitoring_progressing": null,
        "process_alive": false,
        "provider_alive": true,
        "qualification_progressing": 1790223793.1375527,
        "settlement_progressing": null,
        "strategy_progressing": 1790224796.1815042,
        "target_market_discovery_progressing": null
      },
      "candidates_requiring_full_evidence": null,
      "complete_natural_lifecycles": 0,
      "conformance_unavailable": [],
      "coverage_gaps": [
        "reconstruction_incomplete",
        "stream_coverage_loss"
      ],
      "coverage_gaps_by_segment": [
        {
          "segment": {
            "mode": "post_graduation_momentum"
          },
          "transition_records": 261
        },
        {
          "segment": {
            "mode": "late_curve_acceleration"
          },
          "transition_records": 159
        },
        {
          "segment": {
            "mode": "pumpswap_second_leg"
          },
          "transition_records": 85
        },
        {
          "segment": {
            "segment": "not_preserved"
          },
          "transition_records": 32
        }
      ],
      "coverage_health": "coverage_degraded",
      "current_open_positions": 0,
      "current_strategy_phase": "discovered",
      "decision_replay_checked": 846,
      "decision_replay_failures": [],
      "discovered_count": null,
      "discovered_too_late": null,
      "discovery_coverage": null,
      "economic_admission": "eligible_subject_to_frozen_block_gate",
      "evidence_attempt_coverage": null,
      "evidence_completion_coverage": 0.04,
      "full_evidence_attempted": 25,
      "full_evidence_completed": 1,
      "infrastructure_censoring": {
        "classifications": {
          "reconstruction_incomplete": 55,
          "strategy_rejection": 53
        },
        "frozen_policy": "profitability_protocol.json; prospective_acceptance._infra_fraction",
        "overlapping_counts": true
      },
      "last_strategy_progress_at": 1790224796.1815042,
      "last_valid_block": "9225f7e0-b77b-429a-be23-cdd10a334980",
      "native_position_records_open": 0,
      "native_unsettled_records": 0,
      "natural_entries": 0,
      "natural_lifecycle": {
        "complete_natural_lifecycle_observed": false,
        "machinery_certified": "separate_exact_sha_certificate",
        "natural_entry_observed": false,
        "natural_exit_observed": false,
        "natural_monitoring_observed": false,
        "natural_partial_realization_observed_if_strategy_triggers_it": false,
        "natural_settlement_observed": false,
        "target_market_coverage_observed": "coverage_degraded"
      },
      "natural_settlements": 0,
      "never_discovered": null,
      "observed_market_count_scope": "strategy_target_only",
      "observed_market_count_status": "unknown_scope_membership",
      "oldest_open_position_age": null,
      "position_watchdog": {
        "status": "pass",
        "violations": []
      },
      "positions_spanning_blocks": 0,
      "preflight_coverage": null,
      "preflight_evaluated_count": null,
      "provider_health": {
        "errors": {
          "certification_provider_queue_deadline": 4
        },
        "requests": 5799,
        "rpc_latency_seconds": {
          "p50": 0.104760366,
          "p95": 0.159406943,
          "p99": 0.177577226
        }
      },
      "qualified_count": null,
      "queue_saturation": {
        "classified_candidates": {
          "capacity_censored": 0,
          "consumer_deadline": 0,
          "local_budget_exhausted": 0
        },
        "maximum_concurrent_evaluations": null,
        "queue_time_at_capacity_seconds": null
      },
      "strategy_conformance": "pass",
      "structurally_eligible_count": null,
      "target_market_scope": {
        "authority": "sources.json:lanes.pump.prospect_admission; pump_acceleration_strategy.POLICY",
        "denominator": "Source stream completeness; absolute chain opportunity census unavailable.",
        "dimensions": [
          "surface",
          "phase",
          "quote_asset"
        ],
        "universe": "Native-SOL Pump curves in the frozen 60-85% late-curve strategy domain, plus its authenticated PumpSwap graduation/continuation modes; existing positions retain their lifecycle scope."
      },
      "target_market_universe_count": null,
      "upstream_acquisition": {
        "broader_source_rows_are_strategy_observations": false,
        "discovery_progress_at": 1790224796.1815042,
        "native_candidate_discovered_count": 1290,
        "native_funnel_stages": {
          "admitted": 25,
          "discovered": 1290,
          "evaluated": 20,
          "evidence_complete": 1,
          "evidence_requested": 25,
          "prospect_incomplete": 25,
          "prospect_observed": 64,
          "prospect_screened": 53,
          "rejected": 20,
          "terminal": 32
        }
      }
    },
    "ramses": {
      "accounting_reconciliation": {
        "accounting": {
          "allocation_authority": false,
          "by_quote_asset": {},
          "conservation": true,
          "funding_state": "awaiting_first_qualified_pinned_screen",
          "open_positions": 0,
          "paper_entry_ready": false,
          "policy_hash": "bf75a70fcdf68cf231dd354eab7cb56879bc4c16184553db5c121ea0fdc5d4ef",
          "position_count": 0,
          "unlike_quote_units_summed": false
        },
        "lane": "ramses",
        "open_positions": 0,
        "read_only": true,
        "settlement_inferred": false,
        "verified": true
      },
      "acquisition_latency_seconds": {
        "discovered__screened": {
          "count": 7,
          "max": 0.0006024837493896484,
          "p50": 0.00032591819763183594,
          "p95": 0.0004723072052001953
        },
        "evidence_complete__qualified": {
          "count": 0,
          "max": null,
          "p50": null,
          "p95": null
        },
        "evidence_requested__evidence_complete": {
          "count": 0,
          "max": null,
          "p50": null,
          "p95": null
        },
        "screened__evidence_requested": {
          "count": 7,
          "max": 0.0012297630310058594,
          "p50": 0.0007030963897705078,
          "p95": 0.0009005069732666016
        }
      },
      "admission_failures": [],
      "authorized_count": 0,
      "behavioral_liveness": {
        "classification": "awaiting_market_or_policy",
        "discovery_breadth_healthy": "coverage_degraded",
        "evidence_progressing": null,
        "position_monitoring_progressing": null,
        "process_alive": false,
        "provider_alive": true,
        "qualification_progressing": 1790223855.01962,
        "settlement_progressing": null,
        "strategy_progressing": 1790223855.0199795,
        "target_market_discovery_progressing": 1790223855.0181556
      },
      "candidates_requiring_full_evidence": null,
      "complete_natural_lifecycles": 0,
      "conformance_unavailable": [],
      "coverage_gaps": [
        "reconstruction_incomplete"
      ],
      "coverage_gaps_by_segment": [
        {
          "segment": {
            "segment": "not_preserved"
          },
          "transition_records": 17
        }
      ],
      "coverage_health": "coverage_degraded",
      "current_open_positions": 0,
      "current_strategy_phase": "rejected",
      "decision_replay_checked": 17,
      "decision_replay_failures": [],
      "discovered_count": 7,
      "discovered_too_late": null,
      "discovery_coverage": 2.3333333333333335,
      "economic_admission": "eligible_subject_to_frozen_block_gate",
      "evidence_attempt_coverage": null,
      "evidence_completion_coverage": null,
      "full_evidence_attempted": 7,
      "full_evidence_completed": null,
      "infrastructure_censoring": {
        "classifications": {
          "reconstruction_incomplete": 7
        },
        "frozen_policy": "profitability_protocol.json; prospective_acceptance._infra_fraction",
        "overlapping_counts": true
      },
      "last_strategy_progress_at": 1790223855.0199795,
      "last_valid_block": "9225f7e0-b77b-429a-be23-cdd10a334980",
      "native_position_records_open": 0,
      "native_unsettled_records": 0,
      "natural_entries": 0,
      "natural_lifecycle": {
        "complete_natural_lifecycle_observed": false,
        "machinery_certified": "separate_exact_sha_certificate",
        "natural_entry_observed": false,
        "natural_exit_observed": false,
        "natural_monitoring_observed": false,
        "natural_partial_realization_observed_if_strategy_triggers_it": false,
        "natural_settlement_observed": false,
        "target_market_coverage_observed": "coverage_degraded"
      },
      "natural_settlements": 0,
      "never_discovered": null,
      "observed_market_count_scope": "strategy_target_only",
      "observed_market_count_status": "target_candidates_observed",
      "oldest_open_position_age": null,
      "position_watchdog": {
        "status": "pass",
        "violations": []
      },
      "positions_spanning_blocks": 0,
      "preflight_coverage": 1.0,
      "preflight_evaluated_count": 7,
      "provider_health": {
        "errors": {
          "eth_getBlockByNumber:http_429": 3,
          "eth_getLogs:http_429": 2,
          "provider_http_429": 5
        },
        "requests": 1421,
        "rpc_latency_seconds": {
          "p50": 0.345347668,
          "p95": 0.766744275,
          "p99": 0.776553933
        }
      },
      "qualified_count": null,
      "queue_saturation": {
        "classified_candidates": {
          "capacity_censored": 0,
          "consumer_deadline": 0,
          "local_budget_exhausted": 0
        },
        "maximum_concurrent_evaluations": null,
        "queue_time_at_capacity_seconds": null
      },
      "strategy_conformance": "pass",
      "structurally_eligible_count": 3,
      "target_market_scope": {
        "authority": "ramses_universe.scan; ramses_strategy.POLICY",
        "denominator": "Authenticated USDG subset of the complete quiet-entry pool cohort; the broad factory inventory is acquisition overhead.",
        "dimensions": [
          "quote_asset",
          "swap_count",
          "bin_depth"
        ],
        "universe": "Recently active Ramses USDG pools with one or two prior 30-minute swaps, as frozen in sources.json; existing positions retain their lifecycle scope."
      },
      "target_market_universe_count": 3,
      "upstream_acquisition": {
        "broader_source_rows_are_strategy_observations": false,
        "discovery_progress_at": 1790223855.0181556,
        "factory_inventory_count": 288,
        "known_target_candidates": 3,
        "native_candidate_discovered_count": 7,
        "native_funnel_stages": {
          "admitted": 7,
          "discovered": 7,
          "evaluated": 7,
          "evidence_requested": 7,
          "rejected": 7,
          "screened": 7
        },
        "quiet_activity_candidates": 3,
        "scope_exclusions": {}
      }
    }
  },
  "calendar_span": {
    "meteora": 1.2838006923596064,
    "pons": 1.2838006923596064,
    "pump": 1.2838006923596064,
    "ramses": 1.2838006923596064
  },
  "candidate_sha": "1c6da29d08bfbe42e39ea1c8068933aae6b15cdb",
  "canonical_sha": "1c6da29d08bfbe42e39ea1c8068933aae6b15cdb",
  "certified_sha": "1c6da29d08bfbe42e39ea1c8068933aae6b15cdb",
  "completed_blocks_by_lane": {
    "meteora": 1,
    "pons": 1,
    "pump": 1,
    "ramses": 1
  },
  "current_cohort_id": "prospective-four-lane-v6-coverage-repair-20260924",
  "current_economic_metrics": {
    "autonomy": {
      "automatic_campaign_scheduler_activation_allowed": false,
      "checks": {
        "automatic_continuation_required": true,
        "chain_binding_each_block": true,
        "identity_frozen": true,
        "no_manual_strategy_intervention": true,
        "portfolio_economic_pass": false,
        "provider_fail_closed": true,
        "runtime_controls_frozen": true
      },
      "status": "INCOMPLETE"
    },
    "cohort_id": "prospective-four-lane-v6-coverage-repair-20260924",
    "identity_frozen": true,
    "identity_sets": {
      "implementation_hash": [
        "b8a958d59e8f0a9b6e87c82b37a7bd02ae883c3f34bdd7d4e45ec322817dcc67"
      ],
      "integration_sha": [
        "1c6da29d08bfbe42e39ea1c8068933aae6b15cdb"
      ],
      "protocol_sha256": [
        "d4c0b1b29b976fc034f768a3180f2c58a3b62dedae4d76dbceec0cb39edd9936"
      ],
      "source_manifest_hash": [
        "0143be61b3edc2a5ac0a94f05d488a25f3a5df59a8dfba9876245d127b215dd9"
      ]
    },
    "lanes": {
      "meteora": {
        "active_blocks": 0,
        "block_returns": [
          0.0
        ],
        "calendar_span_hours": 1.2838006923596064,
        "completed_blocks": 1,
        "economic_checks": {
          "aggregate_realized_return_positive": false,
          "deployed_capital_hour_positive": false,
          "drawdown": true,
          "lower95_hourly_return_positive": false,
          "profit_factor": false,
          "worst_block": true
        },
        "lower95_return_per_hour": null,
        "max_drawdown": 0.0,
        "maximum_infrastructure_censoring_fraction": 0.0,
        "mean_deployed_return_per_capital_hour": null,
        "mean_return_per_hour": 0.0,
        "natural_settlements": 0,
        "observation_hours": 1.0004936206575,
        "profit_factor_value": null,
        "quality_checks": {
          "accounting": true,
          "active_blocks": false,
          "calendar_span": false,
          "capital_time_complete": true,
          "completed_blocks": false,
          "durable_replay": true,
          "flat_final_records": true,
          "forced_settlements": true,
          "freshness_finality": true,
          "infrastructure_censoring": true,
          "natural_settlements": false,
          "observation_hours": false,
          "telemetry": true
        },
        "status": "INCOMPLETE"
      },
      "pons": {
        "active_blocks": 0,
        "block_returns": [
          0.0
        ],
        "calendar_span_hours": 1.2838006923596064,
        "completed_blocks": 1,
        "economic_checks": {
          "aggregate_realized_return_positive": false,
          "deployed_capital_hour_positive": false,
          "drawdown": true,
          "lower95_hourly_return_positive": false,
          "profit_factor": false,
          "worst_block": true
        },
        "lower95_return_per_hour": null,
        "max_drawdown": 0.0,
        "maximum_infrastructure_censoring_fraction": 0.011627906976744186,
        "mean_deployed_return_per_capital_hour": null,
        "mean_return_per_hour": 0.0,
        "natural_settlements": 0,
        "observation_hours": 1.0004936206575,
        "profit_factor_value": null,
        "quality_checks": {
          "accounting": true,
          "active_blocks": false,
          "calendar_span": false,
          "capital_time_complete": true,
          "completed_blocks": false,
          "durable_replay": true,
          "flat_final_records": true,
          "forced_settlements": true,
          "freshness_finality": true,
          "infrastructure_censoring": true,
          "natural_settlements": false,
          "observation_hours": false,
          "telemetry": true
        },
        "status": "INCOMPLETE"
      },
      "pump": {
        "active_blocks": 0,
        "block_returns": [
          0.0
        ],
        "calendar_span_hours": 1.2838006923596064,
        "completed_blocks": 1,
        "economic_checks": {
          "aggregate_realized_return_positive": false,
          "deployed_capital_hour_positive": false,
          "drawdown": true,
          "lower95_hourly_return_positive": false,
          "profit_factor": false,
          "worst_block": true
        },
        "lower95_return_per_hour": null,
        "max_drawdown": 0.0,
        "maximum_infrastructure_censoring_fraction": 0.0,
        "mean_deployed_return_per_capital_hour": null,
        "mean_return_per_hour": 0.0,
        "natural_settlements": 0,
        "observation_hours": 1.0004936206575,
        "profit_factor_value": null,
        "quality_checks": {
          "accounting": true,
          "active_blocks": false,
          "calendar_span": false,
          "capital_time_complete": true,
          "completed_blocks": false,
          "durable_replay": true,
          "flat_final_records": true,
          "forced_settlements": true,
          "freshness_finality": true,
          "infrastructure_censoring": true,
          "natural_settlements": false,
          "observation_hours": false,
          "telemetry": true
        },
        "status": "INCOMPLETE"
      },
      "ramses": {
        "active_blocks": 0,
        "block_returns": [
          0.0
        ],
        "calendar_span_hours": 1.2838006923596064,
        "completed_blocks": 1,
        "economic_checks": {
          "aggregate_realized_return_positive": false,
          "deployed_capital_hour_positive": false,
          "drawdown": true,
          "lower95_hourly_return_positive": false,
          "profit_factor": false,
          "worst_block": true
        },
        "lower95_return_per_hour": null,
        "max_drawdown": 0.0,
        "maximum_infrastructure_censoring_fraction": 0.0,
        "mean_deployed_return_per_capital_hour": null,
        "mean_return_per_hour": 0.0,
        "natural_settlements": 0,
        "observation_hours": 1.0004936206575,
        "profit_factor_value": null,
        "quality_checks": {
          "accounting": true,
          "active_blocks": false,
          "calendar_span": false,
          "capital_time_complete": true,
          "completed_blocks": false,
          "durable_replay": true,
          "flat_final_records": true,
          "forced_settlements": true,
          "freshness_finality": true,
          "infrastructure_censoring": true,
          "natural_settlements": false,
          "observation_hours": false,
          "telemetry": true
        },
        "status": "INCOMPLETE"
      }
    },
    "live_money": false,
    "paper_only": true,
    "portfolio": {
      "calendar_span_hours": 1.2838006923596064,
      "checks": {
        "all_lanes_economic_pass": false,
        "calendar_span": false,
        "complete_blocks": false,
        "correlation_sample_and_limit": false,
        "drawdown": true,
        "lower95_hourly_return_positive": false,
        "profit_factor": false,
        "worst_block": true
      },
      "complete_blocks": 1,
      "correlations": {
        "meteora__pons": {
          "correlation": null,
          "joint_nonzero_blocks": 0,
          "status": "INCOMPLETE"
        },
        "meteora__ramses": {
          "correlation": null,
          "joint_nonzero_blocks": 0,
          "status": "INCOMPLETE"
        },
        "pons__ramses": {
          "correlation": null,
          "joint_nonzero_blocks": 0,
          "status": "INCOMPLETE"
        },
        "pump__meteora": {
          "correlation": null,
          "joint_nonzero_blocks": 0,
          "status": "INCOMPLETE"
        },
        "pump__pons": {
          "correlation": null,
          "joint_nonzero_blocks": 0,
          "status": "INCOMPLETE"
        },
        "pump__ramses": {
          "correlation": null,
          "joint_nonzero_blocks": 0,
          "status": "INCOMPLETE"
        }
      },
      "lower95_return_per_hour": null,
      "max_drawdown": 0.0,
      "mean_return_per_hour": 0.0,
      "profit_factor_value": null,
      "status": "INCOMPLETE"
    },
    "promotion_eligible": false,
    "protocol_sha256": "d4c0b1b29b976fc034f768a3180f2c58a3b62dedae4d76dbceec0cb39edd9936",
    "schema": "meme-machine-profitability-portfolio-autonomy-result-v1"
  },
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
  "history": [
    {
      "action": "dispatch_intent",
      "at": 1790218524.0877798,
      "dispatch_id": "532c587923464dd3af571397b49c198f"
    },
    {
      "action": "admitted_smoke_preserved",
      "at": 1790224942.5407226,
      "pending_lanes": [],
      "run_id": 35949285193
    },
    {
      "at": 1790224960.7465014,
      "event_id": "35949285193:1:prospective-observation.json",
      "native_run_id": "9225f7e0-b77b-429a-be23-cdd10a334980",
      "record_sha256": "e799393ef2d8307d1893ae90585544cfc24cad10544a2251c19ce2e0997c8988"
    }
  ],
  "infrastructure_censoring": {
    "meteora": 0.0,
    "pons": 0.011627906976744186,
    "pump": 0.0,
    "ramses": 0.0
  },
  "lane_health": {
    "meteora": {
      "accounting_reconciled": true,
      "assurance": {
        "accounting_reconciliation": {
          "accounting": {
            "available": 1000000000,
            "capital_time_through_ns": 0,
            "capital_unit_nanoseconds": 0,
            "cash": 1000000000,
            "economic_replay_verified": false,
            "genesis": {
              "asset": "SOL_lamports",
              "capital": 1000000000,
              "namespace": "solana_meteora_independent_v1",
              "paper_only": true,
              "policy_hash": "a69ec239772a86bc7526594c9822b6fc1e611b45b7e661f618099656b288d55b",
              "run_id": "9225f7e0-b77b-429a-be23-cdd10a334980"
            },
            "journal_events": 1,
            "journal_hash": "bb461fbabd93840be46e3a8641951f34477cf2780051bea2552acf13e813a5c8",
            "marked_equity": 1000000000,
            "net_cash_flows": 0,
            "open_positions": 0,
            "pending": 0,
            "realized_pnl_lamports": 0,
            "reconciled": true,
            "reserved": 0,
            "settled": 0,
            "stale_marks": 0,
            "unrealized_pnl_lamports": 0,
            "unsettled": 0,
            "writeoffs": 0
          },
          "economic_replay_claimed": false,
          "lane": "meteora",
          "open_positions": 0,
          "read_only": true,
          "settlement_inferred": false,
          "verified": true
        },
        "acquisition_latency_seconds": {
          "discovered__screened": {
            "count": 108,
            "max": 3597.135579586029,
            "p50": 2476.996775865555,
            "p95": 3585.6710493564606
          },
          "evidence_complete__qualified": {
            "count": 0,
            "max": null,
            "p50": null,
            "p95": null
          },
          "evidence_requested__evidence_complete": {
            "count": 5,
            "max": 152.39156651496887,
            "p50": 118.40555381774902,
            "p95": 119.99732184410095
          },
          "screened__evidence_requested": {
            "count": 56,
            "max": 5.207428455352783,
            "p50": 1.6278736591339111,
            "p95": 4.824590444564819
          }
        },
        "admission_failures": [],
        "authorized_count": 0,
        "behavioral_liveness": {
          "classification": "awaiting_market_or_policy",
          "discovery_breadth_healthy": "coverage_degraded",
          "evidence_progressing": 1790223690.0112991,
          "position_monitoring_progressing": null,
          "process_alive": false,
          "provider_alive": true,
          "qualification_progressing": 1790223690.1435,
          "settlement_progressing": null,
          "strategy_progressing": 1790223798.759432,
          "target_market_discovery_progressing": 1790223743.4720619
        },
        "candidates_requiring_full_evidence": null,
        "complete_natural_lifecycles": 0,
        "conformance_unavailable": [],
        "coverage_gaps": [
          "reconstruction_incomplete",
          "stream_coverage_loss",
          "discovered_candidates_pending_at_observation_close"
        ],
        "coverage_gaps_by_segment": [
          {
            "segment": {
              "segment": "not_preserved"
            },
            "transition_records": 37
          },
          {
            "discovered_in_page": 166,
            "global_api_total": 131822,
            "global_total_is_strategy_denominator": false,
            "not_discovered_from_acquired_page": 0,
            "observed_at": 1790223739.3089325,
            "one_wsol_pair_count": 166,
            "page": 1,
            "preflight_evaluated_in_page": 59,
            "raw_rows": 250,
            "sort": "fee_tvl_ratio_5m:desc"
          },
          {
            "discovered_in_page": 123,
            "global_api_total": 131822,
            "global_total_is_strategy_denominator": false,
            "not_discovered_from_acquired_page": 0,
            "observed_at": 1790223740.5587394,
            "one_wsol_pair_count": 123,
            "page": 2,
            "preflight_evaluated_in_page": 2,
            "raw_rows": 250,
            "sort": "fee_tvl_ratio_5m:desc"
          },
          {
            "discovered_in_page": 167,
            "global_api_total": 131822,
            "global_total_is_strategy_denominator": false,
            "not_discovered_from_acquired_page": 0,
            "observed_at": 1790223742.089504,
            "one_wsol_pair_count": 167,
            "page": 1,
            "preflight_evaluated_in_page": 61,
            "raw_rows": 250,
            "sort": "volume_5m:desc"
          },
          {
            "discovered_in_page": 50,
            "global_api_total": 131822,
            "global_total_is_strategy_denominator": false,
            "not_discovered_from_acquired_page": 0,
            "observed_at": 1790223743.4534976,
            "one_wsol_pair_count": 50,
            "page": 2,
            "preflight_evaluated_in_page": 3,
            "raw_rows": 250,
            "sort": "volume_5m:desc"
          },
          {
            "discovered_in_page": 160,
            "global_api_total": 131822,
            "global_total_is_strategy_denominator": false,
            "not_discovered_from_acquired_page": 0,
            "observed_at": 1790223745.0118985,
            "one_wsol_pair_count": 160,
            "page": 1,
            "preflight_evaluated_in_page": 57,
            "raw_rows": 250,
            "sort": "volume_30m:desc"
          },
          {
            "discovered_in_page": 170,
            "global_api_total": 131822,
            "global_total_is_strategy_denominator": false,
            "not_discovered_from_acquired_page": 0,
            "observed_at": 1790223746.6482618,
            "one_wsol_pair_count": 170,
            "page": 2,
            "preflight_evaluated_in_page": 32,
            "raw_rows": 250,
            "sort": "volume_30m:desc"
          }
        ],
        "coverage_health": "coverage_degraded",
        "current_open_positions": 0,
        "current_strategy_phase": "trigger_terminal",
        "decision_replay_checked": 5,
        "decision_replay_failures": [],
        "discovered_count": 2076,
        "discovered_too_late": null,
        "discovery_coverage": null,
        "economic_admission": "eligible_subject_to_frozen_block_gate",
        "evidence_attempt_coverage": null,
        "evidence_completion_coverage": 0.08928571428571429,
        "full_evidence_attempted": 56,
        "full_evidence_completed": 5,
        "infrastructure_censoring": {
          "classifications": {
            "no_authentic_activity": 24,
            "reconstruction_incomplete": 37,
            "strategy_rejection": 5,
            "structural_ineligible": 51
          },
          "frozen_policy": "profitability_protocol.json; prospective_acceptance._infra_fraction",
          "overlapping_counts": true
        },
        "last_strategy_progress_at": 1790223798.759432,
        "last_valid_block": null,
        "native_position_records_open": 0,
        "native_unsettled_records": 0,
        "natural_entries": 0,
        "natural_lifecycle": {
          "complete_natural_lifecycle_observed": false,
          "machinery_certified": "separate_exact_sha_certificate",
          "natural_entry_observed": false,
          "natural_exit_observed": false,
          "natural_monitoring_observed": false,
          "natural_partial_realization_observed_if_strategy_triggers_it": false,
          "natural_settlement_observed": false,
          "target_market_coverage_observed": "coverage_degraded"
        },
        "natural_settlements": 0,
        "never_discovered": null,
        "observed_market_count_scope": "strategy_target_only",
        "observed_market_count_status": "target_candidates_observed",
        "observed_source_pair_count": 2076,
        "oldest_open_position_age": null,
        "position_watchdog": {
          "status": "pass",
          "violations": []
        },
        "positions_spanning_blocks": 0,
        "preflight_coverage": 0.05202312138728324,
        "preflight_evaluated_count": 108,
        "provider_health": {
          "errors": {},
          "requests": 1155,
          "rpc_latency_seconds": {
            "p50": 0.085798365,
            "p95": 0.135027103,
            "p99": 0.155252378
          }
        },
        "qualified_count": null,
        "queue_saturation": {
          "classified_candidates": {
            "capacity_censored": 0,
            "consumer_deadline": 0,
            "local_budget_exhausted": 0
          },
          "maximum_concurrent_evaluations": null,
          "queue_time_at_capacity_seconds": null
        },
        "raw_acquired_source_count": 3649,
        "source_coverage": {
          "acquired_source_pages": 6,
          "acquired_union_discovery_coverage": 1.0,
          "acquisition": {
            "census_cycles": 60,
            "census_interval_seconds": 60,
            "coverage": "coverage_unknown",
            "fatal_error": null,
            "first_seen": 2076,
            "invocation": "b02013b4-8c69-4a66-9bc9-e779686ab612",
            "latest_cycle_segments": [
              {
                "details": {
                  "global_total_is_strategy_denominator": false,
                  "raw_rows": 250
                },
                "page": 1,
                "sort": "fee_tvl_ratio_5m:desc",
                "status": "acquired"
              },
              {
                "details": {
                  "global_total_is_strategy_denominator": false,
                  "raw_rows": 250
                },
                "page": 2,
                "sort": "fee_tvl_ratio_5m:desc",
                "status": "acquired"
              },
              {
                "details": {
                  "global_total_is_strategy_denominator": false,
                  "raw_rows": 250
                },
                "page": 1,
                "sort": "volume_5m:desc",
                "status": "acquired"
              },
              {
                "details": {
                  "global_total_is_strategy_denominator": false,
                  "raw_rows": 250
                },
                "page": 2,
                "sort": "volume_5m:desc",
                "status": "acquired"
              },
              {
                "details": {
                  "global_total_is_strategy_denominator": false,
                  "raw_rows": 250
                },
                "page": 1,
                "sort": "volume_30m:desc",
                "status": "acquired"
              },
              {
                "details": {
                  "global_total_is_strategy_denominator": false,
                  "raw_rows": 250
                },
                "page": 2,
                "sort": "volume_30m:desc",
                "status": "acquired"
              }
            ],
            "observation_deadline_at": 1790223797.3032603,
            "oldest_pending_wait_seconds": 3598.890862249,
            "pending": 1918,
            "planned_segments_per_cycle": 6,
            "producer_done": true,
            "producer_running": false,
            "segment_status_counts": {
              "acquired": 360
            },
            "spool": "solana-dlmm-independent-v1-live.discovery.sqlite",
            "target_universe_count": null
          },
          "authority": "Exact frozen DISCOVERY_SORTS, DISCOVERY_PAGES_PER_SORT and DISCOVERY_PAGE_SIZE",
          "census_complete": true,
          "discovered_in_acquired_structural_union": 2076,
          "errors": [],
          "full_strategy_target_universe_count": null,
          "gap_classification": null,
          "inferred_never_observed_outside_acquired_pages": false,
          "late_responses_excluded": [],
          "out_of_target_source_rows": 1573,
          "pending_discovered_candidates": 1918,
          "planned_source_pages": 6,
          "provider_calls_added": 0,
          "raw_acquired_source_union_count": 3649,
          "segments": [
            {
              "discovered_in_page": 166,
              "global_api_total": 131822,
              "global_total_is_strategy_denominator": false,
              "not_discovered_from_acquired_page": 0,
              "observed_at": 1790223739.3089325,
              "one_wsol_pair_count": 166,
              "page": 1,
              "preflight_evaluated_in_page": 59,
              "raw_rows": 250,
              "sort": "fee_tvl_ratio_5m:desc"
            },
            {
              "discovered_in_page": 123,
              "global_api_total": 131822,
              "global_total_is_strategy_denominator": false,
              "not_discovered_from_acquired_page": 0,
              "observed_at": 1790223740.5587394,
              "one_wsol_pair_count": 123,
              "page": 2,
              "preflight_evaluated_in_page": 2,
              "raw_rows": 250,
              "sort": "fee_tvl_ratio_5m:desc"
            },
            {
              "discovered_in_page": 167,
              "global_api_total": 131822,
              "global_total_is_strategy_denominator": false,
              "not_discovered_from_acquired_page": 0,
              "observed_at": 1790223742.089504,
              "one_wsol_pair_count": 167,
              "page": 1,
              "preflight_evaluated_in_page": 61,
              "raw_rows": 250,
              "sort": "volume_5m:desc"
            },
            {
              "discovered_in_page": 50,
              "global_api_total": 131822,
              "global_total_is_strategy_denominator": false,
              "not_discovered_from_acquired_page": 0,
              "observed_at": 1790223743.4534976,
              "one_wsol_pair_count": 50,
              "page": 2,
              "preflight_evaluated_in_page": 3,
              "raw_rows": 250,
              "sort": "volume_5m:desc"
            },
            {
              "discovered_in_page": 160,
              "global_api_total": 131822,
              "global_total_is_strategy_denominator": false,
              "not_discovered_from_acquired_page": 0,
              "observed_at": 1790223745.0118985,
              "one_wsol_pair_count": 160,
              "page": 1,
              "preflight_evaluated_in_page": 57,
              "raw_rows": 250,
              "sort": "volume_30m:desc"
            },
            {
              "discovered_in_page": 170,
              "global_api_total": 131822,
              "global_total_is_strategy_denominator": false,
              "not_discovered_from_acquired_page": 0,
              "observed_at": 1790223746.6482618,
              "one_wsol_pair_count": 170,
              "page": 2,
              "preflight_evaluated_in_page": 32,
              "raw_rows": 250,
              "sort": "volume_30m:desc"
            }
          ],
          "structurally_eligible_acquired_union_count": 2076,
          "target_structural_union_count": 2076,
          "undiscovered_in_acquired_structural_union": 0,
          "union_scope": "acquired ranking pages only; not the full strategy target universe",
          "unobserved_source_pages": []
        },
        "strategy_conformance": "pass",
        "structurally_eligible_count": null,
        "target_market_scope": {
          "authority": "SOLANA_DLMM_INDEPENDENT_V1.json; solana_dlmm_independent_v1 discovery loop",
          "denominator": "Full target-pair inventory is unknown. The bounded ranking-page union measures source acquisition only and does not redefine the target market.",
          "dimensions": [
            "quote_asset",
            "public_sort",
            "pool"
          ],
          "universe": "Nonblacklisted Solana Meteora DLMM pools with exactly one WSOL leg, as defined by the frozen strategy; no minimum TVL or absolute volume."
        },
        "target_market_universe_count": null,
        "upstream_acquisition": {
          "broader_source_rows_are_strategy_observations": false,
          "discovery_progress_at": 1790223743.4720619,
          "native_candidate_discovered_count": 2076,
          "native_funnel_stages": {
            "admitted": 56,
            "discovered": 2076,
            "economic_vector": 5,
            "evaluated": 5,
            "evidence_complete": 5,
            "evidence_requested": 56,
            "forward_observation": 18,
            "fresh_state": 18,
            "prospective_range": 5,
            "reconstruction_complete": 18,
            "reconstruction_started": 18,
            "rejected": 5,
            "screened": 108,
            "terminal": 108,
            "trigger_authenticated": 19,
            "trigger_observed": 19,
            "trigger_started": 23,
            "trigger_terminal": 23,
            "warmup_complete": 14,
            "warmup_started": 18
          }
        }
      },
      "durable_handoff": false,
      "durable_replay": true,
      "economics": {
        "block_return": 0.0,
        "capital_seconds": 0.0,
        "capital_time_complete": true,
        "deployed_return_per_capital_hour": null,
        "flat": true,
        "realized": 0,
        "return_per_observed_hour": 0.0,
        "sleeves": {},
        "starting_capital": 1000000000
      },
      "forced_settled": 0,
      "freshness_finality_unchanged": true,
      "identity_match": true,
      "infrastructure_censoring_fraction": 0.0,
      "native_accounting_replay": true,
      "natural_settled": 0,
      "policy_hash": "90c711e5e3e521fb79f93bc386af5a3067d0a30c83ae3407c550f70db581f966",
      "process_restarts": 0,
      "strategy_version": "solana-dlmm-independent-v2.0-profitability-fee-density-v1-core-hold-v2",
      "telemetry_complete": true,
      "unexpected_exit": false
    },
    "pons": {
      "accounting_reconciled": true,
      "assurance": {
        "accounting_reconciliation": {
          "accounting": {
            "available": 1000000000000000000,
            "booked_realized": 0,
            "capital_at_risk_unit_nanoseconds": 0,
            "capital_integral_complete": true,
            "cash": 1000000000000000000,
            "cash_basis_conservation": true,
            "conservation": true,
            "genesis": 1000000000000000000,
            "namespace": "pons-selective-continuation-v1",
            "native_execution_cost": 0,
            "native_observation_complete": true,
            "policy_hash": "19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84",
            "positions": 0,
            "realized": 0,
            "remaining_cost_basis": 0,
            "reserved": 0,
            "unobserved_native_positions": [],
            "unsettled": 0
          },
          "lane": "pons",
          "open_positions": 0,
          "read_only": true,
          "settlement_inferred": false,
          "verified": true
        },
        "acquisition_latency_seconds": {
          "discovered__screened": {
            "count": 693,
            "max": 0.002372264862060547,
            "p50": 0.0006923675537109375,
            "p95": 0.0010886192321777344
          },
          "evidence_complete__qualified": {
            "count": 0,
            "max": null,
            "p50": null,
            "p95": null
          },
          "evidence_requested__evidence_complete": {
            "count": 0,
            "max": null,
            "p50": null,
            "p95": null
          },
          "screened__evidence_requested": {
            "count": 86,
            "max": 3.0259344577789307,
            "p50": 0.574256420135498,
            "p95": 1.7396152019500732
          }
        },
        "admission_failures": [],
        "authorized_count": 0,
        "behavioral_liveness": {
          "classification": "awaiting_market_or_policy",
          "discovery_breadth_healthy": "coverage_degraded",
          "evidence_progressing": null,
          "position_monitoring_progressing": null,
          "process_alive": false,
          "provider_alive": true,
          "qualification_progressing": null,
          "settlement_progressing": null,
          "strategy_progressing": 1790223864.268943,
          "target_market_discovery_progressing": null
        },
        "candidates_requiring_full_evidence": null,
        "complete_natural_lifecycles": 0,
        "conformance_unavailable": [],
        "coverage_gaps": [
          "provider_failed",
          "reconstruction_incomplete"
        ],
        "coverage_gaps_by_segment": [
          {
            "segment": {
              "segment": "not_preserved"
            },
            "transition_records": 240
          }
        ],
        "coverage_health": "coverage_degraded",
        "current_open_positions": 0,
        "current_strategy_phase": "rejected",
        "decision_replay_checked": 0,
        "decision_replay_failures": [],
        "discovered_count": null,
        "discovered_too_late": 1,
        "discovery_coverage": null,
        "economic_admission": "eligible_subject_to_frozen_block_gate",
        "evidence_attempt_coverage": null,
        "evidence_completion_coverage": null,
        "full_evidence_attempted": 86,
        "full_evidence_completed": null,
        "infrastructure_censoring": {
          "classifications": {
            "provider_failed": 1,
            "reconstruction_incomplete": 239,
            "stale_before_evidence": 1,
            "strategy_rejection": 452
          },
          "frozen_policy": "profitability_protocol.json; prospective_acceptance._infra_fraction",
          "overlapping_counts": true
        },
        "last_strategy_progress_at": 1790223864.268943,
        "last_valid_block": null,
        "native_position_records_open": 0,
        "native_unsettled_records": 0,
        "natural_entries": 0,
        "natural_lifecycle": {
          "complete_natural_lifecycle_observed": false,
          "machinery_certified": "separate_exact_sha_certificate",
          "natural_entry_observed": false,
          "natural_exit_observed": false,
          "natural_monitoring_observed": false,
          "natural_partial_realization_observed_if_strategy_triggers_it": false,
          "natural_settlement_observed": false,
          "target_market_coverage_observed": "coverage_degraded"
        },
        "natural_settlements": 0,
        "never_discovered": null,
        "observed_market_count_scope": "strategy_target_only",
        "observed_market_count_status": "unknown_scope_membership",
        "oldest_open_position_age": null,
        "position_watchdog": {
          "status": "pass",
          "violations": []
        },
        "positions_spanning_blocks": 0,
        "preflight_coverage": null,
        "preflight_evaluated_count": null,
        "provider_health": {
          "errors": {
            "eth_getLogs:http_429": 20,
            "provider_http_429": 20,
            "provider_rpc_3": 1
          },
          "requests": 6264,
          "rpc_latency_seconds": {
            "p50": 0.037858544,
            "p95": 0.341123801,
            "p99": 0.776508274
          }
        },
        "qualified_count": null,
        "queue_saturation": {
          "classified_candidates": {
            "capacity_censored": 0,
            "consumer_deadline": 0,
            "local_budget_exhausted": 0
          },
          "maximum_concurrent_evaluations": null,
          "queue_time_at_capacity_seconds": null
        },
        "strategy_conformance": "pass",
        "structurally_eligible_count": null,
        "target_market_scope": {
          "authority": "pons_selective_cohort.operational_configuration; pons_selective_continuation.POLICY",
          "denominator": "Canonical discovery cursor/log windows; independent all-event denominator unavailable.",
          "dimensions": [
            "curve",
            "graduation_state",
            "event_at"
          ],
          "universe": "Native-quote Pons curves in the frozen 50-85% progress, 120-600s age and 20-90s graduation-ETA domain, plus its authenticated graduation/re-entry modes; existing positions retain their lifecycle scope."
        },
        "target_market_universe_count": null,
        "upstream_acquisition": {
          "broader_source_rows_are_strategy_observations": false,
          "discovery_progress_at": 1790223863.8971958,
          "native_candidate_discovered_count": 2056,
          "native_funnel_stages": {
            "admitted": 86,
            "current_state_complete": 452,
            "current_state_queued": 693,
            "current_state_requested": 692,
            "discovered": 2056,
            "evidence_requested": 86,
            "prospect_admitted": 86,
            "prospect_screened": 452,
            "rejected": 452,
            "screened": 693,
            "terminal": 241
          }
        }
      },
      "durable_handoff": false,
      "durable_replay": true,
      "economics": {
        "block_return": 0.0,
        "capital_seconds": 0.0,
        "capital_time_complete": true,
        "deployed_return_per_capital_hour": null,
        "flat": true,
        "realized": 0,
        "return_per_observed_hour": 0.0,
        "sleeves": {},
        "starting_capital": 1000000000000000000
      },
      "forced_settled": 0,
      "freshness_finality_unchanged": true,
      "identity_match": true,
      "infrastructure_censoring_fraction": 0.011627906976744186,
      "native_accounting_replay": true,
      "natural_settled": 0,
      "policy_hash": "19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84",
      "process_restarts": 0,
      "strategy_version": "pons-selective-continuation-v1/profitability-v1-profit-protection-v2",
      "telemetry_complete": true,
      "unexpected_exit": false
    },
    "pump": {
      "accounting_reconciled": true,
      "assurance": {
        "accounting_reconciliation": {
          "accounting": {
            "basis": 0,
            "capital_hour_denominator": 3600,
            "capital_unit_seconds": 0,
            "cash": 5110384300,
            "initial": 5110384300,
            "lane": "pump-acceleration-independent-v1",
            "marked_equity": 5110384300,
            "open_positions": 0,
            "pending": 0,
            "policy_hash": "b7718de9298e4c825616bed26c87731a65f43c4b12f152b14e1d574eb86eb8d5",
            "realized": 0,
            "reconciled": true,
            "reserved": 0,
            "run_id": "9225f7e0-b77b-429a-be23-cdd10a334980",
            "settled": 0,
            "unrealized": 0
          },
          "accounting_replay": {
            "cash": 5110384300,
            "events": 0,
            "final_hash": "0000000000000000000000000000000000000000000000000000000000000000",
            "verified": true
          },
          "lane": "pump",
          "open_positions": 0,
          "read_only": true,
          "settlement_inferred": false,
          "verified": true
        },
        "acquisition_latency_seconds": {
          "discovered__screened": {
            "count": 0,
            "max": null,
            "p50": null,
            "p95": null
          },
          "evidence_complete__qualified": {
            "count": 0,
            "max": null,
            "p50": null,
            "p95": null
          },
          "evidence_requested__evidence_complete": {
            "count": 1,
            "max": 72.62018966674805,
            "p50": 72.62018966674805,
            "p95": 72.62018966674805
          },
          "screened__evidence_requested": {
            "count": 0,
            "max": null,
            "p50": null,
            "p95": null
          }
        },
        "admission_failures": [],
        "authorized_count": 0,
        "behavioral_liveness": {
          "classification": "awaiting_market_or_policy",
          "discovery_breadth_healthy": "coverage_degraded",
          "evidence_progressing": 1790223518.091707,
          "position_monitoring_progressing": null,
          "process_alive": false,
          "provider_alive": true,
          "qualification_progressing": 1790223793.1375527,
          "settlement_progressing": null,
          "strategy_progressing": 1790224796.1815042,
          "target_market_discovery_progressing": null
        },
        "candidates_requiring_full_evidence": null,
        "complete_natural_lifecycles": 0,
        "conformance_unavailable": [],
        "coverage_gaps": [
          "reconstruction_incomplete",
          "stream_coverage_loss"
        ],
        "coverage_gaps_by_segment": [
          {
            "segment": {
              "mode": "post_graduation_momentum"
            },
            "transition_records": 261
          },
          {
            "segment": {
              "mode": "late_curve_acceleration"
            },
            "transition_records": 159
          },
          {
            "segment": {
              "mode": "pumpswap_second_leg"
            },
            "transition_records": 85
          },
          {
            "segment": {
              "segment": "not_preserved"
            },
            "transition_records": 32
          }
        ],
        "coverage_health": "coverage_degraded",
        "current_open_positions": 0,
        "current_strategy_phase": "discovered",
        "decision_replay_checked": 846,
        "decision_replay_failures": [],
        "discovered_count": null,
        "discovered_too_late": null,
        "discovery_coverage": null,
        "economic_admission": "eligible_subject_to_frozen_block_gate",
        "evidence_attempt_coverage": null,
        "evidence_completion_coverage": 0.04,
        "full_evidence_attempted": 25,
        "full_evidence_completed": 1,
        "infrastructure_censoring": {
          "classifications": {
            "reconstruction_incomplete": 55,
            "strategy_rejection": 53
          },
          "frozen_policy": "profitability_protocol.json; prospective_acceptance._infra_fraction",
          "overlapping_counts": true
        },
        "last_strategy_progress_at": 1790224796.1815042,
        "last_valid_block": null,
        "native_position_records_open": 0,
        "native_unsettled_records": 0,
        "natural_entries": 0,
        "natural_lifecycle": {
          "complete_natural_lifecycle_observed": false,
          "machinery_certified": "separate_exact_sha_certificate",
          "natural_entry_observed": false,
          "natural_exit_observed": false,
          "natural_monitoring_observed": false,
          "natural_partial_realization_observed_if_strategy_triggers_it": false,
          "natural_settlement_observed": false,
          "target_market_coverage_observed": "coverage_degraded"
        },
        "natural_settlements": 0,
        "never_discovered": null,
        "observed_market_count_scope": "strategy_target_only",
        "observed_market_count_status": "unknown_scope_membership",
        "oldest_open_position_age": null,
        "position_watchdog": {
          "status": "pass",
          "violations": []
        },
        "positions_spanning_blocks": 0,
        "preflight_coverage": null,
        "preflight_evaluated_count": null,
        "provider_health": {
          "errors": {
            "certification_provider_queue_deadline": 4
          },
          "requests": 5799,
          "rpc_latency_seconds": {
            "p50": 0.104760366,
            "p95": 0.159406943,
            "p99": 0.177577226
          }
        },
        "qualified_count": null,
        "queue_saturation": {
          "classified_candidates": {
            "capacity_censored": 0,
            "consumer_deadline": 0,
            "local_budget_exhausted": 0
          },
          "maximum_concurrent_evaluations": null,
          "queue_time_at_capacity_seconds": null
        },
        "strategy_conformance": "pass",
        "structurally_eligible_count": null,
        "target_market_scope": {
          "authority": "sources.json:lanes.pump.prospect_admission; pump_acceleration_strategy.POLICY",
          "denominator": "Source stream completeness; absolute chain opportunity census unavailable.",
          "dimensions": [
            "surface",
            "phase",
            "quote_asset"
          ],
          "universe": "Native-SOL Pump curves in the frozen 60-85% late-curve strategy domain, plus its authenticated PumpSwap graduation/continuation modes; existing positions retain their lifecycle scope."
        },
        "target_market_universe_count": null,
        "upstream_acquisition": {
          "broader_source_rows_are_strategy_observations": false,
          "discovery_progress_at": 1790224796.1815042,
          "native_candidate_discovered_count": 1290,
          "native_funnel_stages": {
            "admitted": 25,
            "discovered": 1290,
            "evaluated": 20,
            "evidence_complete": 1,
            "evidence_requested": 25,
            "prospect_incomplete": 25,
            "prospect_observed": 64,
            "prospect_screened": 53,
            "rejected": 20,
            "terminal": 32
          }
        }
      },
      "durable_handoff": false,
      "durable_replay": true,
      "economics": {
        "block_return": 0.0,
        "capital_seconds": 0,
        "capital_time_complete": true,
        "deployed_return_per_capital_hour": null,
        "flat": true,
        "realized": 0,
        "return_per_observed_hour": 0.0,
        "sleeves": {},
        "starting_capital": 5110384300
      },
      "forced_settled": 0,
      "freshness_finality_unchanged": true,
      "identity_match": true,
      "infrastructure_censoring_fraction": 0.0,
      "native_accounting_replay": true,
      "natural_settled": 0,
      "policy_hash": "b7718de9298e4c825616bed26c87731a65f43c4b12f152b14e1d574eb86eb8d5",
      "process_restarts": 0,
      "strategy_version": "pump-acceleration-independent-v1/profitability-v1-profit-protection-v2",
      "telemetry_complete": true,
      "unexpected_exit": false
    },
    "ramses": {
      "accounting_reconciled": true,
      "assurance": {
        "accounting_reconciliation": {
          "accounting": {
            "allocation_authority": false,
            "by_quote_asset": {},
            "conservation": true,
            "funding_state": "awaiting_first_qualified_pinned_screen",
            "open_positions": 0,
            "paper_entry_ready": false,
            "policy_hash": "bf75a70fcdf68cf231dd354eab7cb56879bc4c16184553db5c121ea0fdc5d4ef",
            "position_count": 0,
            "unlike_quote_units_summed": false
          },
          "lane": "ramses",
          "open_positions": 0,
          "read_only": true,
          "settlement_inferred": false,
          "verified": true
        },
        "acquisition_latency_seconds": {
          "discovered__screened": {
            "count": 7,
            "max": 0.0006024837493896484,
            "p50": 0.00032591819763183594,
            "p95": 0.0004723072052001953
          },
          "evidence_complete__qualified": {
            "count": 0,
            "max": null,
            "p50": null,
            "p95": null
          },
          "evidence_requested__evidence_complete": {
            "count": 0,
            "max": null,
            "p50": null,
            "p95": null
          },
          "screened__evidence_requested": {
            "count": 7,
            "max": 0.0012297630310058594,
            "p50": 0.0007030963897705078,
            "p95": 0.0009005069732666016
          }
        },
        "admission_failures": [],
        "authorized_count": 0,
        "behavioral_liveness": {
          "classification": "awaiting_market_or_policy",
          "discovery_breadth_healthy": "coverage_degraded",
          "evidence_progressing": null,
          "position_monitoring_progressing": null,
          "process_alive": false,
          "provider_alive": true,
          "qualification_progressing": 1790223855.01962,
          "settlement_progressing": null,
          "strategy_progressing": 1790223855.0199795,
          "target_market_discovery_progressing": 1790223855.0181556
        },
        "candidates_requiring_full_evidence": null,
        "complete_natural_lifecycles": 0,
        "conformance_unavailable": [],
        "coverage_gaps": [
          "reconstruction_incomplete"
        ],
        "coverage_gaps_by_segment": [
          {
            "segment": {
              "segment": "not_preserved"
            },
            "transition_records": 17
          }
        ],
        "coverage_health": "coverage_degraded",
        "current_open_positions": 0,
        "current_strategy_phase": "rejected",
        "decision_replay_checked": 17,
        "decision_replay_failures": [],
        "discovered_count": 7,
        "discovered_too_late": null,
        "discovery_coverage": 2.3333333333333335,
        "economic_admission": "eligible_subject_to_frozen_block_gate",
        "evidence_attempt_coverage": null,
        "evidence_completion_coverage": null,
        "full_evidence_attempted": 7,
        "full_evidence_completed": null,
        "infrastructure_censoring": {
          "classifications": {
            "reconstruction_incomplete": 7
          },
          "frozen_policy": "profitability_protocol.json; prospective_acceptance._infra_fraction",
          "overlapping_counts": true
        },
        "last_strategy_progress_at": 1790223855.0199795,
        "last_valid_block": null,
        "native_position_records_open": 0,
        "native_unsettled_records": 0,
        "natural_entries": 0,
        "natural_lifecycle": {
          "complete_natural_lifecycle_observed": false,
          "machinery_certified": "separate_exact_sha_certificate",
          "natural_entry_observed": false,
          "natural_exit_observed": false,
          "natural_monitoring_observed": false,
          "natural_partial_realization_observed_if_strategy_triggers_it": false,
          "natural_settlement_observed": false,
          "target_market_coverage_observed": "coverage_degraded"
        },
        "natural_settlements": 0,
        "never_discovered": null,
        "observed_market_count_scope": "strategy_target_only",
        "observed_market_count_status": "target_candidates_observed",
        "oldest_open_position_age": null,
        "position_watchdog": {
          "status": "pass",
          "violations": []
        },
        "positions_spanning_blocks": 0,
        "preflight_coverage": 1.0,
        "preflight_evaluated_count": 7,
        "provider_health": {
          "errors": {
            "eth_getBlockByNumber:http_429": 3,
            "eth_getLogs:http_429": 2,
            "provider_http_429": 5
          },
          "requests": 1421,
          "rpc_latency_seconds": {
            "p50": 0.345347668,
            "p95": 0.766744275,
            "p99": 0.776553933
          }
        },
        "qualified_count": null,
        "queue_saturation": {
          "classified_candidates": {
            "capacity_censored": 0,
            "consumer_deadline": 0,
            "local_budget_exhausted": 0
          },
          "maximum_concurrent_evaluations": null,
          "queue_time_at_capacity_seconds": null
        },
        "strategy_conformance": "pass",
        "structurally_eligible_count": 3,
        "target_market_scope": {
          "authority": "ramses_universe.scan; ramses_strategy.POLICY",
          "denominator": "Authenticated USDG subset of the complete quiet-entry pool cohort; the broad factory inventory is acquisition overhead.",
          "dimensions": [
            "quote_asset",
            "swap_count",
            "bin_depth"
          ],
          "universe": "Recently active Ramses USDG pools with one or two prior 30-minute swaps, as frozen in sources.json; existing positions retain their lifecycle scope."
        },
        "target_market_universe_count": 3,
        "upstream_acquisition": {
          "broader_source_rows_are_strategy_observations": false,
          "discovery_progress_at": 1790223855.0181556,
          "factory_inventory_count": 288,
          "known_target_candidates": 3,
          "native_candidate_discovered_count": 7,
          "native_funnel_stages": {
            "admitted": 7,
            "discovered": 7,
            "evaluated": 7,
            "evidence_requested": 7,
            "rejected": 7,
            "screened": 7
          },
          "quiet_activity_candidates": 3,
          "scope_exclusions": {}
        }
      },
      "durable_handoff": false,
      "durable_replay": true,
      "economics": {
        "block_return": 0.0,
        "capital_seconds": null,
        "capital_time_complete": true,
        "deployed_return_per_capital_hour": null,
        "flat": true,
        "realized": null,
        "return_per_observed_hour": 0.0,
        "sleeves": {},
        "starting_capital": null
      },
      "forced_settled": 0,
      "freshness_finality_unchanged": true,
      "identity_match": true,
      "infrastructure_censoring_fraction": 0.0,
      "native_accounting_replay": true,
      "natural_settled": 0,
      "policy_hash": "bf75a70fcdf68cf231dd354eab7cb56879bc4c16184553db5c121ea0fdc5d4ef",
      "process_restarts": 0,
      "strategy_version": "ramses-active-wide-maker-v3",
      "telemetry_complete": true,
      "unexpected_exit": false
    }
  },
  "last_completed_action": {
    "at": 1790224960.7465014,
    "event_id": "35949285193:1:prospective-observation.json",
    "native_run_id": "9225f7e0-b77b-429a-be23-cdd10a334980",
    "record_sha256": "e799393ef2d8307d1893ae90585544cfc24cad10544a2251c19ce2e0997c8988"
  },
  "latest_certification_run": 35948638345,
  "latest_market_run": 35949285193,
  "machinery_certified_by_lane": {
    "meteora": true,
    "pons": true,
    "pump": true,
    "ramses": true
  },
  "market_observation_validity": {
    "meteora": "coverage_degraded",
    "pons": "coverage_degraded",
    "pump": "coverage_degraded",
    "ramses": "coverage_degraded"
  },
  "material_lane_coverage_gaps": {
    "meteora": [
      "reconstruction_incomplete",
      "stream_coverage_loss",
      "discovered_candidates_pending_at_observation_close"
    ],
    "pons": [
      "provider_failed",
      "reconstruction_incomplete"
    ],
    "pump": [
      "reconstruction_incomplete",
      "stream_coverage_loss"
    ],
    "ramses": [
      "reconstruction_incomplete"
    ]
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
  "next_action": "dispatch_next_frozen_block",
  "observation_hours": {
    "meteora": 1.0004936206575,
    "pons": 1.0004936206575,
    "pump": 1.0004936206575,
    "ramses": 1.0004936206575
  },
  "operational_limit": {
    "maximum_blocks": 192,
    "maximum_calendar_hours": 336
  },
  "operational_validity": {
    "accepted_blocks": 1,
    "accepted_observation_hours": 1.0004936206575,
    "censored_blocks": 0,
    "cohort_age_hours": 1.7895736728111904,
    "observed_hours": 1.0004936206575
  },
  "portfolio_reconciliation": {
    "all_lane_ledgers_reconciled": true,
    "native_quote_units_are_never_summed": true,
    "normalized_portfolio": {
      "calendar_span_hours": 1.2838006923596064,
      "checks": {
        "all_lanes_economic_pass": false,
        "calendar_span": false,
        "complete_blocks": false,
        "correlation_sample_and_limit": false,
        "drawdown": true,
        "lower95_hourly_return_positive": false,
        "profit_factor": false,
        "worst_block": true
      },
      "complete_blocks": 1,
      "correlations": {
        "meteora__pons": {
          "correlation": null,
          "joint_nonzero_blocks": 0,
          "status": "INCOMPLETE"
        },
        "meteora__ramses": {
          "correlation": null,
          "joint_nonzero_blocks": 0,
          "status": "INCOMPLETE"
        },
        "pons__ramses": {
          "correlation": null,
          "joint_nonzero_blocks": 0,
          "status": "INCOMPLETE"
        },
        "pump__meteora": {
          "correlation": null,
          "joint_nonzero_blocks": 0,
          "status": "INCOMPLETE"
        },
        "pump__pons": {
          "correlation": null,
          "joint_nonzero_blocks": 0,
          "status": "INCOMPLETE"
        },
        "pump__ramses": {
          "correlation": null,
          "joint_nonzero_blocks": 0,
          "status": "INCOMPLETE"
        }
      },
      "lower95_return_per_hour": null,
      "max_drawdown": 0.0,
      "mean_return_per_hour": 0.0,
      "profit_factor_value": null,
      "status": "INCOMPLETE"
    }
  },
  "prospective_sha": "1c6da29d08bfbe42e39ea1c8068933aae6b15cdb",
  "realized_and_unrealized_by_lane": {
    "meteora": {
      "realized": 0,
      "units": "lamports",
      "unrealized": 0,
      "unrealized_status": "available"
    },
    "pons": {
      "realized": 0,
      "units": "native_quote_raw",
      "unrealized": null,
      "unrealized_status": "not_marked_by_native_ledger"
    },
    "pump": {
      "realized": 0,
      "units": "lamports",
      "unrealized": 0,
      "unrealized_status": "available"
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
  "updated_at": 1790224960.748984
}
```
