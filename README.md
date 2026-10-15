# The Meme Machine — PAPER

One Python supervisor runs Pump Current/Survivor and Pons Current/Survivor from
committed source. The prepared launch uses a separate $1,000 shared Decimal
portfolio with $50 initial targets and eligible $25 additions, pending explicit
policy, initialization and PAPER approval. The historical $500 portfolio and its
accounting remain preserved. Meteora and
Ramses are PAUSED indefinitely; their code and historical accounting remain.
Existing positions reconcile before discovery resumes. There are no wallet keys,
transaction signers, real trade submissions, owner permits or live-money switch.

Start here: [OPERATIONAL_STATE.md](OPERATIONAL_STATE.md).

The current release and activation preparation is
[Pump-first release](operational/pump-first-release/HANDOFF.md).
Source inclusion does not activate that portfolio or authorize provider spending.

Migration completeness must pass before deployment acceptance. Robinhood USD valuation
uses its existing RPC and the verified Chainlink USDG/USD feed. No genuine
portfolio epoch, market execution or deployment occurred during consolidation
or the read-only oracle repair.

With CPython 3.12.14 and `pip install -r requirements.txt`:

```sh
python -m operational.tests FAST
python -m operational.tests OPERATIONAL
python -m meme_machine.operational check
```

`check` validates runtime and provider configuration without network I/O or state creation.
Tests use temporary synthetic portfolios and prohibit market provider calls.
SQLite 3.45.1 and 3.53.1 were explicitly tested. The only external runtime
dependencies are pinned in `requirements.txt`, including the Model B native stream client.

The ordinary source is under `meme_machine/lanes/`, shared services under
`meme_machine/runtime/`, and the supervisor under `meme_machine/operational/`.
The independent `dashboard/` reads bounded snapshots; it cannot write capital,
call providers or control trading. Render cutover follows operational acceptance.

Deployment assets are in `deployment/`. Later acceptance on existing Droplet
605465049 is [CAPACITY → RECOVERY → AUTONOMY](operational/ACCEPTANCE.md).
It measures machinery and reports P&L without a profitability requirement.

Historical development and qualification material remains in Git history.
[Inventory](OPERATIONAL_CONSOLIDATION_INVENTORY.md), source equivalence and
offline check results live under `operational/`; none grants execution authority
or forms a startup dependency.

[Incident reference](operational/INCIDENT_REFERENCE.md) preserves production
engineering findings, exact historical attribution and unresolved evidence limits.
