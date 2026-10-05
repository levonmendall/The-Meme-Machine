# Ramses economic source attribution

RAMSES_ECONOMICS: UNCHANGED

The intended source is Ramses Active Wide Maker v4 at
`41b5f263efc31bedf9b39039a9f66bed264b70d3`, policy hash
`58d6ca2a911c4d27ea35da8c972f0a6b1c65c3e9192d811834b92d63d2c08b1e`.
The owner-approved latest-policy composition is recorded at
`7a516a6a92be9347661ac0e7f560971c171a0931` in
`certification/notes/latest-policy-runtime-composition.md`.
It explicitly preserves promoted Ramses economics while carrying engineering
repairs. Those historical paths provide source attribution and have no current
operational authority.

The offline reconstruction starts from the exact source and applies all 18
declared overlays in order, including the same clean three-way fallback used by
the historical preparer. It reproduces the exact composed diff SHA256
`cbf75a15df626001d031288ee2658d8878a06493af94a498d449e4814aea1fe9`,
all eight declared composed file hashes and all three unchanged frozen files.
No merge conflict was manually resolved. Every one of the 44 materialized
runtime modules then matches the reconstructed economic AST after explicit
namespace relocation and enumerated operational adapters.

The complete identities, overlay hashes, source hashes and reconstructed
economic comparison hashes are preserved in
[ramses-source-attribution.json](ramses-source-attribution.json). Permanent
`test_ramses_source_attribution` coverage compares current sources to those
historically reconstructed hashes and rejects economic mutations.

| Economic behavior | Verified source |
| --- | --- |
| Entry and pool qualification | `ramses_strategy.classify_pool`, `_active_wide_candidate_ok`; canonical pre-entry history and `select_qualifier` |
| Sizing | `recommended_capital`, `range_local_liquidity_quote`, `wide_range_capital_ceiling` |
| Universe and quote side | `ramses_universe.scan`, `_pool_identity`, `_quiet_activity_cohort`, `_quote_side` |
| Range | `_wide_range_ids`, `_active_wide_freezes`, `build_path_freeze` |
| Costs and profitability | `_cost_total`, `evaluate_fee_pulse`, `paper_outcome`, `hurdle_comparison`, `_segment_costs` |
| Rebalance | `controller_action`, `_requalify_current_pool`, unchanged same-decision deadline controls |
| Exit | `_unwind`, `_unwind_has_full_liquidity`, `paper_removal`, `controller_action` |
| Quote denomination | `quote_value`, `_quote_side`, quote-relative ledger and cost-route evidence |

Namespace moves, owned runtime paths, provider scheduling, finite stop waits,
storage retention and the portfolio/native boundary are operational adapters.
The comparison enumerates these adapters; it does not replace economic function
bodies, policy constants, qualification logic, range logic, cost calculations,
rebalance decisions, exits or quote denomination.

This finding does not declare migration completeness or authorize CAPACITY.

Optional capability hints are an optimization input. Their exact reader now also falls back for JSON shape TypeError/AttributeError, matching its existing missing-file/key fallback. The economic comparison normalizes only this reader's exact AST body hash and exact five-exception pass handler to the historical three-exception handler. A changed reader body or broader exception handler cannot pass that normalization; the economic reference hashes and frozen policy bytes remain unchanged. Permanent regression checks cover both permitted and forbidden mutations.

Pipeline retention no longer attempts cleanup of `progress_sources`, a table the Ramses observation pipeline never created. Pump and Meteora receive the same repair; Pons retains its real source-deduplication table and cleanup. The existing enumerated observation-retention adapter already excludes this block from economic comparison. No new normalization or historical economic reference hash changed. The four-lane regression crosses the actual 8,192-record boundary using old-schema databases and verifies retained history, monotone sequence and restart.
