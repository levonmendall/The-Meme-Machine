# Structural Survivor rally re-entry — implementation candidate (2026-10-16)

**Scope:** Pump Survivor and Pons Survivor, PAPER ONLY. No signing, real-money
execution, provider subscription, account initialization, service start, state
deletion, or AWS/Render deployment is part of this change.

## Selected economic behavior

- A first Survivor entry retains every previous strategy, risk, execution,
  coverage, age, capital and native-quote requirement.
- For a later funded entry on the same strategy/candidate, the authoritative
  sleeve checks that *every* previous funded lifecycle is verified settled and
  no same-asset exposure is open. Cancelled, proven unfilled attempts are not
  filled-trade cycle references. Unresolved attempts cannot be treated as flat.
- A later entry must identify an independently completed peak -> reset ->
  base -> breakout from fresh existing authenticated Survivor price evidence.
  Cycle identity uses family, canonical asset, peak time/price and reset
  time/price; a new quote, buyer population, rolling base boundary or passage
  of wall-clock time alone cannot create a new cycle.
- A new peak and reset must follow the prior cycle's breakout. When a position
  predates this identity format, its verified prior setup time is used as a
  conservative chronological frontier. Unknown/corrupt prior identities fail
  closed.
- No extra setup- or settlement-based cooldown is imposed. This removes the
  old Survivor ">=3600 seconds since setup plus two changed numerical
  dimensions" funding predicate, **not** the genuine time needed for a
  completed price structure or original four-hour initial Survivor eligibility.
- Shared funding, size, exits, right-tail, add conditions, fee/slippage limits,
  protection intervals and Current/Survivor independence are unchanged.

## Source of cycle evidence

**Pump:** the preexisting native completed-hour base, bounded long-structure
witness, reduced peak/reset history, authenticated reset-low retention and
breakout. Expose the exact selected peak price in existing qualification
features; attach a cycle object to the native regime at each qualified turn.

**Pons:** the preexisting post-graduation long/medium/short covered windows,
older peak, two-hour frozen base excluding the last fifteen minutes, reset low
and breakout. Expose the actual peak and reset timestamps plus latest frozen
base witness. No reset-depth-only identity is used for repeat authority.

A new cycle object is emitted only when its chronological structure is
complete and all required witnesses exist. No historical price event is
invented, no retained raw market evidence is replaced, and old decisions are
not retroactively relabeled.

## Shadow comparison, not shadow trading

At every otherwise qualified Survivor candidate turn, store both:

1. The previous setup-based 3600-second/two-changed-feature decision.
2. The selected structural-cycle decision with no extra delay.

The record contains counts of blocking prior lifecycles, latest recorded native
settlement time, elapsed time since settlement when known, proposed cycle ID,
and whether the two rules disagree. It is attached to existing native
qualification/candidate receipts and is not an execution or profit simulation.
The selected structural rule is separately rechecked by the existing
transactional sleeve reservation guard; a shadow record is never a grant.

A rejected repeat stays under ordinary observation and can requalify after an
actually new cycle. First entries remain eligible without a fabricated
structural reference. The comparison cannot override an older native failure,
fresh-quote expiration, concentration veto or unavailable capital.

## Native financial transition / deploy guard

This changes **both Survivor policy hashes**; neither Current policy hash nor
the original financial genesis, portfolio epoch or historical $500 accounting
is altered. Prior opportunity-access Survivor hashes are retained *only*
for exact recovery joins and verified **flat** transition. A non-flat old
decision policy cannot be silently switched. Prior proof must establish
terminal actions and corresponding sleeve/portfolio release ACKs, including
pending scale/commitment/delivery work; otherwise preserve the old selection
and do not deploy. All new decisions must use the new effective policy hash.

This branch intentionally does not edit shared grant allocation logic.
[PR #137](https://github.com/levonmendall/The-Meme-Machine/pull/137)
independently repairs a pre-existing native-grant-before-rejection ordering
problem. Merge and validate that repair before installation of this strategy
if it has not already been integrated. This change does not waive its
obligation-free preflight or introduce a second allocator.

## Tests and limitations

The regression module includes constructed peak/reset/base/breakout sequences,
no-artificial-delay second entries, independent third cycles with repeated
numeric features, stale/corrupt references, legacy checkpoint frontiers,
original Pump/Pons policy evaluator fixtures, durable sleeve shadow receipts,
native writer recheck, restart and capital conservation.

These are deterministic *software* tests, **not authentic market profits**.
They do not demonstrate that zero-delay structural re-entry improves portfolio
returns after failed fills, fees, losses or slippage. Retain the prior rule as
research-only comparison until chronological authenticated market replay can
quantify prevented duplicates and missed winners for both families.

PAPER remains stopped/disabled unless a separate verified operational release
process checks AWS source pin, native state/backup integrity, provider continuity,
open-position protection, combined throughput, original acceptance and current
funding authority. Publishing this branch cannot start PAPER.

## Rollback

Stop PAPER using the normal safe lifecycle, preserve all journals and positions,
and return to a prior effective strategy only through the existing compatible
decision selection/flat-boundary process. Never rewrite a cycle ID, native event,
financial journal or outstanding obligation to fit an old policy.
