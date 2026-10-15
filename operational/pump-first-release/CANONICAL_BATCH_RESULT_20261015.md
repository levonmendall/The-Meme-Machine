# Canonical batch candidate: measured improvement remains insufficient

Executed `f72a17409cc52c0c649c3fd8d1d95ad30e68e45f`, specification publication
`7c981232`, standing issue134. Run output:
`/var/lib/meme-machine-diagnostics/20261015-standing-bulk-f72a1740-055428`.
Root remains sole integration/test/runtime owner; PR133 remains draft.

The single guarded run ended after907.904s, **STARTUP_LIMITATION**, original300s
readiness **FAIL**, funding closed, acceptance0. Both current native workers
reconciled/stopped/exit0, withoutKILL. PID/process-instance/run-bound records and
the independent post-state review are retained; historical RECOVERY_REQUIRED
results are unchanged. Source startup release remained false throughout.

## Current workload, not a controlled historical comparison

First both-native-reconciled full sample456.704743s to last897.624579s:
440.919836s,86complete samples, one current source generation.

| Comparable progress | Slot units/s |
| --- | ---: |
| CONTROL arrival-side receipts |4.65844|
| Candidate native block metadata/join |2.70344|
| Durable timing head |2.71478|
| Newest retained economics |2.72158|
| Published fixed program frontier |2.71478|

Receipt-to-stored gap grew1038→1892slots; stored market age241.7→421.6s.
Candidate-feed-to-join heads are aligned; join-to-durable gap stayed9→4slots.
Backpressure can hold the native reader, but snapshots do not quantify each
put-wait. This is primarily accumulation before persistence, not a large resident
post-join or publication-only queue. It is still a startup-limited workload,
not sustained four-regime readiness. About1.716x current durable progress would
be needed merely to match this window, before authentic burst/backlog recovery.

The bulk path handled53989records/1196calls; one empty scalar call, no failing
or unmeasured candidate phases. Economic store consumed47.035wall/12.180CPU/
20.609runnable-wait seconds for1197frames. O8's76.300wall/21.147CPU related to
different market data and859frames; these are operating context, not a matched
causal speedup. The authentic offline SQL/CPU comparison remains scoped evidence.

Serial candidate path:113.349s exposed preparation,214.129s owner queue,
106.020s callback,433.497of440.920s.306preparation batches/1197frames≈3.912
frames/batch. Held-plus-queued count2–8, with21of86samples at8. Existing shared
credits count held work; another task alone cannot create capacity or memory.

Owner callbacks413.104s + actual checkpoint handoffs26.294s occupy439.398s.
Owner CPU110.956s/runnable wait192.670s overlap those elapsed spans. Preparation
overlap alone cannot supply owner capacity.2330commits consumed36.767wallseconds,
not proof of a lock holder or a durability defect. Original BUSY not reproduced.

Measured owner components include maintenance_decision76.743wall/17.623CPU,
delivery capture35.479/10.655 and ACK12.792/3.196. Publication callback79.045wall
versus inner lifecycle publication34.785wall across168matched calls leaves
44.259s around startup advancement/glue; do not assign that residual entirely
to CPU or SQL. This supports bounded inspection of those exact dependencies,
not another worker sweep or unchanged observation.

## Pons, scheduling and provider limits

Cgroup average1.68858cores, max observed memory1.628GB. Pons used306.09CPU s:
Survivor105.970, main93.168, discovery57.682, hydration49.081, health0.183.
Six fixed-role TIDs persisted, no truncated inventories.123.819GB logical reads
versus217088physical bytes do not establish physical-device saturation. CPU
pressure and22.439s cgroup throttling are retained; hardware sufficiency remains
unproven. No paid expansion or stronger CPU protection claim is justified.

Managed Robinhood samples wereCURRENT86/86, queue max2/wait0.810s. A separate
bounded completion-ring read found2698current Admission rows:2678HTTP200 and
20deadline failures (15during/5before transport), zero recordedHTTP/RPC429,
no retry rows. The ring begins before this run; this describes retained completed
Admission paths, not every external service or bypass. Method counts and exact
failure scopes are retained privately. Deadline failures remain failures; they
are not explained by a quota, and no deadline was extended. No held positions
exercised full quote+USD protection. Public429cause/provider suitability,
READONLY INSERT and original3/5s held protection stay independently unresolved.

