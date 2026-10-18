# Parent-owned transport bridge primitive

`meme_machine.operational.transport_bridge` is an offline-tested protocol and
session primitive. No production caller imports or installs it. It does not grant
provider, financial, broker, filesystem or deployment authority. It is not a
complete transport server or proof of native throughput or provider parity.

A parent supplies immutable `EndpointAlias` objects and a trusted adapter. Wire
data cannot select an adapter, URL, credential, database, SQL statement, path,
allowance, attribution scope, priority or deadline. Alias methods must be a subset
of the existing frozen read-only published methods. The parent privately maps
aliases to real endpoints. No credential-bearing URL is manufactured for a child.

The current verbs are `begin`, `poll`, `cancel` and `close`. Every message includes
the parent-issued session identity and a consecutive integer sequence. `begin`
additionally contains `alias`, explicit `batch`, and `calls` with exact
`method`/`params` fields. Token verbs contain only `token`. Single and batch requests
remain distinct, including a one-element batch. There are no child completion,
acknowledgement, refund, retry, grant or deadline-extension verbs.

Messages use a four-byte unsigned big-endian length followed by JSON. Requests
are bounded at 64 KiB; duplicate keys, nonfinite/floating parameters, deep/large
parameter structures, authority-bearing options and unknown fields are refused.
Lengths are checked before reading a body. One `dispatch` accepts exactly one
complete frame. Exact semantic sequence replays return their original encoded
reply; changed replays, foreign tokens or protocol errors close the session.

Each accepted attempt gets an opaque session-owned token, a parent-assigned
monotonic deadline of at most 30 seconds, and immutable request bytes. Sessions
last at most 1,800 seconds. Pending transports run concurrently with bounded
capacity; dispatch never holds a lock across admission or I/O. At most 64 attempts
retain request parameters bounded by their 64 KiB request frames. Response bodies
and replay replies have a separate 8 MiB combined retention limit and at most
1,024 sequence records. Exhaustion closes
the session; records are never evicted in a way that could execute an old request
again. Poll responses are immutable per sequence, so a later poll needs a new
sequence to observe progress.

`Delivered` means the trusted adapter already committed delivery accounting and
sanitized the response. Successful HTTP delivery additionally requires genuine
EOF; a partial response is charged and cleaned, closes the session, and exposes
no body. Bytes become pollable only after `release` finishes before the fixed
attempt deadline. Accepted accounting cleanup may finish later but cannot extend
that delivery deadline.
Cancellation, expiry, child exit and failures invoke exactly one adapter cleanup
for each accepted attempt, even when execution never began. Cleanup is shielded
from repeated cancellation. Genuine physical EOF is the only reason to release
an unused reservation without uncertainty; no child assertion can establish EOF.
Canceled/failed attempts expose no body. Cleanup failures close the session and
remain failures; the primitive cannot repair a failed durable ledger.

The embedding parent must close inherited external descriptors, deny child
external and unauthorized Unix-socket connections, keep credentials out of the
child environment, and establish a private authenticated channel. It must call
and await `Session.aclose()` on EOF, child death, protocol/framing error or reply
write failure. The module supplies a bounded reader, not a server or that sandbox.
Use one event loop per session; thread callers must marshal to that loop.

The adapter is trusted parent code, never a serialized callable. A real adapter
still needs to preserve each native path's Governor/Admission order, existing
shared Budget reservation before physical I/O, delivered-byte commit before
handoff, batch behavior, request pacing, 429/error debt, original context
attribution, cancellation and uncertain-reservation cleanup. It must share the
original Pump/Pons controls and allowances. It must honor its fixed deadline,
including cancellation while admission or network work is pending. Cooperative
task cancellation cannot stop a blocking or cancellation-suppressing adapter;
the embedding process needs its original outer shutdown fence. No retry occurs
inside this primitive.

Stream transport, `NativeReadBuffer` integration, logical-demand/activity-marker
proxying, constructor injection and production transport coverage are deliberately
unimplemented. Its 256 KiB response limit is narrower than native frame capacity;
it must not be used as a substitute sampler or claimed to prove full parity.
The offline fixture uses the actual `Budget`/`HTTPReceipt` with fake physical I/O;
it does not clone allowances or contact providers. Integration and a genuine
shared-control adapter require separately reviewed work and affected validation.
