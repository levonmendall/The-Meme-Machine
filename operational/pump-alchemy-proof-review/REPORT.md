# Pump / Alchemy — authenticated proof audit

Disposition: **PARTIAL AUTHENTICATED SIZE AND SHORT-TRIAL ADMISSION; LIVE ECONOMIC PARITY NOT PROVEN.**
Production choice: **RETAIN EXISTING WEBSOCKETS.**
This is a new read-only verification/report branch descending directly from
`reports/pump-alchemy-admission-first-validation-20261008` at
`3a212e09a8e5005d2f372969565fe57b77a61d81`.
Do not merge into operational code as a provider optimization.
No program source, subscription, wallet, PAPER epoch or Droplet was changed by this audit.

## What is authenticated

The earlier experiment was executed on 2026-10-08 19:01–19:02 UTC and
recorded one channel, three Yellowstone Subscribe RPCs, one WebSocket connection,
two WS subscriptions, three HTTP requests, and 46.374 seconds total wall time.
All 10 local shared-governor requests were granted (longest wait 1.484 s), with
no observed provider native RESOURCE_EXHAUSTED, no over-budget resource limit and
no retries. This proves **short-window admission for that exact local topology**;
it does *not* reveal active account-wide stream occupancy, the server's effective
stream limit or sustained production headroom. Original details:
[`ADMISSION_RESULTS.json`](../pump-alchemy-admission-first-validation/ADMISSION_RESULTS.json).

Four fully received real Yellowstone PumpSwap success packets were
6,688 / 6,688 / 9,717 / 14,898 application bytes. Total 37,991 bytes,
mean 9,497.75, nearest-rank p50 6,688 and p95/p99 14,898 (N=4).
All four were at Solana slot **454632166**, below the PumpSwap
requested starting floor **454632197** (31 slots behind).
Pump account stream was also observed below its requested floor;
shared control crossed its own floor. This is an ingress-synchronization/
completeness **symptom**, not proof whether provider replay, network or
client scheduling caused the missing finalized intervals.
The authentic packet-size values come from
[`NATIVE_PAYLOAD_DISTRIBUTION.json`](../pump-alchemy-admission-first-validation/NATIVE_PAYLOAD_DISTRIBUTION.json),
not from JSON-RPC serialization.

**New independent connected-account check:** the authenticated Alchemy
Solana RPC on app `9bin99s96t7ga5e9` returned
`getSignatureStatuses(searchTransactionHistory=true)`, context slot
**454749187**, for those exact four signatures. All four have
`confirmationStatus=finalized`, `slot=454632166`, `err=null`
and `status.Ok=null`. Full signature-to-size mapping and the returned
provider status metadata are in
[`AUTHENTICATED_SIGNATURE_STATUSES.json`](AUTHENTICATED_SIGNATURE_STATUSES.json).
The independent RPC check confirms genuine finalized success identity, not
the protobuf byte lengths or economic-event equality.

Alchemy administrative usage for the earlier trial produced separate
WebSocket CU and Yellowstone TB meters; no client-frame to billed-byte parity
was established. The earlier app-scoped deltas were 6,901.7638 WS CU
(34,508,819 tariff-derived bytes) and 0.0000353903 TB
(35,390,300 billing-equivalent native bytes). The receiver captured
28,742,236 WS application bytes and 73,683 native application bytes.
External app traffic, transport/wire overhead, billing aggregation and
cancellation buffers could not be allocated precisely. These unmatched
quantities **must not** be labeled savings.
[`USAGE_RECONCILIATION.json`](../pump-alchemy-admission-first-validation/USAGE_RECONCILIATION.json).

The newer authenticated account-wide usage retrieval remains roughly
1.737M CU and about $0.91 of reported CU value in this billing period.
Native usage Oct 6–8 is 0.0063307322 TB in separate Yellowstone billing
units, not a per-transaction size measurement. Droplet 605465049 was
verified active with 2 vCPU / 8 GiB via the connected DigitalOcean service.
The authenticated RPC also returned a current finalized Solana slot.
None of these observations establishes spare Yellowstone concurrency.

## Live economic parity — explicit FAIL TO PROVE

The earlier paired A/B run produced:
- **Zero** complete common finalized intervals; required minimum was three.
- **Zero** committed canonical economic-event rows and native witness rows.
- **No** exact same-evidence whole-system A/B delivered-byte totals.
- **No** covered Pump and PumpSwap economic success comparison.
- Equal 52 candidate locator/lifecycle projections and equal 246 candidate
  outbox rows, but only with incomplete economic source coverage.
- No funded-position sample, no candidate-work deadline or position-exit
  latency sample.
- No production WebSocket suppression and no replacement activation.

