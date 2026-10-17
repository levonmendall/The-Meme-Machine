# Isolated native spawn workers without named semaphores

The isolated source uses two real spawned preparation/archive interpreters and
one lazy spawned history interpreter. Production continues to use its original
`ProcessPoolExecutor`. The functions, arguments, immutable products, history
snapshot checks, native financial denial initializers, history worker limits,
durable lease/retry decisions and canonical owner application are unchanged.

Each isolated worker has a one-way anonymous task pipe and a one-way anonymous
result pipe. A dedicated parent thread owns each pair and a normal
`concurrent.futures.Future`. Pending cancellation prevents dispatch; dispatch
sets RUNNING before serialization, and accepted running work finishes without
allowing cancellation to claim rollback. A worker crash breaks all pending work
and terminates/joins its peers; only the existing HistoryExecutor constructs a
replacement generation. The adapter does not replay an accepted task.

No multiprocessing Queue, SimpleQueue, Lock, Event or SemLock is constructed.
Known FD, socket, Connection, mmap and resource-sharer payloads are refused before
their pickle reducers run. The native workload passes data and private paths.
CPython's actual spawn machinery still launches its minimal resource-tracker
process through anonymous pipes. In any future Landlock entry it must first
start **after** confinement: a preexisting unrestricted resource-tracker FD is
not an allowed inherited capability. There are no registered named semaphores
and no new `/dev/shm` permission. This component does not establish OS isolation.

There are at most W running plus W+1 queued tasks: five total decoder/archive
tasks or three history/archive tasks. The configured source has two initial
probes (completed before intake), one serialized candidate-preparation carrier,
one archive carrier, and two independently bounded history/retirement carriers.
Submission over capacity fails explicitly instead of blocking the event loop.
The original native upstream byte/queue bounds remain in force.

Each serialized task/result frame is capped at64MiB with a bounded pickle writer
and receiver length check. The native relevant limits are16MiB provider frames,
16MiB candidate commit batches,32MiB economic prepared products,16MiB packed
history input and16MiB archive work. Pickle duplicates/container overhead are
distinct from those native byte populations; this is an additional transport
bound, not proof that every syntactically possible native product fits64MiB.
The tested retained economic/history corpus fits unchanged. A larger product
fails explicitly and follows the original source gap/job retry paths, with no
consumer ACK/checkpoint or historical completeness fabricated. Maximal-corpus
and sustained throughput parity still require measurement. Completed Futures
and their retained results belong to the original bounded native consumers.

Healthy shutdown cancels queued work when requested and joins accepted work and
all worker processes. Uncooperative running work keeps the original65-second
source/owner fence; the existing fixed-entry fatal-drain handoff kills the owned
process tree rather than closing live native resources. No additional grace or
automatic process retry is introduced.

Source-start observation now requires the exact live anonymous command owner
generation and the private DB, rather than a pathname socket. This requires the
separate anonymous command broker component. Its native PendingCommands,
PriorityOwner and command expiry/idempotency behavior remain their own proof.

The focused tests execute real spawn workers, actual economic preparation and
history calculations, identical SQLite FULL economic publication followed by
real consumer delivery and canonical ACK, ordinary exception propagation,
pending cancellation, SIGTERM drain of2+1 workers, worker crash/replacement,
crash-versus-cancel races, oversized frames, and forbidden descriptor payloads.
All providers are offline and all state is disposable. No AWS, Landlock,
full-market parity, financial authority or authoritative PAPER readiness is
asserted by these tests.

## Reviewed named-semaphore alternative

Pinned CPython3.12.14 allocates five named semaphores per ProcessPoolExecutor:
three for the call queue and two for the result queue. Exact-file read/write
Landlock rules could permit spawn reopen. Sem unlinking needs directory-level
REMOVE_FILE, so it cannot be allowed for only the chosen files under `/dev/shm`.
A trusted parent could instead precreate raw SemLocks, use a custom spawn context
to adopt them without child finalizers/registration, and unlink only its recorded
names after every child owner has been reaped. This is technically possible but
requires explicit per-object identity/cleanup proof. An unrestricted prestarted
resource tracker would accept arbitrary semaphore-name unlink requests and is
not an acceptable cleanup helper. A finite preauthorized bank must also handle
history pool replacement without reusing dirty locks or expanding the Landlock
allowlist later. The pipe adapter avoids that additional named-object authority
and generation lifecycle; it changes executor transport/scheduling and therefore
needs the explicit regression evidence above.
