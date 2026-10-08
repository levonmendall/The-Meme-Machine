# Autonomous native PAPER position continuation

Disposition: **BLOCKED_BY_SPECIFIC_PROVIDER_OR_RESOURCE_CONSTRAINT**.
Engineering is published on `engineering/autonomous-position-continuation-20261008`,
starting exactly at `6d14ceec7167b29b5a38c686e4abbfe07a2d4cfa`. Nothing was deployed,
selected, enabled, funded or started on Droplet 605465049. First-position funding
remains closed. This is an engineering receipt, not operational authorization.

## Architecture and repair

The existing `meme-machine-paper.service` and operational supervisor already own
the shared authority, one supervisor flock, lane process locks, process instance
tokens, restart backoff, authenticated evidence worker, provider governors and
native recovery before discovery. SQLite FULL-sync journals, verified replay,
idempotent prepare/delivery and native pending reconciliation remain authoritative.
Pump Current runs `runner._monitor_positions` and its original acceleration
lifecycle. Pump Survivor runs `pumpswap_survivor_runtime.Runtime` through the
existing serialized Survivor Worker. Pons Current runs the original cohort
lifecycle futures, selective PAPER controller and `submit_existing_lifecycles`.
Pons Survivor runs `pons_survivor_runtime.Runtime` on its existing Survivor Worker.
There is no new service, execution manager, database, queue, infrastructure or
approval/signing system. The original four accounting identities remain intact;
only Pump/Pons receive worker processes.

The published bootstrap candidate stopped all those owners at 1,735 seconds
and used `Restart=no`, leaving any open position durable but unmanaged. The repair
makes admission a finite phase of the existing service. `position_continuation.py`
coordinates BOOTSTRAP → CONTINUATION → RECOVERY → FLAT, with explicit FAULT when
protection is unavailable. Economic ownership never transfers to another engine.
Original entry time, 72-hour Survivor deadline, high-water mark, trailing state,
partial realization, remaining quantity and 36-hour Current bridge are unchanged.

Changed components:

* `operational/admission.py`, `supervisor.py`, `position_continuation.py`: verified
  continuation prerequisite, irreversible funding/work closure, normal restart
  restoration, original clocks/claim/allocation, held-lane supervision and flat
  cleanup after native plus shared reconciliation.
* `operational/bounded_provider.py`: separate bootstrap/continuation/recovery
  counters inside the existing finite usage SQLite database. Requests, batches,
  retries and stream opens count before dispatch. Application response/native
  bytes and reserved/uncertain SDK buffers remain charged; dead process buffers
  are reaped once without closing another live process's streams. Phase transfer
  does not create a second connection or double-charge a received response.
* Pump runner, Pons cohort/PAPER/provider admission, both Survivor runtimes and
  `runtime/survivor_history.py`/`survivor_commit.py`: retain native monitoring and
  exits, stop optional discovery and denied-addition probing, record rejection,
  cancel verified unfilled reservations, stop empty Survivor provider work and
  publish actual position evidence/quote availability alongside native replay.
* Selective Solana source/history: stop scout and whole-program optional feeds,
  cancel an already-running optional subscription, retain priority 0–2 held
  interests and their original deadlines, and preserve the existing startup
  authority on restart. Closed optional pages remain incomplete and recoverable.
* Operational lane/observer/monitor: retain native status at shutdown, expose
  phase usage, actual cgroup resources and precise unavailable-protection faults.
* `deployment/paper-bootstrap.conf`: the same service uses restart-on-failure,
  CPUQuota 180%, MemoryHigh 6 GiB, MemoryMax 7 GiB, an absolute lifecycle deadline
  enforced in durable code and a final systemd containment limit. No unit installed.

## Lifecycle and recovery evidence

Funding begins closed. Arming requires 60 seconds of the existing full startup
observation, advancing Pump/PumpSwap/Pons frontiers, native restoration/replay,
handoff and exit wiring, authenticated fresh evidence, shared reconciliation,
provider queue health and verified existing-service cgroup limits. Missing
configuration or native/provider readiness cannot arm funding. This uses existing
operational health and native state, not a process heartbeat alone.

At original start +1,200 seconds, funding and optional work close. No new position
or addition is possible; rejected additions retain diagnostic state. At +1,735
seconds the bootstrap phase closes, reserving its original 65-second shutdown
allowance. Optional workers/transports drain; the same native owner remains alive
for a held position. At +1,800 seconds its management is independent of bootstrap.
Restart closes funding, restores the same run/usage database and native journals,
and neither replenishes the claim nor moves any economic deadline.

