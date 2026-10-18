# Dormant shared-financial prefix observation

This component is a lower read-only primitive for the separate held-population
work. Nothing imports or installs it in normal operation. It issues no boot,
held protection, source closure, readiness or funding capability. The original
flat-only read context and certificate are unchanged.

`_FinancialPrefix(authority, state, replay_proof)` accepts the exact original
`RuntimeCapital` type and reducer. Its initial state must match the private
process-local replay cache populated by the original successful verifier. The
supplied summary or a caller hash cannot replace that cache. Construction must
occur at the genuine owner replay seam: the original authority does not retain
its creating thread, so this helper cannot retrospectively attest connection
birth. It binds its own creating PID/thread, existing connection and original
path/inode cache key. This is not independently authenticated root physical
membership, legacy selection or authorization of an arbitrary book.

The initial original cache is bounded to 4 MiB by existing code. A valid larger
or evicted state refuses observation rather than rejecting native work. The
helper does not invoke the original prefix authenticator, which scans the full
journal, or run a second full replay.

`advance` captures an actual journal head and follows the indexed interval to
that fixed cut, at most 256 rows and 2 MiB of SQL text per call. SQL first checks
the types and byte lengths before fetching journal bodies. Original event,
result, parent, state-hash and projection checks run with the exact original
reducers and Decimal context on detached state. The live authority's replay
flag, writes, handlers, existing transactions and native outcomes remain
unchanged. An original nonblocking mutex protects each short owned SQL snapshot
and its later head check. No connection, writer, pool, settlement or provider
call is created. Cancellation/deadline checks are cooperative; an executing
original SQL/reducer or busy wait is not a hard wall-clock deadline.

Other authorized writers' events are read from the actual global journal, not
inferred from one owner's notifications. Missing sequences and head growth keep
the result incomplete. Conflicting committed content latches UNKNOWN with the
original exception retained privately. COVERED_CUT describes the captured head
at the final check; another writer can commit immediately afterward. It is not
an ongoing all-writer completeness guarantee.

Views retain exact original current/terminal position and pending bodies as
immutable JSON text. The eight selected shared-state classes are counted;
LEGACY_NATIVE_PENDING is explicitly UNESTABLISHED. An owner-checked detached
state accessor preserves original aliases, native requests, cursors and delivery
maps for future bidirectional joins. It is not itself a native book, paused,
capital/trial, sleeve or protection census. Complete held population and actual
version-bound quote/USD outcomes remain separate required components.

There are no runtime hooks in this foundation. Normal runtime source and SQL
are unchanged. The focused tests use actual temporary original native/shared
books, including genuine Pons SelectivePaper/CohortCapital, all four regimes,
lost global ACK, native reserve/fill/partial/scale/terminal and peer-writer
events. Host owner/readiness/provider premises remain explicit offline fixture
inputs. No protected/live sizing or held execution claim follows from a test
pass.
