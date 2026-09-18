# DLMM Research Status

Research-only continuation stacked on draft PR #4. Prospective DLMM allocation remains disabled.

## Protocol-semantic repair

- Mechanical simulator base: draft PR #4.
- Repair commit: `6a9d90e3c48f6584887b3d98208d58cbd60b8e04`.
- `last_update_timestamp` is no longer inferred from `filter_period` alone.
- Reference/volatility decay remains elapsed-time based.
- Persisted `last_update_timestamp` advances only when an authenticated swap crosses at least one bin.
- Same-bin swaps preserve the stored timestamp, including when elapsed time exceeds the filter period.
- Unexplained terminal mutations remain fail-closed.
- Strategy selector remains fixed at `sdk_bidask`, width 8 for the active-market pilot; costs and activity gate are unchanged.

## Validation

The first post-repair live validation attempt was provider-invalid: the public Solana RPC recorded eight failures before a verified opportunity could form. It produced no protocol-semantic contradiction and is not treated as strategy evidence.

This commit triggers one bounded revalidation of the exact same repaired code and unchanged point-in-time high-activity replay. It does not grant allocation authority and does not change strategy behavior.

## Read-only RPC acquisition repair

- Finalized transaction batches are transport optimization only; a partial/rejected batch now falls back only for unresolved items.
- `getTransaction` null is retried once and remains fail-closed if still unavailable.
- Research defaults to Solana's canonical public mainnet endpoint and accepts optional `MM_SOLANA_READ_RPC_URL` for an authorized dedicated read-only endpoint.
- No transaction count, finality, freshness, strategy, cost, or allocation boundary is widened.

## `initialize_bin_array` structural semantics

- Pinned Meteora IDL discriminator `235613b94ed44bd3` is accepted only as `initialize_bin_array`.
- `lb_pair` must be read-only account position 0, instruction data must be exactly discriminator + signed i64 index, account 1 must equal the deterministic `bin_array` PDA, and account 3 must be the system program.
- The instruction is treated as structural only: it creates an empty bin-array account and does not modify modeled LbPair, vault, existing-bin, fee, or virtual-position economics.
- Any subsequent liquidity/config/limit-order mutation remains fail-closed; a swap requiring bins not present in authenticated state still fails closed.
- Strategy `sdk_bidask/8`, costs, activity gate, transaction bounds, and allocation authority are unchanged.

## Dedicated Solana RPC validation

- The dedicated Solana mainnet read-only endpoint has been corrected in GitHub Actions secret `MM_SOLANA_READ_RPC_URL`.
- The workflow validates URL shape before any network call and scopes the secret only to the single DLMM replay step.
- One bounded replay is requested: one supported pool, one cycle, 12-second warmup/outcome windows, unchanged `MAX_TRANSACTIONS=16` and pressure-bounded chunking.
- No repeated provider runs are authorized by this validation marker; the result should be inspected before any further replay.

## Signature start-boundary repair

- Offline repair commit `6256e71700dbcb5fad8334411b1390f702b85e0b` keeps the core verifier unchanged.
- If the first 64-signature page has at most 16 successful post-start transactions but no signature at/before the authenticated start slot, acquisition may make exactly one boundary-only `before=<oldest_signature>` page request.
- Pagination may not silently deduplicate, skip ordering, or expand the accepted transaction set; if it reveals more than `MAX_TRANSACTIONS=16`, the interval still fails closed before transaction bodies are fetched.
- Full CI, resource checks, and synthetic lifecycle passed before this marker.
- This marker authorizes exactly one bounded provider-backed replay of the unchanged one-pool, one-cycle, 12-second research experiment. No repeated replay is authorized without inspecting that result.


## Cache-bypass endpoint proof

