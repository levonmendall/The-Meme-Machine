# Existing dashboard snapshot connection

The existing Render service runs `python -m dashboard --host 0.0.0.0`.
Its owner uses HTTP Basic authentication over HTTPS. The username and random
password live in protected Render environment configuration; a root-owned 0600
`/etc/meme-machine/dashboard-owner.env` is the owner's local recovery locator.
They are never committed or placed in a URL. `/healthz` exposes only web-server
liveness. All pages, assets and reporting APIs require owner authentication.
The ingestion credential cannot read the dashboard, and the owner credential
cannot ingest data. Owner requests cannot mutate any reporting endpoint.

Required Render variables:

| Variable | Purpose |
| --- | --- |
| `MM_DASHBOARD_OWNER_USER` | Single owner username |
| `MM_DASHBOARD_OWNER_PASSWORD` | Random owner password |
| `MM_DASHBOARD_INGEST_TOKEN` | Separate random publisher bearer token |
| `MM_DASHBOARD_SNAPSHOT_PATH` | Local replica, e.g. `/tmp/meme-machine-dashboard/latest.json` |
| `MM_DASHBOARD_EPOCH` | Preserved PAPER epoch |
| `MM_DASHBOARD_CANDIDATE` | Integrated acceptance candidate commit |

Install only the `dashboard/` package in `/opt/meme-machine-dashboard` and the two
`meme-machine-dashboard-publisher` units. Do not change the trading checkout or
install runtime requirements for the publisher. It uses the existing deployed
Python and validated read-only portfolio replay/reporting functions through
`PYTHONPATH=/opt/meme-machine`. Never construct an accounting writer, configure
schemas, checkpoint, acquire the economic lock, call a market provider, or
modify the canonical publication timestamp or valuation deadline.

The root-owned 0600 `/etc/meme-machine/dashboard-publisher.env` contains:
`MM_DASHBOARD_PUSH_URL`, `MM_DASHBOARD_INGEST_TOKEN`, `MM_DASHBOARD_STATE_ROOT`,
`MM_DASHBOARD_RUNTIME`, `MM_DASHBOARD_CANDIDATE`, and
`MM_DASHBOARD_PUBLISHER_COMMIT`. The URL is the existing HTTPS dashboard plus
`/api/dashboard/snapshot`. No provider credentials enter the publisher environment.
Its systemd sandbox makes canonical state and reports read-only and hides provider
environment files. Low scheduling priority, bounded CPU/memory and an 18-second
oneshot timeout keep reporting independent of position work.

Enable only `meme-machine-dashboard-publisher.timer`. It schedules a local report
and one HTTPS POST every 20 seconds, without redirects or inbound Droplet ports.
Failures are recorded in its own journal; the timer retries on its next tick.
There is no PAPER unit dependency or control action.

Render stores one bounded, atomically replaced snapshot on its existing ephemeral
filesystem. A restart shows UNAVAILABLE until the next push. An aged snapshot is
STALE after 60 seconds; observer/monitor observations age independently. Read time,
canonical publication time and market evidence timestamps remain distinct.
Expired marks stay unavailable; no new prices or equity history samples are invented.
Acceptance receipts are matched to candidate commit and preserved epoch. Older
attempts remain visible as historical results. A missing current-candidate attempt
is NOT_STARTED; PASS requires a genuine complete durable receipt and result.

Focused offline validation:

```sh
python -m operational.tests OPERATIONAL --modules dashboard.tests.test_server_security
node dashboard/tests/frontend.mjs
systemd-analyze verify deployment/meme-machine-dashboard-publisher.service deployment/meme-machine-dashboard-publisher.timer
```

After deployment, verify anonymous 401 responses, owner GET access, authenticated
ingestion, actual receipt status and advancing timestamps. Compare trading commit,
PAPER process/restart state, protected configuration and monetary file digests to
the pre-installation record. Do not start PAPER or acceptance phases for this task.
