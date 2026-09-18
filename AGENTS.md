# Scope and execution rules

- Preserve the Pump/PumpSwap contract. The authorized stacked DLMM branch adds only
  Meteora SOL-paired mechanical paper replay; prospective DLMM allocation stays disabled.
- Wallet scouting does not grant purchase authority. Preserve independent policy
  gates, point-in-time evidence, integer accounting, one shared $500 genesis and
  disabled DLMM. Never force a trade or change defaults to improve test outcomes.
- No live money, signing, transaction submission, new costs, merges, deployments,
  repository visibility changes or changes to predecessor repositories/services.
- Preserve current work. Read BUILD_STATUS.md before continuing; avoid broad audits.
- Python 3.12.14; run `python -m unittest discover -v` and resource checks.
- Keep synthetic, captured and prospective experiments separate. Never claim live
  lifecycle, CI success or profitability from fixtures or zero trades.
- Keep secrets, .env files, raw private evidence and runtime DBs out of Git/logs.
- Feature commits and pull requests authorized; main is not implementation authority
  until separately approved. Record exact evidence and next blocking task.
- For DLMM continuation, read DLMM_STATUS.md. Keep PRs #1/#2/#3 independent; do not
  merge or deploy. Run the full unit suite and both resource checks. Real swap fee
  proof requires a verified complete finalized mutation interval; zero swaps and
  synthetic RPC responses do not establish it. Do not weaken freshness or token gates.
