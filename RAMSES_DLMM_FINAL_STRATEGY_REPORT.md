# Ramses DLMM Final Strategy Report

**Status:** STRATEGY RESEARCH COMPLETE / BRANCH B DEVELOPMENT REJECTED / PROFITABILITY NOT CERTIFIED  
**Date:** 2026-09-21 / 2026-09-22 UTC evidence cutoff  
**Venue:** Ramses DLMM, Robinhood Chain (chainId 4663)  
**Authority:** research + paper only; no signing, submission, shared allocation, or live-money authority

## Executive conclusion

The blank-slate historical review does **not** support the old Ramses Fee Pulse strategy.

The strongest evidence supports a different strategy:

> **Quiet-established USDG pre-positioning with public-mint geometry, local-depth sizing, strict executable-unwind gating, and a 24–72 hour fee-harvest window.**

The key economic finding is that the best Ramses LP entries were not the hottest visible fee/volume bursts. They occurred when an otherwise-active USDG pool was locally quiet immediately before liquidity was added. Historical realized LP outcomes show that these quiet entries were substantially more profitable than active-window entries, and corrected fee attribution confirms that the edge was meaningfully fee-driven rather than merely token appreciation.

The final exact terminal-state diagnostic also rejected a fixed symmetric short-horizon implementation. Its frozen evaluator selected:

**`branch_B_public_mint_geometry`**

Therefore the strategy should **not** hard-code one 7-, 17-, or 27-bin symmetric range. The range should be derived from the finalized public mint's actual bin set / sidedness / relative deposit geometry and scaled to governed paper capital.

This report now records the terminal strategy-design result. The repaired longer-horizon Branch B development replay **failed the preregistered certification gates**, so no exact rule was frozen and the untouched chronological holdout was deliberately **not opened**. Ramses Quiet-Mint Harvest v1 / branch_B_public_mint_geometry is therefore **not historically profitability-certified**.

---

# 1. Evidence base

## 1.1 Complete indexed Ramses market history

Workflow run: **35660634784**  
Artifact: **10667753690**  
Digest: **sha256:c7706e54e198d43b7f10038690b48405da05ffd7d7d75068e94c01091cb838f7**

Market evidence:
- 284 indexed DLMM pools
- 207 distinct pools with historical activity
- **989,796 swaps**
- **991,864 fee events**
- **92,763 active 5-minute windows**
- **37,172 two-way 5-minute windows**
- existing strategy policy was explicitly excluded from the indexed strategy search

This is sufficient to reject the idea that the earlier one-pool live observation represented the entire Ramses opportunity set.

## 1.2 Expanded realized LP lifecycle sample

Workflow run: **35663549930**  
Artifact: **10668780170**  
Digest: **sha256:2a883745652d140db6ac0357505897fe3433ef938640d3a5f6bd54012c2575d5**

Result:
- **218 clean realized LP lifecycles** after ownership/lifecycle repair.

## 1.3 Expanded strictly pre-entry signal join

Workflow run: **35663820535**  
Artifact: **10668407769**  
Digest: **sha256:4f701da0dc1f9ae0edae4727e38702a15d24f20ebd646b831d8d040529bd2cf4**

Result:
- 191 derivation + validation lifecycles linked to strictly pre-entry 5m/15m/30m market features.
- final chronological holdout remained outcome-blind.

## 1.4 Corrected event-time LP fee attribution

Workflow run: **35667408178**  
Artifact: **10669119524**  
Digest: **sha256:8ef3563f67c10222c0e228795854197409042a0a33ca774798a1203df033c00f**

This repaired the missing fee-event log identity and attributed historical per-bin LP fees against historical user-bin liquidity versions.

The corrected decomposition is the critical proof that the quiet-entry effect is not merely token-direction luck.

## 1.5 Quiet USDG robustness analysis

Workflow run: **35669945624**  
Artifact: **10669843284**  
Digest: **sha256:a787b8e9cf99fdb0e129506cfcb7db3bda169c39e6665177da6108a9e54e3b73**

