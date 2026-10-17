# Landlock capability and enforcement canary

`meme_machine.operational.landlock_canary.canary(admitted_scratch, seconds=15)`
is a fixed no-provider experiment for the existing nonroot public-observer
workflow. It never starts native market processing or changes host policy.
It does not replace the preserved namespace BLOCKED receipt `39064688867`.

The old `isolated-child-landlock` branch proves neither AWS Landlock capability
nor full isolation: its local ABI query returned ENOSYS38, and its write-only
primitive deliberately left reads/network/IPC unrestricted. No AWS Landlock
ABI result was retained. This canary answers that distinct missing question.

The only supported invocation is through a caller-owned admitted `Scratch`
scope, under the existing exact-source, service-stopped, nonroot-runner, global
concurrency and outer resource/wall fences. The fixed probe reexecs this module
with `-I -B -S` and an empty environment. There is no arbitrary command/module,
production path, credential, provider transport or privileged launcher input.
The module is x86_64 Linux only; unknown architecture or ABI below6 is BLOCKED.
An older ABI is a limitation of this selected canary, not proof that every
alternative architecture is impossible.

The child closes inherited descriptors, including stdio, retaining only a
validated preconnected unnamed STREAM channel on FD3 and anonymous read-only
fixture pipe on FD4. It arms parent-death termination, checks the parent again,
and reduces CPU/file/descriptor/core limits. Landlock handles all sixteen known
filesystem rights and both ABI6 scopes. A single exact-inode, single-link copied
regular file receives read/execute rights; a new owned0700 work directory
receives ordinary read/write/create/rename rights. No original runtime directory,
proc directory, production directory or host `/dev/shm` is allowed.

The copied executable is a source-defined129-byte static x86_64 ELF performing
only exit(0), without PT_INTERP. It demonstrates execute permission on an exact
allowlisted inode. It does **not** prove private copied CPython startup, its
prefix/shared-library/loader resolution, or Python spawn. A future native image
needs actual private host paths and either a verified copied-loader invocation
or an explicitly verified exact OS-loader file allowance, never broad host
runtime directory access.

Landlock filesystem read/write, proc-data, abstract-UNIX and outside-domain
signal denial are exercised **before** seccomp is installed. Only disposable
outside fixtures, sockets and a separate empty-environment signal/proc peer are
targets. Seccomp then denies socket creation, destination connects/binds/listens/
accepts, message/FD passing, metadata mutation, process-memory/FD interfaces,
shared IPC, namespace/mount changes, io_uring and unreviewed syscall ABIs. Each
connect/bind/listen/accept refusal uses a separately precreated child-local
descriptor, so socket() refusal cannot mask those checks. Anonymous STREAM
socketpairs allow reviewed CLOEXEC/NONBLOCK flags, and sendto permits only a
NULL destination. The tested normal fork inherits the boundary; clone3 returns
ENOSYS and namespace clone flags remain denied. An exact classic-BPF interpreter
test checks branch offsets and allowed/denied syscall argument populations.

The30 fixed checks also cover empty effective/permitted/ambient capabilities,
unchanged nonroot real/effective/saved identities, parent IPC, facts delivery, internal socketpair/
pipe, SQLite FULL/WAL, fork restriction inheritance and exact static-fixture exec.
Parent cwd/namespaces/open-descriptor identities and outside fixture bytes/mode
must remain unchanged. The output is bounded16KiB and a successful result needs
every fixed check, child exit0 and every parent predicate. Missing fields,
partial checks, extra child fields, integer-for-Boolean substitutions, nonzero
exit and unknown error text cannot produce a success. Failed receipts publish
only fixed codes/check names, numeric errno/ABI and explicit false authority.

This is **not** a mount/PID/network/IPC namespace. Landlock does not hide all
stat/access/chdir metadata, host paths or PIDs. The receipt explicitly reports
`host_metadata_hidden=false`, `private_shm=false`, `private_pid_namespace=false`
and `private_network_namespace=false`. No private POSIX semaphore namespace,
real spawn pool, complete native image, actual service restrictions, provider
parity, financial protection or full-market capacity is claimed. Public-runner
success would not prove the protected service's context; that later boundary
still needs its own authorized proof.

The actual native implementation currently requires pathname Unix source IPC
and named SemLocks in spawn pools. A child-local socketpair-per-command hook can
retain the existing owner command protocol without any parent FD broker or
SCM_RIGHTS. Both Queue and SimpleQueue use SemLocks. Each ProcessPool needs five
names, and a lazy historian restart needs five new clean names. Exact-parent
precreated banks require custom context adoption, no unrestricted resource
tracker, exact parent-only cleanup and fresh restart generations; they are not
standard-pool compatibility by default. A pipe-only bounded executor avoids that
host object lifecycle but needs actual Future/cancellation/broken-pool/drain
proofs. Neither alternative is implemented by this canary.

Admin integration should mirror `namespace-validate` in the existing
`isolated-public-observer.yml`: exact main-ancestor source approval/manifest,
existing stopped/runner/concurrency checks, `env -i` isolated interpreter,
existing25-second outer fence and15-second inner probe, strict fixed-check
receipt verification and BLOCKED exit2. No broker route, AWS permission,
sysctl/AppArmor change, credentials or provider workload is required. Root owns
that integration and any later dispatch; this component does not dispatch it.

Focused local validation uses only the offline contract/BPF/descriptor tests:
`python -m operational.tests FAST --modules tests.test_landlock_canary`.
It deliberately does not repeat the already established local ENOSYS kernel
probe. These tests do not claim that actual Landlock enforcement ran locally.
