# Four-lane certification handoff

Status: implementation and deterministic prerequisites advanced; **not sustained-certified**.
No four-hour run or natural end-to-end certification has completed in this work.

## Verified sources

The exact remote heads independently read with `git ls-remote`, and rechecked during
implementation, are in `sources.json`. Main is not an implementation source.

| Lane | Source SHA | Frozen policy hash |
|---|---|---|
| Pump | 361d90dbfd12226467ac458f92b16a9f0b017fce | b273bc6be47d4f5a65f39d5d4f616777e02cbe547e19b7a07b0fefe23970c246 |
| Meteora | 45836b18c9afdda29909ebe9cb68d386a47b074f | 171605162c857d90ef7f880fc7f444dff615e452659e78a2f38fd563acfb6ad5 |
| Pons | 7ed22d3bdca3680869ef61b41f063389cb006366 | eeebfeb8329e602d0291c4da9747eda82706daab06706e3b9cef74053050cb81 |
| Ramses | eebcb9136efa41db9a28f2ac95e4dddde0d17b15 | 3b9e02439b32e6857aed86c47ff4c00c227e3ff502b9da70ea55a73abfcdc78a |

The Meteora overlay is exactly PR #64, commit
`6a3be3a2d3c3c45fb3068662a23800e2e3768933`, against its verified source.
This concurrent repair was published while the same defect was being independently
reproduced here. Duplicate PR #65 was closed without merge; its alternate repair and
additional changed-extension negative regression remain preserved on its branch.
No strategy source, policy, freshness/finality rule or recent transport repair is replaced.

Every runtime manifest records the actual integration HEAD, source manifest hash,
reviewed overlay hash, provider configuration fingerprints, run ID and policy hashes.
A commit cannot embed its own SHA; read the runtime manifest or `git rev-parse HEAD`.

## Demonstrated prerequisite repair

The full current Meteora suite failed 4/343 tests: tuple/list inequality after durable
JSON restore caused three replay errors, and one test mocked a removed candle API.
PR #64 normalizes authenticated state metadata before persistence. All 343 tests and
both resource checks pass with that overlay. The independently developed alternate
repair passed 344 tests, including a tampered-extension negative regression.

The pinned-source verification command passed:

- Pump: 236 unit/integration tests and its resource check.
- Meteora with PR #64: 343 tests and both resource checks (including 6,001 synthetic
  DLMM events, settlement and conservation).
- Pons: 205 tests.
- Ramses: 228 tests.
- Certification primitives: 9 tests covering exact integer replay, partial exits,
  recycled capital, double settlement, incomplete costs, namespace isolation,
  append-only journals, false-PASS rejection and actual cross-process pacing.

These are deterministic results, not natural market outcomes.

## Implemented execution path

The supervisor prepares four separate pinned worktrees, validates policy/config
hashes and the exact source overlay, runs the full source suites, launches one
process per lane, and records each process launch/exit. No restart loop exists.
A process returning early or failing is retained as an unexpected exit.

The lane worker calls the original entrypoint once. Observation wrappers preserve
return values and exceptions. Public RPC requests/responses go to compressed durable
archives; lane checkpoints and transport measurements go to a chained append-only
SQLite journal. Heartbeats come from lane progress callbacks, never a timer that
would hide a hung lane. Raw transport data is explicitly labelled as requiring
lane authentication; capture is not an authentication claim.

Only neutral evidence/cache/provider state is shared. Environment construction removes
foreign lane variables and GitHub tokens. A certification-only SQLite governor
bounds combined Solana physical requests conservatively at 2 RPS; Robinhood
uses a shared 2 RPS endpoint gate without raising any original local limit. Position lifecycle hydration receives priority.
Existing lane-specific backoff, session recovery and cursor logic remain intact.

The HTML status view reads the same JSON result; unknown controls remain unproven.
The integer accounting replay primitive exists and is tested, but **is not a
substitute for wiring and verifying each lane's complete native accounting trail**.
The result evaluator deliberately cannot infer missing fees, cash or settlement.

## Commands

