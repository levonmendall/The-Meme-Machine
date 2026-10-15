# Owner retention boundary and supported startup successor

Exact executable `c281058e5993bd7a35190010e9398c982ca7cd1e`, branch
`repair/consolidated-startup-followup-20261014`, draft PR133. Root is sole integration,
test and runtime owner. Standing issue134 covers guarded diagnostics, with fresh
current-state safety checks and all original per-run limits.

The prior f72 run remains readiness FAIL/STARTUP_LIMITATION. In its440.920-second
post-native-reconciliation interval, arrivals4.65844 versus durable2.71478slotunits/s
and gap1038→1892 establish insufficient progress during startup, not steady state.
Owner callbacks/checkpoint holds occupied439.398seconds; candidate serial exposed
preparation113.349/ownerwait214.129/callback106.020seconds. Preparation overlap alone
cannot manufacture owner capacity. Matching those arrivals requires about1.716x
current durable rate before bursts/backlog recovery. Hardware sufficiency unproven.

The tested c5 parent fixes an exact CONTROL availability-prefix scan by selecting
an already installed end index, and restores finalized-parent skipped-prefix
publication across stale sessions. The omitted branch is reproduced offline;
its contribution to the previous live failure is unproven because the first
current block parent was not retained. No provider/cursor/commitment relaxation.

This successor adds four exclusive opt-in retention timers: plan, transaction,
housekeeping and post. The observed64.551-second nested retention cost otherwise
cannot be assigned to reads, mutation/commit, filesystem housekeeping or vacuum.
Transaction includes original context entry/exit, commit/rollback, outcome/cursor
and cooperative-yield work; it is not pure SQL latency. Housekeeping includes
original filesystem work. CPU/runnable overlap wall and must not be added to it.
Unentered phases remain absent; attempted probe loss is sticky and explicit.
Recorder failure preserves the original application exception. SQL, ordering,
limits, ownership, deadlines, yields and commit-only outcome semantics unchanged.

Fixed startup phase/released and exact two-feed intervals/timestamps are read
from the existing authenticated declaration. They are not proof recomputation,
readiness or evidence completeness. No body/failure text is exported. Required
retention counters survive the complete collection/serialization path.

Focused49tests PASS13.327s (outcomes/progress/maintenance, including seven new
fault/clock/rollback/export cases). Combined90tests PASS5.329s (actual integrated
startup/children/recovery/cancellation plus complete controller). Prior32collection
PASS overlaps the90; do not sum distinct cases. c5 source/economic/ACK evidence is
reused with its original207/208 and corrected20case disclosures. No fullFAST or
normal-operation release PASS. Hashes: evidence/owner-retention-validation-20261015.json.

Next: fresh financial/native/pending/provider/recovery/resource checks, exact
source/configuration/service-UID access, then one guarded current-system run under
OWNER_RETENTION_NEXT_OBSERVATION_20261015.json. Original readiness300s, diagnostic
startup900s/measurement900s, work1800s/drain65s/absolute1865s. Output32MiB and two64KiB
terminal reservations unchanged; conservative retained-shape projection33,366,240
metrics bytes fits33,423,360 narrowly, not a universal future-size guarantee.
Funding stays closed; no diagnostic minute is acceptance. On no discriminator or
safety failure, preserve and stop rather than repeat unchanged.

Original BUSY, Pons READONLY, provider recovery semantics,20Pons deadlines,
held quote/USD/protection, backup storage and freeze compatibility stay separate.
The three failed backup points' known single-link2.253GB cannot cover the prior
minimum4.028GB shortfall; large inodes remain linked elsewhere. No deletion,
purchase, bulk copy or timer change. Full-cgroup backup freeze remains an
unresolved architectural protection conflict before autonomous operation.
