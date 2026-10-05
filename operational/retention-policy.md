# PAPER data retention

The retained economic epoch and frozen strategy rules govern operation. Learning
is analysis data: it never qualifies a market, alters a policy, obtains provider
data, retrains a model or admits economic work.

| Persistent family | Class | Lifetime / bound |
| --- | --- | --- |
| Portfolio inception, binding, sleeve capital, reservations, positions, native pending deliveries, lifecycle aliases and reconciliation prefixes | A AUTHORITATIVE_ECONOMIC_STATE | Epoch lifetime. Native reducers preserve exact Decimal cash, realized P&L, replay identities and acknowledged delivery. Closed lifecycle aliases fold into constant sized lane prefixes; historical samples and repeated marks fold through existing journal checkpoints. |
| Native Pump, Pons, Meteora and Ramses books; Current and Survivor controllers; active execution and settlement joins | A plus B ACTIVE_OPERATIONAL_EVIDENCE | Live positions/reservations/deliveries retain their original entry and recovery anchors. Terminal prefixes fold only after native/shared acknowledgements and the frozen lifecycle expiry. No retention path initializes an epoch. |
| Shared Solana records, lineage, hot chunks, archived raw bodies, address dictionaries, coverage, stream receipts, gaps, subscriptions and interests | B | Existing three minute hot tail, bounded owner slices, two GiB hot-store guard, monotonic floors and reference reachability. Active interests, gaps, account continuity and recovery prevent premature retirement. Unreferenced manifests queue physical file deletion in the same commit; at most 32 files unlink per maintenance turn. |
| Archive publication markers | B while in flight, E thereafter | Publication registers before writing raw bytes. Successful commit removes the marker. Interrupted publication gets one day grace and then at most four probes per minute, with a 10,000 directory-entry ceiling. An orphan expires only after checking native record, interest and gap references. Unknown files and symlinks are never followed/deleted. |
| Survivor graduation/candidate identity, recent authenticated events, price bars, exact reset reducer prefix | A identities, B evidence | Existing 64 candidate/100,000 point per candidate ceilings, one hour event history, one day price prefix folding. An open position cannot retire its candidate. Compact price extrema persist before raw bars expire; missing continuity remains missing. |
| Directional opportunity receipts, links, verified price observations and outcome scans | B until observation ends, C LEARNING_RECORD thereafter | Raw journal 4,096 rows, at most 512 retired per owner slice; at most 1,024 outstanding targets, five fixed windows through one day, bounded enrichment and export scans. Missing observations explicitly produce unknown/incomplete outcomes. |
| Compact decision, rejection, progression, lifecycle and outcome facts in `learning_facts_v1` | C | Per SQLite store: 8,192 rows, 64 MiB compressed bodies, 256 KiB uncompressed per fact. Four fixed statistical rollup buckets. Ordinary rejection facts expire first; observed 5x/10x/25x/50x winner facts and their rejection inputs receive priority. Limits remain finite even for winners. No full block/transaction/snapshot reconstruction is retained for learning. |
| Lane pipeline progress | D OPERATIONAL_TELEMETRY plus C material evaluations | Existing 4,096–8,192 debug transition ring. Before deletion, evaluated vectors, exact rejection reasons, qualification, capacity failures, entry/exit and terminal facts enter the bounded learning store. Native pipeline and strategy source are unchanged. |
| Provider governors, demand/queue state, evidence consumers and generation/ordering fences | B while pending; D completed audit | Pending work and active consumer references retain their operational state. Existing completed audit rings retain at most 4,096 rows; Robinhood service samples retain 256. No observer acquires the economic owner lock or uses provider budget. |
| Solana immutable transaction cache, legacy cache and signature interests | E, B for active consumers | One day TTL, protected waiting consumers, orphan interest expiry; old speculative pacing epochs keep two ten-second epochs. Acquisition and hydration audits retain 4,096 rows. |
| Robinhood candidates, observation/transitions, RPC evidence and rolling views | B when referenced, E otherwise | One day idle candidate/cache expiry with pending/claim/consumption/native-position protections and lane ordering prefixes; evidence namespace caps 4,096 (8,192 receipts), rolling window 60 seconds/400 rows per candidate plus one day global expiry. |
| Health, portfolio/dashboard JSON, report projections and publication temporaries | E | Atomic replacement, bounded readers and one canonical projection per producer. Debug JSONL retains 256 rows. Temporary prefix copies are removed by their existing context manager. Projections grant zero trading authority. |
| Observer, monitor, metrics and Uptime state | D/E | Observer: 15 second cadence, 32 KiB sample, seven days/512 MiB log ceiling; one latest/integrity projection. Fixed monitor condition timers/restart rings and fixed public metrics. OS CPU/memory and read-only filesystem limits isolate observation. |
| Acceptance phase stdout/stderr, observations, result/status and temporary files | D/E | 8 MiB per stdout/stderr, 512 MiB observations, eight completed attempts; active/latest attempts protected. Durable systemd unit plus one phase flock. Abnormal termination records failure. |
| Local coherent backup points and DigitalOcean Volume snapshots | Recovery copy of A/B/C | Three completed and three interrupted local points, three off-host snapshots for this volume/prefix only. Unknown/foreign resources are not pruned. SQLite backup and isolated restore verification preserve epoch and single-writer fencing. |
| Journald | D | Host configuration: seven days and 256 MiB. No provider credential values in logs or projections. |

Compact facts retain exact strategy inputs, policy identity, reasons, existing
execution conditions, native entry/partial/scale/exit actions and contribution.
Observed price extrema use exact fractions. Underlying winner labels and native
portfolio outcomes remain distinct. Incomplete evidence never implies a complete
MFE/MAE or counterfactual return; observed winner multiples are lower bounds.

SQLite learning changes commit on the existing native writer, before the relevant
raw fold. Replay and economic reconciliation exclude these analysis tables. The
original authoritative prefixes and active evidence remain the recovery source.
Cold-start storage cleanup uses the existing owner and archive executor before
new market ingestion, preserving original evidence times, gaps and references.

Whole-volume observations record total/used/free/percent, state-root, main DB,
WAL, physical archive and compressed learning bytes. Persistent 85 percent use
or the existing free-space floor produces owner attention. Durable CAPACITY and
AUTONOMY status records baseline/end growth, bytes/hour, peak WAL, archive and
learning growth and a conditional time-to-capacity projection. Observer cgroup
CPU and memory are recorded separately from economic process capacity.
