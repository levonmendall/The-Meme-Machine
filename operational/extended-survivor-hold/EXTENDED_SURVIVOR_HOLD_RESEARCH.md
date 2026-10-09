# EXTENDED_SURVIVOR_HOLD_RESEARCH

Research disposition: **INSUFFICIENT_EVIDENCE**. Production Pump/Pons Survivor maximums remain **72 hours from original entry**, and the eligible Current bridge remains **36 hours**. This isolated evaluation builds on published optimization `5370a633101620ab87c302546a87212334c400ec`. It changes no strategy, service deadline, epoch or provider allowance. The owner's subsequent exceptional-winner direction authorizes an inactive strategy candidate; this report supplies its baseline and limitations, and does not reject conditional continuation as an economic hypothesis.

## Existing baseline and evidence

Both native Survivors retain original entry age, quantity, remaining basis, high-water, tightened/normal trail, common right-tail gain protection, partial realization and irrevocable pending full exit. Pump first realization is 25% of original quantity at +25% after costs; Pons is 25% at +20%. Hard stops are Pump -12% and Pons -10%. Existing family-specific trailing, two-confirmation demand exits and Pons stale-thesis exits remain active. At 2x and above, both use the existing floor of 60% of the **peak gain**, not 60% of gross price. These are risk signals, not guaranteed execution prices.

| Peak appreciation | Native tail signal reference price multiple | Guaranteed realized outcome |
| --- | ---: | --- |
| 2x | 1.6x | Unknown |
| 5x | 3.4x | Unknown |
| 10x | 6.4x | Unknown |
| 25x | 15.4x | Unknown |
| 50x | 30.4x | Unknown |

Ordinary continuation runs through the original economic deadline, then preserves pending-exit completion and reconciliation under a separate **3,600s / 32-reconnect** recovery envelope. The existing operational maximum is **264,065s** from service start, including latest admission and shutdown. Recovery grants no further speculative upside. Bootstrap funding, economic age, lifecycle count and resource balances never restart.

The prior verified inventory screened **503 databases**, audited **33 sources** and identified **19 distinct coherent copies**. It found **zero reusable complete token-specific economic ranges** suitable for this comparison. Survivor histories contained no usable long-hold market tape. Isolated authenticated headers, including a multi-day min/max span, do not prove intervening economic coverage, remaining-quantity execution or liquidity. Existing Pump provider captures cover about **13.764s active** and **2.379s after release**, not four to fourteen days of token-specific exits. Backup copies are not independent samples. Exact source identities and missing requirements are in `RESOURCE_MODEL.json`; no database was recopied and no provider was contacted.

## Economic comparison

For **both Pump and Pons**, all six horizons and all five appreciation strata have **N=0** independently qualified, continuously observed market lifecycles. Realized net P&L, captured peak profit, gains sacrificed at 72h, losses from later reversal, drawdown, liquidity deterioration, execution fees/spread/slippage/gas, capital recycling, portfolio return and downside risk are **unknown**, recorded as JSON null rather than zero.

| Horizon | Pump 2x / 5x / 10x / 25x / 50x | Pons 2x / 5x / 10x / 25x / 50x |
| --- | --- | --- |
| 72h | All N=0; outcome unknown | All N=0; outcome unknown |
| 96h / 4 days | All N=0; outcome unknown | All N=0; outcome unknown |
| 120h / 5 days | All N=0; outcome unknown | All N=0; outcome unknown |
| 168h / 7 days | All N=0; outcome unknown | All N=0; outcome unknown |
| 240h / 10 days | All N=0; outcome unknown | All N=0; outcome unknown |
| 336h / 14 days | All N=0; outcome unknown | All N=0; outcome unknown |

There is no reliable longest economically justified duration, confidence interval or portfolio profitability comparison. Synthetic profitable trajectories test mechanics only. A valid future comparison must enroll opportunities **before** the 72h boundary, include losers/failures, apply the same original exits and partials, and value actual executable remaining-quantity exits and opportunity costs without retrospective winner selection. No collection is authorized here.

