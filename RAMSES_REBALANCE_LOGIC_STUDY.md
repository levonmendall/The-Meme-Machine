> **Superseded:** Historical v2 design study retained for lineage only. The authoritative current specification is `RAMSES_ACTIVE_WIDE_MAKER_REBALANCE_V3.json`. The original chronological v1 holdout has already been consumed and cannot be reused.

# Ramses Exact Rebalance Logic Study

**Status:** HISTORICAL / SUPERSEDED BY RAMSES_ACTIVE_WIDE_MAKER_REBALANCE_V3.json  
**Strategy:** Ramses Active Wide Maker v1  
**Protected holdout:** consumed by frozen v1; zero v1-eligible >=65-bin rebalance observations; unavailable for reuse  
**Authority:** research + paper only

## Executive conclusion

The profitable Ramses operators do **not** follow one universal "move the range after X bins" rule.

Their profitable behavior splits into two distinct actions:

1. **Compound / resize while the active bin is still inside a productive range.**
2. **Full recenter after the active bin has left the old range.**

The weak behavior is the middle case: narrow partial shifts that neither preserve the productive range nor fully recenter it.

The most robust common rule is the replacement geometry and speed:

> **Never remint narrower than 65 bins; replace promptly from fresh state.**

Within the intended strategy segment — USDG, quiet initial entry, initial width >=65 bins, initially two-sided — the first quick-rebalance sample contained:

- 18 books
- 12 owners
- 17 pools
- 15 profitable books
- lower-bound aggregate P&L: **+USD 88,504**

Every observed first quick rebalance that replaced the range at **>=65 bins** was profitable:

- **10/10 wins**
- 7 owners
- 9 pools
- **+USD 55,967** lower-bound P&L

Restricting that to replacements completed within **210 seconds**:

- **9/9 wins**
- 7 owners
- 8 pools
- **+USD 55,544**
- median book return **+12.78%**

The three losing quick-rebalance books replaced at only **16, 32, and 42 bins**, with a median burn-to-remint delay of **260 seconds**.

This is the strongest directly observed rebalance discriminator.

---

## 1. State variable

For the current occupied range:

- lower bin = L
- upper bin = U
- active bin = A
- center = C = (L+U)/2
- half width = H = max(0.5,(U-L)/2)

Define:

**D = abs(A-C) / H**

Interpretation:

- D < 1: active bin remains inside the range.
- D = 1: active bin is at an edge.
- D > 1: active bin has left the range.

This is evaluated only from finalized authenticated Ramses state.

---

## 2. Two rebalance modes

### Mode A — compound / resize

Use this mode only while A remains inside the old range.

The profitable operator sample shows that some successful burn/remint events occur with the active bin still close to the range center. Those are not true recenters. They largely preserve the old range and resize/redeploy it.

Observed resize/compound cluster:

- 4/4 profitable
- **+USD 30,399** lower-bound P&L
- median D: ~0.21
- median old/new overlap: ~72%
- median replacement width: 96 bins

Therefore v1 does **not** use price movement alone to trigger an in-range rebalance.

A compound/resize requires:

1. active bin still inside [L,U];
2. full current unwind executable;
3. attributable fee reserve since the last mint/resize >= **2x the complete rebalance cost**;
4. an executable >=65-bin replacement exists;
5. new and old bin sets overlap by at least **50%**.

If these are not true, hold the range.

This prevents the system from mechanically chasing every active-bin movement.

### Mode B — geometric recenter

A true recenter begins on the **first finalized state in which the active bin leaves the current range**.

Trigger:

> **A < L or A > U**, equivalently **D > 1.0**.

At that point:

1. burn the old position;
2. reread finalized state;
3. construct a fresh broad replacement;
4. require complete executable unwind;
5. remint only if the new economics remain positive after 2x cost stress.

The profitable fee-driven recenter examples were observed around D ~2.5–2.8 by the time the historical operator actually acted. A major failed reset was not performed until approximately D=5.51.

The strategy therefore acts **earlier than the historical lag**: first confirmed range exit triggers the recenter rather than waiting until the position is deeply stranded.

