# O13 — owner bottleneck measured; readiness still failed

Executed `10ae127c399279847df908d555eceb1aaf46ef1d`, published under
`7182909711df7442a55d380e8bbcd85ca6ec22c7`, branch
`repair/consolidated-startup-followup-20261014`, draft PR133. The CONTROL-retention
repair is `27f9a19463aa51fdd0daffb084ed4b373642e311`; fixed development-phase
attribution is `10ae127c`. These changes preserve the existing bulk store,
off-owner preparation, historian, independent delivery, exact ACK and publication
mechanisms. All four native bindings remain `paper-opportunity-access-v1`.

The guarded run `20261015-development-phase-10ae127c-094856` stopped at 902.346s.
Original 300-second readiness **FAIL**, `STARTUP_LIMITATION`, acceptance **0**.
Source release was 197.187s; both native workers first reported reconciled at
596.990s. Reconciliation is not qualification readiness or sustained capacity.

| Same-generation post-native interval: 303.481s | Measured progress |
| --- | ---: |
| Shared CONTROL arrival-side proxy | 4.534054 slot units/s |
| Joined head | 2.118748 |
| Prepared head | 2.128633 |
| Durable completed-evidence head | 2.112157 |
| Minimum retained economic head | 2.112157 |
| Strategy-usable program frontier | UNAVAILABLE; no sampled record |
| Arrival minus stored head gap | 1,404 → 2,139 slots |
| Retained evidence age | 312.279 → 478.760s |

These heads use one PID/session/generation and feed floor457193627. They are not
identity-matched event cohorts or an independent market-rate measurement. The
interval still belongs to a failed startup. V2 analysis excludes an erroneous
initial raw-cursor22.225 rate that mixed retained stock; both artifacts survive.
O12 and O13 are not a controlled before/after comparison.

## What occupies the authoritative owner

Exclusive owner callbacks287.265s plus actual checkpoint handoff15.753s occupied
303.017 of303.481 elapsed seconds. Owner thread CPU56.710s and kernel runnable
delay117.963s are separately measured. Unclassified elapsed time is not proof of
a SQLite lock, GIL wait or device saturation. Checkpoint admission-plus-hold80.802s
overlaps these scopes and is not added.

Source callbacks occupied145.165s, including candidate63.593, scout52.519,
publication15.802, CONTROL11.319 and delivery accounting1.932s. Development43.810,
maintenance decisions47.490, retention24.359, delivery capture7.339 and ACK6.047s
are other labels. Child component timings overlap their parent. Candidate owner
callbacks accumulated170.135s queue wait; capture76.289 and ACK35.463s queue wait
overlap other execution and cannot be added into a throughput loss.

The six development phases survived the complete collector path:

| Exclusive development phase | Calls | Wall s | Thread CPU s | Runnable s |
| --- | ---: | ---: | ---: | ---: |
| Selection | 338 | 7.985 | 2.045 | 4.202 |
| Reactivation | 169 | 30.863 | 3.301 | 9.131 |
| Boundaries | 169 | .190 | .077 | .107 |
| Publication | 169 | .181 | .070 | .142 |
| Plan | 169 | .775 | .238 | .360 |
| Original transaction exit | 169 | 2.689 | .311 | .749 |

No failed/unmeasured phase calls occurred in this interval. Economic storage
separately took32.788wall/6.658CPU/12.642runnable seconds for26,703 records in641
bulk calls, with zero scalar fallback. SQLite COMMIT counters recorded1,680
calls/23.991wall/3.214CPU seconds. These overlap owner callbacks. Preparation
took47.666wall/18.478CPU seconds in165 completed batches; its boundaries differ
from164 completed candidate owner calls. Neither isolated function speed nor
these overlapping aggregates establish a whole-machine correction.

Cgroup CPU averaged1.695cores, with16.540s throttling. Process averages were
Pons.690, source.535, Pump.316 and supervisor.095cores, plus small helpers. Pons
logical reads86.935GB versus physical reads1.159MB do not identify a SQL culprit
or device bandwidth requirement. No hardware sufficiency/insufficiency verdict.

## Corrections and rejected interventions

The actual retirement/publication fixture proved loss of required CONTROL
receipts101/102/103 and valid publication2→0. The repaired hybrid retention
contract protects unread current tails and exact older proof boundaries without
pinning unrelated history. In O13's stopped-state exact predicate check, both
current program children retained their exact sealed CONTROL member. This
supports the narrow dependency-preservation result, not complete publication.
See [the implementation and tests](CONTROL_MEMBERSHIP_RESOLUTION_20261015.md).

