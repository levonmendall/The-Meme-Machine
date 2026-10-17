# One detached shared-capital head per Current sizing evaluation

This is a separate, unselected component based on application
`4d255c12cbb7f516d06bb31ce3f6af79b8c6be96`. It has no deployment or AWS
performance result.

The completed probe `d2e01f2e62477d6d83285cd9d65dd7b45ae57db1`
(`pons-global-ledger-full-4d.json`) identified redundant reads in the original
Current sizing helper: four authority-selection opens and at least five complete
projection decode/hash/reconciliation passes per evaluation. That observation
does not establish the cause of the separately reported Pons 146GB reads.

## Contract

Only `_current_pons_realized_equity()` installs the private lexical evaluation.
It authenticates the original portfolio selection and reads the genuine shared
authority's validated projection and journal head. The short read transaction
closes before native sleeve replay, either native USD read, or other downstream
work. Subsequent selection and ledger reads in this one call use detached facts
from that head. Each ledger caller receives its own deep copy.

The scope binds the actual authority object, resolved paths, portfolio/shared
inodes, process and thread. Reusing a closed or copied foreign-thread context,
changing an inode, accessing another authority, or nesting evaluations fails.
No snapshot survives the call. A concurrent writer may advance the WAL; this
report remains coherent at its acquired head and the next report reads afresh.

Cold calls still run the original selection authentication before constructing
an authority and retain its full journal replay. Warm calls reuse only the
existing thread-local native connection to the same inode. The original
selection, epoch, inception, policy, projection checksum and journal-head guards
remain; failure-only selection checks preserve the predecessor's error order.
Native sleeve replay, attribution checks, both native USD reads and their
original expiry checks are unchanged.

Shared runtime commands refuse the scope before live admission prechecks.
Inherited financial writes also refuse before opening their writer transaction.
Outside this scope, the original transaction, current-head reconciliation,
allocation, settlement and duplicate-delivery paths are unchanged. The detached
head supplies no spending authorization.

## Focused evidence

- Six modules passed 78 cases in 18.351s: the new evaluation tests, original
  native capital preparation, shared capital, concurrency, recovery and Pons
  native acquisition. A final 9-case evaluation run passed in 0.469s after adding
  an explicit genuine cold-replay check; runtime bytes were unchanged between
  these runs.
- A genuine concurrent $1 obligation/discharge advanced the synthetic $1,000
  epoch while native USD acquisition was blocked. The evaluation retained its
  old head, `wal_checkpoint(TRUNCATE)` succeeded while blocked, and the next
  evaluation and a restarted connection both reported the resulting $999.
- Tests retain selection/hash/head refusals, cold authentication-before-open,
  full replay/conservation, missing/stale/second-read USD errors, native
  configuration errors, foreign owner/authority/inode refusals, no mutation
  inside the view, and normal writes after it closes.
- Paired eight-call comparison on the *same* bounded 9,359-byte synthetic
  projection: original 72 projection/40 journal-head reads; evaluation 8/8.
  The final run measured 45.443ms versus 27.165ms wall time for those eight calls.
  Financial projection and results matched; provider requests were zero. This
  is neither the large probe population nor a market-capacity measurement.

Final focused log:
`/workspace/recovery-evidence/shared-read-evaluation-final-focused.log`.
The first failed test receipt remains in
`shared-read-evaluation-first-focused.log`: its assertion expected the textual
cash value `999` while the original exact-money authority returned `999.00`.

Full release suites, exact-source promotion guards, AWS application deployment
and live throughput acceptance have not been performed for this component.
