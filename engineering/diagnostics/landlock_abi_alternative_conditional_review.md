# Conditional Landlock ABI 3/4 containment review

Analysis only; no implementation, policy syscall, test or AWS request. Reviewed
native integration `312a381c74594b7d9b10464471c9151d17717a71`, ABI6 static canary
`0181b0d785f2868bc224b9c2accb7c2d631a3961`, and pinned CPython 3.12.14 executor
sources. AWS run `39068968599` retained a generic failure, not a usable ABI
discriminator. No AWS ABI below six is established by that receipt.

## Conclusion

ABI6 is not intrinsically required to isolate the healthy anonymous-IPC native
processing path. A separately named ABI3/4 filesystem plus stricter seccomp
profile could replace the two scopes by removing outgoing authority rather than
scoping it. It would not preserve the current crash-recovery contract unchanged.
The existing ABI6 canary and its independent pre-seccomp Landlock checks must
remain intact; its failure must never be relabeled success under another profile.

ABI6 supplies abstract-UNIX and signal scopes while permitting operations within
the restricted hierarchy. ABI3 supplies filesystem TRUNCATE in addition to ABI2
REFER. ABI4 TCP rights are unnecessary if all new network connection authority is
denied. A fixed older profile would select exactly supported filesystem rights
and an ABI-compatible ruleset layout; it cannot submit the ABI6 scope fields or
unrecognized filesystem rights and pretend enforcement succeeded. Missing
filesystem IOCTL_DEV mediation requires the existing total ioctl denial to
remain. No ABI1/2 alternative is proposed here.

## Capability closure required for an older profile

- Keep only the independently authenticated copied image readable/executable
  and fresh disposable work writable, with complete supported filesystem rights,
  no production/credential/native financial epoch copies and original descriptor,
  UID/capability, source and resource checks. Landlock metadata visibility limits
  stay explicit; this is no PID/mount/network/SHM namespace.
- Deny every new socket/connect/bind/listen/accept and ancillary descriptor path,
  including preexisting-descriptor tests, sendmsg/recvmsg and mmsg variants,
  pidfd_getfd, proc-FD access and io_uring bypasses. Restricted anonymous UNIX
  STREAM socketpairs remain necessary for asyncio wakeups and NativeCommandHub;
  the authenticated parent channel also remains connected. Ordinary bounded
  read/write, connected send/recv/shutdown and NULL-destination sendto do not
  create a new external destination.
- Deny all direct x86_64 signal senders: kill62, rt_sigqueueinfo129, tkill200,
  tgkill234, rt_tgsigqueueinfo297 and pidfd_send_signal424. Preserve signal
  handler/mask/return operations and kernel-generated PDEATHSIG. Denying only
  kill is not a complete signal boundary.
- Also reject unused fcntl F_SETOWN/F_SETOWN_EX/F_SETSIG and O_ASYNC ownership controls:
  an inherited connected descriptor can otherwise arrange kernel-directed SIGIO
  to an outside PID. Preserve SQLite's required lock operations with an explicit
  argument policy rather than blanket fcntl denial. The existing ioctl denial
  covers alternate async-ownership ioctls.
- Audit external-PID mutation separately from signal delivery: prlimit64,
  scheduler/affinity/priority and I/O-priority setters can affect another process
  with matching credentials. Neither ABI6 scope proves those operations safe.
  Permit only proven self-directed operations actually needed by the fixed
  runtime, or deny them; do not grant a generic host-PID control interface.
- Preserve reviewed syscall architecture, clone3 refusal, namespace/mount,
  process-memory/ptrace, capability and descriptor denials. Review clone parent /
  process-group/session escape flags explicitly. setsid/setpgid and an unowned
  reparenting route cannot be allowed under a process-group-only cleanup proof.

These are closure requirements for a future actual native profile, not a claim
that the static ABI6 canary proves all native containment. Do not install a
privileged helper or change AWS permissions to satisfy them.

## Native liveness is not a signal-denial side effect

Native code does not uniformly use kill(pid,0). `robinhood.plane.process_identity`
and `alive` use boot ID plus PID/start ticks from proc; Solana immutable lease
reclamation calls that original identity check. `alive` currently maps OSError
to false. Under filesystem confinement, denied proc access therefore cannot be
interpreted as genuine process death and used to reclaim an active lease.
Likewise, EPERM from a denied kill(pid,0) cannot mean ALIVE or DEAD by assumption.

