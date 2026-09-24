# Shared paper-portfolio accounting

## Authority and current state

`meme_machine.portfolio_accounting.PortfolioAccounting` is the authoritative
common-portfolio producer for the dashboard contracts in
`docs/READ_ONLY_DASHBOARD.md`. It is outside the dashboard package and imports no
dashboard, provider, strategy, workflow, or network code.

The producer is implemented on top of dashboard PR #104 head
`05d165ede35475abad95fc7b30c49e71fa43973f`. The canonical integration source
remains `cert/prospective-market-v1` at
`1c6da29d08bfbe42e39ea1c8068933aae6b15cdb`.

**The genuine portfolio remains `NOT_INITIALIZED`.** Opening a database creates
only empty schema. No repository file, import, server startup, or dashboard request
calls `establish_inception`. That separately authorized operation must later supply
the real epoch ID, UTC inception time, canonical inception event ID, portfolio
source/config hashes, and all four lane source/policy/config identities.

## Durable model

One SQLite database contains:

* exactly zero or one immutable `meme-machine-portfolio-inception-v1` receipt;
* one append-only, hash-chained event journal with monotonic sequence numbers;
* no mutable canonical balance or position tables.

The producer replays the complete journal on restart and derives balances,
reservations, positions, settlements, fees, shared costs, marks, lane contribution,
and history. SQLite triggers reject updates and deletes to both inception and event
facts. Event IDs are globally unique within the epoch. Facts from another epoch,
before inception, or earlier than the journal clock fail closed.

The receipt JSON and `meme-machine-portfolio-export-v1` JSON are atomic, recoverable
projections. A projection write failure is recorded separately and cannot prevent a
later canonical accounting event. The dashboard still has no writer handle.

## Shared capital and lifecycle operations

The account starts at exactly `$500.00 USD`. Capital moves only through explicit
operations:

| Operation | Accounting effect | Trade count effect |
| --- | --- | --- |
| `reserve` / `release_reservation` | available cash to/from reserved cash | none |
| `enter` | reservation to remaining basis; entry fee becomes realized cost | creates one entered lifecycle |
| `realize` / harvest | releases basis and books exact gross proceeds, fees, and net result | same lifecycle remains open |
| `rebalance` | releases and adds basis under the same lifecycle | increments rebalance count only |
| `mark` | records current bounded net-liquidation evidence or explicit unavailable state | none |
| `settle` | releases all remaining basis and freezes terminal facts | completes the lifecycle once |
| `charge_shared_cost` | reduces shared cash and portfolio realized result | none |
| `record_history_sample` | derives actual portfolio/lane values from current journal state | none |
| `publish` | emits the bounded dashboard contract at a new journal sequence | none |

Available cash is a valid state. The producer never selects a lane, candidate,
position size, or entry. It has no method that places a trade or starts a workflow.

Every valued entry, realization, rebalance, settlement, mark, and shared cost
requires an explicit USD value-evidence identity, hash, source `as_of`, and
source-established `valid_until`. Evidence must be valid at the accounting event;
the producer never extends its deadline. Current marks become `STALE` after that
deadline. Missing native-to-USD authority is rejected at entry/settlement and is
represented as unavailable for marks.

## Native lane integration boundary

**The genuine portfolio remains `NOT_INITIALIZED`.** The integration added in
`meme_machine.portfolio_lane_integration` does not call `establish_inception` and
does not create a database, receipt, epoch, timestamp, balance, or export. With no
explicit binding it returns a dormant no-I/O producer, so existing lane imports,
startup, research runs, and native paper books behave exactly as before.

After a separately authorized inception, one `PortfolioLaneProducer` owns the one
`PortfolioAccounting` writer. It must be opened against an already-existing database
with the exact active epoch and inception SHA. All four adapters share that producer;
there are no per-lane USD ledgers or shadow cash balances. The producer serializes
competing calls through the accountant transaction, so a reservation accepted for
one lane immediately reduces cash available to every other lane.

The normalized native-event contract is
`meme-machine-portfolio-lane-event-v1`. Every delivery contains the exact epoch,
lane, native lifecycle ID, native event ID, per-lifecycle sequence, native journal
hash, source time, action, and action data. Canonical portfolio event and reservation
IDs are deterministic functions of those immutable identities. The producer records
a hash of the complete normalized event in canonical provenance. Redelivery of the
same fact is idempotent; the same event identity with changed content, a sequence
gap/regression, a wrong epoch, or changed inception/source binding fails closed.

The concrete lane hooks are:

| Lane | Native boundary | Shared adapter boundary |
| --- | --- | --- |
| Pump | native paper reserve/fill/partial-harvest/mark/settle journal (`PaperBook` / `PumpAccelerationPaperLifecycle`) | `reserve_before_fill`, `release_failed_fill`, `fill_committed`, `partial_harvest`, `mark`, `settlement` |
| Pons | `SelectivePaper.reserve` and `SelectivePaper.advance` entry/partial exit/runner/settlement | `reserve_before_entry`, `release_cancelled_entry`, `entry_committed`, `partial_exit`, `runner_mark`, `settlement` |
| Ramses | `RamsesStrategyLedger.reserve/open/checkpoint/settle` | `reserve_before_open`, `release_failed_open`, `open_committed`, `reserve_rebalance`, `checkpoint_rebalance`, `mark`, `settlement` |
| Meteora | `Replay.reserve/deposit/mark/withdraw/settle` and any genuine native range rebalance | `reserve_before_deposit`, `release_cancelled_deposit`, `deposit_committed`, `reserve_rebalance`, `range_rebalance`, `mark`, `settlement` |

