# Pons evidence-retention invalidation

This is a causal performance repair candidate based on exact deployed
`ea7221c3d858ffa8799cd02bfa83a576906f6c21`. It does not establish live capacity,
economic cohort closure, historical recovery, readiness or financial authority.
Only `runtime/robinhood/plane.py` changes runtime behavior. The Broker adapter,
provider acquisition/admission, strategy and financial code remain unchanged.

## Actual incident and discriminator

Retained AWS run39095028426 / forensics39096250221 identifies the same main
PID/TID341469/start21608060. From the first **sampled** Pons-restored flag through
the last sample, its validated700.562-second interval read86,205,107,815 logical
bytes and wrote2,278,510,592 physical bytes. The independently sampled Pump-
restored suffix114.876s still read12,224,072,471 logical bytes. The original
signal stack was `Plane.maintain`'s namespace `COUNT(*)`, reached through
`Broker.report_to`/cohort coverage. The61,229-call reporting timer excludes this
maintenance work, so its82.775s cannot bound the complete turn cost. A sampled
stack plus these totals does not determine the fraction spent in this query.

The actual candidate DB was367,153,152B,1,849candidates and4,096transitions and
observations, with a4,978,487B cohort and164B history archive. Namespace counts,
key distributions and widths are unavailable. The disposable benchmark uses the
real Broker/Plane/Attempts/Pipeline warm turn, these candidate/cohort counts, and
explicitly synthetic namespace distributions. No production DB or finance is
copied. An unrelated native peer checkpoint precedes each measured dirty turn.

| Synthetic retained evidence | EA rchar/turn | Candidate rchar/turn | EA→candidate wall/turn |
| --- | ---: | ---: | ---: |
|1namespace×4,096 |2,986,111B |225,407B |2.951→1.913ms |
|4namespaces×8,192 |22,474,881B |270,465B |8.117→1.782ms |
|4×8,193; original obligation protects oldest |66,859,139B |270,467B |63.975→1.741ms |
|4×8,192;4KiB body padding |22,474,883B |270,467B |8.752→1.801ms |

Each comparison is two untraced turns under Cloud's SQLite3.53.1. Original
candidate/evidence/obligation/cache-usage rows remain unchanged. There are no
physical writes inside these warm arms. Traced arms are separate because
expanded SQL tracing itself costs CPU/allocation. This identifies repeated
key-index/count and protected-overflow pruning work independently of body
padding. It does not explain the actual write amplification or prove its AWS
share. A hypothetical skip-all-evidence arm is diagnostic only; it is never
installed as runtime behavior.

The pinned SQLite3.45.1 C API independently executes the original namespace/
COUNT queries:4×8,192 costs98,629VM steps and22.28MB logical reads at64KiB cache,
with a covering index and no TEMP sort. These are new/reused connection-cache
arms, not OS-cold measurements. The C API also executes the candidate's actual
evidence/obligation INSERT, UPDATE and DELETE triggers on all four fixtures,
validates their complete relevant schema, and verifies the original revision
after ROLLBACK. It is not the production Python extension/full native loop.

## Complete invalidation contract

The original count,4,096/8,192limits, `(created DESC,key DESC)` retained set,
receipt-protection anti-join and eviction effects are unchanged. Only a
successfully swept unchanged namespace skips its repeated count/prune. Every
evidence or receipt-obligation INSERT/DELETE/UPDATE advances persistent guarded
revisions for both old and new namespaces. Plain SQLite/old open connections
execute the same triggers. Revisions witness changes; they do not assert a
cardinality or replace original admission/retention checks.

The owner cache holds at most128namespace tuples of revision, active-family
scope and retention limit. More namespaces receive the original sweep. Missing,
foreign, partial or changed revision metadata cannot authorize a skip. Schema
validation includes the complete trigger population on evidence, obligations
and revisions, including the two original usage triggers; extra suppressors
also disable the cache. Revision reset/delete/replacement is rejected. Metadata
contains one persistent revision row per observed namespace, including emptied
namespaces to prevent identity reuse; existing storage admission remains in
force. No revision row is a market/source/financial receipt.

