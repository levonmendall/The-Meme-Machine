# Offline validation and reproduction

Use CPython **3.12.14** and the five exact versions in `requirements.txt`.
The isolated validation environment is
`/mnt/volume_nyc1_1790918115030/pons-historical-bootstrap-evidence-20261008/verification-venv`.
It reads the already preserved, fully pinned verification dependencies through a
local `.pth`; no production environment or dependency was changed. The initial
`/opt/meme-machine/.venv` lacked `based58`: an incomplete FAST attempt was stopped
and is not a validation result. The complete rerun used all pinned versions.

All temporary state, copies, traces and benchmark DBs use the attached-volume
evidence directory. Repository `network_guard()` forbids non-loopback market I/O
in FAST, the affected suite and the benchmark. New tests additionally use only a
supplied synthetic canonical tape and clear runtime environment paths. They open
no production book or database. No market-provider request was made.

## Results

| Check | Result |
|---|---|
| Initial full historical regression set | 33 PASS / 104.464 s |
| Added older-launch caching and runtime warm/position checks | 2 PASS / 9.217 s |
| Broader Pons/provider/native-history/recovery set, excluding FAST duplicates | 338 PASS / 124.724 s; exact modules in [affected-modules.json](affected-modules.json) |
| Complete pinned FAST | 883 tests / 585.492 s; 882 PASS, one documented baseline failure |
| Baseline source-freeze reproduction on untouched starting commit `703d876` | Same failure / 0.276 s |
| Final focused complete set after receipt-cache integration, ABI reuse and inclusive enrollment boundary fix | **47 PASS / 117.148 s**: 36 historical + 11 native provider cases |
| Additional native exact-vector/group replay after ABI reuse | 2 PASS / 22.709 s |
| Final local/shared receipt-cache accounting regression | 1 PASS / 0.821 s; includes local hits when shared-cache telemetry is present |
| Same-input local cost benchmark | Five cases; exact native economic history parity; zero actual market calls |
| Source/database/branch preservation | 33 audited original DBs unchanged; 37 frozen files unchanged; four remote heads preserved |
| Compile, report JSON, test/source checksums, diff whitespace | Checked before publication |

FAST's sole failure is
`tests.test_robinhood_usd_valuation.RobinhoodUSDTests.test_strategy_sources_and_nine_change_tests_byte_unchanged`.
It compares `pons_selective_acquisition.py` to an obsolete earlier source snapshot.
The failure is reproduced on the **exact** untouched starting commit; that file,
the original assertion, and all approved economics remain unchanged here. No
claim of a fully green FAST result is made.

The broad suites preceded the final localized receipt-pin/accounting and
ABI-hoisting changes, and the strict prospective inclusive-boundary fix. The final
47-case affected regression set, the final cache-accounting case and source-pinned
benchmark validate these final changes. The broad expensive suites were not repeated again.
OPERATIONAL was not run: no deployment is authorized. No broad profitability,
CAPACITY, AUTONOMY or repeated seven-day provider study was run.

Small immutable logs and SHA-256 receipts are in
[TEST_RECEIPTS.json](TEST_RECEIPTS.json) and [validation/](validation/).
Tests validate deterministic complete inputs and failure semantics; they do
**not** establish authentic seven-day market coverage or actual provider support.

## Coverage matrix

