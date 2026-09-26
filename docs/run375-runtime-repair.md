# Run 375 runtime repair

Incident market run: `36260920839` (Run 375).
Incident SHA: `87679280006ebf22c8b410fdf558658d190fd235`.

Run 375 exposed two independent runtime defects while preserving PAPER-only
authority and confirming the prior publisher repair.

## Pons SQLite WAL snapshot race

`certification.robinhood.provider_usage.snapshot()` checked that the shared
admission database WAL existed and then performed a separate `stat()`. SQLite can
checkpoint and unlink a WAL between those operations. Run 375 hit that exact race,
raising `FileNotFoundError` and terminating Pons after about 522 seconds.

The repair performs one race-safe stat and treats only `FileNotFoundError` as a
zero-byte transient WAL. Main database failures and other filesystem errors remain
visible. A deterministic regression forces the old exists/stat interleaving.

## Solana ordered persistence saturation

The Solana evidence receiver and parallel decoders remained responsive, but Run
375 spent about 383 seconds in ordered SQLite commits and saturated the existing
64-frame / 96 MiB dispatch bound. The repair does not increase those bounds and
does not weaken `synchronous=FULL`.

Consecutive full-block notifications are now grouped into a bounded owner
transaction: at most eight frames and at most 16 MiB total. The committer first
drains completions already present in the bounded decoded queue into its ordered
ready buffer, which allows genuinely consecutive frames to coalesce instead of
immediately committing the first decoded frame alone. Each frame retains its own
savepoint, receive order remains authoritative, account/control notifications
remain one-at-a-time, and any later malformed frame cannot contaminate earlier
valid frames. The outer commit amortizes the fixed FULL-sync cost.

New telemetry records commit-batch count, peak batch messages/bytes, and avoided
outer transactions. A focused regression injects a fixed outer-commit delay and
proves the bounded path drains without a dispatch-capacity disconnect.

PAPER ONLY. No market workflow is authorized by this repair or its certification.

## Focused certification

Focused workflow `36262997513` passed on the repaired integration runtime and
on both prepared Solana lane worktrees.

Prepared runtime identities:

- Pump: `331724a4fe47993d6eaf258309ddfa01b09a60e8bbde2650f149e4623b3e3afa`
- Meteora: `faf2b08d5b170e04f59c9924d39caf468f37c2abe6864f97b8c9937b0cd8203f`

These identities are frozen in `certification/sources.json` before the full
non-market certification.

The first full non-market attempt (`36263125298`) stopped at protocol freeze
because the frozen Pump/Meteora executable diff identities still named the Run
373 runtime. Strategy versions, source SHAs, and policy hashes were unchanged.
Only those two frozen `source_diff_sha256` values were advanced to the focused-
certified Run 375 prepared identities before retrying non-market certification.