Revisions and sweep decisions share the original serialized transaction.
Publication follows only successful original COMMIT/no-write ROLLBACK. A
maintain-only pre-BEGIN schema witness prevents speculative DDL rolled back by
the original total_changes-based no-write path from publishing a reusable
schema token. Exceptions retain the original cleanup/error precedence. Capturing
the global completed stamp inside the transaction also prevents a later local
writer from being incorrectly certified clean during the publication gap.
Peer changes still invalidate through data_version. Candidate/rolling/audit/
clock/held-protection and age maintenance are never skipped by this namespace
cache. Constructor integrity and true-owner/reopen checks remain intact.

The additive metadata installs atomically, without scanning retained rows, only
when all its named objects are absent. Foreign/partial metadata is left intact
and uses original sweep behavior. Existing malformed native/protection state
retains its original refusal; the optimization supplies no repair authority.

## Validation and cost

88new/adjacent cases pass0.951s;35final receipt/provider/retirement cases pass
10.880s (13overlap;110distinct cases). Fifteen new cases cover raw/old peer
connections, actual concurrent mutations, all evidence/obligation operations,
namespace/key/order changes, release of the oldest protected fact, rollback,
failed COMMIT, actual no-write schema rollback/version reuse, foreign metadata,
extra/missing triggers, reset refusal, restart, paused scopes, capacity fallback
and both peer/local publication gaps. Original durable receipt, tie/NULL/order,
native retirement/accounting/restart/corruption and block-cache cases pass.

A separate128-call native `put_receipt`/scope-ACK fixture compares identical
economic tables with revision triggers absent/present. Issued publication wchar
increases3,998,776→4,526,136B (+13.19%); native ACK wchar49,440→53,560B. Native
rows/usage hashes are identical. Measured publication wall7.053→6.904ms is too
small/noisy to claim a speed benefit; ACK0.171→0.432ms demonstrates additional
bookkeeping. Both kernel physical-write deltas are zero during this brief
disposable interval; no durable-device/fsync claim follows from wchar. The
candidate trades bounded per-mutation revision writes for avoided repeated
unchanged scans. Actual AWS throughput/resource effects remain unverified.

Local retained evidence (no raw state included in Git):

- `pons-ea-evidence-maintenance-before.json` SHA256e7e565667fa4779a94da59e1501368840e5121575b8a3d88a73947edbe419c30
- `pons-ea-evidence-maintenance-after.json` SHA256bc659b9072ea90ee746e00b20c9545e3bc831db859d98c991fe90668b363f118
- `pons-ea-evidence-publication-overhead.json` SHA2563740a1ec017f370e7cfdd3fe98bed2f1faa5371b2a534574297e8419aee88388
- `pons-evidence-revision-adjacent.log` SHA2563785986fe059b970306cf8d7ada97a5b9fa6e9aea0ccd27765580606c6a19a27
- `pons-evidence-revision-receipt-provider.log` SHA25668cd03bee9262d545e9658572e3bf2828d560a4fc991e3cf8310c061f7591b7a

The exact benchmark sources at execution are retained by their receipt hashes:
before81aad91f252a74edf55822b3f94e972d917532de49c98e61ce1dc7b253aec2f8;
aftera42cb4da7f288b6508f2b9051f03937ccd57407e8b9d16bf243659aa1822b294.
The committed script adds a separate publication-overhead mode without changing
the matched native-turn workload. Current runtime Plane SHA256:
`af3b14b42233e0c72e91ba52190c6212ca9ddea576fa0109115f06047343fadf`.

Root's latest actual financial checkpoint remains16758/$1000/0positions/all
nine obligations zero. These offline checks do not write financial databases,
settle historical callbacks, authorize normal operation or change that history.