The accelerated native Survivor test held through 72 hours, including partial
realization and restarts at hours 1, 36 and 71. Entry time 10, high-water 4,000 bps,
300 remaining of 400 original units and realized 7 remained intact. At the original
72-hour deadline an unavailable quote preserved `maximum_hold` exit intent. A
restart plus fresh PAPER quote settled once; cash 1,022 and final native replay
matched, and duplicate observation caused no new settlement. Existing authentic
offline native Pump/Pons recovery tests also exercised actual controllers,
partial exits, shared delivery interruption, duplicate economic events, original
tail behavior and exclusive position ownership.

Provider degradation closes funding immediately and records the precise blocker,
`protected=false` and an incident deadline in the same usage database. Original
native fresh evidence checks still govern decisions; missing quotes retain exit
intent. Ordinary reconnect/recovery consumes the same remaining budgets and needs
no new approval. Recovery deadlines survive service restart. Lost evidence and
resource exhaustion do not produce a synthetic exit or reconciled-flat claim.
Recovery beyond 72 hours is allowed for exit/reconciliation: up to 3,600 seconds,
within original start +264,000 seconds plus 65 seconds final shutdown. Exhaustion
leaves a durable actionable FAULT and the existing independent monitor; it does
not claim an open position is protected. This unresolved resource contingency is
why funded activation is blocked, not permission to abandon an exit.

The temporary service finishes only when actual native owners are flat/reconciled,
shared reservations/commitments/obligations/inbox/pending delivery are empty and
shared replay verifies. An interrupted reconciliation keeps its owner alive.
An idle Survivor worker and Solana source stop provider work when no relevant
obligation requires them. Ramses/Meteora have no discovery, qualification,
history, maintenance or strategy workers.

## Provider envelope and limits of the evidence

`RESOURCE_ENVELOPE.example.json` is a proposed finite resource configuration,
**not approved**, not an account quota and not a prediction of production demand.
Native state has no schema migration; only the new run's existing usage ledger
has additional phase/ownership rows.

| Allowance | Original bootstrap | Proposed continuation | Separate exit/resource recovery |
| --- | ---: | ---: | ---: |
| Modeled RPC CU | 720,000 | 24,000,000 | 2,400,000 |
| RPC elements | 10,000 | 500,000 | 50,000 |
| Physical HTTP/stream attempts | 10,000 | 500,000 | 50,000 |
| Native exposure, including unread reserves | 4 GiB | 32 GiB | 1 GiB |
| Measured HTTP response application bytes | counted | 1 GiB | 128 MiB |
| Conservative modeled spend | $3 | $20 | $2 |
| Actual native opens per phase | existing attempt ceiling | 32 | 32 |

Queue depth 64 and queue wait 5 seconds close funding and trigger bounded
degradation recovery; original governors retain protective priority. Actual
cgroup CPU/memory and queue latency are published. CPU is capped at 1.8 cores;
6 GiB is the readiness/degradation threshold, 7 GiB final cgroup containment.
Memory exhaustion retains durable recovery/escalation, not a protection claim.
All provider usage remains separately observable by phase and provider family,
including Alchemy RPC CU. The 32-GiB native cap also bounds the conservative
websocket model to 6,871,947.6736 CU equivalents, separately from the 24M RPC
allowance; gRPC is bandwidth-priced. Traffic counts application payloads, not unverified
provider wire/invoice bytes. Physical attempts include both HTTP and native opens.

Expected work is one held native lifecycle's original marks, authenticated flow
and structural evidence, quotes, partial/final exits and reconciliation. Pump and
Pons Current poll at their original five-second cadence; Pons Survivor's existing
three-second cadence allows up to 86,400 turns over 72 hours. Its pinned V4 quote
alone has six logical RPC elements before flow, valuation and execution work;
physical counts depend on existing cache hits and provider behavior. Thus 500,000
elements is not demonstrated sufficient. No slowdown, weaker safety or assumed
savings is used to make that proposal fit. Pump traffic also depends on the held
market and authenticated control/recovery volume, which is not bounded by the
nominal one-position count.

