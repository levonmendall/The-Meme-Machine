# Build status / continuation

## Repository and authority

Repository: `levonmendall/The-Meme-Machine`, verified **public** on 2026-09-16.
It had zero branches/commits. Authorized minimal `main` initialization:
`54712c4c6470cc4dc267888f934bd693aac030d0` (README only).
Implementation branch: `feat/pump-directional-paper`, based on that exact SHA.
No previous repository, deployment, provider configuration or production state was
modified. Do not merge, deploy, purchase services or enable live trading.

The reviewable implementation is branch HEAD. Resolve its exact commit with
`git rev-parse HEAD`; the PR and GitHub Actions attach verification to that SHA.
Do not substitute `main` for this implementation. This document cannot embed its
own future commit hash; the delivery/PR records it after commit creation.

## Implemented boundary

Pump.fun standard SOL bonding curves, including metadata-only Token-2022 mints:
wallet scout → independent continuation-v1 qualification → shared allocator →
reservation → later finalized quote/attempt → settled spot position → scheduled
monitoring → delayed exit → settlement → restart reconciliation.
The paper fill model is `pump-sol-cp-v1`. DLMM allocation is disabled. Other named
markets remain planned; there are no placeholder working adapters.

One CPython 3.12.14 app, no third-party dependencies, one SQLite writer. Raw account
bytes embedded with orders preserve quote evidence. Startup/status do not scan
full history. Synthetic/captured/prospective modes and seed configuration are
persisted and cannot silently change on restart.

## Evidence already obtained

- Original milestone: 34 local tests passed, including connected profitable/loss-making
  synthetic paths, meaningful nonqualification, unavailable exits, failed/stale entry
  attempts and fees, duplicate/conflicting delivery, shared capital, disabled LP,
  open/reserved restart, lost fill acknowledgement, actual subprocess termination
  before/after commit, checkpoint/journal corruption, accounting damage, mint
  restrictions, fee tiers, real captured decoding and independent monitoring.
- The bounded prospective-validation patch raised the deterministic suite to **36/36
  passing** on exact GitHub commit `51242c665f55f1843889d4e1d72c6ac806eaf49b`.
  It adds funnel counters and tests the new transient-gap quarantine behavior without
  changing any continuation-v1 strategy threshold.
- `evidence/resource_check.json` baseline: 2,000 synthetic frames / 240,000 submitted
  events; queue admission 100/frame, dedup <=1,000, decisions <=100, gaps <=20.
  The exact prospective-validation CI rerun remained bounded at about 1.26 MB DB,
  0.71 MB WAL and 26,464 KiB peak RSS on the GitHub runner. This is not continuous
  market or physical-disk certification.
- Public mainnet genesis verified. Checked-in captures validate Pump event/account/
  fee decoding. They are not portfolio performance.
- A new read-only Pump program census runs in CI. In run `35158920117` it observed
  one recent finalized buyer. In run `35159048378` it observed two. In push run
  `35159139251` it decoded six recent Pump trade events including four buys from
  four distinct addresses. These are activity observations only, not skill claims.
- The existing captured public seed also produced a real buy nomination in run
  `35158920117`: three wallet events, one buy nomination, nine RPC requests, zero
  provider failures. A later probe on the same seed had no current events. This proves
  the scout can observe a natural buy; it does **not** prove qualification or alpha.
- `evidence/unvalidated_seed_watchlist.json` records three public buyers from the
  first bounded censuses with exact event provenance. They have diagnostic scouting
  authority only: no skill, sizing, or purchase authority.
- Full shadow qualification is now executable in CI without calling `consider`,
  reserving capital, or creating positions. It uses unchanged continuation-v1.
  On push run `35159139251`, four recorded unvalidated seeds produced two observed
  events across one seed, zero current buy nominations, one provider request failure
  on another seed, zero orders, zero positions and unchanged cash. Thus no full live
  qualification result has yet been observed.
- The short Pump-program census reports `program_window_covered=false` because its
  bounded 20-signature tail does not span the full minute on an active global program.
  That diagnostic is not used as market-window authority for entries.
- Public RPC required no credential. No paid provider, subscription, deployment, or
  infrastructure was created. `MM_SOLANA_RPC_URL` remains optional.

## Prospective-validation repair made in this branch

Review found an operational correctness issue in the original prospective path:
`wallet_window_incomplete` and `discovery_data_unavailable` were appended to a
persistent `gaps` list, while the allocator rejected every new entry whenever that
list was nonempty. A single transient public-RPC gap could therefore block new
exposure for the rest of the experiment even after the potentially missed 60-second
nomination window had become stale.

The repair keeps the gap history but fails closed for an explicit
`entry_quarantine_until` covering the complete 60-second signal window. Repeated gaps
extend the quarantine. Existing positions still receive priority monitoring/exits.
After the missing window has fully aged out, unrelated fresh evidence may be evaluated
again. This is a data-readiness/liveness correction, **not a strategy-threshold
change**. Existing databases with legacy gap state migrate conservatively by applying
one signal-window quarantine on first open.

Status now exposes bounded funnel counts for scout batches, new observed events,
seed events, nominations, qualification attempts, qualified candidates, settled
entries and settled exits. `gaps` remains preserved diagnostic history rather than an
eternal trading veto; `active_entry_quarantine` is the current blocking state.

## Limits / acceptance

This remains executable milestone evidence plus bounded real-data diagnostics, **not
prospective operational acceptance or profitability evidence**. No naturally
qualifying market-driven entry-to-settlement has occurred. Keep
`operational_acceptance=false` and `profitability_evidence=false` until independently
earned.

Quotes model hypothetical costs; they do not guarantee landing, exact future gas,
or exact own-trade market response. Finalized snapshots can be too old; that blocks
entries. Graduation outside this surface leaves an explicit unresolved position.
No LP fee engine, partial exits, re-entry, scaling or strategy evolution exists.
Wallet scorecards are bounded/unvalidated cash-flow observations, not complete wallet
returns; full balance boundaries, network-fee attribution and comparative
wallet/control performance remain research work before any skill-based influence.
Rare finalized reorganization economics are not automatically repaired.

## Exact next task

Continue **Pump.fun-only bounded prospective validation**. Re-run the manual/live
workflow diagnostic or a bounded prospective session using recorded unvalidated seeds
and unchanged continuation-v1 until one of these evidence boundaries is reached:

1. a natural nomination reaches full qualification, exposing its exact accept/reject
   reason and executable evidence; or
2. enough repeated observation shows a specific coverage/provider limitation that
   prevents full qualification.

Do not loosen defaults or force activity. Do not add DLMM or another adapter to avoid
this boundary. Do not create a paper position on an ephemeral runner unless its state
can be durably resumed through monitoring and settlement. A shadow `qualified` result
is not a paper trade; an actual market-driven lifecycle still requires durable entry,
monitoring, exit and settlement.

Reproduce deterministic checks:

```sh
python -m unittest discover -v
python -m tests.resource_check
python -m tests.make_tape
python -m meme_machine --mode synthetic --config config.synthetic.json --db /tmp/meme-fresh.db --tape tests/fixtures/synthetic_lifecycle.jsonl
```

Read-only bounded live diagnostics:

```sh
python -m tests.scout_census
python -m tests.live_probe
python -m tests.prospective_qualification
```

Runtime DBs/config.local.json are intentionally not committed. There are no paper
positions created by the CI diagnostics. No merge, deployment, paid service, DLMM,
other venue adapter, live money, signing, or transaction submission is authorized.
