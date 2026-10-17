# Synthetic Solana source conformance

This fixed offline corpus tests native source and worker mechanisms. It supplies
no network, financial capability, readiness exception, manual database seed or
consumer acknowledgement. It is not authenticated market evidence, a Solana VM
execution proof, the copied-main/kernel acceptance, or market capacity evidence.

The original finite corpus correctly failed two independent startup contracts:
its scout progress was 2,069 basis points against the unchanged 6,000 minimum;
its final native header16 could seal only control15, so the source could never
reach its sampled RPC head16 and open rolling feeds.

The replacement has one immutable four-slot ledger:

| Slot | Included transactions | Market time |
| --- | --- | --- |
| 1 | Two failed `AccountNotFound` attempts, one per program; no economics | origin minus3 seconds |
| 2 | Target Pump creation and its initial buy | origin minus2 seconds |
| 3 | Target buy, 110 distinct Pump creations with initial buys, one independent PumpSwap trade | origin minus1 second |
| 4 | Empty finalized linked child | origin |

The sampled RPC head is3. Later native acquisition supplies linked child4, which
can seal3. Nothing calls child4's open interval complete or treats the fixed
snapshot as a continuously advancing market. The first WebSocket messages are
the two real failed ledger entries; their signatures, native error statuses,
RPC rows and slot1 transaction count agree. They establish only the original
subscription frontier. No economic event is inferred from a failed attempt.

There are115 ledger transactions,113 successful economic transactions, and224
decoded events. Every signature/index, membership, event timestamp, block hash,
parent hash and transaction count is shared by RPC, WebSocket and Yellowstone
representations. Program history uses actual100-row pagination with tokens bound
to the exact address and interval. The110 additional creations have distinct
synthetic mint public keys and their correctly derived bonding-curve PDAs.

The target keeps the template's original initial real reserve793.1 trillion.
Its initial buy consumes500 trillion tokens; the subsequent buy consumes another
billion. Virtual/real token and quote reserve deltas agree with both event token
amounts and net quote amounts. The scout is copied from that exact final state
and exact transaction signature, rather than from the initial creation state.
Original policy selects the target; no qualification or funding is asserted.

The workload exceeds the existing1MiB process-preparation threshold through
actual creation/buy logs, not padding, a threshold override, or a probe task.
Each transaction remains below10KiB of log text; the fixed native frame queue
remains below128 frames. The direct regression measures the original
`CandidateCommitQueue` byte expression and executes the unchanged
`SelectiveSource.candidate_commits` dispatch through two real spawned decoder
workers. Original canonical COMMIT, CandidateHistory FULL COMMIT, exact native
ACK and coverage publication earn prewarm release. Original development selection
and acquisition then enqueue a real historical planning job, which executes
through a real spawned history worker and the unchanged apply fence. All workers
join. The test publishes bounded numeric evidence for these source boundaries.

The RPC bodies deliberately include native Pump identity/log fields and omit
unmodeled template balance/CPI metadata. Signatures are explicit synthetic
markers, not signatures verified on any chain. The independent PumpSwap pool
has no fabricated migration from the target mint. Full Survivor qualification,
held protection, financial books, settlement, production restoration, live
provider behavior and complete-market coverage remain unexercised.
