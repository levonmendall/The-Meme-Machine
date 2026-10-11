# Meme Machine PAPER

The operational candidate runs only Pump Current/Survivor and Pons Current/Survivor
under one supervisor. Meteora and Ramses are PAUSED indefinitely, with no new
market work or capital admission; reactivation needs an explicit owner decision.
The intended new launch is the separate $1,000 shared PAPER epoch prepared in
[the release handoff](operational/pump-first-release/HANDOFF.md), using shared
realized-equity sizing, $50 initial targets, eligible $25 additions, 7.5%
cumulative investment and 10% marked admission references. Numeric policy,
epoch initialization, deployment and PAPER activation still need explicit approval.
Historical four-family accounting remains in the preserved $500 portfolio. Its existing epoch,
capital history, positions, reservations and pending deliveries must survive
every deployment. Missing storage is a startup failure, never permission to
create a replacement portfolio.

Before any process starts, canonical and native paused-family obligations must
be clear. Unverified state or exposure blocks startup with exact identities;
positions and pending deliveries are never deleted to enforce a pause.
The deployed historical family sleeves remain unchanged. The new shared-capital
authority must be initialized once in an exclusive new root after approval;
there is no transfer of the old balance or migration of historical accounting.
Startup never creates or reseeds an epoch. Model B is the sole
startup candidate; its existing concurrent-provider certification blocker remains.
This candidate has not been deployed or accepted against real providers.

Entrypoint: `python -m meme_machine.operational run`. CPython 3.12.14;
`pip install -r requirements.txt`. SQLite 3.45.1 and 3.53.1 have both passed the operational suite.

Required environment: `MM_STATE_ROOT`, `MM_MODE=PAPER`, and the existing
Solana and Robinhood read RPC configuration (`SOLANA_READ_RPC_URL` and
`ROBINHOOD_READ_RPC_URL`, with their supported `MM_` aliases). State is SQLite and bounded snapshots below
`MM_STATE_ROOT`, bound to the verified existing persistent volume at deployment.
The historical `/etc/meme-machine/paper.env` remains preserved. New deployment
preparation uses `/etc/meme-machine/paper.shared-1000.env` and its own
`storage.shared-1000.json`; these files are not installed or activated.
Robinhood valuation uses its existing RPC for the verified Chainlink USDG/USD
feed and authenticated native→USDG quotes. Invalid/stale valuation reports
`VALUATION_UNAVAILABLE` and prevents economic work requiring that value.

After volume/epoch protection, durable observation, verified off-host recovery
and owner-accessible monitoring are complete, start with
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

Acceptance runs under `meme-machine-acceptance@CAPACITY.service`, then controlled
RECOVERY and the full 36-hour AUTONOMY unit. Freeze one pushed/deployed candidate
and preserve its runtime configuration through all phases. Follow
[ACCEPTANCE.md](operational/ACCEPTANCE.md) and
[STATE_RECOVERY.md](operational/STATE_RECOVERY.md); preparation or a running job
does not establish acceptance PASS.


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

Startup refuses to create an inception when the canonical portfolio is missing or unbound and existing lane journals, native genesis, inception markers or portfolio WAL files remain. These markers only prevent reseeding; they cannot supply replacement capital or recover the portfolio. Restoring the preserved canonical database resumes its original epoch and positions. OPERATIONAL covers both a missing database and an empty replacement with byte-preserved native journals.
