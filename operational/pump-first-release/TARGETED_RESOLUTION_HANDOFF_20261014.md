# Targeted resolution checkpoint — 2026-10-14

Engineering branch: `engineering/targeted-resolution-20261014`.

The final focused-tested engineering candidate is `5f03b0599af6af05c796e27c867a545f2abb188c`, based on diagnostic checkpoint `06209b854378d7ef31a6ccc409c2f764295d24ed`. SQLite attribution is separately reviewable at `e443005edfb23fb169826717ddb6196847fb3ece`; Pons pacing/HTTP context is `2fa0b59fa8038275676e72fb3c1e7f9380f7724d`. Historian child attribution is `f69ffcf0`; the diagnostic-only launcher/collector is `5f03b059`. Installed source remains `a70e2610743d8595b3d1a36ed25821a6689c29f3`. Preserved checkpoint-connection WIP `66a87ac32f969195352ade7d35150dd2be53b81b` remains separate, untested and undeployed.

## Authority and safe state

Current authority permits isolated engineering, network-blocked offline validation, read-only host/account/documentation inspection and normal Git publication. It does **not** permit installation, service starts, market-provider requests, operational database writes, routing migration, funding or acceptance. PAPER is stopped and disabled; funding remains closed. No trading epoch, monetary history, provider counter, recovery point or production database was reset or changed by this work. At 15:07:05 UTC, read-only reconciliation confirmed $1,000.00 cash, zero positions/reservations/commitments/obligations/pending work, sequence 8,826 and unchanged journal head `ffb6b9bd229457948caa66a6c5a2a4d2716bdf1792be0863d163294261e899af`. Historical sequence 2,036/head `c0cb1d5fd4a156378e4e53764c0f528707ee9a5af799662daf15f207be95723e` also reconciles unchanged. Its schema has no direct cash field; absence was not reported as zero.

The obsolete fixed dollar/attempt allowance is not reinstated. The next missing authorization is the operational scope in [the current observation specification](CURRENT_COMBINED_OBSERVATION_SPEC_20261014.json), not a new spending ceiling. Any later operation must verify actual obligations again; a retained flat-state receipt is insufficient.

## Closed replay route and provenance

Historical full-machine replay is **closed for the currently available material**. Complete Pump inputs/joins, initial state, Pons response history and actor timing are missing. No further search of the same directories, speculative reconstruction, reduced replay presented as representative, or large database-copy request is justified. The 13,851,983,872-byte database exceeding the optional 2-GiB fixture allowance is a separate constraint; changing that allowance would not supply the missing input.

The recovered historical baseline source is `3ef0a6628780ff73dab68d933ca82851f61ea1f4`, from the baseline and linked attempt-7 receipts. This resolves provenance, not comparability. Historical combined rates of 4.389218 incoming and 1.868677 published durable slots/s over 391.18587 seconds and later source-only rates of 4.488991 and 4.410512 over 63.711 seconds remain different workloads/durations. Neither is a controlled speedup comparison. The capped trace ended before the fatal operation; generic code 5 does not establish a lock holder or the combined bottleneck.

The small feasibility disposition is retained in [evidence](evidence/targeted-resolution-feasibility-20261014.json). Reopen replay only upon a concrete new artifact that makes a specified test faithful and useful.

## Tested corrections and diagnostic changes

**Pons dispatch spacing:** existing shared Admission now retains endpoint-wide adaptive public pacing and revalidates a dispatch opportunity after cooldown, admission waiting, serialization and durable start accounting. Stale grants return through the same queue with their original deadline; a new client cannot reset slowdown. Singles/batches use this path. Existing priorities, fairness, accounting, retry counts, role-pacer fallback and independent canonical Alchemy protection remain intact. The original regression workload now yields 500-ms spacing after cooldown, rather than the earlier 125-ms spacing. Mock transport starts are measured; arbitrary operating-system descheduling is not a verified kernel-send guarantee. This corrects a scheduling defect, **not** the historical 429 cause or provider suitability.

**SQLite attribution:** selected existing connection and capture/deliver/ACK/checkpoint boundaries preserve the first error's full SQLite code/name, configured database/open mode, connection identity, fixed operation/phase, transaction state/timing, owned source location, actual executor PID/native thread and device/inode where available. Optional probes and cleanup cannot replace the original error. The bounded operation ring is at most 128 entries of 4,096 encoded bytes; a separately reserved terminal record is at most 64 KiB. The actual child worker termination test preserves this terminal evidence after ring saturation and lost stderr. Diagnostic coverage loss is invalid, rather than evidence of no contention. No busy timeout, retry, transaction, durability or checkpoint behavior was changed. The two existing historian RO readers also preserve actual child executor facts with their original connection arguments. Their existing defer note carries bounded context only when diagnostics are required. Missing/invalid SQLite attribution or a broken historian pool rethrows the same original exception in required diagnostic mode; ordinary defer/backoff remains unchanged. Healthy child coverage is not independently polled. The historical fatal SQLite operation remains **unattributed and unrepaired**.

