# Source and capture responsibility map

This map follows the published native path. Counts describe the corrected
retained capture, excluding the unknowable 915-byte stopping frame. All discovery
identities are retained regardless of profitability, position funding or later
Current rejection. The repair changes neither the universe nor its deadlines.

| Evidence class | Trigger and delivery | Required consumer / authority | Duplicates, projection and persistence |
|---|---|---|---|
| Shared control | `SelectiveSource.control`: persisted checkpoint or tip minus 256-slot overlap; Yellowstone block metadata and finalized slots | Model B fence, chain block-time mapping, continuity/reconnect boundaries; not economic transactions | Metadata/finality also present in candidate streams; each scope has independent witness obligations. Buffered batches up to eight commit through the sole owner. No bodies delivered |
| Pump scout | `scout_request` at startup/reconnect, program-owner/discriminator filters, 56-byte account-data slice | Pump mint/curve discovery and cheap retained nomination; not an interval-completeness proof | 263 updates, 169 identities; locators below the replay floor remain useful. `commit_scout` → lifecycle/outbox → CandidateHistory. Fixed scout independent of candidate churn |
| Pump/PumpSwap rolling logs | `rolling_programs` → `live`, two fixed program mentions on one WS connection, finalized commitment | Independent Current and Survivor cheap history, creation, bonding curve, graduation/trades and later recovery, including presently unfunded candidates | Entire execution logs + signature/error/context delivered. 17 cross-program duplicates, no reconstruction/reconnect in capture. Successful full-log provenance remains intact; failed Python log subtree is now omitted only after full JSON validation |
| Program native status | Same `live`, per-program successful AND failed `transactions_status`, metadata and linked finalized slots; requested `from_slot` | `CandidateTransactionJoin`: independent signature/index witnesses, canonical order and complete slot membership | Successful WS logs alone cannot certify membership/order. Failed statuses are essential negatives. 15,201 statuses below requested floor cost 1,548,879 B physically and are rejected locally. No body, balance/instruction or account-key arrays received |
| Position-specific evidence | `plan_live` + `StableShards` preserve live position/continuation interests; native per-address status and WS logs; original deadlines/priority retained | Existing positions, urgent continuation/safety and exact checkpoint gaps | Zero such complete position samples in the capture. Its future overlap with program streams is not quantified. Cannot remove it based on a zero-position tape. Shard membership freezes after position handoff until retirement |
| Selective archival RPC | `SelectiveHistory.request` intervals → EDF `plan` → existing acquire workers, independently enumerated signatures/indices and finalized bounded history | Exact discovery-to-window history missing from rolling coverage; bonding curve and graduation continuity; CandidateHistory and runtime consumers | Same immutable job identity is now reasserted without redundant DB work; pending pages/cursors/status/deadline unchanged. Physical calls only reduce if a real request is prevented; this repair demonstrates none in the captured window |
| Canonical events / publication | Joined status+logs+block+finality → `commit_candidates` / rolling history → lifecycle staging/publish → durable CandidateHistory acknowledgement | Authoritative economics, independent regime eligibility, retained cheap history, high-water marks and recovery | Exact event identity/index/hash dedup, rolling references and outbox intentionally serve separate authorities. No lossy coalescing. Hashes and retired-body recovery references retained |
| Candidate qualification | `pump_candidates` drives real read-only production Current/Survivor evidence functions; original campaign/graduation deadlines | Complete fixed qualification windows and structural/safety decisions | Zero full Pump samples. Previous `qualification_ready` on skip/error was observer distortion. Complete negative economic decisions may count as technical evidence; missing history cannot become an economic rejection |
| Pons observation | Native Robinhood discovery, authentication, Current evaluation and Survivor bounded seven-day discovery/increments | Independent Pons Current/Survivor, original 0.5-second physical pacing/fairness | Captured bootstrap took one binary-search step and never established full discovery domain. Valid slice rejected when header witnesses enlarged total batch count; one-line repair retains full response/reorg checks |
| Proof observer | Source observer → `TransportMeter`; native raw-frame archive, protobuf/native JSON metadata projection, hashes, level-six compression and stats; process/owner probes | Diagnostic capture, independently inspectable physical receipts and budget audit | Substantial local work, separately profiled. WS projection avoids log-string materialization; exact raw payload remains. Capture writing is not canonical authority. Changed stopping-frame order fixes charged/captured mismatch. Future observer cost must be included in whole-process evidence |

## Actual callers and ownership

`solana_selective_source.py` installs SelectiveHistory on the canonical evidence
owner, starts native sources and manages archive work. Every physical delivery
is observed before routing/filtering/deduplication. Its unchanged subscriptions
are read-only. Priority for positions and urgent original-deadline candidates
is unchanged.

`solana_source_intake.py` previously provided selective native transaction-body
intake for other supported paths. The additional WS helper reuses its bounded
native JSON validation and ambiguity checks. No transaction-body filter is added
to the Pump/PumpSwap feed. WS acknowledgement/errors, successful log indices,
signature and error semantics are preserved.

`solana_candidate_join.py` waits for native signatures/true indices, successful
log facts, block metadata and finalized linkage. Missing logs, native identity
contradiction, backlog bounds and inconsistent order remain fail-closed. Log
arrival may precede native replay by many slots; the 10,210-item tape tail has
no synthetic completeness receipt. There is no guessed filtered enumeration
index. This file is byte-identical to the reference.

`solana_stable_shards.py` retains stable memberships across churn; positions
freeze the handed-off shard. No new shards were created by corrected-capture
candidate churn. The two program subscriptions provide retained cheap history
without deep-watching every candidate. This file is unchanged.

`solana_selective_history.py` owns durable acquisition jobs, immutable bounds,
coverage and observations. Its targeted idempotence repair relies on the existing
single owner. Changed urgency still updates transactionally, and planning still
marks original-deadline failures explicitly. It neither skips needed jobs nor
copies an unrelated coverage checkpoint.

`solana_evidence_runtime.py` supplies native lane readers and exact consumer
interest/checkpoint handoff. `runtime/evidence_worker.py` preserves classification
of unavailable evidence as recoverable/coverage failure and maintains native
priority/safety behavior. Neither file changes.

`engineering/solana_capacity/pump_pons_proof.py` enforces read-only endpoints,
logical request-element counting including retry/batch attempts, application-byte
and planning-CU ceilings, storage/wall stops, and disposable-state isolation.
It opens no production money books. Its old finite execution limits remain; the
new proof specification is a separately reviewed/authorized plan, currently
BLOCKED. Do not run its old execute command to approximate that plan.

## Attribution boundaries

Account slicing and body-free status filters already reduce physical data.
Native parsing, job idempotence and durable event dedup reduce local allocations,
transactions or stored copies; they do not change delivered provider bytes.
Independent native witnesses have separate authority from WS facts. Proof
compression reduces capture size without refunding upstream traffic. Existing
authenticated cache reuse only saves provider consumption when the transport
actually suppresses a physical request; no new such saving is proved here.