A future contained liveness contract needs ALIVE/DEAD/UNKNOWN, original identity
and generation verification, and UNKNOWN refusal to reclaim/replace or admit
overlapping writers. Exact self/owned-worker facts may come from a separately
authenticated existing owner lifecycle; they cannot be fabricated from old
numeric PIDs or exposed through an unrestricted parent PID oracle. Independent
disposable state does not authorize a production lease rewrite. This problem
also exists for a native ABI6 filesystem profile; requiring ABI6 does not solve
denied proc facts.

## Executor and shutdown consequences

`IsolatedSpawnExecutor` already uses two anonymous one-way pipes per worker,
bounded immutable data frames and no per-task FD transfer. CPython's initial
spawn inherits its pipe descriptors; the data pickler rejects resource-sharer
capabilities. Healthy Future completion, queued cancellation, sentinel shutdown
and join require no outgoing signal. Asyncio and source-command socketpairs
are compatible with a connect/bind/ancillary-denying profile.

But `_break_pool` currently calls Process.terminate on peers. With all outgoing
signals denied, Futures can fail while a hung peer keeps its owner join blocked.
HistoryExecutor joins the old pool before replacement. The stricter profile
must explicitly choose whole-child fail-stop when old owners cannot join; it
cannot report transparent restart or start a replacement over the old pool.

Spawned workers and CPython's resource tracker do not currently arm PDEATHSIG.
The tracker ignores TERM/INT and depends on EOF from all inherited writer ends.
A main-child fatal exit does not alone prove descendants or blocked work exited.
Parent-owned whole-group cleanup, immediate death fencing/lifeline startup and
parent-death/leader-exited-first proofs are necessary.

The namespace launcher's current NativeChild polls/reaps the leader and skips
group signaling after it exits; private PID-namespace teardown supplies a
different boundary there. A Landlock-only handle must instead preserve a leased
unreaped group leader until whole-group kill, as the static canary's WNOWAIT
ownership pattern does. It cannot kill a reused numeric PID/group or depend on
signaling old unrelated owners. The external parent retains the original fatal
wall fence; restricted child code receives no new signaling authority.

Cooperative stop is distinct from fatal group kill. NativeChild.stop currently
sends group TERM, while executor workers install default TERM behavior. That can
kill accepted preparation/history work; a main-only signal test is not a group
drain proof. Use existing cooperative owner cancellation or independently leased
main-only TERM for graceful drain, reserving whole-group KILL for the original
fatal fence. Never mark unjoined workers as graceful success or extend deadlines.

## Conditional decision and proof matrix

First obtain the corrected canary's authentic ABI/errno/stage. If ABI6 is present,
an earlier generic error is not evidence for an older profile; correct its
actual cause. If ABI3/4 is observed, a separate alternative may be justified by
the authority actually needed, with its own explicit source approval and receipt
schema. Its abstract/socket/signal checks must describe seccomp denial rather
than falsely claiming the missing Landlock scopes ran before seccomp.

Before claiming native containment for that profile, prove:

| Proof | Required outcome |
| --- | --- |
| Actual copied runtime and 2+1 native workers after confinement | Real preparation/history, source FULL/consumer ACK, socketpair command hub and authenticated parent channel work without named SHM/resource-sharer |
| Complete external effects | All reviewed direct/indirect signaling, socket/ancillary, proc-FD/process-memory and external-PID mutation routes refuse; disposable outside peer/files remain unchanged |
| Native liveness and restart | Denied/unknown observations refuse reclamation; true owned death/identity changes are distinct; no replacement before old owners actually join |
| Accepted-work cancellation | Queued work cancels; admitted FULL/ACK/accounting stays owned; graceful owner stop joins every worker within original bounds |
| Broken/hung/partial startup | No favorable result or transparent retry; preserved partial evidence and original whole-child fatal stop |
| Parent/leader death | Startup death-fence race, main exits first, blocked worker and tracker all end under exact leased group ownership, without PID reuse |
| Fork/exec/escape | Restrictions persist; session/group/reparenting escape is refused; no unowned descendant remains |

No current kernel capability or native parity verdict is changed by this review.

## Native external-PID policy: both ABI tiers

The following is a proposed native policy, not an edit to the trusted static
canary. It applies to ABI6 as well as an optional ABI3/4 backend. The namespace
backend and its original behavior remain unchanged. x86_64 numbers below are
from the upstream v6.12 syscall table; alternate architectures, x32 and unknown
syscalls remain unreviewed and refused.