- Offline cache-bypass repair commit `5c77cef352f10f73da1cae152798b1fc95140fe5` passed the complete test suite, standard resource check, DLMM resource check, and synthetic lifecycle.
- Endpoint-defining DLMM snapshots now bypass the 2-second RPC response cache for both finalized account reads while ordinary discovery reads remain cacheable.
- This marker authorizes exactly one bounded provider-backed replay: one supported pool, one cycle, 12-second windows, unchanged pressure scheduler and `MAX_TRANSACTIONS=16`.
- The proof target is that a pressure-triggered close obtains a strictly newer finalized endpoint slot rather than reusing the authenticated start slot. No second replay is authorized by this marker.


## Endpoint-slot telemetry live proof

- Telemetry-only commit `9f1ca5c3726b4b7fca48088df1e25fab07daddb5` passed complete offline CI before this marker.
- This marker authorizes exactly one bounded provider-backed replay: one supported pool, one cycle, 12-second windows, unchanged pressure scheduler and `MAX_TRANSACTIONS=16`.
- The proof must record `start_slot`, freshly acquired `end_slot`, and `slot_advanced` before signature-census processing, then preserve first-page/fallback census diagnostics even on failure.
- No second replay is authorized by this marker.


## Bounded post-endpoint signature census proof

- Repair head `3d833363b50bbe686071b3ddd9f79feeade9eca8` passed complete offline CI after adding bounded pagination across signatures newer than the authenticated endpoint.
- Acquisition may scan at most 8 finalized pages / 512 signature rows to reach the authenticated interval, discarding every `slot > end_slot` row from the verified transaction set.
- The actual verified interval remains capped at `MAX_TRANSACTIONS=16`; exceeding that bound still fails closed before transaction-body acquisition.
- This marker authorizes exactly one bounded live replay of the unchanged one-pool, one-cycle, 12-second research experiment. No retry is authorized by this marker.


## Paced bounded signature coverage proof

- Green repair head `dc588f6857e45c7e8f0cacf74dfb8ae02b363576` passed 168 tests, standard resource checks, DLMM resource checks, and the synthetic lifecycle with live jobs skipped.
- The census remains finalized and bounded to 16 pages / 1,024 signature rows, with one-second inter-page pacing to avoid provider bursts.
- Rows newer than the authenticated `end_slot` remain coverage-only and cannot enter the verified interval. The actual interval remains hard-capped at `MAX_TRANSACTIONS=16`.
- This marker authorizes exactly one bounded one-pool, one-cycle, 12-second live replay. No retry is authorized by this marker.


## Second paced bounded signature coverage replay

- User explicitly authorized one additional bounded live replay after the prior proof reached the true `MAX_TRANSACTIONS=16` boundary.
- Code, strategy, finality, pagination pacing, 16-page/1,024-row census cap, and `MAX_TRANSACTIONS=16` are unchanged from `7d18c54a43a0559b031755dd3906be4fd83dabc6`.
- This marker authorizes exactly one additional one-pool, one-cycle, 12-second replay. No further retry is authorized by this marker.


## Host-fee end-to-end certification attempt

- Host-fee mechanics and transaction authentication are green offline at `260d4942004c8b6591fe13b0a648ef6488fb79bd`.
- Self-enforcing certification telemetry/gate is green offline at `3293e0dfbee228f073b4a5197cb83298d492635a`.
- This marker authorizes exactly one bounded one-pool, one-cycle, 12-second live replay.
- Certification requires: allocation disabled; at least one verified opportunity; nonempty warmup; nonempty outcome; at least one real nonzero host-fee swap; at least one resolved selected after-cost counterfactual; zero interval errors; zero RPC failures.
- No retry is authorized by this marker.


## Host-fee certification retry after excluded LP mutation

- The first gated certification attempt failed closed on pinned-IDL instruction `remove_liquidity_by_range2` (`cc02c391359191cd`), an exogenous liquidity mutation whose exact per-bin effects cannot be reconstructed from the emitted aggregate RemoveLiquidity event without point-in-time external position state.
- That instruction remains unsupported; no verifier rule or strategy threshold was weakened.
- This marker authorizes one fresh certification window with the exact unchanged host-fee implementation and hard certification predicates.
- No further automatic retry is authorized after this attempt.


