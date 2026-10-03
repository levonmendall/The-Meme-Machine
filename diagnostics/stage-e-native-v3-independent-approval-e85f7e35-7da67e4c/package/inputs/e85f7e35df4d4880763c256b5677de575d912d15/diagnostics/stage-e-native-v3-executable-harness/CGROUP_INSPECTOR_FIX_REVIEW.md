# Native-v3 cgroup inspector applicability correction

**STAGE_E_NATIVE_V3_EXECUTABLE_REVIEW_READY. PAPER ONLY. STOP FOR ASTRA/OWNER.**

The approved inspector rejected the captured runner hierarchy because it required a CPU quota/period row. The complete read-only diagnosis proves that CPU and cpuset are available at the true root but not distributed to its children. Descendant interfaces are consequently absent. Memory is distributed through the runner ancestry and has explicit unrestricted limits. This correction replaces that row-presence heuristic with independently verified controller applicability. It confers no production admission or elapsed-time credit.

The executable base is `f87c72cf2a15e3c099a8bd07acad3b0737d9dd27`, tree `09c48ee0601c4ef12dcef53a027bf2eb02e634a6`, package manifest SHA-256 `b69d6cc95b478b03bafeeb4f7598abe668c141069fb58ebcea0e70ec6016926f`. The publication is a direct descendant of authoritative diagnosis commit `3ba04753e531b6c5e180f49f3da94e71c079b05b`, tree `f35dfeef25b13dd3bb48a2bab4c8c867c1651e54`. All eleven diagnosis-manifest artifacts and its manifest remain unchanged. Raw evidence SHA-256 remains `1a9bf5779ba44d30c65f522d11fe5db3bd349e846276434e0cc095cb372149a8`.

## Executable scope and evidence model

Only `harness/attest.py` changes production executable behavior. No other executable module, workload adapter or workflow is changed. Tests and package/review metadata are the remaining changes.

Each captured ancestor retains version, absolute filesystem/cgroup paths, membership, mount root, directory device/inode, namespace identity and raw interfaces. `PRESENT` retains exact text, including empty values; `ABSENT` has no invented value; `UNREADABLE` retains its failure. Explicit `max` and numeric limits remain different raw values. Documented root exceptions are a separate annotation validated against actual ABSENT evidence at the proven true root. Compatibility numeric columns exist for the existing admission comparators, but are independently rederived and must match raw evidence; they cannot establish applicability or completeness.

The pure verifier parses the captured membership and mountinfo bytes. It requires scope/reader/PID1 cgroup and mount namespace agreement, matching visible cgroup mounts, mount root `/`, correct devices, a true v2 root directory inode of 1 and every root-to-leaf ancestor exactly once. Visible resource-controller mounts without corresponding membership ancestry, delegated mounts, missing/duplicate ancestors and unsupported threaded domains fail.

For every v2 node, enabled controllers must be available there. A non-root node's available controller set must equal its parent's `cgroup.subtree_control`. Every controller applicable to that node requires its documented interfaces, regardless of that node's outgoing subtree enablement. Missing non-root resource files pass only with the complete top-down proof that their controller is not applicable; contradictory unexpected interfaces also fail. Root resource-interface exceptions apply only to the proven true root and never substitute an unlimited value.

The collector computes its informational `complete` field from this proof. Admission and both existing pure resource-verifier routes recompute the proof themselves. A forged `complete:true`, rehashed resource chain, empty error list or rebound UNIT allocation digest cannot bypass missing or contradictory evidence. A captured `complete:false` still refuses admission. The existing ancestor limit comparators inspect every row, including restrictive parents above a disabled child subtree.

Legacy v1 retains its explicit quota/period, cpuset and memory limit comparisons, complete visible mount/membership coverage and unlimited sentinels. Its old-kernel effective-cpuset fallback is backed by the explicit configured cpuset; absent memsw is not RAM evidence and host swap must independently remain zero. Separate v1 unit cases check this path and restrictive limits. No v2 absence uses those legacy fallbacks.

## Deterministic validation

On Python **3.12.14**, the full executable review suite passes **368/368**, with zero failures, errors or skips: all **322** previous tests plus **46** new tests. The unchanged approved contract suite independently passes **55/55**. The pure resource-attestation/verifier subset independently passes **104/104**. The new cgroup module has **44** cases: **33 rejection tests** (30 v2, three legacy v1) and eleven positive/evidence/collection cases. Two additional raw timeline verifier rejection tests bring the new negative total to **35**.

