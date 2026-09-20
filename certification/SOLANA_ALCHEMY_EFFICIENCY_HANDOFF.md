# Combined Solana + Robinhood efficiency repair

This branch composes PR92 (`a34c5d4dce4dc93445b837cfeeb51901825bdb9f`), PR91 observability/accounting, and the current execution-certification sources from `960980c4412f525b15568401a2b8f0c2c25bdbab`. The complete exact source/config/policy manifest is `results/solana-start-manifest.json`; unchanged source files are independently recorded in `results/solana-policy-integrity.json`. Do not merge to main.

## Previous validation and contention

The Robinhood-only validation never launched. Runs 35518217254, 35518214259, 35518094365 and 35518072321 are terminal deterministic CI, with every live job skipped. They are not acceptance evidence. There was no Robinhood-only live run to cancel. Its planned validation is superseded by the combined task.

The unrelated execution-branch legacy diagnostic 35516954272 was still active during repair. It was not cancelled indiscriminately. The new workflow waits read-only for the existing contention guard to pass before any capability probe or market process. Source-head drift fails immediately. Waiting is not lane uptime. No prior process state/readiness is reused.

## Exact sources

| Lane | Source SHA | Policy identity |
|---|---|---|
| Pump | 7bcbf4f6c398e51f4cb01801c057d54244e05abd | bb2631d83f5be287a0afc01dfc6d7a4da8b7086ae0afd09dfbf27df6d9d66a6e |
| Meteora | 0f01c79a4994224bf79b8c365b34f9f58cf3904e | b1de19ed974faf3c92261fe7f4f6cb47570e4890c49e9547d7f4fcc50c7179b8 |
| Pons | c692fe446bdee4ea1179da27a3f0c9f2f281f118 | d9842e32b7ce088bce69f9c4bba98c648017273d9edffbdca2f314f3cdad8ce9 |
| Ramses | 6b7ddd69940f5c9e056b2dca61c443450ca9965e | 50d928914df10568a7bc9679f0887ac7786fe17d67f1c57171c17a5a95fc6766 |

Meteora's current source already changed descriptive/duplicated execution-policy fields, but the execution integration retained a stale raw-file hash. The actual raw hash is `e09ad3d90ab4bfa5e39fb05c59c522712960f80ef3601ca0a0f65baaff701059`; canonical native accounting digest is `21da031409371fee6ddcb28e354dc499c12625661a638faa01ec702c120b4894`. Its embedded policy label remains b1de… . The supervisor validates exact file bytes before exposing that label. Native accounting retains its canonical digest. No policy bytes or semantics were changed in this repair.

## Baseline and diagnosis

Cycle 4 artifact 10605823461, SHA256 `653ba9aaf63e591b7e6691a8b258103d527de9764b5aca722b15f18f5a564aaa`, is preserved. `results/solana-cycle4-baseline.json` records full observation plus normal drain, not an artificially truncated hour.

| Metric | Pump | Meteora | Aggregate |
|---|---:|---:|---:|
| Physical transports | 7,507 | 714 | 8,221 |
| getTransaction members | 28,991 | 331 | 29,322 |
| getMultipleAccounts | 1,623 | 298 | 1,921 |
| getBlockTime | 1,226 | 188 | 1,414 |
| getSignaturesForAddress | 280 | 165 | 445 |
| getGenesisHash | 148 | 1 | 149 |
| getTokenLargestAccounts | 147 | 0 | 147 |
| Complete evidence / economic vectors | 235 | 2 | Not additive opportunities |

Aggregate logical members: 33,398. Estimated Alchemy CU: 1,261,810 using the documented configurable schedule, not an invoice. Each batch member is priced independently. Only 41 repeated Pump getTransaction members and zero repeated Meteora members were observed: duplicate physical transaction fetches alone cannot explain or deliver a 40% reduction.

9,093 retained bodies had only speculative-prefetch interest. Admission replay bounds speculative work to one eight-signature batch per pool per normal ten-second Pump evaluation cadence: 10,593 of 86,590 speculative signatures admitted, 75,997 deferred. All signatures and foreground requirements remain visible. Among retained prefetch-only bodies, 7,639 would be deferred. This is a counterfactual scheduling replay, **not proven live CU savings or equal decision latency**.

Cycle 4 had older strategy policies. It is the latest clean complete infrastructure baseline, but strategy-qualified cohorts are not directly interchangeable with current execution-certification. Report that confound explicitly.

## Repairs and retained controls

