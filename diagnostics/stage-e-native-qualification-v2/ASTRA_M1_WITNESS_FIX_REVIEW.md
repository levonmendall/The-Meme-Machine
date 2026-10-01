# Astra review — Q2 narrow M1 witness correction

PAPER ONLY. Stage E **RED**. Stage F **NOT STARTED**. Integration **NOT AUTHORIZED**. This package submits a qualification-witness correction for review. It embeds **no runtime repair**. The standalone corrected Q2 candidate still produces the required negative M1 result on the unrepaired production base. The positive compatibility evidence is explicitly a combination of focused qualification-unit coverage and existing exact A2 native evidence; it is not qualification of that standalone candidate.

## Exact identities and preserved history

| Role | Commit SHA | Tree |
|---|---|---|
| Original executed Q2 candidate | `7a73165efdb82309c9025a4a86c26f3c6417c7f1` | `2c6eee1dd0aff76fdd71990ea807df8fcfb2f001` |
| Original published package | `cda218bffbaaf650b7eca9c8fc2d7ba0e3124bc2` | Recorded in preservation receipt |
| First correction attempt, superseded | `6f72bcf7c86d7ebb17a0cb40c13eac3a3c3555fd` | `f4a3ad9cf0c3e4577967ce0a5eeba714ec5bf4a3` |
| **Final corrected Q2 candidate S** | **`ace479836690e65c091407e7da7545ad61952f31`** | **`e0440624a431927851b4e30756605f1a44390ccd`** |
| Unrepaired production base | `dc08f9064cf5e37b63f383f52aa709d0afc1723f` | `68736cf664169dee665762019800bf87ca0f1f67` |
| Approved M1 reference | `b11b16fbdc4ea0312b2c6f51de37e4d68e1f2da1` | `bdc9e10bb90e659270b8b3ea995d4c74b7ebeb83` |
| Approved A2 treatment/reference execution | `4d386498b3dc848e1ba27d11dd8d61841ba426d1` | `84903f733e634fa8dd440266c6112209edf24604` |

Branch: `cert/stage-e-native-qualification-v2-m1-witness-fix`. Final S descends from the original publication through the first correction attempt. The publication of this review adds evidence only after S. Resolve its own publication SHA/tree from the Git object containing this file; that publication commit carries no new execution credit.

All **75** original package files are byte-for-byte preserved, including [ASTRA_REVIEW_PACKAGE.md](ASTRA_REVIEW_PACKAGE.md), the failed [original M1 raw artifact](raw/m1-completion.json.gz), and the failed original aggregate. [original-package-preservation.json](m1-witness-fix/original-package-preservation.json) records every original file's SHA-256 and Git blob. Neither original failure is overwritten or reinterpreted. No qualification credit is borrowed from the old Q2 candidate.

The first correction attempt passed 70 classified tests and retained its expected native negative, but review of the exact A2 receipt continuation found that its post-turn check incorrectly required the remaining 488 records to stay pending. The approved next turn legitimately consumes those 488. That attempt's complete bound raw evidence, assembly manifest, classifications, test results, source origins, and controllers are preserved in [first-correction-6f72bcf7-evidence.tar.gz](m1-witness-fix/first-correction-6f72bcf7-evidence.tar.gz), SHA-256 `b063e563fb2127a7bd2699ce3448f4d14c3856f2015d2e7630667cf3300ab085`. [first-correction-history.json](m1-witness-fix/first-correction-history.json) inventories it. Final S has its own predeclaration, assembly, 71-test run, and one native M1 attempt; none of the first attempt's credit is reused.

## Exact witness change

The old predicate was `completion_query_interrupted = reads[0] == 2`. The corrected witness independently records:

- `interruption_injections` and `interruption_injected_at_read` from the actual read-2 urgent `PriorityOwner.submit` inside SQLite's trace callback;
- each ledger read's ordinal, native caller purpose, bounded SQL hash/limit, pending decision identity, transaction state, fetch outcome, SQLite error code, and real owner interrupt flag;
- `completion_read_count`, `interruption_observed`, `bounded_completion_retry_count`, and `retry_read_ordinal` separately;
- the unchanged native `arbiter.complete` call's exact pending identity, actual ledger-derived arguments, return/error, and resulting pending state;
- independent read-only SQLite observations of native mutation, record identities/hashes, durable progress, integrity, and receipt remainder, plus real urgent and next-turn futures.

