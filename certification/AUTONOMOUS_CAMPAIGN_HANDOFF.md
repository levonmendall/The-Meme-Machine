# Autonomous repair and certification campaign — 2026-09-20

This is an append-only continuation of SOLANA_ALCHEMY_EFFICIENCY_HANDOFF.md.
The user explicitly authorized implementation repairs, full deterministic verification,
fresh 600-second smoke and an independent 3,600-second four-lane observation, including
bounded replacement runs after implementation defects. Prior handoff-only pauses are
superseded for this campaign. No merge to main, policy change, signing, transaction
submission, paid provider, increased rate ceiling or narrowed market scope is authorized.

## Reconstructed starting state

Fetched origin and GitHub PR/workflow state before edits. Main remains
`54712c4c6470cc4dc267888f934bd693aac030d0`. Draft PR91
`repair/four-lane-observability@acb7e51127c66e89fc524d81408bdb4a0afec629`
stacks on `cert/one-hour-repair-campaign`; draft PR92
`repair/robinhood-cu-efficiency@a34c5d4dce4dc93445b837cfeeb51901825bdb9f`
stacks on PR91. Draft PR93 `repair/solana-alchemy-efficiency` stacks on PR92;
its starting exact head was `1d92a1360b82460beb461ae89795b85b630eff80`.
Newer PR94 was closed after Pump-pressure work was integrated into PR93.
The remote strategy admission branch remains at
`0982519a68222b7cd0640981a7ac4a8ac7c119dd`, uncomposed at starting head.
Workflow 35542891347 passed deterministic CI, not a four-lane market smoke.
An isolated detached worktree preserves prior local worktrees.

Exact current lane source/policy/config hashes: `results/campaign-policy-integrity.json`.
The descriptive source table in the older handoff predates later Pump/Meteora sources;
`sources.json` and the fetched lane heads are authoritative. All four existing overlays
reproduced byte-for-byte at campaign start. Their latest composed versions are checked
using a fresh private Git index: `results/campaign-overlay-reproduction.json`.

## Preserved smoke and diagnostic evidence

Latest completed smoke 35539161434 used
`0653621edb2a4fa5bfdc0922a1c42149b2774975`, before the newest Pons repair.
Artifact 10614203841, SHA256
`cbbc55c40f4ca3cf9c0b7869ed53998a4affb9d5adedf3d402546dcefe74c4b2`,
was downloaded, checksum verified, extracted and inspected. It retains raw RPC responses,
per-lane ledgers, journals and failed/unresolved evidence. It achieved 600.1215 seconds
of overlap with zero restarts but failed engineering on one unresolved Pons position.
Pump settled two natural paper lifecycles; Pons settled one separate natural lifecycle;
Meteora/Ramses zero. Forced settlements zero. No historical exposure was modified.
The full structured baseline is `results/campaign-baseline-35539161434.json`.

The two Pump getProgramAccounts HTTP 429s were independent concentration scans:
different mint filters, minimum slots, session identities and timestamps ~76 seconds
apart, each retry_count=0. No duplicate scan is proven or deduplicated. The retained
raw requests identify them exactly. Meteora had zero signature-method 429s across 64
getSignaturesForAddress members, with one complete economic vector. Sustained pressure
and efficiency still require the new campaign.

Pump's old raw transport archive records five requests already expired on arrival at
the transport wrapper and one governor deadline. Neither is a provider failure.
Consumer-level expiration counts are separate per-signature interests, not opportunity
counts. The old artifact cannot fully resolve every lease/cooldown/queue cause; it is
not retrospectively relabeled using the new instrumentation.

## Targeted cancellations

