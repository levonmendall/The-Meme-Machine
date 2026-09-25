# Run 35905479952: evidence and repairs

The cancelled smoke is excluded from every clean profitability cohort. Its exact
runtime was `e4c5c0a931bab9d6fab305a3a3298b92784946bc`, native run
`8d7fa8f8-2d9c-4f3f-af52-cda9cb0fa065`. Original GitHub artifact `10772055699`
was downloaded and SHA-256 verified:
`c892bd00d9c83863173d3c87330c75946c3274bfc8bd0b75271415fbc5d07ab5`.

## Root causes and evidence

* Ramses raised `ramses_provider_program_budget_exhausted` in the economic log
  census. The pinned 30-minute window covered blocks 70719011–70736895 (17,885
  blocks). Ten-block chunks required 1,789 logical reads before retries, exceeding
  the unchanged 7 × 200 request budget. Captured telemetry contains 1,364 getLogs
  members: 1,220 successful unique pages and 144 429 members; 21 HTTP 429 responses
  across 252 physical transports. The subsequent transport-deferral patch alone
  could not fix this arithmetic.
* Fresh transports did not prove census progress. The prior liveness change could
  conceal a stalled stage while repeated provider errors continued.
* Cancellation was a separate cross-run event. The `[cancel-runs]` push at
  `44869bbcb1ccb3bb6a9001443d36b77b3eafd14f` created run `35907238815` at
  19:07:51 UTC. The workflow shares a concurrency group and explicitly enables
  cancellation for that exact message. Ramses had already exited at about 19:07:44;
  Pump/Pons received interruption around 19:08:51 and Actions reported cancellation
  at 19:09:06. This supports concurrency cancellation, not a claim that Ramses
  automatically cancelled the workflow. No human cancellation actor is inferred.
* Meteora's public pool list omitted five-minute fee/volume keys. Missing values
  became zero and produced 714 `public_fee_context_zero` rejections; its only Solana
  RPC was chain authentication. A bounded live public GET confirmed the response
  shape. This was missing screening evidence, not demonstrated lack of opportunity.
* Meteora wrote 1,441 full checkpoints totaling 414,087,411 bytes of repeated
  growing rejection history. Its telemetry database reached about 415 MB in ten
  minutes, with another large snapshot copy in the artifact.
* Declared-overlay integrity checked index/worktree agreement without comparing
  against the frozen diff hash. Git's abbreviated blob IDs also varied with object
  database size, making the old diff representation unsuitable as an exact pin.

## Repair boundaries

Ramses economic census now uses independently bounded 1,000-block queries with the
same addresses, topics, complete window and provider. Transaction replay retains
its original ten-block bound. Read-only hosted probe `35909625490` authenticated
the official public endpoint and tested all 287 addresses at 10, 100 and 1,000
blocks. All passed; the 1,000-block response contained one log. Probe artifact
`10772726101` digest:
`b1b769e6f47559f2a5ad094b422c8c2858c69f988b40580e88e65b663982ca9f`.
The original window now needs 18 logical queries. Provider rates, budgets, response
row caps and strategy economics are unchanged. Completed page checkpoints measure
actual progress; exhausted transport/local budgets remain explicit censored scans.
At least one completed census is required for smoke/hourly engineering readiness.

Meteora uses its existing completed five-minute history reader only when the list
omits that context. Measured zero still rejects without another history read.
History failure is incomplete evidence; incomplete buckets cannot qualify. Frozen
on-chain liquidity, fee, cost and entry gates remain authoritative. Public HTTP
responses are archived once. Growing observation rows are preserved once in the
append-only journal, while repeat checkpoints contain counts and locations. The
original complete native report remains intact.

Terminal shutdown audits now reopen each existing native book read-only, replay its
journal and preserve exposure/reserves. They never construct missing books, create
settlements or release reserves. All four cancelled books were checked: Pump
5,110,384,300 lamports, Pons 1,000,000,000,000,000,000 native quote units, Meteora
1,000,000,000 lamports, each with zero exposure; Ramses explicitly awaited its first
qualified pinned funding screen and had no funded book. Synthetic reserve fixtures
also prove that 400 native units and one unresolved position survive this audit;
unobserved Pons native commits correctly fail reconciliation.

Source hashing now uses binary full-index diffs with rename/external diff/textconv
behavior disabled; both staged and unstaged mutations are checked against exact
manifest pins. Pump/Pons runtime content is unchanged; their hash representation
changed. RPC records include secret-safe endpoint fingerprints and provider roles;
estimated Alchemy compute counts only actual Alchemy transports.

## Durable collection

The explicit 2026-09-23 instruction authorizes this frozen paper certification
program before economic acceptance; it does not authorize production promotion.
The new cohort excludes every predecessor observation. Exact full certification is
reused only after matching run SHA, final gate artifact digest, source manifest and
all prepared overlay hashes. Every block refreshes provider/chain checks.

