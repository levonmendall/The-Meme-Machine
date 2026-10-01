# Stage E: static bounded source-admission design

PAPER ONLY — 2026-10-01. Stage E: **RED**. Stage F: **NOT STARTED**.
Material diagnostic budget: **6/6 consumed; 0 unused**. No new execution is authorized.

**Conclusion:** a narrow admission mechanism can be specified without changing admitted FIFO or native side arbitration. Its opportunity-count ceiling is large enough to warrant a serious capacity examination. The preserved evidence does **not** establish that enough useful opportunities exist under its necessary source-protection guards, or that the coupled archive/retirement service fits with adequate recovery surplus. This paper therefore returns **architectural/allocation ambiguity**, not an implementation recommendation and not a proof of inevitable capacity insufficiency.

The current authority is Astra's `PROCEED_TO_BOUNDED_OWNER_SCHEDULING_DESIGN`, supplied in the assignment. Historical stop instructions and budget counters in earlier evidence describe their publication time; they do not reset the current 6/6 budget. Preparation overlap remains retired.

## A. Exact production and evidence identities

| Identity | Pinned value |
| --- | --- |
| Repository | levonmendall/The-Meme-Machine |
| Production commit | dc08f9064cf5e37b63f383f52aa709d0afc1723f |
| Production Git tree | 68736cf664169dee665762019800bf87ca0f1f67 |
| Source-owner ablation execution | 6e104c122dc495d75bd8828a5fea7237b48effdf |
| Ablation execution tree | 084245305a1bbe49c522b99be20396d633add6e2 |
| Ablation run / job / attempt | 36771603217 / 110079106497 / 1 |
| Ablation artifact / bytes | 11124508037 / 934,841 |
| Ablation ZIP SHA-256 binding | 485a522b8e1ab820674528905fa87e953cb444eade31c77635f5ba8cce2cdec6 |
| Housekeeping matched-pair execution | c22e61a176951c364b9dc855c68adad849479afe |
| Housekeeping execution tree | 181617da5edde878ed66ae79d7c6797534b7450b |
| Housekeeping run / job / attempt | 36818149058 / 110227640326 / 1 |
| Housekeeping artifact / bytes | 11142687311 / 1,529,756 |
| Housekeeping ZIP SHA-256 binding | 08028f13ff03f4f78c6700aa8ede205f63eb6730da8dc0a718396e20e3028c54 |
| Housekeeping patch SHA-256 binding | f4d3b0399dcfbe43b968ef0a901be73efe187f1a3ecdc79b16f5defb177f6f2d |
| Preserved evidence/publication base read for this paper | d4068d4fa177225daf8780ee7c9765977f4b8793 |
| Evidence-base Git tree | f3a1f7561c564243ad01fdf47d818ef9eeffaeec |

Pinned production blobs:

| File | Git blob |
| --- | --- |
| meme_machine/solana_evidence_service.py | a54d3ed1876f138a6b2db37ef917f414173869db |
| meme_machine/solana_evidence_control.py | 90628ffdbe98e24a758c320e8965a99a75326272 |
| meme_machine/solana_maintenance_runtime.py | 73a2801136483d47e84e964435d11590f3ba0cdc |
| meme_machine/solana_maintenance_arbiter.py | 337bb569ec5920497dd012c01a14c36fdea2518a |
| meme_machine/solana_maintenance_state.py | 92e7d69d4e5af4f5946aaad19ce4062563670976 |
| meme_machine/solana_evidence_plane.py | 34ef169e139baebfe12f9801b12f1774c94eaa05 |
| meme_machine/solana_checkpoint.py | f1608116b8fa4a5100a46e16f75649659ffe604f |

The production tree has 1,152 blobs. Static comparison against the preserved publication base found all 1,152 blobs and modes unchanged. The housekeeping repair exists as a separate patch artifact, not an applied production change.

Read evidence: [ablation review][ablation-review], [control projection][control], [zero-floor projection][zero], [ablation binding][ablation-binding], [housekeeping review][hk-review], [housekeeping comparison][hk-comparison], [housekeeping binding][hk-binding], and the prior [static owner attribution][prior-owner]. Their timing populations are kept distinct below.

Access boundary: repository text, JSON projections and Git trees were read through GitHub. No shell/workload/test was run. Artifact ZIP digest values above are preserved bindings; these ZIPs were not independently extracted or hash-verified in this task. The frame-1,189 and frame-1,193 timing facts are authoritative evidence supplied in the assignment, not a claimed reconstruction from an extracted raw file.

[AGENTS.md][agents] and [BUILD_STATUS.md][build-status] were read. The assignment's explicit paper-only prohibition takes precedence over historical instructions to run tests. This report adds no runtime, workflow or qualification change.

## B. Current admission pipeline

### Receiving, decoding and becoming eligible

[Reception and decoding][receive] operate separately from ordered owner commit:

1. Before receiving, the receiver reserves space for one maximum-size frame. It waits when `pending_frames >= 64` or `pending_bytes + 16 MiB > 96 MiB`.
2. A retained wire frame receives an increasing `receive_sequence`. `pending_frames` and `pending_bytes` increase at reception, before decoding.
3. Two existing decode workers produce frames independently. Frames of at least 1 MiB use the existing process pool; smaller frames use a thread. Pure preparation carries no database authority.
4. Completions enter the bounded decoded queue. The committer drains currently available completions, up to 64 at a time, into its `ready` map.
5. A decoded frame becomes eligible for ordered processing only when its sequence equals `next_sequence`. A later decoded frame cannot pass a missing earlier frame.
6. Subscription state and message type then determine the native processing path. Decoding alone is not owner admission.

`pending_frames` counts **all received, uncommitted frames**: inbound, decoding, decoded out of order, ready, and a source request awaiting durable completion. It is neither ready-prefix length nor owner queue length.

### Formation and admission

At the [batch caller][batch], the committer checks the next frame and its subscription. For a blocks/account data frame it calls `maintenance_batch_limit(pending_frames)` **before removing frames from `ready`**. It forms a consecutive wire-order prefix, capped by both the returned limit and 16 MiB. An ACK, unknown/retired subscription boundary, unsupported type, absent next sequence or byte limit stops the prefix.

Formation, ordered-wait bookkeeping and tuple construction happen before `await work(...)`. [work()][work] calls `owner.submit()` synchronously before its first await. There is no explicit maintenance wakeup/admission handshake between formation and enqueue.

A batch containing only account notifications has priority 0. Other blocks/account batches have priority 2. The single-frame fallback also assigns accounts priority 0; ordinary source priority is 2. Subscription/control ACK processing is a formation barrier and follows its existing path.

