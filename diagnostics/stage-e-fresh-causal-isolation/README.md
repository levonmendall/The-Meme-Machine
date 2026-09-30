# Fresh Stage-E causal isolation

PAPER ONLY. Stage E RED; Stage F NOT STARTED. Runtime source is
dc08f9064cf5e37b63f383f52aa709d0afc1723f. This branch is diagnostic tooling,
not a Stage-E candidate. Production blobs/modes and canonical workflows remain
unchanged. The rejected candidate and lost Pro artifacts are not inputs.

Read ARCHITECTURE.md and CANONICAL_STAGE_E_RECONSTRUCTION.md first.
The harness reuses repository-local source templates, timing floors, native
serve/owner/arbiter/archive/retirement machinery and mature reader interactions.
There are no providers, wallet, trading, signing, broadcasting or deployment.

## Reproduce

Python 3.12.14, requirements.txt (websockets 17.1). SQLite version is observed,
with differences from 3.45.1 explicitly reported. Run from a clean checkout:

    python -m pip install -r requirements.txt
    python diagnostics/stage-e-fresh-causal-isolation/harness.py --selfcheck
    python diagnostics/stage-e-fresh-causal-isolation/harness.py \
      --request diagnostics/stage-e-fresh-causal-isolation/execution-request.json \
      --output /tmp/stage-e-fresh-evidence
    python diagnostics/stage-e-fresh-causal-isolation/finalize.py \
      --root /tmp/stage-e-fresh-evidence

A material execution requires a reviewed request with validate_only=false, an
unused variant number 1..6 and no ASTRA_GATE.json. Each variant uses fresh local
state. Never rerun a material execution to fish for a result.
The isolated workflow runs only when this branch's execution-request.json changes;
canonical workflow triggers are untouched. [runtime-v2-promotion] in diagnostic
commit messages prevents the existing general CI push job from launching another
broad suite. It is an existing skip condition, not a promotion authorization.

## Predeclared budget and adaptive decisions

| Number | Question | Variable |
| --- | --- | --- |
| 1 | Fresh coupled recovery baseline | None; canonical derived profile |
| 2 | Does source occupancy prevent recovery? | Source owner floor .165 -> 0 ONLY if baseline shows injected floor consumes material capacity |
| 3..6 | Reserved | Declare after fresh evidence; worker, maturity, checkpoint/allocation or confirmation only if still viable |

Validation/syntax/arithmetic and required deterministic checks are not causal
workload variants. Six is a ceiling, not a target. Stop at the first supported
Astra gate; commit ASTRA_GATE.json and never execute another diagnostic.

## Evidence and interpretation

timeline.jsonl: five-second coherent read snapshots; final-snapshot.json: final
snapshot. capacity-timeline.json: compact timeline. terminal-ring.json: 64 most
recent native admission explanations; native-health.json: final native metrics.
summary.json binds configuration, source/diagnostic identities and environment.
SHA256.json hashes every bounded evidence file; GitHub artifact metadata separately
binds the uploaded ZIP. Synthetic runtime DB/archive files stay outside Git/logs
and outside the uploaded artifact; archive hashes are preserved.

Arrival inference is delta eligible hot + delta durable archived, valid only in
the absence of active pins/gaps; it is not source ingestion labeled eligibility.
Pool submit-to-start includes IPC/serialization as well as queue delay.
Runtime stage/transaction/owner/worker intervals overlap. Separate injected delay
from native costs. The diagnostic observer has its own timing and serialization/
persistence totals; wrapper timing measures numeric bookkeeping and does not fully
capture Python entry/return trampolines. No <1% qualification observer claim.

Results, run/artifact bindings and a committed Astra review package will be added
after the baseline and only the discriminators justified by its evidence.
