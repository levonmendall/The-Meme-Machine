# Trusted native stream component, protocol v2

This is local, offline-tested transport work. It is not selected by production
startup and does not establish authenticated isolation, native-harness parity,
AWS validation, readiness or financial authority. The previous component notes
in PARENT_NATIVE_TRANSPORT.md describe its original protocol; this document
supersedes the native stream wire and source-reference schema.

The exact hello protocol is `native-parent-transport-v2`. Its sources contain
only alias, family, endpoint_identity, operation, read_class and authenticated.
`read_class` is `native` or a fixed parent-issued `solana_evidence_1`,
`solana_evidence_2`, `solana_evidence_4`. The latter reconstruct original source
repair priorities and impose the original eight-second whole attempt bound in
the parent. There is no held-priority zero capability or child deadline field.
The parent-selected method allowlist still controls getBlock access.

Each hello stream descriptor is exactly alias, transport, stream,
observation_only and endpoint_identity. A null stream advertises a fixed source
open capability; an opaque stream is a preopened parent instance. The kinds are
yellowstone, solana_websocket and robinhood_sequencer. `native_open` accepts an
alias and returns an operation token; its terminal poll returns an opaque stream
instance only after the original Budget reservation and actual transport open.
`native_read`, `native_write` and `native_close` accept that stream instance,
never a child-selected endpoint or extra alias. Concurrent Yellowstone control,
scout and candidate subscriptions can consequently share a fixed source role
without sharing their individual original reservations or reads. Every native
content reply binds its stream instance. A stale handle cannot affect a later
reconnection. Control operation tokens disappear after the terminal poll;
content tokens disappear after exact offset/hash final handoff ACK.

The hello publishes maximum_streams derived from the original profile's native
inflight bytes, capped at 32. Actual Budget.stream_open still applies every
individual transport reservation and existing global spend, bytes, opens and
reconnect limits. Closed instance handles are retained for idempotent close,
with at most 1,024 lifetime instances per bounded channel. Completed stream
objects release raw transports, buffers and SQLite readers. Operations are
bounded by twice the stream capacity plus HTTP workers and eight control slots.
There is no server mutex across physical I/O.

Robinhood sequencer support uses the original sequencer_feed._WebSocket in the
credentialed parent against its fixed mainnet public feed. It preserves native
handshake/framing, pings, UTF-8 and permessage-deflate processing. No sampler or
second websocket library is substituted. Decompression now bounds output before
materializing it, using the original frame ceiling. The fixed feed is always
observation-only, while canonical economic evidence remains the source-bound
Pons RPC's responsibility. Child writes to this feed are forbidden. A dedicated
owned worker reads the original SDK; shutdown interrupts the socket and joins
accepted work before releasing it. Idle socket timeouts retain the same read and
reservation. Resolver timing and actual public-provider compatibility remain
unvalidated offline.

The original Budget accepts robinhood_sequencer as a native transport with the
same five-frame reservation as its existing websocket transport. This adds no
quota or independent allowance. NativeReadBuffer performs its original FULL
byte accounting before any child handoff; buffer and chunk ACKs remain transport
memory acknowledgements, never source/consumer/financial ACKs. Every close is
uncertain for unread reservation capacity. Abort/close faults still attempt
transport close, original reservation close and reader release, then stop with
a fixed cleanup failure instead of claiming verified cleanup. HTTP receipt
close faults similarly retain ownership, allow one accounting-only idempotent
retry and stop on persistent failure; no retry acquires another provider call.

Validation uses fake physical I/O, actual accounting/admission/native buffering,
anonymous IPC, repository network guard and disposable Scratch. Regressions
cover concurrent independent streams under one alias; original capacity and
reservation limits; stale stream handles; real Nitro compressed SDK frames;
bounded decompression; native abort fault cleanup; source priorities and fixed
eight-second request bounds; transient and persistent HTTP receipt-close faults.
The unchanged native sequencer parser suite also passes. No external provider
requests were performed. Native client v2, clock injection, all real source
owners and four runner construction are separately integrated/tested slices.
