# Natural continuation-v1 Pump -> PumpSwap acceptance

This branch is an isolated paper-only proof stacked on PR #2. It does not change `Engine.qualify`, any strategy threshold, sizing, exit rule, provider default, shared-capital rule, or market authority.

The live acceptance job may create new paper exposure only through the existing finalized-stream `Engine.scout -> Engine.consider -> Engine.qualify` path. It passes only when the exact natural qualification evidence replays as `qualified`, the resulting order first opens a real incomplete Pump.fun bonding-curve position, that same mint later produces a verified completed-curve handoff, and the same order settles on canonical PumpSwap with reconciliation and archive verification.

The winning scout has an additional evidence-purity requirement: it must come from `evidence/unvalidated_seed_watchlist.json` with `source=watchlist`, and the winning nomination must satisfy `market_time > eligible_after` for that exact wallet. Captured-fixture wallets are excluded from the live acceptance seed set. The report publishes the winning scout wallet, source, admission timestamp, nomination market time, and `prospective_admission_valid=true`; `_proof_complete()` refuses certification without that predicate.

Synthetic candidates, captured-fixture scouts, pre-admission activity, forced authorization, direct reservation/position insertion, injected graduation flags, independent PumpSwap allocation, Raydium fallback, signing, transaction submission, live money, paid infrastructure, merge, and deployment are excluded.
