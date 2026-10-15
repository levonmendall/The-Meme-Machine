# Bounded canonical-write and Pons workload correction

Executable `f72a17409cc52c0c649c3fd8d1d95ad30e68e45f`, branch
`repair/consolidated-startup-followup-20261014`, draft PR133. Root remains the
single integration/test/runtime owner. This supersedes the affected branch's
STOP at77171d65 with newly measured source-level evidence; original run results
and rejected/incomplete measurements remain unchanged. Standing issue134 applies.

## Causal change and exact boundaries

O8 measured serial preparation97.832s + owner waiting168.706s + callback137.165s
over404.665s. `SelectiveHistory.ingest` economic_store was the largest exclusive
candidate phase:76.300wall/21.147threadCPU/33.036runnable-wait seconds. This is
shared scheduling plus necessary database work, not a demonstrated SQLite lock.

`RollingHistory.store_many` consolidates repeated fresh-record lookup, transaction
attestation, cursor and counter work inside the existing owner's transaction.
It accepts only bounded unique prepared native records. Indexed checks against
current rolling, canonical and receipt state remain on the owner. Existing,
archived, receipt-only, replayed, null-index or unsupported records select the
unchanged scalar path before writes. Order/index/hash conflicts still fail.
Body/hash, original availability, address/lineage/receipt, insertion ordering,
per-record clock order and last-sampled cursor time are preserved. No new writer,
transaction boundary, cache, ACK, coverage relaxation or durability change.
Four fixed phase counters disclose actual bulk/scalar execution; they are not
committed-economic counters and can precede a later transaction rollback.

Pons audit retention now uses three narrow seq covering indexes with unchanged
4096-record retention, append guards, durable initiation/completion accounting,
admission, priority, routing and deadlines. Survivor's final report reuses one
fresh history read after mutations; earlier decision/protection reads remain
independently fresh. Exact reversible source guards cover only that report block.
All active six opportunity-access changes, nine economics and volume quality stay
unchanged. Backup errors additionally retain bounded numeric admission facts.

## Authentic bounded offline evidence

Private evidence root: the existing sibling `blocker-repair-20261011` (E).
The small evidence index records exact artifact hashes; no database copy or
historical reconstruction was needed. Network access was blocked in tests.

* Unique canonical cohort:3023 authentic retained events/2930 transaction keys/
  64slots. Each disposable variant inserts each identity once. Exact economic,
  receipt, availability, address, lineage, rowid, cursor and counters agree.
  Plain store-transaction CPU0.555194→0.339636s, wall0.643174→0.500915s.
  Separately instrumented SQL API calls36404→896; logical steps36404→18685.
  Both retain64commits; no commit/fsync savings claimed. Scratch containment,
  decoding/preparation, owner contention and strategy work are outside this timer.
* Provider audit pair:32 mocked physical starts/128 logical elements at installed
  10RPS fake-clock profile with saturated4096-row rings. Isolated caller CPU
  0.450227→0.270086s, wall0.730791→0.519255s; logical reads412.365→15.340MB,
  writes10.932→12.276MB. Accounting/retention/append guards agree. No requests
  were dispatched. The earlier mixed-loop result included expensive scratch and
  oracle work; it remains preserved and is not an isolated-accounting CPU proof.
* Two authentic active Pons candidates:final report4reads→1, decoded bytes
  153296→38324, CPU0.005404→0.001499s. Tiny population, no held references;
  this alone cannot explain O8's97.829s Survivor CPU.

These are operation-scoped comparisons, not faithful market replay, whole-machine
throughput, statistical confidence, provider invoices or additive percentages.
The executed provider driver is separately retained; the committed version adds
a disposable-only DROP IF EXISTS guard so future baselines are not both indexed.

## Validation and failures retained

Pinned CPython3.12.14/SQLite3.45.1, supported contained runner, real2vCPU host.
32 backup/storage tests PASS;5 Pons reporting tests PASS; initial31 canonical
tests had30PASS/1FAIL because the cancellation fixture intercepted only scalar
store. Updated actual-bulk cancellation seam:8 affected tests PASS. Initial166
integration cases had165PASS/1ERROR:root Git status refreshed the installed index
to root-only. Exact index metadata repaired with unchanged content hash; actual
service-user source/output regression then PASS. Use no-optional-locks status.

Final171 startup/delivery/protection integration cases PASS102.410s, including
actual disposable supervisor/children, cancellation, interrupted consumers,
exact restart ACKs, history corruption/rollback and protective-capacity fixtures.
Exact source/economic guards passed. Overlapping module counts are not summed as
distinct tests. No uninterrupted166PASS or general release PASS is claimed.
No full FAST dispatched; final FAST/applicable OPERATIONAL remain promotion gates.

## Architecture decision and live verification

O8 required about2.169x durable progress merely to match that window's4.6038
arrivals versus2.1227 durable slot units/s, before burst/backlog recovery.
The859-frame serial budget would need about186.6s instead of403.7s. Local savings
cannot establish that result. Existing preparation is already off-owner; even
ideal removal of its97.832s alone is insufficient at other costs held fixed.
Pipelining one preparation with one ordered commit remains a measured-follow-up
option, requiring shared bounded credits, generation/order and cancellation
contracts. It is deferred until this coherent candidate is measured. Blind owner
priority changes could starve maintenance; extra writers/workers are not used.
CPU scaling is not linear evidence:current hardware sufficiency remains unproven.

The next exact-source specification is
`CANONICAL_BATCH_NEXT_OBSERVATION_20261015.json`. It uses fresh preflight,
service-identity access, the existing one-start controller and original bounds.
It asks whether bulk hits reduce owner occupancy/wait and improve current-run
commit/history/ACK/publication progress with concurrent managed Pons. It is not
a controlled comparison with O8 or a normal PAPER/held-protection PASS.

## Separate recovery/storage and release blockers

Fresh24-check/459-query read-only preflight verifies head10311/$1000/zero eight
obligation categories, historical500, allfourv1, retained receipts/ACKs/pending
work, ownership and applicable older recovery reference. Historical
RECOVERY_REQUIRED remains. Future native drain must be independently checked.

Scheduled04:01:56 backup failed destination copy reserve, not the optional2GiB
copy quota. Current known main-file lower bound leaves at least3.751GiB short of
a complete copy plus5GiB reserve; historical exact free/estimate was not recorded.
No evidence deletion, bulk copy, purchase or timer change occurred. Failed points
are unusable. Whole-process freezing during backup remains incompatible with
uninterrupted3s protection; coordinated snapshot/barrier isolation needs a separate
verified solution before autonomy. BUSY, Pons READONLY, replay-window semantics,
managed-provider suitability, held quote/USD and sustained capacity stay open.

Rollback restores saved source66f85d61 and unit/environment only after stop,
native/financial/pending-state review and compatibility checks. Never rewind
databases, policy history, provider accounting or new canonical work. Diagnosis
stays funding closed, unit disabled/Restart=no; no diagnostic minute counts toward
acceptance and no automatic promotion follows its completion.
