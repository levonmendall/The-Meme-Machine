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


## DLMM economic strategy research v1 implemented

- Research-strategy revision is pinned at `ef344e5f65740d73186b1f7f40712367d5e1a7cb`.
- The prior `sdk_bidask / width 8 / any nonzero warmup` rule is retained only as a legacy comparator. It is no longer the candidate strategy.
- Every candidate outcome now uses the real mechanical `HOLD_SECONDS=60` and the unchanged 350,000-lamport / 35-bps modeled round-trip cost hurdle. The 60-second outcome is composed from five chained independently verified <=12-second acquisition segments; per-segment finality, signature census, `MAX_TRANSACTIONS=16`, transaction reconstruction, mutation rules, and terminal equality are unchanged.
- Pre-entry evidence is range-specific to the proposed liquidity range anchored at the authenticated post-warmup entry state. Recorded features include range liquidity, range-touch volume/fees, 50/100/200-bps approach volume/fees, toward-range volume, actual flow into the range, away/reverting volume, two-way balance, bin travel, net drift, drift ratio, reversal count, and touch-then-revert behavior.
- The development-only cost gate uses an explicit proposed-range fee-capture estimate based on pre-entry range liquidity and requires: projected 60-second range fee capture to clear the unchanged fixed cost, actual flow into the one-sided SOL bid range, and subsequent two-way/reverting activity. It uses no future outcome data.
- Candidate SDK BidAsk placements are normalized by price distance rather than fixed bin count, targeting approximately 100/200/400/800 bps with a bounded 2..32-bin width chosen under each pool's actual `bin_step`. Width 8 remains a comparator, not a universal placement.
- The complete existing `foundation_spot` and `sdk_bidask` grids at widths 2/4/8/16/32 continue to run in shadow on the exact same verified 60-second outcomes.
- Development and holdout are structurally separate. Development requires at least 30 completed observations across at least 5 pools before rule-freeze review. `tests.dlmm_strategy_development_analysis` searches only a predeclared development grid (100/200/400/800-bps distance; 0/0.5x/1x/2x extra fee-surplus margin) and can emit only `status=proposed`; it cannot freeze a rule.
- `DLMM_STRATEGY_RULE_V1.json` is intentionally committed with `status=development`. Holdout fails closed until a separately reviewed commit sets a frozen rule, freeze timestamp, and development cutoff. Holdout observations must be strictly post-freeze and target at least 100 completed observations across at least 10 pools. Holdout data cannot retune the rule.
- Prospective DLMM allocation remains disabled. No Store authority, live-money authority, swap/fee mechanics, cost assumptions, finality rules, verifier capacity, or provider safety predicates changed.
- Exact-head GitHub Actions run `35305570090` passed the full unit suite, standard resource check, DLMM resource check, and canonical synthetic lifecycle.
- No holdout run is authorized while the rule remains unfrozen.


## DLMM provider routing: Alchemy Solana Mainnet only

- DLMM RPC routing is pinned at `d90b4cd869f028c70f584b9e0b8dbeb233fae153`.
- All active DLMM live/replay entrypoints now resolve through one canonical validator: `tests.dlmm_alchemy_provider`.
- The only accepted RPC shape is `https://solana-mainnet.g.alchemy.com/v2/<api-key>`. Solana Labs, PublicNode, devnet, plaintext HTTP, key-only values, query/fragment variants, and any other host fail closed.
- DLMM uses the existing Meme Machine GitHub secret `MM_SOLANA_READ_RPC_URL`. That existing secret is expected to contain the full Alchemy Solana Mainnet endpoint; no replacement secret is required.
- All active DLMM workflows use the dedicated `dlmm-alchemy-solana-live` concurrency group and validate the Alchemy route before making a network request.
- The legacy `tests.dlmm_strategy_high_activity_publicnode` entrypoint is retained only to fail explicitly with `dlmm_publicnode_route_retired_use_alchemy`; it can no longer route traffic.
- Provider telemetry reports `alchemy_solana_mainnet_existing_secret` without logging the configured URL or API key.
- Full deterministic CI passed on exact routing head in run `35306102369`: unit discovery, standard resource check, DLMM resource check, and canonical synthetic lifecycle all succeeded.
- Correction: the connector-selected Alchemy app and its observed capacity are unrelated to the canonical DLMM credential path and must not be used to infer DLMM provider availability.
- Prospective DLMM allocation remains disabled. No strategy thresholds, costs, verifier capacity, finality predicates, swap/fee mechanics, Store authority, signing, or submission behavior changed.


## DLMM Alchemy secret-name correction

