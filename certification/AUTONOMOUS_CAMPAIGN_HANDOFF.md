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


## Frozen-policy campaign checkpoint after concurrent policy branch changes

This checkpoint concerns exact integration fba42effbe23fe1d3428b95e2280cd4dec0a0d06
and workflow35555511322 only. It does not certify the later machinery-proof policies.

The fba42eff smoke passed manual engineering review: job106198284555,
600.112410083 seconds continuous overlap,1604.410291214 seconds total, normal
exits, no restarts, zero final exposure and reconciled accounting. Artifact10620836443
SHA256643e0ed8c2d5a4406fc3e821f550596aa2969f9913be069e41f2e2c2e1fc25d6 was downloaded
and verified before the local workspace became unavailable. Pump/Meteora/Ramses
natural certification remained incomplete. Pons had7 natural market-sale settlements,
all losses totaling -3099014189723880 native quote units; zero forced trades/writeoffs.
Three genuine post-fill RPC429 recoveries retained ledger identity, reservation,
entry and original hold clock. Publisher completed without the former60KB overflow.

The independent fba42eff hour, job106202889441, FAILED continuity: Ramses exited1
at505.60147918199993 seconds during factory_authentication. Shared Robinhood
admission showed86 requested/85 granted/1 failed, maximum wait30.008014887 seconds
and no Ramses provider error. Pons recorded30 failed local admissions. At observation
end it exited0 while still reporting5 open positions,3 natural settlements,
zero writeoffs, remaining basis/reserved exposure and an incomplete capital integral.
That is a failed terminal drain, not a successful settlement. Historical unresolved
baseline exposure also remains unresolved. The exact native boundaries and recovery
journals require the final artifact; local scheduling starvation is a hypothesis
until those records are inspected. Pump has2 natural settlements so far; Meteora
exited0 flat. No time from this hour is eligible for a replacement certification.

Implementation repair prepared locally before workspace loss:
- Shared Robinhood admission gives one aged other-lane request a slot after8
  consecutive same-lane position grants, preserving imminent position deadlines,
  same-lane position priority, original0.5s interval, cooldown, queue limits and
  consumer deadlines. Deterministic old-code reproduction granted20 Pons position
  requests while Ramses got zero and expired at its original10-second deadline.
- A thread-local lifecycle context classifies generic fresh-head reads within Pons
  and Ramses lifecycle work as position priority; exceptions reset the context.
- Ramses bounded local scan recovery permits at most3 attempts only for shared
  admission deadline/capacity loss, preserving pinned frontier and original
  observation deadline. No missing result advances a frontier.
- Local admission telemetry retains method/scope/request/deadline/reason/priority,
  including already-expired requests, without inventing a provider transport.

Local full verification passed1229 lane tests: Pump292, Meteora392, Pons278,
Ramses267;72 supervisor tests; all3 resource gates. Commands were
python -m certification.run verify --worktrees /workspace/scratch/6b0f6ba7cc58/lanes
--output /workspace/scratch/6b0f6ba7cc58/gates-robinhood-fairness-final
and python -m unittest discover -s certification/tests -v.
Private-index reproduction verified byte-identical overlays and unchanged protected
source/config/policy files. Prepared overlay SHA256:
Pump a8e4effbe55d758ec1e744bfab08d42964e58189fd740cd1b2ea7e1e09d7bcf5;
Meteora1f447a3c83bac236c74497f7e12d1e8307331d60fc71ee6459b4e13429c34f65;
Pons c795e113f88f9ec601af7cb5c6cc879a97b526b28fe98507a1044111825a99cc;
Ramses08ed19dfe5583b0cbed300ec74d7ab15f5ab4942a8476fad863e2fc464ba13fd.
These repairs and transcripts were written locally but NOT published. Do not infer
their presence at fba42eff or the current remote head from these test results.
Local execution and Node filesystem access now report environment_offline; no local
artifact or file availability is being claimed beyond previously published evidence.

A fresh remote check found PR93 still draft/open but advanced externally through
3e7121ca3962e7764b2406ae990331411f9f43fc to
c0b8bfb71c1635f60997d92c681d85298bd2030c. The newer handoff describes a separate
one-shot user-authorized machinery-proof follow-up. That instruction is recorded
as repository context, not substituted for this task's explicit frozen-policy controls.
Its manifest switches Meteora to43bbcce60913a9a87404fe6563585159fb72352f
and Ramses tod252724f081a9ca0b3bc5fbd8e28b191568c6499, with changed policy hashes
and loosened economic gates. Meteora two-way balance0.25->0 and expected net
-200000->-1000000; Ramses acceleration1.2x->0, chop1.5->0, imbalance60%->100%,
projected return0->-150000bps. This campaign cannot silently adopt those changes.
Queued successor35558419998 is a separate policy run, not a frozen-policy replacement.

