# Parallel dashboard/runtime integration preparation

Status: **off-path preparation only**.  This work does not activate the portfolio,
bind a certified runtime, deploy Render changes, or participate in Stage-E
qualification.

## Isolation and lineage

Stage-E frozen candidate supplied by the owner:

- candidate: `dc08f9064cf5e37b63f383f52aa709d0afc1723f`
- tree: `68736cf664169dee665762019800bf87ca0f1f67`
- parent: `ce4257309cb1f6ec68e38d363320edf62d59db7f`

At preparation time the exact candidate commit was **not available through the
published GitHub repository**.  It was not reconstructed, published, branched
from, modified, or used for qualification.

Dashboard/accounting lineage preserved here:

| Layer | Published head |
| --- | --- |
| PR #104 read-only dashboard | `05d165ede35475abad95fc7b30c49e71fa43973f` |
| PR #105 shared accounting | `b11bc826e38681355bc6ce535b613fab1a980052` |
| PR #106 four-lane integration | `68ef37c5b9e8955db3c1c5af1797537d4e196b56` |
| Render/dashboard release descendant | `4da955c58924d680317a4990f4ae46f332954272` |

`release/portfolio-dashboard-v1` is a direct descendant of PR #106 (eight
commits ahead, zero behind) and already contains the bounded public staging
server, security regression tests, staging documentation, and `render.yaml`.
The integration-prep branch therefore builds on that published release instead
of reimplementing it.

No Stage-E branch, workload, pressure test, acceptance rule, qualification
cohort, promotion ref, or runtime candidate is changed by this work.

## Existing contracts retained

### Shared accountant

`PortfolioAccounting` remains the only common USD portfolio writer.

- exactly $500.00 USD PAPER inception, only through explicit
  `establish_inception`;
- one immutable inception receipt;
- one append-only/hash-chained SQLite event journal;
- exact Decimal accounting;
- replay on restart;
- atomic `meme-machine-portfolio-export-v1` projection;
- all four lane identities bound at inception;
- no provider, strategy, workflow, signing, or transaction authority.

The five reconciliation equations remain unchanged:

1. lane realized results minus shared costs = portfolio realized P&L;
2. open remaining basis = deployed capital;
3. available + reserved + deployed = $500 + realized P&L;
4. equity = $500 + realized P&L + valid unrealized P&L;
5. position fees + shared costs = total fees/costs.

### Lane adapter

`PortfolioLaneProducer` remains dormant unless an already initialized database,
exact epoch, and exact inception hash are supplied.  It accepts
`meme-machine-portfolio-lane-event-v1`, preserves native lifecycle/event/journal
identity, requires monotonic per-lifecycle sequence, and rejects conflicting
redelivery, sequence gaps/regressions, cross-epoch facts, or missing authoritative
USD evidence.

No activation binding is added in this preparation.

### Dashboard

The dashboard remains a bounded local-file observer.  Its API is GET/HEAD only,
has no writer or provider handle, never initializes the portfolio, and preserves
`NOT_INITIALIZED`, `STALE`, `UNAVAILABLE`, and `FAIL_CLOSED` states.

The current staging server already bounds concurrency/rate and supplies no-store,
CSP, no-referrer, nosniff, and frame-denial headers.  Production owner
authentication is still a deployment boundary, not a trading-runtime feature.

## Published-runtime compatibility map

This audit uses the published Stage-E parent
`ce4257309cb1f6ec68e38d363320edf62d59db7f` only.  It **does not** claim
compatibility with unavailable `dc08f906…`.

