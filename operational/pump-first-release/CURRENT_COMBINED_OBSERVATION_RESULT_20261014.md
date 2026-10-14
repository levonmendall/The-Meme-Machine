# Authorized single observation — stopped for review

**OBSERVATION_FAILED_BEFORE_WORKER_START. No retry is authorized.**

The owner authorized the specification at `282d38946955b46422a34348062ac572777d8473`
and executable `5f03b0599af6af05c796e27c867a545f2abb188c`. That single attempt
has been consumed. This receipt supersedes the earlier prepared/awaiting-approval
status; it does not authorize another deployment, start, provider workload,
database repair, funding transition or acceptance interval.

## What happened

The sole systemd start was recorded at **2026-10-14T16:18:25.610827Z**. The
existing storage pre-start guard passed. Service launcher PID **2690426** then
raised `PermissionError`, errno 13, in
`engineering/diagnostics/current_combined_observation_20261014.py:600`, at
`args.output.is_dir()`. systemd recorded its failure at **16:18:25.900822Z**.

The exact output was
`/var/lib/meme-machine-diagnostics/20261014-current-combined-161351`.
Its parent was **root:root, 0700**; its child was correctly
**meme-machine:meme-machine, 0700**. The service user could not traverse the
parent. Preparation used `mkdir(exist_ok=True, mode=0o755)`, which does not
change an existing directory's mode. The preflight checked child ownership and
configuration/import/source identity but missed actual ancestor traversal.
This was a preparation defect, not a market-processing or database failure.

Failure preceded reading the service clock and construction of
`SingleAttemptSupervisor`. No Pump, Pons, canonical owner, historian or history
consumer actor was started by this entry point. The controller wrote its result
at **16:18:45.827543Z**, with **20.213236859 seconds** from its outer monotonic
origin to its final stop check, within the authorized absolute boundary.

## Results and limitations

| Question | Observed result |
| --- | --- |
| Readiness | Not reached; fatal startup failure. Original readiness field is null, not PASS. No 300-second deadline extension is credited. |
| Pump arrival/preparation/canonical/history/ACK/publication/consumption | Not exercised; no rates, queue trajectory or CPU-capacity conclusion available. |
| Natural SQLite failure | Not reproduced; no SQLite actor was exercised. No lock holder or repair established. |
| Pons dispatch, admission, 429, quote/USD, protection | Not exercised. Prior offline scheduling proof remains distinct from provider suitability and capacity. |
| Provider usage | All existing bootstrap snapshot fields unchanged; zero increments in physical HTTP starts, native opens, logical elements, CU and delivered/uncertain bytes. Modeled incremental usage cost $0; no invoice verification. |
| Acceptance | Zero qualifying minutes; no operational or held-position PASS. |

The original controller result is preserved unchanged: **RECOVERY_REQUIRED**,
`stop_reason=SUPERVISOR_ENDED`, `failure=true`, `drained=true`,
`native_drain=UNVERIFIED_TIMEOUT_ESCALATION_POSSIBLE`. Its `drained` field means
the unit/process check ended, not that native graceful drainage was demonstrated.
Independent review of the fatal source location and journal establishes that
no supervisor or worker actor was constructed, and no worker transaction or
native drain began. No graceful-drain claim replaces the original result.

## Reconciliation and compatible rollback

Fresh read-only reconciliation before and after rollback matches the complete
pre-attempt identities. The operating epoch
`paper-shared-1000-20261011T071207Z` retains **$1,000.00 cash**, sequence **8826**,
and journal head
`ffb6b9bd229457948caa66a6c5a2a4d2716bdf1792be0863d163294261e899af`.
Positions, reservations, commitments, obligations, pending deliveries/backing
and runtime pending/inbox counts are all zero. Historical $500 epoch
`paper-1791089005190643467`, sequence **2036**, head
`c0cb1d5fd4a156378e4e53764c0f528707ee9a5af799662daf15f207be95723e`
also reconciles identically; its missing direct cash field is not reported as zero.

