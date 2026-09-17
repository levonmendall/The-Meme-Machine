# Post-graduation milestone status

Base branch: `feat/pump-directional-paper` at `a65e2e6d3f827cd748b748b68058529579cdbeb8`.
Stacked branch: `feat/post-graduation-pumpswap-raydium`.

Scope remains read-only/paper-only: Pump.fun completed-curve handoff -> canonical PumpSwap or legacy Raydium-v4 identity -> exact-size quotes -> disabled prospective allocation -> synthetic/captured paper lifecycle using the shared Store/Allocator. `continuation-v1` is unchanged. No signing, submission, deployment, paid provider, live money, DLMM allocation, FOMO, or Robinhood work is authorized here.

The active Pump bonding-curve decoder remains unchanged and still rejects zero quote reserves. Post-graduation handoff uses a separate immutable completed-curve decoder because migrated historical curve accounts can have retired/zeroed quote state. It requires `complete=true`, zero real-token inventory, fixed mint authority/freeze semantics, valid supply bounds, SOL quote scope, and no cashback. Legacy pre-Mayhem 81-byte accounts default missing appended mode fields to false/none only in this handoff path.

## Live evidence

Workflow `35186308858` established the first complete canonical PumpSwap read on mainnet for documented migrated mint `7LSsEoJGhLeZzGvDofTdNg7M3JttxQqGWNLo6vWMpump`:

- derived and observed pool: `GseMAnNDvntR5uFePZ51yZBXzNSn7GdFPkfHwfr6d77J`, matching Pump's official documented pool;
- completed-curve handoff slot: `447716801`; PumpSwap snapshot slot: `447716806`;
- base reserve: `649596913609305` token base units;
- effective quote reserve: `127506693554` lamports;
- live selected fee parts: `[2, 93, 30]` bps;
- exact 0.1 SOL read-only quote spent `100000000` lamports for `502781926495` token base units;
- immediate modeled sell returned `97380002` lamports, a `2619998` lamport round-trip loss;
- zero HTTP failures/retries and $0 public-RPC/infrastructure spend;
- no order, allocation, signing, submission, or live-money authority.

Raw source evidence was preserved as Actions artifact `postgrad-live-35186308858-1`, artifact ID `10481987603`.

The legacy Raydium-v4 sample mint `9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump` produced more than one structurally valid WSOL Raydium-v4 pool. The adapter correctly failed closed with `ambiguous_legacy_raydium_pools`; it did not pick a pool by liquidity or convenience.

The next bounded live diagnostic now records every valid Raydium candidate's pool key, immutable `poolOpenTime`, owner, LP reserve, market/open-orders identity and swap fee, plus the completed Pump bonding curve's recent finalized transactions and any `Instruction: Withdraw` match. This is diagnostic only and performs no candidate selection. The goal is to establish the historical Pump-withdraw -> Raydium migration lineage before allowing a legacy pool identity to become executable evidence.

Deterministic regression coverage includes retired/legacy completed-curve handoff, canonical PumpSwap identity/quote math, Raydium-v4/OpenBook layout checks, shared-capital synthetic lifecycle, and prospective allocation refusal. Prospective post-graduation allocation remains hard-disabled until both PumpSwap and legacy Raydium have captured/live-read identity and quote proof.
