# Run 369 Pons accounting repair

Base: `d1fc161401869522db9abbf50e3f6073e80a4374`.
Branch: `repair/run369-pons-accounting-20260925`.
This repair is independent of the Solana runtime repair. Paper only; no market
collection, provider probes, deployment, or workflow dispatch.

## Reproduced defects

On the unchanged base, two minimized causal tests retained
`valid_early_rejection` after newer discovery/queued work. A native broker fixture
advanced the original five-second deadline until the measured service no longer
fit; `pop()` recorded the capacity deferral while opportunity capacity remained
zero. All three assertions failed before implementation.

The broker's `claim()` can terminate pending work without returning a job. Only
returned jobs reached the cohort's pipeline accounting. Separately, the causal
reconciler updated `last_stage` without replacing an earlier status when a newer
unresolved stage had no status mapping.

## Contract

`robinhood/accounting.py` is the single Candidate Plane state-to-class table.
An incremental bounded projection copies its append-only transitions into the
native opportunity pipeline. Source markers and history commit together; replay
and relocation preserve deduplication. Normal coverage handles at most 256 source
rows per call. Ordered decision reporting and shutdown drain only a captured
high-water mark, never an unbounded moving tail. No provider or job ownership
operation is added. Existing durable result consumption remains independent.

Native decision rows carry their work generation; a superseded consumer result
can record only superseded history. Current causal status ignores fenced/older
results. New generations reset candidate decision/evidence state; older legacy
archives use ordered discovery/queued-work boundaries. Native lifecycle state
remains authoritative. Only an explicit authenticated immutable `pairToken`
proof persists as a structural exclusion within the frozen candidate namespace.
Canonical current-state completion is distinct from full strategy evidence.

Historical opportunity classes count distinct native candidates per class, with
intentional overlap across generations. A subsequent observation never subtracts
a real earlier capacity/deadline/provider loss. Assurance independently reads the
Candidate Plane and requires matching candidate/class memberships in the pipeline
and non-understated lane counts. Missing stores or contradictory accounting fail
admission. Strategy/structural screens never substitute for infrastructure classes.
Authenticated early boundaries now retain their existing structural/strategy
meaning in the plane, instead of a generic evidence-failure label.

## Preserved Run 369 reconciliation

Source run: `36200179045`; source artifact SHA-256:
`02e04c9d93ba3aafffe89f16af2e265ef27602a8c67d9c1197a8a4be9501c665`.
The committed fixture contains derived public identities and the one relevant
retained authenticated proof, not a rewritten run database.

| Curve suffix | Source transition | Generation | Capacity classification | Economic relevance established? |
| --- | ---: | ---: | --- | --- |
| `520dc3b0` | 24 | 1 | capacity_censored | Unknown; no canonical completion |
| `9afceec6` | 407 | 2 | capacity_censored | Prior authenticated non-native immutable quote excludes it under the frozen policy |
| `7755224c` | 410 | 8 | capacity_censored | Unknown; no canonical completion |

All three remain historical capacity-censored candidates. The immutable exclusion
is a separate, overlapping fact; it cannot erase the deferral or justify treating
the other two as irrelevant. The original assurance contained only 47 historical
strategy-rejected candidates and zero capacity classifications.

Read-only latest-state reconciliation of the original 101-candidate pipeline
produces 8 explicitly proven structural exclusions, 27 current strategy
rejections, and 66 observed/unresolved candidates. Its original causal summary
had 47 rejections and 54 observed. The retained archive has no generation stamps;
new runtime history does. The original plane also used the generic
`authoritative_evidence_failure` label for authenticated early-screen boundaries;
those labels alone must not be interpreted as evidence of a provider outage.

## Verification and authority

Regressions cover generation rollover, final rejection, immutable exclusions,
append-only history, distinct classes, same-population contradiction, fencing,
valid later completion, bounded projection, atomic crash/replay deduplication,
Ramses lifecycle semantics, and the actual native broker capacity path.

The dedicated `run369-pons-accounting-offline.yml` runs root/resource checks,
prepared-lane supervisor tests, and `certification.robinhood.certify` (all four
native suites, frozen identities, retained Pons/Ramses replay, crash/restart,
integrated accounting, provider governance, and external-network rejection).
Results and exact integration SHA are retained in its artifact. The sole existing
test expectation changed is the authenticated non-native quote's reporting class
from strategy rejection to structural ineligibility; all its evidence/economic
assertions remain.

Pons/Ramses strategy policy files/hashes and provider authority/ceilings are
unchanged. Only the Pons reporting overlay identity is advanced. A subsequent
market run still requires separate authorization, the separate Solana repair,
and deterministic certification of the exact combined integration SHA. Run 369
cannot be retroactively accepted as an uncensored market sample.