The conservative model retains frozen method weights, $0.525/M CU and native
bytes at the higher .0002 CU/byte websocket rate, including reserved uncertainty.
At 24M RPC CU plus 32 GiB native exposure its model is about $16.21; the recovery
envelope is about $1.37. These are arithmetic upper scenarios within the defined
payload model, not measured bills, forecasts or proof of sufficient management.
Account fees, provider metering and future method mix remain unverified. Published
references: [Alchemy pricing](https://www.alchemy.com/pricing) and
[CU/bandwidth schedule](https://www.alchemy.com/docs/reference/compute-unit-costs).

Integration dependencies are already ancestors, preserved without rebasing:
Alchemy acquisition `4c219ed575092195c2db92cd060c9721e3dd8962` and Robinhood PAYG
`73243cb0c135197359c23cce46d3a91a48d8b40a`. Scout-first discovery, filtered log
capability, selective hydration, shared cache/authenticated evidence and bounded
candidate histories remain. No seven-day startup backfill, full transaction feed,
duplicate Survivor discovery or unnecessary PumpSwap body hydration is introduced.
The full 72-hour physical/provider budget remains unproven and cannot be inferred
from the preserved technical captures or these offline tests.

## Validation, preservation and deployment plan

Final focused checks: **261 passed, 0 failed, 0 skipped**: admission/continuation 36,
native recovery/operations 86, acquisition/efficiency 125, campaign scheduling 14. No broad suite or paid
provider workload ran. The test runner rejected market I/O and used temporary
state. Initial failing runs were repaired without relaxing assertions; their
logs/scratch receipts remain outside Git. `VALIDATION.json` records commands,
source digests, counts and log digests. Existing unchanged Survivor risk/prefix
regressions also passed during the earlier focused native run; they are not added
again to the final 261. A final 32-test supervisor/monitor repeat also passed,
without double-counting those tests. The CI skip marker prevents publishing this branch from
restarting the repository's broad FAST workflow.

Fresh read-only verification on 2026-10-08 confirmed Droplet 605465049, mounted
state, stopped/disabled PAPER, original $500 epoch `paper-1791089005190643467`,
canonical sequence 2036, exact original monetary digests, approved policy/migration
and 47 backup files. Existing backup point
`meme-machine-paper-20261008T040243-cd2edc34` and off-host volume snapshot
`23ad67f3-c2cd-11f1-b847-eaa4572de3ae` match their recorded resource/replay identity.
No restore, snapshot, reset or cutover performed. `PRESERVATION.json` retains this
fresh receipt; native journals and concurrent engineering worktrees are untouched.

Deployed source is still `b577cc1c67f4d64f887b430f5e933f376b607dc2`. Its CPython
3.12.14/SQLite 3.45.1 are correct, but the deployed venv lacks pinned grpcio,
protobuf and based58. Validation used the existing isolated engineering venv with
all pinned requirements; no deployment dependencies were installed.

Only after separate explicit authorization of the exact corrected SHA and a
demonstrated adequate continuation envelope, the existing-host plan is:

1. Repeat fresh storage, backup, epoch, policy and monetary verification while
   native writers remain stopped. Preserve all state and the original epoch.
2. Fetch the published branch into `/opt/meme-machine`, check its worktree is
   clean and check out the exact authorized SHA; install its pinned requirements.
3. Reuse the approved migration plan and `cutover.install(...,
   observation_only=True)` with authentic verified storage/backup/native mapping
   prerequisites and `provider_proof_verified=False`. Funding stays closed.
4. Install the specifically authorized finite envelope at
   `/etc/meme-machine/position-continuation.json`, readable by the service. Install
   `deployment/paper-bootstrap.conf` as the existing unit's drop-in. Refresh the
   already-existing observer/monitor code; keep PAPER disabled for reboot startup.
5. `systemctl daemon-reload` then one explicitly authorized
   `systemctl start meme-machine-paper.service`. Existing supervision restores
   ordinary crashes through the same bounded continuation without reauthorization.
   Do not remove the drop-in or change the envelope while any obligation remains.

The repository CLI already exposes only finite observation/bootstrap and the
separately gated ordinary operations. Minimal deployment shell commands are
`git -C /opt/meme-machine fetch origin engineering/autonomous-position-continuation-20261008`,
`git -C /opt/meme-machine checkout --detach <AUTHORIZED_EXACT_SHA>`,
`/opt/meme-machine/.venv/bin/python -m pip install -r /opt/meme-machine/requirements.txt`,
then install the reviewed drop-in/configuration and the two systemctl commands
above. The migration is the existing install function, with no new approval tool.
These commands are a plan and have not been executed.

## Authorization boundary and genuine blockers

Funding remains closed: adequate held-position provider usage/latency across the
entire holding/recovery obligation has not been demonstrated within the proposed
limits. The pinned dependencies must be installed on the existing host during an
authorized deployment, and runtime subscriptions/resource enforcement must be
verified by the existing startup health before any funding. There is no claim of
an authentic funded production lifecycle or live recovery acceptance.

One owner authorization can cover the unchanged FIRST_POSITION_PAPER_BOOTSTRAP
envelope plus separately bounded AUTONOMOUS_POSITION_CONTINUATION in the same
service: no new entries/additions after funding expires, no new capital claim on
restart, original economic deadlines, existing PAPER execution only and automatic
cleanup when flat/reconciled. That is distinct from the prohibited AUTONOMY
acceptance phase. CAPACITY, RECOVERY acceptance, AUTONOMY, other strategies,
real-money activity and additional provider trials remain separately prohibited.
Do not start or fund this candidate solely because its offline tests pass.
