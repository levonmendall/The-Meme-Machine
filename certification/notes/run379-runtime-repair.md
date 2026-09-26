# Run 379 preserved evidence and runtime repairs

Run 379 (`36275141922`) executed certified runtime
`350e9c647cefbee7aa5e40fd7b84810ae5232b07`, native run
`d293c400-46ce-4630-b344-ab1f295c834d`, with the latest promoted policies from
`4ab66653a23475a72abe88bc96adf9f6e0b7fd9a`. Its full certificate was
`36274452439`. It observed real markets but did not pass smoke or fill a PAPER
position. No successor was authorized or started.

The primary archive is `10916932279` (1,048,659,038 bytes), SHA256
`9b1fb42ae2693b6324a2ca22283e21991e185d4a0fd7e482c862c754a0a304c2`.
Compact diagnostics `10917277325` have SHA256
`1f01dfd8a90c0931b7c19215498f4c8cd2d9baddcf2c71bab9733107dc9a3bf0`.
Provider-free review `36275883218`, reviewer source
`73bdc6f03c6a909e4069c6151191fcc2291679b7`, verified the exact primary digest
and source. Review artifact `10916534572` has SHA256
`44e476f21b7a6f58db0962ec7d20b14ce0e17b1bea42a06468125085500f46fa`.

## Confirmed defects

* Meteora exited before native initialization: `policy_for()` checked the old
  source policy-file hash instead of the approved composed hash. The prepared
  file matched `f64304f125edfde0af5dff04b53332bd811bce47cf27fd72e611dafc09abd916`.
  The worker now uses the same exact composed identity as source certification.
  Reverted, mutated and incomplete-manifest cases remain fail-closed. A new
  hosted supervisor regression invokes the real check in all four prepared lanes.
* Pons Survivor completed 96 steps, then its first graduation called the real
  factory reader with `{}` instead of a report containing `reads`. The resulting
  `KeyError: reads` terminated the lane. Initializing the required report fixes
  this caller contract. Regressions use the real factory-read/ABI path, verify
  candidate-history progression, and preserve missing-lineage rejection without
  advancing the cursor. Strategy policies and allocation are unchanged.
* Solana still recorded two `local_receive_backpressure_ping_timeout` and three
  `evidence_control_overloaded` discontinuities. Six gaps remained unresolved;
  Pump reported 31 gap-blocked local reads. The readiness gate correctly failed.
  Ordered persistence took about 370 seconds; background scheduling waited as
  long as 91.6 seconds. Control socket retries also re-enqueued accepted work.

## Solana repairs and deterministic evidence

The existing 64-frame/96-MiB dispatch bounds, 32-frame protocol queue, strict
ordered durable commitment, 8-frame/16-MiB commit ceiling, and 2-GiB hot-store
limit remain. No frame dropping, evidence substitution or strategy relaxation is
introduced.

The owner preserves strict lifecycle/foreground priority. Nonurgent work that
waits one second receives an oldest-first slot, allowing counters, repair and
bounded retention to progress during continuous commits. Background SQL still
yields to lifecycle/foreground requests. Pending socket retries share one
accepted future; identity conflicts fail closed and durable receipt checks remain
authoritative. The reply cache is bounded by the existing durable receipt ceiling
of 8,192 identities and the existing receipt expiry window; admitted work retains
the original 64-entry queue bound. Bounded per-priority queue/execution telemetry
exposes IPC work as well as stream work.

A real loopback websocket regression reproduces the old ping timeout when its
bounded data queue pauses all transport reads, including pong processing. The
repair retains pings but replaces that incompatible autonomous timer with an
explicit 20-second receive-idle bound and a 15-second stalled-commit bound during
admission pressure. Native heartbeat, finalized freshness, continuity and
candidate evidence gates remain unchanged. The silent-source test still creates
an explicit fail-closed gap. The pressure test drains 320 frames without churn,
checks ordering/coverage/durability, and retains the original memory bounds.

The old scheduler deterministically delayed a counter for ten seconds under
continuous commits; the repaired regression services it and maintenance within
the modeled one-second aging interval while preserving urgent precedence.
One hundred retries of a pending command consume one queue slot; distinct work
still rejects at the original bound and reserved lifecycle capacity remains.

The larger replay uses 16 lossless transaction bodies from the digest-pinned
Run 379 archive. Fixture SHA256:
`bad8b6bff69f8cd5976a5405ffed594943fe139dae497687a993728fb6143439`.
It processes 120 frames / 19,200 transactions (about 254 MB), concurrent control
requests and archival of an aged prefix, then proves authoritative local reads
from the fresh tail. Provider payload construction is prepared before service
measurement; the observer polls only bounded counters, rather than imposing
full SQLite telemetry scans on every poll. All 25 control requests complete,
archival advances before the stream finishes, all admitted frames drain, there
are no discontinuities/gaps, and SQLite integrity and original bounds hold.

Run 379's limited 429 responses remain separately attributable; Ramses completed
normally and rejected absent cost evidence. The Pons terminal traceback is the
caller-contract error above. No provider topology, governor or policy rule is
changed to increase activity. Missing Meteora native ledgers remain unknown in
the original artifact; no flat-balance proof is invented for that failed startup.

These are development regressions. A fresh complete exact-SHA hosted certificate
and successful smoke are still required before promotion or a final PAPER run.

## Hosted certification caught a completed-reply race

Candidate `da7f01634e7d1e432a5a48c20cf7220821e4c250` did not touch the market.
Full non-market run `36277256492` and standard CI `36277256361` both failed the
new dense production-pressure regression with `evidence_command_unacknowledged`.
The full artifact `10917419560` has SHA256
`46c9aa4a1affc317d7cdbb875d451c8552c67feae5cee82e4e6c2382b133ecba`.
All 373 supervisor tests, 423 Pons tests and 363 Ramses tests passed; the only
native errors were the same new pressure regression in Pump and Meteora.

The command had committed, but its earlier socket waiter had already received
pending. Removing the shared future immediately on completion forced the next
retry behind another large commit merely to retrieve its durable receipt.
Measured peak commits were 2.3–2.6 seconds. This second queue admission could
exhaust the unchanged three-second acknowledgment deadline.

Completed command futures now remain available through the existing durable
receipt expiry window. A retry returns the already-committed response directly;
new commands still use the original bounded owner queue. Envelope validation is
shared with the durable fence; conflicting identities, expired envelopes and
receipt-capacity exhaustion fail closed. Durable mutation/receipt atomicity,
command deadline and strategy behavior are unchanged. The cache stores bounded
control identities and replies, not market frames.

The deterministic regression commits a command, blocks the owner in the next
large commit, and retries after all original socket waiters have returned. The
old candidate creates a second queued future and fails; the repair returns the
completed future immediately. It also verifies conflicts, capacity and expiry
collection. The production replay is rerun in both composed Solana lanes before
submitting a fresh exact SHA to complete hosted certification.
