# Stage-E native-v3 executable harness review

**STAGE_E_NATIVE_V3_EXECUTABLE_REVIEW_READY — PAPER ONLY.** This package implements the external A/B/C machinery. It grants no execution authority. A, B and C have not run; zero workload frames were released. Stage E remains RED. Stage F remains NOT STARTED. **STOP FOR ASTRA/OWNER.**

The governing package is [`stage-e-native-v3-production-envelope-contract`](../stage-e-native-v3-production-envelope-contract/ASTRA_REVIEW_PACKAGE.md), approved at commit `5ed5aef4dfe1bb7823037fe1ce440c193411a194`. Its complete 192-artifact inventory is verified byte for byte. The native candidate remains S `7a516a6a92be9347661ac0e7f560971c171a0931`, T `9da7d1e1625ba04c1437c63606c90f5e293bdba7`; all 1,241 frozen files retain their hashes and executable modes. Economic and strategy policy files have no changes.

Read [ASTRA_REVIEW_PACKAGE.md](ASTRA_REVIEW_PACKAGE.md) for review scope, [EXECUTABLE_ARCHITECTURE.md](EXECUTABLE_ARCHITECTURE.md) for the process/evidence model, and [FUTURE_DECLARATION.md](FUTURE_DECLARATION.md) for required executor and authority inputs. `EXECUTABLE_BINDINGS.json`, `source_hashes.json` and `package-manifest.json` bind the implementation to the approved contract.

Only these commands were used to validate this package:

```bash
export MM_V3_CANDIDATE_CHECKOUT=/absolute/path/to/unchanged-S-checkout
python3 -B diagnostics/stage-e-native-v3-executable-harness/review.py check
python3 -B diagnostics/stage-e-native-v3-executable-harness/review.py inspect
python3 -B diagnostics/stage-e-native-v3-executable-harness/review.py build
python3 -B diagnostics/stage-e-native-v3-executable-harness/review.py verify-package
```

`check` runs finite unit, deterministic, static and pure verifier tests, including the entire approved 55-test contract suite. Tiny opaque gzip records and mocked snapshots are unit fixtures, not native workload frames. Signature tests use disposable keys and an explicitly nonauthorizing unit payload. `inspect` reads Linux metadata and installed dependency identities; it runs no benchmark, disk-write probe, provider call or native service. `build` creates only a **NOT AUTHORIZED / PREVIEW ONLY** declaration and an unreserved ledger preview. `verify-package` reads every manifest artifact and rejects missing, extra or changed bytes.

`execute.py` is a future material entrypoint with mandatory owner-signature, workflow, executor, runtime, allocation, tape and fresh-ledger admission. It is never called by the review workflow. The material workflow is a disabled `.preview` file outside `.github/workflows`; no material workflow has been installed, dispatched or rerun.

`verify_evidence.py` is a future read-only raw campaign verifier. It imports pure native archive/assessment functions from the exact immutable assembly and cannot launch a workload. An incomplete or invalid campaign cannot earn acceptance. The C classifier separately reports diagnostic performance and mandatory native overload safety in preserved `MEMBER_RESULT.json`; a wrapper stop supplies no native proof.

History remains permanently **OBSERVER_V2: INVALID_PAIR**: trial 1 consumed/invalid; slots 2–6 UNUSED and forbidden; no elapsed-time carry-forward, reuse or acceptance credit. The v3 preview uses a fresh namespace and six UNUSED slots with null elapsed times, reserving no actual trial.
