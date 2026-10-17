# Bookless native Pons Current construction

This is a contained diagnostic capability, not PAPER readiness. It does not
exercise held positions, fills, settlement, capital reconciliation or financial
handoff. Those outcomes are explicitly `UNEXERCISED` and authoritative readiness
is false. No financial book, copied epoch or fabricated positive replay is used.

The actual cohort `run(endpoint, campaign=True, native_resources=cap,
native_ports=ports)` requires the exact parent-issued Current `SourceReference`.
The only provenance string used inside the native broker/history is
`alchemy:<parent endpoint identity>`; physical reads use exact `ChildRPCPort`s.
The discovery, Current and Survivor source capabilities and genuine Nitro clock
are mandatory before any native store opens. Missing physical capability refuses
startup; a sampled RPC clock cannot replace the native Nitro stream.

The fixed bootstrap must configure these module globals before starting the owner
thread: `ROOT=cap.root/'pons-current'`, `REPORT=ROOT/'report.json'`,
`SKILL_DB=ROOT/'pons-selective-wallet-skill.sqlite'`,
`PROGRESS=ROOT/'cohort-progress.json'`, `ROWS_LOG=ROOT/'candidate-rows.jsonl'`,
`QUALIFIERS_LOG=ROOT/'qualifiers.jsonl'`,
`PROVIDER_LOG=ROOT/'provider-sessions.jsonl'`, and
`RECOVERY_LOG=ROOT/'sequencer-recoveries.jsonl'`. Composite operation is required.
Money environment configuration is rejected. This loop owns its actual Pons
Survivor worker; the bootstrap must not create a second Survivor for the lane.

The native implementation retains discovery pacing and recovery, chain proof,
Nitro parsing and canonical range backfill, scout publication, bounded startup
coverage, native evidence contexts, immutable receipt/header caches, wallet skill
history, concurrent discovery/hydration/Survivor work, durable qualified results,
native Attempts, opportunity history, outbox projection and checkpoint-before-ACK
ordering. The existing isolated admission gate executes after qualified
publication and before entry-confirmation, controller identity or lifecycle
submission. Financial recovery, lifecycle executors and capital readers have no
scope in this run. The shared owned Plane is borrowed by Broker/checkpoints;
closing the Current broker cannot close the concurrent Survivor's Plane.

Fresh authenticated sizing receipts preserve real positive qualification sizing.
They retain the underlying five-second Pons valuation expiry; an explicit parent
must refresh them. Stale sizing refuses the candidate through the ordinary
boundary path. It never becomes zero qualification budget or allocation authority.
A native checkpoint and shutdown evidence remain writable after sizing expires.

An own-scope marker is required to restore checkpoints. Foreign epochs, financial
continuation markers, unexpected qualifiers/lifecycles and changed policy are
refused. No old production callback or historical evidence is imported or settled.
The ordinary finite native shutdown drain and original task clocks remain in use;
partial construction closes only private native owners on their owning thread.

Offline evidence for this slice: 9 focused startup/ownership/native-discovery
cases pass; the combined bootstrap/admission/reporting/worker scope passes 49
cases. Existing campaign and candidate-plane
modules pass 19 cases. Native finalization plus those two modules ran 93 cases:
92 pass and one environment error, not a suite pass. The exact failing case is
`tests.lanes.pons.test_pons_finalization.PositionAdmissionTests.test_full_candidate_queue_cannot_refuse_an_imminent_position`;
it refuses at `provider_clock.current_identity` because this Cloud environment
cannot stat `/proc/self/ns/time`. Receipt: `/tmp/mm-engineering-16kc_lth`.
The same case fails on unchanged pre-isolation source
`2379403abb0faaceaec4650195c158e501c5d799`, receipt
`/tmp/mm-engineering-b0r3irhu`. No production clock guard is weakened.

A real parent Nitro adapter, source-owner orchestration, authenticated sizing
producer, kernel containment, integrated native cancellation/qualification run and
bounded live validation remain separate prerequisites. These component tests do
not establish live processing parity, market speed or financial protection.
The parent RPC context currently skips child `MM_RPC_CAPABILITIES` input, so an
authenticated parent batch/receipt capability profile is also required before
claiming the same optimized production provider request shape.