- The canonical provider credential already wired into Meme Machine GitHub is `MM_SOLANA_READ_RPC_URL`.
- No new `MM_ALCHEMY_SOLANA_RPC_URL` or `SOLANA_ROI_ALCHEMY_API_KEY` secret is required for DLMM.
- DLMM reads `MM_SOLANA_READ_RPC_URL` and fails closed unless its value is a full `https://solana-mainnet.g.alchemy.com/v2/<key>` endpoint.
- The previously selected Alchemy connector app is not part of DLMM routing and its usage/capacity must not be attributed to DLMM.
- Provider fallback remains disabled; no strategy, verifier, cost, mechanics, allocation, signing, or submission behavior changed.


## DLMM economic strategy development sample 1

- User authorized a live test of the new range-economic strategy after correcting provider routing to the existing Meme Machine `MM_SOLANA_READ_RPC_URL` Alchemy Solana Mainnet endpoint.
- This run uses exactly: 12-second verified warmup, 60-second verified outcome horizon, unchanged 350,000-lamport / 35-bps cost hurdle, range-specific economic gate, normalized 100/200/400/800-bps SDK BidAsk candidates, and the existing foundation_spot/sdk_bidask 2/4/8/16/32 grid in shadow.
- This is development data only. It cannot establish profitability, freeze the strategy rule, enable holdout, or enable allocation.
- Prospective DLMM allocation remains disabled. No threshold, fee, verifier-capacity, finality, mechanics, signing, or submission change is authorized.
- This marker authorizes exactly one bounded development batch.


## DLMM economic strategy development sample 1 result

- Live development run `35306922171` completed successfully on `4a895938aa52f532de41d427e078f52bb520bcd0`; artifact `10531697313` has SHA256 `98e7967db6eb6df2ad0e7c02632ee963726da5b6803fbb24253cf72b0f5fc6b6`.
- The existing Meme Machine `MM_SOLANA_READ_RPC_URL` passed the Alchemy Solana Mainnet route validator before acquisition.
- Six pools were attempted. Terminal classifications: 2 `over_verification_capacity`, 2 `verified_zero_swap`, 1 `provider_failure`, and 1 `provider_budget_exhausted`. No 60-second opportunity completed, so this batch is not a profitability observation.
- STONK-SOL and JUP-SOL were density-censored by the unchanged 16-transaction verifier. MET-SOL and one EMBER-SOL pool completed verified zero-swap warmups and correctly skipped outcomes. USELESS-SOL failed closed on provider request failure.
- The second EMBER-SOL pool (`5tb9fNLKr2wdJRSTNYRu39kGTjnYVseWo2bGyNgxnLHS`) produced the first live nonzero warmup under the new economic strategy: 3 authenticated swaps and approximately 4.0897 SOL equivalent warmup input volume.
- All four price-normalized one-sided SOL bid candidates correctly rejected entry: approximately 99 bps / width 2, 198 bps / width 4, 391 bps / width 8, and 813 bps / width 17. None of the warmup swaps touched the proposed range, verified flow into the range was zero, reversion evidence was zero, estimated range fee capture was zero, and projected 60-second range-fee surplus remained `-350,000` lamports (the unchanged 35-bps cost hurdle).
- This is a meaningful strategy-control result: the former fixed `sdk_bidask` width-8 rule would have selected solely because warmup activity was nonzero; the new range-economic rule declined the same opportunity because the activity did not occur where the proposed liquidity could earn fees.
- The run then verified the first 12 seconds of the rejected candidate's future outcome (2 authenticated swaps) but could not finish the 60-second label because the shared research RPC object reached its 240-logical-call safety budget.
- Batch RPC telemetry: 240 logical calls, 231 HTTP requests, 43 HTTP 429 failures, and 38 retries. The dominant failures were `getSignaturesForAddress` 429s (31). The final stop is therefore an acquisition/pacing-budget boundary, not a strategy loss or qualification rejection.
- Selected trades: 0. Completed 60-second outcomes: 0. No after-cost profitability conclusion is permitted. Development rule remains unfrozen and allocation remains disabled.


## DLMM Alchemy pacing / per-candidate budget repair and development sample 2

- Acquisition repair is pinned at `897b05f5bae6a614163007d6a2b7126f5a7ccb81`.
- The strategy, 12-second warmup, 60-second holding horizon, 35-bps cost hurdle, normalized range candidates, shadow grids, verifier capacity, finality rules, and disabled allocation are unchanged.
- Alchemy physical requests are now serialized through one pacing gate with a 1.0-second minimum request interval across discovery and all candidates.
- HTTP 429 retries retain one bounded retry but now use at least a 2.0-second cooldown.
- Discovery has its own 120-logical-call budget.
- Every candidate receives a fresh independent 240-logical-call budget. A candidate exhausting its budget is terminal only for that candidate and no longer stops the whole batch.
- Independent logical budgets still share the same physical pacing gate, so a budget reset cannot create a request burst.
- Provider telemetry now reports aggregate HTTP 429 count/rate, pacing sleep, and per-candidate budget exhaustion.
- Regression coverage proves that a first candidate can exhaust all 240 calls and a second candidate still proceeds and completes under a separate budget.
- Exact-head CI run `35307817593` passed the full unit suite, standard resource check, DLMM resource check, and canonical synthetic lifecycle.
- This marker authorizes exactly one rerun of the unchanged DLMM economic-strategy development batch to compare provider 429 behavior and obtain complete 60-second labels if available.


