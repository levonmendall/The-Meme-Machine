# Astra review package — one integration successor

PAPER ONLY. Deterministic integration GREEN. Stage E remains RED; Stage F remains
NOT_STARTED. Authorization: `Q2_APPROVED_AUTHORIZE_INTEGRATION_SUCCESSOR`.
No qualification, canonical or certification credit is claimed.

## 1. Exact integrated identity and ancestry

S = `7a516a6a92be9347661ac0e7f560971c171a0931`.
T = `9da7d1e1625ba04c1437c63606c90f5e293bdba7`.
Assembly digest = `08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659`.
Base = `4d386498b3dc848e1ba27d11dd8d61841ba426d1`, tree `84903f733e634fa8dd440266c6112209edf24604`.
Branch: `integration/stage-e-native-v2-successor`.

The single existing recovery branch is continued from the authorized A2 base,
which already descends from approved M1. No diagnostic branch was merged
wholesale. Component map creation preceded the original recovery edits and the
expanded map preceded this assignment's additional proof/control edits. No
unpublished bytes or lost-session test credit is claimed. The production bytes
are unchanged from the prior durable recovery; fresh results below belong only
to S/T. No final production candidate freeze or promotion intent is created.

Ancestry from the integration base:

`4d386498b3dc848e1ba27d11dd8d61841ba426d1` → `fa5d07fdeb54a5748ef19a3ce4f044672d2bf888` → `430e6ca3a80f7f6dceb7bf03c26a99af1fc2ff7d` → `3c3a1b8f61071a05a52c6163ccad2c26065c073c` → `5082e3c9c6db6c8798563ba21bb226b14ca16f5f` → `7a516a6a92be9347661ac0e7f560971c171a0931`

Required early non-certified checkpoints remain durable: `fa5d07fdeb54a5748ef19a3ce4f044672d2bf888`
(tree `c644d1107ef23aa98be2f9db5bf6bf91629853a1`, 56 changed files) and
`430e6ca3a80f7f6dceb7bf03c26a99af1fc2ff7d` (tree
`082774aa1c1550c182f6b60a51c2f14da042bd05`, 15 changed files).
Their exact changed-file lists are retained in
[recovery checkpoints](../stage-e-native-v2-successor/checkpoints.json).
WIP checkpoints carry no certification credit.

## 2. Components, classifications and overlap resolution

| Component | Approved source commit | Source tree |
| --- | --- | --- |
| A2 | `4d386498b3dc848e1ba27d11dd8d61841ba426d1` | `84903f733e634fa8dd440266c6112209edf24604` |
| HOUSEKEEPING | `d4068d4fa177225daf8780ee7c9765977f4b8793` | `f3a1f7561c564243ad01fdf47d818ef9eeffaeec` |
| M1 | `b11b16fbdc4ea0312b2c6f51de37e4d68e1f2da1` | `bdc9e10bb90e659270b8b3ea995d4c74b7ebeb83` |
| Q2 | `ace479836690e65c091407e7da7545ad61952f31` | `e0440624a431927851b4e30756605f1a44390ccd` |

M1's workflow `36839981757` is an approval reference only; its component pass is
not substituted for this run. Q2 review publication
`ded9f69d311938996320712e1fc173a12885d400` is referenced, not imported wholesale.
The housekeeping patch at
`diagnostics/housekeeping-ordering/treatment.patch` has SHA256
`f4d3b0399dcfbe43b968ef0a901be73efe187f1a3ecdc79b16f5defb177f6f2d`.

[component-map.json](component-map.json) records each source/base commit and tree,
production/test/workflow paths, exact identities, expected overlaps and excluded
diagnostic/evidence files. All 81 files changed from the integration base to S
are classified, and seven inherited M1/A2 files are separately classified.
[changed-files.json](changed-files.json) includes exact Git blob/content hashes,
status and ancestry. The full source-path list appears below; publication-only
files are separately listed in [PACKAGE_FILE_INDEX.json](PACKAGE_FILE_INDEX.json).

