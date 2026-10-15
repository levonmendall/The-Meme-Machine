# Coordinated repair: final engineering evaluation and owner-review pause

**OVERALL STATUS: FAIL — autonomous PAPER readiness was not achieved.** The
repairs removed demonstrated repeated work in controlled component fixtures and
improved the observability of source shutdown. The integrated market test still
failed startup readiness, sustained processing, timely evidence delivery and
strategy progression. Both native workers stopped gracefully, but the new global
source census reported two unsettled accepted handlers: **RECOVERY_REQUIRED**.
No acceptance phase began; qualifying acceptance time is **zero minutes**.

This completes the owner's requested campaign. No subsequent repair, second
observation, provider workload, acceptance attempt or autonomous continuation is
scheduled. Standing issue #134 is preserved, with discretionary execution paused
pending owner review. Historical failures remain unchanged.

## Exact scope and provenance

| Item | Identity |
|---|---|
| Reviewed predecessor / prior owner pause | `f52be1e134b3471470d47c181df63c71192cf50c` |
| Implemented, final focused-tested, installed and executed source | `a793bd580593a87d17a0ab6e5e8581943bec6886` |
| Pre-test specification publication | `edb386c599e236179d3a9122201b9a7c7198b16c` |
| Branch / integration and test owner | `repair/consolidated-startup-followup-20261014` / root |
| Draft PR | [#133](https://github.com/levonmendall/The-Meme-Machine/pull/133) — remains draft, unmerged |
| Runtime | CPython 3.12.14, linked SQLite 3.45.1, existing two-vCPU host |
| Service limits | 1.8 CPU cores, 6 GiB memory, original provider/resource controls |
| Controller SHA256 | `1c18f503c25d8950edd29cd205a24c705f1362f6f058eed0aa796ac26a786656` |
| Installed unit SHA256 | `ad8239060b22ba33793b91e183bb6e11c1f803d8d2feb9c47bbe62b7973f942b` |
| Observation environment SHA256 | `a2ca8e11dd2843046f490be96d7d793c9b27ba6ce9b805fbfbf24112f0042df3` |

Retained run:
`/var/lib/meme-machine-diagnostics/20261015-coordinated-pipeline-a793bd58-144649`.
The clock began approximately **2026-10-15T14:48:10.028Z**; final collection/drain
completed approximately **15:03:17.809Z**, **907.782 seconds** after origin.
Work stopped at 900.170 seconds. The controller's result is
`STOPPED_REVIEW_REQUIRED / STARTUP_LIMITATION`, original readiness `FAIL`.
The requested 300-second post-startup measurement never began because overall
readiness never passed. Later post-native analysis is diagnostic evidence only.

The [hashed final evidence index](evidence/coordinated-pipeline-final-evaluation-20261015.json)
references original private receipts, metrics, source, tests and analysis without
copying historical evidence collections. The earlier
[repair record](COORDINATED_PIPELINE_REPAIR_20261015.md) and
[pre-live validation index](evidence/coordinated-pipeline-validation-20261015.json)
remain the original scoped records. The report's publication is the Git commit
containing this document; it does not change executable a793bd58.

## Evaluation of the implemented corrections

All changes below are in a793bd58. None changed strategy economics, provider
routing, timeouts, queue limits, financial authority or protection deadlines.

| Correction and supported cause | Controlled evidence | Independent disposition |
|---|---|---|
| Scout selection: each locator repeated market/lifecycle/pin reads. `solana_scout_selection.py`, `SelectiveHistory.observe_many` and lifecycle calls now use one bounded view inside the original atomic command, updated after ordered mutations. Identical canonical JSON is hashed once. | 64 authentic retained scout projections, each input once in separate fresh disposable stores; exact predecessor methods versus corrected methods; three alternating untraced pairs plus a separate SQL-traced pair. Reads **586→3**, statements **1064→481**, one commit both; identical rowids and durable-table digest. Median CPU **22.147→15.401 ms**, wall **23.110→16.448 ms**. | **PASS for this component's redundant-work correction.** Not a faithful full-market replay or proof of concurrent capacity. Live scout work remained material. |
| Event outbox: repeated per-record identity/availability and sequence lookup. `SelectiveHistory._queue_events` now uses bounded identity groups, one sequence allocation and ordered inserts. | Exact sequence, replay/duplicate, availability, rollback and conflict regressions passed. Existing sequence floor and transaction retained. | **OFFLINE VERIFIED; operational benefit NOT VERIFIED.** Later exact ACK delays remained large. No isolated whole-machine timing attribution. |
| Maintenance: identical retirement fences reread within one observation. `solana_maintenance_state.py` reuses explicit observation-local fences only while bounds match. | Two-scope fixture reads **118→102**. Mutable application checks remain fresh. | **PASS for measured read reduction; PARTIAL for maintenance efficiency.** Live maintenance still occupied the owner. |
| Archive planning: repeated identical pin checks within a bounded page. `solana_scoped_retirement.py` memoizes only those exact planning keys. | **41** examined rows, **8** checks, **33** reuses. New-position and apply-time pin checks preserved. | **OFFLINE VERIFIED.** No live archive throughput or active-backup protection claim. An introduced cursor-variable shadow was corrected before the frozen executable; the failed run remains retained. |
| Pons shared scout: one event was immediately nominated and nominated again in two later loops; per-event projection repeated maintenance. `pons_selective_cohort.py` now retains one immediate durable nomination at original receipt time and one cohort projection before qualification. Older results cannot overwrite newer claimed generations or renew deadlines. | Actual broker/scout/plane fixture with **32 synthetic events**: nominations **96→32**, maintenance **33→1**, SELECTs **1134→470**, BEGINs **195→68**, identical durable outcomes. Scoped traced CPU **101.128→52.933 ms**, wall **181.424→100.415 ms**. | **PASS for the reproduced duplication defect.** Live full Pons CPU savings are not established; remaining acquisition/valuation and deadline failures prevent readiness. Received-event counters changed from inflated nominations to actual nominations, so old/new counts are not a capacity comparison. |
| Accepted-source ownership: stop/reconnect formerly could cancel processing before a global accepted-work accounting boundary. Existing queues now retain consumers until producers settle and joined queues commit; partial gaps and unfinished CONTROL acquisition ranges are durably retained. `solana_source_drain.py`, source/session teardown and terminal IPC implement the coordinated contract. | Offline stop/reconnect/replacement/fault/restart cases passed; terminal counters and exact CONTROL obligation survived live shutdown. All **33,859** admitted joined frames committed: control3483, rolling1311, scout29065; candidate0. Both native workers exited 0. | **PARTIAL implementation; FAIL global drain.** Accepted handlers564488, settled564486, pending**2**. Terminal `RECOVERY_REQUIRED` is authoritative for this boundary. New CI also fails optional-subscription cutoff cancellation. No global resumability PASS. |
| Terminal diagnostic retention: current PID/run/clocks and fixed drain fields are selected before generic clipping and retained in canonical health/final IPC. | Current canonical terminal and final IPC match exactly; recorder coverage remained valid. The failure was visible despite the controller's generic `drained=true`. | **PASS for retaining these facts.** Exact identities/operations of the two unsettled handlers were not captured. This limitation must be corrected before another attempt, rather than treating the counters as proof of preservation. |

The first scout-only preliminary probe measured fewer reads without a CPU
improvement; it remains retained. The exact-predecessor comparison above has a
different, explicitly recorded scope and supplies the controlled component
claim. Neither probe establishes a machine-wide percentage or monthly savings.

Previous grouped canonical storage, off-owner preparation, independent historian
and delivery, event-driven publication, provider pacing, capital-prefix reuse and
lifecycle/reporting work were retained. In the final live slice, economic-store
counters recorded **321 bulk calls / 21,248 records**, zero scalar calls. This
confirms that the existing bulk path was reached; it does not establish its
incremental performance contribution. These mechanisms were not rebuilt.

## Throughput: requirements were not achieved

The valid final comparison window is **654.759→898.038 seconds**, duration
**243.278 seconds**, after both natives first reported reconciled. Source PID,
generation, source session and rolling session remained unchanged throughout
these 47 full samples. Thus this window does not credit a reconnect head jump as
processing. It is still a startup-limited, funding-closed workload, not a normal
steady-state acceptance interval.

| Current-run measurement | Result |
|---|---:|
| CONTROL receipt-head arrival **proxy** | **3.222646 slot units/s** |
| Joined rolling head | **1.331808 slot units/s** |
| Prepared rolling head | **1.335918 slot units/s** |
| Durable-completion timing head | **1.335918 slot units/s** |
| Newest stored economic head, minimum of both programs | **1.352360 slot units/s** |
| Raw persisted program cursor | **1.335918 slot units/s** |
| Verified strategy-usable program frontier | **UNAVAILABLE; no checkpoint rows appeared** |
| CONTROL minus newest stored economic head | **419→874 slots** |
| Stored economic evidence age | **171.787→342.065 seconds** |
| Durable / CONTROL-proxy rate | **41.45%** |
| Multiplier required merely to match that proxy | **2.412×**, before backlog recovery |

These are head-advancement units, not counts of all required events. The CONTROL
head is itself locally received and can lag the market. It is not an independent
measurement of all market arrivals. Processing nevertheless falls materially
behind even that proxy. Joined/prepared heads track the slow durable head rather
than showing enough completed work waiting only for a frontier display update.
At the last sample the received candidate transaction-status provider timestamp
was already roughly 337 seconds old. Transport receipt rate alone is therefore
not fresh-market capacity.

The older reliable b007217e interval measured **3.711 proxy / 1.509 durable**,
gap1321→1748, age354→483 seconds, CPU1.729 cores. The new window has different
market work, starting state, native activity and duration. Its smaller initial
gap, different rates or later deterioration cannot be attributed causally to
the repairs. **No controlled whole-machine speedup is established.** Overall
rates crossing the rolling-session replacement around 415.6 seconds are excluded
from capacity claims. The closed incomplete historical-replay route was not
reopened.

### What the remaining measurements establish

The single owner was occupied by callbacks for **230.073 seconds**, with a
separately recorded **11.965 seconds** of checkpoint handoff holds, over 243.278
seconds: about **99.5% occupied**. The owner actually executed **43.987 CPU
seconds** and accumulated **94.432 seconds runnable scheduling delay**. The
service used **1.715 cores** of its 1.8-core allowance, with **16.648 seconds**
cgroup throttle time. CPU pressure `some` advanced 185.495 seconds; this is a
cgroup pressure measure, not time attributable solely to the owner.

| Exclusive callback category | Wall seconds | Thread CPU seconds |
|---|---:|---:|
| Candidate commit |70.471|15.191|
| Scout commit |40.339|7.038|
| Candidate development |40.445|6.129|
| Maintenance decision |25.716|5.725|
| Retention |17.647|1.457|

These category rows exclude their parent totals. Operation probes below can
overlap these callbacks and must not be added to them. Within development,
reactivation used 30.895 wall / 4.141 CPU seconds. Within canonical processing,
rolling storage used 31.893 wall / 5.258 CPU seconds and history outbox work 14.196
wall /3.469 CPU seconds. Recorded 967 owner COMMITs used **15.888 wall / 2.488 CPU
seconds**; BEGINs used 0.669 wall seconds. This does **not** demonstrate COMMIT,
checkpointing, a busy lock or a single SQL operation as the dominant cause.

Pons used **166.47 CPU seconds / 0.684 cores**, source 133.79 / 0.550, native
Pump 78.05 / 0.321 and supervisor 22.14 / 0.091. Pons's completed operation probes
show persistent work beyond the corrected nomination loops:

| Pons operation | Calls / failed | CPU seconds | Selected fetch calls |
|---|---:|---:|---:|
| Survivor step |41 /0|51.534|789608|
| Discovery |67 /0|38.009|601561|
| Hydration |28 /28|33.911|961414|

These are reached operation/selected native-API counts, not unique rows or
independent economic events. They locate expensive remaining paths; they do not
prove every fetch is redundant. Some nested rollback counters were nonzero;
without an original exception they are not evidence of SQLite BUSY or READONLY.

Peak service memory was **2,278,965,248 bytes across all 863 retained samples**, below 6 GiB. The volume device
recorded about 645 MB read and 3.604 GB written during the selected interval; these
are whole-device totals. Cgroup I/O pressure advanced 50.631 `some` / 7.412 `full`
seconds. Neither these totals nor wall-minus-CPU establishes an owner disk wait,
GIL bottleneck, lock holder or storage saturation.

**Supported architectural conclusion:** serial owner occupancy and competition
from substantial required Pump/Pons work jointly constrain this run. There is
both processing accumulation and downstream delivery delay. Reducing one
repeated lookup did not remove the whole critical path. A coordinated reduction
of measured owner/consumer work and scheduling demand is justified; a specific
replacement architecture or hardware size is not yet demonstrated. The existing
two-vCPU configuration has not met requirements and has little measured CPU
headroom, but its irreducible insufficiency is **NOT VERIFIED**. A linear 2.412×
hardware extrapolation would ignore serialization, blocked coverage and Pons
deadline work. No purchase or resize is recommended on this evidence alone.

## Publication, recovery and first-failure evaluation

The sampled current canonical cohort contained **96 unique exact identities**.
Independent read-only verification found **66 authenticated consumer receipts
with exact ACKs**, **30 pending preserved**, no sampled identity conflicts, and
preserved prior named cohorts. For the 66 acknowledged sampled obligations,
consumer receipt→canonical ACK delay was **180.197–539.192 seconds**, median
**228.686 seconds**. This is substantial post-persistence delay. It cannot be
explained away as a frontier display issue or added to pre-persistence head lag
as though both described the same population.

The terminal store retained **1,480,899 pending history rows** and **13,819 pending
proofs**, including historical stock. Those totals are not current-run arrivals
or measured growth. Program-wide verified checkpoints remained absent; some
individual receipts can still progress independently. `CandidateLifecycle.publish`
requires authenticated consumer receipts and contiguous gap-free coverage before
advancing a checkpoint. No missing interval was skipped. The exact oldest global
required obligation and complete proof-eligibility census remain unavailable;
the diagnostic intentionally did not reevaluate the entire population.

The earliest failed operating requirement was **300-second readiness**, followed
by the 900-second diagnostic startup ceiling. First sampled reconciliation was
Pons 264.955 seconds and Pump 654.759 seconds. Recorded startup operations include
Pons shared-capital restore 193.238 seconds and Pump observed-candidate restoration
391.565 seconds. Native reconciliation eventually completing does not retroactively
pass readiness or establish fresh strategy evidence.

At shutdown both current native workers received TERM, reported STOPPED/reconciled
and exited 0. Shutdown completed in the existing boundary, without a -9 escalation.
The source then published the separate terminal failure:
`EvidenceUnavailable`, `solana_selective_source.run:1202`, with global
`RECOVERY_REQUIRED`. Its census proves all joined queues committed, while two
accepted handlers lack a settled disposition. Two partial sessions were preserved,
unpreserved-session count is 0, and one CONTROL replay obligation remains:
**slot 457279885**, `coverage_after_id=192778`.

Source inspection establishes why the census fails closed: acceptance increments
before the awaited handler and settlement increments only on successful return.
Aggregate totals and session preservation do not identify the two handlers or
prove their exact incomplete content is durably recoverable. **The specific two
failing handler operations are NOT VERIFIED.** Their existence before this repair
cannot be established because this global census is new. Treat this as an
incomplete ownership/cancellation solution, not a repaired recovery contract.

The new cooperative-stop path also has a directly observed compatibility
regression: the existing optional-program cutoff test now waits in
`rolling_programs:1341` for a child that never receives task cancellation. The
test times out. A correct successor must reconcile cutoff cancellation with
accepted-work ownership, rather than restore indiscriminate cancellation or
increase timeouts. This is a concrete subsystem contract repair, not justification
for a broader redesign.

No natural fatal SQLite BUSY or Pons READONLY exception was captured in this
campaign. The protected terminal channel survived to shutdown and recorded the
non-SQLite drain failure. Earlier BUSY/READONLY failures remain **unresolved, not
repaired**. Previously unsealed CONTROL receipts associated with an older session
also remain a specific recovery concern; the new range marker does not prove
their subsequent sealing/replay. No authoritative recovery was executed after stop.

## Actual strategy progression and Pons capability

All four durable policy selections were freshly checked as
**paper-opportunity-access-v1**, retaining their original financial identities.
Exact strategy/source guards preserve C1–C6, Current/ Survivor independence,
maturity-aware Survivor eligibility, reconsideration, older winners, bounded
executable sizing, all nine original economics, tail bridge, staged scaling and
attention-only volume quality. Meteora/Ramses remain paused. This confirms source
and state integration, not successful live evaluation of every strategy.

Pump admitted scout locators and canonical events, but its native opportunity
pipeline recorded **zero new transitions during this run**; its bounded 4096-row
tail covered the full current interval. Restoration and history retention were
observed; qualification, funding eligibility and PAPER execution were not
demonstrated. Scout frames are not unique discovered opportunities, and old
pipeline entries are not credited as new decisions.

Pons's current-run pipeline recorded 3814 transitions involving 177 candidate
identities, including retained candidates. Forty identities reached `discovered`,
80 requested current state, 160 were watched and 122 received terminal classifications.
These sets overlap and cannot be summed as candidate losses. Operational classes
included 58 capacity-censored, 104 consumer-deadline, 63 stale-during-evidence and 41
superseded-generation identities. No evaluated/qualified/entry-reserved/entry-filled
stages or legitimate strategy-rejection classification appeared. Projected plane
timestamps belonged to this run, rather than old transitions merely re-exported.

The 66 current-run detailed candidate attempts were **all operationally incomplete**:
52 stale acquisition,10 missing/stale native USD,2 pre-transport deadlines,1
during-transport deadline and 1 inherited shared-admission deadline. These counts
are a different scope from operation-level hydration counters. They demonstrate
that the machinery failed to supply timely complete evidence, not that the market
offered no valid strategy opportunities. Whether any excluded candidate otherwise
qualified cannot be known without the missing authentic evidence.

The managed Alchemy route did exercise `eth_getLogs`, block, receipt, code, call
and chain-ID reads. The full run fits the bounded retained request rings:
**2039 physical Robinhood HTTP attempts**, **2038 HTTP 200**, **zero HTTP 429**,
zero recorded RPC errors and no wrapper retries. One physical request hit its
inherited transport deadline; another deadline record had no physical attempt.
The transport records contain 7196 logical elements, including that undispatched
element; durable usage accounts 7195 Robinhood elements. These are not extra calls.

HTTP latency was median 319 ms / p95 703 ms / max 1.911 s; transport admission wait was
median 16.5 ms / p95 113 ms / max 287 ms, maximum in-flight 3. One of 2041 admission
records failed after arriving 182 ms beyond its original absolute deadline. This
does not attribute the expired slack to admission queueing. Managed endpoint
fingerprint `91ad0f2d5dfd637a3c38c64ab009abe28025e0b4c22085fcd73ecdf7093fd6bb`
is retained; no credentials are published.

**Provider conclusion:** the reached managed requests were generally accepted;
end-to-end Pons evidence readiness still failed. The original public-RPC 429 cause,
public adaptive spacing under load, account-wide capacity, complete historical
capability and long-term commercial suitability are not established by this
managed run. Position-monitor-labelled requests on a flat portfolio are not held
positions. Current 5 s / Survivor 3 s held quote/USD protection, exits, order cancellation,
reentry, partial exits, adds, component attribution and long-duration management
are **NOT LIVE TESTED** here. Relevant earlier offline coverage remains scoped
offline evidence. No trades were forced or manufactured.

## Validation, including failures

Development used the supported network-blocked runner, disposable state and
pinned runtime. Counts below overlap; they are not summed into a unique suite.

| Validation | Exact result |
|---|---|
| Final exact-a793 targeted integration, attribution enabled; actual integrated startup, drain/restart/fault, replay, cancellation, collection, owner hooks | **230/230 PASS, 34.214 s** |
| Maintenance/arbiter/retention focused modules | **68/68 PASS, 86.383 s** |
| Pons scout/controller/continuous-campaign integration | **115/115 PASS, 16.666 s** |
| Affected exact economic/source guards | **5/5 PASS, 7.578 s** |
| Owner/drain/scout/rolling focused | **40/40 PASS, 7.649 s** |
| Archive cursor/apply regressions | **2/2 PASS, 0.422 s** |
| Earlier combined integration | **358 PASS /3 ERROR of 361, 104.173 s; FAILED** |
| Automatic a793 held-PAPER CI | **78 PASS /1 ERROR of 79, 5.374 s; FAILED** |
| Complete FAST / complete OPERATIONAL on a793 | **NOT RUN; no release promotion** |

The 361-case errors were the introduced archive cursor shadow, rethrow of an
already-handled rolling retry and a no-owner fixture missing the new compound
control result. Corrections and affected reruns preceded a793; the failed result
remains failed. Earlier source-guard nesting failures, the wrong unresolved-gap
test expectation and in-progress standalone-worker fixture failure are preserved
with their dispositions in the validation index. Assertions and safety deadlines
were not weakened. Two earlier correctness test runs briefly overlapped; their
elapsed durations are not performance comparisons. No tests/profilers competed
with the live observation.

CI [38753995554](https://github.com/levonmendall/The-Meme-Machine/actions/runs/38753995554)
failed
`tests.test_position_continuation.SelectiveShutdownTests.test_running_optional_program_subscription_is_cancelled_at_cutoff`.
The local selected 230 cases missed this affected cutoff regression. **Its terminal
CI result was retrieved after the live campaign and was not incorporated into
the pre-dispatch gate. That was a validation gap.** It remains unresolved; no
post-campaign implementation or rerun was started. Source guards and startup
rehearsal passes cannot erase this failure.

FAST draft runs
[38754004711](https://github.com/levonmendall/The-Meme-Machine/actions/runs/38754004711)
(a793) and
[38754329218](https://github.com/levonmendall/The-Meme-Machine/actions/runs/38754329218)
(edb386c5) were **SKIPPED**, not passing suites. The older manual full FAST
38652038787 and earlier b007 held proof 38741708842 retain their original source
scope; neither is a current-release pass. No new full-suite dispatch was made.

Fresh preflight verified 24 required checks. Independent post-stop review made
9764 bounded read-only queries in 2.885 seconds, no economic writes/provider calls,
and found **25 checks VERIFIED /1 FAILED**: global source drainage. Empty verified
checkpoint-receipt rows mean no invalid checked receipt was found, **not** coverage
success. The post-review helper initially rejected a relative versus absolute
path referring to the same pinned preflight; only the analysis helper's path
normalization was corrected. Original helper and exact preflight hashes remain
retained. No application behavior changed after the campaign.

## Financial, provider and recovery safety at pause

Cash remains **$1000.00**, epoch `paper-shared-1000-20261011T071207Z`. Positions,
reservations, commitments, obligations, pending backing/deliveries, runtime pending
and inbox are all **zero**. Journal head advanced 12276→12608 only through one
`runtime_admission`, 20 `runtime_owner` and 311 `runtime_publish` records. The 332-event
new suffix was independently replayed against the authenticated 12276 baseline;
projection, chain and exact monetary reconciliation matched. Final head:
`63570518d16a12e1071a9cb968f1f928b1e5dbf43c80159a93285424a31ca48c`.
Historical $500 head 2036, inception, checkpoint and main-file preservation checks
passed. No deposits, trades, epoch reset or policy reclassification occurred.

Actual service: **inactive/dead, disabled, Restart=no, MainPID=0**, empty systemd
ControlGroup. Recorded supervisor/source/native/worker PIDs are absent; root
controller completed. Provider queues, native/HTTP reservations and open usage
receipts/streams are zero. Writer ownership is released; no unexpired examined
consumer/historian leases remain. Pending evidence and exact named old/current
receipts are retained. These are stopped-state facts, not proof that all remaining
native recovery can execute safely.

Exact a793 source remains installed clean and stopped. The finite observation
unit/configuration is retained disabled. Previous 66f85d61 source/configuration
bytes are preserved, but are not restored for execution across the new CONTROL
recovery obligation. No database rewind or marker deletion was used to force
rollback compatibility. Future runtime needs compatible recovery and fresh
preflight, following owner review.

Current-run durable usage delta: **2050 physical starts including 6 native opens**
(2039 Robinhood HTTP +5 Solana HTTP +6 native opens),7200 logical RPC elements,
247108 accounted CU, 11,737,570 HTTP bytes and 605,151,227 native bytes. Additional
uncertain native-byte exposure 436,207,616 is separately recorded. The existing
conservative frozen model estimates **$0.239074378515**; provider invoice/actual
charges are **UNAVAILABLE**. This is not a new pricing quote or spending cap.

The applicable existing recovery point remains
`meme-machine-paper-20261013T221423-5891a20c`, manifest SHA
`f3a6b3f8d0b69a86c470cda0b307491d03ea05dff4959729f4c9d168a608adf0`.
Its 301 inventory entries were freshly checked and the completed restore/integrity
proof reused. It is an older usable reference, not a current backup of this run.
The later failed backup remains **unusable**.

After stop, root had approximately 11.730 GB free and the volume 15.816 GB; both
exceed the existing 5 GiB reserve. Canonical DB is 19,105,742,848 bytes, WAL 0 at
inspection; CandidateHistory 1,870,200,832 bytes. Just one canonical copy plus
reserve has an **8,658,030,592-byte minimum shortfall**, excluding other state,
growth and isolated restore needs. It is not the complete storage requirement.
No bulk copy, cleanup, resize or purchase was performed. The existing scheduled
backup was not interrupted or its timer changed; the last observed next trigger
was 2026-10-16T04:02:15Z. Its process-group freeze remains unproven compatible with
uninterrupted 3 s/5 s held protection. Backup capacity and protection compatibility
remain independent autonomy blockers.

## Independent readiness verdict and shortest justified route

| Required subsystem/outcome | Verdict | Basis |
|---|---|---|
| Active strategies/economic identity | **PASS for integration** | Four current durable v1 bindings and source/economic guards; live trading behavior unexercised |
| Monetary accounting/historical preservation | **PASS** | Exact suffix replay/reconciliation, flat obligations, unchanged historical $500 |
| Concurrent worker startup within 300 s | **FAIL** | Pump first sampled reconciled 654.759 s; readiness never true |
| Sustained incoming→durable processing/backlog | **FAIL** | Final continuous proxy 3.223 versus durable 1.336; lag/age increase |
| History receipt/ACK/publication timeliness | **FAIL** | Sampled ACK delays 180–539 s; no verified program checkpoint |
| Native worker TERM and stop | **PASS, scoped** | Both current workers STOPPED/reconciled/exit 0 within bounds |
| Global accepted-source drainage/recovery | **FAIL** | Two unsettled handlers; explicit terminal RECOVERY_REQUIRED; current CONTROL replay not executed |
| Managed reached HTTP methods/admission | **PARTIAL** | Mostly accepted, no 429; incomplete acquisition and deadline failures remain |
| Actual candidate→qualification progression | **FAIL** | Pump no new pipeline transitions; Pons operationally censored/incomplete |
| Held quote/USD protection, exits/adds/reentry | **NOT VERIFIED live** | Funding closed, zero positions; earlier offline tests are scoped |
| Original SQLite BUSY / Pons READONLY repair | **NOT VERIFIED** | No reproduction does not establish repair |
| Fresh backup capacity / protection-compatible backup | **FAIL / NOT VERIFIED**, respectively | Known storage failure and unproved freeze compatibility |
| Two-vCPU adequacy after sufficient corrections | **NOT VERIFIED** | Current workload fails near CPU ceiling; no controlled minimal-hardware proof |
| Uninterrupted one-hour acceptance / autonomy | **NOT VERIFIED; not admitted** | Zero qualifying minutes; prerequisites failed |

Mandatory remaining work, in order:

1. **Complete the accepted-handler cutoff and recovery contract.** Reproduce the
   actual optional-subscription CI failure and the two unsettled handler outcomes
   using current ownership/session teardown paths. Identify each outstanding
   handler's phase and durable disposition; confirm the exact CONTROL range can
   recover without false sealing of old-session receipts. Preserve original
   failures and bounds. This is the immediate runtime safety gate, not an
   impossible retroactive PASS requirement for old killed workers.
2. **Reduce the demonstrated combined owner/Pons critical-path demand.** Target
   the measured candidate/scout/development callbacks and the reached Pons
   Survivor/discovery/hydration work. Selected fetch counts and runnable delay
   identify concrete paths, but only equivalent-workload measurements can justify
   which additional computation/queries to consolidate. Preserve the single writer
   and existing preparation/delivery facilities. Do not choose a generic new pool,
   storage replacement or hardware increase without the missing causal result.
3. **Restore timely candidate history/ACKs and actual evaluation.** Investigate
   the sampled receipt→ACK dependency and absent gap-free checkpoint separately
   from pre-persistence accumulation. Resolve stale acquisition/USD and expired
   deadline paths with complete evidence; do not relax freshness or qualification.
4. **Establish complete backup/isolated-restore capacity and protection-compatible
   maintenance.** A real capacity/storage decision may require owner spending
   approval after complete sizing. No purchase is authorized by this report.
5. **Revalidate remaining genuinely unexercised safety paths**, original SQLite
   failures and provider/replay contracts as implicated by a supported successor.
   Only then freeze a promotion candidate, run final FAST/applicable OPERATIONAL,
   and perform a discriminating live validation before genuine one-hour acceptance.

Optional cleanup, file-count reductions, previously rejected cold-metadata
optimization, generalized tracing, worker-count sweeps and a new historical-replay
search should remain deferred. Pons work reduction, backup design and focused
drain reproduction can be independent offline tasks after resumption, under one
integration/test owner; competing host/provider campaigns would invalidate useful
measurements. There is no defensible completion date for autonomous readiness.
The known failing cancellation test is a bounded starting point, while throughput
repair size depends on the measured mechanism selected; assigning a calendar ETA
would be speculative.

**SINGLE MOST IMPORTANT REMAINING ISSUE:** the current accepted-source lifecycle
cannot establish complete safe drainage/resumability. The principal performance
failure remains the saturated owner/competing-work pipeline, not a repaired
capacity problem hidden by that safety issue.

**RECOMMENDED NEXT ACTION:** after owner review, complete the existing
accepted-handler cancellation/recovery contract, beginning with the failing
cutoff regression and the two recorded unsettled handlers. This has a concrete
failure, source path and preservation invariant; another unchanged market test
would add little information and is not recommended.

**SAFE PAUSE:** exact a793 installed stopped; service disabled/Restart=no; funding
closed; $1000 cash and zero obligations; historical $500 and all retained evidence,
ACKs, pending work, counters and recovery references preserved. Native worker stop
is verified; global source recovery remains RECOVERY_REQUIRED. No autonomous
operation, further engineering or provider test will follow this report without
owner direction.
