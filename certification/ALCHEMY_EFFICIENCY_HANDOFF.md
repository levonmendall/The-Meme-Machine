# Robinhood Alchemy efficiency repair

This work starts at PR91 / `acb7e51127c66e89fc524d81408bdb4a0afec629`.
The new user request authorizes one concurrent 600-second smoke and, only after
clean smoke, one independent 3,600-second paper comparison. This supersedes the
previous handoff-only instruction. The repeating overnight campaign stays stopped.
No live comparison has launched yet. A separate Pump diagnostic must finish first.

## Baseline and diagnosis

Cycle 4 (`35508695288`, integration `6964cfe5c501075e53f3f6f809b85bbdeb50a7cc`)
finished normally. Artifact `10605823461` is preserved with SHA-256
`653ba9aaf63e591b7e6691a8b258103d527de9764b5aca722b15f18f5a564aaa`.
The existing terminal review remains in `results/hourly-review-35508695288.json`.
New reproducible transport/CU baseline: `results/alchemy-cycle4-baseline.json`.

| Metric including normal drain | Pons | Ramses |
|---|---:|---:|
| HTTP requests | 5,558 | 471 |
| Estimated billed CU | 846,478 | 48,816 |
| Evaluated candidates / finalized scans | 1,189 | 10 |
| Complete evidence vectors | 836 | not the same directional metric |
| Complete-but-stale candidates | 498 | not applicable |
| Natural / forced settlements | 0 / 0 | 0 / 0 |

Pons stale-after-complete fraction was 498/1,189 = 41.88%; separately 131
incomplete observations ended in initial acquisition staleness. These categories
are not summed as unique missed trading opportunities. Baseline JSON includes
observation-window-only wire counts separately from normal drain.

The suspected repeated-request denominator was overstated. Pons's 12,616
header-by-number calls contained 12,239 distinct parameter sets; 8,109 receipt
calls contained 7,977 distinct transactions; 9,883 state calls contained 9,878
distinct parameter sets. Existing candidate caches already avoid substantial
repetition. A 40% CU reduction cannot be inferred from exact-request deduplication.
The useful remaining repairs are acquisition shape, header-search overfetch,
session constants, endpoint-scoped reuse, and serial metadata transport latency.
Ramses actually completed ten scans over five active pools. Its zero live scans
were the checkpoint replacement defect already repaired by PR91.

## Implemented behavior

- Shared run-scoped SQLite evidence cache, isolated by endpoint/chain digest.
  Exact block hashes identify state/code reads; overrides stay in the key.
  Receipts require transaction plus expected block identity. Header hash/number
  aliases share a result only with an explicit authenticated pin. Mutable tags
  never become durable state cache keys. Single-block log filters use an exact blockHash on the wire. Multi-block
  numeric log ranges remain in the existing authenticated lane tape; they are
  not cached by merely pinning the two endpoints. No widened strategy windows
  or unauthenticated log reuse. State cache misses use EIP-1898 hash selectors
  only after the bounded endpoint probe proves support; unsupported endpoints
  retain original numeric reads without new durable state reuse. Returned
  headers/receipts/logs must match the pinned hash before caching.
- Cross-process request leases coalesce concurrent identical immutable work;
  each waiter retains its own deadline. Append-only reuse events and original
  raw RPC archives are retained. A leaked lease fails terminal readiness.
- Chain identity is verified once per bounded provider session. Rotation still
  reauthenticates; no endpoint/session trust is silently carried forward.
- Gas-price reuse is restricted to the same pinned block epoch and a quote
  acquired AFTER the receiving candidate's original observation, before its
  unchanged deadline. Source timestamps are retained. A quote predating a new
  candidate is fetched again. Code reuse remains exact-block scoped; there is no
  assumption that all deployment/proxy code is immutable across blocks/reorgs.
- Pons searches the authenticated local header index first. A computed search
  hint is never evidence: an exact adjacent header boundary must prove each
  unchanged 5s/15s anchor. The original bounded cold bootstrap remains.
- A previously authenticated curve-token identity is a request hint only: it
  lets the CURRENT block-pinned factory record join the initial batch. Current
  token(), code, factory provenance and all original authentication remain.
  Wrong hints fall back to current-token acquisition.
- Bounded endpoint capability probes run after gates/contention preflight.
  `eth_callMany` is used only for the compiled Pons curve's audited view getters,
  one contract and one block per bundle, no overrides. First use compares every
  grouped result with independent calls; disagreement disables it. Unsupported
  methods fall back inside the original deadline. The protocol authenticator
  must still accept the exact compiled runtime before any strategy evidence is
  accepted. Arbitrary calls and different blocks are never grouped.
