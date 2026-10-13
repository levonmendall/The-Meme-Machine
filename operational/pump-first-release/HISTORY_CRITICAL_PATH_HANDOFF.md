# History separation: final critical-path refinements

**Engineering only. PAPER remains inactive, disabled and funding closed.**
No deployment, provider acquisition, hardware change, capital initialization or
acceptance was performed. Installed source remains
`ea4f4f1bfb12ef0d3ce01d4df70a93f6d37e7605`. The separate $1,000 epoch and
historical $500 root, usage counters, native histories and original safe-pause
handoff are preserved. Research remains suspended.

## Source and comparison baseline

Branch: `engineering/pump-history-separation-20261013`. The exact source and
publication receipt is `HISTORY_CRITICAL_PATH_PUBLICATION_20261013.json` in E
below. Resolve the implementation with `git log --oneline --all --
meme_machine/solana_economic_preparation.py`; documentation can advance later.

The unchanged published redesign is `dc957c521b6d043a9d4a1bca3c47127bc2f51abb`.
Its FAST CI ran 1,886 tests with one stale test-double error: the tiny Survivor
fixture lacked `calculation_facts`. The fixture-only successor
`c3c753c3bdf8bf6e3dd5c253e21799fb52e8d743` preserves every economic assertion
and passed **1,886 FAST tests** in CI run `38428869088`, finishing
2026-10-13 16:40:13 UTC. It is the incremental comparison baseline. The failed
run `38424684893` and its complete log remain retained.

The original redesign benchmark and its scope remain unchanged in
[HISTORY_SEPARATION_HANDOFF.md](HISTORY_SEPARATION_HANDOFF.md) and
`HISTORY_SEPARATION_FINAL_PROOF_20261013.json`. Do not add its percentages to
these additional results.

## Completed changes

- Preserve the existing historian, capture/deliver/acknowledge consumer, durable
  outbox, exact windows, reset reducer, coalescing and off-owner archives.
- Construct economic events, their canonical/normalized bytes, content hashes
  and census hashes **before** canonical-owner admission. Use compatible local
  prepared records. Continuity, current endpoint/session coordinates, bindings,
  conflicts, original availability, storage checks, writes and checkpoints stay
  on the owner. A preparation failure retains gaps and a safe diagnostic.
- Small unfunded packets use bounded source preparation and yield between
  frames. Large/protective packets use the existing decoder/archive pool and its
  existing 1-MiB boundary. One preparation batch is active. No additional pool,
  provider subscription or acquisition is introduced.
- Replace historical publication polling with committed-work notifications.
  Durable rows remain authority. Epochs prevent lost wakeups; fixed proof
  horizons drain fairly. Unchanged completed proof receipts are not recommitted.
  Actual SQLite contention retains an explicit retry wakeup. Startup always
  visits durable work. Accounting/reporting retain their independent 100-ms
  cadence and accounting-before-publication fence; diagnostics cannot wake
  their own publisher. Original maintenance and deadline timers remain.
- Coalesce short noncritical delivery batches within the original 100-ms
  cadence; full batches and canonical/protective work bypass that delay.
  Delivery remains one bounded thread/batch. Accepted consumer work drains on
  shutdown before canonical ACK; process death instead retains exact replay.
- Fix the configured candidate-history path boundary: environment strings are
  normalized to `Path` before capture, delivery and restart.

No strategy allocation, qualification, exit, holding duration, volume-quality
definition, freshness deadline, capital authority or Pons pacing changed.

## Incremental measurements and limitations

`engineering/solana_capacity/history_refinement_replay.py` compares the same
40,000 retained October 8 provider records through raw parse/join, canonical
owner, durable consumer and exact historical demands. It retains raw input
digests, source-file hashes, SQL counts, owner waits/CPU, preparation/transfer,
history completion, checkpoint update times, pending joins, group CPU/RSS and
urgent scheduling probes. It uses network guards and disposable Scratch.

The tape prefix completes only **three program slots / 287 economic records**.
Its replay prefix and incomplete tail are not fabricated complete. It is not a
current-market capacity, native quotation, Pons deadline or funding-readiness
proof. Economic bytes/order/availability, population, coverage, gaps, checkpoint
slot/receipt and history verdicts must match. Checkpoint `updated` is recorded
separately because actual publication timing legitimately changes.

