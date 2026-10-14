# Operational PAPER application

Maintain the existing four committed lane implementations and shared portfolio.
The supported entrypoint is `python -m meme_machine.operational`.

Use CPython 3.12.14 and the pinned runtime requirements. For routine
changes run the smallest affected offline modules/cases using
`python -m operational.tests FAST --modules <module>` (or `OPERATIONAL --modules`
for modules outside FAST). Include the real integrated startup rehearsal when
supervisor, workers, recovery, or shutdown paths change. Run complete FAST once
on the finalized integrated candidate before release/any live observation, and
OPERATIONAL before deployment as required. Do not repeat the entire suite after
each narrow repair. Tests must use offline providers and temporary state; never
contact market providers in CI.

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

For Pump/Pons startup, recovery, provider, SQLite, throughput or release tasks,
use `.agents/skills/meme-machine-operational-resolution/SKILL.md`. Diagnose
retained failures first, reproduce related code paths offline, and use a single
integration/test owner. Prefer isolated feature branches and draft pull requests;
publish a final release candidate only after its required full CI checks pass.
