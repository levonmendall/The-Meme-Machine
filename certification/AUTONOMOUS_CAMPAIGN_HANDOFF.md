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


## 2026-09-21: accepted c4572 smoke; superseded hour and authentication repair

Candidate c4572e18d078222fe05d6df9eec55d62dfc59f41, workflow35563114670:
smoke job106219609968 and artifact review106224597512 PASS. Continuous four-lane
overlap600.123617827s, total1605.083120743s including normal drain. All exit0,
no restarts, no open positions, reconciled accounting. Natural/forced settlements
zero for all lanes: NATURAL_INCOMPLETE. Smoke archive10624085968 (114429650 bytes)
verified SHA2566cacbfdb6cbff6bc78593aa8fdf35ffefc8ac65bbe9f12a8b828c3a0927621cc.
Review archive10624185885 recorded SHA25691cbf7e4adbeee390d33876d8639158b70754ff6cf0ff8323654798ddf48a388.

Pump1327 physical requests, maximum getTransaction batch8, zero provider429 or
getProgramAccounts calls, zero physical-governor deadline misses. Window2056
complete/18988 expired (18793 before,195 after); stream3574 complete/728 expired/
142 retired. Logical expiry remains substantial and is not mislabeled provider
failure or claimed materially improved. Meteora53 pools/10 admitted/4 authenticated
triggers/3 reconstructions/1 economic vector,43 signature members with zero429.
Pons1324 CurveBuys/297 current-state complete/45 admitted/37 full vectors;
1126 grants/2 local admission misses with original deadlines under0.25s; no fills.
Ramses282-pool inventory/2 scans/1 frontier advancement/3 active evaluations,
101 grants/zero failures. Complete native and raw evidence retained in archives.

Static review after the independent hour began found a concrete wrapper defect:
a replacement session assigned before verify_chain could remain current following
a transient authentication failure and dispatch a later read without successful
authentication. The hour at c4572 is SUPERSEDED and will not certify any replacement.
Targeted cancellation commit17671d8f1d3ad1a3f45bc4f0e5bfe2f883e99cbd,
workflow35565147831/job106225361497, refused cancellation with
not_proven_flat_do_not_cancel. Audit10624171231,9986 bytes,
SHA256c5d53dee5c9a33cbede1bb5a4a7ce43f320c96a7ad64988b424410e69d415ea3.
Natural activity had already occurred. The guard is preserved; the run is allowed
to complete its authorized lifecycle/drain, with no competing market run started.
No runtime is hot-patched and no prior time will count toward the replacement.

Versioned native inputs now require successful authentication before reads or
iteration processing after rotation. Failed authentication keeps the same session
and explicit unauthenticated state; each bounded outer recovery rechecks chain
identity before any read. Durable attempts distinguish authentication retry from
session rotation and do not double count the current session's telemetry.
Original provider limits, policy clocks, recovery bounds and all frozen gates remain.
Four adapter regressions cover transient/persistent authentication, iteration retry
and explicit reauthentication failure. Two full-ledger regressions cover pending
exit recovery and bounded persistent failure retaining unresolved exposure.
Changed native files: position_sessions.py, pons_selective_paper.py,
test_position_sessions.py, test_pons_position_provider_recovery.py (all Pons).
The hosted builder will canonicalize overlays, verify protected hashes, run all
lane/supervisor/concurrency/accounting/resource gates, and publish exact Git blobs.
No live replacement is authorized by this build marker alone.


## 2026-09-21: authentication repair fully verified

Hosted build35565696608/job106226950728 at26cc0c67ffd64e909d4f1c35574038cb276752e1
passed1243 lane tests (Pump292,Meteora392,Pons292,Ramses267),72 supervisor tests
and all3 resource gates. Six added authentication regressions passed, including
full-ledger pending-exit preservation and persistent failure retaining exposure.
Complete transcripts and canonicality proof are appended under
results/hosted-frozen-repair/authentication/.
Build archive10623462758,205953 bytes, recorded SHA256
0e4b2e01b69ba16f32b39ca1cdebdda7866c3a3de25b59f9f2b7fdec8e56c71f.
Verified Pons overlay SHA256d2e6e5f8be017121664ef3b2d2c796da52da1f6f586d54950825e36f28763c9c.
All other overlays and manifest hash7c2505cc65e599929e58511f2463875f86228232d30f053754bf0ec9ef639226
remain unchanged; protected frozen source/config/policy files passed exact hashing.
This commit composes the verified blobs without a live-launch marker.
Superseded35563114670 retains lifecycle authority; its fresh replacement must wait
until that workflow completes and all active/queued market work has been inspected.


## 2026-09-21: c4572 hour failed before replacement launch

At elapsed1388.423s, Pons had already exited(code0) unexpectedly after1369.457s
uptime; four-lane overlap stopped at1369.452s. Terminal snapshot records two
positions, one liquidity writeoff, one still unresolved, no natural market-sale
settlement. Cash/basis conservation remains true; capital integral remains
incomplete. This is an engineering failure, not a clean terminal drain.
Pump has two settled natural trades and no exposure; Meteora/Ramses remain flat.
No replacement market run has started. Verified827af68b remains unlaunched.

The previous cancellation guard correctly refused while lifecycle activity existed.
The situation is now different: the Pons process has already exited and cannot
continue its unresolved position by waiting. A narrowly targeted cancellation of
35563114670@c4572 requires a fresh snapshot proving that exact Pons early exit
and that all still-running lanes are flat, reconciled, have no reserved/pending/
committed capital, and all their cumulative qualifiers are settled. The complete
Pons unresolved book is retained in the cancellation audit; cancellation cannot
relabel it settled. This avoids spending the rest of a failed hour while preserving
all existing artifacts and raw evidence. Exact terminal boundary and writeoff proof
must be reviewed before deciding the next implementation repair.


## 2026-09-21: cancellation outcome and hourly artifact preservation failure

Cancellation attempts35566601403 and35566685373 refused the guard; the latter
snapshot was60.677s old. Their audits remain respectively10623269362
(SHA2567ac1fe023b32f1c37fc630dffad9fbfc0a25ddb1c507401544e28e026af7f2d9)
and10624138999 (SHA256221cacf09bdd5809562c4cc76563fe6b4973f1b866e4be789a3f8721e0d2e8cc).
Commit eb53c8dfbe8bcce9d21687f0f51026d694f594dd added a bounded wait for a fresh
snapshot without relaxing the45s age limit or flat-lane tests. Cancellation
35566755868/job106230020457 succeeded(HTTP202), snapshot age7.2809295654296875s,
elapsed1690.424287857s. Audit10624432398,12703 bytes, recorded SHA256
13b5d224630083a1a389eba1e3784bf264ea6ad1fdc1b5979c5e7434a29a78a8.
The exact audit JSON is retained in results/hourly-35563114670-cancellation.json.

IMPORTANT EVIDENCE GAP: the hourly archive did NOT finalize. The always-run
native copy step completed, but actions/upload-artifact failed while a still-live
SQLite sidecar disappeared during ZIP construction:
certification-hourly/shared-robinhood-admission.sqlite-shm.
The job then cleaned up its runner/orphan processes. GitHub lists only the
previously accepted smoke archive and smoke review. No hourly artifact ID or digest
exists; full native hourly ledgers, raw RPC evidence and path-dependent trade
details cannot be recovered through the available tools. Do not claim that the
complete failed hour was preserved or replay-certified. The original job logs,
three cancellation audits, retained public snapshot, and prior smoke remain.
A sanitized durable copy of job106224629679 logs is stored with this entry.

Retained Pons accounting at cancellation (exact integers from the audit):
cash994978443746350000, remaining basis2516434138096000, reserved3500000000000000,
realized-2505122115554000, execution cost21556253650000, positions2, unsettled1.
Reported writeoffs1 and natural market-sale settlements0. The reported writeoff's
full proof/replay is unavailable because of the archive failure; do not invent it.
One additional unresolved historical Pons exposure remains recorded alongside the
five from35555511322 and the original baseline unresolved position. Nothing is
relabelled settled. Pump reported3 natural settlements and realized-7402388 lamports;
their full hourly entry/exit/cost detail is unavailable, so this is only a retained
aggregate, not profitability or full lifecycle certification.
Meteora/Ramses reported no natural settlements or open exposure.

The current source deterministically reproduces same-lane foreground starvation:
position bursts could yield to Ramses, but never to Pons discovery authentication.
The retained snapshot had18 local admission misses, including11 connectivity
misses, zero Pons provider429, and continuing position grants. This supports an
implementation diagnosis, but the exact cohort/lifecycle terminal boundary is
UNKNOWN due to the artifact gap. Do not assert a fully proven production cause.

Repairs submitted for fresh full deterministic verification:
- Preserve eight position grants before one aged foreground opportunity. Same-lane
  priority10 observation can now receive that bounded turn; generic same-lane
  priority50 research still cannot bypass positions. Imminent position deadlines
  retain precedence. Shared0.5s ceiling, cooldowns, queues, original deadlines,
  lane market scope and all frozen policy/config hashes remain unchanged.
- Scope Pons discovery authentication/polling as foreground; handle an allowlisted
  transient failure during ordinary discovery session rotation without double
  archiving the old session or advancing the original cursor.
- Separate local-capacity recovery from actual provider429 backpressure. Local
  admission does not slow the provider pacer or masquerade as provider throttling;
  recovery remains bounded, and authentication failure remains fail-closed.
- Freeze upload inputs into an isolated staging directory. SQLite online backups
  include committed WAL content and verify integrity; transient sidecars are never
  globbed live by the uploader. Preserve unverified raw bytes if a database backup
  fails, retain all other files, and mark incomplete snapshots explicitly.
- On workflow cancellation, identify leftover workers by exact PID/process group/
  command/lane/output path before stopping them, then let the existing supervisor
  finalize failed/interrupted evidence. No settlement is inferred. The workflow
  entrypoint uses exec so cancellation reaches the publisher directly.
- Supplement artifacts with small sanitized Pons terminal receipts in Actions
  logs, preserving exact integer accounting, known boundary class/hash and ledger
  identity where available. They never replace raw replay evidence.
