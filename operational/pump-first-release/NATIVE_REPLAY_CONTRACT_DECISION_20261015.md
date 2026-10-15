# Native replay contract — 2026-10-15

**Decision: PRECISE_REMAINING_PROVIDER_QUESTION. Do not consume campaign attempt 2.**
The authorized capability-only diagnostic is complete. No stream, PAPER start,
deployment, funding or canonical/economic/history write occurred. The existing
attempt1 RECOVERY_REQUIRED result is unchanged, and the campaign remains at 1/3.

Exact tested/executed diagnostic source:
`2c8168b9d61e820da025956fbe8d4c31ce24ccc6`, branch
`repair/consolidated-startup-followup-20261014`. This adds a standalone two-unary
diagnostic and four tests, without changing production transport authority,
provider routing or any strategy/accounting implementation. The Pons repair
`0000a4f817107cff9b46a881b7f1ae00745aa384` remains preserved and undeployed.

## Verified request and current official documentation

Attempt1's account scout and control stream requested FINALIZED replay at
457039819, exactly then-current HTTP finalized tip 457040075 minus the existing
256-slot overlap. The scout used the Pump owner/discriminator and 49-byte account
slice; control requested block metadata plus commitment-filtered finalized slots.
Both received INVALID_ARGUMENT / failed to get replay position for that slot,
before any native frame. Exact retained requests are linked in the prior attempt
handoff; none was changed or replayed during this capability diagnostic.

