STAGE_E_NATIVE_V3_CGROUP_DIAGNOSIS_COMPLETE

PAPER ONLY. Stage E RED. Stage F NOT STARTED. STOP FOR ASTRA/OWNER.

The missing CPU/cpuset interfaces are causally explained by the complete visible cgroup-v2 hierarchy. Linux supports both controllers and makes them available at the true root, but root `cgroup.subtree_control` contains only `memory pids`. Consequently neither CPU nor cpuset is distributed to `/system.slice`, and neither can be enabled farther down the runner chain. Memory is enabled through the chain; all three memory limits at every non-root ancestor are explicitly `max`. No actual cgroup CPU bandwidth cap, CPU subset restriction or memory limit below the allocated envelope is present in this observation. No absent resource file is converted to `max`.

The approved executable remains unchanged. Its current A preflight remains STAGE_E_NATIVE_V3_A_PREFLIGHT_BLOCKED until a separately authorized inspector correction is reviewed and a fresh admission is performed. No runtime/tape admission or capacity credit is earned by this diagnosis.

The exact executor is DigitalOcean droplet 605465049, hostname `ubuntu-gd-2vcpu-8gb-nyc1`, runner 21 `the meme machine`, boot `f0453f41-fe5e-4e10-bda7-657de65713d8`. Diagnostic PID 30497 belongs directly to `/system.slice/actions.runner.levonmendall-The-Meme-Machine.the_meme_machine.service`; there is no extra diagnostic cgroup beneath the service. It appears in both that cgroup's captured `cgroup.procs` and `cgroup.threads`.

The complete ancestor and controller table follows. N = `CONTROLLER_NOT_ENABLED_FOR_CHILD`; E = `CONTROLLER_ENABLED_WITH_EXPLICIT_UNRESTRICTIVE_LIMIT`; U = `CONTROLLER_UNAVAILABLE` for the specific root resource-limit interface only. No row is HIERARCHY_NOT_VISIBLE or UNRESOLVED and no explicit restrictive CPU/memory limit is found.

| Absolute cgroup path | Available for child distribution (`cgroup.controllers`) | Enabled for children (`cgroup.subtree_control`) | CPU | cpuset | Memory |
|---|---|---|---|---|---|
| `/` | `cpuset cpu io memory hugetlb pids rdma misc` | `memory pids` | N | N | U — root-limit interface exception |
| `/system.slice` | `memory pids` | `memory pids` | N | N | E — `max/max/max` |
| `/system.slice/actions.runner.levonmendall-The-Meme-Machine.the_meme_machine.service` — runner and diagnostic process | `memory pids` | empty | N | N | E — `max/max/max` |
| `/init.scope` — PID 1 visibility cross-check; outside the runner ancestry | `memory pids` | empty | N | N | E — `max/max/max` |

U on the root memory row does **not** mean memory is kernel-unsupported or unavailable for children: it is present in root `cgroup.controllers` and enabled in root `cgroup.subtree_control`. The classification applies to root memory.max/high/swap.max interfaces, which Linux 6.8 specifies only for non-root cgroups. Their absence is a documented root interface exception, not an inferred limit value. CPU/cpuset N at the root describes the outgoing edge; their non-root N states are causally inherited from that disabled parent edge. An empty service subtree_control does not disable its own incoming memory controller: system.slice enables memory for the service.

| Interface | `/` | `/system.slice` | Runner/diagnostic service | `/init.scope` |
|---|---|---|---|---|
| `cgroup.type` | ABSENT — non-root-only core interface | `domain` | `domain` | `domain` |
| `cgroup.procs` | PRESENT, 87 direct IDs | PRESENT, empty | PRESENT, 6 IDs including 30497 | PRESENT, `1` |
| `cgroup.threads` | PRESENT, 87 direct IDs | PRESENT, empty | PRESENT, 41 IDs including 30497 | PRESENT, `1` |
| `cpu.max` | ABSENT — non-root-only interface | ABSENT — CPU not distributed | ABSENT — CPU not distributed | ABSENT — CPU not distributed |
| `cpu.weight` | ABSENT — non-root-only interface | ABSENT — CPU not distributed | ABSENT — CPU not distributed | ABSENT — CPU not distributed |
| `cpuset.cpus` | ABSENT — non-root-only interface | ABSENT — cpuset not distributed | ABSENT — cpuset not distributed | ABSENT — cpuset not distributed |
| `cpuset.cpus.effective` | PRESENT, `0-1` | ABSENT — cpuset not distributed | ABSENT — cpuset not distributed | ABSENT — cpuset not distributed |
| `memory.max` | ABSENT — non-root-only interface | PRESENT, `max` | PRESENT, `max` | PRESENT, `max` |
| `memory.high` | ABSENT — non-root-only interface | PRESENT, `max` | PRESENT, `max` | PRESENT, `max` |
| `memory.swap.max` | ABSENT — non-root-only interface | PRESENT, `max` | PRESENT, `max` | PRESENT, `max` |