This decomposed the quiet USDG sample by:
- holding time,
- width,
- sidedness,
- pool,
- owner,
- P&L concentration.

## 1.6 Hot-burst exact replay

Workflow run: **35662680789**  
Artifact: **10668082594**  
Digest: **sha256:d7b489df5dc9cb791f8cc467e5bc653da981ea7220e62e7e5a456dc4ec924971**

Three high-fee / two-way historical burst candidates were replayed with exact Ramses integer mechanics and 12 width variants.

**All 12 variants were negative.**

This rejects "wait for obvious fee pulse, then enter" as the primary strategy.

## 1.7 Terminal-state quiet-entry diagnostic

Workflow run: **35674333987**  
Branch: `research/ramses-terminal-state-counterfactual-v1`  
Head: **d2a3737c7381bdc2b0bf5e7283c57ee59601d282**

Final decision artifact: **10671859590**  
Digest: **sha256:159a4a8fbb48aaab922395e479711a5e3f34009ffb02c6133f8c5ea527ee9347**

Terminal-state equivalence artifact: **10672138725**  
Digest: **sha256:9bf6afb95d93761e1004f1c0bd34e3968e7ce7e37a3f74ad673323df77904c7b**

All six candidate jobs and aggregation completed successfully.

The terminal-state equivalence check found **exact equivalence = true** for all fields used by the frozen strategy evaluator.

---

# 2. What the historical data says

## 2.1 Active-window LP is generally a bad baseline

Corrected fee decomposition:

### Derivation active 30-minute entries
- n = 78
- pools = 25
- gross win rate = **48.7%**
- median fee return = **+0.556%**
- median gross return ~ **0%**
- mean gross return = **-3.95%**
- mean inventory return = **-6.96%**

### Validation active 30-minute entries
- n = 82
- pools = 24
- gross win rate = **40.2%**
- median fee return = **+0.843%**
- median gross return = **-0.044%**
- mean gross return = **-3.35%**
- mean inventory return = **-9.10%**

Interpretation:

High fee generation is real, but entering while the pool is already active exposes the LP to enough adverse selection / inventory conversion that fees do not reliably compensate for the inventory loss.

This matches the negative exact hot-burst replay.

## 2.2 Quiet entry is the strongest repeatable pre-entry signal

Definition used in the realized sample:

**<=2 swaps in the prior 30 minutes**

### Derivation quiet USDG
- n = 23
- pools = 10
- owners = 22
- win rate = **69.6%**
- median gross return = **+0.235%**
- median fee return = **+0.282%**
- median inventory return ~ **0%**
- median hold = **21.3h**
- median width = **15 bins**

### Validation quiet USDG
- n = 5
- pools = 4
- owners = 5
- win rate = **100%**
- median gross return = **+5.773%**
- median fee return = **+9.724%**
- median inventory return = **-0.412%**
- median hold = **44.1h**
- median width = **17 bins**

The validation sample is small and concentrated, so the magnitude must not be extrapolated directly. The important result is the **sign and decomposition**:

**fees remained strongly positive while median inventory contribution was negative.**

That demonstrates a real LP-fee component rather than a pure directional-token effect.

---

# 3. Holding-period evidence

Holding time is a more stable discriminator than exact bin width.

## Derivation

| Hold | n | Pools | Win rate | Median gross | Median fee | Median inventory |
|---|---:|---:|---:|---:|---:|---:|
| <6h | 5 | 3 | 40% | -0.002% | 0.000% | -0.002% |
| 6–24h | 7 | 6 | 57% | +0.004% | +0.136% | -0.048% |
| **24–72h** | **5** | **3** | **80%** | **+0.319%** | **+0.390%** | ~0.000% |
| >=72h | 6 | 5 | 100% | +3.255% | +0.769% | +1.060% |

## Validation