```sh
python -m unittest certification.tests.test_certification -v
python -m certification.run prepare --worktrees /tmp/mm-cert-worktrees
python -m certification.run verify --worktrees /tmp/mm-cert-worktrees --output /tmp/mm-cert-gates
python -m certification.run run --worktrees /tmp/mm-cert-worktrees --output /tmp/mm-cert-smoke --gate /tmp/mm-cert-gates/deterministic.json --phase smoke --seconds 600
python -m certification.run run --worktrees /tmp/mm-cert-worktrees --output /tmp/mm-cert-sustained --gate /tmp/mm-cert-gates/deterministic.json --phase sustained --seconds 14400
```

The sustained command currently writes a machine-readable BLOCKED result describing
source-level prerequisites. It must not pad bounded studies with idle time, restart
them, or call a sum of short studies continuous certification. The smoke workflow
uses existing repository secrets only, first rejects concurrent legacy market jobs
and changed lane heads, and always uploads evidence. No paid service or deployment.

## Latest preceding market evidence

`initial-run-evidence.json` preserves the initial remote workflow snapshot and the
Meteora failing-job identity. Some jobs were in progress when fetched; that snapshot
is not their final state.

Ramses run `35474731258`, job `105981903159`, subsequently completed: four authentic
frontier-triggered screens, one active pool, no natural qualifier, 73 frontier polls,
three advances, 69 duplicate-frontier scans avoided, forced machinery settled.
It is a machinery proof, not a natural Fee Pulse lifecycle.

## Remaining blockers and next repairs

- Pump: the original runner clamps discovery to 3,300 seconds and stops full-evidence
  work at 120 lifetime attempts. The lane-wide paper book from #67 is integrated. Replace bounded-study
  orchestration with continuous admission and complete cost/economic replay while
  preserving all three frozen modes.
- Meteora: runtime is capped at 7,200 seconds, discovery is one finite census, and
  attempt/complete targets can stop the process early. The v1.7 virtual position's
  final mark is not a durable allocation/unwind/settlement ledger. Persist entry,
  authenticated tape/position checkpoints, cost decomposition and terminal booking.
- Pons: the shared cohort budget from #70 is integrated. Add unresolved-trial
  recovery and accurate partial-exit capital time; preserve trial-specific accounting
  and expose capacity stops and lifecycle completion live.
- Ramses: the extended runner returns after its first natural lifecycle. Continue
  frontier discovery after settlement without restarting, reuse durable inventory,
  and reconcile separate quote assets without adding unlike units.
- All lanes: bind native accounting events and evidence to global lifecycle IDs;
  implement complete per-gate denominators, prospectively frozen research alternatives,
  and capacity reports with censoring distinguished from economic rejection.

No full capacity, strategy-performance, capital-hour profitability or natural
certification claim is supported yet. Raw failures must remain preserved.


## PR #71 integration checks incorporated

The checks in `d9dc1abf55cb2ab37a6181567f616535659dc9a1` are included:
actual four-process overlap, unknown exposure, bounded/expired admission tickets,
terminal report retention, unittest completion summaries, stable session identities,
and method/HTTP/JSON-RPC error telemetry. Its prerequisite result is preserved in
`repair-integration-result.json` as a historical result for that exact revision.

This revision uses original source SHAs plus exact reviewed patches, including the
explicit composition of Pons #68 and #70. It does not use PR #71's execution-SHA
arrangement or its single-network Robinhood governor. One shared source-level
endpoint admission gate serves Robinhood, and the observer does not double-queue it.

## Integration update: newer concurrent repairs

The next overlay set also includes PR #67 (Pump paper book, 241 tests), PR #68
(Pons provider admission and completed-future checkpoints), PR #69 (Ramses admission
and progress, 230 tests), and PR #70 (one Pons cohort capital budget).
Pons #68 and #70 are combined explicitly: keep #68's prior-run rejection/recovery
reason and completed-future collection, add the capital-guard file to protected
artifacts, and pass the guard to every lifecycle. The combined full suite passes
211 tests. Exact repair commits are in `sources.json`.

Both Robinhood lanes use the identical source-level neutral admission module from
#68/#69, with one shared DB and separate lane names. The observer's fallback governor
is disabled for Robinhood when this source-level gate is configured, avoiding duplicate
queueing. Solana still shares its original evidence broker and the conservative
certification transport governor. Raw RPC responses are fsynced before their journal
reference is committed.

