# Pons Selective Continuation v1

## Independence contract

This strategy is independent of every other Meme Machine strategy.

It may share only neutral Robinhood/Pons infrastructure:

- read-only RPC transport and pacing;
- sequencer block clock;
- verified Pons ABI/deployment identity;
- exact Pons curve arithmetic;
- finality/reorg evidence;
- Pons V2 -> Uniswap V4 lineage proof;
- generic restart-safe paper accounting;
- executable curve/V4 quote primitives.

It MUST NOT read, import, inherit or mutate:

- Solana `continuation-v1` or `continuation-v1-robinhood` signals or cohorts;
- Pump.fun/PumpSwap wallet sets, qualification results or outcomes;
- Ramses/DLMM ranges, wallet research, capital or outcomes;
- another strategy's allocator, reservations, positions, database or result artifact;
- another strategy's learned thresholds, scores, rankings or rejection history.

The automated import-boundary regression in
`robinhood_tests/test_pons_selective_independence.py` enforces the principal
code-level boundary.

## Main lane

Policy: `pons-selective-continuation-v1`

Entry is allowed only for native-quote Pons V2 curves and requires the frozen
policy in `robinhood_research/pons_selective_continuation.py`.

Core evidence:

- 55%-92% exact curve progress;
- short token age;
- >=8 percentage points progress over the trailing trajectory window;
- positive curve acceleration;
- <=120-second estimated graduation;
- >=5 independent buyer groups;
- >=3 new independent groups in the recent 15 seconds;
- >=2:1 recent buy:sell quote flow;
- increasing independent net demand;
- bounded largest/top-three buyer-flow concentration;
- no observed recent creator distribution;
- creator tax <=2%;
- exact on-chain `currentSnipeTaxBps(recipient) == 0`;
- <=5% modeled round-trip friction;
- nonzero position after the 0.25%-capital / 2%-real-liquidity /
  10%-independent-net-demand / 3%-impact sizing caps.

The wallet-convergence overlay is Pons-only and point-in-time. It reads only
`pons-selective-continuation-v1` wallet records. It cannot bypass the core
qualification.

## Lifecycle

Each qualifier receives a dedicated paper database under
`pons-selective-continuation-v1-cohort/`.

There is no shared allocator. The strategy has a private paper-capital namespace.

Lifecycle:

authenticated curve qualification
-> delayed executable entry
-> restart reconciliation
-> pre-graduation thesis monitoring
-> authentic Pons V2 -> V4 transition
-> 5-30 second second-wave continuation gate
-> failure exit OR continued runner
-> +25% first-profit partial exit (50%)
-> 11% high-water trailing runner / demand failure / time exit
-> settlement
-> restart reconciliation.

The generic paper ledger gained backward-compatible partial-exit accounting so the
runner can be executed rather than approximated. Existing full-exit callers retain
their old semantics.

## Separate Pons strategies

### `pons-post-graduation-breakout-v1`

Research-only and no allocation authority.

It discovers Pons graduations directly from the Pons factory. It does **not** consume
continuation-v1 qualifiers or positions. It requires a real settling pullback,
then tests new independent V4 buyer growth, accelerating flow and a prospective
breakout over the frozen consolidation high.

### `pons-quote-relative-value-v1`

Research-only and no allocation authority.

It handles non-native Pons quote assets separately and measures token appreciation
directly in the authenticated quote asset from curve reserves. This prevents quote
asset appreciation from being mislabeled as token alpha.

Ordinary allocation is disabled until an arbitrary ERC-20/RWA quote-capital and
settlement adapter is independently certified.

## Natural experiment

The selective-continuation cohort target is 100 genuine natural qualifiers. Rejected
candidates remain in the study. Selection is outcome-blind; there is no reranking or
replacement. Every qualifying paper lifecycle uses the exact frozen policy hash.

The workflows are independently triggered:

- `[pons-selective-cohort]`
- `[pons-breakout-sample]`
- `[pons-relative-sample]`

No signing, transaction submission or live-money capability is introduced.