[Exact witness diff](m1-witness-fix/witness.diff) and [complete implementation diff](m1-witness-fix/implementation.diff) preserve every changed byte. [CHANGED_FILES.json](m1-witness-fix/CHANGED_FILES.json) lists the nine implementation files: `m1.py`, `verify.py`, the new focused `tests/test_m1.py`, schema/plan/version files, classifications, manifest refresh, and the input manifest. All are within `certification/stage_e_native_v2`.

The connection observer forwards SQL, native handlers, cursors, exceptions, and fetched rows unchanged. The completion observation forwards to the original native method without clearing pending or crediting progress. These are witness observations, not replacement completion logic. Only the native runtime can defer preemption on its one bounded retry. A second urgent injection, a fourth read, or a fabricated success flag cannot pass. The independent verifier recomputes all M1 gates even for a failed raw artifact before admitting it to aggregation; a green summary cannot override the observations.

The fixture still requires actual owner acceptance, real native archive mutation, **512 committed records**, cooperative interruption, closed transactions, SQLite integrity, exact pending semantics, urgent completion, the exact 488-record receipt remainder, durable accounting, preserved recovery episodes, and a usable next native turn. No `arbiter.pending` assignment, manual progress credit, or conversion of `maintenance_decision_in_flight` into success was added.

## Schema and controlled bytes

The qualification contract/cohort remain v2. Evidence **schema version advances from 2 to 3**, adding the required M1 witness structure and witness version `native-m1-completion-witness-v2q2-1`. The evidence schema's stable contract identifier remains `stage-e-native-transition-evidence-v2`. The plan declares schema version 3 and the M1 witness version; the refreshed input manifest declares version 3 and binds **94** inputs instead of 93.

| Controlled identity | Original SHA-256 | Final S SHA-256 |
|---|---|---|
| Plan | `e4dad6d059e8860cb7e0304235486874b3fc35a982d60267bcbdbe6fafb0fb8e` | `6c40324250e0870a9207161a0b944d58272922c90bf6fce97c57c2bb3dda16df` |
| Input manifest | `7c19f71addcd248130f7144e8ba1f914064341b23f7765ebeb97c9d210f337e8` | `100acc0f6e86f38af542f293d90cf2174310f8e618644fa8ecb69284bb057961` |
| Evidence schema | `8e9a90276422fea2ae0c1a2caf570fa00b5d69b9352e90560b868b7efd3daa45` | `203d50fe6b81f298c854c42dd6a7f54a2318f956106243783daa1a19a2b3ab87` |
| Gate map, unchanged | `0da0e7acd8ac56db20cdd0101092400983de30051c611684eab4f7267ea4ecf8` | Same |

[controlled-input-hash-changes.json](m1-witness-fix/controlled-input-hash-changes.json) enumerates all eight changed/added controlled entries and the separately changed manifest hash. No controlled byte change is omitted. Draft 2020-12 validates both current parents and both bound child-origin artifacts; [schema-validation.json](m1-witness-fix/schema-validation.json) records the schema hash and pinned tooling. Original schema-version-2 evidence retains its original candidate and hashes.

Run373-v2, Run379-v2, Run380-v2 and their templates, recovery/residence/source-lag thresholds, predecessor gate semantics, held-reader/transition witnesses, observer threshold, trial matrix, and material firewall are unchanged. No mechanical workload/schema-reference update was needed.

## Final S native negative and approved compatibility

| Evidence | Final S on unrepaired base, actual new trial | Approved M1 sequence in existing exact A2 native evidence |
|---|---|---|
| Interruption injected at read | **2** | **2**, urgent acceptance between ordinal 2 and 3 |
| Completion query actually interrupted | SQLite `SQLITE_INTERRUPT` **9**, owner flag true, native completion caller | Native `completion_read_interrupted=true`, real `OperationalError:interrupted` |
| Final matching ledger reads in first turn | **2** | **3**, exact trace ordinals `[1,2,3]` |
| Bounded accounting retries | **0** | **1** |
| Retry read ordinal | None | **3** |
| Completion accounting | No native completion call occurred | Native completion returned, 512 records credited |
| Pending after first turn | Same exact generation/sequence/side survives | Cleared by native completion accounting |
| First-turn durable units/records | **512 / 512** | **512 / 512** |
| First-turn hot records | **1288** | **1288** |
| Receipt remainder after first turn | **488**, exact identity partition retained | **488** |
| Urgent work | Accepted, completed, result **1928** | Accepted exactly once, completed, result **1928** |
| First-turn outcome | Cooperative `evidence_background_yield` | Cooperative `evidence_background_yield` |
| Transaction / integrity | Closed / `ok` | Closed / `ok` |
| Next native admission | **Unusable**, `maintenance_decision_in_flight` | **Usable**, no next error |
| After next turn | 512 durable records; pending still survives; receipt 488 | 1000 total durable records; receipt 0; hot 800 |
| Qualification meaning | Expected **NEGATIVE**, raw `passed=false` | Approved reference compatibility, separate from standalone Q2 |

