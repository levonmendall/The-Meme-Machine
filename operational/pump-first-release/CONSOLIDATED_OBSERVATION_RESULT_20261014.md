# Consolidated observation and offline follow-up — 2026-10-14

Latest recovery-gate decision: [NATIVE_RECOVERY_VERIFICATION_20261015.md](NATIVE_RECOVERY_VERIFICATION_20261015.md)
verifies current-state guarded resumability; it supersedes the historical gate's
retrospective drain requirement. Original failed observation/results below remain unchanged.

Executed source: `1fe5a6f62d37f84ad24f0b7413279c080e3424e5`.
Observation-followup baseline: `c8beb2d1317084779f97214b6015b7c345242085`, branch
`repair/consolidated-startup-followup-20261014`, based on owned integration head
`c1c3fd1662b1acbb917f57bfd0e578fc7a349bce` (includes workflow merge `893640f2`).
Review: [PR 133](https://github.com/levonmendall/The-Meme-Machine/pull/133).
Latest offline lifecycle executable: `ba25499b26103ec5d14f1ce765c8e8f180695f33`.
Follow root `AGENTS.md` and the operational-resolution skill. This attempt
consumed the preceding single-start authorization. The later conditional campaign
has not dispatched; its mandatory native-recovery stop is recorded below.

## Conditional campaign: stopped before dispatch

The owner subsequently authorized three funding-closed starts within 24 hours,
with an explicit stop if preceding native recovery cannot be established safely.
**Zero campaign starts consumed.** At 23:30:22 UTC, a fresh read-only projection/
journal check exactly matched the completed replay ($1,000.00, 8,982 events,
no monetary obligations). Provider ledger and original failure-result bytes were
unchanged; the service remained stopped/failed, disabled and `Restart=no`.

Independent source review found the existing read-only native economic recovery
in `runtime/terminal_reconciliation.py:148` and `runtime/directional_accounting.py:49`.
It does not establish full canonical pending-work, exact receipt/ACK, interrupted
candidate restoration or source recovery/drain invariants. The prior sampled
receipt establishes preservation, not that complete verdict. Actual recovery
uses authoritative `EvidenceWriter` startup, `HistoricalTasks` recovery and
`PrewarmStartup.begin`; it is not an existing comprehensive read-only check.

The native-recovery gate therefore cannot pass on present evidence. Preserve
RECOVERY_REQUIRED and stop the live campaign for owner review, as required by
its mandatory safety clause. No source correction is invented to replace this
missing proof, and no additional offline defect was demonstrated in the Pons
review. The repaired code's focused tests remain scoped evidence.

Next decision: a separately scoped native-recovery verification must establish
the missing boundary before another ordinary combined diagnostic can dispatch.
A recovery-only start despite that unresolved prior boundary would need explicit
owner review; the new campaign does not implicitly authorize this exception.
Do not bypass the gate, replay historical searches or rerun the full suite to
substitute for native recovery. The private gate receipt is
`CAMPAIGN_NATIVE_RECOVERY_GATE_20261014T233022Z.json` under the evidence root.

The latest root-cause addendum authorized the bounded offline evaluation below
of the shared native-recovery/lifecycle contract. It compared the existing local
cancellation correction, a coordinated subsystem correction, and replacement.
The resulting fixtures demonstrate a separate ownership defect; the missing
post-TERM trace does not attribute the historical kill. No exception to the
native-recovery gate is assumed. Original runtime and safety boundaries remain.

## Bounded subsystem correction completed offline

Actual native-entrypoint/factory fixtures demonstrate a **Level-2 resource
lifecycle defect** across pre-loop failure and delayed Survivor failure after
loop entry. This does not attribute the historical 15-second stall or throughput.

| Option | Disposition |
| --- | --- |
| Local cancellation checks only | Preserve c8, but reproduced ownership/future cuts remain. |
| Coordinate existing lifecycle mechanisms | Selected: one owner throughout `main`, seven fixed acquired resources, idempotent closers in original order and constructor-only cancellation on the existing executor. |
| Replace canonical owner/storage/orchestration | Unsupported by current causal evidence; unchanged. |

Pump cleanup attempts every remaining owner after startup, asynchronous close or
final-report failure, preserving the first exception and original return values.
FILL clears only for the owned plane. Survivor cancellation resets before normal
steps. Health retains immediate TERM facts and the original two-second cadence
until terminal completion; the bounded collector recognizes only the new fixed
cleanup/constructor operations. Exact byte reversals preserve all prior economic
guards. No new process, database, provider route or authoritative writer exists.

- Complete ownership regressions: **8 PASS / 0.440 s**.
- Source reversal/final diagnostic serialization: **2 PASS / 1.066 s**.
- Affected combined run: **297 tests / 95.045 s, one failure**. The sole failure
  assumed the startup ERROR must be last; cleanup now follows it. Its strengthened
  assertion requires the exact original ERROR/type, unfinished reconciliation,
  unchanged pending work and each cleanup completion.
- Final actual rehearsal plus ownership: **17 PASS / 2.128 s**, no skips/errors.
  The other 296 passing results are reused with unchanged production source.
  This is not an uninterrupted 297-case PASS or general release PASS.

The 297-case run finished before its worker could be located for interruption;
no interruption signal was sent. REDs and failures remain retained. No repeat
full FAST was dispatched; the c8 baseline result below remains separate.
Runtime: pinned CPython 3.12.14 / SQLite 3.45.1, network-blocked disposable state.

At 00:02:17 UTC the verified $1,000 projection/head, provider ledger and original
RECOVERY_REQUIRED bytes are unchanged. Campaign usage: **zero starts, zero
provider calls, zero new provider spending**. Clean installed source remains
`66f85d61`, stopped/failed, disabled, `Restart=no`. No epoch or database rewind.

Individual constructors still own partial internals before returning. No actual
retained-state recovery, sustained throughput, managed-provider suitability or
held-position PASS is claimed. The strict native-recovery gate remains STOP;
owner review must establish supported native recovery before another ordinary
combined start. No exception to that gate is assumed or requested here.

## Observed result and safe state

Fresh preflight established the flat operating epoch, unchanged historical $500
accounting, durable native pending work, applicable prior recovery reference,
natural backup-free window, provider controls and actual service-user access.
Only the exact authorized source and temporary OBSERVATION configuration were
installed. Funding remained closed. No allocation, reservation or fill occurred.

Service start: **22:40:46 UTC**. First fatal marker: **22:44:41.616816 UTC**.
The controller reported an empty process scope at **250.071 seconds** from its
monotonic start; native drainage failed as detailed below.
The startup failed before the original 300-second readiness deadline; the raw
deadline-only `original_readiness` field remains null, not a fabricated timed
verdict. Readiness was never established and no diagnostic minute counts toward
acceptance. Original controller result remains **RECOVERY_REQUIRED**, unchanged.

Pons PID 2825110 raised `pons_current_watch_interpretation_changed` through
`discovery_future → _poll → read_market → nominate → Broker.enqueue →
_sync_watch_order`. Candidate retirement had preserved a watch at generation 2
under the previous policy. A new SELL committed a v1 generation-1 candidate
before synchronization encountered that older watch. Exact retained bindings
confirm this mechanism. The numeric discovery-executor thread ID is unavailable.

Pump PID 2825109 received TERM while `pump.observed_candidate_events` was active.
Supervisor PID/native thread 2824981 waited the unchanged 15 seconds, sent KILL,
and recorded exit -9. This was not successful native drainage. The sampled
operation was active shortly before TERM. Offline reproduction demonstrates
missing cancellation checks between completed history reads, but the retained
record does not establish which operation ran during the following 15 seconds.
The correction covers that demonstrated cancellation boundary; it does not prove
the final kill's complete mechanism. No OOM, SQLite lock holder or historical
BUSY mechanism is inferred.

Post-stop read-only monetary replay verified **8,982 journal events**, conservation,
cash **$1,000.00**, and zero positions, reservations, commitments, obligations or
pending monetary deliveries. Inception, capital policy and historical $500
accounting are unchanged. The 80 new journal actions were one admission, six
owner and 73 reporting publications; no economic entry action occurred.

Original 24 sampled canonical/history/proof identities remain present. The final
current 32-identity cohort has 21 authenticated receipt/exact ACK matches and 11
pending deliveries. The authenticated source checkpoint remains unreleased in
`WAIT_FOR_DURABLE_PUBLICATION`. These bounded checks establish retained pending records; they
are not a complete native-recovery, resumability or coverage PASS.

Compatible source `66f85d61bf4d3ba9a01efdc0e9eb68949419bda8` and saved small
unit/environment overlays were restored without starting anything. No database,
policy-selection history, provider counter, journal or pending work was rewound.
PAPER remains stopped/failed, disabled, `Restart=no`, funding closed. The installed
source still has known startup defects; do not start it or confuse its old finite
diagnostic overlay with normal continuous PAPER configuration.

## Measured pipeline and provider scope

Current-generation startup interval **98.872–233.752 seconds** (134.881 seconds),
excluding the stale retained-frontier jump:

| Comparable progress | Slot units/second |
| --- | ---: |
| Shared parsed arrival | 4.715 |
| CONTROL | 4.634 |
| Complete join | 1.987 |
| Prepared | 1.972 |
| Newest stored economic | 1.980 |
| Published program frontier | 1.942 |

Pump/PumpSwap overlap is not summed. CONTROL-to-stored gap grew **131→489 slots**;
stored-to-published gap grew **3→8**. Market-time evidence age grew **38.63→116.51 s**.
Most accumulation is before complete join/persistence, not just frontier display.
All samples remained in Pump reconciliation: this is no steady-state capacity
verdict or controlled historical speedup.

Cgroup CPU averaged **1.756 cores** under the original 1.8-core limit, with
13.725 seconds throttled and substantial main-thread runnable waits. Measured SQL
commits totaled 9.17 seconds; source-owner callbacks totaled 106.45 wall/24.13 CPU
seconds. Callback, transaction, checkpoint and queue timings overlap and are not
added. The actual owner executor's runnable delay and per-event transport/read/
join/admission timestamps are unavailable. Provider delay, local scheduling and
canonical backpressure are not sufficiently separated for another throughput
correction or a hardware-insufficiency claim.

The bound Alchemy endpoint recorded **37 Pons HTTP starts / 180 logical elements**:
36 HTTP 200 responses, one `pons_selective_trajectory` evidence-deadline boundary,
and zero HTTP 429. Maximum measured admission wait was 0.229 seconds; minimum
actual dispatch spacing was 0.111 seconds. Exercised methods were `eth_chainId`,
`eth_getCode`, `eth_call`, `eth_getLogs` and `eth_getBlockByNumber`. The deadline
boundary occurred before the fatal watch error; it is retained, not classified
as throttling or a successful request. This short startup proves neither sustained
account capacity nor complete held-position quote/USD protection. Candidate calls
occurred; complete native quote/USD timing is unavailable.

Durable usage delta: **40 HTTP RPC starts plus four native openings** (44 ledger
physical starts), 183 logical elements (180 Robinhood, three Solana), 4,042 CU,
533,701 HTTP bytes and 152,695,045 delivered native bytes. An additional
285,212,672 native bytes remain uncertain/reserved-buffer accounting, not confirmed
delivery. Frozen conservative modeled cost is **$0.048102360285**; provider invoices
are unavailable. No cost ceiling or provider counter was reset or introduced.

## Supported offline repairs and validation

Pump checks cooperative cancellation before candidate enumeration, between
candidates and after each completed history read. It preserves durable work,
original SQL and shutdown deadlines, and unfinished reconciliation. It cannot
interrupt an in-flight blocking read or prove complete live drainage.

Pons reuses existing interpretation renewal and flat/native-owner checks for the
recognized retired-watch projection. It preserves original BUY context, exact
identity and original clocks/deadlines, advances generation fences monotonically,
and requires fresh qualification. Tests cover the actual prior executable's
adapter binding, the retained failed SELL cut, interrupted accepted BUY projection,
equal generations, incompatible identities, corrupt records, claims, results and
native exposure. No old result grants entry. Exact source guards reverse only the
reviewed infrastructure nodes before applying all original economic assertions.

All six active opportunity-access changes, nine earlier economic changes,
attention-only volume quality, Current/Survivor independence, native sizing,
realized-equity compounding, partial exits, trailing and staged scaling remain.
Meteora/Ramses remain paused. These repairs are not installed.

- Original focused RED: five cases / 0.666 s, two failures and six error reports
  (including subtests), retained. Additional BUY-cut, previous-adapter and
  equal-generation REDs are retained separately; no failed result is relabeled.
- Pump's two direct cancellation regressions: **PASS / 0.510 s**.
- Initial coherent integrated source: **223 PASS / 49.362 s**, zero skips/errors.
- Final affected successor: **106 PASS / 35.604 s**, zero skips/errors, including
  all affected source guards, policy/Broker/native-owner cases and the existing
  nine-case integrated startup rehearsal. Unchanged earlier proofs are reused;
  these counts overlap and are not added.
- Already-dispatched complete FAST: **2,165 tests / 1,515.638 s, PASS**, zero
  failures/errors and one disclosed hosted service-identity skip. Exact source
  `c8beb2d1`, terminal
  [run 38652038787](https://github.com/levonmendall/The-Meme-Machine/actions/runs/38652038787)
  result preserved. The draft-PR skipped workflow is not a PASS. This is a
  baseline proof, not validation of subsequent lifecycle edits.

Local checks use the supported OPERATIONAL/FAST runner, network guard and Scratch,
CPython 3.12.14 with linked SQLite 3.45.1. Hosted build details are separate; no
sandbox or CI hardware is treated as Droplet throughput evidence.

The owner subsequently replaced the blanket full-suite diagnostic gate. Root
`AGENTS.md` and the operational-resolution skill now require affected checks,
the actual integrated startup rehearsal for changed lifecycle dependencies,
exact source/economic guards, implicated safety regressions and fresh host
preflight for a separately authorized diagnostic. Full FAST and applicable
complete OPERATIONAL are reserved for the finalized one-hour/normal-operation
candidate or demonstrated broad risk. Focused success is not a release PASS.
Run 38652038787 completed without cancellation; local polling and watch loops
were stopped, with no replacement suite dispatched. The final handoff-only
publication does not change the executable or invalidate its scoped tests.
No runtime authority, deadline, safety control or strategy changed.

## Evidence and remaining single decision

Private run: `/var/lib/meme-machine-diagnostics/20261014-consolidated-startup-224020/`.
Persistent evidence root:
`/root/Documents/Codex/2026-10-10/the-meme-machine-eliminate-redundant-data/blocker-repair-20261011/`.
Original failures, metrics, journal, controller result and failed probes remain
unchanged. Reference, rather than recursively copy, these artifacts:

- `CONSOLIDATED_OBSERVATION_*_PREFLIGHT_20261014T*.json`, root gate and preparation;
- `CONSOLIDATED_OBSERVATION_JOURNAL_20261014T224020Z.log`;
- `CONSOLIDATED_OBSERVATION_PIPELINE_ANALYSIS_20261014T224948Z.json`;
- `CONSOLIDATED_OBSERVATION_POST_NATIVE_20261014T225954896402Z.json`;
- `CONSOLIDATED_OBSERVATION_20261014T224020Z_POST_FINANCIAL_RECONCILIATION.json`;
- `CONSOLIDATED_OBSERVATION_20261014T224020Z_USAGE.json` and Pons transport receipt;
- `CONSOLIDATED_OBSERVATION_ROLLBACK_20261014T224020Z.json`;
- follow-up RED, integration and final-affected logs; exact final CI receipt.

Independent blockers remain: complete native recovery/drain, sustained Pump
processing and the pre-join dependency, original SQLite BUSY attribution, Pons
managed account/method/freshness/held protection suitability, original READONLY
INSERT, later failed backup and active-backup/protection compatibility. No natural
SQLite recurrence occurred; that is not a repair. The closed historical-replay
search stays closed.

**Throughput branch: STOP — insufficient evidence for a justified throughput
correction.** The next runtime question, if separately authorized, is whether
the repaired current system completes native recovery and, after that boundary,
which measured transport-read/join/owner dependency accounts for continuing
pre-persistence lag. It needs current-generation per-stage timing, actual owner
executor scheduling and complete receipt/ACK/publication evidence; a generic
repeat or frontier-only comparison is insufficient. No additional observation
is requested or authorized by this handoff. Preserve original readiness,
protection, resource and shutdown bounds and recheck actual obligations before
any separately authorized operation. Acceptance remains **zero minutes**.
