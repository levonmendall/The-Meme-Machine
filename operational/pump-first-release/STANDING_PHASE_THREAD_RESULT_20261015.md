# Current operating checkpoint: cancellation verified; capacity still fails

Executed `1ee2d5fa6d660e696166f16b772d456b8c0a55d4` under specification
`76a48e67fcb2ef53a2cb82e3c8d5db7d2812b2ee`. Receiving branch is
`repair/consolidated-startup-followup-20261014`, draft PR133; root is the single
integration, testing and runtime owner. Standing issue134 remains effective.
The runtime change added attribution, not a throughput repair. Six active
opportunity-access-v1 changes, nine original economics and volume quality remain
unchanged. No full FAST was dispatched for this diagnostic.

The guarded run stopped after **904.652seconds** with `STARTUP_LIMITATION`:
original300-second readiness **FAIL**, funding closed, acceptance0. The first
declared native-reconciled full samples were Pons218.275s /Pump493.197s. Source
startup release remained false; this was not steady-state or normal PAPER.

Both actual native workers reached STOPPED/reconciled and exited0. Current
PID/process-instance/run-bound TERM/wait/final-health records show Pump2.787s
and Pons3.302s after their TERM requests. No KILL was required. This is the
second observed graceful stop following the indexed creation/cancellable-restore
repair. It proves these workers' stops, not all accepted source-frame drainage
or every future recovery. Historical RECOVERY_REQUIRED results remain unchanged.

## Current-run throughput and causal limits

One generation,493.197→897.862s,404.665seconds,79complete samples after both
native declarations. Slot heads use comparable units; shared program progress is
not summed. Completion-window deltas are not an atomic event census.

| Stage | Slot units/s |
| --- | ---: |
| CONTROL arrival-side receipt |4.6038|
| Joined |2.1227|
| Prepared |2.1104|
| Durable timing head |2.1227|
| Newest retained economic head |2.1030|
| Fixed program publication |2.1005|

Receipt-to-stored gap grew **1117→2129slots**; stored-to-published gap stayed
3→4slots. Stored market-evidence age grew258.1→475.8s. Thus the deficit is
materially before economic persistence; a frontier-display-only explanation is
insufficient. The diagnostic does not establish that missing evidence never
blocks individual proof obligations.

The serial candidate path consumed97.832s preparation/transfer/wait,
168.706s owner waiting and137.165s owner callback execution:403.703of404.665s
for859completed frames. Preparation-worker wall68.239s is already inside the
97.832s; its difference is not proof that all remaining time is serialization.

Largest exclusive candidate phase: `SelectiveHistory.ingest → economic_store`,
76.300wall /21.147thread-CPU /33.036actual-thread runnable-wait seconds.
Delivery-outbox construction:26.828/8.545/12.165. Batch transaction exit:
11.641/3.130/3.281; this includes context-exit/notification, not pure fsync.
All phase failure/unmeasured/runnable-unavailable flags remained0. Phases are
exclusive but not exhaustive. Their CPU and runnable time overlap phase wall.

Whole-owner callback wall383.248s and actual checkpoint handoff holds23.781s
show substantial contention for the serial owner. Do not add inclusive checkpoint
spans108.431/124.739s: they include work/waits outside exclusive handoff holds.
Candidate queue waits overlap other owner work. Source-commit, maintenance,
delivery capture and ACK totals are overlapping labelled views, not independent
time to sum. SQL recorded1721commits /28.080wallseconds; no lock holder or
specific avoidable transaction was identified. No new SQLite fatal was captured.
Original BUSY and Pons READONLY INSERT remain **not reproduced, not repaired**.

Service CPU averaged1.677cores, including source273.74CPU seconds and Pons
289.27; source owner102.486s is included in source. Service cgroup throttle
time18.693s and owner runnable delay174.368s are observed scheduling measures,
not evidence of GIL ownership, a SQL lock, physical disk saturation or irreducible
hardware insufficiency. Current two-vCPU capacity remains **unproven**.

No post-native retirement execution occurred. One earlier retirement callback
peaked0.206s; the old53-second callback did not recur, but this run is not another
complete archival validation. Earlier verified separation/preparation/consumer/
event-driven changes remain; none establishes whole-system capacity by itself.

## Pons and the rejected offline correction

All79post-restoration samples retained six current kernel threads without
truncation. Pons289.27CPU seconds were distributed: Survivor97.829, main87.578,
hydration52.548, two discovery threads51.146, health0.166. This disproves main
telemetry alone accounting for the cost. Logical reads115.628GB versus24KiB
physical reads identify page-cache traffic, not device-read saturation.

One bounded offline real-caller comparison evaluated fixture-only narrow seq
indexes on the three existing4096-row provider audit rings. Both variants used
the same real shared admission/accounting path,32mocked four-element transports,
synthetic copies of real offline audit bodies and equivalent usage/retention
checks. The existing fixture uses the development2-RPS fake-clock admission
profile; this is not the installed10-RPS workload or a market replay.

