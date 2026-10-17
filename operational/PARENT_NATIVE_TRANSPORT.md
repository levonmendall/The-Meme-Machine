# Trusted parent transport component

This component is local engineering work, not selected by the operational
entrypoint and not an authenticated native harness or readiness result. It was
developed on application `0ca14c97a6d69f6ad8e65450b12cf00b45f69dbe`, preserving
the earlier standalone bridge protocol and its tests.

`parent_transport.SourceBinding.configured` resolves the actual parent-configured
Alchemy Solana/Pons URL, binds its nonsecret fingerprint and requires the existing
Governor or canonical Admission object. It creates no provider ledger, allowance,
financial authority or readiness. `SourceReference.from_receipt` accepts only the
public alias/family/fingerprint/work fields emitted by the parent. A configured
authenticated endpoint is not proof of successful network/chain validation.

`ParentHTTP` uses the original Budget reservation and HTTPReceipt delivery/close,
the real Governor/Admission queues, fixed work context, HTTP/RPC 429 accounting,
Pons physical starts/completions and activity marker. Explicit batches remain one
physical JSON-RPC HTTP request. Logical demand is separately exposed, including
cache hits; native client hooks must call it at the original logical boundary.
The parent uses direct TLS without redirects/proxies, eight-second socket waits,
the original attempt deadline, EOF and a 16-MiB aggregate response ceiling.
Unknown read wrappers/chunked framing fail closed when a whole-read deadline
cannot be bound. HTTP error classification/debt survives failed body inspection;
unread bytes remain uncertain. No provider error body or exception text crosses
the channel. Cancellation joins accepted accounting before closing the receipt.

The optional `cancelled=None` additions to Governor.acquire and Admission.acquire
and invoke preserve ordinary production calls. An explicitly injected parent
attempt can stop waiting for a grant without purchasing a physical request or
leaving a queue ticket. Default clocks, policies, deadlines and pricing remain.

`NativeSourceBinding` fixes the authenticated source and Yellowstone/websocket kind
in the parent. Its real factories retain credentials and external sockets. They
preserve native SDK limits and the original stream reservation, NativeReadBuffer,
FULL commit and uncertain-close handling. Native subscriptions reject unfiltered
transaction bodies, paused Meteora work, unknown protobuf fields and unrelated
write methods. Existing bounded account scouts, candidate filters, linked control
metadata/finality and finalized log subscriptions remain supported. Native reads
allow one unacknowledged handoff; a new open earns a new original reservation.

`ParentChannel` serves only an already-connected anonymous channel; it creates no
listener or privileged path. The bootstrap must verify source, OS confinement,
private descriptor ownership and financial denial before physical acquisition.
HTTP/native content is transferred in 64-KiB chunks with exact offset/hash ACKs,
up to the original 16-MiB response/frame bound. Content ownership remains bounded
by accepted workers/native reservations. Completed content is released after its
last handoff ACK; fixed sequence replay retains only the most recent reply.
Old/altered sequences or foreign handles fail closed instead of reexecuting I/O.
Handles bind a native stream generation, so a stale handle cannot close a newer
reconnection. EOF, malformed framing, child death, internal accounting failure,
session deadline or explicit close joins owned work and closes reservations.

The wire verbs are `http_begin` (alias/calls/batch), `poll` (token), `read`
(token/offset), `ack` (token/offset/sha256), `cancel` (token), `demand`
(alias/methods), `activity` (alias), `native_open`, `native_close`, `native_read`
(alias), `native_write` (alias/body_b64) and `close`. Every message also has the
exact session and increasing sequence. Open/close/write and HTTP/read operations
return an accepted token; poll reports their terminal state. Native control tokens
are released after the terminal poll; response tokens after the final chunk ACK.
The hello states all bounds. No deadline, priority, URL, SQL, path, allowance,
credential, financial action or executable can be selected by a wire message.

Transport handoff ACK is memory/backpressure only. It has no source database or
canonical consumer ACK capability. The isolated native owner must still perform
its actual economic work and earn its own source FULL/ACK. No production history
is read or settled by this component.

Validation used Python 3.12.14, the repository network guard and disposable
Scratch. Five affected modules passed 89 cases in 1.677 seconds: parent transport,
existing bridge, native usage intake and Solana/Pons clock-domain regressions.
Twenty-seven adjacent admission, method-pressure and purchase-attribution cases
passed in 0.087 seconds. This Cloud worker cannot stat `/proc/self/ns/time`; the
offline transport and adjacent fixtures explicitly use the repository's stable
test domain. Runtime clock guards were not changed. Initial fixture failures
remain at `/tmp/mm-engineering-g_jq9nrd` and `/tmp/mm-engineering-28p4zzz6`.

These are offline fake physical transports with real accounting/admission, not
AWS or live-provider validation. Missing integration includes a source-authenticated
OS-enforced child bootstrap, all native RPC/stream client hooks, complete source
owners/consumers, four real qualification runners, corpus replay and actual
bounded resource/performance testing. Per-alias work classes also need the actual
RepairRPC priority1/2/4 versus runner/governed-HTTP call-site map; a generic
discovery/current/survivor assignment is not exact scheduling parity. Held/fill/
settlement branches remain unexercised. No complete operational or release claim
is made by these checks.