Superseded legacy Pump diagnostics were accidentally triggered by repair commits lacking
qualification-build markers. Run 35542697441 at f0ab87c was in progress; run 35542796805
at b9c8113 was pending. Both belong to this campaign and conflict with clean provider
capacity. The cancellation workflow was narrowed from cancel-everything to exact
run ID + SHA + branch + workflow allowlisting. Commit
`a2a4daa2459b729c4feff462f71cd19b7ffc09e0`, cancellation run 35545355369, succeeded.
Both targets were subsequently verified cancelled. Original workflow artifact retention
ran for the active diagnostic: artifact 10616038438, SHA256
`bf3a4986dc2b06d113e998e30d0d12d40278ec99868e9956f730274e3c96407e`.
The pending diagnostic had no artifact because its live job never started. Cancellation
audit artifact 10616212792, SHA256
`ebd437a3b93a50e3ce92a669703f484577203220f3e0f477feeb1dec361c0216`.
No unrelated workflow was cancelled. Waiting is not counted as uptime.

## Composed repairs

1. Strategy admission: extracted only semantic changes from 0982519 relative to its
   original lane source plus overlay. Did not install its obsolete full-file overrides
   or apply the branch twice. Pump uses finalized event progress/trajectory/demand and
   extension before expensive RPC evaluation, with optimistic concentration only for
   admission. Same-slot later events cannot enter an earlier event's vector. Screen
   failures and incomplete screens remain durable; later events can re-enter. Pons
   performs authenticated current-state preflight before trajectory/window acquisition.
   Current-state queue, screens and expensive admitted work are separate pipeline stages,
   including when later evidence fails. Full qualification stays authoritative.
2. Pons pending terminal exit: the latest upstream repair could still abandon an
   impossible exit already marked exit_pending. Preserve its intent, amount, original
   hold clock and recovery. At original max hold, reauthenticate full remaining size,
   current curve state and unchanged five-second freshness/finality before a writeoff.
   Recovered liquidity requires actual exit; provider/authentication errors cannot prove
   writeoff. The ledger records zero proceeds and loss of remaining basis, with exact
   replay and capital conservation. Existing immediate fill-feasibility check remains.
3. Local admission observability: requests that never reached transport no longer enter
   provider-error counters. Append-only acquisition phase records distinguish enqueue,
   already-expired work, leases, physical capacity, shared cooldown, actual transport,
   provider 429 and post-transport late results. Consumer deadline decomposition and raw
   request IDs, parameter identities and original deadlines remain separately visible.
4. Canonicality: source_integrity now requires exact byte equality without stripping
   whitespace. All lane source SHAs and protected policy/config/workflow bytes remain
   unchanged. No change to the adaptive starting batch of eight or provider ceilings.

Changed operational lane files are embedded in the canonical Pump, Meteora and Pons
patches. Integration changes are in governor.py, worker.py, run.py, sources.json,
test_evidence_priority.py and this campaign's evidence/handoff files.

## Verification record

Commands:
- python -m unittest discover -s certification/tests -v
- python -m certification.run prepare --worktrees <isolated-directory>
- python -m certification.run verify --worktrees <isolated-directory> --output <gate-directory>
- Fresh private-index read-tree/apply/diff reproduction of each overlay.

Initial full deterministic pass succeeded before final attribution/test refinements.
Final full pass and hosted exact-revision gate results will be appended below.
No local test result is claimed as prospective natural execution or profitability.
Live launch requires fresh workflow hygiene, all hosted gates, exact source integrity,
600 seconds overlap and normal drain. No earlier smoke time is reused.

## Final local verification

All 1208 lane tests passed: meteora 390, pons 272, pump 288, ramses 258. All 68 supervisor/capacity/accounting tests and all three resource gates passed. Complete transcripts and SHA256 hashes are in `results/autonomous-local-verification/`. Four overlays are byte-reproducible; current source SHAs and frozen file hashes are unchanged. New regressions cover same-mint re-entry, Pons preflight avoiding trajectory/window calls, pending impossible exits, fresh durable writeoff proof, stale/provider rejection, and local expiry attribution. The prospective candidate still must pass hosted gates before live observation.

## Published candidate and prospective run

