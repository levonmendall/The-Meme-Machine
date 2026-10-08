# Next finite provider proof — specification, currently BLOCKED

**No provider run is authorized. Both earlier authorizations are consumed.**
This is the minimum useful *warm-history combined* design, with an explicit cold
startup feasibility gate. It cannot be executed by passing larger numbers to the
old harness: that harness accepts at most 600 wall / 180 steady seconds and
constructs cold Pons state. Those bounds remain intact. A reviewed executor must
implement this specification, pin its final commit/tree, and pass offline budget,
seed-provenance, clock and stop tests before an authorization can be used. The
currently published implementation revision and captured source hashes are
recorded in [PUBLICATION.json](PUBLICATION.json).

## 1. Pons startup determines whether a useful short proof exists

The stored immutable Robinhood headers include block 41,443,136 at timestamp
1,787,231,172 and block 82,886,255 at 1,791,418,430. Their average is 9.897436
blocks/s. Applying that rate to seven days estimates **5,985,970 blocks** and
**149,650 forty-block discovery turns**, preceded by about 27 binary-search header
steps. Each full turn requests four ten-block log ranges plus boundary/reorg
headers and a latest header: approximately **1,047,550 logical elements / 299,300
physical HTTP attempts** for the initial frozen domain alone. Caching may reduce
some calls; authentication and candidate history add work. These counts are
estimates, not recorded full-bootstrap usage.

The most optimistic bound allows free/cached headers and one physical batch
per forty-block turn at 0.5-second pacing: 80 blocks/s. Ongoing chain growth then
projects `5,985,970 / (80 − 9.897436) ≈ 23.7 hours`. Two fresh physical requests
per turn imply approximately 40 blocks/s and **55.2 hours** of catch-up before
Current discovery/evaluation, authentication/increments, RPC latency or fairness.
The proof loop's 0.5-second wait overlaps the gap to the next physical admission;
do not double-count that wait as an extra independent slot. Using 12 blocks/s
for variability yields about 29.6 / 72.0 hours for the same two scenarios. No
exact seven-day block boundary or complete candidate-hydration volume is known
from this small capture. These are planning projections, not actual cost or
duration guarantees. Existing cache reuse is a saving only when physical delivery
is genuinely avoided; the optimistic cached scenario is not a measured saving.

The corrected capture establishes one bootstrap binary step and no complete
Survivor discovery cursor. The attached inspected captures provide **no complete
authenticated seven-day Pons seed**. The one-line witness-count repair is
necessary for progression, but does not shrink this history domain.

Therefore a cold combined proof is **BLOCKED** under a minutes-long authorization.
Starting high-volume Solana logs while waiting days for Pons would spend provider
allowance without producing the requested concurrent sample. Do not authorize
that sequence. Do not narrow seven days, increase the forty-block runtime slice,
relax 0.5-second pacing, synthesize completeness, or silently skip Pons.

A separately authorized Pons-only historical preparation may eventually produce
a seed, but its true candidate-hydration cost and duration cannot be bounded
usefully from this tape. No such acquisition is requested or authorized by this
handoff. Prefer a validated existing full snapshot if one becomes available.
Snapshot reuse is a provider saving only for physical calls demonstrably avoided;
its history must remain authenticated and current continuation work must still
be measured.

## 2. Preflight before any paid or public market call

Require an independently reconciled complete Pons snapshot with original seven-day
discovery domain, all retained nominations and required per-candidate histories,
native block hashes, canonical provenance, immutable cache domain and strategy
hash. Pin the snapshot and its verification receipt by SHA-256. A single cursor,
empty candidate list, cache hit or claimed `complete=True` flag is insufficient.
Its bounded tail must be small enough to resume within the startup envelope;
initially declare at most 1,600 discovery blocks behind the verified seed tip,
then validate continuation at the first authorized live head. A larger tail is
BLOCKED; do not start Solana feeds or spend a cold bootstrap allowance by accident.
No qualifying seed currently meets this gate.

Pin exact executor/source commit and tree, approved policy
`e87385900145e53956df18956ee2390f0d95787e6ffc44243251f9b147eb65f2`, four native
strategy contracts and CPython 3.12.14 dependencies. Preserve the integration
commit ancestry and all original strategy hashes. Use a new disposable proof
directory on the existing attached volume. Clone only validated **evidence**, not
production monetary books. Refuse paths resolving to the original epoch, live
state, `/opt/meme-machine`, or a prior unique capture. Open no production money
book. No deployment/service operation, runtime startup-blocker bypass, signing or
financial provider method is part of this proof.

