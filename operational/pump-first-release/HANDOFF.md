# Final PR #130 handoff and Pump-first preparation

PR #130 closes the Alchemy optimization work. This release adds only the two
confirmed blockers below and an inactive, bounded read-only component check.
The final source is the immutable `release/pump-first-paper-20261011` tag, created
after exact-source CI passes. Its commit/tree and completed CI receipts belong in
the accompanying release attestation; this document does not claim pending CI
has passed. Nothing here deploys, funds or starts PAPER.

## Implemented blockers

The FAST failures at published PR #129 source `030705397cf75766b5bffbea41abb8bf8db12104`
were `cgroup_enforcement_unavailable` and `dedicated_two_vcpu_host_required`.
The hosted runner lacked the real containment test's required permissions and
CPU affinity. `.github/workflows/ci.yml` now enables the required CPU/memory/I/O
controllers on the disposable runner and runs the unchanged, network-guarded
FAST suite with exactly two CPUs. No assertion, kernel limit or deadline was
weakened. Previous failed logs remain in `evidence/`.

The existing bootstrap required Pons native readiness, Robinhood health and Pons
canonical progress even when only a Pump first position should receive funding.
The previously prepared, unintegrated `first-owner-scope.patch` was reconciled
against PR #130 and integrated at `c774fca89bd6956ab9446309c612a1699b5a7124`.
An optional `bootstrap_funding_scope` in the existing resource envelope now
selects eligible funding regimes. It preserves shared reconciliation, actual
resource limits, current Pump/PumpSwap coverage, native recovery/exit wiring and
60 seconds of frontier progress. It refuses other regimes before funding-only
USD work. All candidate discovery remains available. Protection of any existing
owner or obligation remains independent of that funding selection.

Basis, eligible additions and fees have separate cumulative ceilings for a
selected scope. Restart, cancellation or exit cannot replenish the claim. An
absent scope retains the original two-family readiness and $25 gross bootstrap.
The new scope is not configured on the host. Its maximum supported amounts are
validation bounds, not authorization to use $50, $25 or a $1,000 epoch.

Focused offline evidence: 81 existing/scope tests passed, followed by all 13 final
scope cases; 93 component/scope/native Pump/bootstrap/continuation/acquisition
tests passed. The final account-bound cases were checked separately. Exact logs,
test-file hashes and failed attempts are in `VALIDATION.json`. GitHub FAST and
the existing Pump proof must pass on the final candidate before integration.

## Smallest next authenticated component

`python -m engineering.pump_first.check` is inert by default. With separate owner
authorization it can inspect one locally retained PumpSwap mint using the existing
Alchemy Solana application `9bin99s96t7ga5e9`, native adapter, native USD reader and
original decoders. It runs one cold and one warm quote sample five seconds apart.
Each sample produces fresh quantity-specific buy/full-sell/partial-sell arithmetic
for an isolated $6.25 diagnostic budget. There is no position or simulated fill,
and those numbers never enter monetary journals.

Expected upper source shape is **7 physical starts / 7 elements / 130 modeled CU**:
one `getGenesisHash`, four `getMultipleAccounts`, two `getBlockTime`. This includes
one authentic SOL/USD account acquisition. The warm sample reuses only validated
vault addresses; pool, mint, vault balances, fees and completed curve/creator are
fresh. The account and quote decoding remains native. Non-swap reserve change,
stale oracle, timeout/error, response identity, purchase limits and the original
five-second acquisition deadline have focused offline checks.

Hard envelope: **15 seconds, 8 starts/elements, 160 reserved upper CU, 2 physical
starts/s, one in flight, 2,000,000 bytes/response, 4 MiB consumed HTTP delivery,
zero retries, streams, subscriptions or orders; maximum marginal charge $0.01**.
Expected real bytes/latency are unmeasured. Public $0.525/M-CU arithmetic is
$0.00006825 for 130 CU and $0.000084 for 160 CU, not an authenticated charge.
The private account record must bound all request/failure/exceptional and any
fixed/start/byte charges within one cent, reserve shared account capacity, and
confirm the runtime credential's binding. Unknown charges refuse execution.

Stop on any deadline, budget, price, transport, response, native identity,
freshness or decoder failure. The hard timer and terminal exception prevent
native client retry wrappers from dispatching more work. No redirects are
allowed. Failed requests retain their reserved cost. The signal deadline bounds
waits as well as reads; the byte limit measures consumed application bytes,
not authenticated wire-byte billing. Receipts contain response hashes rather
than credentials, URLs or complete account payloads.

