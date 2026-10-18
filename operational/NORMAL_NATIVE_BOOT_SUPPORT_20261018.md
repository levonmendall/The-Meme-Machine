# Private native boot support

This future, unselected component derives a private boundary inside the existing
sealed NORMAL pre-write reader, after original financial and all-four native
replay and retained-source/provider checks. The original ownership locks,
held database/support inodes, zero/absent WAL, full physical-generation check,
cancellation and original certificate deadline remain unchanged. It closes all
readers before ordinary constructors. No root wire field or approval changes.

`BootContext.boot_support()` returns a process-private
`NativeBootSupportBoundary`. Its immutable value binds the actual root instance,
record and certificate hashes, application commit/tree, unchanged epoch and
inception, authenticated native-input and physical-generation hashes, visibility
wall time, held source device/inode, and fixed source table/index SQL digest.
Three reverse seeks through the original `(scope,sequence)` index capture the
existing outbox upper cut for each configured program. They do not decode bodies,
scan/count the whole outbox, or produce a population digest. Genuine empty cuts
are `None`; missing source schema refuses the whole private boot publication.

`boundary.outbox_support('program:pump')` returns exactly:

```
schema, support_identity_sha256, association, visibility_wall,
database, upper_sequence
```

The schema is `normal-native-outbox-support-v1`; `database` has exactly
`relative_path`, `device`, `inode`, `schema_sha256`. The relative path is the
original `shared/solana-evidence.sqlite`. The schema digest is SHA256 of the
original sorted compact ASCII JSON of `[type,name,sql]` rows for
`candidate_outbox` and `candidate_outbox_scope`, ordered by name. It does not bind
unrelated future tables or SQLite's entire schema version.

Separate `retained_work` entries capture actual source history/proof, Pump
candidate work/checkpoint, both Survivor history and Pons Plane rowid heads plus
held database identities. These are descriptive metadata pointers in mutable
tables. They prove neither membership nor absence, and cannot classify changed
or reused rows as old/new or discharge queued work. In particular Pons watch
renewal and history/controller restoration still need their original native
generation and complete decision-critical population joins.

An inherited source consumer must authenticate the private owner/root association,
same source inode and fixed schema, and source-generation initial cut; then reach
the genuine fixed-cut key EOF, including future-available, dangling, missing and
deferred keys. Existing payload replay and original FULL retention/publication
and native outcomes remain separate requirements. The accepted premise is the
exact trusted native append-only outbox code under original sole-writer fences,
not database-enforced immutability or protection against arbitrary malicious raw
SQL. No later live MAX echo replaces this pre-write boundary.

The original root seal authenticates Supervisor/application/controller/epoch.
Derived cuts are authenticated by the actual application's held pre-write scope;
they are not additional independent root-sealed census fields. Complete inherited
membership, all-four downstream outcomes/protection, failed-generation recovery,
held-position continuation, readiness, funding and historical completion are not
established by this component. The old two unknown handlers and raw inputs remain
unchanged. No default/no-context launch performs these new metadata reads.

Eight focused producer/original issuance cases passed in 5.025 seconds using
the genuine disposable all-four financial/native replay fixture. They cover
fixed cuts including future/dangling keys, index use and no canonical payload
reads, missing schema, post-capture cancellation/concurrent mutation, immutable
owner scope and unchanged original final-source-check expiry/cancellation.
Root/systemd acquisition remains an explicit simulated premise. The first test
failure is preserved: the old fixture omitted original SelectiveHistory schema;
the fixture now installs that original schema before sealing its physical census.
There was no actual AWS/kernel/provider validation or sustained-capacity test.
