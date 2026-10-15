# Campaign attempt 1 — 2026-10-15

**RECOVERY_REQUIRED. Campaign live branch STOPPED at 1/3 starts.** No attempt 2,
normal PAPER admission or acceptance occurred. The original historical failed
drain remains unchanged; this attempt has its own preserved failure result.

| Source | Exact identity |
| --- | --- |
| Executed implementation | `ba25499b26103ec5d14f1ce765c8e8f180695f33` |
| Corrected specification publication | `a32f49d2061e577644ef2d28f75fefd4a48ebe87` |
| Focused-tested offline successor | `0000a4f817107cff9b46a881b7f1ae00745aa384` |
| Compatible restored installation | `66f85d61bf4d3ba9a01efdc0e9eb68949419bda8` |
| Engineering branch | `repair/consolidated-startup-followup-20261014`, draft PR 133 |

The existing specification was pinned to ba25499b before dispatch, including
controller, unit, configuration and private output identities. Fresh financial,
current-state native, ownership, provider, recovery-reference, storage,
backup-non-overlap and actual service-user access checks passed. The original
300-second readiness requirement, 1,800-second work ceiling, 1,865-second absolute
drain boundary and protection/resource/provider controls remained unchanged.
The campaign had not expired. The exact authorization receive timestamp is not
retained; ordering establishes an earliest expiry bound of
2026-10-15T23:06:44Z. Do not reset the campaign clock or assume authority after it.

## First failure and measurement limitation

The single start occurred around 00:35:22 UTC. The source failed at
00:36:11.896 UTC; the controller ended after **64.599 seconds**. No native market
frames arrived before failure. Both the real Pump account scout and shared
control stream received:

```text
INVALID_ARGUMENT / stream_read
failed to get replay position for slot 457039819
```

The retained `control_current_tail` record proves HTTP finalized tip 457040075
and requested floor 457039819, exactly tip minus the existing 256-slot overlap.
This was a current-tail request, not a replay from the old 457007865 checkpoint.
`solana_selective_source.stream:924` preserved the first semantic rejection and
failed closed. No SQLite exception was reproduced.

This establishes unavailable replay at the requested position on that native
endpoint. It does **not** establish why the provider rejected it, a safe alternate
cursor, or a local software correction. No generic retry, cursor shift, skipped
evidence or provider replacement was implemented.

Current-run arrival, processing, canonical commit, history commit, exact ACK,
publication and strategy-consumption **rates are UNAVAILABLE**. Old retained
frontiers are not new arrivals. Startup prevented a useful capacity interval;
neither the sustained Pump limiter nor a host-capacity conclusion is established.
Readiness was not established before the fatal; the 300-second deadline was not
reached, rather than passed or relaxed.

## Actual native shutdown and current recoverability

Pump cancelled `pump.accounting_restore` after 3.655 seconds in that operation,
cleaned its opened CandidateHistory owner and exited 0 about 0.115 seconds after
TERM. Its final state is STOPPED / reconciled=false. This demonstrates responsive
cancellation at this startup boundary, not completed native recovery.

Pons remained RECONCILING / reconciled=false, received TERM and then KILL after
the existing 15-second lane wait, and exited -9. Its blocking operation is
unavailable. The supervisor's signal/wait records establish the escalation;
they do not identify replay, SQLite, OOM, provider waiting or a lock holder as
the cause. Empty processes and controller `drained=true` do not make this a
successful native drain. The original result remains RECOVERY_REQUIRED.

Fresh bounded post-attempt checks separately verified current-state resumability:
**20 VERIFIED, zero failed/unavailable checks, 155 queries / 0.101 seconds**.
The exact eight-event financial tail replays to journal head 8990, $1,000 cash
and no monetary obligations. Historical $500 accounting and the native flat books
remain intact. The new source session is FAIL_CLOSED/released=false; prior durable
cursors, named pending delivery/proof cohorts and candidate histories remain
preserved. All 32 identities in the retained current receipt cohort now have
authentic exact ACKs, versus 21 before startup; these are retained-work completions,
not new market arrivals. The eight older history witnesses remain pending, with
their outbox/proof witnesses preserved. Owners are dead, leases inactive and the
writer lock unheld.

This supports **SAFE_TO_BEGIN_EXISTING_GUARDED_RECOVERY in the checked scope**.
It neither rewrites either failed shutdown nor proves future actual restoration,
full-store integrity, readiness or drainage. No bulk copy, journal rewind, lease
reset or authoritative recovery write was used for the review.

## Offline correction and focused validation

The actual Pons startup path reproduced a missing cancellation boundary:
initial shared-authority construction lacked the existing
`native_startup_replay(requested.is_set)` scope used elsewhere. The uncorrected
actual lane path ignored the injected TERM at its first replay check.

