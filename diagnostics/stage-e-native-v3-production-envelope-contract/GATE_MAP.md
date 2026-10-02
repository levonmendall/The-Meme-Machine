# Stage-E native v2 → v3 gate map

Authority: exact candidate `7a516a6a92be9347661ac0e7f560971c171a0931` / tree `9da7d1e1625ba04c1437c63606c90f5e293bdba7`. Every one of the 44 required v2 gates is mapped. PAPER ONLY; no execution acceptance earned.

| v2 gate | v3 gate | Treatment | Exact acceptance delta / preservation |
|---|---|---|---|
| exact_source_offline-v2 | exact_source_offline-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| native_crash_matrix-v2 | native_crash_matrix-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| restart_safety-v2 | restart_safety-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| integrated_current_policy-v2 | integrated_current_policy-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| historical_exposure_resolution-v2 | historical_exposure_resolution-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| historical_registry_released-v2 | historical_registry_released-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| resource_bounds-v2 | resource_bounds-v3 | STRENGTHENED_BINDING | Retain predecessor native resource/RSS bounds plus exact declared allocation, ancestor quota/affinity/RAM/isolation/headroom/runtime bindings. >2 executor fails A/B. |
| mature_solana_pressure-v2 | mature_solana_pressure-v3 | SPLIT_CAPACITY_AND_STRESS | All mature capacity members on exact two-vCPU/eight-GiB envelope without synthetic floors; original run381 profile separately retained in C. |
| combined_mature_solana_pressure-v2 | combined_mature_solana_pressure-v3 | SPLIT_CAPACITY_AND_STRESS | Native production work in A/B; two pauses/readers/tail interference and original coverage predicates retained in C. |
| joined_eight_day_system-v2 | joined_eight_day_system-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| exact_integration_identity-v2 | exact_integration_identity-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| six_regime_integration-v2 | six_regime_integration-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| preserved_production_adapter_contracts-v2 | preserved_production_adapter_contracts-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| bounded_preserved_validation-v2 | bounded_preserved_validation-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| cohort-complete-v2 | cohort-complete-v3 | SEPARATED_COHORTS | All four capacity members required; all six observer trials/three valid pairs required; all stress members/failed attempts preserved, with overload safely terminal rather than capacity credit. |
| source-shape-v2 | source-shape-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| pressure-profile-v2 | pressure-profile-v3 | SPLIT_NATIVE_AND_SYNTHETIC | A/B floors zero; unmodified native work. C exact owner/archive/changed-COMMIT sleep profile. No new hardware-minimum inference. |
| burst-schedule-v2 | burst-schedule-v3 | MOVED_ADVERSARIAL_INJECTION | Exact pause frames800/1400,8 seconds,216/378 source seconds retained in C. A/B original fixed clocks/cadence without deliberately injected outages. |
| recovery-v2 | recovery-v3 | SPLIT_PERFORMANCE_AND_SAFETY | Exact120-second/1000/256/256 recovery and latched native origin retained. Original burst recovery predicates reported in C. A/B no-pin age/progress cannot be waived. Overload safety requires unchanged native refusal/restart/pins. |
| fixed-old-cohort-v2 | fixed-old-cohort-v3 | RETAINED_IN_STRESS | Exact frozen old-slot cutoff/cohort and clearance during advancing source retained in C full-profile diagnostic and native bounded recovery obligations; never relabel failed cleanup as passed. |
| debt-tails-v2 | debt-tails-v3 | RETAINED_IN_STRESS | Exact5-second/30 advancing/>=3 windows/>=10 tail halves and debt inequalities retained in C; A/B preserve residence and committed maintenance progress on real production-equivalent input. |
| frame-byte-bounds-v2 | frame-byte-bounds-v3 | SPLIT_SAFETY_AND_COVERAGE | A/B dispatch1..64 and commits1..8 with original byte maxima; C retains dispatch16..64, commit2..8 and backpressure coverage. Lower bounds only exercise synthetic queue/batching, never tighten production minimum CPU. |
| candidate-progress-v2 | candidate-progress-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| urgent-source-fairness-v2 | urgent-source-fairness-v3 | SPLIT_NATIVE_AND_INTERFERENCE | >=10 real urgent ACKs, zero errors, source order and all-scope native progress retained in A/B/C; durable reader-overlap stress witnesses retained in C. |
| checkpoint-completion-v2 | checkpoint-completion-v3 | RETAINED_UNCHANGED | Establish snapshot read before writer commit; native blocking and finish after release. |
| integrity-resources-v2 | integrity-resources-v3 | RETAINED_UNCHANGED | Exact immutable predecessor semantics retained; fresh same-SHA assembled evidence required. |
| provider-isolation-v2 | provider-isolation-v3 | RETAINED_UNCHANGED | Count attempted access before network; reject any attempt. |
| joint-lifecycle-v2 | joint-lifecycle-v3 | SPLIT_CAPACITY_OBSERVATION_AND_STRESS | Retain native committed archive/retirement/generation/floor/pin bounds, strict ages and all-scope progress. Original burst/debt sampling/assessment in C and read-only qualification costs in B. No stage credit from missing baseline observation. |
| native-archive-v2 | native-archive-v3 | RETAINED_UNCHANGED | actual committed native hot-to-archive service with v2 commit/origin/clock binding; equality and stale evidence fail. |
| native-retirement-v2 | native-retirement-v3 | RETAINED_UNCHANGED | committed native retirement and maintenance ledger; same transaction floor allowed with v2 commit/origin/clock binding; equality and stale evidence fail. |
| residence-v2 | residence-v3 | RETAINED_UNCHANGED | hot and retained strictly <240; source lag<45 with v2 commit/origin/clock binding; equality and stale evidence fail. |
| observer-v2 | observer-v3 | RESOURCE_BOUND_SUCCESSOR | Three fixed-order pairs; no retries/replacements/warmups; exact equal work/resource/clock boundaries; native verification; original integer estimator and strict<1%; prerequisite A PASS; new namespace, old INVALID_PAIR sealed. |
| run373-v2 | run373-v3 | RETAINED_UNCHANGED | New immutable clock declaration, coherent preconstructed native economics, original full workload retained; genuinely stale events fail. |
| run379-v2 | run379-v3 | RETAINED_UNCHANGED | New immutable clock declaration, coherent preconstructed native economics, original full workload retained; genuinely stale events fail. |
| run380-v2 | run380-v3 | RETAINED_UNCHANGED | New immutable clock declaration, coherent preconstructed native economics, original full workload retained; genuinely stale events fail. |
| prepared-source-v2 | prepared-source-v3 | RETAINED_UNCHANGED | all 4 exact composed lanes; original overlays/policies; complete immutable assembly manifest, in-process origins and before/after integrity required. |
| prepared-import-collection-v2 | prepared-import-collection-v3 | RETAINED_UNCHANGED | all actual modules and tests from prepared assemblies; complete immutable assembly manifest, in-process origins and before/after integrity required. |
| protocol-freeze-v2 | protocol-freeze-v3 | RETAINED_UNCHANGED | original policies and protocol hashes unchanged; complete immutable assembly manifest, in-process origins and before/after integrity required. |
| same-sha-v2 | same-sha-v3 | RETAINED_UNCHANGED | S2!=S rejected even equal trees; complete immutable assembly manifest, in-process origins and before/after integrity required. |
| artifact-provenance-v2 | artifact-provenance-v3 | APPEND_ONLY_SUCCESSOR_PROVENANCE | Retain first-attempt raw IDs/hashes/run/attempt, reread receipt and immutable failures. New v3 namespace rejects all historical slot IDs and measurements; v2 evidence read-only. |
| workflow-identity-v2 | workflow-identity-v3 | SEPARATE_CANDIDATE_AND_EXTERNAL_CONTRACT | Candidate source origins remain exact S/T. Existing deterministic v2 workflow hashes unchanged. Future v3 external harness/control workflow has separate exact immutable identity and reviewed binding; no workflow from different source can masquerade as candidate S. |
| assembly-origin-v2 | assembly-origin-v3 | EXTERNAL_V3_ORIGIN_BINDING | All candidate/child/dynamic origins and before/after assembly integrity retained. External v3 contract/harness/verifier has separate frozen hashes; no overlay or patch to candidate source files. |
| generation-fencing-v2 | generation-fencing-v3 | RETAINED_UNCHANGED | Native generation rejection plus raw cross-generation/artifact checks. |
| restart-accounting-v2 | restart-accounting-v3 | RETAINED_UNCHANGED | Finite native receipt/retirement continuation and M1 completion regression must pass on eventual exact candidate. |

All native thresholds/definitions are preserved in safety_ledger.json. Synthetic coverage predicates remain in the stress class and cannot substitute for production acceptance. gate-map-v3.json includes complete original rows and source hashes.