| Lane | Published native lifecycle boundary inspected | Durable identity / restart observations | PR #106 adapter assessment |
| --- | --- | --- | --- |
| Pump | `tests.pump_acceleration_natural_prospective` driving `PumpAccelerationPaperLifecycle.reserve/fill/mark/settle`, plus persisted campaign checkpoints | Native position/reservation state and lifecycle history exist; the certification observer also journals events. Final activation must bind a restart-stable native lifecycle ID, event ID, journal hash and per-lifecycle sequence from the certified runtime rather than inventing an observer-local identity. | Adapter action shape is compatible. Binding adaptation is required. Exact candidate verification deferred. |
| Pons | published Robinhood candidate broker/recovery layer plus external `pons_selective_cohort`/continuation lifecycle | Published recovery explicitly preserves `lifecycle_id`, detects replacement identity conflicts, and coalesces restart receipts. Final binding must take sequence authority from the durable native lifecycle journal/order. | Adapter action shape is compatible. Binding adaptation is required. Exact candidate verification deferred. |
| Ramses | published certification wrapper around the assembled external Ramses strategy/extended lifecycle | Published wrapper retains natural lifecycle results and durable campaign artifacts, but the exact certified external source is assembled in the qualification worktree. Durable accounting event ID/sequence must be checked against the exact certified source before binding. | Reserve/open/rebalance/mark/settle surface matches PR #106. Exact native identity mapping remains deferred. |
| Meteora | published certification wrapper around assembled `solana_dlmm_independent_v1`, lifecycle timing, atomic checkpoints and retained observations | Durable checkpoints and lifecycle observations are persisted, but the exact certified external source is assembled in the qualification worktree. Deposit/rebalance/settlement event identity and sequence authority require the exact certified source. | Reserve/deposit/rebalance/mark/settle surface matches PR #106. Exact native identity mapping remains deferred. |

The accounting boundary must adapt to those durable native facts.  No trading
strategy, threshold, provider policy, or evidence-plane behavior should be
changed to simplify accounting.

## Off-path snapshot data plane

Implemented target:

```text
certified PAPER runtime
        |
        | durable native lifecycle facts + authoritative USD evidence
        v
PortfolioLaneProducer / PortfolioAccounting
        |
        | atomic canonical inception.json + export.json
        v
independent snapshot publisher
        |
        | meme-machine-dashboard-snapshot-v1
        | (copy/sync may cross hosts; no runtime wait)
        v
independent replica applier
        |
        | generation-N/{inception.json, accounting.json, snapshot.json}
        | atomic "current" symlink swap
        v
Render-local read-only paths
        |
        v
dashboard Reader -> GET/HEAD UI/API only
```

`meme_machine.portfolio_snapshot_transport` provides this off-path boundary.

### Snapshot properties

A bundle binds:

- epoch ID;
- inception SHA-256;
- canonical export sequence;
- export `as_of` and source-established `valid_until`;
- portfolio/lane source identity hash;
- receipt hash;
- export hash;
- whole-snapshot hash.

The receiver rejects:

- corrupt/partial JSON;
- hash mismatch;
- wrong epoch or changed inception;
- source identity change inside an epoch;
- sequence regression;
- same-sequence equivocation;
- unsupported external adjustments;
- binary floating-point facts;
- over-capacity source/bundle inputs.

Identical redelivery is idempotent.

Each accepted replica is written into a complete generation directory and only
then exposed by one atomic `current` symlink replacement.  Generation files are
0440.  Retention is bounded (default current + one predecessor; maximum four
generations).  A failed copy or failed validation leaves the previous `current`
generation untouched.

The module deliberately implements no provider/network client.  Production may
copy the single bundle file using an independently supervised sync mechanism.
The producer does not synchronously wait for dashboard delivery.

Example producer-side packaging:

```sh
python -m meme_machine.portfolio_snapshot_transport publish \
  --inception /srv/meme-machine/portfolio/inception.json \
  --accounting /srv/meme-machine/portfolio/export.json \
  --bundle /srv/meme-machine/dashboard-spool/snapshot.json
```

After an independently authorized/selected cross-host copy, Render-side apply:

```sh
python -m meme_machine.portfolio_snapshot_transport apply \
  --bundle /var/data/meme-machine-dashboard/incoming/snapshot.json \
  --replica-root /var/data/meme-machine-dashboard/replica
```

Dashboard read paths then remain fixed:

```text
/var/data/meme-machine-dashboard/replica/current/inception.json
/var/data/meme-machine-dashboard/replica/current/accounting.json
```

The symlink target changes atomically; the configured dashboard paths do not.

## Authoritative USD evidence

