# Ramses Active Wide Maker v1 — Chronological Holdout Result

**Frozen rule:** `RAMSES_ACTIVE_WIDE_MAKER_REBALANCE_V1.json`  
**Holdout period:** 1788949990–1789981503  
**Rule changed after holdout access:** no  
**Result:** NO ELIGIBLE REBALANCE OBSERVATIONS

## Conservative holdout reconstruction

The holdout was opened only after the v1 rebalance rule had been committed.

Conservative requirements for an owner/pool book to count:

- all attributed mints and burns occurred inside the holdout interval;
- the indexed Ramses position was closed;
- no earlier or later attributed action for that owner/pool was included;
- entry and rebalance context came from the frozen market index.

Results:

- 85 fully contained closed books
- 9 books matched the frozen entry regime:
  - USDG quote
  - <=2 swaps in the prior 30 minutes
  - initial width >=65 bins
  - initial position two-sided
- those 9 entry books:
  - 5 winners
  - lower-bound aggregate P&L: **+USD 9,428.43**
  - median book return: **+7.17%**

## Rebalance observations

Across those 9 entry books, 7 burn→remint events occurred within one hour.

Observed replacement widths were:

- 1 bin
- 20 bins
- 20 bins
- 1 bin
- 5 bins
- 5 bins
- 23 bins

None satisfied the frozen v1 hard minimum of 65 bins.

Therefore:

- **v1 eligible rebalances: 0**
- holdout wins/losses for v1 rebalance logic: **not measurable**
- v1 rebalance profitability is **not certified and not rejected**

## Research boundary

The holdout has now been observed and cannot be reused to tune or validate a modified threshold set.

Any revised rebalance rule must use:

- the pre-holdout evidence only for design; and
- new prospective paper observations / future chronology for validation.

