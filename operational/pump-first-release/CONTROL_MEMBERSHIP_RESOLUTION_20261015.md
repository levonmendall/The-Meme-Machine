# CONTROL membership retention contract

Exact combined executable `10ae127c399279847df908d555eceb1aaf46ef1d`; retention implementation
`27f9a19463aa51fdd0daffb084ed4b373642e311`, branch
repair/consolidated-startup-followup-20261014, draftPR133.

The actual disposable publication/retirement path reproduced a correctness defect:
CONTROL retirement deleted receipts101/102/103 while candidate blocks and pending
proofs remained. Actual valid publication fell2→0. This establishes a shared
retention/publication contract defect, not historical deletion attribution or the
cause of the upstream capacity deficit.

The correction preserves the unread CONTROL tail anchored by the two current
program children, or the exact startup feed while its current child is missing.
Older pending proofs preserve only their exact lower and actual predecessor upper
receipts. A zero-lower proof cannot pin every later CONTROL row. Original
scope/order/availability/hash/session/sealing and completeness checks remain.
All three continuity representations use the same predicate in prefix and interior
retirement, including below an already advanced monotone floor. Existing whole
coverage/gap witnesses remain indivisible. No deleted receipt is recreated and
no checkpoint or missing coverage is manufactured.

The selected implementation retains one authoritative writer. It adds a compatible
proof-end index and bounded existing-owner metadata work, not a second evidence
store or acquisition path. Deletion first takes an indexed bounded key page,
validates that page with one rowid-IN query, then deletes only exact validated keys.
Volatile fixed horizons rotate through protected pages and behind-cursor changes;
hints advance after commit or a completed no-write page. Restart merely rescans.
Rollback/cancellation preserve durable obligations and original errors. Mutation
pages do not add a SELECT per economic record. Observer/selector share eligibility;
the existing observation VM budget still fails unavailable rather than claiming
zero debt. Those existence probes are not a strict constant-work guarantee.

Retaining the old design loses required proof dependencies. A global oldest-proof
floor would retain unrelated history indefinitely; replacing the canonical store
is unnecessary. The hybrid retains only genuine tail and boundary obligations,
released by existing source/proof progress, under unchanged resource safeguards.

Focused8PASS1.839s; affected maintenance79PASS27.956s, including those8. Coverage
includes dense/composite pages, skipped upper andzero-lower proof boundaries,
actual publication/release, failed deletion/rollback/restart, growing tails,
missing startup child and cancellation. Tests use disposable evidence, not market
capacity replay. Original failing result is retained. Final combined startup/history/source-integrity gate:289PASS74.644s, including
actual integrated startup, economic/history delivery, exactACK, cancellation and
source guards. Imported fixture overlap is disclosed; not completeFAST/release.
Fresh required runtime preflight remains mandatory before the changed diagnostic.

The separately measured candidate-development callback78.110wallseconds still
needs its internal causal discriminator. Six fixed existing-owner timers now cover
selection, reactivation, boundaries, publication, plan and original transaction
exit. SQL/order/deadlines/priorities and cursor advancement are unchanged. Commit
includes the original context exit callback; BEGIN/bookkeeping remain unclassified.
Totals overlap owner callbacks and must not be added to them. Collector retains
fixed numeric rows before clipping, with missing/nonfinite values unavailable.
The unchanged32MiB output projection fits with213000bytes margin, not a universal
future-size guarantee; actual resource/recorder stops remain.

[Exact scoped evidence](evidence/control-membership-resolution-20261015.json).
[O12 preserved result](PROOF_SELECTION_RESULT_20261015.md).

The additional Pons actual read-phase discriminator preserved exact first action
and allbindings:1831rows/5SQL in each variant, .035287CPU seconds original versus
.032796 for receipt-predicate pushdown. Together with the .002095s materialization
saving, this rejects both proposed local patches as material remedies. Original
optional cohort-probeTOOBIG was a diagnostic precheck failure before either
measurement; retained unchanged, then omitted without increasing resource bounds.
No further Pons microbenchmark variants or production changes followed. Actual
invocation frequency and dominant concurrent Pons work remain unestablished.
