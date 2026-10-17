# Explicit nonfinancial native component

This candidate is a component for a future contained native bootstrap. It is
not an executable market workload or a complete four-regime bootstrap. It has
no workflow, environment activation, provider access, copied epoch or financial
state migration. Production calls retain their existing defaults.

The previous constructor order creates positive financial genesis before
`native_boundary.attach()`. Therefore returning no portfolio boundary cannot
establish no-allocation containment. This candidate instead rejects an explicit
`native_resources` capability at the start of Pump/Survivor PaperBook,
SelectivePaper, CohortCapital and SleeveReservations construction, before path
creation, database open, genesis, recovery or replay. `attach()` also rejects it.

`IsolatedNativeResources` exclusively creates a new disposable directory. It
rejects an existing directory, symbolic-link ancestry and known financial state
markers in ancestors. This is an additional component check, not a substitute
for OS filesystem isolation. The parent must still enforce the separately
reviewed filesystem, transport, source and resource boundary. The resource
object is passed by construction; no environment switch selects it.

`AuthenticatedSizingFacts` requires a caller-supplied parent authenticator.
There is no default authentication or production receipt producer in this
candidate. It retains immutable detached facts bound to scope, exact source,
epoch reference, portfolio sequence, policies, native units, valuation evidence
and the actual underlying valuation interval. Units are exactly lamports/wei;
native valuation validity is bounded to 120 seconds for Pump and 5 seconds for
Pons' executable USD route, matching the production readers. The authenticated
receipt cannot extend either underlying expiry, and every sizing/denial access
checks freshness. A joint receipt thus needs refresh within the shortest
underlying interval; this component has no parent receipt producer yet.
A checksum alone is not accepted as authentication. The epoch identifier is a
reference, never a copied epoch,
grant or authority. Native qualification receives positive actual sizing facts;
allocation authority is independently absent.

`open_sleeve(..., native_resources=resources)` opens `NativeObservationState`.
It directly reuses the existing directional candidate, rally-cycle and
opportunity methods. Its separate append-only observation journal verifies
hashes and projections when a connection reopens. It has no financial genesis,
position or financial journal tables, reservation methods, financial replay or
reconciliation. Observation journal growth stops at 10,000 events, preserving
the existing evidence. Opportunity and learning tables use existing retention.
The resource registry retains only live sleeve connections; closing a sleeve
unregisters it, including the per-call Pump observation and sizing helpers.
Only the protected-opportunity-asset query is extracted from the production
method; production still queries its actual unsettled sleeve positions. The
nonfinancial adapter has no position state and returns an empty protection set.

The actual Pump Current `_record_attempt()` and `_reserve_position()` accept the
explicit component. With an owned CandidateHistory and no financial book, the
existing real qualification is durably recorded first. The reservation path
then authenticates that committed full-point-in-time decision, exact original
vector and qualification, and records the existing native nonfinancial funding
denial. It returns before lifecycle identity issuance, execution interest,
controller construction, native reservation or portfolio delivery. Pending
and prior-attempt checks are retained. No qualification result is changed.
This component refuses existing accounting, pipeline or fill-context globals;
it cannot accidentally publish through an already-running native resource.

The actual Survivor steps now call extracted native publication methods and a
post-publication allocation gate. Default production calls perform the same
Plane/Attempts, native History, directional observation and opportunity writes.
Explicit resources require owned native stores and no book, verify those
committed qualifications, then preserve the decision and record the denial
before lifecycle identity issuance or `_enter()`. Pons Current checks its actual
committed full result, generation, qualified transition and Attempts receipt
before denying and before `entry_confirmation`, trial index, controller intent
or submission. Its normal capacity/defer behavior is unchanged without resources.

These actual publication/admission branches are exercised with native offline
fixtures and positive authenticated sizing facts. Genuine negative qualifier
results remain rejected without a funding disposition. Shared CandidateHistory,
Survivor History/PonsHistory and Pons Plane are opened through owned resources;
no financial book is created or impersonated. Full isolated constructors/run
explicitly refuse startup before state creation. They still require proper
bookless loop/reporting adapters, injected provider/owner resources and the
protected parent receipt/transport bridge before an isolated native workload
can run. No source delivery, FULL/ACK or market throughput claim follows.
Native store factories reject preexisting files and main/WAL/SHM/journal
symlinks before invoking the original SQLite constructors. The cached shared
CandidateHistory connection has no cross-thread transaction serialization;
parallel bootstrap must provide per-owner connections or serialization before
sharing it among runner threads. Current tests exercise sequential admission.

The scoped offline proof covers 18 component/admission tests plus 115 existing
accounting, portfolio, native Survivor strategy/runtime and Pons worker checks.
It proves
the explicit constructor rejection occurs before SQLite opens, durable
qualification survives funding denial, actual native observation methods
persist and reopen, authenticated facts remain positive and immutable, stale
or unauthenticated facts fail, foreign/uncommitted/unqualified/corrupt decision
evidence fails, and environment configuration cannot redirect explicit
resources. It is not full-market-speed evidence.

Post-reservation fill-time requalification, funded lifecycle behavior, held
position protection, additions, exits, settlement, historical ACKs and
authoritative PAPER readiness are **UNEXERCISED**. The actual native commit
path reserves before fresh executable fill requalification; no fake grant,
positive book or fabricated replay/ACK is supplied to reach that stage.
