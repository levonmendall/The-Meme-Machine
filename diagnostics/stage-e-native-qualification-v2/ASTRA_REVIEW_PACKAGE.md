# Astra review package — Stage E native qualification v2

PAPER ONLY. Stage E **RED**. Stage F **NOT STARTED**. The contract and deterministic witnesses are implemented; the required native M1 completion witness fails on the authorized production base. No runtime repair, owner-admission change, housekeeping change, material pressure, fresh observer measurement, candidate freeze, promotion, fixed material cohort, or canonical dispatch occurred.

## Exact Git authority and scope

Repository: `levonmendall/The-Meme-Machine`.

| Identity | Exact value |
|---|---|
| Implementation branch at qualification execution | `cert/stage-e-native-qualification-v2` |
| Published implementation head / candidate S | `7a73165efdb82309c9025a4a86c26f3c6417c7f1` |
| Candidate tree T | `2c6eee1dd0aff76fdd71990ea807df8fcfb2f001` |
| Parent of current implementation | `618fcca3ac008b2eb326b2e36164d30c663cef03` |
| Authorized production base | `dc08f9064cf5e37b63f383f52aa709d0afc1723f` |
| Base tree | `68736cf664169dee665762019800bf87ca0f1f67` |
| Lane D reference, read only | `49a45f8b6c80ab31278f4030d8226df6fe7dc009` |
| Reviewed assembly digest | `6f61f187885c2bbd8829235a981d72dd25b307243f1ccb94a260e0974def7bc9` |
| Assembly recipe | `exact-git-tree-v2;generated=[];overlays=[];outputs=external` |
| Source manifest | 1199 tracked files, 22947675 bytes |

The publication commit adds this diagnostics package only, as a descendant of S. Its exact head and tree are the Git object containing this package; the publication receipt returned with this review records both. They are resolved rather than embedded recursively into their own content. `git rev-parse HEAD` and `git rev-parse HEAD^{tree}` resolve those identities at the publication checkout. **That report commit is not candidate S and inherits no qualification credit.** All raw trials explicitly bind S and T above. No production files changed. See [CHANGED_FILES.json](CHANGED_FILES.json).

Only durable reachable GitHub source was used for the implementation base. The inaccessible `06f7a129eb9a1deab02af5f1f6bdfbaea89ea142` is neither a parent nor an imported source. Historical `stage-e-native-transition-contract-v1` has not been reconstructed from names, counts, or previous green results.

Publication through GitHub created S with the exact reviewed tree but a different SHA from local construction commit `96820029fe6d0085860b59d39305bb838ad37e22`. The same-tree/different-commit check rejected that local identity, which ran **zero** bound trials. A new predeclaration and read-only assembly for published S preceded all authoritative bounded trials. See [candidate-identity-v2.json](candidate-identity-v2.json) and [same-tree-different-commit-rejection-v2.json](same-tree-different-commit-rejection-v2.json).

The preceding reachable implementation commit618fcca also ran one exact first-attempt bounded matrix and failed M1. Static review then found that its prepared workflow entered the assembly through a root qualification wrapper; its preflight artifact path also needed explicit flat ZIP staging. Qualification-only corrections produced current S, with no runtime changes. The complete prior evidence set, including its failed M1 raw result, is preserved in [prior-exact-sha-618fcca-evidence.tar.gz](prior-exact-sha-618fcca-evidence.tar.gz) and identified by [prior-exact-sha-history.json](prior-exact-sha-history.json). It cannot qualify S. Each exact SHA has one native trial attempt; neither failed result was discarded or replaced by a passing retry.

## Contract, schema, plan, inputs

| Kind | Explicit identity |
|---|---|
| Contract | `stage-e-native-transition-contract-v2` |
| Cohort | `native-transition-cohort-v2` |
| Held reader | `native-contract-held-reader-v2` |
| Evidence schema | `stage-e-native-transition-evidence-v2`, schema version **2**, JSON Schema draft 2020-12 |
| Plan | `stage-e-native-transition-plan-v2` |
| Clock domain | `native-clock-domain-contract-v2` |
| Observer contract | `native-observer-paired-measurement-v2` |
| Gate map | `stage-e-predecessor-successor-gate-map-v2` |
| Input manifest | `stage-e-successor-input-manifest-v2` |
| Assembly | `stage-e-reviewed-execution-assembly-v2` |

