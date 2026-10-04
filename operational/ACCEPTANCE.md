# Later acceptance on the existing Droplet

Do not execute these steps during consolidation or the oracle repair. USDG/USD
is resolved through the verified read-only Chainlink feed; production `check`
validates configuration without network I/O or inception.

1. Select the exact accepted operational commit containing the USDG/USD repair.
2. On Droplet **605465049**, verify the existing persistent volume's actual mount;
   bind `MM_STATE_ROOT` there with a new empty `paper-v1` directory. Do not import
   campaign balances, positions or P&L. Keep an existing epoch on later updates.
3. Prepare `/opt/meme-machine` at that exact commit, CPython **3.12.14** and
   `websockets==17.1`. Verify SQLite **3.45.1** or the tested compatible successor.
   Run `python -m operational.tests FAST`, then `python -m operational.tests OPERATIONAL`.
4. Install the two existing read-only provider URLs once in the protected env file.
   Install `deployment/meme-machine-paper.service`; configure bounded journald
   retention (for example `SystemMaxUse=256M`, `MaxRetentionSec=7day`). Run
   `python -m meme_machine.operational check`, then start the PAPER service once.
   That future start establishes the genuine $500.00 epoch.
5. Run, in this exact order from the service checkout with its environment:

   ```sh
   python -m meme_machine.operational.acceptance CAPACITY --seconds 3600
   python -m meme_machine.operational.acceptance RECOVERY
   python -m meme_machine.operational.acceptance AUTONOMY --seconds 129600
   ```

CAPACITY requires continued target evidence acquisition, bounded queues/storage
and memory within the existing 2 dedicated vCPU / 8 GiB host. Inspect CPU,
provider failures, backlog and maintenance completion alongside its measurements.
RECOVERY deliberately kills each lane and then the supervisor; verify the same
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
