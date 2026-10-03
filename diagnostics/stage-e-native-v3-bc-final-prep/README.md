# Stage-E native-v3 B/C and final qualification preparation

PAPER ONLY. Stage E: RED. Stage F: NOT STARTED. STOP FOR OWNER.

This is disposable preparation on `diagnostics/stage-e-native-v3-bc-final-prep`, based on approved executable `f480c6b4f7a8442fd148c7ed61bcc4447edaefca`. It adds files only under this directory. It creates no execution permit, campaign registry, material ledger, reserved slot, workflow dispatch, native member, or source feeder. PR #118 remains draft and unchanged.

The frozen contract is `5ed5aef4dfe1bb7823037fe1ce440c193411a194`; S is `7a516a6a92be9347661ac0e7f560971c171a0931`; T is `9da7d1e1625ba04c1437c63606c90f5e293bdba7`; assembly is `08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659`. `FROZEN_INPUTS.json` binds the complete approved executable manifest, tree, contract manifest, infrastructure digest, and all three exact workload hashes. Every executable import first checks the unchanged approved package's 63 files. Contract reads use its unchanged manifest verifier.

## Prepared artifacts

| Artifact | Purpose |
| --- | --- |
| `B_TEMPLATE.json` | Complete observer PREVIEW: frozen workload, envelope, tape, timing, sampling, preservation, verifier, six unreserved identities and three pairs |
| `B_A_PREREQUISITE_SCHEMA.json` | Ten typed A bindings, initially `A_PREREQUISITE_NOT_YET_AVAILABLE` |
| `C_TEMPLATE.json` | Complete synthetic run381 PREVIEW and required safety/restart/refusal/OFF evidence |
| `EVIDENCE_PATH_MAP.json` | Separate exclusive A ingestion, B trial/campaign, C trial/restart/terminal, redundant and final destinations |
| `IMMUTABLE_INPUT_RECEIPT.json` | Explicitly deferred physical receipt; `verified=false` |
| `SHARED_INPUT_SCHEMA.json`, `SHARED_INPUT_BINDING_TEMPLATE.json` | Completed published A-preflight receipt ingestion, stat continuity and signed storage/durability bindings |
| `STORAGE_BUDGET.json`, `B_STORAGE_RESERVATION_TEMPLATE.json`, `C_STORAGE_RESERVATION_TEMPLATE.json` | Integer formulas and unallocated reservation templates |
| `QUALIFICATION_SKELETON.json` | Exact approved 47-gate set, all initially `UNSATISFIED_AWAITING_EVIDENCE`; acceptance text and predecessor mappings retained verbatim |
| `RETAINED_INPUT_SCHEMA.json` | Preserved primary semantic, native, prepared-lane, protocol, origin and full test-transcript inputs; no automatic historical PASS |
| `HANDOFF_PLAN_TEMPLATE.json`, `FAST_HANDOFF.md` | Three bounded readback/verification/preview/review commands |
| `EMPTY_QUALIFICATION_REVIEW.json` | Deterministically blocked final decision with 47 unresolved gates |
| `evidence/` | Allowed-check log, results, adversarial audit and isolation audit |
| `package-manifest.json`, `package.py` | Exact preparation byte inventory and independent-hash verification |

## B and C admission

B remains incapable of admission while any A slot is unresolved. A must be an authenticated, complete, preserved capacity campaign from the exact executable. Supplying typed strings or an asserted PASS cannot satisfy the slot: `verify_bound_B_preview` invokes the unchanged raw A campaign verifier again.

The B order is baseline → observed; observed → baseline; baseline → observed. Six fresh template IDs exist only as JSON. There are no warmups, retries or replacements. All trials use the identical full production workload, tape, executor/hostname/boot, environment and exact 2-vCPU / 8-GiB allocation. The original verifier sums positive integer `perf_counter_ns` durations over three valid pairs and requires `100 * sum(observed_ns - baseline_ns) < sum(baseline_ns)`. Equality at 1% and an observed duration below its baseline fail. No cost is subtracted; setup, teardown, persistence and observer joins stay within the approved timing boundaries. Evidence copying/publication occurs outside those boundaries.

