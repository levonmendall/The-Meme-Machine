# v10 post-run engineering repairs

Historical authority: runtime `07ec67a2b7967fd3e97c056307967ce1738f6d20`, run `36043064083`, certificate `36041821324`, ref `cert/single-market-v9-monitored-20260924`. None is advanced or rewritten.

## Independent continuation repair

Branch `repair/v9-position-continuation-dispatch-20260924`, commit `fe722bb44805aaec486504c1e3586c6699b77ce9`, full exact-SHA non-market certificate `36062329139` passed. Registration-only run `36062328815` passed with continuation jobs skipped. This exact four-file hotfix is composed here. See `V9_CONTINUATION_DISPATCH_HOTFIX.md` for registration and all existing authority guards. A future separately authorized historical continuation must still bind to the original campaign runtime, not a repair SHA. No position continuation was dispatched.

## Evidence and scope

The original hourly artifact `10832096927` is digest-pinned to `59c5eccd9a57ff0bd746c11a174afbe434b38e56650d14e1b63994b7260b6002`. Read-only projection run `36062888664` extracted selected native reports/ledgers, pipeline journals and RPC/decision evidence. All 90 projected file hashes were verified locally. The large shared Solana cache is excluded explicitly, not treated as inspected. No provider collection was used for diagnosis.

Five complete captured decision records are retained in `certification/tests/fixtures/v9-postrun-decisions.json`. Offline replay verifies each original record digest, runtime identity, allowlisted function, result and post-call inputs with networking denied. This is selected-record verification, not a claim to retain the entire historical hash chain.

## Demonstrated defects and deterministic proofs

| Workstream | Evidence and root cause | Repair and proof |
|---|---|---|
| Pump pagination | 1,043 signature request members; 49 repeated shapes, including 18 before-bounded repeats, all repeated after errors. Successful distinct pages overlap: 161 pages include 1,520 previously seen rows. Timestamp/slot minima lose the exact last signature within a slot. | Persist the successful page's last signature as the incremental backfill cursor. Same-slot fixture completes in two physical page requests and makes no further request once coverage is complete. Mutable head pages and failures are not cached as successful evidence. |
| Pump reservation | Mint `GjLvaHKcMDxoWMr3dwF2iREkPiJEdZJ4AaNSA19Vpump`: evidence available at 1790277577; reservation actually recorded at approximately 1790277584.158; old reservation used 7577. Seven seconds of its 20-second fill window had elapsed before reservation. | Reserve at actual wall time, bounded below by evidence availability. Preserve entry delay, timeout, complete fill evidence and demand revalidation. Fixture verifies the clock boundary. This repairs backdating; retained evidence cannot prove a hypothetical fill would succeed. |
| Pons receipt acquisition | 232 successful repeated same-endpoint receipt calls. Monitoring created a context without receipt block-hash pins, bypassing existing safe immutable reuse. | Authenticate requested block hashes and bind transaction receipts to them; pass the context into receipt acquisition. Two overlapping monitoring windows produce identical authenticated results with one physical receipt request instead of two. Wrong hash/domain remains fail-closed. |
| Meteora classification | Candidate reconciliation of 291 raw reconstruction labels resolves 288 capital exclusions, two genuine reconstruction failures and one open position with monitoring evidence gaps. | Explicit capital-occupied/open-continuing classifications; capital exclusions emit evidence-not-required for new admission. An independently required obligation remains required when missing. Warmup observations cannot invent an open position. Capital constraints remain intact. |

Pump's other qualified mint, `32cPAv6kzduGbDjqU8V6AJu7fW5EaojHBT15K47TvGAF`, had complete fill evidence but net demand 5,295 versus decision demand 7,284. Its captured `fill_net_demand` rejection replays unchanged.

All three Pons qualified lifecycles cancelled at entry signal revalidation: adverse flow/velocity, zero net flow/breadth deterioration, and graduation ETA 15 below the frozen minimum. All three captured rejection results replay unchanged. Existing early rejection already prevents expensive downstream work; authenticated headers, pinned calls and session identities already have reuse. No additional metadata cache or economic adjustment was justified.