## DLMM economic strategy development sample 2 result / sample 3 authorization

- Repaired acquisition run `35307948159` completed successfully on `ff5d056e928d0aa8d4f8a7886d7a5580f8db7bc3`.
- Artifact `10532511355` has SHA256 `198228ec61b504f50fb63a9c69b9983011e64aaac2a23d9761742419b895a119`.
- The Alchemy pacing repair eliminated HTTP 429s in this batch: `43 -> 0` versus development sample 1. Aggregate retries fell `38 -> 1`; provider failures fell `43 -> 3`.
- No candidate exhausted its independent 240-call budget; `per_candidate_budget_exhaustion_count=0`. The batch completed 9 supported attempts using 208 logical calls / 202 HTTP requests, proving the old shared-240-call batch bottleneck is removed.
- Physical pacing telemetry: 1.0-second minimum request interval, 202 paced requests, approximately 98.43 seconds of aggregate throttle sleep.
- No 60-second development label completed in this particular market sample because the candidate mix was: 3 over-verification-capacity warmups, 4 verified zero-swap warmups, 1 provider-body failure, and 1 fail-closed host-fee balance-delta verification mismatch.
- These terminal outcomes are not strategy losses and do not re-open the repaired 429/budget issue. Selected trades and completed outcomes remain zero.
- This marker authorizes exactly one additional unchanged development batch under the repaired acquisition path to seek a naturally occurring certifiable nonzero warmup and prove a full 60-second label can complete.


## DLMM claimFee2 reconstruction and development sample 4

- Exact claim-fee reconstruction is pinned at `3971c388d725cfd120f8179bc6d73cebdcdaa40a`.
- The authenticated discriminator `70bf65ab1c907fbb` is the pinned Meteora `claim_fee2` instruction. Its effect is now reconstructed exactly from pre/post reserve and user SPL-token balances: claimed X/Y must leave the authenticated pool reserves and arrive one-for-one in the corresponding user token accounts with the correct mints.
- claimFee2 is represented as an explicit terminal adjustment to the real and counterfactual pool vault state. LbPair/bin terminal equality still independently proves that no unmodeled pool-liquidity state changed.
- Multiple claimFee2 instructions in one transaction, claimFee2 mixed with a target-pool swap, wrong account identity/mint, non-conserving balance deltas, vault underflow, or unknown adjustment shape remain fail-closed.
- `remove_liquidity_by_range2` (`cc02c391359191cd`) remains unsupported and censored; no liquidity-removal rule was weakened.
- Full CI run `35309070266` passed the unit suite, standard resource check, DLMM resource check, and canonical synthetic lifecycle.
- This marker authorizes exactly one unchanged development batch under the already-repaired Alchemy pacing/per-candidate-budget path to seek a complete 60-second label.


## DLMM Alchemy pacing/budget repair: PROVEN; remaining 60-second blockers are protocol coverage

- Development sample 4 ran as `35309193244` on `cc7507c128743958dfba5fc0ac4295d4fc419f63`.
- Artifact `10533310568` has SHA256 `d474a1f3f6cfcfc373a85b2f7a268ecccf5be337b0896c0b81799c401dcf246a`.
- Provider transport remained healthy: 359 logical calls, 351 HTTP requests, 0 HTTP 429s, 3 provider failures, 1 retry, and 0 per-candidate budget exhaustions.
- Across repaired development samples, HTTP 429 behavior improved from 43/231 requests (~18.6%) before the repair to 0/202 (0%), 2/345 (~0.58%), and 0/351 (0%). Shared-batch budget exhaustion fell from 1 to 0 in every repaired batch.
- Therefore the Alchemy pacing and per-candidate-budget assignment is considered proven. Additional identical reruns are not justified merely to test transport.
- claimFee2 support also passed: discriminator `70bf65ab1c907fbb` is now reconstructed as an exact authenticated reserve-to-user fee transfer and no longer needs to be treated as an unknown pool mutation.
- Sample 4 produced an active USELESS-SOL warmup with 3 authenticated swaps. The new economic selector rejected every normalized range before outcome: projected 60-second range-fee surplus remained approximately -347,487 to -349,663 lamports versus the unchanged 350,000-lamport cost hurdle, despite observed flow into the proposed range. This is a legitimate economic rejection, not a provider failure.
- That rejected candidate then accumulated 7 additional authenticated outcome swaps across the first 24 seconds before encountering discriminator `2bd7f784893cf351`, identified as Meteora `swap_exact_out2`. Exact-out swaps are outside the currently certified exact-input replay subset and remain fail-closed.
- `remove_liquidity_by_range2` (`cc02c391359191cd`) also remains fail-closed because exact per-bin liquidity effects are not currently authenticated.
- Some candidates still expose `dlmm_host_fee_balance_delta_mismatch`; this is a separate host-fee transaction-attribution investigation, not an Alchemy transport failure.
- No complete 60-second strategy label has yet been produced. The next engineering work, if pursued, should address exact-out replay and the recurring host-fee transaction attribution with exact authenticated semantics rather than weakening verifier rules or continuing identical live reruns.
- Strategy, costs, 16-transaction verifier capacity, 60-second horizon, allocation authority, signing, and submission remain unchanged.


