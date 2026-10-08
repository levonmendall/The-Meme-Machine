# Operational acceptance on the existing Droplet

Do not execute these steps during consolidation or the oracle repair. USDG/USD
is resolved through the verified read-only Chainlink feed; production `check`
validates configuration without network I/O or inception.

1. Begin only from an explicit independent migration completeness PASS with its
   exact pushed commit/tree. Close volume/epoch protection, durable acceptance
   and observation, off-host backup/isolated recovery, and independent actionable
   email monitoring before freezing the acceptance candidate.
2. On Droplet **605465049**, preserve the existing PAPER epoch and every native
   journal. Never create a replacement directory or reseed capital when storage
   is missing. Verify the actual persistent mount and filesystem UUID. Configure
   root-owned, non-writable-by-others `/etc/meme-machine/storage.json` with exactly
   `mount_target`, `state_root`, `filesystem_uuid`, `volume_device`, `epoch_id`, and
   `inception_sha256` from the preserved canonical portfolio inception. The service
   requires the mount and checks that identity before economic initialization.
   `volume_device` is the original DigitalOcean `/dev/disk/by-id/` volume link;
   clone UUIDs cannot substitute another device. Deploy tracked files as root,
   readable by the service user (0644 files, 0755 directories; preserve executable
   modes). The non-secret storage configuration must also be readable by that
   user; keep provider env files root:root 0600.
3. Prepare `/opt/meme-machine` at that exact commit, CPython **3.12.14** and
   the pinned `requirements.txt` (including Model B gRPC). Verify SQLite **3.45.1** or the tested compatible successor.
   Run `python -m operational.tests FAST`, then `python -m operational.tests OPERATIONAL`.
4. Preserve the two existing read-only provider URLs in the protected env file.
   Install `deployment/meme-machine-paper.service`; configure bounded journald
   retention (for example `SystemMaxUse=256M`, `MaxRetentionSec=7day`). Run
   `python -m meme_machine.operational check`. Never initialize another epoch.
   Reverify the original storage device, inception and full portfolio replay
   before starting the preserved PAPER service.
5. Deploy one exact pushed commit/tree. Install the observer, monitor and
   localhost metrics services and verify their read-only filesystem isolation.
   Keep external alert delivery verified independently of acceptance. Record
   `MM_ACCEPTANCE_COMMIT`, `MM_ACCEPTANCE_TREE`, and `MM_ACCEPTANCE_EPOCH` in
   root:root 0600 `/etc/meme-machine/acceptance.env`; these are acceptance
   measurements, not runtime startup controls. Install the acceptance template.
   Start each unit only after the prior phase's durable result is PASS:

   ```sh
   sudo systemctl start meme-machine-acceptance@CAPACITY.service
   sudo systemctl start meme-machine-acceptance@RECOVERY.service
   sudo systemctl start meme-machine-acceptance@AUTONOMY.service
   ```

The units execute the acceptance CLI with full durations of 3600 and 129600
seconds. One shared flock prevents overlapping phases. Candidate, environment,
runtime unit/storage/backup configuration, epoch, start/end times, exit code,
stdout/stderr, result and continuous observations persist under
`/var/lib/meme-machine-acceptance`. Inspect `latest-PHASE.json`, the referenced
directory's `status.json` and `result.json`, and
`journalctl -u meme-machine-acceptance@PHASE.service`. A short, disconnected,
interrupted or failed run cannot count as PASS. The observer and condition
monitor continue independently of this process.

Freeze the trading runtime configuration through AUTONOMY. A material repair
requires FAST, OPERATIONAL, the configured check, affected startup/backup/monitor/
observation revalidation, a newly pushed/deployed candidate, and a fresh complete
CAPACITY run. Do not combine results from different runtime candidates. Keep an
ordinary operational handoff outside Git with exact identities, epoch, unit,
timestamps, paths, results and next action.

Before market observation, bind explicit request/CU, storage and elapsed-time
ceilings to a separately authorized PAPER run. This consolidation authorizes
offline validation only; no defaults here grant a provider-spending budget.

CAPACITY requires independent progress for Pump, PumpSwap and Pons canonical
coverage, complete Pons startup nomination coverage, bounded queues/storage
and memory within the existing 2 dedicated vCPU / 8 GiB host. Inspect CPU,
provider failures, backlog and maintenance completion alongside its measurements.
The active operational set is exactly `pump, pons`; `meteora, ramses` must remain
explicitly PAUSED with zero strategy processes or new work, including after
recovery. Their historical accounting stays mandatory. RECOVERY deliberately
kills each active lane and then the supervisor; verify the same
epoch, complete native/portfolio reconciliation, no duplicate entries or lost
positions, no pending deliveries or stranded reservations, and resumed management
before discovery. A strategy exit during recovery remains a valid native exit.
AUTONOMY requires continued unattended acquisition and management with successful
automatic recovery and bounded retained state. Review health and normal logs.

Report realized P&L and marked equity where valuation is valid. None of the three
checks requires positive P&L, profit factor, a trade count or an economic cohort.
The small measurement JSON files are status output and grant no execution authority.
Leave the PAPER service running only if all three pass. Then cut the existing
Render dashboard over to the read-only snapshot replica. No dashboard activation
or transfer to Render has been performed by this consolidation.
