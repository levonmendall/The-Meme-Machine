# All-market certification state

Updated: 2026-09-23 UTC. Phase: candidate stabilized; exact-SHA full certification pending.

Runtime authority is `cert/prospective-market-v1`; its last inspected SHA was
`f7e053a7dc4c91c506aaf2116a33e3ce4fbd22fa`. Candidate branch:
`cert/all-market-certification-20260923`. The candidate SHA is the commit containing
this checkpoint and must be read from the `all-market-certification` run's `head_sha`.
No candidate certification or natural profitability claim is made here.

The workflow will certify that exact SHA, promote it only after every required gate
passes, then dispatch a 10-minute smoke and a fresh hourly paper block. Runtime code
stays frozen. Subsequent exact identities, run IDs, counts, metrics and next actions
are recorded on the separate state branch:

[`cert/cohort-state-95f602943ed4`](https://github.com/levonmendall/The-Meme-Machine/blob/cert/cohort-state-95f602943ed4/docs/ALL_MARKET_CERTIFICATION_STATE.md).

That branch's data commits are checkpoints, not runtime revisions. The JSON authority
is `certification/PROSPECTIVE_PROGRAM_STATE.json` on the same branch.

| Claim | Pump | Pons | Meteora | Ramses |
|---|---|---|---|---|
| Candidate machinery certified | pending | pending | pending | pending |
| Candidate natural lifecycle observed | false | false | false | false |
| Candidate economic acceptance established | false | false | false | false |
| Clean cohort blocks / natural settlements | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Observation hours, calendar span and active blocks are all zero for the new cohort.
Candidate market health and infrastructure censoring are unmeasured. Both stopped
predecessors' four native books reconcile with zero exposure; this is historical
reconciliation evidence, not a completed prospective block.

Cohort: `prospective-four-lane-v3-complete-sample-20260923`. Acceptance-policy SHA-256: `f452db20bc750b5cda37b90fb918a7b72f4fa686bcbf864ff8ef16020236b936`.
Strategy and source identities are frozen below; full execution provenance remains
in `certification/sources.json` and `certification/profitability_protocol.json`.

| Lane | Strategy | Policy SHA-256 | Exact overlay diff SHA-256 |
|---|---|---|---|
| pump | pump-acceleration-independent-v1/profitability-v1-profit-protection-v2 | `b7718de9298e4c825616bed26c87731a65f43c4b12f152b14e1d574eb86eb8d5` | `73382447eba168503b2c7dc909ecd3498cffabeaa116166c45a3af4c7b74836d` |
| meteora | solana-dlmm-independent-v2.0-profitability-fee-density-v1-core-hold-v2 | `90c711e5e3e521fb79f93bc386af5a3067d0a30c83ae3407c550f70db581f966` | `a00a177abf1431a274c11f6bac32df5ef17be2893ee9fe23077fa2c4a523237f` |
| pons | pons-selective-continuation-v1/profitability-v1-profit-protection-v2 | `19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84` | `f07dc564d97fa6d73deab049bc4aad5f23b1f29833448d28ee064d735c624363` |
| ramses | ramses-active-wide-maker-v3 | `bf75a70fcdf68cf231dd354eab7cb56879bc4c16184553db5c121ea0fdc5d4ef` | `bd6800b72c3333053daf5bce393487ceb4f3572d65aaee6853d67d42476bb685` |

Last completed action: supervisor/control regressions passed, including actual native
reserved-capital cancellation replay for all four lanes; fresh preparation reproduced
all four exact source hashes. Ramses census, exact 8-pool state-budget and Meteora missing-context regressions
passed. Workflow YAML and frozen protocol checks pass. Full lane, crash, restart,
integrated acceptance, resource, historical resolution, chain-binding and production
adapter gates remain mandatory on the committed candidate.

Engineering blockers: no known remaining defect in the repaired paths; full hosted
certification and smoke are pending. Any failure halts fresh admission and cohort
counting and requires diagnosis, repair and exact-SHA recertification.

Next action: commit the stabilized candidate with `[all-market-cert] [non-market-cert]`;
GitHub Actions owns certification and subsequent bounded observation. The program
retains every accepted block, including zero-trade and losing blocks, and waits for
all durable positions to become terminal before another fresh campaign. An ambiguous
dispatch remains `DISPATCH_PENDING`; it is never blindly retried.

Collection is bounded to 192 blocks or 336 calendar hours, whichever occurs first
at a reconciled block boundary. These operational limits do not change the frozen
minimums: 24 blocks, 24 observation hours, 168 calendar hours, 20 natural settlements
and 8 active blocks per lane, at most 10% infrastructure censoring, and the existing
lane/portfolio return, profit-factor, drawdown and correlation criteria. Insufficient
samples remain incomplete. Production autonomy and live money are not authorized.

Historical references: cancelled market run `35905479952`; prior non-market pass
`35907893183` at `ede31189574ac38df280f2cc0018798623b72e22` (not the new candidate);
read-only provider shape probe `35909625490` at
`e7ce21265884746c921220343caafb6ca10d8c1e`. See
[incident and repair evidence](ALL_MARKET_INCIDENT_35905479952.md).

The predecessor `f7e053a7dc4c91c506aaf2116a33e3ce4fbd22fa` passed all full
non-market gates in run `35914189762` and launched paper run `35915320840`.
Its live smoke proved the repaired Ramses census completed all 18 pages and
Meteora reached authenticated evidence acquisition. A later Ramses hydration
failure exposed another impossible local budget: four full pool states require
1,632 calls before metadata, exceeding 1,400. Both observed scans were censored.
The successor allocates the exact bounded state workload separately (up to 3,265
planned reads / 17 sessions for eight pools), preserving endpoint, pacing, retries,
pool capacity and all 201 bins. At the last checkpoint all four books had zero
exposure and zero settlements; the predecessor remains excluded from this cohort.

The successor additionally requires the existing portfolio joint-sample minimum
before ending collection, and corrects shared-pressure CU attribution so public
RPC calls cannot appear as Alchemy usage. It must pass its own complete certificate.
Its workflow retires the owned predecessor after a verified flat smoke or after
an already-started campaign drains; native exposure is never cancelled away.
Every predecessor artifact and cohort record is retained separately.

Terminal follow-up: run `35915320840` finished with a failed smoke, zero natural
settlements and zero exposure. Its artifact `10776256813` was digest verified.
Meteora's independent audit had a policy-file working-directory defect; the corrected
reader replayed all four preserved books read-only and verified them flat. The
successor retirement gate repeats that native replay before full certification.
Run `35918440394` stopped safely at retirement, before any full certification or
new observation. See the incident report and retained terminal replay receipt.
