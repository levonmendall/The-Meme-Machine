# Post-replacement offline repairs — stopped for review

**OFFLINE_REPAIRS_VALIDATED. No deployment, start or provider workload authorized.**

Receiving branch: `engineering/targeted-resolution-20261014`. Reviewed baseline
`ddcee53eb2498b7281820793408abbea71f2e88a`; failed replacement executable
`0333860364b0602583b7e300cbe7e57303697510`. Exact combined tested candidate:
**`ccc0cb3d52741b382d8680d717e0a226cf04f0b5`**. Subsequent handoff publication
changes documentation/evidence only. The publication SHA and remote verification
are saved in `E/POST_REPLACEMENT_OFFLINE_PUBLICATION_20261014.json`.

`E` is the existing persistent evidence directory
`/root/Documents/Codex/2026-10-10/the-meme-machine-eliminate-redundant-data/blocker-repair-20261011`.
Original failed results, post-attempt databases/journals/counters and the access
repair are preserved. No database rewind, sidecar removal, bulk copy, historical
replay search, recovery campaign, service/configuration change or provider call
occurred in this repair phase. Separate untested/undeployed WIP remains at
`66a87ac32f969195352ade7d35150dd2be53b81b`.

## Reviewable changes and focused validation

| Commit | Correction |
| --- | --- |
| `81d60d5ecd2edbdb779c9ba533c0cd8fd11c6a82` | Pons batch adaptive feedback, inherited fallback deadline, inactive managed observation route and focused tests/provider decision |
| `e281769722d05f5646990054baa77729f529a251` | Honest incomplete reconciliation on cancellation, bounded startup/shutdown attribution and exact source-integrity guard/tests |
| `ccc0cb3d52741b382d8680d717e0a226cf04f0b5` | Required counters, current canonical cohort/exact receipts and ACKs, triggering guard/final native facts and focused regressions |

The final exact candidate passed **171 distinct affected tests in 11.314 seconds**,
zero failures/errors/skips, through the supported network-blocked OPERATIONAL
runner and scratch containment. Runtime: CPython3.12.14, SQLite3.45.1, existing
`/opt/meme-machine/.venv/bin/python`. This is functional validation, not a
performance/capacity benchmark. No full release suite was rerun.

Final log `E/POST_REPLACEMENT_COMBINED_OFFLINE_20261014.log` records the exact
revision, runtime and complete selected classes/cases. It covers six affected
Pons modules, all54 diagnostic/access tests, all11 new Pump cancellation tests,
restart/genesis checks, two existing supervisor shutdown cases and four exact
source-integrity cases. Earlier focused logs remain: Pons92 PASS/4.149s,
diagnostics52 PASS/0.908s, Pump/guard17 PASS/7.002s. These overlap the final run;
their counts and elapsed times must not be added as independent proofs.

Two expected pre-repair RED cases remain retained:
`E/PONS_BATCH_429_PRE_REPAIR_20261014.log` and
`E/PONS_FALLBACK_DEADLINE_PRE_REPAIR_20261014.log`. Successful final assertions
were preserved, not relaxed. Pump's diagnostic wrappers have exact AST pins;
removing only those reviewed wrappers yields the entire published pre-repair
runtime AST. Negative tests reject changed calls/arguments or other edits.
All original economics, nine-change and attention guards remain enforced.

## Pump recovery and cancellation disposition

Four different facts remain separate:

- Monetary reconciliation: previously completed PASS; fresh bounded read-only
  checks match its exact $1,000 projection/head and the historical$500 head.
- Native Pump reconciliation: **unfinished**, last RECONCILING/reconciled=false.
- Canonical pending work: **retained**, not completed or discarded. Indexed
  read-only probes establish at least257 records each in the canonical outbox,
  unconsumed candidate-history outbox and pending proofs; these are lower bounds,
  not population counts or current-run queue-growth measurements.
- Graceful Pump drain: **failed/unverified** after exit-9. The old15.23-second
  stop interval is consistent with the existing15-second escalation, but the
  exact active operation, signal origin and kill caller were not recorded.
  No OOM, SQLite lock holder or causal throughput explanation is inferred.