Candidate `9ef7addcf9d5fb0ca2cc106f0f0a512b4c475bef`, exact tree `58699261dbbddc0f5384df6c78acb440ab3dd501`, was published by fast-forward to PR93. Combined workflow **35545908034** runs hosted gates, a new 600-second smoke, and only after readiness a separate fresh-process 3,600-second observation. All active/queued/pending/waiting workflows were checked immediately before publication; none conflicted. Paper-milestone workflow 35545908051 passed including all three qualification overlays. No live success is inferred from these gates.

## Failed smoke 35545908034 and implementation replacement

Hosted deterministic/resource/source gates passed at `9ef7addcf9d5fb0ca2cc106f0f0a512b4c475bef`.
Pons exited unexpectedly after 135.208 seconds; continuous four-lane overlap was only
135.205191673 seconds. Its traceback proves `worker.py` raised plain TimeoutError for
an expired pre-transport batch outside the native BoundaryError contract. This escaped
the cohort's candidate-local failure handler. No position was filled or left open.
The run is engineering FAIL and NATURAL_INCOMPLETE; no hour launched.

Pump also showed a concrete local scheduling defect: locally rejected batches entered
provider failed-member fallback and attempted individual retries under the same expired
deadline. Repairs preserve native Robinhood BoundaryError for local wrapper admission,
stop Solana local failures before retry/fan-out, check the original deadline on both
sides of local pacing, and exclude unattempted HTTP from physical/provider failures.
Single/batch regressions cover expired consumers, pacer expiration, governor deadlines
and queue capacity. `run.py` now carries the separate local-admission counters into the
consolidated report. No source strategy/economic/finality threshold changed.

After observation cutoff, all four books reported zero open exposure at elapsed 966s.
Campaign mode prevents new Pump admissions after that cutoff. The superseded failed run
was cancelled during idle follow-up by exact-ID/SHA/workflow allowlist, commit
`28ff61cb112726c6ff4012062035a1659121571f`, cancellation run **35547017619**.
This is not normal drain or certification time. Cancellation audit artifact 10616674531,
SHA256 `59971f3ad34fd4b911a4de600a719a19913e3878c96c7b5828782e676e0f7493`.
Failed-run artifact **10616574835**, SHA256
`e5a9566fb59b6e7e2df34c974437004b1dcc37bdf7f9ec375e2ba33c8bf36752`, was downloaded
and checksum-verified. All original bytes remain retained. Pump's gzip footer was
incomplete on cancellation; complete flushed records remain readable and this limitation
is recorded rather than silently repaired. Other three raw streams closed normally.
Structured evidence/traceback is `results/failed-smoke-35545908034.json`.

Final observed physical requests: Pump748, Meteora367, Pons163, Ramses130. No HTTP-status
or RPC-code provider errors were recorded. Pump had zero getProgramAccounts scans in
this market sample; no duplicate scan claim is inferred. Local wrapper failures were
Pump22 expired-before-transport plus10 governor deadlines, Pons1 expiration. Full
consumer/acquisition phase decomposition is retained in the structured evidence.
Natural/forced settled counts were zero in every lane, all open-position counts zero.
Meteora retained broad inventory and completed economic vectors without signature 429s.
Pons has no natural terminal-drain proof in this failed run because it never filled.

Replacement local verification passed all **1212 lane tests** (Pump290, Meteora392,
Pons272, Ramses258), **69 supervisor tests**, and all three resource gates. Logs/hashes
are in `results/local-retry-verification/` and `results/deadline-repair-verification/`.
Fresh-index overlay reproduction and unchanged protected bytes are in
`results/deadline-repair-overlay-reproduction.json`. Hosted exact-revision verification
will rerun before an entirely fresh 600-second smoke and gated independent hour.

## Replacement candidate launched

Candidate `128d744a795d3a465dbf4b5e7719fd9f75930ee8`, workflow **35547208867**,
starts from fresh processes after all in-progress/queued/pending/waiting runs were
verified empty. Exact hosted gates precede its new smoke and conditional independent
hour. The previous run supplies no observation time. PR93 remains draft and unmerged.

