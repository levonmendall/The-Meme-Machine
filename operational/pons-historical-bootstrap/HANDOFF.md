# Pons historical preparation and warm restart

**Outcome: OPTIMIZED_BOOTSTRAP_READY_FOR_BOUNDED_PROVIDER_VALIDATION.**
The implementation and deterministic offline validation are complete. No
authenticated complete seven-day Pons seed was recovered. No live historical
campaign, provider acceptance, deployment or PAPER state migration occurred.
The blocker remains
`combined_position_and_candidate_provider_latency_not_certified`.

The useful immediate change is a durable, independently enumerated factory
census with separate native economic reconstruction and verified warm recovery.
At the existing ten-block provider boundary it halves the empty-census physical
batch count, but does **not** make a seven-day cold bootstrap cheap. Required
economic histories can dominate cost. If the account really is constrained to
ten-block queries, prospective accumulation is preferable unless the owner
explicitly values earlier Survivor availability enough to authorize backfill.

## A. Recoverable historical sources

[SOURCES.json](SOURCES.json) screens 503 main database files and audits 33
relevant sources through 19 distinct, individually copied databases. Main/WAL
checksums were checked before and after replay; originals are unchanged.
No preservation collection was recursively copied and no money book was copied
into a replacement economic epoch.

| Source | Independently inspected contents | Reuse / completeness |
|---|---|---|
| Corrected `sc-proof-corrected-20261008/pons/history.sqlite` | Policy identity, one incomplete binary-search step; zero candidates, points, events and graduation intake | No covered interval or candidate history |
| Original `sc-proof-20261007/pons/history.sqlite` | Same empty history and unfinished boundary search | No seed |
| `shared-capital-validation-20261007/pump-pons-provider-proof/pons/history.sqlite` | Empty native history, policy only | No seed |
| Production Pons lane directory | Health/lock files; no native history database | No seed |
| Production/preserved immutable RPC caches | Production cache has 520 isolated headers, blocks 79,692,264–81,782,454, timestamps 1,791,092,124–1,791,305,215; no log ranges | Existing immutable facts can still serve their native cache keys; these disconnected headers establish no census or economic continuity |
| Short combined proof cache | Headers and receipts, including search boundaries and unrelated live evidence | Authenticated individual facts, no complete seven-day launch/graduation or pool census |
| Current candidate planes and PAPER snapshots | Retained runtime state and reporting snapshots; no independent complete factory/range journal | Existing economic/Current state remains owned by its original authority; not a Survivor universe |
| Preserved lineage/factory/deployer fixtures | Pinned deployments/ABIs and a real graduation/registration/initialization example | Reusable authentication engineering and authentic example identities; not continuous history |
| Recovery/source archives and cloud snapshot inventory | Twenty small inventories/reports or source archive listings; no database in the source archives | [ARTIFACTS.json](ARTIFACTS.json); off-host snapshot contents were not restored or certified |

All selected databases passed integrity checks. Native empty histories passed
their replay/checksum checks on isolated copies. Cache domains and exact source
paths/checksums are in the source report. A report, cursor, successful validation
or snapshot listing did not count as underlying coverage. Original chain/genesis,
boundary hashes, event census, candidate histories and policy provenance cannot
be established for a complete seed from these sources. Their missing intervals
therefore remain the entire required domain; snapshot age alone cannot compute
a valid small catch-up distance. This finding is limited to mounted/recoverable
local evidence, not a claim about unavailable off-host contents.

## B. Root cause

The existing path already uses **indexed factory `PoolGraduated` logs**. It does
not fetch full state for every historical block. The inefficiency is executing
the live discovery turn across an estimated 5,985,970-block backlog: four
ten-block log queries, repeated latest/canonical boundary checks, forty blocks
per turn, and separately paced physical transports. The historical target is
fixed work, but the live path repeatedly pays for a moving latest header.

