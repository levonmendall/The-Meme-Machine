# Astra bounded archive-overlap design blocker

ASTRA_REVIEW_READY: OVERLAP_DESIGN_OR_SAFETY_BLOCKED

The isolated proposal failed the design gate before any material pressure run.
Its fixed initial 750/250 allocation rejects a native-valid single record even
when lookahead is empty. No alternate implementation or further execution follows.
Budget: **4/6 consumed; 0 added; 2 unused**. PAPER ONLY.

## Confirmed conflict

A valid finalized record has a canonical body of **13,631,744 bytes**.
Production ingestion and the service archive worker retain their **16,777,216-byte**
allowance/target. The selected compressed snapshot is only **59,842 bytes**.

On separate fresh databases/processes in one CI job:

| Deterministic one-record boundary | Reference | Proposed allocation |
| --- | ---: | ---: |
| Prepared and archived | 1 | 0 |
| Hot records at endpoint | 0 | 1 |
| Published archive files | 1 | 0 |
| Database integrity | ok | ok |
| Provider calls | 0 | 0 |

Prototype error: `EvidenceUnavailable:overlap_worker_body_reservation`.
Its current-body allocation is **12,582,912 bytes**, reserving the other quarter
despite no lookahead. Before preparation it retains one membership identity,
750 reserved record units, 62,930 parent-object bytes and 60,069 serialized
argument bytes. Rejection publishes nothing and credits no durable progress.

This is a change to native single-file admission, which the assignment forbids.
The proposed allocation cannot pass as written. It does not prove that every
bounded overlap design is impossible or that overlap would fail the .165 prefix.
Adding another allocation/fallback variant after this blocker is outside this stop.

## Code and resource accounting

Execution source: **cba6d17c318f049cf602cfdf8329aef83b8f3163**.
Diagnostic tree: **cc09c06d39b8ab8d9d55e0d9e8175e06141fd58c**.
Isolated modified treatment tree: **7d276678c4ffabaff71a592183eb7dbd0495b236**.
Patch SHA-256: **fa3255ca7f01aaf5a6d61e2637f22c5863839b605bee89f4c3a1eb1a373af750**.

No modified treatment commit was created. The actual staged tree, exact replacement
contents, original blob IDs and all five modified source SHA-256 hashes are retained
in BINDING.json and the artifact. Independent SHA-256 calculation matches all five
CI-reported modified source hashes. Treatment is explicitly not production-byte-identical.

The patch changes only the treatment worktree's carrier/runtime, snapshot exclusion,
snapshot forwarding and maintenance submission, plus an experimental worker module.
All **1,195** reviewed preexisting blobs/modes, including canonical production files,
workflows, arbiter, source batching, leases/deadlines, policy and previous stops,
remain identical on the diagnostic branch.

The proposed state is current plus lookahead, at most one executing preparation,
no third slot, and the existing two-worker pool and one SQL owner. This explicitly
replaces the former one-carrier invariant. Full current membership and the original
compact plan stay charged after partial slices; owner SQL excludes exact identities.
Promotion retains the original worker submission clock and does not reset native
debt/service origins. Short receipts use a planning-only archive admission with
zero durable-service credit.

DESIGN.md derives the 1,000-record, 4-MiB nominal/20-MiB first-item encoded,
16-MiB body, 512-record commit, 4-MiB raw-cache and unchanged source/pool limits.
The draft partitions 750/250 records, 3/1 MiB nominal encoded input, 15/5 MiB
encoded reservation and 12/4 MiB bodies. It includes full plans, references,
snapshots, receipt metadata, Python container and serialized-argument checks,
and retains reservations through receipt acknowledgment. It clears child input
arguments before return and parent arguments only after completed Future observation.

These are **proposed checks, not a proved aggregate physical-resource envelope**.
The raw FILE_CAP per-record overhead assumption and all process-pool residual,
serialization and compression copies lack completed validation. No extra full
1,000-record/16-MiB allowance was allocated; no resource-safety pass is claimed.

## What executed, and what did not

[CI run 36782892873](https://github.com/levonmendall/The-Meme-Machine/actions/runs/36782892873),
job **110117261872**, attempt **1**, runner **GitHub Actions 1000026402**.
Ubuntu 24.04.5; Linux 6.17.0-1022-azure; Python **3.12.14**;
SQLite **3.45.1**; websockets **17.1**; four affinity CPUs [0,1,2,3].
Both boundary samples report load [0.4351,0.1777,0.0664].
Peak RSS was 123,276 /98,340 KiB; fixture work elapsed 0.416 /0.317 seconds.
These costs include different accepted/rejected work and are not recovery-cycle,
worker-utilization or matched-pressure comparisons. Full environment/limits remain
in the artifact. No archive process pool or concurrent pressure work ran here.

The resource compatibility gate failed. The separately versioned 14-test focused
A-H suite was **not run or claimed green**. Actual overlap, disjoint promoted commit
authority, transaction/worker/resource maxima, changed floors/pins/gaps, faults,
idempotent retries, lease transitions, shutdown/restart and native arbiter progress
therefore remain unqualified for this proposal. M1 was neither repaired nor exercised
as a substitute for its separate completion qualification.

The .165 source-owner floor was preserved in both predeclared prospective material
configurations. **Neither pressure arm launched.** There are no new first-window
episodes, native deadlines, open obligations/remaining times, LIVE recovery,
source/retirement advancement, retained-age, source-lag, WAL/checkpoint or observer-cost
measurements to report for a material endpoint. Absence of a run is not prevention
of excess debt or resolved obligations. Recovery under .165 is **not evaluated**.
No cycle timing or proof of actual overlap is established by this boundary fixture.

## Durable evidence and hard stop

[Artifact 11128617306](https://github.com/levonmendall/The-Meme-Machine/actions/runs/36782892873/artifacts/11128617306),
1,058,384 bytes, ZIP digest
**26f68c9ce884534c0e6ff39e689628a4c6eb3e015bb1b8caaee5a37b8f9764d4**.
It retains the exact patch, source identities, gate results, configurations,
environment, code, stop, and independently rehashed previous evidence ZIP/original
COMPARISON.json. The committed CI-log projections preserve measured results without
pretending their hashes equal original artifact-file hashes.

Prior evidence remains run **36771603217**, artifact **11124508037**,
ZIP **485a522b8e1ab820674528905fa87e953cb444eade31c77635f5ba8cce2cdec6**,
original COMPARISON.json
**f8601ccc5316bf0a3885a1d4979a28271f2f16a17b1b04f9c6d775e46b4b94d3**.
Both old byte digests were independently checked by this CI before the boundary
tests. Reviewed measurements and previous stop records remain preserved.

Facts: native acceptance, prototype rejection, unchanged source/tree identities,
zero false durable progress on rejection, both integrity checks ok, no material
execution. Inference: this fixed allocation changes a required native per-file
behavior. Uncertainty: full-copy resource proof, safety/overlap and .165 recovery
remain unestablished; no universal repair/minimality conclusion follows.

FOLLOWUP_STOP.json revokes further diagnostic execution in this scope.
No retry, alternate variant, promotion/merge, successor freeze, canonical Stage E
or Stage F. Reduced ACKs remain unapproved for production.
M1 and the preserved **one preflight failure, two errors and 46 skips** remain separate.
Any accepted implementation still needs deterministic/full-control resolution,
qualification reconstruction and wiring, assembled-source verification, applicable
new <1% observer evidence, exact successor freeze and canonical Stage E.
