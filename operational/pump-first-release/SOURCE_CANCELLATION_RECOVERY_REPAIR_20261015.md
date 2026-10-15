# Accepted-source cancellation and interrupted-handler repair

This completes the identified source-level safety correction. It does not rewrite
[a793bd58’s failed market result](COORDINATED_PIPELINE_FINAL_EVALUATION_20261015.md),
recover the live CONTROL interval, establish sustainable throughput, or authorize
a service start. Original RECOVERY_REQUIRED and failed CI 38753995554 remain.

## Demonstrated causes and corrections

* **Optional cutoff:** `rolling_programs` set an optional stop event and awaited
  a child that could remain in an idle read. The original unchanged test failed
  at its one-second deadline. Cutoff now cancels the optional session coordinator
  once; transport reads/writes observe closure, while one owned teardown retains
  accepted handlers, queues and commit workers under the original deadline.
  Repeated coordinator cancellation joins that same teardown. Timeout fails
  closed; it does not renew the shutdown budget or report drainage.
* **Accepted handlers:** aggregate counts omitted identities and incremented the
  returned count only after a successful callback. A bounded current-run ledger
  now records PID/thread, stream/session, handler ordinal, canonical slot/identity,
  scope digest, phase and disposition. Successful return is explicitly distinct
  from durable commit. Interrupted work is associated atomically with verified
  existing candidate gaps or the exact CONTROL replay obligation in the original
  writer transaction. Unknown identities remain unresolved. The existing health
  store retains locators across restart; it is not another evidence/spending
  authority, an ACK or a coverage proof. Limits are 64 interrupted/active records
  and 48 KiB; loss of accounting coverage stops safely rather than pruning work.
* **CONTROL old-session receipts:** immutable identical receipts kept their old
  session, while sealing selected only new-session pairs. CONTROL-only bounded
  reauthentication now requires exact stored-field agreement and freshly
  authenticated parent **and** child. Old receipt bytes/session remain unchanged;
  proof provenance distinguishes both sessions. Disconnect/restart invalidates
  ephemeral eligibility. Missing children, conflicts, old proofs and prospective
  head jumps cannot satisfy the required interval. The original 256-slot overlap
  and completeness requirements are unchanged.
* **Deadline and diagnostic correctness:** a deadline test exposed a shielded
  cleanup task surviving timeout; timeout now cancels that owned task and fails
  closed. The service caps rather than renews the source’s existing deadline.
  Unexpected child cancellation cannot become a global drainage PASS. Required
  handler census fields survive collection and serialization ahead of clipping;
  malformed/missing evidence remains unavailable.

Only the optional transport/coordinator is canceled at cutoff. Accepted business
work is allowed to finish or retains an explicit verified recovery obligation;
consumer failure, rollback or incomplete terminal persistence stays failed.
No shutdown, readiness, queue, provider or Pons 3/5-second protection limit changed.

## Historical attribution and limits

The preserved run counted **564,488 accepted / 564,486 returned / 2 unsettled**
handlers and **33,859 joined frames committed**. A bounded retained-evidence review
links at least one unmatched callback to observation **230166**:
`yellowstone_census_buffer_bound` in `join.feed` with 257 pending slots,
3,698,572 bytes and 16,931 missing logs. Its exact triggering frame identity was
not recorded. The second handler’s identity and precise operation are unavailable;
an interrupted log-buffer wait is a hypothesis, not an established cause.

The new ledger supplies future identity/disposition evidence. It cannot invent
historical identities or retroactively prove those handlers preserved. Likewise,
CONTROL required slot **457279885**, `coverage_after_id=192778` and older unsealed
receipts remain unchanged in authoritative state. Disposable replay tests prove
contract behavior; actual range availability, complete authenticated acquisition
and clearing that live obligation require a later authorized recovery operation.

## Focused validation

All fixtures are disposable and provider-network blocked under the supported
runner, CPython 3.12.14 / linked SQLite 3.45.1. Counts overlap and are not summed.

| Selection | Terminal result |
| --- | --- |
| Original unchanged optional-cutoff test, before correction | FAIL, 1 error / 1, 1.095 s |
| Same unchanged test after correction | PASS, 1 / 1, 0.398 s |
| Source/handler/CONTROL/diagnostic/startup, owner/SQLite and exact held-PAPER combined | PASS, 294 / 294, 33.244 s |
| Original five-module held-PAPER selection | PASS, 79 / 79, 6.130 s |
| Relevant strategy/source guards, policy, nine economics, shared-capital recovery/economics, volume quality | PASS, 158 / 158, 41.665 s |
| Portable configuration identity and failure/redaction paths | PASS, 6 / 6, 0.077 s |
| Explicit CPU capacity, portable configuration, full source guards, continuation, startup integration | PASS, 141 / 141, 52.603 s |

The 294 selection includes actual supervisor/child startup rehearsal and source
owner/queue/session paths, idle reads/writes, repeated cancellation, full queues,
consumer failure, interrupted commit, partial history, receipt/ACK preservation,
restart and authenticated CONTROL continuity. Synthetic correctness fixtures are
not authentic market replay, a capacity result or held-position live proof.

Preserved development failures include one stale lightweight transaction fixture,
a deadline-test interruption, two new-fixture wiring errors, and a new fault
fixture race (ordinary producer return racing the deliberately canceled child).
Each was corrected without weakening the original held-PAPER assertion or timeout.
Their logs and retained failed scratch scopes remain referenced by the release
index. Full final-suite and exact-source CI outcomes are recorded separately in
the final GitHub integration report; focused success alone is not a release PASS.

## Operational and financial boundary

No deployment, PAPER start, provider market request, authoritative write, policy
selection, portfolio reset or infrastructure change occurred for this repair.
The fresh bounded read-only receipt confirms installed a793bd58, inactive/disabled
PAPER with Restart=no, $1,000 cash in the existing epoch, no positions/reservations/
commitments/obligations/pending monetary deliveries or executions, unchanged
historical $500 head 2036 and current monetary head 12608. Existing source drain,
CONTROL marker and all provider counters remain unchanged. This is a current-state
continuity check against authenticated prior reconciliation, not a new bulk
integrity/recovery proof.

The software cancellation/identity contract is offline verified. Another guarded
runtime diagnostic still requires current-state native recovery, actual CONTROL
coverage, usable recovery/storage references, provider/protection readiness and
all other safety prerequisites. The historical unknown handlers are not cleared.
Pump throughput, candidate publication, Pons live acquisition/valuation, original
BUSY/READONLY failures and backup capacity/protection compatibility remain separate.

**Next operational action after source integration:** validate the preserved native
recovery/CONTROL obligation on the target environment through the existing guarded
recovery contract, then measure the previously identified whole-machine capacity
and publication constraints. No live action is part of this GitHub-only release.
