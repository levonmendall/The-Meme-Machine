# Meteora evidence repair — accepted run 35949285193

Runtime `1c6da29d08bfbe42e39ea1c8068933aae6b15cdb`; original hourly artifact SHA-256 `698dcc65131bdc972f0be3176f8b29d276f8f054c77c86aa780a2bcd237dda6a`. Diagnosis uses the byte-verified native projection in `evidence/native`; `projection-receipt.json` preserves the original archive and derivative identities. This is an offline engineering diagnosis. No historical evidence is rewritten and no market run was launched by this lane task.

## Exact native accounting

The 56 native admitted attempts partition as follows. The legacy `evidence_requested` event happened before fresh-swap admission, so it was not a full-reconstruction denominator.

| Outcome | Pools | Causal interpretation |
| --- | ---: | --- |
| Pre-entry observation reserve exhausted | 23 | Legitimately pending admission context at block close; full reconstruction never became required |
| Trigger timeout without an authenticated trigger, no recorded gap exposure | 11 | Valid early no-activity rejection under the unchanged bounded trigger procedure |
| Trigger timeout without an authenticated trigger, with gap exposure | 3 | Stream gap / incomplete observability; absence of unseen swaps is not proved |
| Trigger authenticated but discarded while fresh state lagged | 1 | Preventable implementation defect, falsely labeled no activity |
| Completely verified zero-swap warmup | 9 | Authoritative early rejection; full economic vector became unnecessary |
| Complete full economic vector; frozen qualification rejected | 5 | Successful evidence completion and valid strategy rejection |
| Failed required warmup reconstruction | 4 | Three unchanged transaction-bound failures and one unsupported legacy liquidity operation |
| **Total** | **56** | |

There were 108 compatibility screens: 51 expected unsupported program/extension/authority/fee-mode rejections, one authenticated zero-liquidity rejection, and these 56 admitted attempts. The extra zero-liquidity pool was `HcS8vfGcjP7bvZ73eyPGWH9zPoY1hERuLhnjf6DYupCR`: raw transport `8e79694b-2c7c-4433-9795-53fbe5268eb1:274`, finalized slot 449908315, all eight requested accounts present, 210 decoded bins, active bin present, aggregate X inventory = Y inventory = LP supply = 0. Its `dlmm_missing_active_or_liquidity` error is a valid structural rejection, not missing reconstruction evidence.

The 51 incomplete attempts occupy six requested causal buckets: required evidence genuinely failed 4; valid early strategy rejection 11; full reconstruction became unnecessary 9; stream gap 3; legitimately pending at block close 23; implementation defect 1. The separate five complete vectors are valid strategy rejections. Other requested buckets have zero demonstrated pool-level cases in this cohort. Supersession and shutdown misclassification below concern overlapping trigger identities, not additional pool losses.

## Required-evidence denominator

| Metric | Count |
| --- | ---: |
| Authenticated candidates requiring fresh state and verified warmup | 19 |
| Legacy broad evidence requests | 56 |
| Actual warmup reconstruction requests | 18 |
| Full economic vectors completed in time | 5 |
| Full vector became unnecessary after authoritative verified-zero warmup | 9 |
| Required evidence failed | 5 |
| Required evidence still pending at observation close | 0 |

Required-evidence accounting is **19 = 5 complete + 9 became unnecessary + 5 failed**. The failures are four warmup failures and the one discarded authenticated trigger. Complete authoritative warmup decisions were **14/19**. After the nine valid early rejections, the residual full-vector completion fraction is **5/10**. Neither 5/56 nor 5/5 describes required full evidence faithfully. These counts cover observed authenticated candidates; unknown events lost during stream gaps are not fabricated into a denominator.

`meteora-causal-classification.json` records all 56 pool identities, original native outcomes, disjoint causal buckets, required evidence flags, and the aggregate calculations.

## Demonstrated trigger loss and repair

