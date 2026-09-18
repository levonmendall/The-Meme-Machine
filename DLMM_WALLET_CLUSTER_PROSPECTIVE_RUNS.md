# Solana DLMM wallet-cluster prospective runs

Candidate freeze: `cc828d1282be6f5f64b8c2cce4ef0d381e31cb45`

- Attempt 1: workflow 35406824601. Incomplete before any signal because the
  batched wallet observer encountered Alchemy 429/provider errors.
- Attempt 2: serialize wallet signature/body reads, retain each wallet cursor until
  every returned transaction body is readable and inspected, and perform a final
  catch-up pass before a no-signal conclusion.

Candidate wallet set, eligible-pool rules, 70-bin source requirement, 0.1 SOL paper
capital, 491-second hold, fixed costs, and all strategy/economic gates are unchanged.