The successor scopes only that initial verification, reuses the existing verified
executor connection and clears the cancellation scope before ordinary recovery
and monetary operations. It adds the exact bounded operation identity
`pons.shared_capital_restore` to existing status/collection. No new owner,
scheduler, retry, deadline, transaction mode or financial authority was added.
This is a demonstrated offline defect and repair, **not attribution or a live
repair claim for this Pons -9**.

Actual cohort tests prove cancellation preserves pending evidence/journal and
honestly reports unfinished reconciliation. Successful startup proves a single
main-thread authority construction, native sleeve reuse, scope cleanup, real
sizing validation with controlled USD evidence and unchanged journal. A real
scout/control characterization also preserves the provider semantic error,
original request and pending records without fabricating a retry or coverage.

Pinned CPython 3.12.14 / linked SQLite 3.45.1, supported contained network-blocked
runner, one integration/test owner:

- Combined affected run: **103 PASS / 6.993 seconds**, no skips/errors. Includes
  13 actual integrated rehearsals, eight native lifecycle, 24 Pump cancellation
  and 58 diagnostic tests.
- Exact economic/source guard: **1 PASS / 7.837 seconds**. All 36 protected
  opportunity-access manifest entries and the manifest are unchanged. The six
  active strategy changes, original nine economics and volume attention remain.
- Earlier two repaired Pons cases: **2 PASS / 0.507 seconds**, overlapping the
  combined run; do not add their counts as separate coverage.
- Original reproduction retained: two cases, one expected Pons failure and one
  passing real source semantic-rejection characterization. The first repaired
  fixture run retained one missing-offline-USD error; the existing MockProvider
  now supplies the required fixture evidence without weakening sizing/freshness.

Independent frozen-diff review found no defect. No complete FAST was dispatched;
these results are scoped diagnostic evidence, not a full release or capacity PASS.
The earlier completed FAST remains prior baseline evidence only.

## Pons and usage

Managed-Pons logical request elements: **zero**. Complete quote/USD and held
protection were not exercised. No current public 429 or READONLY recurrence was
observed, which establishes neither repair nor managed-provider suitability.

The durable ledger records **three physical starts total: one HTTP RPC and two
native openings**, one Solana logical element, 20 frozen-model CU and 43 HTTP
bytes. Confirmed native delivered bytes are zero; 134,217,728 native uncertain
bytes are reservation accounting, not confirmed traffic. Reservations drained
to zero. Existing modeled cost is **$0.01410336144**; provider invoices are
unavailable. No obsolete spending ceiling was restored or counters reset.

## Safe state and single next decision

The compatible pre-attempt source and exact two small overlays were restored
without rewinding any database or policy history. Installed source66f85d61 is
clean; PAPER remains stopped/failed, disabled, Restart=no, MainPID0 and funding
closed. The offline successor is not deployed. The restored old finite diagnostic
overlay is not a normal-service profile and must not be started unchanged.

**Do not launch attempt 2 unchanged.** Obtain the bound native endpoint's actual
replay availability and unavailable/skipped-slot contract before choosing a
coverage-preserving source correction. Existing local `geyser.proto` exposes
`SubscribeReplayInfo.first_available` and finalized `GetSlot`; these could compare
the requested floor with the same native endpoint's advertised replay range.
Neither was executed. Method support, accounting and same-node semantics remain
unverified, and a range alone cannot prove exact-slot completeness. A targeted
capability check would need its own executable/accounted scope under applicable
runtime authority; this handoff does not authorize or silently dispatch it.

Pending that discriminator, the source branch is **STOP — INSUFFICIENT EVIDENCE
FOR A JUSTIFIED CORRECTION OR DECISIVE EXECUTABLE TEST**. No supported production
replay intervention currently justifies consuming attempt 2. Any later retry
also needs current-state recovery and fresh mandatory preflight, the Pons repair's
appropriate validation, an exact updated specification and unexpired authority.

Independent blockers remain: actual native restoration/drain, sustained Pump
capacity, original SQLITE_BUSY, managed-Pons method/account/freshness and complete
quote/USD protection, Pons READONLY INSERT, backup/storage failure and active
backup compatibility with uninterrupted protection. No one-hour or autonomy
milestone was achieved; diagnostic acceptance time is zero.

Exact private artifact locators and SHA256 values are retained in
[campaign-attempt1-20261015.json](evidence/campaign-attempt1-20261015.json).
The original output is
`/var/lib/meme-machine-diagnostics/20261015-campaign-attempt1-ba25499b-002832`.
Its result SHA256 remains
`32f30f36c820d18fce8989354e7670713be2339d448fdcf98d848e93967f9240`.
Large evidence and authoritative databases remain in their existing persistent
locations; the handoff indexes them without making redundant state copies.
