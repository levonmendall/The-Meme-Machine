# Run 378 pre-market orchestration repair

Runtime `1e50d476cfacfa0e5ff977f6288af0368cde6bce` passed complete hosted certificate
`36272436843`: 1,633 native tests, supervisor and all 11 machinery gates. Artifact
`10915928536` has SHA256
`0a8579a83265cc9819edc3fce398b1051264283e33f197604e4147e82b0bb916`.

Smoke workflow `36273032130` (Run 378) never began native work. Claim job
`108490465729` rejected concurrent threshold preflight `36273029605`, source
`9a99c8ae5e57b4ead6671d2eb81d4d0e06802175`. That independently authorized workflow
was provider-free source preparation and deterministic tests. The market guard
did not recognize its new workflow/job identity and conservatively classified it
as market work. The workflow was inspected at its exact source and completed.

The consumed state ref `cert/single-campaign-6d8a18efe2f5abe0` has empty phase
records, no claimed workflow, and no native exposure or hourly phase. Its authority
is not reused. Launcher `36273014675`, SHA
`32f20820b90fa5b86951c1121bfbbb0551ed11bc`, successfully dispatched only Run 378.

A fresh controller authorization was then issued after checking active jobs.
Launcher `36273159144`, SHA `77004061a8974dc31a50472876aa83878e9f8c89`, stopped
at its second quiet check, before dispatch, when another threshold preflight
`36273166316` appeared. Source `4ab66653a23475a72abe88bc96adf9f6e0b7fd9a` had
byte-identical preflight code. No additional market workflow was dispatched.

The correction is a narrowly reviewed workflow-content exception shared by the
single-campaign and legacy preflight guards. It reads at the run's immutable
40-character head SHA and checks SHA256 of the exact workflow bytes. The two
reviewed files are source-only threshold preflight and its `preserved_only: true`
non-market certification wrapper. Names alone do not grant the new exception.
Missing, malformed, changed, or unavailable content retains the block. An altered
pinned wrapper cannot evade the check with an `offline-prerequisites` job name.
No concurrent job is cancelled and no strategy/threshold/provider rule changes.

Deterministic regressions reproduce the Run 378 run/job shape, cover all five
active statuses, exact immutable lookup, mutation and unavailable-source refusal,
unknown workflows, and both guard paths. The old classifier reports the archived
preflight as market; the corrected integrated contention check admits only its
verified provider-free identity. Existing single-dispatch and phase-authority
regressions remain mandatory. Full certification is required on the revised SHA
before issuing another independent smoke-only authorization.
