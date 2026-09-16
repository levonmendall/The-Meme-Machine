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

- 34 local tests pass: connected profitable/loss-making synthetic paths, meaningful
  nonqualification, unavailable exits, failed/stale entry attempts and fees,
  duplicate/conflicting delivery, shared capital, disabled LP, open/reserved restart,
  lost fill acknowledgement, actual subprocess termination before/after commit,
  checkpoint/journal corruption, accounting damage, mint restrictions, fee tiers,
  real captured decoding and independent monitoring.
- `evidence/local_tests.txt` contains the test transcript. Repeat on final HEAD.
- `evidence/resource_check.json`: 2,000 synthetic frames / 240,000 submitted events;
  queue admission 100/frame, dedup <=1,000, decisions <=100, gaps <=20.
  Approximately 1.25 MB DB + 0.62 MB WAL and <20 MiB peak RSS on this host.
  This is a temporary-memory-filesystem workload, not a continuous-market or
  physical-disk/power-loss benchmark. WAL FULL and process-crash behavior are tested.
- `evidence/synthetic_result.json`: one synthetic profitable lifecycle; not market
  performance. Separate losing-path assertions are in the connected tests.
- Public mainnet genesis verified. Three public RPC captures in `tests/fixtures`
  contain a finalized Pump sell at slot 447633818 and a later live curve/mint/fee
  snapshot at slot 447634246. The token is not our paper position.
- `evidence/live_probe.json`: real read-only scout probe, two RPC requests, zero
  errors and no buys in the sampled recent wallet window; no portfolio initialized.
- `evidence/prospective_probe.json`: pre-commit 30-second bounded live application
  run, four requests, three worker cycles, zero provider failures, zero nominations,
  zero paper trades, zero fees and zero realized P&L. Initial $500 converted once
  at recorded $97.84/SOL reference; current USD NAV is deliberately unknown.
  Its `-dirty` release label is explicit; this is not exact-final-release evidence.
- Public RPC required no credential. Coinbase's optional price HTTP lookup timed
  out; initial reference was obtained independently through web finance. No paid
  provider, subscription or infrastructure was created. `MM_SOLANA_RPC_URL` is
  optional; no missing RPC credential is claimed.

## Limits / acceptance

This is executable offline milestone evidence plus a real-data smoke run, **not
prospective operational acceptance or profitability evidence**. No market-driven
entry-to-settlement occurred. Keep `operational_acceptance=false` and
`profitability_evidence=false` until independently earned.

Quotes model hypothetical costs; they do not guarantee landing, exact future gas,
or exact own-trade market response. Finalized snapshots can be too old; that blocks
entries. Graduation outside this surface leaves an explicit unresolved position.
No LP fee engine, partial exits, re-entry, scaling or strategy evolution exists.
Wallet scorecards are bounded/unvalidated cash-flow observations, not complete
wallet returns; full balance boundaries, network-fee attribution and comparative
wallet/control performance remain research work before any skill-based influence.
Gaps block new exposure and require explicit evidence-preserving review; exits stay
scheduled. Rare finalized reorganization economics are not automatically repaired.

## Exact next task

Continue from this branch/PR after reviewing CI. Run repeated **budgeted prospective
Pump.fun-only sessions** with recorded unvalidated seeds and the same persisted
ledger until natural nominations provide independent evidence. Establish a real
market-driven entry → monitored exit → settlement, or preserve explicit rejection /
provider-gap evidence. Do not loosen defaults or force trades. Do not add DLMM or
another adapter to avoid this remaining proof boundary.

Reproduce:

```sh
python -m unittest discover -v
python -m tests.resource_check
python -m tests.make_tape
python -m meme_machine --mode synthetic --config config.synthetic.json --db /tmp/meme-fresh.db --tape tests/fixtures/synthetic_lifecycle.jsonl
```

The working host's ordinary disk was full before this task. Source/test work used
`/dev/shm/meme-build` without deleting prior user work; GitHub is the durable handoff.
Runtime DBs/config.local.json are intentionally not committed. There are no open
positions in the observed live smoke experiment. Do not treat its temporary local
state as a durable deployed portfolio.
