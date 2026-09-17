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