PASS means **native quote/USD component only**. It does not prove complete
opportunity coverage, demand history, creator surveillance, qualification,
combined provider tail latency, complete protective decisions or operational
PAPER. It cannot enable `MM_PUMP_HELD_RPC_MODE=optimized`. That runtime setting
remains baseline until its complete applicable protection proof passes.

The exact disabled plan and private record template are in
`PUMP_COMPONENT_DISABLED.json` and `ACCOUNT_RECORD.unverified.example.json`.
Owner-facing missing evidence is narrowly limited to this app's Billing plan and
effective method/failure charges, Limits headroom, and private credential-to-app
binding. The existing administration connector exposes usage, not those
entitlements. No support message, account change or provider request was sent.

After authorization and authenticated preflight, the prepared command is:

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/meme-machine/.venv/bin/python \
  -m engineering.pump_first.check --execute \
  --source-commit EXACT_FROZEN_RELEASE_SHA \
  --account-record PRIVATE_AUTHENTICATED_RECORD \
  --env-file /etc/meme-machine/paper.env \
  --mint ONE_LOCALLY_RETAINED_MINT \
  --expires-unix OWNER_APPROVED_EXPIRATION \
  --output NEW_PRIVATE_ENGINEERING_RECEIPT
```

Run from the clean frozen engineering checkout, not by starting the PAPER
service. `--execute` is an invocation option, not owner authorization. The private
record template is invalid and cannot be dispatched as supplied.

## Pump-first activation path and actual remaining gates

Read-only inspection found deployed checkout
`b577cc1c67f4d64f887b430f5e933f376b607dc2` clean, service inactive/disabled/PID zero,
and original $500 epoch `paper-1791089005190643467`. Its operating
`portfolio.sqlite` has no selected shared funding authority. No continuation
envelope or bootstrap drop-in is installed; current service CPU/memory limits
are unlimited. These are concrete cutover/resource prerequisites, not new
software projects. The existing prepared bootstrap unit supplies the reviewed
resource limits and native continuation path; installation requires separate
deployment/activation authorization.

1. Finish exact-source CI, integrate PR #130 by fast-forward into the existing
   integration branch and freeze one source tag. Preserve main and historical
   branches; the original integration checkout remains untouched.
2. Obtain the minimal private tariff/binding/headroom record and separately
   authorize only the component above. A component failure blocks funding.
3. Use its retained evidence to price the smallest complete Pump one-owner
   protection/coverage acceptance with the existing acquisition/scheduler and
   isolated monetary state. It must include authentic full history/qualification,
   original Current/Survivor protection, USD, partial/full execution, pending
   intent/recovery, shared provider queue and original deadlines. Its actual
   request/stream envelope remains unmeasured, so it is not authorized by the
   one-cent component and no invented budget is supplied here. Pons certification
   is not a prerequisite for Pump funding; competing discovery resource use
   still needs measurement. No forced candidate or test-clock sale is permitted.
4. Before PAPER, separately authorize the exact release deployment, preserved
   $500 shared-authority cutover, unused one-lifecycle bootstrap and adequate
   continuation/recovery resource envelope. Use the existing verified migration
   and backup machinery, retain the old sizing/risk policy, and prove native
   reconciliation and restore before funding. Do not initialize the proposed
   $1,000 epoch or select its unapproved risk policy.
5. A prospective selected funding scope can include `pump_current` and
   `pump_survivor`; the first naturally qualified lifecycle claims it. With the
   preserved $500 effective-family policy, the initial native target is about
   $6.25 and eligible half-basis add about $3.125 before exact conversion and
   execution constraints. Those are existing targets, not a new allocation.
   Exact fee and provider continuation/recovery ceilings must be separately
   evidenced/approved, not populated from an example. Funding closes at the
   original 1,200 seconds; closing funding never closes position protection.

Long-duration positions remain governed by native economics. Unlimited holding
does not imply infinite provider credit: reserve adequate sustained protection
and recovery capacity and resolve the existing non-replenishing allowance's
continuation/extension requirements before admission. No age-only sale, budget
reset, missed protective observation or synthetic proceeds can make readiness
pass. Independent monitor/observer acceptance and coherent recovery remain
required. Meteora and Ramses stay paused; unproven Pons funding stays closed.

The minimum next step is the bounded Pump component, not another provider plan,
Pons history project, new monitoring service or larger portfolio.
