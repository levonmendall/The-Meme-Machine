# Identical authenticated economic cohorts: integration contract

Source review at `ec042023549bfb1d541e9a30c51021b29c9f1cec`, including its
`runtime/market_heads.py`, head design, native source progress and actual native
publication/consumer paths. This is an implementation contract, not an activated
collector or an economic-completeness result. No runtime, SQL schema, provider,
funding, historical-completion or trading behavior was changed. No tests or AWS
requests were performed for this document.

## What can actually be measured

The present `operational/isolated_native_source.py:progress` records received
native shared slot, durably committed control slot and accepted/committed joined
frames. These are useful local populations. They contain no economic arrival
denominator, no independent head and no Pons economic population.

`MarketHeads` adds an authenticated external coordinate with its original
physical response clock. It intentionally supplies no economic count. Solana
finalized and Pons latest/finalized are separate kinds. A Pons latest receipt
cannot become finalized because a report needs that label. Parent and child
monotonic clocks may only be subtracted after establishing their same boot/time
namespace; otherwise preserve both clocks and derive durations within each owner.

Use one explicit population at each stage:

| Population | Identity | Appropriate rate |
| --- | --- | --- |
| Solana unique native economics | Original `FinalizedRecord.identity` within fixed Pump or PumpSwap program scope, with immutable economic hash/native order | Events/sec at canonical FULL; independently known arrivals only after complete closed interval census |
| Native publication demand | Original history-outbox identity, family/candidate/scope and immutable source hash | Obligations/sec at creation and verified consumer FULL/source ACK; fan-out is not unique-event arrival |
| Pump Current retained discovery | Original source outbox sequence plus economic identity, after actual CandidateHistory FULL | Unique Pump events/sec retained; not completed qualification and not all PumpSwap Survivor history |
| Native strategy work | Candidate/generation/interpretation and original work identity | Durable dispositions/sec by regime; separate qualified, refused, deferred, superseded, censored and failed |
| Pons observations | Original nomination identity and exact raw variant hash | Provider nomination/sec; neither authenticated protocol economics nor successful qualification |
| Pons authenticated economics | Original block hash, transaction hash/index, log index and protocol identity, accepted by actual native receipt/header/ABI/range validators | Authenticated economic events/sec, only after complete required scope/universe closure |

Do not add these rates together or divide slot advancement by one of them.
`RollingHistory.store` and `store_many` already increment `ingested_event`, but
that generic retained counter has no head cohort, program/kind distinction,
complete population, or consumer completion identity. It is not the missing
denominator. `CandidateHistory.complete` is work disposition, not a call made
once for every Current economic event. Current intentionally folds/coalesces
inputs; measurement must preserve that algorithm.

## External-head cohorts and arithmetic

After an actual post-restoration marker, take fresh physical head receipts
`h0=(H0,t0)` and `h1=(H1,t1)` from the same chain/provider/network/generation,
with `H1>=H0` and `t1>t0`. Define the economic coordinate cohort `(H0,H1]`.
It closes only when the native complete acquisition/census for the whole
interval and exact selected program/universe has been verified. A zero count
requires the same proof as a nonzero count. A skipped coordinate is not an
economic event or an inferred empty block.

Once closed, `N(h0,h1)` is a retrospective authenticated population, and
`lambda=N/(t1-t0)` is its rate of newly head-visible arrivals. Closure may occur
well after t1. Until closure, publish `arrival_count=null`, `lambda=null`, the
observed lower bound separately, and the actual external coordinate lag. Do
not estimate hidden arrivals from a previous average or a control-slot ratio.

For any exact closed population P and sample times s0/s1, let D(P,s) be the
number of P's original native event identities durably completed at the chosen
stage by s. Then `mu=(D(P,s1)-D(P,s0))/(s1-s0)` and
`backlog(P,s)=N(P)-D(P,s)`. Require matching population/source/interpretation
hashes, nonnegative subset counts, actual native completion evidence and
monotonic observation clocks. Scope the stage explicitly. A source-FULL
completion does not mean every consumer or strategy completed.

Do not sum unique events against publication obligations. For fan-out, use
its own `created_obligations-verified_ACKed_obligations` backlog. Unique-event
consumer completion is known only when every required original obligation for
that event has the genuine native receipt, or a complete original consumer
checkpoint proves the whole corresponding prefix. Per-event graph tracking is
unnecessary if the existing complete prefix/cohort witness establishes this;
otherwise publish the obligation backlog and leave unique consumer completion
unknown. Superseded generations are explicit native dispositions, never silently
successful economic processing. Deadline-censored work remains censored.

Source and consumer completion clocks must be sampled *after* original COMMIT
returns. A timestamp written inside a transaction precedes its FULL/fsync and is
not the physical commit finish. Durable counts may be recovered from SQLite;
after a crash, a missing post-COMMIT observation clock remains unknown. Do not
add a second transaction merely to persist a more convenient finish timestamp.

## Smallest staged implementation

