# Live PAPER trial — Pump held-RPC optimization (prepared; not dispatched)

**Status: PREPARED, NOT STARTED.** No DigitalOcean shell access or runtime
command execution was available in the connected tools used to author this
branch. The GitHub and Alchemy connections are usable for repository inspection,
configuration review and authenticated usage reads, not for controlling the
existing service on Droplet **605465049**. This document does not itself start
any workload. GitHub Actions in this branch are offline-only; **never run the
PAPER process in CI**. The prepared production switch defaults to baseline.

## Exact source and scope

- Repository: `levonmendall/The-Meme-Machine`.
- Branch: `engineering/pump-pons-style-request-efficiency-20261008`.
- Deploy **only an exact reviewed passing commit SHA** from this branch, never
  its moving name or unreviewed HEAD.
- Existing entrypoint `python -m meme_machine.operational`.
- Existing PAPER service `meme-machine-paper.service` under
  `/opt/meme-machine`. Existing state volume and $500 inception remain
  authoritative; no source-controlled file is a new portfolio or owner.
- Existing Pump and Pons lanes remain available under the current approved
  stage. Meteora and Ramses remain paused. No strategy policy, capital
  allocation, unrelated Pons maintenance or unlimited-time assumption changes.
- Optional only for Pump worker:
  `MM_PUMP_HELD_RPC_MODE=baseline` (default, original reads)
  versus `MM_PUMP_HELD_RPC_MODE=optimized` (combined held-state reads).
  The supervisor validates and propagates it only to Pump; no extra secret.

## A. Gate before touching the host or paid market

1. Require a completed passing **exact-SHA** focused Pump offline proof, plus
   relevant FAST/OPERATIONAL and previous native continuation/restart checks,
   with failures diagnosed rather than waived. A queued job is not a pass.
2. Review on-host worktree and clean baseline. Confirm exact current
   deployed SHA, correct Python 3.12.14 and pinned dependencies, current
   stage/migration compatibility, untouched strategy policies and $500 epoch
   identity. Never `git reset --hard` over unknown work or force a pull.
3. Read-only check `systemctl show meme-machine-paper.service -p ActiveState
   -p SubState -p MainPID`; inspect current health/portfolio/native books,
   reservations, outstanding exits and other managed owners. **If any live
   PAPER position or unresolved obligation exists, do not stop/restart/
   switch code** unless the existing seamless, replay-verified protected
   continuation handoff is independently proven. Do not abandon a winner.
4. Verify preserved exact $500 inception, all native books and shared
   accounting reconcile PASS, every current owner known, the existing off-host
   snapshot/backup is available and sufficient scratch/storage/CPU/memory
   remain. This is an update to source, never a fresh epoch.
5. Check the authorized existing Droplet+provider envelope,
   `/etc/meme-machine/position-continuation.json`, with the original
   bootstrap/continuation/recovery budgets and on-disk usage ledger.
   Do not populate this from a proposed example unless explicitly approved.
   Do not raise RPC CU, attempts, native bytes, queue, provider connection,
   funding, startup or recovery limits to make the test pass. The historical
   `FIRST_POSITION_PAPER_BOOTSTRAP` supported one $25 gross lifecycle, up to
   1,800 seconds initial admission with funding closed at 1,200 seconds,
   followed by only previously approved held-position continuation.
   Whether that allowance remains available must be checked; an already
   consumed allowance is NOT replenished.
6. Ensure every Solana/Robinhood API credential remains only in the existing
   protected `/etc/meme-machine/paper.env`. Never log, print or commit them.
   Confirm credentials and authenticated streams still work before funding.
7. Confirm the observed 2-vCPU / 8-GiB Droplet's actual cgroup budget,
   stream connections, queue depth/latency, fresh finalized Pump+PumpSwap
   coverage and genuine position-recovery protection. An offline pass alone
   does not authorize funded startup.

## B. Enable the optimized mode without touching any keys

Only while service work is safely stopped/flat per A, update the one *nonsecret*
setting in the **existing** protected EnvironmentFile
`/etc/meme-machine/paper.env` (merge/replace the existing occurrence; never
overwrite the file): `MM_PUMP_HELD_RPC_MODE=optimized`.
Do not put the value in Pons or shared provider configs. Keep the existing
`deployment/paper-bootstrap.conf` and native continuation owner unchanged.
Change to `baseline` for the comparator mode; both modes use the same source,
same policies, same dollar inception and same live RPC topology.
The mode is read on process start; a configuration change alone is inert.
Do not restart an already held position merely for an A/B comparison.

