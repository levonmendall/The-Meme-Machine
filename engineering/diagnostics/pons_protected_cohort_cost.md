# Native Pons protection and checkpoint owner costs

This is an offline causal discriminator and compatible repair, not an AWS cost
allocation, market-capacity result, native recovery acknowledgement or PAPER
readiness claim. The retained rehearsal remains failed. No providers,
production files, portfolio epoch or financial books were used or modified.

## Actual observation motivating the discriminator

Protected retained read39084391389 authenticates original app4d255c12 rehearsal
39072867962. Same-identity Current main PID/TID308230 grows107,179,198,634 logical
read bytes/26,545,236 read calls over723.579785 seconds after the first sampled
Pons-restored boundary (samples24–164). Its final161.270725 seconds after the
first sampled Pump-restored boundary still grow24,075,096,678 bytes. These are
observed intervals, not exact startup completion times or economic throughput.
The stopped native candidate database is355,524,608 bytes; its pons_cohort
runtime JSON is4,932,009 bytes. Those widths were missing from earlier small
Plane fixtures. The global financial file is a different namespace.

pons.reporting62,061 calls/77.296394 seconds measures accounting.project only.
It excludes report_to's Plane.maintain. Actual checkpoint invocation counts are
not exported; neither the15-second cadence nor hydrated rows determine them.
Consequently the benchmark cannot allocate a dominant fraction of the107 GB.

## Reproduction and mechanism

The admitted Scratch/network-disabled fixture uses actual Broker/Plane,
Attempts, Pipeline and native reporting/pop/outbox paths:1,696 older-than24h
candidates protected by the native cohort,4,096 observations,4,096 transitions,
5,120 synthetic nonfinancial evidence rows within each original retention bound,
and exactly4,932,009 bytes of synthetic cohort JSON. It retains no Attempts rows,
financial ledger, provider ledger, canonical market authority or production data.
Body distribution and unrelated peer-write cadence are synthetic. The generated
database overshoots the requested geometry by one bounded insertion batch.

Run from the repository with pinned Python3.12.14:

```
python -B -m engineering.diagnostics.pons_protected_cohort_cost /tmp/pons-cost.json --repeat 4
```

The script admits storage through original Scratch, refuses SQLite outside it,
forbids external writes except the named result, and measures thread-local IO
around actual native calls. Peer preparation is outside the measured interval.
Both four-repeat traced and untraced runs are retained. Trace expansion of the
5 MB INSERT adds substantial CPU, so timing comparisons use untraced runs.
The diagnostic before revision did not call the new optional borrowed path or
record runtime hashes; the final script adds those observations without changing
the original fixture/turn/fresh-checkpoint operations.

| Actual native operation | Before logical bytes/call | After logical bytes/call | Before/after wall ms/call |
| --- | ---: | ---: | ---: |
| Unchanged local turn |14,467|14,467|0.397/0.401|
| Local turn after unrelated peer commit |8,888,451|528,515|23.576/2.210|
| maintain after unrelated peer commit |8,835,203|483,459|22.297/1.368|
| Default fresh-owner checkpoint |385,698,690|384,584,580|118.201/143.410|
| Explicit live-owner checkpoint |not available|13,602,595|not available/63.973|

Unrelated-peer turn reads fall94.05%; maintenance reads fall94.53%. Explicit
owner borrowing reads96.47% less than the original fresh-owner path on this
corpus. Default fresh opening still performs its full integrity/schema/recovery
work. No whole-system speedup is inferred. The added schema/index increases
fixture geometry356,257,792→356,347,904 bytes (90,112 bytes); all1,696 protected
identities remain identical, SHA256
6b29788b3cf393c70d73d7c6ca79081ae89c77a02acc9d6db0078a7aeb7571e0.
Checkpoint owner/time/phase metadata and bounded row folding remain native.

