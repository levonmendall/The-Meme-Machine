# Pump acceleration independent strategy v1

Branch: `feat/pump-acceleration-independent-v1`

Base: `research/market-native-opportunity-outcomes@967b625d117c96570811cb07d5616b26e3065231`

## Independence boundary

This strategy family is separate from `continuation-v1`.

It does not import or call `Engine.qualify`, does not reuse the continuation-v1
score or thresholds, does not consume another strategy's order as authority, and
does not modify the existing strategy, DLMM work, Fomo work, or Robinhood work.

It may share authenticated Pump/PumpSwap market-data and low-level quote machinery,
but shared infrastructure never grants strategy authority.

The strategy ID is:

`pump-acceleration-independent-v1`

The three executable paper modes are:

1. `late_curve_acceleration`
2. `post_graduation_momentum`
3. `pumpswap_second_leg`

Skilled-wallet convergence, creator quality, and quote-relative strength are
confirmation inputs. None can authorize a trade alone.

## Frozen v1 late-curve policy

The first paper/research version intentionally requires more than curve position:

- curve progress >= 70%;
- curve velocity >= 20 basis-points of curve progress per second;
- non-negative measured curve acceleration;
- >= 3 independent buyer clusters;
- positive recent buyer growth;
- net-buy share >= 60%;
- concentration <= 35%;
- extension <= 120%;
- composite score >= 65.

The score adds trajectory speed, acceleration, buyer growth, net demand, independent
historical wallet convergence, creator history and quote-relative strength, while
penalizing concentration and extension.

These are frozen v1 research/paper thresholds, not a profitability claim.

## Skilled-wallet confirmation

Wallet skill is only counted when all required history predates the decision.
Wallets that share a funding group collapse to one independent cluster. Creator-linked
wallets are excluded. Future skill results cannot backfill an earlier decision.

## Creator-quality confirmation

Creator quality requires a minimum history sample and must be known before the
decision timestamp. It only adds confirmation/score. A good creator cannot override
failed trajectory, demand, concentration, or extension gates.

## Pump -> PumpSwap continuation

A late-curve paper position may change its surface from Pump.fun to PumpSwap only
after an authenticated graduation handoff. Graduation itself does not force a hold.

After graduation, the independent exit controller requires continuing demand. If
post-graduation demand is not confirmed within the fixed grace window, the position
exits rather than treating migration as bullish by itself.

## Immediate post-graduation momentum

The post-graduation mode waits at least 5 seconds and no more than 180 seconds after
graduation. Entry requires:

- authenticated graduation;
- >= 4 independent buyer clusters;
- positive buyer growth;
- net-buy share >= 60%;
- price above the graduation reference;
- non-negative volume acceleration;
- early-holder sell share <= 35%;
- concentration <= 35%;
- composite score >= 65.

The paper exit policy uses a hard -10% stop, a 12% drawdown from peak, demand
deceleration, or a 300-second timeout.

## PumpSwap second leg

Second-leg entry requires the token to survive graduation and initial distribution,
then show:

- age >= 30 seconds after graduation;
- >= 20 seconds of consolidation;
- a 3%-35% pullback;
- >= 5% breakout from the consolidation reference;
- >= 4 independent buyer clusters;
- positive buyer growth;
- net-buy share >= 60%;
- early-holder sell share <= 35%;
- concentration <= 35%;
- composite score >= 65.

The independent paper exit controller uses the same hard stop and trailing momentum
exit, with a 600-second maximum hold.

## Relative strength

The strategy core is quote-asset native. For a token quoted in NVDAX, SPYX, TSLAX,
GOOGLX, GLDX, SOL, or another supported quote, the relative-strength feature is
TOKEN/QUOTE rather than an inherited USD move.

The helper also supports converting synchronized TOKEN/USD and QUOTE/USD returns into
TOKEN/QUOTE return.

### Current execution boundary

The existing repository Pump execution adapter still fails closed on non-native quote
assets. This strategy core deliberately does **not** weaken that adapter. Non-SOL quote
signals can be scored/researched now, but paper execution on those curves must remain
disabled until a separate adapter proof establishes exact reserve, fee, settlement,
and accounting behavior.

## Paper authority

`PumpAccelerationPaperLifecycle` is strategy-local state only. It has no genesis
capital and no allocator authority. A caller must first obtain a budget from the
existing shared paper-portfolio governance. This avoids creating a second hidden
portfolio while keeping the strategy decision and lifecycle independent.

No signing, transaction submission, live money, or deployment is introduced.