[INTEGRATION_OVERLAP_REVIEW.md](INTEGRATION_OVERLAP_REVIEW.md) shows BASE, M1,
M1/A2, historical housekeeping intent and integrated results, including the exact
production deltas. The retention/runtime overlaps are resolved semantically:
ordinary callbacks retain `retention()` with zero arguments, while only an
eligible turn enters a reversible context that forwards `housekeeping_first=True`
to the writer. M1 completion/cooperative ASTs and A2 control/admission bytes stay
exact. The static supplement independently compares approved AST and frozen
byte identities from inside the reviewed assembly.

## 3. Fresh deterministic suite and material firewall

Every selected test was explicitly classified before execution. The original
621-test list remains separate from four candidate-specific additions. Only
STATIC and DETERMINISTIC_BOUNDED tests/cases ran. Unknown classifications fail
closed, and generic discovery was not used. Finite production regression fixtures
confer no pressure or capacity qualification credit.

| Declared denominator | Run | PASS | FAIL | ERROR | SKIP |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original combined deterministic declaration | 621 | 621 | 0 | 0 | 0 |
| Candidate-specific supplement (one static + three native checks) | 4 | 4 | 0 | 0 | 0 |
| Total unittest execution | 625 | 625 | 0 | 0 | 0 |
| Original Q2 subset, separately reported | 71 | 71 | 0 | 0 | 0 |

The 621 group breakdown is 528 production regressions, 21 housekeeping checks,
71 corrected Q2 checks and one approved A2 native M1 prerequisite. The production
528 includes the fresh M1 25 and A2 29; these are not added again to the total.
All per-test outcomes, classifications, failures/errors/skips and child receipts
are retained in `deterministic/test-results.json` and its logs inside the archive.
There are zero executed skips. The separate resource operation, preflight and six
native cases below are not added to the unittest denominator.

Nine historical root pressure/scaled cases and all declared Q2 material cases
remain NOT_EXECUTED in [NOT_EXECUTED.json](NOT_EXECUTED.json). Historical frozen
Run373/379/380 source and fixtures remain intact; no green historical material
result is required. Their purposes are explicitly mapped by Q2's unchanged
`gate-map-v2.json` to successor-v2 gates. Full 14×10 MiB Run373, 120×160 Run379,
240×512 Run380, combined/recovery pressure and fixed cohorts were not launched.
No new material budget unit was consumed.

## 4. M1 and A2 results

Approved M1 focused regression: **25/25 PASS** on S/T. The corrected actual native
M1 witness passed with these observed values:

| M1 witness requirement | Observed |
| --- | --- |
| Interruption injection | read 2 |
| Matching ledger reads | exactly 3 |
| Bounded accounting retry | exactly 1, ordinal 3 |
| First durable archive records | 512 |
| First receipt remaining | 488 |
| Pending cleared by exact native completion | true |
| Urgent request completed | true |
| Next native admission/turn usable | true |
| Next turn new committed records | 488 |
| Total archive progress | 1000 |
| Final receipt remaining | 0 |
| Duplicate credit / manual pending clear | none / none |

The raw witness records the actual SQL error/owner interrupt, bounded query
identity, exact pending decision/accounting call, durable ledger and receipt,
urgent future completion and next-turn progress. Evidence:
`native/m1-completion/raw-trial-v2.json`.

Owner-admission matrix: **29/29 PASS**, freshly executed on S/T. Original tests
cover old-fails/new-passes native placement, already-infeasible rejection, actual
source-frame charging, exact FIFO, urgent priority, 100 ms acceptance boundaries,
fast-resubmission barriers, shutdown/restart, generation invalidation, wait
accounting, native worker readiness and cross-scope fairness. The M1 prerequisite
and accepted-admission/native-completion-interruption test also passed. A2 was
not redesigned and no component pass was borrowed.