Approximately 149,650 turns produce 1.05 million logical elements and 299,300
physical attempts in the old empty-census model. With 0.5-second pacing and
roughly 9.897 new blocks/second, the earlier 23.7–55.2-hour figures describe
planning catch-up cases, not a measured complete bootstrap. Event witnesses,
candidate histories, retries and competing work are additional. Raising rates
or ordinary ten/forty-block bounds does not solve this correctly.

Existing native history/cursors already survive ordinary restarts. The new path
adds proof of interval coverage and replay, explicit readiness, and tail-only
reorganization invalidation instead of treating a cursor as a historical seed
or invalidating the whole discovery domain after an ordinary frontier fork.

## C. Alternatives and choice

| Approach | Evidence / cost | Decision |
|---|---|---|
| Verified snapshot/cache reuse | No complete seed or authenticated census interval found | Reuse original immutable facts through the existing cache; never manufacture range coverage |
| Existing forty-block live turns | Tested ten-block requests; high repeated physical overhead | Preserve as the unprepared runtime path |
| Separate indexed historical preparation, ten-block requests | Offline exact-output tests; four log slices and two boundary reads in one existing batch against a frozen head | Implemented safe default |
| Wider historical ranges | Official Robinhood documentation lists ten blocks for Free and wider support for paid tiers; actual account capability remains unverified | No automatic widening; one bounded forty-block comparison is prepared |
| Adaptive subdivision | Offline range-size/response saturation failures, durable gaps and restart tests | Implemented; a saturated single block remains incomplete |
| Prospective seven-day accumulation | Same independently complete census, spread over enrollment; avoids a competing cold catch-up burst | Recommended if ten-block restriction holds or Stage B is unaffordable |