No external policy commits are reverted, no queued separate campaign is canceled,
and main remains untouched. Because moving the active PR head would interfere with
that separately queued work, this evidence is checkpointed on
repair/frozen-campaign-handoff, based on the exact tested fba42eff revision.
No duplicate repair PR is opened. The existing PR93 will link this checkpoint.
A read-only hosted artifact review on this branch uses GitHub artifact access only,
no market/provider credentials, no signing and no transaction authority. It preserves
the final artifact checksum, full native records and exact failure diagnosis.

Engineering certification for this frozen-policy campaign remains FAIL.
Natural certification is not inferred from machinery success or changed gates.
Resuming integration requires resolving which policy campaign/head is authoritative
and restoring access to or reconstructing the unpublished verified implementation.


## Final verified fba42eff hourly artifact and unresolved implementation defects

The exact failed hour completed normal process shutdown at4625.056032356 seconds.
Continuous four-lane overlap was only505.60147918199993 seconds. Supervisor exit1;
engineering FAIL. No replacement certification time is claimed and no cancellation
was performed. Artifact10622262502 is566397254 bytes, verified SHA256
670e3fdaf2b003931d04cdde9db9910006bd6c7a511c0f50fce5b04623d7cfee.
Read-only review workflow35561304796/job106214553158 passed on evidence commit
1f353c9d81207259ea21810d9fd39af13b0b5afc. Its complete review artifact10622616161,
6473358 bytes, recorded SHA256ce5805b9527ac95e87ca2082c470a0e68a715dcd60383506e77df382b45e34c9,
contains full Pons and Pump native results, qualification/entry/exit/cost/PnL paths,
Pons journal/recovery/writeoff records, shared admission records and all process logs.
The original566MB archive retains every raw transport and ledger; it was not modified.
Compact exact-integer summary and original result JSON are committed adjacent to
this handoff under results/hourly-35555511322-hosted-review.json and
results/hourly-35555511322-result.json.

All source overlay hashes match fba42eff, manifest SHA256
7c2505cc65e599929e58511f2463875f86228232d30f053754bf0ec9ef639226.
Ramses missing terminal-proof flags are consequences of its process failure; they
are not evidence that the running worktree adopted the later policy revision.

Ramses traceback confirms provider_shared_admission_deadline while verifying cached
factory sentinels: ramses_universe._enumerate_factory -> _factory_rows ->
scope universe_inventory_verify -> shared Admission.acquire. Its only failed
admission consumed30.008014887 seconds and reached no provider transport.
Inventory/finality progress stopped after2 expensive scans; three active pools were
evaluated, no natural qualifier/fill and no exposure. The local bounded-fairness and
same-frontier recovery repair targets this confirmed implementation failure.

Pons exact terminal cause was NOT selective_position_provider_recovery_exhausted.
Trials001,002,003,004,009 all filled, then ended at
provider_session_budget_exhausted. Trials002/003 had no preceding transient recovery.
Trials001/004 retained4/3 local-deadline recoveries; trial009 retained one actual
eth_getLogs RPC429 and one local-deadline recovery. This corrects the earlier
hypothesis that all five positions had exhausted transient recovery.
paper_rpc configures limit200/per_scope190; run_lifecycle rotates only at the start
of an iteration when rpc.used>145. A monitoring iteration may exhaust the remaining
local session budget before reaching that rotation check. This is an additional
implementation defect requiring bounded, deadline-preserving session management
and its own regression. The unpublished fairness repair alone does NOT fix or prove
this path. Do not increase provider contractual rate limits or simply allowlist
unbounded budget retries. No further implementation is claimed complete.

Pons trial010 demonstrates pending-exit preservation: original opened_at1789961824,
pending_due1789961918, same pending token amount through local-deadline recoveries
at hold elapsed125/226, then actual settlement at1789962120, realized loss
-2273191636074254. Other natural settlements were trial007 -27143106252672 and
trial008 +6781647264891961. Total settled realized +4481312522565035 is not a
profitability claim: five positions remain unresolved. Full qualification and
cost/fee/slippage/holding evidence is retained in the native review/archive.
26 qualifiers yielded17 entry failures,6 boundary outcomes (one before reservation),
and3 settlements;25 reservations total. Zero forced lifecycle or writeoff.