## Safe state and usage

591bounded read-only postqueries, required checksVERIFIED, no unavailable/error
findings. Journal head10634, cash/equity1000, zero eight-category monetary
obligations, historical500 preserved, allfourv1 bindings. Exact earlier ACKs
remain authentic; current bounded64cohort has32ACKs/32pending identities, all
preserved. This is not an event census or proof that every accepted source frame
drained. Native worker stop, current resumability and monetary reconciliation
remain distinct. No checkpoint rewind, evidence deletion or false completion.

Usage:368972CU,10498logical elements,2700physical starts including4native;
576236367native bytes plus285212672uncertain;16004146HTTP bytes plus16777216
uncertain. Frozen-model exposure$0.284162449095, provider invoice unavailable.
Streams, receipts and provider reservations closed. Audit rows/logical elements
have different boundaries and are not forcibly equated to the global meter.

Compatible source66f85d61/saved unit/environment restored06:14:42Z; additive
indexes and all newly committed state retained. PAPER inactive/disabled/
Restart=no/fundingclosed. The restored finite launcher must not be started
unchanged. No normal PAPER promotion or acceptance minute is authorized by a
diagnostic completion.

## Continuing offline work and independent backup blocker

A bounded authentic read identified an availability-prefix scan in startup's
CONTROL MAX query. Merely adding ORDER BY retained the scan and was slower;
forcing the already installed maintenance_coverage_end index preserved the same
answer and reduced one isolated queryCPU0.055260→0.000046s. A focused successor
uses that index when present and preserves legacy query semantics otherwise.
31frontier/startup tests PASS9.551s; not deployed or a whole-path improvement.
The initial startup interval and stale-session skipped-prefix branch are under
separate exact-boundary investigation; their contribution to this live failure
is not assumed. No new live attempt will repeat the old conditions unchanged.

Backup failed-point metadata inventory777entries/0.098s preserved all records.
Although logical failed files total29.608GB, the two largest database inodes have
three hardlinks and only two in the inspected points. Removing those names would
not reclaim13.678GB still linked elsewhere. Known single-link allocation is only
2.253GB, less than the prior minimum4.028GB shortfall, before current growth.
No deletion, outside-link search, copy, purchase or timer change occurred.
Whole-process backup freeze remains incompatible with uninterrupted3s protection.
Its coordinated multi-writer snapshot/barrier and bounded WAL-lease contract must
be implemented/proven separately; independent live DB copies would be unsafe.

Six active opportunity-access changes, nine original economics, attention-only
volume quality, independent Current/Survivor eligibility and all hard safeguards
remain intact. Final FAST/applicable OPERATIONAL are still release-promotion
gates, not a requirement to repeat after each focused correction.

## Validated offline successor

`c5b9dc5472fa36983ef524d0b4b6189a2915713e` corrects the existing-index CONTROL frontier read and the
source-proven stale-session skipped-prefix omission. The latter still requires
0<replayfloor<blockslot and finalized parent below that floor; conflicts, session
continuity, economic publication and exact consumer ACK gates stay unchanged.
Its causal role in this particular failed live startup remains unproven.
Three focused prefix cases PASS; combined208cases207PASS/1stale metric-fixture
FAIL93.386s. The failing test expected no preallocated candidate phase rows; it
now asserts their exact fixed keyset/zero initialization and unchanged contents
after1000decode events. Affected20cases PASS3.179s. Integrated startup, source
guards and economic/history/ACK/cancellation tests passed in208run; no claimed
uninterrupted208PASS, full release PASS or another fullFAST.

Two additional native-retention hypotheses were rejected on authentic stopped
state:allthree housekeeping scans were already negligible, and recent MIN(lo)
already selected the availability index. No housekeeping/index/suffix changes
were made. Retained nested counters put64.551of76.743maintenance wallseconds
in native retention across294turns. Exact planning/mutation/commit attribution
is still missing; the smallest next discriminator is bounded timing inside
that actual retain path, retaining original transactions/cancellation and only
fixed cumulative counters. Another unmodified market observation is unjustified.
