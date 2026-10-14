# Diagnostic access repair and authorized replacement

Focused-tested executable successor:
`0333860364b0602583b7e300cbe7e57303697510`, receiving branch
`engineering/targeted-resolution-20261014`. Relative to original executable
`5f03b0599af6af05c796e27c867a545f2abb188c`, executable changes are limited to
the diagnostic launcher/access helper; the affected test module is also included.
The intervening outcome documentation preserves the original failed attempt.

`prepare_output()` explicitly repairs only the diagnostic parent to root and
the configured service's effective group, mode0710, and creates a fresh
service-owned0700 run directory. It rejects another parent, existing run or
symlink. No recursive chmod/chown, credential/database permission or service
protection change is made. Current identity is UID997/GID987/groups[987].

Every `observe_once()` now requires a fresh access proof before its actual
monotonic origin, real clock metadata and PAPER start. The bounded transient
probe copies actual installed identity/filesystem restrictions and adds network
isolation. It verifies all ancestor traversal, the controller's actual metadata
creation path/current umask, service atomic replacement, the terminal recorder's
temporary file/hard-link/directory-fsync publication, and controller read access.
Only its unique disposable child/files are removed. A simulated clock never
becomes the observation clock. An unverified timed-out probe stops preflight and
retains its files; it cannot dispatch PAPER.

Supported pinned runner validation: **39 tests PASS in0.638s**, zero failures,
errors or skips, including actual installed UID/groups/filesystem restrictions:
root-only0700 parent fails; explicit0710 repair passes; root-created0600 clock
fails. Ordering tests prove failure occurs before PAPER start/real clock. Prior
evidence and test fixtures' retained marker remain unchanged. Runtime is CPython
3.12.14, linked SQLite3.45.1. No provider/authoritative-state access or PAPER
start was used for these tests. Independent read-only review passed.

Private exact log:
`/root/Documents/Codex/2026-10-10/the-meme-machine-eliminate-redundant-data/blocker-repair-20261011/DIAGNOSTIC_ACCESS_REPAIR_FOCUSED_20261014.log`.

The owner's subsequent instruction authorizes exactly one replacement observation
after fresh preconditions pass. Use this explicit successor with the original
[specification](CURRENT_COMBINED_OBSERVATION_SPEC_20261014.json) at
`282d38946955b46422a34348062ac572777d8473`; no arbitrary newer executable or WIP.
Preserve funding-closed OBSERVATION, disabled startup/Restart=no, original300s
readiness,900s diagnostic startup/900s collection,1800s work and1865s absolute
boundary with65s shutdown reserve. No diagnostic time counts toward acceptance.
Reconcile actual obligations/accounting, storage, valid recovery references,
source/configuration and backup non-overlap before the one start. No timer,
provider-route, capital, economic policy or infrastructure change is authorized.

Original failed result remains immutable at
`/var/lib/meme-machine-diagnostics/20261014-current-combined-161351/result.json`,
SHA256 `1480bdcb09e6535ea51211b028d664e7fb032f04475e0311056caad2fdc9089e`.
Its RECOVERY_REQUIRED/native-drain-unverified findings are not replaced by these
access tests. Use a fresh replacement run; preserve all old evidence/counters.

After the replacement, retain first failures, stop and verify reconciliation and
native shutdown evidence, then use compatible source/configuration rollback
without rewinding databases. No retry or normal funding/acceptance transition is
authorized. Report unexercised paths and independent blockers honestly.
