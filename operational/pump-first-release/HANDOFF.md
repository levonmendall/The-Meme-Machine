# Final PR #130 handoff and Pump-first preparation

PR #130 closes the Alchemy optimization work. This release adds only the two
confirmed blockers below and an inactive, bounded read-only component check.
The final source is the immutable `release/pump-first-paper-20261011` tag, created
after exact-source CI passes. Its commit/tree and completed CI receipts belong in
the accompanying release attestation; this document does not claim pending CI
has passed. Nothing here deploys, funds or starts PAPER. The intended launch is
the **separate new $1,000 shared PAPER epoch from PR #129**, with the proposed
realized-equity sizing/risk policy still requiring explicit owner approval.
The historical $500 epoch is preserved; its balance is not a funding source.

## Implemented blockers

The FAST failures at published PR #129 source `030705397cf75766b5bffbea41abb8bf8db12104`
were `cgroup_enforcement_unavailable` and `dedicated_two_vcpu_host_required`.
The hosted runner lacked the real containment test's required permissions and
CPU affinity. `.github/workflows/ci.yml` now enables the required CPU/memory/I/O
controllers on the disposable runner and runs the unchanged, network-guarded
FAST suite with exactly two CPUs. No assertion, kernel limit or deadline was
weakened. That repair passed the containment cases. The subsequent full run
exhausted sudo's 1,024 file descriptors in the unchanged multi-owner SQLite
fixtures. The CI parent now receives at least 4,096 descriptors; contained worker
limits remain unchanged. Previous failed logs remain in `evidence/`.

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
tests passed. The corrected $1,000 target, native $50/$25 quotes, local binding refusal and existing new-epoch/dashboard matrix passed 125 focused tests. Exact logs,
test-file hashes and failed attempts are in `VALIDATION.json`. GitHub FAST and
the existing Pump proof must pass on the final candidate before integration.

## Smallest next authenticated component