Two existing decoder counts (one and two) were examined; no combination sweep
was performed. Always-process preparation increased transfer cost and did not
consistently improve complete-path latency. That approach is deferred for small
unfunded packets. Keep the existing two decoder/archive workers: the one-worker
trial did not include competing archive work and cannot justify removing that
capacity. One historian, one delivery batch and one preparation batch remain.

Do not claim an incremental whole-machine speedup or sufficient two-CPU capacity
from this small tape. Final paired measurements and source identities are in
`HISTORY_CRITICAL_PATH_IMPLEMENTATION_PROOF.json`; failed and intermediate
measurements in E are retained. No provider calls were avoided or purchased by
these offline runs; incremental dispatch/CU is zero. Required authenticated
capacity remains unmeasured after the redesign.

## Pons diagnostic integration, separately from repair

Diagnostic commit `f8d66ff2eee5214a85c180e4e37e25ddf6d6bae6` was cherry-picked
without replacing newer Pump work; integrated commit is
`4d45b368e7605b6bb4f25a121ec41162b4726472`. Its original handoff is at
`392b13fdaf1aebcf01e24ad707a5865061b7adf1:operational/pump-first-release/PONS_DEMAND_FAILURE_HANDOFF.md`.

Essential extended SQLite code/name, phase, requested path and process identity
are attached to the original exception **before** optional SQL/filesystem probes.
The traceback note is updated in place, and optional probe failure cannot erase
it. No successful-request scans, diagnostic database writes, retries or accounting
change were added. Nine focused tests passed, including the actual lane `main`
error-reporting boundary with a real disposable read-only SQLite connection;
73 affected Pons/provider regressions passed in a separate nonprofiling window.

The operating `2026-10-13T03:24:03Z` read-only INSERT fault is **unresolved**.
No new runtime window was authorized, so there is no new recurrence/nonrecurrence
claim. On recurrence, retain the note, correlate actual file/connection evidence,
and reproduce the supported mechanism offline before fixing it. Do not chmod,
reset the DB, delete sidecars, increase timeouts or assume a permissions cause.
Original Current five-second / Survivor three-second protection remains required.
Verified factory 40-block capability and unverified-filter fallback remain intact.

## Validation and operating blockers

Focused refinements, stale-source refusal, dedup/restart, commit-before-ACK,
consumer write contention, delayed historian, configured paths, lost wakeups,
idle/diagnostic behavior, preparation dispatch/failure and shutdown drainage are
covered by `tests/test_solana_history_refinement.py` and the preserved separation
tests. Final CI and relevant OPERATIONAL results are in the implementation proof.
One existing OPERATIONAL skip is archived Model A, **not** waived containment.

Exact implementation `e8f7d2ec8ccc0d530c94171390e1966d5c42a70f` passed Pump
offline CI (79 tests). Its full FAST run `38439291019` ran 1,907 tests and
failed three original Pons protection-capacity cases: real partial exits at
3 RPS, a modeled 3-RPS partial-exit turn, and mixed Current/Survivor native
exits. One real 20-position case expanded to 72 physical starts and exceeded
three seconds. The earlier passing baseline used six starts. The underlying
cause is not established; neither Pump replay nor nonrecurrence repairs it.

All three pass in two isolated local windows (78.594 / 78.527 seconds). Failure
prints now precede the original timing assertions and include the shared-exit
boundary/count so an unsuccessful variant cannot omit its necessary evidence.
No deadline, assertion, source economics, provider rate or accounting behavior
changed. The evidence-only successor `60ffa9cdcd7d0e2de257620fb3d8bc4e1b331c1f`
passed **1,907 FAST tests** in run `38446154537` (1,500.963 seconds), finishing
2026-10-13 18:47:36 UTC. This pass does not identify or repair the failed run's
root cause. Preserve both full logs and the failed runner locator
`/tmp/mm-engineering-ce1934e6`; do not infer a provider/permissions cause.

Separate blockers remain:

1. Current-market Pump throughput/freshness after this architecture is unmeasured.
2. Full concurrent Pons protection/controller readiness and the original demand
   INSERT fault are unresolved. Prior seven latency samples are component-only.
