# Read-only portfolio dashboard

## Review boundary

Canonical target: `cert/prospective-market-v1` at
`1c6da29d08bfbe42e39ea1c8068933aae6b15cdb`.
`certification/prospective_program.py:CANONICAL_BRANCH` identifies this target.
GitHub's default `main` is still `54712c4c6470cc4dc267888f934bd693aac030d0`;
it is not the current four-lane implementation. The dashboard does not promote
later repair/campaign branches. Refreshed open PRs and branch names showed no
competing portfolio dashboard implementation.

Implementation branch: `feat/read-only-portfolio-dashboard`.
No merge, deployment, market workflow, account activation, or portfolio inception
was performed. Neither Render account was inspected or used.

## Architecture and integration

The repository uses Python 3.12, SQLite native books, stdlib HTTP status serving,
and no frontend framework. This change adds no dependencies or database.

* `dashboard.model.Reader` reads bounded local files and creates a disposable,
  non-authoritative in-memory view. It does not open a canonical writer, import
  an engine/provider, fetch URLs, inspect environment values, or execute commands.
* `dashboard.api.Dashboard` exposes GET/HEAD responses and static assets. It mounts
  on the existing `ThreadingHTTPServer` handler in `meme_machine/__main__.py`.
  No engine or Store object is passed to it. Existing trading logic is unchanged.
* `python -m dashboard` is an optional **loopback-only local observer/preview**
  using the same stdlib server. It does not start the paper runtime. It is not a
  new required microservice or hosting configuration.
* Frontend: plain HTML/CSS/JavaScript and lightweight SVG sample charts. Fifteen
  second polling pauses for hidden tabs, focused form controls, and open details.
  Stale/error responses replace current-state claims. Source responses are
  allowlisted; raw dictionaries/configuration are never serialized into the UI.
* All API methods except GET/HEAD return 405. There are no trading, workflow,
  configuration, capital-change, or inception endpoints.

Existing server options are additive: `--dashboard-inception`,
`--dashboard-accounting`, and `--dashboard-telemetry`. Omitting them serves an
explicit uninitialized portfolio. The standalone observer also reads safe hashes
from `certification/sources.json`, labeled configured rather than executed.

The observer's exceptions and unavailable inputs cannot block canonical strategy
work: canonical execution never calls the read model, and the existing server's
request handlers run separately from the execution loop. The model writes nothing.
Recovery is a deterministic reread of the same immutable inception receipt and
complete persisted accounting export. There is no authoritative dashboard cache.

## What the current canonical data actually supports

The four-lane control plane persists `result.json`, with lane summaries produced
by `certification/report.py:summarize`. These are directly supported by the System
page through an explicit local `--dashboard-telemetry` path.

| Source | Dashboard use | Boundary |
| --- | --- | --- |
| Pump `result.json.lanes.pump.native_accounting`; native `meme_machine/paper_accounting.py` overlay | Native integer cash, basis, reservations, realized result and reconciliation | Native SOL book; not new-epoch USD performance |
| Pons `result.json.lanes.pons.cohort_accounting`; `pons_selective_capital.py` / `pons_selective_ledger.py` overlays | Native genesis, booked realized result, remaining basis, reservations | Native Robinhood quote units; partial-realization book retained |
| Meteora `result.json.lanes.meteora.native_accounting`; `dlmm_independent_accounting.py` overlay | Native genesis capital, realized lamports, outstanding accounting fields | Native SOL maker book; not a shared USD allocation |
| Ramses `result.json.lanes.ramses.native_accounting.by_quote_asset`; `ramses_strategy_ledger.py` overlay | Allowlisted per-quote-asset integer capital, committed funds and realized results | Quote sleeves remain separate; no invented exchange rates |
| Supervisor observed time, lane health, accounting reconciliation, progress age, provider request totals | Independent operational statuses and last telemetry time | A process heartbeat does not prove fresh market evidence |
| Runtime policy/source hashes and `certification/sources.json` | Safe exact hashes, with runtime/configured provenance distinguished | Never expose provider URLs, credentials, or environment values |

