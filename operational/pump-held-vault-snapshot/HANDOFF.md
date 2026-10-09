# Pump / Alchemy optimization: held-position vault lookup elimination

Status: **ISOLATED ENGINEERING CHANGE — NOT DEPLOYED / NOT PROVIDER-VALIDATED**.
Source base: `engineering/pons-held-efficiency-20261009` at
`5fb45dad68f22d3e44ead3a88596f201a2e5a268`.
This preserves that branch's autonomous PAPER continuation and Pons quote-wakeup
work. Pump, Pons, the $500 inception and native economic journals are not reset.
Meteora and Ramses remain paused.

## Actual code change

`PostGraduationAdapter.pumpswap_snapshot(..., reuse_verified_pool=True)`
reuses *only* two previously verified PumpSwap vault account addresses in a
process-local, at-most-64-key hint cache. The first held observation performs
the old canonical pool probe, complete account read and block-time read;
only after successful full validation is the address hint admitted.
Subsequent held observations fetch a fresh and co-slot-consistent batch containing
pool, mint, both vaults and fee configuration, plus fresh finalized block time.
The current full pool account is decoded every time, and addresses must match
the hint. Drift evicts the hint and fails closed without a mark or trade.
No economic reserve, liquidity, fee, mutable mint or timestamp is cached.
After restart the first observation re-probes.

Only Pump Survivor **maintenance** passes `reuse_verified_pool=True`. Entry,
requalification, scaling, and normal `pumpswap_snapshot` callers retain
the original full probe. Already-authorized settlement continues to reacquire
its own quote, and the original price/staleness/position cadence is unchanged.
Existing strategy economics, long-hold and high-water/realization/exit rules
are untouched. No provider subscriptions or live endpoints change.

New deterministic regressions in
`tests/lanes/pump/test_postgrad.py` cover first-time full validation, next
held read's one-probe reduction, fresh changed reserves and fee tiers, bypass
disabled for entry, pool-vault drift failure, missing account failure, reset
and cold restart. **These tests have been added but not executed in this
environment.** Before promoting: run the focused tests and relevant
FAST/OPERATIONAL suites with pinned CPython 3.12.14, then a bounded PAPER
read-only provider comparison if separately authorized.

## Conditional resource / cost savings

Alchemy lists Solana `getMultipleAccounts` at **20 CU** per call and PAYG
at **$0.525 per million CU** (2026-10-08). Every successful warm-state
held quote using this path replaces two separate account batches with one.
The cost for one eliminated billed request is **$0.0000105**. Example ceilings
if a single held position is reviewed continuously and each request is
otherwise physically dispatched:

- 72 hours / 5-second marks: 51,840 turns, up to ~1.04M CU
  (~**$0.54**) before restarts/rotations, cache hits, faults or flat periods.
- 72 hours / 3-second marks: 86,400 turns, up to ~1.73M CU
  (~**$0.91**) under the same simplifying assumptions.

These are arithmetic sensitivity scenarios, NOT measured production reduction
and NOT projections of the full Pump provider bill. Session rotation resets
the hint and therefore reduces savings; actual physical method deltas must
be recorded. Native throughput, protective latency, held economics and provider
response size must remain comparable.

## Priority-ranked next savings (not switched by this branch)

1. **Provider-side PumpSwap bandwidth selection.** Reuse the already
   published finite A/B executor, not a new broad stream.
   The captured mixture was 50,331,681 application bytes, including
   27,538,305 successful and 13,400,141 failed PumpSwap WS bytes.
   The replacement gross budget is 40,938,446 bytes for 9,819 successes.
   The equal-byte mean is 4,169.31 native B/success, and the equal-dollar
   mean under current published rate assumptions is 5,837.03 B/success.
   Full native payloads were unmeasured and prior authorized validation
   was BLOCKED by `current_account_headroom_required`.
   Do not enable filtered native production substitution until current
   account-wide admission, canonical parity and latency are proven.

2. **Held-position authenticated quiet-window pricing.** Use existing
   finalized pool/base-vault/quote-vault/mint/fee state changes and complete
   canonical slot coverage to prove a quiet window, then skip HTTP quote
   acquisition only when every relevant pool, fee, token and safety mutation
   is absent. Keep the original 5-second protective loop, never mark or sell
   from old quotes, wake immediately for exit, price-near-trigger, unknown
   account changes, stale proof, reorg, slot gap, scale or extraordinary hold
   renewal. Use one bounded heartbeat <=60s only if safe; otherwise QUOTE_NOW.
   Prove incremental native delivered bytes do not exceed saved HTTP charges.

3. **History acquisition deduplication.** The authenticated Solana app showed
   substantial `getTransactionsForAddress` traffic. Reuse candidate-history
   pages, immutable caches, source timestamps and Current/Survivor demand
   without re-reading identical (address, slot range, cursor, provider)
   pages. Preserve full candidate coverage, ordering, independent
   qualification and original deadlines. Do not replace a 100-CU page
   with N 40-CU individual transactions unless actual coverage and billing
   justify it. Count physical calls and unresolved history gaps.

4. **Cached immutable graduation authority with proof.** For a held position,
   old completed-curve evidence is checked on every quote. Consider
   eliminating those 20-CU account and 20-CU block-time reads only if
   finalized graduation immutability, current mint-supply upper bounds,
   canonical conflict/reorg behavior and exact restarts are verified.
   The current branch intentionally retains these calls rather than
   weakening a legitimate risk guard.

5. **Canonical slot-time reuse / transport sharing.** Reuse authenticated
   locally persisted slot timestamps when exactly bound to the fresh
   finalized account slot; fall back to RPC if incomplete. Keep one owner
   for native finality/control/candidate history and avoid duplicative
   gRPC streams across Pump Current/Survivor. As bootstrap funding closes,
   keep only held position interests while optional broad discovery
   retires, as the continuation branch already prepared.

## Acceptance criteria

Complete exact source/event/account/state/quote/economics parity using
independent fixtures, current/Pump Survivor independence, original
candidate deadlines, no market-universe trimming and no missed best winners.
Measure physical HTTP element counts, Alchemy billed CU and native/WS
bytes, connection/stream admission, p50/p95/p99 provider queue latency,
memory/CPU and adverse protection. Prove native persistence/restarts,
partial/full exits, quote outages, 5x/10x winners, high-water, cost basis
and 72h+ exit recovery without synthetic fills. Fail closed on incomplete
evidence. No provider work, deployment, live money, subscriptions or strategy
changes are authorized or performed by this engineering patch.

Rates: https://www.alchemy.com/docs/reference/compute-unit-costs
and https://www.alchemy.com/pricing .
Prior empirical and blocked A/B evidence:
`operational/pumpswap-provider-bandwidth/BASELINE.json`,
`operational/pump-alchemy-capability-executor/REPORT.md` and
`operational/pump-alchemy-provider-validation/REPORT.md`.
