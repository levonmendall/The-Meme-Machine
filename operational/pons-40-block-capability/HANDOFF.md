# Pons forty-block provider capability — one completed test

**UNSUPPORTED_40_BLOCK_RANGE.** The configured authenticated Robinhood Alchemy
provider explicitly rejected the exact forty-block factory query. Four ten-block
queries over the same interval returned one independently authenticated
graduation. Retain the safe ten-block boundary and prefer prospective seven-day
accumulation. The one comparison authorization is consumed. No further RPC,
historical scan, account upgrade, deployment or service restart followed.

The production blocker remains
`combined_position_and_candidate_provider_latency_not_certified`.
This result establishes neither CAPACITY readiness, operational autonomy nor
complete seven-day historical coverage.

## A. Provider capability

- Classification: `UNSUPPORTED_40_BLOCK_RANGE`.
- Stop reason: `explicit_40_block_range_rejection`.
- Date: 2026-10-08; executor preflight at 04:49:09 UTC.
- Provider host: `robinhood-mainnet.g.alchemy.com`; existing configured credential.
- Provider fingerprint: `356037d82405f7b99eee047ef945ebe35e5a4cd68024880b4cdd9c276119b4fb`.
- Chain ID: **4663**, authenticated within the aggregate budget.
- Genesis: `0xaad15f3d702aaea00caf3e9bb56395efe9127bc3b31b24921abf1eee3409305c`.
- Exact tested interval: **56,882,701–56,882,740**, inclusive, forty blocks.
- Factory: `0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e`.
- `TokenLaunched` topic: `0x8d4aad4953d0ca700d468f3753aa14432d1b35b43ec6409f051fb6aa43a89607`.
- `PoolGraduated` topic: `0x0a44ef75df69c534f43cd6c1aa3ef8983065fe5fe79ef9e79f6494e6f258c259`.

Both methods used exactly the same address and OR-topic filter. Historical
factory bytecode at the first block matched the existing compiled deployment
pin: runtime SHA-256
`226a042e6d68a69a6038d4fda211925b03eb5299399434b87a7877f79f6e3848`.
No alternative authority or endpoint was used.

The [captured rejection](responses/response-07.json) is HTTP **400**, RPC code
**-32600**, and explicitly states:

> Under the Free tier plan, you can make eth_getLogs requests with up to a 10 block range.

The provider's suggested smaller interval and upgrade text were not acted on.
This is an explicit tested account/method range restriction, not an empty or
inconclusive sample and not a claim about every Robinhood provider account.

## B. Request comparison and canonical evidence

| Query | First | Last | Returned factory events |
|---|---:|---:|---:|
| Baseline 1 | 56,882,701 | 56,882,710 | 0 |
| Baseline 2 | 56,882,711 | 56,882,720 | 1 |
| Baseline 3 | 56,882,721 | 56,882,730 | 0 |
| Baseline 4 | 56,882,731 | 56,882,740 | 0 |
| Candidate | 56,882,701 | 56,882,740 | unavailable: explicit range rejection |

The four baseline queries are independent JSON-RPC elements with distinct IDs,
carried in one original bounded HTTP batch. Its response is 845 bytes. The one
candidate element uses one HTTP batch and returns a 273-byte error envelope.
Batching does not erase logical usage or provide an automatic fallback.

The sole graduation is the prescribed reference transaction
`0x1d49a28a0e27ecdd952094c4aaa9de2105253a2d62924ec36e761c13e43493c9`.
Its block is **56,882,711**, transaction index **9**, native log index **58**
(`0x3a`), block hash
`0x8aa57ccecd330af14e6a3e5947efa64c255e48c87fa172de377e795881229be7`.
Its fresh canonical header and successful native receipt establish exact
event/header/receipt membership and ABI decoding. This evidence was acquired
before attempting the larger query, rather than relying on the old fixture.

Baseline full-row digest:
`e56e341f5aa7bbb6a7b68c286bce99d78fcd413cb65515ab30d44fe0920507ea`.
The ordered identity and witness digests are in [RESULT.json](RESULT.json);
[responses](responses/) retain the complete, secret-screened provider envelopes.
The predecessor, first and ending block identities were authenticated before
comparison. The first block's parent equals the predecessor hash.

There is **no forty-block event array, equality/order proof, successful support
receipt or post-comparison boundary recheck**. The explicit rejection triggered
immediate shutdown. Candidate event count is unavailable, not zero. No interval
or historical seed was marked complete, and historical widening remains disabled.

## C. Actual resource consumption

