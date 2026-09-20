# Repaired monitored replacement campaign — 2026-09-20

User explicitly requested cancellation of other tests and a repaired replacement
that can be followed while running. No interrupted uptime is carried forward.

## Superseded runs

- 35483374004, ebd03f5780eee46cc59f0338f48830e475480d78: cancelled
  at the user's request. The sustained stage started 02:42:32 UTC and was
  interrupted around 03:45 UTC; it is NOT four-hour certification.
- 35486770334, ce734284ae458a8187316e9570688140ada6b390: cancelled while
  pending before any lane launched, to add remotely readable live status.
- Cancellation workflow 35487362186 succeeded. Its exact allowlist and SHA checks
  are committed on cert/cancel-superseded-20260920 at
  403f1a76b1c8c9e466128e39127f5a8143ecf752. It cancels only those two runs.
- The interrupted sustained evidence was preserved: artifact 10598610814,
  225225725 bytes, SHA256
  a75b391bee3d3ddacd1d11a6a07b41e588c1e88f560a98628262e1ea261bfc8f.
  Smoke artifact 10597391938 remains intact. Interrupted exposure must be reviewed;
  cancellation is not settlement or economic certification.

## Replacement

Base repaired integration is ce734284ae458a8187316e9570688140ada6b390 (PR82),
including PR80/81/83/84. Exact source heads and policy hashes remain in sources.json;
all four heads and main were independently rechecked at 03:47 UTC without drift.
Full combined lane gates had passed 1,067 tests plus 29 supervisor/research tests.
The live publisher adds four tests; all hosted suites run again at the new SHA.

The workflow retains full deterministic gates, 600 seconds of concurrent smoke,
and only on a clean exact-revision smoke, a new 14,400-second sustained window.
Each phase may use the existing normal strategy drain. No automatic lane restart.
The permanent concurrency group still has cancel-in-progress: false.

The phase command is now wrapped by:

    python -m certification.live_status --output certification-smoke --phase smoke -- python -m certification.run run --worktrees "$RUNNER_TEMP/four-lane-worktrees" --output certification-smoke --gate certification-gates/deterministic.json --phase smoke --seconds 600

The sustained phase uses certification-sustained, phase sustained, seconds 14400,
and --smoke-result smoke-readiness.json. Market processes and policies are unchanged.

## Live observation

Dedicated check names: four-lane-live-smoke and four-lane-live-sustained.
Read GET /repos/levonmendall/The-Meme-Machine/commits/INTEGRATION_SHA/check-runs
with filter=all and pagination, then GET /check-runs/CHECK_ID. Match external_id
WORKFLOW_RUN_ID:ATTEMPT:PHASE. output.text contains four-lane-live-v1 JSON.

A separate publisher posts a bounded aggregate snapshot every 60 seconds, retaining
local publisher JSONL and all raw native artifacts. Only checks:write is added;
no signing, contents-write, or market authority is added. The GitHub publication
credential is removed before launching the supervisor and all lane environments
already filter GitHub credentials. Provider URLs/raw bodies are never published.
Publication API initialization must succeed before any lane launches. Three
consecutive update failures mark visibility failed; no child process is restarted.
The external reader must independently compute freshness from observed_at: a stale
check can remain visually in_progress after a runner failure. Unknown values remain
null; process health, forced machinery and natural settled counts stay distinct.

Do not label this campaign started, naturally certified or profitable until the
corresponding live/runtime evidence is observed. Runtime IDs and subsequent results
belong in a separate handoff update without mutating the frozen running revision.


## Terminal-reporting repair after failed replacement smoke

Run 35487539639 at c4fce48f4918467d99cacd558f223c2b61fdf6cb passed all
hosted deterministic suites/resource gates and contention preflight, then failed
at 03:51:44 UTC after 68 seconds of smoke. The sustained job was skipped.
Check 106016774812 proved remotely readable live snapshots. All four lanes had
zero natural/forced settlements; the pre-failure snapshot is not terminal reconciliation.
Artifact 10597761719 preserves the failure (SHA256
5e8f79c03a5ff40260205389f7b1561f2f8a3459c6dd37d3fbe2a8b1946d667a).

The dashboard now renders Pons's native integer cursor separately from Ramses's
frontier dictionary. No strategy data is coerced or modified. Shutdown interrupts
and reaps every child before any archive audit, giving workers an opportunity to
seal their archives. A damaged archive fails that lane's telemetry control; the
remaining lane audits and aggregate FAILED result still persist. Interrupted
accounting is explicitly unresolved, never reported as final reconciled accounting.
The live check also reports the supervisor exit code and failure flag, so an old
responsive snapshot cannot be mistaken for a still-running successful supervisor.

Regression coverage includes the exact integer cursor shape, a real truncated gzip
archive alongside three valid archives, and an injected supervisor exception proving
all four children are reaped and the four-lane terminal failure JSON is retained.
All 36 combined supervisor/research/monitor tests passed locally. Hosted full lane
suites and resource gates repeat on the new revision before fresh market work.
The failed window is never resumed or spliced. No lane strategy, policy, evidence
horizon, provider rate, or accounting economics changed.


## Pons execution-acquisition and unfilled-reservation repair

Smoke 35488026893 (a4ff8cbfb8ae5400687abed6d10140144c455459) completed
600.118 seconds of four-lane overlap, with no process restart, no crash and normal
exits. The four-hour stage correctly remained blocked: all three Pons qualifiers
failed entry with stale_state before any fill, retaining 10500000000000000 native
quote units across three reservations. Native cash remained at genesis and basis
was zero. Full source evidence is retained in artifact 10598344530, SHA256
987bf96aea3917717ae6f93b1bb5e45de84e86cd1fdf5892553adaa152971f31.
Read-only review 35489445781 authenticated that artifact; it made no market calls.

Other progress: Pump 447 discovered / 7 full-evidence / 0 qualified; Meteora 53
pools / 12 screened and 2 complete economic vectors rejected by frozen economics;
Pons 182 evaluated / 60 complete fresh / 3 qualified / 0 filled or settled;
Ramses funded once from its pinned screen, completed 2 scans, and rejected economics.
There were no natural or forced settled lifecycles. All terminal ledgers balanced,
but Pons reservations were unresolved and therefore the smoke was FAIL.

PR86 at 40c66a68704fab147dacbfc25a0819b5a6f9c844 batches the identical pinned
Pons execution reads inside the original freshness timer (2 transports rather than
serial calls), authenticates the repeated pinned header, and never resets candidate
observation time or raises the five-second limit. On a boundary, a replay-proven
zero-fill native reservation is cancelled with the native ledger event, then its
cohort allocation is released exactly once. Filled/ambiguous exposure remains held.
All 226 Pons tests pass, including unchanged native buy/sell quote economics,
slow/reorg rejection, durable stale-entry cancellation, and filled-position protection.
The certification overlay includes this exact lane repair. Full combined gates and
clean smoke must repeat before another fresh four-hour window can begin.
