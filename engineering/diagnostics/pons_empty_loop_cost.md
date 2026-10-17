# Pons empty-turn scheduling reads

The stopped AWS diagnostic of application `99a9d8faca4d75e9e1de7c03cbe221f95312359f`
reported about 148.127 GB of Pons logical reads and 36.604 million read calls.
These aggregate counters do not identify a query. Cost preflight
`39068894627` initially returned `UNAVAILABLE / PermissionError`. Corrected
protected preflight `39070080581` recovered the retained profiles without a
permission change: the observed Pons reporting count rose from 64 to 61,328
across its retained endpoints. This supports a high reporting cadence but does
not attribute logical read bytes to a specific query. This repair establishes
an offline mechanism, not attribution of all AWS traffic or sustained capacity.

The ordinary Current loop calls coverage, committed-result lookup and work
selection after its existing 5 ms empty wait. On the exact deployed source,
recovery scans wide candidate rows to find claims, result delivery scans wide
rows to exclude acknowledged results, and maintenance checks each consumption
against a candidate's generation using its id-only index. Peer header, receipt
or checkpoint commits invalidate maintenance's existing database stamp. Both
previously installed covering indexes remain present throughout this proof.
The retained-source identity scan fixed earlier is not repeated here: projection
itself was cheap in this fully consumed fixture.

The runtime change is confined to
`meme_machine/runtime/robinhood/plane.py`:

- Thin partial indexes select claims and completed-result scheduling keys.
- One materialized SQLite statement selects delivery keys, excludes the exact
  consumed generation, then hydrates complete economic rows in original order.
- A covering `(id,generation)` index serves maintenance membership checks.
- The existing, identical Current watch schema is created idempotently with a
  due-clock index. `pons.py` remains byte identical to the baseline, preserving
  its authenticated adapter identity.

Recovery still checks the original boot/PID/start identity and lease clock on
every call. Every original maintenance call, active-family predicate, protected
record check, result/claim fence and three-/five-second protection deadline stays
in place. There is no new generation cache, version authority, timer delay,
financial constructor, provider capability or historical acknowledgement.

The alternative of dependency-specific publication/version tables could avoid
some repeated maintenance. It adds transactional trigger, invalidation and
restart obligations. Thin scheduling indexes and one-statement hydration remove
the reproduced wide-body reads while retaining immediate visibility through the
existing SQLite transactions, so no new publication mechanism is needed here.

## Same-workload evidence

The script `pons_empty_loop_cost.py` uses native Plane, Broker, Pipeline and
Attempts methods, an independent peer Plane, network denial and admitted Scratch.
It uses 1,169 candidates, 4,096 transitions/observations/evidence facts, 768-byte
padding and an acknowledged result tail. Counts resemble an earlier receipt;
bodies, lane distribution, acknowledged population and peer cadence are synthetic.
Sixteen turns per case use the same corpus and peer mutations on both revisions.

| Native empty turn | Baseline logical bytes | Repaired logical bytes |
| --- | ---: | ---: |
| No writes | 9,935,742 | 8,318 |
| Peer header | 15,199,871 | 618,110 |
| Peer receipt | 15,216,768 | 635,006 |
| Peer checkpoint | 15,233,152 | 651,391 |

All sixteen peer turns still perform sixteen complete maintenance sweeps.
The idle SHA-256 of complete rows in the selected candidate, transition,
observation, consumption, watch and reporting tables matches across versions:
`fde647f9a2982c8c003ad7503ebbfb79ec7b9cc8c9cf736c2b2fb56700fc72f9`.
A further identical 64-event native Scout/Broker publication batch and subsequent
populated constructor/index migration preserve that selected-row hash:
`02db05b482b89d7dbf95f989d481a81db79154e344ea47f2f613355149c7cd9b`.
An additional comparison includes every native user table, including runtime,
cache, receipts and Scout rows; its full table-content hash also matches across
versions and after migration:
`879dc94c8ab3d26c333f8f2d1d326638c24afccec744aae06c3a2c82052f393b`.

The added indexes have a cost. The fixed 64-event batch's logical writes rise
from 5,588,448 to 6,193,944 bytes (+10.8%), while VM work rises from 8,532,000 to
8,538,000 steps (+0.07%). Wall time was 0.3574 versus 0.2115 seconds in the final
synthetic comparison; earlier measurements varied, so no speed ratio is inferred.
Populated constructor/integrity work plus initial index
creation took 0.01420 versus 0.01550 seconds, with about 9.76 MB additional logical
reads and 206 KB additional logical writes. These timings are not AWS guarantees;
physical writeback cannot be inferred from logical write counters.

The final baseline was executed against untouched application `99a9d8f...`.
Runtime SHA-256 values are baseline Plane
`16e60de17cac6fc86895512af47f6a3db8ef31012133ae91fe60b233fa15e9a2`,
repaired Plane `0091fbed25866fa419f8eeb891fa873281c75b892e7506e26fb7952a7110ec29`,
and unchanged Broker `52defbb90f754e7b2ea88e4527bf7bdc30d6251854f89a37f52dabbb70a931f0`.
The two retained receipts are
`/workspace/recovery-evidence/pons-empty-loop-exact99-final-baseline.json` and
`/workspace/recovery-evidence/pons-empty-loop-final-repaired.json`; both retain
statement shapes, approximate VM steps, syscalls, logical/physical I/O, plans,
native hashes and migration results. Benchmark generation is
`pons-empty-loop-cost-v1`, script SHA-256
`76b34785c46f71a7942507f2eafefda182742f093482e769af6bf73cc5b5ed7d`;
the same script was used for both runs.

Eight new regressions cover bounded wide-tail reads, a newly pending candidate,
live/expired and previous-boot claims, paused rows, exact outbox order/results,
projection without acknowledgement, obsolete-generation consumption, real peer
completion during one SQLite snapshot, and cancellation/retry. Combined with
native Plane/Broker, projection, retention and financial-retirement regressions,
66 cases passed in 2.442 seconds without skips. The independent review found no
blocking issue within this scope.

No AWS workload or financial database was touched. The last reported portfolio
was sequence 15,857, $1,000 and flat in AWS rehearsal `39067324778`,
collected by `39068855312`; this offline proof supplies no additional financial
observation or readiness. Exact-source installation, actual retained population,
resource behavior, provider timing and sustained throughput require the existing
protected deployment and one cause-based bounded AWS diagnostic.
