# Current-state repair after Cycle 4

The user's latest instruction is **handoff only; do not start validation**.
The repeating overnight launcher remains paused. No smoke or hourly validation
has started for this repair. A shell push attempted before that instruction
failed authentication, leaving the remote campaign branch unchanged. This repair
is published on a separate review branch with no live-launch marker.
Do not start any live validation, recurring tests, old runs or Frozen Wallet Study.
No live money, signing, submission or allocation authority.

## Terminal baseline

Cycle 4: run 35508695288, integration
`6964cfe5c501075e53f3f6f809b85bbdeb50a7cc`, terminal 2026-09-20T13:33:42Z.
Artifact 10605823461 (298120957 bytes) SHA256
`653ba9aaf63e591b7e6691a8b258103d527de9764b5aca722b15f18f5a564aaa`.
Downloaded bytes were verified; raw archive, native books and completed job log
were inspected. Machine-readable review: `results/hourly-review-35508695288.json`.
All lanes: zero restarts, reconciled, zero open, natural/forced settled 0/0;
3600.158276704 uninterrupted seconds. Legacy execution-integrity PASS; natural
certification INCOMPLETE and several stronger capacity/replay controls unproven.

| Lane | Corrected terminal denominator / completion | Demonstrated blocker |
|---|---|---|
| Pump | 1138 discovered; 235 complete attempts; 0 qualifiers | 54 second-leg history failures; logical consumers were misread as unique opportunities |
| Meteora | 559 discovered; 99 screened; 52 attempts; **2 economic vectors** | Surface incorrectly counted lifecycles; 36 trigger timeouts, 6 expired regimes, 5 zero warmups, 2 unverified reconstructions, 1 deadline |
| Pons | 1189 evaluated; 836 vectors; 498 distinct complete stale observations; 131 authentication stale failures | Timing not decomposed; repeated block-scoped evidence; nomination denominator unmeasured |
| Ramses | **10** completed pinned finalized scans over 5 active pools | Observer overwrote full native checkpoint with partial gate/scan dictionaries; condition D, not a proven hour-long scanner block |

Pons stale classes overlap economic reason counts; do not sum rejection reasons.
Meteora mint-info mismatch and unsupported liquidity shape remain fail-closed;
two valid economic vectors were rejected on frozen economics. No transaction
shape support was invented to turn those censored observations into qualifiers.

## Exact source and policy preservation

All four remote lane heads and the integration head were fetched/reverified before
changes. Exact source SHAs and policy/config/workflow file hashes remain in
`sources.json`, unchanged. Changes are composed as the same four normalized
operational overlays. `source_integrity` now also rechecks frozen source-file
hashes after applying overlays, at verification and at terminal shutdown.

## Repairs

- Lane-local append-only opportunity journals preserve candidate identity, stage,
  classification, timing and policy hash. Unique candidate sets are independent of
  logical consumer counts; one candidate may appear in multiple classes. Pump
  scope is mint, Meteora/Ramses scope is pool, Pons scope is transaction/log index.
  Repeated pool observations are not asserted to be independent opportunities.
- Solana consumers carry lane, owner, candidate/pool, immutable original deadline,
  admission and first transport time. Existing append-only terminals are retained.
  Failures have append-only attempt records; local and explicitly shared totals
  are separate. Migration is serialized across processes. Foreground waiting work
  suspends speculative stream batches; physical admission is bounded by the
  existing acquisition deadline. Position priority remains highest.
- Pump keeps the exact bounded bootstrap, 30-second window, stream-first reuse and
  second-leg history requirements. Stable research owners remove one further
  redundant registration source. Explicit failures retain the actual history
  status. Null transactions remain unresolved unless the provider supplies a
  version/error classification: absence or propagation is not invented.
- Meteora publishes compatibility, trigger, warmup, reconstruction, prospective
  range, economic-vector, deployment/unwind and terminal stages. Authenticated
  trigger identities receive terminal classification, including superseded
  prestate and unresolved shutdown states. Economic vectors and lifecycles are
  counted independently.
- Pons reuses exact pinned-block reads by block hash, never gasPrice/latest reads;
  adjacent candidates' headers use spare slots in an already-needed batch and
  still undergo normal identity authentication. Original deadline bounds shared
  admission. Timing separates queue, local pacing, shared provider admission,
  transport, combined header/receipt/state-cost batch, factory metadata,
  trajectory, window authentication and final decision age. A combined batch
  cannot honestly have independent non-overlapping RPC durations. Complete stale
  vectors are separate from incomplete stale acquisition.
- Robinhood admission recognizes Pons nomination work as urgent. Research waiting
  three seconds advances ahead of new candidates while position exits remain
  first. Append-only grant/wait records permit interval-based starvation review;
  endpoint ceilings and cooldowns are unchanged. No new provider is justified yet.
- Ramses retains full native checkpoints; pinned frontier, gate reason, scan
  stage/progress and asset-separated accounting remain visible during scans.
  No pool or census was removed. Existing synchronous scanner semantics remain;
  progress callbacks expose each stage rather than substituting a new algorithm.
- Process responsiveness and strategy-pipeline progress are separate. A pending
  stage with no progress for 300 seconds is flagged, never automatically restarted.
  An unchanged finalized frontier is a waiting state, not a machinery stall.

## Validation and remaining proof

Local full stack: 1105 lane tests (Pump264, Meteora369, Pons231, Ramses241),
46 supervisor tests and three existing resource gates. Logs and JSON gate hashes
are preserved under `results/current-state-repair-tests.json` after final review.
Intermediate regressions are recorded there; none was removed or weakened.
Hosted workflow must rerun full exact-revision gates and contention guard before
smoke. Hourly launch must consume readiness from that exact revision's smoke.

Commands:
```
python -m unittest discover -s certification/tests -v
python -m certification.run prepare --worktrees <isolated-directory>
python -m certification.run verify --worktrees <isolated-directory> --output <gate-directory>
```
Live validation is withheld by the latest user instruction. The existing path
would require exact-revision gates, no competing market workflow and clean
600-second smoke before an independent hour. No readiness was created or reused.
A future launch requires renewed user authorization; do not add a launch marker.

Remaining empirical questions: Pump full-window coverage under real load; Meteora
replay-compatible activity frequency; Pons stale fraction at comparable evaluated
throughput; Ramses live completed scan/accounting publication and grant fairness.
Lifecycle counters still require actual cost-complete durable settlement. An
engineering result does not prove natural strategy execution or profitability.