| Hold | n | Pools | Win rate | Median gross | Median fee | Median inventory |
|---|---:|---:|---:|---:|---:|---:|
| <6h | 1 | 1 | 100% | +0.100% | 0.000% | +0.100% |
| **24–72h** | **3** | **3** | **100%** | **+5.782%** | **+9.724%** | **-0.412%** |
| >=72h | 1 | 1 | 100% | +5.773% | +12.061% | -6.288% |

The >=72h region is interesting but too sparse and increasingly exposed to inventory regime risk.

### Strategy conclusion

**Core target holding window: 24–72 hours.**

Do not use a fixed 30-minute, 60-minute, or 4-hour maximum.

Exit can occur earlier for risk/economic reasons, but time alone should not force an early exit.

Do not automatically extend beyond 72h in v1 of the new strategy; that extension requires separate validation.

---

# 4. Range-width evidence

The historical sample does **not** support one universal fixed width.

## Derivation width buckets

| Width | n | Pools | Win rate | Median gross | Median fee |
|---|---:|---:|---:|---:|---:|
| <=8 | 2 | 2 | 50% | **-0.525%** | +0.134% |
| **9–16** | **10** | **7** | **90%** | **+0.277%** | **+0.363%** |
| 17–32 | 5 | 3 | 60% | +0.669% | +0.175% |
| 33–64 | 2 | 2 | 50% | +0.221% | +0.320% |
| >=65 | 4 | 2 | 50% | +0.883% | +0.318% |

9–16 bins has the broadest favorable support in derivation, but validation winners occur at widths of 11, 17, 45, and 79 bins.

### Strategy conclusion

- Reject ultra-narrow <=8-bin default ranges.
- Do **not** hard-code 9–16 bins as the universal strategy.
- The market evidence favors **adaptive geometry**.
- Public mint geometry is a defensible pre-entry source of that geometry because the actual successful LP sample itself is composed of observed public mint positions.

---

# 5. Sidedness evidence

No universal one-sided or two-sided rule is justified.

### Derivation
- two-sided: n=16, 68.8% win rate, median gross +0.187%
- x-only: n=3, 66.7% win rate, median gross +0.235%
- y-only: n=4, 75% win rate, median gross +1.147%

### Validation
- two-sided: n=3, 100% win rate, median gross +5.773%
- y-only: n=1, positive
- x-only: n=1, positive but its fee return was zero

### Strategy conclusion

Preserve the **public mint's sidedness / relative distribution** rather than forcing every Ramses position into one sidedness template.

---

# 6. Exact short-horizon quiet-entry diagnostic

The terminal-state diagnostic evaluated six deterministic quiet USDG public-mint signals.

Frozen test:
- <=2 prior-30m swaps
- >=10 prior-24h swaps
- 0.5% local active-liquidity paper sizing
- symmetric 7 / 17 / 27-bin positions
- 1h / 4h holds
- exact terminal-state reconstruction
- executable same-pool unwind
- final holdout not read

Merged summary:
- 6 candidates
- 36 width/hold observations
- only **18 resolved variants**
- **3 of 6 candidates had unresolved unwind inventory**
- 8 resolved variants were positive
- overall median resolved gross return = **-1 bp**

### 1-hour configurations

| Width | Median gross | Positive rate | Resolved | Result |
|---|---:|---:|---:|---|
| 7 bins | -22 bps | 33% | 3/6 | FAIL |
| 17 bins | -23 bps | 33% | 3/6 | FAIL |
| 27 bins | -23 bps | 33% | 3/6 | FAIL |

### 4-hour configurations

| Width | Median gross | Positive rate | Resolved | p10 | Result |
|---|---:|---:|---:|---:|---|
| 7 bins | +20 bps | 67% | 3/6 | -1116 bps | FAIL |
| 17 bins | +4 bps | 67% | 3/6 | -916 bps | FAIL |
| 27 bins | -1 bp | 33% | 3/6 | -799 bps | FAIL |

Every fixed symmetric combination failed the preregistered execution requirement because only 50% of candidates could be cleanly resolved and the downside distribution was unacceptable.