Verify free attached-volume space for the full 16-GiB stock ceiling plus at least
4 GiB cleanup/recovery reserve. Keep temporary files, raw captures and traces on
that volume. Do not buy storage. Allow only the existing Solana Alchemy HTTP/
Yellowstone/WS providers and native Robinhood Alchemy/official public observation
RPC. Pin credential-free endpoint fingerprints and read-method allowlists. The
public Pons endpoint counts against the same Robinhood element budget. Capture
every physical attempt, batch element and retry before dispatch; record native
subscription attempt, acknowledgement/first delivery and rejection separately.

Review the new one-run resource allowance and uncertainty about actual billing.
Authorization must name the final executor revision and seed receipt. Any
missing input or mismatch is **BLOCKED with zero test-provider calls**. The
previous approvals cannot satisfy this gate.

## 3. Finite envelope derived from active delivery

The corrected capture averages 3,656,638 B/s over actual delivery and peaks at
5,247,721 B in one second. The plan uses **twice that observed peak**, 10,495,442
B/s, to allow variable activity and additional position interests. This remains
a short-sample projection; actual larger workload stops at the bound and cannot
be called successful.

| Resource / time | Proposed maximum or minimum |
|---|---:|
| Total hard wall, including shutdown | **900 s**, one run |
| Warm startup/catch-up/release envelope | **240 s maximum** |
| Useful concurrent steady delivery | **600 s minimum**, after all four evidence domains are ready |
| Reserved shutdown/flush/receipt time | **60 s**; no new request after acquisition closes |
| Charged native application payload | **10 GiB = 10,737,418,240 B** |
| Native early stop/headroom | **512 MiB** reserved; stop at 9.5 GiB even if otherwise healthy |
| Native planning CU ceiling | **20,971,520** (`ceil(10 GiB / 512)`) |
| Solana requested RPC elements | **50,000**, retries and batches included |
| Robinhood requested RPC elements | **10,000**, paid and public combined |
| Total logical RPC elements | **60,000** maximum |
| RPC planning CU ceiling | **6,000,000**, existing method weights; 100 per Robinhood element |
| Total planning CU ceiling | **26,971,520**, not actual billed CU |
| New temporary storage stock | **16 GiB**, all proof files/DBs/WAL/traces included |
| Cumulative process-group disk write bytes | **32 GiB**, separate from stored stock |
| Compute / system memory | Existing **2 vCPU / 8 GiB**, no purchase |
| Proof group RSS stop threshold | **4 GiB**, with system available memory below 2 GiB also stopping |
| Required native admission rejection allowance | **0**; stop on first RESOURCE_EXHAUSTED/rejection |

At the conservative rate, 840 acquisition seconds project **8,816,171,280 B**.
Adding 512 MiB headroom gives 9,353,042,192 B, below 10 GiB. This is about 160
times the old 64-MiB allowance, because a meaningful window at the measured log
rate requires gigabytes. The reserve covers at least four simultaneous maximum
16-MiB frames (three recorded native streams plus WS), added position streams,
and roughly 20 seconds of the conservative byte rate. Before opening additional
streams, recompute the in-flight reserve from the *actual* maximum stream count;
refuse admission if 512 MiB is insufficient. Already delivered stopping frames
must still be charged/captured. Do not cancel a read and hide its received bytes.

Observed capture compression is useful for storage projection, but the 16-GiB
ceiling counts actual compressed output, databases, WAL and traces rather than
assuming a fixed ratio. Per-file cumulative WAL writes and page stock are
separate measurements. RPC ceiling estimates are deliberately much larger than
the previous 132-element partial run, allowing selective full qualification and
maintenance; no claim that 60,000 elements guarantees all market arrivals is made.
No candidate population cap or economic evidence loss is permitted at saturation.

Actual billed CU, native tariff, TLS/wire overhead and currency cost remain
UNMEASURED. Billing units may differ from the diagnostic weights. If a hard
currency/billed-CU ceiling is required, obtain the account's authenticated billing
mapping and enforceable cap before authorizing; do not invent a price. The stated
resource limits are hard regardless of provider billing uncertainty.

## 4. Useful sample and scheduling requirements

Release the steady clock only after native admission, initial independent coverage
and Pons warm continuation converge. Snapshot preparation belongs to startup,
never to an invented shortened economic window. Keep all original candidate
deadlines during startup, retries and release. Maximum startup exhaustion is
INSUFFICIENT_SAMPLE or BLOCKED, not permission to start a new 600-second timer
outside the total 900 seconds.