The first hosted harness attempt `35476508893` failed before any market access on a
cross-process queue-cleanup assertion. Explicit connection closure and fresh spawned
test processes repaired that gate. The corrected attempt `35476622573` passed all
hosted deterministic/resource/preflight gates and entered concurrent live-paper smoke
at integration SHA `3e0024c328365548e4bb4a9678b57bbb6dbec004`.
That run uses the previous overlay set; later repairs are not applied to an active run.
No four-hour window has been started or claimed.

The Pons shared-budget prerequisite above is now implemented by #70. Remaining Pons
work is explicit unresolved-trial recovery, capital-time treatment of partial exits,
and complete cost/replay reporting, plus continuous admission without an early cohort
stop. Pump's lane-wide paper book is implemented by #67; duration/capacity orchestration
and full cost decomposition/economic replay remain incomplete.

Current descriptive reporting preserves missing measurements as null. It distinguishes physical transport from admission failure and measures each lane over its own actual uptime. Shared Robinhood pressure is read incrementally without re-reading the whole transport journal on every refresh.

PR #70 follow-up `40bc4c4d1fb81900645fcbce109b4be0341320aa` reconstructs the complete reservation journal before trusting the mutable projection. A missing reservation projection now fails closed rather than releasing capital. Native Pons tests: 209; with #68 composed: 211.

## First completed concurrent smoke and repair

Run `35476622573`, certification ID `e9d8c94b-99f0-421a-a8fe-28065fb6e19f`,
ran from 2026-09-19 23:39:08 UTC through 2026-09-20 00:05:55 UTC, without a
process restart. It FAILED because the certification wrapper used Pons's 4 MB
checkpoint writer for its native 12 MB final report. Pons terminated after 671
seconds with `selective_checkpoint_capacity`. This is an integration defect, not
an economic rejection or failed provider recovery. The wrapper now honors the
native 12 MB terminal bound, writes atomically, and has a >4 MB regression test.
The original 4 MB checkpoint bound remains intact.

| Lane | Observed uptime seconds | Funnel | Natural / forced settled |
|---|---:|---|---:|
| Pump | 1606.56 | 545 discovered, 14 full evidence, 0 qualified | 0 / 0 |
| Meteora | 601.08 | 71 discovered, 11 screened, 0 completed | 0 / 0 |
| Pons | 671.01 | 156 evaluated, 0 qualified | 0 / 0 |
| Ramses | 753.12 | 2 active pools, 2 screens | 0 / 1 |

The original result, timestamps, exact integration SHA, artifact digest and diagnosis
are in `results/smoke-35476622573.json`. Artifact `10594448071` retains the raw
journals and logs. Read-only review workflow `35477969230` retrieved its contents
without making market requests. The original observer did not retain final status
reports reliably or distinguish HTTP errors completely; these limitations prevent
retroactive certification claims and are corrected for the next run.

PR #72 (`1b04eca2984f85c9a47d262dc7ea84796a21754e`) now adds Meteora's native
durable integer journal, actual capital-time, unresolved exposure retention,
fee/inventory/unwind/network decomposition, and deterministic economic replay.
It starts an explicitly recorded 1 SOL paper account, keeping the strategy's
0.1 SOL deployment and all policy thresholds unchanged. Tests: 347 plus both
resource gates; all four new accounting lifecycle regressions pass. Full chain
reauthentication and continuous discovery remain separate unfinished prerequisites.

The first smoke also overlapped external live-diagnostic job `105986654094` in mixed CI workflow `35476545177`. Preflight previously checked selected workflow names only. It now inspects active jobs and fails closed on unrecognized activity. The smoke throughput is descriptive under external contention, not a sustainable-capacity benchmark. The older #71 smoke `35476889114` was already running at discovery; it is not changed in place.

PR #73 (`b3ec5aaca230f2aa9c0e894c9912722a56f2eef1`) repairs Ramses reservations after realized losses and concurrent reservations, adds append-only journal protection and full projection comparison. All three regressions fail on the original source and pass on the repair; 233 full lane tests pass. This prerequisite is added to the next queued smoke, never patched into a running process.

## Continuous-operation update (2026-09-20 00:50 UTC)

Source heads were rechecked and remain exactly those in the manifest. The current
replacement smoke is run `35478805316`, job `105993725328`, at
`2ce75052dcb3ee029ee0643fc0595fb8bebfacf6`. It passed all deterministic and
contention gates and is still running; its outcome is not assumed.

