# Stopped native read ports — dormant draft

Base: `780f4015efd9fba528e97223f8e8e3b1a7322e12`, tree
`7646978bbfb2076aea90625c3c4a32cd4556491c`.

This separate application component makes existing native reducers usable on
already authenticated, stopped read snapshots. It is not selected, approved or
installed on AWS. It does not change a broker action, privileged worker bundle,
policy selector, strategy, native journal or historical completion flag.

## Acquisition boundary

Only the protected original caller may construct `StoppedNativeReadContext`.
It must authenticate the exact application source, complete physical census,
original path-to-inode mapping and all original stopped/exclusive financial and
native ownership fences. Every supplied connection must already be in a
query-only read transaction. The local `validate_snapshot` callable must check
those same premises at entry and exit. It is not a serialized assertion or a
native/provider-supplied boolean. Existing all-nine native financial checks remain
required; this component covers the four active regimes and does not replace
paused-book validation.

Original absolute locators remain closed-map keys even when a future retained
snapshot resolver supplies an authenticated physical copy. The component does
not resolve or reopen host paths, copy an epoch, construct books, install schema,
repair callbacks, settle money, acquire provider data or change the environment.
Cold artifacts are existing read-only CLOEXEC regular descriptors with one link,
fixed identity metadata and original manifest SHA256. The existing narrow
restored-cohort alias remains the only fallback; another epoch or unmapped
locator supplies no authority. Source/frame FULL delivery and ACK semantics are
unchanged.

The context belongs to exactly one PID/TID and a finite monotonic deadline. It
bounds complete fixed table populations, including scalar/duplicate columns,
before decoding: 100,000 rows per table, 4 MiB per field and 128 MiB aggregate
encoded inputs, including unique cold artifacts. Each artifact is at most
32 MiB. Canonical source content is length-checked before fetch/decode, and the
original decoder's own inflated limits remain. These explicit bounds can make a
larger legitimate population UNKNOWN; they are not a demonstrated fit for the
retained AWS population. A failed scope must be discarded. The caller retains
and closes all connections, descriptors and fences. `close()` restores borrowed
row factories and refuses reuse, including on a failed exit fence.

## Interfaces and verified work

`native_restore_context.py` supplies constructor-free real paper, sleeve,
Survivor history, Pons Store/Plane/capital and CandidateHistory views. Its financial
reader uses original full cold shared-capital replay and legacy portfolio replay,
selected epoch/inception/policy joins, conservation and global pending/exposure
checks. It does not use process replay-cache or projection-only shortcuts.

Explicit `read_context=` hooks reuse original Pump restoration, terminal-attempt
fold and release ACK predicates; Pons cohort recovery, all-capital pending
recovery scan, native trial replay, controller/group restoration and reentry
ACK predicates; and canonical hot/cold reference decoding. Default production
constructors and writer paths remain in place. The native Pump terminal fold is
shared; its explicit derivation branch never checkpoints a proof. The Pons Broker
shares a pure retained-snapshot reader with original renewal. Its pure predicate
reports repair-needed rather than running renewal/audit SQL under query-only.

`inspect_stopped_restore_memory(context)` exposes only counts of the four regime
names, a digest and fixed role/limitation metadata after the completed reducer
ports and native/sleeve/global joins pass. Actual retained controller/reentry/rally
memory is inspected in both directions, not just every checkpoint qualifier.
Original completed retirement representations are retained; deleted historical
per-life details are not invented. Interrupted retirement or unavailable
compacted cancellation evidence stays unavailable. Never-filled cancellations
use their original release-delivery ACK and actual native terminal event hash;
they do not require a fabricated global SETTLED position.

The projection always reports false for full input closure, current native
resumability, current economic authority, qualification, funding, boot, normal
operation and historical-handler disposition. It exports no raw bodies, native
IDs, paths, source receipts or financial state. Exceptions are private API errors;
a future public controller must use its fixed sanitized failure projection.

`validate_stopped_restore_closure(context)` deliberately raises
`native_restore_discovery_semantics_unimplemented`. There is no positive full
closure producer in this draft. Half-implemented discovery code was removed.

## Dependency roles

