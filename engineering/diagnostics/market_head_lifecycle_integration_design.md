# Native head measurement lifecycle integration proposal

Design only. The measurement implementation is frozen at `6f288ba7`, based on
application main `92831be8`. The isolated integration inspected here is
`ec042023`, with the original physical parent in `operational/parent_transport.py`
and fixed child executor in `operational/isolated_native_source.py`. No runtime
activation, schema, census, source permission or financial gate changes are made
by this document. The adjacent EOF accounting repair is separately frozen at
`3a2352ee`.

## Two real owners; no child claim of physical acquisition

Production source HTTP runs inside `runtime.evidence_worker.RepairRPC` and Pons
`provider_topology.PacedRpc`. Those are the existing attach points in `6f288ba7`.
The isolated child instead has secret-free ports and no Governor or local
Budget. Its serialized parent handoff is not the provider socket response. Thus
the parent physical transport must own isolated head capture and refresh; do not
broaden `MarketHeads.attach` to accept an arbitrary child response dictionary or
manufacture a URL/Governor in the child.

`ParentHTTP._physical` is the exact isolated capture point: timestamp socket
completion, validate the original response IDs/envelope and `binding.public`,
then observe only successful exact head members before JSON normalization and
`Delivered(clean, True)`. Physical bytes remain the original Budget/purchase
counters. Batch ID matching must use the original IDs, not response-list order.
Ignore numeric historical headers, cached child replies and sequencer clocks.

Parent capture needs a narrowly typed `ParentHTTP`/`SourceBinding` adapter to the
measurement validator. It must accept only the configured bindings already owned
by that exact ParentHTTP instance, verified code/image identity, its actual
process/clock identity and its active ParentChannel session. It does not accept
child-issued network verification. Observe original physical `getGenesisHash`
and `eth_chainId` successes in that parent instance to establish mainnet genesis
and chain 4663 for each immutable provider identity; a mismatching response
invalidates the measurement. Reuse those already purchased identity calls.
Before such a proof exists, head state is `UNAVAILABLE`, not an assumed network.

## Exact generations: preserve their different types and meanings

| Execution path | Existing binding | Required lifecycle rule |
| --- | --- | --- |
| Production Solana | `ServiceState.fence.session`, used by `MaintenanceRuntime.generation` and `admission.generation` | Bind after storage recovery assigns the actual generation; compare the live admission generation on every sample and refuse changed/retired generations |
| Production Pons | Supervisor-issued `MM_LANE_PROCESS_INSTANCE` (32 hex), checked with PID in lane health | Label it `LANE_PROCESS_INSTANCE`, not an economic candidate generation; retain actual provider Admission session separately across ordinary RPC-session rotation |
| Isolated parent transport | `ParentChannel.session` (43-character token), exact session already bound to FD3 and FD4 facts | Label it `PARENT_TRANSPORT_SESSION`; preserve its exact value and parent PID/start/clock identity, without hashing or truncating it into a pretend native UUID |
| Isolated child source | Native owner fence session inside `serve`; source command readiness returns an opaque `_SourceGeneration` | Export an explicit fixed source-owner receipt from the actual owner lifecycle if correlation is needed; never serialize `repr`, object `id`, or infer an owner generation from a ready boolean |

The frozen implementation accepts a 32-hex generation. A follow-up must add a
small typed generation binding for the first three rows, rather than relaxing it
to arbitrary strings. Pons `source_artifacts.REGISTRY.generation` is an integer
cache invalidation generation; it is not a process UUID or a candidate cohort
generation. Report it separately if useful. No source epoch is fabricated to
fit the current constructor. Parent image identity comes from the verified
copied-image manifest; a copied image has no Git checkout and must not run
`verified_checkout` against `/image/app`.

For production, the existing protected administration request already verifies
commit/tree before starting the service. Pass that same secret-free expected
identity through the existing child environment construction, then run the
bounded clean-checkout check in the actual source/lane process. Do not read the
current HEAD and call it independently approved. Missing expected identity makes
the optional measurement unavailable; it grants no new start/source authority.

## Production lifecycle and shutdown hooks

1. Solana: add an optional descriptive measurement owner to
   `evidence_worker.main_async`/`serve`, using the existing installed Budget,
   RepairRPC and stop event. Initialize the collector at the source-start barrier
   after `storage_ready` and actual `admission.generation`, before the guarded
   `SelectiveSource.run` begins. Passive hooks capture already paid head reads.
2. Pons: the `operational.lane` owner creates one collector for its original lane
   process instance after the native startup gate. The optional refresher owns
   its own ordinary `configured_rpc` session; it never borrows a decision or
   protection client's mutable deadline. A small process-local attachment hook
   in the existing configured canonical factories can passively observe the
   actual Current/Survivor/discovery clients. Attachment failure is descriptive
   and cannot alter a native RPC result or route.
3. Each enabled chain owns one named non-daemon worker, outside the shared
   default executor. Existing native singleflight/cache semantics remain. Head
   refresh has one in-flight attempt and completion-based five-second pacing;
   fresh physical receipts suppress it. There is no extra retry or quota.
