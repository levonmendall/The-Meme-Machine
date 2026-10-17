# Original Pons clock over a parent-owned feed

`SequencerBlockClock(parent_stream=stream)` accepts only the exact owned
ChildNativeStream, with transport robinhood_sequencer, operation pons_discovery,
read_class native, source family robinhood and observation_only true. An explicit
URL is refused. This branch never reads a provider URL from the child environment
or constructs an external client. Ordinary construction without parent_stream
keeps the original SDK path and behavior.

The small read adapter supplies socket-style local idle timeouts to the unchanged
native clock. Client v2 keeps one accepted native read across those timeouts;
there is no extra subscription, HTTP call or stream reservation. The parent uses
the original Nitro websocket SDK, NativeReadBuffer and original FULL ledger
before handoff. Reconnect obtains a new parent-issued instance under the same
fixed source and pays its original reservation. Original SequencerFeedState,
range bounds, native malformed/gap/conflict handling, session history and
observation-only status remain in use. Neither a new feed session nor a transport
ACK proves canonical inter-session coverage; the original caller must still do
the existing governed RPC backfill before advancing its authoritative cursor.

Six focused tests passed in 0.552 seconds with real anonymous IPC, original
metering, actual Nitro SDK framing and original clock/parser. Only physical
connect/socket bytes were faked. Tests cover parsed sequence/header timestamps,
one pending idle read with no new reservation, explicit and transport-loss
reconnection, unchanged malformed/gap refusal, and exact type/URL rejection.
The unchanged eleven native sequencer cases passed in 0.002 seconds. The first
combined clock/client/parent/RPC run passed 56 cases in 3.705 seconds before the
two additional malformed/transport-loss regressions were added and passed.

This is a local component, not a full native runner loop, live-provider test,
authenticated launcher result or authoritative PAPER readiness. Parent source
authentication, fresh sizing producer, Pons capabilities and all four complete
runner integration still require their own proofs. No provider requests, AWS
dispatch or financial database writes were performed for this slice.

The startup cleanup follow-up closes the exact acquired parent instance even
when native Clock.connect has not run. Pons Current acquires its feed before
opening native stores, so this path is required on partial startup failure.
The added regression proves native_reserved returns to zero with one original
open, and repeated close does not reacquire. It also exposed a transport failure
publication race: the parent formerly published failed before joining cleanup,
allowing the child's terminal cancellation to interrupt cleanup and falsely
stop the whole channel. Failure is now published after joined cleanup; a
deterministic gated regression proves the operation remains running until then.
The clock and parent modules passed 43 cases in 1.869 seconds after both fixes.
The initial local failure receipt remains at /tmp/mm-engineering-pkror5f1.
