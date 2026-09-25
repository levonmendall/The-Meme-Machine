# Robinhood candidate and evidence plane

Implementation branch: `architecture/robinhood-evidence-plane-20260925`.
Base integration: `507c9d2dd5a38ac636a5e28c1be1c257cb9ab0f0`.
The exact tested implementation SHA is emitted as `integration_sha` by the manual
non-market certificate. This branch grants no market or deployment authority.

## Verified failure model

Pons previously queued transaction/log instances in memory and stopped polling
while its evidence queue was nonempty. Complete candidate authentication,
trajectory construction and window normalization ran on that event's original
five-second clock. Multiple observations of one curve therefore competed as
independent jobs. Its existing immutable cache was process-local. Ramses already
had a durable append-only factory inventory and finalized-frontier scheduling;
those facilities remain. Its bounded native-cost route search did not require
201 bins but previously followed that hydration.

The retained opportunity-loss audit reports 19,280 Pons screened/terminal events,
4,984 infrastructure classifications, and 2,719 pre-queue rows without individual
identity across the audited market runs. These are historical event denominators,
not unique durable candidates. They must not be summed with the new candidate
state counts or treated as disjoint overlapping queue losses.

## Durable state and runtime integration

`plane.py` uses the existing local SQLite architecture, WAL, FULL synchronization,
short immediate transactions and immutable observation/transition tables. The
production composition shares the database next to
`MM_CERTIFICATION_RPC_CACHE_DB`; no server or new infrastructure is required.
Canonical standalone lane invocations share the configured durable Robinhood state
directory. Explicit local fallback paths remain for offline fixtures without
a canonical provider configuration. See [provider finalization](PROVIDER_FINALIZATION.md)
for the authenticated authority, shared ceiling and telemetry contract.

A candidate stores native identity, generation, observation order and time,
desired/completed watermarks, pending intent, interpretation identity, deadline,
priority, rank, owner/claim, current classification and the committed result.
Pons keys include chain/factory/curve; authenticated token and launch provenance
are retained in evidence. Ramses keys include chain/factory/pool. Interpretation
includes policy, provider fingerprint, adapter/source/schema identity and relevant
configuration. A changed interpretation fails closed instead of reusing old work.

Observations are deduplicated by native event identity. Conflicting duplicates
poison admission and remain audited. Newer observations coalesce the pending
identity, advance its generation and fence older completions. Sells also fence
an older Pons buy. Provider calls never hold a candidate transaction. Commit-time
CAS checks the generation, claim and watermark. A superseded provider operation
can only contribute independently valid immutable/exact-state cache evidence.

Pons discovery now persists observations independently of hydration. A bounded
single hydration worker consumes current candidate needs; the consumer handles
completed work independently of slow discovery. Committed full authenticated
results form a durable outbox, including typed-state reconstruction, receipts and
headers needed by the frozen paper path. Fsynced native report archives and a
bounded checkpoint recover consumed effects without repeatedly rewriting all
historical rows. Duplicate redelivery does not renew the original deadline.

Native paper reservation identities are deterministic for broker decisions. A
fresh generation/deadline check commits reservation intent before native capital
reservation. Native post-commit observations project reservation, fill, position
safety and settlement into the audit. Position evidence is independently versioned
so newer discovery cannot suppress an existing position's exit. Native accounting
and its genesis, sizing and conservation rules are unchanged.

Ramses registers reusable pool work and full screening results. Exact duplicate
pool/frontier/decision-input work reuses the committed result. Capability keys
include finalized block hash, pool/token identity, cost amount, source and policy.
Negative routes expire with that state; they are never immutable vetoes. Positive
preflight does not authorize entry or replace executable entry/unwind evidence.
Route-negative pools retain a 12-read radius-1 state sample for their original
active-bin feature/percentile population, while avoiding 408-read wide hydration.
Early structural rows remain in opportunity telemetry.

## Evidence and policy boundaries

Public/sequencer observations nominate and supersede work. They do not populate
canonical reserves, receipts, headers, code, gas or authenticated demand fields.
Receipt/header-authenticated normalized trades update a bounded durable rolling
window using the frozen 60-second/512-event bounds. Duplicate normalization is
reused with exact raw digest, block hash, finality and source provenance; conflicting
observations fail closed. The unchanged strategy projectors consume those exact
inputs for buyer groups, growth, buy/sell/net flow, concentration, creator flow and
repeat-buyer persistence. Exact curve/block reserves and authenticated timestamp
anchors support the unchanged 5/15/30/60-second trajectory calculations. No new
approximate rolling formula or public-to-canonical promotion is introduced.

Verified Pons CREATE2 deployer/non-proxy runtime and one-time token initialization
permit reuse of compiled code/token identity and immutable launch terms after an
authenticated origin, with source-version invalidation and no pre-origin reuse.
Current factory records remain fresh: creator recipient, buyback and graduation
fields are mutable and cannot be cached as a whole immutable record. Launch times,
headers, receipts and exact curve/block reserves persist across restart. Ramses
reuses immutable CWIA token/bin-step metadata and append-only factory membership
only under the pinned factory/implementation runtime identities.