The existing legacy `meme_machine/store.py` seeds the equivalent of $500 into SOL
using one inception conversion. Its own status explicitly leaves current USD value
unavailable. It is neither a new four-lane USD epoch nor authority to reuse past
trades. The profitability acceptance layer calculates weighted experimental
returns across native books; it is not a shared USD cash ledger. The dashboard
does not reuse those floats, pretend that each lane owns $125, or treat supervisor
pending-reservation counts as entered positions.

No current common USD inception, complete new-epoch lifecycle export, canonical
current USD marks, or consolidated cash account was found. Consequently the real
portfolio remains **NOT_INITIALIZED**. A configured but missing/corrupt accounting
file remains unavailable/fail-closed, never a synthetic fallback.

## Explicit $500 inception and accounting export contract

The support below is an input contract for a separately established canonical
account, not a replacement ledger or a new accounting authority. The dashboard
does not create either input. `inception_receipt(epoch_id, inception_at, event_id)`
is a pure validator/constructor: it requires the real identity/time and writes
nothing. No command or endpoint initializes a portfolio.

The immutable receipt has exactly these fields:

```json
{
  "schema": "meme-machine-portfolio-inception-v1",
  "epoch_id": "EXPLICIT_CANONICAL_EPOCH_ID",
  "inception_at": "EXPLICIT_CANONICAL_UTC_TIMESTAMP",
  "canonical_event_id": "EXPLICIT_CANONICAL_INCEPTION_EVENT",
  "starting_capital": "500.00",
  "currency": "USD",
  "paper_only": true
}
```

The persisted accounting export is `meme-machine-portfolio-export-v1` and contains:

| Field | Required semantics |
| --- | --- |
| `mode` | `canonical` for real account reads; `fixture` only in explicit fixture mode |
| `epoch_id`, `inception_sha256` | Exact receipt identity; SHA256 of sorted compact JSON (`canonical(receipt)`) |
| `sequence` | Nonnegative integer snapshot sequence; regressions/equivocation rejected within a reader session |
| `as_of`, `valid_until` | UTC source accounting time and source-established validity deadline; UI never extends it |
| `complete_lifecycle_coverage` | Must be true; export must cover every entered lifecycle since inception |
| `balances` | Exact string USD values or explicit missing values for `equity`, `available_cash`, `reserved_cash`, `deployed_capital`, `realized_pnl`, `fees`, `shared_costs` |
| `positions` | One canonical summary per entered lifecycle, including every terminal settlement |
| `history` | Actual epoch-bound `series`, UTC `at`, and exact USD `value` or null gap; portfolio values are equity, lane values cumulative net P&L |
| `history_complete` | True only for complete canonical sample coverage; gaps preclude drawdown claims |
| Identity fields | Optional `source_sha`, `policy_hash`, `config_hash`, `source_diff_sha256`; validated hexadecimal hashes |

All money must be decimal strings (up to 24 fractional digits) or integers. Binary
floating-point currency is rejected. Calculations use an 80-digit Decimal context;
presentation uses exact decimal-string rounding, ties to even. Timestamps must
include UTC offsets. IDs and displayable lifecycle labels are restricted strings.
Unknown keys are ignored and never disclosed.

Each position requires `epoch_id`, globally unique `id`, `lane`, `asset`,
`exposure_entered: true`, `state: OPEN|SETTLED`, `entered_at`, `remaining_basis`,
and cumulative `realized_pnl` (basis/result may be null when unavailable in USD). Known lifecycle counts remain visible when financial values are missing. SETTLED requires `settled_at` and zero remaining
basis; OPEN requires positive remaining basis when known and no terminal timestamp.
Optional exact monetary fields: `capital`, `entry_value`, `exit_value`, `fees`,
`gross_result`. When both gross and fees exist, gross minus fees must equal net.
Fees are attributable realized costs; the current mark is already net of the
remaining executable exit costs, so those costs must not also be subtracted again.

An open mark is either an explicit unavailable state, or:

```json
{
  "state": "CURRENT",
  "net_liquidation_value": "25.90",
  "as_of": "SOURCE_UTC_TIME",
  "valid_until": "SOURCE_ESTABLISHED_UTC_EXPIRY"
}
```

