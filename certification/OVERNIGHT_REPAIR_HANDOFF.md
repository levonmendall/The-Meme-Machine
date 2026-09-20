> Superseded launch instructions: follow SOLANA_ALCHEMY_EFFICIENCY_HANDOFF.md. Robinhood-only validation never launched; the next authorized validation contains both network repairs and current execution-certification sources. Recurring runs remain stopped.

# One-hour paper repair campaign — September 20, 2026

The user replaced the four-hour schedule with successive **one-hour observation
windows**, reviewing and repairing demonstrated engineering defects between runs.
This supersedes the read-only four-hour monitoring instruction. Paper-only,
frozen policy, freshness, finality, accounting, isolation and evidence controls
remain mandatory. No signing, submission, new paid infrastructure or main merge.

## Pinned repairs and source

Parent integration: `477c153af8efd41d29aacdad25f6e6899df64e67` (PR89), including
consumer scheduling PR87/88 and Pons quote/cancellation PR86. See
`EVIDENCE_SCHEDULING_HANDOFF.md` and `sources.json` for exact source, execution,
policy/config hashes and composed overlays. All four remote source heads were
reverified unchanged at 2026-09-20T06:14Z. Before these duration-only changes the
exact parent passed 1,087 lane tests, 38 supervisor tests and three resource gates.
The hourly supervisor regressions now total 41. The workflow reruns all gates on
its exact head before any live smoke and again before the one-hour window.

Cancelled four-hour run: 35489724704 at
`f7ee2b13036abb0171e0001608d589b51d28947e`; cancellation workflow 35493646305
completed successfully. This is interrupted evidence, never a completed window.
Also stop repair-branch CI run 35492642861, whose automatic live-diagnostic job
would compete for provider capacity. Do not resume cancelled/failed runs
35483374004, 35486770334, 35487539639, or 35488026893. Keep the Frozen Wallet Study
launcher `6aad3e04f1a0819199290a31fdd19053` paused.

## Launch and observation protocol

Execution branch: `cert/one-hour-repair-campaign`. Push a reviewed commit with
`[qualification-build] [four-lane-hourly]` to launch the existing
`.github/workflows/four-lane-certification.yml`. The first marker prevents an
unrelated legacy live diagnostic. A subsequent cycle may update a small request
record with its sequence and prior-run review; this is an explicit new workflow,
never a restart of a lane. Do not push a launch marker while any market run is
active. The shared workflow concurrency lock and contention preflight stay on.

Each workflow performs full deterministic gates, a 600-second concurrent smoke,
normal smoke drain, exact-revision readiness, then a new 3,600-second concurrent
observation and normal strategy-defined drain. The hour begins at the last lane
launch, not workflow creation or smoke. Existing drain allowance remains 3,300
seconds; never shorten a position's hold/exit policy to meet a wall-clock label.
The full workflow can therefore take materially longer than one hour.

Reproducible commands (authorized RPC configuration comes from existing secrets):

```sh
python -m unittest discover -s certification/tests -v
python -m certification.run prepare --worktrees "$RUNNER_TEMP/four-lane-worktrees"
python -m certification.run verify --worktrees "$RUNNER_TEMP/four-lane-worktrees" --output certification-gates
python -m certification.guard
python -m certification.live_status --output certification-smoke --phase smoke -- python -m certification.run run --worktrees "$RUNNER_TEMP/four-lane-worktrees" --output certification-smoke --gate certification-gates/deterministic.json --phase smoke --seconds 600
python -m certification.live_status --output certification-hourly --phase hourly -- python -m certification.run run --worktrees "$RUNNER_TEMP/four-lane-worktrees" --output certification-hourly --gate certification-gates/deterministic.json --phase hourly --seconds 3600 --smoke-result smoke-readiness.json
```