## DLMM protocol coverage v2 — live validation

- Protocol-coverage implementation is pinned at `0bf71bce504662101def207d4d305666928281ac`.
- `swap_exact_out2` is now parsed and replayed against authenticated `Swap2Evt` evidence using exact-output traversal; actual input, requested output, fee/protocol/host accounting, and terminal state must all agree.
- `remove_liquidity_by_range2` is now decoded with its authenticated `RemoveLiquidity` event and reserve/user token transfers. Exact per-bin removed shares are derived from authenticated start->terminal liquidity-supply deltas, must occur only inside the declared removal range, and are replayed in transaction execution order. Multiple removals, incomplete observed ranges, supply increases, mismatched event totals, or ambiguous effects remain fail-closed.
- Host-fee attribution now aggregates the expected host fee by host account and token across all relevant swaps in a transaction before checking the transaction-level SPL balance delta. This repairs the prior false mismatch when multiple hosted swaps share one host account while preserving exact token/account identity.
- Counterfactual research replay and paper replay both consume ordered swap/effect actions, including exact-out swaps and supported external liquidity effects.
- Exact-head CI run `35352006568` passed unit discovery, standard resource check, DLMM resource check, and canonical synthetic lifecycle.
- This marker authorizes exactly one unchanged 12-second warmup / 60-second development batch. Strategy, cost hurdle, verifier capacity, Alchemy routing/pacing, and disabled allocation remain unchanged.


## DLMM protocol coverage v2 — first live result and final event-binding repair

- Live validation run `35352327097` completed successfully on `199a05258b36d6dc332dd44ad325cdd93eeccc8d`.
- Artifact `10550752555` has SHA256 `0e208f29151598fad06be7a831df64fc8eaf13f9b8472719b524d79e42cea258`.
- The run produced the first fully verified 60-second DLMM development observation: CARDS-SOL completed 2 authenticated warmup swaps plus 22 authenticated outcome swaps over the complete 60-second horizon.
- The economic selector rejected CARDS-SOL before outcome because none of the proposed normalized bid ranges were touched in warmup and projected range fee capture did not clear the unchanged 35-bps hurdle. The legacy fixed sdk_bidask width-8 comparator resolved at approximately -35.0008 bps.
- Alchemy transport remained healthy: 0 HTTP 429s and 0 per-candidate budget exhaustions.
- The original recurring host-fee balance-delta mismatch did not recur. Transaction-level host aggregation remains enabled and regression-covered.
- Three other pools exposed `dlmm_claim_fee2_event_without_ordered_call`. Inspection showed that ClaimFee2 EventCpi emission is not guaranteed to be adjacent to the ClaimFee2 instruction because other inner DLMM instructions can intervene.
- Final parser repair `d86206475edcd1f8e844cfb0c71c1ba6c6082f75` binds ClaimFee2 and RemoveLiquidity events only by same top-level transaction execution group, exact PositionV2 identity, exact effect kind, and unique unmatched preceding instruction. It does not use loose nearest-event matching.
- Exact-head CI run `35353440772` passed the complete unit suite, standard resource check, DLMM resource check, and canonical synthetic lifecycle. Regressions explicitly insert intervening DLMM inner instructions and require claim/removal events to bind correctly.
- This marker authorizes exactly one final unchanged development batch to validate the repaired event association on live mainnet evidence. Strategy, costs, 16-transaction capacity, 60-second horizon, Alchemy pacing/budgets, paper-only authority, and disabled allocation remain unchanged.


## DLMM host-fee transfer attribution repair — live rerun

