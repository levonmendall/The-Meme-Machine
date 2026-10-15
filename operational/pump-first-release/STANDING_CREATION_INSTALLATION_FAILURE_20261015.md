# Service-identity source-access failure — 2026-10-15

**RECOVERY_REQUIRED; acceptance 0.** Exact attempted executable:
`4b70109db89382e050ceeebb77ac352509f9fc82`. The funding-closed controller ended
after **20.199 seconds**, `SUPERVISOR_ENDED`. Its original result is preserved.
Readiness was never established; the result's null readiness field is not a
300-second timeout or PASS.

The actual service identity failed the existing pre-supervisor source guard:
`git rev-parse HEAD` returned **128**, reporting that the linked worktree was not
a Git repository. Root's checkout had rewritten linked-HEAD ownership/mode;
new commit-pack metadata and tracked source files were also inaccessible to the
service. The diagnostic-directory access check did not cover complete source/Git
identity access. This is a demonstrated installation/preflight defect, not a
Pump throughput, native SQLite or provider-capacity result.

Failure occurred before the supervisor constructor. No native worker or market
provider workload started and no application-state write was performed by the
failed start. `drained=true` only describes the empty unit/process scope;
`native_drain=UNAVAILABLE` remains unchanged. Neither this empty start nor an
unchanged monetary ledger proves native drainage or repairs the preceding Pump
SIGKILL failure. No creation-restoration optimization was exercised live.

Retained corrections enumerate only the linked-HEAD metadata, three fetched Git
pack files, affected tracked source files and source directories. Their contents
are unchanged; no database, credential, economic-state or evidence permissions
were altered. Actual service-user Git identity passed after the HEAD correction.
A repeatable pre-dispatch service-user source-identity probe is under development;
no successor executable or focused-test PASS is asserted in this handoff.

The bounded post-check recorded **22 VERIFIED checks, 329 indexed queries in
0.178 seconds**: $1,000 cash, exact unchanged head **9,660**, zero eight-category
monetary obligations, historical $500 and all four active v1/financial-genesis
bindings preserved. Current five ACKs/27 pending records and preceding cohorts
remain intact; owners/leases are inactive, writer lock unheld, provider
reservations zero. These are scoped current-state facts, not a whole-store
integrity scan, native recovery completion or operational PASS.

Separately, the scheduled 04:01:56 backup failed with `ArtifactStorageFull`,
`snapshot_id=null`; it did not create a usable new recovery point. Original
failure and journal receipts are retained by reference. Keep that issue open
and retain the existing verified reference. The natural backup window was awaited
without changing timers; no overlapping backup/PAPER workload was started.

At 04:07:53 UTC, compatible clean `66f85d61bf4d3ba9a01efdc0e9eb68949419bda8`
and the two saved small overlays were restored without database rewind, policy
history deletion or counter reset. PAPER is stopped, disabled, `Restart=no`,
funding closed. Do not launch the restored historical finite overlay unchanged.

Next: complete the actual service-identity source-probe correction, validate its
failure-before-start behavior offline, and repeat fresh source/access/recovery/
backup/resource preflight on its finalized candidate. Preserve the six active
opportunity-access changes, nine economics, volume-quality behavior and all hard
protections. Sustained throughput, managed held protection, the previous Pump
cancellation failure, original SQLite faults and backup compatibility remain
independent unresolved issues. No routine attempt-count approval is required
under [standing issue134](https://github.com/levonmendall/The-Meme-Machine/issues/134),
but no unchanged retry or unsafe start is justified.

Exact original artifacts and correction receipts are referenced by hash in
[the evidence index](evidence/standing-creation-installation-failure-20261015.json).
No test, database operation, provider request or service action was performed to
write this handoff; no retained evidence was copied or overwritten.
