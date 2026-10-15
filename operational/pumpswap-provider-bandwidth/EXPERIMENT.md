The next proposed validation is a **60-second Pump/PumpSwap capability experiment**.
It has not been run. The user's execution boundary requires separate authorization
before any market-provider call. This plan is separate from the combined Pons
capacity proof; that executor must not be used for it.

Use the existing Alchemy app credential, endpoint identity, native collector,
Model B startup/join/commit functions, transport meter and shared admission. All
evidence databases and output are newly admitted disposable engineering state.
No PAPER epoch, portfolio, service configuration or strategy worker is opened
for writing. No Meteora or Ramses interest is permitted. No funding or trade is
authorized. Do not call `SelectiveSource.run`, which starts additional acquisition
workers; use its existing `stream` method for the three finite native requests.

These are disposable experiment connections, not an attachment to the running
PAPER service. Within the experiment, the alternative replaces the candidate
request on the same three-RPC/one-channel topology as the reference. If production
is concurrently connected, the experiment would add one native channel with
three RPC streams and one WS connection to the account. That combined pressure
must be admitted by existing shared controls and established account headroom
under the separate authorization. If headroom cannot be established without
changing production or purchasing capacity, do not start the experiment. The
captured three-stream count does not establish account headroom or TCP count.

| Boundary | Hard client limit / stop rule |
| --- | --- |
| Wall time | 60 seconds including startup; cancel at the deadline, finish bounded shutdown within 2 seconds |
| Native transport | One existing-style `grpc.aio.secure_channel` to the endpoint below; three Subscribe RPCs maximum, no new channel or automatic retry |
| WebSocket transport | One connection, two initial fixed program subscriptions; one optional PumpSwap unsubscribe; no reconnect |
| HTTP JSON-RPC | At most 5 physical single-method POSTs: one `getGenesisHash`, four `getSlot`; zero transactions, accounts or archive RPCs |
| RPC CU | At most 90 published method CU; separately 13,422 CU for 64 MiB Solana WS application delivery or 26,844 CU including the entire 64 MiB cancellation reserve, rounded conservatively; no diagnostic native-CU conversion or guaranteed billed maximum |
| Delivery | Stop when combined WS/native received application bytes reach 48 MiB; retain and charge the stopping frame, at most 16 MiB, for a 64 MiB observed-payload ceiling |
| Buffered/in-flight delivery | Reserve another 64 MiB for cancellation and transport overlap; count every observable byte. This reserve is not a verified provider-side billing cap; overrun invalidates the proof and cannot be silently omitted |
| Request writes | Three native subscription writes and at most twelve native ping replies; two WS subscribe writes and at most one unsubscribe write; stop if another is required |
| Frame/queue bound | Native and WS frames at most 16 MiB; one outstanding read per native RPC, WS `max_queue=1`; no accumulating unbounded raw-frame list |
| Storage | Admit 256 MiB output maximum through existing engineering storage policy; stop at 224 MiB, preserve failure/unknown evidence; raw frames compressed incrementally |
| Memory | 512 MiB peak RSS budget; join buffers each retain the existing 32 MiB/256-slot bounds; stop on any bound violation |
| Errors/rebuilds | Zero tolerated admission errors, RESOURCE_EXHAUSTED, reconnects or filter rebuilds; first error stops the experiment |
| Physical method initiations | At most 11: five HTTP POSTs, three native Subscribe RPCs, two WS subscribes, one optional WS unsubscribe; streaming messages are counted separately |
| Extension | None; inadequate samples or incomplete intervals produce INCONCLUSIVE |

The observed byte ceiling is enforced at the same pre-routing receive boundary
as the existing collector. No local client can guarantee that the vendor stops
billing at precisely its receive-counter threshold: packets already dispatched,
oversized rejected messages and bytes buffered in transport can be charged.
Retain shutdown receipts and seek account usage reconciliation before describing
the reserve as a billed maximum. The finite executor must pass frozen-frame
ceiling/cancellation tests before execution. This branch prepares the exact
request and reviewable plan; it does not install a live executor or run it.

Endpoints and methods are fixed:

