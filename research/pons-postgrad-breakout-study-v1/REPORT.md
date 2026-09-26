# Pons Independent Post-Graduation Breakout Study — Final

Date: 2026-09-26

Status: **COMPLETE — UNPROVEN / NOT PROMOTED**

## Objective

Evaluate whether Pons should add an independent post-graduation breakout/continuation
entry that can enter after graduation without requiring a pre-graduation
`pons-selective-continuation-v1` qualifier or position.

## Authority

Research only. Paper only. No signing, transaction submission, live money, production
allocation, or active Pons policy changes were authorized or performed.

The active Pons strategy remains:

- `pons-selective-continuation-v1/profitability-v1-profit-protection-v2`
- policy hash `19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84`

## Research candidate

The repository already contained `pons-post-graduation-breakout-v1`, which is
independent of pre-graduation qualification. It discovers Pons V2 graduations directly
from the authenticated factory, proves V2 -> Uniswap V4 lineage, waits for a settling
pullback, and requires a second-wave breakout with independent buyer growth and
accelerating buy flow.

Its frozen research thresholds were not loosened or searched during this study.

The study added research-only executable shadow measurement:

- authenticated V4Quoter entry quote;
- fixed 30/60/120/300-second shadow exit marks;
- after-cost return including conservative gas proxies;
- no capital reservation or paper position.

## Evidence reviewed

### Retained runs 355-368

An offline, network-forbidden audit of
`certification/evidence/robinhood-runs-355-368.json.gz` reproduced the pinned
SHA-256 `1be70cb9f53bfc9bce039f6913813a6d2a0a21dde39b6b10bf95b9123f47597f`.

Result:

- independent graduation-universe records: 0;
- post-graduation vectors: 0;
- V4 monitor rows: 0;
- Pons lifecycles present: 7;
- lifecycles carried through graduation: 0.

Conclusion: these runs cannot support an unbiased retrospective profitability test
of an independent post-graduation entry. Conditioning on the existing pre-graduation
lane would create selection bias.

### Prospective independent observer

The deterministic Robinhood suite passed 234 tests.

A bounded prospective research sample completed successfully in workflow
`36250916389`. It observed for the full bounded graduation-discovery window and
ended with:

`no_current_pons_graduation`

Therefore:

- authenticated independent graduations observed: 0;
- breakout candidates: 0;
- executable shadow entries: 0;
- forward after-cost return samples: 0.

A later shadow-measurement run was started after deterministic validation, but no
production decision or strategy promotion depends on it.

### Recent active Pons market evidence

Run 370 (`36209572689`) observed 67 unique Pons candidates during approximately
668 seconds of Pons uptime. It produced 24 current-state completions, 28 screened
candidates, 0 qualified entries, and 0 forward observations.

Run 371 (`36225681652`) observed 87 unique Pons candidates during approximately
669 seconds of Pons uptime. It produced 30 current-state completions, 42 screened
candidates, 0 qualified entries, and 0 forward observations.

These runs are not an independent post-graduation dataset, but they confirm that the
current Pons opportunity funnel is selective and that no contemporaneous economic
sample exists from which to justify expanding allocation authority.

## Result

The study does **not** establish that post-graduation breakout entries are
unprofitable.

It establishes that the proposed expansion is **not currently evidence-supported**:

1. preserved historical evidence lacks an unbiased independent post-graduation
   universe;
2. the bounded prospective observer found no graduation in its completed window;
3. there are no executable breakout forward-return observations;
4. therefore winner capture, loser admission, after-cost expectancy, drawdown,
   profit factor, and capacity are all unmeasured.

Promoting the strategy would therefore be speculation rather than an evidence-based
extension of Pons.

## Decision

**Do not promote `pons-post-graduation-breakout-v1` to active Pons allocation.**

Keep:

- the production Pons strategy unchanged;
- breakout allocation authority false;
- the research collector and deterministic tests available for future evidence
  collection;
- no further automatic research collection from this branch.

The hypothesis remains valid for future reconsideration if an unbiased set of
natural Pons graduations with executable forward marks becomes available.

## Final classification

- strategy hypothesis: plausible;
- implementation machinery: deterministic/research-capable;
- current opportunity frequency: sparse in observed sample;
- profitability: unmeasured;
- promotion decision: **NOT PROMOTED**;
- production strategy changed: **false**.