Current required canonical receipts/ACKs and the exact last parent-slot proof
still remained pending. Shutdown-created gaps were later than the final sample
and must not be used to explain the earlier readiness failure. There is both
pre-persistence accumulation and a genuine usable-history/publication limitation.

The same16 retained reactivated identities were inspected read-only. They were
active at the last sample but expired before inspection; no deadline was renewed.
Full current cold metadata used .001492CPU seconds total versus .000344 for an
existence query; every cold lookup returned absent. This rejects the proposed
metadata substitution as a material remedy for this slice. It does not reproduce
the live promotion/demotion transaction or prove its cost. An initial helper
AttributeError from assigning a read-only clock property was preserved; V2 removed
only that assignment. No job DML, archive read, provider or application write.
Earlier Pons materialization/predicate variants also remained immaterial and were
not installed. Candidate Plane reporting is not shared-capital replay; its main
thread path cannot explain the separately measured Pons executor CPU.

Matching the observed arrival proxy requires2.146646× durable progress before
backlog recovery. Under an illustrative fixed-work-mix serialized-time model,
eliminating *all* reactivation would yield only1.113×. Removing required work is
not permissible, and this is not a forecast. The model therefore rejects that
isolated stage as a sufficient solution. Existing preparation offload and bulk
commits are active; implementing them again is not an alternative.

**STOP — INSUFFICIENT EVIDENCE FOR A JUSTIFIED THROUGHPUT CORRECTION.** No new
performance behavior or unchanged live retry follows this result. The missing
fact is the actual operation and blocking mechanism within reached
promotion/demotion/rolling planning and concurrent Pons executor work. Coarse
phase timing, COMMIT totals, cached stopped-state reads and runnable delay cannot
choose between computation, SQL, synchronization and scheduling corrections.
The smallest useful next evidence is a predeclared, bounded operation/thread
attribution trace covering those actual paths, with a discriminator for each
specific intervention. Another rate-only run or synthetic full-capacity claim
would not answer it. Incomplete historical full-machine replay remains closed.
Standing issue134 still applies; no routine approval gate has been introduced.

## Preserved safety and remaining independent boundaries

Both current native workers reported STOPPED/reconciled/exit0, with matching
SIGTERM and no SIGKILL. This verifies native-worker stop only. Global accepted
source-frame drainage remains UNAVAILABLE; the controller's drained=true is not
substituted for it. Original RECOVERY_REQUIRED outcomes remain unchanged.

Bounded post-review:9,098queries/3.455s, no failed/unavailable check entries,
head11938, $1,000.00 cash and zero eight-category monetary obligations. Only the
323-event new suffix was rederived. Historical$500 fingerprints and all four
active policy bindings remained exact. The sampled canonical union retained374
identities:347 exact receipt/ACK and27 pending preserved. This is not a global
delivery census or atomic cross-database snapshot. Future preflight anchors11938.

Compatible source/config rollback to66f85d61 completed without state rewind;
run evidence hashes remained exact. PAPER inactive/disabled/Restart=no/funding
closed. The restored old finite diagnostic unit must never be started unchanged
as continuous service. The tested engineering source remains published.

Usage:2,723 physical starts including4 native openings;10,527 logical elements;
362,372CU;675,543,096 native and15,480,445 HTTP delivered/accounted bytes.
Uncertain exposure285,212,672 native and16,777,216 HTTP bytes remains separate.
Frozen-model cost$0.291124655640; provider invoice UNAVAILABLE. No open receipts or
reserved bytes remained. Managed-route acquisition ran; held quote/USD deadlines,
provider saturation capacity, original BUSY and READONLY faults are not repaired
or proven by absence of recurrence in the exercised subset.

Backup remains independently blocked. Fresh10:23UTC metadata: canonical DB alone
18,249,457,664bytes, volume available16,710,615,040bytes. Including only that DB and
the original5GiB reserve leaves a **minimum6,907,551,744byte shortfall**, before
other state/WAL. Failed backup remains unusable; older applicable recovery proof
was preserved/reused. No cleanup, copy, purchase, quota or timer change occurred.
The timer stayed active; its freshly reported next event was Oct16 04:03:11UTC.
Process-wide backup freezing is separately incompatible unless a verified common
cut/snapshot design preserves original protection deadlines. No bypass is applied.

Exact-source validation reused:289 affected integrationPASS74.644s;79 maintenance
PASS27.956s (includes8 contract tests). No new complete FAST/OPERATIONAL campaign,
full release PASS, one-hour minutes or autonomy claim. Source-level guards and
all strategy/economic protections remain intact.

[Hashed evidence, counters, limits and exact artifact locators](evidence/development-phase-result-20261015.json).
