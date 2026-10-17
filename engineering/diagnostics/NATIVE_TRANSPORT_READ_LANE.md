# Bounded ownership of idle native transport reads

`ChildNativeStream.read_async()` formerly used `asyncio.to_thread(read, None)`.
Every idle stream could hold one default executor thread until new traffic or
shutdown. The actual source's RepairRPC/control/stream close also use that pool;
enough idle streams could prevent those operations from starting. Changing a
global thread limit or provider budget would not repair that dependency.

Each authenticated ChildChannel now owns one dedicated read executor, capped by
the protected parent's unchanged `maximum_streams` hello field. An explicit
registry permits one accepted async read per exact issued stream and at most
that many total tasks. The API accepts only the original native read operation;
no wire-selected callable, endpoint or priority is added. A deny-only native
financial context is installed on each owned read execution.

The waiter retains its registry lease until the actual read and any cancellation
close have joined, including repeated cancellation. Original idle timeouts keep
the same parent read token. Original raw handoff, digest/chunk acknowledgements,
native SDK reads, subscription upload and economic source FULL/ACK stay unchanged.
Synchronous Pons sequencer reads remain on their original owner thread.

Abort signals socket shutdown and executor stop without joining: it can run from
a read worker or inside the control lock while preserving the original error.
Normal `close()` and the fixed entry's `abort_and_join()` then join the owned read
executor outside those locks. Self-join/control-lock attempts refuse explicitly
and retain the executor for the outer owner. A worker-start failure aborts and
cancels potentially queued work before returning the original failure. The
existing typed incomplete-native-drain path still skips all cleanup and exits
through its owned-process fence.

The focused regression keeps ten real parent-reserved offline native streams
idle with a one-thread default executor, then completes original RPC, a genuine
subscription write and close. It checks actual handoff/cancellation accounting,
no extra read on idle timeout, duplicate-read refusal, repeated cancellation,
abort/join and worker-start failure. Existing native handoff, gRPC/websocket,
subscription upload and fixed-entry fatal-drain cases also run.

`maximum_streams` is a capacity ceiling; original per-open native byte reserves,
spend, reconnect and provider pacing may admit fewer simultaneous streams. They
remain authoritative. A test that attempted to fill the advertised32 ceiling
correctly hit the original cumulative native-byte stop reserve; its failed
receipt is retained. The regression uses ten within that same unchanged budget.
No global executor resize, provider allowance, hardware or live workload changed.
These offline proofs establish this causal concurrency repair, not actual AWS
isolation, complete native parity or sustained full-market throughput.
