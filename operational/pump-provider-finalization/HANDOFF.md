# Pump/PumpSwap provider finalization — offline findings and targeted repairs

The corrected capture does **not** establish sustained provider capacity. Its
dominant cost is program-log delivery, rather than transaction bodies or large
duplicate subscriptions. It contains only **2.379 seconds of physical delivery
after Model B release**. The quoted 18-second and 37-second measurements are
upstream timestamp ages during replay; their decomposition into finality,
provider delay and local buffering is unavailable. Local owner scheduling and
publication delay are independently demonstrated.

This branch repairs repeated acquisition writes, repeated WS JSON materialization,
a reproducible Pons history-slice rejection, and misleading proof observations.
It does **not** claim a physical provider-byte or billed-CU saving. The provider
certification blocker remains. No provider call, epoch opening, deployment,
service restart, migration, funding cutover or resource purchase occurred.

## A. Source, authority and preserved evidence

The dedicated branch starts at
`510b61d1950ae54c8b0435b7b7cae3aad0bcc1fe`, tree
`ec76868b459c504b81bd4240f6f8c0236e3d897a`, on
`integration/shared-capital-paper-20261007`. The integration checkout was clean;
the authoritative remote branch still named that commit when inspected. Work is
isolated at `/mnt/volume_nyc1_1790918115030/pump-provider-offline-20261008` on
`repair/pump-provider-offline-20261008`. Other checkouts and remote heads were
preserved. See [PUBLICATION.json](PUBLICATION.json) for the accepted source revision
and [VALIDATION.md](VALIDATION.md) for commands/results.

The two original captures remain on the attached volume:

| Capture | Compressed tape SHA-256 | Tape size |
|---|---|---:|
| `sc-proof-corrected-20261008/provider.frames.zlib` | `edc1ab35e5f2fc6bc4e9bfc35b4c9edd1cbe2103e2a67a57a40c9e4b29aed90c` | 7,593,762 B |
| `sc-proof-20261007/provider.frames.zlib` | `8ed77db5fedbea8b150a7a86fa035ca24929353f3c06aff889f0364808c41c38` | 10,072,624 B |

Capture manifests, including the original proof's nonempty recovery WAL, are in
[BYTE_LATENCY.json](BYTE_LATENCY.json) and [PRIOR_CAPTURE.json](PRIOR_CAPTURE.json).
Every previously inventoried evidence file retains its original checksum.
Read-only SQLite inspection created some empty WAL/SHM sidecars; these contain no
new economic evidence. No unique capture or recovery file was deleted. No large
preservation snapshot was made. Disposable replay databases, full parity rows,
profiles and syscall traces remain at
`/mnt/volume_nyc1_1790918115030/pump-provider-offline-evidence-20261008`.

The capture's Git label predates publication, but **all 29 recorded source hashes
match the published integration source**. The reference replay therefore uses
the published commit, rather than trusting an earlier mutable workspace label.

## B. Physical bytes and economic information

Corrected charged native payload is **50,331,681 B**. The retained tape has
**50,330,766 B**: 48,501,501 WS bytes and 1,829,265 Yellowstone bytes. The final
**915 B** were charged by the global stop before the observer wrote the frame.
Its contents cannot be reconstructed. The new harness captures that stopping
frame without granting it canonical authority. The original proof has the same
observation defect, with 9,691 charged-but-uncaptured bytes.