* **Pump Current:** at least 20 complete production evaluation vectors with the
  full original observation/qualification windows and exact event identity/order.
  A complete economic rejection is a technical sample; coverage failure is not.
  Evaluate all due candidates according to unchanged native scheduling, even
  when sample minima have been reached or funding is unavailable.
* **PumpSwap Survivor:** at least five complete independent recovery/evaluation
  histories within original 4-hour–7-day eligibility, with authenticated
  Pump-to-PumpSwap graduation linkage, full required historical windows and a
  continuous live extension. No 10-minute capture can create these histories from
  nothing; validated historical evidence is a prerequisite. Preserve reactivation,
  cheap history and Current/Survivor independence. Require at least one newly
  observed, independently witnessed graduation continuation where market activity
  permits; its absence is INSUFFICIENT_SAMPLE for that criterion.
* **Pons Current:** at least 20 complete native evidence vectors and 600 seconds
  of bounded current discovery continuity, with original nomination/authentication
  deadlines, quote freshness, fairness and physical 0.5-second pacing.
* **Pons Survivor:** authenticated complete seven-day domain and all required
  candidate histories before steady release, at least five complete independent
  Survivor evaluations, and continuous forty-block progression/canonical boundary
  witnesses through the steady window.
* **Positions:** at least 30 complete maintenance cycles per regime, spanning
  at least 300 seconds, executed at the unchanged native safety cadence, with
  real authenticated states, executable exit/settlement evidence and high-water
  marks. Retain real quantities and original 5% family-equivalent basis in isolated
  position-equivalent diagnostics. No profitable entry or actual funding is
  required; no thin fake quote/partial account sample may count as complete.
  All periodic cycles, failures and deadlines must be counted, not just 30 winners.
* **Shared capital:** run the unchanged isolated 64-request/four-connection
  authority fixture during each half of steady provider load, recording all
  grants, denials, native durable deliveries, conservation and replay receipts.
  Compare with the accepted offline isolated/combined results. This is a
  disposable fixture, not a production funding cutover. Zero five-second fixture
  misses is required, with p50/p95/p99 and full native-safety distributions reported.

Maintain full canonical reconciliation against independently enumerated successful
and failed signature/index witnesses, finalized continuity, exact line indices
and raw lineage hashes for every required interval. Partial startup slots remain
uncovered. Required history or missing identity must be explicit. Measure physical
and local duplicate classes, below-floor delivery, reconnect overlap and per-field
volume to see whether high volume remains necessary under real positions.

Require all 600 steady seconds to include ongoing acquisition: time after a byte
stop, queued processing or shutdown is not active steady delivery. Demonstrate
queue drainage repeatedly during active delivery; one empty shutdown queue is
insufficient. Report arrival/completion rates and work classes in 30-second bins,
peak depth, p50/p95/p99 original age/residence and oldest wait. No positive queue
or join-tail trend across three consecutive bins; final required independent
coverage must catch up before orderly close.

## 5. Clock and resource instrumentation

For each economic identity record chain block time, first **locally observed**
finalized witness, upstream timestamp, local wall/monotonic receipt, decode
start/end, last prerequisite/join readiness, owner admission/claim, durable commit,
outbox staging/consumer durable acknowledgement and qualification completion.
The repaired source already emits receipt/decode/join/owner/durable/publication
diagnostics. Use existing durable outbox/consumer acknowledgements to link exact
identities and completion. Add only missing minimal per-work clock boundaries in
the reviewed executor; keep clock reads outside any authoritative timestamp
assignment. Native strategy deadlines remain original wall/monotonic deadlines.

Provider dispatch and true chain finalized availability remain **UNMEASURED**
unless the provider supplies authenticated timestamp semantics. Label first local
finality availability as a local observation, never as chain-finality duration.
Socket-arrival/kernel or gRPC internal buffering times likewise remain UNMEASURED
if not exposed. Report clock offset/resolution bounds and replay prefixes; never
sum mixed wall and monotonic clocks or advertise created-age as provider latency.

Sample the full process group/cgroup every 0.2 seconds and retain final child CPU
receipts: CPU user/system, RSS/PSS where available, memory peak, event-loop lag,
threads, disk I/O and all children. Summarize 30-second/whole-window utilization,
observer work separately and together. Desired mean steady CPU is at most 90% of
two CPUs; exceeding it is FAIL for headroom even if safety survives.

