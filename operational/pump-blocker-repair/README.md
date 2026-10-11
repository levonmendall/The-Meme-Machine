# Pump streaming blocker repair

This narrow successor retains the ops2 trading economics, provider governor,
native execution, shared $1,000 authority and paused-family policy. The original
release tags and historical $500 epoch remain unchanged. No market dispatch or
PAPER activation is performed by these files.

## Retained authenticated evidence

The ops2 run recorded three scout and two shared-control `INTERNAL` retries,
four rolling `log_buffer_pressure` retries, 63 scouts, zero canonical economic
events and zero candidate checkpoints. The control frontier stopped at
455571559. Scouts and stream pings did not satisfy economic coverage.

The native error observer discarded the already-sanitized error phase/details
unless an optional observer was attached. Production had no such observer.
Neither the provider's actual error reason nor the pending join contents survived.
The records therefore do not identify a provider, replay, filter, finality or
consumer-pressure root cause. Changing those semantics on speculation is unsafe.

The earlier `PROVIDER_BLOCKER_CASE.json` reconstructed a candidate request with
transaction bodies. The actual rolling call explicitly uses
`full_addresses=set()`: program transaction statuses, block metadata and finalized
slot membership, with finalized WebSocket logs supplying economic content. The
old evidence is preserved; this correction does not alter the actual subscription.

The new diagnostics retain the actual serialized request, sanitized gRPC status,
phase and details, bounded message-kind/slot samples and pending join summary in
the existing acquisition-observation store and service journal. They grant no
coverage, freshness, checkpoint or trade authority.

## Resource defect and repair

The old custom-limits UPDATE matched no row because creation did not persist one.
Construction silently substituted defaults. The intended accounted 512-MiB stop
was exceeded: 188,728,906 delivered bytes plus 771,746,163 uncertain bytes. The
old usage database and first failure remain preserved. Its 5,892 modeled CU,
263 logical elements and 102 physical starts are not an invoice assertion.
Of those logical elements, 247 were Robinhood and 16 Solana.

Creation now persists the complete validated envelope. Observation requires an
explicit matching configuration file in the supervisor and all existing child
transports. Missing, invalid or altered configuration refuses startup durably.
Restart preserves the clocks, counters and first failure; orphan reservations
become uncertain usage once. HTTP responses reserve bounded unread capacity.
Native opening requires its complete SDK reservation plus the next maximum frame
within the accounted stop. Delivered tails consume the existing reservation;
unread buffers remain charged. No default or restart can replenish an allowance.

The prepared inactive observation selects Pump only. It refuses to omit any
existing foreign position, reservation or pending intent. Discovery completeness,
canonical ordering, economic rules, quotation freshness and 2-RPS scheduling are
unchanged. This scope change removes unrelated Pons work from a Pump validation.

## Next authenticated gate

`pump-observation.disabled.json` is a proposed envelope, not authorization. It
retains the 512-MiB accounted stop, bounds observation to 900 seconds, permits at
most eight native openings, 1,200 physical starts, 1,800 logical elements and
150,000 conservative RPC CU, and caps modeled incremental spending at $0.20.
Use a new, exclusive usage database after explicit owner authorization. Never
recreate or reset the old failed database. Keep funding disabled and the service
stopped until dispatch is authorized. Do not repeat the consumed component test.

A pass requires progressing authenticated canonical coverage for both Pump
programs and complete genuine candidate/native financial evidence. Missing market
opportunities cannot be invented. Stops, trails, partial/full exits, loss of
evidence and durable restart behavior retain their offline proof; events actually
observed at the endpoint must be reported separately. Complete one-owner native
latency and renewable protection reserve remain mandatory before admission.

Focused receipts and exact changed-file identities are in `VALIDATION.json`.
All failed test scopes remain retained. Local operational evidence, verified disk
duplicate disposition and the new-epoch off-host snapshot are referenced from the
separate operational handoff, not recursively copied into this release.