| Rank / component | Physical bytes | Messages | Meaning / avoidability |
|---|---:|---:|---|
| PumpSwap successful logs | 27,538,305 | 9,819 | Economic trades plus full execution traces; authentic ordering and truncation checks require retained successful logs |
| PumpSwap failed logs | 13,400,141 | 6,967 | Failed attempts have no committed economic events; this standard WS filter still delivers their logs |
| Pump successful logs | 4,521,806 | 1,246 | Discovery/create, bonding-curve trades and migration evidence |
| Pump failed logs | 3,041,169 | 4,352 | Same physical filtering limitation; failed native statuses remain necessary witnesses |
| Candidate status packets | 1,673,692 | 16,352 | Signatures, true transaction indices and success/failure; no transaction bodies |
| Shared block metadata | 72,165 | 345 | Block time/identity and finalized continuity |
| Scout account updates | 63,669 | 263 | 56-byte account-data slices plus native account envelope; discovery locators |
| Shared finalized slots | 11,288 | 345 | Independent linked finality |
| Candidate block metadata / slots | 8,451 | 70 | Independent candidate-stream continuity, not redundant completeness authority |
| WS subscription acknowledgements | 80 | 2 | Two fixed program subscriptions on one delivering WS connection |

Program-log traces constitute **96.37%** of charged native bytes. Failed WS
notifications are **16,441,310 B**, or **33.90%** of WS delivery. Successful logs
include 25,085,434 bytes of PumpSwap JSON log values and 4,210,553 Pump log-value
bytes. All decoded log strings need not become Python objects, but the provider
still transmits them.

Exact cross-program duplicate WS deliveries account for **96,052 B / 17
messages**, only 0.198% of WS volume. Cross-stream native duplicates total
**8,451 B**, representing independently requested metadata/finality. No corrected
capture reconnect or filter rebuild was observed. These are not the dominant
cost. A shared Pump/PumpSwap economic delivery cannot safely be removed by
discarding one program's interests: migration and the two independent histories
must survive. Duplicate detection already preserves canonical identities;
it generally occurs after successful-log parsing/join work.

The native provider delivered **1,548,879 status bytes below the requested
`from_slot`**, plus all 63,669 scout-account bytes below its requested floor.
These are real physical replay-prefix costs. Local rejection of statuses below
the floor does not refund them. Scout locators still legitimately discover 169
identities. The implemented request already carries `from_slot`; this capture
does not prove a narrower supported provider request can suppress that prefix.

The unique successful logs contain 7 Pump creates, 917 Pump trades, 1 migration
and 4,286 PumpSwap trades: **5,211 decoded economic events**, whose event JSON
totals approximately **1.743 MB**. This is an *informative extracted size*, not an
authenticated provider projection or a replacement canonical stream. The full
trace supplies program provenance, line indices and truncation detection.
Only 287 events have complete independent native witnesses in this tape.
Missing witnesses stay explicit; decoded raw facts never certify intervals.

