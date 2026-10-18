# Operational recovery checkpoint — 2026-10-17

This is an engineering checkpoint, not a release or PAPER readiness claim.
The native runtime is frozen at `3465199505c5d56f0bb4de2e67fdf73d2563f366`
(tree `bd2fde2607e485ee35a3092a48069ac379d17b52`). The complete test-only
source guard is `33e7fd0f0d6a3ef04bd8c0f45d3ebcfc30d21ba8`, tree
`68fa59d55c1e1d67c2660e8932a5f867ea1d3056`; independent review cleared it.
All 109 guard cases passed in 187.838 seconds. The affected integration run
covered 668 cases in 96.247 seconds: 664 passed, two were availability skips
and two failed Cloud prerequisites. Both failures reproduced unchanged on main
780: missing /proc/self/ns/time and a non-root test process. Their original
assertions remain. The existing disposable GitHub runner now executes all 49
affected modules, including the complete copied-main case; its result is
pending. This document changes no image source, source approval, strategy
policy or production state.

## GitHub and last observed AWS state

Application main is `780f4015efd9fba528e97223f8e8e3b1a7322e12`, from PR #180.
Administration main is `33b21fa3a7ab3e4012d71f12c8199648fb525e7f`, from PR #103.
The active AWS application approval and installed source remain
`4d255c12cbb7f516d06bb31ce3f6af79b8c6be96` (tree
`379792be6684deb91e81aee1e70dd81f87bb5f77`). Last observed administration
workers are `aca78865a3c7a0110a854e5d2d9a12a497b5fb2e`; newer GitHub workers
have not been observed on AWS.