## Final strategy2-reset / host-fee certification

- Green implementation head `fd88a7fe76642bc61212608d134e62389dbf94b5` passed full offline CI.
- Exact `add_liquidity_by_strategy2` is not replayed as a no-op: its AddLiquidity event lacks per-bin distribution/share detail required for exact reconstruction.
- During pre-entry warmup only, that exact authenticated mutation discards all prior warmup chunks and restarts the full window from a fresh finalized snapshot, bounded to two resets.
- During outcome/post-entry replay, the same mutation remains fail-closed.
- Host-fee accounting, transaction/finality bounds, `MAX_TRANSACTIONS=16`, strategy, costs, and prospective allocation disabled are unchanged.
- This marker authorizes exactly one final one-pool / one-cycle / 12-second host-fee certification replay. No retry is authorized by this marker.


## Dense transaction retrieval certification

- Green repair head `963074d15378efe744e8fd8944907bf3826a4080` passed full offline CI.
- DLMM intervals with 8-16 successful transactions now fetch finalized transaction bodies as serialized single JSON-RPC requests spaced one second apart; smaller intervals retain bounded <=4-item batches.
- Logical transaction count, evidence scope, finality, `MAX_TRANSACTIONS=16`, host-fee accounting, strategy2 warmup-reset policy, strategy and costs are unchanged.
- A single getTransaction JSON-RPC provider error retains exactly one retry but waits at least 1.5 seconds before that retry.
- This marker authorizes exactly one one-pool / one-cycle / 12-second host-fee certification replay. No retry is authorized by this marker.


## Normal live serialized dense retrieval proof

- Current code includes the offline-green dense retrieval repair from `963074d15378efe744e8fd8944907bf3826a4080`.
- This proof uses only the normal one-pool / one-cycle / 12-second live bounded DLMM flow; it does not use historical `getBlock` recovery.
- Any naturally occurring interval with 8-16 successful transactions must use serialized single finalized `getTransaction` calls spaced one second apart. Smaller intervals keep bounded batching.
- Strategy2 handling, host-fee accounting, finality, `MAX_TRANSACTIONS=16`, strategy, costs, and prospective allocation disabled are unchanged.
- This marker authorizes exactly one live replay. No retry is authorized by this marker.


## Predictive pressure-closure live proof

- Green repair head `39e7a303bdd3fa4def18c7dd2fe28ff1645c3d52` passed full offline CI.
- Pressure closure now reserves at least 10 of the 16 transaction slots for endpoint-capture growth, lowers the close threshold further as observed arrival rate and measured endpoint latency rise, and retains the unchanged hard `MAX_TRANSACTIONS=16` verifier.
- Interval endpoints use one finalized account read derived from the already-authenticated start-state identity, with `minContextSlot=start_slot+1`, reducing the transaction-growth window while remaining fail-closed if the active bin moves outside the bounded three-array neighborhood.
- Dense body retrieval, host-fee accounting, strategy2 warmup reset, strategy, costs, finality, and allocation authority are unchanged.
- This marker authorizes exactly one one-pool / one-cycle / 12-second live proof. No retry is authorized by this marker.


## Predictive pressure-closure proof result

- Live run `35294759878` on marker `3cc4c6a3f1021d584f0cfb64f69c43e11641f029` completed successfully.
- All 16 authenticated endpoint chunks completed with `capture_completed=true`, complete start-boundary census, and no interval errors.
- Predictive policy retained `MAX_TRANSACTIONS=16`, reserved at least 10 transaction slots of headroom, and triggered early at preflight counts up to 7. The maximum authenticated interval in this proof contained 2 successful transactions.
- The one-read authenticated endpoint path was exercised on every chunk; measured endpoint capture was about 0.65-1.03 seconds.
- Warmup was nonempty (3 reconstructed swaps), outcome was nonempty (3 reconstructed swaps), one opportunity was produced, and the fixed selected `sdk_bidask` width-8 counterfactual resolved.
- The selected one-observation after-cost result was -35.0008 bps; this is evidence that the machinery executed, not a profitability conclusion.
- Two `getSignaturesForAddress` HTTP 429s occurred and both recovered through the existing bounded retry path. There were zero interval errors, zero batch fallbacks, and no transaction-body retrieval failure.
- No nonzero host-fee swap happened naturally in this window, so this run closes predictive chunk-growth / endpoint-capture certification only; it does not add a new live host-fee exercise.
- Artifact: `dlmm-strategy-replay-35294759878-1`, ID `10527546316`, SHA256 `0fdf375831d1579a9151626b96681e8eb7544ca3b5df4b00549176969e420b18`.
- No additional replay was triggered.


