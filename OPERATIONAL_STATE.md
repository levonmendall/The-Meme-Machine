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