- Host-attribution repair is pinned at `9e707d36c6da6d68a93f630dceefb8ba0ae351c4`.
- Hosted swaps now authenticate from the exact ordered SPL Token transfer into the declared `host_fee_in` account when that transfer is present. The source must be the authenticated swap input-side user/reserve account; TransferChecked must name the authenticated input mint; amount must equal the event's host fee.
- This transfer proof covers the live shapes where the host account is omitted from transaction pre/post token-balance arrays and where unrelated same-transaction movement makes the net host-account delta differ from the swap-owned host fee.
- Exact transaction token-balance delta remains an allowed fallback only when no attributable ordered host transfer is present. Wrong mint, wrong source, wrong amount, ambiguous token rows, or conflicting attributable transfer evidence remain fail-closed.
- Strategy, normalized ranges, 35-bps hurdle, 12-second warmup, 60-second outcome horizon, MAX_TRANSACTIONS=16, Alchemy pacing/budgets, paper-only authority, and disabled allocation are unchanged.
- Exact-head CI run `35366871534` passed the unit suite, standard resource check, DLMM resource check, and canonical synthetic lifecycle.
- This marker authorizes exactly one unchanged development batch to validate the repaired host-fee attribution on natural mainnet traffic.


## Targeted host-fee natural-shape diagnostic

- The previous host-transfer attribution rerun `35367056432` completed successfully but still exposed two natural host-fee verifier failures: STONK-SOL `dlmm_host_fee_token_balance_missing` and USELESS-SOL `dlmm_host_fee_balance_delta_mismatch`.
- A read-only diagnostic now captures the exact finalized transaction shapes only for the two known failing slot windows, including ordered DLMM instructions, ordered SPL Token transfers, account identities, and public pre/post token-balance rows.
- This diagnostic changes no strategy, verifier rule, replay math, costs, provider routing, allocation authority, signing, or submission behavior.
- This marker authorizes exactly one bounded host-fee shape probe.


## DLMM routed host-fee attribution repair — final live rerun

- Routed-host attribution repair is pinned at `402fac6fe5c98096021278303ffbbed6edbd0d39`.
- Host-fee validation now scopes failure authority to the target pool's hosted swaps. Hosted swaps for other DLMM pools in the same routed transaction cannot independently invalidate the target pool.
- If another routed DLMM swap shares the same declared host token account and input mint, its authenticated host fee is included only when reconciling the shared transaction-level host-account balance delta.
- Exact ordered SPL-transfer proof remains preferred when present. Transaction balance delta remains a fallback. Wrong mint, wrong amount, conflicting attributable transfer evidence, or a balance delta matching neither the target nor the exact same-host aggregate remains fail-closed.
- Strategy, range placement, 35-bps hurdle, 12-second warmup, 60-second outcome horizon, MAX_TRANSACTIONS=16, Alchemy pacing/budgets, paper-only authority, and disabled allocation are unchanged.
- Exact-head CI run `35368617972` passed the full unit suite, standard resource check, DLMM resource check, and canonical synthetic lifecycle.
- This marker authorizes exactly one unchanged development batch for final natural validation of routed host-fee attribution.


## DLMM host-fee terminal-conservation fallback — live validation

- Host-fee reconstruction repair is pinned at `ab4f78d8f5ada03d6048a1bcf8a64bb8cfa3abce`.
- Standalone host-fee occurrence parsing remains strict: it still requires exact recipient SPL-transfer or token-balance evidence.
- Complete interval reconstruction may defer recipient-account evidence only when those rows are missing or the net recipient delta is confounded. In that case, the program-authenticated host-fee event plus exact terminal pool reserve/protocol-fee equality is the authoritative conservation proof.
- Exact attributable SPL transfers remain preferred and contradictory transfer evidence still fails. Wrong token identity still fails immediately. A spoofed host-fee event still fails terminal reconstruction.
- This removes a metadata-availability veto without weakening pool-state correctness; the separate live JUP recipient-delta occurrence proof remains preserved.
- Strategy, range placement, 35-bps hurdle, 12-second warmup, 60-second horizon, MAX_TRANSACTIONS=16, Alchemy pacing/budgets, paper-only authority, and disabled allocation remain unchanged.
- Exact-head CI run `35370152998` passed unit discovery, standard resource check, DLMM resource check, and canonical synthetic lifecycle.
- This marker authorizes exactly one unchanged development batch for natural validation.


## PERPSPAD single-transaction isolation and external-effect telemetry repair

- The remaining PERPSPAD failure from run `35370329650` was isolated to exactly one finalized transaction:
  - pool: `EHqk4Fw3pTCf9UW75dWoCMf6a2GxyJ8FGYEj2Qmw9rfr`
  - start slot: `448142429`
  - endpoint slot: `448142448`
  - transaction slot: `448142440`
  - signature: `2pZdWH2LxbJc9VJWDniwNvJeQStq9Ronao4ebMcr5QtJvxmTvBt6iLUxHDkVRLtgcFdBobC1PLpzNZKNnmix5aPt`
