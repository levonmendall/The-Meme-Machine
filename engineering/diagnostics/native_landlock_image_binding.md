# Native copied-image inode binding

This implements the first file-policy predicate for an explicit future native
Landlock backend. It does not install a policy, start a process or select a
fallback from the existing namespace launcher. Actual AWS ABI8 is known from
the independently retained static canary; native seccomp, copied-Python spawn,
provider acquisition, liveness and process cleanup remain separate proofs.

## Existing contracts and fixed interface

`meme_machine.operational.isolated_native_landlock_image.PinnedNativeImage`
accepts the existing `NativeImageApproval`, existing copied-image root and
`manifest_sha256`, a fixed protected-parent `authenticate_manifest` function,
and explicit profile `copied-cpython312-x86_64-v1`. It uses the existing
`isolated-native-copied-image-v1` manifest unchanged. There is no parallel image
manifest or child-controlled command/module/library selector.

The protected parent must authenticate the manifest against its original
approved build result. A checksum computed from the candidate itself is not
authentication. Source commit/tree and requirements must match the immutable
existing source approval; every copied application and dependency file must
match that approval's exact independent file map. Root-owned runtime bytes still
derive from the original trusted builder. The binding does not infer their
provenance merely because the manifest hashes agree.

Construction opens each copied regular file once for bounded hashing while
retaining a separate `O_PATH|O_CLOEXEC|O_NOFOLLOW` inode handle. The existing
2048-file, 64MiB single-file, 256MiB total and 512KiB manifest bounds remain;
directory enumeration is bounded4096 entries. Symlinks, hardlinks, special or
unlisted files, wrong modes/owners, financial ancestors and extra unapproved
application/dependency payloads fail closed. File and directory identities
include device, inode, mode, owner/group, link count, size and modification/change
times. A fresh binding check detects replacement or altered/inheritable handles
without rehashing the entire image.

`binding.rules()` revalidates the binding and returns immutable `ImagePathRule`
objects with borrowed `descriptor`, `access`, `kind` and `name`. This is the
concrete interface for the future reviewed Landlock path-rule consumer: pass
each actual descriptor and its exact rights to the kernel rule structure while
the binding remains alive, immediately after revalidation. Never serialize a
descriptor number or use a saved rule after closing the binding.

Copied directories receive READ_DIR only, which Python FileFinder needs for
module discovery. Each authenticated file receives its own READ_FILE rule.
Only the copied interpreter and loader receive EXECUTE. No directory receives
READ_FILE or any write/create/remove authority. All handles close explicitly or
on partial construction failure; CLOEXEC prevents their survival into the final
interpreter exec. The future launcher must apply policy before that exec.

## One host ELF interpreter, no host runtime directory

Both initial copied CPython exec and its actual stdlib spawn/resource-tracker
exec reopen the ELF PT_INTERP path. Launching only the copied dynamic loader does
not remove that subsequent requirement. This component pins exactly
`/lib64/ld-linux-x86-64.so.2`, following only the fixed root-owned trusted loader
aliases to a root-owned, non-writable canonical regular inode. Its exact bytes
must equal the authenticated image's copied loader. No caller may choose another
host path, and no host directory is granted.

The host rule is READ_FILE|EXECUTE on that one inode. A subsequent fixed-loader
alias change invalidates the predicate; replacement after rule installation
would not grant the new inode access. Every copied ELF must use that same
interpreter or no interpreter, and all DT_NEEDED names must resolve to copied
`runtime/lib` entries. The existing bounded ELF parser is reused without ldd,
readelf or dynamic loader execution. RPATH or fallback host cache/library reads
are not authorized by these rules.

## Evidence and remaining integration

Focused offline tests consume the actual descriptors through the existing
Landlock path-rule structure without calling any policy syscall. They cover
source/profile/authentication mismatch, exact read-only rule sets, a changed
loader alias, ELF closure, copied symlink/hardlink/special/unlisted files,
replacement/mode/inheritance changes, resource bounds and partial pin/read/open/
host/close failures. One test uses the actual existing approved builder and
copied runtime/dependencies once on the frozen source, then closes all rule
handles. The tiny synthetic ELF fixtures are parser fixtures, never executed
or represented as real CPython.

This supplies a usable inode/rule predicate, not a runnable native backend.
Remaining work includes the explicit private layout and exact entry identity,
complete default-deny native syscall profile, original descriptor/UID/capability
checks, real 2+1 workers/resource-tracker death fencing, genuine proc clock and
ALIVE/DEAD/UNKNOWN lease observations, accepted-work cancellation and original
owned-process fatal fence. The existing namespace backend is untouched. No
protected-parent sizing producer, workflow or provider grant is introduced.
Retained production candidate restoration remains a separate capability.

Focused command:
`python -m operational.tests FAST --modules tests.test_isolated_native_landlock_image`.
This is not a full release, kernel enforcement, live-market or readiness result.