Attempt 14, pool `BZJTiubWLruAhoBxCTgU3uVdvXFztsr4cKG7SZcxoQdC`, started from compatibility slot 449910487. Raw transport `10065be4-0fce-4220-836f-96621b15020d:401` returned finalized swap signature `5izen2qh7WcCP75h9yt3YcZF6Lef4qy5e61nPjxvafEJbP1C5juR5TBKrBwHYoD9NzPCRUGhryRvq35WfMifB7ew` at slot 449910506. Transport `:402` authenticated its body at epoch 1790221548.2019253. The subsequent fresh account bundle `:404` returned slot 449910499 at epoch 1790221549.1920655, below the already authenticated trigger.

The original loop advanced the signature cursor, discarded that trigger on the lagging state response, and waited for another swap instead of retrying the required fresh prestate. No further fresh state request occurred. A later gap probe `:406` saw the same signature, which the advanced cursor excluded. The attempt terminated as `fresh_swap_trigger_timeout` despite the proven swap.

The repair retains the authenticated trigger while retrying the fresh finalized account state. It does not rehydrate or require another swap. The original 120-second trigger limit and campaign deadline still apply, including after transport returns. If state remains unavailable, reporting distinguishes that failure from no authentic activity. `tests/fixtures/meteora_trigger_account_lag.json` preserves the authenticated transaction and exact lagging slots; its regression deliberately invents no missing historical catch-up snapshot or warmup.

## Stream continuity

There were five cumulative wake-stream gap events. The terminal state was connected and covered, but that is not proof of complete backfill. All five remain historical gap events.

The gap times were approximately epochs 1790221212, 1790221601, 1790221688, 1790221845, and 1790223370, derived from native `loss_until` with the unchanged two-second wake coverage interval. Four affected trigger waits (attempts 10, 14, 15, 16). Attempt 14 has the independently proved trigger-discard defect above. The other three lack proof that every relevant event during their outage was recovered. The fifth occurred during attempt 31's warmup; its complete authenticated HTTP signature census and endpoint reconstruction independently verified zero swaps. A missing wake notification did not invalidate that verified warmup.

The original trigger loop acknowledged a gap before its bounded authentication read succeeded, and could perform that read while the connection was still down. It also discarded a recovery obligation when hydration remained pending without a 429. That leaves later lost wakeups in the same outage without a post-reconnect recovery read.

The repair retains the recovery obligation until the stream is covered and the bounded authentication read finishes. Pending hydration and 429 outcomes retain the obligation without advancing the cursor. No extra provider, rate ceiling, pagination ceiling, transaction capacity, or economic gate is introduced. This remains bounded candidate-trigger authentication, **not complete physical stream backfill**; the telemetry explicitly says so. An unresolved gap at trigger timeout is reported as a stream gap rather than proven no activity. Tests cover both outage recovery and the unchanged fail-closed boundaries.

## Four genuine warmup failures remain fail-closed

| Pool / attempt | Captured interval | Required successful transactions | Disposition |
| --- | --- | ---: | --- |
| `6raVjeVS2RUvcnv2SJnrWt6f5u19rTZ8ZLw99BoUYMom` / 1 | 449905574 → 449905586 | 49 | Frozen maximum is 16; slot 449905579 alone has 21. Splitting a slot or omitting transactions would weaken evidence. |
| `Cse9CPxSbeZmHRZXFtSGEgauLa3K7epY9K8BGGVQrziY` / 6 | 449907544 → 449907562 | 37 | Captured interval exceeds 16. No authenticated intermediate endpoint exists in this retained interval; historical subdivision is not fabricated. |
| `ovtwEHG1eLuqagpSz8QXxfwrsUNKx58hejKjhWjxoeD` / 7 | 449907812 → 449907835 | 19 | Captured interval exceeds 16. Same unchanged bounded-replay limitation. |
| `FtwzPjTqoFuy8aF8bMBi7QF7UxpdYN5n9YUH6R7DcHjB` / 5 | 449907316 → 449907330 | 5 | Unsupported legacy `add_liquidity_one_side`, discriminator `5e9b6797465fdca5`; required reconstruction fails closed. |

The first three counts include authenticated signature rows already acquired and cached before the final endpoint. They are not just the final incremental HTTP response. Their relevant signature sources were transports `:44/:48`, `:190/:193`, and `:247`, respectively, in each attempt's retained RPC session.