Count successful `write`/`pwrite64` bytes by actual FD/path for main DB, WAL and
capture files, plus sync counts/latencies and WAL peaks/checkpoints. Existing
`strace -f -yy -s 0` tracing can do this without logging payload strings; its
overhead must be measured offline and reported. Keep a finite trace-size allowance
inside the storage ceiling. Process `write_bytes`, WAL file size, cumulative WAL
bytes and logical/canonical bytes are distinct. Record amplification against both
canonical bytes and full received bytes, without treating it as provider CU.

## 6. Stop and result contract

Stop admission and begin accurate cleanup on the first authorized ceiling,
unapproved endpoint/method, required provider admission rejection, corrupt evidence,
unresolved identity contradiction, loss of required canonical coverage, native
position safety starvation or original native position deadline miss. Stop on two
consecutive candidate original-deadline violations, sustained owner depth above
32/64 for five seconds, any owner-capacity overflow, three consecutive 30-second
bins of queue/join growth, insufficient shutdown byte/frame reserve, RSS/system
memory threshold, temporary-stock/write ceiling, or less than 4 GiB volume reserve.
Do not drop economic events to stay below a ceiling.

At acquisition close, reject new requests, cancel/close transports, count/capture
physically received frames, finish or explicitly mark queued work, flush durable
receipts and observer output, record unfinished identities/gaps and stop reason,
hash raw evidence and per-file manifests, and produce results within reserved
headroom. Preserve evidence before removing disposable working copies. No extension,
retry or reseed is implied. Inability to flush/stop within bounds is FAIL.

| Criterion | PASS | FAIL | INSUFFICIENT_SAMPLE | BLOCKED |
|---|---|---|---|---|
| Canonical completeness/order | Every required interval independently reconciles | Gap/contradiction/corruption; any fabricated proof | Required event/continuation population absent with honest partial output | Missing validated historical prerequisite |
| Four candidate evidence domains | Sample minima and complete unchanged windows | Changed decisions/lost eligible candidate or repeated original-deadline misses | Too few complete vectors or startup/resource stop before minima | Seed/source/executor prerequisite absent |
| Native positions | All four minima, full native cadence, zero safety starvation/miss | Any native safety miss or partial observation counted as complete | Too few legitimate executable position-equivalent histories | No authenticated position workload can be prepared |
| Pons concurrency | Current continuity and seven-day Survivor continuity maintained | Physical pacing/fairness/identity/deadline violation or history regression | Steady workload incomplete without a detected correctness violation | Cold domain cannot fit the finite envelope |
| Shared capital | Fixture conservation/order/replay, no >5 s miss | Conservation/order/durability error or fixture latency breach | Fixture incomplete before stop | Approved fixed source/policy unavailable |
| Drainage/admission | All required streams deliver; 600 active seconds, repeated drainage | Rejection/queue-growth/overflow/coverage-loss stop | Honest early ceiling or absent position population | Unsupported required subscription or invalid seed |
| Resource headroom/cost | Whole group bounded, stock/write/rate measured; CU labeled honestly | Ceiling breach, hidden traffic or misstated billed cost | Useful interval ended at a correctly enforced ceiling | Enforceable requested cost mapping unavailable |
| Overall technical proof | Every required technical criterion PASS | Any FAIL | No FAIL but any sample criterion insufficient | Any mandatory preflight BLOCKED |

Economic profitability is not a PASS criterion and is not measured by a bounded
provider proof. Technical PASS still requires owner review before any CAPACITY
readiness or production action. The existing production blocker cannot be cleared
by offline replay or this planning document.

## 7. Concrete proposed authorization, not granted

After the seed and executor preconditions are satisfied and their exact hashes are
published: authorize **one isolated PAPER evidence proof**, at most 900 total
seconds, at least 600 useful steady seconds, 10 GiB native payload, 50,000 Solana
and 10,000 combined Robinhood RPC elements, 26,971,520 diagnostic planning CU,
16 GiB temporary stock and 32 GiB cumulative process writes, on the existing
two-vCPU/eight-GiB host. Require the sample/stop/result contract above, preserve
the original epoch/funding authority/blocker, and grant no deployment, historical
bootstrap purchase, extension or retry. Actual billed CU/currency uncertainty
must be explicitly accepted or bounded using authenticated account billing.

**Current request readiness: BLOCKED.** There is no qualifying Pons historical
seed or final executor implementing this larger envelope. Do not consume another
provider allowance to work around that fact. The immediately reviewable decision
is whether to commission separately bounded authenticated Pons history preparation
or supply an already validated complete snapshot; its source and cost require
separate authorization. No cold-history spending authority is bundled here.
