Native incomplete-drain terminal handoff

An original65-second native shutdown fence can expire with a source task or
consumer/sizing thread still alive. Returning a normal failure then closing
ports/resources would race that owner's private SQLite/cache connections.
asyncio.run() can also enter a second indefinite task/default-executor join.

The contained lifecycle now persists FAILED/all_workers_joined=false and raises
an explicit NativeOwnerDrainFailure. Generic libraries never exit their caller.
The owned Runner, pending source work, private stdout, fixed environment and
private resource handles stay retained on this terminal handoff; no Runner.close,
port/reader/channel/SQLite/cache close occurs underneath a live owner. A failure
that fully joined its owners keeps normal cleanup and its original error.

Only the fixed image/descriptor-validated child entry handles the typed terminal
handoff by emitting a bounded BLOCKED/graceful_shutdown=false receipt to FD1 and
calling os._exit(2). Output is nonblocking and attempted for at most0.1second, so
a full result pipe cannot delay termination. No second graceful interval is
added. The original outer65-second fence remains authoritative and may terminate
the child before that final output attempt completes. The private failure receipt
and earlier progress remain evidence; missing output cannot become PASS.

The entry makes no claim that process/namespace cleanup already completed while
it is still writing the receipt. The existing parent must reap the nonzero exit,
apply its original PID1/process-group fences and finish original accepted HTTP/
stream uncertainty accounting. Kernel process exit closes remaining private
handles; no fabricated native FULL/ACK or production historical disposition is
issued. Production historical/financial files and AWS permissions are untouched.

Focused proof uses real subprocesses, actual private CandidateHistory handles,
a blocked consumer/default-executor owner, and a source that can remain pending.
It verifies exit2, failed/graceful=false receipts, and zero explicit owner-close
calls underneath the live thread. A saturated stdout pipe also terminates within
the bounded test. Only image/descriptor admission is mocked in these isolated
entry tests; this is not an OS/provider/full-market proof. Private fixture drain
limits are short; the public runner retains900/300/65seconds unchanged.
