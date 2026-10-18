# Independent maintenance permit ownership matrix

`tests.test_maintenance_permit_ownership` is an independently authored fixture for the producer-owned ticket/permit core. It uses the actual `PriorityOwner` thread/condition variable, actual accepted concurrent futures and a private native `EvidenceWriter`. Native callbacks commit conservative disposable gaps; the tests never acknowledge history or credit maintenance progress. A controlled clock and explicit barriers exercise long virtual work without long wall sleeps. No providers or new executors.

The11 cases cover:

- Current and older native callbacks consume8 virtual seconds before a permit opens. The eventual command has a genuine later acceptance time/sequence, runs before younger ordinary work and is not backdated to the reservation.
- The full ordinary56-slot queue refuses a ticket. After one slot opens, the pending ticket consumes that existing slot; no queue or urgent capacity is added.
- A second ticket cannot replace a pending/open/accepted ticket. Expired open permits cannot accept or redate a command.
- Priority0 and1 work invalidate unspent open permits and retain urgent precedence.
- A real checkpoint handoff blocks the permit; an open permit blocks a later checkpoint callback until explicitly released.
- Pending cancellation restores exact ordinary capacity. A canceled pending waiter releases its ticket while preserving older accepted work. Canceling a shielded accepted waiter never cancels the real native command.
- Shutdown releases pending tickets and joins accepted native futures through their actual commit.

First result: **11 PASS in0.190s**, no skips, under the implementation owner's original network guard and `Scratch`. The producer held its uncommitted core unchanged during this pass: `solana_evidence_control.py` SHA256 `52f321f14414c066b4b3e8bf7a28b9eae4bf76d7b712ad14676fdc521b5556cc`. Test SHA256 `d915b28f58ada87a1b26adfe36db115f8e17071de7602051593440d7b832d840`. Log/receipt: `/workspace/recovery-evidence/maintenance-permit-independent-first.{log,json}`. The core and service orchestration remain separately authored/reviewed prerequisites; this tests-only commit requires that API and is not independently deployable.

The producer owns the separate genuine native-runtime baseline/treatment test for the48-second expired-command/requeue mechanism. This ownership matrix does not replace that causal proof, full runtime integration, exact-source approval or an actual bounded AWS capacity result. No source guards, maintenance limits, provider allowances, strategy policy or authority flags change here.
