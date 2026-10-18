# Retained maintenance admission failure

AWS forensics run **39090315988**, administration
`6b7ebaf91d5cd554021ca461e68b9af5f5b80218`, read the original stopped state for
application `780f4015efd9fba528e97223f8e8e3b1a7322e12`. Administration validation
39090087130 passed 1,114 tests in 162.404 seconds with one existing skip on
CPython 3.12.14 / SQLite 3.45.1. No application deployment or PAPER start followed
from these diagnostic results.

The selected source terminal is 314 bytes, SHA256
`89658949bcb0d866945c1ceff08398ace5391e160beac0151c6be7b92c6fa642`.
It reports `maintenance_service_deadline_exhausted`: retirement units 1,
records 0, gaps 193, pins 0, observation VM steps 72,000. Safety/deadline delta
is -9.316797 seconds; successful-service drought delta is -6.304167 seconds.
The arbiter rejects selection before executing this unit.

The authenticated source-generation ring has 42 stored events, no evictions;
the exported tail contains 24 events with explicit 18-event omission. All three
scope identities are exported. CONTROL previously committed real continuity
work in successive turns: 924, 74, 63, 35, 9, 7 and 2 units. The last positive
turn has event monotonic 206998.406814946 and execution 0.097894881 seconds.
The next recorded turn starts at 207049.702015073: a 51.295200127-second event
gap. Even subtracting the preceding entire reported execution leaves more than
51.19 seconds without another recorded maintenance entry. The failed turn's
queue delay is 2.140337441 seconds and execution 0.056406867 seconds, both
within their original three-second leases. Its recorded failure precedes the
observer's stop at 207052.747801943. The terminal file itself has no timestamp;
this ordering uses the ring and observer clocks, not an invented file timestamp.
The final successful scope census has CONTROL continuity demand 1, floor change
false, and the same 193 gaps. No exact failing scope was recorded in the failed
event itself.

The exact production caller queues priority-four maintenance through ordinary
nonurgent FIFO admission. It rejects commands older than three seconds before
`MaintenanceRuntime.turn`, then resubmits at the queue tail. Those expired
commands do not enter this ring. The intended `OwnerAdmission.rendezvous` /
`source_accepted` handoff is not called by the production source. All priorities
at least two share accepted-sequence FIFO, so changing four to two does not
solve this contract. The ring does not establish the number of discarded
admissions. Ordinary source callbacks during the gap include 4.468- and
4.714-second executions; a command accepted behind an already-running atomic
operation can therefore exceed its lease before its first opportunity.

The architectural correction must obtain an actual bounded owner opportunity
before accepting maintenance, retain truthful submission/acceptance clocks,
and preserve older ordinary work, urgent protection, atomic commits, checkpoint
ownership, cancellation and the existing service/debt deadlines. It must not
renew an accepted command's lease or call a planning cursor successful service.

Separate reproduced defects are not substituted for this incident: native
retention ignores the arbiter's EDF scope order, and protected key pages can
perform no committed work. The SQLite 3.45.1 keyset normalization component
reduces repeated prefix traversal without changing selected rows, proof guards
or the 1000+1 page limit. Those improvements do not themselves establish that
this admission gap is repaired or that market processing keeps pace.

Financial replay after the retained read remains sequence 16,391, $1,000 cash,
zero positions and all nine obligation measures zero; journal/projection and
inception identities are unchanged. Historical unknown handlers remain two.
Normal readiness, sustained combined economic throughput and one-hour PAPER
acceptance remain unproven. A new controlled comparison requires the actual
recovery and current-state safety prerequisites, not altered historical flags.
