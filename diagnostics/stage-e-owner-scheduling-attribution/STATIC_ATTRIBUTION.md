# Stage E static owner-scheduling attribution

PAPER ONLY. Stage E: RED. Stage F: NOT STARTED. Material budget: **4/6 consumed; 2/6 unused**.

**Conclusion: attribution is incomplete.** Pinned source establishes the ordering, batching, readiness, reservation and resubmission rules. Preserved aggregates establish substantial source service, retirement service and checkpoint mutation-boundary holds. They do not establish one avoidable scheduling/allocation defect, or establish that required service explains most of the particular receipt waits.

No scheduling proposal is made. The missing receipt-level reconstruction must not be replaced by a priority-only explanation, an aggregate subtraction presented as idle time, or invented admission events.

This report carries forward the user's authoritative decision: **ASTRA_DECISION: OVERLAP_RETIRED_RESOURCE_PROOF_CANNOT_CLOSE**. Preparation overlap is retired. Earlier overlap recommendations in the historical ablation review are superseded. No additional overlap variant was investigated.

## A. Pinned identities and evidence

| Identity | Value |
| --- | --- |
| Repository | levonmendall/The-Meme-Machine |
| Production commit | dc08f9064cf5e37b63f383f52aa709d0afc1723f |
| Production tree | 68736cf664169dee665762019800bf87ca0f1f67 |
| Preserved ablation/publication commit used here | 3eeb02f060b4623b6842d8f18853e5340dec0684 |
| Its tree | 51734622aeef4df71601712a55ec92be4f7374a7 |
| Material diagnostic execution commit | 6e104c122dc495d75bd8828a5fea7237b48effdf |
| Execution tree | 084245305a1bbe49c522b99be20396d633add6e2 |
| Run / job / attempt | 36771603217 / 110079106497 / 1 |
| Artifact | 11124508037; 934,841 bytes |
| Bound artifact ZIP SHA-256 | 485a522b8e1ab820674528905fa87e953cb444eade31c77635f5ba8cce2cdec6 |
| Bound control summary SHA-256 | f5c78eb11a5a0906280c124c707d1c4d523c1e43285035d1dd36e5984d05012a |
| Bound execution harness SHA-256 | 4f6f751a8efb5e7593d3444212ab4638d7126cec4131ba29807e390472003aa5 |
| Bound request SHA-256 | 8bf309ddaf7d9c284922c9adc455763fa74248befa23ac5d9796274242704cac |