Detailed preserved transport inspection: failed smoke Pump getTransaction batches were
at most eight members (453 eight-member transports), despite the internal adaptive
controller's higher recovery ceiling. No sixteen-member transport was used. Pump raw
local rejection groups were nine eight-member batches and 23 singles, consistent with
the reproduced futile fallback path. Meteora issued 91 getSignaturesForAddress members
with zero HTTP/RPC errors. This is sample-specific pressure evidence, not certification.

Interim replacement smoke observation: at least 600.483357096 seconds concurrent overlap, no unexpected exits through observation cutoff. Pons completed one natural market-sale lifecycle with realized loss 68,952,100,088,225 native quote units; zero remaining basis/unsettled exposure and both native conservation checks true. Pump one qualifier reserved then cancelled at the unchanged entry-fill timeout, not counted as a trade. One Pump getProgramAccounts HTTP429, no getTransaction or Meteora signature HTTP429 reported through cutoff. Final artifacts/drain still pending; these snapshots are not certification.

## Artifact review supersedes automatic smoke readiness

Smoke artifact **10617471527**, SHA256
`cc7fff38b4de386dcc5803639de8cd5eeee11b9b611e7bd316c9294210047f73`, was downloaded
and verified. Automated smoke engineering PASS, normal exit of all four lanes and
600.483357096-second overlap are retained as observed. Manual campaign review is FAIL
because the artifact proves a further pending-entry priority defect. Both statuses
are retained in `results/smoke-35547208867-review.json`; the workflow gate's narrower
PASS is not represented as full campaign certification.

Exactly one physical Pump getProgramAccounts scan was issued: sequence101,
session e07e19f6-784f-4925-9e69-dc60e61252b8, mint
HS9mD6Au5NzhijuShWSqSceDwzzUbDakVE3bwVynzpKG, minContextSlot448891790,
timestamp1789950115942076199ns, HTTP429, retry_count0. No duplicate physical scan.
All14 local wrapper rejections were eight-member batches with original deadlines;
none fanned out to singles. Provider HTTP/RPC attribution remains intact. Full consumer
loss decomposition and imperfect opportunity completion remain visible in the artifact.

Pump's sole qualifier reserved at1789950115, original due1789950117, original timeout
20 seconds. Position-priority RPC sequences103–104 returned at1789950126.499 with
finalized block time1789950116, correctly too early. The same thread then performed
research priority50 requests105–109 and priority20 hydration110–116 until1789950136.700.
The next position quote117–118 completed1789950137.493 and was correctly rejected as
late. The 10.994-second research interval between position checks is the implementation
defect, not permission to extend the timeout or accept a stale quote.

The repair adds `_service_pending_entries` at every existing main-loop pending-fill
service point. Reserved entries retain lifecycle authority until fill/cancel; active
positions are monitored every service cycle. Finalized stream observation continues
in its existing threads, and research resumes afterward. Delay, economic policy,
20-second timeout and freshness/finality checks are unchanged. Expired reservations
are checked before another provider quote and after blocking quote return. Regressions
reproduce the too-early quote followed by research starvation, prove recheck before
research resumes, and prove pre/post-transport timeout boundaries.

Successor hourly job was stopped, not reused. Cancellation commit
`539c289f2f32c079a7bad9f89762a6d353ba2f52`, run **35548993805**, targeted only campaign
35547208867 at128d744. Latest pre-cancel snapshot had zero exposure in all lanes;
interrupted artifact last snapshot154.815591215 seconds overlap also has zero exposure.
Artifact **10617383134**, SHA256
`a92df116e0628320791313671ddb1e4ced36f2dca412adcd71a315846ecbf59f`, downloaded and
verified; zero seconds accepted toward certification. Cancellation audit10617522963,
SHA256 `da5128bec64c40ebe984f4f93843ce1ac47fa2d163c880d845c72a600fe12b1d`.
All cancelled-run raw bytes remain retained, including incomplete gzip footers.