Thus the only defensible conclusion is **INCONCLUSIVE**. The earlier
raw allocation difference is not verified cost savings. The complete
20,422,414 paired-phase application bytes, 303,190 transition bytes and
8,090,482 shutdown bytes are charged; 28,816,086 total receiver bytes.
Incomplete/early provider frames cannot be treated as proof of coverage.
References: [`RESULT.json`](../pump-alchemy-admission-first-validation/RESULT.json)
and [`BYTE_ACCOUNTING.json`](../pump-alchemy-admission-first-validation/BYTE_ACCOUNTING.json).

## Economic direction under the existing assumptions

The earlier cost break-even was approximately **5,837 bytes per successful
native PumpSwap transaction** at the published mixed WebSocket/native tariffs
when other costs are held equal. The four authentic packets' mean of
9,497.75 bytes is **62.7% ABOVE** that conditional cost threshold, but
all four are below-floor and not a representative sample.

Applying their mean only as a **scenario sensitivity** in the inherited
30-day model gives original WS versus native respectively:
- Quiet: $2.86 versus $4.51.
- Normal: $29.24 versus $43.05.
- Busy: $200.82 versus $230.60.
- Stress: $1,360.23 versus $955.91.

Therefore replacing WebSocket acquisition is **not justified by current
proof**, and may be more expensive in ordinary conditions. Only stress traffic
mix assumptions model native savings at that packet size. No invoiced or
whole-system production savings are established.

## Exact remaining steps to obtain real economic-parity proof

1. **Offline first, zero provider dispatch.** Diagnose the retained authentic
   `capture/provider.frames.zlib`, original immutable clocks,
   requested `from_slot` floors, physical native receipt watermarks,
   WS receipt clocks and subscriber open/first-byte times. Determine whether
   below-floor progress came from provider replay lag, ingress starvation,
   decoder backlog, stream cancellation or another specific defect.
   Do not normalize missing frames, reduce the minimum completed intervals,
   or re-label prefix evidence as complete. Record first and last slot and
   arrival time *per filter* and finalized parent linkage. Inspect bounded
   ingress vs processing separately; Alchemy documents separate ingress,
   bounded queues and batched writes as appropriate for Yellowstone.
2. **Repair only the demonstrated cause.** Preserve one canonical owner,
   independent statuses, exact original economic identities and deadlines,
   no lossy candidate caps, Current/Survivor independence and held-position
   priority. Replay the real archived frames and adverse synthetic fixtures
   offline; prove no skipped/duplicated successful events and no time rollback.
3. **Validate the original finite provider envelope before any additional
   trial.** Maximum one native channel, three Subscribe RPCs, one WS connection,
   two initial WS subscriptions, five physical HTTP requests, 90 modeled
   HTTP CU, 60 seconds overall, 45 seconds for comparison, 48 MiB receiver
   stop, 64 MiB cancellation reserve, 512 MiB RSS, 256 MiB output and
   two-second shutdown. Do not silently replenish quotas, reconnect or
   dispatch a second run on an inconclusive outcome. Verify actual current
   competing workloads and account/native quota as far as supported.
4. **New one-shot provider comparison only after offline repair and available
   remote execution.** Capture native and WS concurrently with exact physical
   receive bytes and provider timestamps. Require at least three *real*
   complete common finalized intervals containing actual Pump and PumpSwap
   success events. Compare all signature/tx/event indices, independent
   success/failure witnesses, decoded economics, candidate history,
   Current/Survivor populations, original deadlines, gap/pending state
   and durable coverage projections; every mismatch or missing status blocks.
   Keep both feeds until a valid comparison is established. Preserve shutdown
   and transition bytes and all source-specific CU/TB metering.
5. **Safety/capacity supplement.** An unfunded 60-second stream probe cannot
   certify held-position and candidate queue latency or recovery over long
   holding periods. Run separately scoped offline pressure/restart/exit
   regressions and a bounded PAPER-only combined-load observation before
   claiming full autonomous capacity; do not dispatch paid market work as a
   side effect of this report.

The connected Alchemy tools provide authenticated RPC and Admin usage but no
live Yellowstone Subscribe-stream controls or account-wide open-stream occupancy
read. Connected DigitalOcean tools expose host details/actions but do not
expose the Droplet's authenticated shell or existing provider-stream process.
Consequently **this audit cannot personally run the on-host paired harness**.
It uses the exact retained authenticated trial and one new independent
signature-status query instead, and does not invent live economic parity.

**No live provider trial, production workload or code change was made by this
audit.** The only new authenticated provider read affecting economics is the
bounded four-signature status check (plus one finalized-slot health read and
one empty address-signature query); these do not certify streaming equivalence.
The old one-run authorization was consumed by the earlier 46-second trial,
and its trial receipt is not reused.

External documentation:
- https://www.alchemy.com/docs/reference/yellowstone-grpc-best-practices
- https://www.alchemy.com/docs/reference/yellowstone-grpc-subscribe-transactions
- https://www.alchemy.com/docs/reference/admin-api/overview
- https://www.alchemy.com/docs/reference/compute-unit-costs
