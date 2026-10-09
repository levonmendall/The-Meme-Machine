# Pump / Alchemy: request-level operating-cost optimization

**Disposition: ISOLATED CODE CANDIDATE — NOT DEPLOYED OR BILLING-VERIFIED.**
Source base: `engineering/pons-held-efficiency-20261009` at
`6c534b06797cc0b299d59da28be50b15bcd38665`.
No market orders, funded PAPER positions, Alchemy traffic experiment,
credential change, native WebSocket/Yellowstone switch, service restart or
inception change occurred. Meteora and Ramses stay paused. Previous
Pons quote-wakeup and exceptional-winner work remain in ancestry unchanged.

## Audited real provider expenses (2026-10-07 UTC Solana app)

Authenticated Alchemy app `9bin99s96t7ga5e9` showed:

| Request category | Reported CU | Unit weight | Derived method requests |
|---|---:|---:|---:|
| `getTransactionsForAddress` | 645,600 | 100 | 6,456 |
| Pump/PumpSwap WebSocket logs | 537,033.5636 | byte-priced | not inferred |
| `getMultipleAccounts` | 154,520 | 20 | 7,726 |
| `getSlot` | 121,360 | 20 | 6,068 |
| `getBlockTime` | 115,440 | 20 | 5,772 |
| `getTokenLargestAccounts` | 36,200 | 20 | 1,810 |
| `getProgramAccounts(V2)` | 41,360 | 20 | 2,068 |

This day includes engineering and provider trials, not just autonomous
production. The observations are *not* a valid daily bill forecast.

Original program-wide WebSocket economics remain required for ordered Pump
Current/Survivor evidence. In the previously authenticated partial size
sample, the proposed broad native replacement was not cheaper under normal
market assumptions and failed full evidence coverage; do not change feeds.

Existing `integration/alchemy-acquisition-final-20261008` already deduplicates
physically identical `getTransactionsForAddress` recovery pages, rolling
coverage, immutable `getBlockTime`, network validation and shared candidate
history. This change deliberately does **not** duplicate those fixes.

## What this branch changes

### Held Current and Survivor: one coherent fresh economic batch

After inspecting the authentic Pump program IDL, the old 60-second
completed-curve creator cache was **rejected and removed**. Pump's admin CTO
may legitimately change the creator post-graduation; preserving the old
fresh checks requires observing a current creator every review.

The optimized `pumpswap_snapshot(mint, ..., held_curve_inline=True)`
includes the **current completed bonding curve account** inside the SAME
finalized `getMultipleAccounts` request as the PumpSwap pool, mint,
base-vault balance, quote-vault balance and fee configuration. It reruns
`graduation_handoff` for that exact slot on every held review. Source
creator, completion status, source pool, mint, Mayhem mode, reserves,
token authority and current fees remain fresh and coherent. A change to
creator is observed immediately; incomplete graduation or a mismatching
pool fails closed without a price/mark/exit.

Only the two previously verified vault **addresses** are retained in a
bounded 64-key in-memory hint cache; all account *contents* are always
read fresh. On the first read, an extra pool-address probe discovers the
two vault addresses. A pool change between cold probe and batch, or a
warm vault-hint mismatch, invalidates the hint and fails closed. A
restart or adapter rotation starts with the original cold probe.

Current and Survivor held positions use the single-slot batch.
Entry, candidate qualification, independent Survivor graduation/scaling
and unheld economic observations retain the old full proof path.
All existing five-second protective checks, native accounting,
high-water/partial exits, demand and concentration checks, worker
priority and owner/deadline semantics remain unchanged.

No new signing, API permissions, queue, subscription, service, database
or provider endpoint were introduced.

Pump official IDL and docs confirming mutable creator via authorized
instructions:
https://github.com/pump-fun/pump-public-docs/blob/main/idl/pump.ts
https://pump.fun/docs/bonding-curve

### Exact finalized block-time reuse

The existing authenticated canonical Solana evidence plane may answer
`getBlockTime` **only** when its published frontier covers the *identical*
fresh finalized RPC account-context slot and the stream-receipt time for
that exact slot is unambiguous. The returned value must be an integer,
positive and not in the future. Otherwise the original authenticated
`getBlockTime` request is made. This optimization never fabricates a
market timestamp, moves a decision boundary or relaxes quote freshness.
It is connected for Pump Current active curves and postgraduation, and
Pump Survivor held snapshots.

## Auditable modeled held-position savings

