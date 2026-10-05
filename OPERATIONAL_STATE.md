# Meme Machine PAPER

Pump Current/Survivor, Pons Current/Survivor, Meteora and Ramses run under one
supervisor with one fresh $500 Decimal portfolio. The candidate is ready for
deployment acceptance; the genuine portfolio epoch has not been initialized.

Entrypoint: `python -m meme_machine.operational run`. CPython 3.12.14;
`pip install -r requirements.txt`. SQLite 3.45.1 and 3.53.1 have both passed the operational suite.

Required environment: `MM_STATE_ROOT`, `MM_SOLANA_READ_RPC_URL`,
`MM_ROBINHOOD_READ_RPC_URL`. State is SQLite and bounded snapshots below
`MM_STATE_ROOT`, bound to the verified existing persistent volume at deployment.
Provider credentials stay outside Git in `/etc/meme-machine/paper.env`.
Robinhood valuation uses its existing RPC for the verified Chainlink USDG/USD
feed and authenticated native→USDG quotes. Invalid/stale valuation reports
`VALUATION_UNAVAILABLE` and prevents economic work requiring that value.

After deployment is authorized, start with
`sudo systemctl start meme-machine-paper`; stop with
`sudo systemctl stop meme-machine-paper`. SIGTERM drains the supervisor and lanes.
The unit restarts unexpected supervisor failures; lane failures recover their
durable journals and pending portfolio deliveries before discovery resumes.

Health: `python -m meme_machine.operational health` and
`journalctl -u meme-machine-paper -f`. Portfolio:
`python -m meme_machine.operational portfolio`. `dashboard-snapshot.json` is a
read-only feed; dashboard failure does not stop trading.

Update: stop the service, retain the state root, check out the accepted exact
operational commit, install its requirements, run FAST and OPERATIONAL tests,
then restart. Recovery resumes the same epoch and positions.

PAPER only: no wallet keys, transaction signer, real submissions, owner permit,
or live-money switch.

Next acceptance command, after deployment:
`python -m meme_machine.operational.acceptance CAPACITY --seconds 3600`.
Continue with controlled RECOVERY, then AUTONOMY as described in
`operational/ACCEPTANCE.md`. Acceptance has not run during consolidation.


Directional opportunity telemetry (observation only)

The Current/Survivor sleeve adds separate opportunity journal, outcome-target,
incremental-scan and schema-marker tables. Existing sleeve genesis, economic
journal, open positions, reservations and PAPER epoch remain unchanged. Legacy
receipts and links transfer inside one SQLite transaction; interrupted DDL or
backfill rolls back and is retried idempotently on opening. Telemetry failure is
observable and cannot authorize, suppress or alter an economic decision.

Current receipts contain policy identity, all rejection reasons, measurable
observed gates, thresholds, comparators, signed distances and category aggregates.
Unknown evidence remains unknown. Marginal-alpha classification requires every
applicable hard-safety, evidence and execution gate to have passed. Original
preflight concentration placeholders cannot count as measured safety evidence.
No quote or provider request is made to complete a receipt.

After a Survivor step, its owned worker may enrich 5-minute, 15-minute, 1-hour,
6-hour and 24-hour rejection outcomes from verified persisted price bars and
immutable links. Each step exports at most 256 bars and scans at most 512 events;
checkpoints survive restart. Backlogged observed history is consumed before its
window is finalized. Excursions and last returns retain explicit observability;
unavailable references or observations never manufacture a return. Committed
Survivor fills and reconciled terminals supply outcomes through existing native
accounting acknowledgements. Enrichment has no provider, qualification, sizing,
reservation, order or economic-journal authority and can be disabled.

Tests: test_opportunity_telemetry and test_current_survivor_independence cover
signed gates, replay/conflicting duplicates, append-only integrity, outcomes,
exact accounting, interruption/restart, context capture and failure isolation.

Read-only Solana evidence facades may be shared by main and position workers, but each calling thread owns its own SQLite reader. The same configured evidence path, scope/finality/freshness checks and command identities remain authoritative. Closing a worker closes only its own reader and does not create a new handle. Meteora continuation explicitly closes its reader on that worker. This changes no durable schema, epoch, journal, reservation or strategy economics. FAST permanently covers all three runtime namespaces, the actual Meteora poll, and production continuation cleanup.

Queued maintenance commands expire before native arbiter entry when their owner wait exceeds the existing three-second lease. Refusal preserves ordinary FIFO and yields before a fresh attempt; it credits no service and does not renew debt deadlines. The native arbiter's lease, stale-observation, generation, completion and failure checks remain authoritative. This changes no schema, epoch, journal, reservation, source batching or strategy economics. OPERATIONAL retains the five original Run 377 persistence/drain regressions with the exact captured offline transaction fixture.
