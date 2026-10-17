The private native transport protocol v3 preserves the original Yellowstone
4MiB gRPC send maximum from solana_selective_source. It does not change provider
allowances, native stream reservations, economic decoding, source FULL/consumer
ACKs or financial authority. It has no workflow, broker or deployment call site.

The exact v3 hello advertises upload_bytes=4194304, upload_chunk_bytes=32768 and
upload_slots=1. There is no v2 fallback. A fixed native_upload_begin declares a
parent-issued stream, exact length and SHA256. The parent admits only Yellowstone
on its existing owned stream and one preallocated buffer per session. The slot
remains owned through SDK write completion and cleanup. Each strict-sequence
chunk declares the same opaque upload/stream and exact next offset. Canonical
base64 carries at most32KiB, staying below the original64KiB control frame limit.
There is no filesystem spool, URL, path, callable, quota or source selection.

Commit accepts only the exact completed length and SHA256. The existing trusted
subscription validator runs before the actual SDK write. The complete buffer is
transferred to the original ParentNativeStream, which retains original budget
admission and raw transport ownership. Yellowstone's original4MiB max-send option
is explicit. The older small native_write verb is restricted to Solana WebSocket;
observation-only Robinhood sequencer writes remain denied. Solana WebSocket keeps
its existing parent64KiB/child32KiB bounds.

The one upload slot limits payload buffering to one4MiB assembly plus a transient
complete4MiB immutable copy. Protobuf validation and original SDK buffers remain
under their original bounds and protected parent resource limits; this is not an
exact total-Python-heap claim. No provider usage reservation is minted for IPC
copies. The child's writer-only lock supplies subscription backpressure. Each
control exchange releases its existing lock immediately; parent SDK I/O is an
accepted asynchronous operation. Other RPC calls and native reads keep running.

The original8s overall deadline includes upload, validation and SDK completion,
as well as client slot waiting. Uncommitted cancellation discards the private
buffer; hash/offset/scope errors, EOF and deadline close/discard without a write.
After commit, cancellation/failure joins actual stream cleanup and records its
original unread uncertainty before terminal status. Exact most-recent-message
replay reuses the accepted token and cannot purchase or repeat a write. An
ambiguous commit is never retried under another logical sequence.

Offline tests use real anonymous IPC, original Budget/stream reservations and
actual protobuf validation with fake physical I/O. A large valid source-shaped
subscription exceeds3MiB and reaches the fake SDK exactly once; a separate byte
fixture exercises the exact4MiB boundary. These are transport/parity regressions,
not live market, native economic processing, hardware or PAPER readiness proof.
