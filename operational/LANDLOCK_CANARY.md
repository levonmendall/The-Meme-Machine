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

Controller SIGTERM/SIGINT enters cleanup instead of abandoning the separately
owned probe session. Cleanup kills that group even if its leader already exited;
WNOWAIT keeps the leader PID reserved until the group kill, then the controller
reaps the leader and fixture peer within one shared two-second fence. Previous
controller signal handlers are restored. All sockets and fixture pipe ends are
registered for cleanup before bind/listen/spawn, including partial setup errors.
The forked static fixture immediately arms SIGKILL parent-death and checks its
parent again: the filter allows only that exact PR_SET_PDEATHSIG operation with
unused arguments zero, alongside the existing read-only policy queries. It
cannot clear/change the fence or admit another prctl operation. Outer SIGKILL
remains the caller's last fence; this is owned-process cleanup, not a PID namespace.

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

## Bounded failure diagnostics

AWS run39068968599 on sourcec135677314cd73983c2977fe85d6417612841ca9
retained only `landlock_canary_probe_failed`, without child exit, ABI or parent
checks. That receipt does not identify the underlying failure or establish a
kernel limitation. The administrative driver's broad exception handler could
replace a failure before or after the probe; its independent stage diagnostics
must also be retained.

The application now covers pre-probe validation/setup and post-probe parent
checks with the same BLOCKED projection. `CODES`, `STAGES` and `ERROR_CLASSES`
are fixed exported allowlists. `failure_fields(error, stage)` returns only
`code`, an allowlisted `stage`, fixed built-in `error_class`, bounded integer
`error_number` when supplied by the actual exception, and a known
`failed_check` for a typed check failure. It never publishes exception text,
filenames, arbitrary class names or tracebacks. Child stages distinguish
identity, ABI, rule installation, independent Landlock checks, seccomp, IPC,
SQLite and descendant checks. Completed child Boolean checks remain available
on a failed receipt; absent checks remain absent.

The controller records the actual child exit through WNOWAIT before decoding
the bounded anonymous response. Thus an empty or malformed response retains its
real exit and decode stage without inventing an ABI or error from the child.
A parsed child receipt is retained before owned-process cleanup and parent
verification. If a later controller failure supersedes a child error, the
bounded `child_failure` object retains that first child's projected `code`,
`stage`, `error_class`, `error_number` and `failed_check`; its ABI, checks and exit
remain top-level. Administrative receipt sanitizers must mirror these fixed
fields, not copy raw JSON. None of these diagnostic fields admits a PASS.

Focused offline regressions inject namespace-read and cleanup failures, use a
real disposable subprocess and anonymous response without any policy syscall,
and verify exit retention, actual owned-peer reaping, partial-child evidence
and privacy projection. They do not diagnose run39068968599 retroactively or
prove actual AWS Landlock/native execution.

## Long pathname fixture correction

Corrected AWS run39070091108 on source0181b0d785f2868bc224b9c2accb7c2d631a3961
reported `controller_listeners`, `OSError`, no errno or child exit, with all four
parent checks true. Its retained Scratch prefix makes the `outside.sock` address
108 bytes. CPython rejects that address before bind(2), because Linux pathname
Unix sockets allow at most107 bytes plus the terminating NUL. The exact retained
address reproduces the same errno-less exception offline. A104-byte control
bind succeeds, and a176-byte independently owned fixture also reproduces it.
This identifies the corrected run's fixture-path defect; it does not recover
missing diagnostic details from the earlier generic run39068968599.

The controller now opens its already admitted private scope with
`O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW`, checks its owner/mode/inode, and binds
the same real `outside.sock` inode through `/proc/self/fd/N/outside.sock`.
The strict child specification includes only the parent-issued numeric scope
descriptor. Before policy installation the child verifies that
`/proc/PARENT/fd/N` resolves to that exact scope directory. That directory FD is
excluded from `pass_fds` and remains CLOEXEC; the controller owns it until after
the actual probe has been killed/reaped. The seccomp connect canary uses the
short `/proc/PARENT/fd/N/outside.sock` address, so Python reaches the syscall
whose exact EPERM is required. No proc filesystem permission is newly granted.

The child separately opens only its already allowed private work directory to
bind its original `bound.sock` and `listener.sock` fixtures and derive its
`denied.sock` address through a short self-FD alias. An ExitStack owns this
directory FD and every socket from creation, including partial bind/listen
failures. All fixtures remain pathname sockets in the original admitted scope;
there is no cwd change, global temporary-directory change, shared short-path
directory, symlink, abstract-socket substitution or broader filesystem rule.

The27 focused offline tests include the exact108-byte failure, real socket
bind/listen/connect under a much longer owned prefix, real controller/child IPC
with the directory FD absent from the child, unchanged cwd/TMPDIR/parent FDs,
and original failure/reaping/privacy/BPF regressions. No actual Landlock or
seccomp policy was installed by these tests. AWS enforcement remains unproved
until the corrected bounded workflow produces its own authentic receipt.

## Closed-stdio fixture ownership correction

AWS run39071600357 on sourcefc7dd4d447dd773b06184ec373c2c65c00cbd85d
observed actual Landlock ABI8. Its filesystem read/write, readonly-image,
proc-data, abstract-scope, signal-scope, inherited-FD and empty-capability checks
were true, and all four parent predicates were true. It remained BLOCKED with
child exit2 and `landlock_canary_spec` at `child_socket_fixtures`. Those genuine
partial checks remain evidence; they do not establish full canary/native parity.

The fixed child deliberately closes stdio. The next private directory open
therefore returns FD0, which the strict numeric short-path alias rejects. A real
offline subprocess reproduces this exact allocation and typed error using the
original `_fixed_fds`, without any kernel policy syscall. Earlier socket fixtures
kept ordinary stdio open and did not cover this condition.

The owned fixture-directory context now moves any handle below5 through
`F_DUPFD_CLOEXEC` with minimum5, then immediately closes its original low handle.
FD3/4 remain reserved for parent IPC/facts. Parent-issued descriptor validation,
directory inode validation and filesystem/seccomp rights remain unchanged. Both
original and duplicate handles are registered before another operation can fail;
duplication, validation and context failures close every owned handle.

All30 focused tests pass, including actual closed-stdio pathname bind/connect
and anonymous status delivery, reserved-channel preservation, low-FD duplication
failure, open failure and existing reaping/privacy/BPF regressions. These are
offline lifecycle/fixture proofs. The known local ENOSYS kernel limitation was
not retried; complete corrected AWS enforcement still requires its own receipt.