Protected preflight [39074173381](https://github.com/levonmendall/meme-machine-admin/actions/runs/39074173381)
at 22:14:38 UTC verified PAPER inactive, PID 0, disabled, Restart=no, funding
closed. Portfolio combined sequence 16232, raw 16231 plus source 1, retained
$1,000 cash, zero positions and all nine obligation categories zero, with full
replay/conservation in epoch `paper-shared-1000-20261011T071207Z`. No recovery
engineering operation since that receipt has changed production state. The
original $500 history is preserved. Both original unknown callbacks remain
unresolved; historical completion is false. Current-control recovery and
native startup/protection remain required for authoritative operation.

## What actual market testing established

Independent observer run 39057030420 completed a 118.141-second sample: 101
provider requests, 640 Pump and 640 PumpSwap raw references, no finalized-head
regression and no actual 429. No Pons factory logs occurred in its bounded
windows. The durable SQLite reopened with integrity_ok. This is sampled public
acquisition, not complete economic processing or protection/429 recovery proof.

The latest combined production diagnostic [39072867962](https://github.com/levonmendall/meme-machine-admin/actions/runs/39072867962),
collected by 39074106702, stopped for STARTUP_LIMITATION after 912.219 seconds.
Its whole sampled interval measured 1.7705 durable frames/s against 3.2536
control slots/s, with head gap 54 to 1225. Pump restoration alone took 593.214
seconds and 14,530 CandidateHistory calls; selected SQL execute/fetch spans
totaled 452.408 seconds. These whole-interval endpoints cannot establish warm
steady-state capacity. Pons read counters were 146.495 GB/36.212M syscalls;
the causal per-thread attribution remains pending. Device I/O/pressure was
observed but was not exclusive to PAPER; fsync/SQL-lock attribution is unknown.

PR #103 reads authenticated retained observations into fixed phase windows and
an after-restoration suffix, alongside per-thread Pons I/O and original
candidate reasons. It adds no provider workload or readiness authority. Its
257 integrated tests passed in 3.145 seconds. This reader still needs its first
protected AWS receipt; another identical live run is unnecessary to obtain
those existing observations.

PR #180 pages authenticated restoration reads and releases SQLite snapshots
before decode/archive I/O. On the identical offline corpus, canonical queries
fell 1024 to 28 and read characters 7,828,064 to 3,736,160; median wall time was
unchanged. Exact main 780 CI 39075482328 passed 1,179 focused tests with four
availability skips; pump-offline 39075482353 passed 90 plus 151 tests, with two
existing skips in the latter group. No AWS speedup is claimed. Admin PR #101
remains draft at `aa03ac9899a502761060d7878aa0e4b835ef8c57`, with 419 focused
tests passed in 4.892 seconds and normal operation false.

The former provider-fact verification row cap is already repaired by admin
PR #89 with complete paginated EOF verification; actual run 39060463435
verified more than 110,000 rows. It is not an unresolved 100,000-row blocker.

## Native architectural test and honest failure

The contained design runs original native consumers, economic decoding,
candidate/history publication, SQLite, source ownership and FULL/ACK work in
disposable state. The trusted parent owns provider acquisition/accounting;
source-bound anonymous IPC exposes bounded operations. No financial stores,
funding authority or production-history settlement are available to the child.
The copied image, Landlock/seccomp policy, spawn ownership and original
65-second accepted-work drain preserve containment and recovery semantics.

The coupled copied-main attempt at 346 failed after 11.655 seconds. Cloud
SQLite 3.53.1 rejected the unchanged forced partial-index query in
`solana_scoped_retirement.ceiling` for shared_history_cache, with
SQLITE_ERROR/no query solution. AWS reports SQLite 3.45.1. The query/index and
failure verdict were not changed to obtain a pass. Strict post-join inspection
found 223 authenticated canonical FULL/ACK rows and matching candidate
references, 340 source receipts and all four regime reports. Two decoder
workers joined with zero exit, including one actual economic job. No history
worker spawned in this coupled run. Parent/owned-process cleanup joined;
external provider calls and production writes were zero. The injected local
launcher explicitly lacked Landlock, so kernel validation remained BLOCKED.

Separate fixed-corpus components exercised actual decoder/history publication
and a real history job, but cannot replace coupled completion. Pons Current
nomination/publication was exercised; ordinary runtime Survivor qualification,
held protection, economic arrival capacity and sustained-market parity remain
unproven. The optional per-evaluation financial-read snapshot 0b4 and extra SQL
profiling cb8 remain separate, unselected branches pending causal evidence.

## Execution boundary and next action

GitHub git transport and the connector remain usable. CLI API authentication
returns 401, and the available connector has no workflow-dispatch action.
There are no AWS/SSH credentials in this execution environment. Do not replace
the existing broker, permissions or workflow with another execution path.

Next protected read-only dispatch:

- Workflow: https://github.com/levonmendall/meme-machine-admin/actions/workflows/paper-control.yml
- Branch: `main`
- Action: `native-forensics`
- application_commit: `4d255c12cbb7f516d06bb31ce3f6af79b8c6be96`
- collect_target: blank

Use the resulting retained phase/thread evidence to select the next causal
repair. Preserve original exact-source validation, stopped deployment, fresh
preflight and current-control recovery before the next bounded live
comparison. Admin kernel PR #102 remains DRAFT_UNFROZEN and refuses execution;
its exact a5 CI 39079198566 passed 83 offline fixtures, with AWS skipped. Six
independently hash-authenticated approved wheels supply 178 runtime-file pins;
the positive source/receipt contract is not approved. A compatible actual
kernel/coupled-main result is still required before live-native testing.

Complete FAST/OPERATIONAL, authoritative financial/native readiness and the
uninterrupted one-hour PAPER acceptance remain outstanding. No short sample,
synthetic result, flat portfolio or source-guard pass substitutes for them.

## Caller-boundary integration, October 18 UTC

Exact candidate5bd CI39080063441 completed 1,186 cases in412.353 seconds:
1,181 passed, four skipped and one failed because an external history test
passed new runtime bytes directly to a legacy source verifier. The native
step was skipped. This was a test-interface integration failure, not evidence
of completed native processing.

Commit `291da939ceb5c5208338a68ffe28a182eef17118` closes that shared interface.
A census of975 tracked Python files found seven external fresh-read sites;
all receive exact reversible normalization. The three mutation-stage calls
and every original assertion remain intact. Each complete caller file
reverses to its exact780 bytes. The separate39,317-byte caller manifest has
SHA256 `74bcfbcba5d917a2bb9c2c9a187544f5164d52845337d6a364b7693186f16967`.
The original422,509-byte native-source manifest remains unchanged. Independent
review cleared the exact source proofs and the fixed static API census; this
is not general analysis of arbitrary Python dynamic dispatch.

All119 focused guard/caller cases passed in217.013 seconds without skips.
The exact original CI failure also passed separately in0.741 seconds. Runtime
image bytes remain346. CI now runs the native subset after a Stage A failure
when dependency setup succeeded and the job was not canceled. Any failure
still fails the job; full-release dispatch remains separate. The corrected
complete copied-main result is pending. No AWS state or financial history was
changed by this test-only correction.
