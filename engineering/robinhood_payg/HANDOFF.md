# Remaining path to autonomous PAPER

The source is an offline engineering release, not a deployment. Keep
`combined_position_and_candidate_provider_latency_not_certified` until actual
qualifying evidence clears it. Do not repeat completed strategy engineering,
global historical bootstrapping, or architectural comparisons.

1. This branch already integrates committed maintenance/shared-proof work
   through `e39784a59cfc585cfea972250dc72954e0adf134`, including its tightened
   deadline handling and fixture migrations; 221 affected regressions pass.
   Reconcile only subsequent **committed** ongoing Pump and maintenance/proof
   work. This branch does not change Pump production files.
   Preserve the Pump work at `engineering/pumpswap-provider-bandwidth-20261008`
   (`874e94a9` at inspection) and the maintenance worktree's outstanding edits.
   Use their final published identities, resolve only actual overlapping scope,
   and run only affected offline integration regressions on additional changes.
   Do not reset/rebase shared worktrees or replace the new Pons tree with Pump's
   older branch contents.
2. Complete the read-only administrative comparison when the restored Alchemy
   connection is callable in the execution session. The owner already verified
   PAYG and supplied both correct app IDs. Compare protected app key metadata
   locally against `/etc/meme-machine/paper.env`; retain booleans/fingerprints
   only. Retrieve actual numeric Pons/Pump method and request-type series with
   the same bounded time window, then replace projection assumptions. Confirm
   the exact account tariff and window; rounded $0.91 / 1.73M is consistent
   with $0.525/M but is not an invoice. Never rotate credentials to repair a
   stale connector binding.
3. After **separate explicit owner authorization**, run the prepared original
   300-second Robinhood proof below from clean exact reviewed source. Its
   limits remain unchanged, including ten-block logs. It checks forward shared
   scout/native candidate paths and public versus canonical market/pool
   witnesses in new isolated state. A natural quiet sample can yield
   INSUFFICIENT_SAMPLE. It does not clear the combined latency guard.
4. Use the ongoing shared Pump/Pons provider-proof effort for the remaining
   qualifying combined latency/capacity evidence, rather than adding another
   orchestration system here. It must use complete authentic candidate history
   and genuine funded PAPER controller samples in admitted isolated copies,
   preserve original deadlines/priority and account-wide Pump/Pons consumption,
   and certify position maintenance/exits under simultaneous Current and
   Survivor demand. If those authentic samples are absent, collect them in an
   explicitly authorized bounded operation; label the deficiency and keep the
   guard. Synthetic positions cannot clear it. Any CAPACITY run, guard removal
   review, proof-limit change or production workload requires its own explicit
   owner authorization.
5. With qualifying evidence and a safe reconciled release, obtain deployment
   and autonomous PAPER authorization. Preserve the existing PAPER state,
   volume, portfolio, inception and epoch. Start forward at the current chain
   head; independent Survivor age/qualification still follows its original
   four-hour through seven-day interval. Monitor actual app consumption,
   deadline waits, position latency, CPU/RSS, WAL/disk and durable gaps. Replace
   provisional daily/monthly costs as observations accumulate. Thirty-day
   billing certification is not a startup gate; funded safety and complete
   candidate evidence are.

The optional forty-block comparison is an efficiency improvement, **not a
mandatory gate to forward PAPER startup at the ten-block fallback**. Do not
delay an otherwise qualifying operation to perfect an unproved subscription
architecture. No paid subscription is chosen in this release.

## Reproduce completed offline work

Use the pinned Python 3.12 environment with repository requirements installed.
The existing engineering interpreter at inspection was
`/root/Documents/Codex/2026-10-08/the-meme-machine-robinhood-scout-first/.venv/bin/python`.
No dependency installation or environment change was made to the deployed
service. Run from the repository:

```bash
python -m operational.tests FAST --verbose
python -m operational.tests OPERATIONAL --verbose
python -m operational.tests FAST --modules tests.test_robinhood_payg tests.test_robinhood_scout --verbose
python -m engineering.robinhood_payg.replay --output /tmp/pons-payg-efficiency.json
python -m engineering.robinhood_scout.decisions --output /tmp/pons-payg-decisions.json
python -m engineering.robinhood_payg.cost_model --output /tmp/pons-payg-cost.json
python -m engineering.robinhood_payg.proof
python -m engineering.robinhood_payg.capability
```

The two proof commands default to provider-free preflight. FAST/OPERATIONAL and
replays forbid external market HTTP/sockets and use admitted isolated Scratch.
The cost model uses the checked-in decision coefficients. Reproduction files
above must use fresh unique output paths if preserving prior evidence.

Protected administrative metadata can optionally be supplied as an owner-only
JSON object keyed by the two app IDs, with their administrative key field.
Never put that input in Git, a proof artifact, a command argument, or logs.
Reconciliation can be repeated read-only:

```bash
python -m engineering.robinhood_payg.identity \
  --env-file /etc/meme-machine/paper.env \
  --app-metadata /root/protected-alchemy-app-metadata.json \
  --output /root/pons-app-reconciliation.json
```

Whole-key agreement is stronger than masked suffix agreement. The latter is
explicitly labeled diagnostic. An app ID alone is not a credential identity.

## Original 300-second proof: prepared, not authorized or executed

