# Render staging deployment

This release surface is the public, read-only portfolio dashboard.

## Authority boundary

The genuine shared portfolio remains **NOT_INITIALIZED**.

The staging web service must not set portfolio activation bindings:
`MM_PORTFOLIO_ACCOUNTING_DB`, `MM_PORTFOLIO_EPOCH_ID`,
`MM_PORTFOLIO_INCEPTION_SHA256`, `MM_PORTFOLIO_INCEPTION_RECEIPT`, or
`MM_PORTFOLIO_EXPORT`.

It does not need market/provider credentials. The dashboard reader performs no
provider acquisition and exposes no market-workflow or inception endpoint.

## Render service

Build:

```sh
pip install --disable-pip-version-check -r requirements.txt
```

Start:

```sh
python -m dashboard --host 0.0.0.0
```

Render supplies `PORT`. Auto-deploy remains off.

The dashboard is intentionally public and has no login requirement. Render
terminates TLS. The service retains no-store, CSP, no-referrer, nosniff, and
frame-denial headers. Mutation methods remain rejected. Request concurrency and
per-client request rate remain bounded.

`/` redirects to `/dashboard`. `/healthz` returns only
`{"status":"ok"}`.

## Storage

Do not attach a persistent disk to this uninitialized staging deployment. A later
portfolio-activation design must separately review durable storage and process
topology.

## Staging verification

Verify:
1. `/` redirects to `/dashboard`.
2. `/dashboard` renders without login.
3. `/api/dashboard/portfolio` reports `NOT_INITIALIZED`.
4. POST/PUT/PATCH/DELETE remain rejected.
5. No provider, market campaign, or portfolio-inception activity occurs.
6. iPhone and desktop geometry are reviewed before production activation.
