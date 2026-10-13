# Pump historical/live separation — engineering successor

PAPER remains **SAFE_PAUSED**. This is the isolated branch
`engineering/pump-history-separation-20261013`, based on published preservation
commit `a55f458baf37c7dafa6286a2a05a287b1a8c2611`. Its implementation baseline
and the unchanged installed source are
`ea4f4f1bfb12ef0d3ce01d4df70a93f6d37e7605`.
Resolve this successor's exact SHA with `git rev-parse HEAD`; the external
publication receipt records the pushed identity. The original
[safe-pause handoff](SAFE_PAUSE_RESUME_HANDOFF.md) remains preserved.

No deployment, service start, provider diagnostic, resize, funding, capital
initialization, research resumption or acceptance was performed. The installed
PAPER unit is inactive/dead, disabled, MainPID 0. The initialized shared epoch
remains `paper-shared-1000-20261011T071207Z`, inception
`aea262d34d976cddeddf83f57045508cf09f3c8e28cf8a2c73ae49d38cc261b1`, approved
policy `b91e83300994b6c02fe5e6bdbeb031cc391e6c8caa97af9fa6df1ecbc4aa979c`.
It has $1,000 cash/equity and no positions or unsettled obligations at the
preserved reconciliation. The historical $500 root is unchanged. Actual live
lag after this change is **unmeasured**; the official acceptance clock is zero.

## Processing boundaries

The canonical evidence owner remains the sole writer of `solana-evidence.sqlite`.
Its live work retains authentication, normalized economic identities, native
ordering, gap/finality/continuity checks, durable event storage, minimal discovery
and origin/binding updates, durable outbox obligations, verified acknowledgements
and canonical proof/checkpoint publication. Urgent protection and its required
fresh completeness checks retain the original priority and synchronous path.

The following work is separate:

| Work | Execution and retained authority |
| --- | --- |
| Historical coverage planning | One bounded process calculates the original `RollingHistory` predicate from committed read-only inputs; owner verifies source generation, bindings, origins, gaps and proof bytes before applying the original mutations. |
| Optional historical acquisition planning | Reuse a current authenticated local plan; otherwise enqueue exact missing-history analysis before any provider dispatch. Original urgent dispatch is unchanged. |
| Candidate-history transformation and delivery | One dedicated thread uses the original consumer transformations and existing CandidateHistory DB; owner verifies its FULL-commit receipts before ACK. |
| Consumer coverage and observation lease updates | Bounded off-owner batches; canonical publication rechecks delivery, source identity, native boundaries and current gaps. Lifecycle state updates reject changed promotions. |
| Cold candidate reconstruction | Same historian and durable job table; decode original archives off-owner in 64-record batches; owner verifies original bytes/availability and restores pointers atomically. |
| Scoped archive preparation | Owner selects and checks pins; historian expands bodies, serializes, compresses and fsyncs the original archive format; owner rechecks current rows, complete ownership/pins and consumed receipts before changing pointers. |
| Existing main archive preparation | Existing native/archive pool and ArchiveFlight machinery remain intact. |
| Survivor reset calculation | Existing Survivor worker incrementally reuses the exact approved reset reducer. No price records are deleted. |

Owner-only retirement, restore and checkpoint mutations are necessary authority
operations. Current pin checks, original financial-consumption checks and urgent
historical obligations are not deferred to optional work. Existing FIFO fairness
and urgent SQL preemption remain unchanged; no replacement scheduler is installed.

## Minimum historical workload

`rolling_preparation_jobs` in the existing canonical DB is the durable queue.
It preserves deadlines, leases, restart recovery and failures. Each unchanged
completed plan has verified dependency/policy identities and a hashed metric;
it is not recalculated or rewritten on every poll. Unstarted requests for the
same candidate, lower boundary and original deadline coalesce only by extending
their upper boundary. Active work and independent families are not overwritten.
The original slot coverage and deadline obligations remain exact; redundant
contained acquisition-job representations can disappear.

Indexed revision records detect coverage/gap changes, including a corrupt rewrite
that leaves its checksum unchanged. Reorganizations, changed bindings, source
generation changes, deletion and incompatible proof changes reject stale results.
Monotone publication may permit a conservative result to apply, but its old gaps
are not cached as the verdict for newly improved coverage. Acquisition dispatch
cannot treat pending analysis as missing or complete evidence.

CandidateHistory supports indexed exact `since`/`through` windows for both inline
and canonical-reference events. Full-history calls retain their original meaning;
Current restart reconstruction still reads its required creation/graduation and
pregraduation evidence. Existing selective Current reads and incremental volume
quality remain intact.

Pump Survivor uses a verified incremental calculation prefix, bound to graduation,
policy, original archive authority, exact point hashes and time boundaries. It
retains every point, the original graduation anchor, the exact boundary witness
and all last-24-hour observations. The original two/six-hour structure, completed
base windows, reset/minimum-low predicate, demand windows and seven-day eligibility
are unchanged. An insertion/rewrite/deletion inside the calculated prefix invalidates
it, including corruption with an unchanged hash. Incomplete/recovery histories
use the original fail-closed path. Fresh executable quotes and protective decisions
are never cached. Pons does not use this new calculation path.

## Bounds and recovery

- One lazy historian process, niceness +5, 512 MiB address-space limit, 128 file
  descriptors. Optional CPU calculations target one-quarter core. Per-task wall
  guards are physical fault containment, not trading or holding expirations.
- Planning reads use a 100-ms SQL guard and at most 16 MiB of immutable proof
  input. Read transactions close before decompression and analysis. Original
  eight-entry/512-KiB proof-prefix cache remains bounded.