- Retain lifecycle_id in the bounded native terminal view, including failed
  positions. No public snapshot returns to unbounded history growth.

Regression coverage includes committed-WAL capture while sidecars disappear,
immutable snapshot independence, corrupt database byte retention, symlink rejection,
verified-worker-only cancellation, exact sanitized terminal receipts, same-lane
foreground fairness, position deadline precedence, discovery recovery cursor/
identity, persistent local pressure and fail-closed authentication.
The next live attempt remains a completely fresh smoke; an hour may follow only
its exact-revision engineering/artifact gates. No elapsed time from this failed,
cancelled hour is reused. No merge, economic change or live-money authority.


### Deterministic archive regression caught and corrected before live use

Build35567907287/job106233302830 failed the new sidecar-race regression: SQLite
backup preserved the source WAL-mode header, so opening the copied database could
create new destination sidecars. No lane suite or live test was launched from this
failed gate. Artifact10624645899,168799 bytes, recorded SHA256
f1fa1a9bcffc635062c2d1d87dfa7ed7b038bdc5d96a6458f1ea5cf8eb00548d preserves the failure.
The collector now explicitly closes both connections and converts only the copied
snapshot to standalone DELETE journal mode before hashing. The same regression
remains enabled. Native source databases and their accounting are not modified.

