# Pons opportunity preservation: frozen no-change selection

Source base: `3de3d376847531ccb90e260cfcc96c37587ccb23`.
Composition base: `d1fc161401869522db9abbf50e3f6073e80a4374`.
Old and selected policy hash:
`19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84`.

**Selection: Policy 0. No strategy revision promoted.** Policies 1 and 2 were
implemented as isolated deterministic research candidates, not runtime entry
interfaces. Their state/hysteresis tests are machinery tests, not evidence of
market benefit. No production strategy path imports the research module. The
original production policy and all overlays remain in force.

## Evidence and denominators

The existing retained replay was run once for initial orientation: all 33 complete
canonical vectors and seven qualifying rows reproduce the frozen implementation.
No provider/network calls. The reusable original fixture, not a rebuilt dataset,
is `certification/evidence/robinhood-runs-355-368.json.gz`, SHA-256
`1be70cb9f53bfc9bce039f6913813a6d2a0a21dde39b6b10bf95b9123f47597f`.

| Population | Count | Meaning |
| --- | ---: | --- |
| Detailed run clusters | 8 | 357, 358, 360, 362, 364, 366, 367, 368 |
| Retained decision rows | 15,051 | Not raw discovery and not independent opportunities |
| Screened observations | 13,682 | Repeated observations included |
| Rows with native curve identity | 10,253 | Other rows cannot be assigned a curve |
| Run/native-curve identities | 1,519 | Re-entry regimes unknown outside canonical subset |
| Complete canonical vectors | 33 | All reconstructed without later features |
| Run/native curves with complete vectors | 19 | Repeated observations collapsed |
| Grade-A unique opportunity regimes | 21 | Two demonstrable re-entry resets under unchanged native rule |
| Qualifying Grade-A regimes | 7/21 | Seven qualifying vectors out of 33; five distinct run/curves |
| Recorded entry attempts/fills | 7/0 | Every recorded attempt canceled; not seven zero-return trades |
| Forward-labeled Grade-A winners/losers | 0/0 | All 21 opportunity outcomes UNKNOWN |
| Grade-B-supported opportunities | 0 proven | Missing forward outcomes, not proof no opportunity existed |

Primary unit: run + native curve + materially distinct re-entry regime. A new
regime requires the original `reentry_regime_reset` between qualified vectors;
repeated rows and single-dimensional changes do not create independent units.

355/356/359 have aggregates/partial retention; 361/363/365 have no comparable
candidate traces. They are not silently placed in the detailed denominator.
The committed current-state rejection audit supplies only a specific missing
preflight subset: 239 overlapping authenticated observations, 203 outside native
quote scope and 36 native temporary-snipe observations. Policy 1 classifies these
203 TERMINAL and 36 DEFERRED. None has a retained forward economic outcome, so
none qualifies for Grade B. This subset is not added to the 15,051-row population.

## Frozen alternatives and selection

`policies.json` freezes alternatives, chronological split, primary unit, and
acceptance before final validation. There are no fitted weights or threshold
searches. Development: 357/358/360/362, six Grade-A regimes, zero qualifiers.
Validation: 364/366/367/368, 15 Grade-A regimes, seven qualifiers.

Policy 1 maps early progress to WATCHING; young age and temporary snipe to
DEFERRED; incomplete/unready trajectory to WATCHING; and immutable scope,
unproven provenance, over-age, beyond-regime or creator hard risk to fail-closed
handling. The 50% floor is never a terminal research WATCH floor. Promotion uses
ordinal scope/provenance, readiness, trajectory, independent-demand quality, and
original-deadline feasibility, with stable identity ties. At most one native
candidate generation is promoted per existing single-worker dispatch; duplicate
redelivery does not create another job. An unknown feasibility estimate cannot
promote. No new provider work, scheduler, persistence or cache architecture was
introduced. These are offline candidate contracts, not a selected runtime change.

Policy 1 cannot demonstrate incremental economic preservation or an acceptable
canonical workload from the retained early rows: their full decision-time
readiness/trajectory and forward marks are absent. Importantly, the existing
Evidence Plane already permits a newer observation after a strategy rejection;
renaming a historical rejection is not proof of an incremental rescued opportunity.

Policy 2 retains canonical qualification and all hard invalidators. Research
hysteresis holds after one moderate soft observation, cancels after two distinct
consecutive observations or severe deterioration, and never extends freshness or
the original deadline. **All seven retained attempts had executable quote age
17–28 seconds against the unchanged five-second limit.** Three also had
nonpositive demand (one with creator distribution). All seven remain canceled
under Policy 2. Refreshing those quotes would require unavailable new executable
state; no counterfactual fill or P&L is fabricated. The mere presence of soft
rejection reasons does not establish a soft-only executable opportunity.

