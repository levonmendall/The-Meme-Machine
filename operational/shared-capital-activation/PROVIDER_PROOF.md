# Pump/Pons technical provider proof — executed, INCONCLUSIVE

The owner authorized the original proof and then exactly one corrected proof.
Both authorizations are consumed. No further provider run is authorized by these
answers. See [OWNER_APPROVAL.json](OWNER_APPROVAL.json), [PROVIDER.json](PROVIDER.json)
and [PROVIDER_CORRECTED.json](PROVIDER_CORRECTED.json).

The existing `combined_position_and_candidate_provider_latency_not_certified`
blocker remains. The deployed epoch and financial books were never opened by
these runs. The separate disposable proof uses authentic provider functions and
Model B; it does not bypass ordinary operational startup or grant capital.

| Ceiling for each authorized proof | Amount |
|---|---:|
| Total hard wall, including startup/shutdown | 600 seconds |
| Intended steady observation, technical diagnostic only | 180 seconds |
| Solana RPC request elements including retries/batches | 2,000 |
| Robinhood RPC request elements including retries/batches | 1,000 |
| Estimated RPC CU | 150,000 |
| Native/WS received application payload | 64 MiB |
| Estimated native CU | 131,072 |
| Disposable storage | 512 MiB |
| Native errors | Stop at 32 |
| Corrected early payload stop | 48 MiB; 16 MiB maximum-frame margin |

Billed CU and dollar cost are **UNMEASURED**. Planning estimates use the existing
Solana diagnostic method weights, 100 CU per Robinhood request element and
`ceil(native_bytes/512)`. Paid Alchemy and the existing official public Pons
observation RPC both count against the Robinhood allowance. TCP connections are
unmeasured: gRPC streams share a physical channel. Delivering streams are verified
from actual frames; WebSocket opens/deliveries are counted separately.

| Measured evidence | Original logical proof | Corrected proof |
|---|---:|---:|
| Total recorded elapsed / measurement window | 146.560 s / 27.430 s | 19.840 s measurement, including startup |
| Observed steady interval | Short, incomplete | 7.794 s |
| Solana / Robinhood RPC elements | 99 / 13 | 12 / 120 |
| Physical HTTP attempts, Solana / Robinhood | 99 / 9 | 12 / 30 |
| Estimated RPC CU | 4,770 | 12,210 |
| Native payload | 67,115,097 B | 50,331,681 B |
| Estimated native CU | 131,085 | 98,305 |
| Disposable storage | 35,825,425 B | 14,093,147 B |
| gRPC subscription attempts / delivering streams | 16 / 16 | 3 / 3 |
| WebSocket opens / delivering connections | 3 / 3 | 1 / 1 |
| Native errors / RESOURCE_EXHAUSTED | 0 / 0 | 0 / 0 |
| Queue peak / capacity | 43 / 64 | 19 / 64 |
| Oldest observed owner wait | 2.597 s | 6.405 s |
| Stable sustained ordinary drainage | NOT_PROVEN | NOT_PROVEN |
| Complete Pump/PumpSwap executable position samples | 0 | 0 |
| Full Pump candidate hydration | 0 / 14 samples | 0 / 2 samples |
| Pons Current candidate evaluations | Harness failed | 14; complete evidence unproven |
| Pons Current position reads | 0 | 1 failed after 5.175 s |
| Pons Survivor seven-day bootstrap | Incomplete | Incomplete; no complete position sample |
| Main process CPU / peak RSS | 24.769 CPU s / 190.375 MiB | 16.688 CPU s / 135.898 MiB |
| Whole process group CPU / RSS | UNMEASURED | UNMEASURED |
| Paused strategy / monetary workers | 0 / 0 | 0 / 0 |

The first proof exceeded the native payload allowance by **6,233 bytes** (13
planning CU) because shutdown was reactive. It also omitted the operational
pause flag and required Pons evaluator arguments. Its smaller worker roster was
therefore not a valid two-family capacity proof. An initial socket-path failure
used one RPC; the continuation subtracted that usage, elapsed time and storage
from the same authorization. These defects are retained in the evidence.

The corrected proof applied the existing pause gate to Meteora scouts, census,
interests and workers; omitted all Meteora position/candidate work; and performed
no Ramses acquisition. It used complete Pons evaluator arguments and stopped at
48 MiB, within every authorized ceiling. Most native payload was the required
Pump/PumpSwap candidate log feed (48,501,501 bytes). Solana RPC work stopped with
the global payload stop; Pons reported `provider_boundary_failure` on its position
read and incomplete Survivor bootstrap. The queue's last depth reached zero near
shutdown; its normal tail was too short and unstable to prove sustained drainage.

Both Model B startups released; canonical reconciliation passed with 1,789 and
287 distinct canonical events, respectively. This proves preservation of events
actually ingested. Complete independent market history/coverage, rich qualification,
original candidate deadlines and complete native position deadlines remain
**NOT_CERTIFIED**. Corrected provider-to-application delivery latency was about
18 s median for the Pump feed; shared feed median was 37.1 s. No positive latency
claim is drawn from a failed or incomplete sample.

The lower stream count cannot be attributed to removal of paused workloads:
measurement windows and candidate/position demand were different and incomplete.
Likewise, Ramses-only acquisition is absent, but a comparable measured reduction
in Robinhood consumption remains unmeasured. This work does not establish that
the prior 665 connection-error bottleneck has been resolved.

Raw frames, RPC bodies and native disposable databases stay outside Git on the
existing volume. Public summaries include source/artifact SHA-256 values. Source
hashes describe the measured working files; `source_commit` in raw results names
the preserved base and is not a claim that an uncommitted harness was published.

Offline, with zero provider I/O:

```sh
python -m engineering.solana_capacity.pump_pons_proof \
  --limits operational/shared-capital-activation/provider-ceilings.proposed.json
```

A future run needs a separately authorized finite budget that can support the
mandatory historical horizons and a useful sustained observation interval.
Review coverage, physical opens/delivery/rejections, queues, original deadlines,
whole-process resources and storage before clearing the blocker. No existing
request allowance may be silently reused. This diagnostic is not any acceptance
phase and does not shorten CAPACITY's 3,600 s or AUTONOMY's 129,600 s windows.