## Current JUP-SOL live host-fee sub-proof

- Core DLMM mechanics/replay are already certified on predictive-closure run `35294759878`.
- This proof targets only the remaining host-fee coverage gap on JUP-SOL `C8Gr6AUuq9hEdSYJzoEpNcdjpojPZwqG5MtQbeouNNwg`.
- It uses the normal finalized snapshot -> predictive bounded chunks -> complete signature census -> authenticated transaction bodies -> host token-account delta -> forward reconstruction -> terminal equality path.
- It does not alter strategy, costs, `MAX_TRANSACTIONS=16`, host-fee math, strategy2 handling, or allocation authority.
- This marker authorizes exactly one 12-second current live host-fee proof. No retry is authorized by this marker.


## JUP-SOL host-fee proof execution after harness correction

- Prior run 35295933429 stopped before any live RPC call because the regression module path was misspelled in the workflow.
- The regression target is corrected to `tests.test_dlmm_host_fee`; no strategy/core/verifier behavior changed.
- This marker authorizes the originally intended single 12-second current JUP-SOL host-fee proof. No additional retry is authorized by this marker.


## JUP-SOL current host-fee proof result

- Corrected live run `35296043555` reached the current JUP-SOL market with zero provider failures/retries.
- The initial predictive pressure census observed 17 successful transactions after the authenticated start slot before an endpoint could be captured.
- The unchanged `MAX_TRANSACTIONS=16` guard correctly failed closed with `dlmm_transaction_pressure_overflow`; no transaction body or host-fee evidence was fabricated or dropped.
- This is a market-density/acquisition boundary, not a host-fee accounting failure. No retry is launched against JUP-SOL.

## Profitability research batch 1

- Begin the first bounded multi-pool profitability batch using current finalized SOL-paired discovery, up to three supported pools, one 12-second warmup and one 12-second outcome per surviving pool.
- Existing strategy grid, fixed selected `sdk_bidask` width 8, costs, finality, predictive chunking, `MAX_TRANSACTIONS=16`, and allocation disabled remain unchanged.
- External LP mutations remain fail-closed in research; no state discontinuity is bridged.
- A verified nonzero host-fee event in any completed warmup/outcome will also close the remaining live host-fee occurrence sub-proof.
- This marker authorizes exactly one profitability pilot batch.


## Live host-fee occurrence closeout

- Full host-fee arithmetic and terminal reconstruction remain covered by the captured/offline authenticated host-fee regressions.
- JUP-SOL state-continuity proof is currently impossible within the unchanged 16-transaction cap because its first 0.5-second census already exceeded the cap.
- The remaining certification gap is therefore narrowed to current live occurrence: one finalized exact-input swap with nonzero host fee and authenticated input-token host-account balance delta.
- This bounded scan checks up to 12 successful finalized transactions on each of STONK-SOL, JUP-SOL, and USELESS-SOL, paced one second per body read, and stops at the first authenticated hosted swap.
- No strategy, verifier, cost, threshold, or allocation authority is changed.
- This marker authorizes exactly one bounded live occurrence scan.


## Hardened live host-fee occurrence scan

