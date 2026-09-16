# Build status / continuation

## Repository and authority

Repository: `levonmendall/The-Meme-Machine`, verified **public** on 2026-09-16.
Authorized minimal `main` initialization remains
`54712c4c6470cc4dc267888f934bd693aac030d0` (README only).
Implementation branch: `feat/pump-directional-paper`. PR #1 remains the review boundary.
No predecessor repository, deployment, provider configuration or production state was
modified. Do not merge, deploy, purchase services or enable live trading.

The reviewable implementation is branch HEAD. Resolve its exact commit with
`git rev-parse HEAD`; GitHub Actions attaches verification to that SHA. Do not
substitute `main` for this implementation.

## Implemented boundary

Pump.fun standard SOL bonding curves, including metadata-only Token-2022 mints:
wallet scout → independent continuation-v1 qualification → shared allocator →
reservation → later finalized quote/attempt → settled spot position → scheduled
monitoring → delayed exit → settlement → restart reconciliation.
The paper fill model is `pump-sol-cp-v1`. DLMM allocation is disabled. Other named
markets remain planned; there are no placeholder working adapters.

One CPython 3.12.14 app, no third-party dependencies, one SQLite writer. Raw account
bytes embedded with orders preserve quote evidence. Startup/status do not scan full
history. Synthetic/captured/prospective modes and seed configuration are persisted
and cannot silently change on restart.

## Deterministic evidence

The original milestone passed 34 tests. Bounded prospective-validation work added
funnel/gap/retry/point-in-time regressions; the exact current-head workflow continues
to run the complete deterministic suite, bounded 240,000-event resource workload,
and synthetic connected lifecycle. Current exact-head push CI is green for both the
`test` and `live-diagnostic` jobs.

Synthetic/captured results remain software evidence only. They are not market-driven
portfolio results or profitability evidence.

## Prospective-validation repairs and instrumentation

Review found that historical `gaps` were originally an eternal entry veto. A transient
public-RPC gap could therefore prevent every later entry even after its potentially
missed 60-second nomination window was stale. The repair preserves gap history but
uses `entry_quarantine_until` to fail closed only for the affected signal window.
Repeated gaps extend quarantine; existing positions retain monitoring/exit priority.
This did not change any continuation-v1 strategy threshold.

Status exposes bounded funnel counts for scout batches, new observed events, seed
events, nominations, qualification attempts, qualified candidates, entries and
settled exits.

`evidence/unvalidated_seed_watchlist.json` contains public finalized Pump.fun buyers
with exact discovery provenance. They are observation-only scouts: no skill claim,
sizing influence, or purchase authority. Their discovery trade is excluded from
future nomination authority; only events after scout admission are admissible.

Provider diagnostics now classify failures without exposing URLs or bodies. The real
HTTP path has at most one paced, budget-counted retry. The repeated validation
workflow no longer runs unrelated scout-census/live-probe requests immediately before
qualification, and the qualification diagnostic evaluates fresh unique nominations
immediately rather than waiting until all scouts have been polled.

The diagnostic also stops polling later scouts once its two-unique-mint evidence
budget is spent. This is a read-only RPC-efficiency change: work that cannot affect
that bounded run's outcome is not performed. It does not alter market eligibility,
entry sizing, or exits.

## Latest exact-head prospective evidence

Exact head for this evidence: `73a7fb170dc9e59847b1951a2f65fc6a7b05fb35`.
Push workflow run: `35160692595`. Both jobs passed.

The admitted-scout shadow run observed 9 admissible events from the active admitted
seed and produced 4 natural nominations. It immediately attempted two unique mints,
with signal ages about 18 and 22 seconds. Both reached account inspection and were
rejected at `initial_snapshot` as `unsupported curve mode or quote asset`:

- `5Re47wrh5ww6RUfLndqpRr24VA3XGzCVLzkQ93GCpump`
- `3NPxFq3VBo3br7uN2HLEiMK1sc71vMtxDUcmoXwQpump`

Those are implementation-scope rejections, not continuation-v1 economic rejections.
They do not prove a supported standard-SOL candidate would qualify.

The efficiency change removed the public-RPC failure seen in the immediately prior
runs: this exact run used 14 RPC requests with **0 failures, 0 retries, and no HTTP
429s**, then deliberately stopped before polling later scouts because its two-mint
evidence budget was exhausted. Cash was unchanged; orders, reservations, positions,
and paper trades all remained zero.

Earlier bounded runs repeatedly produced HTTP 429s. Those remain relevant provider
capacity evidence, but the current reduced-RPC path shows the present bounded proof
can proceed without a 429 when it stops once useful evidence capacity is consumed.
Do not broaden the curve parser or loosen strategy rules merely to obtain a supported
candidate.

## Limits / acceptance

This remains bounded real-data diagnostic evidence, **not prospective operational
acceptance or profitability evidence**. No supported standard-SOL Pump.fun nomination
has yet reached full `evidence_stage=complete` qualification, and no market-driven
entry-to-settlement exists.

A shadow `qualified` result would still not be a paper trade. A real market-driven
lifecycle requires durable state that can be resumed through entry, monitoring, exit,
and settlement. Ephemeral CI diagnostics therefore have no order authority.

Quotes remain hypothetical execution evidence rather than guarantees of landing,
future gas, or own-trade market response. Graduation outside the implemented surface
can leave an unresolved position. No LP fee engine, partial exits, re-entry, scaling,
or strategy evolution is enabled. Wallet performance remains unvalidated.

## Exact next task

Continue **Pump.fun-only bounded observation of the already-admitted scouts** with
unchanged continuation-v1 until a naturally nominated **supported standard-SOL**
Pump.fun curve reaches full qualification evidence. Report its exact accept/reject
reason; do not force qualification.

Use the reduced-RPC live diagnostic. At most one bounded observation attempt should
be made per monitoring interval; do not hammer the public endpoint. If HTTP 429s again
repeatedly prevent useful coverage under this reduced path, stop repeated observation
and treat read-only RPC capacity/efficiency as the next engineering boundary rather
than modifying strategy thresholds.

Do not add DLMM or another venue to avoid this boundary. Do not merge, deploy, add a
paid provider, enable live money/signing/submission, or create a paper position on an
ephemeral GitHub runner.

Reproduce deterministic checks:

```sh
python -m unittest discover -v
python -m tests.resource_check
python -m tests.make_tape
python -m meme_machine --mode synthetic --config config.synthetic.json --db /tmp/meme-fresh.db --tape tests/fixtures/synthetic_lifecycle.jsonl
```

Bounded admitted-scout shadow diagnostic:

```sh
python -m tests.prospective_qualification
```
