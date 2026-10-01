# Durable integration recovery: bounded validation

NON-CERTIFIED. Stage E remains RED; Stage F remains NOT_STARTED. This report
records reconstruction and deterministic integration validation only. Full
pressure cases, observer measurements, prepared/canonical qualification and the
46 historical Q2 skips receive no execution or certification credit.

The recovered integration was built from durable GitHub components starting at
`4d386498b3dc848e1ba27d11dd8d61841ba426d1`. No unpublished source or result from
the disconnected Cloud session is claimed. The explicit 621-test allowlist was
reconstructed from durable source; it does not claim to reproduce the lost list.

## Durable checkpoints

All checkpoints were published to `integration/stage-e-native-v2-successor`.
The first two preceded long test execution. The third preserves corrections
identified by fresh validation of checkpoint 2. Every checkpoint is WIP and
carries zero certification credit.

| Checkpoint | GitHub SHA | Git tree | Changed files |
| --- | --- | --- | ---: |
| Component map, housekeeping semantic port and deterministic allowlist | `fa5d07fdeb54a5748ef19a3ce4f044672d2bf888` | `c644d1107ef23aa98be2f9db5bf6bf91629853a1` | 56 |
| Complete combined source assembly and worker/crash controls | `430e6ca3a80f7f6dceb7bf03c26a99af1fc2ff7d` | `082774aa1c1550c182f6b60a51c2f14da042bd05` | 15 |
| Callback compatibility and deterministic execution controls | `3c3a1b8f61071a05a52c6163ccad2c26065c073c` | `6b28c7945277accf50a9446dea6891865463ed7a` | 14 |

[checkpoints.json](checkpoints.json) records the complete changed-file lists.
[component-map.json](component-map.json) records component commits, trees, blobs
and content hashes for the production base, M1, A2, the reviewed housekeeping
treatment and corrected Q2 source. Component test results remain historical.

## Reconstructed behavior

Ordinary retirement callbacks retain their zero-argument `retention()` call.
Only a housekeeping-eligible retirement enters a scoped context that forwards
`housekeeping_first=True` to the writer. The context restores its prior state on
return or exception. This preserves custom retirement overrides as well as
ordinary M1/A2 paths. The reviewed housekeeping selector, native three-table
batch and scope loop are verified against the durable treatment. M1 completion
and cooperative interruption accounting remain unchanged.

The deterministic controller extracts the entire exact Git tree into one
read-only assembly, predeclares its digest and content identities, and runs the
explicit allowlist under Python `-I -S`. Production decode workers and lifecycle
crash children enter that same assembly without changing worker count, spawn
context, tasks or arguments. Parent and child import/exec origins are checked;
foreign dynamic code is rejected. Provider attempts are durably recorded before
denial. Intentional SIGKILL is recorded with its startup/execution observations
and explicitly lacks a final receipt. One declared transport fixture may connect
to its own registered loopback listener and is counted separately.

Original M1/A2 tests, production admission/arbiter rules, workload shapes and
thresholds remain unchanged. Q2's plan, schema, gate map, firewall, observer
contract and original 71 test identities remain exact. The integrated input
manifest and an environment-specific hash for websockets' unused console
launcher are disclosed in [controlled-input-changes.json](controlled-input-changes.json)
and [dependency-environment-change.json](dependency-environment-change.json).
All importable websockets runtime bytes match the reviewed lock.

## Fresh validation of the exact published source

Tested commit: `3c3a1b8f61071a05a52c6163ccad2c26065c073c`.
Tested tree: `6b28c7945277accf50a9446dea6891865463ed7a`.
Assembly digest: `acb669db9a720eeae921cb366c6d1ac54151460e0f2d79b2d72406486f641545`.
The assembly contains 1,232 source files totaling 28,935,036 bytes. Execution
used Python 3.12.14, SQLite 3.53.1 and content-pinned websockets 17.1.

| Declared group | Result |
| --- | ---: |
| Bounded production regressions | 528/528 PASS |
| Housekeeping integration | 21/21 PASS |
| Original Q2 denominator, reported separately | 71/71 PASS |
| M1 native prerequisite | 1/1 PASS |
| Combined deterministic allowlist | 621/621 PASS; zero failures, errors or skips |

The deterministic run recorded 482 actual parent origins and 54 bound children:
53 completed and one was the expected SIGKILL without a final receipt. Child
foreign-origin rejection passed, provider attempts were zero, and one registered
loopback fixture connection was recorded. No unknown tests or deferred full
pressure/observer cases were selected.

Preflight and all six bounded native cases passed: clock contract, native
transitions, held reader, generation restart, run379 setup and M1 completion.
Their seven parent and seven child evidence records passed validation against
the original Q2 schema; their source-bound aggregate passed. Six frozen-input
integrity checks and the repository resource gate also passed. The resource
gate processed 2,000 synthetic frames and 240,000 submitted events with 23,248 KiB
peak RSS and zero real provider calls. It ran from the same read-only assembly;
it does not establish continuous-market or physical disk durability.

No full pressure case, observer benchmark, remote workflow, prepared/canonical
qualification or new housekeeping-budget unit was executed. Canonical Stage E
remains RED. These bounded results confer no qualification or certification credit.

## Retained evidence and failed attempts

[VALIDATION_RESULTS.json](VALIDATION_RESULTS.json) records the counters, native
cases, protected-byte checks and exact tested identity.
[validated-3c3a1b8f-evidence.tar.gz](validated-3c3a1b8f-evidence.tar.gz) contains
208 raw result/log/manifest artifacts, including per-test outcomes and child
observations. Its SHA256 is
`b3282b9f396e8a91fafed97d6529d88c0b5da33866e2029b8aedd84405551c53`.
[validated-evidence-manifest.json](validated-evidence-manifest.json) lists every
member's size and SHA256. Archive membership and every content hash were
verified; source overlays and runtime databases are not published.

Checkpoint 2's terminated sandbox-IPC attempt and completed failing attempt are
retained in [checkpoint-2-validation-history.json](checkpoint-2-validation-history.json)
and its separately hashed raw archive. Its completed run had 617 passes, two
failures and two errors, including a loopback connection counted as a provider
attempt. Those observations remain recorded. The fixes preserve the ordinary
callback signature, run relative fixtures from the assembly, permit only the
exact reviewed A2 AST-derived helper, and register the declared local listener.
Fresh results above belong solely to the third published checkpoint.

This evidence publication is a report-only descendant of the tested commit.
It records results for the tested SHA/tree and grants no execution credit to its
own new commit. The next blocking task is review of this exact integration;
excluded pressure, observer and qualification work remains outstanding.
