# PAPER decision policy history

The active decision revision is `paper-postgrad-rally-v1`. It grants the native
Pump Survivor worker PAPER allocation authority for qualified 10-minute–4-hour
post-graduation setups and grants the native Pump/Pons Survivor workers authority
for each distinct verified rally cycle. These decisions use existing shared
capital, execution validation, position protection and native reconciliation.
The revision does not create capital, change a portfolio inception, or authorize
real-money orders. Profitability is measured prospectively after readiness and
safety gates pass; an absence of long-term outcomes is not an extra PAPER veto.

`pre_opportunity_access_v1.json` preserves the original decision policies from
`a048ee8cbeb87bff9c589a0b6f587fd909c23ed5`. `opportunity_access_v1.json` preserves
the immediate predecessor from `893b8dd281f4282aed82573db8334c25605755c9`.
`paper_policy_revision.py` verifies each snapshot's source identity, complete
file checksum and individual policy hashes. `previous_hash()` continues to mean
the original historical policy; `predecessor_hash()` means opportunity-access v1.

Selection is independent of financial identity. Existing $1,000 and historical
$500 genesis bytes, portfolio epochs, journals, archives, balances, original
holding policies and recovery obligations remain authoritative. Each decision
revision uses a separate selection checkpoint. A previous revision's checkpoint
is retained and validated, and cannot authorize the new revision on an unresolved
historical position. New selection requires replayed native accounting, explicit
terminal zero balances and clear shared positions, reservations, commitments,
obligations, pending deliveries, backing and ACKs. Unknown evidence fails closed.
Active positions may restart under their already selected effective decision
policy; they may not be silently relabeled as the new policy.

The `rally-cycle-v1` contract binds a candidate to venue/graduation lineage and
authenticated peak/reset/base/breakout timestamps. The durable native registry
retains consumed cycles across history compaction. Re-entry requires a distinct
qualified cycle, a new peak after the preceding breakout, the existing setup
spacing, verified native settlement, global funding release/ACK and clear
obligations. A watch update, process restart or policy revision does not create a
new cycle.

Focused compatibility tests are in `tests.test_paper_policy_compatibility` and
`tests.test_operational_configuration`. Final release gates and genuine funded
PAPER entry, exit and reconciliation evidence remain separate requirements.
