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
