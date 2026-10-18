# Maintenance service at a truthful FIFO boundary

This candidate addresses the demonstrated maintenance admission failure. It does
not establish live throughput, authoritative recovery, or PAPER readiness.

## Actual incident and causal contract

The exact780 run39085764934 retained by protected forensics39090315988 showed
positive CONTROL maintenance service at monotonic206998.406814946, followed by
the next recorded native turn at207049.702015073:51.295200127seconds later.
That turn failed `maintenance_service_deadline_exhausted`. Its recorded owner
delay was2.140337441seconds, below the original3second lease. The failure ring
precedes observer stop207052.747802. Signed terminal drought was−6.304167309s.
The42-event retained ring contains real positive continuity work; a theory of
only zero-progress protected pages does not describe this incident.

In the previous producer, the command clock started before full-queue admission.
All priorities>=2 share accepted-sequence FIFO. A callback reaching its owner
after3seconds refused before `runtime.turn`, then its producer rejoined the
FIFO tail. Such callbacks do not appear in the native arbiter ring. Actual
priority4 queue peaks exceeded20seconds. Exact per-incident expired callback
count remains unknown; the source and controlled native counterfactual establish
the possible starvation mechanism without inventing that count.

## One scheduling ticket, one genuinely new command

The ticket carries no native callable, payload, Need, mutation or service credit.
It consumes one existing ordinary queue slot behind older ordinary work. Urgent
priorities0/1 retain strict priority. When the owner actually reaches the marker,
it opens a100ms permit and reserves that same slot against younger ordinary work.
Only after receipt of that permit does the producer construct a native turn and
record its genuine new submission/acceptance clocks and sequence. The reserved
command remains priority4, with the original SQL interruption and retention
yield hooks. Its original3second entry and execution checks remain unchanged.
The accepted command may precede younger normal submissions because it spends
the marker's existing FIFO position; those submissions retain their mutual order.

The last actual native observation provides an absolute scheduling window:
`observation.monotonic + min(2*leases.pair, leases.drought)` (30seconds under
unchanged default leases). An unspent permit retry cannot move this bound.
This bounds the next observation opportunity, not the deadline of a known economic
cohort. It grants no native service: the real turn freshly observes debt and
enforces every earlier residence, recovery, successful-service, worker and
generation deadline before its original mutations. No aggregate record count is
treated as proof of cohort clearance. No additional debt scan is introduced.

The permit is separate from checkpoint handoff: markers advance checkpoint epoch,
and real checkpoint I/O retains its matching-token ownership. Cancellation, stop,
urgent arrival and permit expiry release only unspent scheduling state. Accepted
native futures remain owned and drained. Notification cancellation is atomic at
grant; refusal tolerates only a real concurrent notification cancellation.
If the original real future becomes terminal before its owner's final slot
cleanup, only that exact completed predecessor may be awaited under the same
absolute appointment bound; a foreign/pending/open ticket is never replaced.
The existing owner shutdown and outer service drain boundaries remain unchanged.

## Bounded offline evidence

The native FIFO counterfactual uses identical40 cursor commits over48 simulated
seconds with the actual owner, SQLite, ServiceState and MaintenanceRuntime.
The original path has seven callback expirations before native entry, then the
real drought failure; its progress ledger remains1unit. The reserved path has
eight positive subsequent native services, ledger9units, and no expiry. These
are synthetic scheduling callbacks, not a market-arrival capacity denominator.

The actual `serve` case places five genuine native counter transactions, costing
four simulated seconds, before the first scheduling marker. The real service
constructs its native turn only afterwards and commits real archive work while
preserving the original entry lease. Separate real-native cases verify repeated
cleared/new housekeeping duties over160 simulated seconds, an absolute SQL-free
getter, and an earlier original record-service deadline failing inside an open
observation window without archiving that overdue population.

Independent ownership tests cover actual owner/CV/futures/SQLite, full ordinary
capacity, urgent arrival, checkpoints, pending/open/accepted cancellation,
shutdown, notification cancellation races and the stop-waiter cleanup handoff.
They introduce no executor or provider access. Local SQLite is3.53.1; the
already-preserved keyset access-path3.45.1 CAPI evidence is a separate proof.

Failures and environmental limits remain retained:
`maintenance-reservation-first-integrated.log` includes the original controlled
clock-domain fixture discrepancy and unchanged root-required diagnostic failure;
`maintenance-observation-window-first.log` retains an initially already-overdue
test population. Corrections use the same production clock domain and a valid
initial population, without changing old assertions or economic policies.

## Next comparison and remaining limits

The existing collector admits fixed `maintenance_boundary` request, grant,
acceptance, callback completion, expiry, cancellation, close, urgent invalidation
and wait counters. Fixed `maintenance_admission` counters expose boundary deadline
failures, expired pre-native callbacks, native entry/completion/failure and yields.
Completion counts callback returns, including errors; it is not service credit.
The protected admin projection must admit the same fixed numeric names.

Validation receipts in `/workspace/recovery-evidence/`:

| Receipt | Actual outcome |
| --- | --- |
| `maintenance-reservation-final-native.log` | 135 cases/33.908s, 6 existing archived-model skips |
| `maintenance-reservation-admission-collector-startup-cases.log` | 73 cases/7.487s, 1 existing archived-model skip |
| `maintenance-reservation-real-serve.log` | 6 new native cases/0.611s, no skips |
| `maintenance-permit-independent-final.log` | 16 independent ownership/race cases/0.327s, no skips |

The final completed-predecessor cleanup retry has an additional deterministic
helper regression; its separate receipt must accompany the frozen integration.
The earlier135-case bundle predates only that narrow retry branch; unchanged
native execution, mutation and lease paths retain their recorded evidence.

This appointment cannot preempt an atomic callback, guarantee service under
unbounded urgent work, or expand the original45/3/15second native budgets. An
infeasible queue or older debt still fails closed. The source remains the sole
SQLite owner; acquisition, FULL/ACK, financial, strategy and historical completion
semantics are unchanged. Exact-source integrated validation and an authorized
concurrent AWS comparison are required before any live performance claim.