Meteora's two remaining candidate failures are `fresh_state_unavailable_after_authenticated_trigger` and `solana_dlmm_transaction_pressure_overflow`. The first retains its authenticated pending trigger and retries fresh state until the frozen deadline; the second enforces the existing transaction scope cap. Neither can be turned into complete evidence. The open position also had two transaction-hydration gaps; its durable handoff remains authoritative, not a forced settlement. Existing position-monitor priority zero, foreground consumer scheduling and background deferral are preserved. Retained evidence does not demonstrate another safe acquisition change beyond the repairs above.

## Ramses accounting: preserve the loss

One native reserve/open/monitor/segment-close/settle sequence, one settled lifecycle, no repeated cost application. All arithmetic is integer raw units of quote token `0x5fc5360d0400a0fd4f2af552add042d716f1d168` (USDG); these figures are not whole-dollar amounts. No decimal scaling or cross-token summation occurs in the PnL function. Token-side input quantities remain in their own raw units and are converted by executable pool quotes, not by assuming equal decimals.

- Inventory effect: -32; executable unwind slippage: -264; gross: -296.
- LP fees captured: 0. No observed lifecycle swap events; no missing positive fee credit is inferred.
- Costs: entry overhead 120862 + add liquidity 241720 + removal 120860 + unwind 29204 = 512646.
- Net: -296 - 512646 = **-512942**.

Cost evidence uses 43,690,000 raw native gas price, 680,779,677,120,000 raw native cycle cost and an authenticated two-hop executable conversion to 512,646 raw quote units. Add-liquidity uses the existing conservative 2x proxy because its receipt sample count is zero (removal one, unwind fifteen). Route fees are included in executable conversion and unwind output, not debited again as a separate expense. LP protocol deductions and composition fees remain native reconstruction inputs. There is no extra host-fee credit. The captured `decompose_pnl` record replays byte-equivalent encoded outputs. No Ramses source or economic change.

## Bounded causal observability

`certification/worker.py` adds thread-local requesting-candidate/evidence context to existing raw RPC records, alongside existing method/provider, queue wait/admission, priority, transport result and error-domain fields. Shared hydration consumers keep their native candidate/owner/signature linkage. Authenticated immutable reuse and broker hydration outcomes add at most 2,048 detailed events per worker with fixed-category aggregate totals thereafter.

`certification/causal.py` streams SQLite candidate history read-only, uses disk sorting and a 2 MiB SQLite cache, and writes at most 10,000 detail rows per pipeline while counting all candidates. One latest candidate status is separate from the required/completed evidence axis. Synthetic trigger sub-identities do not inflate candidates; actual native lifecycle outcomes override generic historical labels. Existing raw history is unchanged. The optional newer Ramses native terminal report read is capped at 2 MiB and omissions are explicit.

`docs/v10-postrun/*-causal-summary.json` records the retained-run reconciliation: Pump 2,593 candidates including two cancellations; Pons 19,902 including three cancellations; Meteora 1,579 including 288 capital exclusions, two genuine reconstruction failures and one open/continuing; Ramses seven including one settlement. These are latest disjoint statuses, not a replacement for historical stage counts. Requesting-thread context does not imply sole ownership of a shared batch; background work without a candidate remains explicitly unattributed. Historical telemetry cannot retrospectively supply context absent from the original records.

## Frozen invariants and validation

Only the three changed lane source-diff identities in `profitability_protocol.json` track the new overlays. All strategy versions, policy hashes, economics, targets, freshness/finality, provider ceilings, sizing, evidence requirements, portfolio rules and authority remain frozen. This does not enroll the repair SHA into the historical prospective cohort.

Focused lane tests: Pump 19, Pons 22, Meteora 3 passed. Root integration suite: 223 tests completed; the sole initial failure was the expected source identity mismatch, repaired and its gate rechecked. Final exact-SHA certification runs the complete supervisor/component suites, native crash/restart checks, integrated acceptance, resource gates, source/policy integrity and established bounded connectivity checks. The certificate result and exact final SHA belong to the associated Actions run, not to an uncommitted claim in this document.

No market campaign, real position continuation, shared portfolio initialization, Render deployment or live-money activity is authorized or performed by these changes. No live failure-rate or profitability improvement is claimed from offline proofs.
