# Proof handoff observation O11: startup still blocked

O11 executed `76785b2a3e814ad456f3ad2d22befdcd68cb8a93` once, funding closed.
It stopped after 902.896590s with STARTUP_LIMITATION and the original
300-second readiness **FAIL**. Acceptance minutes: zero. The exact-proof handoff
and accounting-fence repair has not demonstrated whole-pipeline improvement.
Earlier failed observations and RECOVERY_REQUIRED results remain unchanged.

## Current-run processing evidence

The 368.617984s interval from 529.586467s to 898.204452s contains 72 full samples
after both native workers declared reconciliation. Source startup never released.

| Progress | Slot units/s |
| --- | ---: |
| CONTROL arrival-side receipt | 4.625385 |
| Acquisition/join | 2.403572 |
| Preparation | 2.392721 |
| Canonical durable | 2.384583 |
| Retained economics | 2.400860 |
| Raw program cursor | 2.395434 |
| Usable publication | unavailable; actual program frontiers empty |

CONTROL is an arrival-side proxy, not physical event count. The
CONTROL-to-stored-economics gap grew 1,226→2,046 slots; market evidence age grew
279.024→454.642s. Matching these arrivals alone requires **1.93970×** the measured
canonical durable rate, before surplus for bursts or backlog recovery. Raw
cursor progress does not establish publication, qualification or consumption.
Different market input and startup windows prevent a controlled speedup or
regression comparison with O10.

Owner callbacks consumed 351.046706s and checkpoint handoffs 15.502345s,
together 366.549051s of the interval. Actual owner-thread CPU was 77.529502s and
runnable wait 162.220031s. Preparation parent elapsed 76.476896s, candidate owner
queue 174.642164s and callback 98.055473s totalled 349.174533s; preparation worker
CPU/wall overlap the parent measurement. The cgroup averaged 1.727529 cores and
reported 24.681296s throttling. These overlapping measures are not additive
proof of a lock holder, GIL contention, device saturation or hardware inadequacy.

Maintenance callbacks accounted for 84.331503s wall/18.596009s CPU. Nested
retention measured 73.063862s outer wall: plan 37.874009s, transaction 30.502620s,
housekeeping 0.881335s and post 2.198752s, zero unmeasured delta and one yield.
Those phase timings do not by themselves justify another behavioral repair.

## Exact current startup dependency

Both first-feed intervals are slot 457159942. Stopped-state inspection found
their exact pending proofs, no canonical unconsumed outbox work through that
slot, **no consumer coverage receipt**, no coverage rows and no program
checkpoint. Required coverage remained missing at the final retained sample's
timestamp. Disconnect gaps added later are separated from that sample and do
not explain away the earlier missing coverage.

This differs from O10, where the sampled first-current proofs had durable
consumer receipts. Exact publication after a completed consumer batch cannot
publish a proof the consumer never received. Source review identified capture
and publication sharing the same volatile cursor: advancing publication can
also move capture past an undelivered proof. This is a scheduling-contract
defect to reproduce and correct offline, preserving the existing durable
pending rows, one consumer and one canonical writer. The current dependency
receipt does not reconstruct every live cursor visit. The integration owner's
source-contract work is ongoing; this result does **not** mark it repaired or
attribute the full pre-persistence deficit to it.

## Native stop, accounting and provider scope

Matching current-run health, TERM/wait records and exit codes independently
verify both Pump and Pons STOPPED/reconciled/exit 0. This proves the current
native workers stopped gracefully; accepted source-frame drainage remains
unavailable. Monetary reconciliation is a separate result.

The retained post-review completed 7,260 bounded queries in 2.116139s total
(0.327280s measured SQL time), verifying head 11,290, cash $1,000 and zero in all
eight obligation categories. Historical $500 accounting and all four active
paper-opportunity-access-v1 bindings were preserved. Among 1,700 sampled current
canonical identities, 1,670 had authentic ACKed receipts and 30 remained
preserved pending. This sampled cohort is not a full evidence census.

Pons admission samples were CURRENT with maximum observed queue wait 1.243886s.
The flat funding-closed run did not exercise held quote/USD protection within
the original three/five seconds. Provider suitability and unobserved paths
remain separate from these admission observations.

Usage was 2,695 physical starts including four native openings, 10,180 RPC
elements, 352,062 CU, 662,156,128 native bytes and 15,925,279 HTTP bytes. Uncertain
exposure remains separately recorded. Frozen-model cost: **$0.28430627400**;
provider invoice charges unavailable. No open provider reservations or receipts
remained in the post-review.

Compatible rollback completed at 08:05:41 UTC to
`66f85d61bf4d3ba9a01efdc0e9eb68949419bda8` and the saved configuration, without
database rewind or evidence deletion. Retained service state: inactive,
disabled, Restart=no and funding closed. This documentation step performed no
queries, tests, provider requests, source changes or deployment.

## Next decision and independent blockers

Two bounded Pons discriminators rejected additional corrections. The actual
retained projection queries already use transition-first plans: the original
first-row query consumed 0.000128895s CPU and the caught-up tail 0.000057540s.
Their EXISTS alternatives returned identical ordered rows without a material
benefit. No SQL change or follow-up query was justified.

One opt-in offline case passed in 0.195s, comparing 32 synthetic session-hit
calls against an authentic 4,096-row retained reuse ring. Adding a fixture-only
sequence index changed CPU 0.020405→0.016698s, retained identical rows and the same
265,000 quantized VM steps, and increased writes 544,768→806,912 bytes. At the
retained last-278-second event rate of 14.7044/s, the original measured work
projects to only 0.00938 CPU core (1.39% of the owner-reported 0.674-core Pons
process); the index saves about 0.00170 core. These local/warm extrapolations
do not establish full-machine improvement. The index was rejected as material;
no production Pons correction was added from either discriminator.

First finish the capture/publication scheduling contract's focused reproduction,
correction and stale/cancel/restart validation. Then assess the remaining
pre-persistence deficit using the retained owner/preparation measurements; no
unchanged live retry or capacity PASS follows from this result.

Original SQLite BUSY, Pons READONLY INSERT, native replay semantics and complete
held-position protection remain open on their own evidence. The later failed
backup is unusable; the applicable older recovery reference is not a repair of
backup storage. Full-process-group backup freezing remains a separate
uninterrupted-protection blocker for autonomous operation. No storage cleanup,
timer change or backup workaround is implied.

Exact retained artifact hashes and measurement scopes are in
[the evidence index](evidence/proof-handoff-result-20261015.json). No full release,
sustained capacity, one-hour acceptance or continuous-operation PASS is claimed.