The existing PR #106 interface remains authoritative:

`usd_evidence(evidence_id, evidence_sha256, as_of, valid_until)`

with currency fixed to USD by the constructor.  Valued entry, realization,
rebalance, settlement and current-mark facts require that evidence.  The
accountant/adapter do not acquire FX, infer stale values, extend validity, or turn
missing evidence into zero.

Tests continue to use synthetic evidence only.  Production evidence acquisition
and attachment are intentionally deferred until final runtime activation.

## Synthetic integration and failure matrix

The existing PR #105/#106 tests already exercise the shared $500 account, all
four adapters, competing reservations, overcommit rejection, entry failure
release, valued entry, partial realization/runner behavior, rebalances, marks,
settlements, duplicate/redelivery, conflicting duplicate, sequence
gap/regression, cross epoch, restart/replay, exact Decimal behavior, missing USD
evidence and all five reconciliation equations.

The added transport tests cover the remaining integration boundary:

- atomic bundle publication and atomic replica generation;
- sequence monotonicity;
- same-sequence equivocation;
- cross-epoch rejection;
- source-identity continuity;
- idempotent redelivery;
- corrupted/partial transfer;
- bounded generation retention;
- dashboard restart against the same `current` pointer;
- stale snapshot presentation without extending `valid_until`;
- missing state behavior;
- zero provider call / zero portfolio write during dashboard requests;
- mutation-method rejection;
- transport failure remaining off the accounting path.

`tests/test_dashboard_integration_resources.py` records synthetic wall/CPU time,
bundle/export/SQLite sizes and peak traced memory for projection, serialization,
replica apply and 200 cached dashboard reads.  These measurements are synthetic
only and are **not** Stage-E overhead certification.

## Zero-interference proof boundary

This branch does not import the snapshot transport into a trading runner,
qualification runner, evidence plane, or strategy.

The transport reads already-published projections.  The dashboard reads only the
replica.  A replica error can make the UI stale/unavailable but cannot reject,
delay, reserve, fill, rebalance, settle, or dispatch trading work.

A future runtime composition must preserve this property: snapshot packaging or
network transfer must run independently of the trading/evidence critical path.

## Render preparation

No Render service is modified by this branch.

The existing staging blueprint has auto-deploy disabled and starts:

```sh
python -m dashboard --host 0.0.0.0
```

For a later production cutover, the intended read-only start command is:

```sh
python -m dashboard --host 0.0.0.0 \
  --inception "$MM_DASHBOARD_INCEPTION" \
  --accounting "$MM_DASHBOARD_ACCOUNTING" \
  --telemetry "$MM_DASHBOARD_TELEMETRY"
```

Prepared environment names:

| Variable | Purpose | Authority |
| --- | --- | --- |
| `MM_DASHBOARD_INCEPTION` | replica `current/inception.json` | read only |
| `MM_DASHBOARD_ACCOUNTING` | replica `current/accounting.json` | read only |
| `MM_DASHBOARD_TELEMETRY` | optional persisted supervisor projection | read only |
| `MM_DASHBOARD_MAX_CONCURRENCY` | bounded HTTP concurrency | observer only |
| `MM_DASHBOARD_RATE_LIMIT_PER_MINUTE` | bounded request rate | observer only |
| `PORT` | Render listener | observer only |

The dashboard service must not receive Alchemy/Robinhood credentials,
`MM_PORTFOLIO_ACCOUNTING_DB`, `MM_PORTFOLIO_EPOCH_ID`,
`MM_PORTFOLIO_INCEPTION_SHA256`, signing authority, transaction authority, or
portfolio-writer credentials.

### Production security requirement

The current staging release is intentionally public.  **Production activation
must not reuse that public exposure unchanged.**  Before cutover, place both
`/dashboard*` and `/api/dashboard/*` behind authenticated owner-only access at
a trusted TLS reverse proxy/access layer.  Keep health-check exposure minimal.
Do not add provider credentials or trading controls to implement authentication.

Render terminates TLS at the service edge.  Any additional access layer must
preserve TLS from the user to the trusted edge and must not inject secrets into
dashboard responses.  Keep request concurrency/rate limits enabled.