Consequently:

- A maintenance request already queued precedes a newly submitted normal source batch under FIFO.
- A source batch may be formed and admitted before the maintenance coroutine resumes and submits its next request.
- Formation does not guarantee that maintenance got an opportunity first.
- There is only one outstanding ordered source owner request from this committer, since it awaits durable completion before advancing to another batch.

On successful completion, pending frames/bytes decrease, `commit_progress` advances, receive capacity is signaled, and `next_sequence` advances. None of these steps may be performed by an admission gate.

### Owner selection and urgency

[PriorityOwner][owner] admits at most 64 queued requests, with eight slots reserved for priority 0. Priorities other than 0 are rejected at a queue length of 56. The executing request is outside that count.

Submission assigns a common increasing sequence under `owner.cv`. When the queue contains priority 0/1 work, native priority selection applies. When every queued request has priority at least 2, the owner selects the smallest admission sequence across priorities 2, 3 and 4. Source, maintenance, counters and checkpoint callbacks therefore share admitted nonurgent FIFO.

Normal source never interrupts background SQL. Priority 0/1 work may interrupt background SQL at existing cooperative boundaries; protected atomic retirement slices remain atomic. Checkpoint handoffs retain their existing behavior, including a logical mutation hold during off-owner I/O. This paper changes none of these semantics.

## C. Current maintenance batching, pressure and authority

The constants are:

| Constant | Value |
| --- | ---: |
| STREAM_COMMIT_BATCH_MAX_MESSAGES | 8 frames |
| Maintenance batching threshold | 2 × 8 = **16 pending frames** |
| STREAM_COMMIT_BATCH_MAX_BYTES | 16 MiB |
| STREAM_MAX_MESSAGE_BYTES / STREAM_PREPARED_MAX_BYTES | 16 MiB / 16 MiB |
| STREAM_DISPATCH_MAX_MESSAGES / MAX_BYTES | 64 frames / 96 MiB |
| STREAM_PROTOCOL_QUEUE_FRAMES | 32 |
| STREAM_DECODE_WORKERS | 2 |
| STREAM_COMMIT_STALL_SECONDS | 15 s |
| STREAM_WATCHDOG_SECONDS | 0.1 s |
| STREAM_SUBSCRIPTION_SYNC_SECONDS | 0.25 s |
| STREAM_SOURCE_IDLE_SECONDS | 20 s |
| ARCHIVE_COMMIT_SLICE_RECORDS | 512 records |

The exact [batch-limit rule][batch-limit] is:

| Returned pressure flags | pending_frames | Maximum batch |
| --- | ---: | ---: |
| Either true | 0–15 | 1 |
| Either true | **16 or more** | 8 |
| Both false | Any valid count | 8 |

Actual batches can be smaller because of readiness, barriers or bytes. A one-frame batch does not prove that the pressure branch was taken.

`maintenance_pressure = {'archive': False, 'retention': False}` is local to `serve()`. The key named `retention` carries the runtime's **retirement** pressure result.

The sole [maintenance coroutine][maintenance] owns one runtime and one ArchiveFlight. Every turn is a priority-4 owner request. After a **successful return**, the coroutine replaces the flags with `result.archive_pressure` and `result.retirement_pressure`. These booleans came from the turn's **pre-service** native Need list. Thus a positive flag can survive work that just eliminated its demand. A cooperative yield leaves the old flags intact. Startup flags are false until a successful observation returns. An accepted request may also still be executing before its result is delivered to the coroutine.

After a selected side, or a cooperative yield, maintenance uses `sleep(0)` and tries again. With no selected side, it waits for the archive future or the existing one-second idle cadence. A pending receipt with no future and no feasible side can enter that one-second branch. The admission rule must not use that branch to manufacture feasibility.

At [runtime.turn()][runtime]:

- Owner delay must be at most 3 s; generation and receipt generation must match.
- A completed archive future is consumed **inside the owner**. A preparing future is not ready; an idle flight is ready to initiate planning.
- The normal bounded adapter observes native pins, gaps, floors, debt, oldest ages, housekeeping and progress.
- Native demands and durable episodes are built inside this observation path.
- Archive readiness is `flight.pending is not None or flight.idle`; retirement readiness is true, with demand and feasibility separately required.
- The unchanged arbiter selects at most one side.
- Archive commits at most 512 records per admitted slice. A final slice also obtains the successor snapshot.
- Retirement rechecks its native evidence and bounded transactions. Ledger deltas alone credit service.

The [arbiter][arbiter] uses owner/execution/clock leases of 3/3/3 s and a worker lease of 15 s. The pair reserve is 15 s and drought is 45 s: 240 − 180 − 15. For a selected side, `now + 3 < its deadline`; demanded peers, including unready peers, require `now + 9 < peer deadline`. Measured rates rank feasible surplus only. Recovery deadlines, safety deadlines and service origins are not extended by observations, hints, offers, timeouts or no-progress turns.

## D. One proposed trigger: bounded maintenance opportunity before a new source admission

**Only candidate:** a coalesced wakeup/admission rendezvous with the existing maintenance coroutine, placed in `commit_ordered()` immediately before the next normal data batch is formed. The caller continues to use the current batch-limit function.

The gate cannot call archive or retirement, create a Need, inspect an external debt snapshot, run its own observation, choose a side or change a worker's preparation. The existing coroutine submits the ordinary `runtime.turn()`; that turn supplies all authority.

### State actually available today

| Input before formation | Safe use / limitation |
| --- | --- |
| pending_frames, pending_bytes | Exact local transport counts; available directly |
| next_sequence, ready map, next message/subscription | Ordered prefix and control/account barriers; available directly |
| inbound/decoded queue sizes | Local dispatch hints; do not include the opaque protocol/TCP backlog |
| commit_progress and decoded_at | Local timing; commit_progress changes only after actual source completion |
| maintenance_pressure | Returned scheduling hints with the stale behavior described in C |
| owner queue length, priorities, closed flag, checkpoint handoff | Non-authoritative scheduling state can be copied briefly under existing owner.cv; current telemetry exposes only queued count, not an atomic full scheduling snapshot |
| ArchiveFlight future.done() | Carrier completion hint, not a validated receipt or readiness decision; flight itself belongs to the maintenance coroutine/owner boundary |
| runtime generation returned at initialization | Can be copied as a fencing hint; current pressure dictionary has no generation/epoch |
| Durable episodes, recovery excess, current deadlines, oldest debt, feasible side | **Not safely available to the source caller as current authority** |

