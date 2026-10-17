This module is a canary-only experiment for an unprivileged Linux namespace
boundary. It executes its own fixed disposable tests; it cannot launch an
arbitrary command, native trading runtime, provider transport or financial book.
No production call site imports it. AWS enforcement remains unverified.

`namespace_canary.canary(scope)` requires a current owned 0700 Scratch scope with
its RUNNING disposable marker and matching parent PID. It creates only fresh
rootfs/work directories and synthetic secret/Unix/loopback canaries below that
scope. No real provider or production secret/state path is opened. It uses a
fresh isolated Python subprocess, not preexec_fn or irreversible parent changes.
This launch shape is suitable for a future multithreaded parent: all unshare,
mount, credential, capability, cwd and descriptor operations happen in the fresh
bootstrap interpreter. The parent retains its original contexts and descriptors.
Both the fresh bootstrap and post-isolation interpreter use -S, suppressing all
site/.pth imports. No venv or site-packages enters the child.

The child sets NoNewPrivileges=1, enters its own user namespace with a single
mapping for its original UID/GID, then creates mount, PID, network and IPC
namespaces. UID0 inside that user namespace grants setup capability only within
the new namespaces, not host-root authority. Its mount propagation becomes
private. PID1 creates a small tmpfs root, binds only a copied fixed runtime and
copied exact canary source read-only, and binds the fresh private work directory
writable. No original runtime, source or system-library directory is bound.
/tmp and /dev/shm are private 16 MiB tmpfs mounts;
/proc is read-only and belongs to the new PID namespace. Minimal null/zero/urandom devices are
bound in. The rest of the host filesystem is absent.

The child pivots into this root, detaches the old root, closes every inherited
host descriptor except the two checked anonymous parent result/log pipes and
one checked unnamed parent socketpair, which passes a fixed challenge/response,
changes cwd into /work, locks securebits and empties effective/permitted/
inheritable/bounding/ambient capabilities. A further seccomp filter refuses
namespace reentry, mounts, ptrace/process-memory operations and newer unreviewed
syscalls. Ordinary namespace-free clone/fork remain permitted. clone3 returns
ENOSYS so libc uses its separately flag-filtered legacy clone path; EPERM would
prevent normal pthread/ProcessPool startup. This does not weaken namespace
restrictions. A sanitized environment and Python -I/-B prevent inherited provider,
GitHub/AWS variables, package injection and bytecode writes.

The fixed post-isolation canary checks host-secret read/write denial, detached
old root, read-only source, absent host parent proc/environment, denied ptrace,
host pathname and abstract Unix socket denial, unreachable host loopback listener,
no egress interfaces/routes, zero capabilities, NoNewPrivileges, denied namespace
reentry, and actual local Unix traffic. It exercises real SQLite synchronous FULL
with WAL and a real two-worker spawn ProcessPoolExecutor using private /dev/shm.
It also checks -S remains active, no site/.pth/site-packages exists, and every
Python search path uses the copied /runtime image.
The parent checks unchanged host canary bytes, namespace identities, cwd and
previously open descriptors. It enforces a 15-second child-probe wall limit
(maximum 20),
kills only its new process group on timeout, and returns BLOCKED without fallback.
Output is drained concurrently into bounded buffers and rejected before either
result/log buffer exceeds 16 KiB. Parent-death SIGKILL is armed before and after
namespace setup with a parent-identity recheck. A private pipe lifeline checks
the fork-to-PID1 parent-death race, where getppid reports PID0. PID1 lifetime
contains namespace descendants. Tmpfs
mounts disappear with the namespace. The parent never changes a host mount,
sysctl, permission, sudoers entry, root broker or service configuration.

Local CPython3.12.14 end-to-end proof passed all 23 checks. Seventeen focused offline
cases cover actual enforcement plus malformed specs/receipts, unsafe paths,
kernel refusal, namespace-lock BPF, source/runtime restrictions, output flooding,
parent-death races, copied runtime admission and outer timeout.
Actual capability cases explicitly skip a root test process or an interpreter
installation not owned by root, retaining BLOCKED as the reason. They never
skip an arbitrary runtime Refused result. Root/ownership refusal and resource
bounds still have deterministic regressions; bound tests inject controlled
ELF/source bytes so host installation ownership cannot mask the tested bound.
Kernel/LSM capability refusal is explicitly BLOCKED; a skipped capability case is
not an enforcement PASS. Unexpected setup bugs or invalid receipts fail the test.
Earlier disposable failure scopes are retained under /tmp/mm-engineering-*;
they contain no production or provider data.

Future AWS validation can add a fixed `namespace-validate` action to the existing
unprivileged public-observer workflow, using its exact source/requirements pin,
main-only runner, stopped/disabled PAPER checks and global concurrency group.
It would run only this canary under a 25-second outer timeout in a scrubbed
environment and retain small source/canary receipts. It needs no root action,
package installation, namespace sysctl change, new permission or live provider.
Actual installed PAPER service compatibility must then be independently verified
under its existing NoNewPrivileges, mount restrictions, identity and AppArmor/LSM
context; success under the public runner does not prove that service context.
The outer timeout covers image construction as well as the child probe. The
direct AWS gate must fail every BLOCKED result; it must not use unittest skips
as a successful capability receipt.

This is still not a production-equivalent native test. A complete implementation
needs exact-source native bootstrap with no allocation authority, the real parent-
owned provider controls/transport bridge and streaming backpressure/accounting,
anonymous IPC injection, bounded resource admission and native stop/restart proof.
`namespace_runtime.build` creates a bounded manifest from explicit known
CPython3.12.14 stdlib names, the installed interpreter, selected extension modules
and their bounded ELF64 PT_INTERP/DT_NEEDED dependency closure. It never executes
ldd/readelf and never recursively copies runtime directories. Root-owned regular
runtime files must be non-writable by group/other; symlink resolution must stay
within approved runtime/library roots. Stdlib and canary source links are refused.
Sockets/FIFOs/special files are refused before opening; O_NONBLOCK also closes a
special-file replacement race. Every copy has a size and SHA256 record verified
after creation. A maximum of512 files/128MiB and64MiB per source file applies.
The manifest hash/count/byte total appears in the parent receipt. The local
image contained153 files and approximately38MiB, mostly the installed interpreter.
No discovered Python file, site package, .pth, host configuration or pathname
Unix socket is copied. A missing/incompatible runtime fails BLOCKED; there is no
host-directory or site-processing fallback. This fixed allowlist is only for the
canary. A native launcher needs its own exact reviewed dependency manifest and
must keep credentials absent from every child-visible filesystem path as well
as its environment and anonymous IPC.
No copied financial epoch, historical completion, full-market speed, held-position
protection or one-hour acceptance is supplied by a successful canary.
