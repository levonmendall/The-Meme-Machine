# Fresh Stage-E causal isolation

**ASTRA_REVIEW_READY: HISTORICAL_MECHANISM_REPRODUCED**

PAPER ONLY. Stage E RED; Stage F NOT STARTED. Two material variants executed;
four unused. All diagnostic workload execution has STOPPED. No production repair.

Start with [ASTRA_REVIEW_PACKAGE.md](ASTRA_REVIEW_PACKAGE.md), then
[ARCHITECTURE.md](ARCHITECTURE.md),
[CANONICAL_STAGE_E_RECONSTRUCTION.md](CANONICAL_STAGE_E_RECONSTRUCTION.md),
and [EXPERIMENTS.md](EXPERIMENTS.md).
Runtime reference: dc08f9064cf5e37b63f383f52aa709d0afc1723f.
The branch is a real descendant of that source, not a qualification candidate.
The unavailable rejected candidate and lost Pro artifacts are not inputs.

## Reproducibility and hard stop

The immutable M1/M2 summaries bind configuration, runtime environment, production
tree and diagnostic SHA/tree. M1/M2_ARTIFACT.json bind original uploaded ZIP digests
and per-file hashes. Committed compact evidence survives Actions retention.
The publication artifact verifies and carries the captured complete bounded
timelines, native ring/health, reader interaction, archive hashes and configs.

Astra's decision is required before any further diagnostic workload execution.
ASTRA_GATE.json permanently blocks the harness and the workflow's workload path.
The current execution-request.json has package_only=true and no variants.
Publisher/finalizer use stdlib file/ZIP/hash operations; they never import the
harness, open workload databases, invoke tests or run certification.

For a future authorized reconstruction, use the exact executed diagnostic commit
from M1_SUMMARY.json or M2_SUMMARY.json, Python 3.12.14 and requirements.txt
(websockets 17.1). SQLite was 3.45.1; differences must be recorded. The original
one-variant execution request is stored in each run artifact. Invocation is:

    python diagnostics/stage-e-fresh-causal-isolation/harness.py \
      --request diagnostics/stage-e-fresh-causal-isolation/execution-request.json \
      --output /tmp/stage-e-fresh-evidence

This records the invocation for another reviewer; it does not authorize bypassing
the gate or rerunning the experiment. It runs actual native machinery with the
reachable provider-free Wire, fixed source deadlines, mature interactions and
explicit qualification-profile floors. It is never canonical certification.

## Isolated CI

Only this branch plus changes to execution-request.json trigger the isolated
workflow. Existing production/canonical workflow bytes and triggers are unchanged.
Every diagnostic run uploads evidence even on failure, with source/diagnostic
identity, environment, configuration and SHA256.json. Job success means evidence
was preserved; it never makes Stage E green. Retry is blocked.

The existing general-CI skip condition recognizes [runtime-v2-promotion] in these
diagnostic commit messages. It avoids another broad test run and does not perform
or authorize promotion. The final publication request executes zero workloads.

## Measurement limits

Five-second coherent synopsis/counter reads plus a bounded native terminal ring;
no per-record SQL trace or market bodies. Arrivals = delta eligible hot +delta
durable archive, valid only without active pins/gaps. Owner observation and read
snapshot timestamps remain separate. Post-refusal shutdown gaps are excluded.
Native versus injected workload waits are separate; stage, transaction, owner,
checkpoint and worker times overlap and must not be added as independent costs.

Pool submit-to-start includes IPC/serialization. Diagnostic overhead separately
tracks qualification-equivalent observer, extra debug observation, serialization,
persistence and numeric bookkeeping; Python trampolines/extra clock calls are not
fully measured. No <1% qualification claim or observer-off comparison.
