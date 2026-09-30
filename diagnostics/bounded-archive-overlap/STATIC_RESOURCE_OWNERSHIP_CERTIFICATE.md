# Static resource and ownership certificate

**PAPER ONLY — 2026-09-30. Stage E RED; Stage F NOT STARTED.**

This certificate analyzes one design: **FULL-CAPACITY ACTIVE MATERIALIZATION + COMPACT LOOKAHEAD DESCRIPTOR**. It is a static review, not an implementation, allocation-gate pass, capacity result, or authorization to execute. The 12/4 MiB fixed allocation is retired. It is not revived by changing its current allowance to 16 MiB.

**Finding:** current admission can remain native, and successful worker return separates body construction from receipt authority. However, a bounded, pre-allocation descriptor-admission proof does not close from the inspected source. The exact outstanding obligation is **U-SELECT**, the peak resource charge of obtaining and freezing exact selection/provenance before the existing snapshot-size check. The timing opportunity is conditional on resolving that obligation. No architecture-feasibility or universal impossibility claim is made.

Material budget remains **4/6 consumed, 2/6 unused; this assignment adds zero**. No Python application, workload, test suite, pressure arm, experiment, workflow dispatch, production patch, freeze, canonical Stage E, or Stage F is part of this review. M1 and the preserved preflight **1 failure, 2 errors, 46 skips** remain separate blockers.

## A. Pinned identities

### Production and evidence

- Repository: `levonmendall/The-Meme-Machine`.
- Production commit: `dc08f9064cf5e37b63f383f52aa709d0afc1723f`.
- Production tree: `68736cf664169dee665762019800bf87ca0f1f67`.
- Durable design/evidence read at commit: `2d4fbe500be443a82408272688ee90e7ee6bc1f5`, branch `diagnostics/bounded-archive-overlap-20260930`.
- Fresh causal package: `2cc7a7c42e8f98acd57c2b606d132867d2393def`.
- Fixed-allocation gate execution source: `cba6d17c318f049cf602cfdf8329aef83b8f3163`; run **36782892873**, job **110117261872**, artifact **11128617306**. ZIP SHA-256 `26f68c9ce884534c0e6ff39e689628a4c6eb3e015bb1b8caaee5a37b8f9764d4`.
- Matched ablation run **36771603217**, artifact **11124508037**. ZIP SHA-256 `485a522b8e1ab820674528905fa87e953cb444eade31c77635f5ba8cce2cdec6`; original COMPARISON.json SHA-256 `f8601ccc5316bf0a3885a1d4979a28271f2f16a17b1b04f9c6d775e46b4b94d3`.

The read-only GitHub interface was used; no local execution interface is available in this session. Artifact facts below are taken from their durable review packages and committed log projections, not from a new download, rehash, or measurement. Previously reported independent artifact verification is attributed to its gate, not claimed as performed again here.

