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