Final S M1 trial: `m1-completion:f7afd2dcb0214ed19c00e373455a4d41`; generation `174d9390cbcf4804b2f4c8247e0f4e16`; original raw SHA-256 `1fbc4d234fb433dbaa1d4f310ae0add1bee6513178b2b1be87ec5be53d3b083b`. [raw/m1-completion.json.gz](m1-witness-fix/raw/m1-completion.json.gz) preserves the complete result. [native-results.json](m1-witness-fix/native-results.json), [raw-artifact-provenance.json](m1-witness-fix/raw-artifact-provenance.json), [artifact-inventory.json](m1-witness-fix/artifact-inventory.json), and the native archive receipts bind it. Preflight passes; M1 exits 1 with no harness errors, as the predeclared negative requires. That exit remains a failure of native completion, not a passing trial.

The retry's 512-record credit and the next native turn's **new 488 records** are separate. The positive qualification-unit fixture matches the exact A2 first/post-turn shapes. The corrected witness checks the new committed identities, corresponding ledger increase, native next-turn record credit, and receipt partition; it does not mistake legitimate continuation for duplicate retry progress or require the final ledger to stay at 512.

### Compatibility authority and limits

The existing recipe is `exact-git-tree-v2;generated=[];overlays=[];outputs=external`. It binds one exact candidate SHA/tree and a full source manifest. Importing approved M1 bytes from another SHA would violate that authority. No composite assembly or cross-source runtime execution was created, and no same-SHA rule was weakened. The user-authorized fallback is used: **21 focused qualification-unit tests plus existing exact A2 native evidence**.

[approved-m1-compatibility.json](m1-witness-fix/approved-m1-compatibility.json) verifies the exact reference artifact, trace order, single urgent acceptance, single recovered completion, pending clear, 512 durable credit, receipt continuation, next admission, and the qualification-unit contract's corresponding acceptance. It binds both final S and approved M1/A2 identities and explicitly sets `standalone_q2_native_qualification=false` and `cross_source_execution=false`.

