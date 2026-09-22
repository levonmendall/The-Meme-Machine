> **Superseded:** This interim simplification was written before reconciling the earlier frozen v1/v2 work. The authoritative current rebalance specification is `RAMSES_ACTIVE_WIDE_MAKER_REBALANCE_V3.json`. The v3 rule preserves the v2 hysteresis/overlap controller and adds the pre-holdout capital-preservation gate.\n\n# Ramses Rebalance Logic Analysis

**Status:** SUPERSEDED INTERIM ANALYSIS — SEE RAMSES_ACTIVE_WIDE_MAKER_REBALANCE_V3.json  
**Holdout:** historical chronology was already consumed by the earlier frozen v1 rule; it produced zero eligible >=65-bin rebalances and cannot be reused  
**Data source:** frozen pre-holdout Ramses owner/bin, burn-owner, and swap/fee history

## Executive conclusion

The profitable-operator data does **not** support a single rule such as “rebalance after X bins” or “rebalance when fees fall Y%.”

It supports a state machine:

1. **Do not wait for range escape.**
2. Start proactive replacement evaluation once the active bin reaches the outer half of the current range.
3. If the active bin exits the range, either rebalance immediately or exit.
4. When rebalancing, preserve approximately the same capital, remint quickly, and stay wide.
5. If those mechanics cannot be satisfied, do not chase the position with more capital.

That is the current Ramses Active Wide Maker v1 rebalance logic.

---

## 1. Study cohort

The rebalance study used the same pre-holdout strategy region identified by the Ramses profit map:

- USDG pools
- quiet initial entry: <=2 swaps in the prior 30 minutes
- initial range >=65 bins
- initial placement two-sided

This produced **70 closed pre-holdout books**.

### Quick adjustment versus no quick adjustment

A “quick rebalance” means a burn followed by a replacement mint within one hour.

| Cohort | Books | Win rate | Lower-bound P&L | Median return |
|---|---:|---:|---:|---:|
| Quick rebalance | 19 | **78.9%** | **+USD 88,504** | **+2.67%** |
| No quick rebalance | 51 | 60.8% | +USD 29,337 | +1.77% |

The evidence therefore supports active adjustment rather than passive hold.

---

## 2. The first quick rebalance is highly informative

Eighteen books had a fully reconstructable first quick rebalance with authenticated range geometry and active-bin state.

- 15 winners
- 3 losers
- 12 owners
- 17 pools
- aggregate lower-bound P&L: **+USD 88,504**

### Replacement width

**Replacement width >=65 bins:**

- 10 observations
- **10 winners**
- 7 owners
- 9 pools
- +USD 55,967 aggregate lower-bound P&L

The losing first-rebalance replacements were only 16, 32, and 42 bins.

### Remint speed

**Burn-to-remint <=180 seconds:**

- 13 observations
- 12 winners
- **92.3% win rate**
- +USD 93,243 lower-bound P&L

Winner median delay: **70 seconds**.  
Loser median delay: **260 seconds**.

### Capital preservation

Define:

replacement ratio = replacement position quote value / burn proceeds quote value

**Replacement ratio 0.80-1.20:**

- 10 observations
- **10 winners**
- 9 owners
- 9 pools
- +USD 84,227 lower-bound P&L

Winner median ratio was approximately **1.00**.

The losing examples did the opposite: they either redeployed only a small fraction of the withdrawn capital or injected several times the burn proceeds.

That is strong evidence against “averaging down” or materially increasing capital after an adverse move.

### Combined contract

**width >=65 + remint <=180 seconds + capital ratio 0.80-1.20:**

- 6 first rebalances
- **6 winners**
- 5 owners
- 6 pools
- +USD 47,655 lower-bound P&L
- median book return: **+14.6%**

Adding a two-sided/active-inside requirement leaves 5 observations, all profitable.

This is the strongest directly observed rebalance execution contract.

---

## 3. All quick adjustments confirm the same pattern

Across all reconstructable quick burn-to-mint transitions in the qualifying books:

- **35 transitions**
- 18 books
- winning books: 27 transition observations
- losing books: 8 transition observations

At the **book level**:

### Winning books

Median values:

- share of transitions with replacement width >=65: **100%**
- share with burn-to-remint <=180s: **100%**
- share preserving 80-120% of burn capital: **100%**
- median replacement width: **77 bins**

### Losing books

Median values:

- share with replacement width >=65: **0%**
- share preserving 80-120% of burn capital: **0%**
- median replacement width: **32 bins**
- median capital replacement behavior was materially distorted

This is why the rule treats width and capital preservation as hard mechanics rather than optional preferences.

---

## 4. Why there is not one displacement trigger

Define normalized displacement:

D = abs(active_bin - range_center) / range_half_width

Interpretation:

- D = 0: centered
- D = 0.5: active bin has moved halfway from center to edge
- D = 1.0: active bin is at the edge
- D > 1.0: active bin is outside the range

Observed quick-transition outcomes:

| State at burn | Approximate definition | Transition win-book rate |
|---|---|---:|
| Centered | D < 0.5 | **90.9%** |
| Edge zone | 0.5 <= D <= 1.0 | 77.8% |
| Outside / strongly displaced | D > 1.0 | 66.7% |

