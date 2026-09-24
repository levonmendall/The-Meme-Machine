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
5. wire epoch-bound lane lifecycle events and authoritative USD evidence into this
   producer without importing earlier campaigns;
6. publish the first export and mount its receipt/export paths read-only in the
   protected dashboard deployment.

This implementation does not perform any of those production activation steps.

## Deterministic verification

```sh
python -m unittest tests.test_portfolio_accounting dashboard.tests.test_dashboard -v
python -m unittest discover -v
python -m tests.resource_check
```

The producer tests use synthetic epochs and canonical facts in temporary directories.
They invoke the actual PR #104 `dashboard.model.Reader` for the compatibility gate and
install a network acquisition failure while exercising the producer.