## Infrastructure arithmetic

The frozen application price is $0.525/M CU, with no assumed free allowance, bulk discount, cross-turn quote hit or active-market receipt hit. Pump values below cover optimized snapshot RPC only; native delivered bytes and mandatory gap hydration are additional, unmeasured work. Pons includes original three-second fresh executable quotes, complete economic intervals and canonical checks. Larger ranges remain conditional existing capabilities. Costs exclude bootstrap, extra successful execution checks and actual recovery; those are separately accounted in the primary whole-system model.

| Horizon | Pump snapshot RPC | Pons quiet | Pons ordinary | Pons high volatility | Pons busy |
| --- | ---: | ---: | ---: | ---: | ---: |
| 72h | $2.7321 | $16.8739 | $17.0554 | $22.3171 | $60.4195 |
| 96h | $3.6428 | $22.4986 | $22.7405 | $29.7562 | $80.5594 |
| 120h | $4.5535 | $28.1232 | $28.4256 | $37.1952 | $100.6992 |
| 168h | $6.3748 | $39.3725 | $39.7958 | $52.0733 | $140.9789 |
| 240h | $9.1069 | $56.2464 | $56.8512 | $74.3904 | $201.3984 |
| 336h | $12.7497 | $78.7450 | $79.5917 | $104.1466 | $281.9578 |

Every row's exact method counts, CU, physical attempts and logical elements are in `RESOURCE_MODEL.json`. Quiet Pons grows from **32.14M CU / 1,043,980 elements / 439,180 physical** at 72h to **149.99M / 4,871,899 / 2,049,499** at 336h. Busy 336h is **537.06M / 23,561,770 / 3,401,770**. Volatile/busy minimum rates remain **2.376 / 2.812 RPS**, already exceeding the unchanged local two-RPS governor. Two independent quiet Pons positions need approximately **3.39 RPS**; unverified shared acquisition is not subtracted.

Against unchanged 24M CU, 500,000 elements/physical, $20 RPC/spend component limits, the arithmetic last-fitting durations are:

| Component/scenario | RPC-component bound | Full safe duration proved |
| --- | ---: | --- |
| Pump optimized snapshots | 137.828h | No: stream, gaps, exit latency and complete resource demand unknown |
| Pons quiet | 34.483h | No: below required 72h, bytes/latency unproved |
| Pons ordinary | 33.917h | No |
| Pons volatile | 22.983h | No: request rate also exceeds governor |
| Pons busy | 7.130h | No: request rate also exceeds governor |

These are component bounds, **not permissible holding periods** or guarantees. No horizon above 72h fits the existing operational authorization. Pump 96/120h snapshot arithmetic alone fits some caps; it does not establish full hardware/provider adequacy. The 32-GiB native allowance requires average delivered bytes to fall as duration rises, from 132,560.7 B/s at 72h to 28,405.0 B/s at 336h. The 1-GiB HTTP allowance falls from 12,427.6 B per Pons turn to 2,663.1 B. Neither is a measured payload bound. The existing 2-vCPU/8-GiB host, CPU 1.8, readiness RSS 6 GiB, systemd maximum 7 GiB and queue 64/wait 5s are unchanged.

The degraded model explicitly reserves 10% additional failed physical attempts, at up to 50 elements of 60 CU each per failed batch. It is a conservative stress projection, not an outage probability or enlarged allowance. These attempts must fit original recovery limits and clocks. Exhaustion persists intent and reports `protected=false`; a finite cap cannot guarantee safety under arbitrary failures.

Existing 72h history CPU was **426.84s** for the deterministic two-event/three-second fixture. Linear extrapolation through the longer horizons is workload arithmetic, not a 14-day process benchmark. No new compute instance or recurring service cost is introduced; available full-process CPU, SDK memory and aggregate queue headroom remain unproved. Gross $25 occupancy adds up to $25 times extension-hours of capital-time; actual opportunity cost depends on realized partials and other available opportunities, which are missing.