The relevant evidence is [the stopped overlap review](https://github.com/levonmendall/The-Meme-Machine/blob/2d4fbe500be443a82408272688ee90e7ee6bc1f5/diagnostics/bounded-archive-overlap/ASTRA_REVIEW_PACKAGE.md), [DESIGN.md](https://github.com/levonmendall/The-Meme-Machine/blob/2d4fbe500be443a82408272688ee90e7ee6bc1f5/diagnostics/bounded-archive-overlap/DESIGN.md), [FOLLOWUP_STOP.json](https://github.com/levonmendall/The-Meme-Machine/blob/2d4fbe500be443a82408272688ee90e7ee6bc1f5/diagnostics/bounded-archive-overlap/FOLLOWUP_STOP.json), [the native boundary projection](https://github.com/levonmendall/The-Meme-Machine/blob/2d4fbe500be443a82408272688ee90e7ee6bc1f5/diagnostics/bounded-archive-overlap/REFERENCE_BOUNDARY_LOG_PROJECTION.json), and [the owner-ablation review](https://github.com/levonmendall/The-Meme-Machine/blob/2d4fbe500be443a82408272688ee90e7ee6bc1f5/diagnostics/source-owner-ablation/ASTRA_REVIEW_PACKAGE.md). The user-supplied Astra decision is `ONE_ADDITIONAL_STATIC_PROOF_REQUIRED`; this document does not invent a new Astra verdict.

### Exact production files inspected

All source references in this document are to the production commit above, not to the retired experimental replacements. File names below are under `meme_machine/`; line numbers refer to those exact blobs.

| File | Git blob SHA | Relevant inspected symbols |
| --- | --- | --- |
| solana_maintenance_runtime.py | 73a2801136483d47e84e964435d11590f3ba0cdc | ArchiveFlight; attach; idle; MaintenanceRuntime.turn; execution_lease; demands; progress |
| solana_archive_snapshot.py | 2bb30f9eb3467d9e7914c2fe5266aa4ccf32330b | snapshot; _fetch; _slices; first-item checks; metadata and body reads |
| solana_evidence_plane.py | 34ef169e139baebfe12f9801b12f1774c94eaa05 | EvidenceWriter; ingest; archive_snapshot; _archive_rows; prepare_and_write_archive; _write_archive_raw; commit_archive; retain; transaction; close |
| solana_evidence_service.py | a54d3ed1876f138a6b2db37ef917f414173869db | ServiceState; archive_plan; archive_commit_slice; archive_commit_slice_and_plan; serve; source/decode/maintenance/checkpoint/shutdown |
| solana_evidence_storage.py | 991f2f03e8e1da766b0d605f870d14ceff5eeef1 | prepare; _inflate; decode; archive_body; raw_chunks; collect |
| solana_maintenance_arbiter.py | 337bb569ec5920497dd012c01a14c36fdea2518a | ServiceLeases; ClockModel; Need; choose; complete |
| solana_maintenance_state.py | 92e7d69d4e5af4f5946aaad19ce4062563670976 | native limits; DebtAgeAdapter; bounded observation; durable episodes/progress |
| solana_evidence_control.py | 90628ffdbe98e24a758c320e8965a99a75326272 | PriorityOwner.submit/_run/close; PendingCommands; command bounds |
| solana_evidence_transport.py | 8ad77d49e4155bf60ad2ae60ab92fb55875b7d02 | FinalizedNotificationDecoder; bounded repair inputs |
| solana_evidence_runtime.py | 4123a99f09da57cb0b3084aabd5517751b0b2281 | read snapshots; local interest/ack ownership |
| durable_publication.py | 4d1e04d488082ed342b5ae2d26787f6177e2674e | publish_bytes: temporary write, fsync, replace, directory fsync |
| solana_provider_config.py | fc6084825f23e9339309df6385346ba5991cd683 | public_value and its temporary lowercase copy |


Pinned source links: [ArchiveFlight / MaintenanceRuntime](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_runtime.py), [snapshot selection](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_archive_snapshot.py), [archive writer / commit](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_plane.py#L521), [service submission / lifecycle](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_service.py#L1330), [CPython process executor](https://github.com/python/cpython/blob/2abcf904b8dac8c999d2b3aac76681abb333798a/Lib/concurrent/futures/process.py), [multiprocessing queues](https://github.com/python/cpython/blob/2abcf904b8dac8c999d2b3aac76681abb333798a/Lib/multiprocessing/queues.py).

[AGENTS.md](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/AGENTS.md) and BUILD_STATUS.md were read. The user's explicit static-only instruction controls over their routine test/resource-check guidance. No merge or main mutation is authorized or performed.

### CPython

Inspected **CPython 3.12.14**, tag `v3.12.14`, annotated tag object `4b65faa0b452113bf130086fb1519be6d9cd9b06`, resolved commit `2abcf904b8dac8c999d2b3aac76681abb333798a`.

| CPython file | Git blob SHA |
| --- | --- |
| Lib/concurrent/futures/process.py | ff7c17efaab694c987fd524b60b6177c7770d55e |
| Lib/concurrent/futures/_base.py | 6742a07753c9217802f8a267f20e7fe6ffc28fb6 |
| Lib/multiprocessing/queues.py | 852ae87b27686122a096dfa691c5364d87ebe8aa |
| Lib/multiprocessing/connection.py | 81ed2ae51d182649d7c0d7acd6f1df75f0d95ef9 |
| Lib/multiprocessing/reduction.py | 5593f0682f7fce3dc90402187c1fd404aa2f8a42 |
| Lib/asyncio/futures.py | 0c530bbdbcf2d8e4d6836447c7c2553a900e8a21 |
| Lib/gzip.py | ecfe3a9cd7e6517d9408657f057c71bf165e3a77 |
| Lib/concurrent/futures/thread.py | 61dbff8a485bcdf38ad095d50ed0eeb705615a97 |
| Lib/asyncio/base_events.py | 813a85dbc39d572b52e550cb5c3fed83c61b38c4 |
| Modules/zlibmodule.c | 9759593b6acff4b423c61480e448daa6ad23150b |
| Include/internal/pycore_blocks_output_buffer.h | 28cf6fba4eeba2e68d7cde88b676589befae4c48 |

These are source facts for the requested interpreter. They do not establish a platform allocator/RSS ceiling, pipe byte quota, or immediate garbage collection.

## B. Existing native limits

One MiB is 1,048,576 bytes. A logical serialized-payload bound is not a bound on all Python objects, their copies, SQLite memory, or RSS.

Worker and transport limits below are source settings; websockets max_queue=32 is a protocol high-water setting, not a hard total process buffer quota.

| Source / symbol / lines | Value | Representation bounded | Kind and important qualification |
| --- | ---: | --- | --- |
| solana_archive_snapshot.py:24–50, snapshot(max_records), SQL LIMIT | 1–1,000 selected candidate records | One archive selection's identity rows | Logical per-selection count; not a pool-wide count of every retained plan/copy |
| same:24,48,81–85, max_bytes | 4,194,304 nominal | Stage-one encoded body lengths; stage-two encoded bodies + newly referenced compressed chunks + canonical lineage/coverage tuples | Logical prefix target. Both passes accept the first item beyond the nominal target |
| same:10,49,84, MAX_SINGLE_SNAPSHOT_BYTES | 20,971,520 | The respective accumulated selection costs | Logical hard check; a first item over 20 MiB raises. Does not cap metadata fetched before the check, identities omitted from the cost, object overhead, pickle bytes, or RSS |
| solana_evidence_plane.py:362–373, EvidenceWriter.ingest | 2,048 input records; 16,777,216 total canonical body bytes | One ingestion batch, using PreparedRecord.byte_count | Logical admission, checked after preparation; not a scratch-memory reservation |
| solana_evidence_service.py:1345, worker max_bytes | 16,777,216 | Sum of canonical bodies yielded for a service archive | Logical body target. _archive_rows:543–549 checks after decoding/hashing the next item and has a first-item exception. Native-valid ingestion bodies individually fit 16 MiB; no separate 16 MiB process-memory limit exists |
| solana_evidence_service.py:75,723–728, ARCHIVE_COMMIT_SLICE_RECORDS | 512 | Owner SQL commit plan prefix per archive turn | Logical mutation count. The arbiter separately refuses durable archive progress over 512 at solana_maintenance_arbiter.py:229–231 |
| solana_evidence_storage.py:101–104, _inflate | 16,777,216 accepted bytes; decompress requests +1 | Each inflated hot body base or log chunk | Logical decoded-byte check per inflation. The +1 probe, inputs, parsed data, replacement output, and other chunks coexist |
| same:125–128, decode(decoded_chunks) | 4,194,304 raw-byte cache accounting | Cached decoded log arrays, with raw lengths as costs | Logical accounting; parsed arrays can occupy more memory than their counted raw lengths |
| same:160–168, archive_body(raw_chunks) | 4,194,304 sum of cached raw lengths | Cached raw log bytes in one archive generator | Actual byte payload of cache entries, plus uncharged dictionaries/keys; uncached inflated chunks remain possible |
| solana_evidence_service.py:61–67 | raw message 16 MiB; prepared payload 16 MiB; protocol high-water 32 frames; dispatch 64 messages / 96 MiB original lengths; process threshold 1 MiB; 2 decode coroutines | Transport/dispatch/source decode | Per-message and admission counters. Raw str len is a character count. 96 MiB is not a bound on expanded/serialized prepared products |
| same:130–148,158–193 | prepared canonical body budget 16 MiB; 2,048 transactions per scoped block | Source preparation | On preparation-budget excess, retains the native serial fallback rather than dropping records. Preparation can allocate a next record before the budget check |
| same:70–71,605–609,1127–1159 | ≤8 source messages and ≤16 MiB original lengths per owner batch | Ordered source commit admission | Logical owner batch. Existing maintenance-pressure rule uses one message below 16 pending frames, otherwise preserves ≤8 batching |
| same:809,1244 | ProcessPoolExecutor(max_workers=2), spawn; 2 decode consumers | Concurrent pool workers | Worker count. Source decode and archive preparation share this pool. Small source frames use asyncio.to_thread; this is existing thread execution, not another archive pool |
| solana_evidence_plane.py:242–249,374–380; service.py:525 | writer default 256 MiB; service 2,147,483,648 | DB file + WAL measured before ingest | Disk admission threshold, not process memory or strict post-transaction disk cap. Other writes and transaction overshoot are not bounded by that comparison |
| solana_evidence_service.py:539–540 | PRAGMA cache_size=-16384; temp_store=MEMORY | SQLite page-cache target ≈16 MiB; temporary storage in memory | Configuration target, not total SQLite/RSS ceiling. No native total temp-memory quota is specified |
| solana_evidence_plane.py:25–43,361,582 | free-space warning 512 MiB; critical 128 MiB; ingest reserves 32 MiB; publication checks compressed length +32 MiB | Available filesystem bytes | Disk-space guard. Not an archive-file length or memory ceiling |
| same:552–585; durable_publication.py:8–19 | ≤1,000 body lines from a snapshot; gzip level 1; mtime=0; content-addressed .jsonl.gz | One constructed archive file | No native fixed FILE_CAP, provenance overhead per record, compressed-byte cap, total archive-directory cap, or total archive RAM cap. Length depends on full body AND provenance |
| solana_evidence_control.py:30,41–52 | owner queue 64; 8 entries reserved; nonurgent limit 56 | Queued owner operations | Count limit plus one executing owner operation. One existing SQLite owner; strict urgent priority and FIFO among source/background calls |
| same:16–17,219–238 | command bytes 32,768; durable receipt / PendingCommands default 8,192 | Consumer command and bounded pending-command registry | Distinct domains, not archive memory reservations |
| solana_maintenance_state.py:19–28 | 180 s preservation; 240 s residence; 120 source-seconds recovery; slack 1,000 records; scopes 260; buckets 4,096; pins 8,192; details 8,192; VM budget 250,000 at interval 1,000 | Debt observation and deadlines | Logical observation/clock limits. The observation LIMITs do not bound archive snapshot provenance queries |
| solana_maintenance_arbiter.py:33–50; control.py COMMAND_SECONDS | owner/execution/clock error 3/3/3 s; worker 15 s; pair 15 s; drought 45 s | Native service leases | Time contracts, not byte quotas. Waiting/preparation gives no durable-service credit |
| CPython process.py:118,746–756 | call queue 2+1=3 entries; 2 executing processes | Multiprocessing _CallItems | Count limit, not bytes; pending_work_items and work-id queue have no executor-level capacity |
| same:755; queues.py:359–399 | result SimpleQueue; no explicit item/byte maxsize | Serialized process results and pipe transport | No executor result-byte quota. Kernel pipe backpressure is not a source-defined capacity number |
| production archive carrier: maintenance_runtime.py:25–43 | one future OR one receipt; optional snapshot attachment | Native logical archive operation | Native serial state. The candidate explicitly introduces a second descriptor slot, as requested; it cannot cite the old carrier as an existing two-slot memory allocation |

For regular operation there are at most two awaited process-source submissions plus one archive preparation submission; that application structure is a useful count restraint. Startup submits two probes before the archive loop. Reconnection/cancellation can leave previously submitted source jobs running, so **three is not an unconditional executor-wide pending-job bound** across failures. The executor itself does not provide that bound.

### Exact 4 MiB behavior

Selection is ordered by COALESCE(market_time,first_seen), identity and excludes active lifecycle/address pins, account floors, and unresolved gaps. First the owner accumulates encoded body lengths. The first candidate can exceed 4 MiB but cannot exceed 20 MiB. The second pass charges each selected encoded body, each newly selected compressed chunk once, and the canonical serialization of that record's lineage and same-slot coverage; it independently has the same first-item exception and 20 MiB check.

If the first accepted item's cost exceeds 4 MiB, no second positive-cost item fits the nominal prefix. Otherwise the accepted prefix remains within 4 MiB. The 20 MiB guard applies to the computed cost **after** metadata has been fetched for candidates. SQL_SLICE=128 bounds parameter groups, not returned lineage/coverage rows.

### No total physical-memory ceiling

There is **no source-defined aggregate parent/children/executor/SQLite/source physical-memory ceiling** in these paths. In particular, 16 MiB canonical bodies, the SQLite cache target, and the 2 GiB hot disk threshold cannot be used as that ceiling. Reported RSS from previous runs is a measurement, not admission authority. This absence alone is not a proof that overlap is impossible; it prevents claiming a capacity number that source never defined.

## C. One candidate state machine

This is one proposed architecture with a conservative admission gate, not executable code.

- **C (current)** owns the entire native selection identity membership, full original compact worker plan, pending tail, generation, original submission time, and receipt. None of these authority objects shrinks merely to fund lookahead.
- **L (lookahead)** has exactly one slot. Initially it owns an owner-frozen descriptor containing generation; ordered identity/hash/scope/slot membership; original selection/cutoff provenance; every selected encoded body; every required content-addressed compressed chunk; and the exact lineage/coverage needed to reproduce the selected snapshot. These are immutable payloads. Identity/hash-only pointers to mutable hot rows are insufficient.
- **W (materializer)** is one logical full-capacity archive construction workspace, including all native decode, body-line, join, compression, and publication scratch. It serves C first, then can serve L only after successful C preparation has returned and its old non-workspace executor residuals are charged. W is not a new 16 MiB RAM arena.
- L may be prepared while C retains receipt mutation authority **only if** the admission calculation below succeeds before allocation and W is available. The generated L file/result still has no SQL commit authority.
- C uses unchanged native current admission: 1,000-record selection maximum, 4 MiB nominal /20 MiB exception, full 16 MiB body target, identical order/hash/provenance/publication behavior. No fixed quota is carved out for L.
- L is optional. Any failed, unavailable, unknown, or stale resource/authority admission yields **DEFER LOOKAHEAD**. C proceeds serially unchanged.
- There is no third membership/descriptor, second SQLite writer, new executor, larger worker pool, extra progress credit, or source-load change.
- Preparation never changes native recovery/service/demand origins or source clocks. L's selection and submission times are retained; promotion does not restart its worker lease.
- Logical membership and input bounds apply to individual selections as in production. They do not automatically grant two physical copies' worth of RAM. Supplementary joint guards, if proposed later, must limit L only and must not be misreported as preexisting source limits.

State order:

`IDLE → C_SELECTED → C_SUBMITTED → C_PREPARING → C_RECEIPT → C_DRAINING → C_FINAL_DURABLE → C_ACKNOWLEDGED → C_RELEASED → L_PROMOTED (if admitted) → next C`.

During C_DRAINING, an optional branch is:

`L_ADMISSION → L_DESCRIPTOR → [W available and resources admitted: L_SUBMITTED → L_PREPARING → L_PREPARED]`.

If C acknowledges before L has started, L can be promoted as a descriptor and prepared afterward. That branch is early selection only and **does not satisfy** a preparation-overlap claim. If L preparation finishes early, retain only L's original membership, original compact plan, receipt, clocks, and charged executor residuals until promotion. No other lookahead may replace it while retained.

The candidate requires a bounded owner sizing/admission procedure for L. Calling native snapshot(), then measuring its Python graph/pickle and rejecting it, is not that procedure: the allocation has already happened. U-SELECT below is the missing static certificate for that procedure and the native selection scratch it must account for.

## D. Phase-by-phase lifetime table

### Representation key

These names enumerate physical graphs/buffers separately from their authority. Shared references within one graph count once for payload and separately for their containers; an independently pickled/unpickled copy counts again.

| Name | Exact representation |
| --- | --- |
| M_C / M_L | Full ordered selected identity/hash membership, generation, scope/slot membership and selection metadata. Current selection membership can be larger than the worker's emitted prefix |
| P_C / P_L | Full original compact returned commit plan: identity, hash, body={scope,slot}. No full economic bodies |
| T_C | Pending-tail list and current batch list (≤512), sharing row dictionaries with P_C when deliberately retained by the candidate. Slicing allocates new reference containers |
| S_C / S_L | Parent immutable snapshot/descriptor: rows, encoded str/bytes bodies, lineage tuples, shared same-slot coverage tuples, compressed chunk map, encoded_bytes; plus owner metadata |
| A_x | Parent _WorkItem.args/kwargs, _CallItem and queue/deque reference containers pointing to S_x; normally aliases, not a second parent payload graph |
| Q_x | Pickler/BytesIO call buffer, feeder memoryview, transport/header/send/receive buffers. Distinct from S_x |
| H_x | Child unpickled argument/snapshot graph, independent of the parent graph |
| D_x | Child expanded/parsed structures: base JSON tree, fallback full record tree, parsed log arrays, parsed coverage-proof structures, metadata dictionaries, replacement map |
| K_x / I_x | Raw log cache; inflated base/chunk scratch; decode/replace temporary bytes and str, including an item expanded before the body-prefix check |
| B_x | Current canonical body bytes/str, hash/cost encode temporaries. Only one row is being processed, but its output can coexist with prior lines |
| V_x | Accumulated archive-line strings and list, plus last row/body/metadata locals and temporary concatenations |
| J_x | Joined output and appended-newline string; compression input raw.encode() is another bytes allocation |
| Z_x | zlib state and allocated output blocks, final compressed bytes, checksum/publication temporaries |
| R_x | (compact plan, receipt) result object; receipt name/hash/compressed length/worker_metrics; child and parent copies are distinct |
| F_x / X_x | concurrent Future, asyncio wrapper/waiter/callback references and result storage; or exception, cause/context chain, remote traceback strings and local traceback frames |
| U_x | Owner selection scratch: candidates, ids, refs, lineage, coverage, pairs, selected, selected_chunks, bodies/chunks dictionaries, _fetch.fetchall return list, canonical-cost temporaries and cursors |
| G | Shared source/decode jobs and products, queues, transport, raw messages, SQLite/cache/temp/WAL state, owner/checkpoint work, process-pool pending work and prior residuals |

**G is live in every phase**. It includes up to two source decode consumers, their original raw inputs and source products, existing small-frame thread work, any process-source serialization/deserialization/result storage, protocol frames, up to 64 admitted original source frames with 96 MiB counted lengths, ordered-ready/completed/batch containers, and the single owner. These source representations do not vanish because archive readiness changes. An ordered-ready item may also be referenced by a source batch/completion list. Count alias containers without treating them as independent payload copies.

For source prepared canonical bodies, a simple logical upper sum is 64 ×16 MiB = **1,024 MiB**, before object overhead and copies, despite the 96 MiB raw dispatch admission counter. This is deliberately conservative, not a new pool/RAM entitlement. Serial preparation fallback, base parsed source JSON, source worker inputs/results and exception residuals must also be charged. The default thread executor is existing asyncio behavior: CPython thread.py:138–146 chooses min(32,(os.cpu_count() or 1)+4); serve does not set a replacement. Two decode coroutines bound ordinary simultaneous source consumers, not all default-executor threads or all executor residuals.

### Complete phase inventory

The rows are logical phases, not a claim that every run reaches every row. P7/P8 and the L submission/materialization subphases can occur before P9 only if admitted; the requested promotion/submission phases also describe the serial fallback order.

| Phase | Simultaneously live current representations | Simultaneously live lookahead representations | Workspace / residual / release condition |
| --- | --- | --- | --- |
| P0 — idle | No active membership/plan/receipt. Native last_measured_archive_receipt may retain one prior receipt; coroutine/owner locals may retain the last result until overwritten | None | No active archive W. G and pool feeder's last serialized call may remain. Idle is not proof of zero retained memory |
| P1 — current selection | U_C, growing M_C and S_C; candidates and metadata fetched for records ultimately not selected; SQL cursor/fetchall and canonical-cost scratch | None | No full body materialization. U-SELECT applies here. Native full selection is preserved |
| P2 — current submission | M_C, S_C, A_C, Q_C, F_C; maintenance result/flight.prepared/snapshot locals alias S_C | None | Pending dictionary and feeder can retain parent arguments. Child receive buffer/H_C can begin while parent Q_C remains |
| P3 — current child materialization | M_C + S_C + A_C + Q_C + F_C in parent; H_C + D_C + K_C + I_C + B_C + V_C + growing P_C in child; J_C/Z_C during write subphase | None | W=C. SUM these distinct graphs. Joined text/input bytes/compression blocks/output are not covered by max(B_C,Z_C). Source decode may occupy the other process or queue both source calls |
| P4 — current archive/result delivery | Prior input representations/residuals; durable file; child R_C and result serialization/send buffer; parent receive/unpickle buffer and R_C/F_C; manager _WorkItem/_ResultItem locals | None | Successful preparation function has returned before _process_worker sends its result. No full bodies in R_C. Arguments and serialization residuals are still charged |
| P5 — receipt ready / SQL drain begins | M_C, original P_C, receipt R_C, T_C when a batch is formed; Future/wrapper/callback result copies and current input residuals; native snapshot/future/waiter locals can persist | None | C retains commit authority. W is logically free on successful return, but this is not a zero-residual or RSS-release event |
| P6 — partial slices | Full M_C and P_C, receipt, pending T_C, ≤512 batch container, owner plan/receipt locals, transaction state, F_C/residuals | None until P7 admission | Positive SQL progress does not reduce original membership/authority resource charge. Retry can retain an earlier pending tail |
| P7 — possible L selection | All P6 current obligations, including complete original membership and plan; no release based on tail length | Sizing metadata first; then, only after reservation, U_L, M_L, hashes/generation/scope/slot, growing S_L | No L full body yet. Native snapshot() allocates U_L before its final byte check; that route fails pre-allocation proof. Earliest attempted point is within an admitted archive turn after a successful nonfinal C slice, with C work remaining |
| P8 — L descriptor retained | All P6 current authority and residuals | Full M_L + immutable S_L + descriptor metadata, no mutable-row authority, no third slot | W remains free until L submission. If resources permit, L's A_L/Q_L/H_L/D_L/K_L/I_L/B_L/V_L/J_L/Z_L/R_L/F_L appear as described by P13/P14 while C still drains. They SUM with C, not replace it |
| P9 — current final commit | Full M_C/P_C/receipt; final batch/tail and owner transaction, prior executor residuals | Admitted L descriptor or its preparation/result/receipt and residuals | Publication cannot commit hot removal. SQL final durability alone does not acknowledge C; interruption during dependent planning leaves original receipt held |
| P10 — receipt acknowledgement | M_C/P_C/receipt still owned until the successful owner transition confirms no remaining slice and acknowledges this receipt; owner result/locals/Futures can alias them | L's full membership, immutable input or compact prepared plan/receipt, generation and original clocks | Native acknowledgement is the in-memory carrier transition after archive_commit_slice_and_plan returns, not a new durable acknowledgement row. No resources are assumed gone during the transition itself |
| P11 — authority/resource release | Explicit C owner roots can be dropped only after P10; native last_measured_archive_receipt still holds receipt; old Future, callback, manager, feeder, child and exception roots remain separately charged | L remains the sole successor descriptor/carrier | Logical C authority release does not guarantee physical copy release. Pool join/feeder termination supplies the conservative residual release boundary; no hot-tail shrinking argument substitutes |
| P12 — L promotion | No active C authority after P10/P11; old residuals and telemetry receipt may persist | L membership becomes current; its descriptor/prepared plan/receipt and original clocks are transferred, not copied into a third slot | Owner-only promotion after C ack; validate generation and immutable provenance. Promotion grants eligibility for native mutation checks, never bypasses them |
| P13 — promoted preparation submission | Promoted current M/S/A/Q/F; old C residuals still charged | No separate next L yet; formerly L input is the active descriptor | W available; identical two-process pool. If submission occurred before P9, it had only preparation authority and is not resubmitted |
| P14 — L full materialization | Same graphs as P3 for promoted or preparation-only L; old C full authority still present if before P9, otherwise only old residuals | No third descriptor; this one slot's H/D/K/I/B/V/J/Z/R/F are all charged | Exactly one archive construction executes. Prepared L result remains compact. More preparation waits if W or source/pool/resource admission is unavailable |
| P15 — failure/cancellation | Preserve C original membership/plan/receipt; possibly S/A/Q/H and partially accumulated D/K/I/B/V/J/Z; F/X and cause/context/traceback frames; published file or temporary | Preserve or explicitly discard L authority roots only when safe; still charge its submitted work, result, exceptions and immutable payload | Cancelled waiter is not cancelled worker. A failed full workspace cannot be declared released from Future.done(). No further speculative preparation after unknown/failure residuals; fall back or fail closed according to native state |
| P16 — shutdown/restart | Accepted owner call and all authority roots until its outcome is accounted; producer tasks/results/exceptions, queued or running process calls, receipt/file/SQL state, telemetry reference | No promotion during shutdown; no replayed old-generation L authority on restart | Native task drain/cancellation, owner.close/join and decoder_pool.shutdown(wait=True,cancel_futures=True). A completed pool join releases worker address spaces and feeder frame; parent Future/traceback objects require their own release. Restart reselects native hot work under a new generation and restores durable clocks |

No archive economic body is returned in the native process result. The current snapshot is **not** its commit receipt. It is therefore legitimate to distinguish successful body-construction completion from the later release of exact membership/receipt authority. Nevertheless, the unchanged maintenance coroutine retains `snapshot`, `future`, and potentially `waiter` locals through drain until later overwrite/exit (service.py:1344–1363); these references are part of the native accounting, not automatically cleared by flight.future=None.

## E. Physical and logical resource accounting

### A simultaneous-live sum, not a 16 MiB envelope

Let heap(X) include a graph's actual payload and container allocations, deduplicating aliases **within that graph**. Let Qcall/Qresult include independently serialized buffers, pickle temporary state and transport receive buffers. Shared source/SQLite resources are G_heap. During an admitted preparation overlap, a conservative ledger is:

```text
Live_overlap =
    heap(M_C) + heap(P_C) + heap(T_C containers) + heap(receipt_C)
  + heap(parent-current input graph still referenced)
  + heap(current Future/wrapper/callback/owner result containers)
  + current call/result/child/exception residuals
  + heap(M_L) + heap(S_L) + heap(L descriptor/argument containers)
  + Qcall_L + heap(child H_L)
  + heap(D_L) + bytes(K_L) + heap(I_L) + heap(B_L)
  + heap(V_L) + heap(J_L)
  + bytes(compression input_L)
  + bytes(compression blocks_L) + bytes(compression output_L) + zlib state_L
  + Qresult_L + heap(parent result_L) + heap(F_L)
  + G_heap + shared transport/allocator residuals
```

Terms whose payloads alias are deduplicated with their reference containers retained. Independently live parent/child graphs and serialized copies are SUMMED. A raw body can appear in a canonical str, accumulated line, joined str and compression-input bytes at the same time. A full original plan and pending-tail list can coexist even when the tail has only one record.

A physical budget would require a defined resource domain, a capacity, and upper remaining-obligation charges for each term. **None of the named logical limits defines that aggregate physical domain/capacity.** This certificate does not assign 16/20/96 MiB as its value.

### Source-backed bounds and explicit unresolved terms

| Representation | Source-backed conservative accounting | What remains outside that bound |
| --- | --- | --- |
| Selected count N | N≤1,000; emitted commit plan is an ordered prefix, count≤N | Original selected membership must not be silently equated to emitted membership |
| Selected encoded cost E | E≤20 MiB; normally ≤4 MiB, with one-item exception | IDs/hash strings, dictionary/reference overhead, serialization framing, physical copies, and prefetched metadata are not all included |
| Emitted canonical body bytes B | For native-valid ingested bodies on service path, B≤16 MiB, including an individually large first body | Next row is decoded and hashed before prefix rejection; its body/scratch can coexist with B already in archive lines |
| Next-item scratch | One next native-valid body may be up to another 16 MiB; base/chunk inflation accepts 16 MiB and requests +1 | Parsed trees, intermediate replacements and encoding/hash temporaries must be added. Two log-reference paths can refer to different chunks |
| Raw chunk cache K | Sum cached raw bytes≤4 MiB in an active _archive_rows generator | Current uncached inflation, replacement values, dictionaries, and full output; raw cache is not a total worker cap |
| Expanded JSON/proof objects D | Input byte checks constrain some serialized data; object nodes/strings require an interpreter representation bound | No native object-heap quota; a 4 MiB counted decoded cache need not be a 4 MiB graph. Malformed/exception paths can retain frames |
| Compact plan P | ≤1,000 row dictionaries, each identity/hash/scope/slot only | “Compact” describes omitted bodies; it is not a source-defined compact-plan byte ceiling. Native identity/scope lengths are not fixed by the archive code. Canonical ingestion size constrains individual native records, not a small fixed identity width |
| Tail/batch containers T | At most N tail references plus 512 batch references at a slice boundary, plus any retained earlier result list | Do not release P_C or M_C as these containers shrink. Original worker plan may also remain in Future/result storage |
| Selected provenance | Included in E using canonical tuples at selection; same-slot coverage objects may share references | Output named dictionaries have different overhead. Coverage proofs are parsed for output. No justified native “512 bytes per record” overhead constant exists |
| Selection scratch U | SQL candidate LIMIT≤1,000 and parameter batches≤128 | _fetch().fetchall() for hot refs, lineage and coverage has no returned-row/byte LIMIT; all candidate metadata is collected before final selection. This is U-SELECT |
| Archive-line / joined output J | Exact J is sum of complete body-and-metadata line lengths plus newlines | No fixed native J/FILE_CAP; B alone excludes provenance and identity duplication. Temporary concatenations and `'\n'.join(lines)+'\n'` may coexist with lines and joined storage |
| Credential/public-value scan | For ASCII output, public_value makes a lowercase copy, as large as its input | This is another live allocation during scan. It is separate from compression scratch, not always simultaneous with it |
| gzip output Z | gzip.py:626–629 routes mtime=0 to zlib.compress(...,wbits=31). zlibmodule.c uses output blocks, then a final bytes result | No native compressed-byte quota. Bound must use actual J and linked zlib behavior; cannot substitute 16 MiB or assume output≤input |
| zlib output-block capacity | pycore_blocks_output_buffer.h starts 32 KiB, then 64/256 KiB, 1/4/8/16/16/32/... MiB blocks, max individual block 256 MiB | **256 MiB is a block-size maximum, not total output cap.** For actual output g, allocated blocks can be conservatively charged as ≤g+256 MiB, plus final g bytes and object overhead; no allocation-size guard is added |
| Pickle/queue buffers Q | _ForkingPickler.dumps creates BytesIO and returns a memoryview; full serialized call/result buffers are distinct allocations | E is not pickle length. Unpickle input and new object graph coexist. Serialized-call bytes may outlive completion in the feeder |
| Parent/child memory | Every distinct representation above plus G and allocator retention | Native source supplies no RSS/allocator-release guarantee or aggregate process-memory ceiling |
| Published file | Exact compressed length reported in receipt; content-addressed immutable name; disk-space guard | Temp file and existing same-name file can coexist before replacement. Directory/manifest retention is not a fixed byte cap; publication alone supplies no SQL progress |
| Source shared resources | Raw 64/96 MiB admission; per-prepared-frame 16 MiB body accounting; two consumers/process workers; owner queue 64/56 | Source products, pickle/result copies, thread scratch and failed/cancelled residuals require distinct charges. No executor pending-byte cap exists |

For compressor output `g`, the source-backed block bound above is intentionally very conservative. The final bytes allocation and blocks coexist during _BlocksOutputBuffer_Finish before Py_CLEAR(list); SUM their capacity. Likewise, inflation uses the same block helper and can allocate more capacity than the returned length. Returning a Python object or decrementing its last reference does not promise pages are returned to the OS.

### U-SELECT: the concrete missing static bound

The unproved quantity is:

```text
U_SELECT =
peak bytes of candidate/identity containers
+ returned hot-ref/lineage/coverage rows and strings
+ growing provenance maps/lists
+ canonical-cost serialization temporaries
+ exception-retained selection frames
before exact immutable descriptor selection is admitted/frozen.
```

Relevant source: solana_archive_snapshot.py:44–51,54–76,78–98; _fetch:18–21. The reads for refs/lineage and coverage occur for the candidate set before the per-selected-record cost check at 81–85. Shared coverage reduces duplication in the **finished** graph; a join can still return many overlapping coverage rows and the temporary fetchall list coexists with the map. SQL_SLICE=128 limits query arguments, not the number or size of result rows.

Neither the schema at evidence_plane.py:186–193 nor these snapshot queries gives an operational provenance fan-out/byte cap. DebtAgeAdapter's 4,096-row observation limit applies to different queries. The hot-store disk comparison is a pre-ingest guard, not a certified maximum on all metadata/temporary memory; it cannot be silently converted into U_SELECT≤2 GiB. A finite database on one observed runner is not a source-derived admission bound for every native-valid state.

The candidate could only close this by specifying and statically proving a bounded owner pre-sizing/copy procedure and its complete retained-resource charge, while preserving exact provenance/current behavior and the same owner execution/priority contracts. This certificate does not count “construct the snapshot and then reject it” as such a proof, and does not propose a second design.

## F. CPython process-pool residual accounting

References below use the exact CPython commit in A.

| Path / symbol / source lines | Guaranteed behavior | Conservative charge and release point |
| --- | --- | --- |
| process.py:802–824, submit | Creates _WorkItem(future,fn,args,kwargs), stores it in _pending_work_items, puts work id | Parent S/args remain referenced independently of the caller. submit has no bounded pending dictionary |
| process.py:391–411, add_call_item_to_queue | Sets Future RUNNING before placing _CallItem in three-entry _SafeQueue; does not delete the _WorkItem | Charge parent arguments + queue containers + any active serialization. RUNNING prevents successful cancellation after queue admission |
| queues.py:86–96,232–292, Queue.put/_feed | Queue has deque of call objects. Feeder pickles before taking send lock; local obj becomes serialized memoryview | Charge call graph during pickling, BytesIO/pickle buffer, transport bytes. After send, **obj is not deleted**; on empty deque the feeder can retain the last serialized call indefinitely until next successful pop/overwrite or feeder termination |
| reduction.py:49–52, ForkingPickler.dumps | BytesIO then getbuffer() memoryview | The memoryview retains its backing bytes buffer. Queue serialization is not a zero-copy ownership transfer |
| queues.py:98–122, Queue.get | Receives bytes; releases semaphore before unpickling; creates child graph | Three queue slots do not include executing H graphs. Charge receive buffer + child graph while loads runs; parent copies can coexist |
| process.py:252–276, _process_worker | call_item holds child args through fn invocation and result send; deletes r on success, then deletes call_item | Parent Future may finish before these deletions occur. Charge old H and compact R/serialized output until guaranteed release; normal next task in the **same worker** follows del call_item. Public Future completion does not identify a same-worker barrier |
| process.py:216–225 and queues.py:391–399 | _sendback_result uses SimpleQueue.put, which synchronously pickles and sends | Charge child R + serialized result + send/transport buffers. Parent can receive/finish while child is still returning from this path |
| connection.py:182–219,246–251,381–437 | Sending uses buffers/views; receiving uses BytesIO; pickle loads operates with incoming storage live | Charge serialized result and unpickled parent result simultaneously. Header+payload concatenation for small messages is another copy; large POSIX payload uses separate header send |
| process.py:458–465, process_result_item | Pops _WorkItem then calls Future.set_result/set_exception | WorkItem local still holds args during Future completion/callback invocation. done() can be observed before this function returns and releases the local |
| process.py:357–375, manager run | Deletes result_item only after result processing; releases idle semaphore afterward | Callback/Future observation is earlier than manager's explicit deletion. Keep a manager-result/WorkItem residual charge rather than calling observation a global release barrier |
| _base.py:537–565, set_result/set_exception | Stores _result or _exception; sets FINISHED; then invokes callbacks | Future retains compact result or exception. result() returns it; does not clear it. _invoke_callbacks iterates _done_callbacks without clearing the list |
| asyncio/futures.py:348–420, wrap_future/_chain_future | Copies result/exception into wrapper; schedules cross-thread state delivery/cancel callback | Add wrapper/Handle/callback reference containers. Underlying Python result may alias within parent; both Futures can keep it reachable. Callback observation does not clear caller snapshot/future/waiter or other executor roots |
| process.py:135–148, _ExceptionWithTraceback | Formats remote traceback; clears top exception.__traceback__; preserves exception object and remote string | Do not infer cause/context chains and arbitrary exception attributes are cleared. The worker's exc local is not explicitly deleted on the exception branch; retain failure graph conservatively until known replacement/worker exit |
| process.py:179–189, feeder error | Pops pending work, attaches remote cause, sets Future exception | Parent error/traceback can retain call/serialization/args and local frames. failed/done is not proof of resource release |
| _base.py:364–381; process.py:404,528–552 | cancel succeeds only while PENDING; shutdown cancels pending work, not RUNNING work | An asyncio waiter cancellation/timeout/shield completion releases no worker authority. Charge accepted call until outcome/cleanup |
| process.py:477–527, broken pool | Marks pending Futures failed, clears dictionary, terminates workers, joins internals | Future exception objects can remain in parent. Do not start more archive construction on a broken pool |
| process.py:568–587,856–874, shutdown(wait=True) | Joins manager, closes/joins feeder, joins processes | After successful join, worker address spaces and live feeder locals are gone. Parent retained Futures/tracebacks remain until their roots are separately released |

On the healthy success path, the archive function has already returned before _sendback_result begins, and its compact returned objects do not contain full bodies/lines/cache/compression storage. Thus it is reasonable to treat **logical materialization** as complete at that return, without waiting for SQL acknowledgement. It is unreasonable to treat Future.done(), a callback, some SQL slices, or a file publication as proof that **every** input/result copy or allocator reservation has gone.

For admission, retain the old parent input, one old serialized-call feeder residual, possible child arguments, possible compact result serialization/manager locals, and all still-referenced Future/owner objects until their actual source-backed release or the conservative successful pool-join boundary. No new barrier task, worker affinity mechanism, executor setting, or pool replacement is introduced to force release.

Normal source receivers drain decoders on receive termination (service.py:1264–1277). Other cancellation/error paths use shielded calls and cancel tasks (1297–1300); this does not prove that process calls vanished. The executor pending dictionaries have no byte/count maximum. Speculative L admission therefore requires known source/pool state and must defer across unknown cancellation/failure residuals. This review does not recast the ordinary “two source calls plus one archive” structure as a failure-path global bound.

## G. Current native admission proof

### Without lookahead

The candidate's current path is exactly the production path: select through writer.archive_snapshot with max_records=1,000 and nominal max_bytes=4 MiB; submit EvidenceWriter.prepare_and_write_archive with max_bytes=16 MiB to the same two-process pool; retain the native ordered prefix, complete provenance, content-addressed gzip publication and compact result; drain slices of 512 on the sole owner. No L budget is subtracted, no current count/bytes/body target changes, and no L guard can reject C.

The demonstrated native-valid record is **13,631,744 canonical bytes**, below **16,777,216**. Its durable native boundary projection reports **59,842 selected encoded bytes**, one archived record, zero hot records, one archive file, integrity ok, zero provider calls. It passes this candidate's unchanged current body and selection path. The retired allocation's **12,582,912-byte** current limit does not exist in this candidate.

This proof extends to all native-valid inputs, not just that example:

1. Identical snapshot eligibility/order and native record/encoded first-item behavior preserve every native selection.
2. Identical worker body target and first-item behavior preserve every native emitted prefix, including small compressed representations that restore large legitimate bodies.
3. Identical file/provenance construction preserves the full native output behavior; no fixed extra FILE_CAP is imposed on C.
4. Identical generation/pin/floor/gap/identity/hash and mutation/durability checks preserve native commit behavior.
5. If no safe L admission is available, the same existing serial successor path executes.

This is a **design equivalence proof of admission**, not an executed acceptance test and not a proof of native physical-memory boundedness. Unresolved native scratch cannot be “fixed” here by imposing a tighter current admission limit.

### With lookahead

C retains those same entitlements, full original membership and plan. L may be declined, stopped before submission, or discarded as non-authoritative if it would interfere with them. It cannot reduce C's accepted prefix, original membership charge, working body target, receipt-drain readiness or pending mutation authority. After owner promotion, the next current receives full native capacity; earlier descriptor admission must not force it into a permanently reduced allocation.

Native worker output may be a strict prefix of selected snapshot rows because body expansion reaches its target before encoded selection does. The design must preserve both sets explicitly. It must not add the retired prototype's requirement that emitted identities equal **all** selected identities if production would emit a strict prefix. Unemitted selected rows stay hot and acquire no durable-progress credit.

## H. Lookahead admission rule

Admission is owner-affine, immutable-payload based, optional, and **before allocation**. It is not a memory measurement performed after creating S_L.

For each applicable bounded resource domain d, require:

```text
established current worst-case remaining obligations[d]
+ still-retained original C membership/plan/receipt and input copies[d]
+ executor/process/Future/exception residuals[d]
+ concurrent source/decode/owner/transport requirements[d]
+ descriptor sizing/copy scratch[d]
+ proposed immutable L descriptor and metadata[d]
+ eventual L worker serialization/materialization/result obligations[d]
<= an existing, actually applicable capacity[d]
```

Additionally require:

- W is not executing C or another archive preparation.
- One L slot is empty; the descriptor excludes **every identity in M_C**, not merely the current SQL tail or records already nulled. Selection exclusion is exact owner-side SQL membership.
- Current native entitlements remain reserved until their actual release phases.
- Native per-selection record/encoded rules and file/body behavior remain valid; optional L restriction can only cause DEFER, never a current failure.
- Full immutable body/chunk/provenance authority exists. Hashes alone do not authorize reconstructing future payloads from mutable hot state.
- The same native owner admission, fresh observation, choose/complete, urgency, leases, peer reservations and fairness permit the work. Preparation uses the existing process FIFO; it does not evict or reserve a source worker.
- Generation, current submitted times, descriptor creation/submission times and all service/recovery/source clocks are valid.
- Failure/cancellation residuals are known and conservatively charged; an unknown resource term does not count as zero.
- Planning gives zero durable progress; L is not SQL-ready merely because its preparation completed.

Selection count/body/input limits are different resource domains from process RAM. One cannot compare a SUM of Python/child/pickle/compression bytes against 16 MiB canonical bodies, or debit dispatch's raw-byte counter to create archive RAM. If there is no existing physical capacity for a proposed physical inequality, report it as undefined; do not invent one.

**Current certificate evaluation:** U-SELECT has no proved pre-allocation upper charge, and no native aggregate physical capacity closes the corresponding inequality. Therefore the admitted branch cannot currently be certified. Its operational result at that gate is **DEFER LOOKAHEAD**. Do not reject C, shrink its batch, borrow its entitlement, increase a ceiling, or run an experiment to estimate the missing static bound.

A sizing query that returns only bounded scalars could potentially help, but it must account for the query/identity scratch, exact native ordering, shared chunks and complete provenance, owner interruption, physical copies and the subsequent immutable freeze. Describing such a query is not proof that the native fetchall/canonical-cost allocations are already bounded. That precise static obligation returns to Astra.

## I. Authority and release transitions

The sole SQLite owner retains mutation authority. The coroutine coordinates submission/attachment only at a quiescent owner return. Child processes receive frozen preparation inputs and never SQLite mutation authority.

| Transition | Owner of membership / archive authority / receipt / W | Transfer and release rule |
| --- | --- | --- |
| P0→P1 selection | SQLite owner owns selected membership and mutable-source read authority; no receipt; W free | Freeze exact identities, hashes, source bodies/chunks/provenance and generation. Close cursors on every path. No economic progress |
| P1→P2 submit/attach | Owner-controlled C membership; coroutine attaches a future at quiescent boundary; executor owns additional argument references | Transfer preparation use of the immutable snapshot, not commit authority. Preserve generation and actual original submission time |
| P2→P3 preparation | Child owns W and independent input copy; owner retains C membership | Child restores complete bodies, verifies canonical hashes, builds complete provenance and publishes under native protocol. No SQL, leases or clocks are renewed |
| P3→P4 file/result | File publication protocol owns durable bytes; child/executor own result/input residuals | Published file is preparation output. It cannot drop hot rows or give progress. A successful compact result permits later owner receipt handling |
| P4→P5 owner receipt observation | C membership/original P_C/receipt become owner-held pending work; W logically no longer executing C | Check native generation/clock/worker outcomes. Keep exact original selected membership and emitted plan. Parent, child, queue and Future residuals remain separate charges |
| P5→P6 slices | C retains all mutation authority; single owner handles ≤512-row batch | Native transaction and commit-time checks apply on each row. Tail changes only after a successful returned slice; full M_C/P_C stay retained through ack |
| P6→P7/P8 L admission | Owner owns disjoint L membership/immutable descriptor; C retains receipt authority; W may be free | Reserve first. L gets preparation authority only. No authority can derive from future mutable hot rereads |
| P8→pre-ack L preparation | Child owns W for L, C owner retains M_C/P_C/receipt | A single materializer constructs L; child/parent copies charged. L file/result remain non-authoritative for SQL, even if C debt is zero |
| P6/P8→P9 final C durability | Owner commits C's final attempted prefix; receipt retained until acknowledged | Durability of that transaction is separate from successful dependent selection/return. Preserve receipt and retry idempotently on cooperative interruption |
| P9→P10 acknowledgement | Owner consumes exactly C receipt after successful archive_commit_slice_and_plan result | Native runtime clears C pending and pops only C's administrative receipt origin. This is not permission to clear record service/recovery origins or infer every pinned member was archived |
| P10→P11 release | Owner drops completed C authority roots; telemetry can retain receipt; executor still owns residual references | Release exact membership/original plan only after acknowledgement. Drop expendable payload roots separately only after preparation authority no longer needs them. Never declare all process storage released from this transition |
| P11→P12 promotion | Owner transfers L membership/generation/descriptor or prepared plan/receipt to C | No third carrier and no duplicated promotion; preserve original clocks. Revalidate generation/current authority; mutations still use native owner checks |
| P12→P13/P14 | Coroutine submits promoted frozen input if not already prepared; child owns W; owner holds membership | Same pool, targets, native hash/provenance/publication. No resubmission if a prepared L result is already retained |
| Any→P15/P16 | Owner retains accepted mutations and durable receipts; executor owns accepted calls; shutdown owns joins | Cancellation is not ownership cancellation. Account accepted outcomes, files and SQL before release; old-generation descriptors cannot be promoted after restart |

### Mutation checks and clocks

Before any promoted mutation, maintain:

- **Generation:** state.fence.session matches runtime.generation and carrier generation at owner entry (MaintenanceRuntime.turn). No old descriptor crosses a new FinalizedFence session.
- **Membership/identity/hash:** use the exact immutable worker prefix and original selected membership; the native UPDATE is constrained by identity, hash and body IS NOT NULL. Validate L's returned prefix against its descriptor, not a mutable requery.
- **Pins/gaps/floors:** native snapshot eligibility, active/address-specific interests, unresolved gaps and account-interest floor checks stay intact. commit_archive rechecks them at mutation time; retirement recomputes its floors from current hot state/pins/gaps/account boundaries. Selection is never a pin exemption.
- **Durability:** native hash-checked file construction, fsync/replace/directory-fsync and FULL-synchronous SQLite transactions. File completion is not manifest/row commit; row commit is not caller receipt acknowledgement.
- **Leases/reservations:** fresh owner observation, 3-second owner/execution allowance, 15-second original worker lease, 3-second clock uncertainty, native peer feasibility and deadlines. Speculative planning consumes actual elapsed owner time under the same lease.
- **Fairness:** strict priority for urgent lifecycle/control; FIFO for source and background owner calls; one fresh two-sided choose per turn; no stale queued independent retention loop and no forced archive selection.
- **Progress:** only durable ledger deltas from changed native rows count. Preparation, selection, publication, duplicate updates, pinned skips and administrative acknowledgement do not count as durable record service.

Recovery origin, record-service origin, demand origin and source-clock high-water are **not reset** by descriptor selection, worker start/end, promotion, retries, shrinking tail, or current file publication. Native _episode clears a resolved episode only from the normal debt observation; L cannot do so. Current administrative receipt origin is removed only when that exact receipt is acknowledged, as production already does.

### Earliest legal boundary

There are three different answers, which must not be conflated:

1. **Native successor selection:** evidence_service.py:742–743 selects only after the current final slice has returned no remaining tail, before the owner returns/acknowledges the receipt. It then submits after the acknowledgement/quiescent return. At this boundary useful C SQL drain is already finished.
2. **Potential materializer availability:** on the healthy success path, preparation-function return (P4, known to have occurred when successful R_C is observed at P5) ends full body construction. This is earlier than receipt acknowledgement. Input/queue/child/Future copies remain charged; the native coroutine does not automatically drop its parent snapshot.
3. **Potential L selection during drain:** the earliest scheduling-compatible candidate point is an admitted archive turn with C receipt ready and a nonfinal ≤512-row slice successfully committed, followed by bounded L sizing/selection **within the same execution lease**. Full original C membership/plan remain charged. The resource gate is U-SELECT-dependent, so **no unconditional pre-ack admission point is established by this certificate**.

A smaller SQL tail supplies none of these memory-release guarantees. After P10/P11 the owner can release current membership/plan authority, but it still cannot infer all executor copies are gone. Successful pool shutdown/join (P16) is the conservative worker/feeder physical cleanup boundary; it supplies no running-service overlap interval. Waiting for that boundary to make a resource proof would eliminate the proposed preparation overlap.

## J. Failure, restart and idempotency

| Event | Required behavior in this candidate, preserving native authority | Retained-resource treatment |
| --- | --- | --- |
| Partial C commit | Retain exact original M_C/P_C/receipt; update only returned tail after slice success; L excludes full membership | Full original charge + tail/batch reference containers + all executor residuals. Debt decrease is not release |
| File published before SQL | Keep frozen selected input/membership and compact receipt; native owner decides each removal | Published file may be orphaned; no record progress. File/disk/compression residuals remain until their actual release |
| Final SQL commits, then dependent plan/yield fails | Native caller still holds receipt and retries its plan idempotently; successful rows now have body=NULL, so no duplicate changed-row progress | Original carrier/plan/receipt retained. Owner exception/traceback can retain selection scratch; cannot clear it by claiming hot debt is zero |
| SQL commits before receipt ack | Keep native administrative receipt Need and original submitted time; acknowledge exactly once on successful owner return | Native receipt obligation survives zero hot debt. L stays non-authoritative and no fresh drought/recovery origin is gifted |
| Pins/floors/gaps change after selection | Native commit-time check may skip a newly pinned member; leave it hot; retirement floors/gaps remain conservative | Original file/plan stays fixed. Do not rematerialize different hot data as “same” descriptor; no service credit for skips |
| Generation changes | Fail closed on mismatched runtime/carrier; invalidate L promotion authority; never substitute a new generation on old payload | Submitted workers can still finish and publish; charge them until accounted/joined, without committing old results |
| Worker fails during construction/publication | Surface native failure; C receipt cannot be invented. If file publication happened but result failed, file supplies no SQL authority | Partial bodies/lines/cache and cause/context/traceback chains may survive. No subsequent speculative W use is justified by done() |
| Future cancellation succeeds while pending | No file/receipt implied. Native flow cannot silently convert CancelledError into archive completion | Pending _WorkItem/queue-error/callback roots remain until manager cleanup. Cancellation alone is not their release |
| Coroutine/waiter cancellation or timeout | Accepted owner mutation and RUNNING process work outlive waiter; inspect native outcomes during drain/shutdown | Preserve submitted inputs/results/receipt and callback/exception roots. Shield prevents waiter cancellation from proving call cancellation |
| Owner interruption before transaction durability | Native rollback/yield; retry same authority under fresh native observation/leases | Preserve original receipt/plan; local interrupted frames may retain U. No false successful service |
| Owner interruption after durability | Native ledger is durable; current receipt acknowledgement still outstanding | Retry exact receipt; INSERT OR IGNORE manifest and conditional UPDATE prevent duplicate accounting. Do not republish merely for acknowledgement |
| L becomes stale or cannot be admitted | DEFER/discard only speculative authority at safe boundary; C's native serial work continues | If L was submitted, its executor/file residuals remain charged. No third descriptor or fresh-clock resubmission |
| Source disconnect/decode cancellation | Preserve native gap/fence/source priority and drain/reconnect behavior | Suppress speculative admission when prior source jobs/arguments/results are not known released; no new source contract/pool cleanup policy is invented |
| Shutdown | Stop new planning/promotion; native admitted source drain, task-outcome inspection, owner close, process pool shutdown/join | owner.close has a 5-second join/timeout; a failed close/join is not success. cancel_futures cancels queued-pending work, not RUNNING work; parent results/exceptions need their own release |
| Restart | New writer inserts restart gaps; FinalizedFence uses a new session; normal native selection reexamines hot rows and current pins/floors/gaps | Drop volatile C/L authority; do not replay old descriptors. Durable files/manifests/changed rows remain. Episodes/nonrecord origins reload, rather than resetting deadlines |

Native commit_archive inserts the manifest once and advances counters/progress only for actual changed rows, in the same transaction. A previously completed UPDATE cannot manufacture repeat archive service. Pinned members may remain hot even after a plan has been fully attempted and the receipt acknowledged; exact snapshot/file membership is not a promise that every member was removed.

Publication is content-addressed, not a durable operation-ack queue. The current code has no restart mechanism that grants old volatile worker results new commit authority. Replanning still-hot records under the new session is the native safe behavior. This certificate adds neither a replay ledger nor an M1 completion repair.

## K. Useful-overlap proof obligation

### What the existing measurements actually show

The pinned ablation's committed CONTROL_ANALYSIS_LOG_PROJECTION.json (blob `58ff7bdf35d0de5e49022a3fc79a27db5de9b38f`) and TREATMENT_ANALYSIS_LOG_PROJECTION.json (blob `b6882d407fb16e7b0f2983a2a3e1f8130f3b2cd6`) contain the following non-overlapping cycle partitions. These are prior **serial production** measurements; they are not a run of this candidate.

| Complete-flight mean, seconds | .165 control (145 partitions) | zero-floor treatment (247 partitions) |
| --- | ---: | ---: |
| Dispatch /serialization/queue | .015090 | .007687 |
| Native archive preparation | .320719 | .235019 |
| Actual archive-floor wait | .029535 | .025987 |
| Return transport | .006280 | .005390 |
| Callback to ready marker | .000030 | .000029 |
| Ready receipt to first commit | .214734 | .179341 |
| Sum of commit-stage service | .064183 | .052755 |
| Inter-slice gaps | .317520 | .119104 |
| Final commit stage to receipt consumed | .038250 | .021012 |
| Receipt consumed to next submission | .031917 | .079659 |
| Full cycle | 1.038257 | .725983 |

Mature cohort (launch frames 775–1112): control ready-to-first .253903 s, inter-slice gaps .335711 s, native preparation .305785 s; treatment .189830/.182253/.271544 s. The control's mature gap total is 28.535399 s over 85 complete partitions. One incomplete flight per arm was excluded. No negative partitions and zero computed partition residual were reported.

A descriptive SUM of ready wait + commit service + inter-slice gap is **.596436 s** for the complete control population and **.351200 s** for treatment. It is a receipt-drain scheduling opportunity measure, not a guaranteed free-worker/free-memory interval. The ready wait occurs before an owner L selection is possible in the unchanged flow; after-first-slice opportunity is narrower. Final-commit-to-consumed includes native successor selection/arbiter completion, and consumed-to-submit includes legitimate idle/no-work cases. Neither is wholly avoidable launch delay. Means across different flights are not a paired preparation-overlap witness.

### Actual preparation versus early selection

A useful candidate interval would have to satisfy all of the following for the **same** cycle:

```text
t(current successful preparation return)
  <= t(L descriptor resource admission and immutable freeze)
  <= t(L full preparation begins)
  <  t(current last useful receipt-drain slice / acknowledgement),

current still has positive useful drain work after L starts,
and every resource/authority/lease/source requirement in H holds.
```

Meaningful preparation includes restoring/verifying canonical bodies, constructing archive lines, compression, or fsync publication in W. Selecting IDs/hashes earlier, retaining mutable pointers, or submitting only after C ack does not meet the condition.

The source does **not** require full body storage to remain the mutation receipt: the compact result explicitly removes that coupling. This supplies a plausible pre-ack opportunity when an admitted L descriptor exists. It does **not** prove capacity for obtaining that descriptor or releasing every process residual. A current receipt with >512 emitted records can naturally leave another useful slice after one admitted slice; all full original membership/plan remains charged.

**No certified useful-overlap interval is proved here.** The existing measurements establish nonzero serial drain waits/gaps, but there is no cycle with this candidate's pre-allocation resource predicate established and L full preparation observed or statically guaranteed to start before C's useful drain ends. U-SELECT prevents completing that predicate. Calling these gaps “proved overlap” or converting preparation into service progress would be false.

The currently certifiable DEFER path follows native serial behavior: successor preparation begins after acknowledgement, which would fail the intended repair objective. This is not used to conclude all designs in the requested architecture must wait for acknowledgement: successful worker return is an earlier logical workspace boundary, and the missing pre-admission proof has not established either capacity or impossibility there. Therefore the justified result is unresolved, not a universal retirement based solely on serial fallback.

If Astra establishes that immutable/resource admission can **only** occur after C acknowledgement, then this design has no preparation-overlap solution and must be retired. Earlier selection alone would not change that conclusion. No runtime budget is authorized to decide this static question.

### Short receipts and planning admission

For a current receipt of ≤512 emitted records, native archive_commit_slice_and_plan commits the only slice and selects its successor in the same call; submission is afterward. There is no natural nonfinal-slice window. Boundary/low-demand cycles can likewise offer no useful successor or insufficient time.

This candidate permits at most **one** extra planning-only opportunity per current receipt, and only if the existing arbiter chooses an archive turn from actual observed archive/receipt need, L is absent, and the same owner/execution/peer leases admit it. It runs at existing background priority and FIFO position, is interruptible by urgent work, consumes elapsed lease time, completes with **zero** planning progress, and cannot move any service/recovery/demand/source origin. It must not block C acknowledgement waiting for L or demand repeated zero-progress turns.

That opportunity still requires U-SELECT to be bounded **before** allocation. If only a forced side, fabricated Need, new administrative descriptor demand, enlarged reservation, deferred-current entitlement, renewed clock, or unbounded owner polling would make it run, the operation is **DEFER LOOKAHEAD**. Native receipt Need remains the current receipt's obligation; it is not a free speculative scheduling entitlement.

No source-backed useful short-receipt interval or zero-extra-cost planning admission is claimed. Such an extra turn changes the number of admissions even if all priority/lease rules stay fixed; its actual owner work must fit the unchanged contract, and its delay must not be hidden in the timing comparison. Existing serial-cycle evidence does not quantify this new turn or prove it preserves liveness. The resource gate is unresolved, so no additional planning admission is authorized or implemented here.

## L. Unresolved assumptions and exact Astra re-review obligation

**Primary static obligation U-SELECT:** establish a source-backed, pre-allocation bound for the owner operation that freezes exact disjoint membership plus immutable encoded payload/chunks/lineage/coverage, including provenance prefetch/canonicalization/exception scratch. Show its SUM with the complete current receipt obligations, conservative executor/process residuals, and concurrent source/SQLite/worker requirements fits an actually applicable unchanged resource domain. The 4/20 MiB finished selection check, 16 MiB body target, 512-row tail, and hot-disk guard do not supply that proof.

This is the exact reason the certificate cannot be feasible. It must be answered statically. In particular:

- Do not assume finished snapshot encoded_bytes or post-allocation object/pickle measurements bound the allocations required to get there.
- No total physical-memory ceiling exists in the inspected paths. If a proof needs one, its authority/domain must first be identified; neither old RSS nor an invented “16 MiB envelope” is acceptable.
- Native file size and Python/pickle/compression representation charges must be expressed from full actual provenance and exact interpreter/library representations, not a per-record overhead guess.
- Healthy executor residuals can be conservatively retained as specified in F; completed/cancelled/failed Futures are not release barriers. Unknown source-failure pending work remains an admission veto.
- A same-cycle useful preparation interval and short-receipt planning compatibility remain conditional on closing the resource predicate. Timing averages alone do not close it.

These are disclosed proof limits, not permission to add tests, impose a current limit, change native scheduling/source contracts, or implement a selector. This review does not establish sufficiency for recovery under .165 even if resource feasibility is later proved.

## M. Exact conclusion and stop

Current native acceptance, including the **13,631,744-byte** valid record and native-valid encoded/body prefixes, is preserved by the specified current path. Full materialization and compact receipt authority are different lifetimes, so acknowledgement is not inherently the logical materializer's first release point. Nevertheless, **bounded immutable descriptor admission before allocation and a resource-certified useful pre-ack preparation interval are not proved**. The exact missing bound is U-SELECT above; process residuals may not be erased to make its SUM appear to fit.

Return this certificate to Astra with U-SELECT and its dependency on unchanged resource-domain authority. No implementation, focused A–H suite, remaining material variant, .165 comparison, M1/preflight fix, production promotion, successor freeze, canonical Stage E or Stage F follows. Existing stops/evidence remain preserved. Material budget remains **4/6 consumed, 2/6 unused**. **STOP.**

STATIC_PROOF: RESOURCE_OR_RELEASE_BOUND_UNRESOLVED
