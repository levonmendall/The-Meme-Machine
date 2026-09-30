# Astra review package — fresh Stage-E archive recovery diagnosis

**ASTRA_REVIEW_READY: HISTORICAL_MECHANISM_REPRODUCED**

PAPER ONLY. Stage E remains RED. Stage F has NOT started. Two material variants
were executed; four remain unused. All diagnostic workload execution stopped
at this gate. No production repair, successor freeze, canonical certification
or deployment was performed. Subsequent CI only publishes captured evidence.

## A. Production identity and truthful lineage

Production runtime: `dc08f9064cf5e37b63f383f52aa709d0afc1723f`.
Production tree: `68736cf664169dee665762019800bf87ca0f1f67`.

Dedicated branch: `diagnostics/stage-e-fresh-causal-isolation`, a real descendant
of that runtime. CI verified all **1,152 reachable preexisting blobs and modes**
unchanged, including production and canonical workflows. This is the actual
reachable-tree count, distinct from the historical 1,155-path verification.
Only diagnostic files and one isolated branch-scoped workflow were added.

| Execution | Diagnostic SHA | Tree | Actions run |
| --- | --- | --- | --- |
| M1 | d72b80b5bb8afe21fbea1453f4c926d3f1872c3d | 4bff5cf1c050134ad2abefcded6cb9d00754b08b | [36757944292](https://github.com/levonmendall/The-Meme-Machine/actions/runs/36757944292) |
| M2 | b7928fe14e5952a9811cfa0f50ac36334dbb7d09 | 25999b69b0275f7877854a0298ed9e016ccf01f2 | [36759485146](https://github.com/levonmendall/The-Meme-Machine/actions/runs/36759485146) |

The publication artifact's PUBLICATION_IDENTITY.json records its own SHA/tree.
The final repository binding records that publication and its artifact digest.
There is no claim of descent from unavailable rejected object
`06f7a129eb9a1deab02af5f1f6bdfbaea89ea142` (tree
`90839dfc47c1665e8d84eea62e6ba95e5e369efd`). Neither runtime nor diagnostic
identities are that qualification candidate. No lost Pro artifacts were inputs.

## B. Historical signature versus fresh reproduction

The supplied historical reference planned 4,445 frames /1,200.15 source-seconds,
then failed near 1,215 /328.05 with maintenance_cannot_reserve_both_sides.
Archive was not ready, retirement ready, archive RECOVERY headroom 5.936821 s,
opposite-side preservation required 9 s, feasible set empty; Meteora eligible
5,632 /excess 4,632. Worker age .218312 s and owner admission .209254 s were short.

Fresh M2 follows the entire upstream sequence, not merely the exception name:
post-pause eligibility debt rises; repeated archive drain cannot restore the
1,000-record envelope; the latched recovery deadline loses headroom; RECOVERY
becomes binding; a normal short not-ready interval leaves the feasible set empty.

| Terminal fact | Fresh M2 |
| --- | ---: |
| Native fatal choose frame /source coordinate | 1,207 /325.89 s |
| Final source drain after failure | 1,209 /326.43 s |
| Total elapsed wall time | 330.736 s |
| Meteora archive eligible /recovery excess | 7,552 /6,552 |
| Meteora archive RECOVERY /SAFETY /SERVICE headroom | 5.672391 /41.672391 /44.814337 s |
| Archive readiness /retirement readiness | false /true |
| Feasible set /selected side | [] /none |
| Archive worker age /owner admission | .184300 /.180496 s |
| Retirement own reservation /preserved archive finish | 3 /9 s |
| Archive recovery reservation deficit | 3.327609 s |

The refusal is legitimate. Extending deadlines or weakening it would conceal the
capacity loss. The historical frame and debt counts are not asserted identical.

## C. Fresh baseline, environment and limitations

The harness runs unchanged native serve(), owner, arbiter, SQLite mutators,
archive preparation and retirement. Workload inputs come from reachable
certification/run381_pressure.py, cleanup_recovery.py, combined_observer.py and
the preserved local templates, documented in [ARCHITECTURE.md](ARCHITECTURE.md).
No provider calls, wallet activity, trading, signing, broadcast or capital.

Both variants plan 4,445 frames at .27 s/frame; fixed source deadlines precede
backpressure, eight-second pauses at frames 800/1,400 catch up to the original
clock. Source-owner floor .165 s/frame, archive floor .36 s/1,000 and changing
outer-COMMIT cost .006 s are repository qualification-profile load inputs.
Injected waits are measured separately from native production costs. Native
reader/checkpoint interactions and candidate data reads are retained.

Both ran Ubuntu 24.04 /Linux 6.17.0-1022-azure x86_64 /glibc 2.39, Python
**3.12.14**, SQLite **3.45.1**, websockets **17.1**, four CPUs/affinity CPUs and
about 16,373,450 KiB RAM. Version differences were empty. Full environment,
configuration, runtime SHA/tree and diagnostic file hashes are in each summary.
Hosted CPU performance varied between runs; M1/M2 native-cost differences cannot
be causally attributed to ACK removal alone.

M1 is the minimally instrumented derived full-control baseline. It was truncated
by a separate cooperative interruption/completion defect. That failure prevents
claiming a completed canonical baseline or a controlled ACK-performance effect.
M2 removes only the urgent periodic and candidate ACKs to expose capacity beyond
that blocker; data reads, profile floors, source clocks, readers, transactions,
worker count, reservations and native scheduling remain unchanged. It is a
diagnostic reduced-control workload, not a candidate configuration.

Preflight ran 1,062 existing tests: one failure, two errors, 46 skips.
Required resource check passed. [PREFLIGHT_EVIDENCE.json](PREFLIGHT_EVIDENCE.json)
preserves the failures and artifact hashes. The broad suite is not green.
No rerun, omitted failure, or production/test modification is used to disguise it.

## D. Experiments and stop ledger

| ID | Hypothesis | Variable | Frames/time | Key results | Interpretation |
| --- | --- | --- | --- | --- | --- |
| M1 | Derived coupled baseline exposes recovery capacity | None | Fatal frame 884 /238.68 source s; final 886 /239.22; 242.707 wall s | maintenance_decision_in_flight after selected retirement was interrupted; recovery headroom 94.77 s; both sides ready/feasible | Separate completion blocker; insufficient recovery duration for historical conclusion |
| M2 | Reduced urgent controls permit observing the native capacity path | Urgent ACKs disabled only | Fatal frame 1,207 /325.89 source s; final 1,209 /326.43; 330.736 wall s | Sustained debt growth, latched headroom 96 ->65 ->35 ->5.67 s, archive not ready, empty feasible set | Full historical recovery-capacity mechanism reproduced |
| M3 | Source-owner occupancy drives lost effective archive service | Predeclared but UNEXECUTED: M2 with only source-owner floor .165 ->0 | None | Reserved before gate | Best next component discriminator if Astra requires it; no authorization to run now |
| M4–M6 | Conditional | UNEXECUTED | None | Four total slots unused, including M3 | Stop at first gate; do not fill budget mechanically |

M1's last retirement admission returned OperationalError:interrupted without
completion, then the next choose found the previous decision pending.
MaintenanceRuntime.turn():348-350 reads native progress before arbiter.complete;
an urgent interruption can leave that pending decision. Fresh evidence strongly
supports this independent path. It is not substituted for the historical cause.

## E. Capacity timeline and measurements

SQLite read snapshots and native owner observations have separate timestamps.
Debt/rates below use coherent read snapshots; headroom/readiness use the attached
timestamped native observation. They are not falsely presented as one atomic
sample. The 330.561 s snapshot is after failure/drain and WAL close: its debt is
retained as evidence, but it is excluded from arrival-rate conclusions.

| Wall s /frame | Meteora eligible /excess | Archived-pending | Recovery /safety headroom s | Hot /retained age s | Archive /retirement ready | Source lag s | Cumulative source owner wall s* | Archive worker dispatch peak s |
| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: |
| 210.341 /775 | 384 /0 | 0 | none /56.39 | 180.86 /180.86 | true /true | .859 | 130.03 | .01018 |
| 240.397 /866 | 3,688 /2,688 | 3,096 | 95.98 /49.98 | 187.91 /194.91 | false /true | 6.913 | 145.99 | .32975 |
| 270.421 /985 | 7,528 /6,528 | 1,560 | 65.14 /41.14 | 195.94 /198.94 | true /true | 4.937 | 166.25 | .32975 |
| 300.472 /1,096 | 9,088 /8,088 | 640 | 35.10 /38.10 | 198.99 /200.99 | true /true | 4.989 | 185.59 | .32975 |
| Terminal native choose /1,207 | 7,552 /6,552 | 8,192 | 5.67 /41.67 | Native observation preserved | false /true | separately sampled | separately sampled | worker age .18430 |

*Native source stage plus explicitly injected source-floor wait; overlapping
transaction/owner metrics must not be added again. Exact aggregates are in JSON.

Arrivals are inferred as delta eligible hot + delta durable archived, rather than
source ingestion mislabeled as eligibility. Validity requires no active pins/gaps;
the publication step verifies flags from the existing raw timeline. Shutdown
creates disconnect gaps; those samples are excluded.

| Wall interval s | All-scope inferred arrivals /s | Archive drain /s | Net eligible change | Meteora arrivals /s | Meteora drain /s |
| --- | ---: | ---: | ---: | ---: | ---: |
| 210.341–240.397 | 974.98 | 751.13 | +6,728 | 472.72 | 362.79 |
| 240.397–270.421 | 984.81 | 716.49 | +8,056 | 477.48 | 349.59 |
| 270.421–300.472 | 975.14 | 865.20 | +3,304 | 472.80 | 420.88 |
| Entire 90.131 s | 978.31 | 777.63 | +18,088 | 474.33 | 377.76 |

Over that mature interval, source owner native work 46.443 s plus source-floor
wait 9.123 s occupies **61.65%** of elapsed time. Archive preparation consumes
23.442 native +2.296 injected s, about **28.6%** of elapsed time. Its batch service
processes 69,672 records, roughly 2,707 records per preparation-service second;
this is not end-to-end sustainable throughput. Only one archive flight can
prepare, and a successor snapshot is selected after bounded receipt drain.
Owner FIFO admissions/source work can therefore leave preparation capacity idle.

Archive dispatch-to-child-start totals 2.246 s/72 completions in this interval,
about 31 ms each; it includes IPC/serialization and pool queueing. Return transport
adds .637 s. Archive plan/commit owner stages consume 3.112 /5.180 s; retirement
11.245 s. PASSIVE checkpoint native wall 3.896 s and mutation-boundary checkpoint
wall 4.296 s overlap other work; they are not additive owner occupancy.

At the final sampled state, maintenance/health priority-4 queue wait sums
156.672 s/937 completed admissions, peak .913 s. This is an aggregate over many
queued tasks, not 156 seconds of unique owner occupancy. Native source +injected
owner work totals 205.580 s (**62.16%** of whole-run wall time).
Normal transaction/event source uses priority 2; nonurgent work shares native
FIFO order with maintenance. Worker count remains two.

Diagnostic measured overhead M1 .284909 s (**.1174%**), M2 .952200 s
(**.2879%**): M2 periodic observer .299705, serialization .020923, persistence
.011390, numeric-wrapper bookkeeping .620183 s. Qualification-equivalent
observer time is reported separately from extra debug work. Entry/return
trampolines and extra clock calls are incompletely captured. There is no
uninstrumented matched run, so perfect non-perturbation is not proven; these
measurements do not support a heavily perturbed-run explanation. No <1%
qualification-observer certification is claimed. Both databases passed integrity.

## F. Conclusion by confidence

**PROVEN**

- Under unchanged runtime with repository-derived coupled load and reduced urgent
  controls, effective archive recovery service is below eligibility arrivals for
  three consecutive mature intervals. Debt remains well above the recovery
  envelope and the existing deadline becomes binding before safety/service.
- A short legitimate archive-not-ready state then produces the historical
  two-sided reservation refusal. This is why the terminal failure follows from
  earlier capacity loss; the refusal is not the defect to weaken.
- Source-owner work occupies about 62% of elapsed time under the declared profile.
  Archive preparation is single-flight; source and maintenance share the owner.
- The historical terminal mechanism is reproducible without the lost experiment,
  SQLite DB, capture, scripts or rejected object. Production bytes/modes remain intact.

**STRONGLY SUPPORTED**

- The source/shared-owner and serialized archive receipt/preparation path is the
  first repair-investigation scope: substantial source occupancy plus spare raw
  preparation service explains how achieved archive duty cycle can be too low.
- M1 exposes an independent interruption/completion protocol blocker that must
  be addressed or explicitly resolved before a future full-control certification.

**DISPROVEN / EXCLUDED FOR THIS TERMINAL**

- Safety-bound or service-bound terminal classification: RECOVERY binds at failure.
- Fifteen-second archive-worker lease exhaustion, multi-second terminal owner
  stall, or corrupted SQLite database as this terminal trigger.
- Claims that the inaccessible candidate or Pro artifacts are necessary inputs.

**UNKNOWN**

- Which upstream component is sufficient: source-owner load, avoidable archive
  pipeline idle/admission cost, mature SQLite work, checkpoint handoff, or
  allocation/rate estimates. The runs do not isolate these from one another.
- The marginal effect of removing ACKs; hosted native performance differed.
- Whether all observer perturbation is negligible; no matched observer-off run.
- Sustainable capacity on other hardware or complete 4,445-frame qualification.
- Whether native-operation-only arbiter rate estimates misrank earlier surplus
  turns: source shows they omit preparation/queueing, but no allocation experiment
  establishes that as the cause. It is not a proven repair target.

## G. Proposed production repair target — conditional, NOT implemented

The supported target is **effective archive service through the shared-owner /
single-flight receipt-to-successor-preparation path**, not reservation arithmetic.

A concrete candidate behavior for Astra to assess is bounded overlap of a
successor archive preparation with draining the current receipt, eliminating an
otherwise idle preparation interval behind source admissions. Relevant boundaries:
ArchiveFlight in solana_evidence_service.py, archive_commit_slice_and_plan(),
and MaintenanceRuntime.turn() receipt completion. This is a proposed direction,
not a demonstrated minimum patch; **the evidence does not yet distinguish it from
reducing source-owner cost or correcting earlier maintenance allocation**.
No exact production implementation is authorized or claimed sufficient.
The unchanged .165/.27 source floor already consumes about 61.1% of owner
wall time at the declared cadence; native source optimization cannot remove
that minimum profile pressure. This further limits any source-only proposal.

Expected effect, if this bottleneck is confirmed: raise achieved durable archive
drain above actual eligibility arrivals with enough surplus to restore every
scope to <=1,000 before its already-latched recovery deadline. Do not obtain
green by reducing canonical profile floors, changing source timing, extending
deadlines, increasing transaction/byte limits or concealing a refusal.

Any approved implementation must preserve strict retained age <240, existing
safety/recovery/service semantics, owner/execution/worker leases, clock allowance,
two-sided reservations, generation fencing, bounded carriers/transactions,
source advancement, durable progress and fairness. Overlapping preparation
requires particular proof against duplicate selection, stale generation,
pin/floor changes, unbounded carriers and duplicate progress. The independent
M1 completion issue is a separate review item, not automatic scope expansion.

If component-level discrimination is required before choosing a repair, the
single best next experiment is predeclared M3: same M2 workload and environment,
only source-owner floor .165 ->0; native source processing unchanged. It tests
the causal effect of **profile-imposed shared-owner occupancy**, not production
SQLite cost alone. It is not a candidate configuration or a license to alter
canonical workload. No M3 execution occurs after this gate.

## H. Old-fails /new-passes regression design

After Astra approves the minimum repair, preserve M2 as the empirical old-fails
reference, with its exact pinned source/diagnostic identity and artifact.
Build a deterministic native regression from the actual repository templates,
.27 source period, source-time-preserving pause/catch-up and unchanged bounds.
Hold controlled owner/source occupancy and bounded real archive preparation;
verify actual native eligibility, durable archive/retirement ledger and readiness,
rather than inserting fabricated Need vectors or only checking an exception.

Old behavior must show sustained drain below arrivals, persistent recovery excess,
shrinking latched headroom, a short unfinished preparation, then the legitimate
empty feasible/refusal sequence. Repaired behavior under the SAME workload must
restore the <=1,000 envelope within the existing episode deadline while source
and retirement advance; remain <240, within native leases/bounds, generation
safe and fair. An artificial fast-preparation/unit-only pass is insufficient.
The future full-control canonical cohort must also prove completion under urgent
interruption; M2's reduced ACK load cannot stand in for that qualification.

## I. Fresh Stage-E successor reconstruction

[CANONICAL_STAGE_E_RECONSTRUCTION.md](CANONICAL_STAGE_E_RECONSTRUCTION.md)
documents the reachable predecessor wrapper, same-SHA prerequisite/assembly
checks, native transition gaps and exact future sequence. After Astra:
approved minimum repair ->old-fails/new-passes ->affected and complete deterministic
verification ->explicitly recreate/integrate required native-transition
qualification ->assembled native build verification ->applicable <1% observer
benchmark ->freeze a NEW exact SHA/tree ->ONE complete canonical Stage E.
Failures earn new diagnosis/repair/SHA and fresh certification. Only a genuinely
green exact Stage-E SHA may proceed to Stage F. No rejected identity/evidence is reused.

## J. Durable evidence and decision request

M1_ARTIFACT.json and M2_ARTIFACT.json bind uploaded ZIP SHA-256 and per-file hashes.
Committed summaries, capacity/terminal excerpts and derived interval arithmetic
provide compact durable evidence; the publication artifact also carries the
hash-verified complete existing raw bounded timelines, ring, health, interactions
and configurations. Original artifacts expire after 90 days; committed excerpts
remain in Git. The publication binding records its own retention/digest.
ASTRA_GATE.json prevents further harness/CI workload execution.

Determine whether the fresh evidence is sufficient to authorize the
proposed production repair. If not, specify the minimum additional
discriminating experiment required.