### Storage and sync destination

Production needs durable local replica storage, for example:

`/var/data/meme-machine-dashboard/replica`

Only the independent replica/sync process needs write access to that root.
Generation files themselves are read-only; the dashboard only needs traversal
and read access to `replica/current`.

Do not attach/activate the production disk or sync credentials until separately
authorized.  The cross-host copy mechanism should carry only the snapshot bundle;
it must not carry runtime/provider configuration.

### Health and rollback

- health route: `/healthz`;
- dashboard/accounting freshness is reported through dashboard state, not by
  making the health route a trading dependency;
- rollback: stop advancing `current` and atomically repoint it to the retained
  predecessor generation, or restore the prior dashboard deployment;
- a dashboard rollback never rolls back the authoritative accountant journal.

## Exact post-Stage-E activation checklist

Execute only after Stage E is green and separately authorized.

1. **Exact certified runtime compatibility check**  
   Inspect the exact certified commit/tree.  For each lane record the durable
   lifecycle ID, native event ID, sequence authority, journal/evidence hash,
   reservation boundary, entry boundary, realization/rebalance boundary,
   settlement boundary, and restart/redelivery rule.  Compare those facts to
   `PortfolioLaneProducer`.  Do not alter strategy economics to make them fit.

2. **Final adapter attachment**  
   Add only the narrow runtime-to-adapter calls at durable native boundaries.
   Preserve dormant behavior when no portfolio binding exists.  Prove native
   operation is unchanged with the adapter disabled.

3. **Genuine inception**  
   Create a new empty production PAPER portfolio database.  Choose the explicit
   epoch ID, UTC inception time and canonical inception event ID.  Bind exact
   portfolio and all four lane source/policy/config identities.  Call
   `establish_inception` exactly once for $500.00 USD.  Import no prior campaign.

4. **USD evidence authority**  
   Bind the separately reviewed provider/runtime evidence path that establishes
   USD value evidence under existing freshness/finality rules.  Do not create an
   independent dashboard price source.

5. **First canonical export**  
   Record complete post-inception lifecycle coverage/history as applicable and
   publish the first `meme-machine-portfolio-export-v1`.

6. **Snapshot feed**  
   Start the independent publisher.  Configure the selected cross-host sync with
   snapshot-only credentials.  Apply into an empty production replica root and
   verify epoch/inception/source/sequence hashes.

7. **Render cutover**  
   Provision the durable replica path, configure the three read-only dashboard
   paths, enforce owner-only authenticated access, keep provider/writer secrets
   absent, then switch the protected dashboard to canonical mode.

8. **End-to-end reconciliation**  
   Verify all five accounting equations, exact sequence/inception/source identity,
   no historical pre-inception activity, dashboard state CURRENT only inside the
   canonical validity window, and zero provider/writer calls from dashboard
   requests.

9. **Restart validation**  
   Restart accountant, publisher/replicator and dashboard independently.  Replay
   the same snapshot (must be idempotent), advance one new sequence, and prove no
   duplicate lifecycle, cash, P&L, fee, or settlement accounting.

## Intentionally deferred

- genuine $500 inception;
- production epoch/database activation;
- actual runtime adapter calls;
- exact `dc08f906…` compatibility;
- real provider-backed USD valuation;
- network/sync credential selection;
- canonical merge;
- Stage-E measurement of any observer overhead;
- Render production disk/access/cutover;
- historical trade import;
- previous campaign import.

## Genuine remaining blockers

1. Exact Stage-E candidate `dc08f906…` is not published/available for source
   inspection, so exact-candidate lane compatibility is deferred.
2. Production runtime adapter attachment must wait for that exact compatibility
   check and Stage-E completion.
3. Production USD evidence authority is not yet activated.
4. Cross-host transport product/credential choice (if runtime and Render remain on
   different hosts) is a deployment decision; the snapshot file contract is ready.
5. Owner-only production access and Render production changes require separate
   authorization.

These are deferred dependencies, not reasons to change the Stage-E candidate.
