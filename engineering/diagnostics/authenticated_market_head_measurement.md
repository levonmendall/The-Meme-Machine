# Authenticated head measurement and economic cohort design

This component is based on application main
`92831be8f63cde7db8a74016c2135a770e75667b`. It supplies fresh physical provider
head measurements; it is not activated by the operational entrypoint, does not
write economic state, and does not establish full-market capacity or readiness.
It complements the combined-capacity architecture receipt in administration
`docs/COMBINED_CAPACITY_ARCHITECTURE_20261017.md`. No strategy, financial,
historical-completion, provider-allowance or admission policy changes are made.

## Implemented head contract

`runtime.market_heads.MarketHeads` attaches explicitly to the original native
`RepairRPC` and canonical `PacedRpc`. The hooks run after an actual bounded HTTP
response has been read and its original envelope validated. They run before the
Solana source waits for owner delivery/publication. A cache return, numeric
historical header, sequencer clock, caller-supplied result, public alternative
provider, or injected transport cannot produce a head receipt.

The measurements have different meanings:

| Measurement | Exact physical request | Authority and meaning |
| --- | --- | --- |
| Solana finalized | `getSlot([{commitment: finalized}])` | Original endpoint with verified mainnet genesis; finalized slot coordinate |
| Pons latest | `eth_getBlockByNumber([latest, false])` | Original canonical endpoint with chain ID 4663; latest block number/hash/timestamp |
| Pons finalized | `eth_getBlockByNumber([finalized, false])` | Separate optional measurement when the native client actually makes this request |

Pons latest is never relabeled finalized. Its number alone does not establish
complete log acquisition. Every receipt includes exact application commit/tree,
source PID/process-start ticks/generation, provider identity, verified network,
request method and commitment, RPC session identity, request-start and physical
completion monotonic times, completion wall time, and head coordinate. Pons also
includes its actual header hash and timestamp. URLs, credentials, bodies and
arbitrary exception text are excluded. `HeadSource.verified_checkout` checks
the expected clean checkout and actual process identity once; this local source
binding supplements the existing exact approval guard, rather than replacing it.

The physical completion time remains fixed when the report is sampled later.
Age over five seconds, source/generation change, stop, malformed data, regression
or a same-height Pons hash change yields `UNAVAILABLE`. Missing data remains
unknown. Overlapping requests completing out of order are counted and cannot
renew an older receipt. First and latest physical receipts remain distinct.

`HeadRefresh` is an optional caller-owned controller: one in-flight refresh per
chain in the collector, only after the last applicable physical receipt becomes
stale, and no more than one scheduled attempt per five seconds measured from
completion. There is no catch-up burst. The caller must create one collector for
the run, attach the actual source client after its normal network verification,
own the workers, signal their existing stop event, and join them before reporting
successful cleanup. The component currently has no production caller.

Refreshes require the existing installed operational `Budget`/`PhaseBudget`
transport. Solana retains the original Governor, provider-work attribution and
native HTTP path; Pons retains canonical configuration, chain verification,
shared Admission, pacer, physical retries and 429 debt. Pons uses a fixed
non-position evidence scope and rotates only exhausted ordinary bounded sessions;
new-session chain checks are charged through the original controls. The
controller does not retry a 429 itself, reset debt, create a Budget or add quota.
Pons refresh uses the existing thread-local fallback deadline; it never mutates
a shared client's ordinary deadline or installs a shared cancellation callback.
An optional transport context only subtracts cancellation/deadline capacity.
Cancellation is checked before and after admission and before socket dispatch;
successful head-body reads require the native fixed-length, non-chunked HTTP
response and known socket reader. They rebind the remaining socket timeout and
check cancellation/deadline around every bounded `read1`, charging each delivered
chunk before a partial failure. Unknown, unframed or chunked wrappers are
unavailable rather than asserting an unverified body bound. Ordinary reads
outside the optional context preserve their original behavior. The attempted
deadline is at most eight seconds, but existing SQLite busy waits and opener
header handling retain their original bounds: this is not a hard eight-second
process bound. Original joined-stop and outer execution bounds remain necessary.

Head collection adds constant-size in-memory metadata and no SQLite transaction,
spool, checkpoint, financial write or new authoritative writer. The three
snapshots fit the fixed 8 KiB test bound. Initial source verification uses three
bounded read-only Git commands, not a command per poll. With no reuse, refresh
is nominally at most 180 scheduled reads per chain in 900 seconds or 720/hour,
plus original charged retries and Pons session chain checks. Solana `getSlot`
retains its original 20-CU price. A 0.2-request/second head stream can consume
10% of a two-request/second allowance; admissible provider capacity must be
assessed before activation. Existing fresh native reads suppress that overhead.

Integration still requires the normal run owner to attach the original clients,
start/join optional refresh workers, and project the fixed snapshot through the
existing health cadence. That projection must preserve physical timestamps and
unknown states. No new collector thread, result projection, or readiness use is
silently enabled by importing these hooks.

## Economic cohort correctness plan: not implemented here

A fresh provider coordinate exposes unacquired coordinate lag. It does not say
how many economic events exist in the unacquired interval. Local backpressure
can hide those events from every local queue. Incoming economic count stays
unknown until the same closed native interval has complete authenticated
acquisition, original census/coverage proofs, decoded relevant identities, and
original gap checks. An incomplete interval supplies a lower bound only.