The source must retain existing finality/freshness requirements when establishing
this mark. A current marker in a JSON file alone is not proof of market evidence.
The dashboard never obtains marks, performs native-to-USD conversion, or imports
strategy decision logic. Unsupported native-to-USD valuation remains unavailable.

Optional lifecycle events are actual `{stage, at}` records. Supported stages are
qualification, authorization, paper_entry, monitoring, partial_realization,
rebalance, runner, exit, settlement. Optional lane fields: harvest/runner state,
remaining runner exposure, range identity, in-range flag, LP state, rebalance state
and count. Missing stages are not synthesized.

Old-epoch positions/history are explicitly excluded and counted; same-epoch
positions before inception fail closed. Duplicate lifecycles, missing exposure,
invalid settlements, changed inception, future snapshots, negative basis/costs,
and unsupported external adjustments fail closed. A running reader also rejects
disappearing previously seen lifecycles or revisions of terminal settlement facts.
Canonical durable history must remain append-only across producer restarts; the
observer cannot authenticate a malicious rewrite of both source files and hashes.

## Frozen metrics and reconciliation

* Trades taken: unique entered position lifecycles. Fills, rebalances, partial
  realizations and failed entry attempts are not additional trades.
* Open: entered, positive remaining exposure, no terminal settlement. A harvested
  runner remains open. Completed: canonical terminal settlements only.
* Wins/losses/breakevens: completed lifecycle net realized result, at exact source
  monetary precision. Win rate is wins/(wins+losses); zero denominator unavailable.
* Realized: cumulative canonical net realized amounts, including partial results.
  Unrealized: sum of valid net liquidation values less remaining basis. Missing,
  stale or failed marks do not become zero. Net and current equity are unavailable
  if required current valuations are unavailable.
* Portfolio return: net P&L / $500. Lane contribution: lane net P&L / $500. No
  standalone lane return is invented. Shared costs are visible outside lanes.
* Average result/largest win/loss/holding duration use completed lifecycles only.
  Sample counts are shown. Max portfolio drawdown is calculated from a complete
  canonical observed equity sample series, never just start/current balances;
  it is not an intraperiod or intratrade drawdown claim. Lane drawdown lacks an
  authoritative lane-equity denominator and remains unavailable.
* Daily trade counts use UTC entry and settlement dates. Completed net outcomes
  are assigned to settlement day, explicitly excluding open partial realizations
  and shared costs. This is not daily equity change. Missing daily boundaries and
  zero-activity coverage are not fabricated.

The read model independently exposes five checks:

1. Sum lane realized results minus shared costs equals portfolio realized P&L.
2. Sum open remaining basis equals deployed capital.
3. Cash + reserved + deployed basis equals $500 + realized P&L.
4. Equity equals $500 + realized + valid unrealized P&L.
5. Position fees + shared costs equals total fees/costs.

No external-adjustment balancing item is supported by the current common-account
contract. Inconsistencies remain visible as FAIL_CLOSED with failed checks.
The fixture reconciles to $512.34 = $500 + $8.34 realized + $4 unrealized;
cash $403.34 + reserved $10 + basis $95 = $508.34. Attributable fees $1 plus shared
costs $0.12 are already accounted for, not subtracted twice.

## Surfaces, query bounds and security

UI: `/dashboard` with Overview, Lanes, lane detail, Positions, Trades, Analytics,
System, and a canonical-position detail dialog. iPhone layout uses compact bottom
navigation and position cards; primary financial information does not require
horizontal scrolling. The attached mockup informs colors, hierarchy and density.

GET/HEAD APIs:

* `/api/dashboard/portfolio`
* `/api/dashboard/equity?series=portfolio|pump|pons|ramses|meteora&period=ALL&limit=240`
* `/api/dashboard/lanes`, `/api/dashboard/lanes/{lane}`
* `/api/dashboard/positions`, `/api/dashboard/positions/{id}`
* `/api/dashboard/trades?lane=pump&outcome=winner&q=asset&strategy=identity&from=UTC&to=UTC&limit=25&offset=0`
* `/api/dashboard/analytics`, `/api/dashboard/system`