Rollback completed at **16:25:12.112244Z** to clean installed source
`a70e2610743d8595b3d1a36ed25821a6689c29f3`. Both saved observation overlays
were restored with exact hashes, modes and ownership; source identity metadata
was restored. No databases were rewound, accounting or usage reset, evidence
deleted, or service restarted. No newer branch/WIP was installed. The separate
`66a87ac32f969195352ade7d35150dd2be53b81b` WIP remains untouched.

PAPER ends **stopped, failed/exit-code, MainPID 0, disabled, Restart=no**,
funding closed. The failed unit status was not cleared. The old finite diagnostic
override is restored and must not be mistaken for normal continuous operation.
No backup timer file or setting was changed and no backup ran. Ordinary daemon
reload re-evaluated its randomized next firing (04:04:54 to 04:00:03 UTC on
October 15); neither schedule overlapped this attempt. Existing completed
recovery references were reused, without another bulk copy/integrity run; the
later failed backup remains unusable. Final inspected reserves exceed 5 GiB
on both root and trading volume.

Preserved preparation interruptions include an initial script import failure,
service-user Git identity checks before any start, and a rollback directory-fsync
helper's `closing(int)` error after source/first-overlay restoration. The last
was corrected with `os.close()` in `finally`, then remaining restoration and
exact reconciliation were completed. These were not extra service attempts.

## Smallest supported next correction — not implemented

Make only the diagnostic parent traversable by the existing service group,
for example root:meme-machine **0710**, while keeping run directories private
**0700**, or choose an existing appropriately traversable private parent.
Do not change database permissions, busy timeouts, provider routes or retries.

Focused validation should cover an existing root-only parent and verify, as the
actual service identity under its installed restrictions, directory traversal,
clock readability and creation of a bounded disposable diagnostic file before
any service start. A failure must abort preflight without dispatch. Preserve
the original directory-containment and private-output assertions. No such new
test or live correction was executed during this authorized attempt.

Another observation requires separately scoped owner authorization after that
correction is reviewable and validated. Recheck actual obligations, storage,
recovery references and source/configuration before any eventual start. Do not
automatically retry or restart the closed historical-replay search.

Pump sustained capacity/fatal SQLite attribution, Pons mandatory provider
arrangement and public throttling, separate Pons READONLY INSERT, later backup
failure, and active-backup/protective-deadline compatibility remain open.

## Durable evidence

Small published summary and artifact hashes:
[evidence/current-combined-observation-20261014.json](evidence/current-combined-observation-20261014.json).
The exact specification and executable remain unchanged; this publication adds
only outcome/handoff documentation. No unrelated tests or CI campaign was run.

Private persistent evidence root:
`/root/Documents/Codex/2026-10-10/the-meme-machine-eliminate-redundant-data/blocker-repair-20261011/`.

- `AUTHORIZED_CURRENT_COMBINED_PREPARATION_20261014.json` and retained preparation logs/script.
- `AUTHORIZED_CURRENT_COMBINED_BEFORE_STATES_20261014.json`.
- `AUTHORIZED_CURRENT_COMBINED_CONTROLLER_20261014.log`.
- `AUTHORIZED_CURRENT_COMBINED_JOURNAL_20261014.log`.
- `AUTHORIZED_CURRENT_COMBINED_PROCESSES_AFTER_20261014.txt`.
- `AUTHORIZED_CURRENT_COMBINED_POSTCHECK_20261014.json`.
- `AUTHORIZED_CURRENT_COMBINED_ROLLBACK_20261014.json` (interrupted restoration).
- `AUTHORIZED_CURRENT_COMBINED_ROLLBACK_COMPLETION_20261014.json` (completed, verified restoration).
- Saved configuration overlays; preserve privately, never publish credentials.
- `AUTHORIZED_CURRENT_COMBINED_PUBLICATION_20261014.json` records the exact new documentation SHA and normal remote verification.

Original private `clock.json` and `result.json` remain in the diagnostic directory
above. No metrics or terminal SQLite record was produced before launcher failure.
All authoritative databases, journals, counters and retained earlier failures
remain in their existing storage; none was duplicated into Git.