All requested file content and explicit absence states, including every raw process/thread ID, both hierarchy samples, cpuset memory-node interfaces and directory identities, are preserved in CGROUP_DIAGNOSIS_RAW.json. The parent-to-child available-controller sets equal the parent's subtree_control sets at every captured non-root node. Controller/interface observations were unchanged between the first and final samples. Every requested hierarchy file was either PRESENT or ABSENT; none was unreadable.

Kernel `6.8.0-142-generic` has CONFIG_CGROUPS=y, CONFIG_CGROUP_SCHED=y, CONFIG_FAIR_GROUP_SCHED=y, CONFIG_CFS_BANDWIDTH=y, CONFIG_CPUSETS=y and CONFIG_MEMCG=y. `/proc/cgroups` reports cpu/cpuset/memory each with hierarchy 0 and enabled 1. There is no cgroup-v1 controller mount or membership in the captured process view. These supported/available states are distinct from per-subtree enablement. Deprecated/absent config symbols were preserved as absent, not interpreted as unsupported; actual memory.swap.max and namespace interfaces are present where appropriate.

The Linux v6.8 documentation bytes are preserved with SHA-256 `717277564e1c365c38c080339efbbac1efa82585907c4d4e10fb940dc9c856d3`. It documents the top-down controller rule, non-root cpu.max/memory.max/memory.high/memory.swap.max/cpuset.cpus interfaces and the distinction between CPU accounting and CPU controller enablement. `CPUAccounting=yes` does not contradict the missing bandwidth interfaces: `cpu.stat` exists whether or not the CPU controller is enabled.

Namespace and mount visibility are established jointly. PID 1 is `/usr/lib/systemd/systemd` in `/init.scope`; the diagnostic process and PID 1 have identical cgroup, mount, PID and user namespaces. The cgroup identity is `cgroup:[4026531835]`; mount is `mnt:[4026531841]`; PID is `pid:[4026531836]`; user is `user:[4026531837]`. Their cgroup2 mount entries are identical: mount ID 34, parent ID 24, device `0:29`, root `/`, target `/sys/fs/cgroup`, root directory inode 1. Mount options are `rw,nosuid,nodev,noexec,relatime`, with super-options `rw,nsdelegate,memory_recursiveprot`. Both full mountinfo files were readable. The true root and every ancestor to the runner are visible; no ancestor is skipped. `nsdelegate` is a mount capability, not evidence that this observation is rooted in a delegated subtree. All relevant systemd units report Delegate=no.

The systemd settings were read with systemctl show only. The service's actual unit file was fully inspected read-only; it has no resource-limit directives and no drop-ins. Environment, credential and Exec directive values were excluded from preserved text; the exact full-file SHA-256 is retained. The root and system slices are manager-created units with no FragmentPath or DropInPaths.

| Property | `-.slice` | `system.slice` | Actual runner service |
|---|---|---|---|
| `ControlGroup` | `/` | `/system.slice` | `/system.slice/actions.runner.levonmendall-The-Meme-Machine.the_meme_machine.service` |
| `Slice` | empty | `-.slice` | `system.slice` |
| `CPUAccounting` | `yes` | `yes` | `yes` |
| `CPUQuota` property | ABSENT_PROPERTY | ABSENT_PROPERTY | ABSENT_PROPERTY |
| `CPUQuotaPerSecUSec` | `infinity` | `infinity` | `infinity` |
| `CPUQuotaPeriodUSec` | `infinity` | `infinity` | `infinity` |
| `AllowedCPUs` | empty | empty | empty |
| `AllowedMemoryNodes` | empty | empty | empty |
| `MemoryMax` | `infinity` | `infinity` | `infinity` |
| `MemoryHigh` | `infinity` | `infinity` | `infinity` |
| `MemorySwapMax` | `infinity` | `infinity` | `infinity` |
| `TasksMax` | `infinity` | `infinity` | `9484` |
| `Delegate` | `no` | `no` | `no` |
| `DisableControllers` | empty | empty | empty |
| `DropInPaths` | empty | empty | empty |