Pons accounting exactly: cash991955879578349035, remaining basis12525432944216000,
reserved17500000000000000, unsettled5, native execution cost101165850806000.
Cash+basis=genesis+realized holds; native observation completeness and native replay
hold, but capital_integral_complete=false and terminal exposure is unresolved.
The five ledger identities are preserved in the exact review. No historical or new
exposure is relabeled settled, erased, recreated, or written off from provider errors.

Pump observed1278 mints,24 unique late-curve prospects,54 admitted candidates across
modes,45 expensive evaluations,160 complete evidence records,2 qualifiers/fills and
2 genuine settlements. Fill delays13/13 seconds, holding6/10 seconds. PnLs
-28515027 and+15371221 lamports, total-13143806; cash5097240494, basis/reserved0.
Eight-event accounting replay verified. No forced settlement.
6501 physical transports,3600 eight-member transaction batches,maximum8 and zero
getTransaction429.59 null transaction-body failures remain visible.

Both getProgramAccounts HTTP429s are independent, not duplicate retries:
- sequence2484, physical18aa7fed-11ba-4721-bbb6-fa69ffe4513f:2484,
  mint CXs9Cf7QuXxdiE3Qb3g1AgyDDWQd8j4tLmfzdnxcBaTg, minContextSlot448937839,
  parameter hash0a9adea684a68420127500b3fa2f9c86edc0ffc208a0a9c1a5c542d914762310,
  timestamp1789962413228616700ns, retry0.
- sequence4670, physical715f6c8d-c8fd-48e0-af39-21643160522c:4670,
  mint ZG6E39iPoKvrZcdjQxtPzRmq6BKrKKrTPCBEMFapump, minContextSlot448942655,
  parameter hash18150962a78d5ab95bc9c0194d8dd9ffd7fa0e98021fa26505d2ca4e9d5f06d5,
  timestamp1789963701847166200ns, retry0.
Original per-scan deadline was null; no deadline is fabricated. Full finalized
filters, scope/session and physical identity are retained. These scans correspond
to distinct natural lifecycle mints and remain legitimate pressure evidence.

Pump wrapper local failures:9 physical-governor waits (8priority20,1priority90);
zero queue-capacity/shared-cooldown terminal failures. Acquisition phases separately
retain window1 expiry before transport,24 physical-capacity waits,8 governor waits,
261 post-transport late results; research1 already-expired before enqueue,
12 capacity waits,1 governor wait,11 late results; stream4 before-transport expiries,
2 capacity waits,14 late results. Full consumer decomposition: window115906 expired
before transport,1640 after transport,17042 complete; research16 already expired
before enqueue,481 before transport,88 after,2511 complete; stream6781 before,
708 after,6434 complete,436 retired,126 waiting at its last snapshot. Supervisor
shutdown explicitly classified126 unfinished consumers (89deadline,37censored).
Window pre-transport fraction86.12% versus88.59% defective baseline is a different
market/duration sample, not proof of material improvement. Residual local loss
remains unresolved; do not label untransported work provider rate limiting.
Maximum sampled active broker jobs8; final physical-governor queues empty.

Meteora observed245 pools,53 admitted interests,21 authenticated triggers,
19 reconstructions,9 complete economic vectors,zero natural qualifier/fill.
261 getSignaturesForAddress members and1070 physical grants,zero signature429,
zero local governor misses; max governor wait3.049 seconds. Natural certification
remains NATURAL_INCOMPLETE. Broad inventory, frozen strategy and interval evidence
were retained. Ramses also remains NATURAL_INCOMPLETE. Neither lane's incomplete
natural result is cured by the later machinery-proof policy changes.

Final peak RSS bytes: Pump118910976,Meteora83009536,Pons175505408,Ramses31879168.
No process restarts. Pump/Meteora/Pons exited0; Ramses exited1. Method/HTTP/RPC-code
attribution remains intact. Pons RPC code3 errors are kept separately from its one
RPC429. No hourly publication-size failure was observed.

The separate c0b8bfb machinery-proof workflow35558419998 subsequently FAILED before
any live smoke: supervisor test_execution_source_files_remain_explicitly_hash_pinned
expected an execution-certification strategy label and found machinery-proof-v2.
Its smoke/hour steps were skipped. Artifact10622576228,2965 bytes, recorded digest
80181659ecf7456b21dd314ac06440496c6d409670d25c727c621d8b04b169fb preserves that failure.
This campaign did not disable or alter that test, modify its policies, cancel it,
or reuse its time. Policy/head authority remains a decision outside this task's
no-threshold-change permission. Local runtime access still returns environment_offline.