## C. Live PAPER observation and bounded execution

1. Under the existing finite observing command, with funding **closed**, collect
   a fresh 300-second status/queue/provider/sample-window receipt from the
   already approved Pump/Pons workers. Observe only when the existing service
   state and budget permit this additional provider work.
   This cannot prove held-RPC savings because there is no funded position.
2. Reconcile journal native books and verify original Current/Survivor
   qualification, histories, source selection, no new source clock gaps and
   zero real-money transaction construction/submission.
3. If and only if the previously authorized ONE first-position bootstrap is
   unused and the active continuation envelope has been shown adequate,
   execute that exact one `bootstrap` lifecycle with the already configured
   1,800-second admission bound. Allow the existing qualification gates
   to decide whether a candidate is eligible. Do **not** inject a synthetic
   candidate, a forced trade, an inflated balance or loosened funding guard.
   If no funded position occurs, report **HELD_SAMPLE_UNAVAILABLE**.
4. Once real PAPER exposure exists, the normal Pump Current/Survivor held
   loop will use fresh six-account quotes at its original 5-second cadence.
   It still reads full flow and holder concentration. Verify mode via Pump
   runtime output `held_rpc_mode` / `pump_held_rpc.mode`.
   The original native owner retains every partial/final exit and risk rule,
   including pending exit intent when fresh evidence is unavailable.
5. Track cumulative physical Alchemy Solana HTTP elements, CU by **method**,
   WebSocket delivered application bytes, separately billed Yellowstone TB,
   baseline versus optimized per held review, session/adapter rotations,
   timeout/429 and provider queue/restart delays, cash/reservations,
   realized/marked equity and exit quotation age. Include provider usage
   timestamp/dataThrough and competing app activity; Alchemy hourly buckets
   cannot exclusively attribute a run without correlation.
6. Track the unchanged holder-concentration scan in Pump Current using
   `holder_scan_shadow`: observed counts, unchanged/changed values and
   `postgrad_provider_reader` counters. **Never claim that unchanged values
   license an omitted scan.** Those metrics help determine where the larger
   next-generation holder-state savings might be found.
7. If provider/price/finality safety fails, stop **new funding/optional work**
   and preserve the existing held position owner with durable exit intent.
   Never synthesize an exit, force-sell a winner to satisfy a trial timer,
   reset the $500 equity, or kill a live owner to roll back optimization.

## D. Pass/fail decision

**PASS (PAPER_OPTIMIZED_PROVEN)** requires all of:
- At least one naturally funded, observed existing PAPER Pump position; exact
  reviewed code/mode identity; all program/strategy gates unchanged.
- Fresh, validated held account data, current creator/Mayhem/fee, no missed
  action due to a cached identity, and no stale/unjustified quote or slot.
- Provider physical-element savings relative to equivalent prior
  baseline snapshots and cache effects; reconcile session-level counters
  and app-level CU. No unexplained increased retries, native/WS bytes, CPU,
  memory, queue waits, or cost.
- No worse protective observation/partial/final exit latency, full original
  HWM/right-tail/continuation policy, native reconciliation PASS and
  preserved Current -> Survivor independent eligibility.
- Check across a real restart/recovery only if one occurs under the existing
  protected continuation rules; do not induce an unsafe restart.

**INCONCLUSIVE** if no funded position, unmatched workload, insufficient
timestamp granularity, incomplete coverage or provider metering.
**FAIL_CLOSED** on economic/quote mismatch, bad current pool state,
unprotected position, mode/credential mismatch or provider-budget breach.
No trial or runbook may promote an inconclusive source to production acceptance.

## E. Rollback and reporting

The exact baseline is the same source SHA with
`MM_PUMP_HELD_RPC_MODE=baseline`, not checkout of the earlier branch or
a historical schema. Switch only when safely flat or through an independently
verified live-owner handoff; every open position remains managed and
reconciled. Keep both original and optimized method/session measurements.
The proposed deployment never overwrites the existing shared capital,
native journals, candidate history or $500 inception.
When ready, save a secret-free
`operational/pump-request-efficiency/LIVE_PAPER_RESULT.json`
containing exact SHA, original epoch, mode, UTC window, provider and
physical-call receipts, source headroom, cost delta, position safety,
exit outcomes and all failed/inconclusive reasons.
