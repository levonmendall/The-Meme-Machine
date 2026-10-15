# Operational PAPER application

Maintain the existing four committed lane implementations and shared portfolio.
The supported entrypoint is `python -m meme_machine.operational`.

Use CPython 3.12.14 and the pinned runtime requirements. During development,
run the smallest affected offline modules/cases using
`python -m operational.tests FAST --modules <module>` (or `OPERATIONAL --modules`
for modules outside FAST). Consolidate related repairs before an integration
checkpoint. Tests must use offline providers and temporary state; never contact
market providers in CI.

A funding-closed diagnostic uses a risk-based validation gate, not an automatic
full-suite gate: affected tests and failure paths, the actual integrated startup
rehearsal for changed supervisor/worker/recovery/shutdown dependencies, exact
source-integrity guards, and relevant accounting, protection, provider and recovery
regressions on the combined source. Before an explicitly authorized start, also
require fresh host/source/configuration, obligations, native recovery, storage,
service-user access and provider-control preflight. State which risks the evidence
covers and which remain live-only. Focused success is not a general release PASS;
funding closed does not relax any safety invariant or grant runtime authority.

Reserve one complete FAST and the applicable complete OPERATIONAL release
validation for the finalized one-hour acceptance/normal-operation candidate.
Broader validation may also be necessary when a change's demonstrated risk or
dependency reach requires it; record the reason rather than imposing it on every
repair or diagnostic. Reuse valid exact-source or unchanged-path proofs. After
source changes, rerun affected checks and any release checks actually invalidated.
Do not weaken critical tests, original readiness/protection/shutdown deadlines,
or financial/native recovery requirements to shorten validation.

Keep iterative repairs in draft PRs. Do not manually dispatch full FAST for each
draft repair or mark a PR ready merely to obtain that run. Freeze the candidate
for promotion when it is genuinely ready. Let useful CI finish unless obsolete;
do not repeatedly poll `gh run view` or start a redundant watch/poll loop. Continue
independent lightweight offline work while CI runs, without competing heavy tests
or benchmarks. Retrieve the terminal result at a meaningful checkpoint. Draft
skips, canceled runs and partial suites are not passes.

Preserve exact Decimal accounting, native reconciliation before discovery,
idempotent reservations/delivery, bounded storage and maintenance fairness.
`solana_owner_admission.py` schedules machine work; it is not human permission.

Keep PAPER execution free of wallet keys, transaction signing, real submissions,
live switches, cryptographic permits and owner authorization gates. Credentials
and operational state must stay outside Git. Dashboard failure must not stop
position management.

For engineering, CAPACITY, RECOVERY and AUTONOMY artifacts, follow
`operational/ENGINEERING_STORAGE.md`. Admit large copies through
`meme_machine.operational.backup`, and run offline suites through
`python -m operational.tests`. Never recursively copy old handoffs or snapshot
collections into a new handoff. Reference and verify existing points instead.
Preserve failed or unknown evidence for explicit disposition. Storage admission
applies to new engineering artifacts; native position safety keeps running.

Do not alter strategy economics without an explicit owner instruction. Preserve
historical branches and main. Deployment, genuine inception and market acceptance
are separate authorized tasks. No GitHub workflow is a production scheduler.

Choose corrections at the demonstrated failure's level: isolated implementation,
shared subsystem, or systemic architecture. Recurring ownership/recovery failures,
inadequate capacity after measured local improvements, or accumulating workarounds
require a bounded review of the affected shared contract. Compare retaining,
refactoring and replacing that mechanism; prefer the least justified complexity
that resolves the full cause, not merely the smallest diff. Do not redesign on
an unproven hypothesis. Financial authority, economics, safeguards and incompatible
persistent-state changes still require their applicable explicit approval.

For Pump/Pons startup, recovery, provider, SQLite, throughput or release tasks,
use `.agents/skills/meme-machine-operational-resolution/SKILL.md`. Diagnose
retained failures first, reproduce related code paths offline, and use a single
integration/test owner. Prefer isolated feature branches and draft pull requests.
Publish reviewable diagnostic repairs with their scoped evidence; promote a final
one-hour/normal-operation candidate only after its required release checks pass.
Keep remaining work focused on sustained Pump throughput, managed-Pons acquisition
and protection, correct native recovery, and the authorized operating objective.
