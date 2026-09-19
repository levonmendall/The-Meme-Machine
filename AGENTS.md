# Robinhood foundation continuation

- Repository is GitHub-only. Work on `feat/robinhood-research-foundation`; no Render.
- Read `ROBINHOOD_HANDOFF.md` and `robinhood_research/README.md` before continuing.
- Paper/research only. No signing, transaction submission, live money, purchases,
  merge, deployment, shared $500 allocator connection or changes to Solana branches.
- Preserve the active Solana PR stack, thresholds, strategy tests and experiments.
- Secret: `MM_ROBINHOOD_READ_RPC_URL` in GitHub Actions, complete HTTPS endpoint.
  Never expose its value or assume connectivity from the variable's presence.
- Keep synthetic, captured, natural and prioritized research separate. Bytecode
  presence is not protocol identity. No current Pons ABI or Ramses mechanics are
  certified by this branch. Fail closed at those explicit boundaries.
- Run Python 3.12 `python -m unittest discover -s robinhood_tests -v`.
- No thresholds may be copied from Solana or weakened to manufacture paper trades.
- Keep point-in-time observation timestamps and immutable evidence. Never delete
  existing evidence to make a study fit. Stop bounded study admission at capacity.
