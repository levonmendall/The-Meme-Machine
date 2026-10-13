# Pons demand failure — isolated engineering handoff

**Cause unresolved; specific missing evidence identified.** This is an evidence
capture patch, not a confirmed repair or Pons operating-readiness claim.

Base: `a55f458baf37c7dafa6286a2a05a287b1a8c2611`; preserved implementation:
`ea4f4f1bfb12ef0d3ce01d4df70a93f6d37e7605`. Diagnostic/test commit:
`f8d66ff2eee5214a85c180e4e37e25ddf6d6bae6`. Publication branch:
[`repair/pons-demand-readonly-20261013`](https://github.com/levonmendall/The-Meme-Machine/tree/repair/pons-demand-readonly-20261013).
The subsequent documentation commit adds this handoff only. Exact branch head,
remote confirmation and evidence checksums are in `PONS_PUBLICATION.json` in
the task workspace below. Both commits use the existing `[skip ci]` publication
workflow; there is no PR, merge or deployment.

Changed files: `meme_machine/runtime/robinhood/provider_usage.py`,
`tests/test_provider_usage_wal_race.py`, and this document. The original
`05103e93c28f2731674b1a99403067d57e7b0848` transaction repair and its regression
remain intact.

## Attribution and precise gap

Evidence directory **E**:
`/root/Documents/Codex/2026-10-10/the-meme-machine-eliminate-redundant-data/blocker-repair-20261011`.
`E/continuous-actual-workers-1791861490314.log` records PID 2304789 at
`2026-10-13T03:24:03Z`: Current hydration → `SelectiveEvidenceContext.batch`
→ `view_batch` fallback → `PacedRpc.batch` → `_record_demand` → `logical_demand`
INSERT → `attempt to write a readonly database`. Its receipt identifies `ea4f4f1b`.

The source passes `shared_admission.path`, constructed from
`provider_authority.paths()['provider']`. Supervisor binds it to
`<state-root>/shared/robinhood-provider.sqlite`; the receipt's initialized root
implies `/mnt/volume_nyc1_1790918115030/meme-machine-paper-shared-1000/shared/robinhood-provider.sqlite`.
This is source-derived binding, not a printed failing-connection path. The
cumulative `provider-usage.continuous.sqlite`, capital and Pump canonical
databases are separate. Each demand opens a fresh default read/write/create
connection, reads existing schema outside a transaction, inserts/commits, and
closes. There is no retained demand connection or supported retry mechanism.

The failure enters the pre-attribution wrapper at line 51; the preserved later
wrapper enters at line 71. No `provider-sqlite-failure-*` receipt survives.
`/var/lib/meme-machine-monitor/market-lane-pons-1791861524292-stacks.json` shows
Current/Survivor demand and transport accounting overlap, but aggregate samples
cannot identify the failure-time filesystem event. The retained
`E/PONS_WAL_ROLE_ISOLATION_20261013.json` did not reproduce the failure from a
simple root reader. The copied failed quiescent fixture has no retained result
or script establishing its cause. Later same-source nonrecurrence is not proof
of repair. No evidence establishes root ownership, old-epoch binding, inadequate
hardware, or the previously repaired BUSY_SNAPSHOT as this cause.

Missing: the extended SQLite code/name; actual failing connection path and
state; actor identity; failure-time DB/parent/WAL/SHM identities and permissions;
and relevant connection-time versus failure-time replacement, checkpoint or
sidecar lifecycle. These missing observations cannot be reconstructed offline.

The patch extends the existing wrapper's failure attribution inside `demand`,
before close. It attaches structured facts to the original SQLite exception and
a JSON traceback note: code/name, phase, PID/thread/UID/GID, requested open mode,
connection attempt age, transaction state, DB list, journal/query-only state,
fixed file/parent metadata and filesystem flags/resources. Diagnostic SQL uses
zero busy timeout on the failing connection. Attribution errors cannot replace
the demand error. No endpoint, fingerprint, request/response or exception text
is copied. No successful-request scans, diagnostic database writes, retries,
accounting changes or provider work are added. Filesystem calls have no strict
wall-time bound; failure-time snapshots cannot prove prior file lifecycle.

## Focused offline evidence

Task workspace **W**:
`/root/Documents/Codex/2026-10-13/the-meme-machine-parallel-pons-database`.
Existing development Python and repository network-guarded suites were used.
No separate development host was found. Each short test window checked for
other local offline test/profile processes first; none was visible at launch.
This establishes observed non-overlap, not CPU/I/O isolation or a reserved window.

```sh
/opt/meme-machine/.venv/bin/python -m operational.tests FAST --modules tests.test_provider_usage_wal_race --verbose
/opt/meme-machine/.venv/bin/python -m operational.tests OPERATIONAL --modules tests.lanes.pons.test_provider_topology tests.lanes.pons.test_provider_admission tests.lanes.pons.test_view_batch tests.lanes.pons.test_provider tests.test_provider_purchase_attribution tests.test_provider_retry tests.test_runtime_wal_races --verbose
```

Results: **7 passed / 0.302 s**, **73 passed / 2.076 s**. Logs:
`W/pons-focused-final.log` and `W/pons-affected-regressions.log`.
`git diff --check` passed. The initial fixture failed because its root-owned
Scratch ancestor prevented service-user traversal; only the tiny disposable
fixture location was corrected. `W/pons-focused-initial.log` and failed suite
scratch `/tmp/mm-engineering-jel78uld` are retained.

`W/pons-readonly-comparison.json` compares the original and patched source in a
real unprivileged UID/GID 997 fixture with an existing 0400 database. Both raise
code **8 / SQLITE_READONLY** at INSERT; the patch adds diagnostics, preserves
the error, closes safely, and still records zero failed demand rows. Restoring
only that fixture's mode to 0600 allows a fresh connection to record exactly one
row on both versions. This demonstrates that permissions can produce the text,
not that permissions caused the operating incident. No exception is injected in
that experiment; separate injected-fault tests only test diagnostic resilience.

Actual Pons acquisition caller tests use fake HTTP and independent Current and
Survivor contexts sharing a temporary admission/cache ledger. They cover
concurrent demand with a retained read-only WAL snapshot, successful cache
miss/hit accounting, durable pre-HTTP starts, failed-response accounting,
queue/flight cleanup and subsequent recovery without cached failure or duplicate
purchases. They do not run the complete cohort/controller or live history.

## Integration owner and remaining validation

Addressed to the owner of `engineering/pump-history-separation-20261013`.
Initially inspected successor: `dc957c521b6d043a9d4a1bca3c47127bc2f51abb`;
latest observed committed head: `c3c753c3bdf8bf6e3dd5c253e21799fb52e8d743`,
with newer economic preparation/publication work active. Its checkout is untouched.
This patch is independent of Pump's redesign and interfaces. It changes none of
Pump's assigned owner/history/publisher files or shared suite registration.

1. Integration owner may cherry-pick `f8d66ff2` into the coordinated development
   branch and run the two focused commands above on the combined source. Keep
   the current Pump changes and their own validation requirements intact.
2. Demand-writer validation remains open: under a separately authorized runtime
   window, retain the original exception's diagnostic note if the fault recurs,
   correlate it with available worker/filesystem evidence, then reproduce and
   repair that demonstrated mechanism offline. Do not use nonrecurrence as a
   confirmed repair. No production chmod/chown, database reset, sidecar deletion
   or timeout change is prepared because no such cause is established.
3. Sustained Current/Survivor controller/history validation is separate. Use
   the existing actual family-worker observation and durable acceptance records
   after restart authority; retain history completeness, controller progress,
   three-second Current limits, Survivor obligations and independent consumers.
4. Held-position protection and admission under combined Pump/Pons load are
   separate. Reuse the existing protective-capacity, Current exit sharing,
   Current/Survivor independence and Pump/Pons integration harnesses for offline
   parity; subsequently verify actual fresh native/USD protection, original
   deadlines, admission fairness, canonical lag and resource behavior under a
   separately authorized combined workload.

Backup/storage readiness and coherent normal operating-profile installation
remain shared restart requirements. No live validation was run. The retained
seven acquisition samples (median 2.132229 s, max 2.595040 s) are acquisition-only;
they were not repeated or credited to acceptance. Formal one-hour/36-hour
acceptance remains **zero credited minutes** from this work.

Operating-state changes: **none**. Read-only final inspection: PAPER
inactive/dead, disabled, MainPID 0; installed source remains `ea4f4f1b`.
No operating SQLite database was opened for tests, provider request dispatched,
funding opened, infrastructure changed, pacing altered, monetary file changed,
or $1,000/$500 epoch state modified. Verified 40-block factory capability and
fallbacks, indexed telemetry/maintenance, strategy/economics and protective
deadlines are unchanged.