The executor pins the byte-identical
`engineering/robinhood_scout/NEXT_VALIDATION.json` SHA256
`89d7cbca347bcd1aa0246e37b3d7d1709348e686ab3d8d2bba83ff5b3e2b4e7b`.
The plan is still marked authorization NOT_GRANTED / execution NOT_RUN.
It requires a clean exact commit, PAPER protected environment and a new root
disk output outside the canonical persistent volume. After explicit owner
authorization of this exact reviewed source, an operator can run:

```bash
python -m engineering.robinhood_payg.proof --execute \
  --source-commit FULL_REVIEWED_COMMIT_SHA \
  --env-file /etc/meme-machine/paper.env \
  --output /root/pons-robinhood-proof-UNIQUE_RUN_ID
```

No key is passed on the command line. No portfolio/book is constructed, no
production epoch is accessed, no service is restarted and no deploy occurs.
The parent independently samples process CPU/RSS and output/volume storage;
the child rejects unmetered network and production-state access. Limits are
reserved before provider dispatch and checked during response acquisition.
Provider errors and proof stops are terminal; there is no retry extension.

| Protection | Original unchanged limit |
| --- | --- |
| Elapsed wall time | 300 seconds |
| Physical HTTP | 900 total; 600 public; 300 Alchemy |
| Logical RPC | 2,400 total; 1,200 Alchemy |
| Per-log range | 10 blocks |
| Diagnostic Alchemy CU | 100,000 test stop only |
| HTTP response payload | 128 MiB; native 2MB per response retained |
| Decoded sequencer bytes | 64 MiB ceiling retained |
| Temporary artifacts | 512 MiB, with final-report reserve |
| Process-group RSS / CPU | 4 GiB / 1.8 core equivalents over rolling 30 seconds |
| Persistent volume available | At least 4 GiB |
| Provider admission | Existing 0.5-second interval; no capacity change |

This executor uses filtered HTTP acquisition and does **not** connect a Nitro
or paid-log WebSocket. Its sequencer/subscription byte measurements are zero,
explicitly marked not connected; the production Nitro clock remains unchanged.
Its result does not independently validate production feed reconnect behavior.
It reports native RPC cache/queue/latency telemetry and short market/pool
canonical witnesses. It never claims an entire mature opportunity universe
from a five-minute prospective sample. The outcome retains
`full_market_coverage_certified=false`, genuine funded samples zero and the
combined blocker. The separate ongoing combined proof is the place to add
genuine funded/candidate and production-feed observations under its reviewed
plan. This technical proof alone cannot authorize autonomous startup.

Each forward sample exports native governor arrival/service rates and oldest
waits, scout gap/cursor state, original deadline telemetry and immutable-cache
reuse. Parent samples distinguish SQLite database and WAL stock. Failure to
read required governor instrumentation stops the run. Exact attempted log
intervals are recorded without credential data. Final diagnostics also obey
the original artifact ceiling; an oversized report produces FAIL rather than
silently truncating evidence into a passing certificate.

Before and after an authorized proof, capture administrative CU by the same
app/network/method/request-type filters. Allow for meter lag and concurrent
Pump usage; record exact billing windows. Local HTTP counts, method estimates
and subscription byte estimates are distinct from provider-billed consumption.

## Optional wider-range comparison: separate revised review

`capability.py` prepares a **different** 45-second comparison. Its proposed
forty-block ceiling must be explicitly reviewed and authorized; it does not
modify or borrow authorization from the original ten-block proof. Proposed
ceilings are 32 physical Alchemy requests, zero public requests, 64 logical
elements, 6,400 diagnostic CU, 64 MiB HTTP payload and 128 MiB artifacts.
The original RSS, CPU, native per-response and minimum volume protections
remain. Preflight prints these proposed limits without issuing requests.

The reviewer must choose one exact complete strategy filter, an identified
nonempty historical forty-block interval and the correct administrative team
ID. Supported comparisons are the broad topic-complete dynamic-curve/factory
filter, exact-factory launch/graduation filter, or authenticated Manager with
exact Pons pool IDs and reviewed economic/activity topics. An incomplete
factory-only curve filter or a broad unrelated-pool Manager filter is refused.
After separate authorization:

```bash
python -m engineering.robinhood_payg.capability --execute \
  --source-commit FULL_REVIEWED_COMMIT_SHA \
  --env-file /etc/meme-machine/paper.env \
  --filter-file /root/reviewed-pons-log-filter.json \
  --first REVIEWED_FIRST_BLOCK --team-id VERIFIED_TEAM_ID \
  --output /root/pons-robinhood-range-proof-UNIQUE_RUN_ID
```

The comparison authenticates chain and contract identity, headers and receipt
membership, checks four ten-block pages against the exact wider array, and
rechecks interval boundaries for reorganization. Empty, saturated, reordered
conflicting, removed or incomplete evidence cannot publish a passing record.
It writes only isolated output. No runtime capability is automatically
activated. Installation of an approved record via protected
`MM_PONS_LOG_CAPABILITY_FILE` is a separately authorized deployment step.

Capability scope is exact credential domain, static filter, tested indexed
filter cardinality and at most forty blocks. Different credentials, more pool
IDs or unproved topic combinations fall back to ten. A proved forty-block
sample does not prove larger or denser intervals; density/saturation and
deterministic recovery remain active. A persisted rejection holds that domain
at ten until a genuinely new comparison is installed. Do not change the
governor because one wider request succeeds.