Runtime dictionaries, last observations, health JSON, durable maintenance tables or a read-only external SQLite connection must not become an admission-layer debt/deadline snapshot. A generation-consistent **new owner observation** is required to know current demand, readiness, reservations and progress. A done worker future has not yet passed native receipt/generation checks.

### Minimum proposed non-authoritative metadata

Add only local scheduling metadata to the service/coroutine interface in a future implementation:

- `hint_epoch`: monotonically increasing publication serial after a returned turn; independent of arbiter decision sequence, which does not advance on a no-decision turn.
- `hint_generation`: the runtime generation copied at its normal return boundary.
- `hint_returned_at`: monotonic timestamp of that return.
- `consumed_hint_epoch`: a hint can fund at most one gate attempt, including timeout or no useful result.
- One coalesced opportunity token, one accepted maintenance future identity, and a source-admission acknowledgement.
- A local `receive_capacity_waiting` boolean, set/cleared by the existing receive-capacity wait, so that the source gate can abort immediately when transport needs room.

These are not a debt cache. The source caller does not read the runtime's mutable episode/arbiter/flight dictionaries. The single coroutine publishes the hints after its quiescent return and attaches any prepared worker in the normal order. A returned generation mismatch invalidates the token; the normal owner checks remain authoritative.

### Eligibility conjunction

Offer at most one token only when **all** are true:

1. The next ordered frame is eligible ordinary blocks data; no ACK/control/account head is being held. Under the currently active pressure limit this next batch would initially be one normal frame.
2. Either pressure flag is true.
3. The hint generation matches the locally returned current maintenance generation, the epoch is unconsumed, and its age is at most **1 s**, the existing idle observation cadence.
4. The preceding ordered source owner request has completed. No other gate/token is open.
5. No maintenance turn is already accepted and unfinished. An already accepted turn counts as the existing opportunity; source proceeds immediately without requesting another.
6. `1 <= pending_frames < 16`, byte and lag guards in G hold, and the receiver is not waiting for capacity.
7. A scheduling snapshot under `owner.cv` reports an open owner, no queued priority 0/1 work, no active checkpoint handoff, **an empty queued-request list and no executing callback** (the existing _checkpoint_busy flag is false). Older admitted callbacks are never held or moved. Current executing priority is not safely exposed; treating every busy owner as a bypass avoids inventing an urgent-in-flight hint.

The idle-owner and empty-queue restrictions are deliberately conservative. It does not reserve the owner or prevent subsequent urgent/control admissions. An intervening admission is handled by the unchanged queue and lease checks.

Consume the hint epoch when the opportunity attempt opens, not only when maintenance makes progress. Publish one wakeup to the existing maintenance loop. If the token expires, is aborted, or a newer source admission is already made, the coroutine must discard an unaccepted token before submission.

False-positive pressure can therefore spend **one** bounded observation opportunity for that epoch. A successful fresh no-demand turn clears the flags normally. If no response arrives, that old epoch cannot repeatedly defer source. False-negative or expired pressure simply retains current behavior; it cannot falsely authorize work. Neither case resets a clock.

## E. Finite source-deferral bound

| Bound | Proposed contract |
| --- | --- |
| Deliberate pre-enqueue hold | **100 ms maximum**, derived from STREAM_WATCHDOG_SECONDS = 0.1 |
| New source admissions affected by one offer | At most **one** |
| Actual frames in that resumed batch | At most existing **8**; normally 1 under continuing low-backlog pressure |
| Consecutive newly granted maintenance admissions | **One** |
| Rearming | Previous source admission completed, no token open, and an unconsumed, current returned hint |
| Already accepted maintenance | No extra offer; immediate source admission |
| Stale-positive nonresponse | One attempt per epoch; no retry on the same hint |

The 100 ms is a wakeup-to-**acceptance** allowance, not a requested sleep and not an average maintenance service time. Resume as soon as the one maintenance request is accepted. Do not wait for worker completion, native decision, useful progress or debt discharge.

Immediately after acceptance, close the offer and form/enqueue source in its current wire order. Keep a local acknowledgement barrier against a **second maintenance submission from this offer** until the source request has actually been submitted, or the source path has aborted. This closes the race in which a very short maintenance callback completes and its coroutine resubmits before source resumes. The barrier affects only not-yet-admitted submissions and is released on timeout/failure/cancellation; no queued work is changed.

A granted request retains the existing checked owner/execution leases of 3 + 3 s. Conservatively, its owner-entry/completion contract is at most **6 s from maintenance submission**; source re-enters normal FIFO no later than 100 ms after the offer, independent of that completion. One executing maintenance callback can add at most its existing **3 s execution allowance** of new owner service ahead of source. Queue wait and checkpoint holds are separate and observable.

These are contractual scheduling bounds under the existing responsive-clock/event-loop and lease assumptions. Neither Python timers nor an atomic SQLite/OS operation provide an unconditional real-time guarantee. Timer overshoot or a turn exceeding its lease is recorded as an operating-contract violation, disables further offers, and follows existing failure behavior. **Actual delay including overshoot is never truncated to the 100 ms policy limit.** An average execution time is not substituted for a bound.

The source caller does not acquire an owner/database lock while waiting. Admission-capacity races use the original overload/failure behavior, not an expanded queue or silent dropped source frame.

## F. Consecutive-maintenance and source fairness bound

The gate grants **one fresh turn**, counting planning, no decision and yield as opportunities. It never loops until a side is ready or useful work occurs.

If a maintenance turn is already accepted, the new source request is submitted immediately. If the gate grants a fresh request, its acknowledgement barrier ensures the next source enqueue precedes any second offer-related maintenance enqueue. Only the next completed source admission and a new hint epoch can rearm the gate.

Independent, normally scheduled maintenance requests after source enqueue retain the existing FIFO. Older maintenance/health/checkpoint requests are not canceled or reordered. Urgent arrivals retain native priority. Maintenance cannot use this gate to place a sequence of fresh decisions ahead of a source batch.

This proves bounded **admission interference**. It does not prove full .27-second sustainable source throughput for every operation that merely returns within the much larger leases. Sustainable source throughput remains an explicit capacity obligation; failing it would reject the allocation design.

## G. Source backlog and transport protection

