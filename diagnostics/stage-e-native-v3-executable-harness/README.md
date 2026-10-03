# Stage-E native-v3 executable harness review

**STAGE_E_NATIVE_V3_EXECUTABLE_REVIEW_READY — PAPER ONLY.** The final refusal-time lifecycle blocker is repaired and awaits independent re-review. Each WARMING refusal is bound to its exact native observation time, phase, generation and preserved raw SQLite snapshot; final OFF teardown is verified separately. The approved v3 contract is unchanged. A, B and C have not run; zero workload frames were released. The declaration remains PREVIEW ONLY. Stage E remains RED. Stage F remains NOT STARTED. **STOP FOR ASTRA/OWNER.**

The governing package is [`stage-e-native-v3-production-envelope-contract`](../stage-e-native-v3-production-envelope-contract/ASTRA_REVIEW_PACKAGE.md), approved at commit `5ed5aef4dfe1bb7823037fe1ce440c193411a194`. Its complete 192-artifact inventory is verified byte for byte. The native candidate remains S `7a516a6a92be9347661ac0e7f560971c171a0931`, T `9da7d1e1625ba04c1437c63606c90f5e293bdba7`; all 1,241 frozen files retain their hashes and executable modes. Economic and strategy policy files have no changes.

Read [ASTRA_REVIEW_PACKAGE.md](ASTRA_REVIEW_PACKAGE.md) for review scope, [EXECUTABLE_ARCHITECTURE.md](EXECUTABLE_ARCHITECTURE.md) for the process/evidence model, and [FUTURE_DECLARATION.md](FUTURE_DECLARATION.md) for required executor and authority inputs. `EXECUTABLE_BINDINGS.json`, `source_hashes.json` and `package-manifest.json` bind the implementation to the approved contract.

[EXECUTABLE_FIX_REVIEW.md](EXECUTABLE_FIX_REVIEW.md) maps the final blocker and preserved prior corrections to deterministic regressions. This repair starts from exact reviewed executable commit `49bd4cec92c4da58089ac4b0e4df06b44b3fc319`, tree `1285c4f04773685cced555ab18700f26ad575325`. Its 48 manifest-listed artifacts and the manifest itself passed readback before editing; manifest SHA-256 was `4c410207e205ef5da579d39c759cd85a5a1a5d00f5e4610971c9993d63445d34`. All **302 tests pass**, including 94 new lifecycle regressions and the unchanged 55-test contract suite, with zero failures, errors or skips.

Only these commands were used to validate this package:

```bash
export MM_V3_CANDIDATE_CHECKOUT=/absolute/path/to/unchanged-S-checkout
python3 -B diagnostics/stage-e-native-v3-executable-harness/review.py check
python3 -B diagnostics/stage-e-native-v3-executable-harness/review.py inspect
python3 -B diagnostics/stage-e-native-v3-executable-harness/review.py build
python3 -B diagnostics/stage-e-native-v3-executable-harness/review.py verify-package
```

`check` runs finite unit, deterministic, static and pure verifier tests, including the entire approved 55-test contract suite. Tiny opaque gzip records, hand-written SQL tables, abandoned closed socket fixtures and mocked process/resource evidence are unit fixtures. Lifecycle tests call only frozen native read functions and recompute actual WARMING refusals from SQLite backups; full-profile and terminal C verifier routing use mocked unrelated workload/resource boundaries. Campaign tests mock signatures and native proof; their stored permits contain nonauthorizing UNIT payloads. Signature tests use disposable keys and an explicitly nonauthorizing unit payload. `inspect` reads Linux metadata and installed dependency identities; it runs no benchmark, disk-write probe, provider call or native service. `build` creates only a **NOT AUTHORIZED / PREVIEW ONLY** declaration and an unreserved ledger preview. `verify-package` reads every manifest artifact and rejects missing, extra or changed bytes.

`execute.py` is a future material entrypoint with mandatory owner-signature, workflow, executor, runtime, allocation, tape and fresh-ledger admission. It is never called by the review workflow. The material workflow is a disabled `.preview` file outside `.github/workflows`; no material workflow has been installed, dispatched or rerun.

`verify_evidence.py` is a future read-only raw campaign verifier. It imports pure native archive/assessment functions from the exact immutable assembly and cannot launch a workload. C's explicit terminal overload path preserves FAILED_DIAGNOSTIC and can receive only mandatory safety credit after native proof, exact consumed-prefix evidence, resource coverage, signed campaign authority and durable preservation are reverified. A/B require complete successful campaigns. B independently reverifies A's complete campaign using A's own declaration, permit, allocation and ledger. A wrapper stop supplies no native proof.

History remains permanently **OBSERVER_V2: INVALID_PAIR**: trial 1 consumed/invalid; slots 2–6 UNUSED and forbidden; no elapsed-time carry-forward, reuse or acceptance credit. The v3 preview uses a fresh namespace and six UNUSED slots with null elapsed times, reserving no actual trial.