Required continuation, once authority/workspace access is resolved: recover or
reconstruct the unpublished fairness/context/admission telemetry patch; repair Pons
within-iteration session exhaustion without weakening budgets or deadlines; retain
all five unresolved ledgers; verify frozen policies and canonical overlays; run full
deterministic/resource gates; then one fresh600-second smoke and, only if it passes
normal terminal drain, one independent3600-second hour. Neither engineering success
nor natural completeness is claimed at this checkpoint.


## Isolated frozen-source continuation using hosted deterministic execution

Further reconstruction established a safe continuation path: retain the original
fba42eff frozen source manifest on this isolated branch, leaving PR93's separate
machinery-proof policies untouched. The task explicitly permits branch separation
when existing branch structure requires it. The earlier checkpoint's policy conflict
therefore prevents adopting c0b8bfb, but does not require abandoning infrastructure
repairs on the original frozen sources. Local execution remains unavailable, so the
implementation is reconstructed in versioned inputs and verified on a hosted runner.

The reconstructed repair includes bounded Robinhood cross-lane admission, thread-local
position context, exact local-admission telemetry and bounded same-frontier Ramses scan
recovery. In addition, a Pons PositionSessions wrapper can rotate an exhausted local
200-request session within one operation, retrying only the rejected untransported
operation once. Fresh-session failure remains fail-closed. Provider429/authentication/
per-scope budget errors are not blanket-retried; limit200/per_scope190 are unchanged.
Session authentication and previous telemetry remain mandatory; rotation records
retain original ledger identity and hold clock. No position, qualification or pending
exit is recreated. Existing iteration-headroom rotation is preserved in the wrapper.

New deterministic cases cover sustained cross-lane pressure, imminent position
deadlines, local failure attribution, context/thread isolation, Ramses pinned scan
recovery, bounded Pons session rotation, authentication/configuration failure, and
full-ledger monitor/pending-exit session exhaustion with settlement/reconciliation.
Hosted verification is pending; prior local test results are not substituted for it.
The builder has no provider credentials and only creates Git blobs after every gate
passes; it cannot move any branch ref. Candidate composition remains explicit.

The live workflow accepts this isolated branch but no live run is requested by this
build commit. A subsequent exact canonical candidate must pass all hosted gates and
active-run checks before a fresh smoke and independent hour. No older time is reused.
All old failed artifacts and unresolved positions remain historical evidence.


## Hosted reconstruction verified; fresh frozen-policy candidate composition

Build35562741730/job106218570560 passed on4d484472aa210e6fd541c38345d0a2c421cc3150.
Complete suites: Pump292,Meteora392,Pons286,Ramses267 (1237 total),supervisor72,
all3 resource gates. No test was disabled. The two full Pons lifecycle session-budget
regressions settled/reconciled with one entry and one exit intent; bounded rotation,
configuration/authentication failure and unchanged persistent-pressure behavior passed.
Canonicality and protected source/config/policy hashes passed in a private index.
The exact verified blobs and complete gate transcripts are composed into this candidate.

New overlay SHA256: Pons7d6a4f963d4e37e687fcdfd5af112c211d9e3bd591bcd06dfc58f8b70d44f859;
Ramses204fe6ec0927a58e1115427db167fd580c50b41555826de204343651f13bc5f7.
Pump/Meteora overlays and the original manifest hash7c2505cc65e599929e58511f2463875f86228232d30f053754bf0ec9ef639226
remain unchanged. Build artifact10622812658,204881 bytes, recorded SHA256
b4c8beac22837120f22bbb73113a72099b4fcee085fd1a4ca7f77dcf2edc6b96.
Full logs/canonicality are durable under results/hosted-frozen-repair.

Before composition, active/queued/pending/waiting workflow queries were all empty.
The candidate requests one fresh600-second smoke, then an independent3600-second
hour only after smoke engineering and a read-only artifact review pass. The new
review job verifies the archive digest, exposes complete raw/native failures, and
checks exposure/continuity/batch bounds before the hourly job can start. A final
read-only review follows the hour even on failure. Review jobs have no provider
credentials and consume no market capacity; waiting time is not observation uptime.
The generalized review script is syntax-checked before any live lane launch.
Exact candidate SHA/run ID will be recorded in PR93 and the next handoff entry.
No time from fba42eff or any earlier run is reused; five failed-hour Pons ledgers
and prior unresolved baseline exposure remain unresolved historical evidence.