The workflow exports/restores the exact smoke readiness file. A different code
revision must pass its own smoke. One-hour evaluation is labeled
`one_hour_paper_campaign`; the original four-hour evaluator remains strict. All
other PASS controls and natural-settlement requirements remain unchanged.
Missing natural trades or unproven controls produce INCOMPLETE, not fabricated
success. A nonzero workflow conclusion alone is not enough to diagnose a code
defect: inspect the result's failures versus incomplete reasons.

## Overnight review loop

Use the existing update watch, hourly, through 08:00 America/Los_Angeles on
September 20 (15:00 UTC). At each check find the newest branch workflow, its exact
SHA and attempt. If active, monitor; do not edit its frozen revision or launch a
competing test. If terminal, inspect completed logs, artifact manifests and final
live checks. Persist a per-run review before starting the next cycle. Repair
demonstrated machinery defects on this integration branch, add targeted
regressions and rerun full gates/smoke. If no defect is demonstrated, retain the
frozen strategies and run another independent hour. Never interpret scarcity as
an instruction to loosen gates. Do not automatically promote shadow research.

At 08:00 stop launching new cycles. Allow any active cycle its normal drain,
deliver a final cumulative summary when terminal, then pause the watch. If an
authorization/access boundary prevents safe progress, preserve evidence and
report the exact blocker. A transient provider error does not by itself justify
stopping this overnight task or adding a provider.

Retrieve checks through GET `/commits/{exact_sha}/check-runs?filter=all&per_page=100`
(paginate). Select `four-lane-live-smoke` and `four-lane-live-hourly` with external
ID `{workflow_run_id}:{attempt}:`. Their `output.text` contains
`four-lane-live-v1` JSON. Individual check GET can be unsupported. Recompute age
from observed_at; >120 seconds while running is stale. Read workflow/job status,
supervisor_failed and supervisor_exit_code; stale healthy rows cannot override a
terminal failure. Full logs, raw RPC archives, ledgers and JSON remain in the
workflow's 90-day artifacts. Unknown is not zero, reconciliation or success.

Report per lane: continuity, policy hash, funnel, complete evidence, queue and
consumer deadline terminals, requests/errors/pressure, latency, open positions,
natural versus forced settled, accounting and concrete blockers. Highlight new
natural settlement, process exit/restart, stale data, unresolved reservations,
accounting failure or starvation. Do not count zero-fill cancellations as trades.
Do not claim profitability without final cost-complete reconciled accounting.

Priority investigation: Pump incremental consumer service's measured completion
gain and bounded provider load; Meteora authenticated trigger through complete
economics; Pons batched quote timing and zero-fill reservation release; Ramses
funded startup and natural Fee Pulse outcomes. Preserve every censoring reason.

## Cycle 1 review and cycle 2 repairs

Run [35493891947](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35493891947)
completed an uninterrupted 3,600.128-second four-lane overlap with zero restarts,
zero unexpected exits, empty final provider queues, reconciled lane accounting,
and no open positions. It was naturally **INCOMPLETE**, not an engineering
failure: every lane recorded zero natural and zero forced settlements. The exact
machine-readable review is `results/hourly-review-35493891947.json`; the retained
hourly and smoke artifacts are 10600877928 and 10600507860.

The workflow's terminal `failure` label exposed a reporting defect. The clean
INCOMPLETE result had no certification failures, but the hourly CLI returned one
and live status rewrote it as `supervisor_failed`. Cycle 2 separates hourly
engineering integrity from natural-opportunity completion. A full four-hour PASS
still requires all original controls and natural lifecycle evidence; this change
does not weaken certification.

Pump's logical consumer trail was also amplified by proactive hydration of every
transaction mentioning a PumpSwap pool and by a new owner for every overlapping
decision window. Physical queues nevertheless drained and only six Solana rate
errors appeared late in drain, so another provider was not justified. Cycle 2:

- excludes immutable cache reuse from acquisition-consumer registration;
- gives overlapping Pump decision windows a stable owner and first deadline;
- prefilters proactive PumpSwap work using authenticated matching trade logs;
- still records every stream signature and performs exact candidate hydration
  fail-closed, so unsupported shapes, missing history and economic censoring stay
  visible and unchanged.

