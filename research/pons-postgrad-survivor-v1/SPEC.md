# Pons Post-Graduation Survivor Momentum v1

## Status

New independent PAPER strategy candidate.

It is not an extension of the active pre-graduation Pons policy and does not consume
its qualifiers, positions, wallet scores, thresholds or outcomes.

## Public-market basis

The design uses only open-market observations from the Pons post-graduation segment
for approximately 2026-09-19 through 2026-09-26.

Five public examples illustrate the structure:

| Asset | 7-day return | 7-day range | max drawdown | best approx. 24h move |
| --- | ---: | ---: | ---: | ---: |
| BUN / Bundle Cat | +193.0% | 239.4% | 34.4% | +206.4% |
| SHROOM | +45.0% | 169.2% | 34.5% | +77.3% |
| PARE | -55.6% | 269.4% | 72.9% | +35.2% |
| ROBIN | -59.0% | 155.2% | 60.8% | +67.9% |
| UBIK | -2.0% | 56.4% | 32.3% | +50.0% |

The central observation is not merely that winners can move dramatically. Large
one-day rebounds also occur inside losing trends. Therefore the strategy must not
treat volume or a single sharp breakout as sufficient evidence.

## Thesis

After graduation, a small subset of Pons tokens survives long enough to develop
meaningful secondary liquidity and independent price discovery. The target setup is:

1. authenticated Pons graduation;
2. at least six hours of post-graduation survival;
3. persistent positive trend from graduation, over the long window, six hours and
   two hours;
4. a genuine 5-35% reset from an earlier post-graduation peak;
5. a two-hour base;
6. a fresh but not overextended breakout above the pre-breakout base;
7. expanding independent buyer breadth and accelerating buy flow;
8. low enough executable round-trip friction for a small position.

This deliberately avoids:

- buying immediately because a token graduated;
- ranking by raw volume alone;
- chasing a vertical candle after the breakout is already extended;
- buying a large rebound while the token remains below its broader post-graduation
  trend;
- thin pools where nominal upside cannot be captured at executable prices.

## Frozen candidate policy

### Universe

- 6 hours to 7 days after graduation.
- Authenticated Pons V2 -> Uniswap V4 lineage.
- Native-quote pools for the first implementation so P&L remains in one auditable
  quote unit.

### Trend and structure

- >= +5% from the first post-graduation price.
- >= +10% over the long window (up to 24 hours).
- >= +5% over six hours.
- >= +3% over two hours.
- six-hour directional efficiency >= 25%.
- earlier-peak to base-low reset between 5% and 35%.
- breakout at least 1% above the prior two-hour base high.
- do not enter more than 12% above that base high.

These are intentionally broad structural conditions, not fitted coefficients.

### Demand

Trailing 30 minutes:

- >=5 independent buyers;
- >=2 newly observed independent buyers;
- buy:sell quote flow >=1.4x;
- buy quote flow >=1.25x the previous 30-minute window;
- largest buyer <=35% of buy flow;
- no creator selling.

### Executability and size

- immediate executable round-trip loss <=3.5%;
- 2x-size stressed round-trip loss <=5%;
- target position = 25 bps of strategy capital;
- position must be <=1/40 of trailing 30-minute turnover;
- if those caps shrink size below 5 bps of strategy capital, skip the trade;
- at most two simultaneous positions.

The small target is deliberate. Publicly visible Pons survivor markets can support
useful small trades while still having limited depth.

### Exit

- hard stop: -10% after costs;
- once high-water profit reaches +20%, exit on a 12% drawdown from high water;
- after +40%, tighten to a 10% drawdown;
- persistent 30-minute demand failure requires two consecutive confirmations;
- if six hours pass without a new high and after-cost return is below +5%, exit;
- maximum hold: 72 hours.

There is no automatic partial realization in v1. Full exits keep the initial
post-graduation experiment easier to reconcile and avoid borrowing lifecycle
assumptions from the existing Pons strategy.

## Selection

When more than one token qualifies, no fitted score is used. Candidates are ordered
lexicographically by:

1. long-window return;
2. six-hour return;
3. independent buyer breadth;
4. buy:sell flow;
5. lower executable round-trip cost.

At most the remaining open-position slots are selected.

## Authority

PAPER ONLY.

This branch builds and tests the strategy candidate. It does not activate it in the
current Meme Machine runtime and does not start a market run.
