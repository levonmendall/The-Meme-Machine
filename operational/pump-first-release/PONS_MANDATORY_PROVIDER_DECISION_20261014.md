# Pons provider decision — inactive routing candidate, no deployment

The pacing correction fixes the demonstrated dispatch defect. It does not make
public RPC suitable for mandatory continuous work or identify its original quota.
Current combined diagnostic proposal keeps existing routing; no migration,
purchase, new account or live capability check was executed.

Robinhood identifies public RPC as rate limited and unsuitable for production
or latency-sensitive work, and recommends a provider:
[connecting](https://docs.robinhood.com/chain/connecting/),
[terms](https://docs.robinhood.com/chain/terms-of-service/).
Evaluate the already connected Alchemy mainnet application first.

## What is actually verified

Previously retained authorized account metadata lists application `v5h0vqr0wpp9zscj`,
name Robinhood, with `ROBINHOOD_MAINNET` and `ROBINHOOD_TESTNET`. No credential was
changed. The existing deployed credential/fingerprint binding and exact factory
40-block comparison remain retained; no new market request was made.

The installed continuous profile has Solana 2 RPS and Robinhood 10 RPS, queue
depth 64/wait 5 seconds, original failure backoff and physical resource guards.
These are local operating settings, not proof of an Alchemy account-wide quota.
The connected tools expose neither actual plan/CUPS nor contract terms. Official
[account throughput guidance](https://support.alchemy.com/articles/3788245542-is-alchemy-s-throughput-cu-s-limit-shared-across-all-apps-or-set-per-chain)
states that standard throughput is shared across apps/chains. Do not assume a
separate allowance for the Solana and Robinhood keys.

The account summary reports 10,518,456.4096 CU and a USD-denominated value of
$5.52 month-to-date through `2026-10-14T14:00:00Z`, with partial today included.
This is provider-reported usage/value, not an independently verified invoice or
contract. It cannot establish the cost of this proposed routing change.

## Inactive source-routing candidate

The default `MM_PONS_OBSERVATION_ROUTE=public_existing` preserves prior routing,
including deliberate bypass of Alchemy URLs in `MM_ROBINHOOD_DISCOVERY_RPC_URL`.
An inactive, separately reviewable `canonical_primary` choice now resolves only
the existing `MM_ROBINHOOD_READ_RPC_URL` identity. It constructs the existing
`PacedRpc` with a dedicated mandatory-observation role, the same mandatory
endpoint admission ledger, chain guard and immutable evidence store used by
canonical qualification/protection. It has no public fallback or second
acquisition path. Unknown choices fail closed. No installed environment,
provider route, account, credential or operational database was changed.

The existing discovery consumers already obtain their client through
`configured_discovery_rpc`; their filters, sequencer clock, cursor, gap handling
and candidate authentication remain unchanged. This switch changes the transport
and compatible evidence reuse, not qualification authority. A discovery event
does not authorize entry. Canonical boundary/receipt membership, cursor continuity
and complete intervals still require their existing authentication checks.

Reuse local verified headers/receipts and exact complete log intervals before
buying missing evidence. Existing candidate-scoped/V4 history is not proof of
complete broad discovery; missing universe intervals still require acquisition.
Only the exact factory address/two-topic proof supports 40-block windows. Broad
curve and unverified V4/indexed-pool filters retain 10-block fallback and existing
density/saturation subdivision. No extrapolation from factory capability.

## Minimum validation and cost specification

After explicit routing/capability workload authorization, verify exact chain,
methods, retained-history boundaries, canonical headers/receipts/log ordering,
range rejection/density handling, logical/physical batch accounting and shared
protection priority. Compare exact covered intervals against already retained
evidence, acquire only genuinely missing pieces, and enforce original Current
five-second/Survivor three-second financial-consumption deadlines.

Net unique demand is **not yet measured**: the old public audit omits request
parameters/fingerprints, and method totals cannot establish reusable intervals
or remove already paid exact fallback. Future failure fingerprints help diagnose
duplicates; they are not a full utilization census.

Calculate incremental CU from the existing method weights over unique missing
calls after authenticated reuse and existing fallback, then apply the verified
account terms. Public [PAYG FAQ](https://www.alchemy.com/docs/reference/pay-as-you-go-pricing-faq)
and [plans](https://www.alchemy.com/docs/reference/pricing-plans) currently show
$0.525/M CU. This is a conditional public model, not proof of this account's
contract. A non-reused log element at the frozen 60-CU weight models $0.0000315;
there is no defensible whole-machine/monthly forecast here.

The separately proved factory arithmetic remains 180→60 CU for 30 blocks and
240→60 for 40 blocks; neither establishes net migration cost. No broader cost
study or managed-alternative comparison was initiated. Evaluate an alternative
only if the existing app's actual capabilities/cost make that necessary.

### Remaining evidence before enablement

- Actual account-wide throughput, concurrency, contract/pricing and other app
  demand; installed Robinhood 10 RPS is a local setting, not an entitlement.
- Method and history coverage for the actual broad curve/factory/V4 filters,
  headers and receipts, with exact parity, finality/reorganization and bounded
  dense-response/splitting behavior. Only the retained exact factory proof may
  use 40-block windows; unrelated filters remain on 10-block windows.
- Original five-/three-second protection deadlines under shared observation,
  qualification and protective acquisition. A mock accepted request proves
  routing/accounting, not provider capacity or fresh financial consumption.
- Net incremental unique elements/CU after exact authenticated local reuse and
  subtraction of existing canonical fallback. Numeric multi-block discovery
  ranges are not automatically immutable-cache hits; absent interval evidence
  must not be called already acquired.

**Decision pending:** authorize a bounded capability/freshness check and later
activation only if the actual account evidence supports it. The candidate is
inactive, not installed, and independently unproven for production suitability.
No live traffic or migration is authorized by its offline validation.

## Focused offline correction and verification

The actual `ObservationFallbackRpc.batch` → shared admission → mock HTTP path
reproduced the omitted feedback: one four-element `eth_getLogs` HTTP429 followed
by unchanged canonical fallback left public pacing at 2 RPS. The expected failing
regression is retained separately. The correction applies the same endpoint-wide
adaptive slowdown as singles, 2→1.5 RPS, without adding a batch retry or sleep.
Accepted batches count one physical recovery step, not four logical steps;
twenty accepted public batches recover 1.5→1.6 RPS. No provider quota is inferred.

The existing eight-second shared public cooldown remains authoritative. In the
125-ms mock-response fixture, the next discovery admission waits 7.875 seconds
after fallback, honestly exceeding the unchanged five-second queue guard.
Adaptive feedback does not remove that safety failure or prove the public route
suitable. Canonical protective priority and its independent endpoint cooldown
remain unchanged. The failed public batch and exact fallback remain two physical
attempts/eight logical elements, with no added same-endpoint attempt.

A second expected failing regression showed an original wrapper deadline was
not inherited by its canonical fallback: a three-second deadline could become
a new 30-second admission window. A temporary bound in the client's existing
thread-local admission context now retains the earlier of caller and existing
canonical deadlines through cache wait, admission and transport. It restores on
failure and cannot leak into a concurrent protective consumer of the same client.
No deadline, timeout, queue threshold, cooldown or safety escalation was raised.

**92 focused regressions PASS in 4.149s**, zero failures/errors/skips, supported
network-blocked runner and pinned runtime. Coverage includes actual batch failure,
exact fallback parameters/accounting, cooldown waits, absolute deadline expiry,
concurrent canonical protection, unchanged discovery ranges/cursors, immutable
cache behavior, default routing, explicit bound-primary routing, wrong-chain and
identity rejection. Two expected RED results are preserved by reference in the
engineering evidence root. Test duration is correctness evidence, not throughput
or provider-capacity evidence. No production installation, service start,
provider request or authoritative application-state write occurred.