## 5. Housekeeping equivalence and fresh proof

Focused suite: **21/21 PASS**. Three additional native checks and the static
semantic-equivalence check passed separately.

Eligibility is evaluated only within the exact already-admitted retirement turn:
ready pending prepared archive receipt, positive native housekeeping demand,
`t+E < D_housekeeping <= t+2E+O`, and every other active retirement
`D_scope > t+2E+O`. Effective deadlines include safety, successful-service drought
and active recovery; E=O=3 seconds gives a 9-second peer window.

Exactly one existing native GC invocation runs first. Its orphan predicates,
transaction, one-extra-key lookahead and max_records=1000/table remain exact:
at most 1000 archives, 1000 hot_chunks and 1000 address_keys. No repeated prefix,
second tail GC, checkpoint/vacuum migration or new protected atomic interval is
introduced. Committed progress is published before the existing source/urgent
return boundary. Credit remains retirement / __housekeeping__ / records=0 /
actual committed deletion units. M1/A2 accounting, scope cursor/rotation,
continuity, floors and source-yield policy are preserved.

The suite retains trigger true/false, strict/inclusive boundaries, competing
safety/drought/recovery deadlines, absent demand, unready/absent receipt, one
batch/lookahead bounds, immutable archives, committed source/urgent return,
urgent SQL rollback, pending/orphan truthfulness, no record credit, rotation,
real queued-source handoff and fresh next-turn isolation. Supplements freshly
prove committed-prefix lease expiry revokes service while retaining durable
units, and restart restores progress without duplicate housekeeping credit.

Receipt-74-shaped native control versus integration used actual observed native
needs and a prepared receipt, with two fresh bounded fixtures. Ordinary control
retired 768 records and did no housekeeping, leaving archive peer feasibility
false. Integrated retirement committed 3 housekeeping units, retired zero records,
returned to queued source and restored archive peer feasibility. The receipt
remained pending. The proof does not require a later archive selection.
Raw supplemental witnesses are in `deterministic/test-results.json`.

## 6. Corrected Q2 and successor bounded fixtures

Corrected Q2: **71/71 PASS** from this exact assembly. All original test IDs and
its denominator are unchanged. The five qualification identities, schema v3,
plan, gate map, fixture/workload hashes, firewall, observer contract and native
witness implementation stay exact. Historical `cleanup_recovery_plan.json`,
`stagee24_qualification_plan.json` and fixtures remain unchanged.

The integrated input manifest pins 250 files and is refreshed for the integrated
runtime/controller/proof/declaration bytes. The previously disclosed unused
websockets console-launcher shebang hash is the only dependency-lock difference;
all importable websockets bytes remain exact. Details and fresh identities are
in [controlled-input-changes.json](controlled-input-changes.json) and the linked
recovery dependency disclosure. All affected binding/input/schema/workflow
checks were rerun; no old input hash is falsely retained.

| Successor proof | Fresh bounded result |
| --- | --- |
| Run373-v2 | Three bounded frames decoded natively; coherent wall/monotonic clock, unchanged 3-second contract, stale/incoherent negatives and exact fixture identities passed |
| Run380-v2 | Three bounded frames; valid native envelope/signatures, coherent event/source clocks, fresh/stale economics and immutable economic fields/hash checks passed |
| Run379-v2 | 100 frozen-epoch seed frames × 2 transactions, then 3×2 live; setup elapsed=0, native hot debt=200, historical availability/linked continuity preserved, no timestamp refresh or episode re-enrollment |

All six original deterministic native cases passed on attempt 1; preflight passed
separately. Their exact six-case inventory aggregated successfully. Fourteen
parent/child raw records validated against the unchanged evidence schema v3.
A controller setup assertion initially included preflight in the six-case matrix;
it rejected before launching any trial. That zero-execution setup note is retained.
No source change or candidate trial retry was used to obtain these passes.