- The prior occurrence scan aborted on one unrecoverable getTransaction provider error before completing its bounded candidate set.
- The scanner now records and skips an unrecoverable individual body, continues to the next finalized transaction/pool, prioritizes JUP-SOL, and paces body reads at 1.5 seconds.
- Maximum scope remains 36 transaction bodies across JUP-SOL, STONK-SOL, and USELESS-SOL; it still stops at the first authenticated nonzero host-fee swap.
- This marker authorizes exactly one hardened live occurrence scan.


## Live host-fee occurrence sub-proof: CLOSED

- Run `35296698185` completed successfully with artifact `10527857658` (SHA256 `f8d9617c8bb7a8f432b2aa6196c0db4400c9128819e4bf46324910bebf4b50b3`).
- A current finalized JUP-SOL `swap2` was authenticated at slot `447946195`, signature `5jZVtWauYNCuC9sbyvdA1pcmH4Pr8yMPxgcCQrcE3euJ5y6vDFmHaQE8rxmBvoRNCj34d2NaCeJdNuPrEeLSTM5D`.
- Observed amount in: 29,700,000; total fee: 44,551; protocol fee after host: 3,564; host fee: 890; start bin 107 -> end bin 108.
- The input-token host account balance delta was authenticated by the production transaction parser. RPC calls: 5; failures: 0; retries: 0.
- Together with the existing captured/offline exact terminal-reconstruction tests, this closes the remaining live host-fee occurrence coverage gap.

## Profitability research batch 2: sequential provider-safe collection

- Batch 1 established the provider-pressure boundary: three concurrent pools produced 10 provider failures and no complete opportunity, so it is not used as a strategy result.
- Batch 2 keeps the same discovery universe, strategy grid, costs, point-in-time rules, predictive chunking, and allocation disabled, but observes each supported pool sequentially.
- Warmup may use the already-certified bounded strategy2 snapshot reset per pool; outcome remains fail-closed across external LP mutations.
- This marker authorizes exactly one sequential profitability pilot batch.


## Profitability research batch 2 result

- Sequential batch 2 run `35296801124` completed with artifact `10528463840` (SHA256 `e88a322015df91ed9a0e4a68a0415e63da44b7a88187329d6e4f75661dc4a0f0`).
- Three current supported pools entered the batch: STONK-SOL, JUP-SOL, and MCAT-SOL.
- STONK-SOL and MCAT-SOL each showed 17 successful post-start transactions at the first warmup pressure census and were correctly excluded by the unchanged 16-transaction verifier bound.
- JUP-SOL completed six verified zero-swap warmup chunks, then its outcome observation stopped on a getSignaturesForAddress provider failure after bounded retries.
- Batch totals: 48 logical RPC calls, 3 HTTP 429 failures, 2 retries, zero completed warmup/outcome opportunities, zero strategy results.
- No profitability inference is permitted from this batch. Research collection is active, but the next acquisition step is to screen for certifiable transaction density before committing a full warmup/outcome window.
- Strategy grid, costs, fixed selected sdk_bidask width 8, point-in-time rules, and allocation disabled remain unchanged.


## Profitability research batch 3: density-screened completed-window acquisition

- Acquisition implementation is pinned at `0128a5d6cb52050fe01838ca9b26f581075607e8`.
- Before either warmup or outcome may spend transaction-body/reconstruction work, the runner performs one serialized 0.5-second finalized signature census with a hard observation limit of `MAX_TRANSACTIONS + 1` (17). A visible 17 successful post-start transactions is terminal `over_verification_capacity`; no `getTransaction` reconstruction is attempted for that phase.
- Terminal acquisition classifications are persisted explicitly. `certifiable`, `over_verification_capacity`, `verified_zero_swap`, `provider_failure`, `provider_budget_exhausted`, and fail-closed `verification_failure` remain distinct. Over-capacity and provider failures are censoring outcomes, never "no opportunity".
- The runner observes pools sequentially and scans activity-ranked supported candidates until it obtains 6 fully verified warmup+outcome windows, or reaches the bounded 12-pool / 240-logical-RPC safety limits. It no longer stops merely because a fixed first three pools were attempted.
- Every attempt records its RPC delta. The artifact also reports observation RPC calls per attempted pool and per completed observation.
- Density exclusions are retained as first-class artifact rows with phase/preflight evidence and an explicit warning that results from the remaining certifiable subset cannot be generalized to excluded high-density pools.
- Strategy grid, exact costs, fixed selected `sdk_bidask` width 8 rule, finalized point-in-time ordering, `MAX_TRANSACTIONS=16`, DLMM mechanics, and disabled allocation authority are unchanged.
- New censoring regressions plus the complete repository unit suite, resource check, DLMM resource check, and canonical synthetic lifecycle passed on guarded run `35301101477`; the exact same code then passed again on continuation-branch run `35301218801`. All live jobs were skipped by the qualification guard.
- This marker authorizes exactly one density-screened profitability pilot batch. No merge, deployment, live allocation, strategy threshold change, or verifier-capacity increase is authorized.


