# Fresh experiment ledger

PAPER ONLY. No production or canonical workflow bytes/modes changed.
Runtime reference: dc08f9064cf5e37b63f383f52aa709d0afc1723f.
**ASTRA_REVIEW_READY: HISTORICAL_MECHANISM_REPRODUCED**
Two of SIX material variants consumed. All workload execution stopped; four
slots, including M3, remain unused. Further execution requires Astra's decision.
Budget ceiling: SIX material variants. Deterministic checks and artifact inspection
are separately recorded in PREFLIGHT_EVIDENCE.json, not causal workload variants.

| ID | Hypothesis | Variable | Frames/time | Key results | Interpretation |
| --- | --- | --- | --- | --- | --- |
| M1 | Fresh coupled archive recovery baseline | None: repository-derived canonical local load | Fatal choose at 884 / 238.68 source s; final drain 886 / 239.22 source s; 242.707 wall s | maintenance_decision_in_flight; previous selected retirement interrupted; archive/retirement both ready and feasible; archive recovery ~94.77 s left; native source 75.895 s + injected owner wait 71.205 s; diagnostic measured overhead .1174%; integrity ok | Separate native cooperative-completion blocker truncates capacity evidence. Does not reproduce historical recovery refusal. |
| M2 | Capacity can be observed beyond the fresh urgent-interruption blocker | Urgent ACK load disabled, including 1 s periodic ACK and 10 s candidate ACK; candidate data reads retained | Fatal 1,207 /325.89 source s; final 1,209 /326.43; 330.736 wall s | Recovery headroom 96 ->65 ->35 ->5.67 s; Meteora excess 6,552; archive not ready, retirement ready, feasible []; maintenance_cannot_reserve_both_sides; measured overhead .2879% | HISTORICAL_MECHANISM_REPRODUCED. Diagnostic reduced-control workload; not a candidate configuration. |
| M3 | Source/shared-owner occupancy removes recovery capacity | Predeclared same M2 workload, only source owner floor .165 -> 0 | UNEXECUTED; hard stop | M1 injected source wait was 71.205 s, 29.3% of total runtime | Matched discriminator; native source processing/mutators remain intact. |
| M4..6 | Conditional | Declare from fresh results only | UNEXECUTED; hard stop | No blind retry or parameter fishing | Stop earlier if evidence suffices. |

## M1 quantitative limits

The cold source occupies about 61% of the owner wall budget under the declared
profile. First mature 30-second interval (180.188 ->210.200 wall seconds):
28,776 total records archived, aggregate eligible hot debt 528 ->1,056.
The 8-second pause/catch-up has begun by the terminal window: at 240.259 wall
seconds /877 frames, aggregate eligible debt is 6,688; Meteora debt 3,152 and
archived-pending 1,840, oldest hot ~186.61 s, oldest retained ~190.61 s.
Its last five-second Meteora interval infers 2,432 eligibility arrivals and
2,480 archive drain (net -48). This short post-burst interval is insufficient
to prove sustained recovery headroom collapse or identify a capacity repair.

M1 worker archive dispatch-to-start total .630865 s/82 calls (peak .113429 s).
Native archive work 9.183394 s plus explicitly injected wait 10.417886 s.
Source stage, outer transactions, owner service and worker times overlap;
do not add them as independent occupancy. Periodic observer total .080833 s,
serialization .007310 s, persistence .035235 s, measured numeric-wrapper
bookkeeping .161531 s. Entry/return trampolines are not fully captured.

The native turn at frame 883 selected retirement, returned OperationalError:
interrupted, and recorded no completion ledger result. The next choose at frame
884 raised maintenance_decision_in_flight despite a nonempty feasible set.
Source inspection identifies the relevant path: MaintenanceRuntime.turn's
_native_progress() can be interrupted before arbiter.complete() inside the
operation's finally block. Cooperative failure preserves arbiter admission,
but the prior pending decision can remain. This is fresh evidence supporting
that separate mechanism, not a production fix and not the historical cause.

Full raw M1 evidence is bound in M1_ARTIFACT.json and the immutable Actions artifact.
M1_SUMMARY.json, M1_CAPACITY_EXCERPTS.json and M1_TERMINAL_EXCERPTS.json are literal
compact evidence extracted from its logs, not substitute qualification evidence.

## M2 gate

M2 retained all source/profile/native machinery and disabled urgent ACK load
only. The three mature 30-second intervals have archive drain below inferred
eligibility arrivals, debt persists above the 1,000-record envelope, and the
latched recovery deadline becomes binding. At native fatal frame 1,207,
5.672391 seconds remain; a .184300-second unfinished archive flight makes
archive unready. Retirement's own 3-second reservation fits, but preserving
archive finishes at +9 seconds and misses recovery by 3.327609 seconds.
This is the whole historical chain, not a same-exception classification.

Component attribution remains uncertain. Source/native+injected owner work is
62.16% of total wall time, archive preparation has spare raw service capacity,
and single-flight native receipt/preparation admissions serialize behind owner
work. These support the next investigation scope but do not prove a minimum
patch. No M3 or other workload was executed after the first valid gate.
See ASTRA_REVIEW_PACKAGE.md and M2_ARTIFACT.json for evidence and exact limits.