## 7. Native transitions, held reader, selection and restart

HOT → ARCHIVE and ARCHIVE → RETIREMENT passed through actual integrated writer
and native maintenance paths. Witnesses bind generation, original record hashes,
archive receipt/file hash, committed transaction identities, durable SQL state,
retention outcome and progress ledger. Rollback/attempted/cross-generation
negatives passed and do not earn committed credit. No observer manufactured a
transition. Evidence: `native/native-transitions/raw-trial-v2.json`.

Held reader passed with a snapshot-establishing SELECT before writer transition,
the same snapshot across archive/retirement commits, legitimately blocked
checkpoint while held, reader release, completed checkpoint and integrity `ok`.
BEGIN alone was not accepted. Evidence: `native/held-reader/raw-trial-v2.json`.

Pump and Meteora selection passed via native evidence paths, with actual selected
and excluded candidates/events/transactions and generation. No demands were
fabricated. Selection paths and counts are retained in [RESULTS.json](RESULTS.json)
and the transition raw witness.

Generation/restart passed: stale decision, worker result and receipt rejected;
durable original episode and committed ledger restored; no duplicate/lost
completion; receipt and retirement continuation; preserved restart gap and
integrity. M1's next-turn 488-record continuation separately passed. Evidence:
`native/generation-restart/raw-trial-v2.json`.

## 8. Exact-SHA/assembly, isolation and resource proof

All actual qualification/test/production Python modules executed from the single
reviewed read-only assembly under source-origin guards. The entire S tree
(1241 files, 34380838 bytes) binds S/T, plan, schema, input manifest,
gate map, assembly digest, original trial matrix and local workflow identity.
Python 3.12.14, SQLite 3.53.1, websockets 17.1 and content-pinned tooling were used.
The workflow identity is local deterministic execution; no remote Actions run is
claimed. Both v2 workflow source files remain exact and their static tests passed.

Fresh negative binding tests reject wrong SHA, equal-tree/different-commit,
dirty/staged source, untracked/ignored executable shadows, foreign module/exec
origins, wrong assembly, changed plan/input, stale/replaced artifacts, duplicate
or missing trials, wrong workflow and wrong attempt. Assembly content, file set
and digest were verified before and after all execution; output remained external.

The run recorded 483 actual parent origins and 55 bound children: 54 production
worker/crash/resource-tracker children plus one fresh resource child. Fifty-four
completed; one expected SIGKILL retains startup/exec observations and explicitly
has no final receipt. Every child rejected foreign dynamic code. Seven additional
Q2 origin-probe children passed. Provider calls and attempted provider calls were
zero. One declared transport fixture connected only to its own registered
loopback listener and was counted separately. Worker count/context/tasks remain
unchanged. The original crash literal is bound by exact hash to reviewed source.

The source-bound fresh resource child passed the existing bounded workload:
2,000 synthetic frames / 240,000 submitted events, peak RSS 166704 KiB
(below 200 MiB), DB 1257472 bytes plus WAL 642752 bytes
(below 32 MiB), bounded seen/decisions/gaps and zero real/attempted provider calls.
This includes assembly/origin-control overhead and is not physical-capacity or
continuous-market proof. SQLite integrity/rollback/transaction/queue checks and
accepted-future shutdown tests passed; no production owner thread remained alive.

## 9. Historical skips, observer and remaining gates

All 46 historical skipped tests retain their exact corrected disposition:
33 → future prepared assembly qualification; 13 → future canonical qualification.
None was executed or passed by virtue of mapping. Every status remains
NOT_EXECUTED with passing=false, retained in [NOT_EXECUTED.json](NOT_EXECUTED.json).

Observer status = **NOT_EXECUTED**; measurement = **UNEARNED**.
Only the unchanged strict `ratio < 0.01` contract and its static synthetic
acceptance/rejection checks were validated. No fresh benchmark was run.