The retained initial Pump report was published around189 seconds after service
start. Its pre-restoration snapshot narrows chronology but cannot identify the
operation blocked during the following approximately23 seconds before stop.
Review: `E/PUMP_CANCELLATION_RECOVERY_REVIEW_20261014.json`.

One reporting defect was demonstrated and corrected: `lane.main()` previously
marked cooperative Shutdown reconciled=True regardless of startup completion.
It now preserves the prior verified reconciliation state. This does not make
unfinished work reconciled or fix the historical kill/cancellation cause.

Fixed startup-operation IDs now identify current work and actual executor
PID/native thread; an eight-entry completion ring and passive signal facts
preserve cancellation context. Supervisor shutdown retains requested/sent
signals, caller/target identity, actual wait/timeout/outcome, bounded to48 records.
Optional recorder errors preserve the original application exception. Signal
recording takes no lock and performs no filesystem/database operation. Existing
startup calls/order,15-second lane wait, escalation and65-second service stop
limit are unchanged. Disposable pending-marker tests prove this reporting path
does not delete pending state; they are not full production crash-recovery proof.

## Diagnostic completeness and honest limits

Required fixed pipeline/owner/SQL counters are selected before generic128-key
clipping. Tests exercise realistic nested overflow and the complete SQL sample
and serialized output path. Missing sections remain UNAVAILABLE; overflow is
reported explicitly. Descriptive data retains existing privacy clipping.

The existing cohort mechanism now samples at most32 indexed canonical economic
obligations, retaining unfinished identities. It fences source PID/generation/
session and original identity/slot/availability/hash, validates consumer receipts
and exact compact ACK content, and rejects changed evidence. Old scout/activity
stock cannot fill the cohort. New records do not erase pending identities;
missing receipts, source changes and snapshot skew cannot become successful ACKs.

Limits: newest-pending per-program index prefixes are samples, not population
counts; outbox obligations are not distinct event/slot counts. Cross-database
snapshots are independent. Receipt `at` is the original source time, not consumer
COMMIT completion. Physical raw arrival and per-event generation are not stored
in these economic bodies; capture provenance and original market/availability
times are reported without inventing that evidence. Old market data with recent
availability is classified as retained/replayed, not new arrival. Proof eligibility,
missing-join reasons and strategy-consumption counts remain unavailable where
the existing source does not expose them. No such value is replaced with zero.

The existing >64-depth/>5-second queue guard now saves its triggering depth,
oldest wait, thresholds, observation/sample timestamps and available validated
endpoint/role/cooldown/admission fields before raising the original exception.
Absent endpoint/role/cooldown fields remain UNAVAILABLE. The small failure file
and final result share the existing64-KiB metadata reserve; source SQLite's
terminal channel remains separate. Recording failure cannot replace the original
safety stop. Total32-MiB output,5-second full samples,1-Hz guards and all original
deadlines remain. Final native health is PID-fenced descriptive evidence, never
a drain or reconciliation PASS.

## Pons findings and inactive provider route

The actual four-element eth_getLogs batch →429 →shared cooldown →canonical
fallback →next admission path reproduced missing batch adaptive feedback.
The fix applies the existing endpoint-wide2→1.5-RPS slowdown without another
public attempt, sleep or scheduler. One accepted physical batch is one recovery
step, irrespective of four logical elements; twenty accepted batches recover
1.5→1.6 RPS. Physical/logical accounting and original requests remain distinct.

A second demonstrated defect allowed fallback to acquire a new request window
instead of the caller's absolute deadline. A temporary bound in the existing
thread-local admission scope now preserves the stricter caller/canonical deadline
without altering concurrent protective requests. Tests cover batches, singles,
expiry, fallback, accepted-result accounting and independent canonical priority.

The original eight-second public cooldown **still** yields a7.875-second next
admission wait in the125-ms mock fixture, exceeding the unchanged five-second
queue guard. That incompatibility is exposed, not bypassed. Adaptive feedback
does not identify public quota, cure provider throttling or prove live capacity.

