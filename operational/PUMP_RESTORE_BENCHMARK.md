The offline restoration benchmark compares two clean source checkouts in separate
CPython 3.12.14 processes. It measures the actual
`runner._restore_observed_pump_candidates` and `CandidateHistory` implementations.
The exact pre-PR #166 source is `45185cd007dd0ca17c9cdf2615dde5b551a463cf`;
the merged repair is `e5b95d25200b4bd83937bae21344156dedd12640`.

The first paired local run on October 17, 2026 passed with 16 candidates,
64 native fixture frames, 128 canonical references and two 64-record cold
archives. The exact receipt is [pump-restore-ab-20261017.json](pump-restore-ab-20261017.json).
Both revisions used the same corpus hash
`69f273f2dcecada05b9bb82c0d372f143256d1811c9706ae6d8a1ff94147cff7`
under CPython 3.12.14 and identical pinned requirements.

| Full restoration measurement | Before PR #166 | After PR #166 |
| --- | ---: | ---: |
| Wall seconds | 0.046254676 | 0.038486887 |
| Process CPU seconds | 0.046255666 | 0.038488322 |
| Archive-open calls | 16 | 2 |
| Compressed bytes offered by opens | 105,320 | 13,165 |
| Candidates restored | 16 | 16 |

This single paired synthetic run observed 1.20x wall and CPU ratios and eight
times fewer archive opens. Canonical, candidate, archive and input hashes
matched, as did full restoration, cancellation after eight creations, and
fresh restoration after cancellation. Both sources preserved the logical
native databases, opened no financial databases and made no network calls.
These local mechanism measurements do not establish the earlier 490-second
AWS startup improvement or sustained live-market throughput; those remain
separate representative AWS measurements.

The workload is a synthetic native-frame fixture derived from the retained
`tests/fixtures/solana_selective_cohort.json` capture. Public mint/curve identities,
timestamps, block coordinates and signatures are varied explicitly to create
independent candidate scopes. The resulting transactions are fixture inputs,
not authenticated signed mainnet transactions. The original production event
decoders prepare their economics. The fixture then uses the real linked control
and candidate commits, FULL consumer delivery, original ACK, publication and
guarded cold retirement. A shared archive contains several candidates. No
candidate reference or acknowledgement is fabricated by direct SQL insertion.

For example, with separate clean checkouts at those exact commits:

```sh
python -m operational.pump_restore_benchmark compare \
  --before /workspace/restore-before-166 \
  --after /workspace/restore-after-166 \
  --candidates 16 --references 4 --archive-records 64 \
  --output /workspace/pump-restore-ab.json \
  --capture-output /workspace/pump-restore-frames.json
```

The source checkout paths select exact Git HEADs and trees; dirty checkouts or
different runtime requirement hashes are refused. The controller runs sequential
workers in an admitted engineering `Scratch`, with a 120-second per-worker
deadline by default, periodic storage checks and process-group cancellation.
Successful scratch state is removed only after the small result receipt is
saved; failures retain their entire disposable state and worker diagnostics.
The optional capture output is bounded at 32 MiB. Output paths must be new.

Use `--corpus /workspace/pump-restore-frames.json` in a later comparison to reuse
that exact input workload. Each invocation reconstructs independent disposable
native histories from the captured frames. The result requires matching input,
canonical record, candidate and archive hashes, populations and FULL/ACK batch
counts across both sources. The original source paths remain distinct.

The measured phases are a full restore, cancellation at the same creation
boundary, and a fresh restore after cancellation. A real `ConfirmationBook`
subclass observes creation normally and raises the existing stop request at
the chosen boundary. Production restoration remains unchanged. Both revisions
must return identical normalized creation, graduation, wallet, pool, history
adapter and confirmation outputs in all phases. Logical SQLite digests before
and after must match, including pending work and receipts.

The receipt records wall time, process CPU, archive-open calls and compressed
bytes offered by those opens, block-I/O deltas and process peak RSS. Archive
opens are counted by Python audit events, without replacing production archive
reads or decompression. These counters do not establish physical disk reads;
the OS page cache remains active, and peak RSS includes fixture construction.
Compare CPU and repeated archive opens along with elapsed time. One timed pair
alone does not establish a statistically stable speedup.

The scrubbed worker environment contains no provider keys, portfolio path or
funding authority. Audit enforcement permits SQLite opens only for its two
disposable native databases, refuses network operations and refuses writes
outside its new worker directory. No financial database is opened. This is a
synthetic restoration mechanism benchmark. It does not establish AWS resource
capacity, provider acquisition, continuous economic throughput, historical
recovery, strategy readiness or one-hour PAPER acceptance.
