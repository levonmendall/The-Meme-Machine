# Astra matched source-owner ablation review

ASTRA_REVIEW_READY: SOURCE_OWNER_ABLATION_COMPLETE

PAPER ONLY. The fresh control reproduces the recovery-collapse/readiness/
reservation chain. Treatment completes the fixed prefix and resolves all 57
native debt episodes within their original deadlines. This pair establishes
owner-pressure sensitivity. Component-level attribution remains unresolved;
production archive overlap remains unapproved. Stage E RED, Stage F NOT STARTED.
Exactly 4/6 executions consumed; 2/6 unused. Workload execution has stopped.

## 1. Configuration, identities, resource information

Reviewed package: 2cc7a7c42e8f98acd57c2b606d132867d2393def.
Historical publication run 36764834925 /artifact 11119244681 remains unchanged.
Production source dc08f9064cf5e37b63f383f52aa709d0afc1723f,
tree 68736cf664169dee665762019800bf87ca0f1f67.
Execution diagnostic SHA 6e104c122dc495d75bd8828a5fea7237b48effdf,
tree 084245305a1bbe49c522b99be20396d633add6e2.
Harness SHA-256 4f6f751a8efb5e7593d3444212ab4638d7126cec4131ba29807e390472003aa5.
Request SHA-256 8bf309ddaf7d9c284922c9adc455763fa74248befa23ac5d9796274242704cac.
CI statically verified all 1,152 production and 1,180 reviewed-package
preexisting blobs/modes unchanged, workload input hashes, identical Wire AST,
native choose/transaction/checkpoint wrappers and native worker/floor code.

