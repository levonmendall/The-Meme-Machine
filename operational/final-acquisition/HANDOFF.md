# Final integrated Pump/Pons PAPER acquisition candidate

Source is finalized for the existing operational acceptance workflow. This release
extends `5bf3f245a6ac0146d3950e368ab6e3c22fef5a1c` on
`integration/alchemy-acquisition-final-20261008`; the pushed branch head is the
candidate commit, and `git rev-parse HEAD^{tree}` identifies its complete tree.
The ordinary deployment handoff outside Git pins both identities after commit.
Original epoch: `paper-1791089005190643467`; inception: $500 PAPER.

The ancestry includes PAYG `73243cb0c135197359c23cce46d3a91a48d8b40a`, Pons scout
and forward Survivor, Pump bandwidth/rolling-history repairs, fixed shared
capital, all nine economic changes, and the latest maintenance receipts. The
later Pump capability/Yellowstone experiment commits contain no newer production
source relative to the integrated bandwidth branch. Parallel working trees were
preserved; no older branch contents replaced the integrated production source.

## Implemented acquisition changes

* `SelectiveHistory.plan` rechecks shared canonical rolling coverage immediately
  before dispatch. Complete intervals finish without a provider call. Equivalent
  authenticated aliases and overlapping active requests share acquisition; more
  urgent consumers tighten the existing obligation's priority/deadline. Missing
  tails become existing durable acquisition jobs with their original deadline.
  Pending proofs wait for publication without pretending to be complete. Partial
  paid pages retain their original cursor and bounds across restart.
* Position-stream rebuilds reuse completely published Pump/PumpSwap recovery
  prefixes. The native replay floor advances only after every required prefix is
  canonical. Each remaining direct replay page rechecks coverage before purchase.
  Original historical requirements and durable canonical records stay intact.
* Finalized `getBlockTime` and chain-identity batch members now use the existing
  immutable cache and leases, including equivalent batch/single requests and
  session rotations. Null results and unfinalized times remain uncached. Live
  process leases cannot be stolen merely because their expiry elapsed; crashed
  owners remain recoverable. The transport recursion guard is local to the
  calling context, so concurrent consumers cannot bypass sharing.
* Pump and the shared Solana worker use the existing
  `<state_root>/pump/solana-evidence-broker.sqlite3`, including the worker's genesis
  validation. The supervisor prepares its existing Pump directory before worker
  startup. There is no database relocation or capital migration.
* Identical concurrent finalized history/body repair calls at the same priority
  buy one physical response. Followers receive independent copies and zero
  additional CU/delivery accounting. Fresh heads and different safety priorities
  do not join a weaker-priority read.
* Pons transaction-sender fallback bodies are reusable only with an authenticated
  transaction/block-hash pin. Historical fallback acquisition now carries those
  pins. Receipt-provided senders remain the preferred completed PAYG path. A
  mismatching transaction hash or block hash fails closed.
* Rolling coverage no longer performs an unused duplicate proof lookup and
  decompression. Existing batching, checkpoints, retry bounds, public scouting,
  ten-block log fallback and canonical caches remain in place.

## Runtime call-site accounting

| Method/work | Actual runtime entry points | Classification and retained requirement |
| --- | --- | --- |
| `getTransactionsForAddress` | `solana_selective_source.SelectiveSource.acquire` and `.live`, through `runtime.evidence_worker.RepairRPC` | Recovery-required or strategy-essential missing closed intervals. Complete rolling/canonical intervals, pending publication and equivalent active work no longer create another purchase. |
| Program WebSocket logs | `SelectiveSource` original Pump/PumpSwap `logsSubscribe` feeds | Essential ordered economic logs and continuity. Existing provider delivery, including failed transaction logs, is retained. |
| `getMultipleAccounts` | Pump `provider.PumpAdapter`, `postgrad` state/quote builders, finalized execution evidence | Position-safety-critical and due qualification. Fresh executable accounts keep their original commitment, minimum context and cadence. Historical reconstruction already uses the canonical plane. |
| `getSlot` | Selective source startup, WS acknowledgment/replay fence, exceptional acquisition without a supplied finalized frontier | Recovery/safety freshness. Independent after-ACK head samples remain mandatory; canonical finalized hints already supplied to acquisition are reused. No stale head substitute was introduced. |
| `getBlockTime` | Pump `provider`, `postgrad`, immutable RPC batch/single paths | Immutable only at an endpoint-authenticated finalized slot. Newly finalized account context advances the cache frontier; unfinalized and null results remain fresh purchases. |
| `getGenesisHash` | Pump snapshot, concentration/postgrad/scanning validators; shared worker `validate_network` | Chain authentication is required. Equivalent endpoint-bound validations reuse the existing authenticated result across consumers/restarts. Wrong-chain validation still fails. |
| Pons headers, receipts, sender bodies, contract evidence | `pons_selective_acquisition`, `pons_selective_v4`, `pons_historical`, existing `PacedRpc` reuse | Strategy authentication, due qualification, recovery or funded-position safety. Only exact canonical identities/hash pins share; current numeric membership, fresh state and executable quote requirements remain mandatory. |
| Capability tests, diagnostic replay and provider experiments | Existing `engineering` scripts and offline test fixtures | Engineering-only. No new runtime import, provider experiment, paid subscription or acquisition manager was added. |