| Byte identity | SHA-256 |
|---|---|
| Plan | `e4dad6d059e8860cb7e0304235486874b3fc35a982d60267bcbdbe6fafb0fb8e` |
| Input manifest | `7c19f71addcd248130f7144e8ba1f914064341b23f7765ebeb97c9d210f337e8` |
| Gate map | `0da0e7acd8ac56db20cdd0101092400983de30051c611684eab4f7267ea4ecf8` |
| Evidence schema | `8e9a90276422fea2ae0c1a2caf570fa00b5d69b9352e90560b868b7efd3daa45` |
| `run373-v2.json` | `542580d149b711d2e386e365f8cccbd9f269b29e66559751b57bf255fcf9294e` |
| `run379-v2.json` | `6949f1727ca859d58a0b6dc4b861d4a183d3d912ee4cbdf7c055f1ab0175a449` |
| `run380-v2.json` | `0f5ac9bab9f75d53546742b405b7bb98721198f2af15569a3c76215818242847` |
| `run379-templates-v2.json.gz` | `2dac1b3a1d773d14533a4fbf8c090540a427e58aa6b1d44510ad70f91b384ed9` |
| `run380-templates-v2.json.gz` | `73f5a7bc8dd600ec060f3a9f907fb57b1fac9ea5bdf7d27ff9d3e8df72678ebe` |

[INPUT_HASHES.md](INPUT_HASHES.md) records all 93 controlled input hashes and the separate immutable historical hashes. The complete assembly manifest also hashes every tracked file. Plan identity and input-manifest identity are independently declared, avoiding a circular plan/manifest hash. Outputs live outside the assembly.

Historical `cleanup_recovery_plan.json`, `stagee24_qualification_plan.json`, and historical fixtures/entrypoints remain byte-for-byte unchanged. Their exact hashes are verified against the base and recorded in [historical-input-hashes-v2.json](historical-input-hashes-v2.json). Successor commands explicitly select `certification.stage_e_native_v2`; old commands do not redirect to new fixtures.

## Predecessor-to-successor gates

[gate-map-v2.json](gate-map-v2.json) and [GATE_MAP.md](GATE_MAP.md) enumerate 44 required gates from reachable production/e26 inputs: 25 **RETAINED**, 19 **REPLACED_BY_STRONGER**, zero **UNRESOLVED**. Each names the old purpose and exact old input identity, new purpose and identity, and replacement rationale. These classifications describe contract retention/strength; they do not imply execution or passing capacity results. `validate_inputs` blocks any required UNRESOLVED gate or a dropped named successor.

[gate-readiness-v2.json](gate-readiness-v2.json) records actual disposition. Future pressure, prepared integrated assemblies, resource profiles, non-market end-to-end gates, and canonical requirements remain **NOT EXECUTED**. The local/remote workflow distinction is explicit. Required restart-accounting remains blocked by M1.

## Deterministic and static results

| Case | Classification before execution | Result | Unique trial ID |
|---|---|---|---|
| `preflight` | STATIC | PASS | `preflight:696881dd45ec486eb073b533b52c846e` |
| `clock-contract` | DETERMINISTIC_BOUNDED | PASS | `clock-contract:ef4f518139534e0486116ea7a79dda19` |
| `run379-setup` | DETERMINISTIC_BOUNDED | PASS | `run379-setup:9342fb3ba6ed415e96c2bc70cef0c1c0` |
| `native-transitions` | DETERMINISTIC_BOUNDED | PASS | `native-transitions:bbc67a013dfa4f17aa3afefede427e56` |
| `held-reader` | DETERMINISTIC_BOUNDED | PASS | `held-reader:f17713b3540c42d1881a57b5e7baccff` |
| `generation-restart` | DETERMINISTIC_BOUNDED | PASS | `generation-restart:c72266eada6f494f91e1dbf09d888e0a` |
| `m1-completion` | DETERMINISTIC_BOUNDED | FAIL — BLOCKER | `m1-completion:6f23203c3c634173997cdd296ae14997` |

