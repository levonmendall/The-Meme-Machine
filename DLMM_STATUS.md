# Meteora DLMM mechanical paper foundation

## Revision and authority

- Exact starting PR #2 head: `6403621c21ff4c02046dc787354e0cf04f52e70d`.
- Branch: `feat/meteora-dlmm-paper-foundation`, stacked on
  `feat/post-graduation-pumpswap-raydium`, never PR #3.
- Exact final implementation SHA: `bbc7879a65f8bf2870b5ea75ef78eeb72d0d437a`.
  This status-only follow-up changes no implementation. The PR description and
  final handoff record its exact review-head SHA (a file cannot embed its own
  content-addressed Git commit hash).
- Allocation remains **disabled**. No signing, submission, deployment, merge,
  paid provider, second bankroll or strategy-threshold change.
- **Mechanical implementation and deterministic tests complete; authentic
  nonempty mainnet swap/fee attribution remains unproven.** Do not declare the
  full acceptance matrix complete or start allocation/strategy research yet.

## Implemented boundary

`dlmm.py`: verified finalized pool/mint/vault/bin decoding, Q64.64 prices,
dynamic input fees, exact-input bin traversal, structural pool scout, shared RPC
budget/cache and bounded on-chain indexing fallback. API identities are rechecked
against chain identities. The Data API is not an execution source.

`dlmm_paper.py`: isolated synthetic/captured replay, shared-capital reservation,
first-class durable liquidity positions, per-bin shares/inventory/fee growth,
monitoring, exit intent, withdrawal, exact-size residual liquidation, SOL settlement
and restart reconciliation in the existing Store. Pump reservations/positions and
DLMM occupations consume the same $500 genesis. Reserved capital is not cash.
Pump's unchanged allocator also respects LP exposure during isolated shared replay.

`dlmm_tape.py`: reconstruct a bounded finalized swap-only interval from a known
starting state, complete signature census, authenticated instruction/event identity
and the ending account bundle. Forward-calculated totals and terminal state must
match. Ending state never backfills earlier economics. Non-swap mutations, unknown
instructions, exact-out, host fees, missing history and ambiguous same-slot ordering
are unresolved. A verified interval resumes from its durable prestate/cursor after
lost acknowledgment. Old interval evidence can verify history but cannot yield a
fresh executable mark: the current-state TTL remains 20 seconds.

The normal prospective Pump loop does not instantiate Replay or allocate DLMM.
`prospective_reserve` always rejects; Replay checks Store mode at entry boundaries;
Store reconciliation rejects prospective LP state and an enabled authority flag.
There is no configuration override. The standalone monitoring scheduler handles
existing replay exposure before discovery and defers discovery while it exists.

## Deterministic test mechanics and accounting

- Fixed 0.1 SOL, two initialized adjacent SOL-side bins, excluding active bin;
  explicit SpotOneSide distribution (flat quote-value weights).
- This deliberately avoids active-bin composition fees and token acquisition at
  entry. No initial token inventory is given away. Both SOL=X and SOL=Y are tested.
- Fixed 60-second exit horizon; no rebalance or optimization.
- Hypothetical augmented pool: add virtual shares, replay identical external
  exact-input orders, and independently evolve real and counterfactual pools.
  Their traversals/outputs may differ. This is not an on-chain position.
- LP fee growth excludes protocol fees and uses integer share/claim rounding.
  No APR/time-based earnings. Fees remain assets until withdrawal/liquidation.
- Entry gas: 150,000 lamports (three 50,000-lamport transactions: account creation,
  wrap, add). Exit gas: 200,000 (remove/claim, residual swap, position close,
  unwrap/account close), charged even if a stage can be combined or skipped.
- Refundable occupancy: 60,000,000 position rent + two 2,100,000 token accounts.
  These conservative fixed approximations exceed the pinned SDK's displayed
  0.05740608/0.00203928 SOL constants. Rent is returned only on settlement/close.
  Required bin arrays must already exist; array-creation costs are not omitted.
- Reservation = 164,550,000 lamports. Position basis = 100,350,000; rent =
  64,200,000. Settlement P&L = net SOL returned (excluding rent) minus basis.
  Protocol swap fees reduce execution proceeds, rather than being counted twice.
- Conservation: cash + all reservations + all rent + directional/LP basis =
  initial capital + realized P&L. Settlement IDs remain terminal and cannot reopen.

## Source/version lineage

Official repository `MeteoraAg/dlmm-sdk`, exact commit
`576919e3e4368e542c402f000b4264724f7f23ec`; package `@meteora-ag/dlmm` **1.9.14**;
IDL metadata **0.12.0**. References: `idls/dlmm.json`, Rust `extensions/bin.rs`,
`extensions/lb_pair.rs`, `math/price_math.rs`, and TypeScript `helpers/fee.ts`,
`helpers/bin.ts`, `helpers/u64xu64_math.ts`, `helpers/rebalance/` and PositionV2
claim calculations in `index.ts`.

- `dlmm_idl_subset.json` retains the source hash and relevant exact account types.
- `dlmm_sdk_vectors.json` was generated by executing official TS exports: 40
  price vectors, 6 fee vectors, 144 per-bin swap cases (36 dust cases rejected).
  The optional `tests/dlmm_sdk_oracle.cjs` records source hashes and uses only
  temporary pinned `bn.js@5.2.1` / `typescript@5.0.4` development dependencies.
  No Python runtime dependency was added; no Node service exists.