Pons retains one shared public MarketScout. Paid log filters retain the exact
factory, curve and authenticated Pons pool identities. There is no paid
market-wide second scan, unrelated V4 population, Ramses/DLMM scan or EVM paid WS.
Meteora and Ramses remain fully PAUSED.

## Demonstrated redundant operations removed

`COMPARISON.json` executes the before/after production methods against identical
small offline fixtures, using the committed integration baseline above. These
are physical JSON-RPC elements, not HTTP envelope counts or an account invoice.

| Method | Before | Final | Removed |
| --- | ---: | ---: | ---: |
| `getTransactionsForAddress` | 5 | 3 | 2 |
| `getBlockTime` | 5 | 2 | 3 |
| `eth_getTransactionByHash` | 2 | 1 | 1 |
| Fresh `getMultipleAccounts` | 2 | 2 | 0 |
| **Total** | **14** | **8** | **6** |

The remaining overlapping history tail starts at slot 321 instead of 310, avoiding
11 already-covered slot positions in that request. Complete coverage for every
requesting alias, block times and authenticated senders match. This avoids
**280 CU = $0.000147** on this workload at the current published tariff.
Separately targeted regressions show lane/worker genesis 2→1, simultaneous exact
repair 2→1, and fully published position-rebuild history 1→0, while both required
head samples remain. These separate fixtures are not added to the comparison's
aggregate or extrapolated into historical or monthly billing savings.

Run the saved comparison without network or PAPER state access:

```sh
PYTHONPATH=. python operational/final-acquisition/compare.py
```

## Historical usage and retained provider delivery

The owner-supplied historical account measurements are:

| Method/delivery | Historical CU | Request-equivalents at today's method tariff |
| --- | ---: | ---: |
| `getTransactionsForAddress` | 645,600 | 6,456 |
| WebSocket logs, approximately | 582,352 | Byte-metered |
| `getMultipleAccounts` | 154,640 | 7,732 |
| `getSlot` | 121,680 | 6,084 |
| `getBlockTime` | 115,480 | 5,774 |
| `getGenesisHash` | 21,590 | 2,159 |

The six-method subtotal is 1,641,342 CU, or approximately $0.862 at today's
tariff. This is historical measured usage with an unknown production/engineering
mix and billing duration. The dollar conversion is not an invoice, and these
counts are not all redundant. The owner's separately rounded 1.73M CU / $0.91
report is consistent with the published tariff but does not establish a normal
monthly operating rate.

The existing corrected diagnostic tape charged 50,331,681 application bytes and
retained 50,330,766; 915 charged bytes were uncaptured. It contains 48,501,501 WS
bytes, including 16,441,310 failed-transaction WS bytes, plus 1,673,692 native
status bytes. These WS and compact native transports remain. Local failed-log
discarding provides zero provider-side delivery savings. Application bytes do
not establish TLS, NIC or the provider's exact billing meter.

The rejected 46.374-second full-transaction experiment's four below-floor native
payloads averaged 9,497.75 bytes and supplied no complete common finalized
interval. It established no savings; it is neither activated nor repeated.
Completed Model B removal of 1,516 duplicate queue reassertions / 3,032 SQLite
mutations is preserved as processing/storage improvement, not newly claimed
paid-request savings.

## Conditional monthly costs