The legacy liquidity instruction occurs at slot 449907325, transaction `5PeXkA5PLLR39ZecnB2khGcLiqPjUoDnK2kERgcZLSY8qpWFJEwdUnK5sJuULFPqBeJ2VzKFxFsQtnKZyb6jwM3J`, transport `6e9c3fe6-0eaa-4bda-a204-1119e734db4f:160`. It has 250 instruction bytes and 37 weighted bins. The retained implementation supports other explicitly verified liquidity forms; this is not a typo in an existing supported branch. A new exact weight-allocation/rounding model and authenticated end-to-end replay proof would be required before supporting it. No protocol or accounting approximation was added in this bounded repair.

## Classification and final-checkpoint repair

The stable JSON snapshot's 32 `reconstruction_incomplete` identities were 23 reserve-cutoff pools, four actual failed warmups, one valid zero-liquidity compatibility rejection, and four superseded trigger identities. The final SQLite pipeline had 37 because shutdown added five trigger failures for the same five pools that already had complete evidence and a qualification rejection.

The repaired path records qualification rejection through the common terminal helper, clearing its active trigger. Superseded trigger identities use `superseded_candidate_state`. The zero-liquidity compatibility error is structural. Reserve cutoffs use `pending_at_observation_close` plus an explicit pending stage. Actual terminal cleanup is reflected in the persisted final checkpoint, so the JSON and append-only SQLite agree. Explicit caller-supplied classifications no longer collide with an additional positional classification argument.

New prospective markers record `evidence_required` at authenticated trigger, `evidence_requested` at warmup start, `evidence_not_required` only after a fully verified zero warmup, and `trigger_evidence_requested` for the earlier trigger acquisition. Each required observation and its request/completion/early-rejection/terminal stages carry an explicit `observation_id=pool:trigger_slot`; supersession terminates the previous pool obligation under that exact identity instead of leaving a false pending obligation. They preserve all old source evidence without labeling a partial reconstruction complete. The parent owns the shared dynamic stage/class snapshot implementation.

## Pending work and block authority

Discovery acquired all 360 planned source segments over 60 censuses. Its durable first-sighting spool contained 2,076 candidates; 158 were consumed, 50 failed public context screening, and 1,918 remained unconsumed. The 23 reserve-cutoff attempts were already consumed and are separate from those 1,918 rows.

Current authority is process-scoped first-sighting deduplication with a fresh invocation per campaign. Cross-block continuation applies to funded Meteora/Ramses positions; it does not authorize carrying old unqualified discovery candidates into a new campaign. The spool already preserves the pending rows durably. This repair reports their unfinished status without transferring stale public context, changing candidate ordering, or inventing a new cross-block admission policy. Pending discovery context is not counted as failed required full evidence, and no external target-universe completeness is asserted.

## Changed lane files and verification

- `tests/solana_dlmm_independent_v1.py`: authenticated-trigger retention, gap-recovery bookkeeping, precise requirement/terminal events, consistent final checkpoint.
- `tests/test_meteora_evidence_recovery.py`: focused offline causal regressions, including captured authentic trigger plus lagging account state, native run-to-checkpoint attribution, pending-vs-required distinction, verified-zero early rejection, rate-limit/pending recovery, unchanged deadline and no-fabrication cases.
- `tests/fixtures/meteora_trigger_account_lag.json`: bounded public captured regression evidence with original archive/run provenance.
- `meme_machine/pipeline.py`: shared parent-owned dynamic snapshot support, not a lane strategy change.

Focused tests: **44 passed** (`tests.test_meteora_evidence_recovery` and `tests.test_solana_dlmm_independent_v1`; 14 new regression cases). Final full suite including explicit observation linkage: **444 tests passed in 138.540 seconds**, recorded in `meteora-unit-final.log`. Both mandatory resource checks passed: the generic check processed 240,000 synthetic events over 2,000 frames; the DLMM check processed 6,001 synthetic events with one atomic write per event, bounded cache/cursor, and zero provider calls. Their exact outputs are `meteora-resource.json` and `meteora-dlmm-resource.json`.

No frozen policy file, qualification arithmetic, range/fee math, size, holding/exit rule, fresh-state TTL, provider ceiling, signature/transaction bound, or live-money authority changed. The reconstructed historical limits above remain open and visible. No historical profitability or future trade is inferred from these repairs.