Receipts are the adjacent fixtures/pons_protected_cohort_cost_4d_before.json
(SHA256cbcc069088e7dc2fc2cab3c282ef667809d3c04f693cb84a741b75d97f02786e)
and fixtures/pons_protected_cohort_cost_4d_after.json
(SHA2564dbf6197a944f171b11c65574d595933862ee4d7aa60623458602a072b82b320).
Both were executed with Git HEAD4d255c12: before runtime bytes were unchanged;
after runtime bytes were the reviewed uncommitted patch, explicitly hashed in
the receipt. The frozen repair commit retains those exact runtime hashes. This
is not evidence that the patch was deployed. The original baseline diagnostic
script hash isb79a8bf59016f946f98ed019f550f1f0bed46afaa94a8dc3c6979324f6c25931;
the final script/after receipt hash isab211ae6a90cd7c0e8756bdb494de378d427919679d1164faa0a02ed35d308c5.

## Chosen correction and alternatives

Retaining data_version-only invalidation forces reparsing/hydrating retained
protection on unrelated peer commits. Replacing the native registry or relaxing
protection/retention is not justified. The repair retains every native maintenance
transaction and guard, and refactors only the two demonstrated mechanisms:

* Cache compact protection membership/native status behind a singleton SQLite
  revision updated by persistent triggers for every relevant runtime INSERT,
  UPDATE, DELETE, REPLACE and key move. All native_position prefixes, including
  paused namespaces, invalidate; cache and broad skip identity also bind the
  actual active-family predicate. Mutable candidate membership/generation,
  time/age, claim, receipt obligations, evidence, archive and consumption remain
  freshly evaluated under the original write transaction.
* Guard revision reset/deletion/replacement, validate exact fixed schema when its
  version changes, and retain validated schema tokens only across confirmed
  transaction outcomes. Facts publish only after the original transaction exits
  normally; native read-only ROLLBACK is retained. Failed writes/COMMIT, schema
  rollback and changed revisions cannot publish speculative facts.
* Select eligible candidate keys from a genuinely covering retirement index,
  skip protected identities before loading wide payload/results, and retain the
  original unprotected age/claim/consumption/order-floor/deletion checks.
* Let actual Current checkpoint callsites explicitly borrow their true live Plane.
  Validate exact type, process/start identity, creating thread, regular unique
  inode, fixed path, open owner and absence of a nested transaction. Retain
  recover() on every checkpoint. Initial owner/reopen still executes original
  integrity/schema/recovery; missing optional argument preserves fresh opening.

pons.py changes its authentic adapter_source hash. The existing retained
interpretation transition remains the only renewal path: preserve raw nomination,
original observation/order/age and prior decision audit; request fresh canonical
qualification and fence the old in-flight generation. No old hash is forged.

## Scoped validation and remaining bounds

New focused module:19/19 PASS0.225s. It exercises old/raw process writes,
UPDATE/REPLACE/delete/key moves, held/settled and paused protection, exact age and
unconsumed generation, concurrent peer commits, failed COMMIT, rolled-back
revision reuse, rolled-back schema-version reuse, both mode-change cache/skip
paths, corrupt needed history, genuine owner recovery, foreign thread/path/inode,
closed/nested owners, ordinary fresh opening and exact deployed4d adapter
renewal/restart with stale-reply fencing.

Nine adjacent modules:166/167 PASS39.219s. The sole failure is unchanged
PositionAdmissionTests.test_full_candidate_queue_cannot_refuse_an_imminent_position:
provider_clock_identity_unavailable from the unavailable Cloud time namespace.
Its test/provider admission/clock source bytes are unmodified; no guard was
weakened. Failure evidence remains /tmp/mm-engineering-lkgt3b01. Six additional
original Pons cancellation, shutdown-auto-rollback, cohort replay, old-policy,
retired watch and corruption cases PASS0.386s. The new focused module was rerun
after its final two cases were added; no full release suite is claimed.

Earlier new-fixture mistakes were corrected; failed receipts remain
/tmp/mm-engineering-_vm_9le3, /tmp/mm-engineering-yb0i9zud,
/tmp/mm-engineering-ey0rig30 and /tmp/mm-engineering-mlkc39b3. The first baseline
script audit/bytecode failure remains /tmp/mm-engineering-wvxw_75o. Successful
large Scratch fixtures were cleaned by the original owner.

Independent code review checked complete input invalidation, rollback publication,
eligibility and live-owner callsites; its two concrete findings were corrected.
Final integrated source approval, source access, financial/native/provider
preflight and measured AWS benefit remain required before operational use. This
component does not resolve historical unknown callbacks, restore readiness,
measure economic lambda/mu, prove live held-position protection or meet one-hour
acceptance.