Repair heads are `110dbf34b054daf7a35c72d94196ec7ff0c2c331` for Pump
(PR87) and `00ebf7ffb3e13911d6c842898c98312c98d4e628` for Meteora
(PR88). Frozen source heads and all four policy hashes remain unchanged. Local
exact-revision gates passed 261 Pump, 366 Meteora, 226 Pons and 238 Ramses
tests (1,091 total), 42 supervisor tests, and all three resource gates. The
hosted workflow must independently repeat those gates and pass its own
600-second smoke before cycle 2's one-hour clock begins.

## Cycle 2 preflight block

Run [35500582829](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35500582829)
at exact integration `26511c5858fc47cb8ae2f1f6a547e451a7de135e`
passed all 42 supervisor tests, 1,091 lane tests and three resource gates. The
contention guard then correctly stopped it before smoke because repair-branch
run 35500216681 still had live-diagnostic job 106050553206 in progress. No lane
process launched, so uptime, settlements and accounting are unknown/not
applicable—not zero or successful. Artifact 10602655308 preserves the gates and
preflight record; its digest is
`sha256:b09903313ef83f7a0ccb9a90618cc3fe6e6162c1b24943a80c0706bc05a71950`.

The conflicting diagnostic completed successfully at 2026-09-20T09:37:04Z.
This is not an implementation defect and the guard must not be weakened. A new
independent workflow may now rerun exact-revision gates and begin a fresh smoke;
future repair-branch pushes during this campaign must carry the qualification
marker so legacy live diagnostics do not start alongside certification.

## Cycle 3 review and cycle 4 repair

Run [35503374359](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35503374359)
at exact integration `1d8dcc1994200016754dfcddc9add39a9581444d`
completed 3,600.126 uninterrupted shared seconds with zero restarts, zero
unexpected exits, bounded provider queues, reconciled accounting and no open
positions. Engineering integrity passed; natural certification remained
**INCOMPLETE** with zero natural and zero forced settlements. The exact review is
`results/hourly-review-35503374359.json`; hourly artifact 10603898287 has digest
`sha256:9e06e2a8d402caaba2d14d1e8a8e62b06efb323210994539cdf6a2f927869020`.

Pump improved to 189 complete evidence observations from 1,103 discovered and
produced one frozen-policy qualification. Its durable accounting returned to
zero reserved/open exposure with verified replay and unchanged cash, so the
candidate did not fill and is not a trade. The compact result reported only
`qualified=1`, however, and omitted the qualifier's cancelled entry status and
reason. Cycle 4 repairs that certification-surface defect by publishing filled,
cancelled and reserved entry counts and explicit `entry_cancelled:<reason>`
terminal evidence. It does not alter entry timing, evidence, policy or economics.

Meteora screened 111 of 627 discoveries but produced no complete economic vector;
Pons evaluated 1,204 candidates with 412 stale after evidence and no qualifier;
Ramses completed ten finalized scans over eight active pools and rejected them on
the unchanged economic gates. Solana and Robinhood queues ended empty. Six
Solana rate events and a maximum Robinhood queue depth of two do not justify a
new provider. Current frozen source heads were reverified before the Cycle 4
observability edit.

## Superseding current-state repair

The repeating overnight campaign is stopped. The user subsequently authorized a
single current-state repair validation (smoke plus one hour). See
`CURRENT_STATE_REPAIR_HANDOFF.md` and Cycle 4 terminal JSON. Do not automatically
launch another cycle after that single validation.

Latest instruction supersedes that single-run authorization: finish repairs and
execute a handoff, **do not start validation**. No replacement run launched.


## Current Robinhood CU repair request

The later focused Alchemy/Robinhood request supersedes handoff-only: one smoke
and one independent one-hour comparison are authorized after all exact-revision
gates and no competing live jobs. See ALCHEMY_EFFICIENCY_HANDOFF.md. The recurring
overnight loop stays stopped; no automatic successor is authorized.
