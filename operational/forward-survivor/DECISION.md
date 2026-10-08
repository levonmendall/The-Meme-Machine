Forward-only Survivor operation — 2026-10-08

Implemented on `engineering/forward-survivor-20261008`, based on Pons
`b1f215edd3dc079b623401c7e09e9c91a380e6a0`. This includes the published Pump repairs,
Model B and shared-capital integration, plus the completed storage maintenance
commits. Final identities and preservation checks are in [DELIVERY.json](DELIVERY.json).
No deployment, production state/configuration change, service restart, provider
request, paid upgrade, seven-day enrollment or historical campaign occurred.

Ordinary Pons startup now uses an inclusive, authenticated canonical enrollment
block in the existing history database. It retains every factory launch and
graduation in that prospective domain, with ordered native identities, canonical
bounds and receipt witnesses. A verified previous ordinary observation checkpoint
retains its outage tail on first migration; an unfinished research census does
not become the startup frontier. Missing pre-enrollment launches are authenticated
with token-specific queries around the recorded launch timestamp. Earlier
unobserved opportunities remain `UNOBSERVED`. Retained pre-frontier graduation
nominations recover their exact canonical event and lineage independently.

The global seven-day bootstrap cursor and the `step()` historical-readiness
admission mask are removed. Discovery and economic hydration continue while
unrelated coverage is incomplete. Positions retain priority and their original
admission authority. A candidate requires verified launch/graduation lineage,
contiguous economic history through the exact fresh canonical evaluation block,
authenticated prices/swaps/buyer groups, valid liquidity and execution quotes,
and every frozen strategy gate. Qualification precedes shared-capital admission;
capital denial remains durable. No market-wide historical population requirement
was found in the actual ranking rules; their original tie-breaks are unchanged.

Warm restart restores enrollment, histories, controllers and deadlines. Economic
acquisition groups only overlapping checkpoints, so older recovery intervals
cannot claim newer candidates' work credit or hold their histories back. Missing
intervals are recovered from durable checkpoints in ten-block requests. Forks
invalidate affected evidence and retain unaffected rows. An enrollment-parent
fork rewinds the same prospective domain, retaining the original enrollment
identity and orphan witnesses. Explicit historical research/recovery APIs and old
journals remain available, but ordinary startup never invokes their seven-day
preparation or maturity requirement.

| Regime | Original earliest timing for a newly observed candidate | Operational status |
| --- | --- | --- |
| Pump Current | Original late-curve features, including three distinct finalized seconds; no new age floor. Post-graduation continuation remains 5–180 seconds. | Offline regression validated; BLOCKED / not running |
| Pump Survivor | Four-hour age floor, **six hours of post-graduation prices** for the mandatory six-hour structure. Earlier observations cannot invent the missing price. | Forward discovery already existed; independently tested; BLOCKED / not running |
| Pons Current | 90–900 seconds after launch plus original confirmation/demand gates; post-graduation continuation remains 5–45 seconds. | Offline regression validated; BLOCKED / not running |
| Pons Survivor | **Four hours after graduation**, when complete available history and every original rule pass. The long trend clips to available age up to 24 hours. | Candidate-specific forward operation implemented; BLOCKED / not running |

Both Survivor maximum ages remain seven days, inclusive. Pump's Mayhem safety,
reset/base, two-/six-hour structure, buyers, liquidity and quotes remain mandatory.
Pons's trend, reset/base, breakout, organic buyer-flow and execution rules remain
mandatory. Four hours permits evaluation; it does not promise qualification.

The $500 inception, epoch `paper-1791089005190643467`, five-percent directional
sizing, realized-equity compounding, shared reservations, all nine approved
changes, original Current/Survivor entries/exits, right tails, bridge, staged
scaling and Current-to-Survivor recovery are preserved. Frozen policies and Pump
lane sources are checked against the requested Pons reference. Meteora and Ramses
remain paused with zero operational provider/discovery/capital workload; their
accounting and unresolved obligations remain intact. Offline legacy regression
tests do not activate either family.

