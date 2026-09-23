# All-market certification state

Updated: 2026-09-23 UTC. Phase: candidate stabilized; exact-SHA full certification pending.

Runtime authority is `cert/prospective-market-v1`; its last inspected SHA was
`44869bbcb1ccb3bb6a9001443d36b77b3eafd14f`. Candidate branch:
`cert/all-market-certification-20260923`. The candidate SHA is the commit containing
this checkpoint and must be read from the `all-market-certification` run's `head_sha`.
No candidate certification or natural profitability claim is made here.

The workflow will certify that exact SHA, promote it only after every required gate
passes, then dispatch a 10-minute smoke and a fresh hourly paper block. Runtime code
stays frozen. Subsequent exact identities, run IDs, counts, metrics and next actions
are recorded on the separate state branch:

[`cert/cohort-state-513baef4b555`](https://github.com/levonmendall/The-Meme-Machine/blob/cert/cohort-state-513baef4b555/docs/ALL_MARKET_CERTIFICATION_STATE.md).

That branch's data commits are checkpoints, not runtime revisions. The JSON authority
is `certification/PROSPECTIVE_PROGRAM_STATE.json` on the same branch.

| Claim | Pump | Pons | Meteora | Ramses |
|---|---|---|---|---|
| Candidate machinery certified | pending | pending | pending | pending |
| Candidate natural lifecycle observed | false | false | false | false |
| Candidate economic acceptance established | false | false | false | false |
| Clean cohort blocks / natural settlements | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Observation hours, calendar span and active blocks are all zero for the new cohort.
Candidate market health and infrastructure censoring are unmeasured. The cancelled
predecessor's four native books reconcile with zero exposure; this is historical
reconciliation evidence, not a completed prospective block.

Cohort: `prospective-four-lane-v2-census-context-20260923`. Acceptance-policy SHA-256: `956c79606c95df9edf249f9f09ed209543a18a12a57bc67dd21a4c4a16b78304`.
Strategy and source identities are frozen below; full execution provenance remains
in `certification/sources.json` and `certification/profitability_protocol.json`.

| Lane | Strategy | Policy SHA-256 | Exact overlay diff SHA-256 |
|---|---|---|---|
| pump | pump-acceleration-independent-v1/profitability-v1-profit-protection-v2 | `b7718de9298e4c825616bed26c87731a65f43c4b12f152b14e1d574eb86eb8d5` | `73382447eba168503b2c7dc909ecd3498cffabeaa116166c45a3af4c7b74836d` |
| meteora | solana-dlmm-independent-v2.0-profitability-fee-density-v1-core-hold-v2 | `90c711e5e3e521fb79f93bc386af5a3067d0a30c83ae3407c550f70db581f966` | `a00a177abf1431a274c11f6bac32df5ef17be2893ee9fe23077fa2c4a523237f` |
| pons | pons-selective-continuation-v1/profitability-v1-profit-protection-v2 | `19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84` | `f07dc564d97fa6d73deab049bc4aad5f23b1f29833448d28ee064d735c624363` |
| ramses | ramses-active-wide-maker-v3 | `bf75a70fcdf68cf231dd354eab7cb56879bc4c16184553db5c121ea0fdc5d4ef` | `edad8c4d1fc03b3e90f1d11bda3fcdc5ef7a8a4ba297f3ec50959d3fc40fcf0b` |

Last completed action: 139 supervisor/control tests passed, including actual native
reserved-capital cancellation replay for all four lanes; fresh preparation reproduced
all four exact source hashes. Ramses census and Meteora missing-context regressions
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