Every row used the same declared S/T/plan/input/assembly and first attempt. Each parent contains one separately bound Python child origin probe. Parent origins range from 183 to 212 resolved modules; each process checks source/dependency/standard-library hashes during execution. The child rejects a direct `spec_from_file_location` foreign module before its code executes. All seven parent trials and seven child proofs pass schema validation; **the M1 parent has `passed=false`**. The exact six-case native matrix aggregate has `passed=false`, with only `m1-completion` in `failed_trials`. No raw native trial was retried.

[raw-artifact-provenance-v2.json](raw-artifact-provenance-v2.json) pins both compressed and original raw bytes. [artifact-inventory-v2.json](artifact-inventory-v2.json) pins exact case/trial ID, original raw hash, SHA, assembly, run ID, attempt and generation. [aggregate-v2.json.gz](aggregate-v2.json.gz) preserves the failed aggregate. The raw files contain full identities and child proofs; gzip is transport only, with deterministic mtime zero.

The 50 individually classified deterministic/static tests pass with zero failures, errors or skips. Tests cover coherent/incoherent native clocks, stale economics, frozen economic aging, recovery rebasing, timestamp refresh, equal-240 rejection, native transitions, held snapshots/checkpoints, generation/restart accounting, exact-SHA and equal-tree rejection, dirty/staged tracked bytes, untracked/ignored modules, foreign packages/`.pth`, wrong assembly, input drift, missing/duplicate/replaced artifacts, workflow/attempt mismatches, root qualification launch rejection before execution, and strict observer parsing/comparison. See [tests/test-results.json](tests/test-results.json), [tests/tests.log](tests/tests.log), and [tests/source-binding.json.gz](tests/source-binding.json.gz).

Supplemental unit tests carry no canonical qualification authority. On the prior618fcca candidate, the first assembled supplemental run passed49 tests, but a post-run controller-origin receipt tried to hash `<stdin>` as a file. Both that result and its reporting failure are preserved. Its supplemental test/receipt check was repeated to record module origins; same-SHA native trials were not retried. Current S ran its50 classified tests once from the reviewed assembly, recording289 actual module origins. Earlier unpublished engineering failures and corrections remain in `engineering-history/`; none substitutes for S-bound results.

## Run373 successor

`run373-v2.json` declares **14 × 10 MiB padding**, **80 relevant transactions/frame**, **0.75 seconds** cadence, original dispatch/frame/byte/resource limits and linked finalized-source requirements. Padding and native transaction envelopes are generated from immutable inputs. The production clock-error limit remains **3 seconds**.

Wall epoch is **1800000000**; monotonic epoch **100**; wall equals epoch plus monotonic displacement. Integer microsecond advancement occurs only after `clock.begin`. Economic events and finalized timestamps are fixed before execution at `floor(wall_epoch + index × cadence) - 1`. No timestamps are rewritten on receive. The bounded three-frame decoder proof ends at **1.5 modeled seconds**; full 14 × 10 MiB execution did not occur. Native ClockModel rejection proves >3-second incoherence fails. Stale economic events and residence equality 240 fail.

## Run380 successor

`run380-v2.json` retains **240 frames**, **0.27 seconds**, and the **512-transaction mix** (128 Meteora, 48 Pump, 80 PumpSwap, 256 failed). New compressed templates preserve every non-clock economic field; tests compare a canonical economic projection against the unchanged historical templates. Protocol-specific event timestamps are changed only during deterministic fixture construction. Native decoding and required base58 64-byte signature identifiers/envelopes are exercised. These offline signature identifiers are native envelope evidence, not a claim of newly signed chain transactions.

Events and source block timestamps are constructed from the same declared source/economic schedule; economic aging follows wall even while source stalls. The bounded proof processes three eight-transaction frames at 0/.27/.54 seconds. A genuinely stale Pump event inside a fresh source block is decoded natively and rejected by qualification. Frozen economic aging and eligibility-extending timestamp refresh fail. Full 240 × 512 execution did not occur.

## Run379 successor

`run379-v2.json` retains the original **120 × 160** dense execution shape, **0.05 seconds**, 25 maintenance controls, worker limits, source order, continuity/floor assertions, native hot-debt/progress requirements and original safety/recovery/residence thresholds. It additionally declares **100 × 160** native historical seed transactions. Historical seed availability is fixed at epoch-185 plus the seed schedule; a linked empty block1100 establishes current source at epoch before live block1101. No debt reset or deadline-origin refresh occurs.

