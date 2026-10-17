# Native commit-stage observations

This is the first executable publication slice of
[the closed economic cohort contract](closed_economic_cohort_measurement.md).
It does not close an economic population or prove market processing capacity.
There was no live-provider execution, AWS dispatch, financial write or deployment
for this component.

The fixed isolated entry enables the collector after its existing image and
authenticated sizing checks and actual `NativeRunnerPorts` construction, before
opening native histories. Ordinary production constructors have no collector.
The binding retains the actual authenticated receipt scope, executable commit
and tree, process ID, original sizing-receipt hash, actual parent transport
session and hash of its bounded `SourceReference` registry. A transport session
is explicitly **not** a canonical source generation. The registry describes the
available authenticated transports; it does not attribute each economic row to
a physical request or prove complete source membership. Session/registry/process
changes invalidate measurement. Fresh sizing receipts retain the original
scope/source binding and do not restart these counters.

The hooks observe these existing native writes:

| Counter | Native write | Meaning |
| --- | --- | --- |
| `history_event_rows` | New `CandidateHistory.events` insertion | Native retained history row publication |
| `history_reference_rows` | First `canonical_event_refs` insertion | A validated canonical reference publication, separate from a copied history row |
| `qualified_decision_rows` | New qualified `decisions` insertion | Durable native decision row, without allocation authority |
| `refused_decision_rows` | New refused `decisions` insertion | Durable negative decision row |
| `pons_generation_dispositions` | Actual `Plane._audit` transition insertion | A transition linked to its existing candidate ID/generation, native kind/reason and transition sequence |
| `pons_candidate_consumptions` | First `result_consumption` insertion | Original candidate-generation consumption after unchanged native generation/completion checks; never a source callback ACK |

The transition count is not a count of unique candidate generations. Several
dispositions can refer to one generation. History references, retained event
rows and decisions are independent populations and must not be added to infer
unique source economics. Repeated physical insertions after native retention
are row publications, not a new global uniqueness proof. Unchanged duplicate
native inserts contribute no new row receipt. Native Pons claims, supersession,
censoring, completion, decisions and consumption checks remain unchanged.

`CandidateHistory.transaction` retains its original BEGIN/COMMIT and nested
SAVEPOINT/RELEASE/ROLLBACK boundaries. Each successful nested release merges
bounded metadata into its parent; rollback discards it. Only a returning outer
COMMIT emits a receipt, with clocks sampled afterward. An externally opened
transaction cannot produce a FULL receipt when a helper releases its savepoint.
`Plane.transaction` retains its original no-change ROLLBACK and changed COMMIT.
No additional transaction, SQL statement, fsync or provider acquisition is made.
The measured source-history path still commits its original 64-row batches.

Each connection retains at most 16 frames and 128 tracked row records per outer
transaction. It retains fixed counters and rolling hashes, not row payloads or
a row queue. Each record accepts at most eight bounded scalar fields (256
characters/512 UTF-8 bytes per string). The shared reducer permits at most 16
active stores and uses nonblocking lock acquisition. A closed owner unregisters
its store; repeated native owner restarts do not retain all old connections.
Overflow, contention, unexpected reducer failure, uncertain commit outcome or
ownership loss latches `measurement_loss` and `UNKNOWN`; native work still
commits/returns or raises its original native error. An observer failure after
COMMIT never retries or rolls back committed economic work.

The existing progress JSONL is byte-for-byte unchanged. Its existing first/last
returned progress samples and the terminal receipt retain bounded snapshots.
If these optional snapshots alone would exceed the existing 65,536-byte receipt
bound, only the optional fields are omitted and measurement loss is latched;
the original fields, byte guard and native execution are preserved. Missing
snapshots mean UNKNOWN. There is no persistent measurement journal, restart
reconstruction or authenticated commit-clock recovery. The in-memory hash chain
is a diagnostic summary, not a signature or an independent SQLite durability
attestation.

`source_economic_events`, source publication obligations, verified source ACKs,
unique candidate generations, all-consumer completion, economic lambda/mu and
economic backlog remain null. Cohort closure and complete Pons pool-universe
closure remain UNKNOWN. No source FULL/ACK hook, Solana complete-scope witness,
Pons full-pool hydration/census or external-head population join is implemented
in this slice. Candidate progress alone cannot discharge those dependencies or
authorize PAPER operation. Held protection, fills and settlement remain under
the original isolated harness's UNEXERCISED/false-authority reporting.

Validation uses actual temporary native SQLite databases, original native
methods and an actual anonymous parent/child transport fixture, with offline
physical I/O only. The initial 14 new cases passed in 0.247 seconds. The affected
native/default selection passed 133 cases in 8.164 seconds. Three additional
post-COMMIT reducer-failure, Plane COMMIT-failure and exact receipt-bound cases,
together with the actual source lifecycle tests, passed 48 cases in 3.945
seconds. These are focused component proofs, not live throughput or full release
suite results. A separate final handoff records the frozen source and any later
review corrections.
