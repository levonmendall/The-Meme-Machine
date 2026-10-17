# Retained Pump reference filesystem proof

The exact `0c8e9beae8eed6e4579f4473c4f449f711fb5691` AWS rehearsal
`39060983198` measured Pump observed restoration at 610.8128 seconds across
14,109 candidate-event reads. The retained profile separates 436.0024 seconds
of selected SQL wall time / 34.9224 seconds CPU from approximately 163 seconds
of outside-SQL wall time and CPU. These are overlapping operation categories,
not an independent end-to-end speed forecast.

The earlier same-cohort offline discriminator identified repeated path
resolution as a substantial outside-SQL cost. Each original retained reference
strict-resolved root, candidate, source and target; source and target are the
same path for noncold references. The new implementation walks their common
ancestor chain once **within each individual reference invocation**. Each
parent must be a nonsymlink directory; candidate, source and selected cold
archive must be nonsymlink regular files. The exact legacy locator,
PAPER/epoch/root/selected-source/candidate/canonical-source predicates remain
unchanged. Direct current, foreign and original-deployment locators retain
their prior behavior. Cold fingerprint/hash, record/ref hash and identity,
archive bounds, cancellation and result ownership are unchanged.

This retains no path proof, path mapping or file identity between references.
It does not establish the actual inode held by a cached SQLite connection.
Both the predecessor's multiple `resolve` calls and the new component walk
perform sequential filesystem checks; neither is an atomic defense against
an adversarial rename during one invocation. The proof is equivalent for a
stable tree, with stricter regular-file checks for candidate/source leaves.
Tests cover missing, wrong-type and symlink replacements at each owned
ancestor/leaf between invocations, changed environment after success, and
native cold/reference corruption and cancellation/restart behavior. There is
no claim that a same-path regular-file replacement is detected solely by
inode: the original opened-connection and immutable-record authentication
contract continues.

Retaining the predecessor would retain repeated common-prefix traversals.
Duplicate source/target elimination alone removes less measured cost.
Cross-reference source/path sessions were rejected: standard Python sqlite3
does not expose the opened main-file descriptor, and a `/proc/self/fd` URI
canonicalizes to a pathname rather than establishing that proof. A snapshot
export would introduce extra I/O, ownership and lifecycle complexity. Separate
bounded transaction-page experiments reduced logical reads but did not
establish a reliable wall-time improvement; no transaction-page behavior is
included in this repair.

## Exact workload comparison

`operational/pump_restore_path_benchmark.py` captures one explicitly synthetic
native-frame corpus and constructs actual canonical producer, FULL consumer,
ACK, retirement and native restore state through the existing production APIs.
It warms three quarters through actual `ScopedRetirement.restore`, then moves
the intact disposable cohort. Original reference/manifest paths and hashes
remain unchanged. Only fixture cohort root constants and exact environment
are relocated. An audit guard forbids network, SQLite outside disposable
state and writes outside Scratch except the exact output artifact.

The helper extracts the exact predecessor filesystem function from Git. It
compares that function, a duplicate-only elision comparator, and the candidate
function over **one identical** 32-candidate / 1,024-reference corpus
(768 TEXT / 256 COLD). Six passes per mode alternate order. The unprofiled
actual Pump runner is timed separately from a path-only CPU/lstat profile.
No source transaction, source query, canonical precedence, hash, decoder,
candidate consumer or cancellation implementation is substituted.

| Measure per restore | Original | Duplicate only | Factored walk |
|---|---:|---:|---:|
| Median runner wall seconds | 0.253914 | 0.233923 | 0.186597 |
| Median reader-thread CPU seconds | 0.258862 | 0.236024 | 0.188373 |
| Median profiled path CPU seconds | 0.142387 | 0.122859 | 0.079509 |
| Path lstat calls | 23,296 | 18,176 | 9,472 |
| Archive opens / packed bytes | 4 / 24,446 | 4 / 24,446 | 4 / 24,446 |

All 18 restores have identical economic output digest
`1b39789eddb9511f6ed81ee8eaa2dd494f13d3e3673a5db65f61c284a97a2240`.
The corpus digest is
`d11b5f445eb0d53d406e1437d66d3ee82206c62771870e6b9eb2fe103eb2a865`.
The retained local receipt is
`/workspace/recovery-evidence/pump-restore-path-factoring-0c8.json`, SHA-256
`17b5e76a452bef04772ba252a6e33714bb4247a3377a2f3acf3c1ec5a37e056d`.
Runtime source SHA-256 changes from
`bdd6418f6930581e48d887897493d32cb24bd260faf529e4694306e8f389c6c4`
to `74b40b66a6fd13f7bada63954dfdbb37690bd9c6f3db597a4d3a2182d6ed08cd`.

CPython is pinned 3.12.14. Local SQLite is 3.53.1; AWS uses 3.45.1. This is
`SYNTHETIC_NATIVE_FIXTURE_ONLY_NOT_LIVE_CAPACITY`. It establishes reduced
filesystem validation work with preserved fixture economics, not an AWS
startup or full-market throughput improvement. The unresolved SQL waiting
and Pons logical-read costs remain separate operational bottlenecks.

## Focused validation

Initial 33 cases pass: retained path walk, retained canonical reference,
canonical cold archive cohort and startup archive reuse modules. Six adjacent
modules (startup cancellation, restore selection, recovered archive session,
hot-page retirement, candidate history and native commit batch) run 86 cases
with 10 `retirement_hot_pages` fixture errors at the unchanged indexed query
(`no query solution` on local SQLite 3.53.1) and one existing native commit
batch FIFO assertion failure. The identical 86 cases on unchanged `0c8` runtime
reproduce exactly those 10 errors and that failure. Both failed Scratch
directories remain retained. Baseline log:
`/workspace/recovery-evidence/pump-path-baseline-adjacent-tests.log`.
These failures are disclosed rather than bypassed; required integrated
validation must use the applicable pinned runtime. Exact-source economic guard adaptation
must authenticate only this reviewed filesystem-function delta; a focused
PASS is not full release validation or authoritative readiness.