| Route | Native policy and reason |
| --- | --- |
| kill62, tkill200, tgkill234, rt_sigqueueinfo129, rt_tgsigqueueinfo297, pidfd_send_signal424 | ABI6 may retain required owned-worker signaling only with independently proven signal scope. Older profile denies all outgoing sends and reports whole-child fail-stop instead of transparent broken-pool repair. Neither profile may kill an unrelated old PID |
| fcntl72 async ownership | Deny unused F_SETOWN8, F_SETOWN_EX15, F_SETSIG10, F_NOTIFY1026 and lease/async controls; reject O_ASYNC in F_SETFL4. Only actual lock/descriptor/nonblocking operations are candidates for allowance; unknown commands default-deny |
| prlimit64(302) | If pinned libc needs it, permit target `pid==0` only; a nonzero outside PID may be affected under ordinary same-credential checks. Parent must have set original hard resource limits so pointer-based own-limit changes cannot raise them. No arbitrary target PID allowance |
| sched_setparam142, sched_setscheduler144, sched_setaffinity203, sched_setattr314 | Deny unless the exact pinned native runtime proves a necessary self-only operation. No need for these mutations is established. Even a self-affinity allowance must not bypass the original fixed affinity/resource profile |
| setpriority141 | Default deny. Any demonstrated self-only exception must require `which==PRIO_PROCESS` and `who==0`: a zero ID with PRIO_USER/PRIO_PGRP is not equivalent to self-only |
| ioprio_set251 | Default deny. Any demonstrated self exception must use `which==IOPRIO_WHO_PROCESS` and `who==0`; no UID/group mutation |
| migrate_pages256, move_pages279 | Deny unused target-process memory-placement operations, including query forms unless actually needed. Same-user/ptrace-style access and capability checks are separate from Landlock signal scope |
| process_madvise440 | Deny unused pidfd memory operations. Upstream v6.12 also requires CAP_SYS_NICE for a different mm, and existing capability/pidfd controls remain; do not claim it is an established outside-write exploit in the current empty-capability context |
| process_mrelease448, pidfd_open434/getfd438, ptrace101, process_vm_readv310/writev311, kcmp312 | Deny unused external-task handle, memory, FD and release operations. No supplied pidfd capability is inherited. Legacy clone PIDFD flags are reviewed explicitly, not inferred safe from blocking pidfd_open alone |
| setsid112, setpgid109, clone56 parent/session flags | Deny group/session escape and CLONE_PARENT reparenting; preserve the dedicated group ownership proof. Allow only pinned fork/thread/spawn flag combinations; reject unknown/namespace flags and preserve reviewed clone3 ENOSYS fallback |
| unshare272, setns308, mount/pivot/chroot/new-mount APIs | Keep namespace/mount escape denials. The absence of a new namespace in a Landlock profile does not authorize manipulating the host namespace |
| prctl157 | Restrict to reviewed self operations: NNP/death-fence queries and exact SIGKILL PDEATHSIG setup, plus only any additional pinned-runtime self operation independently shown necessary. No clearing the death fence, gaining subreaper/control authority, dumpability relaxation or namespace/capability changes |
| indirect signals/notification controls | Audit dnotify, POSIX notification, inherited async/OOB descriptor state and sender flags. Keep message/FD passing, pidfd and io_uring denials. Kernel-generated owned-child exit notification and PDEATHSIG are lifecycle effects, not a granted arbitrary signal-send API |

The ownership proof must survive the main child exiting first, group members
blocked in work or IPC, and parent/controller death. It cannot be replaced by a
nice-value assumption, a fabricated positive alive result or polling/reaping a
leader before the last group kill. The exact restrictions, unavailable features
and original shutdown limits must be part of the selected profile's receipt.

## SIGIO: verified upstream mediation, not an ABI6 gap claim

