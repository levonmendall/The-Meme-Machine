# Replacement observation — stopped, recovery review required

**ACCESS_REPAIR_PASS. REPLACEMENT_OBSERVATION_FAILED. No further start authorized.**

Exact focused-tested/executed successor:
`0333860364b0602583b7e300cbe7e57303697510`. Original specification remains
`282d38946955b46422a34348062ac572777d8473`; only its explicitly authorized access
successor was substituted. Repair/results documentation was published at
`a048ee8cbeb87bff9c589a0b6f587fd909c23ed5` before dispatch. Original failed
attempt/result at `f2a1572e` remains unchanged.

## Access repair and validation

The parent is now root:meme-machine 0710; fresh run directory is service-owned 0700.
Only that parent and fresh directory were explicitly set, without recursive
permission changes, database/credential changes or relaxed service protections.
The service's actual UID997/GID987/groups[987] passed both preparation and the
required controller pre-dispatch guard. Network-isolated probes checked ancestor
traversal, the real metadata writer with a disposable simulated clock, atomic
replacement, terminal temporary-file/hard-link/directory-fsync publication, and
controller reads. Probe files were removed; the actual observation clock was
created only afterward. Existing private/outside-economic-state checks remain.

**39 focused tests PASS in 0.638s**, zero failures/errors/skips, supported runner,
CPython3.12.14/SQLite3.45.1. Actual service/filesystem restrictions were exercised:
uncorrected root-only parent fails, corrected parent passes, unreadable root
clock fails. No PAPER start/provider/authoritative-state mutation occurred in
access tests. No unrelated release suite or competing performance test ran.

## Attempt and shutdown

Single service start: **2026-10-14T16:51:21.616528Z**. Controller requested stop
at **16:54:53.954934Z** on `provider_queue_limit:robinhood`. Result written
**16:55:09.216798Z**, **227.599605619s** from outer origin, within1865s.
Readiness was never observed; restoration/original300s readiness fields remain
null because the attempt ended before that deadline. It is a failed startup
observation, not a readiness or capacity PASS. Zero acceptance minutes.

Original replacement result remains **RECOVERY_REQUIRED**, `failure=true`,
`drained=true`, `native_drain=UNVERIFIED_TIMEOUT_ESCALATION_POSSIBLE`.
Further review found **Pump exit_code=-9 while RECONCILING, reconciled=false**.
The observed15.23s stop interval is consistent with the existing15s lane timeout
and its SIGKILL escalation path; the exact kill invocation was not logged.
Pons exited0, STOPPED/reconciled=true. Supervisor exit0, empty cgroup
and inactive unit do not override the failed native Pump drain. Canonical owner
admission ended closed and phaseOFF; exact source-child exit code is not retained.
No terminal SQLite error file was produced: original BUSY remains unreproduced
and unrepaired, rather than receiving a healthy-SQLite certification.

## Pump: measurable accumulation, unresolved dominant cause

Comparable current-generation samples **109.568341→208.207848s**, **98.639507s**,
exclude the restart's large retained-stock frontier jump:

| Progress, per overlapping scope | Delta / rate |
| --- | --- |
| CONTROL frontier, arrival-side proxy | +423 slots / **4.288343 slot units/s** |
| Newest retained economic slot, each program | +150 / **1.520689/s** |
| Published program frontier, each program | +144 / **1.459861/s** |
| CONTROL→retained economic gap | **146→419 slots** |
| Retained economic→publication gap | **1→7 slots**, observed maximum8 |
| Retained economic market age | **44.17→109.81s** |

Pump/PumpSwap scopes overlap and must not be summed. CONTROL is not a recovered
raw-frame/event count; newest economic-slot progress is not a count of every
committed slot/event. The largest visible accumulation precedes retained
economic evidence; publication has a smaller tail. A display-only explanation
is insufficient. This does not distinguish acquisition/join, preparation,
owner scheduling or required persistence as the dominant causal constraint.

Measured owner callback deltas: candidate commits **40 calls,36.75s wall/7.49s
CPU**; scouts **59,24.27s/3.83s**; history publication **30,12.09s/3.97s**.
They are components of source commits, not additional disjoint pipeline time.
Owner SQL: **333 commits,6.141484s wall/0.982493s CPU**; checkpoint owner holds
**17,6.620059s**. Physical checkpoint elapsed is another overlapping measure.
Persisted retention totals did not increase in this window; the old769s total
is not current recurring cost.

Service group averaged **1.680402 CPU cores**, with **7.314423s throttling**
across574 throttled periods. Main-thread runnable waits rose about53s each for
source/Pump/Pons; owner-thread attribution is unavailable. Memory rose about
404→729 MB (about 386→695 MiB); I/O pressure exists but actor I/O wait is not attributed, and
cgroupio.stat was unavailable. These observations support resource competition,
not a hardware-insufficiency, SQLite-lock or GIL verdict.

