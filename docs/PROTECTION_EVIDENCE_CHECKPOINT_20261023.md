# Unwired protection evidence checkpoint — October 23

**NOT operational acceptance. No production wiring, installation or real ledger
migration occurred.** The authoritative installed isolated application remains
f0bff49b; this is a preserved child of the existing local proof prototype.

Root validated exact source `126528ae66b4e1665d69f40ceecf8f5e6e78331d`:
`python3 -m operational.tests FAST --modules tests.test_protection_evidence`
**PASS66/0.573s**. Independent static source/contract review passed. Tests use
synthetic original-entry/quote/USD/shared receipts and the real old PaperBook
implementation in disposable databases. They do not prove authentic host timing,
funded $1,000 strategy execution, provider performance or full release readiness.

## Demonstrated failures and decisions

- Existing37 tests passed, but original OPEN authenticated financial hashes while
  trusting a newly claimed monitor clock. Regression sources9a443ab9/53075fba
  demonstrated old-mark/old-birth reuse, OPEN before/at/inside the window, and
  first-owner reuse. All five invented-grace cases falsely returned RESOLVED.
- An honestly late FAILED dispatch was structurally rejected and prevented a
  later genuinely recovered window. Six initial regressions failed as expected
  in0.076s. Do not repeat unchanged RED runs.
- Retain append-only proof/native/shared/census machinery. Refactor initial grace
  to use an optional trusted `initial_entry(lifecycle_id,birth_ref)` resolver.
  It must resolve exactly one independently authenticated immutable body/hash
  envelope, bounded at its reader, against the actual census birth. Verify full
  source/policy/configuration/epoch/genesis binding, original owner, birth, entry
  ACK, profile, held-clock bracket and original first due/deadline. A hash alone
  is not host authentication. Native journal `at` is a caller timestamp sampled
  before COMMIT; shared ACK or OPEN registration cannot invent held-entry time.
- Resolve initial evidence lazily when coverage depends on first-monitor grace,
  including every OPEN/window boundary. Missing evidence denies that grace.
  A separately verified COMPLETE turn can establish a later recovered interval
  without original-entry evidence. Existing financial/proof history is retained.
- Structural history preserves original due/deadline even for late dispatch.
  COMPLETE records processing completion; selected/leading `_turn` validation
  still checks original quote/USD/risk/native/ACK deadlines. Earlier misses fail
  their own intervals and do not poison a later independently recovered window.
- First executable correction091de261 passed63/64: a valid prior turn covering
  a later short interval incorrectly reported held_coverage=false. Fixed without
  inflating the in-window turn count; source310affd5 passed64.
- Independent review then found that a deadline8.0 miss could hide from a
  window ending8.0/8.2 because dispatch started9.0. Regression-only853c4a52
  reproduced both false passes while the interval ending7.9 and later recovery
  remained valid. Final selection includes a retained obligation if its original
  deadline intersects the window, even when dispatch starts after the end.
  Source126528ae passes all66 tests, including original row preservation.

## Remaining work and resumption

Keep this prototype unwired. Constructor failure containment, financial-storage
headroom (including the shared Pons native budget), archival/retention, complete
execution/exit profiles, real quote/USD/entry/census adapters and authenticated
host/source/clock attestations remain unimplemented or unverified. A finite proof
capacity limit must never prune evidence or claim protection passed. The existing
USD_NOT_CONSUMED result is not full protection evidence.

The primary live throughput discriminator is being retrieved from existing failed
run39820699185 through the independently verified successor collector; see the
administration repository's AUTONOMOUS_PAPER_RESUME_20261023.md and Issue124.
Do not substitute these synthetic tests for those measurements or operational
one-hour/24-hour acceptance. Preserve the old49b0191f branch and all RED/fix
commits. Reuse this exact-source validation until executable source changes.