Financial replay and exact terminal/controller/reentry/cycle memory are current
financial or decision-critical inputs. Public scout/watch nominations, scheduling
cursors/gaps and debug-ring/Pipeline reporting are original startup-repair inputs.
They are not invented prerequisites before every hard funding-closed boot.
Original actors may repair/reacquire them while allocation remains closed.

Complete source-routed discovery/watch generations, scout/graduation joins,
qualification audit/Pipeline membership and frozen/local wallet qualification
documents remain explicitly unimplemented here. Pump restore merges retained
creator memory into a memory-only container; an invented empty wallet cohort is
not substituted for original frozen qualification inputs. Fresh canonical
membership, native USD, quotes and same-generation position protection must be
proved by the actual running actors before existing admission can grant funding.
The original unknown historical handler obligations and false completion state
are preserved independently. None of these ports is a live sizing prerequisite.

## Focused validation and failure preservation

The original network-blocked engineering driver exercises genuine disposable
financial/native transactions. New tests cover original cold financial replay,
query-only/owner/deadline/field bounds, exit-fence failure, fresh next scope,
empty and terminal books for all four regimes, native/global cancellation and
settlement receipts, Pons filled controller groups/reentry, both Survivor rally
memories, full owner-scope restart equality, missing trials/controller receipts,
orphan points and changed groups. Real native source FULL/ACK hot/cold fixtures
use borrowed databases and held archive descriptors with fallback opens/path
reads trapped. Public projection tests assert every authority/closure flag false.

Receipts under `/workspace/recovery-evidence/`:

- `stopped-native-read-ports-25-final-focused.log`: final new component cases.
- `stopped-native-original-pump-reference-adjacent.log`: 84 existing focused
  Pump/policy/reference cases PASS in 6.355 seconds.
- `stopped-native-original-pons-recovery-adjacent.log`: 40 existing Pons/Pump
  recovery, capital snapshot and candidate-plane cases PASS in 5.050 seconds.
- `stopped-native-four-terminals-first.log` and `...second.log`: original guards
  correctly rejected an incomplete fixture (missing sleeve release, then missing
  real commit fence). Those fixtures were corrected using original operations.
- `stopped-native-four-terminals-third.log`: the cancellation modeling defect
  described above, corrected by reusing the original release ACK predicate.
- `stopped-native-four-terminals-fourth.log`: corrected genuine four-regime
  fixture PASS. All failed engineering scratch scopes remain retained.

No broad release suites, actual retained-state execution, kernel exercise,
provider requests, AWS deployment or readiness acceptance occurred. Exact source
approval and independent review are still required before any integration. The
existing dormant admin PR105 must eventually inline reviewed code within its
original four-worker bundle; this application draft adds no fifth worker or
privileged execution path.

## Narrow review corrections

The correction above original component `1ffb8232` bounds every trial records,
projection, journal-checkpoint and controller-group field before the capital
cross-check fetches any native JSON. It reuses the same fixed prebound population
when creating a Store view. An over-limit dependency remains unavailable rather
than entering the native decoder first; ordinary reconciliation is unchanged.

A retained Pons never-filled cancellation now reuses the original exact native
event/capital/sleeve/global release-ACK verifier. It does not require a global
SETTLED position that this genuine release never created. Missing retired trial
evidence still refuses, and filled settlements retain their original ACK check.
The existing per-event financial replay cancellation hook now checks the local
context owner and deadline; full snapshot/fence checks still bracket the scope.

All 28 focused cases passed in 4.625 seconds under the original offline driver.
The three new cases reproduce the three findings against exact original `1ffb`
runtime bytes (two bound subcases, cancellation refusal and continued replay).
That counterfactual failed as expected; no source branch reset was used and
the corrected bytes were restored in a `finally` block. Logs are
`/workspace/recovery-evidence/stopped-native-read-ports-1ffb-counterfactual.log`
and `stopped-native-read-ports-corrections-focused.log`. An earlier baseline
fixture omitted its stopped-owner proof and contained only one replay event;
its separate failure receipt remains `...counterfactual-fixture-first.log`.
No broad suite, AWS/provider work, boot permission or positive full-closure
producer was added. The correction author is separate from its pending reviewer.
