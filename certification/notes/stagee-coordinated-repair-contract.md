# Coordinated Stage E repair contract

Reviewed predecessor: `23f06ed84e5b5e2d4efd074618ab44ae7ed58011`.

This is PAPER-only engineering. No market observation, submission, signing,
provider probing, deployment, or Render operation is authorized by this workflow.

## Mechanisms being repaired

1. Prepared runtime identity generation is one reviewed operation covering both
   source and protocol manifests. Verification is read-only and runs before the
   expensive gates. The updater must reject any non-operational native delta,
   economic-policy change, untracked module, or unreproducible predecessor.
2. Archive selection must preserve exact input/output bytes and pin semantics,
   while replacing four per-record metadata reads with bounded set reads and
   coverage reuse by `(scope, slot)`. A 1,000-record production-SQLite comparison
   must reproduce the old archive bytes and reduce SELECT calls to at most 50.
3. A completed PASSIVE checkpoint is valid for owner-side reset only when no
   intervening owner operation has occurred. Zero lock-wait is not a time bound.
   Delayed completion must be deferred, not used to copy a new tail on the owner.
4. Combined validation must actually exercise both source batch modes after
   retention matures, overlapping real SQLite readers, delayed checkpoint
   completion, and actual priority-zero IPC acknowledgements. Merely registering
   the scenario or passing its constituents independently is insufficient.

## Preserved constraints

All strategy/policy values, four portfolio lanes and six strategy regimes remain
unchanged. The original 2,223-frame, 600.21-second pressure driver, measured
contention, fixtures, 45-second source-lag guard, 240-second age guards, 2 GiB hot
store guard, and source frame/byte limits remain unchanged. Existing lifecycle
and gap pins, FULL-synchronous durability, hashes, source authority and fail-closed
behavior remain mandatory. No data is dropped or excluded to lower pressure.

The canonical durability job receives an additional combined-load test and a
larger workflow time allowance for that added work; no runtime bound is relaxed.
Both original and combined pressure reports are required for the final certificate.

A review proof is not a Stage E certificate. Canonical full certification must run
on the exact final promoted-for-certification SHA. Every failed result remains
preserved; there is no retry-until-green acceptance rule.