The existing shared raw RPC cache retains chain/provider identity and exact block
hash/method/arguments, with lane-level finality verification still mandatory.
Identical calls at different blocks do not substitute. Gas reuse remains confined
to the existing decision cost epoch. Dead-process cache flight ownership is now
recoverable using boot ID/PID/start-time identity. Old unprovable owners fail closed.
No Alchemy ceiling, provider topology, retry budget or freshness limit was raised.

Watch Pons work uses priority 4, authenticated promoted work priority 2, Ramses
screening priority 3, entry confirmation priority 1, and native position work the
existing safety priority. Broker aging cannot overtake safety/entry. Admission
uses the existing endpoint governor queue/cooldown/interval and locally measured
service p95. A cold store only has the first-request lower bound; it does not claim
to predict an unseen full hydration. Infeasible work remains a measured deferred
candidate, separately from strategy rejection, authoritative failure, supersession
and freshness/deadline censoring. Ramses' 210 seconds is a recenter decision deadline,
not a previously nonexistent scan deadline; no new scan deadline was invented.

## Retained replay

Both replay commands install network guards and use only committed retained data.

| Run | Retained Pons decision rows | Native curves in those rows | Complete vectors |
|---|---:|---:|---:|
| 357 | 1,907 | 220 | 2 |
| 358 | 692 | 109 | 0 |
| 360 | 1,036 | 139 | 5 |
| 362 | 3,023 | 268 | 1 |
| 364 | 3,231 | 279 | 7 |
| 366 | 1,880 | 187 | 13 |
| 367 | 493 | 100 | 4 |
| 368 | 2,789 | 217 | 1 |

All 33 complete canonical Pons vectors reproduce the frozen qualification inputs,
reasons, size and economics, including seven qualifiers. The separate campaign
wallet-skill overlay cannot be reconstructed completely and is explicitly excluded
from that core comparison. The policy module itself is byte-identical. The audit
has nine qualifiers overall; missing complete inputs for the other two are not
manufactured. Existing deterministic fill-persistence tests cover entry confirmation.

Of these 15,051 retained decision rows, 10,253 have usable native identity and
recorded observation ordering/time for an identity-only replay. Holding that same
workload before service produces 1,519 candidate jobs across the run partitions,
with 8,734 superseded pending observations. This is a controlled coalescing result,
not a latency counterfactual or a claim of 8,734 saved physical requests. Ten queued
updates also deterministically produce one actual broker job in the lane tests.

For run 364, the full preserved initial Ramses scan and exact transport responses
support a stronger replay: two pools, one route-incapable pool, one wide hydration
avoided, **866 to 470 logical reads (396 fewer)**, unchanged equivalent complete
inputs/decision/economics for the route-capable pool and the same no-trade result
for the route-incapable pool. Fifty-one old transports contained avoided reads;
that is not a prediction of new physical batching. The historical screen used v3;
both compared paths apply current frozen v4 to the same retained evidence.

New physical request totals, Pons new complete-decision conversion, stale-before/
stale-during/consumer-deadline rates, authenticated work per new complete candidate,
and a <10% censoring result are **UNMEASURABLE** from these compact traces. Missing
pre-queue identities, complete provider responses and counterfactual timings prevent
honest inference. Runs 355/356/359 have retained audit aggregates but their large
full artifacts could not be materialized with the available transfer limits.
361/363/365 do not provide a comparable retained candidate trace here. Denominators
are not reduced to manufacture an improvement. Hard-capacity loss cannot be separated
numerically from remaining architectural loss without those missing records.

## Exact non-market verification

After committing the tree, run:

```sh
python -m certification.robinhood.certify --worktrees ../lanes --output ../checks/final-robinhood
```

This runs all four pinned native component suites, supervisor/broker tests, native
SIGKILL transaction probes, production restart guards, integrated policy/lifecycle
bundles, resource checks, policy freeze checks and both retained replays. All test
children forbid external socket connections. It records the exact HEAD and checks
that source identities remain unchanged. No workflow is dispatched.

Frozen identities before and after:

- Pons source `3de3d376847531ccb90e260cfcc96c37587ccb23`; policy
  `19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84`.
- Ramses source `41b5f263efc31bedf9b39039a9f66bed264b70d3`; policy
  `58d6ca2a911c4d27ea35da8c972f0a6b1c65c3e9192d811834b92d63d2c08b1e`.

Exact composed source diff identities are declared in `certification/sources.json`;
the frozen protocol's corresponding source-diff bindings change only to match
those overlays. Strategy economics, authorization rules, trigger/workflow files,
market acceptance rules and provider ceilings remain unchanged.

## Limits and acceptance status

This is single-host local durable state, not distributed failover. Immutable audit
and reusable evidence accumulate; rolling feature retention is bounded. Disk/WAL
failure fails closed. Provider operations performed before a crash cannot be undone.
Recovery never fabricates a fresh clock or rewrites native exposure.

A Pons restart with fully proven flat capital can recover discovery/candidate work.
Unresolved native reservations/open controller context retain safety priority and
exposure and block fresh admission. Existing Ramses native controller checkpoints
and its fail-closed campaign restart contract remain authoritative. These tests do
not claim automatic reconstruction of missing volatile position-controller context.

Deterministic certification is distinct from overall task acceptance. Requested
Pons replay improvement gates 6 and 7 remain **NOT PROVEN / UNMEASURABLE**. Do not
promote this branch or represent it as having met every acceptance gate. No market
run, deployment, Render interaction, or active certification-branch movement is
part of this implementation.