All seed/live frame bytes are constructed before execution. Construction and native setup keep modeled time at wall1800000000 / monotonic100. Only declared live execution advances it. Old economic/availability timestamps remain historical; the original record-origin-plus-240 residence deadline is not rebased to the current source epoch. Recovery enrollment occurs once through native runtime, retaining source-origin-plus-120.

The separately labeled bounded setup witness uses 100 seed frames of **two transactions each** (200 native hot-debt records), then three two-transaction live frames (six transactions). It proves zero setup aging, original availability preservation, linked continuity, no timestamp refresh and no recovery re-enrollment. It ends at **0.1 modeled seconds**. This bounded variant does not satisfy or shrink the required full dense pressure contract.

Full fixture construction and synchronous native replay code are prepared behind a fail-closed material firewall. Full Run379 safety, recovery, controls/floors, fairness, pressure, resources and durable progress still need authorized full-shape evidence; no throughput/capacity result is asserted from this bounded setup.

## Clock, recovery and residence contract

The plan explicitly declares wall, monotonic, source, economic/event, recovery, residence and observer clocks. Source is the finalized block timestamp; event identity/time is immutable; economic/residence now follows wall. Legal advancement is monotone integer microseconds with a frozen setup epoch. Observer timing, when separately authorized, uses real `perf_counter_ns`, never modeled timing.

Recovery remains **120 source seconds** from the original latched episode. Hot residence and retained residence remain **strictly <240 seconds**. Source lag remains **<45 seconds**. Tests reject wall/monotonic incoherence, stale economics disguised by fresh source, source advancing while economic aging freezes, episode replacement/origin/deadline rebasing, timestamp refresh and equality at 240. Original pressure cohort, owner/archive/commit delays, bursts/pauses, bounds, fairness and integrity gates remain in the plan and gate map.

## Native hot→archive and archive→retirement

Actual source decoding and `ServiceState.source` create the native records. Actual `EvidenceWriter.prepare_and_write_archive`, `ServiceState.archive_commit_slice`, and `ServiceState.retention` mutate them. Read-only SQLite tracing observes transaction BEGIN/COMMIT; it never performs the state transition.

Native generation: `2c949fc610c84fda8004acfe78cbf5b5`. Ten exact input records transition from body-present hot state to a committed durable archive with content hash `25b63c86435ec6fc757eec5e765d5a882db1b6bd3dee9bc2e1c3a6eb9a419091`; archive bytes are retained under `native-archives/native-transitions/`. Before/after identity and record-content hashes are in the raw proof.

Eight archived records actually retire. The other two remain legitimate recent-coverage archived-pending debt; the qualifier does not claim that every archived record must retire at once. Native published floors are Pump1001, Meteora1001, PumpSwap1002. Native maintenance-ledger service/completion advances only after commit. Retirement permits eligibility/floor publication and record deletion within the same transaction; no intermediate polling requirement is imposed.

- `archive_transactions`: `d888e5766cf1e85b2d9733d871614d544a6c04ccd89fa31cbfb8760c93d6c558`.
- `retirement_transactions`: `849ab30c023da3fb900968d0226821ede408421ed0ada35664a370ee719ebe2c`.
- `retirement_transactions`: `a6244a00aae5f81449e8b0981bc6cb2dd53d57732a3789da0517cc60c043da89`.
- `retirement_transactions`: `21b8c1fae5e199256c58f7cf9516cf0e6ec33a561110f4124ade47c7a0f33289`.
- `retirement_transactions`: `3049fa37422618d33f4ee539731f3f8cb8c8f912f6954b8afb19f45cc6544eff`.

Rollback tests show no archive/completion/ledger credit. Transaction identities include generation, database identity, ordinal and exact observed statement hashes, bound again to candidate/assembly in each raw result. Attempted and committed work are distinct.

## Held-reader and checkpoint witness