| Local source state | Gate action |
| --- | --- |
| pending_frames 1–15, other guards pass | Opportunity allowed |
| pending_frames **16 exactly** | Source must proceed; existing limit-8 fast path retained |
| pending_frames >16 | Source must proceed; existing limit-8 fast path retained |
| pending_bytes <=64 MiB | Byte guard can pass |
| pending_bytes >64 MiB | Source must proceed |
| Receiver waiting for capacity | Source must proceed |
| High inbound/decoded/ordered-ready count >=16 | Source must proceed; redundant consistency protection under the pending count |
| Control/ACK or account notification at ordered head | Existing path proceeds without this gate |
| Shutdown, connection drain, failure, invalid generation | No gate |
| Owner executing any callback, or active checkpoint handoff | No gate |
| Ordered commit lag or old decoded head at the limit below | No gate |

The 64 MiB guard is `96 MiB - 2 * 16 MiB`: reserve space for two maximum frames while considering an opportunity. Existing reception uses one maximum-frame reserve and remains unchanged. Equality at 64 MiB is allowed only while no capacity wait is active; the next received frame can immediately revoke an **unaccepted** token.

Let `L = 15 - (3 + 3 + .1) = 8.9 s`. Disable the gate when either elapsed time since actual `commit_progress` or the next frame's decoded-to-formation wait is **at least L**. This conservatively avoids offering a full maintenance admission/completion contract near the existing stall limit. It is an **admission guard**, not a claim that 8.9 + 6.1 leaves time for arbitrary source fsync completion. The source callback has transaction-size bounds, but no separately enforced wall-time execution lease; no measured source peak is promoted to one.

Recheck all local backlog guards before a grant is accepted and before source formation resumes. Receive-capacity or urgent/control transitions wake/abort the rendezvous promptly. A grant already accepted is never canceled or moved when backlog increases; source enqueues immediately and the existing bounded native turn finishes/yields normally.

After resumption, recalculate the existing batch limit from **current** flags and counts. If pressure clears, or backlog reaches 16, an 8-frame batch may now be formed. This is why the frame bound is eight rather than a promise that only one frame can be affected. Byte caps, per-frame savepoints, ACK barriers and wire order remain unchanged.

Receiver wakeups, an urgent/control submission, stop/drain and token expiry must be checked by the existing event-loop producers before an unaccepted token can be spent. A queue snapshot is only a hint; actual owner admission still applies the native capacity rules.

The 32-frame protocol queue and TCP backlog are not exact safely exposed inputs to this caller. Their bounds are preserved, and reception/decoding continue during the gate. Low local pending count does **not** prove low protocol backlog; the receiver's capacity-wait flag only covers known local backpressure. This observability limitation matters to the capacity conclusion. Source timestamp lag must not be converted into an invented pending_frames count.

No source frame is discarded, withheld from the original delivery clock, discounted from throughput, or moved ahead of an earlier frame. The receiver's existing 15 s stall test and 20 s idle test retain their clocks and meaning.

## H. Opportunity state machine and outcomes

| State | Transition |
| --- | --- |
| BYPASS | A guard fails or maintenance is already accepted; form/enqueue source normally |
| OFFERED | Consume one hint epoch; open one token and a 100 ms deadline; wake the existing maintenance loop |
| ACCEPTED | Coroutine rechecks live token/guards and submits one normal priority-4 turn; publish acceptance; source forms/enqueues immediately |
| SOURCE_SUBMITTED | Acknowledge the actual source submit; release the token's next-submission barrier; continue normal loops |
| ABORTED | Timeout, backlog, urgent/control, generation, drain/shutdown or failure before acceptance; discard token; source resumes or follows existing fatal/drain path |
| RESULT_RECORDED | Consume the accepted future's eventual native outcome for telemetry; never reopen the same offer or cancel accepted work |

A token is optional and coalesced; it never adds a second maintenance coroutine or a second flight. The existing wait on worker/idle/stop gains this single wakeup alternative. The accepted owner future remains shielded exactly as in work(); a canceled waiter does not abandon its outcome.

For **every nonfatal outcome**, source has already resumed at ACCEPTED. These outcomes cannot extend pre-admission waiting:

| Native outcome | Source behavior / accounting |
| --- | --- |
| A. Archive selected with durable progress | Source already enqueued; record actual archive ledger delta; no second grant |
| B. Retirement selected with durable progress | Source already enqueued; preserve ordinary scope rotation and ledger semantics |
| C. No side required | Source already enqueued; fresh returned flags clear naturally; count a no-demand opportunity |
| D. Archive worker pending / demanded side not ready | Source already enqueued; no wait for readiness; retirement may still be selected natively |
| E. Arbiter returns no decision | Source already enqueued; count no-decision and preserve clocks; no retry from this token |
| F. Native refusal | **Fatal as today.** Keep fail-closed service/shutdown and accepted-frame drain; do not treat refusal as a harmless timeout or retry |
| G. Cooperative yield | Source already enqueued; retain only real durable credit and any native receipt; ordinary later maintenance admission follows FIFO |
| H. Urgent work overtakes | Before acceptance: abort and resume source admission. After acceptance: source enqueues immediately; urgent selection/cooperative interruption stays native |

A selected archive planning turn without committed records is explicitly **zero record progress**. An idle flight being ready to plan is not equivalent to a ready commit receipt. Any generic no-decision result that lacks native explanatory metadata is reported as unknown/no-decision; the admission layer must not fabricate a readiness or infeasibility explanation.

Non-cooperative exceptions, stale/wrong generation, owner overload, exhausted leases and clock failures retain their native fatal meaning. Shutdown/drain disables offers, releases unaccepted tokens and acknowledgement barriers, and joins accepted work by the existing lifecycle. No restart grants new recovery or successful-service time.

## I. Simultaneous archive and retirement pressure

With both flags true, the predicate is the same `any(pressure)` predicate and there is still **one token and one native turn**. There are no separate archive/retirement credits, flags with priority, side quotas or direct archive insertion.

The fresh arbiter can choose archive, retirement, no decision or refusal. An unready archive still constrains the peer reservation. A granted archive planning turn may create a worker flight without progress while retirement remains due. A granted retirement turn may service records, continuity/floors or, under the separate repair's own invariants, housekeeping.

When the latest treatment reached frame 1,189, the supplied raw fact already had no feasible side, with archive/housekeeping headrooms about 8.889/8.523 s. The following four-frame source batch began **after** feasibility was lost. Frame 1,193 still had ready but infeasible sides. The new gate would not reinterpret either condition. A fresh turn there can only preserve the existing no-decision/refusal outcome.

Accordingly the candidate runs from the **first qualifying returned pressure hint throughout the recovery window**, with no terminal-frame, debt-size or deadline trigger. Its proposed benefit is earlier placement while service is still feasible. Terminal splitting and repeated immediate resubmission cannot repair the known failure.