4. Signal the same existing stop before source/consumer drainage. Join the head
   worker within the existing shutdown deadline while original accepted work
   drains. Do not place optional refresh tasks into the source's
   `FIRST_COMPLETED` producer set: a refresh deadline must not terminate the
   economic source. Do not queue a blocking join behind the shared default pool.
5. Mark the collector stopped and publish its retained last physical receipt
   only after joining. A live measurement worker makes cleanup incomplete; use
   the existing typed unsafe-stop/outer process guard rather than daemonizing,
   closing another owner's resources, adding shutdown time, or claiming PASS.

No head freshness value changes financial/native readiness, source ACKs or
historical-completion flags. Ordinary startup and held-position protection keep
their existing order and deadlines. No extra provider purchase precedes the
applicable original startup admission.

## Isolated parent refresh and terminal ownership

The actual future parent session owner, not FD3 request data, enables optional
head refresh. Use existing fixed method/operation/read-class bindings already
present in its SourceBinding map: Solana `getSlot(finalized)` under the original
history-evidence priority, Pons `eth_getBlockByNumber(latest,false)` under an
ordinary non-position evidence operation. If those exact capabilities are absent,
report `UNAVAILABLE_CAPABILITY`; do not infer them from another alias or add a
held-priority route.

Create parent-local attempts through `ParentHTTP.execute`, preserving the
original Budget, Governor/Admission and parent cancellation/deadline handling.
The local owner must preserve an honest fixed work label and session, unique
attempt tokens and the original bounded worker capacity. It must not fake a
child wire request or bypass `_binding`. At most one scheduled attempt per chain
can be pending; capacity/429 denial yields unavailable, without catch-up.

Parent `ParentChannel.aclose` already owns cancellation, retained content and
stream cleanup followed by `ParentHTTP.aclose` joining accepted physical work.
The future session owner signals refresh stop first and joins these optional
tasks as part of that same existing closure. Child's 900-second observation,
original 300-second startup, 65-second drain and outer execution limits remain.
No unified ParentSession run owner/projector is present in the inspected branch:
that small integration must be implemented explicitly, rather than claiming the
transport class alone activates the measurement.

## Fixed telemetry and acceptance limits

Production Solana can place its fixed snapshot inside the existing
`RepairRPC.telemetry()` -> `service_health.repair_http` publication, so no new
SQLite writer/transaction is created. This owner-queued publication can be late;
it must preserve original physical clocks. Pons can supply its fixed snapshot
to the existing `NativeHealthPublisher` heartbeat/atomic health file, preserving
lane PID/process-instance checks. No new per-event log or sampler is needed.

The existing combined diagnostic's `pipeline_sample` currently excludes
`repair_http`, and generic `numeric()` removes the required provenance strings.
Add an explicit fixed head projection instead of passing it through that
numeric filter. Read only the existing selected health row, within the original
input/time/output bounds. The isolated parent owner projects its own collector
directly alongside existing `Budget.snapshot`/purchase summaries; child progress
cannot renew a parent measurement's age.

Reserve at most 4 KiB for a compact projection of fixed head kinds, source and
provider provenance, first/latest coordinate and physical clocks, actual age,
state/fixed reason and discontinuity/refresh counters. Deduplicate shared source
metadata, never clip authentication fields to fit. If the complete fixed shape
cannot fit, mark the whole measurement unavailable. Validate PID/start,
generation and the original clock domain before subtracting monotonic clocks;
sampling or publication time cannot turn an old physical response fresh.
Retained exact-profile readers need the same explicit first/last projection and
continuity rules, preserving their existing artifact bindings and 32 KiB result
bound. Missing old-profile fields remain unavailable.

Any displayed difference from a Solana program frontier is a slot-coordinate
gap, not economic backlog. Pons may compare latest only with actual canonical
`pons_scout_market_cursor`/boundary and minimum active-pool cursor with original
gap checks; a sequencer message or conditional source clock is not that cursor.
Economic arrivals, complete economic workload and economic backlog remain
explicitly `UNKNOWN` until the separate closed-cohort census design is
implemented and proven. A successful head collection window is no one-hour
acceptance or full-market throughput result.

## Bounded implementation slices after design alignment

First integrate the frozen observer and EOF repair without activation. Then
add typed generation/parent physical capture plus fixed provenance projection,
with offline original transport fixtures. Next add the two explicit lifecycle
owners and joined cancellation under existing startup/shutdown tests. Finally
enable the descriptive measurement on one exact-source diagnostic candidate
through its existing authorized controls; retain unavailable values honestly.

Required focused cases include actual native generation/rotation, source/image
mismatch, parent physical versus normalized handoff identity, already paid
identity proof, wrong-chain/finality, stale projection and queued publication,
two simultaneous native clients with one refresh, bounded worker saturation,
429 debt, cancellation during admission/body/accounting, original EOF uncertainty,
startup failure cleanup, source failure while refresh is pending, incomplete
join, and old/oversized/discontinuous retained projections. No provider traffic
or full suite is part of this design-only artifact.
