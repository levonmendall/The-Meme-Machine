# Post-graduation milestone status

Base branch: `feat/pump-directional-paper` at `a65e2e6d3f827cd748b748b68058529579cdbeb8`.
Stacked branch: `feat/post-graduation-pumpswap-raydium`.

Scope remains read-only/paper-only: Pump.fun completed-curve handoff -> verified canonical PumpSwap or explicit provenanced legacy Raydium-v4 identity -> exact-size quotes -> disabled prospective allocation -> synthetic/captured paper lifecycle using the shared Store/Allocator. `continuation-v1` and `Engine.qualify` are unchanged. No signing, submission, deployment, paid provider, live money, DLMM allocation, FOMO, Robinhood, or predecessor-repository changes are authorized here.

## Completed-curve handoff

The active Pump bonding-curve decoder remains unchanged and still rejects zero quote reserves. Post-graduation handoff has a separate immutable completed-curve decoder because migrated historical curve accounts can have retired/zeroed quote state. It requires the canonical bonding-curve PDA, `complete=true`, zero real-token inventory, fixed mint authority/freeze semantics, valid supply bounds, SOL quote scope, and no cashback. Legacy pre-Mayhem 81-byte accounts default missing appended mode fields to false/none only in this handoff path.

## Canonical PumpSwap proof

Workflow `35186308858` established a complete canonical PumpSwap read on mainnet for Pump's documented migrated mint `7LSsEoJGhLeZzGvDofTdNg7M3JttxQqGWNLo6vWMpump`.

- derived and observed pool: `GseMAnNDvntR5uFePZ51yZBXzNSn7GdFPkfHwfr6d77J`, matching Pump's official documented pool;
- completed-curve handoff slot: `447716801`; PumpSwap snapshot slot: `447716806`;
- base reserve: `649596913609305` token base units;
- effective quote reserve: `127506693554` lamports;
- live fee parts: `[2, 93, 30]` bps;
- exact 0.1 SOL read-only buy returned `502781926495` token base units;
- immediate modeled sell returned `97380002` lamports, a `2619998` lamport round-trip loss;
- 0 HTTP failures/retries and $0 public-RPC/infrastructure spend;
- no order, allocation, signing, submission, or live-money authority.

Raw source evidence is Actions artifact `postgrad-live-35186308858-1`, artifact ID `10481987603`. A checked fixture and deterministic regression reproduce the pool identity, vault balances, fee tier and integer quotes from captured mainnet bytes.

## Legacy Raydium-v4 identity boundary

The historical sample mint `9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump` currently has more than one structurally valid WSOL Raydium-v4 pool. Generic discovery therefore still fails closed with `ambiguous_legacy_raydium_pools`; it never ranks by liquidity or chooses a convenient pool.

Pump's current documentation states that old completed curves used the deprecated withdraw/off-chain migration route to Raydium, whereas current migration uses canonical PumpSwap. The bounded free public-RPC history available to this project cannot recover the old Fartcoin Pump withdraw transaction, so **direct Pump-withdraw -> Raydium migration-event lineage is not claimed**.

For research-only current-pair evidence, `evidence/legacy_raydium_pool_registry.json` records one explicit Fartcoin pool, `Bzc9NZfMqkXR6fz1DBph7BDf9BroyEf6pnzESP7v5iiw`, with:

- `current_pair_identity_verified=true`;
- `direct_pump_withdraw_lineage_verified=false`;
- `allocation_eligible=false`;
- public corroborating references recorded as provenance only, never runtime dependencies.

`meme_machine/legacy_raydium.py` accepts that pool as data, then revalidates the full finalized on-chain Raydium-v4/OpenBook/vault/mint identity every read. It normalizes whether the token is the Raydium base or quote side and includes OpenOrders totals and `needTakePnl` in executable reserves. It refuses stale/future marks and cannot grant allocation authority.

Workflow `35187441898`, artifact `10481694551`, proved this explicit read path live on mainnet:

- pool: `Bzc9NZfMqkXR6fz1DBph7BDf9BroyEf6pnzESP7v5iiw`;
- completed Pump handoff slot: `447720091`; Raydium snapshot slot: `447720095`;
- token reserve: `25153410085016` base units;
- SOL reserve: `36242914813688` lamports;
- swap fee: `25 / 10000`;
- exact 0.1 SOL read-only buy returned `69228586` token base units;
- immediate modeled sell returned `99500077` lamports, a `499923` lamport round-trip loss;
- quote age: 12 seconds;
- 6 RPC requests, 0 failures/retries, $0 public-RPC/infrastructure spend;
- current pair identity verified, direct Pump-withdraw lineage false, allocation false, no order/signing/submission/live-money authority.

A captured Raydium fixture preserves the same finalized pool/mint/vault state and decoded OpenOrders totals. The exact packed OpenOrders decoder is also independently covered by deterministic synthetic regression; the live adapter decoded the original 3228-byte OpenOrders account successfully.

## Fail-closed surface resolver

`meme_machine/postgrad_resolver.py` separates discovery from authority:

1. canonical PumpSwap is always attempted first;
2. only a proved `pumpswap_pool_missing` result permits a legacy lookup;
3. provider, malformed-account, stale-data, or identity errors never silently fall through to another venue;
4. legacy fallback requires an explicit bounded provenance record and revalidates it on chain;
5. generic Raydium scans remain diagnostic only and never select an executable pool;
6. every returned post-graduation snapshot still carries `allocation_eligible=false`.

The registry loader rejects duplicate pools/mints, unverified pairs, non-Raydium surfaces, excessive records, or any record claiming allocation authority.

## Paper lifecycle and shared capital

`PostGraduationPaperEngine` uses the existing Store and Allocator semantics. Synthetic/captured tests now cover both PumpSwap and Raydium-v4 through shared-bankroll reservation -> Store restart -> delayed exact-size fill -> restart -> monitoring -> exit intent -> later settlement -> reconciliation/archive verification. Position sizing, gas/rent accounting, 2-second delay, 1% entry slippage and +15%/-10%/15-minute/<5-SOL exits remain aligned with the existing paper lifecycle.

Prospective post-graduation allocation remains hard-disabled. `test_allocation=True` is rejected in prospective mode, and the verified resolver/legacy provenance cannot bypass that guard.

## Current engineering boundary

The adapter, current-pair identity validation, integer quote mechanics, captured mainnet evidence, synthetic restart-safe lifecycle and shared-capital accounting are now in place for canonical PumpSwap and the explicit legacy Raydium research sample. CI on the latest implementation also skips the base Pump natural-qualification live watcher on stacked-branch pushes so strategy-evidence collection stays on the base branch instead of consuming duplicate CI runtime.

The remaining limitation is historical lineage for legacy Raydium: the current Bzc9 pair is strongly identified and live-read verified, but the old Pump withdraw transaction itself has not been reconstructed from an authoritative historical source. That distinction is deliberately carried in every legacy snapshot and keeps prospective Raydium allocation disabled.

Do not enable prospective PumpSwap or Raydium allocation, merge, deploy, add costs, or change `continuation-v1` without separate authorization.
