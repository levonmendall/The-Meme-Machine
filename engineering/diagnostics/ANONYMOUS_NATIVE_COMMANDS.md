# Anonymous native command connections

The isolated child now uses fresh, unnamed AF_UNIX/STREAM socketpairs for its
internal Pump command connections. This component requires explicit, identical
`IsolatedNativeResources` and `NativeRunnerPorts`; production defaults retain the
pathname listener and reconnect path. No environment variable selects it.

The native command protocol is unchanged: one request/reply per attempt, 32-KiB
line bound, original UUID/expiry, six attempts within three seconds, half-second
attempt timeout, pending responses and exact acknowledgement identity. The
existing `command=` fixture shortcut is not used. The actual service consumer
still submits to `PendingCommands`, the sole `PriorityOwner` and the original
durable command/receipt transaction. The broker interprets no command, creates
no ACK and changes no candidate-history, source FULL commit or native ACK code.

`NativeRunnerPorts.require_source_commands_ready()` returns the exact registered
generation only after the service has created its real owner, native schema and
preparation workers. It also checks the private source DB is a regular file.
This is connection readiness, not financial readiness or a cached SQLite inode
proof. The source executor must poll this API instead of waiting for a pathname
socket. Each facade retains its original generation; an old facade cannot adopt
a replacement source silently.

There are at most 32 pending pairs and 32 active handlers, matching the existing
listener backlog and handler limits. A pending slot is reserved before pair
allocation. One coalesced source-loop wakeup carries no unbounded descriptor
list; no lock spans stream/provider I/O. The source wraps an already-connected
peer with `asyncio.open_unix_connection(sock=peer)` and invokes the existing
handler. No bind, listen, accept, connect, sendmsg, recvmsg, descriptor transfer,
new parent broker, URL or credential is involved.

The broker remains available through the original admitted-source drain. At the
old listener-close phase it refuses new connections, closes queued peers and
joins active handlers. Disconnect/cancellation cannot cancel an accepted native
owner future. Even cancellation before a handler's first turn closes its owned
peer. Socket closure alone does not release the generation: `serve` retires it
only after all original owners/executors join. A cleanup failure retains the
generation and refuses port closure/replacement. The existing terminal fatal
drain controller remains responsible for an uncooperative owner.

Native decoder selection uses the separately reviewed `IsolatedSpawnExecutor`
component. The default decoder remains the original `ProcessPoolExecutor`.

The isolated service also owns one dedicated checkpoint thread. Both its bulk
copy and original mutation-boundary reclamation use that same single lane. The
lane is registered before work starts and is joined with the existing source
owners, under the original outer shutdown/fatal fence. Original checkpoint SQL,
handoff token, priorities, FULL durability and cancellation/join are unchanged;
the copied ContextVar context remains attached to off-owner work. Default
production checkpoint dispatch remains unchanged (`executor=None`).

This repairs a reproduced shared-pool starvation cycle in the contained test:
24 synchronous command waiters consumed the default pool's nine threads on
this five-CPU environment, while the source held its real checkpoint handoff
and queued its disk worker behind those waiters. Three of six identical runs
failed before correction (15.515 seconds total); diagnostics showed nine queued
owner requests, an active handoff and no running owner operation. The retained
failure receipts are `/tmp/mm-engineering-auswu4bl`,
`/tmp/mm-engineering-xnkcmrv6` and `/tmp/mm-engineering-ln400kcs`. No deadline was
increased and no command ACK was fabricated. The test now gives the same 24
consumers explicitly owned threads, matching the actual native runner lifecycle.
The deterministic checkpoint regression separately reproduces the shared-pool
block and demonstrates the owned lane can finish the same native checkpoint
while the default pool remains occupied; cancellation still joins the real disk
operation before mutation resumes. This does not prove this cause occurred on
the production deployment.

Actual child `read_async` operations can also occupy the shared default pool
for long idle intervals. A separately owned, bounded transport-read lane is
required before claiming complete isolated source parity; that follow-up is
owned by the child transport component. A dedicated checkpoint lane alone does
not establish that every other source operation has sufficient worker capacity.

Validation: 73 affected command, checkpoint, native constructor/source, pipe
worker and fatal-drain cases passed in 13.951 seconds with frozen worker
dependencies `eaac5ab7` and lazy-start correction `c95736ea`. The original
checkpoint growth/integrity test retained all 272 records, and its eight repaired
WAL samples were zero bytes. Six identical 24-command retests then all passed in
1.925 seconds (`/workspace/recovery-evidence/native-command-after-owned-lanes.log`).
AST comparison confirms the service consumer, command/receipt mutation methods
and original `LocalPumpTape.events_since` remain unchanged. These are offline
component results, not market
throughput or authoritative readiness measurements.

Actual multiprocessing/filter compatibility, the source-executor readiness
hook, OS isolation, authenticated launch, provider capacity, live throughput and
authoritative one-hour PAPER acceptance are separate requirements. This change
does not establish Landlock/seccomp readiness or operational parity.

Focused tests use actual anonymous sockets, the real service owner and SQLite
receipts with offline data. They cover concurrent Current/Survivor facades, lost
reply deduplication, identity conflict/expiry, pending retry, bounded overload,
EOF, cancellation before and after native admission, consumer restart and source
lease refusal. The original `LocalPumpTape.events_since` test verifies its real
FULL candidate-history transaction finishes before its actual native source ACK.
Older constructor fixtures now start that real service instead of creating only
an empty evidence DB. No provider call, funded entry or authoritative historical
acknowledgement is exercised.