**HTTP rejection context:** existing single/batch error paths retain safe headers and sanitized fixed error fields, endpoint/request fingerprints, dispatch/completion timing, labelled process-local inflight counts and existing wrapper ancestry. Body capture is at most 8 KiB under the original absolute transport deadline. Unsupported/late/failed body capture remains explicitly unavailable; the original 429 survives. Accounted bytes are actual consumed bytes, not an assumption that the old response was empty. No new attempt, routing change or traffic to provoke throttling was introduced.

No sustainable full-machine throughput gain is established by these changes. All approved strategy behavior and nine-change source-integrity assertions remain covered.

## Validation and evidence

Pinned runtime: `/opt/meme-machine/.venv/bin/python`, CPython 3.12.14, linked SQLite 3.45.1. Tests use the supported repository runner and its provider-network guard. Scratch fixtures are disposable and contain no authoritative epoch. These sets overlap and must not be summed as unique cases:

| Exact scope | Result | Wall time |
| --- | --- | --- |
| Pons spacing/HTTP/topology/admission/adaptive | 63 PASS | 2.453 s |
| Final Pons, USD source integrity/nine changes/native protection/shared acquisition | 117 PASS | 48.483 s |
| SQLite/history/native usage/preflight/checkpoint | 169 PASS | 19.298 s |
| Final terminal recorder and actual supervisor worker/config paths | 48 PASS | 12.096 s |
| Final historian attribution/history separation/refinement/checkpoint | 90 PASS | 17.239 s |
| Diagnostic launcher/collector final cadence/reserve/coverage | 30 PASS | 0.314 s |
| Earlier launcher plus actual inherited supervisor behavior | 51 PASS | 11.387 s |

The first 63-case run precedes the final endpoint-alias correction; the 117-case run includes it. The 169-case run precedes the final supervisor recorder-forwarding hook; the 48-case run verifies that successor. The first incorrectly selected FAST command exited 2 before collecting tests; its failure log is retained. Final local FAST on exact `2fa0b59f` completed 2,002 tests in 2,252.098 s: 2,000 passed, one failure and one error. Both were the unchanged real containment tests because the root cgroup lacked a delegated I/O controller. The exact two cases then passed in 4.699 s using the repository’s documented temporary `+io` fixture; the original controller configuration was restored in `finally`, and no existing service limit changed. This is a disclosed failed full run plus focused environmental disposition, **not an uninterrupted full FAST PASS**. No valid assertion was modified. The final successor’s only additional runtime changes are historian error attribution/required-diagnostic stopping; its affected history tests pass. Launcher and test registration are engineering-only. Do not describe this as an uninterrupted final-source release-suite PASS or silently erase the earlier failure. The latest addendum requests focused independent validation without duplicating unrelated release work.

External evidence root (not recursively copied into Git): `/root/Documents/Codex/2026-10-10/the-meme-machine-eliminate-redundant-data/blocker-repair-20261011/`.

Relevant receipts/logs:

- `TARGETED_RESOLUTION_FINAL_FAST_2fa0b59f_20261014.log` — full local failure preserved
- `TARGETED_RESOLUTION_CONTAINMENT_CASES_20261014.log` — exact two environmental cases PASS
- `TARGETED_RESOLUTION_CONTAINMENT_HOST_20261014.json` — temporary controller availability/restoration
- `TARGETED_RESOLUTION_SAFE_STATE_20261014.json` — current read-only identities/obligations/service
- `TARGETED_FINAL_PONS_ECONOMIC_GUARDS_20261014.log`
- `TARGETED_TERMINAL_WORKER_FORWARDING_20261014.log`
- `TARGETED_PONS_INTEGRATED_OPERATIONAL_20261014.log`
- `TARGETED_SQLITE_INTEGRATED_OPERATIONAL_20261014.log`
- `TARGETED_PONS_INTEGRATED_20261014.log` — preserved selection error
- `TARGETED_COMBINED_DIAGNOSTIC_FINAL_20261014.log`
- `TARGETED_COMBINED_DIAGNOSTIC_LAUNCHER_20261014.log`
- `TARGETED_HISTORIAN_ATTRIBUTION_FINAL_20261014.log`
- `TARGETED_DIAGNOSTIC_RETAINED_SAMPLE_SHAPE_20261014.json`
- `TARGETED_PONS_CORRECTED_REPRODUCTION_20261014.json`
- `TARGETED_SQLITE_RECORDER_OVERHEAD_20261014.json`
- `STAGED_SUSTAINED_PIPELINE_BASELINE_20261014.json` and linked original attempt receipts
- `STAGED_RECOVERY_FINAL_20261013.json` — prior completed recovery/integrity evidence; not repeated here