`tests/fixtures/diagnosed_host_cgroup_v2.json` is a static, nonauthorizing projection of the authoritative raw diagnosis. Its regression compares every relevant interface against both preserved initial and final observations and checks the original raw digest. It passes cgroup completeness only with complete, consistent causal evidence. The separate `test_envelope.fixture()` remains a UNIT allocation dictionary without a signed production envelope. Mocked collector tests read only predetermined dictionaries; the correction performs no live resource collection.

| Required rejection | Deterministic regression in `test_cgroup_applicability.py` |
|---|---|
| 1. CPU enabled, `cpu.max` absent | `test_reject_CPU_enabled_for_child_with_cpu_max_missing` |
| 2. Ancestor quota below two CPUs | `test_reject_CPU_ancestor_quota_below_two` |
| 3. Restrictive quota above disabled propagation | `test_reject_CPU_quota_above_disabled_child_subtree` |
| 4. Enabled cpuset missing effective interface | `test_reject_cpuset_enabled_with_effective_file_missing` |
| 5. Cpuset excludes a production CPU | `test_reject_cpuset_excluding_production_CPU` |
| 6. Restrictive cpuset above disabled propagation | `test_reject_cpuset_above_disabled_child_subtree` |
| 7. Memory max below 8 GiB | `test_reject_memory_max_below_eight_GiB` |
| 8. Restrictive memory at any applicable ancestor | `test_reject_memory_limit_at_every_applicable_ancestor`; also above disabled propagation |
| 9. Contradictory availability/enablement | `test_reject_contradictory_controllers_and_subtree_control` |
| 10. Enabled controller unavailable from parent | `test_reject_controller_enabled_without_parent_availability` |
| 11. Hidden/missing ancestor | `test_reject_missing_middle_ancestor`; `test_reject_hidden_true_root` |
| 12. Namespace/mount visibility mismatch | `test_reject_namespace_mismatch`; delegated root, mount mismatch and root directory cases |
| 13. Unreadable required interface | `test_reject_unreadable_required_controller_interface` |
| 14. Forged completeness | `test_reject_forged_complete_true`; independent raw timeline re-verification |
| 15. Root exception outside documented root | `test_reject_root_exception_outside_root`; impossible root resource interfaces |
| 16. Missing interface without causal proof | `test_reject_missing_limit_without_disabled_controller_evidence` |

Further cases reject forged parsed limits, empty effective cpusets, missing enabled memory interfaces, unexplained resource files, inconsistent incoming enablement, duplicate ancestors, threaded domains and unbound visible controller mounts. Existing envelope, signatures, storage, process/thread lifetime, continuity, restart, preservation, prerequisite and observer tests are retained. Existing test method bodies are unchanged; only the envelope's common UNIT cgroup fixture is upgraded to the complete raw schema, and the resource-interval module adds two tests.

The initial restricted-sandbox run encountered four Unix-socket fixture permission errors and a missing historical Git object. Historical objects were fetched read-only, and the suite was rerun with the local permission needed for closed abandoned-socket fixtures. No tests were skipped or weakened. No socket service or provider workload was run.

## Preserved authority and next blocker

Frozen candidate S `7a516a6a92be9347661ac0e7f560971c171a0931`, T `9da7d1e1625ba04c1437c63606c90f5e293bdba7`, all 1,241 source files/modes, reviewed assembly, approved contract `5ed5aef4dfe1bb7823037fe1ce440c193411a194` and its 192-artifact inventory remain unchanged. A/B/C bindings, all prior executable repairs, historical Observer-v2 evidence and the forbidden historical slots remain unchanged.

Exactly two allocated dedicated vCPU, exactly two visible/online CPUs and exact affinity, exactly 8 GiB allocated RAM, no swap/balloon substitution, no competitors, runtime identity, storage/headroom, signed capability evidence and process/thread lifetime monitoring are unchanged. `signed_document()`, process collection, resource monitoring and both resource-verifier executable modules are unchanged. **The separately trusted signed allocation envelope remains required and has not been supplied. The diagnosis commit is not that envelope.**

The existing PREVIEW declaration refreshes only infrastructure identities; its campaign, environment, timing, workload, rules and unreserved ledger are retained. No new campaign, ledger reservation or production declaration is prepared. Earlier environment inspection is retained without renewal. This task runs `review.py check` and `verify-package`, not `inspect`, `build`, fresh preflight or a workload entrypoint.

Stage E remains **RED**; Stage F remains **NOT STARTED**; A preflight remains **BLOCKED**. Preflight executions, A/B/C runs, native service loops, source-frame releases and consumed A slots are all **zero**. No host/systemd/cgroup/affinity/kernel/runner/cloud setting is changed. PR #118 remains draft and unmerged. Independent executable re-review is required before any separately authorized fresh preflight. **STOP FOR ASTRA/OWNER.**