Reference [Actions run 36889471128, attempt 1](https://github.com/levonmendall/The-Meme-Machine/actions/runs/36889471128), artifact **11175369007**, ZIP SHA-256 **`e8a6db3d3304961ac2a8bee6e606c879cd8234a7479a523e62851e421c56b487`**, is preserved in [a2-exact-4d386498.zip](m1-witness-fix/a2-reference/a2-exact-4d386498.zip). Its original member hashes all verify. The native gate test `tests.test_owner_admission_phase2.NativeGateTests.test_gate_accepted_native_completion_interruption_preserves_m1` requires `len(reads)==3`; the separate finite prerequisite records actual ordinals `[1,2,3]`. Their exact source blobs are recorded in [source-bindings.json](m1-witness-fix/a2-reference/source-bindings.json).

The M1 runtime blob `44d627be0a867eba3c0394a533eaa9eecff77e07`, arbiter, maintenance-state, evidence-plane, and M1-focused test blobs are identical at approved M1 and A2. A2's 29-test matrix, 25 M1-focused runtime tests, and finite prerequisite passed. **The A2 workflow overall remains failed / `FOCUSED_GATES_BLOCKED` because a separate affected source check failed.** Its original result and logs are retained; this package does not relabel that workflow as successful or rerun its broader checks.

## Classified tests and rejection coverage

Final S ran **71 / 71 PASS**, with zero failures, errors or skips: all **50 existing classified Q2 static/deterministic tests** and **21 focused M1 witness tests**. [classification-before-execution.json](m1-witness-fix/tests/classification-before-execution.json) records every test's classification before execution. [classified-test-results.json](m1-witness-fix/tests/classified-test-results.json) and [tests.log](m1-witness-fix/tests/tests.log) record all exact test identities and outcomes. The supplemental unit run has no canonical qualification authority.

Focused tests deterministically reject all 14 required negative cases: read-1 interruption; read-3 interruption; no real interrupt; no retry; two or more retries; three final reads without read-2 injection; retry with pending surviving; pending cleared without accounting; duplicate durable progress; urgent never completing; lost receipt continuation; unusable next admission; fabricated `decision_completed`; fabricated `next_admission_usable`. Additional checks reject a second urgent injection, wrong SQLite interrupt/owner flag/caller purpose, unsupported next-turn progress, missing ordinal/retry/accounting schema fields, and fabricated aggregation success. The expected unrepaired negative and exact approved first/post-turn sequence are also covered.

The retained 50 tests include plan/input/gate-map hashes, historical-input immutability, schema validity, workflow bindings, same-SHA and equal-tree rejection, complete read-only assemblies, foreign origins, provider attempts, failed-trial preservation, missing/duplicate/replaced artifacts, and aggregate identity/attempt checks. The M1 aggregation test preserves a negative and rejects fabricated success even when its artifact hash is refreshed. No old native raw artifact is used to fill the new candidate's cohort. The full six-case native matrix was not rerun or claimed complete.

## Assembly, origins, artifacts and scope

Final reviewed assembly digest: **`40bbb71b4fd7b4b28af6c5f70c72da4636915c910697581759765b6027b4d18c`**. Source manifest: **1275 files**, **25776461 bytes**; canonical source-manifest SHA-256 **`a1f9df76aed76cac2d85f65727db5a8d653ab26337e7b81a817ade532e0717c6`**. [candidate-identity.json](m1-witness-fix/candidate-identity.json), [assembly-manifest.json.gz](m1-witness-fix/assembly-manifest.json.gz), [source-manifest.json.gz](m1-witness-fix/source-manifest.json.gz), and [predeclaration.json](m1-witness-fix/predeclaration.json) bind the exact tree, plan/input hashes, local run identity, attempt 1, expected negative and compatibility mode before execution.

The local construction SHA `5c7f9af90b0c011d886235ffa88eed7a56c18eb3` has the same final tree but is rejected as a different commit; it ran zero bound native trials. [same-tree-different-commit-rejection.json](m1-witness-fix/same-tree-different-commit-rejection.json) retains the check. Only published S earned the new execution records.

Both bound trial parents and their separately bound child-origin probes verify the same assembly before and after execution. Preflight records **183** parent origins; M1 records **212**; each child records **186**. Each child rejects foreign dynamic code before it executes. The 71-test supplemental run records **292** actual origins and separately pins tooling/controller bytes in [tests/source-binding.json.gz](m1-witness-fix/tests/source-binding.json.gz) and [supplemental-predeclaration.json.gz](m1-witness-fix/supplemental-predeclaration.json.gz). Tooling runs outside canonical runtime authority. Python is **3.12.14**, runtime websockets **17.1** with the unchanged approved content lock; schema/YAML tooling is **jsonschema 4.23.0 / PyYAML 6.0.2**. Provider attempts are empty. Assembly outputs are external; there are no overlays or generated execution sources.

[scope-integrity.json](m1-witness-fix/scope-integrity.json) verifies **344** existing runtime/test/workflow blobs against the authorized production base and verifies the frozen workloads and unchanged qualification witnesses/firewall. It states `runtime_repair_embedded=false`. [artifact-manifest.json](m1-witness-fix/artifact-manifest.json) hashes every new review artifact, both compressed and raw identities where applicable, and this review file. Historical reference/source files are text or original compressed evidence; no runtime SQLite database is published.

**No M1 runtime, A2, housekeeping, production behavior, recovery/residence/source-lag threshold, gate-map semantics, observer threshold, or material firewall change is embedded.** No full Run373 material execution, Run379/Run380 pressure, combined capacity workload, fresh observer benchmark, fixed cohort, canonical Stage E, Stage F, or integration successor occurred. The material budget is not replenished. [not-executed.json](m1-witness-fix/not-executed.json) records these boundaries.

The submitted correction is review-ready. Native M1 completion on the standalone unrepaired Q2 candidate remains blocked, and integration remains unauthorized.