Published PAYG is **$0.525 per million CU**; Solana WS is **0.0002 CU/byte** and
the retained native model uses **$75 per decimal TB**. Sources:
[Alchemy pricing](https://www.alchemy.com/pricing) and
[compute-unit costs](https://www.alchemy.com/docs/reference/compute-unit-costs).
No plan change, free allowance, credit, discount or additional paid capacity is
assumed. `COSTS.json` carries the original scenario inputs and limitations.

| Existing scenario assumptions, 30 days | Pump | Pons | Combined |
| --- | ---: | ---: | ---: |
| Quiet | $2.86 | $9.17–12.19 | **$12.03–15.06** |
| Normal | $29.24 | $61.13–97.42 | **$90.37–126.66** |
| High activity | $200.82 | $465.90–828.78 | **$666.72–1,029.60** |
| Normal with modeled Pump funded-position maintenance | $61.57 | $61.13–97.42 | **$122.70–158.99** |

These carry the selected retained Pump configuration and Pons scout-first
architecture A with the ten-block fallback from the already published models.
They do not deduct a guessed monthly duplicate rate. Normal Pump assumes
2 successful/2 failed Pump events per second, 20 successful/15 failed PumpSwap
events per second, and 0.1 fresh account reads per second. Normal Pons assumes
48 candidates/day, eight qualified/day, six hours of selective canonical watch,
25% funded occupancy and an explicitly unmeasured Current acquisition allowance.
Public market discovery remains continuous; watch hours represent conditional
canonical work rather than a discovery exclusion.

Under those assumptions, normal required Pons canonical/economic reconstruction,
warm funded safety and qualification work alone model 116.43–185.55M CU/month
($61.13–97.42). Pump's retained WS logs, compact native witnesses and fresh
accounts add $29.24. **The $50 combined target is not established.** Lower costs
must come from actual redundant work, not omitted opportunities or safety reads.

Actual autonomous opportunity/activity density and duplicate frequency have not
been observed. Current funded-position work, conditional entries/scaling/exits,
extra state/head checks, retries, reorg churn, genuinely unique history gaps,
public fallback duration and exact provider byte-metering can add costs.
The independent Pump open-position traffic model shows why the base normal
scenario is incomplete. Host cost and taxes are excluded. These unknowns are
limitations of the estimates, not a prerequisite for source readiness. No
30-day billing campaign or forty-block optimization gate is required.

## Preservation, regressions and operational next action

`PRESERVATION.json` verifies 41 frozen economic, capital, maintenance, decoder and
pause source files byte-for-byte against the latest integrated baseline. The
approved shared policy hash remains
`e87385900145e53956df18956ee2390f0d95787e6ffc44243251f9b147eb65f2`.
Original $500 inception, existing epoch, fixed shared-capital caps, 5% realized
family-equivalent sizing, all nine changes, Current/Survivor independence and
all stop/exit/scaling rules remain. No top-N filter, population cap, cheap-scout
economic rejection, capital-dependent qualification or shorter history window
was introduced. Required work remains in existing durable machinery with
funded-position priority and original deadlines.

86 distinct targeted offline cases passed. Logs comprise 63 affected existing
cases, 40 final dispatch/cache/wiring/funding cases and three final Pons pin cases;
overlapping cases are counted once. CPython 3.12.14 and the pinned engineering
environment were used. Coverage includes canonical retention, late/weak
opportunities, pending publication, pagination, deadlines, exact aliases,
cross-consumer leases, dead-owner recovery, fresh account/head requirements,
Pons canonical pins, Current/Survivor independence, native funding idempotence
and prevention of epoch reseeding. No valid assertion was weakened. Already
successful large suites were not repeated. The ordinary configured
`python -m meme_machine.operational check` passed using the existing protected
provider configuration; that command performs no network I/O or economic
initialization. `git diff --check` passed.

Next is the existing [operational acceptance workflow](../ACCEPTANCE.md), using
this one pushed commit/tree and the preserved epoch in its existing
**CAPACITY → RECOVERY → AUTONOMY** order under separately authorized operational
acceptance. The present owner directive supersedes instructions to rerun full
suites solely for this acquisition optimization. No new certification rules,
framework, spending ceiling, provider experiment or infrastructure was added.

There is no remaining identified source defect. The existing
`combined_position_and_candidate_provider_latency_not_certified` fail-closed
guard is preserved; it requires the already-defined, separately authorized
operational acceptance. No acceptance phase was launched or claimed passed.
The PAPER service was observed inactive, at deployed commit
`b577cc1c67f4d64f887b430f5e933f376b607dc2`. It was not deployed/restarted, its
ledger was not opened/migrated, and no live-money activity occurred.
