# First-position PAPER bootstrap

The zero-position epoch previously could not start its evidence worker because
funded-position latency had not been proved. Read-only acquisition now starts
independently. The existing latency guard has moved to normal capital admission,
normal startup and operational acceptance. It remains closed. Bootstrap does not
certify itself or promote into normal admission.

This branch descends directly from `4c219ed575092195c2db92cd060c9721e3dd8962`,
tree `fb5253ff67b96b1f07ccecf803c85252c463487f`, in
`levonmendall/The-Meme-Machine`. It has not been deployed. Droplet `605465049`
still runs the stopped, unchanged `b577cc1c67f4d64f887b430f5e933f376b607dc2`
checkout. Protected configuration and canonical monetary file digests are
unchanged. Epoch `paper-1791089005190643467` retains its original $500 PAPER,
sequence 2036, zero positions, reservations and pending deliveries.

| Boundary | Behavior |
| --- | --- |
| `observe --seconds N` | Existing canonical ingestion and all four Pump/Pons qualification paths; funding closed. Legacy independent funding cannot be used. Existing position safety and delivery recovery remain available. |
| `run` / `normal` | Existing latency guard blocks startup and new exposure. Authentic evidence must receive explicit operational disposition before this blocker can be retired. |
| `bootstrap` | Starts with funding closed. After readiness, the existing allocator can fund one native lifecycle within a durable finite allowance. All other opportunities continue acquisition and qualification. A claimed allowance survives cancellation and restart. |
| AUTONOMY | Guarded admission plus existing same-candidate CAPACITY and RECOVERY PASS receipts. The normal acceptance executor preserves the full 129,600-second window. |

Before the first PAPER position opens, the original storage/epoch fence, approved
shared-capital migration and risk policy, native replay/reconciliation, four
active regime manifests, paused-family emptiness and finite provider allowance
must be valid. Operational health must remain healthy for 60 continuous seconds,
with advancing Pump, PumpSwap and Pons canonical frontiers, source startup
released, complete Pons Current startup coverage, fresh heartbeats, provider
queues no older than five seconds and process RSS below 6 GiB. Readiness must
finish within 600 seconds.

Every candidate must still pass its original qualification, maturity, generation,
execution freshness, executable exit checks, valuation expiry and allocation
rules. Original native sizing, fees, shared cash, risk caps, priority, deadlines,
scaling and exit controllers are preserved. Pump Current, Pump Survivor, Pons
Current and Pons Survivor keep their market coverage. Meteora and Ramses remain
paused. There are no wallet keys, signing or real-money submissions.

The missing authentic evidence is an actually funded native lifecycle maintained
while candidate acquisition remains active: original executable mark/exit inputs,
high-water and safety decisions, native journal and shared-capital continuity,
physical provider waits/latencies and original deadline outcomes. Existing native
books, reports and provider ledgers collect these facts. A nominal quote, a
fixture, an unfilled reservation, a CURRENT USD projection alone or one successful
path cannot certify unobserved paths. The guard remains
`combined_position_and_candidate_provider_latency_not_certified` until that
combined evidence receives explicit review. A missing qualifier or management
sample is INSUFFICIENT_SAMPLE. No 300-second technical proof is requested.

The finite run uses the previously validated HTTP/native boundary wrappers;
their proof workload, artificial disconnect and scheduling hooks are unused.
One cross-process usage ledger counts attempts before dispatch, batches and
retries, delivered native bytes and reserved unread SDK buffers. Existing monitor
alerts now cover a manually started disabled unit and remaining economic
obligations. The existing alert delivery route is unchanged.

Preparation evidence is in [PREPARATION.json](PREPARATION.json): 27 focused
offline boundary checks passed, configured-source/storage checks passed without
provider I/O, and canonical monetary digests match the initial readback. The
baseline FAST run stalled in its existing unsupported archive-page case and was
interrupted; its incomplete receipt and the corrected fixture/selector failures
remain preserved outside Git. No full-suite PASS is claimed.