State transitions are Git commits on a separate cohort state branch. Optimistic
non-force updates retry only detected competing state commits. Dispatch intent is
persisted first; ambiguous requests are not retried. Continuation amendments merge
into the original statistical block, cannot precede its artifact-review gate, and
never add a second sample. Engineering/evidence failure is sticky. Losing and
zero-trade healthy blocks remain in the cohort. No strategy or economic threshold
is changed by the scheduler. Full artifacts are retained for 90 days; state history
and run references persist in Git.

## Successor collection controls

Full non-market certificate `35914189762` passed for `f7e053a7`, then live smoke
`35915320840` showed all four processes responsive. Ramses completed its 18-page
log census and Meteora began authenticated evidence acquisition. That early smoke
also exposed that the shared pressure summary still estimated public RPC calls as
Alchemy compute despite the corrected per-worker ledger. The successor attributes
shared transport methods through normalized endpoint fingerprints; unknown endpoint
identity yields an unknown total rather than an invented Alchemy charge.

A deterministic boundary fixture additionally proved lane sample completion could
stop collection with only eight joint nonzero portfolio observations, below the
existing twelve-observation correlation requirement. The successor continues until
both lane and portfolio sample requirements are met, or the predeclared operational
limit is reached. Economic pass/fail does not select the stopping point. These
control changes require a new cohort and a full exact-SHA recertification. The owned
predecessor is retired only after its flat smoke evidence is preserved, or an already
started campaign has drained; no active position is interrupted to accelerate testing.

## Follow-up state hydration defect in 35915320840

The census fix completed all 18 public log pages, then the first and second Ramses
scans deferred with local budget exhaustion during full state hydration. Each
frozen 201-bin prestate requires six header views plus two views per bin: 408
logical reads per pool. Four eligible quiet USDG pools therefore require 1,632
state reads before factory, receipt and cost metadata; the old shared budget held
only 1,400. This is an impossible implementation bound, not a lack of opportunity.
The live checkpoint recorded zero completed screens, two infrastructure-censored
scans, 2,768 eth_call members and zero exposure.

The repair leaves the metadata and public census budgets at seven 200-call
sessions each and creates a separate state reader sized to the exact candidate
count. It allows one chain authentication plus 408 reads per pool, conservatively
allowing batch fragmentation within each 200-call session. Eight pools require
3,265 planned reads and at most 17 sessions (3,400-call absolute cap). Existing
endpoint, batch size eight, 0.8-second local pause, shared provider pacing, two
rate retries, cooldown, cohort capacity, bin radius and strategy policy remain
unchanged. This corrects the unintended budget defect under the user's explicit
provider-budget exception; it does not accelerate the existing request rate.

Regression tests reproduce the old four-pool failure, then hydrate every bin of
eight states with exactly 3,265 calls, pinned to the same authenticated frontier.
Per-pool completion and the bounded state budget are durable progress evidence.
The intermediate successor workflow 35916280138 was cancelled before certification
by pause commit 48d02412d3ce160ef8e3614cf4d1e983f397e316. No v3 market observation
was launched; all final repairs must receive one full certificate on their exact SHA.

## Terminal audit path repair

The preserved f7 smoke artifact `10776256813` is 183,437,471 bytes with SHA-256
`aa4347cf199363d9724f3eda15213f264c857d9a9f78a52cd883d0e488ec1ef0`.
It completed all workers in 1,604.835 seconds, with no settlements or exposure.
Its terminal audit marked Meteora unreconciled because the native policy loader
looked for `SOLANA_DLMM_INDEPENDENT_V1.json` relative to the integration directory.
The book was intact. The stopped-worker audit now resolves the policy relative to
its pinned native source module, preserving every native validation rule. A test
executes the audit from the integration directory and retains unresolved reserves.

Retirement workflow 35918440394 correctly refused to trust that failed original
audit; no full certificate or successor market run started. The repaired retirement
step independently replays all four archived native books using prepared pinned
sources, records its proof separately, and retains the original failed engineering
result. All four replayed with zero exposure. The original failure remains excluded
from every clean block; no settlement, reserve release or history rewrite occurred.

## Pons public-log metadata mismatch

All 623 `raw_event_identity_disagreement` rows in 35915320840 were reconstructed
from archived provider responses. For every row the official public getLogs result
and Alchemy receipt log differed only in optional `blockTimestamp` metadata: the
public endpoint supplied zero. Transaction hash, block hash/number, transaction/log
indices, address, topics, data and removed status agreed exactly. The old full-object
comparison rejected these authentic logs.

The shared ABI helper now omits only that optional provider annotation during
receipt-log equality; every other field, including unknown extensions, must still
match. Both strict Pons and Ramses readers use the helper. The authenticated matching
header remains the sole event-time authority, with the original future-time and
confirmation checks. Original raw responses are retained unchanged. All 623 cases
replayed successfully without additional RPC. These are historical authentication
regressions, not new natural trades or economic observations.

The owned full certification 35919189403 was cancelled during non-market checks
by pause commit 1004f33cfaa2c15ed8e070a5333885f66777a6af after this defect was
discovered. Its successful retirement proof remains valid historical evidence;
certification must restart once on the final source set before any v3 observation.