The [official Robinhood `eth_getLogs` documentation](https://www.alchemy.com/docs/chains/robinhood-chain/robinhood-chain-api-endpoints/eth-get-logs)
is a method contract and tier description, not verification of this account or a
larger-range completeness result. No indexed-data subscription, undocumented
pagination method, new infrastructure, paid upgrade or alternative provider was
introduced. Native `eth_getLogs` has no page cursor: page envelopes fail closed.
The existing 2 MB client response ceiling remains, even where a vendor documents
a larger server ceiling.

Prospective enrollment remains incomplete until the seven-day cutoff moves
**strictly past** the enrollment timestamp. The strategy's inclusive seven-day
ceiling must first exclude any unacquired events in the enrollment header.
Missing early opportunities during warmup are a real cost; no historical winners
are selected and no incomplete population is called ready.

## D. Implementation and integration

[pons_historical.py](../../meme_machine/lanes/pons/pons_historical.py) adds range,
event, missing-range and candidate-membership tables **inside the original
PonsHistory database**. It takes the existing canonical governed RPC factory;
there is no new endpoint or history service. Chain ID 4663, genesis hash, frozen
Survivor policy, provider fingerprint and verified factory/deployer/hook/manager
code identities are persisted. Range evidence includes canonical boundaries,
query filters, original event identities/order and exact event-set digests.

Stage A freezes a canonical head, durably locates the exact cutoff using adjacent
timestamp boundaries, then enumerates **all** `TokenLaunched` and `PoolGraduated`
events at the verified V2 factory. It uses neither Current retention nor existing
Survivor rows as its census. Event-block canonical headers and receipt membership
authenticate nonempty responses. Empty intervals require complete response arrays
and canonical range evidence; an empty response alone cannot publish coverage.
As with the existing authority, completeness relies on the trusted canonical
provider's documented complete-array contract, not a new cryptographic proof of
all empty intermediate blocks.

Stage B reuses native factory records, compiled curve authentication,
graduation/registration/initialization lineage, PoolKey identities, the existing
V4 decoder and `Runtime._append_tape`. Launches predating the seven-day graduation
domain are located from authenticated `launchedAt()` and a bounded canonical
timestamp census. Already authenticated lineage is persisted across that search.
Only proven non-native quote or horizon expiration can avoid economic hydration;
their supporting evidence is retained. Provider/evidence failures do not become
economic rejections.

The frozen reducer needs the original graduation price anchor, the retained
24-hour price path, reset/2h/6h measurements, recent flow/buyer evidence and fresh
state/execution quotes. The preparation path acquires pool activity from the
graduation onward and uses existing point/flow compaction rather than inventing
a cheaper retrospective eligibility rule. Swap events produce identical native
vectors; ModifyLiquidity/Donate/ProtocolFeeUpdated events are also journaled as
authenticated lifecycle evidence. Qualification still obtains its original fresh
native state/quotes. Cohorts share transport across the existing 64-market bound;
this is a work bound, not a population cap. Once acquired, cohorts are frozen so
new enrollment does not refetch earlier pool ranges.

`pons_survivor_runtime.py` exposes an explicit preparation turn and recognizes a
prepared database on restart. Unprepared ordinary behavior keeps its original
ten/forty limits. The runtime adapter also keeps these limits; wider historical
queries require a separately driven preparation with matching comparison evidence.
Survivor qualification/funding waits for verified census **and** required retained
histories. Current source, policy, deadlines and readiness authority are unchanged.
Native position work runs first; incomplete historical readiness cannot suppress
maintenance of funded positions. Existing global admission remains authoritative.

`provider.py` only adds payload byte telemetry and recognizes an explicit HTTP
400 block-range error in batch responses for safe subdivision. Its session,
batch, pacing, retry, shared-fairness and response bounds are unchanged.
`engineering/pons_history/` contains individual-source auditing, deterministic
fixtures, local measurements and the finite capability comparison. New regression
tests are enrolled in FAST. See [VALIDATION.md](VALIDATION.md).

## E. Warm-start sequence

1. Restore the individually verified native history database and required WAL
   using existing recovery ownership; preserve the original economic book/epoch.
2. Run database integrity, checksums, price/event replay and range/event-set
   coverage replay. A `complete` flag or final cursor cannot replace missing
   prefix ranges or candidate acquisition coverage.
3. Verify original chain/genesis/provider/policy and canonical domain anchor,
   every acquisition frontier, frozen head and every retained candidate checkpoint,
   including qualified/unfunded and held candidates.
4. On a shallow fork, binary-search the last canonical range checkpoint,
   invalidate the affected suffix, preserve prior nominees/controllers and
   reacquire missing material. Native candidate recovery preserves generations,
   positions and original deadlines. Orphan graduations remain incomplete until
   their authenticated replacement is established.
5. Extend to a verified new head and acquire only the uncovered tail. The previous
   checkpoint is checked as bounded overlap; proved numeric ranges are not scanned
   again during an ordinary restart. Resume interrupted subdivision/gap records.
6. Reconcile every graduation disposition and required retained history before
   Survivor readiness. Current prerequisites and the provider blocker still apply.
7. Continue rolling acquisition. Bounded maintenance retains the seven-day domain
   plus a full day of acquisition recovery overlap; held positions are protected
   longer. New acquisition records retire only after both strategy and recovery
   floors expire. Existing economic/learning archives keep their original owners.

The new range/event/identity journals have bounded maintenance, including a
rotating scan so protected old rows do not starve retirement. Original native
controller journals are not deleted. A changed original domain anchor, changed
chain/provider/policy, corrupt replay or changed frozen-head cutoff fails closed
and needs a reviewed canonical boundary reconciliation; it does not silently
restart or certify a different seven-day domain. Restoration CPU/storage scale
with retained evidence and are not proven at real seven-day populated size.

## F. Completeness and independence

Canonical event identity is block hash + transaction hash + native log index;
ordering is block/transaction/log index. Exact overlaps deduplicate, conflicts
fail, and receipt/header/contract/pool relationships are checked. Native append,
event insertion, graduation intake, range checkpoint and progress publication
commit atomically. Pre-dispatch gaps survive interruption; transient failures
retry only the unproved range. No candidate deadline is reset.

All eligible identities remain retained without a count cap. Current rejection,
exit or funding denial cannot determine later Survivor enrollment: the factory
census is independent. Existing quiet reactivation/startup nomination repairs,
qualified/unfunded distinction and economic rejection reasons survive. Historical
requests have priority 50 under the unchanged shared governor, below position
priority 0 and deadline-critical Current work. There is one preparation worker
and sequential physical admission; no extra provider connection is opened.

There is **no authentic complete seven-day equivalence result**. The retained
short captures lack the necessary census and economic tapes. Synthetic headers,
launches, receipts, swaps and added candidates are clearly labeled in fixtures;
they never count as a seed. Complete-input offline parity establishes algorithmic
behavior, not actual candidate recall or provider completeness on a live domain.

## G. Efficiency

[EFFICIENCY.md](EFFICIENCY.md), [MEASUREMENTS.json](MEASUREMENTS.json) and
[PROJECTIONS.json](PROJECTIONS.json) separate measured local CPU/RAM/SQLite work,
generated transport counts and projected live costs. The ten-block empty census
reduces logical work about 14.3% and physical batches 50%, with additional durable
coverage writes. Conditional forty-block results are not verified live support.
Dense economic reconstruction does not show a material request saving; complete
receipts/senders/price paths remain necessary and added lifecycle checks cost work.
Actual physical provider bytes, billed CU, dollars and complete-population duration
remain unmeasured. Diagnostic CU is 100 per dispatched Robinhood RPC element.
Public RPC would count too; none was called here.

## H. Validation

The final test receipts and exact commands are in [VALIDATION.md](VALIDATION.md).
Deterministic cases cover old/new exact population/lineage/order/hash/timestamp,
native evidence vectors and economic rejection parity, shared reconstruction,
restart, missing ranges/headers, paging failures, saturation/subdivision, duplicates,
atomic interruption, frontier forks, controller/deadline preservation, inclusive
expiration and prospective enrollment boundaries, position precedence and shared
priority. Existing Pons/provider/recovery tests provide broader independent coverage.
The documented historical source-freeze failure was reproduced on the exact
untouched starting commit; its assertion and frozen source were preserved.

## I. Smallest next action

Read [NEXT_ACTION.md](NEXT_ACTION.md). The prepared next step is a **separately
authorized** nonempty forty-block log comparison: 45 seconds, at most 64 logical
elements, 32 physical attempts, 6,400 diagnostic CU and 128 MiB disposable stock.
It tests range capability only; it cannot clear the provider blocker or seed Pons.
It has not been executed. No 900-second/10-GiB/60,000-element test is requested.

If widening is unavailable, begin prospective history only under separately
authorized operational/provider work, or review a finite phased acquisition
campaign with the explicit census cost and a density-measured economic envelope.
The smallest useful combined Pump/Pons proof can be sized only after a real seed,
reviewed bounded executor and fresh authorization exist. All original concurrent
economic, native-maintenance, queue-drainage and physical-capacity requirements
remain; a smaller census does not certify them.

## J. Publication and preservation

Dedicated branch: `engineering/pons-historical-bootstrap-20261008`, starting from
`703d8764a775d9680e3b48baf2c96f3fb7cf8eb6`, tree
`6e8706668791410763d287417d0722147d4dc1b5`. Isolated worktree:
`/mnt/volume_nyc1_1790918115030/pons-historical-bootstrap-20261008`.
Disposable copies, test databases and traces stay on the attached volume at
`/mnt/volume_nyc1_1790918115030/pons-historical-bootstrap-evidence-20261008`.

[PRESERVATION.json](PRESERVATION.json) records source checksums, frozen contracts,
the unchanged blocker and unchanged remote heads, including the storage-retention
maintenance branch. [PUBLICATION.json](PUBLICATION.json) records the accepted
source and implementation publication. The final Git commit and tree are also
reported in the owner handoff. Original $500 inception, compounding, fixed aggregate
risk, all nine approved changes, shared capital, Model B, Pump/PumpSwap,
Meteora/Ramses pauses and preservation work were not reopened.
