# Build status / continuation

## Repository and authority

Repository: `levonmendall/The-Meme-Machine` (public). Authorized minimal `main`
initialization remains `54712c4c6470cc4dc267888f934bd693aac030d0`.
Implementation branch: `feat/pump-directional-paper`; PR #1 remains open and unmerged.
Do not merge, deploy, purchase services, enable signing/submission/live money, add
DLMM/other venues, or alter predecessor repositories/services without separate
authorization.

Latest exact code-bearing verification before this documentation-only update:
`43afecb051b58143a4a480c7738551932d89f283`.
Push workflow: `35179532534`.

## Implemented directional boundary

The sole implemented venue remains Pump.fun on Solana mainnet. The paper lifecycle is:
wallet scouting -> independent `continuation-v1` qualification -> shared $500 allocator
-> reservation -> delayed finalized quote/fill -> independent monitoring -> exit ->
settlement -> restart reconciliation. DLMM remains disabled.

Ordinary native-SOL and native-SOL Mayhem curves are supported. Cashback and
non-native quote assets remain fail-closed. The disclosed Mayhem agent wallet cannot
scout or count as independent-demand corroboration. No `continuation-v1` economic
threshold, sizing rule, exit rule, event-cap rule, or portfolio rule changed during
the storage/memory work.

`Engine.qualify` remains the entry-selection portion of `continuation-v1`; the full
strategy also includes scouting, allocation/sizing, delayed execution, monitoring,
exit rules and settlement.

## Point-in-time market evidence

The complete 60-second pool-history problem remains solved by one finalized
Pump-program `logsSubscribe` stream with a bounded in-memory tape. A full uninterrupted
60-second warmup is required before any scout trade gains nomination authority.
Disconnect, parse loss, capacity loss, or time inconsistency removes coverage and
requires fail-closed recovery. The stream has observation authority only.

Previous live proof produced natural post-warmup nominations with complete 60-second
windows. The compact same-provider finalized `getProgramAccounts` concentration path
is also live-proven and keeps the existing <=35% concentration rule unchanged.

The remaining strategy proof is still a naturally nominated, stream-covered candidate
reaching final snapshot evidence and unchanged `Engine.qualify`. Do not alter the
>100-event evidence cap or any economic threshold merely to force a qualification.

## Forced real-data canary boundary

An isolated forced real-data canary at
`d724bc8d6fdbc3f239b311bad0cb20baecdca865` proved the downstream mechanical path:
reservation -> delayed real-data paper fill -> Store restart/reconciliation ->
monitoring -> exit intent -> real-data settlement -> final reconciliation.

That canary used a temporary isolated portfolio and deliberately forced authorization;
it is **not** strategy or profitability evidence and did not touch the authoritative
$500 portfolio. It used no signing, submission, deployment, or live money. Its selected
candidate was independently rejected by unchanged `continuation-v1` for
`exit_liquidity`, which was preserved as the true strategy result.

No additional forced canary should run automatically.

## Storage / memory longevity milestone

The system now has explicit continuous-runtime bounds instead of relying only on the
32 MiB pressure stop.

### 1. Bounded journal-tail rotation

`store.py` retains at most **4,096 journal event bodies**. When the retained tail is
full it retires the oldest rows back to **2,048 retained rows** inside the same SQLite
transaction as the next durable action. The last retired sequence/hash becomes the
new cryptographic chain anchor. Startup verifies the retained first-row/anchor
boundary and tail; `verify_archive()` verifies the complete retained chain from that
anchor.

This is deliberately bounded retention: retired event payloads are not kept forever.
Current portfolio/accounting authority remains in the hashed state checkpoint and the
retained journal continues the hash chain from the compact retired-history anchor.
SQLite pages are reusable after rotation, so allocated DB size can plateau rather than
scale with total runtime.

### 2. Repeated unresolved-monitor coalescing

Open positions are still polled at the existing five-second monitoring cadence.
However, if the exit mark remains identically unavailable, only one unresolved state
is durably journaled per **60 seconds**. Intermediate identical failures return
`unresolved_coalesced` without another SQLite write.