- Block receipts are selected only after support and census identity are proven:
  at least 25 needed receipts, at least 50% relevance, no more than 128 block
  transactions, sufficient original deadline, and lower estimated billed CU.
  This also respects their larger documented throughput weight. Standard
  receipts remain the fallback. No indiscriminate full-block harvesting.
- Existing Pons urgent admission/Ramses aging fairness, 429 cooldown, and rate
  ceilings remain unchanged. No capacity increase or extra provider is justified
  before useful-demand measurements after these repairs.
- Runtime estimates count actual logical wire methods, not cache lookups or HTTP
  batches. Separate metrics retain physical requests, batch members, native/shared
  cache reuse, queue/transport time, scan/vector denominators, and unpriced methods.

Alchemy's documented schedule is frozen in `alchemy-cu-schedule.json`, sourced
from https://www.alchemy.com/docs/reference/compute-unit-costs on 2026-09-20.
It is an estimate, not a billing API or invoice. Standard JSON-RPC batches do not
reduce per-member CU. eth_chainId is 0 billed CU (5 throughput CU), eth_call is
26, headers/receipts/code/gasPrice are 20, logs are 60. Block receipts are 20
billed but 500 throughput CU. Unknown method prices remain unknown.

## Captured-evidence comparison

`results/alchemy-header-replay-before.json` and `results/alchemy-header-replay.json`
reproduce all 836 complete Cycle 4 trajectory vectors exactly, with no missing
captured evidence. Same 1,613 state reads, header reads 11,414 -> 10,540 (-7.7%),
trajectory batches 1,632 -> 1,457 (-10.7%). This is an offline acquisition
experiment, not live freshness, coverage, total-CU savings or profitability.
The narrower eight-header prototype reduced headers more but INCREASED serial
rounds; it was rejected because it could worsen the unchanged five-second gate.

## Reproduction

```sh
python -m certification.rpc_baseline --artifact-root /preserved/cycle4 --output baseline.json
python -m certification.replay_header_index --artifact-root /preserved/cycle4 --lane-source /composed/pons --output replay.json
python -m unittest discover -s certification/tests -v
python -m certification.run prepare --worktrees /new/exact-worktrees
python -m certification.run verify --worktrees /new/exact-worktrees --output /new/gates
```

The existing hosted workflow repeats all four full suites, three Solana resource
checks, integrity, contention, smoke and exact-revision readiness. Only then may
one hourly campaign start. No strategy/policy/config hash changed; no paper
accounting/authority/finality/freshness gate is relaxed. No main merge.

## Pending evidence and honest acceptance

Live support for optimized methods is not yet known. The 40% estimated CU target,
equal-or-better opportunity coverage, freshness, scan latency and bounded useful
Ramses progress remain UNPROVEN until the comparison completes. If the target is
missed, report that explicitly; do not shrink discovery or reinterpret incomplete
observations as economic rejects. No new provider is justified by this baseline.
The separate strategy certification remains incomplete without natural settled
lifecycles, even if engineering controls pass.

## Deterministic release validation

Full unchanged/composed suites passed: Pump 264, Meteora 369, Pons 256, Ramses
257 (1,146 total), plus 54 supervisor/accounting/capacity tests and three Solana
resource checks. Exact overlays and all frozen source/policy/config hashes verify.
Raw logs, hashes, and source manifest are in `results/alchemy-local-validation/`.
Two earlier local Pump subprocess transcripts were truncated without a unittest
footer despite zero exit. The existing gate rejected them. The runner now captures
through a pipe before saving; a regression proves missing footer still fails.
The complete suite and the entire validation stack subsequently passed. No test
was skipped or weakened. Initial failed transcripts remain preserved.

Fresh remote inspection also found separate `cert/*-execution-cert-v1` branches
with explicitly relaxed policy experiments. They are outside this repair: the
four authoritative source heads, operational overlays and frozen policy hashes
remain the verified PR91 set. No experimental strategy changes are imported.

For comparison, extract the completed artifact and run `rpc_baseline` with its
explicit `--run-id`, `--artifact-id` and `--artifact-sha256`; compare with
`python -m certification.compare_cu --before certification/results/alchemy-cycle4-baseline.json --after comparison.json --output comparison-result.json`.
The comparator deliberately cannot declare PASS from lower spend alone.