Upstream Linux v6.12 Landlock registers both `task_kill` and
`file_send_sigiotask` hooks in
[`security/landlock/task.c`](https://github.com/torvalds/linux/blob/v6.12/security/landlock/task.c#L252).
The latter checks `LANDLOCK_SCOPE_SIGNAL` using the file's saved fown domain and
the recipient's domain, returning EPERM outside the permitted hierarchy. The
saved domain is installed by `hook_file_set_fowner` in
[`security/landlock/fs.c`](https://github.com/torvalds/linux/blob/v6.12/security/landlock/fs.c#L1627).
[`fs/fcntl.c`](https://github.com/torvalds/linux/blob/v6.12/fs/fcntl.c#L128)
calls `security_file_set_fowner`; its SIGIO path calls
`security_file_send_sigiotask`. The LSM contract explicitly covers SIGIO/SIGURG in
[`security/security.c`](https://github.com/torvalds/linux/blob/v6.12/security/security.c#L3063).

Therefore six direct-sender seccomp denials alone are insufficient when replacing
ABI6 scope; this is not evidence that ABI6 forgot SIGIO. Inherited descriptor
ownership still matters: the hook uses the saved fown domain, not an assumed
current sender. The fixed fresh socket/pipe handoff must validate that it grants
no unrelated async-owner capability. A strict native profile can deny unused
ownership/O_ASYNC/OOB controls on both tiers and test actual outside-peer effects
instead of depending on an undocumented descriptor state.

These are source-level upstream facts, not proof of the actual AWS kernel's
version, backports or enforcement. The selected kernel/profile still needs the
independent disposable enforcement checks.

## Default-deny native profile versus extending the blacklist

The current canary executes fixed trusted code and truthfully reports
`actual_service_restrictions_verified=false` and `native_execution=false`. Its
incremental deny list is not a complete native permission proof. Continuing to
append one discovered external-PID syscall at a time leaves existing unused
syscalls implicitly allowed and makes closure depend on finding every route.

For future native containment, prefer an independently named, architecture-pinned
default-deny syscall profile with explicit allowed syscall/argument families.
Landlock remains the object/path/domain policy; seccomp cannot inspect paths,
pointed-to structures or prove dynamic PID ancestry. On ABI6 it is useful to
retain the kernel signal-domain boundary for required worker termination; on
older ABI use the explicit no-outgoing-signals lifecycle. No generic user-notify
broker, arbitrary PID service, runtime privilege path or automatic learning mode
is proposed.

Default deny has a real compatibility cost; a successful import alone is not its
proof. The exact copied libc/CPython/dependencies and full native lifetime must
demonstrate the following candidate families before allowance:

| Native need | Required bounded review |
| --- | --- |
| CPython/loader and immutable imports | Private image reads/mmap, TLS/arch_prctl, memory management, close/descriptor operations and actual dependency resolution; no original host runtime/cache/credential directory allowance |
| Threads and synchronization | Pinned clone/thread flags, futex/robust-list/set_tid_address/rseq and thread signal setup; no external PID setters. pthread cancellation or native-library signal sends must be measured and resolved honestly, especially under total outgoing-signal denial |
| Spawned 2+1 preparation/history workers | Exact exec/fork/pipe/dup/close/wait needs, private source imports, immediate death-fence/lifeline handling and resource tracker EOF; no named SemLocks or per-task SCM_RIGHTS dependency |
| Asyncio/grpc/protobuf imports and loop lifetime | epoll/poll, event/timer descriptors, restricted anonymous socketpairs, nonblocking F_SETFL without O_ASYNC and fixed inherited parent traffic. A dependency may probe an optional syscall; only reviewed explicit ENOSYS fallbacks are allowed, not automatic profile broadening |
| SQLite FULL/WAL and private archival I/O | Native private-path open/read/write/pread/pwrite/stat/fsync/fdatasync, rename/unlink/truncate under Landlock and exact fcntl lock commands. No need for global sync, external-process scheduling or generic ioctl is established |
| Cooperative and fatal shutdown | Original signals from the protected parent remain receivable; actual accepted commits/Futures, old worker joins, process-group cleanup and no leaked descriptors/tracker must be demonstrated, not inferred from the syscall list |

Use source analysis to explain each allowance and offline trace/negative kernel
tests to establish the complete exact workload. A trace is coverage evidence,
not permission to allow every observed syscall or remove a failing assertion.
Unknown calls fail closed with a typed receipt. A dependency failure requires a
bounded cause-based correction or an explicit unavailable-profile result; it
does not authorize weakening the object policy or original deadlines.

Relevant upstream reference points are the
[x86_64 syscall table](https://github.com/torvalds/linux/blob/v6.12/arch/x86/entry/syscalls/syscall_64.tbl),
[`kernel/sys.c` prlimit/priority checks](https://github.com/torvalds/linux/blob/v6.12/kernel/sys.c#L1693),
[`kernel/sched/syscalls.c`](https://github.com/torvalds/linux/blob/v6.12/kernel/sched/syscalls.c#L965),
[`mm/migrate.c`](https://github.com/torvalds/linux/blob/v6.12/mm/migrate.c#L2490),
[`mm/madvise.c` process_madvise](https://github.com/torvalds/linux/blob/v6.12/mm/madvise.c#L1480),
and [Landlock ABI compatibility documentation](https://github.com/torvalds/linux/blob/v6.12/Documentation/userspace-api/landlock.rst#L579).
Bounded source copies and SHA256 records are retained locally under
`/workspace/recovery-evidence/landlock-source-v6.12`; none is an AWS execution
receipt or a running-kernel identity proof.
