# Native interruption/completion blocker

The required real completion assertion fails against production dc08f9064cf5e37b63f383f52aa709d0afc1723f. No owner-admission gate or runtime repair was applied.

The ordinary priority-4 request is accepted as owner sequence 1. Fresh DebtAgeAdapter observation constructs native demands, latches a real archive recovery episode and lets the unchanged arbiter select archive. A native immutable receipt already exists; ServiceState commits exactly 512 records and retains 488 receipt records for later slices.

A SQLite trace callback positions one actual priority-0 owner submission at the start of the second completion-ledger SELECT. The first SELECT belongs to fresh observation. The callback does not raise or replace SQL, and the production 1,000-VM progress interval remains unchanged. The real queued urgent request causes PriorityOwner's existing interruption callback to interrupt _native_progress().

MaintenanceRuntime.turn() calls _native_progress() and then arbiter.complete() in its finally block (production lines 348–351). Interruption of the first call prevents the second call. The request future becomes done with evidence_background_yield, while the native arbiter still holds decision sequence 1. Urgent work executes and completes. A later ordinary maintenance request is accepted normally, takes another fresh native observation and fails in unchanged choose() with maintenance_decision_in_flight. Runtime failure then becomes fail-closed.

The failing assertion at test line 200 requires the first decision to be completed. It is not skipped or marked expectedFailure. The next real failure is captured before that assertion to preserve the full refusal chain. All earlier native mutation, integrity, episode, accepted-future and provider assertions reached that line successfully. The later no-error assertion is unreached because the real completion assertion fails; the next error itself is preserved in M1_EVIDENCE.json.

This is an admission-prototype prerequisite because an urgent arrival after maintenance acceptance is a required legal case. The approved gate must leave urgency and Runtime.turn() unchanged. The acceptance future's completion does not imply native decision completion here. A scheduling hint or fast-completion barrier cannot clear the native pending decision without an M1 repair or a weakened completion contract. Neither is authorized. No native pending/debt state was used as source-admission authority; test snapshots run on the owner solely to preserve failure evidence.

The original durable recovery episode remains exactly [program:meteora, archive, 1800000120.0, 1800000000.0, 1000] before and after the next fresh observation. Hot debt remains 1,288 after the 512-record slice. This fixture deliberately leaves recovery excess, and is not claimed as the approved 9.1-second old-fails/new-passes resolution regression. That regression and the already-infeasible negative are NOT_REACHED under the required M1 stop.

The preserved historical M1 summary failed at 886 completed frames with the same maintenance_decision_in_flight signature. Only this finite native prerequisite was run here; the historical pressure run was not rerun or causally reconstructed.

OWNER_ADMISSION_DETERMINISTIC:
BLOCKED_BY_M1