`MM_PONS_OBSERVATION_ROUTE=canonical_primary` is an **inactive source candidate**.
Default public routing is unchanged. Unlike merely substituting an Alchemy URL,
the explicit choice uses only the bound primary with its existing mandatory
admission, chain guard and immutable evidence store; no independent acquisition
system, public fallback or spending authority is introduced. No installed flag
or route changed. Cursor/filter/economic/qualification code remains untouched.
Exact authenticated header/blockHash-log reuse is tested; changed filters and
numeric-range misses still acquire their required evidence. Unverified filters
retain ten-block fallback; only the existing exact factory proof permits40 blocks.

Before activation, establish actual account-wide capacity/terms and other-app
demand; exact required methods/history/filter coverage; original five-/three-second
protection under shared observation; and net incremental unique calls/CU after
verified local reuse and existing fallback. These remain missing. Details:
[PONS_MANDATORY_PROVIDER_DECISION_20261014.md](PONS_MANDATORY_PROVIDER_DECISION_20261014.md).

## Preserved operating state and next decision

At **2026-10-14T17:51:34Z**, clean installed source remains
`a70e2610743d8595b3d1a36ed25821a6689c29f3`. PAPER is inactive, MainPID0, empty
cgroup, disabled, Restart=no; new-risk readiness is false. Cash$1,000.00,
zero positions/reservations/commitments/obligations/pending monetary deliveries;
sequence8896/head `197e8d1ca6c0629b2b810151105f118cfa09aa18d6fdb9f6b903b5d95f76a57e`.
Historical$500 remains sequence2036. Provider counters exactly match the
post-attempt receipt: zero added requests/cost in this phase. Root/volume free
bytes12,392,574,976/21,384,511,488; diagnostic parent0710 retained. Original
RECOVERY_REQUIRED result hashes match. This preservation check reuses the prior
completed monetary reconciliation; it is not a new broad restore/integrity test.
Receipt: `E/POST_REPLACEMENT_OFFLINE_FINAL_STATE_20261014.json`.

| Independent blocker | Disposition |
| --- | --- |
| Batch pacing/fallback deadline | Corrected offline; not installed or live-proven |
| Pump interrupted native recovery/graceful drain | Historical blocking operation/caller unresolved; instrumentation ready |
| Pump sustained full-machine throughput | Unresolved; no before/after throughput claim |
| Public RPC/mandatory managed-provider arrangement | Eight-second cooldown versus five-second guard unresolved; inactive route needs capability/capacity evidence |
| Original Pump SQLite BUSY | Not reproduced/repaired by these tests |
| Pons READONLY INSERT | Original diagnostic/failure remains open; no permission/DB fix |
| Later failed backup and active-backup/protection compatibility | Separate, unresolved; failed point unusable, existing completed recovery reference preserved |

The smallest next runtime question is **which startup operation is still active
at cancellation, and where current canonical obligations accumulate** on this
exact candidate. A separately authorized, single funding-closed observation can
use the existing controller/spec and unchanged providers/guards, retain the new
startup/thread/shutdown facts and stage/receipt counters, and stop on its first
safety failure. Existing maximum900-second startup/900-second post-startup budgets,
1800-second work/1865-second drained boundary and300-second readiness requirement
must remain intact unless an explicitly reviewed successor is authorized.
If a public guard ends it before steady state, the result is startup/provider
limited, not a CPU/capacity verdict. A newly attributed operation can justify a
small disposable reproduction; no recurrence cannot be called a repair. This
candidate does not promise that another public-route run reaches steady state.

The managed-route capability question is separately bounded: inspect actual
account capacity/terms first; reuse the verified factory proof and locally
authenticated evidence; specify only missing methods/exact filter intervals and
shared quote/USD checks before asking for any capability traffic or route switch.
Do not enable the route from an environment-variable change alone. A short
capability check cannot establish sustained capacity, held-position management
or autonomous admission. Neither proposed workload is authorized or executed.

Any subsequent installation/start requires owner review, fresh actual obligations,
source/configuration identity, storage/access/recorder coverage, a usable recovery
reference and backup non-overlap. Preserve post-attempt pending work and compatible
rollback; do not reinstall the old diagnostic driver or rewind databases. Keep
funding closed throughout diagnostics. **Zero one-hour acceptance minutes. Finish
stopped for review; no automatic observation, deployment or restart.**