Candidate heterogeneity was extreme:
- SPY/USDG: positive, including very large 4h terminal-state gains
- RAM/USDG: negative across every 1h/4h width
- NVDA/USDG: weak/mixed
- PAIR/USDG and two website/USDG signals: no full executable unwind

### Mechanical branch decision

The frozen evaluator selected:

> **branch_B_public_mint_geometry**

No short symmetric combination passed.

---

# 7. Final Ramses DLMM strategy definition

## 7.1 Universe

Primary universe:

**Ramses DLMM pools quoted in USDG.**

Reason:
- the strongest realized quiet-entry sample is USDG;
- quote-denominated P&L and unwindability are easier to evaluate;
- it avoids importing the old WNATIVE/fee-pulse assumptions.

Do not require:
- a particular token age,
- U.S. market-session timing,
- a previously profitable LP address,
- a fixed TVL band.

Those filters were investigated and did not have enough robust support to become strategy gates.

## 7.2 Established-but-quiet condition

A pool must be historically active but locally quiet.

Research rule carried forward:

- **prior 30 minutes: <=2 swaps**
- **prior 24 hours: >=10 swaps**

Interpretation:
- "quiet" must mean temporarily dormant,
- not dead / abandoned.

These are development rules from the successful historical signal and must remain frozen through the next exact Branch B validation.

## 7.3 Trigger

Require a **finalized public Ramses DLMM mint** in the qualifying pool.

The public index may nominate the event, but the production-paper path must independently authenticate:
- transaction hash,
- receipt success,
- block hash/header,
- pool address,
- event log index,
- `DepositedToBins` identity,
- exact bin IDs,
- exact deposited token amounts.

No same-block following:

**paper entry must occur no earlier than the next finalized block after the public mint.**

## 7.4 Range construction

Use:

> **the public mint's actual bin geometry, sidedness, and relative token distribution**

scaled to governed paper capital.

Do not use:
- fixed 7 bins,
- fixed 17 bins,
- fixed 27 bins,
- fixed symmetric placement,
- a universal one-sided template.

Why:
- fixed symmetric short-range Branch A failed;
- historical winners span materially different widths;
- width is regime-dependent.

## 7.5 Position sizing

Size from **local executable liquidity**, never total pool TVL.

Initial research ceiling:

**0.5% of local active/range liquidity**

but the exact diagnostic shows even 0.5% can be too large in shallow pools.

Therefore 0.5% is a **ceiling, not a target**.

Required sizing sequence:
1. compute 0.5% local-liquidity ceiling;
2. test complete executable unwind at the entry state;
3. reduce position until full unwind is available;
4. if a meaningful governed minimum position cannot be fully unwound, reject the trade.

An unresolved unwind is a hard failure, regardless of projected fees.

## 7.6 Holding and management

Core target:

**24–72 hours**

with event-driven early exit.

No routine recenter/rebalance is justified by the evidence yet.

Default management:
- hold public mint geometry while economically viable;
- do not exit merely because the pool becomes active after entry — increased activity is the expected harvest phase;
- do not chase price with repeated rebalances;
- if the position exits for risk/economics, wait for a new independent quiet-mint setup.

## 7.7 Early exit

Exit before 72h when any of the following occurs:
- full unwind becomes unavailable;
- active price leaves the economically relevant range and remaining fee opportunity does not justify continuing;
- executable unwind/slippage deteriorates beyond the remaining expected fee reserve;
- inventory/adverse-selection loss exceeds the remaining fee opportunity;
- material pool/liquidity collapse;
- authenticated contract/provider evidence becomes incomplete or stale.

## 7.8 Costs

Use actual current/historical Ramses transaction-cost evidence.

Gas was not the main historical failure mode. Inventory and unwind capacity were.

The strategy must therefore optimize:

**fees - inventory/adverse selection - unwind slippage - transaction costs**

not gross fees alone.

## 7.9 Re-entry

A closed position does not automatically recenter.

Require a **new finalized quiet-mint signal** satisfying the frozen entry conditions before re-entry.

---

# 8. Rules explicitly rejected

The report rejects these as primary Ramses strategy rules:

