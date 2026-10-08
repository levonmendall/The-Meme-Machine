# Operational consolidation inventory

Baseline: `7a516a6a92be9347661ac0e7f560971c171a0931`, tree
`9da7d1e1625ba04c1437c63606c90f5e293bdba7`. Work is sequential on
`operational/paper-v1`. Nothing has been removed or economically changed at this
inventory checkpoint. The owner directive supersedes the obsolete first-Pump-only
scope in AGENTS.md and BUILD_STATUS.md.

`operational/keep-port-archive.json` enumerates every baseline tracked file and the
relevant files in the four pinned lane sources, strategy preparation, dashboard,
accounting, and Stage-E successor. Each entry identifies its source commit,
classification, reason, and (for Python) static imports. The baseline manifest's
patch lists and integration overlay lists are the composition recipe; preparation
is an offline consolidation activity, never operational startup.

## Runtime that must survive

Keep the Solana finalized evidence service, decoder children, shared readers,
transport, repair scheduling, bounded archives, retention, checkpointing, SQLite
transactions, maintenance state/arbiter/runtime, and **solana_owner_admission.py**.
The latter schedules machine work; it does not authorize a human owner. Preserve
M1 completion and starvation prevention. Decision-critical acquisition and
durable lifecycle evidence remain necessary even when their original tests had
Stage-E names.

The lane implementations include executable runners currently under `tests/`:
Pump's `pump_acceleration_natural_prospective.py`, Meteora's
`solana_dlmm_independent_v1.py` and its simulation helpers, Pons' selective cohort,
and Ramses' extended acquisition/lifecycle loop. Port the actual execution code,
including Current/Survivor, cancellation, partial realization, provider retry,
rate-limit recovery, position continuation and replay. Research probes and old
strategies are not additional operational lanes.

## certification/ dependency finding

Normal runtime currently imports these useful implementations from certification:

| Implementation | Disposition |
| --- | --- |
| directional_sleeve, sleeve_reservations | Port shared family allocation and reconciliation |
| survivor_risk, survivor_commit, survivor_paper_book, survivor_history | Port independent observation, fresh commit, risk, persistence and recovery |
| execution_capacity | Port exact capacity downsizing and breadth checks |
| robinhood/plane, provider_authority, provider_usage, rpc_errors, pons, ramses | Port canonical read-only provider coordination, durable cache and native checkpoints |
| lifecycle_timing, position_continuation, continuity_state | Extract native continuation/recovery; discard campaign/workflow gates |
| directional_accounting, terminal_reconciliation | Extract native ledger reconciliation; discard observer proof obligations |
| current_sleeve_archive, survivor_terminal_archive, meteora_archive, pons_terminal_archive, ramses_archive, robinhood/window_archive | Extract bounded terminal compaction and retained replay anchors |
| preserved_checkpoint, lifecycle_identity | Preserve durable prefix/idempotency semantics; replace GitHub artifact/window authority with local durable state |
| journal, journal_proof | Preserve existing passive persistence checks where useful; no execution permission |
| governor, evidence_worker, evidence_supervisor | Port shared pacing and the evidence process; replace certification telemetry and orchestration |
| worker | Port native lane entrypoint calls and work-priority hooks; remove RPC observer duplication and conformance wrappers |

These are mixed files in several cases: PORT_TO_RUNTIME means extraction of the
named behavior, not wholesale retention of their transitive certification imports.
The executable operational tree and its tests must have no certification imports
before cleanup. `campaign_state`, `autonomous_control`, `autonomous_window`,
`autonomous_launch`, `single_campaign_control`, signing/attestation successors,
Stage-E v2/v3 isolation, declarations, review manifests, observer and evidence
packaging belong to historical Git. They are not a production scheduler.

## Source layout and pre-change gate

Resolve conflicts once in ordinary committed lane namespaces. Pump/Meteora have
different provider, postgrad and support bytes; Pons/Ramses have different
provider_topology and protocol bytes. Preserve those distinctions until source
and deterministic equivalence proves sharing safe. Identical shared Solana
service files may remain at the existing root. Do not select the newer historical
file merely because its commit is newer.

Run the existing composition offline from the baseline's exact recipe, verify
all declared composed bytes, then compare relocated source after reversing only
namespace/path adaptation. Run focused deterministic strategy, native accounting,
provider, recovery and maintenance comparisons before the nine changes.
No Stage-E qualification is authorized.

## Prepared strategies, portfolio and dashboard

Use only the nine frozen changes from `16f7dcefb9632be278c10c9377fed5fe847089af`.
Opportunity preservation, tail and scaling implementation contracts are frozen;
reset/recovery research, market studies, and the separate Pons concept are archive
only. Ramses economics are unchanged.

Port the Decimal portfolio journal and four-lane producer from PRs 105/106 and
the read-only dashboard/snapshot code from PR 104 and `c3462c8c`. These adapters
are dormant historically and require authoritative USD facts; they do not supply
exchange rates. Audit the materialized acquisition paths for SOL/USD and the
Robinhood quote denomination before enabling any canonical $500 epoch. No real
epoch will be initialized in consolidation.

The snapshot publisher must be outside trading authority and failure-isolated.
No Render changes are authorized. Dashboard/API and fixtures use the standard
library; portfolio code uses Decimal/SQLite. Historical SHA/provenance fields are
passive facts, not owner permits.

## Cleanup and validation

Remove historical runs, diagnostics, research, evidence tarballs, declarations,
obsolete handoffs, live-trigger markers and market/Stage-E workflows only after
runtime/test import analysis passes. Historical refs, PRs and main remain intact.
Keep deterministic fixtures actually used by retained tests. Replace CI with FAST
offline tests; OPERATIONAL is the deployment gate. ACCEPTANCE later runs exactly
CAPACITY → RECOVERY → AUTONOMY on Droplet 605465049 and is not a profitability test.

Runtime target is CPython 3.12.14 and websockets==17.1. This workspace has Python
3.12.14 and SQLite 3.53.1, not the matched historical SQLite 3.45.1. Record and
test that difference explicitly; use the known SQLite behavior in deployment.
PyYAML/jsonschema are harness dependencies, not yet established runtime needs.
No provider calls, credentials, deployment, systemd start or acceptance runs have
occurred.


Cleanup completed after the runtime and retained test import gate passed. The
final per-file outcomes are in `operational/keep-port-archive.json`; the exact
checkout removal list is `operational/cleanup.json`. Useful certification
implementations were relocated to `meme_machine/runtime/`. Historical Stage-E,
attestation, authorization, review, evidence, diagnostic and workflow surfaces
remain only in existing Git history. No historical branch, PR, main or ref was
deleted or rewritten. Retained scheduling and recovery tests use ordinary names.