| Required behavior | Evidence |
|---|---|
| Independent launch/graduation census, hashes, timestamps, order, relationship recall | `test_exact_boundary_census_and_all_candidate_histories`, native captured-lineage/protocol tests |
| Exact old/new qualification vectors, economic reasons, empty funding book | `test_old_and_new_exact_complete_vectors_and_rejections`, same test with conditional wider ranges |
| Multiple candidates / native group decoding | Shared group reconstruction/restart test and native shared-Survivor/ongoing-scale tests |
| Earlier-than-domain launches | `test_older_launch_search_reuses_authenticated_lineage` |
| Empty ranges need canonical boundaries | Empty range/boundary tests; missing historical header test |
| Truncation, range-size rejection, paging failure | Bounded capability disagreement, adaptive subdivision, saturation and page-envelope tests |
| Duplicate/conflicting events and overlapping turns | Duplicate insertion/conflict tests, durable frontier tests; native canonical-order tests |
| Interrupted atomic writes | Interrupted write test verifies no partial event/checkpoint/intake publication; explicit gap survives |
| Catch-up restart / no proven-range refetch | Restart during catch-up, native worker restore and warm runtime discovery tests |
| Reorganization handling | Population suffix rewind, candidate recovery/controller preservation, corruption/missing event replay tests |
| Original deadlines/generations and funded/unfunded separation | Transient-failure/reorg deadline tests; native history/risk/commit/fairness and existing capital/independence suites |
| Expiration and recovery retention | Strategy/recovery-floor retirement test and native retirement/archive tests |
| Prospective exact inclusive domain | Seven-day equality is still incomplete; later canonical timestamp permits maturity |
| Current traffic during backfill / position precedence | Historical priority 50 vs Current 5/position 0, warm position-before-discovery test, unchanged shared-position/provider fairness tests |
| Readiness cannot be a cursor or `complete` flag | Deleted prefix rejection, missing event digest replay, candidate coverage and population-only readiness tests |
| Cache/provider/resource accounting | Native receipt-pin scope test, logical-vs-physical telemetry, actual payload read/attempt byte tests, rejected response and HTTP range-error accounting |

The primary real graduation/registration/initialization and factory record come
from `tests/lanes/pons/fixtures/pons_lineage_35378762520.json`. All absent headers,
receipts, launches, added candidates and economic paths are explicitly fabricated
test inputs. Compressing seven synthetic days into 169 blocks checks time-domain
semantics; it is not a 5.99-million-block parity tape. No authentic complete tape
or candidate history existed to prove live seven-day parity.

## Reproduce

Run from the dedicated checkout. Point `PONS_PROOF_PYTHON` at a fully pinned
3.12.14 environment and choose **new** disposable attached-volume paths:

```bash
PONS_PROOF_PYTHON=/path/to/pinned-3.12.14/bin/python
PONS_PROOF_TMP=/mnt/volume_nyc1_1790918115030/new-pons-offline-output
mkdir -p "$PONS_PROOF_TMP"
TMPDIR="$PONS_PROOF_TMP" "$PONS_PROOF_PYTHON" -m unittest \
  tests.test_pons_historical tests.lanes.pons.test_provider -v
TMPDIR="$PONS_PROOF_TMP" "$PONS_PROOF_PYTHON" -m operational.tests FAST
```

The additional affected suite is the module list in `affected-modules.json`:

```python
import json, unittest
from pathlib import Path
from operational.tests import network_guard
network_guard()
modules = json.loads(Path('operational/pons-historical-bootstrap/affected-modules.json').read_text())
result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromNames(modules))
assert result.wasSuccessful()
```

The benchmark has a new-directory guard and blocks market network access:

```bash
TMPDIR="$PONS_PROOF_TMP" strace -f -yy -s 0 -e trace=write,pwrite64 \
  -o "$PONS_PROOF_TMP/writes.trace" \
  "$PONS_PROOF_PYTHON" -m engineering.pons_history.benchmark \
  --state "$PONS_PROOF_TMP/new-benchmark-state" \
  --report "$PONS_PROOF_TMP/measurements.json" --blocks 4096
```

Sum successful write/pwrite64 return bytes by actual FD path ending in
`history.sqlite-wal` or `history.sqlite` to reproduce cumulative per-file writes.
The published report includes initialization/acquisition/restoration/close in
these sums; phase process write_bytes and retained WAL stock are distinct.
The final source hashes are in [MEASUREMENTS.json](MEASUREMENTS.json). Tracing and
concurrent offline load are disclosed; generated fake batches are not HTTP
measurements. Both economic benchmark paths acquire receipts/senders, rather
than replacing reconstruction with ready-made economic vectors.

The source audit command uses individually selected sources from a read-only
schema catalog. Use a new output directory; do not rerun over production source
collections or recursively clone them:

```bash
"$PONS_PROOF_PYTHON" -m engineering.pons_history.inventory \
  --catalog /path/to/read-only-database-catalog.json \
  --copies "$PONS_PROOF_TMP/new-individual-source-copies" \
  --report "$PONS_PROOF_TMP/sources.json"
```

No command here runs the live capability comparison, begins live accumulation,
opens a PAPER epoch, connects an alternate provider, or deploys code.