## J. Telemetry and canonical wait accounting

Use bounded counters and at most a 64-entry metadata ring, published through the existing health path; no evidence bodies, provider text, extra per-offer fsync or unbounded event list.

Required counters/fields:

- Source pre-admission attempts, granted admissions, bypasses and aborts by cause.
- Actual pre-admission elapsed total and peak; actual timer overshoot and violations.
- Actual source batches and frames affected, first/last sequence identifiers and current pending-frame/byte count.
- Hint generation, epoch, age, already-accepted/coalesced state and token identity.
- Gate open, accepted-submit, source-submit and eventual native-turn completion monotonic timestamps.
- Outcome counts: archive progress, retirement progress, planning/no-record progress, no demand, worker pending, generic no decision, cooperative yield, refusal and exception.
- Urgent interruptions before/after acceptance, backlog-forced resumes, byte/lag/capacity bypasses, checkpoint bypasses and shutdown cancellation.
- Actual durable record and nonrecord ledger deltas kept separate; no gate-created service credit.

Correlate accepted turns using future/request identity and native result metadata. If an explanatory field is not returned from the fresh owner turn, leave it unknown. Do not recompute arbiter feasibility in the source gate for telemetry.

Define for an eligible ordered frame:

`pre_admission_wait = source_owner_submit - first_eligible_preformation_boundary`.

Also identify the gate-specific span separately from ordinary decoded/ordered waiting. Report:

`source_eligible_to_completion = pre_admission_wait + post_submit_queue_wait + source_execution`.

The intervals are disjoint for a frame's path. A batch's wall span is counted once for capacity; summing the same span once per frame is a latency-weighted statistic, not owner occupancy. Work inside an owner queue wait explains that wait and is not added a second time to total wall.

The current ordered-commit wait **peak** can expose some extra delay if the insertion precedes formation, but it has no corresponding complete gate count/total. Current source commit timing starts after formation and PriorityOwner queue timing starts at enqueue. Neither alone is sufficient. Existing receive-capacity admission-wait counters measure a different stage.

The unchanged canonical source floor remains:

`max(0, .165 * actual_frame_count - native_source_elapsed)`.

Do **not** subtract gate delay or maintenance work from that injected wait. Gate waiting does not qualify as native source work and does not satisfy any part of the .165 source floor. Keep the input delivery clock, full source frame target, source lag and end-to-end throughput requirement intact. Any apparent gain accompanied by lowered source advancement or unseen pre-enqueue time is a failed allocation claim.

## K. Static capacity model

### Non-overlapping accounting categories

For one elapsed interval T, the logical owner availability is bounded by:

`source + archive + retirement + observation/health + other owner work + checkpoint mutation holds <= T`.

| Category | What belongs here / overlap constraint |
| --- | --- |
| Source owner demand | Native source callback plus injected .165 floor remainder. Source outer transaction, embedded preparation/ingest and COMMIT floor are already inside it |
| Archive owner demand | Snapshot planning, bounded commit slice and normal final-slice successor snapshot; do not also add the containing maintenance callback |
| Retirement owner demand | Native bounded record retirement and its surrounding retention call |
| Housekeeping / continuity / floors | Real retirement-side work; part of retention occupancy unless a disjoint native span is available |
| Observation / health | Fresh maintenance adapter/arbitration and health publication; runtime execution includes observation |
| Checkpoint owner boundaries | Prepare/finish callbacks plus actual mutation-handoff holds, including off-owner I/O that prevents owner mutation |
| Worker preparation | Source decode/preparation and the single archive worker run off-owner and can overlap owner work; they constrain readiness/CPU but are not additional owner occupancy |
| Pure gate idle waiting | Only any portion where the logical owner is otherwise idle can consume additional usable wall. Gate time overlapping existing work is latency, not an independent occupancy sum |

No archive cycle, queue wait, outer transaction or off-owner worker total is added to its containing service span.

At .27 s/frame, source floor alone is:

`.165 / .27 = 61.1111% of elapsed wall`.

The top-level remainder is **38.8889% before all other work**. The gate cannot reclaim the floor, native work already below it, required retirement, or a checkpoint hold. It can move a fresh admission earlier and possibly use otherwise idle placement/readiness gaps.

### Coherent preserved ablation-control interval

Use the control projection's exact snapshot interval **210.337256385–300.470607412 s**, T = **90.133351027 s**. This is different from the historical M2 cost interval and from the 85-flight launch cohort.

| Quantity | Observed |
| --- | ---: |
| Committed frame advance | 321 |
| Inferred eligible arrivals | 87,912 records |
| Durable archive advance | 74,176 records |
| Durable retirement advance | 73,844 records |
| Archive drain | 822.958418 records/s |
| Eligible arrivals | 975.354838 records/s |
| Archive shortfall | **152.396420 records/s** |
| Required archive increase to match arrivals | **18.518119%** |
| Retirement drain | 819.274987 records/s |

The zero-injected-source-floor ablation retained native source work and drained about 975.691 records/s against about 975.070 arrivals/s in its own matched interval; all 57 formed native episodes resolved within original deadlines. It establishes sensitivity to owner pressure. Its released source-owner floor is unavailable to this design and is not a reusable capacity budget. Both diagnostic arms retained the .36 s/1,000 archive worker floor and .006 s changing outer-COMMIT floor, two existing decode workers, and the original .27 source cadence. Reduced ACKs remain diagnostic-only.

The native source spans in this interval total 45.369970950 s and requested source-floor wait totals 9.696482142 s. Their 55.066453092 s sum is 61.09% of this interval. The floor for its 321 completed frames is 52.965 s; fixed-interval clipping, actual oversleep, callbacks and checkpoint work make that different from complete owner-priority deltas.

From the same two owner telemetry snapshots:

| Disjoint logical-owner aggregate | Endpoint delta |
| --- | ---: |
| Priority 0 execution | 0 s |
| Priority 1 execution | 0 s |
| Priority 2 execution, source plus checkpoint callbacks | 55.576534 s |
| Priority 4 execution, maintenance plus health/background | 25.218685 s |
| Checkpoint mutation-handoff holds | 4.193162 s |
| Sum | **84.988381 s = 94.291824% of T** |
| Residual envelope | **5.144970 s = 5.708176% of T** |

These are completed-callback/hold aggregate deltas, not an exactly clipped raw interval union; crossing endpoint spans and delivered telemetry can affect the residual. Treat 5.145 s as an **analytical residual envelope**, not a proven reusable-idle bound or a guaranteed spare budget. The interval includes the source pause/catch-up/reader interaction. Its residual may occur when useful native work is unavailable. It must not be assumed continuously available.