First implement a diagnostic-only reducer and opt-in native hook interfaces,
with no extra provider requests, event spool, payload copies, per-event dedup
table or independent authoritative writer. In-memory records may retain only
bounded frame/page aggregate hashes, coordinates, stage counts and clocks.
Lost/evicted measurement provenance invalidates affected cohorts; it must never
discard native work, move a native cursor or satisfy readiness. Default native
execution remains unchanged when no collector is attached.

The reducer may join verified per-frame/per-page summaries to head cohorts
after H1 is known. Do not guess a future head at event insertion. Replayed
frames/pages compare their exact original population hash and do not count as
new arrivals or successful processing. Conflicting hash, source/session change,
reorg, gap, incomplete epoch or measurement loss produces UNKNOWN. Checkpoints
and source identities are evidence dependencies, not caller-supplied `complete`
booleans. A pure arithmetic helper alone cannot mint these witnesses.

For restart-persistent telemetry, a subsequent reviewed slice can store aggregate
receipts under each existing writer and *inside its existing bounded transaction*.
The receipt's key is the original native frame/page or consumer batch identity,
not a new identity per event. This retains rollback and idempotency and introduces
no additional fsync. It is not necessary to make live, uninterrupted diagnostic
measurement restart-persistent in the first slice; after restart the previous
measurement generation can simply be incomplete. Never wrap a 5000-event
discovery page in a new transaction: CandidateHistory's original 64-item FULL
batch boundaries must remain intact.

### Solana hooks: source owner and original consumer owners

1. **Capture the decoded population without decoding twice.**
   `commit_candidates` already has exact `material` from the validated prepared
   product or native scalar decoder. Compute a fixed summary while that material
   is already in hand: program scope, slot/parent/hash, native session/census hash,
   unique event count and digest in original economic order. Accept only the
   fixed complete rolling Pump/PumpSwap program feeds for market-wide arrivals;
   a per-position scoped replay is never market-wide. Grouped Meteora is outside
   this operational population. Preserve replay/failed-status counts separately.
2. **Observe canonical FULL at its real boundary.**
   `candidate_commits.durable` calls `commit_candidate_batch` on the existing
   owner. The outer transaction has returned before its existing final claimed
   clock. Emit the summary there only after success. A batch rollback emits no
   successful FULL. For a general caller that additionally performs inline
   publication after the batch transaction, place the FULL observation directly
   after that transaction's outer COMMIT and before publication: publication can
   fail after canonical data already committed. A still-open enclosing source
   transaction cannot emit a FULL observation. The actual owner callback still
   observes completion if its
   asyncio waiter was canceled. Do not put this solely after `await self.work`,
   since a canceled waiter can miss an accepted owner's successful commit.
3. **Close the complete source interval.**
   Reuse actual control coverage/linked receipts and original
   `RollingHistory.missing(family,program_scope,H0+1,H1,as_of)` plus exact gap,
   membership and source-generation predicates. Require every produced-frame
   summary in the interval, and authenticated native parent witnesses for absent
   coordinates. `published_program_frontiers` supplies a useful current tail
   hint but validates its linked-child tail; its largest point alone is not
   proof of all earlier cohort membership. Do not replace the full predicate
   with `MAX(slot)` or a new telemetry completeness flag.
4. **Count publication fan-out and real ACK separately.**
   `CandidateLifecycle.emit_raw` knows actual `INSERT OR IGNORE` creation.
   `solana_history_delivery.acknowledge` validates unchanged generation/outbox,
   current binding, actual external receipt content and exact ACK order before
   `acknowledge_rows`. Attribute only its real first consumed transition to its
   original obligation cohort. Inline `flush` and separated delivery must have
   equivalent hooks. An ACK batch needs its original content digest; no extra
   provider read, reconstructed ACK or fabricated consumer-FULL clock is allowed.
5. **Current retained history and Survivor history are independent.**
   `consume_pump_discovery` reads only `program:pump`, not PumpSwap, and persists
   original source rows with `retain_pump_source_history` before returning its
   source sequence. An observer inside that function's existing 64-item FULL
   batches can establish durable Current retention. Its returned retained count
   alone counts supplied rows and cannot establish lifetime uniqueness/replay
   completion. `CandidateHistory.append_event` has native identity dedup.
   For Survivor, observe actual `history.append`/checkpoint and subsequent
   `_ack_history_checkpoint`/`advance_interest` after the native history commit;
   preserve scope/candidate/checkpoint hash and consumed frontier. No amount of
   Current retention substitutes for Survivor completeness.

Native entrypoints should own a single collector per run, pass optional observers
to the source/history objects they already own, and join them with their existing
lifetimes. Measurement events are immutable metadata to the diagnostic reducer,
not callbacks that can grant authority or perform source SQL. Never block
priority-zero protection or add a second source owner to obtain statistics.

### Pons closure: a genuine missing capability, not a counter rename

`MarketScout.read_market` supplies broad topic-OR nominations. `_logs` validates
response shape/filter/range/duplicates, and original headers/cursor detect a
retained boundary reorg; `_retain` uses `event_id + digest(body)`, deliberately
allowing raw variants. `_poll` can commit market discovery while deferring a
pool failure. `read_pools` has separate dynamic pool membership/cursors/gaps.
The scout explicitly confers observation authority only. Even when its transport
is canonical, these rows have not all passed `pons.raw_event` receipt membership,
success status/header/ABI validation or curve/factory protocol authentication.