| Resource | Actual | Authorized maximum |
|---|---:|---:|
| Provider execution, including setup, waits and worker shutdown | 3.242420 s | 45 s |
| Physical HTTP attempts, including the failed candidate | 7 | 32 |
| Aggregate logical demand, including one chain-ID cache hit | 14 | 64 |
| Dispatched logical elements | 13 | 64 |
| Diagnostic CU, 100 per dispatched element | 1,300 | 6,400 |
| Largest individual response | 49,986 B | 2,000,000 B |
| Total attempted JSON request payload | 2,455 B | measured; no separate owner cap |
| Total response payload read, including the rejection | 77,535 B | each response bounded |
| Observed temporary-storage peak | 647,813 B | 134,217,728 B (128 MiB) |
| Final test artifacts, including the result | 303,627 B | 128 MiB |
| Provider workers | 1 | 1 |
| Application / transport retries | 0 / 0 | 0 |
| Financial transactions | 0 | 0 |

Local pacer wait was **1.100191 seconds**; shared admission wait was **0.036783
seconds**. Shared transport duration totaled **1.590672 seconds**. The minimum
observed physical admission interval was **0.500256 seconds**, respecting the
unchanged 0.5-second governor. [GOVERNOR_SESSION.json](GOVERNOR_SESSION.json)
contains exactly seven matching native admission/transport records from session
`921c099e52a340e988c57e94f830ec37` and thirteen dispatched elements.

The session's native response-byte counter is 77,262. The physical-boundary meter
additionally includes the intercepted 273-byte rejection, giving **77,535**; the
native counter was not silently clamped or treated as complete. Likewise, native
dispatched demand is thirteen while aggregate caller demand includes the extra
cache hit. Bytes exclude HTTP headers, TLS and unread payload. The observed disk
peak is a sampled high-water value; a separate structural bound protects the
ceiling between samples. Offline report derivation added a small governor extract
after the provider window and is listed separately in [ARTIFACTS.json](ARTIFACTS.json).

**Actual billed CU and dollar cost are unknown.** The 6,400 allowance is a
diagnostic estimate ceiling, not a verified billing cap. No account billing
investigation was performed.

## D. Enforcement and shutdown

The supplied `capability.compare(...)` remains the sole capability evaluator.
Its wrapper counts demand before every public call/batch and reserves actual
HTTP attempts and dispatched elements at the transport boundary. Nested native
calls share the same counters and permanent deadline. Exhausted work is rejected
before native transport-start telemetry and external dispatch; failed starts
remain counted. The immutable cache cannot erase logical demand.

The exact method/parameter/endpoint allowlist admits only this factory filter,
the four prescribed ten-block slices and one forty-block candidate, chain ID,
genesis, bounded canonical headers, required receipts, and the historical factory
code pin. Repeated log queries, unauthorized methods/endpoints and redirects
terminate execution. Native shared admission and priority 50 remain authoritative.
The underlying urllib opener has no transport retry; application retries are zero.

A real-time alarm independently stops blocking work at 44 seconds, reserving
shutdown time within the owner's 45 seconds. A parent process independently
kills the sole worker by 44.5 seconds if necessary. Here the worker exited
normally with wait status zero, and no forced shutdown occurred. That exit status
means controlled completion of the test, not a positive capability result.

Response reads enforce the limit before body acquisition when Content-Length is
available and never probe an excess byte for chunked bodies. Every read chunk
updates durable usage. Credential echoes fail screening before raw publication.
Exceptions emit safe classifications, not transport URLs or credentials.

Disposable outputs use the attached volume. Dispatch and artifact writes reserve
stock; both SQLite files have an eight-MiB page bound, process file growth is
limited to eight MiB, and SQLite temporary work stays in memory. With thirty-two
two-MB response artifacts, six bounded SQLite main/WAL/SHM files and sixteen MiB
of metadata reserve, the structural stock ceiling is **131,108,864 bytes**, below
128 MiB. The parent also monitors storage. No full-state snapshot was created.

All counters include setup and receipt/header witnesses. Dispatch is terminal
after a failure or stop; no application fallback, new range or second experiment
exists in this execution. Durable pre-dispatch reservations and raw response
digests preserve evidence if a worker is killed in flight.

## E. Code and offline validation

Only capability execution and its relevant regression tests were repaired:

- `engineering/pons_history/capability.py`: validate each baseline slice and raw
  native ordering; compare full rows; authenticate the reference before the
  candidate; pin historical factory code and first-boundary parent identity;
  preserve partial evidence; recheck genesis/boundaries only on a completed
  candidate. Dispatch-group counters are no longer named physical upper bounds.
- `engineering/pons_history/bounded.py`: physical transport limits, fixed
  allowlists, response/stock protection, secret screening and a terminal latch.
- `engineering/pons_history/run_capability.py`: existing-provider preflight,
  disposable history, one worker, independent alarm/parent shutdown and receipts.
- Focused executor regressions, ordered capability fixtures in the existing
  historical tests, and registration in the existing FAST test list.