C freezes the approved run381 contention: owner ≥0.165 seconds/frame, archive ≥0.36 seconds/1,000 records, additional commit latency ≥0.006 seconds; source pauses at frames 800 and 1,400 for 8 seconds; held-reader sleeps of 1.25 and 0.1 seconds; completed-tail delay 0.75 seconds. The original raw verifier independently checks threshold-triggered native refusal, pre/post restart SQLite state, new-generation publication, refusal-time WARMING evidence and final OFF. C has no capacity or observer credit. A safe terminal overload can satisfy its mandatory safety disposition; failed or incomplete diagnostic performance remains recorded and cannot automatically satisfy full-profile gates.

## Deferred shared physical inputs

The owner instructed this task to avoid the A workspace and production volume while A preflight is active. No tape was generated, copied, replayed, or physically hashed here; no current production free-space measurement is claimed. All physical/stat/storage fields remain `AWAITING_A_PREFLIGHT_PHYSICAL_INPUT` and cannot become PASS from these templates.

The expected immutable identities are:

| Input | Expected value |
| --- | --- |
| Physical bytes | `2442975789` |
| Physical SHA-256 | `bce25229470bda363d963c441c45e3e7114794d1f3673c0ad4cc4180d39cb583` |
| Frame inventory SHA-256 | `1bc950763062dec84cde1ec59838b609c3f5634e23c184218c98871d3cfc0b5a` |
| 2,223-frame prefix SHA-256 | `2dc21c395ac6439eec8dae5d28ef7b7cd2fd20818e4b86d3c4d9262979c44743` |
| 2,223 decoded canonical SHA-256 | `44410595c3803e983d40d4a89ba1d91dd96df2db715ce1a28d21c51e7804666b` |
| 4,445 decoded canonical SHA-256 | `1cf8f1a30e7ef55d1c5c35737ba3236ef6bca62e892c944652e0e83f6f13a3db` |

`shared_inputs.validate_receipts` reads only independently read-back published receipts. It checks the original A-preflight declaration, physical-hash receipt, original frame inventory and checkpoints; exact path/device/inode/size/mtime/ctime before and after hashing; signed allocation and all capability bytes; original initial/final resource snapshots; reserve and budget derivation; WAL, exclusion, file fsync and directory fsync evidence. Signed capability original paths are resolved by filename and exact signed hash inside the published package, never by opening production paths. A receipt missing stat continuity remains deferred. Scope PID may change between non-material preflight and A; the required executor/hostname/boot and environment equality cannot change.

Importing those receipts reduces packaging work. It does not rehash the physical tape here or waive the approved execution-time hashing, continuity, resource admission or storage checks. Historical free space is never treated as current admission.

## Storage formulas

All variables are nonnegative integer bytes; working, raw and publication bounds must be positive. Let `a` be retained A, `p` retained predecessor evidence, `b` the per-B-trial raw bound, `bm` B metadata, `c` C raw, `cr0/cr1` C pre/post restart state, `cf` failure publication, `cm` C metadata, `fm` final metadata, `w` peak additional working space and `tm` transport metadata.

```
Braw = 6*b
Btrial_redundant = 6*b
Bcampaign = 6*b + bm
Craw = c + cr0 + cr1 + cf
Craw_and_redundant_and_campaign = 3*Craw + cm
Final_one = a + Braw + Craw + p + fm
Total_capacity = 2442975789 + a + p + 3*Braw + bm
                 + 3*Craw + cm + 2*Final_one + w + tm + 12*1024^3
Required_new_free = Total_capacity - 2442975789 - a - p
```

