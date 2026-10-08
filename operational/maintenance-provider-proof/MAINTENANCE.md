# Maintenance disposition

The three reported failures were reproduced on the integrated published source.
The newer 2,377-test receipt contains a PASS for each, but its own scope excludes
later reconciliation changes. It is evidence of intermittent success, not a
source repair or a full-suite validation of the final source. The maintenance
implementation and these three test methods are identical between published
commits 481bd11e and 842c99c4.

| Exact test | Earlier failure | Identified mechanism and disposition |
| --- | --- | --- |
| tests.test_production_maintenance_arbiter.ProductionServeTests.test_simultaneous_high_debt_and_three_scopes | Full-suite 12-second timeout; subsequently passed alone | Fixture construction was inside the timed serve owner constructor. Large native SQLite ingestion, immutable archive publication and synchronization consumed the service allowance before servicing the prescribed workload. Two simultaneous suite workers reproduced the timeout; instrumented workers also showed intermittent success at 9.350 / 10.392 seconds. Construction now finishes before the unchanged 12-second serve deadline. No production maintenance change. |
| tests.test_run381_archive_scheduling.BoundedArchiveRetirementTests.test_eligible_reader_and_all_scopes_progress_under_source_pressure | Full-suite and isolated held-reader timeout | The same timed construction combined with a clock mismatch: archive/retirement used a controlled clock, but idle turns waited a real second while that clock stood still. Contention traces stopped at turns 26/28 and 27/28 after native debt had drained, reporting no_ready_required_work. Real idle waits were 1.003 / 1.002 / 1.003 seconds, ending at the 12-second timer. Moving construction alone still reproduced the failure; making the fixture's idle cadence advance its controlled clock repaired it. Held-reader restrictions and real SQLite/owner execution remain intact. |
| tests.test_run381_archive_scheduling.BoundedArchiveRetirementTests.test_sustained_ready_work_has_bounded_two_sided_service | Full-suite 12-second timeout; subsequently passed alone | Timed fixture construction competed for two-CPU scheduling and SQLite I/O. Both initial concurrent workers failed; instrumented repeats passed at 9.304 / 8.815 seconds. The construction fix removes setup from the service timer; consistent fixture idle timing also applies. All 72 turns and both service assertions remain. No production maintenance change. |

No earlier published commit changed the affected production maintenance files or
these test methods. The initial quiet focused run passed all three in 20.499
seconds. Uninstrumented simultaneous workers reproduced all three failures.
The final fixture passed all three in each simultaneous worker (30.755 and
30.929 seconds, including all construction). The affected two modules passed
51 tests in 83.263 seconds with four existing Model A characterization skips.
Final-source focused and full-suite results are recorded in VALIDATION.json.

The repair is confined to tests/maintenance_production_harness.py. It preserves
the exact records, three scopes, held reader, native source pressure, 36/28/72
turns, real native mutations, worker behavior, assertions and 12-second service
deadline. Seeded state is closed and reopened by actual serve(). When no native
worker is unfinished, idle advances the existing controlled clock by one second
and wakes the real admission coroutine; unfinished workers retain real waits.
The already present synchronous archive completion fixture is unchanged.

SQL timing attributed 1.880 seconds to 3,917 COMMITs, 1.329 seconds to 21 bounded
record deletions, and 0.302 seconds to the corresponding address-reference
deletions. These are measurements, not a claim of an indexing defect. Traces
record actual owner telemetry, maintenance queues, native progress, reader
restrictions and shutdown. No reproducible evidence showed a production lock
deadlock, starvation, priority inversion, unsafe checkpoint, reader violation,
or lost archive/retirement service. Ordinary CPU and I/O contention amplifies
the fixture's timer and clock defects. This does not infer the exact internal
state of an older uninstrumented failing run from its timeout alone.

Supporting traces, reproducer scripts, SQL profile and test logs are preserved
in evidence/ and indexed with SHA-256 identities in VALIDATION.json. Failed
offline scratch locations and earlier harness failure receipts remain available
at their recorded local locators; no failed or unknown evidence was deleted.
