# Independent proof consumption: coordinated scheduling correction

Executable `1385d289524b014b4142f53230f93c109d344931`; implementation `b0c30beab4ddba802b3152e7360c3321a2334be8`.
Branch repair/consolidated-startup-followup-20261014; draft PR133. Root is the
single integration, testing and runtime owner. Pons retained-data checks and
backup source review ran independently without competing tests or provider work.

## Demonstrated cause and selected correction

O11's exact current first-feed proofs were pending but had no consumer receipts,
although no canonical outbox work through their intervals remained unconsumed.
Capture reused the independent publisher's volatile cursor. A focused production
capture reproduction moved that cursor beyond two undelivered proofs and failed.
The previous exact post-consumer publication repair remains valid but cannot
publish evidence never delivered to its consumer. This is a shared scheduling
contract defect, not proof that every upstream CPU deficit has the same cause.

Retaining the shared cursor cannot preserve independent progress. Replacing the
outbox, writer or consumer adds unnecessary authority/recovery complexity.
The selected refactor retains the original durable queues and one consumer,
using separate ACKed keyset horizons. Current first-feed witnesses, indexed
existing urgent demand and current native program tails receive bounded
selection; every cycle reserves retained-history progress. A compatible
scope/interval index supplies the new targeted query. No candidate is deleted.

Each batch is capped at64 identities and the existing shared16-MiB input bound.
The consumer FULL commit precedes exact canonical ACK. The original provider
accounting flush precedes separately admitted exact proof publication; mutable
source/session/binding/gap/unconsumed checks remain authoritative. The background
publisher keeps its own fair cursor. No second writer, outbox, consumer, provider,
worker pool, persistent authority or economic migration is introduced.

Relevant changes reopen finished views. An insertion behind an active cursor
marks that horizon for one further traversal after completion; it does not reset
active cursors and starve their tail. Generation/base comparisons precede hint
ACK. Cancellation and restart retain durable pending rows. Overlapping urgent
intervals select an actual covering predecessor. Runtime explicitly requests
publication-only/scan turns; direct consumer callers retain None when no writer
work exists. Verified receipts are not rewritten merely for publication.

## Focused proof and limitations

The original publisher-cursor and urgent-priority reproductions failed before
correction. Peer review found overlapping-interval and behind-cursor invalidation
edges; both have regressions and are fixed. The earlier combined run's3 failures
are preserved; its existing assertions were retained. Final two history modules:
78PASS/19.076s. Final affected shared-path run: **287PASS/110.673s**, including the
actual startup rehearsal, canonical batching/closure/retention and source guards.
Imported test classes overlap; these are scoped passes, not fullFAST/release or
faithful market-replay/capacity proof. No tests or deadlines were relaxed.

A bounded indexed-window fixture with64 then4096 unrelated intervals measured
200 quantized SQLite VM steps for capture in both populations; the covering seek
was below one100-step quantum. This supports avoiding unrelated-population scans
in that fixture, not a worst-case constant-time interval guarantee or a whole-
machine speedup. No speculative second interval index was added.

O11 remains readinessFAIL with arrival4.625385 and canonical durable2.384583 slot
units/s over368.617984s, gap1226→2046 and evidenceage279.024→454.642s. Matching
that interval needs1.93970x durable progress before burst/recovery headroom.
Actual usable program_frontiers were empty. Owner wall occupancy366.549s,
productiveCPU77.5295s, runnablewait162.2200s and processgroup1.72753cores overlap;
they neither identify a lock holder nor prove hardware inadequacy. The serial
candidate preparation/queue/owner path remains the measured throughput boundary.
Do not extrapolate this scheduling correction into a2x capacity claim.

Three Pons discriminators rejected production changes: retained history rows and
already transition-first projection SQL were immaterial; a fixture-only audit
index saved only about0.00170 projected CPU core while increasing writes. The
opt-in test is preserved separately; no production Pons index/query change.

## Guarded verification and independent blockers

The new exact-source observation asks whether the current startup proof dependency
releases and where actual required evidence then accumulates. It is a changed,
causally supported test, not an unchanged retry or historical controlled capacity
comparison. Fresh financial/native/pending-proof/ownership/access/recovery,
resource/provider and backup-nonoverlap checks remain mandatory. Existing
controller, timing, fundingclosed, provider rates, protection and storage guards
are unchanged. No diagnostic minute counts toward acceptance. Reaching an
unexplained unchanged blockage is a stop, not permission for another repetition.

Backup storage remains short even if known redundant failed-point links were
removed; no evidence was deleted or new storage purchased. Existing backup code
freezes the whole PAPER group through bulk copy, validation and sync. A credible
separate correction captures a coordinated common cut, pins SQLite snapshots and
required immutable inodes/bounded mutable bytes, then resumes workers before bulk
copy. It requires bounded owner leases/expiry, correct cross-store commit/ACK
boundaries and retained-WAL/storage limits. The current backup has no authoritative
remaining quote/USD deadline-slack contract, so a merely shorter freeze cannot
prove protection compatibility. No backup/timer changes or bulk copies occurred.
This source-reviewed architectural boundary and physical space are both open.

OriginalBUSY, PonsREADONLY INSERT, global accepted-frame drainage, full replay
semantics and held quote/USD protection remain separate. Current O11 native
workers STOPPED/reconciled/exit0 and financialhead11290/$1000/zero obligations
were independently checked; historicalRECOVERY_REQUIRED and historical$500
remain intact. The installed stopped rollback is66f85d61 until fresh cutover.

Exact logs/hashes are in [the scoped evidence](evidence/proof-selection-resolution-20261015.json).
O11 evidence remains in [the original result](PROOF_HANDOFF_RESULT_20261015.md).