## Profitability research batch 3 result and acquisition-v2 repair

- Density-screened batch 3 ran as GitHub Actions run `35301321422` on `44399e03ff13229679cb40752adfbc46c94d5e30`.
- Artifact `10529782669` (`dlmm-profitability-pilot-35301321422-1`) has SHA256 `1f10bbf847f4d352233711c9fafac35a872d028aca8e60ef30d6cbeb46c618d8`.
- Seven supported pools were attempted. Terminal classifications were: 3 `over_verification_capacity`, 1 `provider_failure`, 2 `verification_failure`, and 1 `verified_zero_swap`.
- The density exclusions were STONK-SOL, MCAT-SOL, and JUP-SOL. MCAT-SOL and JUP-SOL were rejected directly by the 17-signature preflight at 17 successful post-start transactions. STONK-SOL passed the first 0.5-second census at 11 successful transactions but crossed the unchanged 16-transaction verifier bound during its first authenticated chunk; it was still classified explicitly as `over_verification_capacity`.
- USELESS-SOL passed density preflight but failed closed on `provider_request_failed`; it was not recorded as no opportunity.
- The two generic verification failures, EMBER-SOL pool `5tb9fNLKr2wdJRSTNYRu39kGTjnYVseWo2bGyNgxnLHS` and MET-SOL, were both `dlmm_interval_identity_or_age`. Their pool snapshots had been authenticated during initial discovery and then aged while earlier pools were processed sequentially. This was an acquisition scheduling defect, not a strategy/mechanics failure.
- EMBER-SOL pool `GbrDAq3RjcVWeroLDUwmnuQ8N5xaaKj2Rk2dJDg64CLY` was the only fully verified warmup+outcome window, but both phases contained zero swaps. The fixed selector therefore selected no trade. Its attempt consumed 57 logical RPC calls, including an outcome phase that could not alter the ex-ante selection decision.
- Batch totals: 113 logical RPC calls, 90 observation calls, 11 recorded failures, and 10 retries. Failure kinds were 9 HTTP 429s and 2 provider errors. There were zero selected width-8 trades and no P&L observation. Profitability remains unestablished.
- Acquisition-v2 repairs are now pinned at `9d2107be6702c29e249246aa5b9c5e3fd514fb3f`: each candidate receives a fresh authenticated pool snapshot immediately before its own observation; a verified zero-swap warmup terminates as `verified_zero_swap` without spending an outcome window; and activity discovery can page across up to four current 80-row pages so the scanner is not limited to the first activity page.
- Candidate mint prefiltering, finalized point-in-time rules, exact costs, `sdk_bidask` width 8 selection, `MAX_TRANSACTIONS=16`, swap/fee mechanics, and disabled allocation authority remain unchanged.
- The full repository unit suite, resource check, DLMM resource check, and canonical synthetic lifecycle passed on isolated guarded run `35301727041`. No live proof job ran on that verification.
- No additional profitability batch is authorized by this marker. The next live batch should use the repaired acquisition-v2 path only when the shared Solana public-RPC lane is free; results must continue to preserve density censoring and must not generalize the certifiable subset to excluded high-density pools.