Consequently, the immediately implementable hook can honestly expose:

- complete *provider nomination-query* page counts/digest and original market
  cursor; its exact filter/provider/source and confirmed boundary, with no
  claim that every matching topic was emitted by an authenticated Pons curve;
- active-pool membership hash and original per-pool cursor/gap distribution;
  pool nomination coverage must not disappear when the market cursor advances;
- `Plane.observe` created/updated/repeated nomination and generation links;
  `Plane.finish` actual committed complete/censored/superseded/deferred/failure
  outcomes, `Plane.consume`/Broker ACK, and native Survivor history separately.

That is not full economic lambda. True Pons economic closure requires an
authenticated complete factory/curve/pool universe for the cohort and genuine
native range/event witness coverage across the required scopes. Existing
`pons_historical.Preparation._packet` and its `_witness` supply a useful contract:
exact provider/network/filter/range, original pre/post canonical boundaries,
receipt/header membership and strict raw-event decode, immutable event digest,
participants, history commit and range/gap checkpoint. Reuse already complete
compatible packets and canonical receipt caches. `raw_event` itself expressly
authenticates one log, not range completeness. Selected Current qualification
receipts cover selected curves and cannot prove the rest of the universe empty.

Extending that native witness contract to any missing broad curve/pool scope is
additional real acquisition/validation work, not pure telemetry. It must stay on
the original governed source/consumer paths with their bounds/backpressure,
reuse paid receipts and preserve strategy nomination/selection behavior. A
separate sampler or mandatory full hydration before Current nomination would
change the workload/latency and is not this minimal hook. Until the required
native scope witnesses exist, full Pons economic lambda and global economic
backlog remain null; report nomination rates and native work dispositions under
their correct names. This identifies the missing capability without weakening
source authentication or claiming partial observation is full-market capacity.

## Harness and trusted-parent ownership

For ordinary native operation, the existing evidence-worker owns the Solana
collector/hooks and the Pons cohort owns its original acquisition/Plane hooks.
The outer supervisor combines immutable summaries; it never queries around
an active owner transaction or constructs another authoritative writer.

For the isolated native source, actual provider transports and `MarketHeads`
belong to the trusted parent. Its authenticated head receipts must reach a fixed
bounded parent report/projection and be joined to child native summaries by the
reviewed run/source/provider binding. Do not instantiate a direct provider head
client in the child, pass credentials through the progress channel, or treat
child-supplied head JSON as a physical receipt. The parent's own collector PID
and the child's source PID are separate identities; bind their shared trial
generation explicitly instead of requiring them to be equal.

Extend the existing five-second progress projection with fixed numeric stage
counts, cohort hashes/completeness states and ages, retaining the old local
queues. Keep pre-restore debt and shutdown drain outside the steady rate window.
The marker requires actual native Current restore, Survivor startup/handoff,
Pons startup coverage and source release of the same run. Merely having an
anonymous command endpoint or threads started is not that marker. The existing
256 KiB progress/output bounds must be budgeted for the exact new schema; never
silently clip samples needed to prove the hour. On measurement loss, preserve
native work and make acceptance evidence unavailable.

## Regression discriminators and promotion decision

Root owns execution scheduling. The implementation should add focused offline
tests before any live activation, including:

- same complete native cohort with different batching/replay/fan-out order gives
  identical unique population and original economic hash; rollback/canceled
  accepted-owner success are distinguished at actual COMMIT completion;
- source FULL before external FULL, crash after external FULL before source ACK,
  duplicate ACK, stale generation and corrupt content preserve exact stage
  counts and original native FULL/ACK behavior;
- real Current discovery 64-item history transactions and Survivor checkpoints,
  including partial final slot, coalescing, deferred/censored disposition and
  restart measurement invalidation; no broad new transaction or fake success;
- empty local queues while independent head advances leaves hidden economic
  backlog UNKNOWN; skipped coordinates, stale/reordered heads, Pons latest reorg,
  incomplete scope/pool membership and one missing native witness refuse closure;
- Pons raw variants/foreign protocol emitters never count as authenticated
  economics, and market cursor success cannot hide pool gaps or missing Survivor
  history. Known complete canonical packet replay remains deterministic;
- bounded retained metadata and output, no payload/credential retention, and
  measured SQL/CPU/owner-tail overhead on the same actual fixture workload.

The next live discriminator is not merely a higher frame rate. It is complete
source- and consumer-stage coverage of consecutive externally anchored economic
cohorts after real restoration, no increasing retained obligation/generation
debt, and no rising unacquired coordinate lag. Headroom must use the observed
economic population and service cost, with provider waiting and CPU-throttling
data; proxy slot rates cannot establish it. An uninterrupted hour additionally
requires current monetary/readiness/protection authority and final release
validation. This contract grants none of those facts.