`python -m engineering.pump_first.check` is inert by default. With separate owner
authorization it can inspect one locally retained PumpSwap mint using the existing
Alchemy Solana application `9bin99s96t7ga5e9`, native adapter, native USD reader and
original decoders. It runs one cold and one warm quote sample five seconds apart.
Each sample produces fresh quantity-specific $50 initial and $25 addition buy
quotations and original-position full/partial sell arithmetic. These are isolated
diagnostic quantities for the intended new portfolio, not eligibility or funding.
There is no position or simulated fill; nothing enters monetary journals.

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
The owner separately authorized one read-only component run using the published
price as its **provisional modeled basis**, not a contractual guarantee. Current
[method costs and error pricing](https://www.alchemy.com/docs/reference/compute-unit-costs)
are 10/20/20 CU; applicable errors cost at most the method CU. The
[PAYG FAQ](https://www.alchemy.com/docs/reference/pay-as-you-go-pricing-faq)
states CU pricing without platform fees. Standard HTTP RPC invokes none of the
separately metered streaming or other products, and this bounded run does not
purchase capacity. The supplied dashboard shows 10,000 CU/s and a 431.7 CU/s
recent peak. No new plan or account setting is requested.

The private record must still bound every applicable charge within the modeled
cent, reserve shared headroom and confirm runtime binding. Read-only app
administration confirms the intended app/network; local comparison matches all
eight visible characters of its masked key to the configured runtime credential.
A retained credential fingerprint is checked again immediately before dispatch.
This is not an independent contractual-price attestation. Unknown applicable
charges or a binding mismatch refuse dispatch.

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
The account-specific contractual tariff remains unverified. The owner authorized
the public provisional basis only for this bounded component. Its result belongs
in the release attestation; this source handoff does not anticipate a PASS. No
support message, account change, subscription or PAPER action is authorized.

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
and historical $500 epoch `paper-1791089005190643467`. Its operating
`portfolio.sqlite` has no selected shared funding authority. This is historical
host baseline, not the new launch target or a migration instruction. No continuation
envelope or bootstrap drop-in is installed; current service CPU/memory limits
are unlimited. These are concrete cutover/resource prerequisites, not new
software projects. The existing prepared bootstrap unit supplies the reviewed
resource limits and native continuation path; installation requires separate
deployment/activation authorization.

1. Finish exact-source CI, integrate PR #130 by fast-forward into the existing
   integration branch and freeze one source tag. Preserve main and historical
   branches; the original integration checkout remains untouched.
2. Finish the local tariff/binding/headroom checks and dispatch only the separately
   authorized component above. A component failure blocks funding.
3. Use its retained evidence to price the smallest complete Pump one-owner
   protection/coverage acceptance with the existing acquisition/scheduler and
   isolated monetary state. It must include authentic full history/qualification,
   original Current/Survivor protection, USD, partial/full execution, pending
   intent/recovery, shared provider queue and original deadlines. Its actual
   request/stream envelope remains unmeasured, so it is not authorized by the
   one-cent component and no invented budget is supplied here. Pons certification
   is not a prerequisite for Pump funding; competing discovery resource use
   still needs measurement. No forced candidate or test-clock sale is permitted.
4. Before PAPER, obtain explicit approval of the existing proposed
   `risk-policy.shared-1000.proposed.json` (canonical hash
   `b91e83300994b6c02fe5e6bdbeb031cc391e6c8caa97af9fa6df1ecbc4aa979c`),
   separate new-epoch initialization, exact release deployment and PAPER
   activation. Use PR #129's existing `initialize_new_epoch` on the exclusively
   new `meme-machine-paper-shared-1000` root. Bind new storage/epoch/inception
   identities, verify coherent backup/restore and native/shared reconciliation,
   then select that authority through the existing cutover. Do not migrate the
   old balance, modify historical accounting or reuse its authority/guard.
5. The proposed shared realized-equity policy supplies $50 initial directional
   targets and eligible $25 additions at inception, a 7.5% cumulative asset
   investment reference and a separate 10% marked admission reference. Unrealized
   appreciation does not enlarge the sizing base; partial realization does not
   refill lifetime investment. All original eligibility, exact conversion,
   cash/fee/concentration, addition and protective rules still bind. A selected
   scope includes `pump_current` and `pump_survivor`; the first naturally qualified
   original lifecycle claims the one-owner allowance. Exact fees and sustained
   continuation/recovery ceilings require independent proof/approval, never
   values borrowed from an example. Funding closes at the original 1,200 seconds;
   closing funding never closes position protection.
6. Prepare an isolated new dashboard replica with the new epoch/inception and
   frozen source identities, authenticated ingestion and sequence checks. Before
   inception display **planned $1,000; inactive**. After authorized cutover show
   the genuine new inception and actual shared balances/positions. Preserve the
   separate historical $500 view; never repoint its replica or backdate capital.

`LAUNCH_1000_DISABLED.json`, the new storage template and
`deployment/paper-bootstrap.conf` concretely bind that intended isolated target.
Null fee/resource/epoch/replica fields are deliberate pending gates, not values
usable for activation. The templates have not been installed; no epoch, balance,
dashboard or service has been changed.

The bootstrap drop-in clears the base unit's `EnvironmentFile` list and selects
the separately prepared `/etc/meme-machine/paper.shared-1000.env`. This matters
because environment-file values override `Environment=` values: leaving the
historical `paper.env` selected could restore its old state root. A missing new
private file now refuses startup. Preserve that historical file; prepare new
credentials/configuration only during the separately authorized deployment.
The prepared ordinary PAPER unit keeps that same new private environment and
resource limits after bootstrap. Existing backup/backup-point and acceptance
units also select the new environment; acceptance has its own new private
acceptance configuration. The existing independent observer selects the new
state root. This avoids backing up, validating or observing the historical $500
epoch while the new one runs. No additional service is introduced. Install and
verify these existing units together only during authorized cutover; retain old
unit/configuration receipts and historic backups without reassigning their epoch.

Long-duration positions remain governed by native economics. Unlimited holding
does not imply infinite provider credit: reserve adequate sustained protection
and recovery capacity and resolve the existing non-replenishing allowance's
continuation/extension requirements before admission. No age-only sale, budget
reset, missed protective observation or synthetic proceeds can make readiness
pass. Independent monitor/observer acceptance and coherent recovery remain
required. Meteora and Ramses stay paused; unproven Pons funding stays closed.

The minimum next step is the bounded Pump component, followed by the separately
bounded complete Pump protection acceptance for the intended new shared epoch.
