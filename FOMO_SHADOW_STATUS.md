# Offline Fomo intelligence integration — draft milestone

## Authority boundary

This work remains research-only and stacks on the inactive Fomo scaffold from draft PR #6. It does **not** change Pump market-native discovery, `continuation-v1`, Pump/PumpSwap execution, sizing, exits, signing/submission, or DLMM allocation.

Fomo remains an independent information layer:

`market-native Pump candidate -> unchanged directional qualification -> point-in-time Fomo annotation -> research outcome attribution`

and, separately:

`direct Meteora/DLMM economics + contemporaneous Fomo annotation -> research-only DLMM feature vector`

Fomo cannot nominate or suppress a candidate, turn a rejection into `qualified`, reserve capital, create an order, or enable DLMM. `meme_machine.engine` does not import the Fomo module.

## Point-in-time model

`meme_machine/fomo_shadow.py` now retains bounded normalized leaderboard snapshots with:

- Solana mint identity;
- trending rank and point-in-time rank change;
- trending strength and attention acceleration;
- most-held rank/presence and strength;
- graduated rank/presence;
- provider/source timestamp;
- local availability timestamp;
- provenance;
- freshness and missing-data status;
- a deterministic state id for the exact Fomo state available at a decision timestamp.

Annotation selects only snapshots whose provider time **and** local availability time are no later than the portfolio decision timestamp. Freshness is applied per leaderboard. A fresh board on which the mint is absent is represented as `present=false`; a missing or stale board is represented as unavailable instead of being inferred as absence.

Malformed/non-Solana identity, time regression, conflicting duplicate snapshots, conflicting duplicate rows, future snapshots, missing provenance, and capacity violations fail closed. Stale evidence is returned as unavailable and contributes no score.

The existing transparent research scores remain instrumentation only. They are not calibrated alpha models and have no trading threshold.

## Provider-neutral candidate annotation

`FomoCandidateAnnotator` reads only a candidate mint and decision timestamp. It returns a separate immutable Fomo annotation envelope and never mutates the candidate.

A Pump candidate remains fully evaluable when the Fomo book is empty or the provider is unavailable. Missing Fomo evidence returns `unavailable`; it does not block discovery, qualification, monitoring, or exits.

## Deterministic replay

`tests/fixtures/fomo_shadow_replay.json` is explicitly marked as a **synthetic provider-shaped replay fixture**, not a live Fomo result. It exercises the FomoScan-compatible leaderboard envelope without making a network request.

Replay tests cover:

- exact local-availability alignment;
- future observation exclusion;
- stale evidence rejection;
- malformed Solana identity;
- duplicate/conflicting rows and snapshots;
- time regression;
- missing provenance;
- missing Fomo evidence;
- immutable candidate behavior;
- no order/capital authority;
- DLMM remaining disabled.

No live Fomo request belongs in ordinary CI.

## Incremental-value research record

`FomoResearchLedger` stores bounded summary records for the later question:

> Did Fomo information add predictive value beyond market-native discovery and unchanged `continuation-v1`?

Each record freezes the exact Fomo state id and flattened point-in-time annotation used at the candidate decision, then supports later outcome fields for:

- qualification result;
- rejection reasons;
- Pump entry/no entry;
- graduation;
- realized paper result;
- MFE;
- MAE;
- time-to-graduation;
- time-to-exit.

The ledger contains no weight fitting, threshold optimization, or claim that leaderboard presence is alpha.

## DLMM research bridge

`DirectDlmmEconomics` represents the separate direct-Meteora evidence boundary and has fields for:

- canonical pool identity and token pair;
- current price / active bin;
- liquidity distribution;
- TVL;
- recent and historical volume;
- fee rate / dynamic fees;
- fees generated;
- volatility;
- position range;
- inventory exposure;
- rebalance and withdrawal cost;
- executable LP P&L;
- provider/source and point-in-time availability.

`build_dlmm_research_vector(...)` requires a direct DLMM record, same-mint identity, and contemporaneous availability. The returned Fomo/DLMM research vector references the direct-economics observation id but does not copy direct pool economics into Fomo authority.

Direct DLMM economics may be authoritative as measurements; neither the Fomo annotation nor this bridge has allocation authority. DLMM remains disabled.

## Resource bounds

Fomo storage is intentionally bounded:

- default distinct retained mint bound: **256**;
- default snapshot history: **8 per board**;
- three boards, therefore at most **24 retained normalized snapshots**;
- hard normalized observation-cell bound exposed by status: **3 × 8 × 256 = 6,144**;
- raw provider payload retention: **none**;
- in-memory research outcome bound: **512 records** by default;
- optional research persistence: one **bounded atomic summary snapshot**, rewritten rather than append-only;
- rejection-reason count and text fields are bounded;
- no social/feed archive exists.

The resource regression intentionally overfeeds observation and outcome state and verifies retained counts and persisted snapshot size plateau within those configured bounds.

## Provider boundary

The first executable adapter remains FomoScan-v2-compatible and read-only. It requires both an API key and a separately supplied `provider_spend_authorized=true` switch before a live request can run.

No key is committed or logged. No paid plan is purchased or authorized. Provider failure therefore degrades to `Fomo unavailable` because the production Pump engine has no Fomo dependency.

## Live-access limitation

This milestone contains **no genuine live Fomo result**. Genuine FomoScan polling still requires provider API access (a valid FomoScan API key/plan) plus explicit authorization to consume that provider capacity. Neither is supplied by this task.

That missing live access does not block the offline integration or deterministic replay proof.

## Next genuine experiment

Do not start the live Fomo experiment until the current market-native natural-sample baseline is complete.

The next experiment should freeze the exact same market-native candidates and decision timestamps, then compare:

**market-native baseline vs the exact same candidates with contemporaneous Fomo context**

Fomo must remain out of the clean baseline >=50-vector `continuation-v1` review sample. The first live sample is for incremental-value measurement only; it must not be used to lower thresholds, manufacture trades, fit Fomo weights, or create a separate Fomo strategy.

Direct Meteora/DLMM economics should continue on its independent research path, with Fomo joined only as contemporaneous context.