- Read-only shape probe run `35377346900`, artifact `10560383710`, SHA256 `e8f3cfeea8d5ed09d812364e7cd7580ae82fd50088620935cbe7a3d115b43efb`, proved the transaction contains no target swap. It contains `claim_fee2` followed by `remove_liquidity_by_range2`.
- The prior reason `dlmm_host_fee_token_balance_missing` was therefore misleading. The missing row belongs to the destination user token account for an external-effect transfer, not to host-fee recipient attribution.
- The SOL destination ATA is created in the same transaction and correctly has no `preTokenBalances` row. Ordered `TransferChecked` instructions authenticate the ClaimFee2 and removal transfers exactly:
  - ClaimFee2: 40,982,582 PERPS and 2,111,659 lamports-equivalent WSOL units.
  - RemoveLiquidityByRange2: 1,248,827,314 PERPS and 4,628,172,814 WSOL units.
  - Aggregate reserve deltas and post-user balances match those authenticated transfers exactly.
- External effects now authenticate from ordered reserve→user SPL transfers first. Balance rows remain a conservation cross-check/fallback. A newly-created destination ATA may lack a pre balance row when exact ordered transfers and terminal pool equality prove the movement.
- Missing/ambiguous/shape failures in this path now use `dlmm_external_effect_*` telemetry and no longer report `dlmm_host_fee_*`.
- Wrong mint, wrong source/destination, wrong transfer amount, or inconsistent reserve/user balance deltas remain fail-closed.
- Exact-head CI run `35377640096` passed unit discovery, standard resource check, DLMM resource check, and canonical synthetic lifecycle.
- Strategy, normalized ranges, 35-bps hurdle, 12-second warmup, 60-second outcome horizon, `MAX_TRANSACTIONS=16`, Alchemy pacing/budgets, paper-only authority, and disabled allocation are unchanged.
- This marker authorizes exactly one unchanged development batch to validate the repaired PERPSPAD external-effect path on natural mainnet traffic.


## PERPSPAD external-effect repair — live rerun result

- Identical development rerun `35377921901` completed successfully on `c8b4820b81b2a4b78c051f6c3e318bbfa761123f`.
- Artifact `10561071647` has SHA256 `b3c06a8f9d99b88d0e0b9c2c3d1a0b8157100d0c57cfbf7a9f17cd496ab3f2ab`.
- The previous misleading `dlmm_host_fee_token_balance_missing` did not recur. No `dlmm_external_effect_token_balance_missing` occurred either.
- PERPSPAD was not present in this fresh discovery sample, so the exact historical PERPSPAD transaction repair is deterministic/captured-evidence proven but was not naturally re-observed in this batch.
- The batch attempted 8 supported pools. Terminal classifications: 3 over-verification-capacity, 3 verified-zero-swap, 1 provider failure, and 1 verification failure.
- The sole verification failure was unrelated to host/external-effect attribution: STONK-SOL completed a 2-swap warmup and the first two 12-second outcome segments, then correctly failed closed on authenticated `add_liquidity_by_strategy2` at slot `448159242`. Outcome coverage reached 24 seconds before that mutation.
- STONK's economic selector had already rejected entry before outcome: all normalized bid ranges had zero range-touch fee capture / zero flow into range and projected 60-second range-fee surplus of `-350,000` lamports. No strategy threshold changed.
- Provider transport remained healthy: 318 logical RPC calls, 315 HTTP requests, 0 HTTP 429s, 1 retry, 0 per-candidate budget exhaustions.
- No 60-second window completed in this particular fresh market sample, so no new profitability observation is added. The earlier completed CARDS 60-second observation remains valid.
- Strategy, costs, `MAX_TRANSACTIONS=16`, Alchemy pacing/budgets, paper-only authority, and disabled allocation remain unchanged.


## Expanded DLMM development observation universe

- Observation-cap implementation is pinned at `3e4fea42fea4ef3b9655658b0548c3d9995cdf8e`.
- Development `max_attempted_pools` is increased from 12 to 24. The target remains 6 complete verified 60-second windows, so the batch still stops early when enough complete evidence is obtained.
- Candidate discovery remains activity-ranked and deterministic. No pool is retrospectively added or removed based on outcome.
- `MAX_CANDIDATE_SCAN_MULTIPLIER=4`, activity paging, mint prefiltering, density censoring, per-candidate 240-call RPC budgets, shared Alchemy pacing, and the 16-transaction verifier capacity are unchanged.
- The development job timeout is increased from 20 to 30 minutes only to prevent the wider scan from being truncated by wall-clock limits; no provider-call budget is increased.
- Strategy and economics are unchanged: 12-second warmup, 60-second outcome, 35-bps fixed-cost hurdle, normalized ranges, point-in-time separation, paper-only authority, and disabled allocation.
- Holdout scope remains unchanged and is not activated.
- Exact-head CI run `35383564774` passed the full unit suite, standard resource check, DLMM resource check, and canonical synthetic lifecycle.
- This marker authorizes exactly one expanded development batch with `--max-attempted-pools 24` and `--target-completed 6`.