1. **Hot fee-pulse entry**
   - exact replay negative.

2. **High fee/TVL by itself**
   - high fee density frequently coincides with adverse selection.

3. **High volume/TVL by itself**
   - same problem.

4. **Mandatory two-way/choppy flow**
   - realized winners did not require the most two-way pre-entry tape.

5. **Fixed 1h or 4h exit**
   - historical 24–72h results materially stronger.

6. **Ultra-narrow <=8-bin default**
   - weak derivation results.

7. **Universal 7/17/27-bin symmetric range**
   - exact Branch A failed.

8. **Prior profitable-LP requirement**
   - insufficient support; most quiet winners had no conservative prior closed history.

9. **Clock/session filter**
   - profits were observed across multiple time-of-day regimes.

10. **Pool age as a hard gate**
    - no robust age cutoff justified.

11. **Blind public-mint copying**
    - not allowed. Unwindability and local capacity must be proven first.

---

# 9. Confidence by strategy component

| Component | Confidence | Evidence |
|---|---|---|
| Quiet vs active entry regime | **High** | derivation + validation + fee decomposition + negative hot-burst exact replay |
| USDG focus | **Medium-high** | strongest corrected quiet cohort and cleaner quote P&L |
| 24–72h core hold | **Medium-high** | positive derivation + positive validation across 3 pools |
| Avoid <6h as default | **High** | weak realized history + failed short exact branch |
| Fixed symmetric width | **Rejected** | terminal exact diagnostic |
| Public-mint geometry | **Medium-high as strategy choice** | frozen Branch B decision + historical LP geometry; longer-hold exact replay still pending |
| 0.5% local-liquidity sizing | **Ceiling only** | exact test exposed unresolved unwind at that size |
| Unwind gate | **Very high** | 3/6 terminal candidates failed full unwind |
| No routine rebalance | **Medium** | no robust evidence that chasing range improves returns |
| Exact prospective return magnitude | **Low/unknown** | insufficient Branch B exact + holdout evidence |
| Final profitability certification | **Not yet granted** | final Branch B exact validation + chronological holdout still required |

---

# 10. Final strategy state

## Strategy definition

**Ramses Quiet-Mint Harvest v1 candidate**

1. Search Ramses USDG pools.
2. Require an established pool: >=10 swaps in trailing 24h.
3. Require local quiet: <=2 swaps in trailing 30m.
4. Observe a finalized public DLMM mint.
5. Authenticate the mint independently on-chain.
6. Enter no earlier than the next finalized block.
7. Copy its bin geometry / sidedness / relative distribution.
8. Size at <=0.5% local active/range liquidity and then reduce until full unwind is executable.
9. Reject if full unwind cannot be proven.
10. Harvest for a **24–72h core window**.
11. No routine recentering.
12. Exit early on unwind deterioration, adverse-selection/inventory dominance, range failure, evidence failure, or liquidity collapse.
13. Re-enter only on a new independent quiet-mint setup.
14. Paper-only until certification.

## Certification state

**Strategy architecture: FINALIZED.**  
**Profitability certification: NOT FINALIZED.**

The exact terminal diagnostic has finalized the branch choice and rejected fixed short symmetric ranges.

The remaining certification sequence is:
1. exact Branch B public-mint-geometry replay over the development sample;
2. conservative actual-cost sensitivity;
3. breadth/concentration check;
4. freeze exact rules;
5. only then open the untouched chronological holdout;
6. require positive holdout median + mean after-cost return, >55% win rate, and multi-pool support before calling the strategy historically certified.

Until those gates pass, this strategy may be implemented only as a **paper/shadow candidate**, not as a claimed profitable system.

---

# 11. Implementation note

A draft `strategy/ramses-quiet-mint-v2` branch was started during research, but the user explicitly requested strategy review before implementation.

Therefore this report is authoritative over that draft.

**Do not promote the draft strategy branch based solely on its current code.**  
Implementation should be reconciled to this final report after review/approval.

---

# 12. Bottom line