Pons smoke natural lifecycle is fully retained in the review file: entry native cost
2504757786400000 (input2500000000000000 plus entry gas4757786400000), exit gross quote
2440589798215775, exit gas4784111904000, realized net proceeds2435805686311775, realized
PnL -68952100088225. Quote fees were25000000000000 entry and24652422204199 exit, already
included by the authenticated curve calculation. Entry tokens298006298460952339660474;
entry/exit ledger times1789950430/1789950489, reason momentum_failure. Qualification
vector, quote states, minimum-fill bound, execution-cost model and replay are preserved.
No separate provider billing is invented from estimated compute units. Immediate
full-exit check was executable; no writeoff occurred. Native cash999931047899911775,
remaining basis0, unsettled0, replay verified and both conservation checks true.

Entry-priority replacement verification: **1214 lane tests** (Pump292, Meteora392,
Pons272, Ramses258), **69 supervisor tests**, all3 resource gates pass. Logs are in
`results/entry-priority-verification/`; canonical overlays/frozen-file verification in
`results/entry-priority-overlay-reproduction.json`. A fresh smoke and independent hour
are still required. No prior failed/superseded observation time is reusable.

## Pending-entry candidate launched

Candidate `752dd501266359eb56db2bbe6e9362f306af40bd`, workflow **35549221493**,
was published to PR93 after the repository-wide active/queued/pending/waiting workflow
check was empty. Hosted exact-revision gates precede its fresh smoke and replacement
hour. PR93 remains draft and unmerged; prior campaign evidence remains appended.

## Accepted smoke at 752dd501 and independent hour

Workflow35549221493 smoke completed normal drain with600.1143855829998 seconds overlap,
all exits0, no restarts/unexpected exits, all accounting reconciled and zero exposure.
Artifact10618127519 SHA256 `3c5402eb38dec15d8a84da44de310ebddff04d750c95e688a0800900146e6d2f`
was downloaded and verified. Automated and artifact-review engineering status PASS;
review is `results/smoke-35549221493-review.json` with full natural lifecycle evidence.

All3 Pump reservations filled in12–13 seconds under their original20-second timeout.
From first position check to fill, their original RPC sessions had respectively15,4,4
priority0 records and ZERO intervening research records. Natural PnLs were+1506443,
-8512170 and-15472750 lamports (total-22478477), with holding times78,7,7 seconds.
No cancelled Pump reservation or unresolved exposure. Pons retained10 entry-slippage
rejections and1 natural market-sale settlement, PnL+1723165591410886 native quote units.
No writeoff/forced lifecycle occurred; all losses and rejected opportunities remain.

Pump's two program-account HTTP429s were independent scans: raw525/770, different mint
filters4Y9FuLB.../5h38uRJ..., minimum slots448901191/448901724, sessions76dcc114.../
93677549..., timestamps1789952624124392492/1789952766644939660ns, each retry_count0.
No duplicate physical retry. Pump had0 getTransaction HTTP429s,27 explicit null bodies,
1 local wrapper governor timeout (research_history, priority90), plus1 acquisition-stage
pre-transport expiry. No expired-batch fanout. Pump window consumers:1294 complete,
2509 expired before transport,156 after transport; these per-signature interests are
not independent opportunity counts. Complete evidence and all missing demand remain.

Meteora observed92 pools, issued19 signature members with0 signature429s, but no complete
economic vector in this sample:5 fresh-trigger timeouts,1 warmup-unverified,1 acceleration
regime expiry and1 experiment deadline. One foreground request hit a30-second governor
wait during Pump position monitoring (priority10, raw51); this remains a visible local
capacity loss. Other Meteora requests received101 grants; it is not relabeled as provider
rate limiting. Sustained fairness and completion remain hourly observations to verify.
Ramses completed2 inventory scans and screened1 active pool. Natural certification stays
NATURAL_INCOMPLETE for Meteora/Ramses. No profitability conclusion is drawn.

