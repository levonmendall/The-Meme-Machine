# Finite next action, not a provider authorization

Status: **UNSUPPORTED_40_BLOCK_RANGE**, measured once on 2026-10-08.
The existing account explicitly rejects more than ten blocks for this method.
See [the capability handoff](../pons-40-block-capability/HANDOFF.md).
The range-comparison authorization is consumed; no repeat or additional scan
follows. Prospective seven-day accumulation is the recommended next path under
separate operational/provider authorization. No complete seed exists; deployment,
epoch changes and production PAPER writes remain unauthorized. The combined
latency-certification blocker remains in source.

## Recorded nonempty historical range comparison (closed)

The executed callable is
`engineering.pons_history.capability.compare(disposable_history, existing_governed_provider, first)`.
Importing it makes no request. The caller must supply the original canonical
Robinhood authority and governor, a disposable PonsHistory, and separately
authorized provider usage. The repaired
`engineering.pons_history.run_capability` executor bounds the underlying physical
transport, including nested calls. It opens no alternative connection or authority.

Use the preserved authentic V2 graduation at block **56,882,711** as a locator:
first **56,882,701**, last **56,882,740**. Original captured transaction:
`0x1d49a28a0e27ecdd952094c4aaa9de2105253a2d62924ec36e761c13e43493c9`.
Re-fetch canonical boundaries and event witnesses; the old fixture is not a
current membership assertion. If this exact historical range is unavailable or
empty, return an evidence constraint instead of trying thousands of other ranges.

| Resource | Hard bound / stop behavior |
|---|---|
| Duration | 45 seconds, including governor waits and response work; inherited deadline can shorten it |
| Logical elements | 64, checked before every batch |
| Physical HTTP attempts | At most 32 actual attempts, including failures and nested witnesses; all retries zero |
| RPC methods | Chain/genesis/header reads, one pinned historical factory `eth_getCode`, standard `eth_getLogs`, receipt witnesses |
| Ranges | Four ten-block factory OR-topic requests vs one forty-block request over exactly the same interval |
| Response size | Existing 2,000,000-byte client ceiling; cap failures count and stop |
| Response payload upper bound | 32 × 2,000,000 bytes read = 64,000,000 bytes; no excess-byte probe; headers/TLS/unread bodies excluded |
| Request payload | Small fixed filters and witness hashes; record actual attempted payload bytes using native telemetry |
| Diagnostic CU | ≤6,400 at 100 per dispatched element; billed CU/dollars unavailable without independent account data |
| Temporary stock | ≤128 MiB on the existing attached volume, no root capture or full-state snapshot |
| Concurrency / pacing | One worker, original 0.5-second shared admission and fairness; lower priority 50 |
| Economic state | Disposable evidence database only; no portfolio or production database migration |

The callable verifies chain/genesis, boundaries before/after, exact canonical
event identities/order and full returned rows against the four preserved queries,
plus canonical event headers and native receipt membership. It requires a
nonempty sample. Conflicting duplicates, silent truncation relative to baseline,
page envelopes, changed boundaries, oversized/dense responses, missing results,
account range rejection or any budget exhaustion produce no successful support
receipt. Every dispatched request counts even on failure.

Successful comparison supports only this provider fingerprint, factory filter
and **forty-block maximum** under the complete-array method contract. It does not
establish all future densities, larger ranges, economic completeness, account
throughput or seven-day parity. Manager queries still retain adaptive safeguards;
any unsupported filter/range response remains incomplete. No automatic batch
widening or account-tier change follows. Ordinary runtime stays ten/forty blocks.

The owner authorized exactly one comparison with these ceilings. It completed
with an explicit forty-block rejection: 7 physical attempts, 14 logical demands,
13 dispatched elements, 1,300 diagnostic CU, and 3.242420 seconds including
worker shutdown. The four ten-block responses contain one authenticated
graduation. No successful support receipt or widening was published.

## Then choose prospective acquisition or a phased backfill

If the account is ten-block-limited, prospective acquisition is recommended.
Enrollment stores an original canonical header and starts at the next block.
The complete domain matures only after its inclusive seven-day ceiling has moved
past enrollment. Original Current opportunities still require their existing
authoritative prerequisites and global certification; no guard is bypassed.
Survivor opportunities before maturity are unavailable. Provider cost is spread
over the week, not eliminated. New-graduation economic histories are accumulated
continuously, so future ordinary outages need only tail catch-up.