[Run 36771603217](https://github.com/levonmendall/The-Meme-Machine/actions/runs/36771603217),
job 110079106497, attempt 1, runner GitHub Actions 1000026400, hostname
runnervm8df0l. Control PID 2375 ran 20:17:55–20:23:34 UTC; treatment PID 2500
ran 20:23:34–20:29:42. Process-group joins found no residual processes. Each
arm created independent runtime/db, archive directory, IPC and worker processes.

Only source_owner_floor differs: control .165 s/frame, treatment zero. Both:
1,334 frames, .27 s/frame, five-second observer cadence, native source work,
archive .36 s/1000, changing outer-COMMIT .006 s, two workers, native arbitration,
FIFO owner admission, fairness, reservations, leases and deadlines. Urgent
periodic/candidate ACKs are disabled; candidate data reads remain. Reduced ACKs
are diagnostic only and unapproved for a candidate/certification.

Static prefix: unchanged first burst 216 s, eight-second pause/catch-up to the
original clock, first recovery window 216–336 s, fixed 23.91 s observation guard.
Last zero-index payload deadline 359.91; count-based source coordinate 360.18.
Second burst remains at 378 and is outside the prefix. Neither recovery windows
nor native episode deadlines were changed. Stop rules: native failure, fixed
committed-frame prefix, or 600 s process-group wall bound.

Both: Ubuntu 24.04 runner, Linux 6.17.0-1022-azure x86_64, glibc 2.39,
Python 3.12.14, SQLite 3.45.1, websockets 17.1; expected-version differences empty.
AMD EPYC 7763 64-Core Processor, four exposed/affinity CPUs [0,1,2,3],
16,373,452 KiB physical RAM. CPU/memory cgroup files unavailable; do not infer
a quota. CPU/address-space rlimits unlimited, nofile 65,536, nproc 63,838.
Filesystem capacity 154,894,188,544 bytes; control-start available 92,355,497,984.
Peak parent RSS control 428,820 KiB, treatment 384,604; peak child RSS
102,948 /102,768. Full per-arm CPU frequencies, load, memory, resource use and
limits remain in the summaries. Start load differed: .732 versus 2.247 (1 min);
one treatment-start CPU frequency sampled 2445 MHz versus approximately
3233–3251 MHz at control start. Fixed order, cache warming, scheduling, filesystem,
checkpoint timing and batch formation remain variable. One pair supplies no
order counterbalance or replication.

## 2. Frames, stops, actual debt and original obligations

| Arm | Native fatal frame /source s | Final committed frames /source s | Harness wall s | Whole subprocess wall s | Stop |
| --- | --- | --- | ---: | ---: | --- |
| Control | 1214 /327.78 | 1216 /328.32 | 332.421 | 339.405 | maintenance_cannot_reserve_both_sides |
| Treatment | none | 1334 /360.18 | 361.076 | 367.383 | fixed_diagnostic_prefix |

Neither arm reached 600 seconds. Both DB integrity checks returned ok, provider
calls zero, observer errors empty, and timing record drops zero.

Coherent SQLite debt snapshots at approximately 240 /270 /300 wall seconds,
then control native fatal or treatment live 355.553 snapshot:

| Scope | Control eligible debt trajectory | Treatment eligible debt trajectory |
| --- | --- | --- |
| Meteora | 3840 →6144 →7216 →4568 fatal | 3248 →1080 →512 →512 |
| Pump | 1530 →2448 →3009 →1887 fatal | 1326 →561 →204 →204 |
| PumpSwap | 2750 →4344 →5015 →3145 fatal | 2210 →935 →340 →676 |

Recovery excess is max(eligible debt−1000,0): control terminal excess is
3568 /887 /2145. Treatment last live excess is zero for all three.
Headrooms use separately timestamped native owner observations, not an asserted
atomic join with the SQLite snapshot:

| Scope | Control archive recovery headroom, ~240 →270 →300 →fatal s | Treatment principal post-burst episode resolution |
| --- | --- | --- |
| Meteora | 97.755 →66.908 →36.991 →5.624 | latched frame 826, debt 1408; resolved 1003, debt 928, headroom 67.712 s |
| Pump | 105.755 →74.908 →44.991 →13.624 | latched 846, debt 1077; resolved 897, debt 918, headroom 99.061 s |
| PumpSwap | 97.755 →66.908 →36.991 →5.624 | latched 826, debt 1047; resolved 993, debt 935, headroom 70.352 s |

Control three archive episodes stayed open; late drain improved in 300–330 s
but did not restore their envelopes before the refusal. Meteora/PumpSwap
retirement episodes also stayed open at stop, with future deadlines; these are
unresolved obligations, not asserted expired deadlines.

Treatment resolves 28 archive episodes (16/6/6 by scope) and 29 retirement
episodes (14 Meteora/15 PumpSwap); none open or late. Minimum resolution
headroom across all 57 is 67.712 s. Pump retirement forms no episode:
report prevention of excess debt there, not invented recovery. Every deadline
comes from native latching; no episode is fabricated, extended or reset by
diagnostics. Last treatment resolution occurs at 338.294 harness seconds,
before the 361.076-second end, excluding shutdown as its explanation.

Control terminal: archive false, retirement true, feasible [], selected none.
Meteora/PumpSwap archive RECOVERY binds at +5.624 s. Archive safety +47.624,
service +44.803 (Pump service +44.573). Retirement Meteora safety +26.624,
service +40.251; Pump +42.624/+38.040; PumpSwap +33.624/+39.389.
Housekeeping safety +9.906, service +12.918. Retirement's own 3 s reservation
fits; preserving archive requires finish at +9 s, deficit 3.376 s.
Archive worker age .196271 s and owner admission .192676 s remain short;
worker lease 15 s, owner/execution leases 3 s, clock allowance 3 s unchanged.

At treatment live 355.553 s: archive safety 56.605/56.605/55.605 s and
service 44.883 s for each scope; no active archive recovery deadline.
Meteora/Pump retirement safety 54.605/55.605 and service 40.655/41.604.
Native readiness true/true. The final treatment ring has no needs after
shutdown; that empty observation is not used as recovery evidence.

66 control and 72 treatment periodic live snapshots have pins=gaps=0.
Shutdown creates three disconnect gaps in each final snapshot. Final snapshots
are retained but excluded from eligibility-arrival/recovery conclusions.
Mature ~210–300 s inferred eligibility arrivals (delta eligible hot plus delta
durable archived) are 87,912 in each arm. Drain control 74,176 (822.958/s)
versus arrivals 975.355/s; treatment 87,968 (975.691/s) versus 975.070/s.
Three control 30-second intervals each drain below arrivals. Treatment initial
debt forms, then actual surplus drain and native resolutions establish recovery.

Durable archive/retirement totals: control 138,768 /123,689; treatment
176,616 /176,352. Per-scope archive and retired ledgers, archive file hashes,
valid inferred arrival intervals, retained/hot ages, source lag, native
observations, original deadlines and terminal rings remain in the evidence.

## 3. Native source versus injected owner time

| Measurement | Control | Treatment |
| --- | ---: | ---: |
| Native source-owner stage wall, whole arm s | 167.074 | 178.365 |
| Injected source-floor wait requested /actual s | 38.482 /39.024 | 0 /0 |
| Retained COMMIT-floor wait inside source stage s | 6.979 | 8.010 |
| Native-stage wall less measured COMMIT floor s | 160.095 | 170.354 |
| Source batches /frames | 1125 /1216 | 1290 /1334 |
| Native stage mean s/batch | .148510 | .138267 |
| Native stage mean s/frame (frame weighted) | .137396 | .133707 |
| Native source-owner thread CPU s | 139.929 | 151.750 |
| Mature ~210–300 native owner stage s | 45.370 | 47.478 |
| Mature requested source-floor wait s | 9.696 | 0 |
| Mature native +requested source-floor fraction | 61.09% | 52.66% |

Native work remains. Native stage wall includes identical COMMIT-floor injection
and embedded wrappers; that retained floor is measured separately. Source floor
actual sleep includes scheduler oversleep. Whole-arm totals have different
lengths, so mature matched intervals and per-frame costs are also reported.
Batch histograms control sizes 1/2/3/4: 1089/7/3/26; treatment 1271/5/3/11.
Every batch's native wall, per-frame cost, CPU, committed count and injected
wait remains in source-batches.json. Source-worker dispatch/execution/transport,
source storage stage and owner priority telemetry remain separate; worker,
transaction and owner-stage spans overlap and cannot be summed as occupancy.

## 4. Archive cycle timing and limitations

Recorded complete submit-to-next-submit partitions: control 145 of 146 flights,
treatment 247 of 248. One incomplete boundary flight in each is excluded; no
missing timings are inferred from aggregate counters. Partitions have zero
computed residual and no negative components.

Mean seconds per completely timestamped flight (whole-arm populations):

| Non-overlapping cycle portion | Control | Treatment |
| --- | ---: | ---: |
| Submit →child start (dispatch/serialization/queue) | .015090 | .007687 |
| Native child archive preparation | .320719 | .235019 |
| Actual archive-floor waiting | .029535 | .025987 |
| Child end →parent callback (transport) | .006280 | .005390 |
| Callback →ready marker | .000030 | .000029 |
| Ready receipt →first commit stage | .214734 | .179341 |
| Sum of commit-slice stage service | .064183 | .052755 |
| Gaps between commit stages | .317520 | .119104 |
| Final commit stage →receipt consumed | .038250 | .021012 |
| Receipt consumed →successor submission | .031917 | .079659 |
| Entire cycle | 1.038257 | .725983 |

Archive-request owner admission mean .198399 / .100992 s; ready-to-owner-entry
mean .150965 / .105209 s. Those task wait metrics overlap the partition and are
not additional occupancy. Mature flight-cohort ready-to-first-commit means
.253903 /.189830, inter-slice gaps .335711 /.182253, native preparation
.305785 /.271544 s. Cohort membership uses launch frame 775–1112, not the exact
wall-snapshot interval; raw per-flight coordinates permit narrower analysis.

Whole populations have different archive batch sizes and amounts of legitimate
low-demand idle time. Receipt-consumed-to-next-submission can include no
eligible work, idle cadence, arbitration, source/checkpoint work and loop delay.
It is not all avoidable launch delay. The final-commit-to-consumed portion
includes native successor snapshot selection and arbiter completion.
Per-flight snapshot_stage is the input snapshot for that flight; the derived
archive-cycle-decomposition.json label successor_snapshot_stage refers to this
same input snapshot, and is a labeling limitation, not proof of overlapping work.

Commit stages include retry attempts where applicable; wall spans include native
durability and retained COMMIT floors. Callback-ready marker precedes actual
Future.set_result by small bookkeeping; clocks are same-host monotonic.
Native child timing is measured, not inferred from counters. Clock calls,
wrapper entry/return and all observer perturbation are incompletely measured.
The decomposition localizes real serialized-cycle delays but alone cannot
prove which repair is minimum, sufficient, or how much overlapping preparation
would safely recover.

Reader/candidate wall 4.857 /4.820 s over 32/35 reads. Native PASSIVE checkpoint
17.811 /17.754 s; mutation-boundary checkpoint 7.585 /7.678; checkpoint with
interaction 19.930 /19.874. They overlap worker/owner/source time.
Both arms retain one held-reader cycle and one completed-tail delay. Source
advances five frames during each held snapshot. Control has zero compaction
advance and no eligible witness at either endpoint (no_eligible_witness);
treatment has 768 compaction advance and an eligible end witness (serviced).
This difference is preserved, not converted into a canonical interaction pass.

Measured extra diagnostic overhead control .925 s (.2783%), treatment 1.191 s
(.3298%); qualification-equivalent observer portions .327 /.265 s separately.
Observer/wrapper/serialization/persistence details remain in the summaries.
No matched uninstrumented arm exists, and no <1% qualification certificate
is claimed.

## 5–7. Interpretation and remaining discriminator

The control reproduces the entire accepted mechanism, with real preceding debt
growth and shrinking latched headroom. Treatment produces real surplus drain,
restores every formed native obligation within its original deadline, and
prevents Pump retirement excess. It does more than survive the old failure frame.
Removing injected source-owner waiting changes the coupled outcome while native
source processing stays substantial. This establishes owner-pressure sensitivity
for this diagnostic pair and its reduced ACK configuration.

It does not establish native source processing alone as the historical cause,
a source-only repair, safe canonical floor removal, production overlap as minimum
or sufficient repair, future-candidate reduced ACK acceptance, Stage E/F
certification, or general capacity on other hardware.

The overlap proposal is better supported as an investigation direction by
directly measured ready-receipt and inter-slice idle intervals and improved
archive service under lower owner pressure. Its minimum/sufficient-repair claim
remains unproven. Successor submission itself is typically near-immediate after
receipt consumption; the low-pressure population also has legitimate idle time.
No production overlap repair is approved or implemented.

The single best remaining discriminator, if component attribution is still
required, is a separately authorized diagnostic comparison holding source floor
.165 and all other native controls fixed, changing only whether bounded successor
preparation can overlap current receipt drain. It must preserve reservation,
generation, pin/floor, fairness and duplicate-progress semantics, and prove
actual recovery before original deadlines using per-flight timing. This is a
recommendation only: no implementation or execution, and no remaining-budget
spend is authorized here.

## 8. Evidence binding and hard stop

Artifact 11124508037, 934,841 bytes, expires 2026-12-29T20:17:43Z.
ZIP SHA-256:
485a522b8e1ab820674528905fa87e953cb444eade31c77635f5ba8cce2cdec6

Original artifact COMPARISON.json SHA-256:
f8601ccc5316bf0a3885a1d4979a28271f2f16a17b1b04f9c6d775e46b4b94d3
Control summary:
f5c78eb11a5a0906280c124c707d1c4d523c1e43285035d1dd36e5984d05012a
Treatment summary:
85ef9746f6cff3fd6be531fb8a922642fe2a8bbe8de0e72ba1eec19aaaa5dadd

ARTIFACT_FILE_HASHES.json binds all 59 preserved files, including raw timelines,
source batches, archive cycles, original episode events, rings, health,
interactions, configurations, historical blockers and static verification.
Full bounded raw telemetry resides in the downloadable Actions artifact.
Runtime databases/archive payloads stay outside Git/logs; archive hashes and
durable progress evidence are preserved. ANALYSIS_LOG_PROJECTION files are
literal machine JSON extracted from the CI log, not byte-identical copies of
the artifact's pretty-printed analysis files. CI_JOB_LOG.txt preserves their
decoded source log. BINDING.json identifies these distinct projections.

Original stopped review package and gate remain historical evidence.
M1 interruption/completion failure and preflight one failure, two errors,
46 skips remain separate, unchanged blockers. Broad certification suite skipped.
No production repair, candidate freeze, canonical Stage E, or Stage F occurred.
Repository FOLLOWUP_STOP.json blocks new harness/driver invocations.

Budget: fresh control execution 3 and treatment 4; total 4/6, unused 2/6.
No retries. Stop for Astra.
