# Owner-review checkpoint — stopped, preserved, not operationally ready

The current work is complete for this checkpoint. The owner requested a pause
after the running diagnostic and its analysis, not another repair iteration.
PAPER is inactive, disabled, `Restart=no`, and funding/allocation admission is
closed. No market children or provider reservations remain. Standing issue134
is retained; further discretionary execution waits for owner direction.

**Source identities.** Branch `repair/consolidated-startup-followup-20261014`,
draft [PR133](https://github.com/levonmendall/The-Meme-Machine/pull/133).
Reviewed baseline `ced262d4b488059fcc555f7684ec95b86221d546`; implemented,
focused-tested and executed attribution candidate
`b007217e7930fa728604df4aa2a96f68f998e1ec`; its specification/validation publication
`268a76fe1f6ea5cec15a6d2e80c565e1f4d5b745`. After verified native/financial
post-review, compatible source/configuration rollback restored installed
`66f85d61bf4d3ba9a01efdc0e9eb68949419bda8`. The latter is stopped rollback source,
not the latest engineering candidate. No database was rewound. The restored
finite diagnostic unit must never be started unchanged as normal operation.

The [machine-readable result and private evidence hashes](evidence/operation-attribution-pause-result-20261015.json)
retain exact measurements, failed probes, helper identities and state references.
Original failures, including all historical RECOVERY_REQUIRED results, remain
unchanged. Private evidence stays in the existing sibling
`blocker-repair-20261011`; the new run is
`/var/lib/meme-machine-diagnostics/20261015-operation-attribution-b007217e-132123`.

**Completed engineering.** The new opt-in recorder measures 30 fixed reached
operations: candidate selection/reactivation/promotion/demotion, binding/history
planning, economic ingestion/storage/outbox, capture/ACK/publication/checkpoint/
maintenance, and actual Pons discovery/hydration/Survivor/reporting callbacks.
It separates executor queue time, thread CPU, wall time, kernel runnable delay,
direct synchronous children, and selected SQLite statement/executemany/fetch/
transaction/checkpoint API costs. It retains immutable collection clocks and
explicit missing/unexercised states before generic clipping. No SQL text,
bindings, frame locals, new writer, provider or scheduling mechanism was added.
The first SQLite exception gets essential facts before optional operation lookup.
Exact reversible source guards retain every existing economic assertion.

Compact equivalent-value JSON and a 300-second diagnostic post-startup option
fit the unchanged32MiB output allowance, including two protected64KiB terminal
reserves. Original300s readiness,900s startup,1800s work and1865s absolute limits
remain. Actual output was13,921,902bytes. Detailed SQL iteration timing added
about14ms CPU per2000 disposable rows in the supporting probe; this diagnostic
overhead is disclosed, not assumed zero. No throughput behavior correction was
introduced in this candidate.

Two preparation guards stopped before any PAPER start/provider dispatch: an
old template-source placeholder, then the controller's inherited0077 umask
making its disposable root-created clock unreadable to the service UID. The
template identity and invocation umask were corrected; actualUID997/GID987
access passed. Both failures remain retained. Exactly one PAPER start followed.

**Latest live result.** The run stopped at905.037s with STARTUP_LIMITATION,
original readiness FAIL and acceptance0minutes. Source release occurred around
218.6s; the first sample with both native workers reconciled was628.710s.
Native restoration therefore did not meet the300s readiness contract.

There was a natural Pump native INTERNAL error between sampled818.963s and
824.284s. A reconnect was followed by a **2207-slot newest-stored-head jump**
between845.477s and850.753s. The source's existing `rolling_replay_boundary()`
deliberately preserves a missing-WebSocket-history gap and starts a prospective
linked tail. The jump is not completed historical processing. The initial raw
analysis's9.467 post-native head-units/s crosses this discontinuity and is
explicitly rejected as continuous durable throughput; both analyses survive.
No required gap was subtracted, skipped or relabelled complete.

The useful comparison is the190.253s interval after both native declarations
and before that error. It is still failed startup, not sustained operation:

| Same-generation pre-error measurement | Result |
| --- | ---: |
| Shared CONTROL arrival-side proxy |3.710851 slot units/s|
| Joined head |1.498006|
| Prepared head |1.487494|
| Durable completion timing head |1.508519|
| Minimum newest retained economics |1.466469|
| Verified strategy-usable program frontier |UNAVAILABLE|
| CONTROL-minus-stored proxy gap |1321→1748 slots|
| Retained market-evidence age |354.149→483.402s|
| Process-group CPU |1.728920 cores|
| Cgroup throttling |13.890s|
| Owner thread CPU / runnable delay |37.760s /81.967s|

CONTROL is a locally received proxy, not independently measured full-market
arrival. Native backpressure can delay it too. Approximately2.46times the
measured durable-head progress would match this proxy in this slice; that is
not a new acceptance target or a proven hardware requirement. Different market
workloads, startup conditions, instrumentation and the reconnect prevent a
controlled speedup comparison with O13's4.534/2.112 measurements.

**What attribution established.** The owner remains essentially continuously
occupied. Completed callback deltas181.463s plus actual checkpoint holds9.829s
cross the190.253s sample boundaries; their191.292s sum must not be reported as
an exact occupancy percentage. Queue waits overlap execution elsewhere.

| Reached owner component, same pre-error slice | Wall s | Thread CPU s |
| --- | ---: | ---: |
| Candidate commit callback |54.143|12.197|
| Scout commit callback |41.805|8.290|
| Maintenance decision callback |23.033|5.796|
| Candidate development callback |17.867|3.350|
| Retention callback |14.839|1.324|
| Inner rolling store, included in candidate work |23.782|4.102|
| Inner history outbox, included in candidate work |9.137|2.326|

Scout commits issued68301 selected statement calls and39867 fetch boundaries;
selected statement time was29.514wall/3.006CPU seconds. Rolling storage used
1722executemany API calls,18.923wall/2.625CPU seconds. These are API boundaries,
not unique SQL plans or complete logical-step counts. There were853authoritative
COMMIT calls/11.632wall/1.810CPU seconds. Checkpoint native execution6.602s and
logical owner-handoff9.829s have different boundaries and are not added together.
SQL durations, runnable delay and parent timings overlap. They do not identify
a lock holder, GIL owner, physical-device saturation or pure fsync time.
Commit latency percentiles and the specific competing SQL/lock actor remain
unavailable; aggregate timing and reached source operations are established.

Actual Pons executor CPU was Survivor step39.683s, Current discovery25.874s and
hydration25.257s. These paths respectively reached584810,430873 and698686 selected
fetch boundaries. Reporting used3.764CPU seconds; Survivor enrichment used
0.008s. Some reporting work is nested: these figures are not added into a second
process total. Current hydration completed23callbacks with exceptions in this
slice; those are fail-closed acquisition outcomes, not successful qualifications.
Fetch boundaries include iteration and fetch calls, not distinct decoded records.
The whole270s post-native scope measured Pons0.677, source0.559, Pump0.320 and
supervisor0.094CPU cores, but includes the reconnect and is resource evidence only.

The evidence supports an affected **subsystem** problem involving serial
candidate/SQLite work, competing native CPU and recovery/publication dependencies.
It does not yet prove one removable SQL operation causes the whole deficit.
Cold-history metadata remains negligible:314calls/0.137CPU seconds here. The
earlier rejected cold-metadata optimization remains rejected. One minor query
change cannot be represented as a demonstrated whole-machine solution.
Whether two CPUs suffice after a coordinated correction remains UNVERIFIED.

**Previously completed grouped storage/Pons improvements remain intact.**
[The authentic offline comparison](CANONICAL_BATCH_ARCHITECTURE_20261015.md)
inserted3023unique retained records: canonical storage API calls36404→896,
logical steps36404→18685 and transaction CPU0.555194→0.339636s, preserving64commits
and exact economic/order/receipt/lineage/cursor state. Provider audit indexing
reduced isolated caller CPU0.450227→0.270086s and logical reads412.365→15.340MB.
Pons final reporting used1rather than4history reads on two retained candidates.
These are demonstrated component savings, not additive whole-machine percentages.
Later live runs still failed readiness; current bulk storage remained reached
with no scalar economic fallback in the pre-error slice. The existing off-owner
preparation, historian, independent history consumer and event-driven publication
were retained, not rebuilt.

**Candidate and provider readiness.** All four actual native policy bindings
remain `paper-opportunity-access-v1`. Six opportunity-access changes, nine
original economics, attention-only volume quality, Current/Survivor independence,
long-duration winners, smaller executable sizing, partial exits and scaling are
unchanged. Meteora/Ramses remain paused. Source release and native discovery are
observed; reliable discovery→complete evidence→qualification→PAPER execution is
NOT established. Current program checkpoint/proof rows remain absent in the
checked scope; sampled pending proof CONTROL bounds were unavailable. No missing
evidence was authorized as complete. Current sampled237canonical identities have
207authentic exact ACKs and30preserved pending obligations; this is not a census.

Managed Pons used the existing Alchemy route. A bounded4096-completion ring,
covering before run start, contained2154current-run transports:2152HTTP200 and
2transport-deadline failures, no recorded429 and no retry rows. Maximum recorded
admission wait was0.325s. This covers those retained paths, not provider suitability
or all external traffic. The current candidate-row artifact separately records
70incomplete outcomes:53stale evidence acquisition,13missing/stale native USD,
3pre-transport deadlines and1during-transport deadline. Candidate queue waits
reached12.662s; this differs from provider-admission waiting. The USD mechanism
is not yet diagnosed. No positions exercised complete quote/USD protection or
the original Survivor3s/Current5s deadlines. Public-RPC throttling, managed
capacity/coverage and original READONLY INSERT remain separate requirements.

Current FINALIZED replay/filter acceptance was previously observed in the
[bounded capability test](NATIVE_REPLAY_CAPABILITY_RESULT_20261015.md); historical
replay rejection and exact provider replay semantics remain unresolved. This run's
natural INTERNAL/reconnect adds actual reliability/continuity evidence, not proof
that the original replay failure is repaired. Original SQLITE_BUSY and Pons
READONLY INSERT were not reproduced or repaired by this attempt.

**Validation.** Supported network-blocked runner; CPython3.12.14/SQLite3.45.1 on
the actual two-vCPU host. Final affected runs:122/122 focused;294/294 integration
with instrumentation enabled, including actual supervisor/child startup rehearsal,
cancellation, history/ACK, accounting, active strategy and protection regressions;
140/140 final source-guard/collector. Counts overlap and are not summed as distinct
tests. Initial113cases had2fixture errors; initial140had2source-guard test failures.
Corrected successors passed; original logs/scratch remain. An initial completion
analysis read the wrong audit timestamp and failed without a verdict; corrected
bounded analysis uses actual `admitted_at`. Initial raw head-rate interpretation
was corrected for the native discontinuity. No failed result was erased.

[CI38741708842](https://github.com/levonmendall/The-Meme-Machine/actions/runs/38741708842)
passed the exact b007217e Pump held PAPER offline proof. Draft FAST runs
[38741715877](https://github.com/levonmendall/The-Meme-Machine/actions/runs/38741715877)
and [38741849724](https://github.com/levonmendall/The-Meme-Machine/actions/runs/38741849724)
were skipped, not passes. Earlier manual full run
[38652038787](https://github.com/levonmendall/The-Meme-Machine/actions/runs/38652038787)
passed `c8beb2d1317084779f97214b6015b7c345242085`; it is not exact-source final
release proof for b007217e. No new full FAST or complete OPERATIONAL was dispatched.
Those remain final promotion gates, not routine narrow-repair requirements.

**Financial, shutdown and recovery state.** Independent9572bounded read-only
postqueries/3.022s verified25required checks, without failed/unavailable checks
inside that named scope. Exact338-event suffix replay reached journal12276,
hash `4b6722660efa0e2c0fca72d8b867630e379715b32eda374d7846793c1757935c`.
Cash$1000; all eight monetary obligation categories zero. The338events comprised
313runtime publications,24owner updates and1OBSERVATION admission; no trade or
capital action. Historical$500 head2036/inception/checkpoint remain preserved.
All earlier checked named cohorts remain present or authentically ACKed.

Both native workers independently show current-instance STOPPED/reconciled,
TERM and exit0; no KILL. Controller exit and empty processes alone were not used
as proof. Financial reconciliation is separate. **Global accepted-source-frame
drainage remains UNAVAILABLE**: source `run/live` cancels commit tasks before a
global accepted-queue join, including on replacement/error paths; final IPC omits
the richer terminal pipeline census. This is a confirmed missing ownership/drain
handshake, not evidence of known durable-record loss. Required partial/replay and
outbox/proof work is retained. No universal recovery or retroactive PASS is claimed.

The existing compatible recovery point
`meme-machine-paper-20261013T221423-5891a20c` remains applicable:301entries and
manifest SHA `f3a6b3f8d0b69a86c470cda0b307491d03ea05dff4959729f4c9d168a608adf0`
were freshly checked against retained restore/integrity evidence. The later failed
backup remains unusable. No bulk copy or full integrity campaign was repeated.
At pause: volume free16.260GB; root free11.778GB; canonical DB18.643GB and WAL38.102MB.
One canonical copy plus the5GiB reserve alone needs **7.752GB more** on that volume,
before other state, WAL growth or isolated restore. Earlier6.908GB was a historical
lower bound. Backup process-group freezing also lacks held-protection compatibility.
Backup timer is unchanged; no backup process is active. No storage was purchased,
evidence deleted or reserve reduced. Current state/evidence is durably retained
locally; a new complete off-host/current recovery point was not manufactured.

Provider usage:2165physical starts including6native openings,7626logical RPC
elements,266688CU. Accounted native bytes727554073, with436207616uncertain bytes
reported separately; HTTP bytes12095557, with16777216uncertain. These meter fields
are not all confirmed delivery and must not be blindly summed. Native failures1
matches the observed INTERNAL count. All provider reservations/streams/receipts
closed. Frozen-model exposure$0.262206177345; provider invoice UNAVAILABLE.

**Remaining work, in priority order.**

1. Fresh complete strategy-usable Pump evidence: resolve the demonstrated serial
   candidate/owner workload and CPU scheduling contribution, preserving required
   acquisition and completeness. Profile/reproduce the reached scout/lifecycle,
   economic/outbox and Pons Survivor/hydration work using bounded disposable
   fixtures; compare a targeted batch correction with coordinated pipeline
   refactoring. Do not repeat the closed full historical replay search or claim
   another minor optimization can supply the missing whole-machine capacity.
2. Coordinate ModelB interruption/reconnect/drain ownership. Use existing owners:
   close intake, settle handlers, finish accepted durable commits, preserve partial
   replay gaps, cancel idle workers, retain terminal counts. Cover normal stop,
   replacement and transport error under original deadlines. This is proposed,
   not implemented. A prospective current head must never count as gap recovery.
3. Diagnose managed-Pons missing/stale USD and candidate acquisition deadline
   outcomes. Preserve native quotation/valuation and3/5s held protection; accepted
   HTTP requests alone do not solve this. Historical public429 and READONLY need
   their own evidence-supported dispositions.
4. Complete current backup/storage and protection-compatible maintenance design.
   Size the full recovery/restore requirement before any least-cost storage
   decision; purchasing capacity remains outside authority. Preserve current
   backup failure and existing verified point.
5. With these operating gates satisfied, demonstrate actual four-regime candidate
   progression and uninterrupted protection, finalize one coherent candidate,
   complete FAST/applicable OPERATIONAL once, perform genuine60-minute PAPER
   acceptance, then use a verified continuous-service profile. No diagnostic
   minute, synthetic trade or disconnected healthy interval counts.

Reporting/journal cleanups and negligible cold metadata are optional efficiency
work, not new acceptance prerequisites. No defensible total engineering ETA or
two-CPU capacity guarantee is available. The drain-handshake work is a bounded
subsystem change with existing disposable fixtures; the throughput/valuation
mechanisms still need causal proof before their effort can be estimated.

**Final decision.** What works: integrated strategy source, scoped offline
startup/safety checks, current provider acquisition, durable local retention,
sampled exact ACKs, actual graceful native stops and monetary reconciliation.
What does not: timely readiness, fresh complete strategy-usable evidence,
sustained concurrent capacity, verified held protection/current backup and
autonomy. The single primary blocker is **fresh, continuous strategy-usable Pump
evidence under concurrent load**. The next resume task is a coordinated
candidate-processing/owner and recovery-contract correction driven by the
pre-error profile, not an unchanged live retry. Owner review comes first.

Process/financial/persisted-state pause is verified; complete global source-frame
drain/recovery remains explicitly limited. No engineering tests, market workloads,
new starts, acceptance or autonomous campaign will follow this publication until
the owner directs resumption.