Policy 3 is not eligible for evaluation: there are no repeated Grade-A forward
executable outcomes supporting a concentration/breadth or other canonical gate
change across runs. Probes and scaling are UNMEASURABLE and not evaluated.

The acceptance gate treats unknown winner, loser, downside or workload effects
as insufficient to promote a revision. Eight leave-one-run-out evaluations, with
no refitting, retain baseline. This is robustness of the evidence-sufficiency
conclusion, **not statistical proof that baseline is profitable or optimal**.

## Selected gate treatment

All baseline economic gates remain byte-identical. TERMINAL_HARD here is a hard
rejection of the current entry decision, not a token-wide permanent rejection.

| Feature | Selected classification | Treatment |
| --- | --- | --- |
| Progress | NOT_PROVEN_FOR_CHANGE | Keep 50–85% canonical entry region; later generations reevaluated |
| Age | NOT_PROVEN_FOR_CHANGE | Keep 120–600 seconds; no age reversal |
| ETA | NOT_PROVEN_FOR_CHANGE | Keep 20–90 seconds |
| Trajectory completeness | NOT_PROVEN_FOR_CHANGE | Complete authoritative trajectory still required |
| Velocity | NOT_PROVEN_FOR_CHANGE | Existing progress/velocity gate retained |
| Acceleration | NOT_PROVEN_FOR_CHANGE | Existing acceleration gate retained |
| Independent breadth | NOT_PROVEN_FOR_CHANGE | Existing minimum retained |
| Buyer growth | NOT_PROVEN_FOR_CHANGE | Existing minimum retained |
| Buy/sell ratio | NOT_PROVEN_FOR_CHANGE | Existing ratio retained |
| Net demand | TERMINAL_HARD | Nonpositive demand cannot enter |
| Flow acceleration | NOT_PROVEN_FOR_CHANGE | Existing acceleration gate retained |
| Largest-buyer concentration | NOT_PROVEN_FOR_CHANGE | Existing maximum retained |
| Top-3 concentration | NOT_PROVEN_FOR_CHANGE | Existing maximum retained |
| Creator distribution | TERMINAL_HARD | Creator selling/adverse history remains a veto |
| Creator tax | TERMINAL_HARD | Existing maximum retained |
| Round-trip cost | TERMINAL_HARD | Unavailable/unacceptable economics veto entry |
| Entry impact | SIZING / TERMINAL_HARD | Existing impact-bounded size; zero executable size rejected |
| Scope/provenance/freshness | TERMINAL_HARD | Authenticated native quote, structural validity and five-second limit unchanged |

No new ENTRY_SOFT, REMOVED, or sizing treatment is selected. Baseline fill
persistence remains unchanged; research hysteresis is not enabled.

## Baseline versus selected

Same 33/33 reconstructed canonical decisions; same 7/21 qualifying opportunity
regimes; same 7/33 qualifying rows; same 0/7 recorded fills. Incremental captures
are not demonstrated. Winner capture, loser admission, Grade-B preservation,
executable after-cost returns and downside are UNMEASURABLE (zero forward-labeled
opportunities). Decision-time modeled round-trip friction is retained for 33
vectors, range 234–680 bps; this is not a realized return or a forward payoff.
The selected production workload is unchanged by source equivalence; candidate
policy counterfactual calls, latency, canonical readiness conversion and capacity
costs are UNMEASURABLE. A policy that promotes nearly everything is not accepted.

## Authority and implementation

PAPER ONLY. No market run, strategy-development provider collection, deployment,
Run 369 policy-selection data, or Run 369 Pump/Meteora repair. Pump, Meteora,
Ramses v4, accounting, provider topology/authority/ceilings, finality/freshness,
quote scope, total target size, generation fencing and caches are unchanged.
Profit-protection-v2 is byte-identical: -8% hard downside, +18% first realization,
3333 bps partial sale, runner/trailing/adverse-flow/creator handling, two soft
confirmations, 120-second no-high runner handling and original maximum hold.

The source branch adds frozen offline policy candidates, their tests and this
report. The composition advances only the Pons source identity through existing
`certification.run prepare`; it preserves every declared overlay. Final composed
replay and exact-SHA certificates are authoritative for verification. No revised
strategy should be promoted on the current evidence.
