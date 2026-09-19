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

Only neutral Solana evidence/cache state is shared. Environment construction removes
foreign lane variables and GitHub tokens. A certification-only SQLite governor
bounds combined physical requests conservatively at 2 RPS per network without
raising any original local limit. Position lifecycle hydration receives priority.
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
  work at 120 lifetime attempts. Its isolated lifecycle histories have no consolidated
  lane cash/reservation ledger. Replace bounded-study orchestration with continuous
  admission and durable accounting while preserving all three frozen modes.
- Meteora: runtime is capped at 7,200 seconds, discovery is one finite census, and
  attempt/complete targets can stop the process early. The v1.7 virtual position's
  final mark is not a durable allocation/unwind/settlement ledger. Persist entry,
  authenticated tape/position checkpoints, cost decomposition and terminal booking.
- Pons: each parallel trial initializes its own capital ledger. Before portfolio
  certification, enforce one lane-local atomic capital budget across trials, preserve
  partial-exit accounting, and expose capacity stops and lifecycle completion live.
- Ramses: the extended runner returns after its first natural lifecycle. Continue
  frontier discovery after settlement without restarting, reuse durable inventory,
  and reconcile separate quote assets without adding unlike units.
- All lanes: bind native accounting events and evidence to global lifecycle IDs;
  implement complete per-gate denominators, prospectively frozen research alternatives,
  and capacity reports with censoring distinguished from economic rejection.

No full capacity, strategy-performance, capital-hour profitability or natural
certification claim is supported yet. Raw failures must remain preserved.


## Repair integration follow-on (2026-09-19 UTC)

This branch is stacked on PR #66 at `3e0024c328365548e4bb4a9678b57bbb6dbec004`.
It does not replace that concurrent work or modify main. The source lane heads
remain unchanged; `sources.json` now distinguishes the original source SHA from
the exact **execution SHA** containing these prerequisite repairs:

| Lane | Execution SHA | Review |
|---|---|---|
| Pump | 2b2af01299ce99b0f036981bfad57107713c68b7 | PR #67 |
| Meteora | 6a3be3a2d3c3c45fb3068662a23800e2e3768933 | PR #64 |
| Pons | c96d9092f7645c0def4fb2c237477644280f7041 | PR #68 |
| Ramses | 3ec74dfa223d3eecae3c3d525ceb27bcdf63d5f6 | PR #69 |

Pump now enforces one lane-wide $500 genesis using an integer SQLite paper book.
Atomic reservations prevent parallel trials minting capital. The append-only journal
retains decision/entry evidence, fill basis, marks, exit/settlement and capital-time;
reopening independently replays booked flows and compares the mutable projection.
This does not yet establish full quote/cost/economic reconstruction certification.
The normal frozen policy source and hash are unchanged.

Pons no longer deletes prior trial databases or reports on repeated invocation;
it refuses reuse without explicit recovery. Completed futures are persisted while
discovery continues. Its trial ledgers still need a lane-wide atomic capital budget.
Ramses adds atomic progress checkpoints. Both repair branches also contain an
optional neutral endpoint admission gate for other concurrent callers; **this
integration uses PR #66's one network governor only**, so it does not stack two
extra admission gates.

The supervisor now checks actual four-process overlap, treats unknown exposure as
unproven, retains terminal reports, bounds and expires admission tickets, checks
unittest completion summaries, and records method/HTTP status/JSON-RPC error codes
without endpoint credentials. Source worktrees are clean exact execution commits,
not an uncontrolled merge or unreviewed runtime patch.

Latest preceding Meteora run 35474758564 completed its 20-minute observation:
19 attempts, zero complete; 12 fresh-swap timeouts, 3 regime expirations, 2 valid
zero-swap warmup rejections, 1 unverified warmup, 1 runtime deadline. These counts
come from job 105981977326's terminal log, not an inferred economic failure.
The artifact was enumerated, but its download was unavailable in this runtime.

The separate PR #66 smoke run `35476622573` was already running when this integration
was prepared. It must not be reported as validation of these newer execution SHAs.
The follow-on workflow uses the same concurrency group and never cancels that run.
No four-hour or natural E2E certificate exists yet. Continuous runners, complete
native accounting binding (especially Meteora and Pons), cost decomposition,
prospective shadow optimization, and complete capacity denominators remain blockers.


Follow-on local validation: Pump 241, Meteora 343, Pons 207, Ramses 230 tests;
all required resource checks passed. Eleven integration regressions also pass,
including expired/capacity-bound admission, unknown exposure, short overlap,
terminal report retention, and RPC error-code telemetry. Exact command/log hashes
and source identities are in `repair-integration-result.json`. This is a
prerequisite test result, not a live certification result.