Reuse these completed receipts:

* [Accepted migration and risk approval](../shared-capital-activation/OWNER_APPROVAL.json),
  [migration identity](../shared-capital-activation/MIGRATION.json), and the existing
  full migration plan at `/mnt/volume_nyc1_1790918115030/shared-capital-validation-20261007/actual-epoch-migration-plan.json`.
  Plan SHA-256: `45ce1ec34183d7b143ec382e002e4094f97de25d81e381f99dcff4c1d2abfada`.
* [Maintenance/finite executor validation](../maintenance-provider-proof/VALIDATION.json),
  [Model B preservation](../pump-provider-finalization/PRESERVATION.json),
  [completed acquisition validations](../final-acquisition/REGRESSIONS.json) and
  [prior provider proof dispositions](../shared-capital-activation/PROVIDER_PROOF.md).
  Their paid-run approvals are consumed.
* Latest off-host snapshot `23ad67f3-c2cd-11f1-b847-eaa4572de3ae`,
  point `/mnt/volume_nyc1_1790918115030/meme-machine-backups/meme-machine-paper-20261008T040243-cd2edc34`:
  47 file digests reverified, 896,335,681 bytes, zero mismatches and matching
  canonical replay. Reuse the existing G02 authentic isolated restore and source
  reverification receipts in the 2026-10-05 operationalization workspace. A new
  shared-authority off-host restore has not been claimed.
* Existing G03 owner-email delivery receipt, enabled DO uptime check and one
  owner email recipient. No new alert message was sent.

After explicit approval, deploy this published descendant with the pinned
CPython 3.12.14 runtime/dependencies. While all PAPER writers remain stopped,
recheck the preserved identity, verified backup, native mapping, recovery receipt
and matching approved policy; use the existing `cutover.install` with
`observation_only=True`. Keep `provider_proof_verified=False` and all other
required prerequisites authentically verified. This selects shared accounting
with funding closed; it does not reseed or certify providers.

Install [the prepared bootstrap drop-in](../../deployment/paper-bootstrap.conf)
on `meme-machine-paper.service`, refresh the independent observation/monitor
consumers to this candidate, keep PAPER disabled
for automatic startup and start the single authorized bootstrap. `Restart=no`,
the 1,735-second service limit and 65-second shutdown allowance enforce an
independent 1,800-second ceiling. Do not reuse its allowance after interruption.
At shutdown preserve any open position or pending native delivery for original
recovery; there is no forced synthetic exit. Remove the bootstrap drop-in before
the existing CAPACITY → RECOVERY → AUTONOMY workflow. Those phases retain their
full durations and require separate provider authorization.

**Authorization requested — FIRST_POSITION_PAPER_BOOTSTRAP only:** approve
deployment and the observation-only authority selection above, then one run of
at most **1,800 seconds including startup/shutdown**, with new funding closed at
**1,200 seconds**, **one native PAPER lifecycle** and **$25 maximum cumulative
gross PAPER allocation including costs and approved adds**. Paid providers are
the existing Alchemy Solana HTTP/Yellowstone/WebSocket and Robinhood HTTP
endpoints; existing public Pons observation RPC also counts toward request limits.
Shared ceilings: **720,000 modeled RPC CU**, **10,000 RPC elements**,
**10,000 physical HTTP/stream attempts**, **4 GiB total native exposure including
2 GiB reserved shutdown buffers**, and **$3 conservative modeled provider spend**.
Billing remains unmeasured; the cost model uses the published
[CU schedule](https://www.alchemy.com/docs/reference/compute-unit-costs) and
[PAYG price](https://www.alchemy.com/pricing), with conservative frozen method
weights. Stop on quota/time exhaustion, readiness timeout, lost health/coverage
or reconciliation; native qualification/freshness/deadline failures reject
exposure. No qualifying fill by the funding cutoff produces no position sample
and no automatic extension. This approval does not authorize CAPACITY, RECOVERY,
AUTONOMY or any real-money transaction.