Alchemy Solana method prices checked in the published CU schedule:
`getMultipleAccounts=20 CU`, `getBlockTime=20 CU`.
Listed PAYG conversion: **$0.525 / million CU**.

For ONE funded PumpSwap position, the old full review logically
purchased three `getMultipleAccounts` (60 CU) and two `getBlockTime`
(40 CU), total **100 CU**, before existing cache hits.
Under this branch the warm held quote buys ONE fresh six-address
`getMultipleAccounts` (20 CU); zero or one exact-slot `getBlockTime`
(0–20 CU), depending on authenticated shared finalized coverage.
The source completed-curve creator and token identity are included
in that live batch; there is **no 60-second static creator cache**.
The first quote after restart/rotation still buys one 20-CU pool probe.

| Scenario: continuous 5-second reviews over 72h (51,840 turns) | Held-quote CU | USD at published rate |
|---|---:|---:|
| Old logical method cost, before cache hits | 5,184,000 | $2.72160 |
| Warm optimized, exact-slot time unavailable | 2,073,600 | $1.08864 |
| Warm optimized, exact-slot time always available | 1,036,800 | $0.54432 |
| **Potential reduction** | **3,110,400–4,147,200 CU** | **$1.63296–$2.17728** |

These are **source-level physical-method sensitivity estimates**, not
actual measured CU or billing reductions. Extra cold probes after
process/session rotation and restart, retries and coverage loss can
reduce savings. If the pre-existing immutable cache already served a
method without a billed provider request, this patch cannot save that
charge again. The model excludes concentration/flow reads, candidate
history, the original WebSocket economics feed, transaction-history
repair, response bytes, connection charges and latency. No price,
high-water update, continuation requirement or exit is skipped. This
patch adds no new holding maximum or forced sale, but does not override
any original position deadline or inactive exceptional-winner policy.

The new module `tests.lanes.pump.test_postgrad_read_efficiency`
covers cold/warm request counts; same-slot current curve creator and
completion-state changes; changed vault reserves and fee tiers; live
vault drift (including between the probe and batch); missing accounts;
restart re-probing; exact-slot timestamp fallback; and exact local
`buy_quote`/`sell_quote` parity. It is registered in FAST and
OPERATIONAL. **It is not certified passing until the CI result is
reported for the exact final source SHA.**

## Bigger costs and why they are not suppressed indiscriminately

1. Historical repair: expensive 100-CU `getTransactionsForAddress`
   pages were already de-duplicated in the integrated acquisition branch.
   More calls should only be eliminated against exact acknowledged
   `(endpoint, family, address, slot range, cursor, lineage)` coverage.
   No missing-window promotion, top-N truncation or candidate starvation.
2. Always-on Pump/PumpSwap WS: native-body replacement was 9,497.75 B
   mean in only four below-floor samples, versus ~5,837 B conditional
   dollar break-even. No end-to-end economic parity. Preserve existing
   WS until a genuinely cheaper architecture proves equivalent discovery,
   economics, order, status and recovery.
3. **Current concentration work**: `runner._monitor_positions` invokes
   `_postgrad_concentration` every five-second postgrad holding review.
   It uses a compact filtered token-account program scan or a full
   largest-accounts fallback to calculate the original Current signal
   and continuation protections. This remains intact. A lower-cost
   future solution could build a complete canonical mint-specific
   holder-balance state with initial immutable census, bounded filtered
   account deltas, closure/burn/mint handling, restarts/reorg and independent
   per-tick top-five parity. Without that proof, skipping reads might
   sacrifice profitable exits, scaling opportunities or safety.
4. **Event-driven quote wakes**: the existing Pump/PumpSwap economic tape
   can help only after proofs cover every reserve, token, fee, timestamp
   and risk mutator. The existing five-second protective loop and fresh
   execution quote cannot be replaced with an old mark on a silent feed.
   An inactive wake planner is not billed savings.
5. Candidate admission is **capital independent**; Current->Survivor
   preservation, 5% sleeves, realized-equity compounding, staged winner
   additions and right-tail rules are untouched.

## Production/acceptance decision

Do not merge or deploy this branch solely on static savings arithmetic.
Require passing focused Pump quote/Survivor/Current tests and the suite,
then an independently scoped PAPER provider proof measuring actual
billed CU by method, RPC elements, WS/native delivered bytes, queue/exit
p95/p99 latency and native journal parity. Only claim dollar savings
against an equivalent-coverage baseline including all changed
requests. No market-provider trial was executed in this branch.