Already-present bytes are removed only from the new-free-space requirement, not total capacity. This conservative plan retains every raw, redundant, campaign and final copy simultaneously; it does not assume deduplication or delete evidence. `storage.calculate` and `storage.feasibility` give exact totals and shortfall by filesystem. Every declared filesystem must fit; free space from different mounts is never pooled. The known lower bound is tape plus 12 GiB; actual A+B+C feasibility remains deferred until genuine A receipts and reviewed raw/working upper bounds arrive. No disk reservation, mount change or deletion occurred here. Future harness reservation templates must contain complete measured inputs and positive bounds and still pass unchanged `attest.reserve_storage` at execution time.

## Preservation and raw qualification

`preservation.py` fsyncs files and parent directories, inventories every regular byte, seals manifests, creates exclusive redundant copies, and verifies copy hashes. Redundant files become read-only. Large future evidence files use numbered blobs of at most 16 MiB; the transport manifest binds original paths, lengths, raw hashes and every chunk. Publication creates only a fresh evidence branch through Git data APIs. It cannot call Actions, create a permit or update an existing evidence ref. Readback fixes an immutable commit, checks the full tree twice, independently rehashes chunks and reconstructed files, and verifies the original seal. Partial, extra, torn, symlinked, mismatched and changed-after-manifest evidence fails. GitHub readback itself gives no campaign credit.

`ingestion.py` delegates campaign/trial/member verification to the exact approved read-only verifier. It checks original owner/allocation signatures and independently trusted keys, terminal ledgers, all trial inventories, resources/lifetime coverage, raw SQLite/origin/source evidence and retained/redundant preservation receipts. B recursively re-verifies A and strict observer arithmetic. C cannot be ingested into an A/B class. Original signed absolute paths and redundant sources must remain available on the future verifier host, including immutable assembly and tape where the approved verifier requires them. The adapter does not rewrite signed declarations or invent replacement preservation receipts.

The final 47-gate skeleton preserves exact approved acceptance predicates. `qualification.generate` accepts raw package references only, recomputes every gate, records verified path/hash bindings and retains unsatisfied states on missing proof. Supplemental retained gates require their preserved primary raw JSON, exact composed four-lane source inventories, before/after hashes, real runtime origins, full successful unittest transcripts matched to statically collected exact-source tests, and a byte-inventory attestation from the independently trusted owner key. This attestation concerns preserved bytes and grants no execution authority. Summaries, manual PASS flags and the historical Observer-v2 invalid pair cannot supply missing proof or observer credit.

Only verified A, six-trial/three-pair B, required C safety, all artifact/preservation bindings and all 47 satisfied gates can yield `STAGE_E_NATIVE_V3_QUALIFIED`. Otherwise the review is `STAGE_E_NATIVE_V3_QUALIFICATION_BLOCKED`, Stage E RED, Stage F NOT STARTED. The decision is for Astra/owner review and cannot start Stage F.

## Reproduction

From the isolated preparation checkout, with a separate unchanged exact-S static-source checkout:

```bash
PYTHONDONTWRITEBYTECODE=1 python diagnostics/stage-e-native-v3-bc-final-prep/run_checks.py /path/to/isolated-exact-S
PYTHONDONTWRITEBYTECODE=1 python diagnostics/stage-e-native-v3-bc-final-prep/build_templates.py
PYTHONDONTWRITEBYTECODE=1 python diagnostics/stage-e-native-v3-bc-final-prep/handoff.py empty-review --output /tmp/fresh-empty-stage-e-review
```

The runner selects only preparation fixtures, the unchanged contract static suite, pure envelope/resource interval tests and pure evidence predicates. It hashes all 1,241 exact-S tracked files before and after; its in-memory source selector points the unchanged contract tests at that disposable checkout. It never runs the full executable suite, native stress, a member, the tape generator, a production workload or a workflow. Reproduction writes fresh test logs, so use an expendable copy; verify the published seal before editing anything. The sealed package is independently verified with `package.py verify --manifest-sha256 EXACT_PUBLISHED_MANIFEST_SHA256`.
