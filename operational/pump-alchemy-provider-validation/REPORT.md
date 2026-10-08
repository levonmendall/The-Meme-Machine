**BLOCKED — `current_account_headroom_required`.** The credential prerequisite
passed. Current account-wide connection, stream and throughput headroom could
not be verified through the available authenticated administration tools or the
existing shared governor. The single authorized experiment was **not started**;
this task dispatched **zero market-provider requests**. No replacement path is
activated. Retain the existing WebSocket acquisition configuration; economic
superiority remains undetermined.

This publication descends directly from
`engineering/pump-alchemy-capability-executor-20261008`, commit
`91ad8b608da357049c8c02e783fc41904634a535`. The published remote head was verified
at that commit. The report branch is
[`reports/pump-alchemy-provider-validation-20261008`](https://github.com/levonmendall/The-Meme-Machine/tree/reports/pump-alchemy-provider-validation-20261008).
Only this report and its evidence are added. The prepared executor, its limits,
production sources and earlier economic evidence remain unchanged.

The owner's authorization covers one conditional 60-second experiment. There
was no execution attempt, retry, reconnect, extension or provider admission
probe. The blocked preflight does not consume a run or schedule future work.
No positive result is inferred from the prior synthetic/offline validations.

| Requested result | Observation |
| --- | --- |
| Native successful transaction payload distribution | N=0; mean, min, p50, p95, p99 and max unmeasured |
| Architecture A / B total delivered bytes | Unmeasured; neither experiment architecture was opened |
| Provider-side byte / percentage savings | Unmeasurable; 0 bytes credited as verified savings; percentage undefined |
| Economic-event, ordered-history and candidate-state parity | Not run |
| Candidate discovery, Current/Survivor independence and canonical completeness | Not run; existing behavior preserved |
| Original deadlines, queues and observable latency | Shared local queue empty; comparison and deadline/latency parity not run |
| Provider admission | Not attempted; account-wide headroom unverified |
| Experiment resources | No experiment process or capture; all published limits retained |
| Monthly Pump cost | Scenario estimates below; no certified production monthly cost |
| Acquisition decision | Retain existing WebSockets; comparative economic winner undetermined |

**Credential and administration evidence.** Authenticated `list_apps` and both
`get_app` calls returned the requested Pump/Solana app `9bin99s96t7ga5e9` and
Pons/Robinhood app `v5h0vqr0wpp9zscj`, with the expected networks. The existing
secret-free reconciliation compared the configured Droplet credentials to the
owner-provided administrative suffixes. Both match, the endpoint roles are
valid, the keys are distinct, and the native Pump token matches the configured
Pump credential. This is masked-suffix administrative association, not a
cryptographic comparison to an undisclosed full administrative key.
[CREDENTIAL_RECONCILIATION.json](CREDENTIAL_RECONCILIATION.json) records the
checks without publishing a credential, suffix or secret-bearing URL.

The Pump endpoint SHA-256 is
`8f3feda9d10baa64d74b5ecb3a97cfa48af379982666f93a425e537668a51749`, matching the
published executor and authoritative capture. The Pons endpoint is checked
without making a Pons market request or altering its configuration.

**Exact admission blocker.** The connected Alchemy tools expose app details and
historical usage, but no live account-wide channel/Subscribe-stream occupancy,
effective connection/stream allowances, WebSocket connection/subscription
occupancy, or current rolling throughput headroom. No trusted current receipt
or binding reservation covering other account workloads was available. The
required additional topology remains one native channel, three Subscribe RPCs,
one WebSocket connection, two initial subscriptions and five candidate filters.
Each capacity must cover existing interests plus these additions.

The actual existing shared Solana governor was inspected in read-only mode. It
had no queued work, no remaining provider or method cooldown, zero historical
rate errors in its provider row, and no grants in the preceding 60 seconds. Its
schema has no connection/stream reservation table. It regulates local physical
request scheduling and priority; it cannot attest to global active streams.
[SHARED_GOVERNOR.json](SHARED_GOVERNOR.json) retains that observation.
[LOCAL_WORKLOADS.json](LOCAL_WORKLOADS.json) records local processes and TCP
counts without provider addresses or command-line secrets. These observations
cannot enumerate other hosts, attribute every connection or count subscriptions.

PAPER has MainPID=0 and remains inactive, with its existing start/exit timestamps.
That observation does not establish account-wide provider availability. A
published quota or a zero short-window usage delta is also insufficient. The
original executor's read-only preflight guard rejects the unverified assessment
with `current_account_headroom_required`, as recorded in
[PREFLIGHT.json](PREFLIGHT.json). The live executor was never invoked and no
affirmative headroom receipt was manufactured.

The remaining prerequisite is a trusted **current account-wide occupancy and
effective-limit observation, or binding capacity reservation**, accounting for
all concurrent workloads and the exact additional topology. It must support a
receipt valid for at most 300 seconds, tied to the verified Pump endpoint and
this authorization, without production changes or purchasing capacity. This
report does not authorize a new run or expand the existing authorization.

**Authenticated usage, separate from the experiment.** Nine read-only Alchemy
administrative calls succeeded. Account usage summaries report
**1,730,149.7724 CU and $0.91** for the current billing period. Both observed
summaries contain the same totals, with data-through timestamps 18:39 and 18:44
UTC on 2026-10-08. The zero reported CU change covers this observation interval;
it is not an experiment delta, an absence-of-traffic proof or a savings result.

The longer usage queries cover 2026-10-02 through approximately 18:45 UTC on
2026-10-08. Pump's returned CU rows sum to **1,730,139.7724 CU**: 1,154,690 HTTP
CU and 575,449.7724 WebSocket CU. Pons contributes 10 HTTP CU. The separate native
meter reports **0.0062953418 TB** for Pump gRPC, comprising 0.0046426064 TB on
October 6, 0.0016483698 TB on October 7 and 0.0000043656 TB in the partial
October 8 bucket. These are earlier account workloads, not a native-success
payload measurement or a matched architectural comparison.

Using decimal TB, the native usage corresponds to **6,295,341,800 billing-unit
bytes**. Inverting the published Solana WebSocket tariff gives **2,877,248,862
billing-unit bytes** for the historical WebSocket CU. Both conversions are
derived; neither is a new captured provider/application/wire-byte measurement.
The CU summary does not include a TB-denominated native meter. At current list
prices, the historical Pump CU and native usage imply approximately **$1.38**
combined usage, including about **$0.47** for gRPC. That combined USD figure is
calculated from tariffs; it is not an authenticated invoice total.
[ADMIN_USAGE.json](ADMIN_USAGE.json) preserves returned product units, filters,
timestamps and rows; [USAGE_RECONCILIATION.json](USAGE_RECONCILIATION.json)
preserves all derived values.

Alchemy's usage documentation distinguishes the native `SOLANA_GRPC_TB` meter
from CU products. Usage is reported in time buckets; the responses declare
minute updates and a partial current day. The CU and native snapshots have
different data-through timestamps. Reporting and aggregation delay prevent a
sub-minute attribution claim. No final invoice, custom account rate or
experiment-scoped billed delta is available. [Alchemy Admin API documentation](https://www.alchemy.com/docs/reference/admin-api/overview).

**Preserved byte break-even and monthly estimates.** The unchanged historical
capture contains 27,538,305 successful and 13,400,141 failed PumpSwap WebSocket
bytes across 9,819 successful messages. Its gross replacement budget is
40,938,446 bytes, yielding approximately **4,169.31 native bytes per success**
for a byte break-even. This task has no native payload samples to compare to
that threshold. The earlier 915 charged-but-uncaptured bytes remain unknown;
they are not discarded, classified retroactively or credited as savings.
[Preserved baseline](../pumpswap-provider-bandwidth/BASELINE.json).

Current published tariffs remain $0.525 per million CU, 0.0002 CU per delivered
Solana WebSocket byte and $75 per decimal TB of Yellowstone traffic. Their
different byte prices imply a **5,837.03-byte cost break-even** in that same
historical PumpSwap mix if every common cost and overlap remains identical.
This is a conditional tariff calculation; increased marginal native overhead
or repeated full bodies changes it. [Alchemy pricing](https://www.alchemy.com/pricing),
[Solana transport tariffs](https://www.alchemy.com/docs/reference/compute-unit-costs).

The original 30-day model is retained, with explicit activity assumptions and
native mean-payload sensitivities. It retains Pump acquisition, independent
statuses, scouts/control, known prefixes and HTTP method CU. It does not convert
this diagnostic window or account history into steady-state market activity.
All figures below are **estimates**, with native sizes still assumed:

| Scenario | Existing WS architecture | Filtered native: 3,000 B | Filtered native: 4,200 B | Filtered native: 6,000 B |
| --- | ---: | ---: | ---: | ---: |
| Quiet | $2.86 | $1.98 | $2.45 | $3.15 |
| Normal | $29.24 | $17.79 | $22.46 | $29.45 |
| Busy | $200.82 | $104.29 | $127.61 | $162.61 |
| Stress | $1,360.23 | $450.65 | $543.96 | $683.93 |

Quiet, normal, busy and stress assume respectively Pump success/failure rates
of 0.2/0.2, 2/2, 10/15 and 40/120 per second; PumpSwap success/failure rates of
2/1, 20/15, 100/150 and 400/1,600 per second. Their scout rates are 0.1, 1, 5 and
20 per second, with baseline account RPC rates 0.01, 0.1, 1 and 4 per second.
[COST_ESTIMATES.json](COST_ESTIMATES.json) retains the exact original assumptions,
byte totals, startup components and limitations. HTTP response bytes, exact
billing overhead and the unstarted experiment's heartbeat/status/overlap/shutdown
comparison remain unmeasured. These scenarios do not certify admission and
include no new paid capacity, credits, taxes or custom prices.

The scenarios show why both native size and the failed/successful traffic mix
matter: either architecture can cost less under the stated assumptions. They
do not establish a current economic winner. Local traffic disposal receives
zero savings credit. Existing economic evidence, original clocks and pending
completeness are preserved without promoting an unsampled case to PASS.

**Preservation and verification.** No service restart, deployment, production
subscription change, wallet action, credential edit, strategy change or capital
allocation change was performed. Meteora and Ramses remain paused in the
unchanged operating-family source. The original `$500.00` PAPER epoch remains
`paper-1791089005190643467`. Five protected inception/portfolio/genesis files are
hash-checked before/after report preparation; the 64-file durable-state inventory
is compared by size, inode and modification timestamp. The existing production
sources and all pre-existing tracked evidence are compared to the requested
commit. [PRESERVATION.json](PRESERVATION.json) records the actual checks and their
limits. The inventory is metadata evidence; it is not a content hash of every
large state file.

The report checks use the previously validated CPython 3.12.14 environment. They
verify receipt consistency, unchanged source/limit identities, accounting
arithmetic, preservation and secret-free publication. No engineering regression
suite was rerun and no market fixture was acquired. The branch's existing GitHub
workflow contains no deployment step. This evidence-only publication uses
`[skip ci]` in its commit message to avoid repeating the completed engineering
suite; no new GitHub CI pass is claimed.
[VALIDATION.json](VALIDATION.json) and [MANIFEST.json](MANIFEST.json) identify the
published evidence and hashes.

Validation did not pass, so there is no production-change recommendation for
activation. The appropriate operational action is to retain the existing
WebSocket path and resolve `current_account_headroom_required`. Live held-position
safety and `combined_position_and_candidate_provider_latency_not_certified`
remain untested by this capability probe. No future provider run is started,
repeated or automatically extended by this publication.