The4.925s pair preserved exact retained rows, append-only guards, durable
initiation before mock HTTP and identical usage deltas. Logical read bytes fell
452.143→19.556MB; read calls110732→5120. CPU only fell1.825→1.748s, and writes
increased10.945→12.296MB. SQL operation counts and quantized VM work were
unchanged. This is **not a material CPU or whole-machine throughput repair**;
no production indexes or accounting changes were implemented. Initiated-attempt
and completion accounting are distinct crash-safety obligations, not redundant
writes to delete. No further unchanged index experiment is justified.

Managed-provider queue health was CURRENT, max sampled depth1/wait1.166s.
The retained projection does not establish every response status/method or actual
quote/USD latency. Both native portfolios were flat; held-position3/5-second
protection, provider suitability and backup compatibility remain unverified.
Public pacing/batch feedback retain offline proofs; they do not establish the
original429quota. The canonical managed route does not silently fall back to
public mandatory acquisition.

The single sequential offline pair does not establish statistical confidence or
identical OS-cache conditions. Its timing includes the same bounded correctness
and scratch checks in each variant. No percentage is extrapolated to market
processing, provider bills or the whole host.

## Recovery, accounting and evidence

Post-run read-only review:463bounded queries /4.743s, no failed/unavailable
required checks. Current authenticated financial tail/projected state agree at
head10311 (`f9886bd17204281b339096f844d12e82d8d2b4b8fd9a02d2372d784092dc2cb4`),
$1000cash, all eight obligation categories empty. Historical$500 accounting,
allfourv1 bindings, native ownership and preserved pending-work witnesses agree.
Independent short reads/named witnesses are not a whole-store integrity census.

Current bounded canonical-cohort union160:128authentic receipts/exactACKs,
32pending identities retained after stop. Prior current32 are now exactly ACKed;
earlier retained cohorts remain preserved/authentic. No fake completion or cursor
rewind was used. Complete required-history backlog, proof eligibility and
strategy-consumption rate remain unavailable; source-frame drain cannot be
inferred solely from the worker stop. These limits remain explicit.

Usage:388692CU,10762logical elements,2877physical starts including4native
openings;609321817delivered native bytes plus285212672uncertain accounted
native bytes,16307217HTTP bytes plus16777216uncertain accounted HTTP bytes.
Frozen-model exposure **$0.297989421345**; provider invoice unavailable. Streams,
HTTP receipts and provider reservations closed. No fixed spending gate added.

The scheduled04:01:56backup failed ArtifactStorageFull and remains unusable;
it was not interrupted, deleted or substituted for the older applicable recovery
reference. Active backup's process-group freeze versus3-second protection remains
open. No bulk copy, hardware purchase, quota change or backup-timer change.

Compatible rollback restored clean66f85d61 and saved overlays at05:12:48Z,
without any database rewind. PAPER is inactive, disabled, Restart=no, funding
closed. Do not start the restored old finite launcher unchanged.

## Validation and next decision

Executable1ee retains the focused diagnostic gate: initial247cases246PASS/
1stale duplicate-field assertion ERROR; corrected affected collector plus four
exact source/economic guards34PASS; final30collector PASS. Integrated startup,
canonical/pending-history and cancellation cases passed in the initial run.
This is not an uninterrupted247PASS or general release PASS. Earlier completed
FAST38652038787 passed only olderc8beb2d source. Final FAST/applicable complete
OPERATIONAL remain promotion gates, not routine diagnostic costs.

The demonstrated limiter is the serial preparation/owner path under concurrent
load; its largest measured candidate suboperation is economic_store. No specific
avoidable operation or lock has yet justified a production throughput correction.
The Pons audit-index hypothesis is rejected as a material remedy. Do not retry
this same live source/conditions or claim a controlled speedup over older runs.
Only a causally specified, bounded discriminator or measured correction can
justify further runtime work under standing authority. No routine reapproval is
needed, but genuine recovery/provider/protection gates still apply.

**STOP — INSUFFICIENT EVIDENCE FOR A JUSTIFIED CORRECTION OR DECISIVE TEST**
for the current throughput-optimization branch. A final bounded source review
found required per-record identity/conflict, availability, address, lineage,
receipt and cursor work. The known repeated transaction-level `attest_order`
tuple is a hypothesis of material savings, not a demonstrated solution. Existing
small authentic frame fixtures can time the real function, but cannot reproduce
the measured large-state cost; repeated ingest measures duplicates and fabricated
identities change the workload. Do not reopen the closed historical replay search
or turn that microbenchmark into a capacity claim.

The missing technical fact is operation-level productive CPU/SQL attribution
inside economic_store and the expensive Pons roles that supports a causal
intervention of meaningful size. A newly available faithful fixture or a bounded
measurement with a stated discriminator and acceptable overhead could reopen the
affected branch. Standing authority remains available; no routine owner approval
is requested. No further production repair, provider workload or live start is
scheduled from this result. Other safeguards and historical evidence stay intact.

Raw output:
`/var/lib/meme-machine-diagnostics/20261015-standing-phase-thread-1ee2d5fa-045539`.
The small evidence index records private artifact locators and hashes without
copying databases, credentials or retained historical bundles into Git.