**91 relevant tests passed**, using CPython **3.12.14**, in **132.169 seconds**
offline. [VALIDATION.txt](VALIDATION.txt) preserves the receipt. Command:

```text
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/mnt/volume_nyc1_1790918115030 /opt/meme-machine/.venv/bin/python -m unittest tests.test_pons_capability_executor tests.test_pons_historical tests.lanes.pons.test_provider tests.lanes.pons.test_provider_admission tests.lanes.pons.test_immutable_rpc
```

Injected transports cover success, nested boundary calls, physical/logical/CU
exhaustion, forbidden methods/parameters/endpoints, redirects, failed-attempt
counting and no retry, explicit range rejection, fixed and chunked response
bounds, truncated/invalid envelopes, storage reservations, credential echoes,
wrong chain/factory, reordered/additional events, reorganization, complete
worker evidence preservation and a parent-killed stalled worker. Initial offline
fixture/order failures were corrected before live dispatch; no provider allowance
was consumed to debug the harness. Production runtime modules were unchanged.

## F. Economic significance and next direction

| Estimated empty seven-day census | Prepared ten-block | Hypothetical forty-block, unavailable here |
|---|---:|---:|
| Logical elements | 897,897 | 224,476 |
| Physical attempts | 149,650 | 37,413 |
| Diagnostic CU | 89.79M | 22.45M |
| Moving-head catch-up | 23.72 hours | 5.36 hours |

The hypothetical reduction is about 75% of census requests. **This account's
rejection makes those savings unavailable; no actual cost saving is verified.**
Raising aggregate request budgets cannot change its per-query boundary. The
figures cover an estimated empty census, not full economic reconstruction.
Graduation authentication, older launch evidence, pool activity, receipts,
senders, price history and candidate evaluation remain additional.

Choose **prospective accumulation** as the default next direction. Under separate
operational/provider authorization, begin independent authenticated enrollment,
persist canonical launch/graduation events and required native histories,
preserve the rolling seven-day domain, and resume uncovered tails from durable
checkpoints after ordinary outages. The inclusive seven-day cutoff must move
strictly past enrollment, with all required histories complete, before Survivor
readiness. Current cannot select or truncate the Survivor census.

This trades **at least seven days of delayed Survivor availability**, plus any
outstanding evidence work, for avoiding an immediate cold catch-up burst. The
ten-block empty cold census alone projects 20.78 static hours / 23.72 moving-head
hours at the full useful pacing slots, before all economic work and competing
Current/position traffic. Prospective acquisition spreads the census over the
week, approximately 0.247 four-range packets/second at the planning block rate;
it does not eliminate total census or economic cost. Earlier Survivor opportunity
loss is real, but no measured dollar/economic advantage justifies backfill here.
The original seven-day domain is preserved.

The 400-block density/economic test is **not the selected path and was not run**.
Its larger proposed limits remain proposals with an unreviewed aggregate executor,
not authorization. Prospective enrollment was not started either. Updated
[EFFICIENCY.md](../pons-historical-bootstrap/EFFICIENCY.md),
[PROJECTIONS.json](../pons-historical-bootstrap/PROJECTIONS.json) and
[NEXT_ACTION.md](../pons-historical-bootstrap/NEXT_ACTION.md) record this decision.

## G. Preserved invariants

The original **$500** PAPER inception and active epoch
`paper-1791089005190643467` remain unchanged. Original family-equivalent **5%**
sizing, shared capital/limits/funding architecture, all nine approved strategy
changes, candidate history and economic policy, Current/Survivor independence,
Pump/PumpSwap repairs and startup, Model B, Meteora/Ramses pauses and retention
improvements were preserved. No portfolio, funding-authority, trade-record,
operational-service or production runtime source change was made.

[PRESERVATION.json](PRESERVATION.json) reports no changes across **71** selected
production/configuration files: **56** content checksums and **15** size/mtime
checks for retained large archives. The PAPER service was inactive before and
after; no deployment/restart occurred. Only the required existing shared Robinhood
admission/usage ledger received test telemetry. Disposable SQLite files stayed
outside Git; public RPC envelopes were screened before publication.

## H. Publication and ancestry

Dedicated branch: `engineering/pons-40-block-capability-20261008`.
Starting published commit: `b8434e30b9de296fdb36a48e3992d12ac7b64546`;
starting tree: `8269ae5fa1006aa12da3cc2ddb1b5bacbcc4e53c`.
The provider executed committed source
`125e20dee9fb3d9a1a712bb9b05fc215d5999fd8`, tree
`e6592eb76c7fc7c9aa44e2befcf69bdc2c444349`.
The result publication is a descendant of both; original branches and main were
preserved. Exact final publication commit/tree, immutable GitHub handoff URL,
remote object verification and clean-worktree evidence accompany the final report.
The command and artifact digests allow review without another provider request.
