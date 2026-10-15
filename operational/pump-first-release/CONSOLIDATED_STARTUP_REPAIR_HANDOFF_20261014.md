# Consolidated startup repair — 2026-10-14

Implementation: `1fe5a6f62d37f84ad24f0b7413279c080e3424e5`, branch
`engineering/targeted-resolution-20261014`. Final FAST on publication
`36ed4d94c4366d84041ff991d76f97b1b6590fa2` completed: **2,155 tests / 1,356.754 s,
zero failures/errors, one disclosed skip** (configured service identity unavailable
on the hosted runner). Its executable and tests are identical to the implementation.
The complete terminal log and receipt are retained in
`blocker-repair-20261011/CONSOLIDATED_STARTUP_FINAL_VALIDATION_20261014.json` and
[Actions run 38644441056](https://github.com/levonmendall/The-Meme-Machine/actions/runs/38644441056).

## Workflow continuation — 2026-10-14

The owned branch fast-forwarded cleanly through workflow merge
`893640f2fbf323e64e943cced9976f65766e420e`. Read root `AGENTS.md` and
[the operational-resolution skill](../../.agents/skills/meme-machine-operational-resolution/SKILL.md).
They are materialized in this sparse checkout. The merge changes instructions,
CI triggers and oversight documentation only; no application, fixture or test
source changed. It has no separate FAST result, and is not represented as a new
tested executable. The existing exact-executable results above remain applicable.

The owner's latest instruction authorizes continued **offline engineering only**.
The earlier observation preparation stopped before any installation, configuration
change, service start, provider request or authoritative write. No observation
was dispatched. Completed small read-only preflight notes remain in the evidence
root as `CONSOLIDATED_OBSERVATION_*_PREFLIGHT_20261014.json` and
`CONSOLIDATED_OBSERVATION_NATIVE_PREFLIGHT_STOPPED_20261014.json`; they do not
establish fresh native recovery or confer runtime authority.

Use one integration/test owner, affected network-blocked tests during development,
the existing integrated startup rehearsal for lifecycle changes, and one complete
FAST on a finalized changed executable. Run the applicable OPERATIONAL gate before
any separately authorized deployment. Do not repeat full suites for this
documentation/workflow continuation or restart the closed historical-replay search.
Preserve the existing failure register below; select a further source correction
only when a causal mechanism is demonstrated. No new live start is authorized.

The existing native and provider agents completed a narrow source-only review
under this workflow; neither found another causally demonstrated, unfixed defect
that supports an additional offline correction. They ran no tests or operational
probes. The completed cancellation, explicit Pons recovery path, provider feedback
and recording repairs remain intact. The public cooldown/queue conflict is still
reproducible by the retained offline regression; it is an intentional safety
boundary, not permission to bypass cooldown or increase the queue allowance.

One lifecycle coverage limitation remains explicit: Pump initialization precedes
the runner's loop-level `finally`. The missing-evidence startup rehearsal closes
its own fixture resources and does not prove graceful production cleanup for
every early startup exception. This review did not establish that boundary as a
new production failure or justify a broader cleanup change. See
`tests/test_integrated_startup_rehearsal.py` and
`tests/test_pump_cancellation_diagnostics.py`. Current-generation accumulation,
complete native recovery/drain, historical SQLite attribution and managed-provider
capacity still require the already specified runtime evidence or new causal
artifacts; no such evidence was generated in this continuation. Preserve the
prepared observation specification without executing it under offline authority.

PAPER remains stopped/disabled, `Restart=no`, funding closed. Installed source is
still `66f85d61bf4d3ba9a01efdc0e9eb68949419bda8`. No new deployment, PAPER start,
market-provider request or authoritative write was performed by these repairs.
The preceding one-start authorization is consumed. This is an offline candidate,
not operating readiness or acceptance. The original result remains
`RECOVERY_REQUIRED`.

## First fatal and preservation

The authorized attempt started at **21:20:29 UTC**. Pons PID `2796620` raised
`BoundaryError: paper_policy_transition_cohort_evidence_unavailable` in
`runtime/robinhood/pons.py:recover_cohort`, called directly by
`pons_selective_cohort.run` during startup. Recovery inferred native capital from
the shared canonical candidate-plane directory. Actual native capital existed in
the lane directory. This was a policy-recovery path error, not a demonstrated
provider, hardware or market-throughput failure. A numeric failing native thread
ID was not retained for this Pons exception; do not invent one.

Supervisor PID/native thread `2796147` sent Pump PID `2796619` TERM at
21:21:13.3768, waited the original 15 seconds, then sent KILL at 21:21:28.377.
Pump exited `-9`. This establishes the current escalation caller, not the caller
of an older incident or OOM. Empty unit scope after 59.640 seconds is not native
drainage. Current native recovery remained unfinished.

Post-attempt read-only financial replay verified **8,902 events**, cash
**$1,000.00**, conservation, and zero positions, reservations, commitments,
obligations or pending monetary deliveries. The seven new journal events were
one `runtime_admission`, four `runtime_owner`, and two `runtime_publish` actions.
Capital policy/inception and the historical $500 state are unchanged. A bounded
previously verified sample of 24 pending canonical/history/proof identities is
still present; all eight sampled history bodies remain checksum-valid and
unconsumed. This is not a whole-store or native-recovery PASS.

The v1 policy-selection checkpoint committed before TERM is preserved. Old
`a70e261` lacks its compatibility handling, so it was **not** restored. Only saved
compatible small unit/environment overlays were restored, without a start.
Installed `66f85d61` stays stopped; it still contains the now-repaired startup
error until a new installation is separately authorized.

## Supported corrections and dependency register

| Dependency | Evidence / disposition |
| --- | --- |
| Pons shared plane → native capital | **Demonstrated and corrected.** Pass `ROOT/pons-selective-cohort-capital.sqlite` explicitly to `recover_cohort`; keep legacy colocated callers. Same fixture fails under old inference and passes with original authority. All policy/replay/flat/release checks remain. |
| Pump initial attachment → cold shared-capital replay | **Demonstrated and corrected cancellation.** Authentic disposable input shows SQLite setup under 1 ms per observed phase, then replay continuing after TERM until KILL. Constructor-only cancellation checkpoints now roll back the read and close connections. |
| Pump native attach cleanup | **Corrected and fault-tested.** Close the native book if attachment fails; preserve the first exception even if cleanup fails. Already committed policy selection, journal and pending state remain. |
| Early TERM → native health | **Demonstrated and corrected.** TERM before the first two-second heartbeat previously lost active operation/signal facts. Final wake records them; bounded publication serialization prevents a late heartbeat overwriting STOPPED. Recording unavailability never grants reconciliation. |
| Supervisor → policy/child configuration | Existing v1/default and canonical-route forwarding retained; actual launch-command/environment and native entry seams tested. No second scheduler/consumer introduced. |
| Canonical owner → historian → consumer → exact ACK | Actual disposable constructors and commit/reopen/replay/ACK exercised. Missing history remains incomplete; accepted pending identities survive cancellation and BUSY. No historical replay/capacity claim. |
| SQLite connection/transaction failure | Real disposable delivery BUSY and existing attribution/READONLY tests pass. The historical source SQLITE_BUSY mechanism and lock holder remain **unattributed**. No timeout, retry, durability or checkpoint change. |
| Pons admission / HTTP rejection / fallback | Existing adaptive batch feedback, inherited deadline, spacing, accounting and bounded context recording retained and tested. Public eight-second cooldown versus five-second guard remains an **operating constraint**, not bypassed. |
| Managed Pons mandatory reads | Prepared route retained; no current Robinhood request reached transport. Method/filter coverage, account-wide concurrency/utilization/terms, freshness and complete quote+USD protection remain **live/account-dependent**. Owner-reported 10,000 CU/s alone is insufficient. Exact factory 40-block proof is not extended to other filters. |
| Pons READONLY INSERT | Original cause **unresolved**; essentials-first worker recorder/tests retained. No speculative permission/database repair. |
| Sustained Pump processing | **Unresolved/live-dependent.** This attempt has no current-generation usable interval. Earlier arrival/economic/publication deficits remain evidence, not a controlled before/after comparison. |
| Recovery/backup | Valid prior recovery reference remains distinct from failed 2026-10-14 backup. Backup failure and process-group freeze versus protection deadlines remain separate blockers. No backup/timer/storage mutation or repeated bulk verification. |

The replay callback is scoped only to `pump.accounting_restore` and the initial
read-only constructor verification. It is cleared before a verified owner can
be reused. Ordinary monetary mutations, protection and settlement do not gain
cancellation checks. No partial replay populates the verified-prefix cache.
Full replay remains required on resume and was not made faster. Scoped exact
source pins reverse only these reviewed infrastructure nodes before applying
the original combined strategy/economic guards.

All six `paper-opportunity-access-v1` changes remain active, together with the
nine earlier economic changes and attention-only volume-quality behavior.
Current/Survivor independence, genuine winner duration, sizing, compounding,
partial exits and scaling are unchanged. Meteora/Ramses remain paused.

## Validation and measurement scope

- Pons policy/recovery: **19 PASS / 1.523 s**.
- Pump cancellation/shared-capital/recovery selection: **48 PASS / 18.267 s**.
- Final coherent targeted OPERATIONAL: **293 PASS / 62.290 s**, no failures,
  errors or skips, including a clean **nine-case startup rehearsal**.
- Earlier 293-case run had one legitimate old-wrapper source-guard failure.
  Exact successor normalization was added without changing its economic pins or
  negative assertions. Initial rehearsal API/fixture/timestamp errors and a new
  SETTLED expectation error are preserved, not relabeled passing.
- Final required FAST: **2,155 tests / 1,356.754 s**, zero failures/errors and
  one disclosed hosted service-identity skip; complete direct job log and
  exact-source receipt retained above. The actual-host access guard remains
  mandatory before any separately authorized service start.

Pinned local CPython is **3.12.14**, linked SQLite **3.45.1**, two host CPUs.
Hosted CI pins CPython 3.12.14 and two-CPU containment; its linked SQLite build is
not inferred from local results.

Matched narrow authentic monetary/native attachment fixture (all three input DB
hashes identical): before **15.862 s / KILL -9**; after **0.792 s / exit 0**,
TERM-to-finish **5.03 ms**, `STOPPED`, operation `CANCELLED`,
**`reconciled=false`**. This proves cooperative interruption of initial replay,
not complete recovery, cold replay acceleration or whole-machine throughput.

The rehearsal uses real supervisor subprocess ownership and actual lane/native
initializers, books, historian and history protocol. Provider/session/market-step
boundaries are controlled. Its synthetic $500 child mechanics are not the
operating $1,000 portfolio, live admission or held-position proof. Real evidence
socket/provider continuity, sustained capacity, full quote+USD deadlines and
complete live recovery remain outside its scope. Startup failures before the
runner loop's finally are not reported as successful native reconciliation.

## Retained evidence and next decision

Persistent evidence root:
`/root/Documents/Codex/2026-10-10/the-meme-machine-eliminate-redundant-data/blocker-repair-20261011/`.
Original private attempt:
`/var/lib/meme-machine-diagnostics/20261014-integrated-combined-211136/`.
Original files, journals, usage and failed fixtures remain intact. Key locators:

- `INTEGRATED_OBSERVATION_ANALYSIS_20261014.json`, journal/controller logs;
- `INTEGRATED_OBSERVATION_POST_FINANCIAL_RECONCILIATION_20261014.json`,
  `INTEGRATED_OBSERVATION_POST_PENDING_SAMPLE_20261014.json`, compatible rollback;
- `PUMP_NATIVE_STARTUP_CANCEL_COMPARISON_20261014.json`, original and corrected
  attachment receipts; original failed fixture `/tmp/mm-engineering-glhgnwaz`;
- `INTEGRATED_PONS_COHORT_AUTHORITY_REPAIR_20261014.json`;
- `CONSOLIDATED_STARTUP_OPERATIONAL_FIRST_20261014.log`, affected-case log and
  `CONSOLIDATED_STARTUP_OPERATIONAL_FINAL_20261014.log`;
- `CONSOLIDATED_STARTUP_FINAL_VALIDATION_20261014.json` for the terminal CI record.

Actual attempt usage: **one Solana HTTP/logical request, 20 CU, 43 HTTP bytes,
zero Robinhood elements/native openings or delivered native bytes**. Frozen
conservative model **$0.0000105**, not a provider invoice. No meaningful market
throughput, Pons quote/USD or held-protection interval was exercised. Acceptance
remains **zero minutes**.

The single successor proposal is
`CONSOLIDATED_STARTUP_NEXT_OBSERVATION_SPEC_20261014.json`. It preserves original
300-second readiness, 900/900-second diagnostic allowances, 1,800-second work stop,
65-second shutdown reserve and 1,865-second absolute boundary. It uses the same
actors, existing managed route, 2/10-RPS profiles, enumerated writes and safety
limits. No retry, allocation admission or acceptance transition is proposed.
Its purpose is to measure current-generation accumulation after the corrected
initialization and identify one causal intervention, or stop with the precise
remaining limitation. Funding closed does not mean read-only.

**Do not execute it without new owner authorization.** Before a permitted start,
verify terminal exact-source release checks, fresh financial obligations and
native resumability separately, preserved v1 state compatibility, actual service
identity/access, applicable recovery reference, mounted reserves, provider
controls and a natural backup-free window. Do not rewind state or mistake
disabled finite diagnostic overlays for a normal continuous PAPER service.
