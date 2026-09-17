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
