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