The preceding PR #71 smoke `35476889114` ended with a Pons unexpected exit. Its
artifact `10595461557` (SHA256
`752c074a3be457b48d750feaac7da1914a5006cdc3d34d50840a99f9d0192cf7`)
is retained. A read-only artifact review is queued; no running market process is
modified or restarted.

Pons observer checkpoints now journal each completed candidate exactly once rather
than repeatedly copying the entire growing cohort. Native full observations remain
fsynced. Provider activity updates distinguish actual completed transports (including
explicit failures) from evidence qualification. Ramses natural settlement reporting
uses its actual `ledger_final` and segment reconciliation fields and excludes forced
proofs. All 16 supervisor tests pass.

Meteora continuous campaign PR #74 (`957ff70af2065c7bf0227f00a7fab0f44e0f81f0`)
is separately reviewable on top of #72: 350 tests and both resource gates pass. It
keeps one process/book/broker alive, admits only new first sightings from bounded
censuses, applies the same attempt capacity per 20 minutes, and preserves normal
policy exits. It is not yet part of the running smoke. Pump scheduling/stream
retirement work is under deterministic validation on `repair/pump-continuous-campaign`.

Four-hour certification, complete natural lifecycles, prospective shadow alternatives,
and final lane accounting/capacity controls remain incomplete.

## Continuous campaign integration (2026-09-20 01:09 UTC)

Smoke `35478805316` completed with zero restarts/unexpected exits and 600.519 seconds
of actual four-process overlap. Total drain-inclusive elapsed time was 1,626.556
seconds. It is INCOMPLETE, not a four-hour certification. Pump retained 49 complete
vectors from 517 discovered mints, Pons evaluated 213 candidates, and Meteora
screened 20 of 100 discovered pools. No natural settlement was established. Both
provider queues drained; shared Robinhood maximum observed queue depth was 2, with
1,276 HTTP 200 transports, no retries and no RPC errors. The Solana governor recorded
2,637 grants and zero rate errors. Exact per-lane evidence is in
`results/smoke-35478805316.json` and artifact `10595876501`.

The source/native terminal Ramses report is being read separately because the old
supervisor could overwrite its final summary with stale progress while Pump drained.
The retained native report is not erased. This integration prevents that overwrite
and has a regression for it. The older PR #71 artifact review confirmed the already
repaired Pons 4 MB checkpoint-helper misuse as its unexpected exit.

The next smoke uses these exact additional reviewed overlays:

- Pump #75: `6377b4c46da95c4591848939c714f7766e789acd` — explicit continuous
  duration, unchanged full-evidence capacity per rolling interval, acknowledged
  retirement of expired subscriptions, and position monitoring before hydration.
- Meteora #74: `957ff70af2065c7bf0227f00a7fab0f44e0f81f0` — repeated bounded
  census of new first sightings, unchanged rolling attempt capacity, one book and
  broker, normal frozen position drain.
- Pons #76: `3378ecc3e7a130e8dcd1fa1ef88105235875c6b1` — one initialized
  cohort budget, continuous discovery, durable queue terminal reasons, complete
  compressed reports behind bounded views, and admitted-position drain on failure.
- Ramses #77: `a88d2c07daa3c3f0c77e0b78362fe269bbdeca4a` — continued
  frontier discovery after settlement, one prospectively frozen budget per quote
  asset from the initial pinned screen, no replenishment or cross-asset sums.

Validation: Pump 245 tests/resource gate; Meteora 350 tests/both resource gates;
Pons 215 tests; Ramses 236 tests. All passed in the combined worktrees. The supervisor
suite now has 19 tests including lossless evidence-work timing and terminal-report
retention. Operational configuration hashes are separate from unchanged policy
hashes. Full source SHA + overlay hashes remain in the runtime manifest.