Alchemy's current [Subscribe Request reference](https://www.alchemy.com/docs/reference/yellowstone-grpc-subscribe-request)
describes a 6,000-slot replay window, while its
[Historical Replay guide](https://www.alchemy.com/docs/reference/yellowstone-grpc-historical-replay)
describes approximately 432,000 slots. The request reference documents FINALIZED,
account slices and the request fields used here. Neither page establishes the
actual backend's availability, exact-slot behavior or those combinations' replay
contract. The [CU table](https://www.alchemy.com/docs/reference/compute-unit-costs)
lists SubscribeReplayInfo and GetSlot at 10 CU each.

## Actual capability results

Both calls used the existing authenticated binding on
`solana-mainnet.streaming.alchemy.com:443`, one TLS channel, disabled gRPC retries,
five-second transport deadlines and existing 2-RPS shared admission. Endpoint
identity remains
`8f3feda9d10baa64d74b5ecb3a97cfa48af379982666f93a425e537668a51749`.

| Method | Invocation UTC | Status | Response | Payload / transport wall |
| --- | --- | --- | --- | --- |
| SubscribeReplayInfo, once | 01:04:51.210094 | OK | first_available=456183362 | 6 bytes / about109 ms |
| GetSlot FINALIZED, once | 01:04:51.710658 | OK | slot=457048070 | 6 bytes / about15 ms |

Recorded admission waits were 7.7 ms and 358.9 ms; invocation spacing was about
500.6 ms. These are client invocation/completion measurements, not wire-start or
provider execution timings. Response metadata identified only istio-envoy, with
no backend/request identity establishing same-node attribution. The directory
label ending0111Z is only a locator; the recorded 01:04:51 UTC timestamps above
are authoritative.

The numerical advertised span is **864,708 slots**. A contemporaneous native-tip
minus256 floor would be 457047814, above first_available by 864452. The original
rejected cursor is above the currently advertised floor by 856457 and behind the
new native finalized tip by 8251.

Therefore a simple too-old request is **not supported by the present advertised
bounds**. This is a later sample, not the availability/commitment state of the
original failing backend. The bounds do not prove each slot exists, that account
and control replay share identical retention, that finalized replay is supported
for those exact filters, or that two calls on one channel reached one node.
No supported provider correction or necessary source redesign follows yet.
In particular, REPLAY_SLOTS, from_slot, overlap, source checkpoints, evidence gaps,
finality and canonical completeness were not changed.

## Precise provider question and next discriminator

The sanitized provider question is:

> Why did FINALIZED account-scout and block-meta/slot subscriptions at
> from_slot=457039819 fail to obtain a replay position when HTTP finalized tip was
> 457040075? For this bound mainnet application/endpoint, what is the supported
> replay contract for these exact filters and commitment, skipped/unavailable
> slots, and load-balanced replay cursors? How should the advertised
> first_available range relate to an individual subscription's accepted floor?

No support message or new provider request was sent. An authoritative answer can
resolve this without another market diagnostic. Alternatively,
[NATIVE_REPLAY_CAPABILITY_NEXT_TEST_20261015.json](NATIVE_REPLAY_CAPABILITY_NEXT_TEST_20261015.json)
prepares one short standalone discriminator: fresh same-endpoint unary range/tip
and HTTP tip, exact control/scout FINALIZED replay requests, then at most one
conditional commitment comparison if a semantic rejection warrants it. It keeps
the original common HTTP-tip-minus256 cursor, existing accounting, one stream at
a time and a 45-second absolute boundary. It cannot produce economic coverage,
trade authority, throughput proof or a historical repair claim.

That proposal is **unexecuted and requires separate stream authorization and a
focused-tested driver**. It does not renew the completed two-call scope, reset
the campaign clock or authorize PAPER. Load-balancing ambiguity or another
inconclusive result ends the branch for provider clarification, without an
unchanged repeat. Do not invent a recovery bypass or new provider/hardware need
from the current evidence.

## Pons cancellation, validation and preserved state

Independent bounded offline source review found reachable non-cooperative
regions before shared-authority replay cancellation registration
(`shared_capital/authority.py:259–279`) and in CohortCapital's own SQL/reconciliation
(`lanes/pons/pons_selective_capital.py:17–91`). These are possible boundaries,
not demonstrated causes of attempt1's -9. Its one process sample precedes TERM;
there is no main-thread stack/SQL scope during the following 15-second drain.
No speculative SQL, timeout or lifecycle repair was added.

The smallest missing runtime discriminator is the actual main-thread startup
operation at TERM and while drain fails. A future separately authorized run could
capture one capped code-only stack from the existing health thread after TERM,
outside the signal handler, without locals. That instrumentation is not yet
implemented or deployed. The existing tested constructor cancellation fix remains.

Four focused network-blocked tests pass in **0.172 seconds**, using real disposable
Budget accounting and actual protobufs. They cover two exact methods/finalized
commitment, no retry/substitution, reservation cleanup on diagnostic-output failure,
unsupported errors and credential/header redaction. Independent review caught two
reservation/uncertainty issues before dispatch; both were corrected and verified.
Prior focused logs are retained. No full FAST, startup rehearsal or financial
recovery campaign was repeated: production source is unchanged from the previous
validated successor, and the earlier source/economic proofs remain applicable.

Actual/accounted usage: **two unary HTTP/2 attempts, two Solana logical elements,
20 CU, 12 protobuf payload bytes**, zero uncertain/reserved remainder and zero
native stream openings. These extend the existing usage/hourly/admission ledgers;
HTTP counter names include unary HTTP/2 transport. Wire/TLS bytes and invoices
remain unavailable. Existing frozen model increment: **$0.0000105**, not a bill.

PAPER remains stopped/failed, disabled, Restart=no and MainPID0. Installed source
`66f85d61` is untouched. Funding remains closed. No $1,000 epoch, historical $500,
policy, strategy, capital, journal, retained evidence or protective deadline changed.
No extra allocation/trade/acceptance authority was used or inferred.

Exact results, counters, source identities and private artifact hashes:
[replay-unary-contract-20261015.json](evidence/replay-unary-contract-20261015.json).
Original attempt, SQLite BUSY, Pons READONLY, sustained throughput, held protection,
native drain and backup/protection blockers remain separately open.
