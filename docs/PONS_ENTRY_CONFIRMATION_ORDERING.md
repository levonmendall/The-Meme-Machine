# Pons entry confirmation ordering repair

Base: `131771154c741159d047df07a6c3eb055ed7d0e2`.
Base certificate: GitHub Actions `36209857990`, verified successful at that exact SHA.
Branch: `repair/pons-entry-confirmation-ordering-20260925`.

The Pons source remains `3de3d376847531ccb90e260cfcc96c37587ccb23`.
Policy hash before and after:
`19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84`.

## Defect and repair

The unmodified composed production `run_lifecycle` was exercised with its native
reservation, journal and cancellation path and a simulated 20-second persistence
phase. It returned `entry_quote_stale_after_confirmation`, quote age 20 seconds,
and zero entry tokens. This reproduction preceded implementation.

Previously: reserve → delay → executable quote → broad persistence → age check.
Now: reserve → delay → anchor quote → broad persistence → generation check →
new executable quote → bounded current validation → generation-fenced native commit.

The anchor acquisition preserves the existing persistence inputs. It is never the
final executable quote. The final acquisition uses the original native quote,
identity and finality machinery and the same two-transport pinned read batch.
No timestamp is rewritten. Current snipe state is exposed from the already-read
pinned response, requiring no extra read. Existing impact and round-trip thresholds
are applied to current executable state without changing the reserved amount.

If the final frontier is unchanged, the persistence result is reused after exact
block-hash/time/state agreement. If it advances, two authoritative header pins and
one exact log interval are checked, with at most 256 blocks and 32 events. Event
headers and receipts use the existing authenticated decoder and hash-pinned
immutable receipt cache. Retained authenticated events are reused for current
rolling demand; no new trajectory acquisition or 60-second history search occurs.
Missing completeness, conflicting pins, excess capacity or adverse demand fails
closed. Rolling cache rows alone are not treated as a completeness certificate.

The final age check accounts for actual wall time and monotonic elapsed time,
including quote acquisition latency, immediately before the native commit. A
Candidate Plane transaction fences generation changes through commit; native
projection callbacks run after that transaction to avoid recursively locking the
same database. The native journal remains authoritative across callback/restart
boundaries. Existing restart guards and explicit recovery requirements remain.

## Deterministic evidence

The native-quote fixture runs real quote parsing, finality recording, paper entry
and journal writes, with an offline RPC and simulated clock:

| Measure | Old ordering | Repaired ordering |
|---|---:|---:|
| Simulated broad persistence time | 20 s | 20 s |
| Final quote phase | Before persistence | After persistence |
| Final acquisition phase | 0.5 s fixture | 0.5 s fixture |
| Quote age at decision | 20 s, cancel | 0 s, commit |
| Quote logical reads | 8 | 16 total, 8 per acquisition |
| Quote physical transports | 2 | 4 total, 2 per acquisition |
| Provider work after final quote, unchanged frontier | Not applicable | 0 |
| Broad reconstruction after final quote | 1 | 0 |

The persistence latency is simulated; its provider work is stubbed and is not a
measurement of real market reconstruction cost. An advancing frontier has bounded
additional header/log/receipt reads and may still fail the unchanged five-second
limit. No real-market speedup, fill rate or profitability is inferred.

Runtime output preserves persistence elapsed time, final acquisition elapsed time,
quote age, before/after quote provider telemetry, post-quote provider sessions,
delta scope and retained-event reuse count. Existing telemetry retains logical
requests, physical HTTP requests and immutable-cache reuse separately.

Focused tests cover native entry after slow persistence, real final-quote
staleness, quote reuse and timestamp forgery, finality/identity rejection,
zero/unavailable output, snipe state, current impact, hard demand/creator gates,
thesis decay, bounded exact deltas, superseded generation and duplicate delivery
after a durable entry. Existing recovery fixtures stub the new execution validators
at the same boundary as their pre-existing quote mocks; their native accounting
and recovery assertions are preserved.

Full Pons suite: 398 tests passed. Composed Candidate Plane/provider checks: 66
passed. Full exact-SHA certification results must be read from the associated
local/hosted certificate, rather than inferred from these component counts.

## Retained replay

`python -m certification.pons_entry_confirmation_replay` reads the existing
`certification/evidence/robinhood-runs-355-368.json.gz` without rebuilding it.
Dataset SHA256: `1be70cb9f53bfc9bce039f6913813a6d2a0a21dde39b6b10bf95b9123f47597f`.

Seven quote ages remain 19, 18, 21, 28, 27, 18 and 17 seconds. Four have staleness
as their only listed hard invalidator. Two also have nonpositive net demand;
one also has creator distribution and nonpositive net demand. All original
persistence reasons remain recorded and binding, including the four cases without
another hard invalidator. Fresh historical executable quotes, rescued fills and
profits remain **UNMEASURABLE**.

## Composition and authority

One new overlay, `certification/patches/pons-entry-confirmation-ordering.patch`,
applies after all existing Pons overlays. The Run 369 accounting overlay is intact.
`sources.json` declares the overlay and composed diff identity. Only that identity
is also updated in `profitability_protocol.json`; no portfolio or economic gate
changes. The additional hosted wrapper invokes the existing non-market workflow
on this repair branch with `[non-market-cert]`. It launches no market workflow.

PAPER ONLY. No market run, strategy threshold or policy-hash change, freshness
relaxation, provider-limit increase, sizing increase, exit-policy change, new
strategy-development provider collection, deployment or Render interaction.
Pump, Meteora and Ramses runtime manifests/overlays are unchanged.
