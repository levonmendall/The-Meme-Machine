# Run 381 remaining archive-progress repair

Full certificate 36293751021, exact SHA
3d4be5c538fdde44b37c159c5c5dad9200a5039e, failed; it is not certified or
promoted. Artifact 10923193063 has digest
f1d7c62e6e5861a79526d4f7e12ccca2674b5566384094c967fa61418b79eb40.
Native, supervisor, SIGKILL, restart, integrated and resource gates passed.
At 1,743 source frames, oldest retained evidence reached 240.35 seconds.
All 1,744 admitted messages drained, no runtime disconnect/capacity stop occurred,
and source lag peaked at 2.41 seconds. Archival/cleanup throughput was insufficient.

Owner source execution averaged about .163 seconds/frame; archive workers took
about .358 seconds/1,000 prepared records. The source remained fresh while 1,552
subscription polls queued priority-zero reads, even with no account interests.
There were 120 interrupted archive plans and 47 interrupted archive commits;
275 commit/plan calls spent 100.46 seconds waiting and 334 plan calls spent
72.39 seconds waiting. Completed archive publication alone is insufficient.

The repair replaces unchanged priority-zero subscription polling with a single
thread-safe dirty hint. Committed interest/release changes and candidate expiry
set it; a new connection always forces a durable-state reload. It is cleared
before the owner read so a concurrent change remains signaled. The same .25-second
cadence, priority-zero real reconciliation, 256-account bound, ordering and
PAPER-only authority remain. The hint never supplies account or evidence authority.

Four new regressions cover quiet subscriptions, mutation during send, a disconnected
IPC waiter, expiry and restart. The quiet-state regression fails the exact old
implementation (five priority-zero reads instead of one). Focused service/fence
checks passed 17 tests, and 26 archive/retention/Run376/atomic-frame checks passed.
A 32-frame smoke of the provider-free measured-contention fixture passed, with
one initial sync and 35 unchanged polls avoided.

The diagnostic replay now has an optional measured-contention profile enforcing
minimum owner duration .165 seconds/frame and archive-worker duration .36 seconds
per 1,000 records, rounded up from the failed full certificate. It also records
bounded CPU/affinity/quota/load counters. These are test-only timing floors, not
production delays, queue growth, threshold changes or relaxed acceptance bounds.
The full old/repaired 600-second comparison must stabilize before another full
certificate, and an exact-SHA full certificate must pass before any market run.
No signing, submission, live money, deployment or Render interaction occurred.
