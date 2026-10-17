# Actual native source executor component

The explicit `isolated_native_entry` now has a `run_contained` implementation.
It keeps normal production constructors and their financial/recovery guards as
the default. The new branch requires the exact owned resources and parent ports;
there is no environment switch, URL fallback, local Budget/Governor, financial
epoch copy, production database path, signing or trading authority.

The fixed child initializes its own candidate-history file, then runs the actual
`RepairRPC`, `SelectiveSource`, evidence `serve`, sole SQLite priority owner,
two spawned decoder/preparation processes, separated history preparation process,
delivery executor, FULL/ACK delivery, native backpressure and maintenance. Actual
Pump Current and Pons Current run concurrently on separate owned threads; their
original Worker implementations own their respective Survivors. Native imports
bind fixed disposable paths before either consumer starts. Explicit execution
scopes and process/thread initializers deny financial constructors before I/O.
No old callback or production recovery evidence is read, rewritten or settled.

Provider HTTP, native Yellowstone/log websocket and Nitro acquisition use the
existing parent-issued capabilities. Source HTTP priorities 1–6 and the original
history/recovery/unattributed purchase roles remain independent. Unknown roles,
priority zero, ambient URLs and unverified getBlock repair are refused. Logical
source consumers are recorded through the parent even for singleflight followers;
only actual attempts purchase provider resources. Child source receipt bytes are
exact **parent-public-handoff bytes**, which can differ from physical bytes even
for successful JSON-RPC due to parent normalization. Child CU/call accounting is
not physical provider accounting; the original parent Budget remains authoritative.

The execution window is fixed at 900 seconds after validated bootstrap, with the
original 300-second source-socket startup bound and 65-second cooperative cleanup
bound. Socket existence is labeled as such, never financial/native readiness.
Startup and observation-after-socket durations are separate. Sizing refresh runs
throughout startup and work, retains the original five-second Pons valuation
freshness, and stops on missing, stale, malformed or foreign parent facts. The
source first stops intake and drains accepted work. Every consumer/source thread,
SQLite owner and preparation executor must finish before successful return. A
live worker produces a failed partial receipt, never a graceful PASS; the outer
fixed process boundary remains responsible for forced termination.

Private output is bounded to 8 MiB and progress to 256 KiB. The 64 KiB terminal
receipt records fixed numeric source counters and original source-drain counters.
Five-second progress samples compare finalized native control slots with durable
control slots, and separately record each joined-frame queue's accepted/committed
population. Slots are never translated into economic frames or transactions.
First/last work samples precede stop/drain, which is separately timed. These
metrics do not establish complete economic coverage by themselves.

On the actual original operational builders, with maximum-length 44-character
valid pubkeys and maximum encoded from_slot, protobuf sizes are: control 29 B,
scout 83 B, Pump candidate/rolling 48-address status subscription 2,707 B, and
PumpSwap ActivityRoutes 50-address shard 13,969 B. All pass the existing fixed
parent subscription validator and 32 KiB write envelope without clipping. The
parent's general send ceiling remains smaller than the original 4 MiB native
transport ceiling; unexercised larger subscriptions are not certified.

## Offline validation and limits

`python -m operational.tests FAST --modules tests.test_isolated_native_source`
ran on CPython 3.12.14 with engineering Scratch and network_guard: 22 tests passed
in 2.249 seconds, no skips. This includes actual parent Budget/HTTP/native IPC,
separate handoff/physical bytes, logical singleflight consumers, real source
SQLite/service startup and cleanup, and actual spawned preparation initializers.
The source-owner fixture supplies no market economic data or coverage claims.

This component has not completed an actual market run. The OS namespace boundary
currently refuses user-namespace setup on the AWS host; the protected genuine
financial/USD sizing producer and its workflow integration remain separate work.
Authenticated optimization-profile transfer is not implemented: source getBlock
repair and Pons block-receipt/callMany profiles therefore remain unexercised.
Production-state restoration, held-position priority-zero protection, funding,
fills and settlement are also unexercised. A fresh disposable run cannot replace
restoring the production candidate history. Host/storage/resource admission and
absolute child termination must be provided by the existing reviewed outer
boundary before launch; this component is not a kernel sandbox. The receipt
always says `financial_authority=false`, `normal_readiness=false`,
`complete_production_parity=false`. Neither this component nor a 900-second
observation is the required one-hour authoritative PAPER acceptance.
