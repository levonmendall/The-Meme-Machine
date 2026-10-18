# Exact EA performance successor, 2026-10-18

The operational baseline is application main
`b10b7a13a0e872038018a43816e2ff0f75c93e55`, tree
`4d4493fc3b07e71ab57ea64098463028f999d03d`, identical to the approved and
installed EA source `ea7221c3d858ffa8799cd02bfa83a576906f6c21`.
This candidate changes exactly three runtime files. It contains no dormant
isolated-live, normal-boot, source-generation or new cohort hooks.

* Pump component `759e24dfa4ca73ea8c747d951c9e20f7c288ebf7` retains complete
  coherent source captures across the original bounded 25ms read leases.
  It preserves body/hash/archive/manifest authentication, cancellation, byte
  limits and original-order scalar fallback. Its new fixed operation name is
  `pump.restore_source_capture`; the original 20 restoration counters remain.
* Pons component `e0a95ec2dea33daa3b054511974a9a0bdb512d27` caches completed
  namespace retention work behind exact semantic revision triggers. All raw,
  peer and legacy evidence/obligation mutations invalidate the affected token.
  Schema validation, the original retention predicates and ownership remain;
  publication follows the original transaction's successful exit, including
  the original no-write ROLLBACK behavior.

The combined frozen runtime is
`6eb8ab1ba1702224c1354c570db4f87aeb7b5ccd`, tree
`70319a41b9f766c9608153d8c6057a4c7fb2fbca`. Its complete changed runtime
sources are:

| Path | SHA256 |
| --- | --- |
| `meme_machine/runtime/candidate_restore_reads.py` | `d968a422bf83c2f5029a5f282cbd15a677ba8dcfbbca717e6e478119da8a50de` |
| `meme_machine/runtime/operation_costs.py` | `c3fccb8bef2c207dae72b0c9d8405d13b700692de746d825a3382cd6bdd08d22` |
| `meme_machine/runtime/robinhood/plane.py` | `af3b14b42233e0c72e91ba52190c6212ca9ddea576fa0109115f06047343fadf` |

The new test-only outer proof reconstructs all three complete b10 source files
and all three whole protected guard files. Ten explicit fresh-read wrappers
run before the unchanged EA16 and older source/economic guard chains. Original
exported predecessor bodies, assertions, constants and mutation calls remain
unchanged. The immutable EA16 fixture SHA256 remains
`f1982ceef86d7acab5666c66bf951651d0f565dfd765300b691195b372f1b79c`.
The new fixture is 127368 bytes, SHA256
`9b99d04abfa913311a0c7dc771390908a3a60e4c36f88c4f241d6ba4fc0a8e50`.
The fixed changed-source census rejects extra, deleted or modified tracked
inputs and unlisted untracked/ignored runtime inputs. This is source-check
test provenance, not runtime source authorization or financial readiness.

Validation used the original offline FAST runner, network guard and Scratch:

* 20 source-integrity cases passed in 13.168s.
* The actual recorder → existing dynamic collector → retained JSON projection
  regression passed in 0.003s. No administration whitelist change is needed:
  the installed administration collector/reader imports application `NAMES`.
* 219 combined source/strategy, Pump restoration, Pons retention/protection,
  startup cancellation and shared-capital recovery cases passed in 180.781s,
  with no skips or failures. The unique total across these runs is 235.

The first combined selection was refused before executing tests because it
named a nonexistent checkpoint module; its log was retained. The corrected
selection used the actual existing protection module. No assertion was changed
to address that selection error. Complete FAST/OPERATIONAL release suites were
not run for this funding-closed diagnostic candidate.

Component-level matched measurements and their limits are retained in
`pump_restore_reference_pages.md` and `pons_evidence_retention_revision.md`.
Local native Python uses SQLite 3.53.1; separate pinned 3.45 C-API checks do not
establish Python-engine timing parity. In particular, the Pons revision writes
add measured issued-write overhead on receipt publication. No AWS performance
improvement has yet been established for this combined candidate.

All 22 direct recovery-module blobs remain identical to the installed EA
compatibility proof. No provider, financial, strategy or source-control module
changed. Original historical callback completion remains false/unknown; the
two unknown dispositions are preserved. Last supplied AWS financial receipt
was portfolio sequence 16758, $1000 cash, no positions and all nine obligations
zero, unchanged by recovery 39096889719. These local tests did not access AWS
financial state.

The next authorized comparison must deploy an exact approved source through
the existing controls. It remains a capacity discriminator. Existing
`canonical_backlog_population` and `eligible_input_rate` are unknown; frames and
slots are different populations. Improved restoration time or head-gap proxies
cannot establish sustained full economic-market throughput, normal readiness
or one-hour autonomous PAPER acceptance.

## Hosted fixture correction

Focused GitHub CI 39098442871 on `593dedc3914a42af1e91a21d51a47295562b423b`
failed one of 1301 cases in 333.514s (four existing skips). The unchanged
stalled-startup child query finished in about 7.204s, between its first eligible
roughly-six-second health publication and the next two-second heartbeat. The
test sent TERM after the first publication but required two records before the
deferred handler became visible. The exact original case passed locally in
9.587s; the fixture, reporter and status source were byte-identical to b10.
The failing GitHub receipt remains a failure.

The first test-only barrier correction, head
`df1db5c9818c1e968da1cd6b656fa0af364049e6`, passed its exact case locally in
19.845s and its 12-case module in 16.892s. However, hosted CI 39099344192
failed the same case in 325.247s across 1301 cases (four existing skips): a
health row already had `query_active=false`. That correction's constant-only
recursive query never referenced the locked database. The local SQLite 3.53.1
lock observation did not prove the same dependency on hosted SQLite 3.45.1.
The original failure and this second failed head remain failed receipts; the
first correction's portable-lock claim is withdrawn.

The corrected fixture now seeds the same aggregate's recursion with
`SELECT id-1 FROM fixture_barrier WHERE id=1`, from the disposable database's
single row `(1)`. This is an actual table read in the same SQLite `execute`
call as the recursive aggregate. It keeps seed zero, recursive limit
60,000,000 and sum 1,800,000,030,000,000. There is no preceding blocking SQL
call that returns to Python while TERM is pending. The parent still holds the
disposable DELETE-mode database EXCLUSIVE, sends TERM after the first genuine
health record, and releases only after a second nonterminal, query-active
record with no observed signal or set cancellation Event. No Python UDF,
progress handler, sleep-based signal deferral, reporter change or SQL
interruption is introduced. All original result, two-record, zero-handler,
SIGTERM, owner-join and 25-second outer assertions remain.

A new shared-query discriminator uses a zero recursive limit: while the lock
is held, the query must return actual `SQLITE_BUSY` or `SQLITE_LOCKED`; after
release it must return zero, and a limit of 1000 must return 500500. Its locked
failure cannot be explained by recursive CPU work. This passed locally in
0.053s with `SQLITE_BUSY` (5). The corrected original child case passed in
16.661s. The final 13-case module passed in 16.986s without skips or failures;
its actual child recorded six pre-handler health samples, the first after
6.002s, the complete expected sum, zero progress handlers, SIGTERM 15 and a
joined health owner. These observations retain the original signal semantics;
they do not separately attest SQLite's internal prepare-versus-step boundary.

All production runtime, source-proof and old guard bytes remain identical to
the already-reviewed performance candidate. The previous 235 focused checks
remain evidence for those unchanged bytes. Fresh exact-head GitHub checks are
required; neither failed previous head substitutes for them. No deployment or
AWS performance gain is claimed by this fixture correction.
