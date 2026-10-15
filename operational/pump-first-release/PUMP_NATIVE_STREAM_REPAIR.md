# Pump native stream blocker: retained evidence and narrow repair

The bounded authenticated observation used deployed source
`8782b263632d0163f07e93a6b1cffa5b94071e87`. It failed; it is not a protection
pass. The consumed observation database is retained under the initialized
`paper-shared-1000-20261011T071207Z` root, and the earlier failed database and
its expenditure counters remain unchanged.

The endpoint delivered scout accounts, block metadata, finalized slots and
program transaction statuses. Scout, control and program streams then reported
`INTERNAL` during `stream_read`, with the redacted detail
`Stream removed (RST_STREAM (Received RST_STREAM with error code 2))`.
There are 102 durable scouts, but zero program checkpoints, canonical economic
events, candidate content receipts, qualified decisions or positions. Scouts
are not economic evidence. Neither a new quote component run nor funding occurred.

The observed request filters already select Pump account-owner/discriminator
data with a 49-byte slice, two relevant program status filters, finalized
membership metadata and the existing economic WebSocket logs. Removing those
economic or membership inputs would weaken coverage. No filter, replay window,
finality fence or strategy requirement is changed by this repair.

A concrete local contributor was reproduced offline: the metered WebSocket
reader and gRPC response deserializer performed a durable SQLite write for every
frame on the native event loop. Buffered deliveries could monopolize that loop,
preventing ready control/program consumers from running. The retained native
samples show growing consumption lag; replayed provider timestamps also include
historical delivery, so their absolute age is not claimed as current protective
latency. An upstream reset's internal server cause cannot be inferred from code 2.

The repair uses the existing event-loop executor for per-frame accounting.
Received content is returned only after its original durable transaction commits.
Existing SDK reservations cover the frame while it is being charged. Cancellation
waits for accounting to settle before the stream reservation can close. No charge
is batched, deferred beyond consumption, forgiven or replaced by an estimate.
Original limits, provider governor, stream admission, uncertainty accounting,
failure records, request methods, native economics and protective deadlines stay
unchanged. This is a correction to the existing meter, not a second consumer or
monitor.

On the actual volume, a 300-frame / 2,100-byte offline replay delayed a ready
control turn by 1.561414 seconds with synchronous accounting and 0.001493 seconds
with the repair. Both durably charged exactly 630,000 bytes, with zero provider
requests. Total storage work remains; this demonstrates event-loop fairness, not
an authenticated provider fix or a trading-latency acceptance result.

Focused proof: 55 preflight, continuation and source-intake tests passed; another
27 original budget/transport tests passed. New regressions hold the durable
writer while control advances, require commitment before content returns,
exercise repeated cancellation, retain a charged tail after the original failure,
and test the installed gRPC deserializer/reader boundary. Existing strict limits,
restart, uncertainty, missing configuration, finality and intake assertions remain.
The baseline 8782 full FAST CI completed successfully (run 38145179151).

The authenticated failed run consumed 13 physical starts including eight native
openings, five logical RPC elements, 100 conservative RPC CU, 215 known HTTP
bytes and 370,516,158 accounted native bytes including uncertainty. It stopped
at the sealed eight-opening limit, below the unchanged 512-MiB stop boundary.
Its conservative public-price modeled upper is $0.03895669659, not an invoice.
Custom limits matched the approved file in the parent and children; no permissive
default envelope or counter reset occurred in this run.

Provider equivalence remains unproved until a new, separately bounded
authenticated observation establishes advancing canonical program coverage and
complete genuine candidate protection. The consumed attempt cannot be resumed
by clearing its failure, resetting counters or increasing its opening limit.
PAPER remains stopped, admission closed, cash $1,000 and positions/pending
executions zero. Pons funding stays disabled; the two paused families remain
paused. The dashboard restoration is independently deployed and does not activate
this native repair or change capital/service configuration.
