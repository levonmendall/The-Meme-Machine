# Certified coverage repair and successor handoff

Runtime branch: `repair/target-market-coverage-20260924`. Canonical market branch: `cert/prospective-market-v1`. Both point to **`1c6da29d08bfbe42e39ea1c8068933aae6b15cdb`**. This checkpoint is on a separate documentation branch; its commit is not the runtime SHA.

Successor cohort: **`prospective-four-lane-v6-coverage-repair-20260924`**. Market workflow: [35949285193](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35949285193). Durable state branch: `cert/cohort-state-d4c12afcd902`; authoritative file: `certification/PROSPECTIVE_PROGRAM_STATE.json`. At launch the state was RUNNING with zero records, paper_only=true and live_money=false.

<!-- live-handoff-state -->
**Handoff state at 2026-09-24T03:08:50.023092+00:00:** full exact-SHA non-market engineering certification and final historical replay/preservation passed. Market run 35949285193 is in concurrent smoke. The ten-minute common observation completed; Meteora and Ramses exited cleanly, while the existing Pump runner retains its frozen 1,000-second follow-up. No gate has failed and the latest four native books were flat/reconciled. Final smoke, strategy/market assurance, archive review and hourly-start verification remain pending. This is an interim checkpoint, not a claim that the full promotion chain has completed. Continue observing this existing run; do not start another.
<!-- /live-handoff-state -->

| Lane | Demonstrated cause → repair | Remaining limitation |
|---|---|---|
| Pons | Redundant authenticated factory rounds, repeated out-of-age trajectory acquisition, and HTTP overrun → reuse immutable identity hints with fresh authentication, skip already-known invalid ages, and cap transport by the original deadline. | Earlier queue expiry and provider failures cannot be recovered. Admission deadlines and frozen timing remain; absolute target denominator is unknown. |
| Meteora | Evidence processing starved source pages; independently changing mint supply caused a false pool-state mismatch → separate paced discovery producer with durable FIFO and strict supply-only comparison. | Pending work is explicit; frozen attempt/transaction bounds remain. Missing position-state evidence still fails closed. |
| Pump | Already-excluded signatures reentered history hydration → reuse existing safe-negative hints without inventing bodies or trades. | Missing evidence, sparse trajectories and horizon expiry remain. Native lifecycle and profit protection are unchanged. |
| Ramses | Optional receipt timestamp metadata rejected identical preentry logs → use the existing strict receipt-log matcher in this path. | Five historical pools lacked permitted executable cost routes; historical RPC/429 losses and missing later entry evidence remain. |

Focused acquisition regressions passed. Four exact-source lane suites passed: Pump 316, Meteora 430, Pons 351, Ramses 337 (1,434 total, external sockets blocked). Supervisor suite: 167 passed. Integrated acquisition/qualification/lifecycle and shared-capacity gate: passed locally and in the final hosted certificate. Added coverage includes Pons cache/age boundaries and original deadlines, Meteora cadence/order/failure/shutdown/mint controls, Pump negative-history reuse, Ramses captured preentry authentication/conflict rejection, and exact predecessor preservation.

Full engineering certificate: [35948638345](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35948638345), **PASS**, exact SHA above. All existing component, supervisor/recovery, accounting/crash, resource, integration, source, historical-exposure, chain-binding and connectivity requirements passed. Artifact **10788635040**, SHA256 `818a8ff130867a94419ea2e7ed5017921011fa4fbb9c472ad51721527a42e14c`.

Superseded candidate `e497aeea20d9b41df54e105ad90c93ca048a9bfd` failed certificate 35948220381: the real unresolved-position guard fired, then an outdated non-closeable iterator fixture failed cleanup. Correcting the fixture preserved the same rejection and unchanged-ledger assertions; no lane overlay or policy changed. No successor or historical replay ran from the failed candidate.