| Architecture | Cost and completeness assessment | Decision |
| --- | --- | --- |
| Free ten-block HTTP polling | Existing bounded canonical acquisition is implemented and offline tested. At the saved block-rate estimate, factory enumeration alone exceeds the monthly allowance. | Use existing infrastructure for finite validation; sustainable Free autonomy is unproved. |
| Filtered Robinhood WebSocket | Documented `eth_subscribe(logs)` supports topic filters. Delivered-byte cost is attractive for sparse events, but uptime/head checks do not prove that no factory event was missed. | Not enabled; no separate ingestion framework or unsupported completeness claim. |
| PAYG historical bootstrap | Wider ranges are documented. Factory-only seven-day query counts for 100/1,000/10,000 blocks are 59,860/5,986/599; pool economic histories and witnesses remain additional. | Retired as an operational prerequisite. No upgrade or capability test justified by startup. |
| Filtered stream plus HTTP recovery | Can reduce notification latency and duplicate hydration. Savings require an authenticated completeness contract; continuing full ten-block enumeration preserves its cost floor. | Potential later transport improvement only after finite evidence demonstrates benefit. |

Reusing the existing forward pipeline has the lowest additional engineering and
infrastructure cost. A sustainable month-long Free solution is not established:
the saved block-rate estimate exceeds the allowance even for factory discovery.
Actual ordinary workload, account usage and an authenticated subscription
completeness contract must determine the next provider decision. A paid upgrade
is not justified by the removed startup requirement.