`CPUQuota` is a unit-file directive; this systemd version exports its resolved quota as CPUQuotaPerSecUSec. The requested property absence is preserved explicitly; the resolved property is infinity, and the inspected unit contains no CPUQuota directive. Empty AllowedCPUs/AllowedMemoryNodes are not by themselves used as proof: the hierarchy, effective root CPU set and actual affinity provide that proof. TasksMax=9484 is a real task-count cap; it is not a CPU quota or cpuset restriction.

Authenticated DigitalOcean readbacks before and after diagnosis preserve the same `gd-2vcpu-8gb` / General Purpose 2x SSD allocation: exactly 2 allocated vCPU and 8192 MiB = 8589934592 allocated RAM bytes. The unchanged official provider capability document binds General Purpose plans to dedicated vCPU. Guest metadata matches droplet ID/hostname, and the live boot ID equals the prior preflight boot. Visible possible/present/online CPUs and diagnostic affinity are exactly 0-1. Usable MemTotal is 8327667712 bytes; swap remains zero. The cloud allocation remains valid and is kept separate from the cgroup non-restriction proof. No separately signed allocation envelope/trusted signing key was present in the supplied prior preflight record, and no new signed envelope is created or claimed.

The exact current-inspector failure is its row-presence heuristic: cpu_rows=[], one root effective-cpuset row, two non-root memory rows, and unified_root=False because the process belongs to a service cgroup. Therefore `bool(cpu_rows and cpuset_rows and memory_rows) or unified_root` is false. The inspector collects neither cgroup.controllers nor cgroup.subtree_control and cannot causally justify this documented absent CPU interface state. This is a completeness false negative for the observed host, not evidence of an actual restrictive CPU quota.

The smallest proposed correction stays within harness/attest.py: collect controller availability/enablement and explicit file states; validate the fully visible root-to-leaf graph and documented root-only interface exceptions; require explicit valid limits whenever a controller arrives from the parent; accept missing non-root files only when the complete hierarchy proves that controller cannot apply there; and replace the global requirement for a quota row with complete causal coverage for each resource. Preserve every existing explicit restrictive-limit check, hidden-ancestor refusal, exact 2-vCPU/8-GiB authenticated allocation and all other safety/lifetime/resource rules. An enabled parent with a missing child limit, unreadable files, inconsistent controller sets or hidden ancestry must remain blocking. Empty leaf subtree_control cannot substitute for checking that leaf's incoming controller limits. Only static controller fields should enter the resource constraint identity; dynamic procs/threads membership must remain in the separate process evidence.

PROPOSED_INSPECTOR_CORRECTION.json records the proposal and required acceptance/rejection review cases. No correction or host setting was implemented. The read-only diagnostic step used one inline Python process and systemctl read commands, with no checkout, diagnostic file writes, resource setter, unit reload/restart or workload invocation. Returned bytes were preserved outside the executor. No A/B/C, source frame, tape read/replay or slot consumption occurred. Approved contract/executable and draft PR #118 remain unchanged; Stage E remains RED and Stage F NOT STARTED.

Collector commit: `14afe1eab90e5804b0cb52a49c9e59d98dc6e0b8`; workflow run 37094421860, attempt 1; job 111121313457, runner 21. Raw canonical payload: 58777 bytes, SHA-256 `1a9bf5779ba44d30c65f522d11fe5db3bd349e846276434e0cc095cb372149a8`. Its hash and byte count were recomputed after independent authenticated job-log retrieval. Raw cloud, prior preflight, controller and Linux-semantics bytes are included in this publication's exact-byte manifest.
