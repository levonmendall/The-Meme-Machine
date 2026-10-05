# Solana and provider incident reference

Classification: **OPERATIONAL_REFERENCE**. This preserves engineering conclusions
from Runs 370, 371, 372 and 375. It grants no entry, market-run, deployment,
certification or profitability authority. Exact historical sources and byte hashes
are in [incident-reference-sources.json](incident-reference-sources.json).
Historical workflow receipts identify observations; they are not runtime gates.

## Run 370: storage amplification, gaps and consistent local reads

The original failure snapshot had 2,061,034,952 hot bytes
(1,908,203,520 database + 152,831,432 WAL). The later checkpointed snapshot was
2,000,011,264 bytes; it is not the earlier failure measurement. That later database
contained 2,202,553 address references for 33,164 distinct addresses. Repeated
address/record strings and indexes occupied 932,081,664 bytes; the records table
occupied another 886,996,992 bytes. The transport was already shared: the problem
was not three physical full-block copies. Large logs still repeated across
transaction/event lineage.

Preserve dictionary-indexed address/record identities, lossless immutable-body
compression, content-addressed log chunks and decoding before original hash
verification. Plain JSON history remains readable; index migration is transactional.
Archive publication must precede hot-payload removal; commit must recheck pins.
Archive-time indexing, bounded cleanup and preservation floors matter as much as
compression. Never solve pressure by discarding active lifecycle pins, weakening
the hard store bound, manufacturing continuity or widening freshness/finality.

The old 64-record archive selection without an archive-time index, twenty-two
candidate interests and broad unresolved gaps prevented useful retirement.
Disconnect had examined old sessions' unsealed receipts. Repair therefore must
retire authenticated covered receipts, prevent contained duplicate gaps, and scope
disconnect fences to the current session. A repaired interval that advanced from
slot 100 to 200 must not reopen at 100; the next gap begins at 201. Before the repair
availability time, historical coverage remains unavailable. Account snapshots do
not attest a continuous interval and must not acquire that authority on restart.

Filter a full block to its authenticated program scope before enforcing the scoped
2,048-transaction bound. Tolerate late notifications from recently retired account
subscriptions. Preserve fixed secret-safe disconnect attribution. Five original
filter-bound failures were reproduced. Twelve generic ConnectionClosedError
closures lacked evidence to distinguish provider close, size rejection or local
backpressure; **their cause remains unknown**.

The scaled 32 MiB reproduction exhausted capacity at simulated second 1,020.
Its repaired counterpart reached second 2,400 without failure. This establishes a
mechanism, not the exact historical failure time. An earlier broad-pressure attempt
was interrupted and must not be reported as a completed test. A stronger synthetic
replay later completed 1,800 simulated seconds in 795.56 wall seconds:
901 messages, 6,269,743,647 source bytes, 129,744 transactions, 65,773 events,
175,987 archived and 175,553 compacted records. All seventeen reconnects produced
fifty-one explicit program gaps that were repaired; all twenty-two candidate leases
expired without discarding the open lifecycle pin. Hot payloads stabilized at 19,530.
Sampled peak hot/DB/WAL bytes were 529,175,040 / 415,182,848 / 113,992,192.
The last 400 simulated seconds declined by 819,200 bytes. Coarse samples do not
replace transaction/checkpoint-boundary peak measurements.

Each lane completed 159 of 174 planned local queries; the remaining fifteen were
inside deliberately disconnected intervals and correctly failed closed. This is
synthetic engineering evidence, not a historical economic counterfactual. Indefinite
repair unavailability or indefinite retention can correctly exhaust any finite
store and stop admission. No finite store promises unlimited preservation.

An authenticated local tape discovered fifty-two Pump candidates, but continuity
gaps blocked the required covered window before the completed-local-read counter.
A direct provider request cannot substitute for authenticated stream activity,
fresh usable health, discovery and completed local reads. Preserve this requirement
when evaluating later operational acceptance; frontier/process liveness alone is
not proof of successful consumer progression. The original Run 370 consumer and
smoke regression obligations remain separately reviewable in the migration ledger.

Concurrent archive cleanup exposed another race: selecting a body and then
decoding its collected shared log chunk outside the same SQLite snapshot.
Both discovery paths must hold one bounded read snapshot through selection and
lossless decode, releasing before acknowledgement, including exceptions. The
regression must demonstrate subsequent unblocked WAL reclamation.

## Runs 371 and 372: responsive receive and deployed-source reachability

Receive/pong handling must stay independent of SQLite ingestion, compaction,
repair and consumer work. Bounded dispatch overflow is an explicit failure, not
permission to drop evidence. A deterministic 23-message burst with a slowed owner
proved the decoupling requirement.

Run 372 still had eight local ping/backpressure closures after 270 messages and
about 1.62 GB because the repaired integration service had not reached both frozen
lane implementations. The lesson is to verify the actual current child import/
implementation path, not merely root tests or an old workflow result. Operational
namespaces replace the old prepared-worktree composition machinery.

Large frames require a bounded 64-frame / 96 MiB dispatch budget, raw-byte receive,
credential scanning and JSON/program filtering away from the event loop. Spawned
decoder children return compact relevant transactions. Shared Pump/PumpSwap
protocol decoding must be strategy-independent and consistent across consumers.
The retained approximately 7 MB-frame regression checks coverage, queue bounds,
event-loop responsiveness and absence of backpressure/dispatch discontinuity.

Run 371 also established Ramses transient-pressure containment: exhausted 429 or
shared admission boundaries defer/censor the individual finalized-frontier poll or
market screen. A partial screen cannot qualify. Structural/finality failures stay
fail-closed. This plumbing changes no strategy threshold, universe or provider limit.
Keep bounded secret-safe process-terminal diagnostics; old compact certification
artifacts are not required for operational diagnosis.

## Run 375: disappearing WAL and ordered-commit saturation

SQLite may checkpoint/unlink a WAL between an exists check and stat. The original
Pons process died after approximately 522 seconds from that race. Perform one
race-safe stat; only FileNotFoundError means zero transient WAL bytes. Main database
and other filesystem failures remain visible. The exact retained regression forces
this interleaving against current provider_usage.

Responsive receivers/decoders alone did not prevent approximately 383 seconds in
ordered commits from saturating the existing 64-frame / 96 MiB budget.
Coalesce only consecutive finalized frames already available to the ordered
committer, with at most eight frames / 16 MiB per FULL-synchronous outer transaction.
Each frame retains its savepoint; a malformed later frame cannot corrupt earlier
valid frames. Receive order stays authoritative. Account/control notifications keep
their individual semantics. Report commit batches, peak messages/bytes and avoided
outer transactions. Neither bigger queues nor weaker durability establishes a fix.

## Current coverage and remaining limits

Retained operational tests include Run 370 storage/gap checks, partial-batch
rollback, retention outcomes/progress, actual Run 372 spawned large-frame execution,
dispatch/subscription fairness, Ramses scan recovery and the Run 375 WAL race.
Their exact mappings are source-pinned in the companion manifest.
Current runtime closure and complete removed-file review remain separate mandatory
migration gates. The pending restored Run 380 fixed-source pressure regression
has a lag failure; this reference does not mark it accepted.
