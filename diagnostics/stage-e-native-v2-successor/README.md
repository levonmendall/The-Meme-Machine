# Durable Stage E integration recovery

NON-CERTIFIED WIP. Paper only. Stage E remains RED; Stage F NOT STARTED.
No material pressure or observer benchmark is authorized by this recovery.

Recovery starts only at GitHub commit
`4d386498b3dc848e1ba27d11dd8d61841ba426d1`, tree
`84903f733e634fa8dd440266c6112209edf24604`. The lost session's
unpublished bytes and test outcomes are unavailable and are not claimed.
`component-map.json` pins the durable component commits, trees, blobs and hashes.
Historical approval/report limitations remain historical; the current recovery
instruction authorizes reconstruction and these integration-branch checkpoints.

The housekeeping helper and native three-table batch come from the exact durable
treatment patch. Its selector is ported onto M1 without changing completion or
cooperative-interruption accounting. Ordinary retirement still calls `retention()`
with no arguments. Only an eligible housekeeping prefix passes
`housekeeping_first=True`, including forwarding to the writer. No arbiter,
admission, deadline, lease, scope rotation or service-credit rule is changed.
The imported housekeeping regression checks the fresh ordinary call with no kwargs.

`deterministic-allowlist.json` is a new explicit 621-test declaration, derived
from durable source. It is not a claim to recover the old local allowlist.
It contains 528 bounded production regressions, 21 housekeeping tests, the
unchanged original 71 Q2 test identities, and one M1 native prerequisite.
Nine root tests using sustained/scaled pressure are explicitly deferred.
Unknown tests are not run; required skips fail the declared denominator.
Q2's 71-test denominator is reported independently.

Checkpoint 1 preserves the map, port, imported Q2 source and allowlist before
long tests. Its Q2 input manifest still describes the standalone Q2 component;
fresh integrated binding and worker/crash execution controls remain unfinished.
Checkpoint 2 must preserve the complete combined source assembly before validation.
Neither WIP checkpoint earns certification credit. Exact checkpoint SHA/tree and
changed files are recorded after publication, without circular self-identities.
