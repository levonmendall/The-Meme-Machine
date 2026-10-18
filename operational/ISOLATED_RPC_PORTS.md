# Explicit native RPC ports

These opt-in constructor hooks preserve production defaults. They do not start a
native harness. They require the exact owned `ChildRPCPort` from the already
connected parent channel, and use its frozen `SourceReference` directly. There
is no invented URL, URL parsing fallback, credential, child Governor/Admission,
copied quota ledger or financial capability on this path.

Pump factories accept `parent_port`, `shared_reads` and `evidence_broker`.
Construct `ImmutableReads(private_path, endpoint_identity=port.source.endpoint_identity)`
and `EvidenceBroker(private_path)` explicitly. The existing immutable read,
broker, cache, batch, budget, retry and decoding algorithms remain active. The
source hash must match the port, both caches must be actual native classes on the
same explicit path, and inherited environment paths are not consulted. Native
in-process adaptive pacing remains; the original physical Governor executes in
the parent. `governed_sol_http` only bypasses a child Governor after validating
the exact port's channel/source ownership.

Pons `configured_rpc` and managed `configured_discovery_rpc` accept `parent_port`
and an explicit `immutable_store=EvidenceStore(private_path)`. The actual native
PacedRpc, Reuse, RPC scalar/batch decoding, logical scope/session budgets and
chain verification remain. The parent port supplies real logical demand and
activity markers, including RPC cache hits. It selects canonical authenticated
HTTP explicitly; it does not impersonate the public observation route. The
isolated Reuse namespace hashes the genuine endpoint fingerprint rather than a
credential-bearing URL. The store is independent, and its real cache rules are
unchanged. Telemetry identifies parent control rather than fabricating child
physical-provider counts.

`SelectiveEvidenceContext(None, parent_port=port, immutable_store=store, cache=cache)`
preserves its original memory caches, bounded batches and session rotation. Each
new actual RPC session earns its chain proof. Ordinary callers retain the exact
existing endpoint construction and capability-file behavior.

On the combined source, 67 IPC/native-hook/parent/bridge cases passed in 3.417
seconds. Nine adjacent native RPC/provider/cache modules ran 102 cases in 10.820
seconds: 100 passed, one existing skip, and one environmental failure. The
failure was `ProviderAuthorityTests.test_process_death_preserves_unresolved_physical_attempt`:
the spawned Python cannot stat `/proc/self/ns/time` in this managed worker, so it
stops at the unchanged provider-clock guard before its requested crash point.
The identical case/cause was independently reproduced on baseline application
`0c8e9beae8eed6e4579f4473c4f449f711fb5691` in 0.165 seconds. Retained scopes are
`/tmp/mm-engineering-61t1u896` and `/tmp/mm-engineering-irran8gu`. The outer tests
use the existing explicit offline clock-domain fixture; no runtime clock guard
was weakened. Offline physical transports and real SQLite accounting were used;
no provider calls or AWS workflows were executed.

Still required: source-authenticated OS confinement, actual producer/bootstrap
integration, multiple simultaneous native stream instances, the native Nitro
sequencer feed, exact per-role scheduling assignments, public capability-profile
facts bound to the parent source, full native qualification/owner FULL/ACK paths,
replay and live resource/capacity validation. RPC parsing/IPC overhead also needs
measurement in the identical before/after harness. Capability-file optimized
quote/batch features are not inferred from unavailable child credentials or
implicitly borrowed from production paths. Held/fill/settlement work remains
unexercised. These hooks establish none of authoritative PAPER readiness,
production-equivalent complete workload parity or the one-hour acceptance.
# Pump logical demand follow-up

The explicit Pump parent path forwards original logical calls before native
short-lived or immutable cache access. A ContextVar scopes one caller across
the mixin/base/batch and scalar retry layers, so cache hits stay visible and
physical retries do not duplicate the logical demand. Parent purchases retain
the same fixed source work labels. Solana Governor remains a physical admission
controller; this does not invent a new durable governor demand table. Pons keeps
its existing durable logical-demand accounting. Default calls without an
explicit port keep their original behavior. Actual parent ledger regressions
prove two scalar immutable-cache consumers with one HTTP request, and four
batch consumers with one two-element physical batch.
