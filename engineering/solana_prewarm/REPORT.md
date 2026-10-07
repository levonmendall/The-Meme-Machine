LEGACY_STARTUP: ARCHIVED

NEW_STARTUP: PROVISIONAL

NEW_STARTUP_PROMISING_ONE_PROOF_REMAINS

MODEL B is implemented as the only startup path. MODEL A remains immutable study material, not a second supported implementation or silent fallback. The shared canonical store contains the rolling economic reservoir; CandidateHistory indexes it. No strategy, capital, portfolio or position economics changed. The expensive candidate worker count remains two.

The one remaining proof is a bounded mixed steady-state run on the final source through the actual shared governor with complete rolling candidate and position prerequisites, no feasible original-deadline misses, and normal queue drain. This includes frontier convergence and complete continuation evidence; a mark-only sample is insufficient. It is not a request to revive or repair Model A. Monthly incidence and cost certification depend on this proof.

The last provider-backed Model B capture reached consumer release in 16.204 seconds and steady state in 16.208 seconds. Ordinary startup made zero cold reconstruction calls, zero transaction-body fetches and zero gap-fill RPC calls. It subsequently failed closed on an initial native subscription write. The final source moves that write inside the existing scoped retry handler, with a deterministic regression proving error classification, stream cancellation, retained interests and unchanged deadlines. That repair has not been represented as a successful final-source live mixed run.

The final audit also repaired the authenticated-creation/live-tail case: knowing a creation boundary does not mean its later live slots have finished publishing. Promotion now records a durable upper-bound publication wait, repairs only deficits behind the published frontier, and preserves the first deadline through retries/restart. Three regressions cover authenticated creation, closed-gap plus open-tail separation, and first membership/deadline expiry. This repair also follows the last live capture, so that capture is not claimed to certify final-source steady state.

## Archival and source references

The last legacy commit is `c8a980b69ca1d26a1d72e8554bc32fc9f73e8932`, tree `348ad500e397f53e3eff33c6412c138a6d7ceb2d`. [The archive](../solana_startup_archive/README.md) authenticates exact source, configuration, tests, known failures, preserved captures and prior uncertified cost/stress measurements. The old implementation was not repaired or rerun after the archival decision. Thirty-three tests requiring the removed startup/dispatcher are archive characterization; shared maintenance tests remain active using actual Model B publication.

[baseline.json](baseline.json) records the verified PR/branch/base and safe endpoint identity before edits. [identities.json](identities.json) records publication identities. [files_changed.json](files_changed.json) lists every file changed in this closure, relative to the verified legacy head. [ARCHITECTURE.md](ARCHITECTURE.md) describes the active source path and ownership. Source hashes for the live capture and its exact tested-source archive are retained independently of the final-source regressions.

## Startup and control measurements

These are the authenticated `startup-b6` run, not a successful capacity certificate. Startup and subsequent mixed work have separate byte accounting. Raw application provider payload includes overlapping-shard duplicates before local filtering/deduplication; TLS/NIC framing was not measured.