The caller invokes reservation at the last safe point before the corresponding
native entry can commit. A rejected/failed native entry delivers the deterministic
release event. Once genuine native exposure is durable, the entry event converts
that same reservation to common deployed basis. If acknowledgement is lost at any
boundary, restart replays the unchanged native journal event: the producer returns
the existing receipt rather than debiting cash, P&L, or fees again. A reservation
left by interruption remains visible and is never silently released; recovery must
replay the durable native entry or an authoritative native cancellation.

The existing native lifecycle identities map one-to-one to canonical IDs as
`<lane>:<native-lifecycle-id>`. Partial exits, harvests, runner transitions, and
rebalances retain that ID. Only terminal settlement completes it. Position fees are
sent with their actual entry/realization/rebalance/settlement fact. True portfolio
shared costs continue to use the accountant's existing `charge_shared_cost` operation
and are never allocated to a lane merely to balance reconciliation.

Valued events require an explicit authoritative USD evidence ID/hash with the source
`as_of` and source-established `valid_until`. The adapter does not read a provider,
perform FX, extend freshness, or accept binary floating point. The present native
lane books do not themselves establish a common native-to-USD conversion; therefore
an activated caller without separately authoritative USD evidence fails closed at
entry/realization/rebalance/settlement. Current marks accept the same bounded proof.
Missing, unknown, fail-closed, or already-stale marks remain explicit and do not
block unrelated immutable lifecycle facts.

For later protected runtime composition, `producer_from_environment` recognizes only
a complete binding: `MM_PORTFOLIO_ACCOUNTING_DB`, `MM_PORTFOLIO_EPOCH_ID`, and
`MM_PORTFOLIO_INCEPTION_SHA256`. If none are present it is dormant. A partial binding,
missing database, uninitialized database, epoch mismatch, or receipt-hash mismatch
fails closed. Receipt/export projection paths are optional and do not grant inception
authority.

The current native books remain evidence rather than consolidated USD balances:

| Lane | Current canonical source | Native accounting retained |
| --- | --- | --- |
| Pump | `324fee081dd7664a30df4d88aaa1448d28e3033e` | integer SOL paper book and journal |
| Pons | `3de3d376847531ccb90e260cfcc96c37587ccb23` | partial/runner quote-unit cohort ledger |
| Ramses | `5dd003b45a60a73e19bf1162f81e4f1ccd2b4ef2` | separate quote-asset maker ledgers |
| Meteora | `ec0b96f999f460c35cb63b27cd0387c4f81f9898` | integer SOL DLMM paper book and journal |

The common journal preserves each native lifecycle ID and native journal hash as
provenance. It does not sum native genesis balances, assign `$125` sleeves, import
historical campaigns, or convert native units itself. After a separately reviewed
activation/integration change, existing lane runtimes may submit a normalized common
event only when their canonical lifecycle has genuine epoch-bound exposure and an
authoritative USD value fact under existing freshness/finality rules.

Pump, Pons, Ramses, and Meteora contributions are derived independently from their
entered common lifecycles. Pons runner/harvest state and Ramses/Meteora pool/range,
in-range, maker, and rebalance state are retained without reproducing strategy logic.

## Reconciliation and history

Every journal append proves these exact Decimal equations where valuation exists:

1. lane realized results minus shared costs equals portfolio realized P&L;
2. open remaining basis equals deployed capital;
3. available cash plus reserved cash plus deployed basis equals `$500.00` plus
   realized P&L;
4. equity equals `$500.00` plus realized P&L plus valid unrealized P&L;
5. position fees plus shared costs equals total fees/costs.

Equation 4 is explicitly unavailable when any open mark is missing, unavailable, or
stale. It is never forced to zero. The other equations remain exact. No external
adjustment, balancing account, or rounding plug exists.

History starts with the canonical `$500.00` inception sample and zero lane
contribution samples. Later samples are derived from the journal, append-only, and
may contain explicit null gaps. `history_complete` becomes true only when an
explicit complete sample covers the export `as_of`; later accounting activity makes
that claim incomplete until new coverage is recorded.

## Later activation step

After merge and deployment readiness review, a separately authorized operation must:

1. choose the genuine epoch ID, UTC inception timestamp, and canonical event ID;
2. construct and review the exact `$500.00 USD`, `paper_only: true` receipt;
3. bind the deployed portfolio and four lane source/policy/config identities;
4. call `establish_inception` once against a new empty durable database;
5. configure the already-implemented epoch-bound lane adapters with the initialized
   database/epoch/hash and supply authoritative USD facts at each native boundary,
   without importing earlier campaigns;
6. publish the first export and mount its receipt/export paths read-only in the
   protected dashboard deployment.

This implementation does not perform any of those production activation steps.

## Deterministic verification

```sh
python -m unittest tests.test_portfolio_accounting tests.test_portfolio_lane_integration dashboard.tests.test_dashboard -v
python -m unittest discover -v
python -m tests.resource_check
```

The producer/integration tests use synthetic epochs and canonical facts in temporary
directories. They drive all four lane adapter surfaces, competing reservations,
restart/redelivery, partial/runner/rebalance/settlement behavior, and invoke the actual
PR #104 `dashboard.model.Reader` for the compatibility gate. Network acquisition is
installed as an immediate failure while the producer and adapters are exercised.