| Lane | Frozen source SHA | Declared source diff SHA256 | Frozen strategy policy SHA256 |
|---|---|---|---|
| Pons | `3de3d376847531ccb90e260cfcc96c37587ccb23` | `eba51a72058bb6a72a0e7e5d78db4fbc4d8c0b6e3a8327b0e8adc44bd507558e` | `19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84` |
| Meteora | `ec0b96f999f460c35cb63b27cd0387c4f81f9898` | `c6906c074f683f44a220281579f1c0ab86c8ce34e05f2ed1703b5eda4557e5af` | `90c711e5e3e521fb79f93bc386af5a3067d0a30c83ae3407c550f70db581f966` |
| Pump | `324fee081dd7664a30df4d88aaa1448d28e3033e` | `924799d001c51f898422a2494b75b1afcf2869583572af471f1bcc42d2176cd8` | `b7718de9298e4c825616bed26c87731a65f43c4b12f152b14e1d574eb86eb8d5` |
| Ramses | `5dd003b45a60a73e19bf1162f81e4f1ccd2b4ef2` | `1264b5213376b8f1fa7b8e2c5d0359b20be1ef44f7dddd4a1c6441e811a05173` | `bf75a70fcdf68cf231dd354eab7cb56879bc4c16184553db5c121ea0fdc5d4ef` |

Exact strategy versions remain those in the runtime's `certification/sources.json` and `certification/profitability_protocol.json`.

- Source manifest SHA256: `0143be61b3edc2a5ac0a94f05d488a25f3a5df59a8dfba9876245d127b215dd9`.
- Implementation SHA256: `b8a958d59e8f0a9b6e87c82b37a7bd02ae883c3f34bdd7d4e45ec322817dcc67`.
- Protocol/acceptance-policy identity: `d4c0b1b29b976fc034f768a3180f2c58a3b62dedae4d76dbceec0cb39edd9936`.
- Unchanged acceptance terms excluding cohort, parent and source-diff bindings: `61ccacc2aae26a1c197bc37b72f52f0326bae95bfad20e73c3fcd0b6e1cd521f`.

Strategy economics unchanged: **yes**. Target-market scope unchanged: **yes**. Provider limits unchanged: **yes**. Paper-only unchanged: **yes**. Profitability thresholds, drawdown requirement and precommitted portfolio normalization remain frozen.

Predecessor censored block preserved: **yes**. Cohort `prospective-four-lane-v5-market-assurance-20260923`, SHA `c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66`, workflow **35935431384**, state branch `cert/cohort-state-59078c3dec08`, record SHA256 `90b6440a6429f8dc1f14f0ae63900bbcb2e7d8523c9719d55ad2561e6da8ff48`. It remains halted with zero accepted blocks/hours and one censored block. All four preserved native books were replayed read-only and verified flat; Pump's original five-event accounting and natural settlement remain intact and unadmitted.

The final historical replay passed once before successor collection: 157 captured Pons trajectory rows retained their frozen decisions (123 repeated age rejects were already knowable), 20 Pump negative samples had zero contradictions (2,101 redundant history interests documented), two Ramses pool cases authenticated, and the Meteora supply-only endpoint interval reconstructed without changing controls or pool fields. The Meteora signature prefix is not an independent post-endpoint census or recovered full warmup. No historical evidence, entries or accepted blocks were invented.

Preservation/replay/launch receipts: artifact **10787747054**, SHA256 `43c6396e3b2f581f403fda7086dbae28cb2988c5ab396e923b52e15edb835c7e`; replay result SHA256 `8d529d38ee31754fab4deb3a5bac024e822437a5796feef5abe42e3e37dd82ef`. Original artifact **10785439707** and digest-verified derivative **10786398294** remain referenced by the receipts. No predecessor records were imported into the successor.

Success, failure and cancellation all run native archival, post-block assurance and artifact upload (`if: always()`). The durable program is armed to review the base artifact, retain any open native positions through the existing continuation workflow, and dispatch another frozen block only after unchanged engineering, accounting, evidence and admission gates pass. Infrastructure owns observation and continuation; do not launch a duplicate campaign or interrupt existing native positions.

Exact next action: read the latest state on `cert/cohort-state-d4c12afcd902` and workflow 35949285193 after its first repaired block completes. Inspect digest-verified hourly and review artifacts, source/policy identity, decision replay, native accounting, continuity, required source segments, timely attempts/completions, queue/provider wait, deadlines, reconstruction outcomes and actual infrastructure censoring. Compare those operational metrics with the preserved lane reports in this folder. Apply identical frozen admission logic to winning and losing blocks. If healthy, let the program continue; if halted, preserve the record and diagnose its stated gate before any repair/recertification.

The running workflow is evidence collection, not a claim of completed coverage improvement or profitability.
