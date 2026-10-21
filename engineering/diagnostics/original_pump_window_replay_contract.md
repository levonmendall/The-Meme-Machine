# Original Pump window: logical compute replay contract

This engineering consumer starts at authenticated normalized canonical-economic
admission, then uses the existing ingestion, CandidateHistory publication and
QualificationReader implementations. It measures neither provider/network/wire
decoding nor the original SQLite file layout. It has no financial, signing,
provider, source-release or privileged-host authority.

## Cohort and lineage

The export-only producer selects source `ec2-39625860455-1`, authenticates its
sealed manifest/file hashes, and verifies the two retained sample boundaries:

| Boundary | Host monotonic | Pump incoming | Pump durably observed |
|---|---:|---:|---:|
| Before | 173209.046747116 | 9 | 0 |
| After | 173329.296718508 | 5090 | 4062 |

Let the corresponding retained `latest_source_sequence` values be `s0` and
`s1`. Verify scoped prefix counts of 9 and 5090. Select exactly 5081 distinct
`program:pump` identities with `s0 < sequence <= s1`, ordered by original
sequence. Global sequence gaps must never be filled using arithmetic. The
first nine identities are a separate prelude. All selected identities are
inputs, including work unpublished in the original terminal state.

The agreed export schema is `ec2-sealed-market-replay-parcel-v1`: a root-owned
`manifest.json` authenticates the exact bytes/rows/SHA256 of
`market-inputs.jsonl`. The consumer requires the manifest SHA256 from the
authenticated export receipt; a self-declared manifest is insufficient. It contains:

* Root lineage: source request/generation/application identities, source seal
  and exported-part hashes, verified boundary counts/sequences and the ordered
  selected-identity digest.
* Event packets: original sequence, canonical identity/scope/slot/first_seen,
  canonical bytes/hash, source/endpoint-hash lineage and any authenticated
  encoded/chunk/cold dependencies. No provider URL, credential, provider-control
  database or financial record is included.
* Typed market context with a proven visibility boundary. Final-only facts are
  lineage or unavailable evidence, never early replay state. The consumer must
  not load final bindings, creations, coverage/checkpoints or ACKs as earlier
  facts. Original gap and incomplete-input facts remain incomplete.

JSONL packet forms are fixed:

* `input`: `role` (`warmup`/`measured`), `sequence`, `identity`, `scope`, `slot`,
  `first_seen`. Reconstruct the measured digest from ordered five-column input
  rows `[sequence,identity,scope,slot,first_seen]`, as the producer does.
* `native_record`: `role` (`warmup`/`measured`/`context`) and `value`. Value
  includes canonical record/metadata/hash, `storage_encoding`, `storage_body`,
  authenticated `hot_chunks`, optional `cold_archive_sha256`,
  `source_lineage` and `historical_commit_visibility_proven=false`.
* `market_context`: fixed `table`/`columns`/`row` (BLOBs are tagged base64),
  `temporal_use=lineage_only_no_early_state_or_ack_import`, and
  `historical_visibility_proven=false`. These rows are not replay state.
* `context_table`: an explicitly unavailable context table.
* `retained_market_facts`: poison/retention facts with no normalized source
  health and no available historical health timeline.
* `original_qualification`: authenticated original observation identity,
  sequence/candidate/slot, body SHA256, fixed stage/native kind/failure class,
  false financial/full-completion flags, and
  `temporal_use=terminal_observation_only_no_fresh_state_import`. Select only
  rows through the retained endpoint `durable_sequence`, and verify its exact
  count4062 and stage histogram against the same retained sample. The ordered
  `[sequence,identity,body_sha256]` digest binds these terminal observations.
  They establish original selected/prelude membership and classifications,
  never replay state or an original per-event decision clock.

In the current parcel all final context is visibility-unproven and stays
lineage-only. In particular, source-receipt `at` and witness `observed_at` are
not historical external-commit clocks. Only the selected/prelude canonical
economic packets are admitted into fresh pipeline state; unknown old health,
coverage, proof or provider inputs must fail through the existing predicates.

Fresh generated outbox sequences and absolute reference/generation hashes can
differ from the original cohort. The report maps original sequence to native
identity and fresh sequence explicitly; no production table is relabeled to
imitate an old cursor. Canonical identities/content/order/first availability
must remain unchanged. Rebound locators are declared, not silently normalized.

## Runs and measurements

Run an independent instrumented reference/optimized cost pair, followed by
reference, optimized, optimized, reference (ABBA) timing passes, each in an
independently empty private store on the same host. Timing passes use batch
stage timers only; SQL, hash/decode and per-event timing probes are disabled,
and validation queries execute after timing. Both versions use the same deterministic
visible-prefix schedule and source batch bounds. Preserve source sequence
order; the replay clock never moves backward when a late event retains an
earlier first_seen. No record/context is exposed before its declared boundary.
This schedule is a controlled compute input, not an invented reconstruction of
unrecorded original publication or live decision timing.

In each run, admit the prelude nine to the canonical source but leave zero
qualification observations. Start timing with nine pending. Then feed the
selected 5081 through actual ingestion/adoption, capture/deliver/ACK and the
chosen QualificationReader seam. Report selected-ID completion separately
from all 5090 pipeline inputs. Never assume the original 4062 observations all
belonged to the selected cohort. Report other-family/context work separately.

Measure input authentication, ingestion, delivery, qualification and restart
wall/CPU time; SQL operation counts for canonical, history, reference-reader
and private qualification databases, including writes/transaction boundaries;
first-lazy-connection trace completeness; and per-stage outcomes. SQL trace
counts alone do not establish SQL execution time. A separate lightweight pass
authenticates/counts the same selected identities without strategy processing;
it is a cost floor, not proof of strategy equivalence or permission to drop events.
Both readers retain the same predicates, PR197 sizing correction and identical
retained or unavailable provider inputs. Only the two predecessor versus
optimized read seams differ; PR197's harness repair is not a reader speedup.
The report retains both original and freshly generated storage-encoding
distributions. Reached TEXT/SEP1 decode arguments and SHA call/input-byte costs
are profiled separately; a hot TEXT fixture cannot establish a decode saving
for every live encoding. Instrumented cost-pair durations are excluded from
timing comparisons. ABBA does not guarantee equivalent operating-system caches.

Compare exact canonical/native identities and content hashes, ordered semantic
history, qualification rows/classifications, cohort membership, durable cursors
and actual reader restart. Test a real external-commit-before-ACK interruption
and preserve the existing idempotent recovery boundary. Fingerprint parcel
inputs before/after. Missing creation, source health, coverage, quote, oracle,
concentration or historical timing remains explicit; equality of unavailable
outcomes is not complete strategy equivalence or PAPER readiness. No production
cache, event dropping, economic-predicate change or simulated-capital mutation
is part of this consumer.

No privileged execution, original-path mounting or original-state permission
change is part of this serialization or consumer.
