# Render staging deployment

This release surface is for the protected read-only portfolio dashboard only.

## Authority boundary

The genuine shared portfolio remains **NOT_INITIALIZED**.

The staging web service must not set any of these portfolio activation bindings:

- `MM_PORTFOLIO_ACCOUNTING_DB`
- `MM_PORTFOLIO_EPOCH_ID`
- `MM_PORTFOLIO_INCEPTION_SHA256`
- `MM_PORTFOLIO_INCEPTION_RECEIPT`
- `MM_PORTFOLIO_EXPORT`

It also does not need market/provider credentials. The dashboard reader performs no
provider acquisition and has no market-workflow or inception endpoint.

## Render service

Use one Python web service from the reviewed release branch.

Build command:

```sh
pip install --disable-pip-version-check -r requirements.txt
```

Start command:

```sh
python -m dashboard --host 0.0.0.0
```

Render supplies `PORT`; the server reads it automatically.

Set auto-deploy **off** for initial staging. Deploy only reviewed release commits.

Required service environment:

- `MM_DASHBOARD_USERNAME`
- `MM_DASHBOARD_PASSWORD` (20+ characters)

Optional bounded controls:

- `MM_DASHBOARD_MAX_CONCURRENCY` (default 16, maximum 64)
- `MM_DASHBOARD_RATE_LIMIT_PER_MINUTE` (default 120, maximum 600)

A non-loopback bind fails closed if owner credentials are absent or incomplete.

## Network surface

`/healthz` is intentionally unauthenticated and returns only:

```json
{"status":"ok"}
```

All `/dashboard`, `/dashboard/*`, and `/api/dashboard/*` requests require HTTP
Basic authentication. Render terminates public TLS. The service additionally
retains no-store, CSP, no-referrer, nosniff, and frame-denial headers.

All mutation methods remain rejected. The server does not consume request bodies,
uses a bounded request queue, caps active request threads, and applies a bounded
per-client request rate.

## Storage

Do **not** attach a persistent disk for this uninitialized staging deployment.
There is no canonical portfolio state to persist yet.

A later portfolio-activation design must separately review durable storage and
process topology because Render persistent disks are single-service/single-instance
resources. That later review must not reuse historical native bankroll state.

## Staging verification

Verify:

1. `/healthz` returns 200 without credentials.
2. `/dashboard` returns 401 without credentials.
3. `/dashboard` renders with the owner credentials.
4. `/api/dashboard/portfolio` reports `NOT_INITIALIZED`.
5. POST/PUT/PATCH/DELETE remain rejected.
6. No provider, market campaign, or portfolio-inception activity occurs.
7. iPhone and desktop geometry are reviewed before production activation.
