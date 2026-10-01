# Predecessor → v2 gate map

Source authority: exact reachable `dc08f9064cf5e37b63f383f52aa709d0afc1723f`. No unavailable native v1 bytes are inferred.

| Predecessor gate | Class | Successor | Execution | Purpose / proof |
|---|---|---|---|---|
| exact_source_offline | RETAINED | exact_source_offline-v2 | future-canonical | exact source offline |
| native_crash_matrix | RETAINED | native_crash_matrix-v2 | future-canonical | native crash matrix |
| restart_safety | RETAINED | restart_safety-v2 | future-canonical | restart safety |
| integrated_current_policy | RETAINED | integrated_current_policy-v2 | future-canonical | integrated current policy |
| historical_exposure_resolution | RETAINED | historical_exposure_resolution-v2 | future-canonical | historical exposure resolution |
| historical_registry_released | RETAINED | historical_registry_released-v2 | future-canonical | historical registry released |
| resource_bounds | RETAINED | resource_bounds-v2 | future-canonical | resource bounds |
| mature_solana_pressure | RETAINED | mature_solana_pressure-v2 | future-canonical | mature solana pressure |
| combined_mature_solana_pressure | RETAINED | combined_mature_solana_pressure-v2 | future-canonical | combined mature solana pressure |
| joined_eight_day_system | RETAINED | joined_eight_day_system-v2 | future-canonical | joined eight day system |
| exact_integration_identity | RETAINED | exact_integration_identity-v2 | future-canonical | exact integration identity |
| six_regime_integration | RETAINED | six_regime_integration-v2 | future-canonical | six regime integration |
| preserved_production_adapter_contracts | RETAINED | preserved_production_adapter_contracts-v2 | future-canonical | preserved production adapter contracts |
| bounded_preserved_validation | RETAINED | bounded_preserved_validation-v2 | future-canonical | bounded preserved validation |
| cohort-complete | RETAINED | cohort-complete-v2 | future-canonical | all combined-1/2/3 and recovery-1; all attempts retained |
| source-shape | RETAINED | source-shape-v2 | future-canonical | 2223 frames x3 and 4445 recovery at .27s |
| pressure-profile | RETAINED | pressure-profile-v2 | future-canonical | owner .165/frame; archive .36/thousand; commit .006; original seeds |
| burst-schedule | RETAINED | burst-schedule-v2 | future-canonical | 216/378 source seconds; frame 800/1400 pauses 8s |
| recovery | RETAINED | recovery-v2 | future-canonical | 120 source seconds; envelope1000; decline256; trend256 |
| fixed-old-cohort | RETAINED | fixed-old-cohort-v2 | future-canonical | frozen cutoff cohort clears during source advance |
| debt-tails | RETAINED | debt-tails-v2 | future-canonical | 30 advancing samples; >=3 each burst window; >=10 tail halves |
| frame-byte-bounds | RETAINED | frame-byte-bounds-v2 | future-canonical | dispatch peak16..64; bytes<=96MiB; commit2..8; bytes<=16MiB |
| candidate-progress | RETAINED | candidate-progress-v2 | future-canonical | candidate checks>1; archive records verified>0 |
| urgent-source-fairness | RETAINED | urgent-source-fairness-v2 | future-canonical | 10 urgent acks; zero urgent errors; source order; all 3 scopes progress |
| checkpoint-completion | REPLACED_BY_STRONGER | checkpoint-completion-v2 | held-reader | Establish snapshot read before writer commit; native blocking and finish after release. |
| integrity-resources | RETAINED | integrity-resources-v2 | future-canonical | zero corruption; db/wal/rss/filesystem bounds; hot<2GiB |
| provider-isolation | REPLACED_BY_STRONGER | provider-isolation-v2 | future-canonical | Count attempted access before network; reject any attempt. |
| joint-lifecycle | REPLACED_BY_STRONGER | joint-lifecycle-v2 | future-canonical | hot eligibility and archived-pending debt for all scopes with v2 commit/origin/clock binding; equality and stale evidence fail. |
| native-archive | REPLACED_BY_STRONGER | native-archive-v2 | native-transitions | actual committed native hot-to-archive service with v2 commit/origin/clock binding; equality and stale evidence fail. |
| native-retirement | REPLACED_BY_STRONGER | native-retirement-v2 | native-transitions | committed native retirement and maintenance ledger; same transaction floor allowed with v2 commit/origin/clock binding; equality and stale evidence fail. |
| residence | REPLACED_BY_STRONGER | residence-v2 | future-canonical | hot and retained strictly <240; source lag<45 with v2 commit/origin/clock binding; equality and stale evidence fail. |
| observer | REPLACED_BY_STRONGER | observer-v2 | future-canonical | fresh exact-candidate raw paired measurements, strict <.01 with v2 commit/origin/clock binding; equality and stale evidence fail. |
| run373 | REPLACED_BY_STRONGER | run373-v2 | run373-full | New immutable clock declaration, coherent preconstructed native economics, original full workload retained; genuinely stale events fail. |
| run379 | REPLACED_BY_STRONGER | run379-v2 | run379-full | New immutable clock declaration, coherent preconstructed native economics, original full workload retained; genuinely stale events fail. |
| run380 | REPLACED_BY_STRONGER | run380-v2 | run380-full | New immutable clock declaration, coherent preconstructed native economics, original full workload retained; genuinely stale events fail. |
| prepared-source | REPLACED_BY_STRONGER | prepared-source-v2 | prepared-assembly | all 4 exact composed lanes; original overlays/policies; complete immutable assembly manifest, in-process origins and before/after integrity required. |
| prepared-import-collection | REPLACED_BY_STRONGER | prepared-import-collection-v2 | prepared-assembly | all actual modules and tests from prepared assemblies; complete immutable assembly manifest, in-process origins and before/after integrity required. |
| protocol-freeze | REPLACED_BY_STRONGER | protocol-freeze-v2 | prepared-assembly | original policies and protocol hashes unchanged; complete immutable assembly manifest, in-process origins and before/after integrity required. |
| same-sha | REPLACED_BY_STRONGER | same-sha-v2 | preflight | S2!=S rejected even equal trees; complete immutable assembly manifest, in-process origins and before/after integrity required. |
| artifact-provenance | REPLACED_BY_STRONGER | artifact-provenance-v2 | prepared-assembly | exact raw artifact IDs/digests/run/attempt; reread after fetch; complete immutable assembly manifest, in-process origins and before/after integrity required. |
| workflow-identity | REPLACED_BY_STRONGER | workflow-identity-v2 | preflight | workflow and reusable resolve to exact candidate S; complete immutable assembly manifest, in-process origins and before/after integrity required. |
| assembly-origin | REPLACED_BY_STRONGER | assembly-origin-v2 | preflight | same assembly preflight and native trials; child/local dynamic origins checked; complete immutable assembly manifest, in-process origins and before/after integrity required. |
| generation-fencing | REPLACED_BY_STRONGER | generation-fencing-v2 | generation-restart | Native generation rejection plus raw cross-generation/artifact checks. |
| restart-accounting | REPLACED_BY_STRONGER | restart-accounting-v2 | m1-completion | Finite native receipt/retirement continuation and M1 completion regression must pass on eventual exact candidate. |