Positions/trades return at most 100 records, offset at most 5000. Charts return at
most 500 actual samples; requested periods are enabled only when history covers
them. A bounded recent slice explicitly reports truncation. Sample dots avoid
false interpolation across unsampled intervals. Native responses never contain
the raw provider configuration.

V1 input bounds: 4 MiB per file, 5000 lifecycle summaries, 2000 history samples,
100 lifecycle stages per position. Over-capacity inputs fail closed, never
truncate canonical accounting. A producer reaching these bounds needs a separately
reviewed indexed/read-model extension; silently dropping historical lifecycles is
not supported. Aggregation is cached across a page's requests; source file changes
and exact validity deadlines invalidate the cache. API filtering is bounded in
memory. No full canonical ledger scans, indexes, migrations or writes occur.

There is no existing authentication product to reuse. Both servers bind loopback.
Before any deployment, enforce authenticated owner-only access at a trusted reverse
proxy, TLS, bounded request concurrency/rate/body limits, and read-only file mounts.
Protect **both static pages and every API route**. Do not expose the stdlib preview
directly to the internet. The code sets no-store, CSP (same-origin assets/connect),
no-referrer, nosniff and frame-denial headers. This task adds no account/auth system.

## Deterministic preview and checks

From the repository, create a fresh disposable directory (never canonical paths):

```sh
python -m dashboard.fixtures /tmp/mm-dashboard-fixture
python -m dashboard --fixture-dir /tmp/mm-dashboard-fixture --port 8090
```

Open loopback `/dashboard`. Every screen identifies DEVELOPMENT FIXTURE, synthetic
balances/trades, and a fixed clock. Canonical mode refuses fixture-mode exports;
fixture arguments cannot be combined with canonical input paths. Fixture creation
uses exclusive file creation and refuses to overwrite existing files.

```sh
python -m unittest dashboard.tests.test_dashboard -v
node --check dashboard/static/app.js
node dashboard/tests/frontend.mjs
python -m unittest discover -v
python -m tests.resource_check
```

Frontend tests use Node's built-in VM and the real loopback Python API: no new
browser framework or packages. They exercise all ten routes, fixture/uninitialized
display, exact presentation rounding, details, method rejection, and existing
responsive rules. They can emit inert static HTML review snapshots via an optional
output-directory argument. These are not browser screenshots.

The provided cloud browser rejects loopback HTTP previews; it also explicitly
blocks local-file previews. No alternate browser/policy workaround was attempted
after that block. Desktop and iPhone browser geometry, interaction accessibility,
and genuine screenshots remain a manual review gate. No browser-rendered QA claim
is made from DOM-string tests.

## Remaining activation/deployment boundary

**The real portfolio is NOT_INITIALIZED.** The one portfolio activation operation
still required is separately establishing a genuine canonical shared $500 USD epoch
with its immutable receipt and an authoritative, complete epoch-bound USD export,
then attaching the protected observer to those persisted inputs. Current native
lane books do not supply that consolidated USD export; do not activate the UI by
renaming research snapshots or manually manufacturing balances. If the canonical
runtime cannot supply USD marks/fields, those fields must remain unavailable.

That activation may require separately authorized canonical accounting integration;
this dashboard contract does not grant it or alter construction authority. Review
the native/FX/rent accounting semantics before producing the export. Also finish
desktop/iPhone browser review and deployment-time access protection. None of these
steps, either Render account, or any market certification/run is authorized here.

No canonical accounting correctness repair was made. Strategy economics, scope,
provider limits, evidence/finality/freshness rules, position lifecycle, construction
authority, canonical history, and paper-only authority remain unchanged.

## Final verification evidence

See `docs/dashboard-verification.json` for exact source hashes and measured results.
Final code passed 457 discovered tests: 449 passed, 8 existing native-worktree tests
skipped because their prepared source trees were not present. This includes all
54 dashboard tests. The fixture HTTP/renderer checks passed all 10 UI routes plus
uninitialized display and exact formatting. JavaScript syntax, Python compilation,
and diff whitespace checks passed. Resource check: 2000 frames, 240000 submitted
events, 18844 KiB peak RSS, 1257472-byte DB, 642752-byte WAL, zero real provider calls.
No full four-lane certification or browser geometry verification is claimed.
