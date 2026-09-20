# Acquisition blockers repaired — 2026-09-20

This continues engineering while original workflow 35483374004 remains pinned
to ebd03f5780eee46cc59f0338f48830e475480d78. It must not be patched or restarted.
The previously queued workflow 35485166791 was checked pending with no jobs;
its unstarted revision 0b996823162cb614b64b85fe36d4eb93e704fa20 is deliberately
superseded by this repair. Publication to cert/four-lane-capacity-v2 requests a
new clean smoke and four-hour run under the same concurrency group. This is a
replacement of unstarted work, not a process restart or spliced uptime window.

## Exact source and repair identities

The four canonical lane heads were independently checked and remain:
- Pump 361d90dbfd12226467ac458f92b16a9f0b017fce
- Meteora 45836b18c9afdda29909ebe9cb68d386a47b074f
- Pons 7ed22d3bdca3680869ef61b41f063389cb006366
- Ramses eebcb9136efa41db9a28f2ac95e4dddde0d17b15

Exact branch names, policy/config hashes, provider variable identities and all
prior repairs remain in sources.json. New lane repair heads:
- PR #83 Pump 7774ebe0f712a0e12848de1c54aaaf44df8480e7
- PR #84 Meteora 45041de0669c9f0db2dc27793ab2da2a77e72a25
- Existing PR #80 Pons 38d264c9dd878e2f70ffb461c18bd12ecdd7c1d6
- Existing PR #81 Ramses 325c6052056500146b88d1ad3e83bf5db5b9657a

The resulting exact integration SHA is this published commit (recorded in the
workflow and every certification result). Main remains unmerged. PAPER ONLY.

## Diagnosed from retained live evidence, then reproduced

Read-only review 35485976103 / job 106012306470 inspected original artifact
10597391938, SHA-256
977e69aed5b94f092cd894c827b34208ae9020474ac6aa5d792d2d2caef91c92.
Full extracted failure detail is retained in
results/smoke-35483374004-acquisition-diagnosis.json.

Pump had 6,238 expired window jobs and 959 completed background-history jobs;
only two complete strategy vectors. The decoder renewed its six-second budget
for each chunk. Older history still ran while the current window was incomplete.
Initial stream misses remained marked missing even when bootstrap completed the
same immutable body. Five pre-repair failures were reproduced; the repair adds
six regression tests including cross-process lease protection.

Meteora reached an authenticated fresh swap in four of eight attempts. Each
triggered warmup's initial census fetched 16 pages / 1,024 rows despite a lower
boundary witness on page one. Three then failed transaction hydration; the fourth
hit the campaign runtime deadline. Cold-start overfetch is now one page for that
same deterministic interval. Warm incremental acquisition must prove the entire
bridge to its cached head. Missing coverage, boundary, cardinality or transaction
index cannot publish an updated head; the next retry cannot skip the missing gap.
The four no-wakeup trigger timeouts remain evidence of observed inactivity, not
manufactured trade opportunities or proven strategy losses.

## What changes

- One Pump decoder deadline across chunks; deferred background second-leg work
  while the exact current decision window is incomplete.
- Reconcile captured stream misses using immutable cached bodies, without RPC.
- Shared time-sensitive jobs ordered by deadline; positions retain first priority,
  research retains last priority. Pending expired jobs can be re-requested without
  wasting a refresh. Active leases are never cleared by a duplicate request.
- Meteora cold census stops at the authenticated boundary. Warm pagination
  exhaustion explicitly fails, and staged evidence publishes only after checks.
- Meteora timing now instruments the actual triggered warmup, trigger, census,
  and reconstruction functions. The old instrumentation wrapped an inactive path.
- Pump capacity reporting includes postgraduation and second-leg acquisition
  censoring instead of omitting those failures from the incomplete denominator.

The shared EvidenceBroker class is identical across the two Solana worktrees:
SHA-256 3ea197cb8813dc2307b2fbf640ca2ff33208e92b8c4b121a72d8eaef0b272591.
Lane-specific stream classes retain their existing semantics. All frozen Pump
modes, exact 30-second decision window, three-attempt bootstrap, Meteora v1.7
warmup/size/range/hurdle, unsupported-economics rejection, Pons five-second clock,
and Ramses finality/hold policy remain unchanged. No rate ceiling increases.

## Validation and next execution

Reproduction commands:
```
python -m unittest discover -s certification/tests -v
python -m certification.run prepare --worktrees /new/pinned-worktrees
python -m certification.run verify --worktrees /new/pinned-worktrees --output /new/gates
```
29 supervisor/research/control tests; Pump 251; Meteora 356; Pons 222; Ramses 238:
1,096 tests pass, plus all three Solana resource gates. Machine result:
results/acquisition-combined-deterministic.json. A local Ramses log-copy/hash
mismatch was preserved and independently rerun; final selected log hashes were
all verified. Hosted execution repeats all gates against its exact published SHA.

The updated PR #82 workflow runs a new 600-second concurrent smoke, then a new
14400-second continuous campaign only after that smoke passes. It waits behind
any current campaign and never restarts lane processes. All raw success/failure
telemetry and native ledgers are retained. Current frozen-run artifacts remain
separate from repaired-run evidence.

Remaining questions: measure Pump complete-window throughput and position
responsiveness; verify Meteora reaches full reconstruction and economic gates;
measure the live Pons batching deadline gain; verify Ramses funding on quiet
startup then natural Fee Pulse qualification. No live improvement, natural
settlement, after-cost edge or full certification is claimed by these tests.