Two measurement limitations matter: `observation.numeric()`'s128-key clipping
dropped nested pipeline/aggregate timing counters when current processing began;
the fixed32-record history cohort selected old scout/activity records, all
DELIVERY_PENDING. Current-run history commit/exact-ACK/strategy-consumption
rates therefore remain unmeasured. Recent canonical pending heads were visible,
with sampled ages about0.90–5.39s, but are not a queue-population count. Pump
remained RECONCILING and provider termination prevented a steady-state interval.
**No production throughput correction is yet causally justified.**

## Pons: natural throttling and admission delay

Current-window indexed audit: **68 completed Pons transports**, public7 and
canonical Alchemy61. Two natural public **HTTP429** responses occurred on
four-element `eth_getLogs` batches (dispatch elapsed203.799s/213.337s, including
drainage). Public endpoint is `https://rpc.mainnet.chain.robinhood.com`, not
Alchemy. Both contexts show process-endpoint in-flight1/retry0, onlycf-ray,
no Retry-After/rate-limit details. Chunked body capture was safely skipped
under the original deadline; provider's exact restriction remains unknown.

Public dispatch spacing: min**0.586s**, median**0.907s**, max**8.253s**.
The old125ms post-cooldown burst was not observed. Following the first429,
discovery admission55403 waited **6.979s**; existing `Admission.invoke` sets
an8s endpoint cooldown. Rejection→cooldown→long discovery admission is supported.
Canonical transports had no recorded boundary error; maximum observed canonical
admission wait was0.123s. This does not prove complete protection deadlines.

The last full sample reports queue depth1/oldest wait0.845s. The controller
raises its queue guard before appending the failing sample, so its exact
threshold-crossing depth/wait is unavailable. Complete quote+USD turns were not
retained. Fifteen position_monitor/two conversion transports establish related
reads, not held-position or three-/five-second protection capacity.

## Accounting, usage and rollback

Fresh monetary replay/reconciliation **PASS**, $1,000.00 cash, zero positions,
reservations, commitments, obligations and pending work. Routine authorized
reporting advanced sequence8826→**8896**, journal head
`197e8d1ca6c0629b2b810151105f118cfa09aa18d6fdb9f6b903b5d95f76a57e`.
Epoch/policy/inception and realized balances remain unchanged. Historical$500
complete identity remains unchanged (sequence2036). Read-only native Pump
positions and both directional-sleeve held populations are zero; this is
financial safety evidence, not successful Pump startup/recovery.

Durable usage deltas: **75 physical HTTP attempts,4 native opens,260 logical
elements,7302 modeled RPC CU (6262 Alchemy CU),641264 HTTP bytes,145774792 native
bytes**. Uncertain unread-byte accounting: HTTP33554432/native285212672; not
delivered-byte claims. Existing conservative model increment **$0.049087233720**,
including uncertain native bytes; provider charges/plan fees not verified.
Completed Pons transports and global attempt counters have different scopes.
No spending-based stop or new quota was introduced.

Compatible source/configuration rollback completed **17:09:36.158078Z** to clean
`a70e2610743d8595b3d1a36ed25821a6689c29f3`. Saved overlays restored exactly;
source identity metadata restored. The authorized diagnostic parent repair
remains0710. Post-observation states/counters were verified unchanged by rollback;
no database rewind, accounting reset, evidence removal or restart occurred.
PAPER ends **inactive/dead, MainPID0, disabled, Restart=no**, funding closed.
Backup timers/routes/profiles/credentials were not changed. Existing completed
recovery references remain; later failed backup remains unusable. Native Pump
recovery review is required before any separately authorized restart.

## Smallest justified next work — not executed

1. Preserve the triggering queue facts before raising the existing guard;
   explicitly retain required pipeline counters within the same output bound
   and use the existing tracker with a current canonical cohort. Focused
   regressions should prove no changed safety threshold or false ACK/readiness.
2. Offline reproduce the captured batch429/fallback/next-admission sequence.
   `ObservationFallbackRpc.batch` omits the single-call adaptive slowdown hook;
   evaluate that exact difference before a patch. This does not explain the
   provider restriction or prove adaptive slowdown will cure429s. Keep the
   independent managed-provider decision open.
3. Attribute Pump's long RECONCILING operation and missed graceful cancellation
   using existing retained startup state/code, without reopening the closed
   full historical replay. Do not increase shutdown deadlines or infer a
   throughput repair from one slow callback.

No new tests, fixes or provider workloads were executed after the attempt.
No unchanged observation retry is justified or authorized. Pump capacity,
original SQLite BUSY, Pons provider suitability/READONLY INSERT, later backup
failure and backup/protection compatibility remain independent open blockers.

Private evidence root:
`/root/Documents/Codex/2026-10-10/the-meme-machine-eliminate-redundant-data/blocker-repair-20261011/`.
Use `REPLACEMENT_OBSERVATION_*` preparation/before-state/controller/journal,
postcheck/final-health/shutdown-review/analysis/rollback/publication receipts,
the focused access-test log and original diagnostic output directory
`/var/lib/meme-machine-diagnostics/20261014-replacement-combined-165022`.
Small published summary/hashes:
[evidence/replacement-observation-20261014.json](evidence/replacement-observation-20261014.json).
Keep databases and larger evidence in their original persistent storage.
