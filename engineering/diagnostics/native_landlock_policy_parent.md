# Explicit native policy and owned supervisor

This is a separate, explicit Landlock launcher for the fixed copied native entry.
The existing namespace launcher and static canary are unchanged. It requires the
existing authenticated NativeImageApproval and original parent transport/facts;
it introduces no workflow, AWS permission, broker path or funding authority.
The copied layout/spawn-shim component is a separate required dependency.

## Policy

`native_landlock_policy.NativePolicy` requires unprivileged, capability-empty,
single-threaded Linux x86_64 setup, Landlock ABI6+, no-new-privileges, and the
reviewed PinnedNativeImage. It consumes the actual borrowed O_PATH image handles;
no caller-provided rule path or host directory read grant is accepted. The work
directory receives private filesystem rights without execute/device creation.
Two additional fixed file inodes permit the genuine installing main process's
own `/proc/self/stat` and the boot-ID file. Descendant self-stat inodes are not
granted; pure decoder/history workers do not gain a proc/PID oracle.

The syscall filter defaults to EPERM for unlisted calls. Non-x86_64 architectures
are killed; x32/new syscall numbers cannot fall through to allowance. Narrow
cases retain actual fork/thread shapes, anonymous AF_UNIX STREAM socketpairs,
NULL-destination send/recv, own-limit/affinity queries, native SQLite file locks,
nonblocking/CLOEXEC descriptor flags, and arming SIGKILL parent-death only.
Network/socket creation, connect/bind/listen/accept, message vectors/SCM_RIGHTS,
async fcntl/PID ownership, namespace/privilege changes, metadata setters,
scheduler/ioprio and unrelated process-limit setters, foreign-PID queries, process_vm/ptrace,
new kernel APIs and unreviewed flags remain denied. Positive-PID TERM/KILL is
also restricted by Landlock's signal scope. The static canary's deny-list filter
is not reused as the native filter.

The actual unchanged history initializer needs self AS/NOFILE reductions and
nice5. Those are narrow exceptions; no foreign PID, other resource, priority
class or nice value is admitted. Kernel nonroot hard-limit semantics remain
unchanged, including the main's original inherited AS limit; no speculative new
virtual-address ceiling is added. Existing outer process/cgroup limits still
contain the run. The explicit profile requires initial nice0; the history
initializer lowers its own hard AS/NOFILE limits to512MiB/128 and nice5.

Path rules install before syscall restrictions and the fixed private exec.
Descriptor cleanup attempts every owned temporary handle even on partial failure.
Image handles remain borrowed until the launcher closes them; all are CLOEXEC.

## Parent and process ownership

`isolated_native_landlock_launcher.launch_native` is main-thread only and
requires the caller's SIGCHLD default disposition. It builds the approved image
with the explicit native profile. A bounded anonymous setup pipe transfers the
parent's actual retained approval/build receipt to a fresh setup interpreter.
That descriptor's protected origin is the trust boundary; a self-computed image
checksum is not an authenticator. The setup repeats exact source validation,
normalizes FD3 transport/FD4 facts before pinning, and consumes the reviewed
five-field NativeChildLayout. No arbitrary target/module/env is accepted.

Only the fresh single-threaded session leader sets CHILD_SUBREAPER. The host
parent's policy does not change. Its native child arms parent-death and checks
the expected parent before policy/exec. The supervisor closes its transport,
facts and image descriptors, and waits/reaps its actual child and adopted
descendants. Kernel waitpid reaching ECHILD is required for a clean physical
join; no optional proc children file or child-selected numeric PID is trusted.
Timeout/unknown live descendants produce failure125. That forced containment
is never represented as successful graceful drainage.

Graceful TERM goes only to the retained supervisor, whose main-thread relay
checks WNOWAIT/ECHILD before forwarding TERM to its unreaped native child.
The source can then drain accepted decoder/history jobs using its original
shutdown protocol; an external group TERM must not kill those jobs prematurely.
Cancellation before fork is remembered; a signal after native reap cannot target
a reused PID. A forked child's inherited remembering handler is reset and its
remembered cancellation checked before native preparation. Hard KILL still
targets the whole original owned process group.
The outer parent holds its session-leader PID with WNOWAIT until group KILL,
then reaps it. Its original 65s stop and 1,865s wall bounds remain unchanged.
Output stays bounded at 64KiB per stream, including failures.
Concurrent waiters consult the first stop request's shared, nonextending deadline;
waiting for another waiter never starts a second grace interval. Supervisor125
always refuses graceful/all-worker claims, even if the native receipt was already
BLOCKED. Reader-construction failures close the setup stdin pipe and retain the
physical owner on the original exception when cleanup is incomplete.
Constructor cleanup also holds the same signal/reap ownership lock while
waiting and updating the reaped state; an actual started-reader WNOWAIT gate
proves cleanup cannot release the leader PID before its pending group signal.

## Current evidence and limitations

Eighteen focused cases pass at749ab1d0, including an actual seccomp-installed process using
threads, anonymous socketpair send/recv and SQLite FULL/WAL. Pure BPF tests
exercise argument halves and negative privilege/PID/async/destination/unknown
paths. Real disposable subprocess cases prove original tracker EOF followed by
subreaper ECHILD; cancellation-before-fork and safe refusal after reap; accepted
worker completion under the supervisor TERM relay; hard group KILL before leader
reap; rogue descendant failure versus containment; output overflow; and reader
thread-start failure cleanup, inherited stop delivery, concurrent stop/wait and
the unchanged history initializer's actual limits/nice under the filter, and
copied CPython's real2decoder+1HistoryExecutor+tracker under the inherited filter.
The latter preserves the actual short-lived submitter/retained spawning owner,
worker/tracker lifeline and PDEATHSIG, deny-only initializer and original limits;
all physical owners join, with zero provider calls and no financial authority.
An additional real started-reader failure regression retains its still-running
owner and output streams until that original reader actually joins. These
subprocess fixtures do not claim Landlock,
copied-image or full-native economic acceptance.

Command:
`python -m operational.tests FAST --modules tests.test_native_landlock_policy tests.test_native_landlock_launcher`

Receipts: `native-landlock-policy-parent-correction.log` (18PASS8.139s),
`native-landlock-coupled-adjacent.log` (28PASS11.515s; image/layout/spawn/fatal),
and `native-landlock-original-supervisor-focused.log` (2PASS.597s) in
`/workspace/recovery-evidence`. The final focused receipt includes the additional
started-reader regression and a bounded copied/syscall result projection.
An initial real-tracker case exposed absent Cloud `/proc/.../children`; that
dependency was removed in favor of kernel waitpid ownership. Its failure scratch
is retained at `/tmp/mm-engineering-iout9c0l`.
Three new history-filter fixture setup failures were corrected without weakening
the syscall policy: isolated `-S` lacked the real dependency path, Cloud's hard
NOFILE16384 forbade raising to65536, and Python translated a denied rlimit syscall
toValueError. The final negative test calls the actual syscall and checksEPERM.
Failed scratch roots remain `/tmp/mm-engineering-jqjzcc9d`,
`/tmp/mm-engineering-zb9hqi0i` and `/tmp/mm-engineering-0yexebz4`.

Independent code review found no material blocker in the frozen native policy;
five subsequent launcher findings have scoped correction regressions and await
independent recheck. Actual coupled copied-Python 2+1 worker/tracker execution still
need their separate integrated validation and review. Actual AWS ABI8 static
canary success is a separate receipt and does not prove this native route.
No full release, provider operation, deployment, retained restoration authority,
PAPER readiness or full-market-speed result is asserted here.
