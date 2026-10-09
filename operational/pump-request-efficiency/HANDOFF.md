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

### Held Current and Survivor: immutable lineage versus fresh economics

`PostGraduationAdapter.held_graduation_handoff` caches only successful
immutable *completed-curve* identity (mint, creator, source pool and Mayhem flag)
for 60 seconds within the current RPC adapter. On first observation,
expiration, clock rollback or restart, it re-fetches and validates the
actual completed curve and mint. Immutable field disagreement invalidates
the cache and fails closed. Entry/qualification/scaling use the original
full authentication path and are never allowed to treat a held hint as
qualification evidence.

`pumpswap_snapshot(..., reuse_verified_pool=True)` reuses only previously
verified base/quote vault *addresses*. It still re-fetches the finalized
current PumpSwap pool, token mint, both vault account bodies and fee
configuration **every protective tick**. It verifies current pool identity,
fresh vault addresses, reserves, token owner/supply, Mayhem mode, virtual
reserves and fee schedule. A cold probe that changes before its second
fresh batch, or a warm hint that no longer matches, fails closed.
No quote/price, liquidity, holder concentration or mutable fee is cached.

Both paths have bounded 64-key caches local to the current adapter. No
database migration, new signing/authorization, subscription, worker, or
second economic owner was added. Current and Survivor retain existing
five-second monitoring, mark/high-water, partial and final exit, risk,
flow, deadline, and pending-exit behavior. Survivor's ordinary entry/scale
path remains independent; Current's continuation requalification and
concentration probes are not weakened.

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

For ONE funded PumpSwap position, one full old held review logically
consumes 3 `getMultipleAccounts` and 2 `getBlockTime` = **100 CU**,
ignoring identical-cache hits. Under the new path, after the cold
baseline: 1 fresh multiaccount group per review (20 CU), one identity
revalidation group each 60s (20 CU), plus up to one clock read per
review and revalidation if the exact-slot finalized plane has not
caught up (20 CU each). **No** price or protective update is skipped.

| Scenario: 5-second cadence over 72 hours, 51,840 turns | Held-quote CU | Modeled USD |
|---|---:|---:|
| Before, every logical method physically billed | 5,184,000 | $2.72160 |
| After, no exact-slot local timestamps ever available | 2,246,400 | $1.17936 |
| After, exact-slot local timestamps always available | 1,123,200 | $0.58968 |
| **Potential reduction** | **2,937,600 to 4,060,800 CU** | **$1.54224 to $2.13192** |

The 4,320 identity revalidations at 60-second intervals are included.
Extra cold probes after adapter rotation, service restarts, failed reads,
cache hits already supplied by the pre-existing immutable layer,
different active-position counts and varying activity reduce realized
savings. Concentration/flow, candidate discovery, historical acquisition,
provider-delivered streaming bytes, quote-response payloads and latency
are **not** included in this narrow model, so these dollars are NOT
an all-in 72-hour provider cost or verified invoice saving.
The source may run longer than 72h where explicitly allowed by existing
policy; this patch creates no forced-exit timer or position expiration.

A self-contained offline regression module
`tests.lanes.pump.test_postgrad_read_efficiency` is registered in the
FAST/OPERATIONAL test registry. It checks method counts, unchanged
`buy_quote` and `sell_quote` math with fresh state, changed reserves and
fees, cold/warm vault drift, missing/invalid account input, a changed
graduation creator, 60-second revalidation, restart reset and exact-slot
clock fallback. GitHub CI is the only available full source test executor
in this session; absence of a completed passing CI receipt means **NOT
VALIDATED**. No test claimed pass until the runner actually completes.

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
