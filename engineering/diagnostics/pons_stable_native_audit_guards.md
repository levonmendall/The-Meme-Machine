# Stable native Pons audit retention

This is a funding-closed performance component based on exact deployed
`0e9a0ffe1912c28258735909ebce933803585556`. It changes neither strategy nor
provider work, financial authority, readiness, shutdown limits or retention
populations. No live improvement or full-market capacity is established here.

## Supported cause and choice

The retained same-process MAIN interval in
`0e9a0ffe-native-forensics-39104629749.json` is 712.967996 seconds after the
first sampled Pons-restored flag, with 65,703,253,998 logical read bytes and
16,427,040 read syscalls; all seven interval issue counts are zero. The actual
Plane retains 4,096 transitions and 4,096 observations. These facts identify a
remaining target, not a measured fraction attributable to a particular query.

The original native audit-ring pruning drops and recreates its delete trigger.
Those global schema changes invalidate every evidence-retention token. A
matched native offline fixture reproduces the repeated namespace counts and
pruning while evidence and outstanding receipt obligations stay unchanged.

Retaining the existing DDL route everywhere keeps this invalidation. Accepting
apparently equivalent schema-cookie transitions was rejected: an unobserved
foreign cookie reset can replay a previously genuine transition and suppress
required evidence retention. The rejected checkpoint is preserved separately as
`11014bf7897cbc53628edcebeb4fbe5b1c21a4f4`; its failing receipt is
`pons-audit-schema-lineage-unobserved-reset.log`, Scratch
`/tmp/mm-engineering-p5ba5o1d`. Its 108 other passes do not clear that failure.
No lineage, cookie exemption, or alternate evidence invalidation survives here.

The selected correction replaces only the two native audit delete guards with
stable guards. Their predicate permits the original fixed DELETE only on the
actual Plane connection during its original serialized transaction and native
prune call. All other update/delete guards remain in place. The original strict
global evidence schema check, revision triggers, pre-BEGIN schema witness,
post-transaction cache publication and maintenance completion stamp remain.

## Guard and compatibility contract

The two guards call `mm_native_audit_delete(table, key) IS NOT 1`: NULL, missing
functions, exceptions and non-one results refuse ordinary DELETE. Only the
original `transitions/seq` and `observations/rowid` routes may open a private
permit, with the original 4,096 limit, participation predicate and computed
integer cutoff. Original boundary reads and cancellation remain in `storage`.
The permit binds the actual owner, process, connection, inode, invoking thread
and original transaction token. It exists only around the fixed DELETE, is
nonnested and is unconditionally cleared on every exit. No provider operation
or user callback is added. An exact bounded census of both rings' four triggers
must match before opening it. A closed predicate probe detects a replaced or
missing registered function; it never authorizes a row or re-registers a UDF.

This assumes approved Python source and the owned connection. Arbitrary Python
can register its own always-one function; this is not a sandbox against that.

Construction validates both guards under one `BEGIN IMMEDIATE` before changing
either. Individually exact legacy/canonical definitions, including known mixed
pairs, can migrate atomically. Unknown/oversized definitions disable the new
path. Missing guards on preexisting tables cannot earn the new path via the
original constructor's `IF NOT EXISTS` reconstruction. A genuinely fresh
database migrates both newly created legacy guards immediately. Newly read
guard SQL is limited to 1,024 bytes; the live census returns at most the four
expected triggers plus one sentinel, with 64-byte names. Table entries return
presence only. No retained payload scan is added.

An already-open connection without this UDF still cannot directly DELETE under
the canonical guard. Its original serialized `storage.audit_ring` route may
drop/delete/restore the guard as before; this changes the schema cookie and
forces the original evidence fallback. The new helper also uses that original
route when a supported private transaction token is unavailable, when a known
legacy guard reappears, or when relevant metadata is unknown. No broad trigger
disable, authorizer override, permission change or new SQL writer is added.

## Matched native counterfactual

