# Engineering storage

The existing PAPER epoch, portfolio, native journals, pending deliveries,
reservations, candidate recovery histories, native cursors, migration identities,
and operational configuration are authoritative. They are never scratch space.
Live state stays on its verified attached volume. Required recovery points and
unresolved acceptance/accounting evidence stay accessible until their replacement
is independently verified or the owner explicitly approves their disposition.

Root disk warns at 75% and refuses new nonessential bulk artifact operations at
85%, including the proposed copy's growth. Keep at least 5 GiB free on the root
and the destination after a copy. The operating target is below 70%, with at
least 15 GB available. Existing native position safety maintenance does not call
the engineering admission functions and continues independently of these quotas.
No service, epoch, funding authority, strategy rule or market family is activated
by an artifact check.

| Environment setting | Default |
| --- | ---: |
| `MM_STORAGE_WARN_PERCENT` | 75 |
| `MM_STORAGE_BLOCK_PERCENT` | 85 |
| `MM_STORAGE_MIN_FREE_BYTES` | 5368709120 |
| `MM_ENGINEERING_SCRATCH_MAX_BYTES` | 1073741824 per offline scope |
| `MM_ENGINEERING_SCRATCH_TOTAL_BYTES` | 2147483648 retained scratch per parent |
| `MM_ENGINEERING_SNAPSHOT_MAX_BYTES` | 2147483648 per optional copy |
| `MM_ENGINEERING_SNAPSHOT_TOTAL_BYTES` | 4294967296 retained per snapshot parent; also the acceptance output budget |
| `MM_ENGINEERING_TMPDIR` | Existing system temporary directory |

Keep the engineering temporary directory on the root filesystem. Moving bulky
scratch or old archives to the PAPER volume does not repair retention and consumes
active-state headroom. An explicitly approved archival destination still needs a
verified mount, a surviving recovery locator and adequate PAPER capacity.

## New engineering artifacts

Run `python -m operational.tests FAST` for routine offline checks. The driver
creates a marked, unique scratch scope and supervises only its offline worker
process group. Every 0.25 seconds it checks aggregate scratch allocation and root
headroom, including the unused scratch budget. It stops that engineering group
when a limit is exceeded. Successful scopes clean their own fixtures; failures
and interruptions retain evidence and print its exact location. Retained failures
consume quota and eventually block new scopes instead of being silently erased.
Unknown directories, links and other jobs are preserved. This is an admission
and watchdog policy, not a filesystem quota; the reserve covers growth between
checks and a bounded worker termination interval.

For other completed, disposable offline fixtures use
`meme_machine.operational.artifact_storage.Scratch` and call `check()` throughout
work, then set `success=True` only after verification and saving any required
result outside the scratch scope. Never put unique real recovery state into a
disposable scope. Generic `unittest` and historical scripts do not automatically
gain this lifecycle; use the supported driver or integrate these checks.

Before an ad hoc optional copy, run this on the maintenance source checkout:

```sh
python -m meme_machine.operational.artifact_storage \
  --source /absolute/source --destination /absolute/destination-parent
```

This command is read-only. Stop if it returns nonzero. Then use `backup.prepare`
or `backup.copy_state` for a coherent state point, under their existing writer
quiescence contract. These functions enforce both byte quotas and available
headroom before copying, recheck space during SQLite backup and between files,
and keep interrupted/failed copies marked unusable. Do not checkpoint, truncate
or remove WAL files to save space or make a copy eligible for reuse.

`copy_state(root, new_target, reuse=existing_point)` can return the existing point
without creating `new_target`. It requires a completed coherent manifest, exact
source digests for every retained file, verified backup digests and matching
portfolio replay. New optional copies record both quiescent source digests and
backup digests because SQLite's backup API can rewrite header bookkeeping.
Nonempty WAL/rollback journals prohibit this reuse path. A matching portfolio
alone does not prove matching native cursors or recovery evidence. Changed or
unverifiable points require a new admitted copy, never an overwritten point.

Prefer targeted logs, query results, configuration identity and patches for a
diagnostic whose recovery semantics do not require a complete new state point.
For a handoff, retain those small items plus locators, exact source identities and
fresh digest verification of existing state points. Do not `copytree` an entire
preserved, restore-test, handoff, backup or Codex session collection into another
package. A previous handoff is a referenced source, not a recursive copy input.

## Recovery and acceptance evidence

The existing scheduled backup retains its existing three local/off-host points
on the verified volume and enforces destination headroom. Its `nonessential=False`
call distinguishes ordinary recovery backups from optional root engineering
copies; it does not bypass the mount/epoch guard or destination reserve. Optional
copies use the default `nonessential=True`. Native maintenance has no dependency
on either artifact quota.

Acceptance admits the bounded observation/log budget before a new attempt and
checks root headroom during the attempt. A pressure stop terminates the acceptance
child only and persists a failure record. Unresolved FAIL records are retained;
automatic completed-attempt retention applies to unreferenced PASS records.
The retained output quota blocks another attempt when review is required.
Root warnings and exhaustion conditions use the existing independent monitor,
including while PAPER is deliberately disabled. Disk percentage includes available
blocks consistently with `df`, including reserved blocks on the volume.

## Disposition

Classify every proposed cleanup by its contents, creation job and dependencies:
authoritative state and unique recovery evidence are preserved; unknown artifacts
are preserved; demonstrably redundant verified copies and disposable synthetic
fixtures are distinct. Never prune real recovery evidence based on date alone.
For a recovery-sensitive deletion obtain owner approval for exact paths, sizes,
survivors and recovery consequences. Verify all surviving files independently and
resolve old path references before removing redundant bytes. A staged redirect
plus a durable deletion journal allows interruption without loss of recovery
access. Never remove a whole artifact family or mutate a sealed survivor.

On Droplet 605465049, the 2026-10-08 storage cleanup keeps the sealed
`/var/lib/meme-machine-handoff/20261006T053005Z-capacity-hold` intact. The approved
15 dated preservation directories, three old restore tests and one cold-drain
test now resolve through root-owned symlinks to their exact copies inside it.
These historical points remain distinct from one another. The two former copies
shared the root filesystem; the redirects do not create additional off-host
protection. Preserve the separately retained verified volume recovery snapshots.
