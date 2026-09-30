# Bounded archive-overlap proposal: allocation design gate

PAPER ONLY. This is an isolated proposed implementation, not production repair,
promotion, qualification, successor freeze, Stage E or Stage F authority.
Previous stop records and every reviewed blob/mode remain unchanged.

## Exact scope and state change

The pinned ArchiveFlight is one logical future/receipt: attach rejects a pending
receipt. MaintenanceRuntime.turn performs one fresh owner decision. The final
archive_commit_slice_and_plan already selects a successor in that admission;
the maintenance coroutine submits it without another owner admission.
This proposal explicitly replaces the one-carrier state with current plus
lookahead. It does not claim preservation of the former concurrency invariant.

The proposed carrier has no third slot, at most one executing preparation,
no new executor, and the existing two-process pool and single SQL owner.
Current full membership and original full commit plan remain charged after
a 512-row slice. Exact identities exclude current membership in native
owner-serialized SQL selection. Readiness and commit authority are separate:
lookahead can become authoritative only on owner promotion, after current
acknowledgment and completed-worker observation. Promotion copies the original
submission clock; native episode/service clocks are untouched.
For a short current receipt the proposal uses an extra planning-only archive
admission, credited with zero durable progress. Arbitration itself is unchanged.

## Source-derived limits and accounting

Pinned production source is dc08f9064cf5e37b63f383f52aa709d0afc1723f,
tree 68736cf664169dee665762019800bf87ca0f1f67.
The exact replacement files and original blob IDs are separately versioned.
apply.py accepts only a fresh detached treatment worktree and records its staged
tree, actual source SHA-256 hashes and patch SHA-256. Modified treatment is
explicitly NOT production-byte-identical. Control production remains unchanged.

Source facts:
- archive snapshot maximum 1,000 records; target 4 MiB encoded input;
  first-item exception bounded by MAX_SINGLE_SNAPSHOT_BYTES = 20 MiB;
- native ingestion body allowance 16 MiB; service worker body target 16 MiB;
- archive SQL commit slice 512 records; retirement bound 1,000 unchanged;
- source message/prepared/commit batch 16 MiB; dispatch 96 MiB/64 messages;
  source batching maximum 8 messages; decoder pool 2 processes;
- raw chunk inflation bounded by 16 MiB per chunk and raw chunk cache 4 MiB;
- owner/execution/clock allowance 3/3/3 s; worker lease 15 s;
  residence 240 s; recovery 120 source-seconds; slack 1,000 records.

The draft partitions logical reservation 750/250, rather than adding another
1,000-record/16-MiB allowance. It partitions nominal encoded targets 3/1 MiB,
encoded hard reservation 15/5 MiB, and body allowance 12/4 MiB.
It charges full identities, full compact plans, retained snapshots, receipt
metadata, references, Python container size and serialized worker arguments.
The child argument dictionary is cleared before return; the separate parent's
argument snapshot is cleared only after Future completion. Original full plans
remain retained through receipt acknowledgment. Telemetry is bounded at 64
carrier events. Native decoder scratch, raw cache, serialization/compression
copies and executor residual results require their existing pool-wide budgets;
one active preparation alone is not proof that all copies have been released.

Additional experimental checks include a 20-MiB retained-parent object check,
serialized-argument checks, and body/file checks before appending worker output.
The proposed FILE_CAP arithmetic includes 512 bytes of per-record overhead.
That overhead is a proposed conservative guard, not a source-proven bound on
all provenance serialization. No claim of a complete physical-memory proof or
passed aggregate-resource gate is made.

## First design conflict and bounded confirmation

Even with no lookahead, the initial current slot has only 12 MiB body allowance.
A native-valid single record containing 13 MiB of ordinary padding fits the
unchanged 16-MiB ingestion and archive worker limits. Its compressed hot snapshot
can fit the 4-MiB target. The draft worker rejects it with
overlap_worker_body_reservation, instead of preserving native per-file behavior.

A one-record boundary check compares native publication/commit with this proposed
allocation, on separate fresh databases/processes. It is a short deterministic
capacity test; it has no source stream, source floor injection, reader pressure,
long horizon or recovery experiment. It cannot consume a material execution or
establish prefix recovery. The fixture checks integrity and absence of false
durable progress on rejection.

If confirmed, this is the first design blocker: accepting the draft would change
native single-file admission even when overlap is absent. No fallback/second
allocation variant, changed limit or material pressure run follows this gate.
The proposal does not establish that every possible bounded overlap is impossible.

The broader focused A-H suite is versioned for review but is not invoked after
this design blocker. Its presence is not a test pass. No entire preflight suite,
source-floor removal or broad qualification is invoked.

## Preservation and budget

Reviewed evidence: run 36771603217, artifact 11124508037;
ZIP SHA-256 485a522b8e1ab820674528905fa87e953cb444eade31c77635f5ba8cce2cdec6;
original COMPARISON.json SHA-256
f8601ccc5316bf0a3885a1d4979a28271f2f16a17b1b04f9c6d775e46b4b94d3.
The gate independently downloads and hashes those exact bytes.

A separately scoped request predeclares control then treatment, .165 in both,
and the unchanged 1,334-frame/360.18 source-second configuration. Its material
launch flag is false. There is no pressure harness invocation in this workflow.
Before/after gate: 4/6 consumed, 0 added, 2 remain. A blocker hard-stops execution.

M1 remains separate and unmodified. The preserved preflight is 1 failure,
2 errors, 46 skips in 1,062 tests. No test weakening or completion-protocol repair.
Reduced ACKs remain diagnostic only. Stage E RED; Stage F NOT STARTED.