The important finding is **not** that centered positions should always rebalance.

It is that waiting until the position is already outside the range is worse. Skilled profitable operators often adjust proactively before complete range failure.

Therefore:

- **D >=0.50** is the proactive-review boundary.
- **D >=1.00** is the hard rebalance/exit boundary.
- D <0.50 by itself is **not** a rebalance trigger.

---

## 5. Fee and activity changes are not reliable standalone triggers

The study also measured trailing LP fee production, swap activity, and active-bin movement before burns.

There was no clean threshold where:

- a particular fee spike,
- a particular fee decline,
- a particular 15m/30m active-bin move,
- or a fixed number of swaps

separated profitable from losing rebalances.

For example, winning adjustments occurred in both:

- quiet/zero-fee periods, and
- very active/high-fee periods.

Similarly, the replacement range did not need to have a higher trailing fee-per-bin value than the old range. Losing operators sometimes moved into apparently higher recent fee-density ranges and still lost.

Therefore **recent fee density alone must not authorize a rebalance**.

The relevant economic objective remains:

expected fees - inventory/adverse-selection risk - rebalance cost - terminal unwind cost

but the operator evidence does not support reducing that objective to a single recent-fee threshold.

---

## 6. Frozen v1 state machine

### Monitor

Evaluate the open position on every finalized block.

Calculate:

- active bin
- lower/upper range
- normalized displacement D
- current range width
- sidedness/inventory state
- full executable unwind
- candidate replacement geometry
- replacement notional relative to burn proceeds

### Normal state: D <0.50

Hold by default.

Do not churn merely because fees change.

A rebalance may only occur here if a separately validated inventory/economic condition requires it. The current v1 does not authorize fee-only churn.

### Proactive zone: 0.50 <= D <1.00

Begin replacement preparation.

Before burning, require a replacement that satisfies all hard mechanics:

- width >=65 bins
- full executable unwind at current state
- expected replacement notional within 80-120% of burn proceeds
- evidence current/finalized

If those cannot be met, continue monitoring or exit rather than add capital.

### Hard zone: D >=1.00 or active bin outside range

The position is no longer acceptable as a normal active-maker range.

Either:

1. burn and redeploy under the replacement contract, or
2. exit to USDG/cash.

Do not leave a failed range open solely to avoid realizing inventory conversion.

---

## 7. Replacement contract

A valid v1 rebalance must satisfy:

### Speed

**Burn-to-remint target: <=180 seconds.**

If the replacement cannot be completed within that window because state/evidence has changed, remain out rather than chase.

### Width

**Minimum replacement width: 65 bins.**

Preferred research band:

**65-200 bins**

The rule does not hard-code one width inside that region; final width is selected from executable local depth and inventory risk.

### Capital

**Replacement notional: 80-120% of burn proceeds.**

Default target is approximately 100%.

No averaging down.  
No doubling the position to rescue a losing range.

### Sidedness

Default:

**two-sided**

The data contain profitable high-bin-step one-sided repair exceptions, so two-sided placement is the v1 default rather than a universal claim about every profitable Ramses position.

### Active-bin placement

Preferred:

**active bin inside the replacement range**, ideally within the inner 75% of the new half-width.

This is a preference, not a hard v1 rejection, because some profitable high-step operator repairs intentionally placed the active bin at or slightly beyond an edge.

### Unwind

**Full executable unwind remains mandatory.**

A replacement that cannot be completely exited is rejected regardless of its projected fees.

---

## 8. What this logic explicitly prevents

The rule prevents the failure modes observed in losing operator books:

- waiting until catastrophic range displacement before preparing a replacement
- reminting slowly after the burn
- replacing a wide range with a narrow one
- injecting several times the withdrawn capital after an adverse move
- redeploying only a tiny residual fraction without an intentional exit decision
- using a fee spike as the sole reason to chase a new range
- leaving capital trapped in a range without a proven terminal unwind

---

## 9. Current confidence

### High confidence

- active adjustment materially outperformed passive books
- capital preservation around 1:1 is important
- wide replacement ranges are materially safer
- remint latency matters
- waiting until full range escape is inferior
- full unwindability is non-negotiable

### Medium confidence

- D=0.50 as the proactive-review boundary
- two-sided replacement as the default
- preferred 65-200-bin range band

These are conservative translations of the observed operator behavior and still require paper validation.

### Not supported as hard rules

- fixed timed rebalance
- one fee-density threshold
- one swap-count threshold after entry
- one exact displacement value that explains every profitable rebalance

---

## Final v1 logic

> **Monitor continuously. Hold while the active bin remains in the inner half of a valid wide range. Once it enters the outer half, prepare a replacement. At range escape, rebalance or exit. When rebalancing, redeploy approximately the same capital within three minutes into a fully unwindable >=65-bin range, normally two-sided. Never add capital to rescue an adverse move.**

This is the most defensible exact rebalance logic supported by the current Ramses operator evidence.

It remains **shadow/paper only** until exact replay and prospective paper validation.
