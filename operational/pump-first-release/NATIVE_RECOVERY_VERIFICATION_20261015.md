# Current native-state resumability — 2026-10-15

**NATIVE_RECOVERY_VERIFIED**, scoped to **SAFE_TO_BEGIN_EXISTING_GUARDED_RECOVERY**.
Current state is consistent in the checked recovery scope; existing owners can
resume incomplete work under their original fences. No separate recovery-only
operation is needed merely to replace the retrospective shutdown gate.

Executable remains `ba25499b26103ec5d14f1ce765c8e8f180695f33`.
Verification source: `839be8b2d3e745696b259de333deec886ba7148e` on
`repair/consolidated-startup-followup-20261014`, draft PR 133. Production source
is byte-identical to ba25499b. No speculative compatibility repair was added.

The original forced-stop `RECOVERY_REQUIRED` remains unchanged. This decision
neither turns that event into graceful drainage nor certifies completed future
startup, readiness, full-store integrity, market capacity or held protection.

| Current-state finding | Verdict and evidence |
| --- | --- |
| Financial/native ownership | VERIFIED: $1,000 cash, exact projection and raw journal head 8,982 match completed replay; native books and sleeves flat, no monetary obligations. Historical $500 untouched; existing preservation proof reused. |
| Source/policy/epoch | VERIFIED: epoch `paper-shared-1000-20261011T071207Z`; six active v1 changes, nine economics and volume behavior unchanged. Pump Survivor's exact predecessor, 90 retained candidates and missing selection are supported incomplete lazy restoration at the verified flat boundary. No history or genesis is rewritten. |
| Canonical continuity | VERIFIED: source session/body and three durable cursors match prior receipt. Startup remains WAIT_FOR_DURABLE_PUBLICATION/released=false; correct program checkpoint keys are absent. Incomplete publication is retained, never reported complete. |
| Delivery/ACK preservation | VERIFIED in named cohorts: 32 current identities = 21 authentic exact compact ACKs + 11 pending; all 24 older outbox/history/proof identities retained. No loss, duplicate or false completion found within those checks. |
| Ownership/leases | VERIFIED at inspection: no active consumer or historian lease; same-file writer lock unheld; persisted runtime/Pons owners dead. Existing restart must still obtain exclusive ownership. |
| Interrupted restart/cancellation | VERIFIED offline: actual consumer/historian process kills, retained pending replay, unchanged events/receipts, new-token/current-session ACK fencing, stale source/proof rejection, original deadlines and lifecycle cleanup. |
| Population totals/full-store census | UNAVAILABLE; indexed prefixes prove at least 257 records each, not totals. No bulk copy or integrity scan. |
| Actual new runtime recovery, throughput, provider/held protection | UNAVAILABLE; not executed and not inferred from disposable fixtures. |

No current-state safety invariant failed. Legitimate pending work is not a reason
to require completion before recovery begins. Existing `EvidenceWriter` flock and
restart gaps, `FinalizedFence` session invalidation, `HistoricalTasks` lease reclaim,
`PrewarmStartup.begin` released=false and exact `acknowledge()` receipt/generation
checks provide the recovery contract. Missing evidence still blocks the affected
qualification/publication. No writer, timeout, deadline, strategy or storage
contract was changed.

## Focused validation

Pinned CPython 3.12.14 / SQLite 3.45.1; supported network-blocked runner and
contained disposable state. No complete FAST or OPERATIONAL campaign was launched.

- Actual integrated rehearsal + lifecycle: **19 PASS / 3.161 s**, zero skips/errors.
- Eight additional recovery/crash/source-guard cases passed in a nine-entry run
  that **FAILED** due to one incorrectly named test class. Correct named ACK case:
  **1 PASS / 0.178 s**. Do not relabel that failed run as passing.
- First two-case new-fixture run: one failure from assuming inline events instead
  of existing canonical references. The fixture now verifies resolved economic
  identities/order and exact references/receipts. Final rehearsal above passes;
  no production change was necessary. All original failed evidence is retained.

There are 28 distinct passing checks across these scoped runs, not one uninterrupted
28-case suite or general release PASS. Prior valid ba254/c8 proofs remain separate.

Read-only canonical probe: **106 bounded queries / 0.037792 s**, no errors.
An initial large count stalled in disk I/O and was terminated after 26 seconds;
that exact process was reaped and no replacement population scan was run. A
preliminary wrong-scope checkpoint query was invalidated; final verification uses
actual `program_scope()` keys. Final monetary comparison also corrects reporting
sequence 8,983 versus raw journal head 8,982; raw prior/current heads and complete
projection match. These probe mistakes are retained, not application defects.

## Amended gate and next operational boundary

Replace “previous worker must have drained gracefully” with: **the current
source/policy-compatible authoritative state is consistent and can safely enter
the existing guarded recovery, with pending work preserved and ownership fenced**.
The original failed drain remains historical evidence. Any new corruption,
conflicting owner, unexplained missing accepted work, obligation mismatch or
unsupported migration still stops dispatch and requires correction/review.

The three-start campaign allowance remains **0/3 consumed**. It can resume under
this explicitly amended current-state gate once its operational retry scope is
approved and fresh ordinary preflight passes. This verification does not start a
service or add runtime authority. PAPER remains stopped/disabled, `Restart=no`,
funding closed; installed clean source remains `66f85d61`.

The next operational question is whether the repaired implementation completes
native restoration within the original readiness requirement, and where current
acquisition/join/owner/persistence/history/ACK/publication accumulates work while
managed Pons runs. Use the existing bounded controller and safeguards; no new
recovery platform, provider feed, forced trade, deadline extension or unchanged
retry is justified. Runtime must accurately report incomplete reconciliation;
startup/diagnostic time remains outside acceptance.

Evidence index: [native-resumability-verification-20261015.json](evidence/native-resumability-verification-20261015.json).
Private artifacts remain in `/root/Documents/Codex/2026-10-10/the-meme-machine-eliminate-redundant-data/blocker-repair-20261011` with exact hashes in that index. Final safe-state
receipt is `NATIVE_RESUMABILITY_FINAL_SAFE_STATE_20261015.json` at 00:19:26 UTC;
original result bytes remain SHA256 `234a147368e2b9b337fdb5248ca7a1c7a363e07aa0e421503d5dc0c1d3335fe8`.
Independent throughput, original BUSY/READONLY, managed protection and backup
issues remain open. No deployment, provider call or authoritative write occurred.
