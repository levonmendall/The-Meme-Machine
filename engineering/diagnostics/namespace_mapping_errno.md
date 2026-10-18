CI39084155482 on `aba344d9954d190ccbe8291a696ea8452ca6e4ab` reached the
original namespace canary as nonroot. USER unshare returned successfully, then
the fixed setgroups deny write raised PermissionError. The generic diagnostic
retained its stack frames but omitted errno. The original availability test
therefore failed, rather than inventing an availability result.

The correction preserves all three mapping writes, their exact values/order,
the preceding USER unshare and every subsequent namespace/security check. A
fixed-name helper catches only OSError carrying an actual integer errno in
1..4095 and raises the existing Blocked type with an operation-specific code.
Missing/invalid errno and non-OSError failures retain their original behavior.
The generic main fallback, test assertions, availability rule and all kernel
operations remain unchanged. No failure can resume mapping, mount or probe work.

Disabling setgroups is required before an unprivileged gid_map write; successful
USER unshare does not justify omitting it. The recorded PermissionError alone
does not distinguish LSM policy from proc mapping/DAC restrictions. This is
separate from the Landlock copied-main package trust failure, which occurred
before a copied child was launched and does not require user namespaces.

The seven new regressions plus the unchanged eleven-case namespace module
passed18 cases in0.874 seconds under the supported FAST network guard/Scratch
driver. Independent code review cleared runtime SHA256
`1be8af8f10462771d4f422b550fb2ee33954a7f057e633d691fb02c00e0e6136`
and new-test SHA256
`dda6759c4891fc10cca464269ec1a9b7088f67098df2001514563f788d2b09d5`.
This component changes runtime diagnostic source bytes. The frozen346 complete
source proof must be explicitly updated before combined validation; its old
unchanged-byte claim cannot be reused. No AWS kernel, native throughput,
financial recovery, normal PAPER or release acceptance is established here.