- `https://solana-mainnet.g.alchemy.com/v2/<existing-app-key>`:
  `getGenesisHash`, params `[]`, once; `getSlot`, params
  `[{"commitment":"finalized"}]`, up to four times. No retries.
- `wss://solana-mainnet.streaming.alchemy.com/v2/<existing-app-key>`:
  `logsSubscribe`, params `[{"mentions":[PROGRAM]}, {"commitment":"finalized"}]`,
  once each for Pump `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` and PumpSwap
  `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`.
  The optional `logsUnsubscribe` takes the actual returned PumpSwap subscription
  ID. Preserve and count its acknowledgement and all trailing notifications.
- TLS `solana-mainnet.streaming.alchemy.com:443`,
  `/geyser.Geyser/Subscribe`, existing `x-token` metadata:
  scout, independent control, and candidate replacement requests, once each.

The scout is the existing `scout_request()` in the operating Pump-only scope:
one `accounts["p"]` filter with Pump owner and the BondingCurve discriminator,
account data slice offset 0/length 56, FINALIZED. The control request is the
existing metadata `"b"` and finalized slots `"f"` request. Both retain the
existing control overlap; their delivered prefixes are charged separately.

The replacement candidate request is generated offline by
`engineering.solana_capacity.bandwidth_audit.capability_request(from_slot)`.
It uses the production `candidate_subscription` builder. Exactly five filters:

```text
commitment: FINALIZED
from_slot: the common floor established by the original Model B WS frontier
transactions["t"]:
  vote: false
  failed: false
  account_include: [pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA]
  account_exclude: []
  account_required: []
transactions_status["0"]:
  vote: false
  failed: UNSET
  account_include: [6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P]
transactions_status["1"]:
  vote: false
  failed: UNSET
  account_include: [pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA]
blocks_meta["b"]: {}
slots["f"]: {filter_by_commitment: true}
```

No transaction-field projection, success-only WS field, account exclusion,
candidate ranking, pool cap or larger include-list limit is proposed. A status
packet remains independent of the full body and retains error, signature, index,
bank and all matching filter labels. ALT/static account membership must agree.

During the first **45 seconds maximum**, collect both WS program feeds and the
replacement native transaction filter on the existing candidate Subscribe RPC.
This intentionally delivers reference and alternative data simultaneously;
charge both. Two offline production joins consume identical original statuses,
metadata, finality and receipt clocks: the reference join takes both WS logs;
the alternative takes Pump WS logs plus full successful PumpSwap native bodies.
Write to separate disposable owners and compare original identities, indices,
all log lines/event positions, economic records, failure census, canonical
coverage, candidate history and first decision deadlines. Native full bodies
must never stand in for the independent status census.

If complete common intervals and all bounds permit, the final **15 seconds
maximum** may unsubscribe the PumpSwap WS interest. Do not add or restart a
connection. Keep Pump WS, the full native success filter and both status filters.
Prove all required success bodies against the status census and linked finalized
children. Acknowledge and meter trailing WS packets rather than discarding them.
This shows actual subscription suppression, while the first phase supplies the
paired traffic comparison. It cannot establish long-horizon market parity.
If the first phase is incomplete or contradictory, omit the second phase and
stop. Always leave the production subscription path unchanged.

Required positive evidence is at least three complete common finalized intervals,
authentic Pump and PumpSwap successes, a PumpSwap buy and sell when present,
exact true transaction/log indices, multi-program membership when present,
identical canonical rows and durable candidate-history outputs, and measured
full native payload including transaction metadata, prefix, filter labels,
heartbeat, overlap and shutdown traffic. Required negative evidence is native
failed identities/errors with zero committed failed trades, absent or late body/
status preventing completeness, no silently discarded native contradiction,
and zero admission/reconnect pressure. Missing market cases remain UNSAMPLED;
the finite window must not be extended to manufacture them.

Before a production switch could be justified, the paired data must show lower
**total** delivered bytes for the same complete intervals after all native,
recovery and HTTP charges; same launch/migration and economic-event population;
no deterioration of original candidate or position latency; and equivalence in
the frozen late-Survivor, disconnect, reorganization, overlap, held-position and
accounting fixtures. This small probe contains no funded-position acceptance
sample. It does not clear
`combined_position_and_candidate_provider_latency_not_certified`.
