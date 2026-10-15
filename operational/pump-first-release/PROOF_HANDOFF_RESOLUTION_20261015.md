# Durable proof handoff: observed dependency and scoped repair

Branch: `repair/consolidated-startup-followup-20261014`, draft PR133. Root is the
single integration/test/runtime owner. This handoff records O10 and the supported
offline repair; it does not establish readiness, capacity or acceptance.

## Exact source and validation boundary

O10 executed `c281058e5993bd7a35190010e9398c982ca7cd1e`. The proof-handoff repair
is committed as `ab621aba7d33245aa0090a24ef1dc07338f2b5b0`. Its combined integration run passed 246 tests in
102.915s. An earlier preliminary implementation passed12 delivery tests in2.137s;
that preliminary scope was superseded and is not final-source validation. These
runs overlap and must not be summed as distinct cases. The
original selected scheduling regression failed before the repair; an earlier
selection outside FAST was correctly rejected, not a test pass.

Source review then found that the new exact-publication path needed the original
provider-accounting-before-publication fence. Final executable
`76785b2a3e814ad456f3ad2d22befdcd68cb8a93` completes `flush_delivery()` before its
separate exact-publication owner admission. Both affected modules (history
separation/refinement) passed 69 tests in 17.908s on that successor. The first
class-as-module runner command was rejected before execution (exit 2), not an
application failure. The earlier 246-test result belongs to ab621aba and is reused
only for unchanged dependencies. No full FAST or normal-operation release PASS
is claimed. See the small [evidence index](evidence/proof-handoff-resolution-20261015.json).

## What O10 actually measured

The run stopped after 905.291s with STARTUP_LIMITATION, original 300-second
readiness FAIL, funding closed and zero acceptance minutes. Both current native
workers reached STOPPED/reconciled and exited 0; their matching TERM/wait records
independently support native-worker graceful stop. Accepted source-frame drainage
remains unavailable. Earlier RECOVERY_REQUIRED outcomes remain unchanged.

From the first both-native-reconciled sample at 540.101s to the final full sample
at 898.469s, the single-generation interval was 358.367866s:

| Progress | Slot units/s | Meaning |
| --- | ---: | --- |
| CONTROL receipt | 4.632112 | Arrival-side proxy, not physical event count |
| Acquisition/join | 2.751363 | Newest joined native block metadata |
| Preparation | 2.745782 | Prepared head |
| Canonical durable | 2.756944 | Durably committed head |
| Retained economics | 2.745782 | Minimum newest stored economic head |
| Raw program cursor | 2.745782 | Stored cursor; **not usable publication** |
| Usable program frontier | unavailable | Actual `program_frontiers` were empty |

Source startup stayed WAIT_FOR_DURABLE_PUBLICATION and never released. Strategy
consumption and qualification readiness therefore remain unavailable. This also
corrects the earlier O9 description: its 2.71478/s raw cursor was labelled a
published frontier, although the true program frontier was empty there too.

CONTROL-to-retained-economics gap grew 970→1,646 slots; evidence market age grew
223.664→366.032s. Matching the measured arrivals alone requires at least
**1.68016× the measured canonical durable rate**, before burst/backlog recovery.
Fixing publication alone cannot supply this missing processing capacity.

Owner callbacks plus checkpoint handoffs occupied 357.556 of 358.368s. Actual
owner-thread CPU was 80.615s and runnable wait 146.770s. Candidate preparation
parent elapsed 105.480s, owner queue 152.326s and callback 98.763s totalled
356.569s; worker preparation CPU/wall overlap parent elapsed and are not added
again. The cgroup averaged 1.704 CPU cores, with 18.191s reported throttling.
These observations do not identify a lock holder, infer GIL contention from
wall-minus-CPU, or prove hardware insufficiency.

