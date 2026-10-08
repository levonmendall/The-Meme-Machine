# Offline validation and reproduction

Use CPython 3.12.14 and the repository's pinned requirements. The session used
`/mnt/volume_nyc1_1790918115030/preserved-codex-workspaces/2026-10-06/the-meme-machine-efficiency-successor/verification-venv/bin/python`.
All authoritative/temporary DBs and generated tapes belong on the attached volume.
Provider credentials are not needed for any command here. No market call was made.

## Tests

| Check | Result |
|---|---|
| Reproduced targeted baseline defects | 3 cases: one failing unchanged-request mutation assertion; one valid Pons slice incorrectly rejected; one missing-response fail-closed case passed |
| Same targeted cases after repair | **3 PASS** |
| Affected source/join/history/startup/Pons/shared-capital/nine-change suite | **173 tests PASS**, one existing skip, 105.505 s |
| Broad FAST, including new regressions and unchanged economic fixtures | **846 tests**, 427.690 s, **one pre-existing failure** |
| Final focused observer/intake/capture-bound/proof accounting checks | **37 tests PASS**, 0.957 s |
| Isolated baseline source-freeze assertion | Same failure reproduced directly on untouched published integration commit, 1 test / 0.239 s |
| Identical native tape replay | Exact 287 canonical rows and all candidate/consumer projections equal; hash/order/first-seen match captured authority |
| Both combined-load cycles | Same canonical and consumer projection digests in reference/repaired load cycles |
| Per-file syscall tracing | Exact 47,534,936 cumulative WAL bytes in both serial replays; no write/sync errors |
| Approved policy/native contracts/frozen sources/capture manifest | **PASS**, [PRESERVATION.json](PRESERVATION.json) |
| Source compile / JSON reports / diff whitespace | **PASS**, final review receipt in [PUBLICATION.json](PUBLICATION.json) |

FAST fails `tests.test_robinhood_usd_valuation.RobinhoodUSDTests.test_strategy_sources_and_nine_change_tests_byte_unchanged`
at its comparison of `meme_machine/lanes/pons/pons_selective_acquisition.py` with an
earlier repository revision. That file is unchanged from the authoritative
published integration and this branch. The integration handoff already records
the failure. No assertion, strategy source or earlier snapshot was changed to
make the suite green. The failure remains a published baseline limitation.
The broad run preceded the last observer-only WS projection and tool temporary
directory/bounded-reader changes. Their final focused tests and full raw-tape/
routing-field parity then passed. The complete suite was not repeated for those
isolated diagnostic changes.

Small test logs and their SHA-256 receipts are in
[validation/FAST-final.log](validation/FAST-final.log),
[validation/affected.log](validation/affected.log),
[validation/targeted-baseline.log](validation/targeted-baseline.log),
[validation/targeted-repaired.log](validation/targeted-repaired.log),
[validation/source-freeze-baseline.log](validation/source-freeze-baseline.log) and
[validation/focused-final.log](validation/focused-final.log) and
[TEST_RECEIPTS.json](TEST_RECEIPTS.json). OPERATIONAL was not run: there is no
deployment, and the user requested affected diagnostics followed by a single
warranted broader validation. No CAPACITY/RECOVERY/AUTONOMY or broad trading
backtest was run.

## Reproduce the capture investigation

Set the following shell variables to a pinned Python and **new empty output
locations** on the attached volume. Never reuse an existing capture/output DB.

```bash
PROOF_PYTHON=/path/to/cpython-3.12.14-venv/bin/python
PROOF_BASE=/mnt/volume_nyc1_1790918115030/shared-capital-integration-20261007
PROOF_CANDIDATE=/mnt/volume_nyc1_1790918115030/pump-provider-offline-20261008
PROOF_CAPTURE=/mnt/volume_nyc1_1790918115030/sc-proof-corrected-20261008
PROOF_OUT=/mnt/volume_nyc1_1790918115030/a-new-offline-proof-directory
mkdir -p "$PROOF_OUT"
```

The supplied source checkout must have the exact published baseline revision
for the reference. The candidate revision must match the publication receipt.
Both recorded source-hash vectors and raw tape SHA-256 are verified in the report.
The tools use the same raw frozen tape, authentic native joins and original wall
observations; performance uses a separate monotonic clock.