A recovered quote is persisted immediately. Real failed exit attempts are never
coalesced because they have economic gas-cost/accounting effects and remain fully
auditable.

### 3. Deterministic regression proof

Exact head `43afecb051b58143a4a480c7738551932d89f283` passed the normal test job in push
workflow `35179532534`:

- **65/65 deterministic tests passed**;
- new regressions prove journal rotation + restart chain continuity;
- retained-tail corruption is still detected after rotation;
- repeated unresolved monitor writes are coalesced;
- real failed exit attempts still create distinct durable accounting events;
- bounded synthetic workload remains 2,000 frames / 240,000 submitted events;
- resource workload DB: **1,261,568 bytes**;
- resource workload WAL: **708,672 bytes**;
- resource workload peak RSS: **27,260 KiB**;
- synthetic connected entry -> monitoring -> exit -> settlement remains green.

### 4. Accelerated 24-hour high-traffic soak

Workflow `35179532534`, job `105068502765`, ran:

```sh
python -m tests.longevity_soak --hours 24 --events-per-minute 1200 --writes-per-minute 12
```

This represents 24 logical hours at 1,200 decoded events/minute, the normal twelve
durable heartbeat writes/minute, and a continuously unmarkable open position polled at
the existing five-second cadence. The harness also continuously churns the bounded RPC
cache.

All plateau assertions passed. Key evidence:

- **18,725** total journal events were written during the experiment;
- **8 journal rotations** occurred;
- final retained journal rows: **2,333**;
- final retired-history anchor sequence: **16,392**;
- final DB: **1,093,632 bytes**;
- final WAL: **865,232 bytes**;
- combined DB+WAL allocation stabilized at **1,958,864 bytes** from hour 8 through
  hour 24;
- hourly durable write rate stayed exactly **780 writes/hour** rather than increasing
  with runtime;
- finalized-tape occupancy stayed at **2,400 events** with **0 capacity losses**;
- RPC cache stayed at **128 entries** and about **20 KiB**;
- RSS reached **30,232 KiB** by hour 8 and remained at that high-water mark through
  hour 24;
- `journal_rows_bounded=true`;
- `journal_rotated=true`;
- `late_storage_plateau=true`;
- `late_rss_plateau=true`;
- `write_rate_not_accelerating=true`;
- `late_write_rate_not_higher_than_early=true`;
- all tape/cache bound assertions passed;
- failed assertions: none.

The accelerated run completed in about **17.6 wall-clock seconds**. It proves bounded
logical-runtime behavior under sustained synthetic load; it is **not** a substitute
for holding one process alive for 24 wall-clock hours. `tests/longevity_soak.py
--real-time` provides that mode when a suitable durable host is explicitly authorized.
No deployment or paid infrastructure was added for this milestone.

## Current storage/memory assessment

There is now direct evidence that the major hot-state structures do not scale linearly
with runtime under the tested workload. The design is materially different from the
old repository's accumulation pattern: the finalized tape, RPC cache, decisions, gaps,
dedup state and journal event bodies all have explicit bounds, and repeated identical
unresolved monitoring no longer creates five-second durable-write growth.

Remaining limitation: no claim is made yet about a true 24-hour wall-clock process
residency test on a durable host, filesystem-specific long-run behavior, or future
additional venues. Those should be measured before broadening deployment scope if a
stronger operational certification is required.

## Reproduce

```sh
python -m pip install -r requirements.txt
python -m unittest discover -v
python -m tests.resource_check
python -m tests.make_tape
python -m meme_machine --mode synthetic --config config.synthetic.json --db /tmp/meme-fresh.db --tape tests/fixtures/synthetic_lifecycle.jsonl
python -m tests.longevity_soak --hours 24 --events-per-minute 1200 --writes-per-minute 12
```

True wall-clock residency mode, only on an explicitly authorized suitable host:

```sh
python -m tests.longevity_soak --hours 24 --events-per-minute 1200 --writes-per-minute 12 --real-time
```

Natural no-order-authority qualification remains:

```sh
python -m tests.prospective_stream_qualification
```