The tiny SQLite overhead probe retained identical 4,096 rows, 4,480 statements and digest `dde445b66a62e663d2be9b1f70a4ae53712ef2c497ca2e7f37b270480e615284`. Native/instrumented CPU was 0.022444033/0.03228234 s; wall time was 0.080706994/0.089435693 s. This measures recorder overhead on that synthetic workload, **not** Pump throughput or a cost saving. The corrected pacing workload took 0.315116 s wall/0.231861 s CPU with simulated clock; it made no provider calls.

## Independent release issues

| Issue | Disposition |
| --- | --- |
| Pons post-cooldown dispatch defect | Corrected offline; current-market effectiveness not observed |
| Pump fatal SQLite operation | Recorder tested; historical failing operation/lock holder unknown |
| Pump sustained combined capacity | Unresolved; faithful historical replay unavailable; current observation proposed |
| Pons mandatory provider arrangement | Decision specification prepared; public production suitability/account limits not proven; no migration |
| Pons demand-writer READONLY INSERT | Separate original failure; no causal repair claimed |
| Later backup/storage failure | Latest point is incomplete/unusable; generic copy failure not diagnosed by these tests |
| Active backup versus protection | Existing process-group freeze can exceed Survivor's 3-s deadline; full-autonomy issue, not silently disabled |

[The provider decision](PONS_MANDATORY_PROVIDER_DECISION_20261014.md) distinguishes current official public-RPC guidance, existing Alchemy account metadata, exact filter capability, unknown account-wide limits and unmeasured net incremental demand. No account purchase or routing deployment is authorized.

## Next operation and rollback

Prepare one current-generation combined funding-closed observation, **not** an old-run reproduction. Its primary purpose is to locate accumulation across preparation, owner admission/commit, history delivery, ACK/proof/publication and actual strategy consumption. Natural fatal SQLite capture is a separate secondary opportunity. Report missing edges honestly; a flat portfolio cannot prove held-position capacity. No diagnostic minute counts toward acceptance.

The observation review identified that systemd `Restart=no` does not prevent the supervisor's own recovery, the old duration excludes initialization, and the existing broad observer cannot supply the promised lightweight collector. These gaps are closed by the focused-tested `engineering/diagnostics/current_combined_observation_20261014.py`: it rejects recovery before a second lane/source spawn, validates actual unit settings and exact source identity, starts one outer clock before the service request, and runs bounded read-only metric/cohort collection. Do not execute the old staged driver unchanged.

Full SQL/counter/cohort samples run every five seconds; one-second guards remain at most 1 KiB and retain the cached SQL sample’s original timestamps. A read-only retained-shape check projected 47,437,920 bytes at the old cadence versus 16,619,040 at the corrected cadence, before future shape/kernel additions. This is output feasibility, not a market throughput benefit. Actual cap remains 32 MiB with separate 64-KiB terminal and 64-KiB metadata reserves. No diagnostic-file deletion or artificial evidence freshness is used.

The exact proposal requests up to 900 s diagnostic startup and 900 s post-startup collection, work stop by 1,800 s and a 65-s shutdown reservation. Original 300-s readiness failure remains FAIL. Unit runtime fallback is 1,800 s, rather than 1,865 s followed by another shutdown interval. Timeout, failed unit, fatal error or recorder loss is recovery-required. Zero children alone does not prove native graceful drainage. Per-event precommit/proof reason/SQL actor and passive Pons ancestry limitations remain explicit; only observed aggregate and receipt/ACK edges may support a decision.

Once separately authorized, verify source/configuration, service/process state, actual selected/historical epochs and all obligations, mounted storage/reserve, recorder ownership/terminal capacity, provider profile and backup non-overlap. Reference valid recovery evidence without another bulk copy. Save small configuration overlays, install only the validated candidate, and start only the bounded OBSERVATION launcher. Keep allocations closed and the normal service disabled.

At the first failure or collection/deadline end, use established graceful shutdown and retain durable pending work, terminal error, usage and current state. A failed drain is a safety failure, not a complete observation. Restore previous small overlays/source only after obligations and additive schema compatibility permit; never rewind a database, delete sidecars, reset counters/epoch, or automatically restart. The single next decision is a measured, specific corrective operation/dependency—or STOP without an unchanged retry.

Publication is normal, non-force, to the owned engineering branch. Exact published documentation head/remote verification is retained in `E/TARGETED_RESOLUTION_PUBLICATION_20261014.json`; deployment candidate remains the explicit focused-tested source above. Final status: **READY_FOR_BOUNDED_OBSERVATION_AUTHORIZATION**. No operation is automatically dispatched.