Actual snapshot-establishing SQL is `SELECT identity,hash,body,archive FROM records ORDER BY identity`. Snapshot read identity is `63bd89ea85e9979620e8329ddbc93690927cd166633fd295018bd1f98128860c`; result hash `20aadd59448a7529e5c363ef6bcead4c7146aa9c0c6642711e60430dbd4b0546`. The read precedes the archive writer transaction `2860b50b35f842514910c1434d9720d0b41b11f35f2f75ff6c6f4b688b0b5250` and remains open across the five actual committed archive/retirement transactions. The reader continues seeing its established snapshot after writer commit.

While held, PASSIVE returns `[0, 580, 435]` and TRUNCATE `[1, 580, 435]`: committed pages remain legitimately reader-blocked. After explicit reader release, PASSIVE returns `[0, 580, 580]` and TRUNCATE `[0, 0, 0]`. Database integrity is `ok`. BEGIN or an open connection alone is never accepted as a held snapshot.

## Pump and Meteora native selection / source progress

Each lane uses its actual native evidence view. Pump selects the captured mint through its native address join; an unrelated candidate is excluded. Meteora selects the captured candidate transaction window with a valid native start boundary; a missing boundary is excluded. Raw evidence records exact selected events/signatures, lane telemetry, generation and durable record identities. No demand vector is fabricated for qualification and no policy changes occur.

Source advances through actual linked finalized receipts, with zero unresolved gaps. Native floors and maintenance progress are read durably afterward. Archive and retirement results exclude rollback/observation-only attempts. The bounded witness establishes native mechanisms; full fairness/resource/source-lag requirements remain future gates.

## Generation fencing and restart / M1

Production rejects stale maintenance decisions, stale completed worker results and stale archive receipts after generation change. Artifact verification rejects cross-generation evidence, raw generation changes and wrong-generation inventory. Stale committed record credit is zero.

The finite 1002-record restart fixture persists a native recovery episode and receipt, commits 512 service records, proves incomplete/rolled-back service is not credited, closes/restarts native state, reconstructs the exact durable ledger and original episode, continues the receipt to 1000 archived records, prevents duplicate completion, continues retirement (998 records), and preserves the native restart continuity gap. Episode rows before and after are identical: `[['program:meteora', 'archive', 1800000120.0, 1800000000.0, 1000]]`. A new owner generation must re-read the original durable receipt; old-generation worker evidence is not transferred.

M1 is a mandatory **independent native regression contract**, not an imported branch repair. It seeds 1928 finite native records, uses `PriorityOwner`, interrupts the real maintenance-completion query with one urgent admission, and attempts the next owner turn. First native archive slice commits **512** records; **488** receipt records remain. The first cooperative yield is nonfatal and the transaction closes, but the pending maintenance decision survives. The next admission fails with `EvidenceUnavailable:maintenance_decision_in_flight` and marks the arbiter failed.

- `decision_completed` = false.
- `next_admission_usable` = false.

The original episode, durable 512-record progress, receipt continuation and integrity are preserved in the failed raw proof. No runtime repair was applied. An eventual integrated candidate must re-earn this gate under its own exact SHA/assembly. M1 has not been merged, and A2 has not been merged.

## Execution identity, assembly and workflow

All source is extracted by Git blob identity from S, with no overlays/generated source and a complete manifest. Dirty/staged tracked content, symlinks, untracked/ignored executable shadows and foreign packages are rejected. Assembly files/directories are read-only; complete membership, modes and hashes are verified before and after every actual trial. Outputs/databases/logs stay outside source assembly.

Trial and child Python processes use `-I -S`, sanitized environment, source-first approved paths, direct compilation of reviewed source instead of cached bytecode, a guarded import finder and an execution audit for dynamic imports. Actual origins/hashes are recorded in-process. Arbitrary trial subprocesses are rejected; the explicit child probe is independently bound. The runtime dependency websockets17.1 has its installed file bytes separately pinned in `dependency-lock-v2.json`; Python3.12.14/interpreter and standard-library bytes are recorded in the assembly identity. The supplemental static tooling is PyYAML6.0.2/jsonschema4.23.0, with actual loaded origins/hashes in the supplemental receipt.

The declaration uses run ID `q2-local-static-deterministic-20261001-7a73165`, attempt **1**, event **local_static_deterministic**. It explicitly records both workflow paths and exact workflow/reusable SHA S. This is local static/deterministic evidence, not a fabricated GitHub Actions run. No workflow was dispatched. Future remote execution queries the actual run identity/referenced reusable workflow and requires exact S, first attempt, pinned infrastructure actions, exact artifact IDs/ZIP digests and unchanged re-read inventories.