3. Off-host backup failed `ArtifactStorageFull`; recovery/storage needs resolution.
   Latest read-only root/volume check: 75% / 85%, 13 GiB / 7.2 GiB free.
4. Normal profile installation/reconciliation, funding admission, one-hour and
   longer autonomy acceptance require separate owner authority. Credited time: 0.

## Minimum later validation, deployment and rollback

Do not execute this sequence under the current authorization.

1. Confirm exact reviewed CI source, no changed live owners/pending obligations,
   retained $1,000 epoch/inception/policy, provider ledgers and volume identity.
   Resolve backup/storage and inspect the installed observation drop-in; it still
   carries a diagnostic timeout and must not be mistaken for continuous PAPER.
2. Separately authorize a single unfunded combined validation using existing
   feeds/credentials and pacing (Solana 2 RPS, previously validated Robinhood
   10 RPS). Proposed experiment envelope: 900 seconds, 1,200 physical starts
   including eight native openings, 1,800 logical elements, 150,000 conservative
   CU, 512 MiB accounted native and 128 MiB HTTP data, existing response/frame,
   queue/memory/disk bounds and zero signing/funding. Reconcile the exact method
   plan and frozen pricing with the owner before dispatch; these are proposed,
   not renewed authorization or continuous-operation limits.
3. Install only the exact source through the existing reconciled cutover, with
   `MM_SOLANA_HISTORY_SEPARATED=1`, existing volume/provider/capital identities,
   volume tracker and four intended regime configuration. Keep funding closed.
   Measure current frontier age, incoming/committed rates, backlog, oldest
   required history, CPU/RSS, maintenance, original protective deadlines and
   Pons diagnostic/exit/USD/recovery behavior together. Stop the experiment on
   a genuine evidence, protection, accounting or physical-capacity failure.
4. Preserve every failed counter/journal. Only after real prerequisites and
   explicit operating authority pass may normal PAPER and the real one-hour
   clock resume. Do not transfer diagnostic lifetimes into continuous operation.

Rollback: stop new admission, preserve actual obligations/protection, drain the
single consumer batch and owner, then use the known source and same epoch/root.
Do not start the old profile blindly. The existing flag rollback recovery drains
durable historical preparation jobs; canonical outbox ACK/proof publication and
original archive formats remain compatible. Never reset counters, restore old
$500 sizing, recreate the epoch or delete failed evidence.

E: `/root/Documents/Codex/2026-10-10/the-meme-machine-eliminate-redundant-data/blocker-repair-20261011`.

## Coordinated lifecycle/reporting integration

Receiving source: `60ffa9cdcd7d0e2de257620fb3d8bc4e1b331c1f`, with its full
FAST result preserved before integration. Package:
`9cdc1b5428f8ebf0bfcc6206cb8122b354654d9d`, branch
`implementation/ready-lifecycle-reporting-20261013`, base `e8f7d2ec`.
The four published commits are incorporated through a normal non-fast-forward
merge, preserving ancestry and all newer receiving changes. No merge conflict
occurred. Package handoff and component conventions are retained in
`READY_LIFECYCLE_REPORTING_HANDOFF.md` and `COMPONENT_PERFORMANCE_REPORTING.md`.

The original source guard correctly rejected the package's explicit approved
changes. Three previously protected files are now pinned byte-for-byte to the
published package, after verifying their exact prior source through the original
economic guard. A new regression rejects further edits and compares the original
reset predicate, entry/exit thresholds and policy. No file is broadly exempted;
all other strategy and nine-change guards remain unchanged. The initial failure
and final two passing guard cases are retained in E.

Combined correctness, recovery and performance verification remain pending on
the coherent merged candidate. The package's 235 distinct passing regressions
are prior package evidence, not combined-source validation. Missing legacy vector/
time joins and unavailable original/add detail remain unavailable. They do not
become blanket startup gates; decision-critical missing evidence still blocks
that decision. Pons database fault, storage/backup failure and authenticated
four-regime capacity remain separate unresolved operating blockers.

Operating authority remains offline-only. No deployment, provider acquisition,
PAPER restart, funding or acceptance is authorized by integration.