Workflow35567906325 also failed YAML validation because cancelled() was used in
a run expression. Per GitHub's contexts reference
(https://docs.github.com/en/actions/reference/workflows-and-actions/contexts),
status functions belong in step/job if conditions. A dedicated if:cancelled() step
now sets a trusted cancellation flag; the collector consumes that flag. Both
failures are retained, and the complete gates must pass before any live launch.


## 2026-09-21: verified capacity/archive candidate and fresh staged launch

Build35568087595/job106233813173 at1673eb4cd8b49bbc8d748a387f2b3eb8ad4035a1
PASS:1253 lane tests (Pump292,Meteora392,Pons300,Ramses269),78 supervisor tests,
all3 resource gates, exact canonical overlay reproduction and frozen file hashes.
Artifact10625031687,208621 bytes, recorded SHA256
b90831615faf5740498f53e7958b428aac5cd6e3f9546e865439500687ef8ad1.
Complete transcripts/canonicality are appended under
results/hosted-frozen-repair/capacity-and-archive/.
Pons overlay SHA256e6e5824e8cee8479913303363d055bd77d0c539307f1e5b5d55883fcc9d7c90a;
Ramses8e4eb8de96c73c8812f760733d48dd6921f2817922d959b5c98ca85e903a2786.
Pump/Meteora overlays and original manifest7c2505cc65e599929e58511f2463875f86228232d30f053754bf0ec9ef639226
remain unchanged. This commit composes precisely the hosted verified blobs.

Fresh prelaunch inspection: in_progress/queued/pending/waiting workflow lists all
empty. All147 branches were enumerated across two pages. Four original frozen
source heads, main54712c4c, PR91acb7e511, PR92a34c5d4d and PR93c0b8bfb remain
as previously recorded; no newer PR after closed94. Prospect branch0982519a remains
unchanged and its equivalent repair remains composed exactly once.
The separate changed-policy PR93 head remains untouched.

Read-only review35566806078/job106230168533 ended with exact_hour_artifact_not_available,
confirming no missing-hour artifact was recovered. Its failed read-only wait used
no provider credentials or market capacity. That evidence gap remains unresolved.
A strictly identified check-state correction will mark old hourly check106224946839
failed while retaining its pre-cancellation JSON and a durable before/after audit;
it does not invent a final accounting measurement.

The new marker requests one fresh600-second four-lane smoke. Its source gates,
normal drain, archive checksum/native review and engineering controls must pass
before one independent3600-second hour starts from fresh process state. Prior
smoke/hour time is not reused. No profitability or natural completion is inferred
from deterministic or engineering success.


## 2026-09-21: 437a8445 smoke accepted; remaining authentication scheduling defect

Exact candidate437a844579c5d8e982a172dca7cbe160f066d099, workflow35568442889,
smoke job106234826385 and raw/native review106240924283 passed.
Continuous overlap600.124634884s; normal drain total1605.016779171s. All four
exit0, no restarts, no open positions, reconciled run-specific books.
Archive10626230498,72379323 bytes, verified SHA256
1568c2024fb20b01bbd4ad9febd194bb1130eb2b68f362c27c921597fdfb78d0.
Review10626100967,270828 bytes, recorded SHA256
6b12897805c0b3ec1fd385f4b35c69d2827a05437d76540558189c2b40e3a596.
The repaired isolated artifact staging completed successfully. A separate read-only
file-checksum/SQLite audit is requested in this commit and uses no provider secrets.

Pons4 natural market-sale settlements, zero forced and zero writeoffs. All4 lost:
-115288648968118,-2065046779447658,-2068798264482066,-164747550498457 native quote
units; total-4413881243396299. Exact cohort cash995586118756603701, basis/reserved0,
execution cost40832014544000; native replay and capital integrals complete.
Two positions each survived4 actual provider429 recoveries and one authenticated
mid-operation local session rotation at used200, preserving original identities,
hold clocks, pending state and entry. No position was recreated.
Pump1 natural settlement+22998693 lamports, four-event ledger replay verified.
All full qualification/entry/exit/cost records remain in raw/native archive.
Meteora/Ramses natural0: NATURAL_INCOMPLETE. No profitability claim.

Pump805 physical transports, max getTransaction batch8, zero transaction429;
four null transaction responses remain incomplete evidence. One getProgramAccounts
HTTP429: physical0a640ea9-d162-48b9-a92f-532adb999e8d:413, parameter hash
262df93ae330ba290f9fd13f78d9ec269c31a3f60f9d15a4ffaa5ed7dee62674,
mint86SSLD31hkdCkoaBAMksTzgir7xio9FfKvAysqChpump, finalized minContextSlot448975954,
observed1789972569477526999ns, retry0, original deadline null. Exactly one physical
scan appears, so no duplicate scan is established. Original absent metadata is
not invented. Method/HTTP/RPC-code attribution retained.
Pump one physical-governor miss; one prefetch expiration before transport;
zero queue-capacity/shared-cooldown/lease-wait failure records. Window consumers:
21845 expired (21837 before transport,8 after),296 complete; these are logical
signature interests, not unique missed opportunities or provider429s. Thirty-four
window late-result phase records remain visible. A causal improvement in logical
expiry is not established by unlike live workloads.
Meteora59 observed pools,11 admitted,4 reconstructions,2 economic vectors;
58 signature-history members,zero429,253 physical grants,zero misses.
Ramses282-pool inventory,2 scans,95 grants,zero misses,maxwait18.040898010s.
Maximum RSS: Pump94728192,Meteora59621376,Pons53813248,Ramses32215040 bytes.
Source manifest7c2505cc65e599929e58511f2463875f86228232d30f053754bf0ec9ef639226
and all four canonical overlay hashes match the candidate. Full hosted gates reran.

The independent hour job106240974615/check106241394327 began after smoke review.
Further source-level attribution of19 Pons local admission failures found a concrete
remaining defect: SelectiveEvidenceContext.acquire authenticates a new current-state
session via _rpc before assigning ctx.deadline to rpc.evidence_deadline.
Authentication therefore uses generic priority50 and the30s shared cap instead
of the original five-second candidate deadline. Five recorded connectivity waits
lasted30s. Discovery authentication and open-position authentication were fixed
previously, but this separate current-state path was not.
The hour is SUPERSEDED as replacement certification evidence. The targeted
cancellation requested here requires a fresh<45s snapshot, all four lanes flat and
reconciled, no reserved/pending/committed capital, and all qualifiers already settled.
If refused, existing lifecycle authority continues; no competing market validation
will start. Cancellation never changes historical unresolved books.
A repair will bind the original deadline and foreground priority before current-state
authentication, add regression coverage, and rerun complete canonical deterministic
gates, a new smoke and a new independent hour. No economic or freshness gate changes.

The prior failed-hour check correction succeeded: workflow35568442894,
job106234826153; check106224946839 is completed/failure, preserving its original
pre-cancellation JSON. Audit10624826382,11104 bytes, SHA256
3d5fa165223a89b42232681a7b0f54f781811a6ae7e2a1689db6ccd9938d5a93.
The prior missing-hour evidence gap and seven aggregate historical unresolved Pons
exposures remain recorded; fresh flat books do not resolve that historical exposure.


### Stable-archive audit and current-state authentication regression

Read-only audit35570800072/job106241833861 passed:78 exact file checksums and22
standalone SQLite quick_checks; no errors. It verified committed snapshots in the
original smoke archive without changing native files. Audit archive10625702432,
312072 bytes, SHA2563bca84cf28bfb3bbf3489e483cbc4f8126191575db96514dae68c9facef46613.
Cancellation35570800141/job106241834038 refused while Pump had open exposure.
Audit10626430049,10784 bytes, SHA25622c2c9e110a2b084be40c715de14d7e38b050538b922aa2a318c0ea932f25065.
The latest snapshot subsequently reported that Pump position settled. A new
identically guarded cancellation attempt is requested, retaining the refused audit.

The repair passes ctx.deadline into _rpc before verify_chain and scopes context
rotation as foreground. Position context still wins priority0. Failed replacement
authentication never installs a session; the previously completed session is cleared
after one telemetry archive, preventing repeated double-counting on retries.
Regression cases exercise original deadline propagation, real shared-admission
expiry at4.25s rather than30s, already-expired admission without transport/wait,
failed rotation without old-session reuse or telemetry duplication, later independent
candidate authentication, and position priority/context cleanup.
All changes are acquisition implementation only. Full hosted canonicality and all
deterministic/resource gates must pass before composing any replacement candidate.


### Superseded hour stopped flat; partial archive successfully retained

Exact targeted cancellation35571032945/job106242524772 succeeded after the fresh
guard proved all lanes flat and reconciled, including2 settled Pump qualifiers.
Four-lane overlap309.315109386s; total309.898071626s. This interrupted observation
is not a completed hour or engineering certification.
Partial-hour archive10626455341,14391416 bytes, recorded SHA256
6440ddcce42013962a076ee28bf78e6c9916a69374d5411e0254e505c63b691e.
Unlike the prior c4572 archive failure, isolated staging/upload completed and the
hourly check closed as cancelled. A read-only checksum/native/SQLite review of this
exact partial archive is requested. Original failed cancellation audit is retained.
The full exact pre-cancellation snapshot is appended in results; no native exposure
was relabelled settled by cancellation, and no prior duration counts for replacement.

Cancellation audit10625792486,11823 bytes, recorded sha256:d5bb48f906eb6d89c50af01749caa36ea07632145502a53364d09cbe07805f2e.


### Candidate authentication gates passed; cancellation-aware native review

Build35571033151/job106242525448 atd2db9ed3742f20a6b34ba434a189a76c8df6dde6
PASS:1258 lane tests (Pump292,Meteora392,Pons305,Ramses269),78 supervisor tests,
all3 resource gates, byte-for-byte canonicality and original frozen hashes.
Five new real-admission/authentication regressions pass. Verified Pons overlay
SHA2565cecafc43872bc5a3517b7b1af7792e38d615d2baa6cab68e8bd3d1ad7a14950.
Build artifact10625927434,210226 bytes, SHA256
f95ecf3e484b5d5a584bc4b24874a0a1dd44e1762a6341f5925a8d9d5bca7232.
Complete verified overlays/transcripts are composed by this commit, without live launch.

Partial-hour review35571142383/job106242846594 verified the archive checksum,
then failed because it assumed Pons complete-result.json.gz exists after cancellation.
The runner was deliberately interrupted while flat, before normal Pons finalization;
the collector retained the checkpoint and native journals. This is not the previous
lost ZIP failure. Its failed review artifact10626092073 is retained (584 bytes,
SHA2569d9758d49e963946c6caf998e0644cb0bd816030171d0ed0ba7e62e20b145dbc).
For cancelled runs only, the read-only reviewer may inspect the retained checkpoint
and journals while explicitly marking the complete native final report absent.
It may not infer final lifecycles from that checkpoint. Normal smoke/hour review
still requires the complete report and unchanged engineering controls.


### Partial-hour audit complete; accidental legacy contention removed before replacement

Read-only35571312207/job106243347389 passed65 file checksums and18 standalone
SQLite checks, no snapshot errors. Pons final report is explicitly absent because
of cancellation; retained checkpoint/native books show no Pons positions.
Pump2 naturally settled paper lifecycles, realized+73402696 lamports, nine-event
replay verified; full original entry/exit/qualification/cost path remains archived.
Review10625299976,94271 bytes, SHA256
115e4288ae9e261b7f67ed3fc8276682f344070834704cd962ba5ca4664c9282.

Prelaunch inspection found accidental legacy paper-milestone diagnostics created
by commits without the existing [qualification-build] suppression marker:
35570800018@f63e1e7abf87f17e0babc16ec4436aa6bebb3078 (active shadow job106241833964)
and35571312143@bd2f08ef22790cdc092e917fc8a08b24ed232ff1 (queued shadow diagnostic).
These read-only finalized-stream shadow jobs have no paper lifecycle authority.
An exact run/SHA/branch/workflow/job allowlist cancellation is requested here.
Original success/failure artifacts are preserved by their always-run upload step.
This accidental overlap affects the already superseded interrupted437a8445 hour,
not its earlier completed smoke. It is explicitly not certification evidence.
Every subsequent documentation/build/audit marker will also include
[qualification-build], using the existing workflow control rather than disabling
any deterministic test. No replacement market run starts until those jobs terminate.
Main, all four frozen source heads, prospect branch and separate PR93 policy head
were refreshed and remain unchanged.


### Fresh exact-revision replacement launch after hygiene and review

Cancellation35571461052/job106243796288 completed successfully for both exact
legacy targets. Audit10626127805,3040 bytes, recorded SHA256
fcd24b926c2bf27adcc18a262f28e900b6b0745a21fe1a2a0deefe97ebb2f62c.
Legacy35570800018 retained qualification-vector artifact10626097711 (166 bytes,
SHA2564253285272b963dbb836ccf1e72a526a0a6f102d0616a3973abd78f0a9235e81);
its interrupted buffered report carries no accepted observation result.
35571312143 had no finalized artifact; it was stopped before its queued shadow
diagnostic launched. Job logs and the cancellation audit retain the interruption.
No historical evidence was deleted or natural lifecycle inferred from these runs.

Fresh active/queued/pending/waiting inspection found no competing market job.
Only deterministic paper-milestone35571461072 remained active; its live-diagnostic,
postgrad, longevity, auth-smoke and forced jobs were explicitly skipped.
All original lane heads and manifest/overlay hashes were freshly verified unchanged
except the fully tested Pons acquisition overlay5cecafc4.
This marker launches one fresh600-second smoke at the resulting exact commit,
then one independent3600-second hour only after its engineering and raw/native
artifact review pass. Both start from new process state; no previous time is reused.
The new authentication regressions/full suites/resource gates rerun on the candidate.
The original frozen thresholds, market scopes, provider ceilings and paper-only
authority remain unchanged. Engineering certification is still pending.


## 2026-09-21: 46b3db01 fresh smoke accepted; independent hour started

Exact candidate46b3db017656d2885e9c8d0020d2e95bd6e9c240,
workflow35571580714: smoke106244151600 and artifact review106251211024 PASS.
Four-lane overlap600.120825438s; normal follow-up/drain total1604.350171121s.
All exit0, zero restarts, flat reconciled native books, zero natural/forced fills
in every lane. NATURAL_INCOMPLETE remains; no forced event is substituted.
Archive10627252352,96539575 bytes, verified SHA256
5f22b180e46ec434319a43ced48245b4eab68761945d263174788a72eeed5743.
Review10627486638,983195 bytes, SHA256
33ad7c491cb0db9b044e8fb2122e44635f47909429246dd18b37db3be92c2a05.
Complete raw/native review and exact result are appended under results/.

Final smoke-plus-follow-up aggregates (not600s-only opportunity denominators):
- Pump1441 physical requests, max getTransaction batch8, zero429/GPA scans.
  Fifty-four null transaction responses remain incomplete. Full stream42642 trades,
  392 creation events,381 distinct discovered candidates; no gaps or capacity loss.
  Eight strategy prospect observations,2 admitted late-curve prospects;7 total
  admitted including postgrad work,4 unique evidence-complete candidates,
  21 complete evidence attempts. No qualification.
- Pump window interests2055 complete,8448 expired:8194 before transport,
  254 after transport started. Research89 complete/111 expired(7 before,104 after);
  prefetch2540 complete/715 expired(624 before,91 after),19 retired. Eight waiting
  consumers explicitly censored at shutdown. These logical signatures are not
  independent lost opportunities.
  Attempt phases:1 pump-window expiration before transport,1 physical-governor
  miss,56 late-result phases,550 window transports;2 prefetch expirations,
  26 provider-unavailable attempts,9 background-history deferrals to foreground.
  Queue-capacity/shared-cooldown/lease-wait failure phases zero in retained tables.
  No local failure is credited as provider429. Unlike-market comparisons do not
  establish causal improvement in the logical expiration fraction.
- Meteora59 pools,10 admitted,2 authenticated triggers/reconstructions,0 economic
  vectors, all2 triggers terminally classified. Unsupported frozen-domain shapes,
  absent fresh activity and warmup failures remain visible, not loosened.
  37 signature-history members,zero429,155 grants/no governor misses.
- Pons1300 events observed,328 current-state attempts,276 complete current states,
  25 strategy prospects,20 full vectors,zero qualification. Current-state auth
  missed its already-expired original deadline in0.000352347s atpriority10;
  the second trajectory admission missed its remaining0.026s deadline after0.053s.
  No30s authentication wait. Total1180 grants,2 local misses,maxwait0.902104006s,
  no provider error. Full frozen economic rejections remain visible.
- Ramses282-pool inventory,frontier-gated scans,1 active-pool economic screen;
  97 grants,no local/provider failure,maxwait3.474096342s. No qualifier.
Maximum sampled active broker jobs8. Max RSS Pump102305792,Meteora54591488,
Pons69709824,Ramses31936512 bytes. Manifest7c2505cc65e599929e58511f2463875f86228232d30f053754bf0ec9ef639226
and all canonical overlay hashes match the exact candidate.

Before the hour, all active/queued/pending/waiting lists were inspected: only this
workflow was active, all other queues empty. Fresh hourly job106251255024,
live check106251726679, reran complete gates and passed source/contention checks.
It now starts a new independent3600-second four-lane observation with fresh books
and processes. No smoke/prior-run time is reused. Read-only supplementary inspection
of smoke file checksums and exact null-body signature/attempt attribution runs
separately without provider credentials; it does not modify the running candidate.
The campaign remains paper-only, original policies unchanged, main unmerged,
historical unresolved exposure and prior evidence gap explicitly preserved.


### Deeper raw smoke audit found repeated default-signature hydration

Read-only audit35574182732/job106252183605 verified71 file checksums and18
standalone SQLite snapshots, with no errors. Archive10627561998,1035037 bytes,
SHA2560a753202a88c065ba6047dd0f55f65d7362a3123754eee8389c0b749d57029bb.
The exact raw attribution is appended with this entry.

The54 null_getTransaction error records all request the same signature:
1111111111111111111111111111111111111111111111111111111111111111.
Twenty-nine additional explicit response.result:null records identify that same
signature (including batch responses); this is not54 independent unavailable
transactions. Most repeated work is stream_prefetch, with fresh acquisition
attempts repeatedly renewing transport scheduling for the same unusable identity.
Raw transport instrumentation preserves request parameters and does not redact
signatures. Source inspection found no default-signature admission check.
Primary SDK references establish that this exact base58 value is Signature.default()
and encodes64 zero bytes:
https://kevinheavey.github.io/solders/api_reference/signature.html
https://docs.rs/solana-signature/latest/src/solana_signature/lib.rs.html

The coarse smoke engineering gate passed, but this concrete acquisition defect
supersedes46b3db01 for sustained-efficiency acceptance. Its independent hour has
already recorded natural Pump paper activity; the exact-target cancellation here
requires a fresh<45s flat/reconciled/no-reserved-capital snapshot with every qualifier
settled. If that guard refuses, existing lifecycle authority continues. No running
process is patched, no previous observation time will certify the replacement.

Planned implementation repair: retain default-signature stream observations and
logical consumers with explicit invalid-identity provenance/terminal evidence, but
do not enqueue or retry physical getTransaction work for that default identifier.
Ordinary real signatures, unresolved valid null responses, independent original
deadlines, immutable coalescing, candidate re-entry and full frozen qualification
remain unchanged. No market/pool is removed and no failed evidence is erased.
Complete deterministic/concurrency/resource/hash gates and fresh smoke/hour remain
required after the repair. Historical unresolved positions remain unchanged.


### Default-signature implementation and safe supersession (2026-09-21)
Cancellation run35574595599/job106253470678 stopped only35571580714@46b3db017656d2885e9c8d0020d2e95bd6e9c240 after a3.989s-old snapshot proved allfour lanesflat/reconciled and nooutstanding qualifier. Cancellationaudit10627034208,11760bytes,SHA256cc0910a003b53577528da3888efa070e45f14bb1ce9b35bb6183f01798d18c6c. Partialhour isnotcertificationtime; nativeartifact review follows.
Versioned buildinputs now preserve bothlanes' existing code differences and reject only exactSDKdefault64-zero-byte signature before physicalhydration. Eachoriginal consumer retains itsdeadline and append-only invalid-identity terminal; broad notifications/rawpayloads retained, default observations identified byslot/address/payloadhash instead of conflating distinctevents. Validnull results remainretryable and cannotrevive expiredconsumers. Mixedbatches stillacquire validbodies; directqueue/cache cannotfabricate defaultsuccess. No policy/finality/provider limitchanges.
Eight regressionsperSolanalane cover repeatedbackground rejection withoutRPCconstruction, mixedbatchreuse, foreground deadline/failureattribution, validnullrecovery, observationretention/reentry, queue/cache failclosed, directsharedRPC, andlegacywaitingconsumer. Fullcanonical fourlane/supervisor/resource gates requested; no freshmarketvalidation authorizedbythiscommit.


### Superseded46b3 hour: complete artifact audit
Read-only review35575320116/job106255726574 verified archive10626868488 (34951915bytes; SHA2561603e2d4be91f0e09d5353d575ee2c476ce2a41bf85fedfa8bda2099ee23d694),66filechecksums and19SQLite backups,zero integrity failures. Auditartifact10628520064,93605bytes,SHA2562fda1033bc967dea048d671b987929375845ec99c6fbc7cf12922a8a062b2dd8.
Intentional cancellation total426.78339505s, overlap425.533905826s: NOT an engineering pass or reusable certificationtime. SIGINT exits and missing terminalcomplete files are explicitly censored, not asserted normaldrain. Fresh pre-cancel flatbookguard is retained separately. Pons hadzero naturalpositions; nativecheckpoint retained, nofinal lifecycle inference. OtherDLMM laneszero natural/forced.
Pump3naturalsettled: -927961,+116104376,+131440995lamports; total+246617410; cash5357001710,basis/reserved/pending0. Twelve ledger events replay exactly. Fullentry/exit/history available inhourlyreview andnativearchive; noprofitabilityclaim. GPA429threeindependent scans, parameterhashes1bd303b402eb67ce5f6426013afe832e050cc06db71c655ccedc21ca4f84f89a,1eb7d6646374427cacb990dd93dad879aac857b2f96b20b38491b1709bfb085e,c2b53502e1e64b2e49c61da2b0305bff5d6249ffd6730689652725f317d57da5. Eachdifferentmint/filter/slot andphysicalID, retry_count0,HTTP429,JSON-RPCerrorcodesempty. Originaldeadline null is retained as attribution limitation. Do notdeduplicate unrelated scans.
Pump547physicaltransports,maxbatch8,no getTransaction429/nullresult inthispartialhour. Solana governor noadmissionmiss; Pumpwindow552complete/3223expired, research167complete/8expired,prefetch295complete/145expired/44waitingatcancel; incompleteevidence retained. Pons2localadmissionmisses underoriginaldeadline (0.203s trajectorywait,0.000356s alreadyexpired auth), Ramses86grants0miss; no30s authregression. Meteora186grants0miss,36completeDLMMtransactionconsumers. HistoricalunresolvedPonsaggregate7 remainsunresolved; freshflatbooks donotresolvehistory.


### Default-signature candidate gates and staged validation
Hostedbuild35575320078/job106255726071 at60b3f2551cc180ae8bd681d5cfc6067c9d8b3fff PASSED: Pump300,Meteora400,Pons305,Ramses269 (1274lane tests),78supervisor tests,allthree resourcechecks. Commands/results/exactloghashes undercertification/results/hosted-frozen-repair/default-signature-admission/. Artifact10627539474,215688bytes,SHA256b1e0bf099a64f3a71c38573290148fde1813f04a3e55eed1a7be0e69f0aea42f.
Allfour originalsourcepins andprotectedfiles unchanged; source_manifest_hash7c2505cc65e599929e58511f2463875f86228232d30f053754bf0ec9ef639226. Privateindexreconstructionbyteidentical. NewPumpoverlayf96fe7dd1ed18712edeee5a9c93ebd1721198750c11780fe079ed522860db42e; Meteora01eb6e2e62a6e1696d005676c34ed1353973a2726fc63064b7651cce0e825567. Pons5cecafc43872bc5a3517b7b1af7792e38d615d2baa6cab68e8bd3d1ad7a14950 andRamses8e4eb8de96c73c8812f760733d48dd6921f2817922d959b5c98ca85e903a2786 unchanged. Pump/Meteora existing pacingdifferences preserved.
Immediately beforecandidatecomposition GitHubin_progress/queued/waiting/pending allEMPTY. No marketvalidation contention. Thiscommit composesexactverifiedblobs and requestsonefresh600sconcurrentfourlane smoke, normalpolicy drain andartifactreview beforeoneindependentfresh3600shour. No prioruptimecounts; no recurringjob. ExactcandidateSHA/runIDs recordedafterGitHubcreation. Everycommit usesqualification-build topreventlegacyshadowdiagnostics.


### dbeef7e8 smoke and live-ingress attribution defect (2026-09-21)
Candidate dbeef7e872944b352d00c2da2f8a055fe9896c70,workflow35575632874,smokejob106256761683/livecheck106257304332. Fourlaneoverlap600.144557741s reached; defaultsignature guardexercised twooriginalconsumers andpreventedproviderfailure. Duringfollow-up, Pump pretransport logicalexpiry remainedlarge (29186windowconsumers at604s) despiteonlythree candidateinterests andonegovernormiss. Raw finalauditpending; notclassified as429pressure.
Sourceinspection proves existing Pump history safe_negative screen checks finalized payload.logs but DynamicAddressLogStream didnotpass payloadforordinaryvalidsignatures. Existingtesttest_bootstrap_hydration_clears_initial_stream_miss_without_another_rpc supplied payloadmanually, so itmissed theliveingress wiringdefect. Repair retains full finalizednotification value inhotandappend-onlycompressedarchive; existing negative-only screen andallstrategy gates remainunchanged. Missing/empty/truncated/possiblePumpSwap logsstillrequire authoritativebody. Broadsubscriptions/inventory unchanged. BothSolanaoverlays receivethe payloadretentionfix; noMeteora strategy screenadded.
Newfullgatesrequested withend-to-end finalizedWebSocket→broker→history regressions:1000provenunrelatedobservations remainarchivedwithzeroRPCconsumers; missing/empty/truncated/possiblePumpSwap staypendingonnullbody; latervalidsamepool prospectcanreenter; bothlanesrawpayloadretentionnevergrantsbodyauthority. Thisisan implementationconnection repair, notchanged economicpolicy.
Currentdbeef7e8smoke supersededfor efficiency certification; letitsauthorizedfollow-up/drain finishandpreservefullartifact. Prevent/safelycancelits successorhour; do nothotpatchrunningprocesses. Pons exitednormallyat670.05s, threequalifiers withcampaign_window_closed beforefill, zero naturaltrades, flatnativebasis/cashconservation. Confirmfullnativejournal beforefinalconclusion. Historicalunresolvedexposure remainsunchanged.


Targeted successor-prevention watcher requested for35575632874@dbeef7e8 only. Itwaits forconcurrent-smoke jobcompletion andnonexpired smokeartifact, preservesjob/artifactmetadata, andonlycancels ifhourly-campaign hasnotstarted andno livehourlycheckexists. It refuses aftersuccessorstart ratherthanrisk lifecycleauthority. No runninglanehotpatch, nooverlap-time reuse. Newimplementationbuild35576999390 atfec13a430b8c7c5f3c1528640bc88dbf50c71a76 remainsdeterministiconly.


Stream-retention build35576999390/job106260969777 PASSED: Pump304,Meteora401,Pons305,Ramses269,total1279lane tests;78supervisor;three resourcegates;allfour overlaysbyteidentical/frozenfilesunchanged. Artifact10627984376,217762bytes,SHA256c9bcc9f79b0f55dbb403173971efa759e59473db020f453ec63d835893d6244a.
Beforecandidatecomposition, exposeexistingunique stream_prefiltered_signatures count inPump history.status (rawnotificationsremainfullyretained), withend-to-endregression assertingthe1000filtered count. This observability addition requiresfullgates again; priorpassedartifactretainedandnewlogsuse separatefolder. Watcher35577124205/job106261367051 remainswaitingforsmokeartifact; latest1268.6stotalallbooksflat, onlyPumpfollow-upactive. No successor orreplacement marketwork.


### Fully verified stream-log candidate composed; dbeef7e8 successor prevented
Observability-complete build35577742498/job106263300525 atdd916fa626e08524f307cfcdc3791685a0b5e522 PASSED1279lane tests(Pump304,Meteora401,Pons305,Ramses269),78supervisor,three resourcegates. Allcommandlogsandcanonicality proofs retained undercertification/results/hosted-frozen-repair/stream-log-retention-observability/; earlierstream-log-retention buildlogsalso retained. Artifact10628754333,217833bytes,SHA25690268573cc8bf58eb3a6eb18404fb38e25827b57a95a4ddae371cea5ced0c96d. Allfrozenfilehashes/sourcepins unchanged. Pumpoverlay6055678fc96b8a8a32735849638d831c665886c1515cbea2f107665756e6f047, Meteoraoverlayc2457cfb28e8c94ab6af394f4bca88cc4d8a4617a9d2df33349a658456c9dd60. Pons/Ramsesoverlaybytes unchanged.
dbeef7e8smoke finishednormally,total1604.281396529s,overlap600.144557741s,alllanesexit0/allbooksflat,zero natural/forcedsettled. Fullsmokeartifact10629420043,101420803bytes,SHA2562b12e897b986607dc4b1f54d2fb560f07f555e6c8e2e1a0b7a6572a7e0d22a22. Supersessionwatcher35577124205/job106261367051 cancelledonlyafterfullsmokeartifactfinalizedandbeforehourly-campaignstarted/no livehourlycheck. Interruptedreadonlyreviewartifact10629041070,SHA256cc5d3dad4f8a291755267b25f5de6d4159b1f1ec45ff3f0239989eb6faac505a retained; completeindependentreadonlyreview requestedhere.
Thiscommit composesverifiedoverlays andrequestsreadonlystablearchive/null/stream-admissionaudit ofdbeef7e8. ItdoesNOTstartmarketvalidation. Freshsmoke/hourcandidatewillfollowonlyafterauditandactivequeuehygiene. Originaldefaultsignaturedefectandliveingressdefectremainvisibleinsupersededevidence; nooldtimecounts.


### Complete dbeef7e8 artifact audit and correction
Readonlyaudit35578218957/job106264802003 verified76files and21SQLitebackups withzero failures. Fullreviewartifact10627764719,1398427bytes,SHA25681bd7a5d6bb3bbe3119b2277eb8d3b912360dcc52ea252bc59d00d585c83bd20. Cancellationaudit10629100932,1927bytes,SHA256144a6bae4fb708dba81a8506829531528f63b023190008724598aed66759768d. Fullsmokehasnormaldrain/exit0/accountingPASS butis supersededforconfirmed acquisitiondefect; nohourstarted.
CORRECTION topreliminarypublicsnapshotinterpretationabove: thethreePonsqualified entryattempts endedentry_failed:fill_full_exit_unavailable, NOT campaign_window_closed. Allthree reservationjournals replayverified, zeroentrytokens/cost/fees/proceeds/PnL, cash/basisconservation, releasedreservations, nofillednaturaltrade, nowriteoff. Campaign_window_closed counts referredtoseparatecohortterminalrecords; donotconflate themwithentryoutcomes. NaturalcertificationALLLANESINCOMPLETE.
Pump1127physicaltransports,maxgetTransactionbatch8,0providererrors/429/nulls,0GPArequests;16completeattempts/twouniquecompletecandidates,5admitted,2latecurveprospects,359discoveredthroughfollow-up. Onephysicalgovernordeadlinemiss;48posttransportlateattempts. Window383complete/29242expired(29186beforetransport,56after);prefetch2540complete/633expired(597before,36after)/18retired;invaliddefault1window+2prefetchconsumers. Largeunresolvedlocalcapacityloss remainsvisible.
Streamaudit:54386archivedpoolnotifications;54357ordinarynotificationshadnoretainedpayload;29defaultnotifications retainedpayload. Of5452acquiredunique bodies tiedtopoolhints,1189hadcompletelogsexcludingPumpSwap and4263hadpossiblePumpSwapinvocation. Missing48934bodyobservations arenotassumedirrelevant. Thisdirectlysubstantiates avoidablework frommissinglivepayload; repairimpactwillbemeasured innewrunwithoutclaimingallmissesarefixable.
Meteora22pools/9admitted/6authenticatedreconstructions/5economicvectors,81getSignaturesForAddressmembers,0rateerrors/0governormisses. Pons1657CurveBuyobservations,399minimalcurrentstateattempts/330complete,69admitted,64completeevaluationvectors,3prefillfeasibilityrejections;one0.2slocaltrajectoryadmissionmiss,0providererrors. Ramses282inventorypools,3scans/1evaluated,92grants0miss. PeaksPump100536320,Meteora59949056,Pons81485824,Ramses31936512bytes. Fullnativepaths andfailed/incompleteevidence retained.
Immediatelybeforethisfreshcandidate GitHubin_progress/queued/pending/waiting allEMPTY. Thiscommit startsonefresh600sconcurrentfourlane smoke onthecanonicalrepair, thenonlyonsuccessfulreview+normaldrain onefreshindependent3600shour. No prioruptimecounts. No policy/providerlimit changes. HistoricalunresolvedPonsaggregate7unchanged.


### 7427d71b staged validation in progress
Candidate7427d71b685d9a273732b65265a34e49d4f8bbd5,workflow35578433187,smokejob106265470788/livecheck106266065398. Fresh600.137910658sfourlaneoverlap achieved, allfouralive/norestarts throughobservation. Follow-upcontinues underoriginalpolicy; notyetaccepted. Pump2naturalsettled,currentaggregate-228157030lamports,cash4882227270,basis/reserved0; fulltradeauditpending. GPAHTTP4292retainedforidentityaudit. Pons10qualified withzero reportedfilledbasis/realizedPnl; exactnativeentryoutcomespending. PonsRPCcode3andone transportfailure retained, noauthentication/providererror suppression. Meteora/Ramses normalexitflat.
Thiscommit startsreadonlyaudit waitingonlyfortheexact completed smokeartifact; no providercredentials ornewmarketrun. Auditwillverifyallchecksums/SQLite, actualretainedlogshapes, per-pool actualprefilter countersincludingretiredhistories, method/status/RPCphysicalattribution andnativeaccounting. Itcanfinishwhileindependenthoursetupgatesrun; currentcandidateprocessesremainunchanged. No inference frommissingbodies; do notcountwait/follow-upashourlyobservation.


### 7427d71b smoke accepted; one independent hour in setup
Freshsmoke completedPASS,total1605.157976051s,overlap600.137910658s,allfour normalexit0,zero restarts,flat/reconciled. Nativeartifact10630635604,179317428bytes,SHA256a643d14eb24bdf00ddf1ffde2bff3fa7315192f657a61a8270a8a2888a934166. Standardreview10629578669,SHA25600fc9f236400455f5299ea7cafba35529160faab9c642654ffe2aae35e3aebfe. Independentreadonlyaudit35579907805/job106270124124 verified83files/28SQLitebackups,zero failures; artifact10629858323,1502390bytes,SHA25605d26b1312facbea4b93dd10ae6fd34a62560eb6b28d3329875770db4960a682.
Pumptwo naturallifecycles (risk_stop),-46686299and-181470731lamports,total-228157030;8ledger eventsreplayverified,cash4882227270,basis/reserved/pending0. Everyqualification/entry/exit/nativefeesandcostpath retained. BothGPAHTTP429s areindependent: differentmints/slots/physicalIDs,paramhashesd887f1a8f0e61f7d2f24fff49ce6285cd94f2598fc59fdf27379300d10c0484b and5f446402b1b7f49a1f25e170e5d43f888b306fb330d77a242d88a0da5188cb50; retry_count0,JSON-RPCcodesempty,originaldeadlineNULL (attributionlimitationretained). 1112physicaltransports,maxgetTransactionbatch8,zeroTx429/nulls. Threephysicalgovernormisses/45latetransportattempts/oneleasewait; noqueue-capacityrejection orhiddenoverduejobs.
Prefilterrepair liveevidence:72007poolnotificationsallpayloadsretained;36517complete-lognotifications excludePumpSwap,35488possiblePumpSwap,2truncated. All5741acquiredunique bodies tiedtopoolhints containPumpSwapinvocation; noirrelevant-bodyacquisition observed. Windowpretransportexpiries8814 vs29186precedingsmoke,withdifferentmarketdemand/twovsthreehistorycandidates; reductionisobservednotcontrolledcausality. Window316complete/8852expired(38aftertransport); research242complete/25expired;prefetch2736complete/324expired/4retired/100waiting atshutdown explicitlycensored94andexpired6 viaappend-onlyshutdownterminals. Originaldeadlinesnotrevived; threeprefetchdefaultconsumers terminalinvalid,0defaultproviderrequests.
Pons10qualifiers ALLentry_failed:entry_slippage underunchangedfrozengate, zeroentrytokens/basis/proceeds/PnL; reservation/nativeaccountingreplaypreserved. NoPonsfilledtradeorwriteoffinthissmoke. FourRPCcode3failuresandone transportfailure retained asaffectedbatcherrors; per-responseerror-member auditemptydoesNOTmeanzeroRPCerrors. Correctreadonlyauditlookups toreadretiredPumpterminalhistoriesfromcertification-native/smoke/pump, notcertification-smoke/pump. Priorcounter0wasincompleteauditlookup, notclaimnoactualscreening. Fullrawfileswerepresent/verified; productioncodeunchanged.
Hourly-campaignjob106273649910 startedfreshsetupONLYafterstandardandindependentread-onlysmoke reviewsPASS. Exactsource7427d71b remainscandidate. Thiscommit onlypersistsresultsandcorrectsreadonlyattribution; nohotpatch, noadditionalmarketvalidation.


### Corrected smoke counter attribution and hourly launch
Correctedreadonlyaudit35581274986/job106274481415 succeeded; artifact10630556709,1503153bytes,SHA2561022ea034bf3874337e5e36c4849bc4b3bd300a30b67a60d59542e797bc3c0ea. Retiredterminalfileexistsandwasalwayspreserved undercertification-native/smoke/pump/pump-acceleration-natural-prospective.terminal.jsonl.
Completeactualforeground prefiltercounters remainZERO forall12current/retiredhistories inthissmoke. Therefore doNOTclaim36517archivednegative notifications wereactuallyscreened byforegroundhistory, orcausallyattributeallobserveddeadlineimprovement tothisfix. Those36517notificationswereretained,andacquiredpoolbodiesallinvokedPumpSwap; mechanismhasend-to-enddeterministiccoverage, butthisexactsmokedidnotnaturallyexerciseforegroundnegativecounter. Earlier1189irrelevantacquiredbodiesprovepreviousdefect existed, notsame-marketcontrolledcomparison.
Ponsrawerrors are4exception-onlyRPCcode3failedbatchesand1transportfailedbatch. Actualresponseerror-member listisemptybecausethesefailureswereexceptionswithnoresponsemembers; preserveaffectedbatchmethodsets/physicalIDs/code3, HTTPstatusunknown, donotinventwhichmemberfailed. ExactattributionJSONsaved. Ponslocaladmissionmisses4, allunderoriginaldeadlines/max.241628swait; no30sauthregression. Ramses122grants0miss,max3.48254s. Meteora71signaturehistorymembers0rateerrors.
Freshhourjob106273649910/livecheck106274851741 began2026-09-21T09:06:13Z aftersource/gate/hygienechecks. Exactcandidate7427d71b685d9a273732b65265a34e49d4f8bbd5 inworkflow35578433187; fresh3600srequested, zero smokeuptimeincluded, no recurringjob. EngineeringhourPENDING; Pons/Meteora/RamsesnaturalcertificationINCOMPLETE, historicalunresolved7unchanged. Thiscommit isdurableevidenceonly; currentprocessesunchanged.


### 2026-09-21 — Exact 7427 hourly continuity failure; evidence preservation in progress

The independent hourly run 35578433187 on candidate 7427d71b685d9a273732b65265a34e49d4f8bbd5 failed the required four-lane continuity condition: Ramses exited with code 1 after 3213.884026284 seconds. The 3270.386020959-second checkpoint marks unexpected_exit=true during economic_log_census at finalized block 68699706; no Ramses position was open. Exact exception awaits the complete native process log. This is NOT a successful 3600-second certification and no time will be reused.

At that checkpoint Pump had five natural settlements, realized -184752643 lamports; Pons had four natural settlements, realized -259469250303112 native quote units. All four current books were flat and reconciled; forced lifecycles were zero. The next snapshot contained a new Pons qualifier not yet represented in the terminal capital-book position count, so cancellation was not executed. Remaining lanes retain their original observation/drain clocks to preserve native lifecycle truth. There is no successor market validation; only the read-only exact-artifact review is being started. Historical seven unresolved Pons positions remain unresolved.

Five Pump getProgramAccounts HTTP 429s, zero reported getTransaction 429s, and Pons receipt RPC -32000 plus exception-only RPC code 3 batches remain visible. The auxiliary Pons feed reconnected twice with cross-session sequence discontinuities; per-session zero gap counters are not a claim of continuous feed coverage. Canonical authenticated RPC discovery continues with preserved cursor/catch-up semantics; raw recovery proof will be audited.

Full final artifact, checksum verification, root cause, and any implementation repair will be appended after native drain and archive completion. No strategy, threshold, finality, scope, provider ceiling, or live-money authority has changed.


At the 3753.920968426-second checkpoint, Pons had completed its native cohort normally (seven natural settlements, fifteen qualifiers, zero open exposure); Meteora also exited normally. A targeted cancellation is now requested for the remaining failed-hour follow-up, with a fresh under-45-second all-book flat/reconciliation guard, exact run/SHA identity, Pump qualifier/settlement equality, Pons normal exit plus terminal capital-book position/qualifier equality, zero unsettled basis, complete capital integral, and no reservations/pending exposure. Failed Pons entries are terminal native book positions, not natural trades. The guard must refuse cancellation if any invariant is not satisfied. Full cancellation result and artifact audit remain pending.


The guarded cancellation succeeded in run 35587288297/job 106293442878 after a 25.8409600258-second-old snapshot satisfied every guard. Audit artifact 10632683941 is 13570 bytes, SHA256 bfd369872aa58303d47d65e0edb8eec9b3bea1a05b3d8cb7ee4e146e5f9f1ac9. Failed-hour artifact 10632897444 is 593023678 bytes, SHA256 be3e70c5fae7a90cbfac6070bd04d99f655e0f35a23ff409fc80179ee7b4c1cd. Independent audit run 35586644476/job 106291417322 verified 88 files and 33 SQLite online backups with zero integrity failures. Elapsed time was 3874.561832332 seconds; four-lane overlap stayed 3213.884026284 seconds. Pump's later cancellation is intentional and not normal drain or certification uptime.

Ramses' preserved traceback identifies BoundaryError:event_dynamic_capacity in ramses.py:_dynamic_value called from ramses_universe.py:_decode_economic_logs. The native decoder rejects arrays over 64 elements even within its separate 65536-byte event payload bound. Exact archived-event attribution is being run before any implementation change to determine whether the input is well formed.

Pons has a complete native final result: 15 qualifiers, 8 failed entries (3 entry_slippage, 5 fill_full_exit_unavailable), 7 natural settlements, all losses, aggregate -481026378102351 native quote units. It exited normally with zero remaining cost basis/reservations/unsettled positions and complete capital integral. Pump has 5 natural settlements, aggregate -184752643 lamports; its 20-event ledger replay verified. Every lifecycle, rejected entry, fee/cost path and raw record remains in the archive. Historical seven unresolved Pons positions are unchanged.


The first targeted dynamic-event audit (35587882946/job 106295353216) failed before artifact processing because its script directory did not expose the repository package on sys.path. This read-only audit harness error is retained and corrected by resolving the repository root explicitly; no lane source or candidate changes, no provider access, and no market run occurred.


The second read-only attempt (35587986529/job 106295686353) confirmed the integration checkout does not contain native lane packages at all; those exist only in pinned worktrees. The audit now embeds the unchanged pure Keccak helper from the frozen Ramses source, verifies the standard empty-input vector, and uses the exact pinned liquidity-event ABI definitions. Both failed audit logs remain retained. This is an audit dependency correction only.


### Ramses dynamic-event implementation repair and verification candidate

Read-only attribution run 35588110584/job 106296089354 verified the exact offending finalized WithdrawnFromBins event: transaction 0x4a9d6383f5677b2987fffb71cecc84d8c94cfd67ccd9112918a69700f96d261a, pool 0x45f04989c768dd130b54f7f79dade8c384499833, block 0x4184551, log 0xd. Both arrays contain 140 complete elements, with offsets 64 and 4576 and total data length 9088 bytes; data SHA256 8f9c2ed07850ee35e19f1d207c019a45981c63c5871c0ad8bfa2a510cff0261f. Physical request 73e1a584-0632-4396-a17d-ece5df30eb7a:350 returned HTTP200, no RPC error, retry_count0. This was a valid bounded provider result, not malformed evidence or provider pressure. Attribution artifact10633470922 SHA25689415d084ab034deadd898cea740ee788637f1dd94d75b9b8760bb6bc6b9f241 retains the full event.

The repair changes only Ramses event acquisition decoding: each array count must fit the already-complete payload before allocation, under the unchanged 65536-byte event ceiling. Dynamic offsets may not alias the static head. It does not change strategy ranges, pool universe, admission, economic thresholds, freshness/finality, provider limits, or ledger/replay rules. Eight regressions cover the exact real 140-bin event, broad census continuation including another pool's swap, deposit/withdrawal/transfer arrays, the exact existing byte ceiling, forged huge counts, truncated tails, invalid offsets, and removed/unregistered logs. Full deterministic, resource, canonical overlay and frozen-hash gates must pass before composition or live validation. Previous source overlays remain the active qualification overlays until generated byte-canonical replacements are verified.

Files supplied to the hosted builder: robinhood_research/ramses.py, robinhood_tests/test_ramses_dynamic_event_capacity.py, and the exact archived event fixture. Existing all-lane repairs remain in frozen_repair_inputs.json. Builder proof output gets a new ramses-dynamic-events directory so no prior gates are overwritten. The stale 7427 hourly check is separately being finalized as FAILURE with its prior checkpoint retained and the verified full artifact linked.

Further failed-hour audit: all five Pump GPA429s are different finalized mint/filter/slot identities and physical requests, retry_count0, with distinct parameter hashes6730ba5fc02e837855f53a9ff78f6c410e7dc01a8a75eb4d2848d0fe0f69a604,64155165afb0192848f3620b1f2902d5d235d5a932939c4c1f2a6528a609bd7f,cc92aa0ce417667b82d3f3bb014eb1e3d38b8e7147fe92ff1ee6b3aa8811c048,d4ab6890f47d07759188eb748ae3ce4010264c1758400438fe404bfe14d2c07e,96c2a5b52578f16be15fc79207bd923b4ccc38bcbcaeb45613d6f507e5ea2f1e. Original deadlines remain null for those scans, an attribution limitation. Pump actual getTransaction batch maximum8 and zero Tx429. The actual finalized-log foreground screen excluded69408 pool/signature pairs while retaining all137483 notifications; this time the repaired path was exercised live. Acquired negative-log bodies1663 remain visible and are not assumed avoidable without acquisition-time attribution. Window5410 complete/39679 expired (39215 before transport,464 after); research2697 complete/418 expired; prefetch3202 complete/2518 expired/185 retired/4 waiting at cancellation. Ten invalid-default consumers were retained. Shared Solana67 Pump local misses,0 Meteora misses; Meteora186 signature-history members and0provider errors. Ramses354 grants/0misses/0provider errors before its decoder exit; Pons29 bounded local admission misses, no revived deadlines. Per-method HTTP/RPC telemetry and full failed evidence are retained.


### Verified replacement composition and fresh staged validation request

Hosted build35588675785/job106297857174 on1e250cca2867b7cb0734bfb97b9a504b9c4a2472 PASSED all1287 lane tests (Pump304, Meteora401, Pons305, Ramses277),78 supervisor tests, and all3 resource gates. All eight real-event/decoder regressions passed. Canonical private-index reapplication was byte-identical for every overlay and every protected frozen file hash matched. The generated Ramses overlay SHA256 is4ad9be892befa24ba698778ff9736b43fdb3c36224333b2d906eb1a435c5b23e; Pump6055678fc96b8a8a32735849638d831c665886c1515cbea2f107665756e6f047, Meteorac2457cfb28e8c94ab6af394f4bca88cc4d8a4617a9d2df33349a658456c9dd60 and Pons5cecafc43872bc5a3517b7b1af7792e38d615d2baa6cab68e8bd3d1ad7a14950 are unchanged. Manifest SHA256 remains7c2505cc65e599929e58511f2463875f86228232d30f053754bf0ec9ef639226.

Exact commands/results and resource measurements are retained in certification/results/hosted-frozen-repair/ramses-dynamic-events/. Build artifact10634045352 is222785bytes, SHA256b063cb303ee83e57c9d49d5d0f3a9cab024ebf701d39fb1b584622028ac5115c. Synthetic resource tests made zero provider calls; their filesystem/RSS limits are not claims of live throughput or profitability.

Before requesting replacement live validation, all in_progress, queued, pending and waiting workflow lists were empty. This commit composes only the verified generated blobs and requests one fresh600-second four-lane smoke followed, only through the smoke gate and review, by one independent3600-second hour from fresh processes. No previous smoke/hour time is reused; no recurring job is created. Exact new SHA/run ID will be appended after launch.

The old hourly check106274851741 has been finalized as FAILURE by35588676066/job106297857700, preserving its pre-cancellation text. Audit artifact10633771355 SHA256c2845bb670d36c9c011acfa847399dc258396145fee6ca4730ebf139d99e5eb8. Full failed-hour independent review artifact10632368184 SHA25606f6df7f5979f8ce152dc5b23e71b17c396134dd953b149bf6556037b425c804. Original historical unresolved exposure, all failed runs, exact raw/native records and both profitable and losing paper lifecycles remain retained.


The new exact candidate is65253887d56e0c692d80bb78092f824749f3b6b3 onrepair/frozen-campaign-handoff. Workflow35589047835 (concurrent-smoke job106299025885) is repeating the candidate's full deterministic/source gates before fresh live processes. PR93 was updated with the verified decoder repair, old-hour failure and native drain/accounting results. The PR remains draft/open and its separate changed-policy headc0b8bfb71c1635f60997d92c681d85298bd2030c is unchanged. No merge or signing authority has been introduced.


Replacement smoke check106299590703 is active on exact65253887d56e0c692d80bb78092f824749f3b6b3 in workflow35589047835. At422.368340715seconds all four processes were responsive, with zero restarts/provider errors/natural qualifiers/open exposure. Ramses had completed its second finalized-frontier scan over the unchanged283-pool inventory. A separate read-only audit is now waiting only for this exact smoke artifact; it has no provider credentials or market-launch marker. Smoke engineering acceptance still requires its full600seconds, normal drain and evidence review.


### 65253887 replacement smoke accepted; independent hour pending/running its launch gates

Exact candidate65253887d56e0c692d80bb78092f824749f3b6b3 completed600.126211391seconds of concurrent four-lane observation and normal drain (total1604.724172427seconds) in workflow35589047835/job106299025885/check106299590703. All four native exits were0, zero restarts/unexpected exits, source/manifest/frozen-policy hashes matched, all books reconciled and flat, and smoke_engineering=PASS. Standard review job106306968023 and independent review35589918365/job106301739956 passed. The independent review verified75files and20SQLite online backups with zero integrity failures; all raw provider archives were complete.

Full smoke artifact10634148771:105671564bytes,SHA2560bcb64abd01db540a0aa8d67e7aaf2f3c1dcd2239874fc76e20b3be0b9f925a9. Standard review artifact10634308297:SHA256231170340620b6f4542334b97c6d6fca7aa7dd08e0e1e95d8ecb653c7863f23d. Independent review artifact10634248538:1032601bytes,SHA256c79547dcbb96b8941b41381fa29f679442ad4bcb1fd721394fd47d425b57e2c4. Complete final result, observation-end checkpoint, native audit, stream attribution and method/status/error records are committed alongside this handoff.

Pump:520discovered through full follow-up,3admitted,42complete evidence attempts/two unique complete candidates,0qualifiers/fills. Physical transports939; actualgetTransactionmaxbatch8; no provider errors, no GPA requests, no Tx429/null failures. Window523complete andZEROexpired window consumers. Research548complete/228expired before transport; prefetch2674complete/10retired/16waiting, with all16 explicitly censored by append-only shutdown terminals. One background governor expiry, one lease wait, nine physical-capacity waits,21research deferrals, no post-transport late phase and no queue-capacity rejection.1884actual finalized-log pool/signature exclusions were measured;36309notifications retained.631acquired negative-log bodies remain visible and are not assumed avoidable without acquisition-time attribution. This clean local-window result is materially better than the defective smokes, with differing natural market demand explicitly acknowledged.

Meteora:24pools observed,11admitted,2complete economic vectors,62getSignaturesForAddressmembers,0provider errors/0governor misses. Ramses:complete283-pool inventory,2finalized-frontier scans,oneactivepool evaluated,92provider grants/0misses; no decoder error or provider error. Their natural certification remains incomplete.

Pons:2673observed CurveBuys,398minimal-current-state attempts,41admitted prospects,33complete evaluation vectors,2qualifiers. First qualifier was entry_failed:fill_full_exit_unavailable (zero fill/basis/proceeds/PnL); second was a genuine natural fill that continued through normal drain and settled with realized loss-64808735209048 native quote units. Entry cost basis2503925842594000; actual realized sale proceeds2439117107384952; native execution costs7871830938000. Full entry/exit/qualification/fee/slippage path is in the native artifact. Ledger replay and capital integral are complete; cash999935191264790952, remaining basis/reserved/unsettled0. No writeoff, no forced lifecycle, no post-fill provider failure. Four local admission misses remained within original clocks (overall maximum wait4.437405794s);0provider errors. Natural lifecycle counts Pump0,Meteora0,Pons1,Ramses0; forced0everylane. No profitability claim.

Memory high-water bytes:Pump97001472,Meteora60465152,Pons76451840,Ramses32100352. Public output stayed bounded. The final pre-hour workflow inspection found only this exact market run and its credential-free artifact audit active, no queued/waiting market runs; pending documentation workflow had no live marker and will skip. Hourly job106307032256 starts from fresh process state only after this accepted smoke and its own gates. No smoke time or failed7427hour time counts toward the replacement hour. Historical seven unresolved Pons positions and the old c457 archive gap remain unchanged.


### 65253887 replacement hour completed observation; native drain and raw audit pending

Workflow35589047835/hourjob106307032256/check106307594374 completed3601.286185694seconds of continuous four-lane observation on exact65253887d56e0c692d80bb78092f824749f3b6b3. At elapsed3626.136984025seconds, Meteora and Ramses had exited0 normally, with zero restarts/unexpected exits and flat books. Pump/Pons remained under their unchanged normal follow-up/drain policy. No hour certification is claimed before full normal termination, raw artifact integrity and native accounting review.

At this checkpoint Pump had2natural settled trades, aggregate realized-20661319lamports; Pons4natural settled trades, aggregate realized-726802524305016native quote units (cash999273197475694984,basis/reserved/unsettled0,capital integral complete). Pons19qualifiers include15nonfilled terminal entry attempts; raw audit will verify each separately. No forced lifecycle has been reported. Meteora completed6economic vectors from484observed pools/56admissions, Ramses retained all283inventory pools. Both DLMM lanes have0natural qualifiers and remain NATURAL_INCOMPLETE.

Pump reports2getProgramAccounts HTTP429 errors and no getTransaction429. Their exact parameter/physical/retry identities will be audited. Meteora/Pons/Ramses report no provider errors; local misses remain separately visible. One substantial limitation is Pump logical evidence expiration despite low physical-governor misses. Meteora's2transaction-pressure-overflow cases correspond to its existing16-transaction exact-reconstruction bound, not signature-provider429 or a narrowed inventory.

Pons auxiliary feed header age increased during observation. This header is not assumed to be an L2 block timestamp. The read-only final audit now additionally retains every authenticated Pons block-header response and log range, plus bounded summaries, to establish whether actual acquisition backlog exists before calling coverage healthy. It has no provider credentials and does not alter the running candidate.

The end-of-observation workflow inspection found only this exact market run active, no queued/waiting market validations, and one pending documentation-only workflow without a live-launch marker. Repository recheck still shows main54712c4c6470cc4dc267888f934bd693aac030d0; PR93draft/open headc0b8bfb71c1635f60997d92c681d85298bd2030c; PR91/92andstrategy-admission0982519unchanged; no newer PR afterclosed94. Full branch/PR observations and this exact checkpoint are committed here. Historical seven unresolved Pons positions and the c457 raw-hour gap remain unchanged.


The first full-hour audit35597326342/job106325055578 verified94files/38SQLite backups with zero integrity failures, all raw archives complete, all native books flat and replayed, and the runner's engineering controls passed. Its supplemental Pons-frontier extractor parsed no rows because Robinhood archives contain native (method,params) pairs and unwrapped ordered results, whereas the extractor assumed JSON-RPC wire envelopes. That zero-row output is explicitly NOT coverage evidence. The original audit result is preserved; a corrected read-only pass handles the documented worker.py schema and fails explicitly if no authenticated headers or broad discovery ranges parse. No live code or frozen strategy has been changed.


### 65253887 complete hour: native engineering controls pass; coverage audit remains open

Exact65253887d56e0c692d80bb78092f824749f3b6b3, workflow35589047835/hourjob106307032256, completed3601.286185694seconds concurrent observation and normal drain, total4636.500797635999seconds. All four exits0; zero restarts/unexpected exits; all current books flat/reconciled. Runner hourly_engineering=PASS; standard review106330117897passed. This is not yet campaign acceptance: supplemental authenticated Pons discovery-frontier attribution is pending, and natural certification is separately incomplete.

Full hourly artifact10638031918:858505234bytes,SHA2561661557530a552225e131f7bd0d0f5f8559cbeeb1865ffaabbfa1de1dd1e9064. Standard review10637942194:10313038bytes,SHA25609a887e4a8e1c469874509ad455690da751dcaa0c8598b71f221b8a4d468336e. Independent first audit35597326342/job106325055578,artifact10638121879:10496465bytes,SHA25611f19225fb96025e7dff70009a6ed4bad127335b16f2c8f1eeff3a6074a2f46c. It verified94files and38SQLite online backups with zero integrity failures; all four provider archives are complete. Initial supplemental frontier-parser zero-row output is explicitly limited and preserved; corrected audit35599239146/job106331144698 is read-only and in progress. No market validation is currently running.

Manifest7c2505cc65e599929e58511f2463875f86228232d30f053754bf0ec9ef639226 and all four candidate overlays match their canonical builds. Frozen policy/config/freshness/finality/paper-only gates all pass. Maximum sampled active broker jobs16, no unfinished broker shutdown consumers/jobs. Memory high-water bytes:Pump137109504,Meteora94302208,Pons206761984,Ramses34529280; public snapshots remained bounded around45KB. Shared queues remained bounded; no restart or contention time was spliced.

Pump:1414discovered,19strategy prospects,49total admitted evidence candidates,39unique evaluated,190complete attempts/22unique complete candidates,2natural fills and settlements. Trade1+37778420lamports (demand_deceleration);trade2-58439739 (risk_stop); aggregate-20661319,cash5089722981,basis/reserved/pending0. Eight-event ledger replay verified. Full entry/exit/history/mark/cost path retained.6432physical transports,28804getTransaction members, actualmaximum batch8,0getTransaction429/null failures. TWO program-accountHTTP429s were independent Token2022 concentration scans: mint8tGaHM6rMWweq24eHRKZgohg1Tm1LQ8ripoY8KYtpump,slot449037165,parameter417581922d2d5def60e234b91a235d735154347113363f3fdd9b52da4424582e,physical9a3258c4-fd7b-4e74-8cb9-3b3b54230791:642; mintHCYTjy4f8fdVmHUVw7AyJyV3RQRmzByfdLwVUsCJpump,slot449045429,parameter81b8a02cb891d1fe9956cef821f22f089a48b341ab19fa2492f21a7821da6351,physical5dcfc351-33cd-4ca3-b667-11067221f100:4513. Both retry_count0,distinct timestamps and noRPCerrorcode. They must not be deduplicated. Original scan deadline isNULL in these records, an attribution limitation retained explicitly.

Pump local loss remains substantial and separate from provider failure. Window11291complete/54943expired:53845before transport(53264unique signatures),1098after transport began. Research3713complete/562expired(533before/29after). Prefetch5561complete/5468expired(4910before/558after),268retired;20invalid default-signature logical records never sent as valid acquisitions. Physical phases:2already-expired-before-enqueue;21explicit expired-before-transport attempts;68capacity waits;13governor deadline misses(11window,2research);256post-transport late phases(238window,3research,15prefetch);5local-budget failures and5research deferrals. No queue-capacity, lease-wait or shared-cooldown phase appears in this hour's phase rows; absence of a phase count is not an attribution of every logical expiry to one physical cause. No waiting consumers remain. Actual finalized-log negative screen excluded95433pool/signature pairs, while287285notifications were retained.2923acquired negative-log bodies remain visible and are not assumed avoidable without acquisition-time proof. Physical governor misses are lower than67in the prior failed hour; window completions are11291versus5410, but natural market demand/duration differ and no controlled causal comparison is claimed.

Meteora:484pools,112screens,56admissions,11reconstructions,6economic vectors,0qualifiers/natural trades.178getSignaturesForAddressmembers,847physical transports,0provider errors/0governor misses; broadmarket inventory unchanged. All incomplete and unsupported cases remain visible, including2exact-interval transaction counts above the existing16-transaction reconstruction bound and1runtime-deadline terminal. No interval truncation or boundary weakening.

Pons:15914observed CurveBuys,2298minimal-state attempts,1655complete minimal states,387prospects,335full vectors,20qualifiers.15nonfilled terminal entries are excluded from natural counts. FIVE natural market-sale settlements, ALLLOSSES:
index0 -328473879765551;
index1 -164296251161624;
index2 -167559163205624;
index18 -66473230172217;
index19 -66496796000217.
Aggregate-793299320305233native quote units;cash999206700679694767;basis/reserved/unsettled0; native execution costs55105449598000; all20position journals replay verified and capital integrals complete. Last natural started1789992134.7677567 and ended1789992162.0629628 during authorized follow-up, preserving the original lifecycle and real exit. Zero writeoffs/forced trades/provider errors.27local admission misses remain in original-clock durable records. No ordinary provider failure was reclassified as terminal sale or writeoff.

Ramses:11finalized scans/10frontier advances; unchanged283-poolinventory;10active-pool evaluation records;0qualifiers/natural trades.399provider grants/0admission failures/0provider errors; decoder repair remained stable. Pump/Meteora and Pons/Ramses each received capacity; no hidden mutual starvation. Natural certification remains NATURAL_INCOMPLETE for both DLMM lanes. Profitability is not established. Historical seven unresolved Pons exposures and the older c457 archive gap remain unchanged.


### Confirmed Pons discovery throughput defect; 65253887 is NOT the final accepted campaign

Corrected read-only audit35599239146/job106331144698 parsed11102authenticated Pons block responses and2532broad discovery ranges. Its artifact10637818076 (10715422bytes,SHA256b23cca81d2cdc2f077f3503b6a994ca749086e4ae314b142a339054df24d9465) is preserved. Last broad range68769638..68769647 completed at1789992132.174823173 (physical077b72e5-334b-4012-98b8-8457fb7250b1:6863,HTTP200). An authenticated latest header already read at1789992044.331525830 was block68780342 (physical5c035cab-c7d9-4120-886e-df4e93b02d17:6724,header timestamp1789992044). Thus broad discovery remained10695blocks behind a head known87.843297343seconds earlier. A near-contemporaneous latest header at1789992136.388068126 was68781256 (physical005eabd1-4e21-4e0b-8b42-9b062d80c8a2:6869,age0.388seconds). This confirms a real acquisition backlog; it is not inferred solely from the auxiliary header age.

Source cause: the cohort reads at most one ten-block discovery range, then performs a candidate evaluation on the same loop. The observed archive advances only24837broad blocks across approximately3665seconds despite the authenticated frontier advancing faster. The runner's narrower lifecycle/integrity PASS is retained honestly, but this hour is superseded for campaign acceptance because timely broad observation was not sustained. All source, provider and accounting evidence remains intact. No successor market run has started; all positions drained normally, so no cancellation was necessary.

Implementation repair now enters deterministic verification: coalesce at most FOUR contiguous ten-block observation ranges within the SAME original0.5second poll clock, and issue one bounded physical RPC batch while keeping each logical eth_getLogs range<=10blocks. The authenticated cursor advances only after all requested responses succeed. Preserve per-range1000-event bounds, each buy/sell log, order, chain authentication, transient recovery, candidate original deadlines, source evidence, all qualification and paper lifecycle rules, the2rps shared governor and Ramses fairness. Four ranges remain within the existing post-rotation session headroom even for single-block fallback. No provider ceiling or strategy threshold changes.

Native files changed:robinhood_research/pons_selective_cohort.py andnewrobinhood_tests/test_discovery_range_batching.py. Eleven regressions cover producer/candidate-work backlog, contiguous once-only range coverage, one original poll clock, no-op frontier, unchanged single-range transport, auth fail-closed/no retry, bounded transient recovery with same cursor/ranges, malformed responses, per-range event limits, transport batch capacity, and invalid sequence bounds. Existing deterministic suites will all run; source overlays must remain byte-for-byte canonical. Proof files use a new append-only pons-discovery-range-batching directory.

Counting correction: prior handoff statements calling the pipeline's15914discovered records 'CurveBuys' are overly broad. The source records discovery before its buy-only screen, so that denominator includes both CurveBuy and CurveSell. The supplemental audit now counts exact unique authenticated event topics, separating native warmup from post-warmup discovery, instead of relabeling the existing denominator. Earlier records are retained with this explicit correction.


### Pons discovery scheduling repair verified; fresh staged candidate launch

Build35599677494/job106332546487 at3765362b899bd3eb14733bdf4444bd56733e451a PASSED1298lane tests (Pump304,Meteora401,Pons316,Ramses277),78supervisor tests, and all3resource gates. All11new Pons discovery-batching regressions passed. Every canonical overlay reapplied byte-for-byte, all protected policy/config hashes unchanged. Only Pons overlay changed, toSHA25630473cf97e5284645a5981fad547d46205e9ba62dfa930d34c7e12ccef874089 (Git blobf3afd5277c697cebb217521fb871d3e44886c4fc). Pump/Meteora/Ramses overlays are identical to65253887. Build artifact10637963974:225750bytes,SHA2565aa81d57a65e2bfc9625840bb1bcb04dcbb2154f66dc5b3d47cb93dec2719cb9. Complete command logs, canonicality and gate records are committed in the new pons-discovery-range-batching proof directory.

Final exact event audit35599677606/job106332547137 establishes7814CurveBuys and8100CurveSells after native warmup, totaling the pipeline's15914discovery records. Warmup separately contained287buys/588sells. Artifact10638321902:10715632bytes,SHA256d5f122a7a937f021a3b6ef9fddd3e3a8f4be8a825bf7a9835085422d4f0f1a5e. No combined buy/sell denominator is relabeled as buy count going forward.

The standard smoke/hour artifact-review jobs now call the already-exercised complete inspect_stable_artifact.py audit (checksums,SQLite,native accounting,method/scan attribution and authenticated frontier evidence), keeping hourly-campaign dependent on smoke-artifact-review. Both scripts are compiled in the existing pre-live gate. This strengthens the read-only prerequisite; it does not modify market code or remove an existing check. The staged workflow reruns all deterministic/source gates on the exact newly composed candidate before any fresh market process starts.

Immediately before this launch, in_progress/queued/pending/waiting Actions lists were all empty. No cancellations were needed. This commit composes only the verified overlays/proofs, workflow audit strengthening and append-only evidence, and requests one fresh600second concurrent smoke followed, only after its complete review, by one independent3600second hour. No prior observation/drain time is reused. PR93 records the confirmed old-hour coverage defect and continuing repair. Frozen strategy/economic/freshness/finality rules, all market scopes, provider ceilings, paper-only authority and historical exposure remain unchanged.
