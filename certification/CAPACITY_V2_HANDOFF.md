# Four-lane capacity integration: 2026-09-20

This branch is based on integration ebd03f5780eee46cc59f0338f48830e475480d78
plus the separate prospective research/reporting branch (PR #79,
7901e0803792e26dd8d8087d3914c642d359f876). The exact resulting commit is the
commit containing this file, recorded by every run as `integration_sha`.
It does not change the revision of the running campaign, merge main, or launch
another competing market job.

## Sources and paper-only boundary

Remote heads independently rechecked at 02:44 UTC; all four remain unchanged:

| Lane | Source branch | Source SHA |
|---|---|---|
| Pump | feat/pump-acceleration-independent-v1 | 361d90dbfd12226467ac458f92b16a9f0b017fce |
| Meteora | research/solana-dlmm-independent-v1 | 45836b18c9afdda29909ebe9cb68d386a47b074f |
| Pons | feat/pons-selective-continuation-v1 | 7ed22d3bdca3680869ef61b41f063389cb006366 |
| Ramses | feat/robinhood-research-foundation | eebcb9136efa41db9a28f2ac95e4dddde0d17b15 |

`sources.json` retains exact policy/config hashes, strategy versions, provider
configuration variable identities and each overlaid repair commit. No secret
endpoint is stored. Existing source policy files remain byte-identical.
The original user four-lane scope supersedes the historical single-Pump scope
in root AGENTS.md/BUILD_STATUS.md; all paper-only/no-signing restrictions remain.

This integration includes PR #80 (Pons spare-slot immutable evidence batching,
38d264c9dd878e2f70ffb461c18bd12ecdd7c1d6) and PR #81 (Ramses defer initial
capital until the first fundable finalized screen,
325c6052056500146b88d1ad3e83bf5db5b9657a). Both are isolated lane changes.
No strategy thresholds, evidence deadlines, provider rate ceilings, first
observation times, finality checks, prospective ranges or exit rules change.

## Preserved latest smoke and active observation

Workflow 35483374004 / smoke job 106005093849 ran exact integration ebd03f5.
Run 2fa41cd0-88ba-4845-b167-ced816dca812 has 600.176895746 seconds of concurrent
observation, zero restarts, all four normal exits, zero open positions and
reconciled native books. All four had zero natural and zero forced settlements.
Raw result: `results/smoke-35483374004.json`. Artifact 10597391938, 48,014,943
bytes, SHA-256 977e69aed5b94f092cd894c827b34208ae9020474ac6aa5d792d2d2caef91c92.

| Lane | Process uptime seconds including normal drain | Observed flow | Physical requests |
|---|---:|---|---:|
| Pump | 1601.712456386 | 390 discovered; 2 complete evidence; 0 qualified | 676 |
| Meteora | 601.682193585 | 73 discovered; 16 screened; 0 complete observations | 220 |
| Pons | 669.279598476 | 161 evaluated; 0 qualified | 1055 |
| Ramses | 600.176895746 | 2 finalized scans; 4 active pools | 115 |

The original engineering gate returned PASS and automatically started sustained
job 106008580976, four-hour step at 02:42:32 UTC. That is an active observation,
not a certification claim. The smoke also confirmed the Ramses empty-start bug:
its initial capital map is permanently empty. Mathematical zero-balance
reconciliation does not prove funded position capacity. The corrected readiness
check now rejects this state, with a separate machine-readable review in
`results/smoke-35483374004-readiness-review.json`. The original result is retained
unchanged. The current campaign cannot validate PR #81; the repaired integration
requires fresh deterministic gates, clean smoke, and a new full continuous
four-hour window. Never splice these windows. No process was restarted.

Shared Robinhood: 1170 HTTP-200 transports, zero retries, maximum queue depth 2,
final queue empty. Solana: 896 physical grants, 8 rate errors, maximum sampled
active broker jobs 276. These are measurements, not proof of sustainable
headroom. Pump's full-evidence throughput fell sharply from 62 complete vectors
in the earlier smoke; provider pressure and evidence censoring must be examined
before any economic conclusion. The read-only retained-artifact review collects
full gate/latency/censoring evidence without competing for RPC resources.

## Added observation controls

Every worker now reports cumulative CPU user/system time, peak resident memory,
and available logical CPUs. Separate counters measure serialized observer raw
archive, journal append and snapshot wall time. The counters explicitly exclude
strategy-native telemetry, lock wait, and the current final snapshot; they are
not total telemetry CPU cost. Physical transport monotonic start timestamps are
retained for later exact rate-spacing audits. The supervisor's 30-second durable
resource samples include these metrics. Older artifacts correctly show null.

The compact HTML status view has per-lane health, restart/uptime, open and settled
counts, complete policy identity, funnel, evidence/stream state, top terminal
reasons, native balances/PnL, provider requests/latencies, and errors. Shared
provider pressure remains visible. Full native reports and machine-readable
telemetry remain retained; no log reduction finances throughput.

## Reproduction and gates

```
python -m unittest discover -s certification/tests -v
python -m certification.run prepare --worktrees /new/pinned-worktrees
python -m certification.run verify --worktrees /new/pinned-worktrees --output /new/gates
python -m certification.run run --worktrees /new/pinned-worktrees --gate /new/gates/deterministic.json --output /new/smoke --seconds 600 --phase smoke
```

The last command requires the existing authorized provider environment and no
other competing market workflow. For sustained execution use separate new
worktrees and gates, `--phase sustained --seconds 14400 --smoke-result` pointing
to the clean smoke result from the exact same revision. The existing workflow
performs these steps on separate runners and preserves all success/failure
artifacts. This branch launches only when explicitly marked `[four-lane-sustained]` or `[four-lane-smoke]`; the shared concurrency group waits for any existing campaign to finish. The intended publication queues a fresh smoke plus four-hour run without cancelling the active observation.

## Remaining work by lane

Pump: quantify expired high-priority decision jobs against actual provider-rate
pressure and immutable cache reuse. Preserve bounded exact-window bootstrap.
Meteora: distinguish fresh-trigger/warmup and transaction-shape censoring from
v1.7 economic rejection, then obtain a complete natural LP lifecycle.
Pons: measure live deadline benefit of PR #80 while preserving the original
five-second clock; obtain natural entry, path-dependent partial exits and full
native settlement/replay.
Ramses: verify repaired quiet-start funding prospectively and obtain a natural
Fee Pulse settlement; forced +60-second proofs never establish policy returns.
All lanes: authenticate native outcome/path/cost joins for preregistered shadow
scores, add evidence-backed queue/headroom/starvation and replay certification
controls, and complete an uninterrupted four-hour window with natural lifecycles.
No return, strategy improvement or all-four-lane PASS is claimed.

Local validation: 29 supervisor/research/control tests, 245 Pump, 350 Meteora,
222 Pons, and 238 Ramses tests passed, plus all three Solana resource gates.
Exact local result and verified log hashes are in
`results/capacity-v2-local-deterministic.json`. Hosted execution repeats gates
against the final published commit. The first local verification produced a
retained Ramses log/hash mismatch despite its reported success; it is not used
as evidence. A fresh complete verification produced matching logs and hashes.
