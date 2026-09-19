# Robinhood research foundation

This is an isolated, incomplete protocol foundation for The Meme Machine. It runs
locally and in GitHub Actions. There is no Render service or deployment. There is
no signer, transaction submission, shared $500 allocator, or natural-trade policy.

Run deterministic and captured regressions:

```sh
python -m unittest discover -s robinhood_tests -v
```

Run the bounded read proof where the authorized secret is available:

```sh
python -m robinhood_research.probe
```

`MM_ROBINHOOD_READ_RPC_URL` must contain the complete HTTPS RPC URL. Do not place it
in a config file, command argument, Git commit, or report. The isolated Actions
workflow reads this exact repository secret. There is no schedule. A push bearing
`[robinhood-read-proof]` to this dedicated branch triggers one bounded read job.
The workflow has contents-read permission and never calls Solana providers.

## Multi-source Robinhood observability

The read plane now supports independent provider redundancy without changing strategy
authority:

- `MM_ROBINHOOD_READ_RPC_URL`: existing authenticated primary RPC.
- `MM_ROBINHOOD_QUICKNODE_RPC_URL`: optional independent QuickNode secondary.
  Standard read-only `eth_*` requests may fail over only after a provider/capability
  failure. Provider-specific methods such as `alchemy_getAssetTransfers` remain
  pinned to the primary.
- `https://rpc.mainnet.chain.robinhood.com`: official public RPC, diagnostic-only;
  it is never an automatic evidence or decision fallback.
- `wss://feed.mainnet.chain.robinhood.com`: official sequencer feed,
  observation-only. It tracks liveness, sequence gaps/conflicts and feed timestamps
  but cannot qualify, authorize, fill or settle a paper position.

`python -m robinhood_research.observability_probe` performs one bounded comparison
of the primary, QuickNode, public RPC and sequencer feed. A push containing
`[robinhood-observability-proof]` runs the same proof in Actions when the QuickNode
secret is configured.


## Implemented boundaries

- `provider.py`: read-method allowlist, wrong-chain guard, sanitized errors,
  per-scope accounting, bounded retries and terminal 429 behavior.
- `evidence.py`: immutable evidence hashes; receipt-reconciled bounded block/log
  ingestion; duplicate elimination; cursor/log atomicity; fail-closed gaps/reorgs.
- `protocols.py`: strictly decoded synthetic Pons candidate layouts; Pons V1/V2
  and other speculative origin classification; exact Ethereum V4 PoolKey ID;
  graduation requires matching factory state, hook registration and initialization.
- `directional.py`: 5/10/30/60s descriptive flow/breadth/acceleration features,
  explicit missing fields, state freshness and immutable point-in-time evidence.
- `outcomes.py`: enrollment freezes evidence before future observations; 15/60/
  300/900s outcomes, sampled MFE/MAE and tail hits, missing exits and missing paths.
  V1/V2, prioritized/natural and synthetic/captured cohorts are never pooled.
- `paper.py`: independent reservation, delay, entry, monitored exit intent,
  unavailable exit retention, proven transition, settlement and restart recovery.
  Native policy and real quote adapters remain unavailable; only synthetic paper
  decisions exercise the lifecycle. Quotes are net of pool fees; gas is separate.
- `liquidity.py`: synthetic bin mutation/share/fee conformance and prospective
  range proposals; fixed 60s outcome interface; 35bps minimum research hurdle.
  Both failed and passing cases remain measurable. No LP allocation authority.

## What is NOT implemented or certified

The Pons layouts inherited from predecessor code are candidates, not current ABI
verification. Real Pons decoding and graduation routing deliberately fail closed.
V1/V3 and non-Pons V3/V4 have discovery/classification interfaces, not full executable
venue adapters. Pools.trade provenance is not verified. No reserve/fee/tax curve
quote is claimed from generic AMM arithmetic. No live strategy thresholds exist.

Ramses has **no verified deployment address or ABI in this branch**. `RamsesAdapter`
always rejects raw state/mutations. The synthetic fee-rate and share accounting
harness is not Ramses mechanics and must never be reported as a Ramses observation.
Its supplied-bin reserves exclude separately accrued fee balances; its projection
uses equal quote-value capital per proposed bin. Exact Ramses mint/burn rounding,
variable fee transitions, claims, token ordering, fee-only mode and counterfactual
pool-impact replay remain unresolved. Uniswap LP allocation is disabled.

## Finality and point-in-time correctness

Every evidence record retains event time **and actual observation time**. Current
foundation admission requires finalized records. Historical finalized data can be
indexed, but cannot be backdated into a prospective 5s-fresh quote. Captured mainnet
proof shows finalized state lagging latest by more than five seconds. A production
short-horizon observer still needs a separately reviewed sequencer-confirmed tape,
append-only reorg invalidation and later finalization; relaxing timestamps or
calling delayed finalized data a prospective observation is forbidden.

## Retention and resource policy

| Dataset | Retention class | Enforced bound |
| --- | --- | --- |
| Immutable decisions, lineage, outcomes, paper journals | Retain forever within a closed study | 10,000 total records default; stop new writes/admission at capacity; export before a new study |
| Discovery logs and coverage proofs | Bounded history per study | Same hard row cap, max 32KiB per record; no silent deletion |
| SQLite DB | Bounded study | 16,384 pages (64MiB with default 4KiB pages), 2MiB page cache; rollback journal; synchronous FULL |
| Open/settled paper position state | Latest state plus immutable transition journal | 100 positions per experiment; total journal row and DB bounds still apply |
| Repeated identical unavailable exits | Aggregate/coalesce | No new journal row for unchanged reason |
| HTTP payload | Ephemeral | Max 2MB per response; 10s timeout |
| Block-by-hash cache | Latest N, ephemeral | 128 entries, each HTTP response bound applies |
| Provider accounting | Ephemeral per bounded session | Max 32 scopes; default 80 session and 40 per-scope attempts; retries consume budget |
| Certification ingestion batch | Ephemeral until committed | Max 32 blocks, 2,000 receipts, 1,000 logs |
| Feature/warmup/replay events | Ephemeral | Max 10,000 events per call |
| Forward ticks | Bounded history | Enrollment through 900s + declared tolerance; DB cap applies |
| Mainnet probe artifact | Retain 30 days | One bounded ten-block capture, max 1,000 logs |

This is a bounded-session design, not an unlimited unattended collector. No existing
evidence is deleted. If storage fills, stop and export/review the study. Financial
records remain intact. Per-pool quotas protect unrelated pools from one busy pool;
the session cap remains an explicit resource ceiling, not a throughput guarantee.

## Next causal work

1. Obtain verifiable current Pons factory/curve/hook ABI and matching deployed
   implementation/proxy identities, then add captured raw-launch and raw-graduation
   replay before enabling real Pons decode or quotes.
2. Resolve real-time confirmation semantics without future leakage, implement
   receipt-confirmed acquisition and finalization/reorg invalidation, then collect
   natural forward samples before choosing a policy.
3. Verify Ramses Robinhood deployment, ABI/source and exact accounting; replace the
   permanently gated adapter only after captured per-bin economic replay passes.

Do not alter the Solana experiments to make any of these steps easier.