The supported standard [`logsSubscribe` request](https://solana.com/docs/rpc/websocket/logssubscribe)
allows one mentioned address and commitment; it provides no success-only or
log-field projection. Yellowstone already requests statuses, metadata, finalized
slots and sliced accounts. Its documented [`from_slot` historical replay](https://www.alchemy.com/docs/reference/yellowstone-grpc-historical-replay)
does not authenticate a physical dispatch timestamp. No evidence justifies
changing the frozen economic universe, removing failed signature witnesses,
reducing finality checks, capping candidates, or replacing Model B. A vendor
success-only/log projection could be useful only after a supported capability and
same-tape provenance/completeness parity are established; none is asserted here.

## C. Four separate costs and ranked local work

1. **Delivered:** 50.332 MB charged application payload; wire framing, TLS and
   NIC traffic are unmeasured. No implemented subscription change means no
   demonstrated physical saving.
2. **Decoded/processed:** baseline WS source parsed each frame twice; the repair
   validates once with the existing bounded native JSON parser. Full successful
   messages remain exact. Failed log strings remain native, avoiding materializing
   12,658,383 UTF-8 bytes / 182,803 strings in the retained Python projection.
   Both paths still scan the complete physical payload. Final quiet decode trials
   have median CPU 0.739 vs 0.532 s; an earlier exploratory pair was 0.726 vs
   0.724 s. Allocation/parse-pass reduction is demonstrated, but these component
   trials do **not** establish a whole-process CPU speedup.
3. **Stored/written:** the captured canonical DB is 4,075,520 B; its raw observer
   tape is 7,593,762 B, and all disposable proof storage was 14,093,147 B. These
   are stocks. Captured process I/O separately reports 114,298,880 write bytes
   and 91,174,186 `wchar` bytes over 20.288 seconds, including observer and every
   database. They are not solely SQLite WAL traffic. A monitor saw a 26,957,192 B
   WAL before checkpoint; cumulative original per-file WAL writes are
   **UNMEASURED**. [JOURNAL.json](JOURNAL.json) measures per-file writes in a separate
   offline replay, with tracing overhead explicitly excluded from latency claims:
   **43,037,872 canonical WAL bytes + 4,497,064 consumer WAL bytes**, identical
   before/after, plus **16,133,500 B of temporary SQLite sorting writes**.
   WAL/logical-canonical-body amplification is **170.67×** against 278,519 B of
   replayed event bodies. This includes discovery, references, coverage and
   handoff work, so the denominator is not all useful logical DB work. Traced
   sort files were small ephemeral `/var/tmp` files; the reproduction tools now
   explicitly direct SQLite/temp files to the attached-volume output directory.
4. **CU:** corrected planning native CU is 98,305, computed as
   `ceil(charged_bytes/512)`; RPC planning CU is 12,210 across 12 Solana and 120
   Robinhood request elements. Actual billed CU and dollar cost are
   **UNMEASURED**. These estimates are diagnostic weights, not proof of provider
   tariff or a billed saving. The repairs do not cancel a demonstrated physical
   request; cache/job reuse is not advertised as a provider saving.

Ranked DB page stocks are: candidate-history outbox 516,096 B, rolling economic
events 450,560 B, acquisition observations 237,568 B, coverage data/index
425,984 B combined, and promotion-history metrics 176,128 B. These include
legitimate canonical history, references and durable consumer handoff; similar
facts serving distinct authorities are not automatically waste. Canonical event
body stock is 273,095 B, published outbox body stock 258,428 B. No canonical
history or recovery artifact is removed by this repair.

The original owner produced 1,517 capacity-pressure observations; 999 repeat the
same `(job,kind,body)` and do not convey a changed acquisition request. A
controlled reconstruction of **1,516 existing-job reassertions** preserves the
exact job projection while eliminating **3,032 SQLite mutations** and
**19,800,064 process write bytes**. Final baseline reassertion CPU/wall is
0.282/1.803 s; repaired is 0.0199/0.0199 s, with zero writes. Captured final job arguments are used;
unrecorded original caller arguments cannot be reconstructed exactly. The test
also proves genuinely higher priority/earlier deadlines still update, without
renewing deadlines or resetting pages/cursors/status. Initial and changed
pressure telemetry remains available.

In serial profiled replay, SQLite execution, lifecycle publication/flush and
source commits dominate local work; frame decompression/JSON and joins follow.
The final profiled observer pair costs 2.602 vs 2.725 CPU seconds, including hashes,
protobuf decoding and level-six compression. The targeted observer projection
validates the whole WS JSON while extracting only routing metadata, avoiding
**40,775,483 additional Python log-string bytes**. Every raw delivery and WS
routing field remains exact; the three raw-delivery digests (capture, baseline
observer and repaired observer) match. The profiled CPU is slightly higher with
native projection/ambiguity checks; no observer CPU saving is claimed. Compression
and raw capture settings remain unchanged. This is substantial diagnostic overhead
on a two-vCPU host; original live observer cost remains unmeasured. Detailed receipts are in [PROCESSING.json](PROCESSING.json) and
[CONTENTION.json](CONTENTION.json).

## D. Timing attribution

Keep three clocks separate: chain block time (integer wall time), upstream
protobuf `created_at`, and local receipt/monotonic process clocks. The original
meter subtracted `created_at` from receipt and called it provider latency. That
timestamp is retained on replay and does not prove fresh provider dispatch.
The outbox's `available` clock is the maximum successful log/status receipt
establishing economic content, before independent finalized publication; it is
not a provider dispatch timestamp or the first chain-event observation.

| Path segment | Recoverable evidence / limitation |
|---|---|
| Chain event → finalized availability | **UNMEASURED**. Block time is known; metadata `created_at − block_time` median ≈1.02–1.05 s is not a certified finality duration |
| Finalized availability → provider dispatch → transport arrival | **UNMEASURED**. No dispatch clock or independent socket-arrival timestamp |
| Replay/startup contribution | Directly present: 256-slot shared overlap and additional delivered prefix; status median created age 17.976 s, scout age 91.066 s; shared metadata age 41.299 s and slot age 33.162 s |
| Live-like shared tail | Only 20 metadata/slot observations after release; mixed p50 age 0.100 s, p95 8.119 s; 10 metadata observations have median chain age 8.851 s. Bimodal packet types must remain separate |
| Candidate native tail | 114 status packets after release still have median created age 18.824 s; the short capture never proves native catch-up to live logs |
| Local receipt → decode → join | Original per-frame decode and buffering segments **UNMEASURED**. Same-tape decode/CPU profiles are component estimates, not original transport delay |
| Owner scheduling | Peak observed oldest wait **6.405 s**: a local owner queue observation, not network latency. Per-frame residence cannot be exactly paired from this capture |
| Decode/join → durable commit | Original precise boundaries **UNMEASURED**; repaired source adds join-ready, owner-claim and durable-end wall/monotonic boundaries |
| Content receipt → outbox staging | 8 canonical publication rows: p50 0.276 s, maximum **6.429 s**; combines unmeasured decode/join/scheduling/storage rather than isolating SQLite contention |
| Outbox staging → consumer durable acknowledgement | Same 8 rows: p50 0.137 s, maximum **0.558 s**; acknowledgement follows durable CandidateHistory ingestion |
| Content receipt → publication acknowledgement | p50 0.412 s, maximum **6.988 s**; this is a measured local end-to-end publication path, not provider dispatch delay |
| Publication → complete qualification | **UNMEASURED**: zero full Pump hydrations and incomplete original windows. A finished skip/error previously populated `qualification_ready`; that false measurement is repaired |

Identical native facts with identical upstream timestamps arrive on separate
streams 3.631 s apart at the median, up to 8.694 s apart. This proves the upstream
timestamp is not a per-delivery dispatch timestamp; it does not decide whether
the separation originates in provider replay, local transport buffering or
serial owner processing. There is no measured clock-skew bound.

The window is 19.840 s, nominal steady interval 7.794 s, but captured receipt
spans 13.764 s, ending **5.415 s before running close**. Only **2.379 s** of
post-release delivery exists. Active captured application throughput averages
**3.657 MB/s**; the largest one-second bucket is **5,247,721 B/s**. Dividing by
the full window understates acquisition demand by including shutdown drainage.

## E. Repairs and completeness parity

| Changed file | Behavioral change / justification |
|---|---|
| `meme_machine/solana_source_intake.py` | One bounded native WS JSON validation; successful notification exact, failed identity/error retained without Python log strings; malformed/ambiguous routing fails closed |
| `meme_machine/solana_selective_source.py` | Uses that intake instead of two Python decodes; adds receipt/decode/join/owner/durable/publication diagnostic clocks; subscriptions and economic deadlines unchanged |
| `meme_machine/solana_selective_history.py` | Same-or-weaker existing acquisition request returns without transaction or repeated pressure write; real urgency still follows original durable update |
| `meme_machine/lanes/pons/pons_survivor_runtime.py` | `len(log_batches) == log_call_count`, rather than count including independent header witnesses; full response count, boundary identity and cursor reorg checks retained |
| `engineering/solana_capacity/transport_meter.py`, `certify.py` | Reports upstream timestamp age separately from unmeasured provider delivery latency; records new local clocks and observer/decode aggregates; extracts WS routing metadata without materializing log strings, preserving complete raw frames |
| `engineering/solana_capacity/pump_pons_proof.py` | Captures a physically received ceiling-triggering frame before propagating stop |
| `engineering/solana_capacity/pump_candidates.py` | Distinguishes disposition finished from actual complete hydration/qualification time; skips/errors cannot count as ready |
| `engineering/solana_capacity/offline_*.py` | Bounded offline attribution, deterministic replay, isolated processing, contention and small publication receipts |
| `tests/test_provider_efficiency.py`, `operational/tests.py` | Regressions for these defects, included in FAST; no economic assertion weakened |

Exact identical-tape parity passes for all **287 canonical rows**, including
signature, true transaction index, original event/log index, hash, first-seen
clock and complete body. Baseline/repaired digest:
`ed2e970c41ee81c8955aa6a48eddfa63fd060cd0bb9700559c319118b6d3d037`.
All 169 discovery/lifecycle/consumer candidate identities, first observations,
bindings, origins, checkpoints, coverage and consumer references match exactly.
Only disposable canonical path names are normalized after verifying each
reference's original checksum. The captured DB matches all identity/order/hash/
first-seen columns; its 282 retained bodies match, and five bodies previously
retired by normal retention are reproduced identically in both raw-tape replays.
No missing captured body is treated as newly authenticated history.

The canonical subset contains 60 Pump trades, 2 creates and 225 PumpSwap trades
over slots 454380077–454380079. **10,210 early successful log facts remain
unwitnessed in both replays**. There is no canonical migration sample and no
complete native position sample. The capture therefore cannot prove full
graduation/Survivor qualification/position parity. Unchanged affected fixtures
cover graduation continuity, Current/Survivor independence, retained history,
reactivation, high-water marks, structural decisions, no lookahead, original
deadlines and native funding/replay. This limitation is explicitly retained in
[PARITY.json](PARITY.json); offline equality is not live completeness.

Pons's valid cold-slice regression fails on the baseline and passes after the
one-line repair. Missing response and identity/reorg contradictions still fail
closed without advancing a cursor. This is a specific discovery correctness
defect, not new Pons strategy engineering. Baseline defect failures and the
separate pre-existing FAST source-freeze failure are preserved in validation.

## F. Concurrent resource regression and frozen economics

The existing two-vCPU / 8,327,667,712-byte host ran isolated ingestion, allocator
and Pons-admission fixtures, then combined competing processes. The same frozen
tape repeats while the unchanged 64-request allocator fixture runs. Network
guards reject market I/O. All authority and evidence DBs are disposable.

| Measurement | Baseline alone / combined | Repaired alone / combined |
|---|---|---|
| Grant median | 193 / 297 ms | 181 / 261 ms |
| Grant p95 | 364 / 494 ms | 329 / 474 ms |
| Grant p99 | 365 / 521 ms | 329 / 562 ms |
| Native settlement/delivery median, 180 calls | 40.5 / 59.6 ms | 37.5 / 56.8 ms |
| Native delivery p99 | 82.2 / 143.1 ms | 84.8 / 109.1 ms |
| Allocator CPU | 8.285 / 12.476 s | 8.187 / 12.521 s |
| Allocator wall | 10.748 / 15.722 s | 10.609 / 15.270 s |
| Serial ingestion CPU / wall | 4.842 / 6.966 s | 4.769 / 6.589 s |
| First concurrent ingestion CPU / wall | 7.245 / 10.099 s | 7.285 / 9.912 s |
| Funding five-second fixture misses | 0 / 0 | 0 / 0 |
| Conservation / application retry | true / 0 | true / 0 |
| Sampled combined group peak RSS | 182,751,232 B | 188,530,688 B |

Both variants produce exactly the same canonical/consumer digests in both load
cycles. Main serial replay writes 87,232,512 process bytes and performs 8,440
SQLite mutations in both versions. That pass does not recreate the archive
worker polling reassertions; their savings are measured separately. Single
paired runs and profiler/host variability do not support claiming improved
allocator p99 or whole-ingestion CPU. Combined work demonstrably costs CPU and
latency, but reveals no new conservation/order/durability failure or five-second
fixture breach. Do not redesign the ledger based on these fixtures.

Pons executes 24 real governor-admission probes split between Current/selective
and Survivor/history in each phase, retaining physical admission interval 0.5 s
and fairness/priority. There are zero physical market requests, errors or fixture
deadline misses; repaired maximum admission waits are 3.504 s alone / 3.509 s
combined. This preserves fixture fairness, **not** concurrent market coverage or
actual position safety. Real original candidate deadlines, native quote/safety
deadlines, full Pons history progression and eight archive workers remain
unmeasured under live combined load.

[PRESERVATION.json](PRESERVATION.json) verifies frozen strategy files, all shared
capital implementation files, fixed policy and selected native scheduling/
continuity sources against the published integration. All nine approved changes,
four native strategy contracts, family-equivalence sizing and original 5%
realized-family rule remain byte-identical. The canonical approved policy hash is
`e87385900145e53956df18956ee2390f0d95787e6ffc44243251f9b147eb65f2`.
The original `$500` inception, four-family attribution and
`paper-1791089005190643467` authority remain untouched. Meteora/Ramses remain
paused. Model B and the production startup blocker are preserved. Model A and
Stage E certification were not reopened.

## G. Next proof and independent readiness

[NEXT_PROOF.md](NEXT_PROOF.md) and [NEXT_PROOF.json](NEXT_PROOF.json) specify finite
budgets, samples, clocks, stop rules and a separate authorization request. A cold
Pons seven-day start is **not compatible with a minutes-long combined proof**:
captured header pairs imply approximately 9.90 blocks/s, almost 6 million blocks,
and about 149,650 forty-block turns before ongoing chain growth or candidate
hydration. An absolute optimistic floor allowing one physical batch per turn
and free/cached headers is about **23.7 hours** with ongoing chain growth;
two fresh physical calls per turn project about **55.2 hours**, before Current
work and candidate hydration. The loop wait overlaps physical pacing and must
not be added twice. Neither estimate is compatible with three minutes.
Existing captures contain no complete authenticated seven-day Pons seed.

The proposed short combined proof is therefore **BLOCKED before spending** until
authentic full Pons history and a reviewed finite executor are available. The old
harness deliberately retains its 600-second/180-second bounds and cold bootstrap;
the new plan must not be passed to it or silently clamped. This handoff does not
grant a new run, retry, extension or historical-data acquisition.

| Readiness dimension | Classification |
|---|---|
| Pump/PumpSwap captured canonical parity | **PASS**, exact witnessed subset only |
| Pump/PumpSwap full evidence completeness | **NOT_PROVEN**; incomplete raw-log/native-witness tail and qualification history |
| Candidate original-deadline performance | **NOT_PROVEN** live; preservation fixtures pass, full Pump samples zero |
| Native position deadlines | **NOT_PROVEN**, no complete captured Pump positions; synthetic settlements pass |
| Pons concurrent coverage | **BLOCKED** for cold seven-day proof; slice correctness repaired, admission fixtures pass |
| Shared-capital contention | **PASS offline fixture limits**, material measurable contention; live safety still unproved |
| Sustained provider drainage | **NOT_PROVEN**; 2.379 s active post-release, queue zero at shutdown is insufficient |
| Provider resource cost | **MEASURED application payload / planning CU; billed CU UNMEASURED** |
| CAPACITY readiness | **BLOCKED**, `combined_position_and_candidate_provider_latency_not_certified` retained |

Zero RESOURCE_EXHAUSTED in this capture is encouraging. The old 665-error mixed
workload and shorter corrected run are not controlled duration/load comparisons.
No capacity certification or production acceptance follows from offline replay.
