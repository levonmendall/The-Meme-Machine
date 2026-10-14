# Consolidated observation and offline follow-up — 2026-10-14

Executed source: `1fe5a6f62d37f84ad24f0b7413279c080e3424e5`.
Offline repair executable: `c8beb2d1317084779f97214b6015b7c345242085`, branch
`repair/consolidated-startup-followup-20261014`, based on owned integration head
`c1c3fd1662b1acbb917f57bfd0e578fc7a349bce` (includes workflow merge `893640f2`).
Review: [PR 133](https://github.com/levonmendall/The-Meme-Machine/pull/133).
Follow root `AGENTS.md` and the operational-resolution skill. No further live
start is authorized; this attempt consumed the single-start authorization.

## Observed result and safe state

Fresh preflight established the flat operating epoch, unchanged historical $500
accounting, durable native pending work, applicable prior recovery reference,
natural backup-free window, provider controls and actual service-user access.
Only the exact authorized source and temporary OBSERVATION configuration were
installed. Funding remained closed. No allocation, reservation or fill occurred.

Service start: **22:40:46 UTC**. First fatal marker: **22:44:41.616816 UTC**.
Controller completed drainage at **250.071 seconds** from its monotonic start.
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
operation had continued between completed history reads without a cancellation
check. No OOM, SQLite lock holder or historical BUSY mechanism is inferred.

Post-stop read-only monetary replay verified **8,982 journal events**, conservation,
cash **$1,000.00**, and zero positions, reservations, commitments, obligations or
pending monetary deliveries. Inception, capital policy and historical $500
accounting are unchanged. The 80 new journal actions were one admission, six
owner and 73 reporting publications; no economic entry action occurred.

Original 24 sampled canonical/history/proof identities remain present. The final
current 32-identity cohort has 21 authenticated receipt/exact ACK matches and 11
pending deliveries. The authenticated source checkpoint remains unreleased in
`WAIT_FOR_DURABLE_PUBLICATION`. These bounded checks preserve resumability; they
are not a complete native-recovery or coverage PASS.

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
- Already-dispatched complete FAST: see exact terminal result of
  [run 38652038787](https://github.com/levonmendall/The-Meme-Machine/actions/runs/38652038787)
  on `c8beb2d1`. The draft-PR skipped workflow is not a PASS.

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
Run 38652038787 was already useful and is allowed to finish; local polling and
watch loops were stopped, with no replacement suite dispatched. These subsequent
instruction/handoff-only edits do not change the executable or invalidate its
recorded tests. No runtime authority, deadline, safety control or strategy changed.

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
