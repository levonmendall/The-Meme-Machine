# Post-graduation milestone status

Base branch: `feat/pump-directional-paper` at `a65e2e6d3f827cd748b748b68058529579cdbeb8`.
Stacked branch: `feat/post-graduation-pumpswap-raydium`.

Scope remains paper-only and bounded. `continuation-v1` and `Engine.qualify` are unchanged. No signing, transaction submission, live money, deployment, paid provider, DLMM allocation, FOMO, Robinhood, or predecessor-repository changes are authorized here.

The important current boundary is now:

- **new exposure is still authorized only by the existing Pump `continuation-v1` path**;
- an already-authorized Pump reservation or open Pump position can now continue durably onto the deterministic canonical PumpSwap pool if the bonding curve graduates;
- PumpSwap cannot independently nominate, qualify, size, reserve, or originate a new position;
- legacy Raydium remains research/replay only and is not instantiated as a prospective execution fallback.

## Completed-curve handoff

The active Pump bonding-curve decoder remains unchanged and still rejects zero quote reserves. Post-graduation handoff has a separate immutable completed-curve decoder because migrated accounts can have retired/zeroed quote state. It requires the canonical bonding-curve PDA, `complete=true`, zero real-token inventory, fixed mint authority/freeze semantics, valid supply bounds, SOL quote scope, and no cashback. Legacy pre-Mayhem 81-byte accounts default missing appended mode fields to false/none only in this handoff path.

## Canonical PumpSwap mainnet proof

Workflow `35186308858` established a complete canonical PumpSwap read on mainnet for Pump's documented migrated mint `7LSsEoJGhLeZzGvDofTdNg7M3JttxQqGWNLo6vWMpump`.

- derived and observed pool: `GseMAnNDvntR5uFePZ51yZBXzNSn7GdFPkfHwfr6d77J`, matching Pump's documented pool;
- completed-curve handoff slot: `447716801`; PumpSwap snapshot slot: `447716806`;
- base reserve: `649596913609305` token base units;
- effective quote reserve: `127506693554` lamports;
- live fee parts: `[2, 93, 30]` bps;
- exact 0.1 SOL read-only buy returned `502781926495` token base units;
- immediate modeled sell returned `97380002` lamports, a `2619998` lamport round-trip loss;
- 0 HTTP failures/retries and $0 public-RPC/infrastructure spend;
- no signing, submission, or live-money authority.

Raw source evidence is Actions artifact `postgrad-live-35186308858-1`, artifact ID `10481987603`. A checked fixture reproduces pool identity, vault balances, dynamic fee tier, and integer quotes from captured mainnet bytes.

## Durable prospective Pump -> PumpSwap continuation

`meme_machine/pumpswap_runtime.py` now carries **existing Pump-authorized paper exposure** across a verified current-era graduation.

For a pending reservation:

1. the reservation must already exist in the shared Store from the unchanged Pump qualification/allocator path;
2. completion of the canonical Pump curve is verified and the immutable graduation handoff is persisted;
3. the canonical PumpSwap pool is derived and fully revalidated from finalized accounts;
4. the existing budget is reused and the original minimum-token slippage floor is preserved;
5. a post-delay PumpSwap quote with a newer slot is required before fill;
6. if canonical PumpSwap evidence remains unavailable, the reservation waits only for a bounded 60-second continuation horizon and is then cancelled/released rather than guessed or routed to Raydium.

For an already-open Pump position:

- graduation handoff is persisted in the same durable Store;
- after restart the runtime resumes directly from canonical PumpSwap rather than depending on the retired Pump curve;
- exact-size PumpSwap sell quotes provide marks and exits;
- the existing +15% take-profit, -10% risk exit, 15-minute timeout and <5 SOL liquidity-invalidation rules remain unchanged;
- unresolved PumpSwap marks preserve the position and use the existing coalesced unresolved-write cadence;
- settlement returns rent/cash through the same shared $500 accounting and reconciliation path.

