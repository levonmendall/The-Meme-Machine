# Retained cancelled-source buffered economic interval

This is a separate offline prototype from application780. It is not installed,
approved source, a source restart, callback settlement, complete market coverage
or operational readiness. No producer, cancellation, trading, financial, provider,
deadline or shutdown behavior changes here.

The original source task marks `unexpected_cancellation:true` when it receives
CancelledError before its stop event was set. Its global teardown can nevertheless
finish every accepted queue frame and preserve an interrupted pre-feed WebSocket
callback against actual durable program gaps. An unexpected source cancellation
and an unreturned callback remain failures even if independently reconstructed
economics subsequently become available.

The current legacy census has SHA256
`d01237f6fa0e819de4ab6b8c3068f6c8ba5565fec67d20d1780c7b302dd0caec`;
the complete retained ledger has SHA256
`97cafc5760e592ef574954bb49ba2b271852b676c66a504cfb73a9d55d9876b6`.
AWS39087381577 preserved these as 3368 and 6943 bytes. The original historical
source census remains `RECOVERY_REQUIRED` with two unknown callbacks. The new
current callback is handler222983, PumpSwap `LOG_BUFFER_WAIT`, slot458249851,
bound to gap51409. Its closed rolling session252109 reported completed458249731,
11232 buffered logs / 33548943 bytes at slots458249732–458249851 and no pending
accepted commit-queue frames. Both program disconnect gaps begin458249395.

## Admission is not proof

Only that exact legacy census/whole-ledger pair selects the separate
`CANCELLED_SOURCE_BUFFERED_LOGS` input class. A caller cannot use the optional
internal mode with another pair, and simply changing `unexpected_cancellation`
on a previously supported census continues to fail. The original default input
validator still requires the flag to be false. The actual retained cancellation
flag, callback identity and failure disposition are never normalized or removed.

After selection, every original buffered validator still runs: historical
reference, terminal committed four-queue census, valid run/PID accounting,
zero active/failed/unresolved handlers, exact complete current-run records and
unique retained identities; one closed rolling session plus its original matching
native-join record; exact per-program native heads; bounded buffered slots/bytes;
two unambiguous durable gap origins, actual handler scope/gap/session bindings
and provider endpoint identity. The cancelled class additionally requires the
observed two closed sessions, one preserved partial session and a finite ordered
source monotonic lifetime. The fixed hashes cannot stand in for any of these
independent current-database checks.

Preserving this descriptor asserts only inputs. The original recovery mechanism
must acquire exhausted authenticated archive pages for both programs through
the last actually held observation, decode and commit their economics, deliver
actual CandidateHistory FULL event/coverage receipts, verify canonical ACKs and
publish original gap-aware coverage. The independent verifier checks jobs, all
page receipts, supplementation bindings, consumer receipt hashes, published
coverage points, no unconsumed program records and actual gap partitions. Missing
receipts, partial ACKs, moved heads, changed joins or gaps continue to refuse.

Only the finite observed interval may become economically recovered. The earlier
subscription prefix and still-unavailable future remain explicit original gap
partitions. `full_subscription_completeness_claim`, original queue acknowledgement,
original graceful drain, callback completion and historical recovery stay false.
All original historical records, health bytes, native heads and financial state
are preserved. A fresh source or PAPER start would still need its independently
reviewed compatible source, financial, current-state recovery, provider, resource
and protection gates; this prototype performs neither.

## Future producer contract, not implemented

The exact legacy pair compensates for a missing explicit cancellation-origin
witness in the old terminal schema. Replacing recurring pins requires a bounded
source-produced witness at the actual `CancelledError`/not-stopped boundary,
bound to source PID/start/run, monotonic time, original accepted-handler census
and the terminal owner generation. Original terminal commit must bind that
witness to actual complete joined-task/session/queue closure. Failed or unavailable
terminal publication remains unverified; a new empty process cannot create it
for a prior run.

Such a future witness would only select a structural input class. It must still
earn the same complete ledger/session/join/head/gap/archive/FULL/ACK proofs and
preserve every original failure flag. It cannot prove the first external cause,
undo a cancellation or certify unrelated dynamic families. Producer generation,
failure/cancellation races, terminal COMMIT failure, process replacement and
concurrent session closure need direct original-run regressions before replacing
legacy pins. No future witness producer or generic admission is added here.

## Scoped offline result

The official FAST driver, original network guard and disposable Scratch ran the
new nine-case module plus unchanged buffered-prejoin, session-economic,
archive-recovered and source-handler modules: 53 tests passed in 6.811 seconds,
without skips. CPython was 3.12.14; its local SQLite was 3.53.1. This is separate
from deployed SQLite3.45.1 validation and proves no real retained recovery,
provider result, fresh readiness or sustained throughput. The receipt is
`/workspace/recovery-evidence/cancelled-buffered-source-first.log`, SHA256
`a02a048c07e82a65eefd267860a9e48be4adf27e05dc6863ab2cc2856458a8fe`.
No AWS or provider calls occurred. The parent independently reviewed the frozen
runtime diff (source_drain SHA256
`beebea4c7efafb59464b0ddb01d6cfdac2c21a9ea3ab441ba8f460b067dce57c`)
and reported scoped code clearance; that review is not an operational approval.