Before hourly observation, active/queued/pending/waiting workflows were rechecked: only
35549221493 active, all other queues empty. The fresh hourly job106185034210 reran all
hosted gates and uses the same exact752dd501 source/overlay revision. Live check106185318738.
No smoke uptime counts toward the required3600-second independent observation.

Hourly midpoint snapshot (not final certification):1806.3597875459998 seconds concurrent
overlap, all four lanes responsive. Pons8 natural settlements and1 open position;
original lifecycle authority remains active. One post-fill Robinhood JSON-RPC429 was
observed around18 minutes; subsequent settlements occurred without lane restart. Exact
recovery identity/PnL will be checked from final native artifacts. Pump68 complete
candidate evidence records, Meteora4 economic vectors, Pons102 full vectors. No Solana
HTTP429 reported so far; incomplete/null and local admission evidence remain visible.

## Terminal classification defect found during hourly artifact preparation

The hourly live check106185318738 stopped advancing after3554.3319998760003 seconds
of overlap at observed timestamp1789957537.1718543. The workflow remained active;
no certification conclusion is drawn from this stale checkpoint. Last visible books
were flat, Pump3/Pons18 natural settlements, no unexpected exits. Publisher and
supervisor artifacts must establish the cause before any replacement run.

Independent source review found `persist_terminal` omitted `settlement_kind` from
its compact Pons lifecycle whitelist. A correctly booked liquidity writeoff could
therefore be counted as a natural market sale by the supervisor after terminal
compaction. No current live writeoff has been observed; this is nevertheless a
required terminal-truth regression. The fix retains the discriminator and makes
summary classification also recognize the exact durable position reason
`liquidity_writeoff:impossible_full_position_exit`, including older compact reports.
It changes neither ledger economics nor policy and does not relabel unresolved books.

Files changed: Pons overlay native `pons_selective_cohort.py` and
`test_pons_continuous_campaign.py`; supervisor `certification/report.py` and
`certification/tests/test_certification.py`. New tests prove compact/archive kind
retention, exact loss retention, zero natural-sale credit for explicit and historical
compact writeoffs, and independent counting of a real market sale.

Local verification:1215 lane tests (Pump292, Meteora392, Pons273, Ramses258),70
supervisor tests and all3 resource gates pass. Logs in
`results/terminal-report-verification/`; all overlays byte-reproduce and frozen files
match, recorded in `results/terminal-report-overlay-reproduction.json`. These tests
ran against the local revised tree while Git HEAD and hosted validation remain752dd501;
the deterministic manifest's integration SHA is the base, not a claim that the edited
reporting code ran in the current hour. A new exact candidate and fresh smoke/hour
are required after the visibility issue is diagnosed.

## Completed 752dd501 hour: execution PASS, campaign review FAIL

Run35549221493 hourly job106185034210 finished with workflow failure, preserving
artifact10620090080, SHA256
`e219603870cc0adcd856498fb94f68afeb3cf2851c3dc19a102c4e86fc32e222` (531588445 bytes).
Archive was downloaded, checksum-verified and extracted without changing original bytes.
Full review is `results/hourly-35549221493-review.json`; four adjacent Pons lifecycle
files preserve all20 qualifications/lifecycles including2 entry failures and18 losses.

Exact752dd501 observation achieved3600.1381197540004 seconds concurrent overlap, with
4628.684449273 seconds total including normal drain. Every lane exited0, no unexpected
exit/restart, all books reconciled, zero exposure, zero forced lifecycles, no writeoff.
Automated hourly execution integrity PASS is retained. Campaign review FAIL is explicit:
terminal live publication failed and terminal writeoff classification needed repair.
ZERO seconds from this hour count toward the replacement revision's certification.

