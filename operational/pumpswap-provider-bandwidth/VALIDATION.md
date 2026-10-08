The affected engineering checks pass. The full suites are **not green**: three
failures/errors reproduce on the untouched reference, and one maintenance test
failed only in the full OPERATIONAL run. No production source or existing test
expectation was edited. This publication does not authorize a production switch.

All commands used CPython 3.12.14 with the existing pinned environment. Every test
and replay process called `operational.tests.network_guard()` to deny nonlocal
network access. State was disposable, with `TMPDIR` and `SQLITE_TMPDIR` set to
admitted scratch storage. The task supervisor reused the already published
engineering `artifact_storage.Scratch` implementation from Pons commit
`d0c67bee09cb58f4b60627c6fdec1ecfee299caf`, checked headroom/quota every 250 ms,
and terminated the process group at its wall budget. It did not change that
implementation or the concurrent checkout. Failure scratch was retained.

| Run | Result | Test time | Limit / disposition |
| --- | --- | ---: | --- |
| Affected provider, native join, startup, candidate-history, Current/Survivor and capital modules | 136 tests, PASS | 32.394 s | Ten modules; actual production reducers/qualification fixtures |
| Final added bandwidth-audit class | 9 tests, PASS | 0.073 s | Includes the final older scoped-interest regression and current tariff model |
| Full corrected capture, reference and hypothetical omission | Exact canonical and durable-output equality | 9.819 / 10.151 wall s | 287 canonical events, 1,215 native witness tuples; 10,210 incomplete facts stay incomplete |
| FAST | 856 tests, 1 failure | 284.729 s | Historical source-freeze assertion; reproduced on untouched reference |
| OPERATIONAL | 2,276 tests, 2 failures, 2 errors, 33 skips | 702.899 s | Source freeze and two IPC errors reproduce; suite-only generation failure unresolved |
| Selected four failing checks on untouched reference | 1 failure, 2 errors; generation check PASS | 2.544 s | Same source freeze / archived-startup rejection |
| Same selected four checks on this branch | 1 failure, 2 errors; generation check PASS | 2.610 s | No new isolated failure |
| Generation-check diagnostics | 20/20 reject the old generation on each branch | See receipts | Every run has `maintenance_generation_changed` and zero archived records |
| Entire maintenance module, reference / this branch | 33 PASS / 33 with 1 timeout | 57.867 / 72.634 s | Generation check passes both; unchanged simultaneous-debt fixture times out on this branch |
| Simultaneous-debt fixture isolated, reference / this branch | PASS / PASS | 6.049 / 9.604 s | Native service/reducers unchanged; 12-second harness timeout remains intact |

The affected-module run predates addition of the ninth audit test. The final
class run covers that addition. FAST imported eight new tests; OPERATIONAL
imported nine. Monthly scenario inputs were subsequently made more conservative
by explicitly retaining exceptional reactivation archive requests; the final
class and cost-model CLI were run against that final implementation.
The final class was also rerun after extending the raw-input budget to cover
subscription envelopes as well as deliveries; the measured attribution is
unchanged.

`test_strategy_sources_and_nine_change_tests_byte_unchanged` fails because the
reference's already approved Pons selective-acquisition source differs from an
older historical freeze. The standalone test fails identically at reference
`703d8764a775d9680e3b48baf2c96f3fb7cf8eb6`. The 363-file preservation audit verifies
this branch against that requested reference rather than changing the freeze or
reverting prior approved work.

Both `Run369IPCTests` errors are archived fixtures that invoke `serve()` without
the required Model B source driver. The service rejects startup with
`legacy_startup_archived_model_b_driver_required`; the disconnected-client test
also sees `ConnectionRefusedError` because no server callback was established.
Both errors reproduce on the untouched reference. The Model B boundary remains
unchanged.

`ProductionServeTests.test_generation_change_revokes_old_runtime` failed once in
the full OPERATIONAL run because its returned error list did not contain
`generation_changed`. It passes on both branches in the four-check comparison,
and each branch's 20 diagnostic repetitions rejects the changed generation with
zero archives. The test and harness are byte-identical to the reference. The
harness stops after its first maintenance turn and records concurrent service
errors; the adjacent stale-observation fixture already allows retries after
cooperative source/control preemption. That suggests scheduling sensitivity,
but the original failure did not retain its error list and a root cause is
**not proven**. Do not classify it as a reproduced baseline failure or hide it by
changing expectations. Full maintenance-module rerun receipts are recorded in
[VALIDATION.json](VALIDATION.json).

The full-module rerun then hit `TimeoutError` in the unchanged
`test_simultaneous_high_debt_and_three_scopes` fixture's 12-second service wait.
The reference module passed; isolated comparison passes in 6.049/9.604 seconds
on reference/this branch. The concurrently published Pons validation at commit
`481bd11e918cda9c5de624a619f44688dc97fefb` independently reports the same timeout
against byte-identical maintenance/service sources. That corroborates an
existing host/maintenance limitation, but does not certify its cause or resolve
the timeout. It remains an explicit validation limitation; no runtime deadline,
safety gate or existing fixture expectation was changed.

Published [VALIDATION.json](VALIDATION.json) records every run's exact command,
working tree, exit code, resource receipt, log digest and retained-scratch
identity. Small full-suite/failure logs and resource receipts accompany it in
`validation/`; larger replay output stays at the authenticated locators in
[PARITY.json](PARITY.json). The initial capture itself remains unchanged at its
original mounted-volume location. Failed scratch is not authority for market
or strategy completeness.

Replay CPU includes profiling and omission inspection. Both replays received the
original 48,501,501 WS bytes and 1,829,265 native bytes. Omitting 16,441,310 failed
WS bytes from the hypothetical reducer input is not an actual provider result.
Complete fixture qualification/ledger checks protect the current architecture;
there are no authentic full native PumpSwap transaction envelopes or complete
funded-position replacement inputs. [COVERAGE.md](COVERAGE.md) gives each
mandatory/adversarial requirement its evidence and limit.

To repeat the main checks from the repository with an approved CPython 3.12.14
environment and supervised temporary storage:

```bash
python -m operational.tests FAST
python -m operational.tests OPERATIONAL
python -c 'from operational.tests import network_guard; network_guard(); import unittest; r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName("tests.test_provider_efficiency.ProviderBandwidthAuditTests")); raise SystemExit(not r.wasSuccessful())'
python -m engineering.solana_capacity.bandwidth_audit --capture /mnt/volume_nyc1_1790918115030/sc-proof-corrected-20261008 --output /path/to/admitted/audit.json
python -m engineering.solana_capacity.bandwidth_cost --audit /path/to/admitted/audit.json --output /path/to/admitted/cost.json
python -m engineering.solana_capacity.offline_replay --source /path/to/repo --capture /mnt/volume_nyc1_1790918115030/sc-proof-corrected-20261008 --output /path/to/admitted/reference-replay
python -m engineering.solana_capacity.offline_replay --source /path/to/repo --capture /mnt/volume_nyc1_1790918115030/sc-proof-corrected-20261008 --output /path/to/admitted/hypothesis-replay --hypothetically-omit-failed-ws
```

Output replay directories must not already exist. These commands contact no
market provider. The last command labels the unsupported omission hypothesis
and reports zero verified savings. No native full-payload replacement acceptance,
live deadline guarantee, connection headroom or production CPU reduction follows
from these checks.