The existing before receipt is
`/workspace/recovery-evidence/pons-audit-schema-before-0e9.json`, SHA-256
`28331e799cbfd4a84bddf566d84edbaea1e0697fe5335f9bdb326f18e74f8ad3`.
The stable-guard after receipt is
`/workspace/recovery-evidence/pons-audit-schema-after-stable-guards.json`, SHA-256
`5adf225f121932710a0aad7e4319efa358df9c506068e43b2c39db9940a1473c`.
Both use actual native Broker/Plane/Attempts/Pipeline methods, CPython 3.12.14
and Cloud SQLite 3.53.1, independent disposable same-generated arms, original
WAL/FULL and cache size -2000. No provider requests or production-state copy.
The after receipt's `source_commit` records checkout HEAD (the base 0e9), not
an assertion of clean source: its three explicit `runtime_hashes` bind the
modified reached executable bytes. Those bytes are unchanged in the final
component; the before/after receipts and script are preserved without rewrite.

The explicit synthetic shape has 1,866 candidates, both full 4,096-row rings,
four 8,192-record receipt namespaces, 256-byte receipt body padding and a
5,030,660-byte protected cohort. It matches selected retained geometry, not the
entire production data distribution. Two samples per arm include all new SQL,
UDF, CPU, read and write work; these are local page-cache observations.

| Peer work before the same native MAIN turn | Original MAIN rchar | Stable MAIN rchar | Original / stable MAIN wall |
| --- | ---: | ---: | --- |
| Unrelated checkpoint | 282,752–295,040 | 282,752–295,040 | 2.09–2.42 / 2.07–2.67 ms |
| Actual transition-ring prune | 28,205,186–28,209,282 | 5,927,042–5,931,138 | 12.29–12.72 / 4.51–4.98 ms |
| Actual observation and transition prunes | 32,735,363–32,743,555 | 10,477,699 | 14.26–14.75 / 6.71–7.68 ms |

The prune arms remove all four repeated evidence COUNTs and both trigger DROPs;
the schema cookie stays stable and all four namespace tokens survive. Approximate
VM steps fall from 195–196k to 95k and 273–274k to 173k respectively. Peer wchar
decreases; MAIN wchar is unchanged or lower. Complete evidence, obligations and
revision-row hashes, candidate counts and both exact ring limits match before
and after. Remaining 5–10 MB per native turn is explicitly not solved by this
change. This is mechanism evidence, not a causal attribution of the actual
65.7 GB, a hard storage-latency bound or a readiness/throughput PASS.

## Validation and next decision

The final affected selection passes **121/121 in 14.738 seconds**, without
skips or failures, including all original 15 evidence-retention cases and 23
new guard/fault cases. Receipt
`pons-stable-audit-guards-final-focused.log` SHA-256
`28f5014908f66791fe10777f06e220f84b3f378efaea3e87966ee0e546c1aac4`
covers original Plane, protection/reopen, covering retirement, durable receipt
obligations, native candidate and dense-V4 receipt modules. This is affected
validation, not a complete release suite. New native guard tests cover
full-ring peer/self pruning, cross-thread invocation, direct SQL/UDF refusal,
partial/unknown/oversized migration, old-connection fallback, original paused
and NULL participation, same-transaction foreign DDL, the rejected cookie-reset
counterexample, cancellation, DELETE and COMMIT errors, reentrancy, rollback,
abrupt child exit/restart, fork/foreign-connection scope and atomic migration
failure. Exact final affected-test and independent-review receipts are recorded
in the component handoff. Source-proof closure must authenticate storage and
the new helper as executable dependencies before any controlled deployment.

The actual pinned SQLite 3.45.1 C API also passes ten finite SQL-compatibility
checks in 0.247 seconds on a 16 KiB disposable database. The probe imports this
helper's actual canonical/legacy guard SQL and verifies missing/non-one/NULL
function refusal, fixed row bounds, unchanged UPDATE guards, stable schema,
rollback and committed reopen behavior, and bounded `octet_length` metadata
queries. Receipt `pons-stable-guard-sqlite345.json` SHA-256
`d54ef1a1393706faa606979dd36414c829df83a877c6a42e55d539bd6da3c13e`
binds probe SHA-256
`50c170fc54c0fa0c43fc40411bac064a3b86eb38650ed51b07bbcfe53f10e068`
and DSO SHA-256
`e6b6daa1908cc4ebb2a2275fd771c26ef13a23ace38f4681e4fcf7bb09075b09`.
This proves SQL compatibility only; it does not run the real private Python
owner capability or measure native Python performance on SQLite 3.45.1.

Only a new exact-source live comparison can establish the real effect under
current provider, storage and workload conditions. Financial and native
recovery approval remain separate and retain their original gates.