The exact verified factory/topics are recorded in [NEXT_PROOF.json](NEXT_PROOF.json).
Robinhood documents ten-block Free ranges and wider PAYG support; this implementation
keeps the tested ten-block limit. [Robinhood log documentation](https://www.alchemy.com/docs/chains/robinhood-chain/robinhood-chain-api-endpoints/eth-get-logs),
[Robinhood subscription documentation](https://www.alchemy.com/docs/chains/robinhood-chain/robinhood-chain-api-endpoints/eth-subscribe).

Published `eth_getLogs` pricing is 60 CU. Thus the previous 598,597 method requests
cost an estimated **35,915,820 CU**, 5,915,820 above the Free monthly allowance,
before any economics or Pump work. The approximately 149,650 physical four-log
batches are not 149,650 billable method calls. At the saved estimated 9.897 blocks/s,
continuous factory enumeration projects **153,924,960 CU / 30 days**, about
**$80.81 PAYG-equivalent**, before headers, receipts, economic cohorts, quotes,
Current, positions and shared Pump usage. PAYG charges all usage; the Free 30M
allowance is not a PAYG credit. [Robinhood method pricing](https://www.alchemy.com/docs/chains/robinhood-chain/robinhood-chain-api-endpoints/eth-get-logs),
[plan pricing](https://www.alchemy.com/pricing).

EVM subscriptions cost 0.04 CU per delivered byte: 1 MB costs 40,000 CU.
Fifteen-second head checks model 3.456M CU/month. Filtered Pons bytes are unmeasured.
[Pricing basis](https://www.alchemy.com/docs/reference/compute-unit-costs).

Economic cohorts still acquire every required pool swap
and witness; each continuously scanned cohort can add another factory-sized log
budget, depending on coverage, density and cache reuse. A five-minute factory
outage adds approximately 297 log calls / 17,820 CU, plus affected economics.
These are estimates, not account billing. The removed cold-census campaign adds
zero startup requests; canonical enrollment and relevant histories still cost
provider work.

The saved Pump capture contains 48,501,501 Solana WebSocket payload bytes and
1,829,265 Yellowstone payload bytes. Applying published rates gives approximately
9,700.3 CU and $0.000137; its 132 RPC elements model to 2,984 CU. Old 98,305 native /
12,210 RPC figures are diagnostic ceilings; billing is unmeasured. Only 2.379
seconds of post-release delivery cannot establish a monthly rate. Solana uses
0.0002 CU/byte and Yellowstone $75/TB.
[Published stream pricing](https://www.alchemy.com/docs/reference/compute-unit-costs).
[ECONOMICS.json](ECONOMICS.json) retains formulas, outage costs and unknowns.

Offline replay of the authentic saved tape exactly preserves 287 canonical rows,
169 candidate identities, native order, hashes and original first-seen clocks.
On this two-vCPU / 8-GiB host, the concurrent replay/admission/capital fixture
sampled 175.27 MiB peak group RSS. Shared-capital grant p99 was 613.6 ms and native
delivery p99 119.0 ms, with no five-second fixture deadline misses and conserved
$500 capital. Three concurrent tape replays plus allocator/admission used about
1.59 CPU cores over 24.50 seconds and wrote about 442 MiB cumulatively; this
synthetic workload is not a normal storage-growth projection. Its temporary
stock was about 19 MiB and cleaned only after verified parity. No live position
or provider deadline was certified. [Measured receipt](validation/CONTENTION.json).

The serialized Pons worker now checks at three seconds: its forty-block work
bound has a theoretical 13.33 blocks/s ceiling, compared with eight at the old
five-second cadence. The 0.5-second shared provider admission interval, ten-block
queries, fair candidate/cohort rotation and Pump's five-second worker are unchanged.
Actual drainage may be slower under authentication, economics and positions;
CPU, persistent storage growth, candidate deadlines and combined provider latency
still require normal-architecture operational evidence.

FAST passed **944 tests**, including all **18** new forward-operation cases.
OPERATIONAL ran **2,365 tests**: 2,329 passed, three original maintenance tests
timed out and 33 existing Model A characterization tests were skipped. The three
failed cases and their native maintenance implementation are byte-identical to
the owner's baseline; they do not execute the changed Survivor paths. Two pass
in isolated replay, while the held-reader archive case still times out. Full
OPERATIONAL is **not green**; deadlines and workload assertions remain intact.
Receipts and earlier failure dispositions are in [VALIDATION.json](VALIDATION.json),
with [the requirement-to-test matrix](TEST_MATRIX.json). The new deterministic
cases cover cold/warm startup, legacy checkpoint migration, four-hour Pons entry,
Pump's separate timing, individual incompleteness, capital denial, outage crossings,
forks, inclusive age bounds, uncapped prospective discovery and position priority.
Synthetic gate-passing prices/quotes are explicitly test fixtures, not successful
market validation. The original stale infrastructure freeze assertion was repaired
to use the owner's supplied baseline while still pinning strategy functions,
both frozen policies, Pump lane files and the nine-change manifest.

`combined_position_and_candidate_provider_latency_not_certified` remains in
production source. A green maintenance/OPERATIONAL result, sustainable Free usage,
authentic combined candidate/position
deadlines, steady drainage, off-host restore and final CAPACITY/RECOVERY/AUTONOMY
acceptance are unresolved. The existing technical proof harness needs its full
resource/response-byte ceilings wired before dispatch; it cannot certify native
positions or mature Survivor qualification with an insufficient sample. These
are concrete evidence gaps; an absent seven-day census is no longer one of them.

The shortest operating sequence is to resolve or reproduce the unchanged
maintenance timeouts under the intended host workload, finish the finite executor
contract, obtain
separate authorization for the bounded **300-second** normal-architecture proof
in [NEXT_PROOF.json](NEXT_PROOF.json), then use the existing exclusive preserved-epoch
Model B cutover and required acceptance phases when validated. The proof ceilings
are 7,200 RPC elements (1,200 Robinhood / 6,000 Solana), 720,000 published RPC CU,
2 GiB native delivery, 128 MiB HTTP responses, 4 GiB group RSS and 30 seconds for
shutdown, with explicit queue/deadline/CPU/write stops. No dispatch is authorized
by this report. A missing mature candidate or authentic position sample is
`INSUFFICIENT_SAMPLE`, never fabricated PASS.

Normal observation then restores money/positions first and observes all four
regimes concurrently. Pump/Pons Current can qualify immediately under their own
rules; Survivor collects independently at once and evaluates individual candidates
at its genuine timing/evidence boundaries. Existing complete candidates resume
after canonical verification. CAPACITY remains 3,600 seconds and AUTONOMY 129,600
seconds with the existing recovery requirements; neither creates a seven-day
Survivor initialization rule. No strategy is reported ACTIVE until its ongoing
observation, qualification and applicable PAPER safety authority actually run.
