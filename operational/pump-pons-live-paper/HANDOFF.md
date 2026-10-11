# Live-PAPER integration of PR #126 + PR #127

**Repository integration candidate — not a host deployment or a funded run.**
This branch composes the current Pump optimization PR #126 and Pons shadow
PR #127 on their common Pons-held-efficiency parent PR #124. It preserves
existing continuation and exceptional-winner engineering in ancestry.

## What runs when an authorized existing PAPER service starts

* Pump Current and Survivor: setting `MM_PUMP_HELD_RPC_MODE=optimized`
  enables fresh same-finalized-slot held PumpSwap curve/pool/mint/vault/fee
  batches, immutable vault-address hints only, and exact-slot timestamp
  reuse with original authenticated-RPC fallback. Original five-second
  position protection, holder-concentration/flow reads, entry/requalification,
  high-water, partial/full exits and recovery remain unchanged.
* Pons Current and Survivor: setting `MM_PONS_HELD_PAPER_SHADOW=1`
  passes the capped Pons event-coverage observer into the actual Pons lane
  environment. The prior standalone PR lacked this supervisor allowlist.
  Each existing native owner obtains a fresh executable quote and decides
  all native actions BEFORE any optional shadow work. Eight samples per
  controller, every tenth eligible HOLD tick, are configured by the example.
  The two-second diagnostic deadline and priority-30 admission remain.
  Live controllers dispatch the observer asynchronously, with at most one
  sample in flight per controller. Its separate bounded RPC session uses the
  same endpoint, cross-process governor and finite usage ledger; it does not
  mutate or wait on the native controller's RPC or local pacing lock. Native
  exits and shutdown never join an optional diagnostic.
* Pons event-first quote omission is NOT activated: both original quote
  cadences (Current five seconds, Survivor three seconds) and all
  continuation/exceptional-winner rules remain unchanged.
* Optional shadow reads are refused in POSITION_ONLY/funding-closed mode.
  There is no permission to spend past a finite existing provider budget,
  no extra funded lifecycle and no new paid subscription. No naturally funded
  held position means no held-position test observation.
* Meteora and Ramses remain paused; the original $500 PAPER epoch, shared
  portfolio, journals, exposure, provider authentication, capital rules
  and existing service supervision are not changed.

## Exact next-start deployment procedure (not executed here)

1. Freeze one exact SHA from this integration branch; wait for passing
   FAST, OPERATIONAL and focused integration/held tests on that exact SHA.
   Diagnose any failures; do not interpret queued tests as passing.
2. On Droplet 605465049, read-only inspect the actual deployed SHA, service,
   positions, pending exits, original 500-dollar epoch/reconciliation, on-disk
   finite provider ledger and off-host recovery point. Do not restart or
   replace an active position owner without independently proven seamless
   handoff. Do not regenerate portfolio state or consume an expired allowance.
3. Only on a safe, authorized stopped/flat checkout, deploy the frozen SHA
   to `/opt/meme-machine`, retain `/etc/meme-machine/paper.env` and all
   keys, and run `python -m operational.tests FAST` followed by
   `python -m operational.tests OPERATIONAL` with the pinned Python 3.12.14.
4. Install the tracked `deployment/pump-pons-live-paper.env.example` to
   `/etc/meme-machine/pump-pons-live-paper.env` using root-owned 0600
   permissions (nonsecret values only). Install the tracked
   `deployment/pump-pons-live-paper.conf` as
   `/etc/systemd/system/meme-machine-paper.service.d/20-pump-pons-live-paper.conf`.
   Reconcile any existing definitions of these flags in `paper.env`;
   the later `EnvironmentFile` must select the intended values.
   Run `systemctl daemon-reload` and inspect the effective unit/environment
   names without disclosing provider URLs or secrets.
5. Start only under the existing separately authorized bounded PAPER
   observation/bootstrap/continuation envelope. This document does NOT
   authorize provider spending, a second bootstrap claim, a larger budget,
   unattended CAPACITY/RECOVERY/AUTONOMY or real-money trading.
6. Verify the actual Pump worker reports `optimized`, Pons worker reports
   `held_paper_shadow.enabled=true`, and no other lane inherits either
   setting. For Pump measure method-level physical Alchemy CU, source/cadence,
   exit age, queue latency, real economic parity and journal reconciliation.
   For Pons report the optional shadow's genuine added CU and counters;
   `hypothetical_quote_omissions` are NOT realized cost reductions.
   If the owner goes POSITION_ONLY, observe that Pons samples are refused.
7. Stop optional experiment/funding on any provider budget, native protection,
   quote, canonical, reorg, queue or deadline discrepancy. Do not terminate an
   open PAPER position merely to disable a test or roll back a branch; protect
   it with the existing native owner and persist recovery/exit intent.

## Rollback and outcomes

Once safely flat, removing the drop-in/restoring the earlier environment
selects the original Pump baseline and disables the Pons optional shadow
without changing strategy or portfolio data. Never restart an open winner
to switch modes. Record one exact-SHA result with full per-provider physical
billing, request/byte counts, state and protective-exit evidence.

The PR #126 baseline savings of 100 CU vs 20–40 CU per warm method review
is a sensitivity model, not a bill. PR #127's projected 70–95% long-hold
optimization is still a hypothesis because this version does not omit
quotes. Its purpose in live PAPER is to collect protected measurements.

Connected GitHub and DigitalOcean tools used here cannot execute shell
commands inside the Droplet. Repository publication does not install the
checkout/drop-in or prove that the PAPER service is running.