Priority-4 completion advance is 363, giving **69.473 ms per completed priority-4 callback**. That is a mixture including health and no-progress turns, **not a measured duration bound or an isolated useful-maintenance mean**.

The separate historical [MATURE_CAPACITY_COSTS.json][historical-costs] gives native retention 11.245493 s /114 calls, archive planning 3.112479 s /75, and archive commit stages 5.180340 s /143 in its approximately 90.131 s interval. These are about 98.645/41.500/36.226 ms per stage call, respectively. Its worker and PASSIVE checkpoint spans overlap other work. It is a different execution; these means supply scale estimates only and are not added to the coherent ablation deltas.

### Opportunity frequency and useful-service scale

At nominal source cadence, one offer per one-frame source admission has an upper offer rate of **3.703704/s**, or about 444 offers per 120 s. The actual rate is lower because of already accepted maintenance, hint epochs, queue/backlog/byte/age guards, worker readiness, urgent work and larger source batches.

Illustrative *additional successful-turn* requirements:

| Assumed useful records per turn | Extra archive turns/s for +152.396/s | Extra retirement turns/s for +156.080/s |
| --- | ---: | ---: |
| Archive 512; retirement 510 | 0.297649 | 0.306039 |
| Archive 256; retirement 256 | 0.595299 | 0.609687 |

512 archive records and retirement 510 (256 +254) are observed successful bounded-turn examples in the preserved control. Another observed retirement turn advanced 588. These are examples and planning assumptions, not minimum yields. Archive receipts cap at 1,000 and normally need two <=512-record admissions; idle planning and final receipt acknowledgement can yield zero records.

Thus a favorable mix needs about **0.604 extra useful turns/s**, and a smaller-yield mix about **1.205/s**, before extra zero-progress turns and recovery surplus. Relative to 3.704 potential offers/s, roughly **16.3% or 32.5%** would have to become genuinely additional useful service with a sufficient native side mix. An offer that advances the same already-planned work but displaces equal later service is not an extra turn.

The count ceiling is not obviously below the deficit scale. It also does not establish attainable useful frequency. Average batches below eight, aggregate source lag, or aggregate receipt waits do not reveal the gate's conjunction at actual formation boundaries.

For the separate 85-flight mature control cohort, summed cycle-partition means are **1.112228 s**. At unchanged record yield, an 18.5181% rate increase would require roughly **173.782 ms less elapsed cycle time** on average. Avoiding exactly one .165-second source placement per flight gives only a **17.4192%** cycle-rate increase in that simplified model. It is therefore insufficient to claim that one shifted batch per receipt by itself closes the deficit. The candidate would need eligible opportunities at multiple source boundaries across flights and both maintenance sides, or additional useful idle/readiness placement. It does not grant multiple consecutive turns at one boundary.

The latest housekeeping-treatment 84-flight cohort still averages about .243905 s ready-to-first-commit and .343176 s summed inter-slice gaps, with .067415 s commit-stage service and .318697 s native preparation. Those waits are large relative to 174 ms, but include required source/retirement/checkpoint service. They are **not** a recoverable-time estimate.

## L. Coupled archive and retirement capacity

For a scope, let H be eligible hot debt, P archived-pending records, A durable archive rate, R durable retirement rate, and lambda eligible arrival rate. Ignoring scope eligibility changes only for this accounting illustration:

`dH/dt = lambda - A`; `dP/dt = A - R`.

Current coherent control has A ≈822.958 and R ≈819.275. Increasing A to 975.355 while holding R fixed grows P by approximately **156.080 records/s**. Archive improvement alone therefore exports the failure to retirement. At the target, R needs about **19.0510%** more observed drain just to match arrivals, plus any retirement recovery surplus.

A deliberately conservative proportional scale illustration increases **all** observed priority-4 occupancy, including housekeeping, continuity, floors, observation and health, by the larger of the archive/retirement factors:

`max(975.355/822.958, 975.355/819.275) = 1.190509723`.

That costs about **4.804405 additional seconds per 90.133 s**, leaving only **0.340565 s**, or about **0.378% of wall**, inside the residual envelope. It is not a guaranteed cost model: service costs, readiness, side mix and observation count need not scale linearly. Using the archive factor alone leaves .474944 s but underestimates the retirement factor.

This narrow fit is inadequate to certify recovery surplus:

- Both sides must discharge previously accumulated recovery excess within their original 120-source-second deadlines, not merely equal arrivals.
- Housekeeping/continuity/floor progress cannot substitute for required retired-record progress or renew its drought.
- Extra planning/no-decision observations and idle portions of the 100 ms rendezvous can consume the small residual. A pathological timeout on every nominal frame would expose about 33.3 s of pre-admission waiting per 90 s, which plainly cannot be described as spare capacity. Epoch consumption limits stale-positive retries, but does not prove a productive opportunity distribution.
- The read evidence's periodic/candidate urgent ACKs were disabled. Canonical urgent demand may consume the small remaining margin; no ACK reduction is credited to this design.
- The strict high-backlog guard can disable new offers precisely during a critical window. The preserved raw batch schema did not persist its pending-frame counts, pressure flags or exact branch result. Source lag is not enough to decide whether this actually happens.
- Off-owner archive preparation still requires the existing single flight. Earlier owner observation while its worker is pending may help retirement but cannot be counted as archive records.
- The latest treatment's simultaneous recovery collision proves that retirement demand and housekeeping cannot be omitted from the model.

There is no theorem here that retirement necessarily becomes the bottleneck, and no conservative proof that enough coupled capacity remains. The static theoretical offer count permits the needed scale; the allocation of usable wall and native selection remains unresolved. This is the concrete reason for the final ambiguity marker.

## M. Housekeeping correctness repair remains separate

Hold the Astra-retained housekeeping patch constant across any future relevant comparison. Do not add its predicate, side preference or service credit to the source gate.

Its own eligibility/invariants remain:

- Fresh generation-consistent owner evidence and an **already-admitted retirement decision**.
- Pending ready archive receipt and positive native housekeeping.
- Housekeeping is the sole retirement blocker inside the 9 s peer window: its effective deadline satisfies t+E < D <= t+2E+O.
- Every other active retirement obligation is strictly beyond that window.
- One existing bounded housekeeping batch, with existing max_records=1000 per table and at most 3,000 operational deletions across the three tables.
- Immediate source/urgent return after committed prefix progress, existing saved cursor/rotation, and no duplicate tail batch.
- Credit only retirement / __housekeeping__ operational units; zero retired-record credit.
- Truthful pending/unknown reporting for work not reexamined after later record retirement.

