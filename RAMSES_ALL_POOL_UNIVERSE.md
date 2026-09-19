# Ramses all-pool universe screen

Fee Pulse is no longer constrained by the earlier WNATIVE-only Ramses proof.

`robinhood_research.ramses_universe` now provides a bounded all-pool screening plane:

- enumerate every pool registered in the authenticated Ramses factory;
- observe finalized Swap activity over a fixed 300-block pre-entry window;
- classify pools with no recent swaps as inactive/no-trade without expensive state expansion;
- build exact seven-bin prestate for at most 32 recently active pools;
- authenticate each expanded pool against the pinned Ramses implementation and factory;
- calculate turnover/active-liquidity, current fee, volume acceleration, gross/net bin movement, chop and flow imbalance;
- calculate turnover and fee percentiles across the contemporaneously active cohort;
- run the frozen `ramses-fee-pulse-v1` classifier;
- freeze an eight-pool research watch cohort using pre-entry information only.

The ranking is screening only. Finalized discovery logs are not treated as receipt-authenticated strategy outcome evidence. Any pool selected for a prospective paper lifecycle still requires exact receipt/header identity, frozen range construction before outcome, terminal replay equality and executable unwind/cost evidence.

For arbitrary token pairs the scanner uses token Y as the canonical accounting quote for dimensionless turnover and return calculations. Any gas-cost input must already be converted into that pool's quote-token raw units. External anchor/directional signals must express direction as Ramses bin direction (`up` or `down`) and remain subject to the frozen signal freshness/confidence/edge gates.

Natural allocation remains disabled.


## Independence boundary

The all-pool scanner belongs exclusively to `robinhood-ramses-dlmm-independent`. Its universe is reconstructed from the authenticated Ramses factory itself; it does not accept another strategy's candidate list or ranking.

The scanner's watch cohort, percentiles and no-trade decisions are derived solely from Ramses state/log evidence plus explicitly permitted Ramses inputs. It has no shared allocator and no allocation authority. External anchor and directional context must satisfy the strategy-domain provenance contract before it can influence a Ramses decision.