- One planning/restore lease and at most one additional scoped-archive future;
  the same process executes them. Candidate delivery uses 64 rows/16 MiB and
  one separate thread. Existing 32-MiB cold decode and 16-MiB archive bounds remain.
- Worker failures retain hot evidence, durable jobs, candidate identities and
  original deadlines, with bounded backoff. A broken historian is replaced
  independently of native decoding/canonical intake. No provider traffic is
  generated by these workers.
- Crash after consumer commit and before ACK replays the same original identities.
  Crash before archive publication leaves original hot data and a possible
  unreferenced fsynced file. No canonical pointer changes before durable preparation.
- `MM_SOLANA_HISTORY_SEPARATED=0` uses the original synchronous paths and drains
  queued new obligations through those original checks. It does not reset counters.

All original economics, shared capital, native quotes/USD, stops/partials/trails,
Current/Survivor independence, winner scaling and legitimate holding duration
remain unchanged. The source-integrity guard pins the exact reviewed acquisition
adapter delta, and a separate AST comparison verifies that only its history-read
and prefix-source nodes changed. Pons 40-block factory capability, ten-block
unverified-filter fallback, 10-RPS profile and three/five-second deadlines are
unchanged. Meteora/Ramses remain paused; dashboard files are unchanged.

## Offline evidence and limits of the result

External evidence directory **E** is
`/root/Documents/Codex/2026-10-10/the-meme-machine-eliminate-redundant-data/blocker-repair-20261011`.
Small publication/test/benchmark identities are in
`HISTORY_SEPARATION_PUBLICATION_20261013.json` and the adjacent implementation
proof. Large retained histories stay in their original locations.

`E/HISTORY_SEPARATION_FINAL_PROOF_20261013.json` replays identical authentic
stored economics: 1,024 records, 18 event-bearing slots, 652 historical fragments,
52 bindings, 44 retained candidates and 16 history requests across Pump/PumpSwap.
Ordered event identities/content, candidate populations, exact missing-window
verdicts and coverage/deadline obligations match. One redundant contained job is
coalesced (393→392); no required interval or economic record disappears.

| Measured replay scope | Original | Separated |
| --- | ---: | ---: |
| Historical owner CPU | 10.105 s | 0.148 s |
| Historian process CPU | 0 | 0.566 s |
| Parent CPU | 14.071 s | 2.202 s |
| Historical proof points decoded | 3,893,480 | 165,925 |
| Canonical-owner SQL statements, all traced stages | 43,876 | 25,562 |
| Live subset intake | 1.37 event-bearing slots/s | 17.23 event-bearing slots/s |
| Full subset + history/delivery drain | 13.167 s | 2.786 s |
| Owner publication p95 | 1.061 s | 0.092 s |
| Urgent owner read maximum | 0.0024 s | 0.0119 s |

The separate deterministic seven-day minute-price regression retains all 10,081
points. Twenty exact reset evaluations, including first prefix construction,
use 4.879→1.009 CPU seconds and decode 201,620→37,481 records. SQL statements
increase 60→185 because the replacement uses small indexed integrity lookups;
this is not a claim of fewer statements in that calculation. Exact strategy
qualification equivalence is separately tested on a late eligible Survivor.

These are bounded **offline** owner-pipeline and synthetic calculation results.
The replay excludes native transport/join, broad-market input, actual native
quote/USD protection, concurrent Pons and full-machine acceptance. It does not
measure live lag improvement or prove sustainable two-CPU market capacity.
The historic authenticated 3.97 incoming / 1.99 completed slots/s and 628→984
lag remain the comparison baseline. No new provider requests/CU, billed savings,
monthly savings or hardware requirement are claimed.

Failed evidence is retained: `/tmp/mm-engineering-36wybq06` (initial fixture
API/clock errors), `/tmp/mm-engineering-br8o7qiz` and
`/tmp/mm-engineering-75d62y45` (overstrict raw-job-identity comparison that detected
the deliberately coalesced contained obligation), and `/tmp/mm-engineering-jwr3cjb4`
(incorrect test unpin call). Their logs remain in E. Final assertions retain exact
canonical/eligibility/coverage/deadline checks and explicitly verify coalescing.

## Deployment preparation — do not execute during this pause

The normal profile `deployment/paper-continuous.conf` prepares
`MM_SOLANA_HISTORY_SEPARATED=1`; supervisor forwarding is limited to the existing
Solana evidence worker. It is **not installed**.

After separate owner authorization, use the existing coherent deployment path:

1. Recheck exact source/CI, service inactivity or open obligations, single-writer
   ownership, epoch/inception/policy, preserved historical state and recovery points.
2. Pass storage/mount, backup/restore, resource and deployment-scope OPERATIONAL
   checks. Root was 75% and the trading volume 85% with 7.2 GiB available at this
   checkpoint; the existing backup storage warning/failure must not be bypassed.
3. Install the exact published successor and prepared normal profile coherently.
   Do not blindly start the existing unit: the preserved observation drop-in still
   selects `observe --seconds 1200`, `Restart=no`, `RuntimeMaxSec=1265`.
4. Preserve the initialized $1,000 root, risk state, counters and credentials;
   reconcile existing positions/intents before any startup. Do not reinitialize.
5. Run a separately authorized bounded authenticated comparison of the actual
   native intake/join/publication, stable backlog, concurrent Pons protection,
   maintenance and four-regime gates. Do not rerun the consumed quote component.
6. Fund and start acceptance only after applicable original readiness and owner
   activation authority pass. The new engineering evidence is not that authority.

Rollback first uses the same successor with the feature flag off, allowing queued
obligations to drain through the original paths. Retained raw price/history data
supports the original readers. An older source rollback requires quiescence,
reconciliation and confirmation that new queued obligations have drained; never
drop new tables or rewind portfolio/provider history to make rollback easier.
