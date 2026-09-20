# Pump acquisition repair

Source branch: feat/pump-acceleration-independent-v1, exact source SHA
361d90dbfd12226467ac458f92b16a9f0b017fce. Stacked repair base:
6377b4c46da95c4591848939c714f7766e789acd (continuous paper campaign).
Frozen policy b273bc6be47d4f5a65f39d5d4f616777e02cbe547e19b7a07b0fefe23970c246.
No strategy, finality, signing or live-money authority changes.

Latest retained smoke 35483374004 / 2fa41cd0-88ba-4845-b167-ced816dca812:
390 discovered, two complete vectors, zero natural settlements. Read-only
acquisition review 35485976103 exposed 6,238 expired Pump-window jobs,
959 completed lower-priority research jobs, and candidate windows still marked
incomplete despite some body work having completed during the same refresh.
The 18 window acquisitions had p50 19.08 / p95 54.39 seconds.

Changes:
- A six-second decoder deadline applies across chunks; it is not renewed for
  every 16-body chunk. Missing evidence still fails qualification closed.
- Defer older second-leg history while the current decision window is incomplete.
  All frozen strategy modes remain; no history is fabricated or discarded.
- Reconcile captured stream misses against the shared immutable cache after
  bootstrap/decoder work, without another RPC. Do not preserve an obsolete miss
  count after that exact body was hydrated by this or another lane.
- Shared broker uses earliest deadline among time-sensitive decision classes,
  with open positions still first and background history still last.
- Requeue expired pending body work immediately, preserving active leases. This
  changes an infrastructure work request, never a candidate observation clock.

The existing three-attempt bounded bootstrap, exact 30-second horizon, stream
coverage, transaction-version support, global pacing/backpressure, immutable
reuse and accounting semantics remain. New budget/deferred-work counters remain
observable in history status; raw transport telemetry is unchanged.

Five failure cases were reproduced against the pre-repair behavior. Six new
regressions pass, including active-lease expiry protection. Full suite:
251 tests passed; python -m tests.resource_check passed. Command:
python -m unittest discover -v

Live throughput gain is not yet measured. Integration must run full gates,
clean concurrent smoke and a fresh four-hour window before claiming that gain
or natural lifecycle certification. These changes never patch a running lane.
