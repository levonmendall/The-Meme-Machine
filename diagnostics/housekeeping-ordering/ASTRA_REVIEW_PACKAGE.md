# Housekeeping ordering prototype: final matched pair for Astra

The isolated treatment serviced the binding housekeeping obligation and returned
to queued source work, but **did not restore recovery capacity**. Both arms
stopped with `maintenance_cannot_reserve_both_sides` before the 1,334-frame
prefix and before completion of the original first recovery window and guard.

**PAPER ONLY. Stage E RED. Stage F NOT STARTED. Budget: 6/6 consumed; 0/6 unused.
STOP FOR ASTRA.** Preparation overlap remains retired.

| Result | Control | Treatment |
| --- | ---: | ---: |
| Final committed frames | 1,214 | 1,207 |
| Final count-based source seconds | 327.78 | 325.89 |
| Native refusal decision frames | 1,212 | 1,205 |
| Housekeeping-only peer-blocking admitted turns | 25 | 2 |
| Those turns with actual housekeeping service | 2 | 2 |
| Those turns with no housekeeping service | 23 | 0 |
| Promoted prefix invocations | 0 | 2 |
| Committed housekeeping deletion units from prefixes | 0 | 1,782 |
| Prefix returns to queued source | 0 | 2 |
| Recorded trigger/progress rule violations | 0 | 0 |
| Native first-window recovery episodes | 24 | 20 |
| Episodes still open at stop | 5 | 5 |
| Forced process bound / residual process group | false / false | false / false |
| Database integrity | ok | ok |

The two treatment prefixes published committed housekeeping progress and returned
without ordinary scope retirement, continuity/floor work or a second deletion
batch behind queued source work. The 1,782 units are operational row deletions,
credited to retirement / __housekeeping__; housekeeping record credit is zero.
The runner's bounded native-turn evidence reports no dropped timings and no
observer errors. Counts of eligible turns are observations within each independent
arm, not matched receipt identities.

The ordering change resolves the tested within-retirement service inversion.
It is **insufficient for the frozen .165 workload in this pair**. Treatment
completed seven fewer frames (1.89 count-based source seconds) than control.
There is no successful recovery/prefix result and no basis for production
promotion or canonical certification. A single fixed-order pair cannot attribute
the terminal performance difference to the patch alone.

At control refusal, archive was unready and retirement ready. The effective
archive recovery deadline had about **5.925230 seconds** remaining, so retirement
could not preserve its demanded archive peer. Control reproduces the legitimate
unready-archive recovery/reservation refusal chain.

At treatment refusal, both sides were ready, but archive had about
**5.930879 seconds** and retirement about **5.564875 seconds** remaining.
Another retirement obligation, Meteora recovery, was also inside the nine-second
peer window at **8.930879 seconds**. No side was feasible. There was no admitted
retirement turn to reorder, and housekeeping was not the sole retirement blocker.
The frozen arbiter correctly refused; the treatment grants no admission override.

Completed mature-flight inter-slice gap peak changed from **4.078570 s** (88
control flights) to **1.073592 s** (84 treatment flights); mean changed from
0.357361 s to 0.343176 s. Mature ready-to-first-commit mean increased from
0.199166 s to 0.243905 s, and its peak from 1.035444 s to 1.229207 s. These are
descriptive timing distributions from independent flights. Each arm has one
incomplete flight excluded from complete timestamp partitions. The shorter
worst gap is not evidence of sufficient recovery capacity.

The focused gate passed **54/54 treatment tests, 1/1 control reproduction and
resource checks** before either material arm. The first test-only gate had one
duplicate-demand fixture error and launched zero material arms. Its correction
gave the mocked next turn a fresh list. The treatment patch was unchanged.
Both attempts and their artifacts are preserved; no material arm was retried.

The patch is stored at [treatment.patch](treatment.patch) and is applied only to
a disposable detached treatment checkout. All **1,197 protected evidence-base
blobs/modes**, including **1,152 production blobs/modes**, remain unchanged on
this diagnostic branch. Static verification proved the existing housekeeping
AST, orphan predicates, extra-key lookahead, ordinary transaction, per-table
max_records bound and committed ledger semantics unchanged. The native scope
loop/transactions, pins, floors, gaps, continuity and record semantics, arbiter,
owner, leases, ledger and outcome model are preserved.

Eligibility uses the exact fresh observation, admitted decision, generation and
effective safety/drought/recovery deadlines: t+E < D_housekeeping <= t+2E+O,
with every other active retirement obligation strictly later than t+2E+O.
A prepared receipt must be pending and ready, and native housekeeping demand
positive. The prefix is one existing bounded batch, never a 256-record slice:
max_records=1000 permits at most 1000 deletions per table and 3000 operational
rows total. It adds no protected atomic interval, checkpoint or vacuum work.
A source/urgent boundary yields immediately after publication. With no waiter,
the unchanged saved scope rotation continues. The tail never repeats the batch.
Newly orphaned rows after subsequent record retirement remain unexamined and
cannot be declared idle; eligibility is recomputed each turn.

Both arms retain **source floor .165**, archive .36 s/1000, COMMIT .006,
two workers, native .27 cadence, reduced urgent ACK controls, local readers and
checkpoints, native readiness/generation fencing, leases, reservation rules,
recovery windows, workload hashes and bounds. They run sequentially in one job
with fresh subprocess groups, stores and archive directories. Entries 5 and 6
are the only new material launches. Each stopped on native failure, without
reaching the 600-second wall limit. The existing historical Astra gates,
M1 interruption/completion blocker and preflight failures remain unchanged.

Execution: [c22e61a](https://github.com/levonmendall/The-Meme-Machine/commit/c22e61a176951c364b9dc855c68adad849479afe).
Source: dc08f9064cf5e37b63f383f52aa709d0afc1723f.
Evidence base: 750190b2067ca2fca771b531396d8e06a9351c62.
Run/job/attempt: **36818149058 / 110227640326 / 1**.
[CI run](https://github.com/levonmendall/The-Meme-Machine/actions/runs/36818149058).
[Artifact 11142687311](https://github.com/levonmendall/The-Meme-Machine/actions/runs/36818149058/artifacts/11142687311),
**1,529,756 bytes**,
ZIP SHA-256 **08028f13ff03f4f78c6700aa8ede205f63eb6730da8dc0a718396e20e3028c54**. Upload-log and REST digest metadata agree.

[Binding](BINDING.json), [comparison projection](COMPARISON_LOG_PROJECTION.json),
[runner file hashes](ARTIFACT_FILE_HASHES.json), [full CI log](CI_JOB_LOG.txt) and
[stop record](FOLLOWUP_STOP.json) are preserved. Public script/patch bytes were
independently SHA-256 checked against the runner bindings. Parsed log projections
are labeled as projections. The artifact ZIP was not independently extracted in
this session; raw native turns, per-flight records, source batches, timelines,
episode transitions, outcomes and original summaries are bound in that artifact.

Reported mixed diagnostic overhead was 0.265135% control and 0.313559% treatment.
Native and extra observer accounting remains mixed; this is not an independent
strict less-than-1-percent qualification. Hosted scheduler, CPU/filesystem,
cache, batch formation and checkpoint timing remain variable. Component spans
overlap and cannot be summed as independent occupancy.

**Immediate stop is now durable.** No further material execution, scheduler
redesign, M1/preflight repair, production promotion, successor freeze, canonical
Stage E or Stage F is authorized. Return this captured result for Astra review.
