# Pons retained-audit I/O attribution

AWS funding-closed rehearsal `39060983198`, exact application `0c8e9bea`,
reported approximately 375.41 GB logical reads / 92 million read syscalls but
360.84 MB physical reads. Retained operation profiles from protected preflight
`39062800091` show that reporting after PR172 is not the whole cost. Its
`pons.reporting` timer measures `accounting.project`, while the caller also
performs Plane maintenance, Attempts maintenance and Pipeline snapshots.
Current discovery completed 710 operations and approximately 236,349 selected
SQL statements. These are observed aggregate counters, not per-query I/O proof.

`pons_maintenance_cost.py` uses the existing `pons_query_cost.py` fixture and
measurement helper. It builds actual Plane, Broker, Pipeline, Attempts and
MarketScout objects under admitted Scratch with all network disabled and no
financial books or authority. The explicitly synthetic fixture begins with
1,381 candidates, 4,096 observations/transitions and 4,096 evidence records,
768-byte padding and actual header-number cache shapes. Actual native
MarketScout acquisition uses fixed local public-log arrays, then calls real
Broker nomination. No provider or economic qualification is simulated as ready.

The largest reproduced I/O pattern is the native append-only debug-ring
retention read performed by `storage.audit_ring` after native nominations:

```sql
SELECT seq FROM transitions
WHERE candidate NOT IN (SELECT id FROM candidates WHERE NOT (lane IN ('pump','pons')))
ORDER BY seq DESC LIMIT 1 OFFSET 4095
```

The existing plan scans wide transition and candidate table rows. The exact
retention boundary alone reads approximately 7.06 MB per call in the synthetic
fixture; its inactive-candidate subquery reads approximately 2.84 MB. Updated
native nominations emit multiple audit transitions, repeating those reads.
This reproduces a plausible large discovery I/O cause; it does not establish
that this query accounts for all 375 GB observed on AWS.

In contrast, unchanged Plane maintenance reads 126 bytes per measured call;
peer-header-invalidated maintenance reads about 0.553 MB, Pipeline snapshots
126 bytes after the existing cache, full Plane retained-count snapshots
22.9 MB and pending Broker materialization 2.86 MB. Numeric-tip cache reads
about 0.041 MB despite its unindexed ordering. Attempts sweeping zero attempts
reads about 2.85 MB once due; no claim is made for an unmeasured attempt cohort.
Provider Budget reads remain run-scoped, and no large HTTP audit-table scan is
attributed to them. Constructor quick-check remains a distinct unmeasured
production-frequency question.

## Same-workload index discriminator

Three independent SQLite backups of identical native fixture state execute
the same eight batches of eight native observations. Only diagnostic ordinary
covering indices differ; no query or retention predicate is changed.

| Per eight-event batch | Existing | Candidate `(lane,id)` | Both plus transition `(seq,candidate)` |
|---|---:|---:|---:|
| Mean wall seconds | 0.068704 | 0.035024 | 0.020363 |
| Mean thread CPU seconds | 0.068682 | 0.035028 | 0.020365 |
| Logical read bytes | 272,336,512 | 78,921,857 | 462,465 |
| Read syscalls | 66,490.375 | 19,270 | 114.875 |
| Approximate SQLite VM steps | 1,198,250 | 1,198,250 | 1,198,875 |

All candidates, observations, transitions, watches, scout events and runtime
checkpoint tables have identical final logical hash:
`d915dd8cf4ce84deea02826026febae6fffa55e3c33906698c82ec3c343cbc8d`.
The VM workload remains essentially unchanged; covering access avoids wide
row-body/page reads. EXPLAIN uses both covering indices for the same native
boundary and candidate exclusion queries. No source histories, ACKs,
qualification, financial obligations or retention selection are skipped.

Actual diagnostic index sizes are 57,344 bytes / 14 pages for candidates and
151,552 bytes / 37 pages for transitions. Local creation costs were 1.13 ms and
2.17 ms. Total logical database size rose from 16,805,888 to 17,006,592 bytes
(some existing free pages were reused). These fixture costs are not AWS bounds.
The existing Plane constructor runs quick-check/DDL directly; Broker checks
cancellation around it. This repair supplies no new hard index-creation
cancellation bound and preserves the original startup/readiness deadline.

Final receipt: `/workspace/recovery-evidence/pons-maintenance-index-final-0c8.json`,
SHA256 `bc497029796b71ddd22925673260991fb47219cc37a0324f99843b62793ccf77`.
Original Plane source SHA256:
`586181911937141a4e87256f8f468c23308b51d3a712b6ded2f88d8962b9b773`.
CPython 3.12.14, local SQLite 3.53.1; AWS is SQLite 3.45.1. All physical reads
were zero in this local comparison. This is synthetic native query attribution,
not a production population, full-market capacity or AWS improvement claim.

Retaining wide scans preserves the demonstrated read amplification. Refactoring
retention accounting would introduce semantic and recovery obligations. Two
ordinary covering indices preserve all current operations and are the least
complex demonstrated correction. Validate exact-source guards, native
publication, append-only/paused-family retention, restart and plans on the
integrated pinned runtime, then measure one guarded funding-closed AWS rehearsal.