- `dlmm_official_historical.json` retains official SDK binary fixture bytes and
  hashes, with absent finalized slot/capture time explicitly null. It proves
  decoding, not a point-in-time live lifecycle.
- Program ID: `LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo`.
- Official docs: [formulas](https://docs.meteora.ag/core-products/dlmm/formulas),
  [Data API](https://docs.meteora.ag/developer-guides/dlmm/api-reference/overview).
  Current API endpoint is `https://dlmm.datapi.meteora.ag/pools`; documented limit
  30 RPS. Both this endpoint and the older `dlmm-api.meteora.ag` returned HTTP 403
  here. No repeated retries, paid replacement or API-dependent authority was added.

## Authentic evidence versus synthetic results

- `dlmm_mainnet_eligible.json`: finalized mainnet slot **447850434**, pool
  `J8a3ZKcDZA8HSinuCyjJggU8hnDgwkZKmwH8qDZ9nUcY`, active bin **-2177**, step **25**.
  One atomic account bundle includes mints, vaults, pool fees and available arrays.
  The runtime decoder/scout accepts it structurally without allocation authority.
- Captured-byte deposit -> restart -> withdrawal -> SOL settlement returns
  **-350,002 lamports**, entirely modeled costs plus 2 lamports share rounding.
  There were no invented swaps or fees in that experiment.
- `dlmm_mainnet_interval.json`: slots **447850801–447850871**, complete finalized
  signature census, **zero swaps** in that interval. Forward state continuity
  verifies retrospectively. The original probe rejected it as a current quote
  because retrieval completed 27 seconds after the ending block time. The test
  preserves that rejection and independently verifies historical continuity.
  This is not proof of real swap fee attribution.
- `dlmm_mainnet.json`: authentic negative observation of pool `EtAdVRLF…` at
  slot **447846823**, active bin -78; required active array absent. It remains
  rejected, not rewritten into a qualifying observation.
- Synthetic fixtures cover nonempty single/multi-bin swaps, both SOL orientations,
  fee accrual, one-sided/out-of-range inventory, exact residual liquidation and
  complete settlement. Synthetic RPC wire fixtures exercise the real interval
  verifier, including restart after a real-path swap commit; they are not mainnet.

## Verification and bounds

Required commands: `python -m unittest discover -v`,
`python -m tests.resource_check`, `python -m tests.dlmm_resource_check` and the
existing `python -m meme_machine --mode synthetic ...` connected Pump replay.
Exact results are in `evidence/dlmm_tests.txt`, `dlmm_resource_check.json`,
`dlmm_pump_resource_check.json`, and `dlmm_pump_connected.json`.

All **130** unit tests pass, including all **101** existing Pump/PumpSwap tests.
The DLMM resource run processes **6,001** synthetic orders, settles and reopens the
Store; one atomic write per admitted event, constant three-integer cursor, zero
growing dedup rows. Checkpoint ~36 KB, journal <=4,096 retained rows, DB+WAL <2 MB,
peak RSS <20 MiB; existing cache caps remain 128 entries / 8 MiB. Four active
positions, 100 lifetime orders, <=210 bins per pool, <=64 signature references,
<=16 transactions and <=2 MB interval transaction evidence. No raw swap archive.
Repeated unresolved marks are coalesced to at most one durable record/minute.

This workspace's overlay filesystem reports zero free space; unchanged baseline
tests correctly hit the existing pressure gate there. Local tests used
`TMPDIR=/dev/shm/meme-dlmm-tests` (memory filesystem). No guard was disabled and
no user files were deleted. These are process/retention checks, not evidence of
physical-disk durability or sustained live throughput. CI runs both resource checks
on its normal temporary disk. Optional live jobs remain skipped by the existing
`[qualification-build]` commit marker.

## Remaining acceptance boundary and exact next step

Capture a **nonempty supported finalized swap interval** on a validated SOL pool;
replay it through `dlmm_tape.reconstruct` and compare every traversed bin, dynamic
fee, fee-growth accumulator, inventory and terminal state against chain evidence.
The public RPC methods are accessible; no additional credential is currently
required. The missing item is an authentic supported nonempty interval with full
ordering/mutation evidence, not permission to trade. A richer block-order reader
or LP-mutation interpreter is needed only if the observed interval demands it.

Keep unsupported behavior fail-closed: Token-2022/extensions, farming, permissioned
or inactive pools, output-token fee mode, active limit orders, dust swaps,
missing arrays, exact-out/host-fee swaps, multiple pool transactions in one slot,
and intervening LP/config mutations. Full program-level differential proof of
deposit/share/fee-growth rounding is not claimed from the per-bin SDK quote oracle.

Use `python -m tests.dlmm_live_probe --pool <validated-pool> --output <capture.json>`
for an explicitly bounded read-only attempt. Do not run repeated open-ended probes,
force a qualifying trade, enable prospective DLMM, change Pump policy, merge or
deploy. Finish authentic mechanical fee proof before strategy research or any
request to grant allocation authority.