The main prospective runtime now constructs `PostGraduationAdapter` over the same bounded RPC budget and `PumpSwapPaperRuntime` over the same SQLite Store. Existing orders/positions are serviced before discovery. The prospective runtime deliberately disables the Raydium scanner; current-era continuation is PumpSwap-only.

This is **continuation authority, not new PumpSwap allocation authority**. `pumpswap_continuation.new_allocation_authority` is always false and no PumpSwap-originated reservation API is exposed to the prospective loop.

## Connected verification

Latest code-bearing proof: `18e6c9f39ab5967d69d60c3e3823086b3a2cd2b8`, push workflow `35235184302`.

- **99/99 deterministic tests passed**;
- the main prospective `_monitor_existing` routing is tested for both a due reservation and an open Pump position when the Pump curve is retired;
- a pending Pump reservation can transition to canonical PumpSwap, fill, close/reopen the Store, and retain the PumpSwap position/reconciliation state;
- an open Pump position can transition to PumpSwap, persist its handoff, restart, monitor, form an exit intent, settle, and verify the journal archive;
- missing PumpSwap evidence fails closed: the reservation is bounded and released, while an existing position remains unresolved rather than disappearing;
- a not-yet-graduated curve cannot create post-graduation authority;
- the captured mainnet PumpSwap fixture is connected through the durable prospective Store path, proving the real captured handoff/quote can fill an already-existing reservation and survive restart;
- the existing 2,000-frame / 240,000-event resource check remained green: DB `1261568` bytes, WAL `708672` bytes, journal rows `4002`, peak RSS `27256 KiB`, and zero real provider calls in the synthetic resource test;
- the canonical synthetic lifecycle remained green.

No CI test creates an authoritative market-driven trade. The captured fixture is evidence plumbing, not profitability evidence.

## Legacy Raydium-v4 identity boundary

The historical sample mint `9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump` currently has more than one structurally valid WSOL Raydium-v4 pool. Generic discovery therefore fails closed with `ambiguous_legacy_raydium_pools`; it never ranks pools by liquidity or convenience.

For research-only current-pair evidence, `evidence/legacy_raydium_pool_registry.json` records explicit pool `Bzc9NZfMqkXR6fz1DBph7BDf9BroyEf6pnzESP7v5iiw` with `current_pair_identity_verified=true`, `direct_pump_withdraw_lineage_verified=false`, and `allocation_eligible=false`.

Workflow `35187441898`, artifact `10481694551`, proved the current Raydium-v4/OpenBook/vault identity and exact-size quote mechanics live on mainnet. That does not make the pool a prospective execution surface.

## One targeted historical-lineage attempt

Workflow `35232477616`, archival job `105239864025`, artifact `10502232524`, made the one authorized bounded attempt to recover the old Pump-withdraw -> Raydium migration transaction. It scanned `180` pages / `180000` finalized migrator signatures using `197` bounded RPC requests, but the oldest signature reached was Unix time `1788282010` while the target pair creation timestamp was `1729231787`. It therefore never reached the 2024 target window. There were 16 HTTP-429 retries, zero target-window candidates, zero target transaction bodies examined, and no direct lineage match.

That proves chronological public-RPC paging is not a viable bounded archival method; it does not disprove the historical lineage. Any later attempt should use an indexed historical source capable of seeking directly to 2024. No registry flag or allocation authority was changed.

## Current engineering boundary

The **current Pump -> canonical PumpSwap post-graduation continuation is now wired into the durable prospective paper runtime** for existing Pump-authorized reservations and positions. The remaining evidence boundary is a real market-driven lifecycle in which unchanged `continuation-v1` naturally creates Pump exposure and that same exposure subsequently graduates and is continued/settled on PumpSwap. Until such a natural lifecycle occurs, this implementation is mechanically and captured-data proven but not operational-acceptance or profitability evidence.

New PumpSwap-originated allocation remains disabled. Legacy Raydium remains research-only. Do not merge, deploy, add costs, enable signing/live money, or change `continuation-v1` without separate authorization.