* Both actual HTTP paths (Pump Alchemy and Meteora's direct-Alchemy compatibility shim) inherit the new immutable-read layer; dead OnFinality compatibility code is not substituted for the active topology.
* Compatible finalized JSON getTransaction reads route through the shared broker, including direct callers. One signature has one physical job/lease and an append-only compressed body. Conflicting bodies fail closed. Hot eviction no longer causes refetch; original acquisition time remains authoritative for consumer deadlines.
* Concurrent consumers wait within their own original deadline for an existing leased fetch. Cached interests do not create new acquisition consumers. Different encoding/commitment/version requirements remain separate rather than silently changing decoding authority.
* getGenesisHash is shared across rotations by exact opaque endpoint identity. Endpoint changes require a new proof; transaction authority cannot silently change. A wrong network still fails native mainnet authentication.
* getBlockTime is reused only at/below a finalized slot proven by the same endpoint's authenticated finalized transaction/account response. Null/error responses are not cached.
* Broad public WebSocket discovery is unchanged. Every stream signature survives hot-window eviction in an append-only compressed hint archive. Public hints never populate the authoritative body cache. Speculative prefetch is bounded per pool; foreground requests are not restricted by that budget.
* Broker background work yields to admitted foreground consumers. The physical governor gives Pump and Meteora foreground requests a common deadline class and a bounded aged grant, while positions remain first. Background work is never aged above foreground. Per-lane grants, waits and misses are durable.
* Background RPC rotations preserve their pacer. An internally recovered getTransaction 429 also updates shared broker batch pressure; bounded recovery remains. Global endpoint cooldown/rate ceilings are unchanged.
* Existing incremental PumpSwap history, bounded exact-window bootstrap, Meteora exact interval/boundary proof, duplicate detection and warmup remain. Signature-cache hits/misses are now attributed.
* Dynamic reserves, balances, active bins, liquidity and full mint accounts are not given a new persistent cache. Current mint accounts contain mutable safety fields; a decimals-only cache cannot replace their required authentication. No safe shared immutable epoch was established for arbitrary cross-candidate dynamic snapshots, so there is no added TTL reuse or batch delay.
* PR92's shared Robinhood cache, header index, receipt/log/state reuse, original-deadline evidence, capability/parity checks, Pons timing and Ramses fairness remain. Fixed the hourly capability-probe output path so the supervisor actually receives the proven capabilities beside its deterministic gate.
* Raw logical wire members, HTTP transports, priority/kind, cache reuse, endpoint proof events, unique signatures/bodies, estimated CU and honest completion denominators are exposed independently. Zero economic vectors produces no requests/vector efficiency claim.

## Validation and reproduction

Run `python -m unittest discover -s certification/tests -v`.
Prepare new isolated worktrees with `python -m certification.run prepare --worktrees PATH`.
Run all four composed suites and all three resource checks with `python -m certification.run verify --worktrees PATH --output GATES`.
Reproduce baseline with `python -m certification.solana_baseline ARTIFACT/certification-hourly --run-id 35508695288 --output baseline.json`.

Local transcripts/counts are in `results/solana-local-validation/`. Source integrity still requires exact worktree heads, exact protected files, and byte-identical operational overlays. The former cache-eviction test now requires the stronger invariant: identical body with **one** fetch after hot eviction, rather than expecting a second fetch.

Only the combined workflow may validate this task. A single marker push on `repair/solana-alchemy-efficiency` runs current-revision gates, waits for contention clearance, performs the 600-second concurrent smoke and normal drain, then uses exact readiness for one fresh 3,600-second four-lane campaign. No process restart, window splicing, competing lane test, or recurring launch is authorized by this handoff.

## Acceptance status

Deterministic correctness is separate from live efficiency and natural execution. Live 40% savings, equal-or-better useful coverage, unchanged Pons stale fraction and non-starved Ramses must be measured in the combined campaign; none is inferred from lower speculative admission. No natural lifecycle or profitability claim is made. Another provider is not justified by existing evidence. Dynamic account acquisition, exact second-leg history, Meteora complete-economic-vector throughput and Pons evidence freshness remain measurement priorities.

## Preflight supersession

35520048920 at 3ad467a0 was cancelled during read-only contention waiting, before any lane launch. Full hosted deterministic/resource gates had passed. A focused concurrent-consumer reproducer found two broker reservations for one fetch; the follow-up atomically claims the unique job before reserving physical capacity, releases it on an unavailable reservation, and respects sibling 429 batch reductions during the wait. Cancellation workflow 35520619194 succeeded with exact run/SHA allowlisting. This is superseded preflight evidence, not a smoke or hourly observation. See results/solana-preflight-review-35520048920.json.

A second focused regression proves that a body arriving after an acquisition deadline is retained as immutable history but cannot complete that expired consumer. A later independent consumer may reuse it under its own unchanged deadline.

## Hosted gate race, run 35520877325

Revision 22516a91 failed the Pump and Meteora concurrent-fetch regression in hosted CI (2 fetches where 1 is required). All 60 supervisor tests, 515 Robinhood tests, and three resource gates passed. No probe, smoke, or lane launched. The preserved artifact is 10609010093 (SHA256 dd64f8f2f907623c4b1d5cde5786f5a86915f4b2bf11c8b661761bf86f6e707f).

The demonstrated race was between the cache check and queue UPSERT: another process could complete the immutable fetch before the stale UPSERT revived its job. Both now execute in one SQLite write transaction. Atomic claims also reconcile jobs already fulfilled by a cache producer. The original concurrent assertion remains unchanged; a deterministic cache-between-queue-and-claim regression and 100 repeated concurrent trials pass. See results/solana-hosted-gate-review-35520877325.json. This is failed deterministic preflight evidence, not interrupted market evidence.

Replacement local verification: Pump 281, Meteora 385, Pons 257, Ramses 258 (1,181 total); 60 supervisor tests; all three resource gates and exact-source/config/overlay integrity passed. Transcripts: results/solana-atomic-validation/.
