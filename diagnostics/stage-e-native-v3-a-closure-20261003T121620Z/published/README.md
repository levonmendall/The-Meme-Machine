# Stage-E Native V3-A preflight closure — PAPER ONLY

STAGE_E_NATIVE_V3_A_PREFLIGHT: BLOCKED

The first exact unresolved blocker is `frozen_runtime_version`: the actual CPython reports **3.12.3**, while the frozen contract requires **3.12.14**. The executable resolves under a directory named `Python/3.12.14`, but its actual version is 3.12.3. The unchanged `binding.runtime_identity()` refused it. Websockets metadata reports 17.1; the full locked-file runtime check was not reached. No runtime change is authorized or performed.

Fresh records resolve the prior fwupd owner/provenance gap. PID 36400 belongs to packaged `fwupd.service`, activated through D-Bus and the refresh timer. Journal evidence records successful natural deactivation at 12:06:52 UTC. fwupd is absent from the fresh snapshots. Its installed executable matches package version 2.0.20-1ubuntu2~24.04.2 and the installed manifest. The installed idle timeout documentation and repeated approximately 300-second deactivation history are preserved. This gives no future-PID exemption and does not reconstruct historical CPU/I/O counters that were not retained.

The complete process inventories, owner/unit/cgroup/provenance/activity mappings, corrected cgroup raw evidence, fresh provider response, CPU/RAM observations and durable-mount capability proof are preserved. The allocation was signed with a newly established dedicated RSA-3072/OpenSSL-SHA256 key and verified independently by the controller and exact approved harness. The public key was separately published before signature acceptance. The private key was held only in the controller process and discarded when that process exited after one signature.

Signed allocation SHA-256: `18146a60f179e2025a2c3797ecfd4a23cb72bb374912f7a2bd67297eaf767e08`. Public-key SHA-256: `5504ae8cfe2f20fcb3245c327e76e6f376f5cd8da895c56ffab3b258ae0079a4`. Exact provider receipt SHA-256: `d38aeb771d2ccff5bdde27eaf0abd9f26a7eb678318eee95cd2eb0fad6655fdb`.

The native runtime failure occurred before complete storage-budget/reservation, tape physical/frame/prefix/decoded verification, runtime reservation, UNIX path bounds and declaration validation. Those checks remain **NOT REACHED**. No complete environment manifest, A campaign, execution declaration, ledger reservation or owner execution permit was created. A process-to-service mapping is not a substitute for the frozen signed PID/start-time/executable admission predicate.

Approved contract `5ed5aef4dfe1bb7823037fe1ce440c193411a194`; executable `f480c6b4f7a8442fd148c7ed61bcc4447edaefca`; tree `6805846ed6d5c2acb31d843d749b80b923df87a1`; S `7a516a6a92be9347661ac0e7f560971c171a0931`; T `9da7d1e1625ba04c1437c63606c90f5e293bdba7`; assembly `08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659`. Droplet 605465049 / gd-2vcpu-8gb, host `ubuntu-gd-2vcpu-8gb-nyc1`, boot `f0453f41-fe5e-4e10-bda7-657de65713d8`. PR #118 remains open, draft and unmerged. No harness, contract, candidate, runtime or host-resource configuration changed.

Every published file is listed with exact bytes and SHA-256 in `MANIFEST.json`. Original evidence remains on the executor and in bounded GitHub Actions artifacts. Only evidence and collection-source receipts are included in this publication tree.

Stage E remains RED. Stage F remains NOT STARTED. **A processes started: 0; A slots consumed: 0; source frames released: 0.** No quiescence was performed.

STOP FOR OWNER. A separate owner-authorized runtime correction and a completely fresh preflight are required before any A authorization can be considered.