```bash
"$PROOF_PYTHON" -m engineering.solana_capacity.offline_attribution \
  --capture "$PROOF_CAPTURE" --output "$PROOF_OUT/corrected-attribution-final.json"

"$PROOF_PYTHON" engineering/solana_capacity/offline_replay.py \
  --source "$PROOF_BASE" --capture "$PROOF_CAPTURE" --output "$PROOF_OUT/replay-baseline"
"$PROOF_PYTHON" engineering/solana_capacity/offline_replay.py \
  --source "$PROOF_CANDIDATE" --capture "$PROOF_CAPTURE" --output "$PROOF_OUT/replay-repaired"

"$PROOF_PYTHON" engineering/solana_capacity/offline_processing.py \
  --source "$PROOF_BASE" --capture "$PROOF_CAPTURE" --output "$PROOF_OUT/processing-baseline"
"$PROOF_PYTHON" engineering/solana_capacity/offline_processing.py \
  --source "$PROOF_CANDIDATE" --capture "$PROOF_CAPTURE" --output "$PROOF_OUT/processing-repaired"

"$PROOF_PYTHON" engineering/solana_capacity/offline_contention.py \
  --source "$PROOF_BASE" --capture "$PROOF_CAPTURE" --output "$PROOF_OUT/contention-baseline"
"$PROOF_PYTHON" engineering/solana_capacity/offline_contention.py \
  --source "$PROOF_CANDIDATE" --capture "$PROOF_CAPTURE" --output "$PROOF_OUT/contention-repaired"
```

Run performance pairs sequentially on the existing two-vCPU/eight-GiB host, with
other heavy diagnostics stopped. The first exploratory repaired replay overlapped
attribution and took 9.70 s / 7.15 CPU s, compared with 6.67 s / 4.78 CPU s for
the earlier reference. That uncontrolled pair is preserved on the volume and
is **not** evidence of an optimization regression or speedup. The final quiet
isolated/combined results in CONTENTION.json are the reported pair. Single pairs
still do not establish statistically significant CPU or allocator-tail improvement.

The processing receipt's three decode trials deliberately measure the actual
two-pass reference and one-pass repair. Its observer component uses the unchanged
level-six raw-frame capture, with exact raw-delivery and WS routing-field digests
verified before/after. Final observer WS metadata uses native bounded JSON
projection. Its profiled CPU is slightly higher; 40.78 MB of Python log-string
materialization is avoided without a claimed CPU saving. Final processing
directories have suffix `-final`; use those names when reproducing publication
receipts. Request reassertions use captured final immutable
job bounds and observation times; they cannot reproduce unrecorded caller arguments.
The contention fixture exercises the real Pons admission implementation with
offline fake transport identities and zero market requests. It does not certify
market history or native position deadlines.

For journal attribution, use **new** `journal-baseline` and `journal-repaired`
output paths, run the following twice with the corresponding source, then run
`offline_journal`. The trace itself must also stay on the attached volume.

```bash
strace -f -yy -s 0 -e trace=write,pwrite64,fdatasync,fsync \
  -o "$PROOF_OUT/journal-baseline.strace" \
  "$PROOF_PYTHON" engineering/solana_capacity/offline_replay.py \
  --source "$PROOF_BASE" --capture "$PROOF_CAPTURE" --output "$PROOF_OUT/journal-baseline"

"$PROOF_PYTHON" -m engineering.solana_capacity.offline_journal \
  --evidence "$PROOF_OUT" --output "$PROOF_OUT/JOURNAL.json"
```

Tracing records successful FD writes/syncs without strings. Its overhead makes
latency/CPU unsuitable for comparison. This measurement confirms substantial
SQLite journal/sort traffic under serial captured input; it cannot reconstruct
the original live process's unrecorded per-file cumulative writes. The first
trace saw small ephemeral SQLite sorter files in `/var/tmp`; the finalized tools
set `SQLITE_TMPDIR` and `TMPDIR` to their volume-backed disposable output directory.
All large raw captures and databases remain on the attached volume.

`offline_report` assembles small receipts from the named final attribution,
processing and contention output directories, checks full parity rather than
counts, checks the original canonical key/hash/first-seen columns and all retained
bodies, and compares frozen files/policy/capture manifests. It does not copy full
raw frames or parity bodies into Git.

```bash
"$PROOF_PYTHON" -m engineering.solana_capacity.offline_report \
  --evidence "$PROOF_OUT" --baseline "$PROOF_BASE" --candidate "$PROOF_CANDIDATE" \
  --output "$PROOF_OUT/small-receipts"
TMPDIR="$PROOF_OUT" "$PROOF_PYTHON" -m operational.tests FAST
```

To reproduce all publication manifests, also attribute the preserved original
capture to `original-attribution-final.json` and retain the initial attribution
receipts as `corrected-attribution.json` / `original-attribution.json`. Their
before/after inventories prove existing evidence bytes were preserved. The
publication receipt lists the exact local artifact directory and source tree.

The retained tape's independent-witness tail is incomplete. Serial replay does
not recreate original network/finality delay, eight archive-worker polling,
governor delays, candidate deadline pressure or positions. These limitations
must survive reproduction and remain explicit readiness failures/insufficient
samples, rather than becoming synthetic interval receipts.
