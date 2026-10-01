# M1 interruption/completion repair — paper only

Production base: `dc08f9064cf5e37b63f383f52aa709d0afc1723f`
(tree `68736cf664169dee665762019800bf87ca0f1f67`).
Branch: `repair/stage-e-m1-completion`.

Only runtime completion/error handling changes. Arbiter selection, PriorityOwner,
native mutation methods, generation authority, source admission/batching,
worker count, reservations, leases, deadlines, housekeeping order, strategy and
canonical qualification wiring are preserved.

## Exact defect and old evidence

After `choose()` accepts a decision, execution can commit native work and then
yield. The execution `finally` calls `_native_progress()` before
`arbiter.complete()`. The SELECT itself is preemptible: a real urgent owner
admission at its trace callback interrupts SQLite after the archive slice has
committed. Completion is skipped; the next turn fails with
`maintenance_decision_in_flight`.

The finite regression uses the schema-valid Lane A prerequisite fixture from
`fbb376c4a19267af9ba331022fe95bdb8609b299`, without editing Lane A.
It archives 128 bounded account-scope ledger records natively, then commits one
512-record slice from a 1,000-record receipt against 1,800 eligible hot records.
The urgent admission targets the second ledger SELECT, after commit. It verifies
512 durable units/records, 1,288 remaining hot records, a 488-record receipt tail,
closed transaction, SQLite integrity, no provider calls, exact pending identity,
and the subsequent ordinary turn.

The baseline-only branch commit `c4923108836bcb67850b24df98336ed4beafc1f4`
(tree `31ed45c1fd8813c88a2f63cc3c74e754c9a109f0`) confirmed the real failure.
[Baseline CI](https://github.com/levonmendall/The-Meme-Machine/actions/runs/36837415431):
one regression failure, zero regression errors; the directly affected 106 tests
passed. Its normal deterministic suite had two failures (including M1), two
errors, and 46 skips. The other failure/errors are preserved, outside M1.
An earlier fixture attempt on `93228dee...` did not exercise the defect and is
not old-fails evidence.

## Minimum repair and accounting

After native execution or rollback, read the committed ledger normally. On an
authenticated cooperative read interruption, retry this bounded SELECT once
with SQL preemption temporarily deferred, then restore the prior handler.
No native mutation is replayed. Verify generation and the existing total
execution deadline, and call `complete()` with the original Decision object and
native deltas. Preserve the cooperative yield after accounting. A native fatal
error takes precedence over a recovered reporting yield.

The decision's bounded event has exactly one terminal completion outcome:
`completed` or `failed_closed`. Known native deltas remain in its event even
when identity, generation or expiry rejects service credit. If accounting cannot
truthfully finish, fail closed and retain the exact pending object as a diagnostic
tripwire; admission is revoked, so that object is not retried or silently cleared.
A fresh runtime reconstructs committed service from the durable ledger.
Zero work, rolled-back work, and an uncommitted outer transaction earn no progress.
An archive worker/receipt can remain genuinely pending independently of a
completed owner decision.

SQLite errors require both interrupt provenance and the actual SQLITE_INTERRUPT
result (or the exact fallback message for errors without a code). An unrelated
OperationalError remains a chained storage failure even when PriorityOwner
remembers an earlier interrupt. A failure from complete() cannot masquerade as
a cooperative yield.

## Focused verification

`tests/test_m1_maintenance_completion.py` covers before-mutation yield,
preemptible preparation, urgent work deferred across the atomic native slice,
forced SQLite interruption/rollback, committed retirement and housekeeping
followed by yield, archive commit followed by reporting interruption, zero
progress, failed/repeated ledger reads, fatal-operation precedence, actual
SQLite error after a real owner interrupt, exact/wrong/duplicate completion
identity, failure after completion, repeated receipt retry, durable reconstruction,
a genuinely pending worker, generation changes, execution expiry (including
observation time and recovery-read time), and an uncommitted outer transaction.

The branch-specific deterministic workflow runs identical reproduction inputs
against the pinned old runtime, rejects fixture/import errors as proof, then runs
the focused suite, directly affected runtime/storage/interruption tests, normal
unittest discovery, and the resource gate. It does not run a material pressure
profile, canonical Stage E, or Stage F.

Run locally in Python 3.12.14 with the existing requirements:

```sh
python diagnostics/m1-completion/verify.py --output /tmp/m1-verification
```

The workflow artifact is the authoritative evidence package: exact SHA/tree,
environment, changed files, protected production-file check, `repair.patch`,
`old-repro.json/log`, `new-focused.json/log`, affected/deterministic/resource logs,
and `RESULTS.json`. A failed broader suite is retained and is not automatically
classified as an M1 failure when the focused and directly affected checks pass.

Remaining limit: a bounded SQL read or native atomic commit can still block in
the OS/storage layer; it is not claimed to be preemptible. Late returns fail the
unchanged lease and receive no service-success credit. Genuine storage/accounting
failure requires fail-closed recovery/restart, not guessed completion.
