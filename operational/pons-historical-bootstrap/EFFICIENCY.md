# Acquisition costs and practical choice

Numbers below distinguish local measurements, generated transport batches and live projections. No market-provider request or billed-CU measurement occurred.

## Measured empty factory census

The same 4,096-block synthetic seven-day domain was supplied to the original and prepared paths. Initialization/boundary search is excluded from this census table and reported separately in the JSON. Both paths retain all relevant event identities; this deliberately empty case isolates overhead.

| Path | Logical elements | Generated batches | Encoded request / response B | CPU s | Wall s | Peak process RSS KiB | Final history DB B | Cumulative history WAL writes B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| legacy10 | 718 | 206 | 134,321 / 95,554 | 1.290 | 2.015 | 33,616 | 49,152 | 1,800,504 |
| prepared10 | 616 | 103 | 154,460 / 69,748 | 0.445 | 1.248 | 36,464 | 262,144 | 8,557,368 |
| prepared40_conditional | 155 | 26 | 38,827 / 17,585 | 0.100 | 0.346 | 36,464 | 163,840 | 2,748,104 |

The default ten-block path sends exactly the same 410 log ranges as the legacy path. It removes 102 repeated latest-header reads and combines headers/logs in the original bounded JSON-RPC transport. Requests contain the additional independent launch topic; request bytes therefore rise despite fewer elements. Additional coverage journals also increase WAL traffic. Forty-block data uses synthetic capability evidence and is conditional, not live provider support.

CPU is measured process time, not a live latency prediction. The measurement used write/pwrite64 tracing on the two-vCPU Droplet. Peak RSS is the cumulative process maximum, not an independent fresh-process comparison. Stock is the final checkpointed history DB; cumulative WAL includes initialization, acquisition, restoration and close. Phase write_bytes is separately recorded and must not be equated with WAL stock or per-file WAL writes.

## Measured mandatory economic reconstruction

The same two graduated pools and 140-block dense synthetic activity tape feed the existing shared native collector and the prepared shared path. Receipt, transaction-sender and event-header acquisition are included. Native histories are exactly equal. New lifecycle events add two receipt/sender witnesses, while Swap reductions remain unchanged.

| Path | Logical elements | Generated batches | Encoded request / response B | CPU s | Peak RSS KiB | Final history DB B | Cumulative WAL writes B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| legacy_economic | 724 | 27 | 111,764 / 867,054 | 2.437 | 38,176 | 237,568 | 2,748,104 |
| prepared_group_economic | 728 | 26 | 107,553 / 745,500 | 3.853 | 38,176 | 802,816 | 3,440,264 |

This is not a demonstrated whole-bootstrap speedup. Dense economic work remains almost the same RPC cost and is slower locally with additional raw-event authentication/journaling. Avoiding uneconomic future winners is not an allowed optimization. Structural non-native quote and expired-domain exclusions are the only implemented hydration avoidance.

## Seven-day census projections

These are empty-census estimates for the prior planning 5,985,970 blocks. Actual boundaries use canonical timestamps. Event witnesses, older-launch searches, candidate histories, failures, fairness and Current/position maintenance are additional. None of the times is a measured complete bootstrap.

| Requirement | Existing cold scan | Prepared ten-block path | Prepared forty-block path, if verified |
|---|---:|---:|---:|
| Historical block intervals covered | 5,985,970 | 5,985,970 | 5,985,970 |
| Logical census RPC elements | 1,047,547 | 897,897 | 224,476 |
| Physical census attempts, no cache/errors | 299,300 | 149,650 | 37,413 |
| Diagnostic CU at 100/element | 104,754,700 | 89,789,700 | 22,447,600 |
| Static frozen-domain census hours | 41.57 | 20.78 | 5.20 |
| Moving-head catch-up hours | 55.24 | 23.72 | 5.36 |
| Empty durable history projection | 49,152 B cursor only | 245.5 MB | 101.9 MB |
| Empty cumulative WAL-write projection | 2.63 GB | 12.51 GB | 4.02 GB |
| Complete candidate recall | required | required; native parity on fixtures | required; live capability unverified |
| Canonical completeness | required | checkpointed ranges plus native witnesses | same, with comparison/subdivision safeguards |
| Provider dollars / billed CU | unmeasured | unmeasured | unmeasured |
| CPU/RAM at populated seven-day scale | unmeasured | unmeasured; local measurements above | unmeasured; local measurements above |
| Recovery correctness | native cursor/history restore | explicit replay + canonical frontier + suffix recovery | same; runtime catch-up still ten/forty |

All physical timing uses the unchanged 0.5-second admission interval. The moving-head model assumes approximately 9.897 blocks/second and the entire useful slot budget, which active Current/positions will reduce. The legacy cached-header optimistic case can already approach 23.7 hours; the ten-block optimization makes that overhead case achievable in the generated empty path, rather than proving a 55.2-to-23.7-hour live improvement. The exact ceil formula gives 1,047,547 old logical elements; the earlier 1,047,550 figure was rounded.

Durable empty storage projects fixed tables plus scaled range/index pages. Economic raw events, candidate points, identity metadata, SQLite overhead and the shared immutable cache are additional and depend on real activity. Cumulative WAL extrapolation includes one-time initialization/close overhead from the small case and is a conservative rough model, not retained disk occupancy. The runtime keeps an additional day of recovery overlap and protects held histories longer, so rolling steady stock exceeds the seven-day-only model. All state belongs on the existing attached volume.

## Warm restart and prospective accumulation

The measured empty 4,096-block prepared restoration uses five logical reads in four generated batches, no log refetch, plus local full integrity/checksum/range replay. Its exact CPU/wall/write numbers are in MEASUREMENTS.json. Populated restoration adds each cohort frontier, older-launch frontier and every retained candidate checkpoint, with full local replay. It is O(retained evidence), not O(uncovered seven-day provider scan). Existing native cursor persistence is preserved; a cursor alone is insufficient for the new completeness gate.

At the planning chain growth rate, a five-minute outage produces about 2,970 blocks: 75 ten/forty census packets, 447 logical census elements, and at least 37.5 seconds of useful physical pacing plus restoration/witness/economic work. Moving-head growth and shared fairness can extend that. These are projections, not live restart measurements. No candidate original deadline is renewed.

Prospective accumulation has no immediate seven-day seed. It avoids a catch-up burst and spread-only census demand is roughly 0.247 four-range packets/second at the planning block rate, before latest/extension checks, witnesses, histories or other traffic. Readiness requires the original inclusive domain to mature and complete candidate evidence; seven days of elapsed wall time alone is insufficient. The rolling census does not eliminate seven-day RPC count or economic work. Opportunity loss before Survivor readiness is the explicit tradeoff.

Given the inspected evidence, prefer the finite forty-block capability comparison first. If the account cannot widen, prefer prospective accumulation over a tens-of-millions-CU cold census unless the owner authorizes and values earlier Survivor readiness. If widening succeeds, measure candidate density before cost/stock approval for a full campaign. No projected orders-of-magnitude whole-bootstrap saving is asserted.

Native telemetry now records logical elements, actual physical attempts, batches, cache avoidance, provider errors and payload bytes. Bytes mean attempted HTTP JSON payload and response payload actually read; TLS/headers/partial sends and unread error bodies are excluded. Estimated CU is the existing diagnostic weight. Actual billed CU requires independent account evidence and stays null. Public RPC calls count as consumption.