Publication diagnosis: first failure at1789957598.169829 immediately after the first
lane's terminal report. Ramses terminal `finality_state.observations` added177 frontier
observations; the public view became70293 bytes and raised `live_status_payload_capacity`.
The prior session-list bound did not cover this history. Nineteen ValueErrors followed;
the publisher finished with supervisor_exit_code0 and visibility_failed=true. No lane
or supervisor failure was hidden. The repair adds `compact_finality_state`, retaining
all aggregate counts/gate reasons and2 recent observations; the complete original
history stays in native/raw artifacts. The captured terminal result now renders46992
bytes. A1000-observation regression checks exact totals, recent selection, source
immutability and the60KB bound. Supervisor suite now71 tests; lane1215 tests and3resource
gates unchanged and passing. Files: `certification/live_status.py`,
`certification/tests/test_live_status.py`, plus the previously recorded writeoff fix.

Pump naturally filled/settled3, entry delays11/12/12 seconds, holding times8/7/7 seconds.
PnLs -5506819,-11112604,-174348732 lamports, sum -190968155; cash4919416145 and basis0.
Replay12 events verified. Losses are retained unchanged, not an implementation pass
being presented as profitability. GPA429s raw4825/4970 are independent: mint filters
91f14Qr.../A7Hpn94..., slots448917075/448917399, different parameter hashes and sessions,
physical IDs29779731...:4825/4fe9aa27...:4970, timestamps1789956864000624205/
1789956951935856426ns, retry0 both. No duplicate scan. getTransaction429=0; maxbatch8,
3578 eight-member physical batches. One true transport timeout and9 null bodies remain.

Pump local decomposition:15 wrapper governor deadline rejections,14 physical wait and
1 deadline already expired at governor admission; zero queue-capacity rejection or
shared-cooldown terminal rejection. Native acquisition phases separately retain7
pump-window expiries before transport,10 governor waits,24 capacity waits,239 late
transport results; research and stream phases are separately recorded in the review.
The13 local request-budget exhausted episodes remain visible. Window consumers18915
complete,48683 expired before transport,1724 after transport; before-transport fraction
70.23% versus88.59% in the defective600-second baseline. These are different market
samples/durations and per-signature interests, not a causal proof or unique opportunity
count. Residual loss is substantial; no provider error is invented for untransported work.
No expired-batch fallback fanout was observed. All34 position-monitor consumers completed.

Meteora:210 getSignaturesForAddress members,0 signature429s,5 complete economic vectors,
922 physical grants with0 deadline misses and maxwait6.922s. Exact reconstruction and
rejections remain in the raw artifact. No natural qualifier; NATURAL_INCOMPLETE.
Ramses:177 frontier observations,10 advances,11 expensive inventory scans,282-pool
inventory retained,416 Robinhood transports/grants with0 failure. No natural qualifier;
NATURAL_INCOMPLETE. Final Solana and Robinhood governor queues empty; no mutual starvation.
Peak RSS bytes Pump123711488/Meteora101183488/Pons179855360/Ramses34541568.

Pons:20 qualifiers,2 entry failures,18 natural market-sale settlements, all losses;
realized -2407251945184515 native quote units, native execution cost195057506862000,
cash997592748054815485, remaining basis0/reserved0/unsettled0. Conservation, native
observation completeness, and every filled lifecycle's replay verified. No writeoff or
post-fill provider-recovery attempt occurred. Correction to the midpoint interpretation:
the observed JSON-RPC429 occurred in priority50 candidate trajectory acquisition while
a separate position was open; it was not that position's monitoring failure. One
eth_getLogs RPC-32602 and one mixed-method trajectory RPC429 batch remain attributed.
Neither is relabeled as successful evidence. All qualification vectors, entry/exit,
quote fees, modeled gas, min-fill/slippage bounds, holding paths and realized results
remain in the lifecycle files and original native ledgers. No provider billing invented
from estimated compute units. Historical unresolved baseline exposure remains unresolved.

A fresh exact-revision600-second smoke and independent3600-second hour will follow
these two implementation-only reporting repairs. No policy/provider limits changed.
