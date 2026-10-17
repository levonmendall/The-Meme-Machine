# Parent physical-head lifecycle component

This is a future isolated-harness component based on `689ef65d`, not a change to
the installed operational candidate or a deployed measurement. The explicit
parent-only entry is `ParentChannel.start_head_measurement(approval, image)`.
There is no environment trigger, child verb, new source alias, privileged path,
financial constructor or readiness authority. The caller must already hold the
original protected parent startup and financial fences; this component neither
acquires those fences nor substitutes a boolean attestation for them.

The existing authenticated `NativeImageApproval` supplies the expected source.
The real parent's clean checkout must match that candidate's complete Git
identity through `source_objects`; no predecessor SHA is embedded and the
current HEAD is never independently blessed. The existing copied-image verifier
checks the actual manifest/files. The image commit/tree/requirements and complete
application file mapping must match the same approval. This is not an assertion
that the image has executed or that OS containment has passed.

Ownership binds actual parent PID/start ticks, the original provider clock
domain, the exact ParentHTTP/source objects and the actual ParentChannel session.
The 43-character session is exported unchanged as `PARENT_TRANSPORT_SESSION`.
An observed ownership/generation/clock change stays invalid even if an earlier
value returns. Pons's actual Admission session is retained separately, with its
original meaning. Neither it nor the transport session impersonates the child's
opaque `_SourceGeneration`; `canonical_source_generation` remains unknown.

The optional ParentHTTP hook sees original socket response rows, request IDs and
physical start/completion clocks after native envelope/public-data validation,
before normalized child handoff. It matches batch members by original ID,
reuses already purchased `getGenesisHash`/`eth_chainId` successes to establish
mainnet/4663, and latches a contradictory identity response. A cached child
result or serialized parent handoff cannot renew these clocks. Numeric historical
headers, non-finalized Solana reads and sequencer messages are not captured as
the requested head kinds. Latest and finalized Pons remain distinct.

There is at most one pending owned refresh attempt per chain. Automatic workers
wait for an existing physical network proof. Solana refresh requires the exact
existing `pump_history_receipt`/`solana_evidence_2` binding with `getSlot`; Pons
requires the existing native `pons_discovery` binding with
`eth_getBlockByNumber`. Missing or ambiguous capabilities stay unavailable.
Requests use only the original ParentHTTP demand/execute/release path and shared
worker capacity, Budget, Governor/Admission, fixed work contexts, deadlines and
429 debt. No identity call, retry, replacement allowance or catch-up burst is
added. An admitted attempt schedules its next opportunity five seconds after
completion; a fresh passive head suppresses a purchase.

Refresh attempts have dedicated owned tasks, so sampler stop cannot cancel a
shared caller task or an unrelated native leader. A caller's actual cancellation
still cancels and joins its own accepted attempt before propagating. Startup
retains each scheduled task before scheduling the next; failure keeps the
partially constructed owner published for cleanup and refuses a duplicate start.

ParentChannel signals sampler stop before its original native/content drainage.
Only an explicitly enabled head owner adds its tasks to a common bounded 65-second
join; HTTP cleanup uses that same deadline rather than a second grace interval.
An incomplete join retains the original owners/tasks in `NativeOwnerDrainFailure`
for the existing fatal outer-owner process contract. The library does not kill a
process, daemonize a worker, close another owner's resources or claim stopped
before its tasks join. The default channel path and child protocol are unchanged.

The fixed public projection is at most 4 KiB. Immutable binding provenance is
deduplicated, with full first/latest coordinates and physical clocks retained.
An oversized complete projection is unavailable rather than clipped. Head values
are provider coordinates, not an economic workload denominator. Economic arrivals,
canonical coverage, canonical source-generation correlation and normal readiness
remain unknown/false. This is no full-market speed or one-hour PAPER acceptance.

Validation uses actual disposable Budget/Governor/Admission and offline physical
HTTP fixtures. Positive source fixtures explicitly replace only the checkout
guard; actual copied-image bytes/manifest validation runs, and a real wrong-source
checkout is refused. No live source approval or image execution is claimed by
those fixtures. Focused cases cover source/image mismatch, response-ID ordering,
network/head kinds, sticky generation/process/clock changes, stale pacing,
physical failures/429 uncertainty, capacity without leader cancellation, owned
startup failure, admitted cancellation and incomplete drain. Failed fixture and
projection-bound receipts were preserved during development. Final scoped test
results are **18 focused cases PASS in 7.727 seconds**, plus **82 adjacent parent
transport, existing head, sequencer-clock and child-transport cases PASS in
2.411 seconds**. Those adjacent paths do not activate this new optional owner;
their runtime files were unchanged by the final owned-attempt wrapper correction.
An earlier combined 98-case checkpoint also passed before that correction.
These are scoped offline proofs, not a full release suite or live acceptance.