If D exceeds **3.0** before a valid replacement is ready, v1 does not chase the market. It exits/holds quote and waits for a fresh state.

---

## 3. Replacement geometry

The replacement is not allowed to become a narrow range.

Hard floor:

> **65 bins**

Candidate grid:

- 65
- 90
- 120
- 150
- 200 bins

For every candidate:

- active bin must be inside the replacement;
- full unwind must be executable at the new state;
- the complete lifecycle must remain positive under 2x cost stress.

Among candidates that pass, choose the highest expected after-cost fee return. Use the narrower width only as the tie-breaker.

Observed fast profitable wide replacements had:

- p25 width ~87 bins
- median width ~119 bins
- p75 width ~153 bins

So 90–150 bins is the empirical center of the successful region, while 65 is the hard minimum.

---

## 4. Do not use partial shifts

The historical transitions were classified by how much the new and old bin sets overlapped.

### Preserve / resize
- >=50% old/new overlap
- 4/4 wins in the clear resize/compound cluster
- +USD 30.4k

### Full reset / recenter
- <=10% overlap or a very large center displacement
- 7/8 wins in the observed reset cluster
- +USD 54.9k

### Partial shift
- between those regimes
- only 4/6 wins
- approximately +USD 3.2k total
- materially weaker economics

Therefore Ramses Active Wide Maker v1 **prohibits intermediate 10–50% overlap shifts**.

A rebalance must either:

- preserve the existing productive range substantially; or
- make a genuine fresh recenter.

No half-measures.

---

## 5. Execution speed

The wide profitable rebalance cluster completed extremely quickly.

For >=65-bin replacements:

- 9 profitable examples finished within **210 seconds**;
- 9/9 were winners;
- aggregate P&L +USD 55.5k.

v1 therefore uses:

- operational target: **<=180 seconds**
- hard same-decision deadline: **210 seconds**

If the remint cannot be completed from the same valid state by 210 seconds:

1. discard the stale replacement;
2. reread finalized state;
3. rerun the complete range/economic decision.

Do not submit a stale geometry.

---

## 6. Sidedness

Seven of the nine fast wide profitable replacements were two-sided.

Two one-sided exceptions were also profitable, but the sample is too small to establish a transferable one-sided rebalance rule.

Therefore:

> **Two-sided replacement is required in v1.**

One-sided inventory repair remains a separate research question and is not authorized by this rebalance specification.

---

## 7. Sizing

Rebalancing is not permission to increase risk.

Use range-local executable liquidity only.

Maximum:

**0.50% of local executable/range liquidity**

Reduction schedule:

**50 -> 25 -> 12 -> 6 -> 3 -> 1 bps**

The reminted position must be no larger than:

- the governed target size; and
- the largest position that can be completely unwound.

No automatic size-up during a recenter.

---

## 8. Exit instead of rebalance

Do not remint when any of these is true:

- no executable replacement of at least 65 bins exists;
- complete unwind cannot be proven;
- expected after-cost economics fail 2x cost stress;
- active state / receipts / provider evidence are incomplete;
- D > 3 before replacement is ready;
- two-sided deployment would require uneconomic inventory conversion.

In those states, exit to governed quote inventory and wait.

---

## 9. Exact state machine

### HOLD
If active bin is inside the range and compound economics do not pass:

**hold**.

### COMPOUND_RESIZE
If active bin remains inside, fee reserve >=2x rebalance cost, full unwind is executable, and an >=65-bin replacement with >=50% overlap passes:

**burn -> recompute -> broad two-sided remint**.

### RECENTER
At the first finalized range exit:

**burn -> recompute from fresh state -> broad two-sided remint**.

Replacement must have <=10% old/new overlap for a true recenter.

### EXIT
If the replacement gates fail:

**do not remint**.

---

## 10. Evidence boundary

This is a frozen **pre-holdout research rule**, not a profitability certification.

The protected chronological holdout remains unread.

The next valid step is targeted exact replay / paper validation of this rule. The thresholds must not be loosened because a replay fails.