| Requested result | Evidence / result |
|---|---|
| Clean boot | Read-only live boot reached the durable release barrier; no Model A invocation |
| Same-slot scout/publication race | PASS deterministic: durable wait, authenticated creation publication, zero cold calls, original deadline unchanged |
| True late discovery | PASS deterministic: only proven missing prefix requested, complete retained suffix reused |
| Owner queue pressure | PASS deterministic: 24 retained producer commands and 32 shared-entrypoint commands drain exactly once under a three-slot nonurgent bound |
| Unchanged membership | PASS deterministic: 100 repeated identical observations, one necessary revision/mutation; live 103 of 132 plan requests suppressed (78.03%) |
| Restart | PASS at restore, feed start, recovery overlap, publication wait, release and steady state; original deadline and canonical identity preserved |
| Mixed workload | INCOMPLETE: candidate/position prerequisites and normal drain not certified |
| Feed-connected time | 8.425 s from measurement start |
| First actual normalized event | 8.118 s; this is not an invented quiet-interval milestone |
| Contiguous initial coverage | 16.201 s |
| Consumer release | 16.204 s |
| Steady-state transition | 16.208 s |
| Ordinary-startup cold reconstruction | 0 |
| Ordinary-startup transaction bodies / gap-fill calls | 0 / 0 |
| Canonical-owner queue peak | 58 of 64; final telemetry queue zero after failure shutdown, not normal-drain proof |
| Queue drain time | Not certified; deterministic pressure tests drain, live run stopped on failure |
| No-op plan requests suppressed | 103 / 132; 29 plans, 118 installs include rebuild/recovery retries |
| Producer retry wait p50 / p95 / max | 5.898 / 36.430 / 59.282 s; long waits preclude steady-state capacity claims |
| Admission wait peak | 8.691 s |
| Startup raw provider bytes | 52,992,895 (native 1,924,534; WebSocket 51,068,151; HTTP 210) |
| Startup RPC | 4 calls / 70 CU |
| Startup recovery HTTP bytes | 0 |
| Subsequent raw provider bytes | 249,019,040 over 123.611 s, including drain/abort time |
| Subsequent HTTP / RPC | 66,586,389 bytes / 863 calls / 26,670 CU |
| Subsequent normalized rate | 7,252,328,112 payload bytes/hour; 776,726 RPC CU/hour; arithmetic for this censored mix only |
| Continuous cold-recovery frequency | Uncertified: initial late-discovery stock, explicit position bootstrap, restart and live rebuild work are mixed |
| Total run | 139.815 s / 302,011,935 raw payload bytes / 867 calls / 26,740 CU |
| Measured diagnostic payload price | $0.038253 for this run; framing excluded |
| Duplicate native delivery | 819,670 bytes; 5.1197% overhead versus unique native bytes; fully billed |
| CPU | 167.738 parent CPU-seconds, 119.971% of one core; decoder-child CPU not sampled |
| Peak RSS | 291,868 KiB parent process |
| Local writes / storage | 157,428 observed SQLite changes; peak WAL 115,772,032 bytes; canonical DB 76,898,304; candidate DB 20,381,696; cold archive 21,611 |
| Normalized economics | 6,537 records / 16,727,274 hot logical bytes; local materialization is not provider billing credit |
| Expensive workers | Limit two, unchanged; no new saturation proof |
| Provider governor | Sampled queue maximum four, HTTP concurrency peak three, zero 429s |
| Required gaps / feasible deadline misses | Not proven zero; last running all-scope gaps 4,225, many include rebuilt memberships; no complete required-gap audit at normal drain |

All six prior passed blockers remain protected by focused regressions. The preserved Pump routing result is 1,064/1,064 with no omissions; PumpSwap decoding is 879/879 body-free. They were not reopened as research. New capture classifies nonmonetary evidence workload only; no position or funding execution was performed.

## Warm promotion and parity

The four-scope preserved workload has four Model B promotions with already-complete history: 100% no-backfill, 0% small-gap, 0% cold reconstruction, 0% body-required. Both models use the same candidate cohort, market interval, 12 distinct ordered economics and original 150-second deadlines. The Model A result was preserved before archiving; it was not rerun.

| Metric | Preserved Model A | Model B captured replay | Difference |
|---|---:|---:|---|
| Delivered input provider bytes | 119,108 | 119,108 | Equal; no local byte reduction credited |
| Promotion backfill RPC calls | 4 | 0 | 4 avoided in this replay |
| Promotion backfill RPC CU | 400 | 0 | 400 avoided in this replay |
| Promotion transaction bodies | 17 | 0 | 17 avoided in this replay |
| Local promotion-ready p50 | 0.010714 s | 0.003114 s | 70.9% lower |
| Local promotion-ready p95 | 0.010768 s | 0.003212 s | 70.2% lower |
| Local promotion-ready max | 0.033186 s | 0.004870 s | 85.3% lower |
| History complete at promotion | 0/4 | 4/4 | Warm before urgency |
| Backfill jobs/promotion | 1 | 0 | None required |
| Ordered event recall | 12/12 | 12/12 | Identical identities, ordering and economic fields |
| Unresolved gaps | 0 | 0 | Equal |
| Deadline misses | 0 | 0 | Equal in local replay only |
| Expensive-worker utilization | Not measured | Not measured | Not a worker-capacity test |
| Local replay CPU | 0.110002 s | 0.102194 s | 7.1% lower in this short local replay |
| Peak RSS | 48,388 KiB | 45,660 KiB | 5.6% lower |
| SQLite changed rows | 156 | 179 | 14.7% higher |
| SQLite write statements | 156 | 161 | 5 additional statements |
| Canonical hot storage | 659,456 | 700,416 bytes | 40,960 additional bytes |
| Candidate database | 114,688 | 159,744 bytes | 45,056 additional bytes |

These local timings exclude live transport and provider latency. Continuous live acquisition may cost more than this small replay; provider savings and overall production superiority are not certified.