[Preserved review](https://github.com/levonmendall/The-Meme-Machine/blob/3eeb02f060b4623b6842d8f18853e5340dec0684/diagnostics/source-owner-ablation/ASTRA_REVIEW_PACKAGE.md), [binding](https://github.com/levonmendall/The-Meme-Machine/blob/3eeb02f060b4623b6842d8f18853e5340dec0684/diagnostics/source-owner-ablation/BINDING.json), [control analysis projection](https://github.com/levonmendall/The-Meme-Machine/blob/3eeb02f060b4623b6842d8f18853e5340dec0684/diagnostics/source-owner-ablation/CONTROL_ANALYSIS_LOG_PROJECTION.json), [original artifact-file hashes](https://github.com/levonmendall/The-Meme-Machine/blob/3eeb02f060b4623b6842d8f18853e5340dec0684/diagnostics/source-owner-ablation/ARTIFACT_FILE_HASHES.json), [CI log](https://github.com/levonmendall/The-Meme-Machine/blob/3eeb02f060b4623b6842d8f18853e5340dec0684/diagnostics/source-owner-ablation/CI_JOB_LOG.txt), and [completed run](https://github.com/levonmendall/The-Meme-Machine/actions/runs/36771603217) are the evidence references. The log projections are compact JSON extracted from CI, not byte-identical copies of the artifact's pretty-printed files.

Static tree comparison in this task found **all 1,152 pinned production blobs and modes unchanged** in the preserved publication base. There are 1,195 blobs in that base, including diagnostic additions. No production source was edited.

Inspected source identities:

| File | Git blob SHA |
| --- | --- |
| meme_machine/solana_evidence_control.py | 90628ffdbe98e24a758c320e8965a99a75326272 |
| meme_machine/solana_maintenance_runtime.py | 73a2801136483d47e84e964435d11590f3ba0cdc |
| meme_machine/solana_evidence_service.py | a54d3ed1876f138a6b2db37ef917f414173869db |
| meme_machine/solana_maintenance_arbiter.py | 337bb569ec5920497dd012c01a14c36fdea2518a |
| meme_machine/solana_checkpoint.py | f1608116b8fa4a5100a46e16f75649659ffe604f |
| meme_machine/solana_maintenance_state.py | 92e7d69d4e5af4f5946aaad19ce4062563670976 |
| meme_machine/solana_evidence_plane.py | 34ef169e139baebfe12f9801b12f1774c94eaa05 |
| meme_machine/solana_archive_snapshot.py | 2bb30f9eb3467d9e7914c2fe5266aa4ccf32330b |

The .165 control used native source work, .165 seconds/frame source-owner floor, .36 seconds/1,000 archive records worker floor, .006 seconds/changing outer COMMIT, two decode workers, the unchanged 1,334-frame prefix, .27 seconds/frame delivery coordinate and five-second observation cadence. Periodic and candidate urgent ACKs were disabled in both ablation arms; candidate data reads remained. That diagnostic configuration is not canonical qualification authority.

Control failed natively at frame 1214 / source coordinate 327.78, with 1216 frames durably committed after drain. Failure was maintenance_cannot_reserve_both_sides. Treatment removed only the injected source-owner floor and completed the prefix, resolving all 57 formed native episodes within original deadlines. This establishes conditional owner-pressure sensitivity, not a particular production scheduling defect.

**Evidence access boundary in this task:** the artifact download tool returned a ZIP file reference, but the available tools expose no filesystem reader, shell or ZIP extractor. A text-accessible publication of its raw control files was requested. No such text copy was available while this report was prepared. The complete raw cycle/batch arrays were therefore not read here. Their bindings were read; that is not a claim that the ZIP bytes or individual raw files were independently hash-verified here. CI log inspection confirms that its ARM_ANALYSIS publication omits per_flight, as the analyzer explicitly does at [analyze.py line 128](https://github.com/levonmendall/The-Meme-Machine/blob/3eeb02f060b4623b6842d8f18853e5340dec0684/diagnostics/source-owner-ablation/analyze.py#L128).

Required raw files already preserved, with their bound SHA-256 values:

| Artifact member | SHA-256 |
| --- | --- |
| control/archive-cycles.json | 1cae2d97792a8d56fff7d4f535764971460ebe9d9286b2bb0f9a2f95f0a0952f |
| control/archive-cycle-decomposition.json | 4f3bf8bc6ea03a9e88136334f4a9d44fbcb3d31ef333e352c66a01899dc694f1 |
| control/source-batches.json | a03b1d85f19b1f09a21dcea445c200368b32d8c3a9b8176f4e39b0d87a524b84 |
| control/timeline.jsonl | 5906aa33d993790e28b740440c37acee0583b9632ff74d480c3c2ba1584b14ee |
| control/native-health.json | 948cfefaae724d61d5ecaa1ff5d753ee151d173a45311fdd6ad6de551c6bdde5 |
| control/terminal-ring.json | 2ab1e7ceb9535dfab5d524d972ab0ad234b2d0d4bc0725d21323f6fe7cbacf25 |
| control/episode-events.json | 83dc69518adf06e32e609fb872e8a17052a7d781e9c0c217b11cb1a0d4cdf447 |

## B. Production scheduling semantics

### Owner admission, overtaking and interruption

[PriorityOwner.submit and _run](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_control.py#L41-L143) implement these rules:

1. Submission under the condition lock increments a common sequence, records an enqueue clock and pushes (priority, sequence, expiry, callback, future). Capacity is 64 queued requests; only priority 0 may use the eight reserved slots. Other priorities have a 56-request admission limit. The executing callback is outside that queue count.
2. When any priority below 2 is queued, heap order selects the lowest priority number, then sequence. Thus priority 0 can overtake priority 1, and both can overtake already-admitted source/background requests.
3. When the minimum queued priority is at least 2, the owner selects the smallest sequence across **the entire queue**, including priorities 2, 3 and 4. Normal source, counters, maintenance, health and FIFO checkpoint requests share admission order. Priority 2 alone does not let newer source work pass priority 4.
4. The one-second check increments aged_selections for an already-selected old FIFO request. It neither changes its rank nor rescues maintenance ahead of an older source request. There is no active aging threshold that changes source-versus-maintenance selection.
5. An executing callback is not displaced by queue selection. Priority-4 SQL has a progress handler; only queued priority <2 requests can interrupt it. Normal priority-2 source commits cannot roll back an archive scan/slice. Atomic retention mutation disables SQL interruption until its durable boundary.
6. A retention boundary recognizes queued priority 2 or 3 as 'source' work, and priority <2 as 'urgent'. Priority 4 alone does not request that boundary yield. The native retention code may finish two additional separate bounded transactions after observing normal queued work, then yields and rotates scopes. Urgent work gets the next protected transaction boundary.

The ordered source coroutine awaits each admitted batch before submitting another. Pending transport frames are not separate already-admitted owner requests. After a source batch finishes, a newly submitted nonurgent successor source batch cannot pass maintenance that was already queued.

Block-containing batches use priority 2. An all-account batch uses priority 0, even when maintenance pressure is active; a mixed block/account batch uses priority 2. Nonbatched account observations also use priority 0. Foreground command priorities are assigned independently. [Ordered commit](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_service.py#L1109-L1227) must therefore be inspected as well as the owner's numeric priorities.

The source comment at service lines 856–860 describes an independent retention loop being held between archive slices. **That comment does not describe the executable pinned maintenance authority.** The actual single loop calls the fresh owner-entry arbiter; retirement can be selected while an archive receipt is pending. No inter-slice retirement-exclusion condition is implemented by that comment.

### Readiness, leases and native arbitration

[MaintenanceRuntime.turn](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_runtime.py#L263-L374) checks the three-second owner lease and generation at entry, consumes a completed archive future into pending, obtains fresh native debt, then calls choose. Archive is ready when pending exists or the flight is idle; preparation in flight is not ready. Retirement readiness is true, but selection additionally requires positive native demand and feasibility.

Each successful archive commit admission mutates at most 512 records. Only the final slice also selects the successor snapshot inside the same callback. There is one archive future/receipt carrier. The administrative receipt obligation preserves idempotent acknowledgement if a final durable slice is followed by a cooperative yield.

[choose/complete](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_arbiter.py#L147-L245) uses the minimum of native safety, per-scope successful-service and latched recovery deadlines. Recovery is latched at excess over 1,000 records using the original 120-source-second obligation. Clock allowance, owner and execution leases are three seconds each; worker lease is 15 seconds. The service drought is 45 seconds.

For a selected side, now+3 must be strictly before its deadline; now+3+3+3 must be strictly before each demanded peer deadline, including temporarily unready peers. Debt/rate pressure ranks feasible sides, with earliest deadlines and previous-side tie breaking. Measured rates never extend a lease or deadline. Only positive native durable progress renews a scope's service origin; housekeeping cannot renew required record retirement.

choose can return None when no feasible side exists but its immediate refusal test has not fired. It raises maintenance_cannot_reserve_both_sides when there are deadlines and at least one is reached by now+execution+owner. In particular, None is not proof that no native demand exists. Two ready demanded sides with deadlines between now+6 and now+9 can both fail the peer test without yet triggering that refusal. This static condition is relevant to the idle branch below; its occurrence in a representative control receipt has not been demonstrated.

Decision.scopes is a deadline ordering in the arbiter result; turn does not pass that tuple as a new forced scope execution order. Archive selection retains its native oldest-time/identity ordering; native retirement retains its durable-boundary rotation. This report does not infer a new scope scheduler from the arbiter's tuple.

### maintenance_batch_limit

[Batch limit](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_service.py#L850-L870) returns:

| Last returned maintenance pressure | pending_frames at formation | Limit |
| --- | ---: | ---: |
| Either archive or retirement true | <16 | 1 |
| Either true | >=16 | 8 |
| Both false | Any valid pending count | 8 |

The threshold is twice STREAM_COMMIT_BATCH_MAX_MESSAGES, which is 8. pending_frames counts admitted receive frames through durable source completion, including work still decoding, decoded out of order, and the pending commit; it is not just the consecutive ready prefix. Dispatch remains bounded at 64 frames / 96 MiB. Actual batches additionally require consecutive ready data frames, subscription/control barriers, and the 16 MiB transaction bound.

Pressure flags are updated on the event-loop coroutine **after a successful maintenance turn returns**, using the pre-service native needs observed in that turn. They are not a direct instantaneous measure of archive debt at source batch formation. Cooperative yield leaves the prior flags intact. Therefore maintenance pressure and multi-frame source admission can legally coexist, and actual current debt alone does not reconstruct the flags used by a batch.

### Checkpoint and health

[work](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_service.py#L813-L847) records queue/execution aggregates, not a per-request event log. Health has its own single outstanding priority-4 owner request and one-second cadence; it does not await completion within the maintenance coroutine.

[Checkpoint](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_service.py#L1368-L1419) queues priority-2 prepare and generation-fenced finish callbacks. PASSIVE copying runs off-owner. A stale completed copy can acquire a priority-2 FIFO mutation-boundary handoff through [reclaim_at_boundary](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_checkpoint.py#L19-L55). During that lease, _run cannot enter another callback, including urgent work newly arriving after acquisition, until the matching release. Previously admitted urgent work is selected before handoff acquisition. The boundary's copy/reset is off-owner I/O but blocks logical owner mutation; it must not be labeled owner-idle time or added again to a wait already containing it.

## C. Representative receipt selection

The preserved control has 146 flights; 145 complete timestamp partitions. Flight 146 has no commit stage and is excluded. The analyzer's mature cohort is **85 complete flights with launch committed_frame 775–1112**. It is a flight-launch cohort, not the exact 210–300-second capacity interval.

| Measurement, seconds | Whole mean | Mature mean | Mature median | Mature peak |
| --- | ---: | ---: | ---: | ---: |
| Ready marker to first commit stage | 0.214734 | 0.253903 | 0.151839 | 4.352266 |
| Sum of gaps between a flight's commit stages | 0.317520 | 0.335711 | 0.191175 | 3.392567 |
| Sum of commit-stage service | 0.064183 | 0.063489 | 0.059184 | 0.128649 |

The requested concrete receipt set **cannot honestly be identified from these aggregates**. The published projection excludes sequence-linked per_flight records. A maximum, a median, and their other fields cannot be joined as though they were one receipt.

Use the following fixed small selection once the existing raw members are accessible:

| Role | Deterministic selector in the 85-flight cohort | Published constraint |
| --- | --- | --- |
| Large ready delay | Maximum ready_receipt_to_first_commit; lowest sequence breaks ties | 4.352265500 seconds |
| Large inter-slice delay | Maximum per-flight inter_slice_gaps; lowest sequence breaks ties | 3.392566550 seconds, a sum of gaps rather than necessarily one gap |
| Typical receipt | 43rd record sorted by ready_receipt_to_first_commit, then sequence | Median 0.151838960 seconds |

If the first two select the same receipt, retain it once and also select the largest-gap distinct receipt. These selectors are an offline reconstruction specification, **not a claim that receipt identities have been selected or their raw timelines inspected**. No worst-case-only sample is offered.

The whole-population mean ready-to-first owner-entry proxy is 0.150964850 seconds; maximum 0.657175814. All 145 complete flights have that field. Subtracting its whole-population mean from the same population's ready-to-first-commit mean yields **0.063769122 seconds after first entry, on average**. That remainder includes execution and potentially additional turns; it is not coroutine idle time.

Because the 4.352265500-second ready-delay maximum occurs in the mature cohort and every complete flight's first-entry proxy delay is at most 0.657175814 seconds, that long receipt has **at least 3.695089686 seconds after its first ready-observing turn entry and before its first commit stage**. Thus its large delay cannot all be the queue wait of its first maintenance request. This is an identity-free bound, not a cause attribution.

## D. Per-receipt timeline and timestamp boundaries

The actual T0–T7 table for three identified receipts remains incomplete. The preservation harness tells us exactly which fields an offline extraction can supply:

| Event | Preserved raw field / boundary | Availability here |
| --- | --- | --- |
| Worker native preparation ends | archive-cycles.native_end | Raw member bound, values unavailable |
| T0 parent ready marker | mapped_ready_mark; mapped_ready_return brackets Future.set_result bookkeeping | Raw member bound, values unavailable |
| T1 maintenance request begins submission | receipt_request_submitted; each turns[].request_submitted | Available in raw, not the published per-flight projection |
| T2 ready-observing maintenance callback entry | receipt_owner_entry / turns[].entry | Proxy inside the owner callback; actual scheduler dequeue/enqueue sequence not persisted |
| T3 first commit slice start/end | commit_stages[0].start/end/error | Available in raw |
| T4 next maintenance submission | following turns[].request_submitted, including intervening retirement turns | Available in raw; exact PriorityOwner acceptance timestamp absent |
| T5 next maintenance callback entry | following turns[].entry | Available in raw |
| T6 later commit slice start/end | subsequent commit_stages[] | Available in raw |
| T7 logical receipt consumed/acknowledged | receipt_consumed_at | Available in raw; not an urgent consumer ACK or a new file publication |
| Successor worker submission | successor_submit_begin / submit_end | Available in raw |

[Harness worker/cycle markers](https://github.com/levonmendall/The-Meme-Machine/blob/3eeb02f060b4623b6842d8f18853e5340dec0684/diagnostics/source-owner-ablation/harness.py#L148-L187), [turn markers](https://github.com/levonmendall/The-Meme-Machine/blob/3eeb02f060b4623b6842d8f18853e5340dec0684/diagnostics/source-owner-ablation/harness.py#L344-L373), and [stage markers](https://github.com/levonmendall/The-Meme-Machine/blob/3eeb02f060b4623b6842d8f18853e5340dec0684/diagnostics/source-owner-ablation/harness.py#L392-L404) define these clocks.

T1 can precede T0: a maintenance request can be queued while preparation is running, then observe the future ready at owner entry. Do not impose the artificial order T0 < T1 < T2. For a ready wait, use the post-ready part of that queued request.

A turn's exit marker is taken at the beginning of the harness finally block. It precedes that wrapper's remaining bookkeeping, work's return timestamp and the owner's Future.set_result. Therefore next request_submitted minus previous turn.exit is an **upper bound on pre-submission coroutine delay**, not a pure coroutine measurement.

For one gap with adjacent committing turns and no intervening turn, use these disjoint portions:

- Previous commit stage end to previous turn exit: current owner callback tail.
- Previous turn exit to next request_submitted: callback completion/bookkeeping, future delivery and coroutine resumption/yield before submission, jointly bounded.
- Next request_submitted to next turn entry: admission/wait prefix, with actual enqueue slightly later and owner selection slightly earlier than the callback marker.
- Next turn entry to next commit-stage start: current maintenance observation/arbitration and pre-commit work.

If retirement or another maintenance turn intervenes, split at every turn's submission/entry/exit instead. Classify source service intersecting a queue wait as a cause of that wait; do not add it a second time as independent delay. The same applies to handoff holds.

## E. Wait classification

No exact representative interval receives a fabricated attribution. At present, its decomposition among these categories is **UNRESOLVED**:

| Requested class | What evidence would establish it | What is established here |
| --- | --- | --- |
| REQUIRED SOURCE SERVICE | Source execution span intersecting the wait, frame count, native/floor cost and admission relation | Whole/mature source service is substantial; no representative join available |
| REQUIRED RETIREMENT SERVICE | Intervening selected retirement turn plus native debt/deadline/progress and peer feasibility | Real debt and progress exist; which turns fall inside chosen receipt gaps is unresolved |
| URGENT / CONTROL SERVICE | Priority <2 operation entry/exit intersecting a wait | Mature sampled priority-0 and priority-1 completion/execution counters do not advance |
| CHECKPOINT / HEALTH SERVICE | Per-call callback spans; checkpoint handoff acquisition/release for logical mutation hold | Aggregate checkpoint holds and priority-4 work exist; receipt-local spans absent |
| FIFO WAIT BEHIND OLDER ADMITTED WORK | Both admission sequences/accepted times and execution spans | The production rule is proven; individual preserved source admissions lack the order fields |
| MAINTENANCE COROUTINE RESUBMISSION DELAY | Prior completion to next actual enqueue, excluding owner callback tail | Raw turn.exit to next request_submitted gives only a combined upper bound |
| IDLE / SCHEDULER DELAY | Complete owner-operation and mutation-handoff timeline leaving an uncovered gap | Cannot be obtained by subtracting worker/source/transaction totals |
| UNRESOLVED | Time for which the foregoing attribution cannot be bounded separately | Required classification for the unresolved receipt portions |

Between coherent samples at elapsed **210.337256385** and **300.470607412** seconds:

| Owner aggregate delta | Value |
| --- | ---: |
| Priority 0 completed / execution | 0 / 0 seconds |
| Priority 1 completed / execution | 0 / 0 seconds |
| Priority 2 completed / execution | 381 / 55.576534 seconds |
| Priority 4 completed / execution | 363 / 25.218685 seconds |
| Checkpoint handoffs / recorded hold duration | 42 / 4.193162 seconds |

These are completion-accounted counter deltas; boundary-spanning callbacks need clipping for an exact wall-interval occupancy calculation. Priority 2 includes source and checkpoint callbacks; priority 4 includes maintenance and health. The checkpoint hold starts inside its acquisition callback and can overlap that callback tail. **Do not sum these rows with storage-stage timings, worker timings or archive wait partitions.**

Unchanged urgent counters, disabled diagnostic ACKs and ongoing source advancement provide strong aggregate evidence against urgent/control service being the dominant mature-delay explanation. This is not a per-receipt exclusion based on a reconstructed operation trace.

## F. Source-batch attribution

The .165 control records 1,125 batches / 1,216 frames:

| Frames per batch | Batches |
| --- | ---: |
| 1 | 1,089 |
| 2 | 7 |
| 3 | 3 |
| 4 | 26 |

The raw source-batch schema records start, native_end, end, frames, committed, committed_total, native_seconds, CPU, retained COMMIT-floor wait and source-floor requested/actual wait. It **does not record**:

- pending_frames or consecutive ready-frame count at batch formation;
- either maintenance_pressure bit as read by maintenance_batch_limit;
- exact batch_limit branch result, the batch's priority or queue sequence;
- source owner submission/acceptance time.

For any recorded multi-frame batch, static source proves limit 8 was active and either both pressure flags were false **or** pending_frames was at least 16. It cannot distinguish those cases or recover the exact pending count. Conversely, a one-frame batch does not prove limit 1: a fast-path batch can contain only one ready frame or hit a barrier.

For the three requested representative intervals, pending frames, batch size(s), pressure flags, threshold branch, older-admission relation and clipped owner time are therefore not asserted. Extracting the raw source start/end arrays can establish intersecting native/floor execution and frame counts. It cannot recover the unrecorded formation inputs by treating coarse debt samples as instantaneous pressure.

An already-running source batch must finish before a maintenance admission can enter. Ordinary source does not preempt background SQL, and source transactions preserve wire order, per-frame savepoints and FULL durability. An older admitted source batch ahead of maintenance is legal FIFO service. Splitting a multi-frame fast-path batch may increase fsyncs and impair transport drain; the pressure exception exists to preserve bounded source reception. No evidence here proves that removing it would retain capacity and fairness.

A normal source batch starting after an already-queued maintenance request would contradict the FIFO rule unless it was actually older-admitted or urgent. The missing submission/sequence fields prevent using source start alone as evidence of illegal overtaking.

## G. Maintenance resubmission attribution

[serve().maintenance](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_service.py#L1330-L1366) does the following:

1. Awaits its single runtime.turn owner request.
2. Updates pressure flags after successful return.
3. Attaches the sole archive worker if flight.prepared exists.
4. If a side was selected, awaits asyncio.sleep(0) and promptly begins the next loop submission. Cooperative archive/background yield also uses sleep(0) and continues.
5. If no side was selected and a worker future exists, waits on that future with a shielded one-second timeout; completion can wake it before one second.
6. If no side was selected and no future exists, waits on stop for up to one second.

A normal successful nonfinal archive slice retains pending; its side is archive, so it takes **sleep(0), not the one-second idle cadence**. An intervening successful retirement turn also takes sleep(0). Health completion is awaited by a separate coroutine, not by maintenance.

However, an already-pending ready receipt with choose returning None takes the last branch: its future has been consumed, so no future wakeup exists and the loop can wait one second. Static source permits this under the no-feasible-side condition described in B. It has not been shown to recur in the control receipt sample, nor to admit a legal earlier archive operation under the same reservations. Removing that wait alone cannot make an infeasible side feasible.

The existing raw turns can answer whether the loop takes this branch: look for selected=None, error=None, pending_after=True, then measure to the next request_submitted. The raw turn exit/submission bound also tests ordinary prompt requeue. It does not justify calling the preceding owner queue wait a resubmission delay.

The published consumed-to-successor worker submission median is 0.001169703 seconds whole population and 0.001127149 seconds mature cohort. That supports prompt launch **after logical consumption** for a typical flight. It measures a different boundary from slice end to next maintenance enqueue. Mature mean is 0.053603945 seconds and peak 1.151107508, which may include legitimate idle demand and arbitration; neither is automatically wasted time.

Pure callback-completed-to-actual-enqueue delay additionally needs the owner's completion and accepted-enqueue timestamps. Those per-request timestamps are not persisted by this harness. The raw bounded composite is useful without inventing them.

## H. Retirement and fairness attribution

The control has actual retirement demand and durable progress. In the same approximately 210–300-second capacity interval, native retirement advances **73,844 records** (35,968 Meteora; 14,331 Pump; 23,545 PumpSwap). Record retirement cannot be discarded as archival overhead.

The preserved latest-decision observations show:

| Sample | Observed state and implication |
| --- | --- |
| ~210 s / frame 775 | Both sides ready and feasible; retirement selected, with 256 Meteora and 254 PumpSwap durable records. This demonstrates legal competition while a receipt obligation exists; it does not establish that this exact retirement admission was deadline-forced rather than preferred by debt surplus. |
| ~240 s / frame 866 | Both ready and feasible; archive selected, 512 durable records, owner_delay 0.658549 s. The wait cause cannot be identified from that number alone. |
| ~270 s / frame 985 | Archive unready; only retirement feasible and selected. This is required native retirement service while archive preparation is unavailable, not demonstrated displacement of a ready receipt. |
| ~300 s / frame 1096 | Archive unready; retirement selected, 588 durable records. Archive recovery headroom is shrinking, but high debt does not make a preparing receipt ready. |
| Fatal / frame 1214 | Archive unready; retirement ready; neither side feasible. Archive recovery headroom 5.624251 s cannot preserve the reserved peer completion at +9 s. The refusal is explained by the existing contract. |

These native owner observations have their own timestamps and are not an asserted atomic join to the nearby SQLite debt sample.

[Native retirement](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_plane.py#L641-L750) rechecks hot floors, recent coverage, pins, gaps and account floors, retires at most 256 record rows per mutation transaction, and tracks real committed progress. [Boundary rotation](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_plane.py#L783-L824) rotates after urgent service or the bounded allowance behind normal source, preserving later scopes under persistent dense first-scope debt. Record, continuity, floor and housekeeping demand have distinct valid progress obligations.

The 176 retention storage-stage errors in the whole control are not 176 proved rollbacks or wasted retries. A durable-boundary evidence_background_yield is counted as a storage-stage error; ServiceState.retention catches it and returns the committed outcome for native arbiter completion.

For an intervening retirement turn to be called avoidable, its fresh feasible set, deadlines, debt scores/rate window, scope origins, decision reason and successor consequences must show that archive could legally have run earlier while retaining retirement service. The per-flight turn schema does not include all of that decision state. Five-second latest-decision snapshots and the final rolling rings cannot supply every evicted turn. No retirement-starvation proposal is made.

## I. Bounded counterfactual

**No admissible X-before-Y counterfactual is established.** No pair is presented as both already admitted with known sequence/priority, measured execution and preserved higher-priority/peer requirements. An older source admission cannot simply be moved behind archive on the strength of archive debt; a not-yet-submitted maintenance request cannot be selected earlier as if it were queued.

The following bounds are descriptive, not a scheduling proposal:

- Whole mean post-first-entry ready delay: 63.769122 ms, which remains a mixture of actual owner work and subsequent turns.
- At least 3,695.089686 ms after first ready-observing entry for the mature maximum-ready-delay receipt. Its causes and admissible improvement remain unresolved.
- Mature ready-to-first-commit plus per-flight summed inter-slice gaps total 50.117166711 seconds across 85 completed flight partitions. This is the size of the investigated timing envelope, **not recoverable time**.
- A later nonurgent source admission has **zero opportunity to overtake** a maintenance request already in the FIFO queue under the pinned selection rule. This rules out that specific priority-only theory; it says nothing about older work, urgent batches, or the interval before maintenance submits.

No source service, retirement service, queue wait, checkpoint hold or coroutine interval is subtracted twice. No new scheduler simulation or workload timing is introduced.

## J. Capacity relevance and remaining repair direction

Coherent control snapshots from elapsed 210.337256385 to 300.470607412 seconds span **90.133351027 seconds**:

| Quantity | Value |
| --- | ---: |
| Inferred eligible arrivals | 87,912 records |
| Durable archive drain | 74,176 records |
| Net added eligible debt | 13,736 records |
| Arrival rate | 975.354838 records/s |
| Drain rate | 822.958418 records/s |
| Drain-rate shortfall | 152.396420 records/s |
| Increase over observed drain just to match arrivals | 18.5181% |

Clearing prior recovery debt within original deadlines requires additional surplus. Merely explaining the terminal 3.375749-second reservation shortfall is not a demonstrated capacity repair.

The 85-flight launch cohort is a different timing population; its 50.117-second investigated-wait sum cannot be converted into rows or compared as if all of it lay within this 90.133-second capacity interval. Required service must be retained before any recoverable time bound is meaningful.

The source floor is implemented per batch as:

    wait = max(0, .165 * frame_count - native_elapsed)

For the **fixed observed whole-arm batch partition**, native source wall is 167.074015578 seconds and requested injected source wait is 38.482058591 seconds. Their sum is 205.556074169 seconds. The immutable per-frame floor for 1,216 frames is 200.640000000 seconds. Consequently the entire observed native excess above that floor is only **4.916074169 seconds**, before accounting for which batches overlap pressured receipts or when recovery needs the service. Actual injected sleep overshoot adds 0.541793776 seconds; it is measured timing, not promised recoverable capacity.

Optimizing native source work already below .165 seconds/frame at the unchanged batch partition simply increases injected waiting by the same amount. The mean native cost being below the floor does not prove every batch is below it; the whole-arm excess proves some batches exceed their own floor. A capacity claim requires identifying that excess or another demonstrated effect, not claiming all 167 seconds of native work is available.

The strongest defensible remaining *static examination* is therefore the measured serial owner critical path—native source work above its immutable floor, native debt/retirement work, archive snapshot selection and commit SQL, or checkpoint holds—after the raw interval join identifies a recurring bounded cost. This report does not select or authorize an optimization. Commit-stage service itself averages only 63.489451 ms per mature flight; removing its entire necessary cost is neither legal nor an established solution to the 18.5181% rate deficit.

The paired treatment demonstrates pressure sensitivity conditional on reduced ACKs and one fixed-order experiment; it does not identify the minimum repair at unchanged .165 load. No qualification or recovery credit is claimed for source changes below that floor.

## K. Exact conclusion and proposed next step

**No specific bounded scheduling defect has been established. Required service is substantial, but receipt-local dominance has not been established either.** The remaining supported category is a mixture that the currently inspected evidence cannot separate.

Decision-rule assessment:

| Required condition | Assessment |
| --- | --- |
| Recurring particular delay | Aggregate delays recur; specific receipt-level mechanism unresolved |
| Attributable to avoidable allocation rather than required service | Not established |
| Large enough to affect archive deficit | Investigated envelope is large; lawful recoverable bound unavailable |
| Preserves source, retirement, fairness, urgent work, leases, reservations, deadlines and transaction bounds | No concrete counterfactual proves this |
| Narrow and testable minimum change | No qualifying proposal |

The next step is **OFFLINE/static only**: extract the existing bound ZIP in an environment with a local file reader, verify the bound control members, apply the three selection rules in C, and join commit/turn/source spans on the same-host monotonic clock. That resolves receipt identity, individual T0–T7 markers, intersecting source frame/service costs, intervening retirement turns and the bounded resubmission composite. It spends no material execution and must not invoke harness.py, pair.py, service.serve or a workload.

Even after that join, these fields are absent from the preservation schema:

| Missing event/field | Why it matters | Can the existing raw files restore it? |
| --- | --- | --- |
| Per-request owner label, priority, sequence, actual acceptance, dequeue/entry and completion clocks for source, health, checkpoint and maintenance | Distinguish older-admitted FIFO work from pre-submission delay; enumerate every owner operation | Maintenance callback proxies and source execution spans allow partial bounds, but not the complete ledger |
| pending_frames, ready prefix/barrier state, exact pressure bits and returned batch_limit at source batch formation | Distinguish the >=16 transport exception from false/stale pressure; quantify safe allocation opportunity | No exact reconstruction from source frame totals or five-second samples |
| Each checkpoint handoff acquisition and matching release clock | Clip logical owner holds to receipt waits and distinguish them from idle | Aggregate hold totals and sampled endpoints cannot restore all individual holds |
| Per-turn fresh need/deadline/origin/rate and decision feasibility/reason/score state across the mature cohort | Determine whether intervening retirement is deadline/reservation-required, fairness-required or legally reorderable | Latest observations/final rings resolve some turns, not the evicted complete sequence |
| Previous owner callback completion and next actual maintenance enqueue | Isolate pure resubmission delay from callback tail and future delivery | Raw turn.exit/request_submitted provides only an upper bound |

If the offline join leaves a purported defect dependent on these fields, **only a separately reviewed runtime measurement can resolve it**. The specific measurement requirement is a bounded per-admission event ledger and batch-formation/arbiter-state fields above, with one common monotonic clock and no evidence bodies. It is a requirement returned for review, not authorization to instrument production or run a fifth execution. No runtime measurement is performed or prescribed for immediate execution here.

Verification in this task was static: pinned source/blob/mode comparison, inspection of preservation code and CI projections, and arithmetic over existing aggregates. No production service, pressure workload, Stage E/F, M1 repair, preflight repair, canonical qualification change, successor freeze or material diagnostic was run. The sole new repository file is this paper report on a separate documentation branch; its commit suppresses push CI.

**STOP. Budget remains 4/6 consumed; 2/6 unused. PAPER ONLY.**

SCHEDULING_ATTRIBUTION: EVIDENCE_INSUFFICIENT
