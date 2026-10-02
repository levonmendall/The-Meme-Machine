# Self-hosted observer targeting stop

OBSERVER_V2: IDENTITY_OR_WORKLOAD_MISMATCH

PAPER ONLY. Stopped before preparation and Trial 1. All six trial slots remain unused: zero started trials, zero started workload members, zero retries, and zero invalid pairs. Stage E remains RED; Stage F remains NOT STARTED. STOP FOR ASTRA.

The user identified GitHub runner `the meme machine` on DigitalOcean host `ubuntu-gd-2vcpu-8gb-nyc1`, droplet ID `605465049`. DigitalOcean's control-plane inventory contains one active Ubuntu 24.04 x64 droplet matching the supplied 2-vCPU, 8-GB RAM, 50-GB local-disk description, with volume `580be5d5-be20-11f1-bb2f-3ee8be45f379` attached. That inventory does not verify a GitHub job's actual host, the volume's mount path or free space, or the runner service.

The user confirmed the current registered labels are `self-hosted`, `Linux`, and `X64`, and that Astra's required label `meme-machine-stage-e-observer` has **not been added**. The user subsequently asked to leave the runner as supplied and said they would update Astra. The runner name and its routing labels are distinct settings. No revised Astra targeting rule was supplied in this session.

The repository runner inventory endpoint returned HTTP 403, `Resource not accessible by integration`. Its response specifies the required permission `administration=read`. Consequently, runner registration and global unique eligibility could not be independently inspected or corrected with the connected credential. No Actions run was returned by the snapshot query for runs created since the droplet's provisioning time, 2026-10-02T05:10:13Z. No workflow was dispatched in this attempt.

The mandatory identity gate prevents preparation or execution with these targeting facts. This result records the missing required identity binding; it does not claim that the provisioned droplet is the wrong machine or that the approved workload semantics changed.

Candidate S `7a516a6a92be9347661ac0e7f560971c171a0931` still points to T `9da7d1e1625ba04c1437c63606c90f5e293bdba7`, confirmed by GitHub's immutable commit API and local Git. The reviewed assembly remains `08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659`. The durable predecessor is `d8d242a1c125cbdf9c774011039c4c1215a1d116`; its historical records are preserved. No local reviewed assembly was reconstructed, imported, or executed in this attempt.

No external observer infrastructure, full tape, equivalence proof, clock audit, differential proof, or executable predeclaration was produced. There are no measured durations, raw pairs, or ratio. Native `observer.verify()` was not invoked without a formal measurement. No acceptance credit is earned. Unit and workload resource checks were not run because this is a documentary stop before the required on-host identity inspection.

Only new documentary files in `diagnostics/stage-e-observer-v2-self-hosted/` are published. No workflow, candidate, historical evidence, runner settings, runtime database, or credentials are changed or included. Prepared qualification, canonical Stage E, and Stage F did not execute.

For any future continuation, the required observer label must be installed and unique, or Astra must explicitly revise that targeting requirement. The actual self-hosted job must then prove its runner identity, droplet ID, hostname, environment, and mounted-volume capacity before proceeding through the approved preparation sequence and a new executable predeclaration readback.