Pump Current and Pump Survivor strategy regressions retain decision/eligibility parity. The real positive Meteora capture remains full/minimal TRUE with identical vectors. Its replay uses the current normalized evidence reader: 31 RPC calls, 620 CU, 659,383 HTTP bytes, zero RPC transaction bodies/blocks, six scoped native bodies, 98.675 seconds original deadline margin. Supported mechanics, restart, Current→Survivor preservation and capital-independent qualification remain covered.

The live mix observed 63 Pump promotions (12 zero-rich dispositions, 51 censored) and 31 Meteora promotions (nine structural incompatibilities, 22 censored). It did not produce a complete compatible Meteora qualification vector. Its 63 repeated history-preparation observations all belonged to recovery/late-discovery intervals; they are not a denominator for normal warm promotions. Twenty-six acquisition jobs completed and 104 remained pending at failure shutdown. The run fetched 24 selective transaction bodies and 7,822 scoped recovery bodies after startup. Those are real paid bytes, not normal-promotion incidence. No production hydration percentage is inferred from censored work.

Pump position marks were ready in 23/24 samples but continuation dependencies remained unready in 22. Survivor/PumpSwap marks were ready in 24/24 but pre-graduation continuation history remained unready in 24. Meteora had 20/38 ready samples. Complete marks alone do not certify HWM, bridge, staged-add, exit, safety or settlement evidence. Position read latencies p50/p95/p99/max were Pump 2.884/3.319/3.322/3.358 seconds, PumpSwap 3.099/3.204/3.207/3.519, Meteora 3.327/6.505/6.505/11.059. Nine incompatible Meteora dispositions had 24.118/28.721/28.721/30.233 seconds to terminal readiness; this is not compatible qualification latency.

## Cost and protected state

[cost_model.json](cost_model.json) separately records startup and subsequent observed payload/RPC traffic, provenance, window, sample count and classification. Former assumed 6,700 promotions/day and 5,000 selective bodies/day are retired. LOW, EXPECTED, serviceable HIGH, catastrophic/recovery envelope, total expected infrastructure and savings are **not certified** and remain null. Host/storage reference is $73/month. The old broad $1,332.83/month and Model A's uncertified conditional estimate are historical comparisons, not new estimates. No price band is claimed.

Pricing rechecked 2026-10-07 16:46:39 UTC: Yellowstone starts at $75/decimal TB; PAYG RPC $0.525/million CU; Solana WebSocket 0.0002 CU/delivered byte. HTTP response bytes are reported separately and not priced as Yellowstone. See [Alchemy pricing](https://www.alchemy.com/pricing) and [official compute-unit costs](https://www.alchemy.com/docs/reference/compute-unit-costs). Monthly production incidence is not established by a two-minute mixed run.

[strategy_audit.json](strategy_audit.json) verifies 231 protected strategy/policy/nine-change source and test files byte-for-byte against the verified head. Pons and Ramses economics are unchanged, shared-capital remains isolated, and the $500 inception/portfolio state was not opened or modified. [protected_services.json](protected_services.json) records PAPER inactive, CAPACITY's pre-existing failed/stopped state, and RECOVERY/AUTONOMY inactive. No service, monetary PAPER controller, deployment, signing or submission was started.

## Validation

[validation.json](validation.json) records final-source focused Model B, seven-blocker/Gate-1 affected regressions, FAST, affected OPERATIONAL and GitHub exact accepted storage/environment failure identities. Earlier fixture failures and the pre-repair provider abort remain recorded; they are not relabeled as passing measurements. The live capture's tested-source archive makes its boundary from later regression fixes reproducible.

Final classification: **B — NEW_STARTUP_PROMISING_ONE_PROOF_REMAINS**. PR #121 stays draft, open and unmerged. MODEL A stays archived.

Final local acceptance: focused 172 tests PASS (one archived characterization skipped), shared startup/maintenance 101 PASS (one archived characterization skipped), FAST 659 PASS, affected OPERATIONAL 767 PASS across 91 modules (eight archive characterizations skipped). New local product failure identities: 0. GitHub accepted-baseline comparison is recorded in [github_baseline_parity.json](github_baseline_parity.json) after publication.

GitHub source push [37657838165](https://github.com/levonmendall/The-Meme-Machine/actions/runs/37657838165) (659 tests) and PR merge-preview [37657849433](https://github.com/levonmendall/The-Meme-Machine/actions/runs/37657849433) (662 tests) both match the exact accepted nine failures/two errors. New identities: 0; missing/changed accepted identities: 0. The preview includes the pre-existing base Ramses pause tests; Solana implementation sources are identical. Later audit-only delivery leaves these tested source hashes unchanged.