Material capacity status = **NOT_EXECUTED**. Full pressure, prepared/fixed/full
cohort qualification, residence/debt-tail/capacity/recovery/observer evidence and
future canonical Stage E remain unearned. The original required gate names are
retained in NOT_EXECUTED.json. This green proves deterministic composition only;
it does not close the historical ~18.5% deficit, establish retirement capacity or
canonical readiness. Stage E stays RED and Stage F stays NOT_STARTED.

## 10. Durable evidence and hard stop

[RESULTS.json](RESULTS.json) provides exact counters, component test identities,
M1 fields, supplemental native witnesses, transition/reader/selection/restart
summaries, identities and remaining statuses. [integration-evidence.tar.gz](integration-evidence.tar.gz)
contains 209 raw result, log, assembly/declaration and child-observation artifacts.
Archive SHA256: `cf2ad63c686a695c8aa81adb8fc2506fc58d5a251efc27dd9f9e50fa4501a53f`.
[evidence-manifest.json](evidence-manifest.json) pins every member's size/hash.
Runtime databases, source overlays and unapproved executable probes are excluded.
The full exact source tree is durably available at S; archive membership and
all content hashes are verified before publication.

Earlier recovery failures remain separately retained in the recovery history and
hashed raw archives. They receive no pass credit. This package is published as a
report-only descendant of S and records execution solely for S/T; the publication
commit itself receives no execution or certification credit.

**STOP / RETURN TO ASTRA.** No observer benchmark, material workload, fixed cohort,
canonical Stage E, promotion intent, canonical branch move, final production
candidate freeze or Stage F was performed. Next blocking task: Astra review of
this exact deterministic integration and package.

## Complete source changed-file list

