# Coordinated processing and source recovery repair

Executable **a793bd580593a87d17a0ab6e5e8581943bec6886**, branch
`repair/consolidated-startup-followup-20261014`, draft PR133. This continues
from f52be1e under the owner's resumed scope and standing issue134. The original
owner-review report, failed observations and RECOVERY_REQUIRED outcomes remain
unchanged. Root is the integration, test and runtime owner.

## Implemented corrections

The measured scout callback repeatedly selected market fields, lifecycle state
and consumer pins for every locator. A bounded explicit view now supplies those
reads within the existing atomic owner command. Each ordered mutation updates
that view; it never survives the command or supplies economic authority. Every
observation, activity receipt, reactivation, outbox identity and priority remains.
Canonical JSON is hashed once rather than serialized again for its checksum.

Event-outbox allocation reads existing identities and canonical availability in
bounded groups, then allocates the original monotonic sequence once. Replays and
duplicates consume no sequence. The transaction, immutable conflicts, native
order, original availability, exact consumer receipt and ACK contracts remain.

Maintenance reuses its freshly read retention fences within one read-only owner
observation. Archive planning reuses identical candidate/slot pin checks within
its bounded page. Archive application still checks current ownership and pins
before changing a pointer. No cadence, maintenance deadline or quota was reduced.

The actual Pons shared-scout path nominated each event immediately and again in
two later loops. Those loops also repeated plane maintenance for each event.
There is now one immediate durable nomination at the original receipt time and
one projection after the returned cohort, before qualification. Standalone
discovery retains its single nomination. A returned older cohort cannot overwrite
a newer claimed generation or renew its five-second qualification deadline.

Source shutdown now closes intake, settles received handlers, and keeps existing
commit workers alive until their producers finish and accepted queues drain.
The same ownership applies to reconnect and filter replacement. A late failed
committer releases blocked producers through explicit failure, never a false
task-done. Original exceptions survive cleanup. Partial joins retain exact gaps
and unfinished CONTROL acquisition ranges through restart. Only newly validated,
contiguous coverage can reduce the latter obligation; no coverage is fabricated.
The original 256-slot overlap and shutdown bounds remain unchanged.

Current PID, unique run identity, clocks, accepted/committed/pending counts and
unresolved history/proof obligations survive terminal publication and collection.
`DRAINED` describes completed accepted queue commits and accounted partial joins;
it does not mean all historical coverage, proofs or strategy readiness are done.
Fatal writer/storage failure remains RECOVERY_REQUIRED. There is no new raw-frame
spool or claim that unavailable replay can always recover arbitrary raw frames.
Previously durable unsealed CONTROL receipts with an older session remain a
separate recovery limitation; their coverage is never asserted by this change.

## Evidence and validation

The [hashed evidence index](evidence/coordinated-pipeline-validation-20261015.json)
retains scope, exact private artifacts and failure dispositions. On 64 authentic
retained scout projections, separate fresh disposable stores produced identical
rowids and durable contents. Selection reads fell **586→3**, statements
**1064→481**, with one commit in both. Three alternating untraced pairs measured
median component CPU **22.147→15.401 ms** and wall **23.110→16.448 ms**. This is
not historical market replay, concurrent capacity or a whole-machine percentage.

The actual Pons broker/scout/plane fixture uses 32 synthetic events: nominations
**96→32**, maintenance **33→1**, SELECTs **1134→470**, BEGINs **195→68**, with
matching durable candidates, watches, transitions and reporting stages. Scoped
CPU was 101.128→52.933 ms; traced fixture timing does not establish provider or
market capacity. Two-scope maintenance reads fell **118→102**. Archive planning
reused **33** identical checks across 41 examined rows; mutation checks stay fresh.

Final exact-candidate targeted integration: **230/230 PASS, 34.214s**, attribution
enabled, including actual integrated startup, source drain/restart/failure,
native replay, cancellation, owner hooks and diagnostic collection. Related
maintenance **68/68**, Pons/controller **115/115**, affected exact economic/source
guards **5/5**, owner/drain **40/40**, archive correction **2/2** passed. These
counts overlap and are not summed. No complete FAST or OPERATIONAL was dispatched.

Earlier combined 361-case validation had 358 passes and three errors: an archive
cursor variable shadow, rethrow of an already handled native retry, and a no-owner
census fixture missing the new control-query result. Corrections and affected
reruns passed; that run remains FAILED. Earlier source-guard nesting failures and
the original drain boundary assertion remain preserved. The first new preflight
helper rejected Pons's retained `already_exited` event by expecting only
`wait_completed`; its original independent STOPPED/reconciled/TERM/exit0 proof
remains valid. No dispatch followed that verifier failure.

All six opportunity-access changes, nine original economics, volume-quality
attention and four independent native regimes remain active and unchanged.
Meteora/Ramses remain paused. Focused success is not a release or operating PASS.

## Next guarded measurement

Use [the exact-source specification](COORDINATED_PIPELINE_NEXT_OBSERVATION_20261015.json)
only after fresh financial/native, ownership, provider, resource, recovery,
backup non-overlap and actual service-user checks pass. No competing tests,
profilers or providers. Preserve funding closed, disabled service and Restart=no.
Readiness remains 300s; diagnostic startup up to 900s and measurement up to 300s
remain inside the original 1800s work/1865s absolute boundary.

The question is whether these coordinated changes reduce owner/Pons costs and
improve the complete current-generation commit→history→ACK→proof→strategy path.
Segment rates across native reconnects: a prospective head jump is not catch-up.
The prior reliable slice was 3.711 CONTROL-proxy units/s versus 1.509 durable
head units/s, backlog 1321→1748 and evidence age 354→483s. It is an unmatched
market interval, not a controlled baseline or independent full-market arrival.
No current whole-machine improvement or two-CPU sufficiency is established yet.

Afterward independently verify native worker shutdown, the current source census,
retained pending identities and monetary reconciliation. Keep source/configuration
rollback stopped if older code cannot consume a new pending recovery obligation;
never rewind databases or discard that obligation to make rollback appear safe.

Original SQLite BUSY, Pons READONLY, missing/stale USD, held-position 3s/5s
protection, provider replay semantics and usable program publication remain
separate. Backup requires at least another 7.752 GB just for the known canonical
copy and reserve, excluding other state/WAL and isolated restore. Failed backups
remain unusable, and process-wide freezing has not proved protection compatibility.
No infrastructure purchase, recovery copy, timer change or acceptance occurred.
