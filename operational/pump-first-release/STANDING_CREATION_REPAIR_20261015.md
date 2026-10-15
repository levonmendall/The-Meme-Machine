# Creation cancellation and reporting work — 2026-10-15

Exact executable **4b70109db89382e050ceeebb77ac352509f9fc82**, branch
`repair/consolidated-startup-followup-20261014`. Owner standing
[issue134](https://github.com/levonmendall/The-Meme-Machine/issues/134) remains
active without a global start count, expiration or routine per-run approval.
The per-controller one-start and original safety limits remain unchanged.

The preceding [retirement result](STANDING_RETIREMENT_RESULT_20261015.md) remains
RECOVERY_REQUIRED: Pump exceeded TERM's 15-second lane wait and exited -9.
Its captured stack was `LocalPumpTape._creation` expanding up to 1,000 rich
economic bodies with `fetchall`, before inspecting creation. It was a read-only
native lookup; financial flatness never substitutes for native cancellation.

The existing `rolling_origins` receipt already identifies authenticated creation.
The correction uses that exact canonical identity, verifies its body hash, mint,
scope, kind, slot and market time, and keeps original availability. It reads one
body instead of unrelated subsequent trades. Legacy missing-origin and cold-body
CandidateHistory paths remain; legacy SQL streams the original ordered limit and
checks native cancellation between reads/decodes. Rollback failure cannot replace
the original cancellation. Caller-owned SQLite progress handlers are untouched.
This introduces no second writer, acquisition, coverage proof or schema change.
Disposable tests preserve a nonempty pending canonical outbox exactly after
cancellation and restart. A creation behind 1,001 later trades remains reachable;
an exact fixture with 20 later trades decodes 22 bodies via the legacy path and
one via its verified origin, with identical result. These are scoped operation
counts, not market-throughput measurements or a guarantee against every OS wait.

Pons spent .678 CPU cores in the prior post-reconciliation interval, with a
natural stack inside `provider_totals`' full endpoint telemetry. Counter-only
reporting now reads the same fresh native session counters. It preserves the
32 completed sessions, missing/None behavior and legacy telemetry protocol.
An actual disposable context/RPC/admission regression measures the previous
endpoint snapshot, cache scan, at least two DB openings and 16 CU-schedule reads;
the same totals now require zero DB/schedule reads. Full health and fresh
authoritative admission are unchanged. Existing telemetry already bounds its
audit queries; this is not a claim that it scanned canonical market history.
No whole-process CPU reduction is yet established.

The controller now binds final stop evidence to the observed supervisor/native
PIDs, process instances, current run, clocks and exit records. Killed,
nonterminal, unreconciled, missing or stale evidence forces RECOVERY_REQUIRED
even when the process group is empty and money unchanged. A clean result means
only current native workers stopped; it is not global recovery, usable evidence,
readiness or capacity. The prior raw result is immutable.

Network-blocked validation used pinned CPython3.12.14 / SQLite3.45.1 and the
supported contained runner, one testing owner. Initial reproduction: two expected
failures. Focused corrected checks:21 PASS. Combined actual startup rehearsal,
native lifecycle/cancellation, controller, provider, canonical closure,
thread ownership and CandidateHistory modules:246 PASS in50.809s. Final13 PASS
in21.635s cover the final diagnostic-clock bound, exact pending identity/restart
fixture and four exact economic/source guards. The final small clock/test
refinements postdate the 246-case run; its unchanged surrounding proofs remain
valid. Fixture-construction errors and a misnamed test selector are preserved;
they were corrected, not presented as passing runs. Source pins name the exact
reviewed operation/function; all economic siblings and original package guards
remain. No full FAST or general release PASS was claimed.

All log identities are in [the evidence index](evidence/standing-creation-repair-20261015.json).
The six active opportunity-access changes, original nine economics, volume-quality
behavior, $1,000 epoch and historical $500 were not changed. This engineering
checkpoint issued no provider calls or authoritative writes and started no PAPER
service. Installation is still clean66f85d61, stopped/disabled/Restart=no, funding
closed until controlled cutover and fresh preflight.

The updated [standing specification](STANDING_OPERATIONAL_RESOLUTION_NEXT_RUN_20261015.json)
pins this exact candidate, fresh private output and unit/environment/controller
identities. Its next discriminator is actual native cancellation plus measured
Pons process cost and current Pump pre-persistence backlog after restoration.
Run only in a natural backup-free window after fresh financial, native pending
work, exclusive ownership, recovery-reference, access and resource checks. Do not
count diagnostic minutes, equate source heads to complete strategy consumption,
or infer held quote/USD protection from flat operation. Persistent capacity,
native replay semantics, original BUSY, Pons READONLY and backup/protection remain
independent blockers. Use measured results to choose the next intervention;
never repeat unchanged failed conditions.