The passed 54 focused tests, old-behavior control reproduction and resource checks are historical evidence; none were rerun here. Both eligible treatment prefixes committed 1,782 deletion units, but control/treatment still refused at native frames 1,212/1,205 and drained to 1,214/1,207 final frames. Treatment archive/retirement headrooms were about 5.930879/5.564875 s, with Meteora retirement recovery about 8.930879 s. Both sides were ready and neither feasible. This patch is a correctness repair, not the admission/capacity repair.

## N. Future deterministic test specification — DO NOT RUN

Use a controllable monotonic clock, explicit event-loop/owner submission barriers and fresh native database fixtures. Assert returned owner evidence and actual durable ledger deltas. Do not introduce authoritative Need/deadline snapshots in the gate, relax reservations, or substitute real timing averages for the 100 ms policy contract. The housekeeping patch is held constant.

| Group / required cases | Required assertions |
| --- | --- |
| Backlog below / exactly at / above threshold | 15 can offer; 16 and 17 bypass. Existing 1/8 limits and bytes remain exact |
| Bytes / dispatch / transport | 64 MiB equality, just above, receive-capacity waiting, dispatch at 64/96 MiB, decoded out-of-order prefix, protocol backpressure hint unknown; force source resume without frame loss or expanded bounds |
| Pressure archive only / retirement only / both | Same opportunity gate; one native turn; side comes only from fresh arbiter result |
| Archive ready / worker pending / retirement ready | Fresh owner readiness; no worker wait or fabricated archive progress; native retirement remains possible |
| Comfortable / approaching reservation / already infeasible deadlines | Normal native selection; strict >9 s peer checks; no gate-based admission override. Already infeasible remains no-decision/refusal |
| Continuously queued source | Each offer affects one new admission; second grant cannot precede that source submit; eventual source completion under original operating assumptions |
| High dispatch backlog / ordered lag | Immediate bypass/abort at thresholds; original batching fast path and stall clock preserved |
| No maintenance demand | False hints produce at most one bounded zero-demand observation for the epoch; future false flags bypass |
| Urgent before / during / immediately after turn | Before acceptance abort; after acceptance native urgent selection/interruption; account-only priority-0 batches and ACK barriers bypass |
| Stale positive / negative / epoch unchanged | Positive attempt consumed even on timeout; negative falls back; no repeated old-token grants |
| Generation changes | Close unaccepted token; accepted turn enforces native generation checks; no off-owner episode mutation |
| Repeated archive / retirement / cross-scope work | No admission-side side bias or forced scope ordering; native rotation and record/service origins retained |
| No decision / preparation-only | Source submit does not await a useful result; no progress credit or clock renewal |
| Cooperative yield | Accepted future outcome consumed; source's already queued sequence precedes any later normal requeue; durable progress only |
| Maintenance exception / native refusal / overload | Original fatal/overload propagation and accepted-frame drain; tokens/barriers released; no retry-until-success |
| Restart / shutdown / connection drain | Gate disabled for drain; no abandoned accepted future or archive worker; durable episodes and origins survive |
| Timer boundary / late acceptance | Acceptance at/after expiry cannot spend an invalid token; actual overshoot measured; no late grant after source enqueue |
| Fast completion race | Maintenance finishes before source coroutine wakes; acknowledgement barrier still prevents a second grant from jumping source |
| Accounting | Positive pre-admission total/peak, affected frame count, monotonic event identities, no queue-wait disappearance, no double-counted owner/worker spans |
| Ordering | Exact source wire sequence and savepoints; queued older source/maintenance/health/checkpoint identities retain nonurgent FIFO; no new owner capacities |

Test source-progress and receive-drain assertions under the original source requirements. Passing the local gate tests would not establish full Stage E sustainable capacity or canonical qualification.

## O. One deterministic old-fails / new-passes regression target

Target the **unaccepted maintenance submission race**, not terminal batch splitting.

Create a finite stream of source admissions with both native recovery obligations active and both sides ready. Preserve the original durable episode deadlines throughout. A controlled dispatch barrier makes the committer reach a new normal source admission while the maintenance coroutine is quiescent and has a current positive hint. There is no accepted maintenance request to reorder.

At the final chosen pre-loss boundary, use a fresh native fixture whose two effective deadlines have **9.1 s** headroom, with archive debt such that one legitimate 512-record slice can reduce its recovery debt to the native 1,000-record envelope. Keep safety/drought deadlines later; let native surplus ranking determine the selected side from the fixture. Native source service retains its .165 s/frame floor.

OLD: source submit occurs before the pending coroutine's fresh submit. After the .165 s source callback, peer headroom is at most 8.935 s; both side choices fail their strict 9 s peer reserve. The next normal observation returns no decision, and continued source/idle progression leads toward the existing refusal. Earlier source admissions in the finite sequence establish the sustained-pressure context.

NEW: the gate wakes the same coroutine and accepts one ordinary maintenance request before forming that new source batch. Fresh native observation occurs while the 9.1 s peer reserve still fits; the arbiter's fixture-selected archive slice makes actual durable progress and genuinely resolves that archive recovery excess. Source then submits within the 100 ms policy bound, with .165 source floor intact. Its subsequent peer turn uses fresh evidence and unchanged reservations.

Assertions:

1. OLD lacks a timely native decision at this boundary; NEW gets one. This is an owner-admission placement result, not a full recovery-capacity pass.
2. Every request admitted before the boundary retains its original relative nonurgent sequence.
3. The gated maintenance submit precedes the one new source submit; no second grant does.
4. Source really submits/runs, retains its frames/order/floor, and no wait is hidden outside queue metrics.
5. The chosen side comes from the native arbiter and fresh owner fixture; the gate has no archive preference.
6. Durable episode deadlines remain byte-for-byte unchanged until legitimate native debt resolution removes an episode. Only actual native progress may renew service origins.
7. Repeat the same admission-order target with an already infeasible fixture: NEW must **not** turn failure into success.

The 9.1 s boundary is strictly **before** feasibility loss. It does not replay the known frame-1,189 batch, whose pre-batch state was already infeasible. The gate's trigger itself has no deadline threshold and is exercised from comfortable earlier-window pressure in the matrix. This small regression does not claim that the actual production race recurs at the required rate or require the 4,445-frame canonical workload.

## P. Assumptions, infeasibility conditions and unresolved architecture

Guaranteed policy properties, conditional on normal timer/owner operating contracts:

