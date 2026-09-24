# Single-workflow execution control handoff

Implementation is ready for parent review and integration. No commits, pushes, workflow dispatches, cancellations, provider calls, or state-branch writes were performed by this subtask.

Owner authority is `evidence-reconstruction-20260924-one-market-v1`, in `certification/single_campaign_authorization.json`. It permits one new workflow containing fresh smoke followed by one hourly campaign when smoke passes and native positions are verified flat. It prohibits successor runs, replacements, market workflow reruns, dispatch retries and separate position continuations regardless of the outcome.

The old run `35956802640` is recorded as externally observed cancelled state. This repair did not request its cancellation.

## Files owned by this subtask

- `.github/workflows/four-lane-certification.yml`
- `.github/workflows/position-continuation.yml`
- `.github/workflows/prospective-cohort-review.yml`
- `.github/workflows/evidence-reconstruction-certification.yml` (new)
- `.github/workflows/single-campaign-launch.yml` (new)
- `certification/single_campaign_authorization.json` (new)
- `certification/single_campaign_control.py` (new)
- `certification/prospective_program.py`
- `certification/smoke_continuation.py`
- `certification/protocol_freeze.py`
- `certification/tests/test_single_campaign_control.py` (new)
- `certification/tests/test_prospective_program.py`

No change to the profitability protocol is required by these controls. The separately frozen execution envelope restricts scheduling authority. Historical acceptance economics and qualification criteria remain untouched. Parent owns the successor cohort/source identity updates and final integration.

## Durable behavior

The authorization uses a separate append-only Git state ref named `cert/single-campaign-<first 16 hex characters of digest(authorization_id)>`. Its record is `certification/SINGLE_CAMPAIGN_STATE.json`. Non-forced ref updates serialize competing claims. There are no mutation or dispatch retry loops.

Before dispatch, the launcher verifies its own exact workflow/branch/run-attempt identity, an exact runtime ref, a terminal-success full non-market certificate with matching artifact/source identities, and the runtime's committed Python/JSON/patch/workflow bytes. The bound identity contains runtime SHA, executable tree digest, implementation digest, source-manifest digest, source-diff digests, lane policy/version identities, protocol digest, and execution-configuration digest. The single-run parameters are fixed to fresh smoke 600 seconds followed by hourly 3,600 seconds, `program=false`.

The launcher checks all pages for all five nonterminal statuses (`queued`, `in_progress`, `waiting`, `pending`, `requested`), including all job pages. Known offline certificates/reviews and materialized generic CI test jobs are not confused with market work. Other launchers and historical cohort-review workflows are treated as campaign-capable. Unknown queued workflows fail closed. Missing, duplicate, truncated or search-capped listings fail closed.

It then commits the consumed dispatch intent before the one HTTP POST, and performs another complete quiet inventory immediately before that POST. A network timeout, HTTP ambiguity, CAS collision or new competing market run cannot authorize another POST. The already-consumed state remains the durable stop.

The market workflow must claim that intent before any provider work. `run_attempt > 1`, wrong SHA/ref/workflow/nonce, a duplicate claim, or a phase repeat fails closed. The same run may enter smoke once and hourly once. Hourly requires the prior smoke phase to be successful and natively flat, plus the existing smoke artifact review and readiness gates.

The same authorization's already-consumed launcher may still be uploading its receipt when the market run starts. Claim/phase contention checks exclude only that exact stored launcher ID, after independently verifying its workflow, branch, attempt and stored launch SHA, and the current market run. All other launchers remain conflicts. The launcher never performs market work and its dispatch permission has already been consumed.

All paths halt after the authorized workflow. Open or unknown native exposure is recorded as `HALTED_UNRESOLVED`; no position is declared settled or rewritten. A cancellation that prevents final bookkeeping still leaves the one-shot intent consumed, so no automatic follow-up is possible. Native archives and the ordinary failure artifacts remain authoritative for recovery review.

Four-lane push triggering was removed. Moving the canonical branch to the certified SHA therefore cannot start a market job. Legacy program `start`, `claim`, `advance`, `retire` and direct successor `dispatch` are blocked under the envelope. Position-continuation is rejected before restoring state or touching a provider. Smoke-continuation register/complete are also blocked before API construction or state mutation, closing their direct continuation-dispatch path; historical readiness remains read-only. Current cohort review is read-only. The original automatic-continuation/program workflow blocks remain present for historical protocol checks but are unreachable under the mandatory one-shot claim and explicitly exclude `single_campaign=true`.

## Parent activation sequence after the final tree is stable

1. Commit/publish the repaired integration on `repair/evidence-reconstruction-20260924` with **both** `[evidence-reconstruction-cert]` and `[non-market-cert]` in the message. The new wrapper invokes the full exact-SHA `non-market-certification.yml`. It has no market launcher or recovery/successor job.
2. Wait for that exact wrapper run to complete successfully, and verify its full non-market job and artifact. Do not change the runtime SHA after this certification.
3. Create a new runtime branch such as `cert/single-market-evidence-reconstruction-20260924` pointing at that exact certified SHA. Its name must match `cert/single-market-[a-z0-9-]+`. No four-lane push trigger exists.
4. Refresh all active statuses and current halted predecessor state as directed by the parent. Do not launch if any market work is active/queued/pending/requested/waiting or unresolved predecessor exposure remains.
5. Create a **separate launcher-only commit**, parented from the certified runtime, on `launch/evidence-reconstruction-single-20260924`. Add `.github/single-campaign-launch-request.json` with exactly these four fields, replacing placeholders with the real certified values:

   ```json
   {
     "runtime_sha": "FULL_40_CHARACTER_CERTIFIED_RUNTIME_SHA",
     "runtime_ref": "cert/single-market-evidence-reconstruction-20260924",
     "certification_run_id": 123456789,
     "authorization_id": "evidence-reconstruction-20260924-one-market-v1"
   }
   ```

   Use `[single-market-launch]` in this separate launch commit's message. Do not place this marker on the runtime/certification commit. The launcher reads the request, checks out the already-certified runtime, and performs the guarded single POST. It never changes that runtime or canonical ref.

6. Observe the resulting sole `four-lane-certification` run to terminal. A failed smoke, pending native position, failed hourly run, cancelled workflow or ambiguous dispatch consumes this authorization; **do not rerun, replace, retry, dispatch continuation or launch a successor**. Preserve/report the exact state and native handoff instead.

The durable state and artifacts `single-campaign-dispatch-*`, `single-campaign-claim-*`, `single-campaign-terminal-*`, and the normal smoke/hourly archives support the final owner report.

## Verification performed

Command:

```text
python -m unittest certification.tests.test_single_campaign_control certification.tests.test_prospective_program certification.tests.test_prospective_acceptance certification.tests.test_smoke_continuation -v
```

**46 tests passed**, including 24 new single-run tests. They cover duplicate and ambiguous dispatch, consumed authority, failed/colliding persistence, exact identity/configuration drift, nonterminal certificate rejection, all active statuses, second run/job pages, ambiguous/capped inventory, current-vs-other launcher distinction, run-attempt rejection, one-time claim/phase entry, zero successors/continuations, and preserved unresolved native exposure. The legacy dispatch retry regression is explicitly scoped to the historical control by mocking the new envelope prohibition; current control behavior has its own independent tests.

All five changed/new workflow YAMLs parsed successfully. Python syntax and `git diff --check` passed. Full exact-SHA hosted certification and market activation remain the parent's explicit next actions after integration.