The market review found a plausible Ramses DLMM edge, but it is **not** "provide liquidity during the hottest volume."

The best-supported strategy is:

> **be positioned before the fee burst, in an established USDG pool that has gone quiet, using the geometry revealed by a finalized public LP mint, at a size that can be fully unwound, and hold through the subsequent fee cycle for roughly 24–72 hours unless inventory or exit economics deteriorate.**

The data strongly support the **entry regime** and **holding horizon**.

The terminal exact replay strongly rejects fixed short symmetric ranges and proves that **unwindability is a first-class strategy gate**.

That is the Ramses DLMM strategy definition to carry forward.


---

# 12. Terminal Branch B certification result

Final repair/completion workflow: **35685789656**  
Final decision artifact: **10676927755**  
Final workflow conclusion: **success** (the research workflow completed; the strategy gate itself failed)  
Holdout outcomes read: **false**

The final repaired development set overlaid only the ten mechanically repaired candidates onto the original 24-candidate preregistered development cohort. Strategy rules, candidate selection, public-mint geometry, sizing schedule, holding periods, conservative cost anchor, 2x cost stress, breadth criteria, and profitability thresholds were unchanged.

Final coverage:
- 24 preregistered development candidates
- **20 completed candidates**
- **16 distinct completed pools**
- 4 remaining fail-closed mechanical rejections
- no holdout observations opened

The four terminal mechanical rejections were:
- candidate 0: public geometry could not be represented at any permitted size without scale underflow;
- candidate 18: next-block geometry was wrong-sided at every permitted size;
- candidates 3 and 5: full executable unwind could not be proven even at the minimum permitted size.

## Certification-eligible 24-hour horizon

- resolved observations: **15**
- pools: **12**
- win rate: **0%**
- median after-cost return: **-510 bps (-5.10%)**
- mean after-cost return: **-6,581.53 bps (-65.82%)**
- equal-pool-weighted median: **-740 bps (-7.40%)**
- equal-pool-weighted mean: **-8,161.79 bps (-81.62%)**
- 2x-cost-stress median: **-727 bps (-7.27%)**
- 2x-cost-stress mean: **-12,410.07 bps (-124.10%)**
- preregistered development gate: **FAIL**

## Certification-eligible 72-hour horizon

- resolved observations: **14**
- pools: **10**
- win rate: **14.29%**
- median after-cost return: **-239.5 bps (-2.395%)**
- mean after-cost return: **-6,270 bps (-62.70%)**
- equal-pool-weighted median: **-410 bps (-4.10%)**
- equal-pool-weighted mean: **-8,685.2 bps (-86.85%)**
- 2x-cost-stress median: **-498.5 bps (-4.985%)**
- 2x-cost-stress mean: **-12,244.36 bps (-122.44%)**
- positive-PnL concentration in the largest contributing pool: **93.70%**, versus the preregistered <=40% ceiling
- preregistered development gate: **FAIL**

The development prerequisite also required at least **20 resolved observations at the selected certification horizon**. Neither 24h nor 72h reached that minimum. More importantly, the resolved economics themselves were strongly negative, so the failure is not merely a sample-size technicality.

## Final decision

**development_gate_failed**

No Branch B rule was frozen. No profitability claim is granted. The final chronological 20% holdout remains untouched and should remain untouched for this strategy specification. Opening it after a failed development gate would violate the preregistered research protocol and spend the protected holdout on a rule that already lacks development support.

The completed research therefore supports this final interpretation:

- the historical quiet-USDG observation was a useful research lead;
- fixed short-horizon symmetric geometry was rejected;
- exact public-mint geometry was the strongest remaining implementation hypothesis;
- after exact mechanics, executable-unwind requirements, conservative costs, repaired event decoding, repaired cost-route evidence, and broader development coverage, **that hypothesis did not demonstrate a certifiable after-cost edge**.

Any future Ramses strategy would require a **new preregistered strategy hypothesis and a new development protocol**. The untouched holdout from this campaign must not be repurposed to tune the rejected Branch B rule.