| Source path (base → S) | Classification |
| --- | --- |
| `.github/workflows/stagee-native-qualification-v2-reusable.yml` | Q2 |
| `.github/workflows/stagee-native-qualification-v2.yml` | Q2 |
| `certification/stage_e_integration/__init__.py` | INTEGRATION_ONLY |
| `certification/stage_e_integration/bootstrap.py` | INTEGRATION_ONLY |
| `certification/stage_e_integration/crash_child.py` | INTEGRATION_ONLY |
| `certification/stage_e_integration/driver.py` | INTEGRATION_ONLY |
| `certification/stage_e_integration/generated.py` | INTEGRATION_ONLY |
| `certification/stage_e_integration/guard.py` | INTEGRATION_ONLY |
| `certification/stage_e_integration/prepare.py` | INTEGRATION_ONLY |
| `certification/stage_e_integration/static_verify.py` | INTEGRATION_ONLY |
| `certification/stage_e_integration/successor_checks.py` | INTEGRATION_ONLY |
| `certification/stage_e_integration/tooling-lock.json` | INTEGRATION_ONLY |
| `certification/stage_e_native_v2/GATE_MAP.md` | Q2 |
| `certification/stage_e_native_v2/HISTORICAL_SKIPS.md` | Q2 |
| `certification/stage_e_native_v2/__init__.py` | Q2 |
| `certification/stage_e_native_v2/__main__.py` | Q2 |
| `certification/stage_e_native_v2/binding.py` | Q2 |
| `certification/stage_e_native_v2/bootstrap.py` | Q2 |
| `certification/stage_e_native_v2/clock.py` | Q2 |
| `certification/stage_e_native_v2/contract.py` | Q2 |
| `certification/stage_e_native_v2/dependency-lock-v2.json` | Q2 |
| `certification/stage_e_native_v2/evidence-schema-v2.json` | Q2 |
| `certification/stage_e_native_v2/firewall.py` | Q2 |
| `certification/stage_e_native_v2/fixtures.py` | Q2 |
| `certification/stage_e_native_v2/fixtures/run373-v2.json` | Q2 |
| `certification/stage_e_native_v2/fixtures/run379-template-provenance-v2.json` | Q2 |
| `certification/stage_e_native_v2/fixtures/run379-templates-v2.json.gz` | Q2 |
| `certification/stage_e_native_v2/fixtures/run379-v2.json` | Q2 |
| `certification/stage_e_native_v2/fixtures/run380-template-provenance-v2.json` | Q2 |
| `certification/stage_e_native_v2/fixtures/run380-templates-v2.json.gz` | Q2 |
| `certification/stage_e_native_v2/fixtures/run380-v2.json` | Q2 |
| `certification/stage_e_native_v2/gate-map-v2.json` | Q2 |
| `certification/stage_e_native_v2/historical-skips-v2.json` | Q2 |
| `certification/stage_e_native_v2/input-manifest-v2.json` | Q2 |
| `certification/stage_e_native_v2/isolation.py` | Q2 |
| `certification/stage_e_native_v2/m1.py` | Q2 |
| `certification/stage_e_native_v2/material.py` | Q2 |
| `certification/stage_e_native_v2/native.py` | Q2 |
| `certification/stage_e_native_v2/observer-contract-v2.json` | Q2 |
| `certification/stage_e_native_v2/observer.py` | Q2 |
| `certification/stage_e_native_v2/plan-v2.json` | Q2 |
| `certification/stage_e_native_v2/refresh_manifest.py` | Q2 |
| `certification/stage_e_native_v2/restart.py` | Q2 |
| `certification/stage_e_native_v2/run379.py` | Q2 |
| `certification/stage_e_native_v2/runner.py` | Q2 |
| `certification/stage_e_native_v2/test-classifications-v2.json` | Q2 |
| `certification/stage_e_native_v2/test_driver.py` | Q2 |
| `certification/stage_e_native_v2/tests/__init__.py` | Q2 |
| `certification/stage_e_native_v2/tests/test_binding.py` | Q2 |
| `certification/stage_e_native_v2/tests/test_clocks.py` | Q2 |
| `certification/stage_e_native_v2/tests/test_contract.py` | Q2 |
| `certification/stage_e_native_v2/tests/test_m1.py` | Q2 |
| `certification/stage_e_native_v2/tests/test_native.py` | Q2 |
| `certification/stage_e_native_v2/tests/test_workflow.py` | Q2 |
| `certification/stage_e_native_v2/transport.py` | Q2 |
| `certification/stage_e_native_v2/trial-definition-v2.json` | Q2 |
| `certification/stage_e_native_v2/verify.py` | Q2 |
| `certification/stage_e_native_v2/workflow.py` | Q2 |
| `diagnostics/stage-e-integration-successor/INTEGRATION_OVERLAP_REVIEW.md` | INTEGRATION_ONLY |
| `diagnostics/stage-e-integration-successor/component-map.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-integration-successor/controlled-input-changes.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-integration-successor/deterministic-supplement.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/README.md` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/RECOVERY_REVIEW.md` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/VALIDATION_RESULTS.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/checkpoint-1-static.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/checkpoint-2-failed-validation-manifest.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/checkpoint-2-failed-validation.tar.gz` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/checkpoint-2-static.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/checkpoint-2-validation-history.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/checkpoints.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/component-map.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/controlled-input-changes.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/dependency-environment-change.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/deterministic-allowlist.json` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/validated-3c3a1b8f-evidence.tar.gz` | INTEGRATION_ONLY |
| `diagnostics/stage-e-native-v2-successor/validated-evidence-manifest.json` | INTEGRATION_ONLY |
| `meme_machine/solana_evidence_plane.py` | HOUSEKEEPING |
| `meme_machine/solana_evidence_service.py` | HOUSEKEEPING |
| `meme_machine/solana_maintenance_runtime.py` | HOUSEKEEPING |
| `tests/test_housekeeping_integration.py` | HOUSEKEEPING |

ASTRA_REVIEW_READY:
INTEGRATION_SUCCESSOR_DETERMINISTIC_GREEN
