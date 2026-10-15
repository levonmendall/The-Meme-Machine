# Replay capability and standing operational authority — 2026-10-15

**Standing authority adopted; current requests accepted; historical replay cause
and exact recovery contract remain unresolved.** Read owner
[issue134](https://github.com/levonmendall/The-Meme-Machine/issues/134).
Global three-start limits, 24-hour expiry and routine per-run approvals are removed
from AGENTS.md, the operational-resolution skill and active specification wording.
Existing per-run one-start, readiness, protection, resource, recovery and shutdown
safeguards remain. Diagnosis stays funding closed until original normal-operation
gates pass. Original RECOVERY_REQUIRED results are unchanged.

| Source | Identity |
| --- | --- |
| Executed standalone diagnostic | `5e4728ae2208a90fb027ce951d3a6830f93f18b2` |
| Standing workflow | `70e6e25c9329862da209136ae8a148b73e4895fd` |
| Focused-tested offline attribution successor | `6b0b10edf729b4c1c13dd3b7a56916d4d6797bc4` |
| Installed source, unchanged | `66f85d61bf4d3ba9a01efdc0e9eb68949419bda8` |
| Branch | `repair/consolidated-startup-followup-20261014`, draft PR 133 |

## Actual provider result

The single authorized experiment completed in **3.380 seconds**, inside its
45-second absolute boundary. It used the existing authenticated endpoint,
2-RPS shared admission and durable provider accounting. One concurrent stream,
two total subscriptions, 64 messages per stream, 22,791 delivered native protobuf
bytes. All reservations and the TLS channel closed. No PAPER start, economic,
canonical, candidate-history or policy write occurred.

Native first_available was 456190360. Native and HTTP finalized tips both equalled
457055103. The unchanged common cursor was 457054847, exactly HTTP tip minus 256.
Both exact FINALIZED control and scout requests returned matching data and reached
the 64-message limit. No INVALID_ARGUMENT occurred, so **the conditional CONFIRMED
comparison was not run**. No offset, commitment, subscription or provider changed.

Offline decoding verified every retained protobuf length/hash and request identity:

- Control: 32 finalized slot updates plus 32 block metadata updates, 457054816–457054847.
- Scout: 64 Pump account updates, 31 public keys, correct owner/discriminator,
  filter p and 49-byte data slices,457054816–457054825.
- Both began 31 slots before the requested cursor, consistent with an apparent
  32-slot boundary in this sample. One sample does not establish chunking semantics.

**Current filter/commitment compatibility is observed.** Historical replay failure
is not reproduced or repaired. The bounded control sample ends at the requested
cursor; scout samples are all before it. Neither proves complete post-cursor
history, canonical economic coverage, throughput or position protection. Same TLS
channel/istio-envoy metadata does not establish same replay backend.

No provider configuration fix or source-architecture replacement is justified
from these observations alone. The exact lower-bound/skip-slot/backend contract
is the missing technical fact. The existing join already excludes pre-floor
frames from economic coverage; it is not permission to invent completion for
missing slots. No arbitrary cursor alignment/shift or repeated experiment was made.

## Next technical boundary

The [sanitized Alchemy support question](ALCHEMY_NATIVE_REPLAY_SUPPORT_QUESTION_20261015.md)
is prepared, not sent. It asks how accepted cursors, skipped slots, per-filter and
per-commitment history, backend affinity and earlier-than-cursor delivery relate
to first_available and the original rejection. Clarification/configuration on the
existing provider is the first decision. A recovery architecture change is only
justified if that contract proves the existing authenticated mechanisms insufficient.

**No unchanged replay experiment or combined retry is justified by acceptance
alone.** Provider semantics/causal evidence remain missing, rather than routine
owner authorization. A distinct funding-closed combined observation is justified
by the reproduced Pons cancellation correction and new main-thread attribution,
provided fresh safety preflight passes. Its question is actual native lifecycle
and pipeline accumulation, not the long-term replay contract. Existing joins
exclude pre-floor frames and require complete linked evidence; no gap or cursor
is relabelled complete. Another semantic rejection ends collection safely.
Proceed under issue134 for that independently justified next step. Do not request
another generic resume approval or restore global attempt/expiry limits.

## Pons offline progress and safety

A disposable real cohort fixture demonstrated that its SQL prelude can wait on a
writer before cooperative shared replay cancellation is consulted. It retained
the original 30-second SQLite timeout and exact journal/pending state; the test
lock was held below 0.25 seconds. This is a supported boundary characterization,
not attribution of the historical Pons -9 and not a SQL repair.

The successor adds one bounded cancellation stack snapshot from the existing
health thread after stop. It records at most eight owned Python module/function/
line frames and actual reporter/main-thread identities. No locals, paths, SQL,
source text or extra thread. Missing/failed capture stays unavailable, never
changes readiness and cannot replace the first application error. Final health
and the actual diagnostic serializer preserve it. Existing 0000a4f8 constructor
cancellation and original shutdown deadlines remain unchanged.

Fresh read-only applicability at 01:34:25 UTC: **15 checks VERIFIED; 132 bounded
queries / 0.018 seconds SQL, 0.150 seconds total**. Cash $1,000, raw head 8990, no
monetary obligations, historical $500 unchanged. Current session/checkpoints,
32 exact ACKs, older pending work and proof/outbox witnesses are preserved;
owners dead, leases inactive, writer lock unheld. Existing recovery reference
and 301 retained entries remain applicable. This permits existing guarded recovery
in the checked scope; no retroactive native-drain PASS or future recovery proof.

PAPER remains stopped/failed, disabled, Restart=no, funding closed. Installed
source/configuration and all six opportunity changes, nine economics and volume
attention remain intact. Original SQLite BUSY, Pons READONLY, actual native drain,
sustained capacity, managed-Pons complete protection, backup failure and backup/
protection compatibility remain separate. No acceptance time accrued.

## Validation and usage

- Standalone requests/errors/deadlines/accounting/cleanup plus SQL boundary:
  **13 PASS / 3.548 seconds**. Initial 13-case run failed five assertions: original
  rejection headers were overwritten by cleanup probes, expired admission skipped
  channel teardown, and close left no final-recording margin. All were corrected;
  original failures are retained and assertions were not weakened.
- Changed native attribution, actual integrated startup/lifecycle and diagnostics:
  **107 PASS / 7.036 seconds**, including 13 actual integrated rehearsals.
- Exact economic/source guard: **1 PASS / 7.754 seconds**.
- Pinned CPython 3.12.14 / SQLite 3.45.1, contained network-blocked runner, one
  integration/test owner. No complete FAST repeated; no full release PASS claimed.

Usage: five physical starts total (two unary, one HTTP, two native subscriptions),
three Solana unary/HTTP logical elements, 40 modeled CU, 55 unary/HTTP protobuf/JSON
bytes and 22,791 native protobuf bytes. Conservative uncertain native SDK accounting
is 134,217,728 bytes, **not confirmed delivery**; remaining reservations are zero.
Existing frozen model including that uncertainty: **$0.014116254495**, not an invoice
or verified provider charge. No old spending ceiling was restored.

Exact private locators/hashes and analysis:
[native-replay-capability-result-20261015.json](evidence/native-replay-capability-result-20261015.json).
Large state stays in place; no bulk copy, replay reset, source installation,
backup-timer change, quota increase, provider migration or infrastructure purchase.
