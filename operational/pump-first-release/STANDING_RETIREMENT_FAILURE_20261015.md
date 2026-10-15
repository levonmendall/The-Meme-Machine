# Standing diagnostic: scoped-retirement owner hold

Exact executed source `5c72109288dd29fb113f86bc6ba15808884587a9`, specification
publication `a9531205`, one funding-closed run under owner issue134.
**RECOVERY_REQUIRED; original300-second readiness FAIL; acceptance0.**
The attempt stopped after488.107seconds. Every prior failure remains unchanged.

The completed owner record identifies priority4 sequence2429, stage `retention`,
source `solana_selective_source.py:1199`, actual native thread2898194 in source
PID2898192: **53.805663seconds wall /4.155781seconds thread CPU**. During46.640seconds
sampled inside it, the thread accumulated9.630seconds runnable delay; seven
samples were uninterruptible sleep, six in `folio_wait_bit_common`. Storage-page
waiting is directly observed; one SQL statement, a lock holder, GIL contention
or hardware insufficiency is not established. Cached active-stage health was
stale; the completed-operation record supplies the accurate operation identity.

The source's original terminal error is
`maintenance_service_deadline_exhausted`, side retirement,155gaps,2units,
74,000VMsteps, safety/deadline remaining approximately−16seconds. Pump failed
while RECONCILING on `evidence_command_unacknowledged`, not SQLite BUSY.
Pons reconciled at202.740seconds and stopped TERM→exit0 in2.023seconds.
Pump never reconciled. Financial reconciliation is not native drainage.

Before the long hold, a comparable295.911-second startup window measured
CONTROL4.630, joined2.396, stored2.393 and published2.406slotunits/second.
CONTROL-minus-stored grew71→733, stored-minus-published7→3 and stored evidence
age26.09→170.02seconds. This establishes pre-persistence accumulation during
startup, not sustainable capacity or a controlled speedup over another market
window. The group used1.670CPUcores; maximum sampled RSS2.385GB.
The bounded cohort observed815obligations,790authenticated receipts and783exact
ACKs; final32 contained7receipts awaiting exact ACK and25delivery-pending items.
These are sampled obligations, not all economic-event throughput.

Read-only post-review verified the exact358-event tail from retained head8982
to9340, $1,000cash, zero eight-category monetary obligations, historical$500 and
all four active v1 policy bindings. New cohort after shutdown:7exact ACKs,
25pending; previous cohort32all ACKed. Older pending records/witnesses remain.
Owners are dead, leases inactive and writer lock unheld. Source phaseFAILED,
admissionclosed/failed, queue0. Current-state consistency supports guarded
recovery only after the causal defect is corrected; no successful native-drain
or next-start PASS is claimed.

Usage:239,636CU;6,085logical elements (3Solana/6,082Robinhood);1,474physical
starts **including**4native opens. Accounted bytes11,092,105HTTP and269,932,406native;
uncertain byte reservations16,777,216HTTP /285,212,672native are not confirmed
traffic. New native failures0, live reservations/open rows0, new-riskfalse.
Frozen modeled cost **$0.184099133190**; provider invoices unavailable.
No complete held quote/USD protection, provider suitability or SQLite-repair proof.

Saved compatible66f85d61 source and two small overlays restored without database
rewind. PAPER stopped/failed, disabled, Restart=no, fundingclosed. The restored
old diagnostic overlay must never be started unchanged.

Next supported work is a bounded offline retirement-planning repair: reproduce
population-scaled metadata reads, preserve all candidate/shared-owner pins and
canonical precedence, and measure their correction. The53.8-second operation is
proven; individual query contributions and residual sustained-capacity deficit
remain open. Do not repeat unchanged live conditions. Keep original BUSY,
Pons READONLY, replay semantics and backup/protection issues separate.

Private persistent evidence root is the existing `blocker-repair-20261011` sibling:

- `STANDING_OWNER_RETRY_PIPELINE_ANALYSIS_20261015.json`, SHA256
  `57a8a0b056b076aa9fcc305333ef9c443d40614492e7fb601d2372385692e05c`.
- `STANDING_OWNER_RETRY_POST_NATIVE_FINANCIAL_20261015.json`, SHA256
  `50a8d586897fc07ae4e35f4557ff8edad6f90521250c3081c2084b9ba59bee5b`.
- `STANDING_OWNER_RETRY_UNIT_JOURNAL_20261015.jsonl`, full journal records.
- `STANDING_OWNER_RETRY_ROLLBACK_20261015.json`, compatible rollback receipt.
- `/var/lib/meme-machine-diagnostics/20261015-standing-owner-5c721092-022002`,
  result SHA256`de4c28ad8b4f94e3e292e73533b77ed1001bf3d28db468691c144c5d171372e7`;
  original `source-sqlite-terminal.txt` retained.
- `STANDING_OWNER_RETIREMENT_ACCESS_PLAN_20261015.json` and
  `STANDING_OWNER_RETIREMENT_PIN_ACCESS_PLANS_20261015.json`: read-only EXPLAIN,
  not SQL execution timing. The latter shared-owner illustration mismatches
  Pump/PumpSwap scope; disposable tests must use the exact matching record scope.

## Supported subsystem correction under offline validation

A query-only correction removes reproduced unrelated-population work, but cannot
bound candidate-local history reconstruction. Replacing the canonical owner or
storage authority is unnecessary. The chosen affected-subsystem refactor uses
existing hot-length indexes and archival prepare/apply instead:

- At most64metadata inputs in one planning turn; exact indexed equal-length,
  intermediate-length and ceiling ranges, without candidate-history sorts.
- Fixed cycle ceilings and rotating representations; new/restored smaller keys
  are revisited without chasing an indefinitely growing tail.
- Cursors are existing SQLite metadata, advanced only with accepted archive apply;
  source-generation and exact previous-cursor checks reject stale results.
- Full canonical visibility, bound ownership, exact consumed receipt, every
  shared-owner pin and the existing65-owner conservative fence remain required.
- Rich bodies are read only after qualification for archival and byte-credit
  checks. Preparation remains on the existing historian; mutable pin/identity
  checks and durable pointer writes remain on the single owner.
- New live planning/apply reports only its examined page. Optional global-oldest
  and cold-byte-total scans are deferred, explicitly unavailable, not zero.
  No qualification/readiness/protection rule depends on those diagnostics.
- Additive metadata indexes seek exact aliases, pending proofs, acquisition jobs
  and consumer work. Existing CandidateHistory writer installs its index; the
  read-only planning connection never writes schema.
- Existing BUSY deferral value0 is honored by the live archival loop instead of
  being treated as a plan dictionary. No timeout or retry policy changed.

Disposable baseline with4,096unrelated records: shared-owner37,700VMsteps,
pin checks98,300VMsteps. Corrected paths:1,000 and<100steps respectively,
with identical ownership/pin results. These are SQL-work counts, not whole-machine
throughput percentages. Original failed reproduction and invocation evidence is
retained. Full-path market impact remains unestablished until guarded measurement.

The earlier September bounded provider hydration remains distinct from Pump's
current local observed-candidate fold. Source review found no demonstrated
reversion of ModelB: the16.204-second result measured source-consumer release,
not full native manager restoration. The current full local fold was introduced
to recover real creator/graduation/early-holder facts and remains a separate
measured startup cost. Do not discard those facts, rebuild already-separated
history machinery or infer an architectural regression from unlike timings.