Static validation parses YAML, checks candidate/plan/input forwarding, same assembly preflight/trial, exact reusable identity, the complete six-case matrix, four immutable action SHAs, failure-preserving uploads, unique case/trial artifact names, flat exact preflight ZIP content, and always-run aggregation. Workflow preflight and native trials start directly at the assembled bootstrap under `env -i` and `python -I -S`; no root-checkout qualification launcher enters a trial. The root trial CLI explicitly rejects execution. Preflight tar/raw/log artifacts are staged at one flat artifact root, including failed preflight evidence. Aggregation also executes in a sanitized Python process from the reviewed assembly, records128 actual resolved verifier-module origins, and verifies assembly before/after; its failed result is preserved. Transport never supplies the executing qualification verifier from its root checkout. Actionlint is unavailable. The workflow prepares/executes only the bounded v2 matrix; integrated pressure remains separate. Equal tree/different commit, wrong SHA/tree/assembly/plan/input/contract/schema/workflow/attempt, missing/duplicate trial, substituted modules and replaced artifacts are all negative-test cases. The aggregator accepts the exact declared cohort and retains failures; no passing retry selection exists.

## Historical 46 skips

[historical-skips-v2.json](historical-skips-v2.json) and [HISTORICAL_SKIPS.md](HISTORICAL_SKIPS.md) identify all 46 exact historical unittest IDs from durable run36756490388, attempt1, artifact11116354967. ZIP hash `f64223a28818a0c0ee69e1451df623b8550bb1afd28c6c94b368802d090ae457`; raw unittest log hash `afd19c3842af1c00ff5e35f35917d6511e1ceeb67257235469d88e324a4181a0`.

Thirty-three are assigned to prepared-assembly qualification; thirteen to future canonical qualification. Every historical case remains NOT_EXECUTED/passing=false here. Native v2 tests do not silently substitute for those historical cases. No required skip counts as a pass.

## Material firewall and observer — not executed

[not-executed-v2.json](not-executed-v2.json) lists every MATERIAL_PRESSURE case. Classification occurs before full fixture allocation or execution. Unknown/ambiguous cases fail closed. The implemented fixture builders/replay can be statically reviewed, but full pressure, prepared integrated qualification, fixed combined/recovery cohort and canonical qualification were not executed. Existing workload budget was not reset.

The observer contract predeclares exact baseline, complete-workload elapsed-monotonic metric, summed paired estimator, three alternating-order repetitions/no retries, raw-pair validity, workload identity and candidate/assembly/plan binding. It requires raw pairs and uses a finite strict comparator: **ratio <0.01**. Equality, NaN/infinity, missing numerator/denominator, malformed or invalid pairs, mismatched estimator and foreign workload/candidate/assembly/plan fail. Synthetic parser fixtures are comparator tests, not measurements. Historical observer data contributes no v2 acceptance. **Fresh observer measurements: zero.**

## Remaining blockers and hard stop

1. **Required M1 native completion witness fails on exact production base plus qualification-only changes.** The missing completed decision and unusable subsequent owner admission block deterministic readiness. This is observed native behavior, not a missing production observation interface; existing interfaces support the bounded witness.
2. Material/full-shape pressure, fairness, recovery/resource/residence profiles, prepared integrated assemblies, all 46 historical cases and future canonical gates are unearned. Their original requirements remain intact. The synchronous prepared replay does not implement or certify a capacity driver for the retained large combined profiles.
3. The new workflow is statically validated only; no remote run/artifact evidence or fresh observer overhead exists. Eventual integration must freshly bind all such evidence to its exact S/T/plan/assembly.
4. The report publication SHA is different from execution S. It cannot borrow S's bounded evidence as qualification authority for another generation or commit.

Return this deterministic/static package to Astra. No merge, runtime repair, material execution, observer benchmark, candidate freeze, fixed material cohort, canonical Stage E, promotion or Stage F follows this package.

ASTRA_REVIEW_READY:
NATIVE_QUALIFICATION_V2_BLOCKED_BY_WITNESS