## addLiquidity2 exact-shape probe

- Expanded-universe run `35383813365` exposed one warmup verifier failure on MET-SOL pool `FzA8Fji7xdr9jfN7Y2YCUGLYwBzqP1eicKA4dX4m8BJg` with discriminator `e4a24e1c46db7473`, identified as Meteora `add_liquidity2`.
- The exact failed interval is finalized slot `448176914` through `448176933` with two successful transactions.
- This marker authorizes one read-only bounded probe of those exact transactions to capture the addLiquidity2 payload, per-bin distribution, AddLiquidity event, SPL transfers, and token-balance rows.
- No verifier acceptance rule, strategy, cost, range, provider budget, allocation authority, signing, or submission behavior changes in this probe.


## addLiquidity2 support and cumulative 30-observation collection

- Exact implementation head is `e15e0f22f4f4d3b3b49ec7fbc0f15eb1b7d72323`.
- Read-only natural-shape probe run `35393738069` completed successfully with artifact `10566442552` (SHA256 `27abf68463fe46c6d58776d40e746770bd16d65fc8821656a0618044e2ff0d22`).
- The probe captured the exact MET-SOL interval that previously failed on discriminator `e4a24e1c46db7473`, confirming it is Meteora `add_liquidity2`.
- Natural instruction/event arithmetic is exact and bounded:
  - slot `448176921`: max X `9,285,399`; 25 explicit bins `557..581`; distribution sums to 10,000 bps; per-bin integer floors sum to actual/event/TransferChecked X `9,285,387`.
  - slot `448176930`: max Y `735,872,697`; 45 explicit bins `511..555`; distribution sums to 10,000 bps; per-bin integer floors sum to actual/event/TransferChecked Y `735,872,676`.
  - both events report active bin `556`; X deposits are strictly above active and Y deposits strictly below active, so the supported natural subset avoids active-bin composition-fee ambiguity.
- Isolated, single-sided `add_liquidity2` is now decoded from the pinned IDL, bound to exactly one AddLiquidity event, authenticated by ordered user→reserve SPL transfers, replayed per bin using the explicit floor distribution and `deposit_share`, then required to match the authenticated terminal pool state.
- A mixed `remove_liquidity_by_range2` + `add_liquidity2` rebalance is not partially reconstructed. During pre-entry warmup it emits the existing bounded snapshot-reset signal, discards prior warmup chunks, takes a fresh finalized snapshot after the mutation, and restarts the full warmup. During outcome/post-entry it remains fail-closed. This preserves point-in-time correctness.
- The observed MET-SOL failure was such a mixed rebalance (and one transaction also contained a swap), so the new warmup-reset path directly addresses the natural censoring case without inventing missing PositionV2 share history.
- Full CI run `35394371286` passed unit discovery, standard resource check, DLMM resource check, and canonical synthetic lifecycle.
- Development observation tracking is now cumulative and deduped by `(pool, entry_slot, end_slot)`. The preserved baseline contains 7 complete observations across 5 distinct pools, leaving 23 observations to the planned 30-observation development boundary.
- Every complete observation now records the best projected 60-second fee capture, best projected surplus, exact lamport/bps gap to the unchanged `350,000`-lamport hurdle, and fee-hurdle coverage ratio. The artifact also preserves the full merged cumulative observation ledger for promotion into the next run.
- The current closest observed case remains JUP-SOL: projected fee capture `5,748.15985295281` lamports, projected surplus `-344,251.8401470472` lamports, hurdle gap `344,251.8401470472` lamports / approximately `34.425184` bps.
- Strategy, normalized ranges, 12-second warmup, 60-second outcome horizon, 35-bps fixed cost hurdle, `MAX_TRANSACTIONS=16`, 24-pool development observation ceiling, Alchemy pacing/per-pool budgets, paper-only authority, and disabled allocation are unchanged.
- This marker authorizes exactly one widened development batch (`--max-attempted-pools 24 --target-completed 6`) using the new addLiquidity2 handling and cumulative hurdle-distance reporting.


## Wallet-derived DLMM strategy discovery