- One consumed token, one fresh submission, at most one new source batch affected.
- 100 ms pre-enqueue policy maximum, measured actual elapsed including overshoot.
- Immediate backlog/control/drain bypass, unchanged 16-frame batching threshold.
- No admitted FIFO change, no urgent-priority change, no transaction/worker/queue bound increase.
- Normal owner observation, readiness, arbiter, durable progress and original clocks remain the sole authority.

Performance estimates only:

- 3.704 potential offers/s is a ceiling, not useful service.
- 0.604–1.205 additional successful turns/s uses illustrative yields, not guaranteed progress.
- 4.804 s coupled incremental occupancy is a proportional illustration, not a reserved capacity grant.
- The residual envelope, cycle reduction and retirement effects are execution-specific and not hard liveness bounds.

Outstanding static/evidence obligations:

1. **Trigger coverage:** how many pressured preformation boundaries actually have pending_frames <16, available bytes, a current unconsumed hint, no accepted maintenance, an idle owner and an empty owner queue? These conjunctive inputs were not persisted in the available raw batch schema/projections.
2. **Net useful placement:** how much residual owner availability intersects freshly required, ready and feasible work, and how much earlier receipt service becomes additional progress rather than shifted service?
3. **Coupled marginal cost:** the projections do not isolate useful fresh maintenance observation/selection costs and extra retirement/housekeeping costs at the gate's actual opportunity mix.
4. **Source continuity:** the code has finite queue/transaction sizes and a receiver stall check, but no source callback wall-time lease. The proposed guards bound new admission interference, not an unconditional full-throughput/fsync theorem.
5. **Canonical urgent demand:** reduced ACK evidence cannot establish the remaining capacity margin under restored canonical controls.

These are precise allocation/operating-contract gaps. They are not permission to instrument or execute anything.

Reject this candidate as statically infeasible if source-backed analysis establishes any of the following:

- Achieving useful service requires exceeding the 100 ms admission bound or changing existing owner/execution/worker contracts.
- Repeated source suppression or more than one consecutive granted turn is necessary.
- Necessary source backlog guards disable the gate throughout the useful recovery interval.
- After retaining all source, retirement, housekeeping, observation and checkpoint work, the maximum useful benefit is materially below +152.396 archive records/s and recovery surplus.
- Increased archive service necessarily pushes retirement outside its original recovery/service obligations.
- Stale hint/debt becomes side/deadline/progress authority.
- Already admitted FIFO, urgent priority, reservations, deadlines, worker/transaction bounds or clocks would need to change.

None of those universal impossibility claims is proven by the readable evidence. Equally, the favorable offer-count and proportional models do not resolve the five gaps above. This paper does not replace those gaps with “needs testing” or ask for an execution budget.

## Q. Exact conclusion and hard Astra gate

**One bounded pre-source opportunity is mechanically specifiable and conditionally plausible by opportunity count. Its sufficient useful capacity under unchanged .165 load is not statically established.** The coherent owner envelope is already about 94.3% occupied; proportional coupled matching leaves about 0.34 s per 90 s before recovery surplus and additional timing/urgent costs. The gate's useful coverage under necessary backlog and existing-admission guards is unrecorded. Calling this ready for implementation would require treating an upper frequency/residual envelope as available production capacity.

Return this paper to Astra to decide whether the allocation mechanism is legitimate under the unchanged source load, whether its admission/fairness/source protections are adequate, and whether the static capacity case can support any later implementation/deterministic testing. Only Astra can consider a new material budget afterward; **this paper makes no budget request**.

M1 interruption/completion, broad preflight (1 failure, 2 errors, 46 skips), canonical native-transition qualification reconstruction/wiring, and restoration of canonical ACK behavior remain separate Stage E blockers. Housekeeping correctness remains a separate repair. No runtime implementation, tests, treatment, CI workload, candidate freeze, M1/preflight repair, canonical change, Stage E run or Stage F work is performed or authorized by this output.

[agents]: https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/AGENTS.md
[build-status]: https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/BUILD_STATUS.md
[receive]: https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_service.py#L979
[batch]: https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_service.py#L1083
[work]: https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_service.py#L813
[batch-limit]: https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_service.py#L850
[maintenance]: https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_service.py#L1330
[owner]: https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_control.py#L33
[runtime]: https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_runtime.py#L263
[arbiter]: https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_arbiter.py#L148
[ablation-review]: https://github.com/levonmendall/The-Meme-Machine/blob/d4068d4fa177225daf8780ee7c9765977f4b8793/diagnostics/source-owner-ablation/ASTRA_REVIEW_PACKAGE.md
[ablation-binding]: https://github.com/levonmendall/The-Meme-Machine/blob/d4068d4fa177225daf8780ee7c9765977f4b8793/diagnostics/source-owner-ablation/BINDING.json
[control]: https://github.com/levonmendall/The-Meme-Machine/blob/d4068d4fa177225daf8780ee7c9765977f4b8793/diagnostics/source-owner-ablation/CONTROL_ANALYSIS_LOG_PROJECTION.json
[zero]: https://github.com/levonmendall/The-Meme-Machine/blob/d4068d4fa177225daf8780ee7c9765977f4b8793/diagnostics/source-owner-ablation/TREATMENT_ANALYSIS_LOG_PROJECTION.json
[hk-review]: https://github.com/levonmendall/The-Meme-Machine/blob/d4068d4fa177225daf8780ee7c9765977f4b8793/diagnostics/housekeeping-ordering/ASTRA_REVIEW_PACKAGE.md
[hk-binding]: https://github.com/levonmendall/The-Meme-Machine/blob/d4068d4fa177225daf8780ee7c9765977f4b8793/diagnostics/housekeeping-ordering/BINDING.json
[hk-comparison]: https://github.com/levonmendall/The-Meme-Machine/blob/d4068d4fa177225daf8780ee7c9765977f4b8793/diagnostics/housekeeping-ordering/COMPARISON_LOG_PROJECTION.json
[prior-owner]: https://github.com/levonmendall/The-Meme-Machine/blob/d4068d4fa177225daf8780ee7c9765977f4b8793/diagnostics/stage-e-owner-scheduling-attribution/STATIC_ATTRIBUTION.md
[historical-costs]: https://github.com/levonmendall/The-Meme-Machine/blob/d4068d4fa177225daf8780ee7c9765977f4b8793/diagnostics/stage-e-fresh-causal-isolation/MATURE_CAPACITY_COSTS.json

OWNER_ADMISSION_DESIGN:
ARCHITECTURAL_AMBIGUITY_REMAINS
