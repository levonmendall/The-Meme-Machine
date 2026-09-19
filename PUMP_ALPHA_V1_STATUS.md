# Pump Alpha v1 — independent Pump.fun / PumpSwap strategy family

## Boundary

pump-alpha-v1 is independent of continuation-v1, the market-native priority selector,
Fomo research, and DLMM. It consumes normalized point-in-time Pump/PumpSwap
observations and emits only its own paper-strategy signals. It never calls
Engine.consider, never changes an existing qualification threshold, and has no
shared-allocator, signing, submission, deployment, or live-money authority.

Hard authorization gates are separate from ranking. A high score cannot compensate
for failed concentration, trajectory, demand, price, or freshness gates.

## Strategy family

### Late-curve acceleration

The pre-graduation mode requires an incomplete late bonding curve plus high recent
curve velocity and positive acceleration. Independent buyer breadth, buyer growth,
net demand relative to the curve's quote-asset graduation target, concentration,
freshness, and extension are hard gates.

The score then ranks passing candidates using curve position, velocity, acceleration,
buyer breadth and growth, net demand, quote-relative strength, skilled-wallet
convergence, and creator history. Concentration and extreme extension reduce ranking.

### Skilled-wallet convergence

Wallet quality is confirmation only. Historical skill must have been established
before the observed trade. A profile needs a minimum historical sample, positive
historical ROI, and positive historical net P&L. Wallets sharing a funding group
collapse into one independent group, and creator-related wallets are excluded.

Confirmation also requires unrelated buyer groups to arrive after the first skilled
entry. This prevents a small coordinated group from manufacturing the signal.

### Creator quality

Creator quality is point-in-time confirmation only. History must predate the current
decision. A strong creator profile can improve ranking but cannot rescue a candidate
that fails the trajectory or demand gates.

### Pump to PumpSwap graduation continuation

A qualifying pre-graduation state becomes graduation_pending after an authenticated
canonical graduation. It can continue as a PumpSwap carry only when independent
post-graduation demand qualifies. Otherwise the state becomes exit_required after the
fixed grace interval.

### Immediate post-graduation momentum

A flat strategy can enter after graduation. It requires new independent buyers,
positive quote-normalized net demand, price at or above the graduation reference, a
shallow pullback, accelerating buy volume, non-declining buy size, limited early
holder distribution, and acceptable concentration.

### PumpSwap second-leg breakout

The second-leg mode requires the complete sequence: initial rally, bounded pullback,
minimum consolidation duration, fresh breakout, new buyer groups not present in the
earlier wave, positive net demand, and limited early-holder distribution.

### Quote-relative strength

All price features use the on-chain TOKEN/QUOTE ratio from the actual trading pair.
SOL-paired signals are therefore TOKEN/SOL and a future custom quote pair naturally
becomes TOKEN/that-quote rather than mistaking movement in the quote asset for token
alpha.

The current executable Pump adapter is still native-SOL only. Non-SOL/custom-quote
signals remain fail-closed for execution until the corresponding quote and accounting
adapter is independently verified.

## Exit behavior

The independent exit evaluator is momentum-oriented: hard stop, trailing drawdown
after a positive peak, maximum hold, net-demand reversal, or combined buyer/volume
deceleration can end the position.

## Validation rule

This is a frozen candidate policy, not profitability evidence. Unit and synthetic
results prove mechanics only. Natural prospective testing must preserve decision-time
features, executable entry/exit quotes, graduation lineage, post-graduation buyer
identity, and all costs. Do not refit thresholds from the first successful sample and
do not infer allocation authority from a small number of wins.