Retention took 57.215s outer wall; entered phases were plan 30.017s, transaction
23.541s, housekeeping 0.549s and post 1.966s, with zero unmeasured delta. Even
removing every measured retention-phase wall second would provide only a
1.18549× elapsed upper bound; that is neither a proposed relaxation nor enough
to close the 1.68016× deficit.

## Demonstrated handoff defect and correction

The independent delivery worker FULL-commits coverage receipts while the owner's
fair proof cursor may advance. Delivery previously ACKed the batch and only woke
the independent scan. A completed batch could consequently remain behind that
cursor until a long horizon wrap. In addition, publishing one valid sibling can
repair gap rows and invalidate a later sibling's receipt if contexts are checked
only after each preceding mutation.

The disposable regression uses the actual capture/deliver/ACK and publication
paths: 192 pending proofs, a 64-proof completed consumer batch, and an intervening
owner publication turn. The original path leaves that exact batch pending; the
repair publishes it without a horizon rescan. This establishes a scheduling
defect, not a faithful market replay, CPU share or whole-machine speedup.

The repair adds bounded exact-ID publication (at most 64 unique SHA identities),
while retaining the ordinary fair scan. It re-reads pending rows and validates
all selected current receipt/unconsumed contexts before gap mutations in one
canonical transaction. The source ACKs durable consumer output, preserves the
accounting fence, then submits exact publication through a separate existing
priority-2 owner admission. No second writer, queue or outbox is introduced.
Intervening generation, binding, control or external-gap changes remain stale;
failed transactions preserve pending proofs, and exact mode never moves the
background cursor. Cancellation after ACK retains receipts and pending work for
restart. BUSY retains the existing durable retry semantics; an immediate exact
latency guarantee is not claimed when that exact admission is deferred.

A separate bounded Pons discriminator measured the actual retained active
population: two candidates, 31,487 body bytes, one `History.rows()` SQL statement,
0.001262084s thread CPU and 0.001254614s wall. This single warm call does not
support a material active-history population-scan correction; no further Pons
query or speculative reporting optimization follows from it.

Stopped-state inspection found 16,719 pending proofs, including 4,342 current
ones. The two first-current receipts matched at the final sample's gap boundary;
disconnect gaps were created only afterward. Older sampled receipts remained
stale. These facts support the dependency investigation but do not prove when
the publisher visited every proof or permit stale evidence to pass.

## Preserved state, usage and remaining blockers

Retained post-review verified head 10,965, cash $1,000, zero obligations in all
eight recorded categories, historical $500 preservation and all four active v1
policy bindings. Of 1,635 sampled canonical outbox identities, 1,629 were ACKed
with authentic receipts and six remained preserved pending; this is a bounded
cohort, not a completeness census. Compatible source/configuration rollback
restored `66f85d61bf4d3ba9a01efdc0e9eb68949419bda8` without a database rewind.
PAPER was inactive/disabled, Restart=no and funding closed.

O10 accounted 2,896 physical starts including four native openings, 11,462 RPC
elements, 403,292 RPC CU, 638,701,359 native bytes and 16,779,722 HTTP bytes.
Uncertain exposure was separately retained. Frozen-model cost was $0.308739273255;
provider invoice charges are unavailable. This documentation step made no
provider requests, authoritative writes, tests or deployment changes.

Sustained Pump capacity, startup release and usable evidence remain unresolved.
Pons had CURRENT admission samples, but the empty portfolio did not exercise
complete quote/USD protection within three/five seconds. Original SQLite BUSY,
Pons READONLY INSERT and native replay semantics remain separate questions.
The later failed backup remains unusable; the applicable older recovery proof
does not resolve storage failure. Full-process-group backup freezing remains
incompatible with an unproven uninterrupted-protection claim. No cleanup,
timer change, additional copy or backup repair is implied here.

Next: use the existing risk-based diagnostic gate and fresh safety preflight to decide the
next guarded measurement. It must measure actual startup release/usable frontier
and the remaining pre-persistence capacity deficit separately. No unchanged retry
or promotion to normal PAPER follows from this offline scheduling fixture.