## Accelerated safety, storage and recovery proof

Final focused run: **12 passed, 0 failed, 0 skipped in 62.583s**, with the supported storage-supervised network-blocked offline driver. Production policy/service/budget source hashes match the published baseline. Exact IDs, commands, source/log hashes, traces and repaired development-fixture failures are in `VALIDATION.json` and `validation/`.

* **1,981,440 pure native risk evaluations** across all six hypothetical horizons: Pons three-second cadence and Pump five-second cadence. Unmodified baseline exits at original 72h for every 2x/5x/10x/25x/50x stratum. Temporary copied policy dictionaries model longer holds only inside the test; all pre-72h decisions match. Original hard, creator, structural, right-tail and pending exits win over the hypothetical extension.
* Both native Books preserve original entry, realized quarter sale, remaining quantity, high-water and durable pending exit through each boundary and near-deadline restart. Actual existing runtime terminal-reconciliation paths repair an interrupted shared release once; duplicate exit notifications add no economic event. Fixture result +22 native units is mechanical accounting, **not market P&L**.
* Native pinned quotes at every horizon reject old >5s evidence, reacquire canonical forks, preserve full/partial quantity distinction and return unavailable on provider faults. Multi-block polling gaps do not imply complete economic history. No internal retry storm or stale cached successful execution is accepted.
* **Actual SQLite**: a dense 24h hot window of one numeric point/second, carried through all proposed boundary timestamps, retains **86,403 points, 3,490 pages, 14,295,040 bytes**, WAL zero after reopen. Re-observation inserts zero rows. Original reducer anchors remain; open history cannot retire, verified terminal history can. CPU **51.60s**, process peak RSS **114,968 KiB**. Deliberately missing intervals stay incomplete and cannot qualify. This exercises real storage/retention/restart; it is not a continuously authenticated 336h market simulation or a maximum-payload guarantee.
* Original operational expiry rejects a proposed 14-day speculative hold, closes funding and reports `protected=false`; cumulative usage and pending intent survive restart without budget renewal.

The primary handoff separately contains actual **72h Survivor** and **36h Current** native history, quote, journal, SQLite count/page pressure, event/window parity and pending-exit tests. Those remain the operational priority and are not duplicated here.

## Exit models and conditional candidate

Model A retains the currently approved fixed 72h exit. Model B's universal longer deadline has no economic support and does not resolve resource constraints. Model C is the owner's intended candidate: ordinary 72h checkpoint, fresh exceptional-winner qualification and automatic bounded renewals, with every original exit winning and no clock, quantity, accounting or resource reset. It is a **candidate hypothesis**, not an approved production policy.

The research initially compares 1/3/6h renewal windows and 96/120/168/240/336h resource stress horizons; none is an economically selected maximum. The subsequent candidate must not turn 7/14 days into an arbitrary forced-sale replacement. It must use native right-tail evidence, realized initial profits, independent demand, healthy activity, executable liquidity and structural health; fresh complete evidence and sufficient finite operational/recovery resources are mandatory at each renewal. Failed qualification or missing evidence must create safe durable exit intent. Ordinary eligible renewals must be automatic after one policy approval, with no cryptographic permits or repeated human approvals.

The most defensible **current operational** policy is unchanged 72h, while the isolated conditional candidate is reviewed. Historical evidence is insufficient to justify its thresholds or realized economics. Resource validation remains the already-prepared primary `CONTINUATION_RESOURCE_OBSERVATION`; it has not run and cannot validate arbitrary long outages or an economically optimal duration. No paid historical collection, deployment, extension, funding or trading is authorized.

Conclusion: **INSUFFICIENT_EVIDENCE** for economic extension support, with additional explicit provider/resource constraints. The exact engineering publication and integration are recorded in the primary handoff; this report never grants operational extension authority.
