The public native workload is a contained engineering alternative for testing
decoding, candidate persistence and restoration against actual public traffic.
It always reports `PARTIAL_NATIVE_ALTERNATIVE` and exits 2. It supplies no PAPER
readiness, historical recovery, financial protection or acceptance attestation.

The separate administration approval and `native-validate` / `native-observe`
actions use the existing unprivileged public-observer workflow. They execute a
verified application commit/tree in a scrubbed environment, require PAPER to be
stopped and disabled, and retain a private corpus and summary. Provider methods
are read-only, endpoints fixed, starts globally paced at least one second apart,
with 150 requests, 16 MiB per response and 64 MiB aggregate corpus limits. A 429
closes acquisition for both lanes. The fixed outer process boundary is 225 seconds
followed by TERM and six seconds to KILL. Native Python work is joined before its
SQLite owner closes; bounded native cancellation itself remains unproven.

| Path | Reused processing | Remaining production capability |
| --- | --- | --- |
| Pump/PumpSwap | Full public blocks, production economic decoders, FULL SQLite candidate transactions, ordered history reads, actual Pump creation restoration | Authenticated native stream, canonical source preparation and FULL/ACK delivery, cold-reference volume, qualification and held protection |
| Pons | Native MarketScout, Broker, Pipeline, receipt/header event decoding, economic normalization, candidate/history persistence and actual reopen | Managed canonical acquisition, physical batching, complete Current/Survivor hydration and canonical history, held protection |

Public blocks cannot truthfully be labeled `alchemy_finalized_stream` or
`alchemy_finalized_repair`. The production source guard retains that distinction.
The AWS administrative runner cannot read production provider secrets or write
production financial state. A complete disposable production run therefore still
requires an isolated authenticated provider capability and a native no-funding
boundary; this public alternative supplies neither by bypassing those guards.

Each attempted input has a durable body hash. Completion is recorded only after
native consumption returns. Pons RPC responses are linked to the exact attempted
window. Failed partial windows stay retained and are excluded explicitly from
completed-input comparisons. The summary records separate attempted/completed
counts, sampled chain-head/backlog populations, process CPU/RSS/I/O and host I/O
pressure. Cgroup totals, canonical economic backlog and held protection are
reported as unavailable or unproven.

Pump acquires `getBlocks` lists for at most40 slots with finalized commitment.
Only returned block slots enter decoding and completed-input comparisons. Missing
slots are retained as provider-enumerated absences, without an empty economic
block or an on-chain skip/completeness claim; finalized public backends can
disagree. The corpus retains the enumeration RPC responses and the progress
summary retains their exact slot populations. Total sampled head span,
unenumerated head span, returned blocks and reported absences remain separate.
Pump backlog counts only provider-enumerated available blocks awaiting decoding;
zero in that population never proves complete market processing.

Failure summaries retain explicitly allowed literal component codes and, for a
native Pons boundary, only its application module, function and source line.
Provider JSON-RPC rejection receipts retain only the approved method and a signed
32-bit integer code; provider messages, data and arbitrary exception text are
excluded.

For an exact-input replay, use
`isolated_native_workload.replay(corpus_path, fresh_private_root, expected_sha256)`
on another verified checkout. Supply the whole-file SHA from the retained capture
summary. The replay verifies the file and every event/request/response binding,
preserves response order for each identical request within its completed window,
and requires every linked response to be consumed once. Calls with different
request keys may be interleaved differently; there is no network fallback.
Public slot enumeration is acquisition evidence outside the decoded replay
workload. Compare logical candidate/economic hashes and restoration output before
interpreting timings. Public provenance remains public after replay. Use the
separate exact-source Pump benchmark for authenticated cold-reference fixture
comparisons; its measured synthetic result is retained in this repository.

Focused integration checkpoint on CPython3.12.14: 47 network-blocked tests passed in0.397s across public transport/corpus/cleanup/replay and actual Pump/Pons component modules. This includes strict source/funding isolation, original malformed/partial input, SQLite ownership, cancellation, restart and failure evidence. Completed-corpus replay orchestration also has deterministic fake-native contract tests; these checks do not supply a live market or production release pass.

An additional real combined integration case passed using both actual native projections and the same recorded corpus through the real two-thread replay. It preserved Pump logical/block hashes, Pons economic/candidate/pending populations and original clocks, restoration, joined/closed owners and unchanged corpus bytes. The new native modules therefore have48 passing focused cases;17 affected observer cases also pass.

The review correction adds seven focused cases for public block enumeration and first-cause privacy. The affected workload/replay modules pass36 cases in0.305s, including the actual combined replay; unchanged Pump/Pons modules retain19 passing cases (55 native cases total). The first integrated candidate55be669d passed GitHub focused run39055442178:1066 tests/380.005s/two configured skips. That earlier receipt is scoped to its exact source, and is not final release evidence for this correction.