- The legacy 12-second warmup / 60-second holding strategy is on enforced research hold under `DLMM_60S_RESEARCH_HOLD.json`.
- Its final preserved development record contains 10 complete observations across 5 pools, 0 selected trades, and no economically adequate fee-capture case. The legacy workflow's development and holdout jobs are disabled while this hold is active.
- New research is governed by `DLMM_WALLET_STUDY_PROTOCOL_V1.json`.
- Phase A is outcome-blind wallet discovery. It may read current pool metadata and finalized Solana DLMM LP transactions, but the discovery code hard-rejects Meteora portfolio/PnL/position endpoints.
- Pool sample: first 12 SOL-paired, non-blacklisted pools ranked by 24h fee/TVL, with TVL >= $50,000 and 24h volume >= $25,000.
- Wallet evidence: recent finalized `add_liquidity2`, `add_liquidity_by_strategy2`, `remove_liquidity_by_range2`, or `rebalance_liquidity` signer activity; at most 5 discovered wallets per pool; target 30 wallets; minimum 12 to freeze.
- Only after the exact wallet addresses are committed in `DLMM_WALLET_COHORT_V1.json` with `status=frozen_pre_pnl` may Phase B query Meteora portfolio and position PnL/history endpoints.
- Phase B's preregistered profitable-wallet definition requires at least 5 closed positions, at least 2 distinct closed-position pools, positive aggregate USD PnL, positive aggregate SOL PnL, and at least a 55% positive-position rate in USD.
- Phase B is behavior discovery only. It cannot freeze a trading strategy automatically.
- Any candidate strategy must be derived only from repeatable patterns in the frozen wallet cohort, frozen in a later reviewed commit, and tested prospectively on strictly post-freeze data.
- Full deterministic CI on implementation head `2b3e4dba3ff510f75b35b9945388850f7f5c2fcd` passed unit discovery, standard resource checks, DLMM resource checks, and canonical synthetic lifecycle.
- This marker authorizes exactly one Phase A wallet-cohort discovery run. It does not authorize PnL analysis, strategy freeze, allocation, signing, submission, or live money.


## Wallet cohort discovery retry after provider-failure isolation

- Initial Phase A run `35401807605` reached the authorized Alchemy endpoint with the PnL access guard intact, but one unrecoverable `getTransaction` provider error aborted the whole discovery job before a cohort artifact could be produced.
- Repair `6628accd276835f6c6fc5d363cab292c03237768` changes only discovery failure scope: signature-census failure is terminal for that pool; individual transaction-body failure is recorded/skipped; later transactions and pools continue under the same bounded budgets and shared pacing.
- No PnL endpoint is permitted in Phase A, no wallet can enter based on profitability, and pool/wallet sampling rules are unchanged.
- Full CI run `35401880174` passed.
- This marker authorizes exactly one blind Phase A retry.


## Frozen pre-PnL wallet cohort

- Blind Phase A run `35401999021` completed successfully.
- Discovery read no Meteora portfolio/PnL/position endpoint; `pnl_data_read=false` is preserved in artifact `10570948107` (SHA256 `a5dc9764e157f4d543866b34ea925fdfaf6dc05244ee3a46097c9a09f745325b`).
- The bounded sample observed 49 supported LP actor events across the preregistered 12 SOL-paired pools and produced 23 unique wallets. The target was 30; 23 exceeds the preregistered minimum of 12, so the exact addresses are frozen rather than broadening the sample after seeing outcomes.
- Frozen cohort file: `DLMM_WALLET_COHORT_V1.json`.
- Cohort wallet-list SHA256: `95a7cad9e2f7418afde8d9003cc3eb79743ea18b344845640a182faf97db7708`.
- Phase B may now read Meteora portfolio, closed-position PnL, and position-history endpoints for only these frozen wallets.
- Profitability classification thresholds remain exactly preregistered; this marker does not permit adding/replacing wallets based on PnL.
- This marker authorizes one Phase B behavior-analysis run only. It does not authorize strategy freeze or prospective allocation.


## Wallet cohort normalized Phase B rerun

- Frozen cohort remains exactly 23 wallets with cohort hash `sha256:95a7cad9e2f7418afde8d9003cc3eb79743ea18b344845640a182faf97db7708`.
- No wallet membership changed after PnL analysis.
- The first Phase B run identified repeatable holding-duration and rebalance signals, but raw bin counts are not economically comparable across pools with different bin steps.
- Current analysis code now records pool `binStep`, converts each closed position's bin width to approximate price-span basis points, and classifies first-add composition as SOL-only, token-only, or two-sided from the immutable position event history.
- This marker authorizes one rerun of Phase B on the exact same frozen cohort to normalize range geometry and composition before any candidate strategy is frozen.
- It does not authorize cohort replacement, threshold fitting from the legacy 60-second sample, prospective allocation, signing, submission, or live money.
