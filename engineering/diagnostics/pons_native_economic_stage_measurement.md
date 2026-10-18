# Pons native economic publication observations

This opt-in future component records real native processing stages. It changes
no strategy, funding, readiness, recovery flag, provider filter, request pacing,
SQL statement or transaction boundary. It is not selected by an environment
variable. The deployed EA operational candidate is outside this branch.

`PonsEconomicCohorts(run_identity, endpoint)` binds the actual process and native
provider/interpretation generation. Passing it explicitly to the existing Pons
cohort runner shares the observer with its Current plane and Survivor worker.
Each existing economic path can also be exercised independently with disposable
native state. An observer failure makes measurement unknown and does not reject,
roll back, retry or alter the original economic operation.

| Observed stage | Actual native hook | Scope limit |
| --- | --- | --- |
| Current curve economics | Existing complete canonical window, original receipt/header/ABI decoder, then `CurrentHistory.remember` | Selected curve and original 60-second window |
| Survivor V4 economics | Original `collect_v4_activity`, including receipt/header/ABI/sender checks, then actual `_increment` / `_increment_candidates` and `_append_tape` | The native selected pool range |
| New versus replay row | Original prior-row lookup immediately before native insertion | First insertion in that history, not first global arrival |
| Durable publication | Actual Current Plane COMMIT or Survivor outer History COMMIT | Savepoint release alone is not publication |

Canonical identities contain the original block hash, transaction hash and log
index. Semantic hashes come from the native normalized economics. Native history
event hashes are checked against the corresponding decoded projection before
counting a publication. Public scout variants are excluded. Separate Current and
Survivor publication transactions are not added together as globally unique
economic arrivals. Repeated overlapping native windows are scoped observations,
not independent nonoverlapping market-rate samples.

Survivor metadata follows the original nested transaction. A bounded side frame
merges only after the native savepoint release and publishes only after its
outer COMMIT returns. Inner/outer rollback discards those observations; an
unowned preexisting transaction is unmeasured. Capture or post-COMMIT observer
failure never changes the native return/error precedence. There are no observer
database queries or provider calls. The pending decoder metadata holds at most
eight native ranges and 2,048 event identities in total; a stage has at most
2,048 rows and transaction nesting at most eight frames. Overflow stops only
measurement. The common reducer separately enforces its fixed identity,
obligation, cohort and byte limits.

The first component reports incomplete source closure explicitly. It does not
call Solana `acknowledged`, does not reinterpret Pons receipt-cache release as
economic delivery, and does not infer completion from an empty fanout list.
Current held V4 history, complete configured pool/curve membership and native
generation dispositions remain unexercised here. The common Pons delivery
contract therefore remains `PONS_CONSUMER_COMPLETION_UNESTABLISHED`; full-market
lambda, mu, sustained capacity and readiness remain unknown.

Twenty-one final focused cases passed in 1.289 seconds: seven common reducer cases and
fourteen Pons cases. The Pons cases execute the real CurveBuy decoder and native
Current SQLite history, and the actual Survivor `_increment` path through V4
decoding and native SQLite history. Instrumented versus default Survivor SQL,
provider-method counts and economic facts are exactly equal on the same fixed
synthetic inputs. Fault cases cover real outer/nested COMMIT and rollback,
denied COMMIT, post-COMMIT observer failure, replay, bounds, foreign transaction,
changed native semantics and native reorganization refusal. No financial book,
qualified trade, market provider or authoritative production state is involved.

Receipts:

- `/workspace/recovery-evidence/pons-economic-stage-focused-initial.log`
- `/workspace/recovery-evidence/pons-economic-stage-final-focused.log`
- `/workspace/recovery-evidence/pons-economic-stage-final-common-focused.log`
- `/workspace/recovery-evidence/pons-economic-stage-affected-defaults.log`

## Minimum remaining source and consumer closure

The native Survivor base policy has a **seven-day upper graduation-age bound**,
with its four-hour base floor and original 24-hour, six-hour and two-hour trend
windows. Approved opportunity extensions remain unchanged; a shorter nominal
opportunity window does not remove the seven-day universe. A four-hour
factory census alone cannot establish the eligible pool universe. This is a
measurement requirement, not a new restriction on observational work or a
request to change the strategy.

The normal shared-scout path explicitly says pre-enrollment coverage is
unobserved. Its `market_wide_coverage_required=False` and provisional pool rows
do not prove the universe. `Preparation.readiness` deliberately treats
`forward_only` population coverage separately from incomplete candidates,
pending graduations and historical recall. Its normal readiness boolean is not
a closed economic census.

The smallest valid closure needs the following original native evidence, tied
to one frozen canonical upper head and the same provider/source generation:

1. Complete pinned-factory graduation coverage over the seven-day eligibility
   domain, or an equally complete authenticated retained membership prefix plus
   its contiguous forward delta. Original `Preparation._packet` range witnesses
   and its existing resume/replay traversals can supply this where present. A
   new full history scan or provider request is not part of this instrument.
2. Every graduation through that head has its real authenticated candidate or
   original durable structural/expiry disposition. Pending intake is not a
   disposition. Actual pool/watch registration and native retained held-position
   membership must be reconciled without substituting a row count.
3. Every included curve/pool interval has its original complete canonical filter
   and native economic identity census, with an independent expected count/hash
   to detect a missing measurement hook. Public variant counts cannot supply it.
4. Actual required consumers have their original durable history frontier and
   candidate-generation outcome. Current coalescing, supersession, deadline
   refusal and result consumption must be measured as their real native
   dispositions. `Plane.consume` is an existing per-generation checkpointed
   result acknowledgement; it is not a Solana source FULL/ACK.

Eight existing affected native cases also passed in 2.586 seconds: original
factory/candidate census, shared history restart, atomic-write failure, increment
protection, Current qualification parity, native frontier restart, reorganization
without position mutation and source-generation invalidation.

These inputs can be accumulated by bounded hooks on the native factory-range,
graduation authentication, watch registration, canonical window and generation
commit points, and by reusing already occurring native replay traversals. They
must not be reconstructed from provider request totals or optional diagnostics.
Where the original retained factory prefix is absent, the missing input is the
actual authenticated pre-enrollment factory domain; new in-memory bookkeeping
cannot create it. Native historical acquisition, if needed, is a separate
existing governed operation under the original operational controls. Neither a
constant false flag nor a fabricated positive completes this capability.