The following backfill proposals remain historical contingencies, not the next
recommended execution or authorization. This account's forty-block gate failed.
No independently measured complete-population economic envelope supports cold
backfill over prospective accumulation. The implementation remains resumable.

1. **Capability gate above: completed, unsupported.** Retain ten-block queries;
   do not repeat, purchase a tier or switch providers.
2. **Density/economic sizing gate, new authorization required:** a fixed 400-block
   canonical factory interval containing an authentic graduation, with complete
   receipts and one bounded 40-block economic slice for each discovered eligible
   pool. Proposed overall ceilings: 600 seconds, 2,000 logical elements,
   1,000 physical attempts, 200,000 diagnostic CU, 128 MiB response payload and
   256 MiB disposable storage, at unchanged physical pacing. No candidate cap:
   stop incomplete when an envelope is exhausted, retaining every identity and
   its outstanding work. The aggregate payload/storage limiter and live executor
   for this gate are **not implemented/reviewed**, so it is not yet runnable.
3. **Complete census, separately authorized after gate 2:** freeze an exact
   timestamp domain. For the planning 5,985,970 blocks, default ten-block empty
   census needs 897,897 elements / 149,650 attempts / 89.79 million diagnostic CU,
   plus at most about 40 boundary/identity setup elements and event witnesses.
   A finite proposed outer ceiling is 1,100,000 elements / 180,000 attempts /
   110 million diagnostic CU / 96 hours / 1 GiB read payload / 2 GiB durable
   evidence stock. The witness density measured in gate 2 must first justify this
   envelope; exceeding it stops incomplete and retains progress. Forty-block
   support projects 224,476 elements / 37,413 attempts / 22.45 million diagnostic
   CU for the empty census, but the authorization must use measured event costs,
   not this empty lower bound. No executor implementing these aggregate ceilings
   is claimed to exist.
4. **Complete economic reconstruction, new finite envelope:** enumerate every
   relevant pool and exact graduation-to-frontier interval from the independent
   census, then price its observed event/header/receipt/sender density and native
   replay writes. Sum all cohort work without selecting winners or capping the
   candidate universe. Publish a request/time/storage envelope before dispatch.
   No defensible numeric whole-population ceiling exists from the available short
   tapes; this gate must remain blocked until census/density evidence exists.

The outer limits are proposed stop ceilings, not predictions that complete
acquisition fits them. In particular a 1 GiB census payload allowance can be
inadequate for dense event receipts, and Stage B can dominate all Stage A savings.
Partial work can be retained and reviewed without certifying readiness. Dollar
cost and actual billed CU are unknown, not zero. No new subscription, Droplet,
external DB or paid-plan change is included in any gate.

## Combined proof after real warm state

The former 900-second/10-GiB/60,000-element proposal is superseded as an immediate
next action. It still lacks a seed, reviewed enlarged executor and authorization.
The range comparison cannot substitute for it.

Once a real seed is verified, a separately reviewed combined executor can restore
it without historical reconstruction and spend its envelope on concurrent work:
complete Pump Current evidence, PumpSwap Survivor continuity, complete Pons
Current evidence and Pons Survivor eligibility/progression; actual native
position-equivalent maintenance; shared-capital contention; sustained drainage;
original deadlines; physical provider bytes/capacity and CPU/RAM/WAL/storage.
The previous handoff measured 3,656,638 B/s over active native delivery. Keeping
its 600-second concurrent sample minimum projects about 2.194 GB at that mean,
before startup, recovery, additional positions and density variation. At the
previous conservative twice-peak rate, the same 600 seconds require 6.297 GB;
an additional assumed 60 acquisition seconds and 512 MiB headroom total about
7.464 GB. A conditional 8-GiB envelope could therefore be smaller than 10 GiB
**if** genuine warm startup fits 60 seconds and that rate/stream reserve remains
adequate. Neither condition is established on a real seed, and no such executor
has been reviewed. This is a cost illustration, not an authorized proof or a
replacement of the previous completeness/sample requirements.

A finite combined ceiling should follow measured warm restoration and queue
arrival/drainage rates. It may be materially smaller and more informative than
10 GiB because Survivor backfill is absent, but no sustained proof duration or
resource total is justified by these synthetic tapes. Genuine concurrent evidence
must clear the blocker; it stays until those properties are demonstrated.
