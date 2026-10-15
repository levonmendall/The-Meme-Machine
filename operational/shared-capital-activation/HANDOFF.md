# Shared capital PAPER integration handoff

**Integrated and offline validated; not deployed or accepted for autonomous
operation.** The owner approved the exact fixed caps and two bounded provider
proofs. The corrected proof respected its ceilings but did not certify complete
concurrent provider coverage or deadlines. The original deployed $500 epoch is
unchanged, and `meme-machine-paper.service` remains inactive.

## A. Integration identity and preservation

Repository: `levonmendall/The-Meme-Machine`.
Dedicated branch: `integration/shared-capital-paper-20261007`.
[Published branch](https://github.com/levonmendall/The-Meme-Machine/tree/integration/shared-capital-paper-20261007).
The implementation commit/tree are recorded in `PUBLICATION.json` by a
publication-only child. The final branch head/tree and clean worktree receipt
are supplied with delivery; a file cannot contain its own commit hash.

The starting head was exactly `9ee5d3a400227b0add3d80226430ced47f833590`, tree
`75f7d1948826321291e90c539293316705bf3ca6`. Its tested parent
`9eb7e6d15912ca214de2f5cd1c905abc0b1cedf1`, validated Pons repair
`f6f21a3d10e1e3460122ffb8db016e929ffa5b44`, and shared-capital implementation
`062f4aef04a35539e83f32282de2937497d3d6df` remain ancestors. See
[PRESERVATION.json](PRESERVATION.json) for file/contract checks. The five Pons
repair source files and their campaign tests remain byte-identical to the
published integration candidate. Model B and Pump/PumpSwap canonical machinery
are preserved. No abandoned Model A startup or Stage E campaign was reopened.

All 493 previously recorded remote heads were unchanged immediately before
publication. Publication adds only this dedicated branch; no force push or
preserved/WIP branch edit occurs. Unvalidated Pons WIP remains isolated.

## B. Runtime authority and exact accounting

A verified migration selects `shared-capital.sqlite` through a durable marker in
the original `portfolio.sqlite`. Environment variables cannot reseed or select a
competing cash authority. Missing, corrupt or conflicting selection fails closed.
The original authority is fenced by its existing lock plus SQL triggers, including
against an older executable. The frozen legacy accounting remains readable.

| Native path | Integrated behavior after verified selection |
|---|---|
| Pump Current | Qualified lifecycle reservation uses SharedSleeve; native fills, marks, partial realizations, exits and adds use SharedNativePortfolio through the existing NativeBoundary |
| Pump Survivor | Original qualification/generation fences and native PaperBook; shared entry/add holds and the same native delivery bridge |
| Pons Current | Existing CohortCapital/SelectivePaper retain their journals, identities and integer accounting; shared reservation receipts and native delivery supply/settle capital |
| Pons Survivor | Original survivor book, evidence and commitment machinery; shared entry/add holds and native delivery |
| Recovery | Existing native journal replay resolves durable pending delivery; verified native absence alone cancels an orphaned hold |
| Supervisor/observer/backup/dashboard | Selected-authority readers; coherent read snapshots, original epoch/inception and independent C/D/R/P/O reporting |
| Meteora/Ramses | PAUSED; empty durable manifests without owners/workers; preserved historical attribution; new funding rejected |

The existing allocator/reducer and migration engine are reused. Every writer
reads the latest durable projection under `BEGIN IMMEDIATE`; operation identity,
result and state hash commit together with FULL synchronization. Independent
SQLite connections cannot grant from reconstructed sleeve cash. Ordinary reads
validate the projection without replaying the entire journal or rescanning marks
for risk. Replay is mandatory on a new authority connection and recovery.

A reservation moves R to P when the native commitment is prepared. Consumption
removes that one hold, decreases C and increases D; realization releases basis
and records proceeds/P&L once. An interrupted native delivery retains its economic
clock, hash, sequence and actual commitment. Duplicate replies with a later retry
clock do not duplicate funding. Original sizing, high water, partial fills and
native costs stay in the native books. Signed family cash after shared funding is
historical attribution, never spendable cash; every such step requires verified
shared backing or the complete historical migration mapping.

All regressions reconcile `C + D = E`, `free_cash = C - R - P - O >= 0`, and
`D + R + P + O <= E`, with original inception $500. Shared floors are new-risk
ceilings; they create no hypothetical reservations or fabricated obligations.

Candidate qualification remains native and capital-independent. Exact funding
constraints are durable qualified-but-unfunded outcomes. Current denial does not
suppress Survivor. Only actual native requests trigger fixed rounds; unchanged
heartbeats and observer publication append no allocation events. All four active
producer inbox manifests must be explicit and ready. Paused manifests are durable
empties. Missing active ownership blocks grants while native safety/settlement
continues independently. Native execution freshness and qualification deadlines
are unchanged; allocation does not invent a shorter economic deadline.

## C. Capital efficiency and measured overhead

[PERFORMANCE.json](PERFORMANCE.json) contains the final measurements and original
controlled-tape outputs; [PERFORMANCE_INITIAL.json](PERFORMANCE_INITIAL.json)
retains the earlier measurement. These are **synthetic accounting/workload
results, not predicted market profits**.

The isolated native test funds 21 Pump positions at $6.25, deploying $131.25 and
leaving $368.75 authoritative cash. Native family inception stays $125, including
signed attribution of -$6.25 after using additional shared cash. Replay and exact
conservation pass.

| Identical 21-opportunity scripted tape | Hard family sleeves | Approved fixed shared policy |
|---|---:|---:|
| Individual requested target | $6.25 | $6.25 |
| Funded / qualified but unfunded | 20 / 1 | 21 / 0 |
| Exact denial | HARD_SLEEVE_CAPITAL | None |
| Peak deployed basis / inception utilization | $125 / 25% | $131.25 / 26.25% |
| Cash at peak deployment | $375 | $368.75 |
| Original paused-family cash inaccessible by partition | $250 | $0 |
| Mean discrete-window utilization | 8.3333% | 8.75% |
| Scripted realized net P&L | $4.625 | $5.25 |
| Scripted total costs | $0.25 | $0.2625 |
| Terminal cash / realized equity | $504.625 | $505.25 |
| Maximum asset exposure / aggregate drawdown | 1.25% / 0% | 1.25% / 0% |

The comparator's `stranded_idle_sleeve_usd` is a time average over all inactive
sleeves/settlement intervals, not cash at peak. Cash left by a concentration or
cash-floor constraint is risk-restricted cash, not a hard historical partition.
No funded position is exited to restore nominal budgets.

The actual two-vCPU/eight-GiB Droplet ran a finite 64-request test: four independent
SQLite authority connections, 16 simultaneous four-regime rounds, real durable
native reserve/entry/mark delivery and zero market-provider calls. An independent
FAST suite in another workspace and a brief isolated migration validation also
used the host; this is measured contention, not an idle microbenchmark.

| Metric | Final measured result |
|---|---:|
| Grant latency median / p95 / p99 | 286.54 / 1,676.52 / 1,716.86 ms |
| Missed five-second fixture funding thresholds | 0, all four regimes |
| Request / durable transaction throughput | 3.40 / 23.35 per second |
| Durable transactions / journal events | 440 / 445 |
| SQLite BEGIN wait median / p95 / p99 | 27.95 / 183.93 / 233.41 ms |
| BEGIN waits above 1 ms / app retries / errors | 49 / 0 / 0 |
| Measured wall / process CPU | 18.842 s / 13.759 CPU s |
| Mean process CPU share of two vCPU / peak process RSS | 36.51% / 48.50 MiB |
| Process write bytes / journal database / final WAL | 200,871,936 / 1,462,272 / 6,414,872 B |
| Replay time / conservation | 3.506 s / PASS |

The test funded 15 positions in every regime: portfolio exposure $375; each active
family $187.50; each regime $93.75; each asset $6.25; each network $187.50;
crypto/directional $375. Actual C/free cash $125, D $375, R/P/O zero. Four further
qualified requests, one per regime/two per family, were denied precisely by
`CORRELATED_EXPOSURE:crypto_beta`. No eligible cash was stranded by a historical
partition. Drawdown was zero under marks equal to basis.

The earlier run measured 189.84/307.05/314.55 ms and 5.65 requests/s. Different
concurrent host work means this pair cannot establish a causal performance
improvement. The write amplification and CPU cost are material burst measurements;
they are not claimed negligible. Fixture thresholds exclude provider time and
are not original native opportunity-deadline certification. Complete combined
market/position load and long-duration shared-journal growth remain unmeasured.
The ledger is append-only; storage guards remain in place, and autonomous storage
acceptance must use the final architecture. No new storage/retention engine was
introduced or append-only safety weakened to improve a benchmark.

## D. Preserved trade sizing and economics

`sizing_basis = effective_family_equivalence`, `adaptive = false`. Each of the four
directional regimes retains 5% of realized family-equivalent equity: **$6.25 at the
original $125 family inception**, irrespective of the $500 funding pool or paused
families. Native integer flooring and fees are preserved. In the shared native
partial-realization regression, Pump family equity becomes $125.938, portfolio
realized equity $500.938, native 5% target 6,296 units at $0.001/unit, and remaining
basis $4.688. Unrelated family equity does not receive that P&L. Subsequent
settlement leaves $504.25 cash with zero deployed basis in that fixture.

Pump Current -8% stop/+15% first realization, Pons Current -8%/+18%, 25% first
sales, original ordinary trails, independent Survivor eligibility, common >=2x
right-tail protection/40% peak-profit giveback, original-open 36-hour bridge and
single permitted winner add are preserved. Adds retain 2.5% family-equivalent
sizing, half-original-basis limit, 7.5% post-add ceiling and all original timing,
structure, execution, safety and admission gates. Shared allocation treats an add
as additional actual reserved capital. Archived Meteora economics remain intact.
No alpha or illustrative adaptive sizing was activated.

## E. Authentic epoch and migration readiness

See [DEPLOYMENT.json](DEPLOYMENT.json), [DEPLOYMENT_FINAL.json](DEPLOYMENT_FINAL.json),
[MIGRATION.json](MIGRATION.json), [NATIVE_MAPPING.json](NATIVE_MAPPING.json) and
[BACKUP_READINESS.json](BACKUP_READINESS.json).

| Actual preserved identity | Verified value |
|---|---|
| Deployed commit / service | b577cc1c67f4d64f887b430f5e933f376b607dc2 / inactive, clean source |
| Host | ubuntu-gd-2vcpu-8gb-nyc1; 2 vCPU; 7,941 MiB RAM |
| State root | /mnt/volume_nyc1_1790918115030/meme-machine-paper-v1 |
| Volume / filesystem UUID | 580be5d5-be20-11f1-bb2f-3ee8be45f379 / 0ce00d89-000b-4af1-960f-d5be400ff115 |
| Epoch / original inception | paper-1791089005190643467 / $500 |
| Native positions / reservations / pending deliveries / obligations | 0 / 0 / 0 / 0 |
| Historical native aliases/cursors | Both empty, verified from actual accounting |
| Realized P&L / deployed basis / original cash | $0 / $0 / $500 |
| Original family inception | $125 each, all four families |
| Source sequence / reconciliation | 2,036 / PASS |

Coherent backup: 47 files/17 SQLite databases, verified copy and isolated replay
PASS. Existing DO snapshot `3884b6cb-c204-11f1-b1b3-0210d2110bba` was verified by
read-only API response against the actual volume. Its local application-point
manifest matches the epoch/accounting. An independent restore from that off-host
snapshot is **NOT_RUN**; snapshot existence is not restoration evidence.

The existing migration engine maps all six preserved contracts; actual position,
reservation, obligation, pending/cursor inventories are correctly empty. Isolated
installation, duplicate migration/selection, interruption/restart regressions,
replay, older-binary SQL fencing, shared backup replay and unused rollback pass.
The final actual-copy validator was rerun after operational-reader fixes. No
source epoch, P&L, native ID, cursor, basis or funding was invented/reseeded.

Exclusive future cutover uses the existing stopped-root procedure:

1. Satisfy authentic provider, recovery/off-host restoration and existing safety
   preconditions; use the owner-approved exact policy. Complete outstanding native
   recovery before changing authority. Currently no such economic obligations exist.
2. Stop/freeze all economic writers; verify cgroup ownership, original device/epoch,
   current obligations, complete coherent backup and native mapping again. Reprepare
   the plan from the current verified copy; do not trust this older plan after activity.
3. `cutover.install` takes the original file lock and SQL writer fence, recomputes
   the migration plan, installs/replays the existing shared ledger, then commits the
   durable marker and legacy SQL fences. Its prerequisite flags must be supported by
   actual evidence; disposable test flags in the validator are expressly simulated.
4. Start only the published shared-compatible executable against the same epoch.
   Verify both native families recover before discovery, all four active manifests,
   paused empties, exact C/D/R/P/O, original IDs/cursors and single authority.
5. Run full final-architecture CAPACITY, RECOVERY and AUTONOMY under separately
   authorized finite provider/storage budgets and the existing evidence contracts.

`rollback_unused` is permitted only while the shared ledger contains the migration
and no further durable event. After any durable activity, stop new risk and roll
back only to shared-compatible code using that same ledger/native journals. Never
restart legacy sleeve funding against unaccounted shared activity. No deployment,
unit/env change, actual funding marker or economic cutover occurred here.

Root-disk evidence/workspaces were relocated with byte/hash/metadata verification
onto the existing volume and original-path symlinks; no WIP was discarded or new
storage purchased. Separate preservation work in another workspace also freed root
space. Final available space and identities are in DEPLOYMENT_FINAL.json; capacity
must be checked again immediately before any cutover.

## F. Provider capacity

[PROVIDER_PROOF.md](PROVIDER_PROOF.md) records exact limits, attempts, errors, queues,
coverage and resource limitations. Both finite authorizations were consumed. The
corrected run used 12 Solana/120 Robinhood RPC elements, 12,210 planning RPC CU,
50,331,681 native bytes/98,305 planning native CU and 14,093,147 disposable bytes.
Three gRPC streams and one WebSocket were opened and delivered; native errors zero.
Model B released and canonical replay preserved 287 distinct ingested events.

Its 19.840-second measurement contained only 7.794 seconds of steady activity.
Queue peak 19/64, oldest wait 6.405 seconds; sustained drainage unproven. No complete
Pump/PumpSwap position or rich candidate sample; Pons seven-day Survivor history
incomplete, Current position quote failed. No required deadline or full independent
coverage certification follows from these samples. Neither reduced discoveries nor
fewer streams establish an efficiency improvement. The prior 665-error bottleneck
is **not proven resolved**. Ramses-only acquisition is absent, but its consumption
benefit has no comparable measured baseline. Billed CU, monthly cost, TCP connection
count and whole-process-group resource totals remain unmeasured.

## G. Validation and autonomous readiness

| Check | Result / evidence |
|---|---|
| Final affected runtime/operational modules | PASS: 73 tests, 34.429 s; validation/operational-integration-delta.log |
| Native/concurrency/recovery/migration/economic focused set | 59 applicable cases PASS; one preserved maintenance timeout under concurrent root preservation, later isolated PASS; validation/final-integration-delta.log |
| Original native recovery/nine checks | PASS: 32 tests; validation/recovery-pinned.log |
| Original shared-ledger schema/recovery | PASS: 18 tests; validation/preserved-ledger-final.log; zero-default policy extensions preserve old journal/seed hashes on replay |
| Final reporting cases / syntax / source preservation | PASS: 3 reporting cases, Python compile, JavaScript syntax, diff whitespace and 22 byte-identical frozen files |
| Final quiet preserved maintenance fairness | PASS: 1 test, 11.931 s; validation/maintenance-quiet-final.log |
| Actual preserved-epoch final migration/replay | PASS offline; MIGRATION.json; validation/actual-migration-final.log |
| Broad FAST | FAIL: 832 tests, one pre-existing source-freeze assertion; validation/FAST-final.log |
| Broad OPERATIONAL exploratory run | FAIL: 2,246 tests, seven failures/three errors/33 skips; validation/OPERATIONAL.log; resolved integration failures and preserved baseline cases detailed below |
| Corrected bounded provider proof | INCONCLUSIVE; every authorized ceiling respected; blocker retained |
| CAPACITY | BLOCKED / NOT_RUN; full 3,600 s required on final deployed architecture |
| RECOVERY acceptance | BLOCKED / NOT_RUN; accepted CAPACITY, actual kill/restart recovery and independent off-host restore required |
| AUTONOMY | BLOCKED / NOT_RUN; accepted prior phases, actual attention/dashboard transport, full 129,600 s required |

The broad OPERATIONAL run found five new native-unit sizing failures and one new
mark-clock error; those were repaired and their unchanged behavior assertions pass
in later focused/FAST checks. Remaining source-freeze failure references an earlier
Pons source predating the already-validated f6 repair. Two old IPC tests invoke the
abandoned Model A path without a Model B driver. All three reproduce on unchanged
9ee in an isolated baseline checkout (validation/baseline-9ee-confirmation.log).
The preserved maintenance fairness timeout passed in a quiet targeted run, with no
source/test threshold change. Global suites are not represented as green.

One obsolete shared-feature test prohibited every operational shared-capital import,
which conflicts with the requested integration. Its freeze checks remain and its
activation assertion now verifies unchanged legacy authority/$125 equity/no shared
ledger creation when no durable selection exists. The unrelated failing source
freeze and Model A tests remain unmodified; no production startup fallback was added.

Focused cases cover simultaneous funding/multiple connections, crash before funding,
committed-before-ack, duplicate/changed-clock/out-of-order events, stale generations,
reservations/partial realization/exit/settlement, continuation, staged add/orphaned add,
missing marks/cash/risk limits, paused requests, four-regime competition, incomplete
manifest/round restart, coherent read-only observation, native migration backing and
exclusive/idempotent cutover. Existing suites/recovery machinery provide the property,
race and economic checks; no competing allocator or migration engine was created.

## H. Owner decisions and genuine remaining prerequisites

| Item | Current status | Required next evidence or owner decision |
|---|---|---|
| Numeric fixed risk caps | APPROVED; exact canonical SHA e87385900145e53956df18956ee2390f0d95787e6ffc44243251f9b147eb65f2 | None; use this exact configuration for a verified cutover |
| Deployment access/epoch/storage | AVAILABLE and read-only verified | No access request; reverify immediately before cutover |
| Additional complete provider proof | Two authorizations consumed; complete concurrent coverage/deadlines NOT_CERTIFIED | Authorize a new finite coverage-capable proof budget before further calls; no paid-plan/infrastructure increase implied |
| Independent off-host restoration | Existing snapshot object verified; restore NOT_RUN | Supply/obtain independently verified restoration using authorized existing resources; creating a replacement volume/Droplet is outside this task |
| Owner attention delivery/dashboard transport | Repository paths offline tested; deployed final-architecture delivery/transport NOT_RUN | Actual required route/transport evidence; external test messages need explicit instructions |
| Combined allocator/native deadline and sustained storage evidence | Short allocator measurements only; material write cost recorded | Final-architecture bounded capacity/storage evidence; do not assume negligible overhead |
| Final PAPER cutover and acceptance | NOT_DEPLOYED; CAPACITY/RECOVERY/AUTONOMY BLOCKED | Complete genuine prerequisites, exclusive preserved-epoch cutover, then full required windows; no temporary sleeve-funded acceptance campaign |

No risk approval, deployment access or epoch-reconciliation blocker is fabricated.
Implementation readiness, synthetic utilization and offline replay are not live
PAPER acceptance. The safe repository work is published; unresolved authentic
provider, restoration and operating evidence remains explicit.