Use existing canonical identities and owner transactions, without a second
event spool or writer. Cohorts bind source/tree, policy/filter identity,
provider/network, source generation/session, closed native coordinate interval,
and the original coverage/census proof identities. Since an eventual H1 is not
known while ingesting, aggregate committed closed native frames/pages first;
join these to sampled head cohorts only when the complete interval is known.
Do not assign an event to a guessed future head. Replays, fan-out obligations,
native decisions and physical provider work remain different units.

The minimal source hooks are:

| Stage and unit | Existing authority hook | Proposed aggregate rule |
| --- | --- | --- |
| Solana canonical unique event | `SelectiveHistory.ingest` -> `RollingHistory.store/store_many` -> `_queue_events`, within `commit_candidate_batch` | Count existing unique pending candidate-outbox identities by closed frame/program in the same outer FULL transaction; rollback the aggregate with the batch |
| Pump/PumpSwap publication obligation | `CandidateLifecycle.emit_raw` and `queue_records` | Count actual `INSERT OR IGNORE` row creation by candidate/scope, separately from unique economics and duplicate/replay demand |
| Consumer durable delivery and source ACK | `solana_history_delivery.deliver` and `acknowledge`, then `CandidateLifecycle.acknowledge_rows` | Count exact selected rows only after original consumer FULL and verified source generation/content/order; a source ACK proves the preceding FULL but does not invent an independently timed FULL counter |
| Solana complete program coverage | `published_program_frontiers` and original membership/gap/missing/unconsumed checks | Require those predicates for the whole cohort interval; a published last point alone does not prove all earlier membership |
| Pump Current native disposition | `CandidateHistory.complete` | Keep complete/deferred/failed/deadline-missed separately; deadline-missed is neither complete qualification nor economic rejection |
| Pump Survivor native history disposition | Original history append/checkpoint and `_ack_history_checkpoint` | Count only original durable scope/consumer checkpoint completion, independently of Current |
| Pons acquired market/pool economics | `MarketScout.read_market`, `_retain`, canonical log/header validation and original committed page cursor | Aggregate unique economic identities only for completely validated closed market and active-pool pages, not just curve/factory discovery |
| Pons nomination/generation | `Plane.observe` | Preserve actual identity and generation supersession links; repeated nomination and coalesced generations are not new unique economic events |
| Pons Current result and native consumption | `Plane.finish`, `Plane.consume` / `Broker.acknowledge` | Count original committed current-generation dispositions and consumption independently; late/freshness-censored completion stays incomplete |
| Pons Survivor history disposition | Original scout graduation checkpoint plus canonical history append/checkpoint | A graduation cursor alone does not prove durable survivor history or protection readiness |

The existing generic Solana evidence-writer counters miss actual rolling-source
ingest, and prepared-record counts include replay. Candidate-history references
are fan-out, not economic arrivals. Pons scout event counts shrink during
retention, retained variants use event identity plus body digest, and
`Plane.observation_counts.received` includes repeated nominations. None can serve
as a lifetime unique-economic denominator without the specific proof above.

Keep aggregate cohort rows under the existing sole writer, in its existing
transaction, with no extra fsync and no per-event secondary dedup table. A
Solana batch already bounds frames (at most eight) and programs/scopes; a Pons
market page is already bounded to ten blocks, but active-pool paths need the
same attribution. Proposed aggregate work should scale with committed bounded
frames/pages, not retained history size. Measure the extra SQL VM work and
owner queue/execution tails before accepting this cost. Retention must not
decrement completed cohort counters. Source/generation discontinuity closes an
incomplete cohort and starts a new one; it never silently stitches evidence.

For each complete cohort and each required consumer, report arrivals, original
canonical FULL, actual consumer FULL/source ACK, native disposition and backlog
in matching units. Preserve accepted/deferred/superseded/censored/failed/unknown
separately. Derive backlog only when both operands refer to that exact complete
population. Keep unacquired head-coordinate lag separately visible and unknown
economic backlog explicitly unknown. This design needs review and regression
proof before any schema, counter or acceptance gate is changed.

## Scoped offline evidence

`tests.test_market_heads`: 27 cases passed in 0.751 seconds under the official
Scratch/network guard with CPython 3.12.14. Cases exercise original Budget,
Governor and Pons Admission against offline transport, physical/cache identity,
stale age, 429 debt, one in-flight refresh, pre-dispatch cancellation, bounded
deadlines, canonical chain/source provenance, session rotation and discontinuity.
The successful-body trickle/cancel cases use real `HTTPResponse`/`SocketIO`
with an offline socket interface, and retain partial-byte/uncertain accounting.
Truncated known-length bodies retain uncertain debt, provider identity survives
RPC-session collection, and a fresh skip at the exact five-second boundary does
not postpone the next stale attempt by another interval.
The shared-Pons-peer regression preserves its original explicit deadline while
the refresh thread receives a tighter bound. After these corrections, the two
affected existing Budget/retry modules passed all 36 cases in 2.564 seconds.

Six affected existing modules ran 102 cases: 82 passed. The other 20 encountered
the environment's absent `/proc/self/ns/time`, causing the existing provider
clock guard to reject construction; one process-death test consequently could
not reach its intentional exit. The unchanged baseline independently reproduces
that clock failure. These are not release passes, and no clock guard or original
test was weakened. No provider workload, AWS execution or full-suite claim is
part of this component's evidence.