The next workflow invokes `--campaign` for each worker, retains the full native
archives and asset ledgers, and gives normal positions up to 3,300 seconds to drain
(including Ramses' unchanged 1,800-second hold and slow finalized-frontier allowance).
The four-hour command is still blocked pending this refreshed concurrent smoke and
remaining accounting/replay controls. No four-hour observation has begun.

## Refreshed smoke and Pons partial accounting (2026-09-20 02:03 UTC)

Workflow 35480694517 / run 7389409f-708f-4a81-8ec6-c498c20294f7 completed
600.161 seconds of four-process overlap at integration
0ffe8ffc52e29890e9e68443888ade6c2e07b6e6. All four exited normally, zero
restarts, accounting reconciled, no open positions, and zero natural qualifiers.
Pump: 516 discovered / 62 complete; Meteora: 88 discovered / 20 screened;
Pons: 192 evaluated; Ramses: 3 scans / 3 active pools. Solana governor recorded
854 grants and 2 rate errors; Robinhood recorded 1,315 HTTP 200 requests, zero
retries, maximum queue depth 2. Both final provider queues were empty. This is
INCOMPLETE certification, not a four-hour or natural-execution PASS.
The machine result and artifact identity/digest are in results/smoke-35480694517.json.

The preceding smoke's native Ramses artifact confirms one forced machinery
settlement with exact reconciliation. It used placeholder execution costs, is
explicitly strategy-ineligible, and proves neither natural qualification nor
profitability. The correction is stored separately beside the untouched original
supervisor result in results/smoke-35478805316-ramses-native-review.json.

Pons PR #78 / 44355aaac41a06a80f306f4458bbf200b118f179 adds immutable
quote/mark evidence, native partial cash and cost-basis replay, event-time
capital-at-risk integrals, globally unique lifecycle IDs, and a post-commit
cohort observer. Reservations still release only at full settlement. Missing
observer updates prevent consolidated cash reconciliation claims. All 220
Robinhood tests and 20 supervisor tests pass. Five new accounting regressions
cover partial/recycled capital, journal/projection damage, marks, clock rollback,
and the native-commit/observer crash window. Policy hashes remain unchanged.

The updated overlay still requires a fresh concurrent smoke before the four-hour
run. Final shared-broker evidence is being inspected without market access.
Unproven final certification controls remain explicit and cannot become PASS
merely because processes stay alive or deterministic tests pass.

## Gated sustained campaign workflow (2026-09-20 02:11 UTC)

The final shared-database review is retained in
results/smoke-35480694517-shared-database-review.json. It verified the artifact
digest, empty physical provider queues, 1,976 completed evidence jobs, 4,966
expired jobs (4,768 priority 20), and eight pending priority-90 research jobs.
These are explicit evidence censoring/capacity observations, not strategy losses.
The next supervisor records every unfinished job with a shutdown reason without
editing its original broker record. Thirty-second durable samples retain shared
queue/pressure/health histories for boundedness and starvation review.

Full native suites/resource gates pass on the #78 overlay: Pump 245, Meteora 350,
Pons 220, Ramses 236. Supervisor/control suite: 23 tests pass. New controls verify
every raw transport hash against the append-only journal and the final process
policy identity; they reject missing records, mixed lane state and process nonce
changes. Native source integrity is checked again after the run. No signing or
submission method is permitted to count as paper-only evidence.

Workflow `.github/workflows/four-lane-certification.yml` now has separate smoke
(75-minute bound) and sustained (330-minute bound) jobs. The sustained job uses
fresh worktrees/books and accepts only a clean ten-minute engineering smoke from
the exact same integration/source/implementation hashes. It never restarts a lane
inside a window. The small readiness handoff includes the full smoke-result hash;
full native evidence is retained in the preceding artifact. Separate jobs preserve
the full policy-defined drain allowance without GitHub's job duration limit
truncating the four-hour window. Per-asset Ramses campaign books are explicitly
archived alongside the other native paper records.

Reproduction: `python -m unittest discover -s certification/tests -v`;
`python -m certification.run prepare --worktrees /new/isolated/worktrees`;
`python -m certification.run verify --worktrees /new/isolated/worktrees --output gates`;
`python -m certification.guard`; then `python -m certification.run run
--worktrees /new/isolated/worktrees --output smoke --gate gates/deterministic.json
--phase smoke --seconds 600`. For the fresh sustained worktrees, repeat prepare,
verify and guard, then run with `--phase sustained --seconds 14400
--smoke-result smoke/result.json` and distinct output. Existing authorized RPC
secrets are supplied only inside Actions; no secret values are persisted.

The commit marker `[four-lane-sustained]` schedules the two-stage workflow.
Engineering smoke PASS is explicitly separate from full certification PASS.
No-starvation, durable economic replay and detailed capacity controls remain
unproven until supported by the retained campaign evidence; the final evaluator
keeps missing evidence INCOMPLETE. Natural outcomes remain zero in completed
runs. The four-hour run is requested by this revision, not claimed completed.
